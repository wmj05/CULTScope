"""离线校验 Cult 候选暂存 CSV；不导入知识库、不修改审核状态、不调用 API。"""

from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATES = (
    BACKEND_DIR / "data" / "candidates" / "cult_candidates_batch01.csv"
)
DEFAULT_KNOWLEDGE = BACKEND_DIR / "data" / "knowledge" / "cult_seed.csv"
DEFAULT_CRITERIA = BACKEND_DIR / "data" / "knowledge" / "cult_criteria.csv"

CANDIDATE_FIELDS = [
    "candidate_id",
    "title",
    "original_title",
    "year",
    "source_id",
    "source_title",
    "source_url",
    "source_evidence",
    "inclusion_reason",
    "candidate_criteria_codes",
    "tmdb_id",
    "imdb_id",
    "verification_status",
    "candidate_status",
    "notes",
]
CANDIDATE_ID_RE = re.compile(r"CB\d{2}-\d{3}")
SOURCE_ID_RE = re.compile(r"CB\d{2}-S\d{2}")
IMDB_ID_RE = re.compile(r"tt\d+")


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    candidate_id: str
    message: str


@dataclass
class CandidateReport:
    total: int = 0
    verified: int = 0
    unverified: int = 0
    issues: list[Issue] = field(default_factory=list)

    @property
    def duplicates(self) -> int:
        return sum(issue.code == "duplicate" for issue in self.issues)

    @property
    def anomalies(self) -> int:
        return sum(issue.code != "duplicate" for issue in self.issues)

    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def is_valid(self) -> bool:
        return not self.errors


