"""候选电影身份核验的离线只读校验器。

不调用 TMDb，不写入知识库或身份映射，不修改任何生产 CSV：

    python scripts/validate_candidate_identity.py --check

校验范围：
1. 每部候选恰好一条身份记录，candidate_id 与候选表一一对应。
2. 标题、年份与候选表一致；状态只能是 confirmed / needs_review /
   unmatched / conflict / duplicate_existing。
3. confirmed 必须给出 TMDb ID、TMDb 标题、年份一致且方法不能只是标题加年份。
4. confirmed 不得与正式知识库的 TMDb/IMDb ID 重复；重复必须标记
   duplicate_existing 并注明正式知识库 ID。
5. 候选之间不得出现 TMDb ID 或 IMDb ID 重复；同一 TMDb ID 的 IMDb ID 冲突报错。
6. 未确认的 ID 必须留空，不能为完整率填入猜测值。
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts.validate_cult_candidates import (  # noqa: E402
    CANDIDATE_FIELDS,
    CANDIDATE_ID_RE,
    Issue,
    _normalize_title,
    _read_csv,
)

DEFAULT_CANDIDATES = BACKEND_DIR / "data" / "candidates" / "cult_candidates_batch01.csv"
DEFAULT_IDENTITY = BACKEND_DIR / "data" / "candidates" / "cult_candidate_identity_batch01.csv"
DEFAULT_KNOWLEDGE = BACKEND_DIR / "data" / "knowledge" / "cult_seed.csv"
DEFAULT_IDENTITY_MAP = BACKEND_DIR / "data" / "knowledge" / "seed_identity_map.csv"

IDENTITY_FIELDS = [
    "candidate_id",
    "candidate_title",
    "candidate_year",
    "tmdb_id",
    "tmdb_title",
    "tmdb_original_title",
    "tmdb_release_date",
    "tmdb_year",
    "imdb_id",
    "tmdb_url",
    "imdb_url",
    "match_method",
    "match_status",
    "identity_evidence",
    "checked_at",
    "notes",
]

MATCH_STATUSES = {
    "confirmed",
    "needs_review",
    "unmatched",
    "conflict",
    "duplicate_existing",
}
MATCH_METHODS = {
    "tmdb_search_title_year",
    "tmdb_search_details",
    "tmdb_original_title",
    "tmdb_external_ids",
    "tmdb_website_wikidata",
    "manual_review",
}
TITLE_ONLY_METHODS = {"tmdb_search_title_year"}
IMDB_ID_RE = re.compile(r"tt\d{7,9}")
TMDB_URL_RE = re.compile(r"https://www\.themoviedb\.org/movie/(\d+)")
IMDB_URL_RE = re.compile(r"https://www\.imdb\.com/title/(tt\d{7,9})/?")


@dataclass
class IdentityReport:
    total_candidates: int = 0
    identity_rows: int = 0
    confirmed: int = 0
    needs_review: int = 0
    unmatched: int = 0
    conflict: int = 0
    duplicate_existing: int = 0
    tmdb_confirmed: int = 0
    imdb_confirmed: int = 0
    tmdb_id_missing: int = 0
    imdb_id_missing: int = 0
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def is_valid(self) -> bool:
        return not self.errors


def _add(
    issues: list[Issue],
    candidate_id: str,
    code: str,
    message: str,
    severity: str = "error",
) -> None:
    issues.append(Issue(severity, code, candidate_id, message))


def _valid_date(value: str) -> bool:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _valid_tmdb(value: str) -> bool:
    return value.isdigit() and int(value) > 0


def validate_identity_rows(
    candidate_rows: list[dict[str, str]],
    identity_rows: list[dict[str, str]],
    knowledge_rows: list[dict[str, str]],
) -> IdentityReport:
    report = IdentityReport(total_candidates=len(candidate_rows))
    report.identity_rows = len(identity_rows)
    candidates = {row["candidate_id"]: row for row in candidate_rows}
    knowledge_tmdb = {
        row.get("tmdb_id", ""): row["seed_id"]
        for row in knowledge_rows
        if row.get("tmdb_id")
    }
    knowledge_imdb = {
        row.get("imdb_id", ""): row["seed_id"]
        for row in knowledge_rows
        if row.get("imdb_id")
    }
    knowledge_titles: dict[str, list[dict[str, str]]] = {}
    for row in knowledge_rows:
        for title in {row.get("title", ""), row.get("original_title", "")}:
            normalized = _normalize_title(title)
            if normalized:
                knowledge_titles.setdefault(normalized, []).append(row)

    seen_ids: Counter[str] = Counter()
    seen_tmdb: dict[str, str] = {}
    seen_imdb: dict[str, str] = {}
    tmdb_imdb: dict[str, tuple[str, str]] = {}

    for row in identity_rows:
        candidate_id = row.get("candidate_id", "") or "<空>"
        seen_ids[candidate_id] += 1
        candidate = candidates.get(candidate_id)
        if candidate is None:
            _add(report.issues, candidate_id, "unknown_candidate", "身份记录引用了不存在的候选")
            continue
        if not CANDIDATE_ID_RE.fullmatch(candidate_id):
            _add(report.issues, candidate_id, "candidate_id", "candidate_id 格式应为 CB01-001")

        status = row.get("match_status", "")
        if status not in MATCH_STATUSES:
            _add(report.issues, candidate_id, "match_status", "match_status 无效")
            continue
        if status == "confirmed":
            report.confirmed += 1
        elif status == "needs_review":
            report.needs_review += 1
        elif status == "unmatched":
            report.unmatched += 1
        elif status == "conflict":
            report.conflict += 1
        elif status == "duplicate_existing":
            report.duplicate_existing += 1

        if not row.get("candidate_title", ""):
            _add(report.issues, candidate_id, "candidate_title", "缺少 candidate_title")
        else:
            candidate_titles = {
                _normalize_title(candidate.get("title", "")),
                _normalize_title(candidate.get("original_title", "")),
            } - {""}
            if _normalize_title(row["candidate_title"]) not in candidate_titles:
                _add(
                    report.issues, candidate_id, "candidate_title",
                    "candidate_title 与候选表标题不一致",
                )
        if row.get("candidate_year", "") != candidate.get("year", ""):
            _add(report.issues, candidate_id, "candidate_year", "candidate_year 与候选表年份不一致")

        if not row.get("checked_at", ""):
            _add(report.issues, candidate_id, "checked_at", "缺少 checked_at")
        elif not _valid_date(row["checked_at"]):
            _add(report.issues, candidate_id, "checked_at", "checked_at 必须是 YYYY-MM-DD")

        if not row.get("identity_evidence", ""):
            _add(report.issues, candidate_id, "identity_evidence", "缺少 identity_evidence")

        method = row.get("match_method", "")
        if method and method not in MATCH_METHODS:
            _add(report.issues, candidate_id, "match_method", "match_method 无效")

        tmdb_id = row.get("tmdb_id", "")
        imdb_id = row.get("imdb_id", "")
        if tmdb_id and not _valid_tmdb(tmdb_id):
            _add(report.issues, candidate_id, "tmdb_id", "TMDb ID 格式无效")
        if imdb_id and not IMDB_ID_RE.fullmatch(imdb_id):
            _add(report.issues, candidate_id, "imdb_id", "IMDb ID 格式无效")
        if not tmdb_id:
            report.tmdb_id_missing += 1
        if not imdb_id:
            report.imdb_id_missing += 1

        if status in {"confirmed", "duplicate_existing"}:
            if not tmdb_id:
                _add(report.issues, candidate_id, "tmdb_required", f"{status} 必须给出 TMDb ID")
            if not row.get("tmdb_title", ""):
                _add(report.issues, candidate_id, "tmdb_title", f"{status} 缺少 tmdb_title")
            if not method:
                _add(report.issues, candidate_id, "match_method", f"{status} 缺少 match_method")

        if status == "confirmed":
            if method in TITLE_ONLY_METHODS:
                _add(
                    report.issues, candidate_id, "insufficient_identity",
                    "仅凭标题和年份不得判定 confirmed，需要详情或原始片名等额外依据",
                )
            if tmdb_id and row.get("tmdb_year", "") != candidate.get("year", ""):
                _add(
                    report.issues, candidate_id, "year_mismatch",
                    f"TMDb 年份 {row.get('tmdb_year') or '<空>'} 与候选年份 "
                    f"{candidate.get('year')} 不一致",
                )
            if tmdb_id and row.get("tmdb_title", ""):
                titles = {
                    _normalize_title(row["tmdb_title"]),
                    _normalize_title(row.get("tmdb_original_title", "")),
                } - {""}
                candidate_titles = {
                    _normalize_title(candidate.get("title", "")),
                    _normalize_title(candidate.get("original_title", "")),
                } - {""}
                if not titles & candidate_titles:
                    _add(
                        report.issues, candidate_id, "title_mismatch",
                        "TMDb 标题与候选标题均不匹配",
                    )
            if method == "tmdb_original_title":
                if _normalize_title(row.get("tmdb_original_title", "")) != _normalize_title(
                    candidate.get("original_title", "")
                ):
                    _add(
                        report.issues, candidate_id, "original_title_mismatch",
                        "确认依据为原始片名，但 TMDb 原始片名与候选不一致",
                    )
            if imdb_id:
                report.imdb_confirmed += 1
            if tmdb_id:
                report.tmdb_confirmed += 1

        if status in {"unmatched", "needs_review", "conflict"}:
            if row.get("tmdb_year", "") and candidate.get("year", "") != row["tmdb_year"]:
                _add(
                    report.issues, candidate_id, "year_differs",
                    "tmdb_year 与候选年份不一致，需在人工复核中确认年份口径",
                    "warning",
                )

        if status == "duplicate_existing":
            if not re.search(r"CS-\d{4}", row.get("notes", "")):
                _add(
                    report.issues, candidate_id, "duplicate_reference",
                    "duplicate_existing 必须在 notes 中注明正式知识库 ID",
                )
            if tmdb_id and tmdb_id not in knowledge_tmdb:
                _add(
                    report.issues, candidate_id, "duplicate_mismatch",
                    "duplicate_existing 的 TMDb ID 不在正式知识库中",
                )

        if status != "duplicate_existing":
            if tmdb_id and tmdb_id in knowledge_tmdb:
                _add(
                    report.issues, candidate_id, "duplicate_existing_required",
                    f"TMDb ID 与正式知识库 {knowledge_tmdb[tmdb_id]} 重复，必须标记 duplicate_existing",
                )
            if imdb_id and imdb_id in knowledge_imdb:
                _add(
                    report.issues, candidate_id, "duplicate_existing_required",
                    f"IMDb ID 与正式知识库 {knowledge_imdb[imdb_id]} 重复，必须标记 duplicate_existing",
                )

        normalized_title = _normalize_title(candidate.get("original_title", "") or candidate.get("title", ""))
        for existing in knowledge_titles.get(normalized_title, []):
            if existing.get("year") == candidate.get("year") and status != "duplicate_existing":
                _add(
                    report.issues, candidate_id, "duplicate_existing_required",
                    f"与正式知识库 {existing['seed_id']} 同名同年，必须标记 duplicate_existing",
                )
            elif existing.get("year") != candidate.get("year"):
                _add(
                    report.issues, candidate_id, "same_title_different_year",
                    f"与 {existing['seed_id']} 同名但年份不同，需确认不是同名翻拍",
                    "warning",
                )

        if tmdb_id:
            if tmdb_id in seen_tmdb and seen_tmdb[tmdb_id] != candidate_id:
                _add(
                    report.issues, candidate_id, "duplicate_tmdb",
                    f"TMDb ID 与候选 {seen_tmdb[tmdb_id]} 重复",
                )
            seen_tmdb.setdefault(tmdb_id, candidate_id)
            if imdb_id:
                previous = tmdb_imdb.get(tmdb_id)
                if previous and previous[0] and previous[0] != imdb_id:
                    _add(
                        report.issues, candidate_id, "imdb_conflict",
                        f"同一 TMDb ID 的 IMDb ID 冲突：{previous[1]}={previous[0]}，"
                        f"{candidate_id}={imdb_id}",
                    )
                tmdb_imdb.setdefault(tmdb_id, (imdb_id, candidate_id))
        if imdb_id:
            if imdb_id in seen_imdb and seen_imdb[imdb_id] != candidate_id:
                _add(
                    report.issues, candidate_id, "duplicate_imdb",
                    f"IMDb ID 与候选 {seen_imdb[imdb_id]} 重复",
                )
            seen_imdb.setdefault(imdb_id, candidate_id)

        if tmdb_id:
            if not row.get("tmdb_url", ""):
                _add(report.issues, candidate_id, "tmdb_url", "有 TMDb ID 时缺少 tmdb_url")
            else:
                match = TMDB_URL_RE.fullmatch(row["tmdb_url"])
                if match is None or match.group(1) != tmdb_id:
                    _add(
                        report.issues, candidate_id, "tmdb_url",
                        "tmdb_url 必须指向对应 TMDb ID",
                    )
        if imdb_id:
            if not row.get("imdb_url", ""):
                _add(report.issues, candidate_id, "imdb_url", "有 IMDb ID 时缺少 imdb_url")
            else:
                match = IMDB_URL_RE.fullmatch(row["imdb_url"])
                if match is None or match.group(1) != imdb_id:
                    _add(
                        report.issues, candidate_id, "imdb_url",
                        "imdb_url 必须指向对应 IMDb ID",
                    )

    for candidate_id in candidates:
        count = seen_ids.get(candidate_id, 0)
        if count == 0:
            _add(report.issues, candidate_id, "identity_missing", "候选缺少身份记录")
        elif count > 1:
            _add(report.issues, candidate_id, "identity_duplicate", "候选存在多条身份记录")

    if report.confirmed + report.needs_review + report.unmatched + report.conflict + report.duplicate_existing != report.identity_rows:
        _add(
            report.issues, "<汇总>", "status_total",
            "各状态数量之和与身份记录条数不一致",
        )
    return report


def validate_identity_files(
    candidates_path: Path,
    identity_path: Path,
    knowledge_path: Path,
) -> IdentityReport:
    candidates = _read_csv(Path(candidates_path), CANDIDATE_FIELDS)
    identity = _read_csv(Path(identity_path), IDENTITY_FIELDS)
    knowledge = _read_csv(
        Path(knowledge_path),
        ["seed_id", "title", "original_title", "year", "tmdb_id", "imdb_id"],
    )
    return validate_identity_rows(candidates, identity, knowledge)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--identity", type=Path, default=DEFAULT_IDENTITY)
    parser.add_argument("--knowledge", type=Path, default=DEFAULT_KNOWLEDGE)
    parser.add_argument("--check", action="store_true", help="只读校验（默认行为）")
    args = parser.parse_args()
    try:
        report = validate_identity_files(args.candidates, args.identity, args.knowledge)
    except (OSError, ValueError, UnicodeError, csv.Error) as exc:
        print(f"错误：{exc}")
        return 1
    print(
        f"身份统计：candidates={report.total_candidates}，rows={report.identity_rows}，"
        f"confirmed={report.confirmed}，needs_review={report.needs_review}，"
        f"unmatched={report.unmatched}，conflict={report.conflict}，"
        f"duplicate_existing={report.duplicate_existing}"
    )
    print(
        f"ID 统计：tmdb_confirmed={report.tmdb_confirmed}，"
        f"imdb_confirmed={report.imdb_confirmed}，"
        f"tmdb_missing={report.tmdb_id_missing}，imdb_missing={report.imdb_id_missing}"
    )
    for issue in report.issues:
        print(f"- [{issue.severity}/{issue.code}] {issue.candidate_id}：{issue.message}")
    if not report.issues:
        print("- 无异常")
    print("只读校验：未修改候选表、身份记录或正式知识库。")
    return 0 if report.is_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
