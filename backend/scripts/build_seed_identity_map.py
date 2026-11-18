"""构建探索种子与 Cult 知识库种子的身份映射，不调用外部 API。

自动 confirmed 仅来自一致的稳定 ID，且年份一致、其他已知 ID 不冲突。
标题年份候选只能进入 needs_review。已有 match_method=manual* 的记录整行保留，
人工审核人、时间和原因应记录在 notes 中。

只读检查：
    python scripts/build_seed_identity_map.py --check
安全写入：
    python scripts/build_seed_identity_map.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import tempfile
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_EXPLORE = BACKEND_DIR / "scripts" / "seed_movies.csv"
DEFAULT_KNOWLEDGE = BACKEND_DIR / "data" / "knowledge" / "cult_seed.csv"
DEFAULT_EXPLORE_MOVIES = BACKEND_DIR / "data" / "processed" / "cult_movies.csv"
DEFAULT_OUTPUT = BACKEND_DIR / "data" / "knowledge" / "seed_identity_map.csv"

FIELDNAMES = [
    "explore_seed_id",
    "knowledge_seed_id",
    "tmdb_id",
    "imdb_id",
    "match_method",
    "match_status",
    "notes",
]
STATUSES = {"confirmed", "needs_review", "unmatched"}
KNOWLEDGE_ID_RE = re.compile(r"CS-\d{4}")
IMDB_ID_RE = re.compile(r"tt\d+")


class IdentityMapError(RuntimeError):
    """输入、合并或写入不安全，映射文件未被修改。"""


def _read_csv(path: Path, required: list[str]) -> list[dict[str, str]]:
    if not path.is_file():
        raise IdentityMapError(f"文件不存在：{path}")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = reader.fieldnames or []
            if len(headers) != len(set(headers)):
                raise IdentityMapError(f"CSV 表头存在重复字段：{path}")
            missing = set(required) - set(headers)
            if missing:
                raise IdentityMapError(
                    f"CSV 缺少字段 {sorted(missing)}：{path}"
                )
            rows = []
            for line_number, row in enumerate(reader, start=2):
                if None in row:
                    raise IdentityMapError(
                        f"CSV 第 {line_number} 行存在多余单元格：{path}"
                    )
                rows.append(
                    {
                        key: (value or "").strip()
                        for key, value in row.items()
                    }
                )
            return rows
    except (UnicodeError, csv.Error) as exc:
        raise IdentityMapError(f"CSV 无法按 UTF-8 读取：{path}（{exc}）") from exc


def _validate_tmdb(value: str, label: str) -> None:
    if value and (not value.isdigit() or int(value) <= 0):
        raise IdentityMapError(f"{label} 不是有效的 TMDb ID：{value!r}")


def _validate_imdb(value: str, label: str) -> None:
    if value and not IMDB_ID_RE.fullmatch(value):
        raise IdentityMapError(f"{label} 不是有效的 IMDb ID：{value!r}")


def _validate_year(value: str, label: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise IdentityMapError(f"{label} 不是有效年份：{value!r}") from None


def _validate_inputs(
    explore_rows: list[dict[str, str]],
    knowledge_rows: list[dict[str, str]],
    movie_rows: list[dict[str, str]],
) -> None:
    if not explore_rows:
        raise IdentityMapError("探索种子为空")
    if not knowledge_rows:
        raise IdentityMapError("知识库种子为空")

    explore_ids = [row["seed_id"] for row in explore_rows]
    knowledge_ids = [row["seed_id"] for row in knowledge_rows]
    for label, values in (("探索", explore_ids), ("知识库", knowledge_ids)):
        duplicates = sorted(value for value, count in Counter(values).items() if count > 1)
        if duplicates:
            raise IdentityMapError(f"{label}种子 seed_id 重复：{duplicates}")
        if any(not value for value in values):
            raise IdentityMapError(f"{label}种子存在空 seed_id")

    for row in explore_rows:
        label = f"探索种子 {row['seed_id']}"
        if not row["seed_id"].isdigit() or int(row["seed_id"]) <= 0:
            raise IdentityMapError(f"{label} 的 seed_id 必须是正整数")
        if not row["title"]:
            raise IdentityMapError(f"{label} 缺少标题")
        _validate_year(row["year"], label)
        _validate_tmdb(row.get("tmdb_id", ""), label)
        _validate_imdb(row.get("imdb_id", ""), label)

    for row in knowledge_rows:
        label = f"知识库种子 {row['seed_id']}"
        if not KNOWLEDGE_ID_RE.fullmatch(row["seed_id"]):
            raise IdentityMapError(f"{label} 不符合 CS-0001 格式")
        if not row["original_title"] and not row["title"]:
            raise IdentityMapError(f"{label} 缺少可核对标题")
        _validate_year(row["year"], label)
        _validate_tmdb(row["tmdb_id"], label)
        _validate_imdb(row["imdb_id"], label)

    movie_ids = [row["seed_id"] for row in movie_rows]
    duplicates = sorted(value for value, count in Counter(movie_ids).items() if count > 1)
    if duplicates:
        raise IdentityMapError(f"探索元数据 seed_id 重复：{duplicates}")
    unknown = sorted(set(movie_ids) - set(explore_ids))
    if unknown:
        raise IdentityMapError(f"探索元数据包含未知 seed_id：{unknown}")
    explore_by_id = {row["seed_id"]: row for row in explore_rows}
    for row in movie_rows:
        label = f"探索元数据 {row['seed_id']}"
        movie_year = _validate_year(row["seed_year"], label)
        seed_year = int(explore_by_id[row["seed_id"]]["year"])
        if movie_year != seed_year:
            raise IdentityMapError(
                f"{label} 的 seed_year 与探索种子不一致："
                f"采集={movie_year}，种子={seed_year}"
            )
        _validate_tmdb(row["tmdb_id"], label)
        _validate_imdb(row.get("imdb_id", ""), label)


def _metadata_by_explore(
    explore_rows: list[dict[str, str]],
    movie_rows: list[dict[str, str]],
) -> dict[str, dict[str, str]]:
    metadata = {
        row["seed_id"]: {
            "tmdb_id": row.get("tmdb_id", ""),
            "imdb_id": row.get("imdb_id", ""),
        }
        for row in explore_rows
    }
    for row in movie_rows:
        if row["match_status"] != "matched":
            continue
        target = metadata[row["seed_id"]]
        for field in ("tmdb_id", "imdb_id"):
            value = row.get(field, "")
            if target[field] and value and target[field] != value:
                raise IdentityMapError(
                    f"探索种子 {row['seed_id']} 与探索元数据的 {field} 冲突："
                    f"{target[field]} != {value}"
                )
            target[field] = target[field] or value
    return metadata


def _normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _digest(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_existing(
    rows: list[dict[str, str]],
    explore_ids: set[str],
    knowledge_ids: set[str],
) -> None:
    seen_explore: set[str] = set()
    seen_knowledge: set[str] = set()
    for row in rows:
        explore_id = row["explore_seed_id"]
        knowledge_id = row["knowledge_seed_id"]
        label = f"已有映射 {explore_id or '<空>'}"
        if not explore_id.isdigit() or int(explore_id) <= 0:
            raise IdentityMapError(f"{label} 的探索 ID 无效")
        if explore_id in seen_explore:
            raise IdentityMapError(f"已有映射中探索种子重复：{explore_id}")
        seen_explore.add(explore_id)
        if explore_id not in explore_ids:
            raise IdentityMapError(
                f"已有映射引用了不存在的探索种子 {explore_id}，停止合并以避免丢失记录"
            )
        if row["match_status"] not in STATUSES:
            raise IdentityMapError(f"{label} 的 match_status 无效")
        if not row["match_method"]:
            raise IdentityMapError(f"{label} 缺少 match_method")
        if row["match_status"] == "confirmed" and not knowledge_id:
            raise IdentityMapError(f"{label} confirmed 但缺少知识库 ID")
        if row["match_status"] == "unmatched" and knowledge_id:
            raise IdentityMapError(f"{label} unmatched 但包含知识库 ID")
        if knowledge_id:
            if not KNOWLEDGE_ID_RE.fullmatch(knowledge_id):
                raise IdentityMapError(f"{label} 的知识库 ID 格式无效")
            if knowledge_id in seen_knowledge:
                raise IdentityMapError(
                    f"已有映射中知识库身份重复：{knowledge_id}，停止合并"
                )
            seen_knowledge.add(knowledge_id)
        if row["match_method"].startswith("manual"):
            if knowledge_id and knowledge_id not in knowledge_ids:
                raise IdentityMapError(
                    f"人工映射 {explore_id} 引用了不存在的 {knowledge_id}，停止合并"
                )
        _validate_tmdb(row["tmdb_id"], label)
        _validate_imdb(row["imdb_id"], label)


def _relation(
    explore: dict[str, str],
    knowledge: dict[str, str],
    metadata: dict[str, str],
) -> dict[str, str | int] | None:
    explore_tmdb = metadata["tmdb_id"]
    explore_imdb = metadata["imdb_id"]
    knowledge_tmdb = knowledge["tmdb_id"]
    knowledge_imdb = knowledge["imdb_id"]

    tmdb_match = bool(
        explore_tmdb and knowledge_tmdb and explore_tmdb == knowledge_tmdb
    )
    imdb_match = bool(
        explore_imdb and knowledge_imdb and explore_imdb == knowledge_imdb
    )
    id_match = tmdb_match or imdb_match
    explore_title = _normalize_title(explore["title"])
    knowledge_titles = {
        _normalize_title(knowledge["original_title"]),
        _normalize_title(knowledge["title"]),
    }
    title_match = bool(explore_title and explore_title in knowledge_titles)
    if not id_match and not title_match:
        return None

    explore_year = int(explore["year"])
    knowledge_year = int(knowledge["year"])
    year_match = explore_year == knowledge_year
    conflicts = []
    if explore_tmdb and knowledge_tmdb and explore_tmdb != knowledge_tmdb:
        conflicts.append(
            f"TMDb ID 冲突：探索={explore_tmdb}，知识库={knowledge_tmdb}"
        )
    if explore_imdb and knowledge_imdb and explore_imdb != knowledge_imdb:
        conflicts.append(
            f"IMDb ID 冲突：探索={explore_imdb}，知识库={knowledge_imdb}"
        )

    if id_match and not conflicts and year_match:
        if tmdb_match and imdb_match:
            method = "tmdb_id+imdb_id"
            evidence = "TMDb ID、IMDb ID 均一致"
        elif tmdb_match:
            method = "tmdb_id"
            evidence = f"TMDb ID 一致（{explore_tmdb}）"
        else:
            method = "imdb_id"
            evidence = f"IMDb ID 一致（{explore_imdb}）"
        status = "confirmed"
        notes = [evidence, "年份一致"]
        if not title_match:
            notes.append("标题写法不同，以稳定 ID 关联")
        rank = -1
    elif conflicts:
        status = "needs_review"
        method = "id_conflict"
        notes = conflicts
        if not year_match:
            notes.append(f"年份冲突：探索={explore_year}，知识库={knowledge_year}")
        rank = 2
    elif id_match and not year_match:
        status = "needs_review"
        method = "id_year_conflict"
        notes = [
            "稳定 ID 一致但年份冲突："
            f"探索={explore_year}，知识库={knowledge_year}"
        ]
        rank = 1
    elif not year_match:
        status = "needs_review"
        method = "title_year_conflict"
        notes = [
            "同名候选但年份不同："
            f"探索={explore_year}，知识库={knowledge_year}"
        ]
        rank = 3
    else:
        status = "needs_review"
        method = "title_year"
        notes = ["仅标题和年份一致，缺少一致稳定 ID，需人工确认"]
        rank = 0

    return {
        "explore_seed_id": explore["seed_id"],
        "knowledge_seed_id": knowledge["seed_id"],
        "tmdb_id": explore_tmdb or knowledge_tmdb,
        "imdb_id": explore_imdb or knowledge_imdb,
        "match_method": method,
        "match_status": status,
        "notes": "；".join(notes),
        "rank": rank,
    }


def _blank_row(
    explore: dict[str, str],
    metadata: dict[str, str],
    method: str,
    status: str,
    notes: str,
) -> dict[str, str]:
    return {
        "explore_seed_id": explore["seed_id"],
        "knowledge_seed_id": "",
        "tmdb_id": metadata["tmdb_id"],
        "imdb_id": metadata["imdb_id"],
        "match_method": method,
        "match_status": status,
        "notes": notes,
    }


def _public_row(relation: dict[str, str | int]) -> dict[str, str]:
    return {field: str(relation[field]) for field in FIELDNAMES}


def _build_rows(
    explore_rows: list[dict[str, str]],
    knowledge_rows: list[dict[str, str]],
    movie_rows: list[dict[str, str]],
    existing_rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[str]]:
    metadata = _metadata_by_explore(explore_rows, movie_rows)
    manual_rows = {
        row["explore_seed_id"]: row
        for row in existing_rows
        if row["match_method"].startswith("manual")
    }
    manual_knowledge_ids = {
        row["knowledge_seed_id"]
        for row in manual_rows.values()
        if row["knowledge_seed_id"]
    }

    relations: dict[str, list[dict[str, str | int]]] = {}
    for explore in explore_rows:
        candidates = []
        for knowledge in knowledge_rows:
            relation = _relation(
                explore, knowledge, metadata[explore["seed_id"]]
            )
            if relation is not None:
                candidates.append(relation)
        relations[explore["seed_id"]] = candidates

    confirmed_counts = Counter(
        str(candidate["knowledge_seed_id"])
        for candidates in relations.values()
        for candidate in candidates
        if candidate["match_status"] == "confirmed"
    )
    confirmed_rows: dict[str, dict[str, str | int]] = {}
    for explore in explore_rows:
        explore_id = explore["seed_id"]
        if explore_id in manual_rows:
            continue
        candidates = [
            candidate
            for candidate in relations[explore_id]
            if candidate["match_status"] == "confirmed"
        ]
        if len(candidates) == 1:
            knowledge_id = str(candidates[0]["knowledge_seed_id"])
            if (
                confirmed_counts[knowledge_id] == 1
                and knowledge_id not in manual_knowledge_ids
            ):
                confirmed_rows[explore_id] = candidates[0]

    blocked_knowledge_ids = manual_knowledge_ids | {
        str(row["knowledge_seed_id"]) for row in confirmed_rows.values()
    }
    output: dict[str, dict[str, str]] = {}
    for explore in sorted(explore_rows, key=lambda row: int(row["seed_id"])):
        explore_id = explore["seed_id"]
        if explore_id in manual_rows:
            output[explore_id] = dict(manual_rows[explore_id])
            continue
        if explore_id in confirmed_rows:
            output[explore_id] = _public_row(confirmed_rows[explore_id])
            continue

        candidates = relations[explore_id]
        available = [
            candidate
            for candidate in candidates
            if candidate["knowledge_seed_id"] not in blocked_knowledge_ids
        ]
        blocked = [
            candidate
            for candidate in candidates
            if candidate["knowledge_seed_id"] in blocked_knowledge_ids
        ]
        if not candidates:
            output[explore_id] = _blank_row(
                explore,
                metadata[explore_id],
                "none",
                "unmatched",
                "未找到一致稳定 ID 或同名候选，需补充元数据或人工复核",
            )
            continue
        if not available:
            blocked_ids = sorted(
                {str(candidate["knowledge_seed_id"]) for candidate in blocked}
            )
            output[explore_id] = _blank_row(
                explore,
                metadata[explore_id],
                "duplicate_mapping",
                "needs_review",
                f"候选知识库身份已被其他映射保留：{'|'.join(blocked_ids)}，需人工复核",
            )
            continue

        confirmed_candidates = [
            candidate for candidate in available
            if candidate["match_status"] == "confirmed"
        ]
        if confirmed_candidates:
            candidate_ids = sorted(
                {str(candidate["knowledge_seed_id"]) for candidate in confirmed_candidates}
            )
            output[explore_id] = _blank_row(
                explore,
                metadata[explore_id],
                "duplicate_mapping",
                "needs_review",
                f"稳定 ID 对应多个或重复身份：{'|'.join(candidate_ids)}，未自动确认",
            )
            continue

        best_rank = min(int(candidate["rank"]) for candidate in available)
        best = [
            candidate for candidate in available
            if int(candidate["rank"]) == best_rank
        ]
        if len(best) != 1:
            candidate_ids = sorted(
                {str(candidate["knowledge_seed_id"]) for candidate in best}
            )
            output[explore_id] = _blank_row(
                explore,
                metadata[explore_id],
                "ambiguous_match",
                "needs_review",
                f"存在多个同级候选：{'|'.join(candidate_ids)}，未自动选择",
            )
            continue
        row = _public_row(best[0])
        if blocked:
            blocked_ids = sorted(
                {str(candidate["knowledge_seed_id"]) for candidate in blocked}
            )
            row["notes"] += f"；另有候选身份已保留：{'|'.join(blocked_ids)}"
        output[explore_id] = row

    # 非 confirmed 候选也必须保持一对一；无法安全选择时不保留候选 ID。
    knowledge_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in output.values():
        if row["match_status"] == "needs_review" and row["knowledge_seed_id"]:
            knowledge_groups[row["knowledge_seed_id"]].append(row)
    for knowledge_id, rows in knowledge_groups.items():
        if len(rows) <= 1:
            continue
        for row in rows:
            row["knowledge_seed_id"] = ""
            row["match_method"] = "duplicate_mapping"
            row["notes"] += f"；多个探索种子竞争知识库候选 {knowledge_id}，未自动分配"

    rows = [output[row["seed_id"]] for row in sorted(
        explore_rows, key=lambda item: int(item["seed_id"])
    )]
    anomalies = [
        f"探索种子 {row['explore_seed_id']}：{row['match_status']}/"
        f"{row['match_method']}；{row['notes']}"
        for row in rows
        if row["match_status"] != "confirmed"
    ]
    for explore_id, manual in manual_rows.items():
        conflicting = [
            str(candidate["knowledge_seed_id"])
            for candidate in relations[explore_id]
            if candidate["match_status"] == "confirmed"
            and candidate["knowledge_seed_id"] != manual["knowledge_seed_id"]
        ]
        if conflicting:
            anomalies.append(
                f"探索种子 {explore_id}：人工映射 {manual['knowledge_seed_id']} "
                f"与自动稳定 ID 候选 {'|'.join(sorted(conflicting))} 不同；"
                "已保留人工记录，需复核"
            )
    return rows, anomalies


def _validate_output(
    rows: list[dict[str, str]],
    explore_ids: set[str],
    knowledge_ids: set[str],
) -> None:
    actual_explore = [row["explore_seed_id"] for row in rows]
    if len(actual_explore) != len(set(actual_explore)):
        raise IdentityMapError("输出中探索种子存在重复映射")
    if set(actual_explore) != explore_ids:
        raise IdentityMapError("输出未完整且仅覆盖当前探索种子")

    seen_knowledge: set[str] = set()
    for row in rows:
        label = f"输出映射 {row['explore_seed_id']}"
        knowledge_id = row["knowledge_seed_id"]
        if row["match_status"] not in STATUSES:
            raise IdentityMapError(f"{label} 状态无效")
        if row["match_status"] == "confirmed":
            if not knowledge_id:
                raise IdentityMapError(f"{label} confirmed 但知识库 ID 为空")
            if row["match_method"] not in {
                "tmdb_id", "imdb_id", "tmdb_id+imdb_id"
            } and not row["match_method"].startswith("manual"):
                raise IdentityMapError(f"{label} 的确认方式无效")
        if row["match_status"] == "unmatched" and knowledge_id:
            raise IdentityMapError(f"{label} unmatched 但知识库 ID 非空")
        if knowledge_id:
            if knowledge_id not in knowledge_ids:
                raise IdentityMapError(f"{label} 引用了未知知识库身份 {knowledge_id}")
            if knowledge_id in seen_knowledge:
                raise IdentityMapError(f"输出中知识库身份重复：{knowledge_id}")
            seen_knowledge.add(knowledge_id)
        _validate_tmdb(row["tmdb_id"], label)
        _validate_imdb(row["imdb_id"], label)


def _fsync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write_atomic(
    output_path: Path,
    rows: list[dict[str, str]],
    explore_ids: set[str],
    knowledge_ids: set[str],
    expected_digest: str | None,
) -> None:
    if not output_path.parent.is_dir():
        raise IdentityMapError(f"输出目录不存在：{output_path.parent}")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(
            descriptor, "w", encoding="utf-8-sig", newline=""
        ) as handle:
            writer = csv.DictWriter(
                handle, fieldnames=FIELDNAMES, lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())

        temporary_rows = _read_csv(temporary_path, FIELDNAMES)
        _validate_output(temporary_rows, explore_ids, knowledge_ids)
        if temporary_rows != rows:
            raise IdentityMapError("临时文件回读结果与已验证数据不一致")
        if _digest(output_path) != expected_digest:
            raise IdentityMapError(
                "映射文件在本次生成期间被外部修改，已停止写入以避免覆盖人工记录"
            )
        os.replace(temporary_path, output_path)
        _fsync_directory(output_path.parent)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _confirmed_differences(
    existing_rows: list[dict[str, str]],
    new_rows: list[dict[str, str]],
) -> list[str]:
    """报告已有 confirmed 的关键字段变化，不比较可再生的说明文本。"""
    new_by_id = {row["explore_seed_id"]: row for row in new_rows}
    labels = {
        "knowledge_seed_id": "知识库 ID",
        "tmdb_id": "TMDb ID",
        "imdb_id": "IMDb ID",
        "match_status": "状态",
    }
    differences = []
    for old in existing_rows:
        if old["match_status"] != "confirmed":
            continue
        explore_id = old["explore_seed_id"]
        new = new_by_id.get(explore_id)
        if new is None:
            differences.append(f"探索种子 {explore_id}：新结果缺少该 confirmed 记录")
            continue
        changes = [
            f"{labels[field]}={old[field] or '<空>'} -> {new[field] or '<空>'}"
            for field in labels
            if old[field] != new[field]
        ]
        if changes:
            differences.append(f"探索种子 {explore_id}：" + "；".join(changes))
    return differences


def generate_identity_map(
    explore_path: Path,
    knowledge_path: Path,
    explore_movies_path: Path,
    output_path: Path,
    *,
    write: bool = False,
) -> tuple[list[dict[str, str]], list[str]]:
    """读取、验证并合并映射；write=False 时不创建或修改任何文件。"""
    paths = [Path(path) for path in (
        explore_path, knowledge_path, explore_movies_path, output_path
    )]
    explore_path, knowledge_path, explore_movies_path, output_path = paths
    if output_path.resolve() in {
        explore_path.resolve(), knowledge_path.resolve(), explore_movies_path.resolve()
    }:
        raise IdentityMapError("输出路径不得覆盖任何输入 CSV")

    explore_rows = _read_csv(explore_path, ["seed_id", "title", "year"])
    knowledge_rows = _read_csv(
        knowledge_path,
        ["seed_id", "title", "original_title", "year", "tmdb_id", "imdb_id"],
    )
    movie_rows = _read_csv(
        explore_movies_path,
        ["seed_id", "seed_title", "seed_year", "match_status", "tmdb_id"],
    )
    _validate_inputs(explore_rows, knowledge_rows, movie_rows)

    expected_digest = _digest(output_path)
    existing_rows = (
        _read_csv(output_path, FIELDNAMES) if output_path.exists() else []
    )
    explore_ids = {row["seed_id"] for row in explore_rows}
    knowledge_ids = {row["seed_id"] for row in knowledge_rows}
    _validate_existing(existing_rows, explore_ids, knowledge_ids)

    rows, anomalies = _build_rows(
        explore_rows, knowledge_rows, movie_rows, existing_rows
    )
    _validate_output(rows, explore_ids, knowledge_ids)
    confirmed_differences = _confirmed_differences(existing_rows, rows)
    anomalies.extend(
        f"confirmed 差异：{difference}" for difference in confirmed_differences
    )
    if write and confirmed_differences:
        report = "\n".join(f"- {item}" for item in confirmed_differences)
        raise IdentityMapError(
            "检测到未经人工确认的 confirmed 关键关联变化，已阻止覆盖。\n"
            f"差异报告：\n{report}\n"
            "如已人工复核，请先显式将对应记录标记为 manual 并记录复核说明。"
        )
    if write:
        _write_atomic(
            output_path, rows, explore_ids, knowledge_ids, expected_digest
        )
    return rows, anomalies


def _print_report(
    rows: list[dict[str, str]], anomalies: list[str], written: bool
) -> None:
    counts = Counter(row["match_status"] for row in rows)
    print(
        "映射统计："
        f"confirmed={counts['confirmed']}，"
        f"needs_review={counts['needs_review']}，"
        f"unmatched={counts['unmatched']}"
    )
    print(f"异常及待复核记录：{len(anomalies)}")
    for anomaly in anomalies:
        print(f"- {anomaly}")
    if not anomalies:
        print("- 无")
    print("已安全写入映射文件。" if written else "只读检查模式：未写入文件。")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--explore", type=Path, default=DEFAULT_EXPLORE)
    parser.add_argument("--knowledge", type=Path, default=DEFAULT_KNOWLEDGE)
    parser.add_argument(
        "--explore-movies", type=Path, default=DEFAULT_EXPLORE_MOVIES
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check", action="store_true", help="只验证并输出统计，不写入映射文件"
    )
    args = parser.parse_args()
    try:
        rows, anomalies = generate_identity_map(
            args.explore,
            args.knowledge,
            args.explore_movies,
            args.output,
            write=not args.check,
        )
    except (IdentityMapError, OSError) as exc:
        print(f"错误：{exc}")
        return 1
    _print_report(rows, anomalies, written=not args.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