def _read_csv(path: Path, required: list[str]) -> list[dict[str, str]]:
    if not path.is_file():
        raise ValueError(f"文件不存在：{path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        missing = set(required) - set(headers)
        if missing:
            raise ValueError(f"CSV 缺少字段 {sorted(missing)}：{path}")
        rows = []
        for line_number, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(f"CSV 第 {line_number} 行存在多余单元格：{path}")
            rows.append({key: (value or "").strip() for key, value in row.items()})
        return rows


def _normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _valid_year(value: str) -> bool:
    return value.isdigit() and 1888 <= int(value) <= date.today().year


def _valid_url(value: str) -> bool:
    if not value or any(character.isspace() for character in value):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def can_enter_knowledge_review(row: dict[str, str]) -> bool:
    """仅表示可进入后续人工审核准备，不表示自动导入或 approved。"""
    return (
        row.get("verification_status") == "verified"
        and row.get("candidate_status") == "staged"
        and bool(row.get("source_id"))
        and bool(row.get("source_title"))
        and _valid_url(row.get("source_url", ""))
        and bool(row.get("source_evidence"))
        and bool(row.get("inclusion_reason"))
        and bool(row.get("candidate_criteria_codes"))
    )


def validate_candidate_rows(
    candidate_rows: list[dict[str, str]],
    knowledge_rows: list[dict[str, str]],
    criteria_rows: list[dict[str, str]],
) -> CandidateReport:
    report = CandidateReport(total=len(candidate_rows))
    report.verified = sum(
        row.get("verification_status") == "verified" for row in candidate_rows
    )
    report.unverified = sum(
        row.get("verification_status") == "unverified" for row in candidate_rows
    )
    criteria_codes = {row["criterion_code"] for row in criteria_rows}

    def add(candidate_id: str, severity: str, code: str, message: str) -> None:
        report.issues.append(Issue(severity, code, candidate_id, message))

    seen_ids: set[str] = set()
    seen_candidate_titles: dict[str, list[dict[str, str]]] = {}
    seen_tmdb: dict[str, str] = {}
    seen_imdb: dict[str, str] = {}
    source_metadata: dict[str, tuple[str, str]] = {}
    knowledge_titles: dict[str, list[dict[str, str]]] = {}
    knowledge_tmdb = {row.get("tmdb_id", "") for row in knowledge_rows} - {""}
    knowledge_imdb = {row.get("imdb_id", "") for row in knowledge_rows} - {""}
    for row in knowledge_rows:
        for title in {row.get("title", ""), row.get("original_title", "")}:
            normalized = _normalize_title(title)
            if normalized:
                knowledge_titles.setdefault(normalized, []).append(row)

    for row in candidate_rows:
        candidate_id = row.get("candidate_id", "") or "<空>"
        if not CANDIDATE_ID_RE.fullmatch(candidate_id):
            add(candidate_id, "error", "candidate_id", "candidate_id 格式应为 CB01-001")
        if candidate_id in seen_ids:
            add(candidate_id, "error", "candidate_id", "candidate_id 重复")
        seen_ids.add(candidate_id)

        for field_name in (
            "title", "original_title", "source_id", "source_title",
            "source_url", "inclusion_reason", "verification_status",
            "candidate_status",
        ):
            if not row.get(field_name, ""):
                add(candidate_id, "error", "source_required", f"缺少字段：{field_name}")
        if not SOURCE_ID_RE.fullmatch(row.get("source_id", "")):
            add(candidate_id, "error", "source_id", "source_id 格式应为 CB01-S01")
        if not _valid_url(row.get("source_url", "")):
            add(candidate_id, "error", "url", "source_url 必须是有效 HTTP(S) URL")
        if not _valid_year(row.get("year", "")):
            add(candidate_id, "error", "year", "year 必须是有效且非未来的四位年份")

        verification_status = row.get("verification_status", "")
        if verification_status not in {"verified", "unverified"}:
            add(candidate_id, "error", "verification_status", "verification_status 无效")
        if row.get("candidate_status") != "staged":
            add(
                candidate_id, "error", "formal_promotion",
                "候选必须保持 staged，不得直接写入正式知识库或 approved",
            )
        if verification_status == "verified" and not row.get("source_evidence", ""):
            add(
                candidate_id, "error", "missing_evidence",
                "缺少来源证据的候选不能标记为 verified",
            )
        if verification_status == "unverified":
            if not row.get("notes", ""):
                add(candidate_id, "error", "unverified_note", "unverified 候选必须说明未核验原因")
            if row.get("tmdb_id", "") or row.get("imdb_id", ""):
                add(
                    candidate_id, "error", "unverified_ids",
                    "unverified 候选的 TMDb/IMDb ID 必须留空",
                )

        tmdb_id = row.get("tmdb_id", "")
        imdb_id = row.get("imdb_id", "")
        if tmdb_id and (not tmdb_id.isdigit() or int(tmdb_id) <= 0):
            add(candidate_id, "error", "tmdb_id", "TMDb ID 格式无效")
        if imdb_id and not IMDB_ID_RE.fullmatch(imdb_id):
            add(candidate_id, "error", "imdb_id", "IMDb ID 格式无效")

        codes = [code for code in row.get("candidate_criteria_codes", "").split("|") if code]
        unknown_codes = sorted(set(codes) - criteria_codes)
        if unknown_codes:
            add(candidate_id, "error", "criteria", f"未知 Cult 标准代码：{unknown_codes}")
        if verification_status == "verified" and not codes:
            add(candidate_id, "error", "criteria", "verified 候选至少需要一个候选标准代码")

        source_key = (row.get("source_title", ""), row.get("source_url", ""))
        if row.get("source_id", "") in source_metadata and source_metadata[row["source_id"]] != source_key:
            add(candidate_id, "error", "source_conflict", "同一 source_id 的标题或 URL 不一致")
        elif row.get("source_id", ""):
            source_metadata[row["source_id"]] = source_key

        normalized = _normalize_title(row.get("original_title", "") or row.get("title", ""))
        year = row.get("year", "")
        for existing in knowledge_titles.get(normalized, []):
            if existing.get("year") == year:
                add(
                    candidate_id, "error", "duplicate",
                    f"与正式知识库样本重复：{existing['seed_id']}（标题年份一致）",
                )
            else:
                add(
                    candidate_id, "warning", "same_title_different_year",
                    f"与 {existing['seed_id']} 同名但年份不同，需确认不是不同版本",
                )
        if tmdb_id and tmdb_id in knowledge_tmdb:
            add(candidate_id, "error", "duplicate", "与正式知识库样本的 TMDb ID 重复")
        if imdb_id and imdb_id in knowledge_imdb:
            add(candidate_id, "error", "duplicate", "与正式知识库样本的 IMDb ID 重复")

        for existing in seen_candidate_titles.get(normalized, []):
            if existing.get("year") == year:
                add(candidate_id, "error", "duplicate", f"与候选 {existing['candidate_id']} 标题年份重复")
            else:
                add(
                    candidate_id, "warning", "same_title_different_year",
                    f"与候选 {existing['candidate_id']} 同名但年份不同",
                )
        if normalized:
            seen_candidate_titles.setdefault(normalized, []).append(row)
        if tmdb_id and tmdb_id in seen_tmdb:
            add(candidate_id, "error", "duplicate", f"与候选 {seen_tmdb[tmdb_id]} 的 TMDb ID 重复")
        if imdb_id and imdb_id in seen_imdb:
            add(candidate_id, "error", "duplicate", f"与候选 {seen_imdb[imdb_id]} 的 IMDb ID 重复")
        if tmdb_id:
            seen_tmdb[tmdb_id] = candidate_id
        if imdb_id:
            seen_imdb[imdb_id] = candidate_id
    return report


def validate_candidate_files(
    candidates_path: Path, knowledge_path: Path, criteria_path: Path
) -> CandidateReport:
    candidates = _read_csv(Path(candidates_path), CANDIDATE_FIELDS)
    knowledge = _read_csv(
        Path(knowledge_path), ["seed_id", "title", "original_title", "year", "tmdb_id", "imdb_id"]
    )
    criteria = _read_csv(Path(criteria_path), ["criterion_code"])
    return validate_candidate_rows(candidates, knowledge, criteria)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--knowledge", type=Path, default=DEFAULT_KNOWLEDGE)
    parser.add_argument("--criteria", type=Path, default=DEFAULT_CRITERIA)
    args = parser.parse_args()
    try:
        report = validate_candidate_files(args.candidates, args.knowledge, args.criteria)
    except (OSError, ValueError, UnicodeError, csv.Error) as exc:
        print(f"错误：{exc}")
        return 1
    print(
        f"候选统计：total={report.total}，verified={report.verified}，"
        f"unverified={report.unverified}，duplicates={report.duplicates}，"
        f"anomalies={report.anomalies}"
    )
    for issue in report.issues:
        print(f"- [{issue.severity}/{issue.code}] {issue.candidate_id}：{issue.message}")
    if not report.issues:
        print("- 无重复或异常")
    print("只读校验：未修改候选文件或正式知识库。")
    return 0 if report.is_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
