"""生成候选电影人工审核资料包（只读源数据，只写资料包 CSV）。

    python scripts/build_candidate_review_packets.py --check
    python scripts/build_candidate_review_packets.py --write

资料包一部候选一条记录，把身份、来源、Cult 标准证据与人工决定分成独立字段。
脚本不会填写任何 human_* 字段，也不会修改候选、来源、审核、身份或正式知识库文件。
重复执行产生完全相同的字节内容（幂等）。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import os
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts.validate_candidate_identity import IDENTITY_FIELDS  # noqa: E402
from scripts.validate_candidate_sources import (  # noqa: E402
    REVIEW_FIELDS,
    SOURCE_FIELDS,
)
from scripts.validate_cult_candidates import (  # noqa: E402
    CANDIDATE_FIELDS,
    _read_csv,
)

DEFAULT_CANDIDATES = BACKEND_DIR / "data" / "candidates" / "cult_candidates_batch01.csv"
DEFAULT_SOURCES = BACKEND_DIR / "data" / "candidates" / "cult_candidate_sources_batch01.csv"
DEFAULT_REVIEW = BACKEND_DIR / "data" / "candidates" / "cult_candidate_review_batch01.csv"
DEFAULT_IDENTITY = BACKEND_DIR / "data" / "candidates" / "cult_candidate_identity_batch01.csv"
DEFAULT_CRITERIA = BACKEND_DIR / "data" / "knowledge" / "cult_criteria.csv"
DEFAULT_PACKETS = BACKEND_DIR / "data" / "candidates" / "cult_candidate_review_packets_batch01.csv"

PACKET_FIELDS = [
    "candidate_id",
    "title",
    "original_title",
    "year",
    "review_group",
    "identity_status",
    "tmdb_id",
    "imdb_id",
    "primary_source",
    "second_source_status",
    "independent_source_count",
    "supported_criteria",
    "evidence_quality",
    "evidence_summary",
    "evidence_gaps",
    "current_review_status",
    "recommended_action",
    "human_decision",
    "human_reviewer",
    "human_reviewed_at",
    "human_review_reason",
    "human_approved_criteria",
]

REVIEW_GROUPS = {"A", "B", "C"}
HUMAN_DECISIONS = {"", "approve", "reject", "request_more_evidence", "defer"}
HUMAN_FIELDS = [
    "human_decision",
    "human_reviewer",
    "human_reviewed_at",
    "human_review_reason",
    "human_approved_criteria",
]
BINDING_FIELDS = ["title", "original_title", "year", "tmdb_id", "imdb_id"]


class PacketWriteError(RuntimeError):
    """拒绝写入资料包：人工字段可能丢失、被改写或错误关联。"""


def _codes(value: str) -> list[str]:
    return [code for code in value.split("|") if code]


def _join(parts: list[str]) -> str:
    return "；".join(part for part in parts if part)


def _primary_by_candidate(source_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    primary: dict[str, dict[str, str]] = {}
    for row in source_rows:
        if row.get("source_role") == "primary":
            primary[row["candidate_id"]] = row
    return primary


def _second_by_candidate(
    source_rows: list[dict[str, str]],
) -> dict[str, list[dict[str, str]]]:
    secondary: dict[str, list[dict[str, str]]] = {}
    for row in source_rows:
        if row.get("source_role") == "second":
            secondary.setdefault(row["candidate_id"], []).append(row)
    return secondary


def _count_independent(second_rows: list[dict[str, str]]) -> int:
    return sum(
        1
        for row in second_rows
        if row.get("independence_status") == "independent"
        and row.get("verification_status") == "verified"
    )


def _review_group(identity_status: str, review_status: str) -> str:
    if identity_status != "confirmed":
        return "B"
    if review_status == "needs_more_evidence":
        return "C"
    return "A"


def _recommended_action(
    identity_status: str,
    review_status: str,
    second_status: str,
) -> str:
    if identity_status != "confirmed":
        return "identity_review"
    if review_status == "needs_more_evidence" or second_status != "verified":
        return "collect_more_evidence"
    return "human_review"


def _primary_text(row: dict[str, str] | None) -> str:
    if row is None:
        return ""
    return f"{row.get('publisher', '')}｜{row.get('source_title', '')}｜{row.get('source_url', '')}"


def _evidence_summary(
    primary: dict[str, str] | None,
    second_rows: list[dict[str, str]],
    second_status: str,
) -> str:
    parts: list[str] = []
    if primary is not None:
        parts.append(
            f"第一来源（{primary.get('publisher', '')}）："
            f"{primary.get('evidence_summary', '')}"
        )
    for row in sorted(second_rows, key=lambda item: item.get("source_id", "")):
        parts.append(
            f"第二来源（{row.get('publisher', '')}，"
            f"{row.get('verification_status', '')}）："
            f"{row.get('evidence_summary', '')}"
        )
    if not second_rows:
        parts.append(f"第二来源：无来源记录（{second_status}）")
    return _join(parts)


def _evidence_gaps(
    identity_status: str,
    review_status: str,
    second_status: str,
    independent_count: int,
    second_rows: list[dict[str, str]],
    unsupported: str,
) -> str:
    parts: list[str] = []
    if unsupported:
        parts.append(f"未获来源支持的标准：{unsupported}")
    if second_status == "unavailable":
        parts.append("第二来源不可访问，缺少可读取的独立佐证")
    elif second_status == "not_found":
        parts.append("未找到独立第二来源")
    elif independent_count == 0 and second_rows:
        publishers = sorted(
            {row.get("publisher", "") for row in second_rows if row.get("publisher")}
        )
        parts.append(
            "第二来源与第一来源同属一个出版机构"
            f"（{('、'.join(publishers)) or '未记录'}），独立来源数为 0"
        )
    if review_status == "needs_more_evidence":
        parts.append("审核表判定证据不足，需补充后再审")
    if identity_status == "needs_review":
        parts.append("身份尚未确认，年份口径存在差异，需人工复核")
    if not parts:
        parts.append("无结构性证据缺口；仍须人工核对原始段落与定位")
    return _join(parts)


def build_packet_rows(
    candidate_rows: list[dict[str, str]],
    source_rows: list[dict[str, str]],
    review_rows: list[dict[str, str]],
    identity_rows: list[dict[str, str]],
    existing_rows: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """按候选顺序生成资料包行。

    未提供 existing_rows 时 human_* 字段一律留空（新建资料包）。
    提供已有资料包时按 candidate_id 原样继承人工字段，绝不清空或按行号错配。
    """
    reviews = {row["candidate_id"]: row for row in review_rows}
    identities = {row["candidate_id"]: row for row in identity_rows}
    primary_index = _primary_by_candidate(source_rows)
    second_index = _second_by_candidate(source_rows)

    packets: list[dict[str, str]] = []
    for candidate in candidate_rows:
        candidate_id = candidate["candidate_id"]
        review = reviews.get(candidate_id, {})
        identity = identities.get(candidate_id, {})
        second_rows = second_index.get(candidate_id, [])
        primary = primary_index.get(candidate_id)

        identity_status = identity.get("match_status", "")
        review_status = review.get("review_status", "")
        second_status = review.get("second_source_status", "")
        supported = review.get("supported_criteria", "")
        unsupported = review.get("unsupported_criteria", "")
        independent_count = _count_independent(second_rows)

        packets.append(
            {
                "candidate_id": candidate_id,
                "title": candidate.get("title", ""),
                "original_title": candidate.get("original_title", ""),
                "year": candidate.get("year", ""),
                "review_group": _review_group(identity_status, review_status),
                "identity_status": identity_status,
                "tmdb_id": identity.get("tmdb_id", ""),
                "imdb_id": identity.get("imdb_id", ""),
                "primary_source": _primary_text(primary),
                "second_source_status": second_status,
                "independent_source_count": str(independent_count),
                "supported_criteria": supported,
                "evidence_quality": review.get("evidence_quality", ""),
                "evidence_summary": _evidence_summary(
                    primary, second_rows, second_status
                ),
                "evidence_gaps": _evidence_gaps(
                    identity_status,
                    review_status,
                    second_status,
                    independent_count,
                    second_rows,
                    unsupported,
                ),
                "current_review_status": review_status,
                "recommended_action": _recommended_action(
                    identity_status, review_status, second_status
                ),
                "human_decision": "",
                "human_reviewer": "",
                "human_reviewed_at": "",
                "human_review_reason": "",
                "human_approved_criteria": "",
            }
        )
    if existing_rows:
        packets = merge_human_fields(packets, existing_rows)
    return packets


def merge_human_fields(
    rows: list[dict[str, str]],
    existing_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    """按 candidate_id 继承人工字段；任何可能丢失或错配的情况直接拒绝。"""
    existing: dict[str, dict[str, str]] = {}
    for old in existing_rows:
        candidate_id = old.get("candidate_id", "")
        if not candidate_id:
            raise PacketWriteError("已有资料包存在空 candidate_id，拒绝合并")
        if candidate_id in existing:
            raise PacketWriteError(
                f"已有资料包 candidate_id 重复：{candidate_id}，拒绝合并"
            )
        decision = old.get("human_decision", "")
        if decision not in HUMAN_DECISIONS:
            raise PacketWriteError(
                f"{candidate_id} 的 human_decision 非法：{decision!r}，拒绝合并"
            )
        existing[candidate_id] = old

    incoming = {row["candidate_id"] for row in rows}
    missing = sorted(set(existing) - incoming)
    if missing:
        raise PacketWriteError(
            "以下候选在重新生成结果中缺失，写入会丢失人工记录：" + "、".join(missing)
        )

    for row in rows:
        old = existing.get(row["candidate_id"])
        if old is None:
            continue
        has_human = any(old.get(name, "") for name in HUMAN_FIELDS)
        if has_human:
            changed = [
                f"{name}: {old.get(name, '')!r} → {row.get(name, '')!r}"
                for name in BINDING_FIELDS
                if old.get(name, "") != row.get(name, "")
            ]
            if changed:
                raise PacketWriteError(
                    f"{row['candidate_id']} 已有非空人工审核记录，"
                    "身份字段发生变化，拒绝静默更新；需人工复核字段差异："
                    + "；".join(changed)
                )
        for name in HUMAN_FIELDS:
            row[name] = old.get(name, "")
    return rows


def _render_csv(rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer, fieldnames=PACKET_FIELDS, lineterminator="\n", extrasaction="ignore"
    )
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_temp_packet(path: Path, expected_rows: list[dict[str, str]]) -> None:
    """回读临时文件，核对字段顺序、行数与人工审核信息。"""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            raise PacketWriteError("临时资料包为空，拒绝替换")
    if header != PACKET_FIELDS:
        raise PacketWriteError("临时资料包字段顺序不匹配，拒绝替换")

    actual = _read_csv(path, PACKET_FIELDS)
    if len(actual) != len(expected_rows):
        raise PacketWriteError(
            f"临时资料包行数 {len(actual)} 与预期 {len(expected_rows)} 不一致，拒绝替换"
        )
    expected_by_id = {row["candidate_id"]: row for row in expected_rows}
    if len(expected_by_id) != len(expected_rows):
        raise PacketWriteError("预期资料包存在重复 candidate_id，拒绝替换")
    for row in actual:
        expected = expected_by_id.get(row.get("candidate_id", ""))
        if expected is None:
            raise PacketWriteError(
                f"临时资料包出现未知候选 {row.get('candidate_id', '')}，拒绝替换"
            )
        for name in HUMAN_FIELDS:
            if row.get(name, "") != expected.get(name, ""):
                raise PacketWriteError(
                    f"{row['candidate_id']} 的 {name} 回读不一致，拒绝替换"
                )


def _atomic_replace(
    path: Path,
    content: bytes,
    expected_rows: list[dict[str, str]],
    original_hash: str | None,
) -> None:
    """同目录临时文件 + fsync + 回读校验 + SHA-256 并发检查 + os.replace。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle_fd, temp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    temp_path: Path | None = Path(temp_name)
    try:
        with os.fdopen(handle_fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _verify_temp_packet(temp_path, expected_rows)
        current_hash = _sha256(path) if path.is_file() else None
        if current_hash != original_hash:
            raise PacketWriteError(
                "目标资料包在读取后被其他进程修改，拒绝覆盖"
            )
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


def write_packets(path: Path, rows: list[dict[str, str]]) -> bool:
    """原子写入资料包；已有文件的人工字段按 candidate_id 原样保留。

    rows 必须是程序生成的行，human_* 必须为空。已有资料包存在人工记录时：
    - 内容完全一致则不动文件；
    - 派生字段变化时只更新派生字段，人工字段保持原值；
    - 人工已审核记录的身份字段变化、候选缺失、ID 重复、非法决定时抛
      PacketWriteError，绝不覆盖；
    - 写入使用同目录临时文件与 os.replace，任何异常都不会破坏原文件。
    返回是否发生写入。
    """
    for row in rows:
        filled = [name for name in HUMAN_FIELDS if row.get(name, "")]
        if filled:
            raise PacketWriteError(
                f"{row.get('candidate_id', '')} 的生成行包含人工字段 {filled}；"
                "程序不得自动填写或改写人工决定"
            )

    original_hash = _sha256(path) if path.is_file() else None
    existing = load_packet_rows(path)
    merged = merge_human_fields([dict(row) for row in rows], existing) if existing else rows
    if existing:
        existing_by_id = {row["candidate_id"]: row for row in existing}
        if len(existing_by_id) == len(merged) and all(
            existing_by_id.get(row["candidate_id"]) == row for row in merged
        ):
            return False
    content = _render_csv(merged)
    if original_hash is not None and path.read_bytes() == content:
        return False
    _atomic_replace(path, content, merged, original_hash)
    return True


def load_packet_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    return _read_csv(path, PACKET_FIELDS)


def inspect_human_records(path: Path) -> dict[str, object]:
    """只读列出已有资料包中的人工审核记录。"""
    rows = load_packet_rows(path)
    records = []
    errors: list[str] = []
    seen: set[str] = set()
    for row in rows:
        candidate_id = row.get("candidate_id", "")
        if candidate_id in seen:
            errors.append(f"candidate_id 重复：{candidate_id}")
        seen.add(candidate_id)
        if not any(row.get(name, "") for name in HUMAN_FIELDS):
            continue
        decision = row.get("human_decision", "")
        if decision not in HUMAN_DECISIONS:
            errors.append(f"{candidate_id} 的 human_decision 非法：{decision!r}")
        records.append(
            {
                "candidate_id": candidate_id,
                "title": row.get("title", ""),
                "human_decision": decision,
                "human_reviewer": row.get("human_reviewer", ""),
                "human_reviewed_at": row.get("human_reviewed_at", ""),
            }
        )
    return {"records": records, "errors": errors}


def summarize(packets: list[dict[str, str]]) -> dict[str, object]:
    groups = {group: 0 for group in sorted(REVIEW_GROUPS)}
    for packet in packets:
        groups[packet.get("review_group", "")] = (
            groups.get(packet.get("review_group", ""), 0) + 1
        )
    return {
        "total": len(packets),
        "groups": groups,
        "identity_pending": sum(
            packet.get("identity_status") != "confirmed" for packet in packets
        ),
        "evidence_pending": sum(
            packet.get("current_review_status") == "needs_more_evidence"
            for packet in packets
        ),
        "human_decisions": sum(bool(packet.get("human_decision")) for packet in packets),
    }


def build_from_files(
    candidates_path: Path,
    sources_path: Path,
    review_path: Path,
    identity_path: Path,
    existing_rows: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    return build_packet_rows(
        _read_csv(candidates_path, CANDIDATE_FIELDS),
        _read_csv(sources_path, SOURCE_FIELDS),
        _read_csv(review_path, REVIEW_FIELDS),
        _read_csv(identity_path, IDENTITY_FIELDS),
        existing_rows=existing_rows,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成候选电影人工审核资料包")
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--identity", type=Path, default=DEFAULT_IDENTITY)
    parser.add_argument("--packets", type=Path, default=DEFAULT_PACKETS)
    parser.add_argument("--write", action="store_true", help="写入资料包 CSV（默认只预览）")
    parser.add_argument("--check", action="store_true", help="只读检查人工记录与派生字段")
    args = parser.parse_args(argv)

    existing = load_packet_rows(args.packets)
    inspection = inspect_human_records(args.packets)
    if existing:
        print(f"已有资料包：{args.packets}")
        print(f"存在人工审核记录的候选：{len(inspection['records'])}")
        for record in inspection["records"]:
            print(
                f"  - {record['candidate_id']}｜{record['title']}｜"
                f"decision={record['human_decision'] or '未填写'}｜"
                f"reviewer={record['human_reviewer'] or '未填写'}｜"
                f"reviewed_at={record['human_reviewed_at'] or '未填写'}"
            )
        for error in inspection["errors"]:
            print(f"  ! {error}")

    try:
        packets = build_from_files(
            args.candidates,
            args.sources,
            args.review,
            args.identity,
            existing_rows=existing or None,
        )
    except PacketWriteError as error:
        print(f"拒绝生成：{error}")
        return 2

    summary = summarize(packets)
    print(f"资料包记录：{summary['total']}")
    print(
        "审核分组："
        + "、".join(f"{group}={count}" for group, count in summary["groups"].items())
    )
    print(f"身份待复核：{summary['identity_pending']}")
    print(f"证据待补充：{summary['evidence_pending']}")
    print(f"已填写人工决定：{summary['human_decisions']}（程序不填写任何 human_* 字段）")

    if existing:
        old_by_id = {row["candidate_id"]: row for row in existing}
        changed_ids = [
            fresh["candidate_id"]
            for fresh in packets
            if fresh["candidate_id"] in old_by_id
            and any(
                fresh.get(name, "") != old_by_id[fresh["candidate_id"]].get(name, "")
                for name in PACKET_FIELDS
                if name not in HUMAN_FIELDS
            )
        ]
        if changed_ids:
            print("派生字段将更新（人工字段按 candidate_id 保留）：" + "、".join(changed_ids))
        else:
            print("派生字段与现有资料包一致")

    if args.write and not args.check:
        try:
            changed = write_packets(args.packets, packets)
        except PacketWriteError as error:
            print(f"拒绝写入：{error}")
            return 2
        print(f"写入资料包：{'已更新' if changed else '内容一致，未改动'} → {args.packets}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
