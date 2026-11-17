"""第三阶段知识库校验器。

用法（在 backend 目录下）：
    python scripts/validate_knowledge.py
    python scripts/validate_knowledge.py --data-dir data/knowledge

校验范围：
- CSV 表头与 Pydantic 字段约束；
- seed_id / tmdb_id / source_id / criterion_code / tag_id 唯一性；
- 种子、证据、标签、审核日志之间的外键完整性；
- approved 电影的 T1/T2 来源与至少两条经正文核实（verified）且有证据支持的 Cult 标准；
- 人工标签必须有来源和证据，推断标签必须有 rule_id，且不得覆盖人工标注；
- 审核日志的哈希链与时间顺序，防止历史被改写或乱序追加。
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, ValidationError

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.schemas.knowledge import (  # noqa: E402
    REVIEW_LOG_GENESIS,
    CriterionEvidence,
    CultCriterion,
    CultSeed,
    CultSource,
    CultTag,
    MovieCultTag,
    MovieCultTagCandidate,
    ReviewLogEntry,
    compute_review_entry_hash,
)

DEFAULT_DATA_DIR = BACKEND_DIR / "data" / "knowledge"

EXPECTED_HEADERS: dict[str, list[str]] = {
    "cult_seed.csv": [
        "seed_id",
        "title",
        "original_title",
        "year",
        "tmdb_id",
        "imdb_id",
        "candidate_source_ids",
        "cult_criteria_codes",
        "review_status",
        "confidence",
        "reviewer",
        "reviewed_at",
        "notes",
    ],
    "cult_sources.csv": [
        "source_id",
        "title",
        "source_type",
        "url",
        "publisher",
        "published_year",
        "language",
        "reliability_tier",
        "notes",
    ],
    "cult_criteria.csv": [
        "criterion_code",
        "name_zh",
        "name_en",
        "definition",
        "evidence_requirement",
        "exclusion_note",
        "version",
    ],
    "movie_criterion_evidence.csv": [
        "seed_id",
        "criterion_code",
        "source_id",
        "evidence_summary",
        "locator",
        "verification_status",
        "human_status",
        "confirmed_by",
        "confirmed_at",
        "added_by",
        "added_at",
    ],
    "cult_tags.csv": [
        "tag_id",
        "label_zh",
        "label_en",
        "dimension",
        "definition",
        "inclusion_criteria",
        "exclusion_criteria",
        "status",
        "version",
    ],
    "movie_cult_tags.csv": [
        "seed_id",
        "tag_id",
        "origin",
        "confidence",
        "evidence",
        "source_ids",
        "rule_id",
        "annotator",
        "reviewed",
        "updated_at",
    ],
    "movie_cult_tag_candidates.csv": [
        "seed_id",
        "tag_id",
        "evidence",
        "source_ids",
        "proposed_by",
        "proposed_at",
        "human_status",
        "confirmed_by",
        "confirmed_at",
    ],
    "review_log.csv": [
        "timestamp",
        "seed_id",
        "field",
        "old_value",
        "new_value",
        "actor",
        "reason",
        "prev_hash",
        "entry_hash",
    ],
}

FILE_MODELS: dict[str, type[BaseModel]] = {
    "cult_seed.csv": CultSeed,
    "cult_sources.csv": CultSource,
    "cult_criteria.csv": CultCriterion,
    "movie_criterion_evidence.csv": CriterionEvidence,
    "cult_tags.csv": CultTag,
    "movie_cult_tags.csv": MovieCultTag,
    "movie_cult_tag_candidates.csv": MovieCultTagCandidate,
    "review_log.csv": ReviewLogEntry,
}


@dataclass(frozen=True)
class Issue:
    severity: str
    file: str
    line: int
    field: str
    message: str

    def __str__(self) -> str:
        label = "错误" if self.severity == "error" else "警告"
        location = f"{self.file}:{self.line}" if self.line > 0 else self.file
        return f"[{label}] {location} {self.field}: {self.message}"


@dataclass
class ParsedRecord:
    line: int
    raw: dict[str, str]
    model: BaseModel


@dataclass
class ValidationReport:
    data_dir: Path
    issues: list[Issue] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)

    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, severity: str, file: str, line: int, field_name: str, message: str) -> None:
        self.issues.append(Issue(severity, file, line, field_name, message))


def _split_multi(value: str) -> list[str]:
    return [part.strip() for part in value.split("|") if part.strip()]


def _parse_bool(value: str) -> bool | str:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n", ""}:
        return False
    return value


def _seed_data(raw: dict[str, str]) -> dict:
    return {
        **raw,
        "tmdb_id": raw["tmdb_id"] or None,
        "imdb_id": raw["imdb_id"] or None,
        "candidate_source_ids": _split_multi(raw["candidate_source_ids"]),
        "cult_criteria_codes": _split_multi(raw["cult_criteria_codes"]),
        "confidence": raw["confidence"] or "unknown",
        "reviewed_at": raw["reviewed_at"] or None,
    }


def _source_data(raw: dict[str, str]) -> dict:
    return {**raw, "published_year": raw["published_year"] or None}


def _movie_tag_data(raw: dict[str, str]) -> dict:
    return {
        **raw,
        "confidence": raw["confidence"] or None,
        "source_ids": _split_multi(raw["source_ids"]),
        "reviewed": _parse_bool(raw["reviewed"]),
        "updated_at": raw["updated_at"] or None,
    }


def _evidence_data(raw: dict[str, str]) -> dict:
    return {
        **raw,
        "human_status": raw.get("human_status") or "pending",
        "confirmed_at": raw.get("confirmed_at") or None,
    }


def _tag_candidate_data(raw: dict[str, str]) -> dict:
    return {
        **raw,
        "source_ids": _split_multi(raw["source_ids"]),
        "human_status": raw.get("human_status") or "pending",
        "confirmed_at": raw.get("confirmed_at") or None,
    }


PREPROCESSORS: dict[str, Callable[[dict[str, str]], dict]] = {
    "cult_seed.csv": _seed_data,
    "cult_sources.csv": _source_data,
    "movie_criterion_evidence.csv": _evidence_data,
    "movie_cult_tags.csv": _movie_tag_data,
    "movie_cult_tag_candidates.csv": _tag_candidate_data,
}


def _read_rows(
    data_dir: Path, filename: str, report: ValidationReport
) -> list[tuple[int, dict[str, str]]]:
    path = data_dir / filename
    if not path.exists():
        report.add("error", filename, 0, "file", f"文件不存在：{path}")
        return []

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []
        expected = EXPECTED_HEADERS[filename]
        if header != expected:
            missing = [column for column in expected if column not in header]
            unexpected = [column for column in header if column not in expected]
            details = []
            if missing:
                details.append(f"缺少列 {missing}")
            if unexpected:
                details.append(f"多余列 {unexpected}")
            if not details:
                details.append("列顺序与约定不一致")
            report.add("error", filename, 1, "header", "；".join(details))
            return []

        rows: list[tuple[int, dict[str, str]]] = []
        for row in reader:
            if not any((value or "").strip() for value in row.values() if value is not None):
                continue
            cleaned = {
                key: (value or "").strip()
                for key, value in row.items()
                if key is not None
            }
            rows.append((reader.line_num, cleaned))
        return rows


def _load_records(
    data_dir: Path, filename: str, report: ValidationReport
) -> list[ParsedRecord]:
    rows = _read_rows(data_dir, filename, report)
    preprocess = PREPROCESSORS.get(filename, lambda raw: raw)
    model_cls = FILE_MODELS[filename]
    records: list[ParsedRecord] = []

    for line, raw in rows:
        try:
            model = model_cls.model_validate(preprocess(raw))
        except ValidationError as exc:
            for error in exc.errors():
                location = ".".join(str(item) for item in error["loc"]) or "*"
                message = str(error["msg"]).removeprefix("Value error, ")
                report.add("error", filename, line, location, message)
            continue
        records.append(ParsedRecord(line=line, raw=raw, model=model))

    return records


def _check_unique(
    records: list[ParsedRecord],
    filename: str,
    field_name: str,
    report: ValidationReport,
    allow_none: bool = False,
) -> dict:
    seen: dict = {}
    first_lines: dict = {}
    for record in records:
        value = getattr(record.model, field_name)
        if value is None and allow_none:
            continue
        if value in seen:
            report.add(
                "error",
                filename,
                record.line,
                field_name,
                f"{field_name} 重复：{value}（首次出现于第 {first_lines[value]} 行）",
            )
            continue
        seen[value] = record.model
        first_lines[value] = record.line
    return seen


def _check_references(
    record: ParsedRecord,
    filename: str,
    field_name: str,
    values: list[str],
    known: dict,
    report: ValidationReport,
    label: str,
) -> None:
    for value in values:
        if value not in known:
            report.add(
                "error",
                filename,
                record.line,
                field_name,
                f"{label}不存在：{value}",
            )


def _check_approved_rule(
    seeds: list[ParsedRecord],
    evidence: list[ParsedRecord],
    sources: dict[str, CultSource],
    report: ValidationReport,
) -> None:
    evidence_by_seed: dict[str, list[CriterionEvidence]] = defaultdict(list)
    for record in evidence:
        item = record.model
        assert isinstance(item, CriterionEvidence)
        evidence_by_seed[item.seed_id].append(item)

    for record in seeds:
        seed = record.model
        assert isinstance(seed, CultSeed)

        if seed.review_status != "approved":
            if seed.review_status == "draft":
                if not seed.candidate_source_ids:
                    report.add(
                        "warning",
                        "cult_seed.csv",
                        record.line,
                        "candidate_source_ids",
                        "draft 尚未登记候选来源",
                    )
                if not seed.cult_criteria_codes:
                    report.add(
                        "warning",
                        "cult_seed.csv",
                        record.line,
                        "cult_criteria_codes",
                        "draft 尚未选择 Cult 认定标准",
                    )
            if not seed.imdb_id:
                report.add(
                    "warning",
                    "cult_seed.csv",
                    record.line,
                    "imdb_id",
                    "IMDb ID 缺失，待补录",
                )
            continue

        strong_sources = [
            source_id
            for source_id in seed.candidate_source_ids
            if source_id in sources
            and sources[source_id].reliability_tier in {"T1", "T2"}
        ]
        if not strong_sources:
            report.add(
                "error",
                "cult_seed.csv",
                record.line,
                "candidate_source_ids",
                "approved 电影至少需要一个有效的 T1/T2 来源",
            )

        supported: set[str] = set()
        for item in evidence_by_seed.get(seed.seed_id, []):
            if item.criterion_code not in seed.cult_criteria_codes:
                continue
            if item.verification_status != "verified":
                continue
            if item.human_status != "confirmed":
                continue
            source = sources.get(item.source_id)
            if source and source.reliability_tier in {"T1", "T2"}:
                supported.add(item.criterion_code)

        if len(supported) < 2:
            report.add(
                "error",
                "cult_seed.csv",
                record.line,
                "cult_criteria_codes",
                "approved 电影至少需要两条经正文核实（verified）、经人工确认（confirmed）、"
                "且有 T1/T2 来源证据支持的 Cult 认定标准；"
                f"当前仅 {len(supported)} 条",
            )


def _check_movie_tags(
    records: list[ParsedRecord],
    seeds: dict[str, CultSeed],
    tags: dict[str, CultTag],
    sources: dict[str, CultSource],
    report: ValidationReport,
) -> None:
    pairs: dict[tuple[str, str], list[ParsedRecord]] = defaultdict(list)
    for record in records:
        item = record.model
        assert isinstance(item, MovieCultTag)
        pairs[(item.seed_id, item.tag_id)].append(record)

        if item.seed_id not in seeds:
            report.add("error", "movie_cult_tags.csv", record.line, "seed_id", f"电影不存在：{item.seed_id}")
        tag = tags.get(item.tag_id)
        if tag is None:
            report.add("error", "movie_cult_tags.csv", record.line, "tag_id", f"标签不存在：{item.tag_id}")
        elif tag.status == "deprecated":
            report.add("warning", "movie_cult_tags.csv", record.line, "tag_id", f"引用了已废弃标签：{item.tag_id}")

        if item.origin == "manual":
            for source_id in item.source_ids:
                if source_id not in sources:
                    report.add(
                        "error",
                        "movie_cult_tags.csv",
                        record.line,
                        "source_ids",
                        f"来源不存在：{source_id}",
                    )

    for (seed_id, tag_id), records_for_pair in pairs.items():
        origins = {record.model.origin for record in records_for_pair}  # type: ignore[attr-defined]
        if "manual" in origins and "inferred" in origins:
            for record in records_for_pair:
                if record.model.origin == "inferred":  # type: ignore[attr-defined]
                    report.add(
                        "error",
                        "movie_cult_tags.csv",
                        record.line,
                        "tag_id",
                        f"推断标签与人工标注重复（{seed_id} / {tag_id}），"
                        "推断结果不得覆盖人工标注",
                    )
        elif len(records_for_pair) > 1:
            for record in records_for_pair[1:]:
                report.add(
                    "error",
                    "movie_cult_tags.csv",
                    record.line,
                    "tag_id",
                    f"同一电影与标签被重复标注：{seed_id} / {tag_id}",
                )


def _check_tag_candidates(
    records: list[ParsedRecord],
    movie_tag_records: list[ParsedRecord],
    seeds: dict[str, CultSeed],
    tags: dict[str, CultTag],
    sources: dict[str, CultSource],
    report: ValidationReport,
) -> None:
    """候选标签与正式人工标注必须严格分离。"""
    formal_manual: set[tuple[str, str]] = set()
    for record in movie_tag_records:
        item = record.model
        assert isinstance(item, MovieCultTag)
        if item.origin == "manual" and item.reviewed:
            formal_manual.add((item.seed_id, item.tag_id))

    pairs: dict[tuple[str, str], list[ParsedRecord]] = defaultdict(list)
    for record in records:
        item = record.model
        assert isinstance(item, MovieCultTagCandidate)
        pairs[(item.seed_id, item.tag_id)].append(record)

        if item.seed_id not in seeds:
            report.add(
                "error",
                "movie_cult_tag_candidates.csv",
                record.line,
                "seed_id",
                f"电影不存在：{item.seed_id}",
            )
        tag = tags.get(item.tag_id)
        if tag is None:
            report.add(
                "error",
                "movie_cult_tag_candidates.csv",
                record.line,
                "tag_id",
                f"标签不存在：{item.tag_id}",
            )
        elif tag.status == "deprecated":
            report.add(
                "warning",
                "movie_cult_tag_candidates.csv",
                record.line,
                "tag_id",
                f"候选引用了已废弃标签：{item.tag_id}",
            )
        for source_id in item.source_ids:
            if source_id not in sources:
                report.add(
                    "error",
                    "movie_cult_tag_candidates.csv",
                    record.line,
                    "source_ids",
                    f"来源不存在：{source_id}",
                )

        pair = (item.seed_id, item.tag_id)
        if item.human_status == "confirmed":
            if pair not in formal_manual:
                report.add(
                    "error",
                    "movie_cult_tag_candidates.csv",
                    record.line,
                    "human_status",
                    "已人工确认的候选标签必须提升为 movie_cult_tags 中 "
                    "origin=manual 且 reviewed=true 的正式标签",
                )
        elif pair in formal_manual:
            report.add(
                "error",
                "movie_cult_tag_candidates.csv",
                record.line,
                "human_status",
                "候选标签尚未人工确认，却已存在于正式人工标注集合",
            )

    for (seed_id, tag_id), pair_records in pairs.items():
        for record in pair_records[1:]:
            report.add(
                "error",
                "movie_cult_tag_candidates.csv",
                record.line,
                "tag_id",
                f"同一电影与候选标签被重复登记：{seed_id} / {tag_id}",
            )


def _check_status_history(
    seed_records: list[ParsedRecord],
    log_records: list[ParsedRecord],
    report: ValidationReport,
) -> None:
    logged_seeds = {
        record.model.seed_id
        for record in log_records
        if record.model.field == "review_status"  # type: ignore[attr-defined]
    }
    for record in seed_records:
        seed = record.model
        assert isinstance(seed, CultSeed)
        if seed.review_status != "draft" and seed.seed_id not in logged_seeds:
            report.add(
                "warning",
                "cult_seed.csv",
                record.line,
                "review_status",
                "非 draft 状态缺少 review_status 变更日志，"
                "可运行 review_knowledge.py backfill 补录",
            )


def _check_review_log(
    records: list[ParsedRecord],
    seeds: dict[str, CultSeed],
    report: ValidationReport,
) -> None:
    expected_prev = REVIEW_LOG_GENESIS
    previous_timestamp: datetime | None = None
    seen_rows: set[tuple[str, ...]] = set()

    for record in records:
        item = record.model
        assert isinstance(item, ReviewLogEntry)
        raw = record.raw

        if raw["prev_hash"] != expected_prev:
            report.add(
                "error",
                "review_log.csv",
                record.line,
                "prev_hash",
                "哈希链断裂：prev_hash 与上一条 entry_hash 不一致，历史可能被改写或乱序",
            )

        expected_hash = compute_review_entry_hash(
            prev_hash=raw["prev_hash"],
            timestamp=raw["timestamp"],
            seed_id=raw["seed_id"],
            field=raw["field"],
            old_value=raw["old_value"],
            new_value=raw["new_value"],
            actor=raw["actor"],
            reason=raw["reason"],
        )
        if expected_hash != raw["entry_hash"]:
            report.add(
                "error",
                "review_log.csv",
                record.line,
                "entry_hash",
                "哈希校验失败：日志内容与 entry_hash 不匹配",
            )
        expected_prev = raw["entry_hash"]

        if previous_timestamp is not None and item.timestamp < previous_timestamp:
            report.add(
                "error",
                "review_log.csv",
                record.line,
                "timestamp",
                "时间戳早于上一条日志，违反追加写入顺序",
            )
        previous_timestamp = item.timestamp

        row_key = tuple(raw[column] for column in EXPECTED_HEADERS["review_log.csv"])
        if row_key in seen_rows:
            report.add(
                "error",
                "review_log.csv",
                record.line,
                "timestamp",
                "检测到完全重复的日志记录",
            )
        seen_rows.add(row_key)

        if item.seed_id not in seeds:
            report.add(
                "error",
                "review_log.csv",
                record.line,
                "seed_id",
                f"审核日志引用的电影不存在：{item.seed_id}",
            )


def validate_knowledge(data_dir: str | Path | None = None) -> ValidationReport:
    """校验知识库目录；返回包含问题列表与统计信息的报告。"""
    directory = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    report = ValidationReport(data_dir=directory)

    seed_records = _load_records(directory, "cult_seed.csv", report)
    source_records = _load_records(directory, "cult_sources.csv", report)
    criterion_records = _load_records(directory, "cult_criteria.csv", report)
    evidence_records = _load_records(directory, "movie_criterion_evidence.csv", report)
    tag_records = _load_records(directory, "cult_tags.csv", report)
    movie_tag_records = _load_records(directory, "movie_cult_tags.csv", report)
    candidate_tag_records = _load_records(directory, "movie_cult_tag_candidates.csv", report)
    log_records = _load_records(directory, "review_log.csv", report)

    seed_by_id: dict[str, CultSeed] = _check_unique(
        seed_records, "cult_seed.csv", "seed_id", report
    )
    _check_unique(seed_records, "cult_seed.csv", "tmdb_id", report, allow_none=True)
    source_by_id: dict[str, CultSource] = _check_unique(
        source_records, "cult_sources.csv", "source_id", report
    )
    criterion_by_code: dict[str, CultCriterion] = _check_unique(
        criterion_records, "cult_criteria.csv", "criterion_code", report
    )
    tag_by_id: dict[str, CultTag] = _check_unique(
        tag_records, "cult_tags.csv", "tag_id", report
    )

    for record in seed_records:
        seed = record.model
        assert isinstance(seed, CultSeed)
        _check_references(
            record,
            "cult_seed.csv",
            "candidate_source_ids",
            seed.candidate_source_ids,
            source_by_id,
            report,
            "候选来源",
        )
        _check_references(
            record,
            "cult_seed.csv",
            "cult_criteria_codes",
            seed.cult_criteria_codes,
            criterion_by_code,
            report,
            "Cult 认定标准",
        )

    for record in evidence_records:
        item = record.model
        assert isinstance(item, CriterionEvidence)
        if item.seed_id not in seed_by_id:
            report.add(
                "error",
                "movie_criterion_evidence.csv",
                record.line,
                "seed_id",
                f"电影不存在：{item.seed_id}",
            )
        elif item.criterion_code not in seed_by_id[item.seed_id].cult_criteria_codes:
            report.add(
                "warning",
                "movie_criterion_evidence.csv",
                record.line,
                "criterion_code",
                "证据对应的标准未在种子的 cult_criteria_codes 中声明",
            )
        if item.criterion_code not in criterion_by_code:
            report.add(
                "error",
                "movie_criterion_evidence.csv",
                record.line,
                "criterion_code",
                f"Cult 认定标准不存在：{item.criterion_code}",
            )
        if item.source_id not in source_by_id:
            report.add(
                "error",
                "movie_criterion_evidence.csv",
                record.line,
                "source_id",
                f"来源不存在：{item.source_id}",
            )
        if item.verification_status == "disputed":
            report.add(
                "warning",
                "movie_criterion_evidence.csv",
                record.line,
                "verification_status",
                "证据标记为 disputed，需人工裁定后才能用于审核",
            )

    _check_approved_rule(seed_records, evidence_records, source_by_id, report)
    _check_movie_tags(movie_tag_records, seed_by_id, tag_by_id, source_by_id, report)
    _check_tag_candidates(
        candidate_tag_records,
        movie_tag_records,
        seed_by_id,
        tag_by_id,
        source_by_id,
        report,
    )
    _check_review_log(log_records, seed_by_id, report)
    _check_status_history(seed_records, log_records, report)

    statuses = [record.model.review_status for record in seed_records]  # type: ignore[attr-defined]
    report.stats = {
        "seeds": len(seed_records),
        "approved": statuses.count("approved"),
        "draft": statuses.count("draft"),
        "pending": statuses.count("pending"),
        "rejected": statuses.count("rejected"),
        "needs_fix": statuses.count("needs_fix"),
        "sources": len(source_records),
        "criteria": len(criterion_records),
        "tags": len(tag_records),
        "evidence": len(evidence_records),
        "evidence_verified": sum(
            1
            for record in evidence_records
            if record.model.verification_status == "verified"  # type: ignore[attr-defined]
        ),
        "evidence_unverified": sum(
            1
            for record in evidence_records
            if record.model.verification_status == "unverified"  # type: ignore[attr-defined]
        ),
        "evidence_disputed": sum(
            1
            for record in evidence_records
            if record.model.verification_status == "disputed"  # type: ignore[attr-defined]
        ),
        "evidence_confirmed": sum(
            1
            for record in evidence_records
            if record.model.human_status == "confirmed"  # type: ignore[attr-defined]
        ),
        "evidence_human_pending": sum(
            1
            for record in evidence_records
            if record.model.human_status == "pending"  # type: ignore[attr-defined]
        ),
        "evidence_human_rejected": sum(
            1
            for record in evidence_records
            if record.model.human_status == "rejected"  # type: ignore[attr-defined]
        ),
        "tag_candidates": len(candidate_tag_records),
        "tag_candidates_confirmed": sum(
            1
            for record in candidate_tag_records
            if record.model.human_status == "confirmed"  # type: ignore[attr-defined]
        ),
        "tag_candidates_pending": sum(
            1
            for record in candidate_tag_records
            if record.model.human_status == "pending"  # type: ignore[attr-defined]
        ),
        "tag_candidates_rejected": sum(
            1
            for record in candidate_tag_records
            if record.model.human_status == "rejected"  # type: ignore[attr-defined]
        ),
        "movie_tags": len(movie_tag_records),
        "manual_tags": sum(
            1 for record in movie_tag_records if record.model.origin == "manual"  # type: ignore[attr-defined]
        ),
        "inferred_tags": sum(
            1 for record in movie_tag_records if record.model.origin == "inferred"  # type: ignore[attr-defined]
        ),
        "review_log": len(log_records),
    }
    return report


def format_report(report: ValidationReport, hide_warnings: bool = False) -> str:
    lines = ["CULTScope 知识库校验", f"目录：{report.data_dir}", ""]
    visible = [
        issue for issue in report.issues if not (hide_warnings and issue.severity == "warning")
    ]
    if visible:
        lines.extend(str(issue) for issue in visible)
        lines.append("")

    stats = report.stats
    lines.append(
        "统计："
        f"电影 {stats.get('seeds', 0)} 部"
        f"（approved {stats.get('approved', 0)}，draft {stats.get('draft', 0)}，"
        f"pending {stats.get('pending', 0)}，rejected {stats.get('rejected', 0)}，"
        f"needs_fix {stats.get('needs_fix', 0)}）；"
        f"来源 {stats.get('sources', 0)}；标准 {stats.get('criteria', 0)}；"
        f"文化标签 {stats.get('tags', 0)}；证据 {stats.get('evidence', 0)}"
        f"（verified {stats.get('evidence_verified', 0)}，"
        f"人工确认 {stats.get('evidence_confirmed', 0)}，"
        f"待人工 {stats.get('evidence_human_pending', 0)}，"
        f"人工驳回 {stats.get('evidence_human_rejected', 0)}，"
        f"unverified {stats.get('evidence_unverified', 0)}，"
        f"disputed {stats.get('evidence_disputed', 0)}）；"
        f"候选标签 {stats.get('tag_candidates', 0)}"
        f"（确认 {stats.get('tag_candidates_confirmed', 0)}，"
        f"待定 {stats.get('tag_candidates_pending', 0)}，"
        f"驳回 {stats.get('tag_candidates_rejected', 0)}）；"
        f"标签映射 {stats.get('movie_tags', 0)}"
        f"（人工 {stats.get('manual_tags', 0)}，推断 {stats.get('inferred_tags', 0)}）；"
        f"审核日志 {stats.get('review_log', 0)} 条"
    )
    result = "通过" if report.ok else "未通过"
    lines.append(
        f"结果：{result}（错误 {len(report.errors)}，警告 {len(report.warnings)}）"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验 CULTScope 知识库 CSV")
    parser.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help="知识库目录，默认 backend/data/knowledge",
    )
    parser.add_argument(
        "--hide-warnings",
        action="store_true",
        help="只显示错误",
    )
    args = parser.parse_args(argv)

    report = validate_knowledge(args.data_dir)
    print(format_report(report, hide_warnings=args.hide_warnings))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
