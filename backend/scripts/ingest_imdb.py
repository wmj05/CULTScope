"""阶段 3.5.2A：IMDb 数据摄取（流式读取、小样本可测、可复现）。

输入（默认）：
    backend/data/raw/imdb/title.basics.tsv.gz
    backend/data/raw/imdb/title.ratings.tsv.gz

输出（默认）：
    backend/data/processed/large/imdb_titles_movies.csv
    backend/data/processed/large/imdb_ratings.csv
    docs/data_manifests/manifest_imdb_title.basics.json
    docs/data_manifests/manifest_imdb_title.ratings.json

用法（在仓库根目录）：
    python backend/scripts/ingest_imdb.py --help
    python backend/scripts/ingest_imdb.py --dry-run
    python backend/scripts/ingest_imdb.py --ingest-date 2026-11-18

约束：
    * 使用标准库 + 已安装依赖，不新增依赖。
    * 按行流式读取 gzip，不一次性载入内存。
    * 不读取、不写入 knowledge / candidates，不修改既有 TMDb 流程。
    * 失败时不留下半写入的正式输出文件。

提交语义（重要限制）：
    * 四个输出（两个 CSV + 两份 manifest）先在目标目录生成临时文件并校验，
      全部准备完成后才统一提交；提交过程中保留旧文件备份，可捕获异常时回滚。
    * 这不是跨文件的原子事务。若进程在提交期间被强制终止或机器断电，
      仍可能留下部分新文件与 `.bak-*` 备份，需要人工按备份恢复。
      本脚本不承诺断电/强杀后的自动恢复。
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Iterable, TextIO

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent

DEFAULT_BASICS = BACKEND_DIR / "data" / "raw" / "imdb" / "title.basics.tsv.gz"
DEFAULT_RATINGS = BACKEND_DIR / "data" / "raw" / "imdb" / "title.ratings.tsv.gz"
DEFAULT_OUTPUT_DIR = BACKEND_DIR / "data" / "processed" / "large"
DEFAULT_MANIFEST_DIR = REPO_ROOT / "docs" / "data_manifests"

BASICS_URL = "https://datasets.imdbws.com/title.basics.tsv.gz"
RATINGS_URL = "https://datasets.imdbws.com/title.ratings.tsv.gz"

SCRIPT_VERSION = "0.1.0"

TCONST_PATTERN = re.compile(r"^tt\d{7,}$")
BASICS_REQUIRED_COLUMNS = [
    "tconst",
    "titleType",
    "primaryTitle",
    "originalTitle",
    "isAdult",
    "startYear",
    "endYear",
    "runtimeMinutes",
    "genres",
]
RATINGS_REQUIRED_COLUMNS = ["tconst", "averageRating", "numVotes"]

BASICS_OUTPUT_COLUMNS = [
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
RATINGS_OUTPUT_COLUMNS = ["tconst", "average_rating", "num_votes", "ingest_date"]

BASICS_OUTPUT_NAME = "imdb_titles_movies.csv"
RATINGS_OUTPUT_NAME = "imdb_ratings.csv"
BASICS_MANIFEST_NAME = "manifest_imdb_title.basics.json"
RATINGS_MANIFEST_NAME = "manifest_imdb_title.ratings.json"

# 这些路径属于正式数据，任何输出都不得覆盖或写入
PROTECTED_DIRS = [
    BACKEND_DIR / "data" / "knowledge",
    BACKEND_DIR / "data" / "candidates",
    BACKEND_DIR / "data" / "raw" / "tmdb",
]
PROTECTED_FILES = [
    BACKEND_DIR / "data" / "processed" / "cult_movies_clean.csv",
]

# 仅允许脚本自己的默认目录，或仓库外的临时目录；
# 仓库内的其他位置一律视为“非本脚本管理的项目文件”。
ALLOWED_OUTPUT_ROOT = DEFAULT_OUTPUT_DIR
ALLOWED_MANIFEST_ROOT = DEFAULT_MANIFEST_DIR


class IngestError(RuntimeError):
    """输入损坏、结构不符或输出路径不安全时抛出。"""


def _normalize(value: str) -> str:
    """IMDb 用字面量 \\N 表示缺失值，其余字段去首尾空白。"""
    text = value.strip()
    return "" if text == "\\N" else text


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _detect_git_commit() -> str:
    """读取当前提交作为血缘信息；失败时返回 unknown，不阻塞摄取。"""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    commit = completed.stdout.strip()
    return commit if completed.returncode == 0 and commit else "unknown"


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _assert_safe_paths(output_dir: Path, manifest_dir: Path) -> None:
    """拒绝写入正式数据、TMDb 数据以及仓库内非本脚本管理的目录。

    仓库外的路径（如 tempfile 创建的临时目录）允许使用，便于测试。
    """
    resolved_output = output_dir.resolve()
    resolved_manifest = manifest_dir.resolve()
    resolved_repo = REPO_ROOT.resolve()

    for protected in PROTECTED_DIRS:
        protected_resolved = protected.resolve()
        for label, target in (("输出目录", resolved_output), ("清单目录", resolved_manifest)):
            if _is_within(target, protected_resolved):
                raise IngestError(
                    f"{label}不得位于受保护目录内：{target}（受保护：{protected_resolved}）"
                )

    for label, target, allowed in (
        ("输出目录", resolved_output, ALLOWED_OUTPUT_ROOT.resolve()),
        ("清单目录", resolved_manifest, ALLOWED_MANIFEST_ROOT.resolve()),
    ):
        if _is_within(target, resolved_repo) and not _is_within(target, allowed):
            raise IngestError(
                f"{label}不在本脚本管理范围内：{target}；"
                f"仅允许 {allowed} 或仓库外的临时目录"
            )

    protected_files = {path.resolve() for path in PROTECTED_FILES}
    planned = [
        resolved_output / BASICS_OUTPUT_NAME,
        resolved_output / RATINGS_OUTPUT_NAME,
        resolved_manifest / BASICS_MANIFEST_NAME,
        resolved_manifest / RATINGS_MANIFEST_NAME,
    ]
    for path in planned:
        if path in protected_files:
            raise IngestError(f"输出路径会覆盖受保护文件：{path}")


def _iter_tsv(
    path: Path, required_columns: list[str]
) -> Iterable[tuple[int, list[str], dict[str, int], int]]:
    """逐行读取 gzip TSV，返回行号、字段、列索引和期望列数。"""
    if not path.exists():
        raise IngestError(f"输入文件不存在：{path}")

    try:
        with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
            try:
                header = next(reader)
            except StopIteration as exc:
                raise IngestError(f"输入文件为空：{path}") from exc

            missing = [name for name in required_columns if name not in header]
            if missing:
                raise IngestError(f"输入文件缺少必需列 {missing}：{path}")

            index = {name: header.index(name) for name in required_columns}
            expected_width = len(header)
            for line_number, row in enumerate(reader, start=2):
                yield line_number, row, index, expected_width
    except IngestError:
        raise
    except (gzip.BadGzipFile, EOFError, OSError, UnicodeDecodeError, csv.Error) as exc:
        raise IngestError(f"无法读取输入文件 {path}：{exc}") from exc


def _parse_int(raw: str, minimum: int | None = None) -> tuple[int | None, str]:
    """解析整数，返回 (值, 状态)。状态为 ok / missing / invalid。"""
    text = _normalize(raw)
    if not text:
        return None, "missing"
    try:
        value = int(text)
    except ValueError:
        return None, "invalid"
    if minimum is not None and value < minimum:
        return None, "invalid"
    return value, "ok"


def _parse_rating(raw: str) -> float | None:
    text = _normalize(raw)
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if 1.0 <= value <= 10.0 else None


def _new_temp_file(directory: Path, prefix: str) -> tuple[TextIO, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{prefix}-", suffix=".tmp", dir=str(directory)
    )
    return os.fdopen(descriptor, "w", encoding="utf-8", newline=""), Path(name)


def _close_and_flush(handle: TextIO) -> None:
    handle.flush()
    os.fsync(handle.fileno())
    handle.close()


def _verify_csv(path: Path, expected_header: list[str], expected_rows: int) -> None:
    """回读临时文件，确认表头与行数，避免半写入文件被替换。"""
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header != expected_header:
            raise IngestError(f"临时文件表头校验失败：{path}")
        count = sum(1 for _ in reader)
    if count != expected_rows:
        raise IngestError(
            f"临时文件行数校验失败：{path} 期望 {expected_rows}，实际 {count}"
        )


def _stage_json(target: Path, payload: dict) -> Path:
    """在目标同目录写入并校验 JSON 临时文件，但不替换目标文件。"""
    handle, temp_path = _new_temp_file(target.parent, target.name)
    try:
        with handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        json.loads(temp_path.read_text(encoding="utf-8"))
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise
    return temp_path


def _replace(staged: Path, target: Path) -> None:
    """提交单个暂存文件。单文件替换是原子的，但四个文件整体不是原子事务。"""
    os.replace(staged, target)


def _commit_outputs(entries: list[tuple[Path, Path]]) -> None:
    """依次提交暂存文件；任一失败则回滚已提交项并恢复旧文件。

    每个旧文件在提交前移动到同目录的 `.bak-*`，提交成功后删除。
    回滚时成功移回原位的备份不再存在；若某个备份移回失败，该备份是原始
    数据的最后一份副本，必须保留并在异常信息中列出，等待人工恢复。
    该机制只覆盖可捕获异常；断电或进程被强制终止不在保证范围内。
    """
    backups: list[tuple[Path, Path]] = []
    installed: list[Path] = []
    try:
        for staged, target in entries:
            if target.exists():
                descriptor, backup_name = tempfile.mkstemp(
                    prefix=f".{target.name}.bak-", dir=str(target.parent)
                )
                os.close(descriptor)
                backup = Path(backup_name)
                try:
                    os.replace(target, backup)
                except OSError:
                    backup.unlink(missing_ok=True)
                    raise
                backups.append((target, backup))
            _replace(staged, target)
            installed.append(target)
    except Exception as exc:
        rollback_errors: list[str] = []
        unrestored: list[str] = []
        for target in reversed(installed):
            try:
                if target.exists():
                    target.unlink()
            except OSError as rollback_exc:
                rollback_errors.append(f"删除 {target} 失败：{rollback_exc}")
        for target, backup in reversed(backups):
            try:
                if backup.exists():
                    os.replace(backup, target)
            except OSError as rollback_exc:
                # 恢复失败时备份仍留在磁盘上，是原始数据的最后一份副本，
                # 不得自动清理，需人工按此路径恢复。
                unrestored.append(f"{target}（备份保留于 {backup}）")
                rollback_errors.append(f"恢复 {target} 失败：{rollback_exc}")
        detail = f"；回滚异常：{'；'.join(rollback_errors)}" if rollback_errors else ""
        if unrestored:
            detail += (
                "；以下旧文件未能自动恢复，对应备份已保留，需人工恢复："
                + "；".join(unrestored)
            )
        raise IngestError(f"多文件提交失败，已尝试回滚：{exc}{detail}") from exc
    else:
        for _, backup in backups:
            try:
                if backup.exists():
                    backup.unlink()
            except OSError:
                pass


def _empty_basics_stats() -> dict:
    return {
        "raw_rows": 0,
        "retained_rows": 0,
        "malformed_rows": 0,
        "invalid_tconst": 0,
        "excluded_title_type": 0,
        "excluded_adult": 0,
        "excluded_invalid_is_adult": 0,
        "duplicate_tconst": 0,
        "missing_start_year": 0,
        "invalid_start_year": 0,
        "missing_end_year": 0,
        "invalid_end_year": 0,
        "missing_runtime": 0,
        "invalid_runtime": 0,
        "missing_genres": 0,
        "title_type_counts": Counter(),
    }


def _empty_ratings_stats() -> dict:
    return {
        "raw_rows": 0,
        "retained_rows": 0,
        "malformed_rows": 0,
        "invalid_tconst": 0,
        "excluded_orphan": 0,
        "excluded_invalid_rating": 0,
        "excluded_invalid_votes": 0,
        "duplicate_tconst": 0,
    }


def _scan_basics(
    path: Path,
    writer: csv.writer | None,
    stats: dict,
    retained_ids: set[str],
    ingest_date: str,
) -> None:
    for line_number, row, index, width in _iter_tsv(path, BASICS_REQUIRED_COLUMNS):
        stats["raw_rows"] += 1
        if len(row) != width:
            stats["malformed_rows"] += 1
            continue

        tconst = _normalize(row[index["tconst"]])
        if not TCONST_PATTERN.match(tconst):
            stats["invalid_tconst"] += 1
            continue

        title_type = _normalize(row[index["titleType"]])
        stats["title_type_counts"][title_type or "(empty)"] += 1
        if title_type != "movie":
            stats["excluded_title_type"] += 1
            continue

        is_adult = _normalize(row[index["isAdult"]])
        if is_adult == "1":
            stats["excluded_adult"] += 1
            continue
        if is_adult != "0":
            stats["excluded_invalid_is_adult"] += 1
            continue

        if tconst in retained_ids:
            stats["duplicate_tconst"] += 1
            continue

        start_year, start_status = _parse_int(row[index["startYear"]])
        if start_status == "missing":
            stats["missing_start_year"] += 1
        elif start_status == "invalid":
            stats["invalid_start_year"] += 1

        end_year, end_status = _parse_int(row[index["endYear"]])
        if end_status == "missing":
            stats["missing_end_year"] += 1
        elif end_status == "invalid":
            stats["invalid_end_year"] += 1

        runtime, runtime_status = _parse_int(row[index["runtimeMinutes"]], minimum=1)
        if runtime_status == "missing":
            stats["missing_runtime"] += 1
        elif runtime_status == "invalid":
            stats["invalid_runtime"] += 1

        genres = _normalize(row[index["genres"]])
        if not genres:
            stats["missing_genres"] += 1

        retained_ids.add(tconst)
        stats["retained_rows"] += 1

        if writer is not None:
            writer.writerow(
                [
                    tconst,
                    title_type,
                    _normalize(row[index["primaryTitle"]]),
                    _normalize(row[index["originalTitle"]]),
                    is_adult,
                    "" if start_year is None else start_year,
                    "" if end_year is None else end_year,
                    "" if runtime is None else runtime,
                    genres,
                    ingest_date,
                ]
            )

    if stats["retained_rows"] == 0:
        raise IngestError(f"未从 {path} 保留任何电影记录，停止写入")


def _scan_ratings(
    path: Path,
    writer: csv.writer | None,
    stats: dict,
    retained_ids: set[str],
    ingest_date: str,
) -> None:
    seen: set[str] = set()
    for _line_number, row, index, width in _iter_tsv(path, RATINGS_REQUIRED_COLUMNS):
        stats["raw_rows"] += 1
        if len(row) != width:
            stats["malformed_rows"] += 1
            continue

        tconst = _normalize(row[index["tconst"]])
        if not TCONST_PATTERN.match(tconst):
            stats["invalid_tconst"] += 1
            continue

        # 评分表严格按保留的电影主表过滤，排除项全部计数
        if tconst not in retained_ids:
            stats["excluded_orphan"] += 1
            continue

        rating = _parse_rating(row[index["averageRating"]])
        if rating is None:
            stats["excluded_invalid_rating"] += 1
            continue

        votes, votes_status = _parse_int(row[index["numVotes"]], minimum=1)
        if votes_status != "ok" or votes is None:
            stats["excluded_invalid_votes"] += 1
            continue

        if tconst in seen:
            stats["duplicate_tconst"] += 1
            continue

        seen.add(tconst)
        stats["retained_rows"] += 1

        if writer is not None:
            writer.writerow([tconst, f"{rating:.1f}", votes, ingest_date])


def _excluded_rows(stats: dict) -> int:
    return stats["raw_rows"] - stats["retained_rows"]


def _build_manifest(
    *,
    dataset: str,
    official_url: str,
    input_path: Path,
    stats: dict,
    filter_rules: list[str],
    ingest_date: str,
    downloaded_at: str | None,
    git_commit: str,
    output_name: str,
    output_path: Path,
) -> dict:
    breakdown = {
        key: value
        for key, value in stats.items()
        if isinstance(value, int)
        and key not in {"raw_rows", "retained_rows", "excluded_rows"}
    }
    return {
        "source": "imdb",
        "dataset": dataset,
        "official_url": official_url,
        "downloaded_at": downloaded_at,
        "sha256": _sha256(input_path),
        "file_bytes": input_path.stat().st_size,
        "raw_rows": stats["raw_rows"],
        "retained_rows": stats["retained_rows"],
        "excluded_rows": _excluded_rows(stats),
        "filter_rules": filter_rules,
        "script_version": SCRIPT_VERSION,
        "git_commit": git_commit,
        "ingest_date": ingest_date,
        "excluded_breakdown": breakdown,
        "output_file": output_name,
        "output_sha256": _sha256(output_path),
        "output_rows": stats["retained_rows"],
    }


def _validate_ingest_date(value: str) -> str:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise IngestError(f"--ingest-date 不是合法日期：{value}") from exc
    return value


def ingest_imdb(
    *,
    basics_path: Path,
    ratings_path: Path,
    output_dir: Path,
    manifest_dir: Path,
    ingest_date: str,
    downloaded_at: str | None = None,
    dry_run: bool = False,
    git_commit: str | None = None,
) -> dict:
    """执行一次 IMDb 摄取，返回统计信息。

    该函数不读取、不写入 knowledge / candidates，也不修改既有清洗数据。
    """
    basics_path = Path(basics_path)
    ratings_path = Path(ratings_path)
    output_dir = Path(output_dir)
    manifest_dir = Path(manifest_dir)

    _validate_ingest_date(ingest_date)
    _assert_safe_paths(output_dir, manifest_dir)

    commit = git_commit or _detect_git_commit()

    basics_stats = _empty_basics_stats()
    ratings_stats = _empty_ratings_stats()
    retained_ids: set[str] = set()

    handles: list[TextIO] = []
    staged_paths: list[Path] = []
    temp_basics: Path | None = None
    temp_ratings: Path | None = None
    basics_writer: csv.writer | None = None
    ratings_writer: csv.writer | None = None

    try:
        if not dry_run:
            basics_handle, temp_basics = _new_temp_file(output_dir, "imdb-titles")
            handles.append(basics_handle)
            staged_paths.append(temp_basics)
            basics_writer = csv.writer(basics_handle, lineterminator="\n")
            basics_writer.writerow(BASICS_OUTPUT_COLUMNS)

        _scan_basics(basics_path, basics_writer, basics_stats, retained_ids, ingest_date)

        if not dry_run:
            ratings_handle, temp_ratings = _new_temp_file(output_dir, "imdb-ratings")
            handles.append(ratings_handle)
            staged_paths.append(temp_ratings)
            ratings_writer = csv.writer(ratings_handle, lineterminator="\n")
            ratings_writer.writerow(RATINGS_OUTPUT_COLUMNS)

        _scan_ratings(ratings_path, ratings_writer, ratings_stats, retained_ids, ingest_date)

        basics_stats["excluded_rows"] = _excluded_rows(basics_stats)
        ratings_stats["excluded_rows"] = _excluded_rows(ratings_stats)

        output_basics = output_dir / BASICS_OUTPUT_NAME
        output_ratings = output_dir / RATINGS_OUTPUT_NAME

        if not dry_run:
            for handle in handles:
                _close_and_flush(handle)
            handles.clear()

            assert temp_basics is not None and temp_ratings is not None
            _verify_csv(temp_basics, BASICS_OUTPUT_COLUMNS, basics_stats["retained_rows"])
            _verify_csv(temp_ratings, RATINGS_OUTPUT_COLUMNS, ratings_stats["retained_rows"])

            basics_manifest = _build_manifest(
                dataset="title.basics",
                official_url=BASICS_URL,
                input_path=basics_path,
                stats=basics_stats,
                filter_rules=[
                    "titleType == 'movie'",
                    "isAdult == '0'",
                    "tconst matches ^tt\\d{7,}$",
                    "duplicate tconst: keep first",
                ],
                ingest_date=ingest_date,
                downloaded_at=downloaded_at,
                git_commit=commit,
                output_name=BASICS_OUTPUT_NAME,
                output_path=temp_basics,
            )
            ratings_manifest = _build_manifest(
                dataset="title.ratings",
                official_url=RATINGS_URL,
                input_path=ratings_path,
                stats=ratings_stats,
                filter_rules=[
                    "tconst in retained imdb_titles_movies",
                    "1.0 <= averageRating <= 10.0",
                    "numVotes >= 1",
                    "duplicate tconst: keep first",
                ],
                ingest_date=ingest_date,
                downloaded_at=downloaded_at,
                git_commit=commit,
                output_name=RATINGS_OUTPUT_NAME,
                output_path=temp_ratings,
            )

            basics_manifest_path = manifest_dir / BASICS_MANIFEST_NAME
            ratings_manifest_path = manifest_dir / RATINGS_MANIFEST_NAME
            staged_basics_manifest = _stage_json(basics_manifest_path, basics_manifest)
            staged_paths.append(staged_basics_manifest)
            staged_ratings_manifest = _stage_json(ratings_manifest_path, ratings_manifest)
            staged_paths.append(staged_ratings_manifest)

            # 四个文件全部生成并校验后才开始覆盖正式输出
            _commit_outputs(
                [
                    (temp_basics, output_basics),
                    (temp_ratings, output_ratings),
                    (staged_basics_manifest, basics_manifest_path),
                    (staged_ratings_manifest, ratings_manifest_path),
                ]
            )

        return {
            "dry_run": dry_run,
            "ingest_date": ingest_date,
            "basics": basics_stats,
            "ratings": ratings_stats,
            "outputs": {
                "titles": str(output_dir / BASICS_OUTPUT_NAME),
                "ratings": str(output_dir / RATINGS_OUTPUT_NAME),
                "manifests": [
                    str(manifest_dir / BASICS_MANIFEST_NAME),
                    str(manifest_dir / RATINGS_MANIFEST_NAME),
                ],
            },
        }
    finally:
        for handle in handles:
            try:
                handle.close()
            except OSError:
                pass
        for staged in staged_paths:
            if staged.exists():
                try:
                    staged.unlink()
                except OSError:
                    pass


def _print_report(report: dict) -> None:
    basics = report["basics"]
    ratings = report["ratings"]
    print("\n========== IMDb 摄取完成 ==========")
    print(f"模式：{'dry-run（不写盘）' if report['dry_run'] else '正式输出'}")
    print(f"数据快照日期：{report['ingest_date']}")
    print(
        "电影主表："
        f"原始 {basics['raw_rows']} 行，保留 {basics['retained_rows']} 行，"
        f"排除 {basics['raw_rows'] - basics['retained_rows']} 行"
    )
    print(
        "  - 非 movie 类型：{}；成人内容：{}；重复 tconst：{}；畸形行：{}".format(
            basics["excluded_title_type"],
            basics["excluded_adult"],
            basics["duplicate_tconst"],
            basics["malformed_rows"],
        )
    )
    print(
        "  - 年份缺失 {} / 非法 {}；片长缺失 {} / 非法 {}；类型缺失 {}".format(
            basics["missing_start_year"],
            basics["invalid_start_year"],
            basics["missing_runtime"],
            basics["invalid_runtime"],
            basics["missing_genres"],
        )
    )
    print(
        "评分表："
        f"原始 {ratings['raw_rows']} 行，保留 {ratings['retained_rows']} 行，"
        f"排除 {ratings['raw_rows'] - ratings['retained_rows']} 行"
    )
    print(
        "  - 非保留电影：{}；非法评分：{}；非法票数：{}；重复 tconst：{}；畸形行：{}".format(
            ratings["excluded_orphan"],
            ratings["excluded_invalid_rating"],
            ratings["excluded_invalid_votes"],
            ratings["duplicate_tconst"],
            ratings["malformed_rows"],
        )
    )
    if not report["dry_run"]:
        print(f"主表输出：{report['outputs']['titles']}")
        print(f"评分输出：{report['outputs']['ratings']}")
        for manifest in report["outputs"]["manifests"]:
            print(f"清单输出：{manifest}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="IMDb 数据摄取：流式读取 title.basics / title.ratings，输出标准化 CSV 与血缘清单。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--basics", type=Path, default=DEFAULT_BASICS, help="title.basics.tsv.gz 路径")
    parser.add_argument("--ratings", type=Path, default=DEFAULT_RATINGS, help="title.ratings.tsv.gz 路径")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="标准化 CSV 输出目录")
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR, help="血缘清单输出目录（纳入 Git）")
    parser.add_argument(
        "--ingest-date",
        default=date.today().isoformat(),
        help="写入输出与清单的数据快照日期（YYYY-MM-DD）",
    )
    parser.add_argument(
        "--downloaded-at",
        default=None,
        help="原始文件下载时间；未知时保持为空，不伪造",
    )
    parser.add_argument("--dry-run", action="store_true", help="只检查与统计，不产生任何输出文件")
    parser.add_argument(
        "--git-commit",
        default=None,
        help="写入清单的 git commit；默认自动读取当前 HEAD",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        report = ingest_imdb(
            basics_path=args.basics,
            ratings_path=args.ratings,
            output_dir=args.output_dir,
            manifest_dir=args.manifest_dir,
            ingest_date=args.ingest_date,
            downloaded_at=args.downloaded_at,
            dry_run=args.dry_run,
            git_commit=args.git_commit,
        )
    except IngestError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"[错误] 文件写入失败：{exc}", file=sys.stderr)
        return 1

    _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
