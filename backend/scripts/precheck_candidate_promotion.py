"""候选电影正式入库 dry-run 预检（只读）。

    python scripts/precheck_candidate_promotion.py
    python scripts/precheck_candidate_promotion.py --report <路径>

预检只回答“是否满足技术入库条件”，不执行任何写入，也不替代人工批准。
没有 human_decision=approve 时，可入库数量恒为 0。
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts.build_candidate_review_packets import (  # noqa: E402
    DEFAULT_CANDIDATES,
    DEFAULT_CRITERIA,
    DEFAULT_IDENTITY,
    DEFAULT_PACKETS,
    DEFAULT_REVIEW,
    DEFAULT_SOURCES,
    HUMAN_DECISIONS,
    HUMAN_FIELDS,
    PACKET_FIELDS,
    PacketWriteError,
    build_from_files,
    load_packet_rows,
)
from scripts.validate_candidate_identity import IDENTITY_FIELDS  # noqa: E402
from scripts.validate_candidate_sources import (  # noqa: E402
    REVIEW_FIELDS,
    SOURCE_FIELDS,
)
from scripts.validate_cult_candidates import (  # noqa: E402
    CANDIDATE_FIELDS,
    _normalize_title,
    _read_csv,
    _valid_url,
    _valid_year,
)

DEFAULT_KNOWLEDGE = BACKEND_DIR / "data" / "knowledge" / "cult_seed.csv"

FORBIDDEN_REVIEWERS = {"ai", "system", "system-backfill", "ai-draft"}
APPROVE_TIERS = {"T1", "T2"}
REVIEW_STATUSES = {"pending_human_review", "needs_more_evidence", "not_recommended"}
EVIDENCE_QUALITIES = {"strong", "moderate", "weak", "insufficient"}
TMDB_ID_RE = re.compile(r"\d+")
IMDB_ID_RE = re.compile(r"tt\d{7,9}")

CHECK_CODES = [
    "human_approval",
    "human_audit",
    "identity",
    "identity_conflict",
    "evidence_rules",
    "duplicate_existing",
    "traceability",
    "field_compatibility",
]


@dataclass
class CheckResult:
    code: str
    ok: bool
    message: str


@dataclass
class CandidatePrecheck:
    candidate_id: str
    title: str
    review_group: str
    human_decision: str
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(check.ok for check in self.checks)

    @property
    def blocked_reasons(self) -> list[str]:
        return [f"{check.code}: {check.message}" for check in self.checks if not check.ok]


@dataclass
class PromotionReport:
    candidates: list[CandidatePrecheck] = field(default_factory=list)
    groups: dict[str, int] = field(default_factory=dict)
    decisions: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(self.candidates)

    @property
    def passed(self) -> int:
        return sum(candidate.passed for candidate in self.candidates)

    @property
    def approved(self) -> int:
        return sum(candidate.human_decision == "approve" for candidate in self.candidates)


def _codes(value: str) -> list[str]:
    return [code for code in value.split("|") if code]


def _valid_timestamp(value: str) -> bool:
    if not value:
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _check_decision(packet: dict[str, str]) -> CheckResult:
    decision = packet.get("human_decision", "")
    if decision != "approve":
        detail = decision or "未填写"
        return CheckResult(
            "human_approval", False, f"human_decision={detail}，未获人工批准"
        )
    return CheckResult("human_approval", True, "human_decision=approve")


def _check_audit(packet: dict[str, str]) -> CheckResult:
    reviewer = packet.get("human_reviewer", "").strip()
    reviewed_at = packet.get("human_reviewed_at", "").strip()
    reason = packet.get("human_review_reason", "").strip()
    approved = set(_codes(packet.get("human_approved_criteria", "")))
    supported = set(_codes(packet.get("supported_criteria", "")))
    problems: list[str] = []
    if not reviewer:
        problems.append("缺少审核人")
    elif reviewer.lower() in FORBIDDEN_REVIEWERS or "ai" == reviewer.lower():
        problems.append("审核人不能是 AI/系统占位名")
    if not reviewed_at:
        problems.append("缺少审核日期")
    elif not _valid_timestamp(reviewed_at):
        problems.append("审核日期不是合法的 ISO 8601 时间")
    if not reason:
        problems.append("缺少审核理由")
    if not approved:
        problems.append("缺少被采纳的 C1–C8 标准")
    elif len(approved) < 2:
        problems.append("批准至少需要采纳 2 项 Cult 标准")
    elif approved - supported:
        problems.append(f"采纳了未获支持的标准：{sorted(approved - supported)}")
    if problems:
        return CheckResult("human_audit", False, "；".join(problems))
    return CheckResult("human_audit", True, "审核人、日期、理由与采纳标准完整")


def _check_identity(packet: dict[str, str]) -> CheckResult:
    status = packet.get("identity_status", "")
    if status != "confirmed":
        return CheckResult("identity", False, f"身份状态为 {status or '空'}，未确认")
    return CheckResult("identity", True, "身份已确认")


def _check_identity_conflict(
    packet: dict[str, str],
    identity_rows: list[dict[str, str]],
) -> CheckResult:
    candidate_id = packet["candidate_id"]
    tmdb_id = packet.get("tmdb_id", "")
    imdb_id = packet.get("imdb_id", "")
    problems: list[str] = []
    if not TMDB_ID_RE.fullmatch(tmdb_id):
        problems.append("TMDb ID 缺失或格式非法")
    if not IMDB_ID_RE.fullmatch(imdb_id):
        problems.append("IMDb ID 缺失或格式非法")
    for row in identity_rows:
        if row["candidate_id"] == candidate_id:
            continue
        if tmdb_id and row.get("tmdb_id") == tmdb_id:
            problems.append(f"TMDb ID {tmdb_id} 与 {row['candidate_id']} 重复")
        if imdb_id and row.get("imdb_id") == imdb_id:
            problems.append(f"IMDb ID {imdb_id} 与 {row['candidate_id']} 重复")
    if packet.get("identity_status") in {"conflict", "duplicate_existing"}:
        problems.append(f"身份状态为 {packet['identity_status']}")
    if problems:
        return CheckResult("identity_conflict", False, "；".join(problems))
    return CheckResult("identity_conflict", True, "TMDb/IMDb 标识无已知冲突")


def _check_evidence_rules(
    packet: dict[str, str],
    source_rows: list[dict[str, str]],
    criteria_codes: set[str],
) -> CheckResult:
    candidate_id = packet["candidate_id"]
    problems: list[str] = []
    code_set = set(_codes(packet.get("supported_criteria", "")))
    if not code_set:
        problems.append("没有任何受支持的标准")
    elif len(code_set) < 2:
        problems.append("既有审核规则要求至少 2 项受支持的标准")
    unknown = sorted(code_set - criteria_codes)
    if unknown:
        problems.append(f"未知标准代码：{unknown}")
    if packet.get("evidence_quality") not in {"strong", "moderate"}:
        problems.append(f"证据质量为 {packet.get('evidence_quality') or '空'}")
    if packet.get("second_source_status") != "verified":
        problems.append(f"第二来源状态为 {packet.get('second_source_status') or '空'}")

    candidate_sources = [row for row in source_rows if row["candidate_id"] == candidate_id]
    primary = [row for row in candidate_sources if row.get("source_role") == "primary"]
    second = [row for row in candidate_sources if row.get("source_role") == "second"]
    if not primary:
        problems.append("缺少第一来源记录")
    elif primary[0].get("reliability_tier") not in APPROVE_TIERS:
        problems.append("第一来源未达到 T1/T2")
    if not [row for row in second if row.get("verification_status") == "verified"]:
        problems.append("没有已核验的第二来源记录")
    for code in code_set:
        supported_rows = [
            row
            for row in candidate_sources
            if row.get("verification_status") == "verified"
            and row.get("reliability_tier") in APPROVE_TIERS
            and code in _codes(row.get("supported_criteria", ""))
        ]
        if not supported_rows:
            problems.append(f"{code} 没有 T1/T2 可核验来源")
    if problems:
        return CheckResult("evidence_rules", False, "；".join(problems))
    return CheckResult("evidence_rules", True, "来源与标准证据满足既有审核规则")


def _check_duplicate(
    packet: dict[str, str],
    knowledge_rows: list[dict[str, str]],
) -> CheckResult:
    problems: list[str] = []
    if packet.get("identity_status") == "duplicate_existing":
        problems.append("身份状态标记为 duplicate_existing")
    tmdb_id = packet.get("tmdb_id", "")
    imdb_id = packet.get("imdb_id", "")
    title_key = (_normalize_title(packet.get("title", "")), packet.get("year", ""))
    for row in knowledge_rows:
        if tmdb_id and row.get("tmdb_id") == tmdb_id:
            problems.append(f"TMDb ID 与正式库 {row['seed_id']} 重复")
        if imdb_id and row.get("imdb_id") == imdb_id:
            problems.append(f"IMDb ID 与正式库 {row['seed_id']} 重复")
        if title_key[0] and (
            _normalize_title(row.get("title", "")),
            row.get("year", ""),
        ) == title_key:
            problems.append(f"片名与年份与正式库 {row['seed_id']} 重复")
        if title_key[0] and _normalize_title(
            row.get("original_title", "")
        ) == title_key[0] and row.get("year", "") == title_key[1]:
            problems.append(f"原始片名与年份与正式库 {row['seed_id']} 重复")
    if problems:
        return CheckResult("duplicate_existing", False, "；".join(problems))
    return CheckResult("duplicate_existing", True, "与正式知识库无重复")


def _check_traceability(
    packet: dict[str, str],
    source_rows: list[dict[str, str]],
) -> CheckResult:
    candidate_id = packet["candidate_id"]
    problems: list[str] = []
    candidate_sources = [row for row in source_rows if row["candidate_id"] == candidate_id]
    if not candidate_sources:
        problems.append("没有任何来源记录")
    for row in candidate_sources:
        if not _valid_url(row.get("source_url", "")):
            problems.append(f"{row.get('source_id', '')} 来源 URL 无效")
        if not row.get("locator", ""):
            problems.append(f"{row.get('source_id', '')} 缺少定位信息")
    for code in _codes(packet.get("supported_criteria", "")):
        traceable = [
            row
            for row in candidate_sources
            if code in _codes(row.get("supported_criteria", ""))
            and _valid_url(row.get("source_url", ""))
        ]
        if not traceable:
            problems.append(f"{code} 无法追溯到具体来源")
    if not packet.get("evidence_summary", ""):
        problems.append("缺少证据摘要")
    if not _valid_url(packet.get("primary_source", "").split("｜")[-1]):
        problems.append("primary_source 缺少可追溯 URL")
    if problems:
        return CheckResult("traceability", False, "；".join(problems))
    return CheckResult("traceability", True, "来源与证据可追溯")


def _check_fields(packet: dict[str, str]) -> CheckResult:
    problems: list[str] = []
    missing = [name for name in PACKET_FIELDS if name not in packet]
    if missing:
        problems.append(f"资料包缺少字段：{missing}")
    for name in (
        "title",
        "original_title",
        "year",
        "tmdb_id",
        "imdb_id",
        "supported_criteria",
        "current_review_status",
    ):
        if not packet.get(name, ""):
            problems.append(f"{name} 为空")
    if packet.get("year") and not _valid_year(packet["year"]):
        problems.append("year 非法")
    if packet.get("current_review_status") not in REVIEW_STATUSES:
        problems.append(f"review_status 非法：{packet.get('current_review_status')}")
    if packet.get("human_decision", "") not in HUMAN_DECISIONS:
        problems.append(f"human_decision 非法：{packet.get('human_decision')}")
    if packet.get("evidence_quality") not in EVIDENCE_QUALITIES:
        problems.append(f"evidence_quality 非法：{packet.get('evidence_quality')}")
    if problems:
        return CheckResult("field_compatibility", False, "；".join(problems))
    return CheckResult("field_compatibility", True, "字段结构可映射到正式知识库")


def precheck_candidates(
    packets: list[dict[str, str]],
    source_rows: list[dict[str, str]],
    identity_rows: list[dict[str, str]],
    knowledge_rows: list[dict[str, str]],
    criteria_rows: list[dict[str, str]],
) -> PromotionReport:
    report = PromotionReport()
    criteria_codes = {row["criterion_code"] for row in criteria_rows}
    for packet in packets:
        report.groups[packet.get("review_group", "")] = (
            report.groups.get(packet.get("review_group", ""), 0) + 1
        )
        decision = packet.get("human_decision", "") or "未填写"
        report.decisions[decision] = report.decisions.get(decision, 0) + 1
        result = CandidatePrecheck(
            candidate_id=packet["candidate_id"],
            title=packet.get("title", ""),
            review_group=packet.get("review_group", ""),
            human_decision=packet.get("human_decision", ""),
        )
        result.checks = [
            _check_decision(packet),
            _check_audit(packet),
            _check_identity(packet),
            _check_identity_conflict(packet, identity_rows),
            _check_evidence_rules(packet, source_rows, criteria_codes),
            _check_duplicate(packet, knowledge_rows),
            _check_traceability(packet, source_rows),
            _check_fields(packet),
        ]
        report.candidates.append(result)
    return report


def build_cb01_018_note(
    packets: list[dict[str, str]],
    identity_rows: list[dict[str, str]],
) -> list[str]:
    packet = next((row for row in packets if row["candidate_id"] == "CB01-018"), None)
    identity = next(
        (row for row in identity_rows if row["candidate_id"] == "CB01-018"), None
    )
    if packet is None or identity is None:
        return ["未找到 CB01-018 的候选或身份记录。"]
    return [
        f"- 标题：{packet.get('title', '')}（{packet.get('original_title', '')}）",
        f"- 候选年份（保留，不覆盖）：{packet.get('year', '')}",
        f"- TMDb ID：{identity.get('tmdb_id', '') or '未记录'}；"
        f"TMDb 年份字段：{identity.get('tmdb_year', '') or '未记录'}；"
        f"TMDb release_date：{identity.get('tmdb_release_date', '') or '未记录'}",
        f"- IMDb ID：{identity.get('imdb_id', '') or '未记录'}",
        f"- 身份状态（保留）：{identity.get('match_status', '')}",
        "- 口径区分：",
        "  - 1967：候选采用的年份，对应影片在 Acapulco 电影节首映的年份；"
        "项目既有身份记录如此标注，本阶段未再新增外部核实。",
        "  - 1970：TMDb 的 year 字段，属于数据库年份口径，不等同首映日期。",
        "  - 1972-06-08（MX）：TMDb 记录的墨西哥上映日期，属于地区发行日期。",
        "  - IMDb：本阶段仅核验 ID 对应关系（tt0061643），未采用其年份字段。",
        "- 人工复核建议：确认“1967 首映 → 后续地区公映”的年份口径，"
        "并核对 TMDb year=1970 的字段含义；确认前不得改为 confirmed，不得进入 A 类。",
        "- 外部核实限制：TMDb API 域名在本机 DNS 不可达（阶段 3.4.5 已记录），"
        "本阶段未新增外部访问，未编造任何日期。",
    ]


def prepare_precheck_packets(
    candidates_path: Path,
    sources_path: Path,
    review_path: Path,
    identity_path: Path,
    packets_path: Path,
) -> tuple[list[dict[str, str]], list[str]]:
    """按源 CSV 重新计算派生字段，并按 candidate_id 继承已有资料包的人工字段。

    返回 (最新资料包, 派生字段已过期的 candidate_id 列表)。绝不写入磁盘。
    """
    existing = load_packet_rows(packets_path)
    fresh = build_from_files(
        candidates_path,
        sources_path,
        review_path,
        identity_path,
        existing_rows=existing or None,
    )
    if not existing:
        return fresh, []
    old_by_id = {row["candidate_id"]: row for row in existing}
    stale = [
        row["candidate_id"]
        for row in fresh
        if row["candidate_id"] in old_by_id
        and any(
            row.get(name, "") != old_by_id[row["candidate_id"]].get(name, "")
            for name in PACKET_FIELDS
            if name not in HUMAN_FIELDS
        )
    ]
    return fresh, stale


def render_report(
    report: PromotionReport,
    packets: list[dict[str, str]],
    identity_rows: list[dict[str, str]],
) -> str:
    lines = [
        "# CULTScope 批次 CB01 正式入库 dry-run 预检报告",
        "",
        "本报告为只读预检结果，不执行任何入库写操作，也不替代人工批准。",
        "",
        "## 汇总",
        "",
        f"- 候选总数：{report.total}",
        "- 审核分组："
        + "、".join(f"{group}={count}" for group, count in sorted(report.groups.items())),
        "- 人工决定："
        + "、".join(f"{key}={value}" for key, value in sorted(report.decisions.items())),
        f"- 人工批准记录：{report.approved}",
        f"- 通过全部 8 项技术预检：{report.passed}",
        f"- 实际可入库数量：{report.passed}（未执行写操作）",
        "",
        "## 逐片预检",
        "",
        "| candidate_id | 标题 | 分组 | 人工决定 | 预检 | 阻塞项 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for candidate in report.candidates:
        status = "通过" if candidate.passed else "不通过"
        reasons = "<br>".join(candidate.blocked_reasons) or "-"
        decision = candidate.human_decision or "未填写"
        lines.append(
            f"| {candidate.candidate_id} | {candidate.title} | {candidate.review_group} "
            f"| {decision} | {status} | {reasons} |"
        )
    lines.extend(
        [
            "",
            "## CB01-018 Fando and Lis 年份复核说明",
            "",
            *build_cb01_018_note(packets, identity_rows),
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="候选电影正式入库 dry-run 预检")
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--identity", type=Path, default=DEFAULT_IDENTITY)
    parser.add_argument("--criteria", type=Path, default=DEFAULT_CRITERIA)
    parser.add_argument("--knowledge", type=Path, default=DEFAULT_KNOWLEDGE)
    parser.add_argument("--packets", type=Path, default=DEFAULT_PACKETS)
    parser.add_argument("--report", type=Path, default=None, help="可选：写出 Markdown 报告")
    args = parser.parse_args(argv)

    try:
        packets, stale_ids = prepare_precheck_packets(
            args.candidates,
            args.sources,
            args.review,
            args.identity,
            args.packets,
        )
    except PacketWriteError as error:
        print(f"拒绝预检：{error}")
        return 2
    if stale_ids:
        print(
            "警告：资料包存在过期派生字段，已按源 CSV 重新计算（不写盘）："
            + "、".join(stale_ids)
        )
        print("建议运行 build_candidate_review_packets.py --write 更新资料包")
    identity_rows = _read_csv(args.identity, IDENTITY_FIELDS)
    source_rows = _read_csv(args.sources, SOURCE_FIELDS)
    knowledge_rows = _read_csv(
        args.knowledge,
        ["seed_id", "title", "original_title", "year", "tmdb_id", "imdb_id"],
    )
    criteria_rows = _read_csv(args.criteria, ["criterion_code", "name_zh", "name_en"])

    report = precheck_candidates(
        packets, source_rows, identity_rows, knowledge_rows, criteria_rows
    )
    print(f"候选总数：{report.total}")
    print(
        "审核分组："
        + "、".join(f"{group}={count}" for group, count in sorted(report.groups.items()))
    )
    print(
        "人工决定："
        + "、".join(f"{key}={value}" for key, value in sorted(report.decisions.items()))
    )
    print(f"通过全部技术预检：{report.passed}")
    print(f"实际可入库数量：{report.passed}（本阶段未执行任何写操作）")
    for candidate in report.candidates:
        status = "PASS" if candidate.passed else "BLOCK"
        reasons = "；".join(candidate.blocked_reasons) or "-"
        print(
            f"[{status}] {candidate.candidate_id} {candidate.title} "
            f"({candidate.review_group}) {reasons}"
        )
    print("\nCB01-018 年份复核说明：")
    for line in build_cb01_018_note(packets, identity_rows):
        print(line)

    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            render_report(report, packets, identity_rows), encoding="utf-8"
        )
        print(f"\n预检报告已写入：{args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
