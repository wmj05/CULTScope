"""Cult 知识库只读接口的响应结构。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CultMovieSummary(BaseModel):
    seed_id: str
    title: str
    original_title: str
    year: int
    review_status: str
    confirmed_criteria_count: int
    formal_tag_count: int


class CultMovieListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    status: str
    items: list[CultMovieSummary] = Field(default_factory=list)


class CultCriterion(BaseModel):
    criterion_code: str
    name_zh: str
    name_en: str
    definition: str
    evidence_requirement: str
    exclusion_note: str
    version: float


class CultMovieCriterion(CultCriterion):
    human_confirmed: bool
    tier_eligible_confirmed: bool
    confirmed_evidence_count: int
    tier_eligible_evidence_count: int
    pending_evidence_count: int
    rejected_evidence_count: int


class CultTag(BaseModel):
    tag_id: str
    label_zh: str
    label_en: str
    dimension: str
    definition: str
    inclusion_criteria: str
    exclusion_criteria: str
    version: float


class CultMovieTag(CultTag):
    seed_id: str
    origin: str
    confidence: float | None = None
    evidence: str
    source_ids: list[str] = Field(default_factory=list)
    annotator: str
    reviewed: bool
    updated_at: str | None = None


class CultMovieTagCandidate(CultTag):
    seed_id: str
    record_type: Literal["candidate"] = "candidate"
    human_status: str
    evidence: str
    source_ids: list[str] = Field(default_factory=list)
    proposed_by: str
    proposed_at: str
    confirmed_by: str = ""
    confirmed_at: str | None = None


class CultMovieTagsResponse(BaseModel):
    seed_id: str
    include_candidates: bool
    formal_total: int
    candidates_total: int
    formal: list[CultMovieTag] = Field(default_factory=list)
    candidates: list[CultMovieTagCandidate] = Field(default_factory=list)


class CultMovieDetail(BaseModel):
    seed_id: str
    title: str
    original_title: str
    year: int
    tmdb_id: int | None = None
    imdb_id: str | None = None
    review_status: str
    confidence: str
    reviewer: str
    reviewed_at: str | None = None
    notes: str
    candidate_source_ids: list[str] = Field(default_factory=list)
    declared_criteria_codes: list[str] = Field(default_factory=list)
    confirmed_criteria_count: int
    formal_tag_count: int
    candidate_tag_count: int
    criteria: list[CultMovieCriterion] = Field(default_factory=list)
    tags: list[CultMovieTag] = Field(default_factory=list)


class CultEvidenceItem(BaseModel):
    criterion_code: str
    criterion_name_zh: str
    criterion_name_en: str
    source_id: str
    source_title: str
    source_tier: str
    source_url: str
    publisher: str
    evidence_summary: str
    locator: str
    verification_status: str
    human_status: str
    confirmed_by: str = ""
    confirmed_at: str | None = None
    approved_threshold_eligible: bool


class CultEvidenceResponse(BaseModel):
    seed_id: str
    include_pending: bool
    total: int
    items: list[CultEvidenceItem] = Field(default_factory=list)


class CultCriteriaResponse(BaseModel):
    total: int
    items: list[CultCriterion] = Field(default_factory=list)


class CultTagsDictionaryResponse(BaseModel):
    total: int
    items: list[CultTag] = Field(default_factory=list)


class ReviewStatusCounts(BaseModel):
    draft: int
    pending: int
    approved: int
    rejected: int
    needs_fix: int


class EvidenceStats(BaseModel):
    scope: str
    total: int
    confirmed: int
    pending: int
    rejected: int


class FormalTagStats(BaseModel):
    scope: str
    total: int
    manual: int
    inferred: int


class CandidateTagStats(BaseModel):
    scope: str
    total: int
    confirmed: int
    pending: int
    rejected: int


class ApprovedScopeStats(BaseModel):
    movies: int
    evidence_confirmed: int
    formal_tags: int
    candidate_tags_confirmed: int


class CultStatsResponse(BaseModel):
    movies_total: int
    review_status_counts: ReviewStatusCounts
    evidence: EvidenceStats
    formal_tags: FormalTagStats
    candidate_tags: CandidateTagStats
    approved_scope: ApprovedScopeStats
    scope_note: str
