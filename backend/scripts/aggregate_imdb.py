"""阶段 3.5.3B：IMDb 标准化 CSV → 轻量 JSON 聚合统计。

只做读操作：不修改摄取脚本、不修改质量评估脚本、不修改原始数据。
输出用于前端图表展示，采用流式读取、两遍扫描（主表 → 评分表）。

输入（默认）：
    backend/data/processed/large/imdb_titles_movies.csv
    backend/data/processed/large/imdb_ratings.csv

输出（默认）：
    backend/data/processed/large/imdb_aggregate.json

聚合指标：
    * 电影年份分布（正常年份 + 缺失 + 异常 + 未来）
    * 电影类型分布（genres 逗号拆分，一部多类型可计入多个）
    * IMDb 评分分布（0.5 分区间，0.0-0.5, 0.5-1.0, ..., 9.5-10.0）
    * IMDb 投票量分布（对数桶，与质量评估阶段口径一致）
    * 按年份的评分趋势（各年份有评分电影数、平均评分、平均投票数）
    * 评分覆盖率（全部 / 有评分 / 无评分）

安全：
    * 输出路径与质量报告同目录保护规则（复用 assess_imdb_quality 常量）。
    * 仓库内仅允许写入 imdb_aggregate.json。
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

# ---------- 与 assess_imdb_quality 保持一致的常量 ----------

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent

DEFAULT_BASICS = BACKEND_DIR / "data" / "processed" / "large" / "imdb_titles_movies.csv"
DEFAULT_RATINGS = BACKEND_DIR / "data" / "processed" / "large" / "imdb_ratings.csv"
DEFAULT_OUTPUT = BACKEND_DIR / "data" / "processed" / "large" / "imdb_aggregate.json"

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


# ---------- 异常 ----------


class AggregateError(RuntimeError):
    """参数校验、输入损坏或输出路径不安全。"""


# ---------- 路径保护（复用 assess_imdb_quality 逻辑） ----------


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _safe_input_label(path: Path) -> str:
    try:
        rel = path.resolve().relative_to(REPO_ROOT.resolve())
        return str(rel)
    except ValueError:
        return f"external:{path.name}"


def _assert_safe_output(path: Path, *, allowed: Path) -> None:
    resolved = path.resolve()
    repo = REPO_ROOT.resolve()
    if _is_within(resolved, repo):
        if resolved != allowed.resolve():
            raise AggregateError(
                f"聚合输出路径不在允许范围内：{resolved}；仅允许 {allowed}"
            )
        return
    parent = resolved.parent
    probe = parent
    for _ in range(6):
        if (probe / ".git").exists():
            raise AggregateError(
                f"聚合输出路径落在另一个 Git 仓库内：{resolved}；请改用系统临时目录"
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
            raise AggregateError(f"{path} 缺少必需列 {missing}")
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
    """将原始票数映射到固定的对数区间桶。

    与 assess_imdb_quality._votes_bucket 口径一致。
    """
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


def _rating_bucket(rating: float) -> str:
    """将评分映射到 0.5 分区间桶。

    区间边界：[0.0, 0.5), [0.5, 1.0), ..., [9.5, 10.0]。
    评分 10.0 归入 '9.5-10.0'。
    仅对 1.0..10.0 的有效评分有意义。
    """
    if rating < 0:
        return "invalid"
    # 边界：floor(rating * 2) / 2 作为左边界
    left = int(rating * 2) / 2.0
    if left >= 10.0:
        left = 9.5
    right = left + 0.5
    if right > 10.0:
        right = 10.0
    return f"{left:.1f}-{right:.1f}"


# ---------- 扫描主表 ----------


def _scan_basics(
    path: Path,
    *,
    max_rows: int | None = None,
) -> dict:
    if not path.exists():
        raise AggregateError(f"主表不存在：{path}")

    year_counts: Counter[int] = Counter()
    missing_year = 0
    invalid_year = 0
    future_year = 0
    genre_counts: Counter[str] = Counter()
    tconst_to_year: dict[str, int | None] = {}
    seen_tconsts: set[str] = set()
    duplicate_tconst = 0
    total = 0

    this_year = datetime.now().year + 1

    for row in _iter_rows(path, BASICS_COLUMNS):
        if max_rows is not None and total >= max_rows:
            break
        total += 1

        tconst = row.get("tconst", "").strip()
        if not tconst:
            # 无 tconst 的行无法关联评分、也不计入任何统计口径
            continue

        # 重复 tconst：first-wins，不覆盖先前记录；只累加计数器
        if tconst in seen_tconsts:
            duplicate_tconst += 1
            continue
        seen_tconsts.add(tconst)

        year_val: int | None = None
        year_text = row.get("start_year", "").strip()
        if year_text == "":
            missing_year += 1
        elif _is_int(year_text):
            iv = int(year_text)
            if iv < EARLIEST_MOVIE_YEAR:
                invalid_year += 1
            elif iv > this_year:
                future_year += 1
            else:
                year_counts[iv] += 1
                year_val = iv
        else:
            invalid_year += 1

        genres_text = row.get("genres", "").strip()
        if genres_text:
            for genre in genres_text.split(","):
                genre = genre.strip()
                if genre:
                    genre_counts[genre] += 1

        tconst_to_year[tconst] = year_val

    return {
        "year_counts": dict(sorted(year_counts.items())),
        "missing_year": missing_year,
        "invalid_year": invalid_year,
        "future_year": future_year,
        "genre_counts": dict(sorted(genre_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "tconst_to_year": tconst_to_year,
        "unique_tconst": len(seen_tconsts),
        "duplicate_tconst": duplicate_tconst,
        "total": total,
    }


# ---------- 扫描评分表 ----------


def _scan_ratings(
    path: Path,
    tconst_to_year: dict[str, int | None],
    *,
    max_rows: int | None = None,
) -> dict:
    if not path.exists():
        raise AggregateError(f"评分表不存在：{path}")

    rating_bucket_counts: Counter[str] = Counter()
    votes_bucket_counts: Counter[str] = Counter()
    # year_stats 每桶独立维护：rated_count / valid_rating_count / valid_votes_count
    # 以及对应的 sum。分母用 valid_*_count，为 0 则输出 null。
    year_stats: dict[int, dict[str, float | int]] = {}
    rated_tconsts: set[str] = set()
    duplicate_tconst = 0
    orphan_count = 0
    invalid_rating = 0
    invalid_votes = 0
    valid_rating_total = 0
    valid_votes_total = 0
    total = 0

    for row in _iter_rows(path, RATINGS_COLUMNS):
        if max_rows is not None and total >= max_rows:
            break
        total += 1

        tconst = row.get("tconst", "").strip()
        if not tconst:
            continue

        if tconst not in tconst_to_year:
            orphan_count += 1
            continue  # 孤立评分不参与后续统计

        # 重复 tconst：first-wins，不覆盖已有评分
        if tconst in rated_tconsts:
            duplicate_tconst += 1
            continue
        rated_tconsts.add(tconst)

        rating_text = row.get("average_rating", "").strip()
        votes_text = row.get("num_votes", "").strip()

        rating_valid = rating_text != "" and _is_float(rating_text)
        votes_valid = votes_text != "" and _is_int(votes_text)

        rating_val = float(rating_text) if rating_valid else None
        votes_val = int(votes_text) if votes_valid else None

        rating_ok = rating_val is not None and 1.0 <= rating_val <= 10.0
        votes_ok = votes_val is not None and votes_val >= 1

        if rating_ok:
            rating_bucket_counts[_rating_bucket(rating_val)] += 1
            valid_rating_total += 1
        else:
            invalid_rating += 1

        if votes_ok:
            votes_bucket_counts[_votes_bucket(votes_val)] += 1
            valid_votes_total += 1
        else:
            invalid_votes += 1

        # 年份趋势桶
        year = tconst_to_year.get(tconst)
        if year is not None:
            bucket = year_stats.setdefault(
                year,
                {
                    "rated_count": 0,
                    "valid_rating_count": 0,
                    "valid_votes_count": 0,
                    "rating_sum": 0.0,
                    "votes_sum": 0,
                },
            )
            bucket["rated_count"] += 1
            if rating_ok:
                bucket["valid_rating_count"] += 1
                bucket["rating_sum"] += float(rating_val)  # type: ignore[arg-type]
            if votes_ok:
                bucket["valid_votes_count"] += 1
                bucket["votes_sum"] += int(votes_val)  # type: ignore[arg-type]

    # 计算各年份均值：rating_mean 只除以 valid_rating_count，votes_mean 只除以 valid_votes_count
    year_trend = {}
    for year in sorted(year_stats):
        bucket = year_stats[year]
        rated = int(bucket["rated_count"])
        vrc = int(bucket["valid_rating_count"])
        vvc = int(bucket["valid_votes_count"])
        rating_mean = round(float(bucket["rating_sum"]) / vrc, 4) if vrc > 0 else None
        votes_mean = round(int(bucket["votes_sum"]) / vvc, 2) if vvc > 0 else None
        year_trend[year] = {
            "rated_count": rated,
            "valid_rating_count": vrc,
            "valid_votes_count": vvc,
            "rating_mean": rating_mean,
            "votes_mean": votes_mean,
        }

    return {
        "rating_bucket_counts": dict(sorted(rating_bucket_counts.items())),
        "votes_bucket_counts": dict(votes_bucket_counts),
        "year_trend": year_trend,
        "rated_tconsts": rated_tconsts,
        "orphan_count": orphan_count,
        "duplicate_tconst": duplicate_tconst,
        "invalid_rating": invalid_rating,
        "invalid_votes": invalid_votes,
        "valid_rating_total": valid_rating_total,
        "valid_votes_total": valid_votes_total,
        "total": total,
    }


# ---------- 完整性校验 ----------


def _check_integrity(
    basics_result: dict,
    ratings_result: dict,
    report: dict,
) -> None:
    """写入前执行五项完整性校验；全部失败时抛 AggregateError。

    1. 正常年份 + 缺失 + 非法 + 未来 == 电影总数
    2. 有评分电影 + 无评分电影 == 电影总数
    3. 评分分桶合计 == 有效评分总数
    4. 投票分桶合计 == 有效投票总数
    5. 各年份 trend 的分母 ≤ 该年份 rated_count，且 sum(valid_rating_count) ≤ valid_rating_total
    """
    errors: list[str] = []

    total = report["coverage"]["total_movies"]
    yd = report["year_distribution"]
    # normal_year_movies 的 values 是 {"total_movies": N, "rated_movies": M}
    normal_sum = sum(v["total_movies"] for v in yd["per_year"].values())
    year_total = normal_sum + yd["missing_year"] + yd["invalid_year"] + yd["future_year"]
    if year_total != total:
        errors.append(
            f"年份分布合计 {year_total} != 电影总数 {total} "
            f"(正常 {normal_sum} + 缺失 {yd['missing_year']} + 非法 {yd['invalid_year']} + 未来 {yd['future_year']})"
        )

    rated = report["coverage"]["rated_movies"]
    unrated = report["coverage"]["unrated_movies"]
    if rated + unrated != total:
        errors.append(
            f"覆盖率合计 {rated} + {unrated} = {rated + unrated} != 电影总数 {total}"
        )

    rb = report["rating_distribution"]
    rb_sum = sum(rb.values())
    if rb_sum != ratings_result["valid_rating_total"]:
        errors.append(
            f"评分分桶合计 {rb_sum} != 有效评分总数 {ratings_result['valid_rating_total']}"
        )

    vb = report["votes_distribution"]
    vb_sum = sum(vb.values())
    if vb_sum != ratings_result["valid_votes_total"]:
        errors.append(
            f"投票分桶合计 {vb_sum} != 有效投票总数 {ratings_result['valid_votes_total']}"
        )

    # 5. 年份 trend 分母 <= rated_count；全局分母之和 <= 全局有效
    sum_vrc = 0
    sum_vvc = 0
    for year, entry in report["year_rating_trend"].items():
        rc = entry["rated_count"]
        vrc = entry["valid_rating_count"]
        vvc = entry["valid_votes_count"]
        if vrc > rc:
            errors.append(f"年份 {year}: valid_rating_count {vrc} > rated_count {rc}")
        if vvc > rc:
            errors.append(f"年份 {year}: valid_votes_count {vvc} > rated_count {rc}")
        sum_vrc += vrc
        sum_vvc += vvc
    if sum_vrc > ratings_result["valid_rating_total"]:
        errors.append(
            f"年份 valid_rating_count 求和 {sum_vrc} > 全局有效评分 {ratings_result['valid_rating_total']}"
        )
    if sum_vvc > ratings_result["valid_votes_total"]:
        errors.append(
            f"年份 valid_votes_count 求和 {sum_vvc} > 全局有效投票 {ratings_result['valid_votes_total']}"
        )

    if errors:
        joined = "\n  - ".join(errors)
        raise AggregateError(f"聚合完整性校验失败：\n  - {joined}")


# ---------- 主入口 ----------


def aggregate(
    basics_path: Path,
    ratings_path: Path,
    output_path: Path,
    *,
    dry_run: bool = False,
    max_rows: int | None = None,
) -> dict:
    if max_rows is not None and max_rows <= 0:
        raise AggregateError(f"max_rows 必须为正整数，收到 {max_rows}")

    basics_path = Path(basics_path)
    ratings_path = Path(ratings_path)
    output_path = Path(output_path)

    if not dry_run:
        _assert_safe_output(output_path, allowed=DEFAULT_OUTPUT)

    basics_hash = {
        "sha256": _sha256(basics_path),
        "file_bytes": basics_path.stat().st_size,
        "label": _safe_input_label(basics_path),
    }
    ratings_hash = {
        "sha256": _sha256(ratings_path),
        "file_bytes": ratings_path.stat().st_size,
        "label": _safe_input_label(ratings_path),
    }

    basics_result = _scan_basics(basics_path, max_rows=max_rows)
    ratings_result = _scan_ratings(
        ratings_path, basics_result["tconst_to_year"], max_rows=max_rows
    )

    # 覆盖率口径：以 basics 的唯一 tconst 为全集（与质量评估一致）
    total_movies = basics_result["unique_tconst"]
    rated_count = len(ratings_result["rated_tconsts"])
    unrated_count = total_movies - rated_count

    # 合并年份分布：趋势中未出现的年份（0 部评分）也要保留 total
    year_distribution = {}
    for year, count in basics_result["year_counts"].items():
        trend = ratings_result["year_trend"].get(year, {})
        year_distribution[year] = {
            "total_movies": count,
            "rated_movies": trend.get("rated_count", 0),
        }

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "basics_input": basics_hash,
        "ratings_input": ratings_hash,
        "aggregate_constraints": {
            "max_rows_per_table": max_rows,
            "early_valid_year": EARLIEST_MOVIE_YEAR,
            "future_year_cutoff": datetime.now().year + 1,
            "rating_bucket_width": 0.5,
            "votes_bucket_definition": [
                "invalid", "1-10", "11-100", "101-1k",
                "1k-10k", "10k-100k", "100k-1M", ">1M",
            ],
            "duplicate_policy": "first-wins",
        },
        "coverage": {
            "total_movies": total_movies,
            "rated_movies": rated_count,
            "unrated_movies": unrated_count,
            "coverage_ratio": round(rated_count / total_movies, 6) if total_movies else 0.0,
            "orphan_ratings": ratings_result["orphan_count"],
        },
        "year_distribution": {
            "per_year": year_distribution,
            "missing_year": basics_result["missing_year"],
            "invalid_year": basics_result["invalid_year"],
            "future_year": basics_result["future_year"],
        },
        "genre_distribution": basics_result["genre_counts"],
        "rating_distribution": ratings_result["rating_bucket_counts"],
        "votes_distribution": ratings_result["votes_bucket_counts"],
        "year_rating_trend": ratings_result["year_trend"],
        "quality_flags": {
            "invalid_ratings_skipped": ratings_result["invalid_rating"],
            "invalid_votes_skipped": ratings_result["invalid_votes"],
        },
        "duplicate_counts": {
            "basics_duplicate_tconst": basics_result["duplicate_tconst"],
            "ratings_duplicate_tconst": ratings_result["duplicate_tconst"],
        },
    }

    # 完整性校验：任何失败都禁止覆盖旧文件
    _check_integrity(basics_result, ratings_result, report)

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
        description="将 IMDb 标准化 CSV 聚合成轻量 JSON（只读、流式、安全输出）。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--basics", type=Path, default=DEFAULT_BASICS, help="标准化主表 CSV 路径"
    )
    parser.add_argument(
        "--ratings", type=Path, default=DEFAULT_RATINGS, help="标准化评分表 CSV 路径"
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT, help="聚合 JSON 输出路径"
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help="最多扫描行数（正整数；用于调试/测试，默认全量）",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="只在标准输出打印摘要，不写文件"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_rows is not None and args.max_rows <= 0:
        print("[错误] --max-rows 必须为正整数", file=sys.stderr)
        return 2
    try:
        report = aggregate(
            args.basics,
            args.ratings,
            args.output,
            dry_run=args.dry_run,
            max_rows=args.max_rows,
        )
    except (OSError, AggregateError, RuntimeError) as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1

    cov = report["coverage"]
    print(f"[聚合] 电影总数 {cov['total_movies']}，有评分 {cov['rated_movies']}，覆盖率 {cov['coverage_ratio']:.2%}")
    print(f"[年份] 正常年份 {len(report['year_distribution']['per_year'])} 档，"
          f"缺失 {report['year_distribution']['missing_year']}，"
          f"异常 {report['year_distribution']['invalid_year']}，"
          f"未来 {report['year_distribution']['future_year']}")
    print(f"[类型] {len(report['genre_distribution'])} 个类型")
    print(f"[评分分布] {len(report['rating_distribution'])} 个区间")
    print(f"[投票分布] {len(report['votes_distribution'])} 个桶")
    if not args.dry_run:
        print(f"[完成] 聚合 JSON 已写入 {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
