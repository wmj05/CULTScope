"""候选来源交叉验证与人工审核准备的离线只读校验器。

不调用 TMDb，不写入知识库，不修改任何生产 CSV。
只校验暂存材料之间的一致性：

    python scripts/validate_candidate_sources.py --check

校验范围：
1. 每部候选恰好有一条 primary 来源，URL、标题与发布机构完整。
2. 第二来源不得与第一来源使用同一 URL；独立来源不得与第一来源同属一个出版机构。
3. 来源标记 verified 必须已记录 accessed_at 与证据摘要。
4. 标准代码必须存在于 cult_criteria.csv，且无证据时不得勾选。
5. 审核表不得出现 approved，缺少第二来源时必须保持 needs_more_evidence。
6. 第二来源状态必须与来源记录的实际 verification_status 一致：
   verified 需至少一条已核验记录，unavailable 不得含已核验记录，
   not_found 不得存在任何第二来源记录，unavailable 不计入已核验统计。
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts.validate_cult_candidates import (  # noqa: E402
    CANDIDATE_FIELDS,
    CANDIDATE_ID_RE,
    SOURCE_ID_RE,
    Issue,
    _read_csv,
    _valid_url,
    validate_candidate_rows,
)

DEFAULT_CANDIDATES = BACKEND_DIR / "data" / "candidates" / "cult_candidates_batch01.csv"
DEFAULT_SOURCES = BACKEND_DIR / "data" / "candidates" / "cult_candidate_sources_batch01.csv"
DEFAULT_REVIEW = BACKEND_DIR / "data" / "candidates" / "cult_candidate_review_batch01.csv"
DEFAULT_KNOWLEDGE = BACKEND_DIR / "data" / "knowledge" / "cult_seed.csv"
DEFAULT_CRITERIA = BACKEND_DIR / "data" / "knowledge" / "cult_criteria.csv"

SOURCE_FIELDS = [
    "candidate_id",
    "source_id",
    "source_role",
    "source_title",
    "publisher",
    "source_url",
    "publication_date",
    "accessed_at",
    "language",
    "reliability_tier",
    "evidence_summary",
    "locator",
    "supported_criteria",
    "evidence_directness",
    "independence_status",
    "verification_status",
    "notes",
]

REVIEW_FIELDS = [
    "candidate_id",
    "original_source_status",
    "second_source_status",
    "evidence_quality",
    "supported_criteria",
    "unsupported_criteria",
    "review_recommendation",
    "reviewer",
    "review_status",
    "notes",
]

SOURCE_ROLES = {"primary", "second"}
INDEPENDENCE_STATUSES = {"not_applicable", "independent", "same_publisher", "unverified"}
SOURCE_VERIFICATION_STATUSES = {"verified", "unavailable"}
DIRECTNESS = {"direct", "indirect", "none"}
SECOND_SOURCE_STATUSES = {"verified", "not_found", "unavailable"}
REVIEW_STATUSES = {"pending_human_review", "needs_more_evidence", "not_recommended"}
RECOMMENDATIONS = {"priority_review", "review_after_evidence", "not_recommended_yet"}
EVIDENCE_QUALITIES = {"strong", "moderate", "weak", "insufficient"}


@dataclass
class SourceReport:
    total_candidates: int = 0
    primary_rows: int = 0
    second_rows: int = 0
    second_verified: int = 0
    second_not_found: int = 0
    second_unavailable: int = 0
    independent_second: int = 0
    independent_publishers: int = 0
    independent_urls: int = 0
    criteria_supported: int = 0
    pending_human_review: int = 0
    needs_more_evidence: int = 0
    approved: int = 0
    criteria_distribution: dict[str, int] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def is_valid(self) -> bool:
        return not self.errors


def _codes(value: str) -> list[str]:
    return [code for code in value.split("|") if code]


def _add(
    issues: list[Issue], candidate_id: str, code: str, message: str, severity: str = "error"
) -> None:
    issues.append(Issue(severity, code, candidate_id, message))


def validate_source_rows(
    candidate_rows: list[dict[str, str]],
    source_rows: list[dict[str, str]],
    criteria_rows: list[dict[str, str]],
) -> SourceReport:
    report = SourceReport(total_candidates=len(candidate_rows))
    criteria_codes = {row["criterion_code"] for row in criteria_rows}
    candidate_ids = {row["candidate_id"] for row in candidate_rows}
    primary: dict[str, dict[str, str]] = {}
    secondary: dict[str, list[dict[str, str]]] = {}
    seen_pairs: set[tuple[str, str]] = set()

    for row in source_rows:
        candidate_id = row.get("candidate_id", "") or "<空>"
        role = row.get("source_role", "")
        if candidate_id not in candidate_ids:
            _add(report.issues, candidate_id, "unknown_candidate", "来源引用了不存在的候选")
        if role == "primary":
            report.primary_rows += 1
        elif role == "second":
            report.second_rows += 1
            secondary.setdefault(candidate_id, []).append(row)
        else:
            _add(report.issues, candidate_id, "source_role", "source_role 只能是 primary 或 second")

        if not SOURCE_ID_RE.fullmatch(row.get("source_id", "")):
            _add(report.issues, candidate_id, "source_id", "source_id 格式应为 CB01-S01")
        for field_name in ("source_title", "publisher", "accessed_at"):
            if not row.get(field_name, ""):
                _add(
                    report.issues, candidate_id, "source_required",
                    f"缺少字段：{field_name}",
                )
        if not _valid_url(row.get("source_url", "")):
            _add(report.issues, candidate_id, "url", "source_url 必须是有效 HTTP(S) URL")

        verification = row.get("verification_status", "")
        if verification not in SOURCE_VERIFICATION_STATUSES:
            _add(report.issues, candidate_id, "verification_status", "来源 verification_status 无效")
        if verification == "verified" and not row.get("evidence_summary", ""):
            _add(
                report.issues, candidate_id, "missing_evidence",
                "来源已标记 verified 但缺少证据摘要",
            )
        if verification == "verified" and not row.get("accessed_at", ""):
            _add(
                report.issues, candidate_id, "missing_access",
                "来源已标记 verified 但缺少访问日期",
            )

        independence = row.get("independence_status", "")
        if independence not in INDEPENDENCE_STATUSES:
            _add(report.issues, candidate_id, "independence", "independence_status 无效")
        if role == "primary" and independence != "not_applicable":
            _add(report.issues, candidate_id, "independence", "primary 来源的 independence_status 应为 not_applicable")
        if role == "second" and independence == "not_applicable":
            _add(report.issues, candidate_id, "independence", "second 来源必须标注独立性")

        directness = row.get("evidence_directness", "")
        if directness not in DIRECTNESS:
            _add(report.issues, candidate_id, "directness", "evidence_directness 无效")

        codes = _codes(row.get("supported_criteria", ""))
        unknown = sorted(set(codes) - criteria_codes)
        if unknown:
            _add(report.issues, candidate_id, "criteria", f"未知 Cult 标准代码：{unknown}")
        if codes and directness == "none":
            _add(
                report.issues, candidate_id, "criteria_evidence",
                "标注了支持标准却声明证据为 none",
            )

        pair = (candidate_id, row.get("source_url", ""))
        if pair in seen_pairs:
            _add(report.issues, candidate_id, "duplicate", "同一候选重复使用同一来源 URL")
        seen_pairs.add(pair)

    seen_primary: set[str] = set()
    for row in source_rows:
        if row.get("source_role") != "primary":
            continue
        candidate_id = row.get("candidate_id", "")
        if candidate_id in seen_primary:
            _add(report.issues, candidate_id, "primary_duplicate", "同一候选存在多条 primary 来源")
        seen_primary.add(candidate_id)
        primary[candidate_id] = row

    for candidate in candidate_rows:
        candidate_id = candidate["candidate_id"]
        if candidate_id not in seen_primary:
            _add(report.issues, candidate_id, "primary_missing", "缺少 primary 来源记录")

    for candidate_id, rows in secondary.items():
        primary_row = primary.get(candidate_id)
        if primary_row is None:
            continue
        for row in rows:
            if row.get("source_url") == primary_row.get("source_url"):
                _add(
                    report.issues, candidate_id, "same_source",
                    "第二来源与第一来源 URL 相同，不能算作独立来源",
                )
            if (
                row.get("independence_status") == "independent"
                and row.get("publisher") == primary_row.get("publisher")
            ):
                _add(
                    report.issues, candidate_id, "same_publisher",
                    "第二来源与第一来源同属一个出版机构，不能标记为 independent",
                )

    return report


def validate_review_rows(
    candidate_rows: list[dict[str, str]],
    review_rows: list[dict[str, str]],
    source_rows: list[dict[str, str]],
    report: SourceReport,
) -> None:
    candidate_ids = [row["candidate_id"] for row in candidate_rows]
    supported_by_candidate: dict[str, set[str]] = {}
    second_by_candidate: dict[str, list[dict[str, str]]] = {}
    for row in source_rows:
        supported_by_candidate.setdefault(row["candidate_id"], set()).update(
            _codes(row.get("supported_criteria", ""))
        )
        if row.get("source_role") == "second":
            second_by_candidate.setdefault(row["candidate_id"], []).append(row)

    seen: set[str] = set()
    for row in review_rows:
        candidate_id = row.get("candidate_id", "") or "<空>"
        if candidate_id not in set(candidate_ids):
            _add(report.issues, candidate_id, "unknown_candidate", "审核表引用了不存在的候选")
            continue
        if candidate_id in seen:
            _add(report.issues, candidate_id, "review_duplicate", "审核记录重复")
        seen.add(candidate_id)

        status = row.get("review_status", "")
        if status not in REVIEW_STATUSES:
            _add(
                report.issues, candidate_id, "review_status",
                "review_status 只能是 pending_human_review、needs_more_evidence 或 not_recommended",
            )
        if row.get("review_recommendation", "") not in RECOMMENDATIONS:
            _add(report.issues, candidate_id, "recommendation", "review_recommendation 无效")
        if row.get("evidence_quality", "") not in EVIDENCE_QUALITIES:
            _add(report.issues, candidate_id, "evidence_quality", "evidence_quality 无效")

        second_status = row.get("second_source_status", "")
        if second_status not in SECOND_SOURCE_STATUSES:
            _add(report.issues, candidate_id, "second_status", "second_source_status 无效")
        second_records = second_by_candidate.get(candidate_id, [])
        verified_records = [
            record
            for record in second_records
            if record.get("verification_status") == "verified"
        ]
        unavailable_records = [
            record
            for record in second_records
            if record.get("verification_status") == "unavailable"
        ]
        if second_status == "verified":
            if not verified_records:
                _add(
                    report.issues, candidate_id, "second_missing",
                    "审核表标记第二来源 verified，但来源表缺少 verification_status=verified 的第二来源记录",
                )
        elif second_status == "unavailable":
            if verified_records:
                _add(
                    report.issues, candidate_id, "second_conflict",
                    "来源表存在已核验的第二来源，审核表不得标记为 unavailable",
                )
            elif len(unavailable_records) != len(second_records):
                _add(
                    report.issues, candidate_id, "second_conflict",
                    "审核表标记 unavailable 时，第二来源记录状态必须全部为 unavailable",
                )
        elif second_status == "not_found":
            if second_records:
                _add(
                    report.issues, candidate_id, "second_conflict",
                    "审核表标记 not_found，但来源表存在第二来源记录",
                )
        if second_status != "verified" and status != "needs_more_evidence":
            _add(
                report.issues, candidate_id, "second_pending",
                "缺少可核验的第二来源时必须保持 needs_more_evidence",
            )

        supported = set(_codes(row.get("supported_criteria", "")))
        unsupported = set(_codes(row.get("unsupported_criteria", "")))
        source_supported = supported_by_candidate.get(candidate_id, set())
        if supported - source_supported:
            _add(
                report.issues, candidate_id, "criteria_unsupported",
                f"审核表记录了来源未支持的标准：{sorted(supported - source_supported)}",
            )
        missing = source_supported - supported
        if missing:
            _add(
                report.issues, candidate_id, "criteria_missing",
                f"来源已支持但审核表未记录的标准：{sorted(missing)}",
            )
        if supported & unsupported:
            _add(
                report.issues, candidate_id, "criteria_conflict",
                f"同一标准同时出现在支持与不支持列表：{sorted(supported & unsupported)}",
            )

        if "approved" in {status, row.get("review_recommendation", "")}:
            _add(report.issues, candidate_id, "formal_promotion", "候选不得直接标记为 approved")

    for candidate_id in candidate_ids:
        if candidate_id not in seen:
            _add(report.issues, candidate_id, "review_missing", "审核表缺少该候选的记录")


def validate_candidate_review_files(
    candidates_path: Path,
    sources_path: Path,
    review_path: Path,
    knowledge_path: Path,
    criteria_path: Path,
) -> tuple[SourceReport, object]:
    candidate_rows = _read_csv(candidates_path, CANDIDATE_FIELDS)
    source_rows = _read_csv(sources_path, SOURCE_FIELDS)
    review_rows = _read_csv(review_path, REVIEW_FIELDS)
    knowledge_rows = _read_csv(
        knowledge_path, ["seed_id", "title", "original_title", "year", "tmdb_id", "imdb_id"]
    )
    criteria_rows = _read_csv(criteria_path, ["criterion_code", "name_zh", "name_en"])

    base_report = validate_candidate_rows(candidate_rows, knowledge_rows, criteria_rows)
    report = validate_source_rows(candidate_rows, source_rows, criteria_rows)
    report.issues.extend(base_report.issues)
    validate_review_rows(candidate_rows, review_rows, source_rows, report)

    for row in review_rows:
        if row.get("second_source_status") == "verified":
            report.second_verified += 1
        elif row.get("second_source_status") == "not_found":
            report.second_not_found += 1
        elif row.get("second_source_status") == "unavailable":
            report.second_unavailable += 1
        if row.get("review_status") == "pending_human_review":
            report.pending_human_review += 1
        if row.get("review_status") == "needs_more_evidence":
            report.needs_more_evidence += 1
        if "approved" in {
            row.get("review_status", ""),
            row.get("review_recommendation", ""),
        }:
            report.approved += 1
        codes = _codes(row.get("supported_criteria", ""))
        report.criteria_supported += len(codes)
        for code in codes:
            report.criteria_distribution[code] = (
                report.criteria_distribution.get(code, 0) + 1
            )

    independent_records = [
        row
        for row in source_rows
        if row.get("source_role") == "second"
        and row.get("independence_status") == "independent"
        and row.get("verification_status") == "verified"
    ]
    report.independent_second = len(independent_records)
    report.independent_publishers = len(
        {row.get("publisher", "") for row in independent_records if row.get("publisher")}
    )
    report.independent_urls = len(
        {row.get("source_url", "") for row in independent_records if row.get("source_url")}
    )
    return report, base_report


def main() -> int:
    parser = argparse.ArgumentParser(description="校验候选来源与人工审核准备材料")
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--knowledge", type=Path, default=DEFAULT_KNOWLEDGE)
    parser.add_argument("--criteria", type=Path, default=DEFAULT_CRITERIA)
    parser.add_argument("--check", action="store_true", help="只读校验并输出统计")
    args = parser.parse_args()

    report, _ = validate_candidate_review_files(
        args.candidates,
        args.sources,
        args.review,
        args.knowledge,
        args.criteria,
    )
    print(f"候选电影：{report.total_candidates}")
    print(f"第一来源：{report.primary_rows}")
    print(f"第二来源：{report.second_rows}")
    print(f"第二来源已核验候选：{report.second_verified}")
    print(f"第二来源不可访问候选：{report.second_unavailable}")
    print(f"第二来源未找到候选：{report.second_not_found}")
    print(f"独立第二来源关联记录：{report.independent_second}")
    print(f"不同出版机构名称：{report.independent_publishers}")
    print(f"独立来源 URL 去重：{report.independent_urls}")
    print(f"候选电影－Cult 标准关联：{report.criteria_supported}")
    print(f"待人工审核：{report.pending_human_review}")
    print(f"待补充证据：{report.needs_more_evidence}")
    print(f"approved：{report.approved}")
    distribution = "、".join(
        f"{code}={report.criteria_distribution[code]}"
        for code in sorted(report.criteria_distribution)
    )
    print(f"标准分布：{distribution or '无'}")
    for issue in report.issues:
        print(f"[{issue.severity}] {issue.candidate_id} {issue.code}: {issue.message}")
    print("校验通过" if report.is_valid else f"校验失败：{len(report.errors)} 项错误")
    return 0 if report.is_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
