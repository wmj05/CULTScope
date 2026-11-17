"""Cult 知识库只读查询服务。

数据全部来自 backend/data/knowledge 下的 CSV，不做缓存、不写文件。
读取时复用审核锁，保证不会在事务写入中途读取到跨文件不一致的数据。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services import review_store

ELIGIBLE_TIERS = {"T1", "T2"}
REVIEW_STATUSES = ("draft", "pending", "approved", "rejected", "needs_fix")
SCOPE_NOTE = (
    "统计覆盖全部电影，包含 draft/pending 的待审核证据与候选标签；"
    "approved_scope 单独汇总已批准电影，避免把待审核数据误当作正式结论。"
)

REQUIRED_COLUMNS = {
    "cult_seed.csv": (
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
    ),
    "cult_sources.csv": (
        "source_id",
        "title",
        "url",
        "publisher",
        "reliability_tier",
    ),
    "cult_criteria.csv": (
        "criterion_code",
        "name_zh",
        "name_en",
        "definition",
        "evidence_requirement",
        "exclusion_note",
        "version",
    ),
    "movie_criterion_evidence.csv": (
        "seed_id",
        "criterion_code",
        "source_id",
        "evidence_summary",
        "locator",
        "verification_status",
        "human_status",
        "confirmed_by",
        "confirmed_at",
    ),
    "cult_tags.csv": (
        "tag_id",
        "label_zh",
        "label_en",
        "dimension",
        "definition",
        "inclusion_criteria",
        "exclusion_criteria",
        "version",
    ),
    "movie_cult_tags.csv": (
        "seed_id",
        "tag_id",
        "origin",
        "confidence",
        "evidence",
        "source_ids",
        "annotator",
        "reviewed",
        "updated_at",
    ),
    "movie_cult_tag_candidates.csv": (
        "seed_id",
        "tag_id",
        "evidence",
        "source_ids",
        "proposed_by",
        "proposed_at",
        "human_status",
        "confirmed_by",
        "confirmed_at",
    ),
}


class MovieNotFound(LookupError):
    """请求的电影 ID 不在知识库中。"""


class KnowledgeDataError(RuntimeError):
    """CSV 缺失、损坏或关联记录不完整，无法安全返回数据。"""


def _text(value: object) -> str:
    return str(value or "").strip()


def _split(value: object) -> list[str]:
    text = _text(value)
    return [item.strip() for item in text.split("|") if item.strip()] if text else []


def _int(value: object, field: str) -> int:
    try:
        return int(_text(value))
    except ValueError:
        raise KnowledgeDataError(f"知识库字段格式异常：{field}") from None


def _optional_int(value: object, field: str) -> int | None:
    text = _text(value)
    if not text:
        return None
    return _int(text, field)


def _optional_float(value: object, field: str) -> float | None:
    text = _text(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        raise KnowledgeDataError(f"知识库字段格式异常：{field}") from None


def _bool(value: object) -> bool:
    return _text(value).lower() in {"true", "1", "yes", "y"}


@dataclass(frozen=True)
class Snapshot:
    seeds: list[dict[str, str]]
    sources: dict[str, dict[str, str]]
    criteria: dict[str, dict[str, str]]
    tags: dict[str, dict[str, str]]
    evidence: list[dict[str, str]]
    formal_tags: list[dict[str, str]]
    candidates: list[dict[str, str]]
    evidence_by_seed: dict[str, list[dict[str, str]]]
    formal_by_seed: dict[str, list[dict[str, str]]]
    candidates_by_seed: dict[str, list[dict[str, str]]]

    def seed(self, seed_id: str) -> dict[str, str]:
        for row in self.seeds:
            if row["seed_id"] == seed_id:
                return row
        raise MovieNotFound(f"电影不存在：{seed_id}")

    def source(self, source_id: str) -> dict[str, str]:
        try:
            return self.sources[source_id]
        except KeyError:
            raise KnowledgeDataError(f"证据引用的来源不存在：{source_id}") from None

    def criterion(self, code: str) -> dict[str, str]:
        try:
            return self.criteria[code]
        except KeyError:
            raise KnowledgeDataError(f"关联的 Cult 标准不存在：{code}") from None

    def tag(self, tag_id: str) -> dict[str, str]:
        try:
            return self.tags[tag_id]
        except KeyError:
            raise KnowledgeDataError(f"关联的文化标签不存在：{tag_id}") from None


def _load(data_dir: Path | None = None) -> Snapshot:
    try:
        raw = review_store.read_snapshot(data_dir)
    except FileNotFoundError:
        raise KnowledgeDataError("知识库文件缺失，暂时无法读取") from None
    except OSError:
        raise KnowledgeDataError("知识库文件读取失败") from None

    try:
        for filename, columns in REQUIRED_COLUMNS.items():
            for row in raw[filename]:
                if any(column not in row for column in columns):
                    raise KnowledgeDataError(
                        f"知识库字段不完整，暂时无法读取：{filename}"
                    )
        seeds = raw["cult_seed.csv"]
        sources = {row["source_id"]: row for row in raw["cult_sources.csv"]}
        criteria = {row["criterion_code"]: row for row in raw["cult_criteria.csv"]}
        tags = {row["tag_id"]: row for row in raw["cult_tags.csv"]}
        evidence = raw["movie_criterion_evidence.csv"]
        formal_tags = raw["movie_cult_tags.csv"]
        candidates = raw["movie_cult_tag_candidates.csv"]
    except KeyError:
        raise KnowledgeDataError("知识库表头或关联字段缺失，暂时无法读取") from None

    evidence_by_seed: dict[str, list[dict[str, str]]] = {}
    for row in evidence:
        evidence_by_seed.setdefault(row["seed_id"], []).append(row)
    formal_by_seed: dict[str, list[dict[str, str]]] = {}
    for row in formal_tags:
        formal_by_seed.setdefault(row["seed_id"], []).append(row)
    candidates_by_seed: dict[str, list[dict[str, str]]] = {}
    for row in candidates:
        candidates_by_seed.setdefault(row["seed_id"], []).append(row)

    return Snapshot(
        seeds=seeds,
        sources=sources,
        criteria=criteria,
        tags=tags,
        evidence=evidence,
        formal_tags=formal_tags,
        candidates=candidates,
        evidence_by_seed=evidence_by_seed,
        formal_by_seed=formal_by_seed,
        candidates_by_seed=candidates_by_seed,
    )


def _criterion_dict(row: dict[str, str]) -> dict:
    return {
        "criterion_code": row["criterion_code"],
        "name_zh": row["name_zh"],
        "name_en": row["name_en"],
        "definition": row["definition"],
        "evidence_requirement": row["evidence_requirement"],
        "exclusion_note": row["exclusion_note"],
        "version": _optional_float(row["version"], "version") or 0.0,
    }


def _tag_dict(row: dict[str, str]) -> dict:
    return {
        "tag_id": row["tag_id"],
        "label_zh": row["label_zh"],
        "label_en": row["label_en"],
        "dimension": row["dimension"],
        "definition": row["definition"],
        "inclusion_criteria": row["inclusion_criteria"],
        "exclusion_criteria": row["exclusion_criteria"],
        "version": _optional_float(row["version"], "version") or 0.0,
    }


def _is_confirmed_verified(row: dict[str, str]) -> bool:
    return (
        row["verification_status"] == "verified"
        and row["human_status"] == "confirmed"
    )


def _is_tier_eligible(row: dict[str, str], snapshot: Snapshot) -> bool:
    return snapshot.source(row["source_id"])["reliability_tier"] in ELIGIBLE_TIERS


def _eligible_confirmed_codes(
    seed_id: str, declared: list[str], snapshot: Snapshot
) -> set[str]:
    codes: set[str] = set()
    for row in snapshot.evidence_by_seed.get(seed_id, []):
        code = row["criterion_code"]
        if code not in declared or not _is_confirmed_verified(row):
            continue
        if _is_tier_eligible(row, snapshot):
            codes.add(code)
    return codes


def _formal_tag_count(seed_id: str, snapshot: Snapshot) -> int:
    return len(snapshot.formal_by_seed.get(seed_id, []))


def _movie_summary(row: dict[str, str], snapshot: Snapshot) -> dict:
    declared = _split(row["cult_criteria_codes"])
    return {
        "seed_id": row["seed_id"],
        "title": row["title"],
        "original_title": row["original_title"],
        "year": _int(row["year"], "year"),
        "review_status": row["review_status"],
        "confirmed_criteria_count": len(
            _eligible_confirmed_codes(row["seed_id"], declared, snapshot)
        ),
        "formal_tag_count": _formal_tag_count(row["seed_id"], snapshot),
    }


def list_movies(
    status: str = "approved",
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    data_dir: Path | None = None,
) -> dict:
    snapshot = _load(data_dir)
    rows = [
        row
        for row in snapshot.seeds
        if status == "all" or row["review_status"] == status
    ]
    if q:
        needle = q.strip().casefold()
        rows = [
            row
            for row in rows
            if any(
                needle in _text(row[field]).casefold()
                for field in ("title", "original_title", "seed_id", "imdb_id", "tmdb_id")
            )
        ]
    rows.sort(key=lambda row: row["seed_id"])
    total = len(rows)
    page = rows[offset : offset + limit]
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "status": status,
        "items": [_movie_summary(row, snapshot) for row in page],
    }


def get_movie(seed_id: str, data_dir: Path | None = None) -> dict:
    snapshot = _load(data_dir)
    seed = snapshot.seed(seed_id)
    declared = _split(seed["cult_criteria_codes"])

    criteria: list[dict] = []
    for code in declared:
        definition = _criterion_dict(snapshot.criterion(code))
        evidence = [
            row
            for row in snapshot.evidence_by_seed.get(seed_id, [])
            if row["criterion_code"] == code
        ]
        confirmed = [row for row in evidence if _is_confirmed_verified(row)]
        eligible = [row for row in confirmed if _is_tier_eligible(row, snapshot)]
        criteria.append(
            {
                **definition,
                "human_confirmed": bool(confirmed),
                "tier_eligible_confirmed": bool(eligible),
                "confirmed_evidence_count": len(confirmed),
                "tier_eligible_evidence_count": len(eligible),
                "pending_evidence_count": sum(
                    1 for row in evidence if row["human_status"] == "pending"
                ),
                "rejected_evidence_count": sum(
                    1 for row in evidence if row["human_status"] == "rejected"
                ),
            }
        )

    tags = []
    for row in snapshot.formal_by_seed.get(seed_id, []):
        definition = _tag_dict(snapshot.tag(row["tag_id"]))
        tags.append(
            {
                **definition,
                "seed_id": seed_id,
                "origin": row["origin"],
                "confidence": _optional_float(row["confidence"], "confidence"),
                "evidence": row["evidence"],
                "source_ids": _split(row["source_ids"]),
                "annotator": row["annotator"],
                "reviewed": _bool(row["reviewed"]),
                "updated_at": _text(row["updated_at"]) or None,
            }
        )

    return {
        "seed_id": seed["seed_id"],
        "title": seed["title"],
        "original_title": seed["original_title"],
        "year": _int(seed["year"], "year"),
        "tmdb_id": _optional_int(seed["tmdb_id"], "tmdb_id"),
        "imdb_id": _text(seed["imdb_id"]) or None,
        "review_status": seed["review_status"],
        "confidence": seed["confidence"] or "unknown",
        "reviewer": seed["reviewer"],
        "reviewed_at": _text(seed["reviewed_at"]) or None,
        "notes": seed["notes"],
        "candidate_source_ids": _split(seed["candidate_source_ids"]),
        "declared_criteria_codes": declared,
        "confirmed_criteria_count": len(
            _eligible_confirmed_codes(seed_id, declared, snapshot)
        ),
        "formal_tag_count": len(tags),
        "candidate_tag_count": len(snapshot.candidates_by_seed.get(seed_id, [])),
        "criteria": criteria,
        "tags": tags,
    }


def list_evidence(
    seed_id: str,
    include_pending: bool = False,
    data_dir: Path | None = None,
) -> dict:
    snapshot = _load(data_dir)
    snapshot.seed(seed_id)
    rows = list(snapshot.evidence_by_seed.get(seed_id, []))
    if not include_pending:
        rows = [row for row in rows if row["human_status"] == "confirmed"]
    rows.sort(key=lambda row: (row["criterion_code"], row["source_id"]))

    items: list[dict] = []
    for row in rows:
        source = snapshot.source(row["source_id"])
        criterion = snapshot.criterion(row["criterion_code"])
        items.append(
            {
                "criterion_code": row["criterion_code"],
                "criterion_name_zh": criterion["name_zh"],
                "criterion_name_en": criterion["name_en"],
                "source_id": row["source_id"],
                "source_title": source["title"],
                "source_tier": source["reliability_tier"],
                "source_url": source["url"],
                "publisher": source["publisher"],
                "evidence_summary": row["evidence_summary"],
                "locator": row["locator"],
                "verification_status": row["verification_status"],
                "human_status": row["human_status"],
                "confirmed_by": row["confirmed_by"],
                "confirmed_at": _text(row["confirmed_at"]) or None,
                "approved_threshold_eligible": _is_confirmed_verified(row)
                and _is_tier_eligible(row, snapshot),
            }
        )

    return {
        "seed_id": seed_id,
        "include_pending": include_pending,
        "total": len(items),
        "items": items,
    }


def _formal_tag_row(row: dict[str, str], snapshot: Snapshot) -> dict:
    definition = _tag_dict(snapshot.tag(row["tag_id"]))
    return {
        **definition,
        "seed_id": row["seed_id"],
        "origin": row["origin"],
        "confidence": _optional_float(row["confidence"], "confidence"),
        "evidence": row["evidence"],
        "source_ids": _split(row["source_ids"]),
        "annotator": row["annotator"],
        "reviewed": _bool(row["reviewed"]),
        "updated_at": _text(row["updated_at"]) or None,
    }


def _candidate_tag_row(row: dict[str, str], snapshot: Snapshot) -> dict:
    definition = _tag_dict(snapshot.tag(row["tag_id"]))
    return {
        **definition,
        "seed_id": row["seed_id"],
        "record_type": "candidate",
        "human_status": row["human_status"],
        "evidence": row["evidence"],
        "source_ids": _split(row["source_ids"]),
        "proposed_by": row["proposed_by"],
        "proposed_at": row["proposed_at"],
        "confirmed_by": row["confirmed_by"],
        "confirmed_at": _text(row["confirmed_at"]) or None,
    }


def list_movie_tags(
    seed_id: str,
    include_candidates: bool = False,
    data_dir: Path | None = None,
) -> dict:
    snapshot = _load(data_dir)
    snapshot.seed(seed_id)
    formal_rows = sorted(
        snapshot.formal_by_seed.get(seed_id, []), key=lambda row: row["tag_id"]
    )
    candidate_rows = snapshot.candidates_by_seed.get(seed_id, [])
    return {
        "seed_id": seed_id,
        "include_candidates": include_candidates,
        "formal_total": len(formal_rows),
        "candidates_total": len(candidate_rows),
        "formal": [_formal_tag_row(row, snapshot) for row in formal_rows],
        "candidates": (
            [_candidate_tag_row(row, snapshot) for row in candidate_rows]
            if include_candidates
            else []
        ),
    }


def list_criteria(data_dir: Path | None = None) -> dict:
    snapshot = _load(data_dir)
    rows = sorted(snapshot.criteria.values(), key=lambda row: row["criterion_code"])
    return {"total": len(rows), "items": [_criterion_dict(row) for row in rows]}


def list_tag_dictionary(data_dir: Path | None = None) -> dict:
    snapshot = _load(data_dir)
    rows = sorted(
        snapshot.tags.values(), key=lambda row: (row["dimension"], row["tag_id"])
    )
    return {"total": len(rows), "items": [_tag_dict(row) for row in rows]}


def get_stats(data_dir: Path | None = None) -> dict:
    snapshot = _load(data_dir)
    status_counts = {status: 0 for status in REVIEW_STATUSES}
    for row in snapshot.seeds:
        status_counts[row["review_status"]] = (
            status_counts.get(row["review_status"], 0) + 1
        )

    evidence_counts = {"confirmed": 0, "pending": 0, "rejected": 0}
    for row in snapshot.evidence:
        status = row["human_status"]
        evidence_counts[status] = evidence_counts.get(status, 0) + 1

    formal_manual = sum(1 for row in snapshot.formal_tags if row["origin"] == "manual")
    formal_inferred = sum(
        1 for row in snapshot.formal_tags if row["origin"] == "inferred"
    )

    candidate_counts = {"confirmed": 0, "pending": 0, "rejected": 0}
    for row in snapshot.candidates:
        status = row["human_status"]
        candidate_counts[status] = candidate_counts.get(status, 0) + 1

    approved_ids = {
        row["seed_id"] for row in snapshot.seeds if row["review_status"] == "approved"
    }
    return {
        "movies_total": len(snapshot.seeds),
        "review_status_counts": status_counts,
        "evidence": {
            "scope": "all_movies",
            "total": len(snapshot.evidence),
            **evidence_counts,
        },
        "formal_tags": {
            "scope": "all_movies",
            "total": len(snapshot.formal_tags),
            "manual": formal_manual,
            "inferred": formal_inferred,
        },
        "candidate_tags": {
            "scope": "all_movies",
            "total": len(snapshot.candidates),
            **candidate_counts,
        },
        "approved_scope": {
            "movies": len(approved_ids),
            "evidence_confirmed": sum(
                1
                for row in snapshot.evidence
                if row["seed_id"] in approved_ids
                and row["human_status"] == "confirmed"
            ),
            "formal_tags": sum(
                1 for row in snapshot.formal_tags if row["seed_id"] in approved_ids
            ),
            "candidate_tags_confirmed": sum(
                1
                for row in snapshot.candidates
                if row["seed_id"] in approved_ids
                and row["human_status"] == "confirmed"
            ),
        },
        "scope_note": SCOPE_NOTE,
    }
