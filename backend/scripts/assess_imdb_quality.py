"""阶段 3.5.3A：IMDb 标准化 CSV 数据质量评估。

只做读操作：不修改摄取脚本、不修改原始数据、不修改正式知识库。
报告使用同目录临时文件 + os.replace 原子替换；仓库内路径受保护。

输入（默认）：
    backend/data/processed/large/imdb_titles_movies.csv
    backend/data/processed/large/imdb_ratings.csv

输出（默认）：
    backend/data/processed/large/imdb_quality_report.json

评估指标：
    * 主表记录总数、tconst 唯一性
    * 评分表记录总数、tconst 唯一性
    * 年份、片长、类型字段缺失比例
    * 上映年份合理性与异常值（<1877 或 >下一年）
    * 评分范围、投票数量有效性（1..10，>=1）
    * 主表评分覆盖率、孤立评分
    * 输出 JSON：输入 SHA-256、评估时间、关键指标与异常统计

输出路径保护：
    * 默认写入 backend/data/processed/large/imdb_quality_report.json。
    * 仓库内仅允许写入此路径；禁止覆盖 IMDb CSV、manifest、
      knowledge/candidates、TMDb raw、scripts、docs、frontend 等。
    * 仓库外临时目录允许写入，便于测试。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent

DEFAULT_BASICS = BACKEND_DIR / "data" / "processed" / "large" / "imdb_titles_movies.csv"
DEFAULT_RATINGS = BACKEND_DIR / "data" / "processed" / "large" / "imdb_ratings.csv"
DEFAULT_OUTPUT = BACKEND_DIR / "data" / "processed" / "large" / "imdb_quality_report.json"

BASICS_COLUMNS = [
    "tconst",
    "title_type",
    "primary_title",
    "original_title",
    "is_adult",
    "start_year",
    "end_year",
    "runtime_minutes",
    "genres",
    "ingest_date",
]
RATINGS_COLUMNS = ["tconst", "average_rating", "num_votes", "ingest_date"]

EARLIEST_MOVIE_YEAR = 1877

# 仓库内允许写入的目标（只有质量报告本身）
ALLOWED_OUTPUT = DEFAULT_OUTPUT
# 禁止写入的目录 / 文件
PROTECTED_DIRS = [
    BACKEND_DIR / "data" / "processed" / "large",  # 目录下的 csv/manifest 除外，仅允许自己
    BACKEND_DIR / "data" / "knowledge",
    BACKEND_DIR / "data" / "candidates",
    BACKEND_DIR / "data" / "raw" / "tmdb",
    BACKEND_DIR / "data" / "raw" / "imdb",
    BACKEND_DIR / "scripts",
    BACKEND_DIR / "tests",
    REPO_ROOT / "docs",
    REPO_ROOT / "frontend",
]
PROTECTED_FILES = [
    DEFAULT_BASICS,
    DEFAULT_RATINGS,
    REPO_ROOT / "docs" / "data_manifests" / "manifest_imdb_title.basics.json",
    REPO_ROOT / "docs" / "data_manifests" / "manifest_imdb_title.ratings.json",
    BACKEND_DIR / "data" / "processed" / "cult_movies_clean.csv",
]


class QualityError(RuntimeError):
    """参数校验、输入损坏或输出路径不安全。"""


# ---------- 路径与隐私 ----------


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _safe_input_label(path: Path) -> str:
    """报告中的输入标识：仓库内相对路径；仓库外仅用文件名。

    绝不泄露本机绝对路径、用户名或 home 目录。
    """
    try:
        rel = path.resolve().relative_to(REPO_ROOT.resolve())
        return str(rel)
    except ValueError:
        return f"external:{path.name}"


def _assert_safe_output(path: Path) -> None:
    resolved = path.resolve()
    repo = REPO_ROOT.resolve()
    if _is_within(resolved, repo):
        if resolved != ALLOWED_OUTPUT.resolve():
            raise QualityError(
                f"报告输出路径不在允许范围内：{resolved}；仅允许 "
                f"{ALLOWED_OUTPUT} 或仓库外临时目录"
            )
        return
    # 仓库外：仅临时目录语义允许。拒绝写入另一个 Git 仓库或高风险位置。
    parent = resolved.parent
    probe = parent
    for _ in range(6):
        if (probe / ".git").exists():
            raise QualityError(
                f"报告输出路径落在另一个 Git 仓库内：{resolved}；"
                f"请改用系统临时目录"
            )
        if probe == probe.parent:
            break
        probe = probe.parent


# ---------- 工具 ----------


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _iter_rows(path: Path, columns: list[str]) -> Iterable[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        observed = reader.fieldnames or []
        missing = [name for name in columns if name not in observed]
        if missing:
            raise QualityError(f"{path} 缺少必需列 {missing}")
        for row in reader:
            yield row


def _is_int(value: str) -> bool:
    if not value or len(value) > 10:
        return False
    if value.startswith("-"):
        return value[1:].isdigit() and len(value) > 1
    return value.isdigit()


def _is_float(value: str) -> bool:
    if not value:
        return False
    try:
        float(value)
    except ValueError:
        return False
    return True


def _votes_bucket(votes: int) -> str:
    """将原始票数映射到固定的对数区间桶，控制内存占用。"""
    if votes <= 0:
        return "invalid"
    if votes <= 10:
        return "1-10"
    if votes <= 100:
        return "11-100"
    if votes <= 1_000:
        return "101-1k"
    if votes <= 10_000:
        return "1k-10k"
    if votes <= 100_000:
        return "10k-100k"
    if votes <= 1_000_000:
        return "100k-1M"
    return ">1M"


# ---------- 评估 ----------


def assess_basics(
    path: Path,
    seen_ratings: set[str],
    *,
    max_rows: int | None = None,
) -> dict:
    if not path.exists():
        raise QualityError(f"主表不存在：{path}")
    if max_rows is not None and max_rows <= 0:
        raise QualityError(f"max_rows 必须为正整数，收到 {max_rows}")

    total = 0
    unique_ids: set[str] = set()
    duplicate_tconst = 0
    missing_start_year = 0
    missing_end_year = 0
    missing_runtime = 0
    missing_genres = 0
    invalid_start_year = 0
    future_year = 0
    invalid_runtime = 0
    zero_runtime = 0
    negative_runtime = 0
    title_type_counts: Counter[str] = Counter()
    odd_year_samples: list[str] = []
    future_year_samples: list[str] = []

    this_year = datetime.now().year + 1

    for row in _iter_rows(path, BASICS_COLUMNS):
        if max_rows is not None and total >= max_rows:
            break
        total += 1

        tconst = row.get("tconst", "")
        if tconst in unique_ids:
            duplicate_tconst += 1
        else:
            unique_ids.add(tconst)

        title_type = row.get("title_type", "").strip()
        if title_type:
            title_type_counts[title_type] += 1

        if row.get("start_year", "").strip() == "":
            missing_start_year += 1
        else:
            val = row["start_year"].strip()
            if not _is_int(val):
                invalid_start_year += 1
                if len(odd_year_samples) < 5:
                    odd_year_samples.append(f"{tconst}:{val}")
            else:
                iv = int(val)
                if iv < EARLIEST_MOVIE_YEAR:
                    invalid_start_year += 1
                    if len(odd_year_samples) < 5:
                        odd_year_samples.append(f"{tconst}:{iv}")
                elif iv > this_year:
                    future_year += 1
                    if len(future_year_samples) < 5:
                        future_year_samples.append(f"{tconst}:{iv}")

        if row.get("end_year", "").strip() == "":
            missing_end_year += 1

        runtime = row.get("runtime_minutes", "").strip()
        if runtime == "":
            missing_runtime += 1
        elif _is_int(runtime):
            ir = int(runtime)
            if ir < 0:
                negative_runtime += 1
            elif ir == 0:
                zero_runtime += 1
        else:
            invalid_runtime += 1

        genres = row.get("genres", "").strip()
        if genres == "":
            missing_genres += 1

    ratings_covered = len(unique_ids & seen_ratings)
    orphan_titles = len(unique_ids - seen_ratings)
    rating_coverage = ratings_covered / len(unique_ids) if unique_ids else 0.0

    return {
        "file": _safe_input_label(path),
        "rows_total": total,
        "unique_tconst": len(unique_ids),
        "duplicate_tconst": duplicate_tconst,
        "missing_start_year": missing_start_year,
        "missing_end_year": missing_end_year,
        "missing_runtime": missing_runtime,
        "missing_genres": missing_genres,
        "invalid_start_year": invalid_start_year,
        "future_start_year": future_year,
        "invalid_runtime": invalid_runtime,
        "zero_runtime": zero_runtime,
        "negative_runtime": negative_runtime,
        "title_type_counts": dict(title_type_counts),
        "odd_start_year_samples": odd_year_samples,
        "future_start_year_samples": future_year_samples,
        "ratings_covered_count": ratings_covered,
        "orphan_titles_count": orphan_titles,
        "rating_coverage_ratio": round(rating_coverage, 6),
    }


def assess_ratings(
    path: Path,
    seen_basics: set[str],
    *,
    max_rows: int | None = None,
) -> dict:
    if not path.exists():
        raise QualityError(f"评分表不存在：{path}")
    if max_rows is not None and max_rows <= 0:
        raise QualityError(f"max_rows 必须为正整数，收到 {max_rows}")

    total = 0
    unique_ids: set[str] = set()
    duplicate_tconst = 0
    invalid_rating = 0
    rating_out_of_range = 0
    invalid_votes = 0
    votes_out_of_range = 0
    orphan_count = 0

    rating_histogram: Counter[str] = Counter()
    votes_bucket: Counter[str] = Counter()
    rating_min = 11.0
    rating_max = 0.0
    rating_sum = 0.0
    rating_count = 0

    for row in _iter_rows(path, RATINGS_COLUMNS):
        if max_rows is not None and total >= max_rows:
            break
        total += 1

        tconst = row.get("tconst", "")
        if tconst in unique_ids:
            duplicate_tconst += 1
        else:
            unique_ids.add(tconst)

        if tconst and tconst not in seen_basics:
            orphan_count += 1

        rating_text = row.get("average_rating", "").strip()
        votes_text = row.get("num_votes", "").strip()

        if rating_text == "" or not _is_float(rating_text):
            invalid_rating += 1
        else:
            rating = float(rating_text)
            rating_histogram[rating_text] += 1
            if 1.0 <= rating <= 10.0:
                rating_sum += rating
                rating_count += 1
                rating_min = min(rating_min, rating)
                rating_max = max(rating_max, rating)
            else:
                rating_out_of_range += 1

        if votes_text == "" or not _is_int(votes_text):
            invalid_votes += 1
        else:
            votes = int(votes_text)
            votes_bucket[_votes_bucket(votes)] += 1
            if votes < 1:
                votes_out_of_range += 1

    mean_rating = rating_sum / rating_count if rating_count else 0.0

    return {
        "file": _safe_input_label(path),
        "rows_total": total,
        "unique_tconst": len(unique_ids),
        "duplicate_tconst": duplicate_tconst,
        "invalid_rating": invalid_rating,
        "rating_out_of_range": rating_out_of_range,
        "invalid_votes": invalid_votes,
        "votes_out_of_range": votes_out_of_range,
        "orphan_count": orphan_count,
        "rating_min": rating_min if rating_min <= 10 else None,
        "rating_max": rating_max if rating_max >= 1 else None,
        "rating_mean": round(mean_rating, 4) if rating_count else None,
        "rating_count": rating_count,
        "top_rating_values": dict(rating_histogram.most_common(10)),
        "votes_bucket_histogram": dict(votes_bucket),
    }


def assess(
    basics_path: Path,
    ratings_path: Path,
    output_path: Path,
    *,
    dry_run: bool = False,
    max_rows: int | None = None,
) -> dict:
    if max_rows is not None and max_rows <= 0:
        raise QualityError(f"max_rows 必须为正整数，收到 {max_rows}")

    basics_path = Path(basics_path)
    ratings_path = Path(ratings_path)
    output_path = Path(output_path)

    if not dry_run:
        _assert_safe_output(output_path)

    basics_hashes = {
        "sha256": _sha256(basics_path),
        "file_bytes": basics_path.stat().st_size,
        "label": _safe_input_label(basics_path),
    }
    ratings_hashes = {
        "sha256": _sha256(ratings_path),
        "file_bytes": ratings_path.stat().st_size,
        "label": _safe_input_label(ratings_path),
    }

    seen_basics: set[str] = set()
    seen_ratings: set[str] = set()
    basics_scanned = 0
    ratings_scanned = 0

    for row in _iter_rows(basics_path, BASICS_COLUMNS):
        if max_rows is not None and basics_scanned >= max_rows:
            break
        basics_scanned += 1
        tconst = row.get("tconst", "").strip()
        if tconst:
            seen_basics.add(tconst)
    for row in _iter_rows(ratings_path, RATINGS_COLUMNS):
        if max_rows is not None and ratings_scanned >= max_rows:
            break
        ratings_scanned += 1
        tconst = row.get("tconst", "").strip()
        if tconst:
            seen_ratings.add(tconst)

    basics_report = assess_basics(basics_path, seen_ratings, max_rows=max_rows)
    ratings_report = assess_ratings(ratings_path, seen_basics, max_rows=max_rows)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "basics_input": basics_hashes,
        "ratings_input": ratings_hashes,
        "assessment_constraints": {
            "max_rows_per_table": max_rows,
            "early_valid_year": EARLIEST_MOVIE_YEAR,
            "future_year_cutoff": datetime.now().year + 1,
        },
        "basics": basics_report,
        "ratings": ratings_report,
    }

    if dry_run:
        return report

    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.", suffix=".part", dir=str(output_path.parent)
    )
    try:
        os.close(descriptor)
        temp_path = Path(temp_name)
        payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        temp_path.write_text(payload, encoding="utf-8")
        os.replace(temp_path, output_path)
    except Exception:
        try:
            Path(temp_name).unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="评估 IMDb 标准化 CSV 数据质量（只读、流式、安全输出）。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--basics", type=Path, default=DEFAULT_BASICS, help="标准化主表 CSV 路径"
    )
    parser.add_argument(
        "--ratings", type=Path, default=DEFAULT_RATINGS, help="标准化评分表 CSV 路径"
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT, help="质量报告 JSON 路径"
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help="最多扫描的行数（正整数；用于调试/测试，默认全量）",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="只输出到标准输出，不写报告文件"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_rows is not None and args.max_rows <= 0:
        print("[错误] --max-rows 必须为正整数", file=sys.stderr)
        return 2
    try:
        report = assess(
            args.basics,
            args.ratings,
            args.output,
            dry_run=args.dry_run,
            max_rows=args.max_rows,
        )
    except (OSError, QualityError, RuntimeError) as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1

    basics = report["basics"]
    ratings = report["ratings"]
    print(f"[主表] {basics['rows_total']} 行，唯一 tconst {basics['unique_tconst']}")
    print(
        f"        评分覆盖 {basics['ratings_covered_count']} 部，"
        f"覆盖率 {basics['rating_coverage_ratio']:.2%}"
    )
    print(
        f"        缺失 start_year {basics['missing_start_year']}，"
        f"runtime {basics['missing_runtime']}，genres {basics['missing_genres']}"
    )
    print(
        f"        异常 start_year"
        f"：{basics['invalid_start_year'] + basics['future_start_year']}"
    )
    print(f"[评分] {ratings['rows_total']} 行，唯一 tconst {ratings['unique_tconst']}")
    print(
        f"       孤儿评分 {ratings['orphan_count']}，"
        f"无效评分 {ratings['invalid_rating'] + ratings['rating_out_of_range']}，"
        f"无效票数 {ratings['invalid_votes'] + ratings['votes_out_of_range']}"
    )
    if not args.dry_run:
        print(f"[完成] 报告已写入 {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
