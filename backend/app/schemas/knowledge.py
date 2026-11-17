"""第三阶段知识库的数据结构定义。

区分三类信息：
- TMDb API 字段：tmdb_id、imdb_id 等外部事实；
- 人工标注：候选来源、Cult 认定依据、审核状态、文化标签；
- 算法推断：后续阶段的标签建议与网络统计（本模块暂不实现）。
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

REVIEW_LOG_GENESIS = "GENESIS"
HASH_PATTERN = r"^[0-9a-f]{64}$"

SeedStatus = Literal["draft", "pending", "approved", "rejected", "needs_fix"]
ConfidenceLevel = Literal["high", "medium", "low", "unknown"]
ReliabilityTier = Literal["T1", "T2", "T3"]
VerificationStatus = Literal["unverified", "verified", "disputed"]
HumanStatus = Literal["pending", "confirmed", "rejected"]
SourceType = Literal["academic", "institution", "database", "media", "community", "other"]
TagDimension = Literal["aesthetic", "theme", "production", "reception", "influence"]
TagStatus = Literal["active", "deprecated"]
TagOrigin = Literal["manual", "inferred"]

# 本项目的审核状态迁移约定，不是 Cult 研究的普遍规则。
ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"pending"},
    "pending": {"approved", "rejected", "needs_fix"},
    "needs_fix": {"pending"},
    "rejected": {"pending"},
    "approved": {"needs_fix"},
}


def validate_status_transition(old_status: str, new_status: str) -> None:
    """校验审核状态迁移；重复提交与越级迁移都会被拒绝。"""
    if old_status == new_status:
        raise ValueError(f"重复提交：review_status 已经是 {old_status}")
    allowed = ALLOWED_STATUS_TRANSITIONS.get(old_status, set())
    if new_status not in allowed:
        raise ValueError(f"非法状态迁移：{old_status} → {new_status}")

SeedId = Annotated[str, Field(pattern=r"^CS-\d{4}$")]
SourceId = Annotated[str, Field(pattern=r"^S-\d{3}$")]
CriterionCode = Annotated[str, Field(pattern=r"^C[1-8]$")]
TagId = Annotated[str, Field(pattern=r"^[a-z0-9_]{3,64}$")]


class KnowledgeBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CultSeed(KnowledgeBaseModel):
    seed_id: SeedId
    title: str = Field(min_length=1)
    original_title: str = ""
    year: int = Field(ge=1888, le=2100)
    tmdb_id: int | None = Field(default=None, gt=0)
    imdb_id: str | None = Field(default=None, pattern=r"^tt\d{7,8}$")
    candidate_source_ids: list[SourceId] = Field(default_factory=list)
    cult_criteria_codes: list[CriterionCode] = Field(default_factory=list)
    review_status: SeedStatus = "draft"
    confidence: ConfidenceLevel = "unknown"
    reviewer: str = ""
    reviewed_at: datetime | None = None
    notes: str = ""

    @model_validator(mode="after")
    def check_review_fields(self) -> "CultSeed":
        if bool(self.reviewer) != bool(self.reviewed_at):
            raise ValueError("reviewer 与 reviewed_at 必须同时填写或同时留空")
        if self.review_status == "approved" and not (self.reviewer and self.reviewed_at):
            raise ValueError("approved 电影必须填写 reviewer 和 reviewed_at")
        return self


class CultSource(KnowledgeBaseModel):
    source_id: SourceId
    title: str = Field(min_length=1)
    source_type: SourceType
    url: HttpUrl
    publisher: str = Field(min_length=1)
    published_year: int | None = Field(default=None, ge=1800, le=2100)
    language: str = Field(min_length=2, max_length=16)
    reliability_tier: ReliabilityTier
    notes: str = ""


class CultCriterion(KnowledgeBaseModel):
    criterion_code: CriterionCode
    name_zh: str = Field(min_length=1)
    name_en: str = Field(min_length=1)
    definition: str = Field(min_length=10)
    evidence_requirement: str = Field(min_length=10)
    exclusion_note: str = Field(min_length=5)
    version: float = Field(gt=0)


class CriterionEvidence(KnowledgeBaseModel):
    """一条证据只对应一部电影、一个标准、一个来源。

    verification_status 记录“来源正文是否确实支持该结论”：
    - unverified：尚未逐字核对来源正文；
    - verified：已抓取来源正文并确认其文字支持 evidence_summary；
    - disputed：来源之间存在冲突，需人工裁定。

    human_status 记录“人工是否确认该证据支持对应标准”：
    - pending：尚未人工确认；
    - confirmed：人工确认；
    - rejected：人工驳回。
    两个字段相互独立；verified 不代表人工通过。
    """

    seed_id: SeedId
    criterion_code: CriterionCode
    source_id: SourceId
    evidence_summary: str = Field(min_length=5)
    locator: str = Field(min_length=1)
    verification_status: VerificationStatus = "unverified"
    human_status: HumanStatus = "pending"
    confirmed_by: str = ""
    confirmed_at: datetime | None = None
    added_by: str = Field(min_length=1)
    added_at: datetime

    @field_validator("confirmed_at")
    @classmethod
    def check_confirmed_at_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("confirmed_at 必须包含时区")
        return value

    @model_validator(mode="after")
    def check_human_confirmation(self) -> "CriterionEvidence":
        if self.human_status == "pending":
            if self.confirmed_by or self.confirmed_at:
                raise ValueError("human_status=pending 时 confirmed_by 与 confirmed_at 必须留空")
        elif not (self.confirmed_by and self.confirmed_at):
            raise ValueError("confirmed/rejected 证据必须填写 confirmed_by 和 confirmed_at")
        return self


class CultTag(KnowledgeBaseModel):
    tag_id: TagId
    label_zh: str = Field(min_length=1)
    label_en: str = Field(min_length=1)
    dimension: TagDimension
    definition: str = Field(min_length=10)
    inclusion_criteria: str = Field(min_length=5)
    exclusion_criteria: str = Field(min_length=5)
    status: TagStatus = "active"
    version: float = Field(gt=0)


class MovieCultTag(KnowledgeBaseModel):
    seed_id: SeedId
    tag_id: TagId
    origin: TagOrigin
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: str = ""
    source_ids: list[SourceId] = Field(default_factory=list)
    rule_id: str = ""
    annotator: str = ""
    reviewed: bool = False
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def check_origin_requirements(self) -> "MovieCultTag":
        if self.origin == "manual":
            if not self.evidence:
                raise ValueError("人工标签必须填写 evidence")
            if not self.source_ids:
                raise ValueError("人工标签必须填写 source_ids")
            if not self.annotator:
                raise ValueError("人工标签必须填写 annotator")
        if self.origin == "inferred":
            if not self.rule_id:
                raise ValueError("推断标签必须填写 rule_id")
            if self.confidence is None:
                raise ValueError("推断标签必须填写 confidence")
        return self


class MovieCultTagCandidate(KnowledgeBaseModel):
    """AI 或规则提出的候选标签，与正式 movie_cult_tags 完全分离。

    只有 human_status=confirmed 后，才允许提升为 origin=manual 的正式标签。
    """

    seed_id: SeedId
    tag_id: TagId
    evidence: str = Field(min_length=5)
    source_ids: list[SourceId] = Field(min_length=1)
    proposed_by: str = Field(min_length=1)
    proposed_at: datetime
    human_status: HumanStatus = "pending"
    confirmed_by: str = ""
    confirmed_at: datetime | None = None

    @field_validator("confirmed_at")
    @classmethod
    def check_confirmed_at_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("confirmed_at 必须包含时区")
        return value

    @model_validator(mode="after")
    def check_human_confirmation(self) -> "MovieCultTagCandidate":
        if self.human_status == "pending":
            if self.confirmed_by or self.confirmed_at:
                raise ValueError("human_status=pending 时 confirmed_by 与 confirmed_at 必须留空")
        elif not (self.confirmed_by and self.confirmed_at):
            raise ValueError("confirmed/rejected 候选标签必须填写 confirmed_by 和 confirmed_at")
        return self


class ReviewLogEntry(KnowledgeBaseModel):
    timestamp: datetime
    seed_id: SeedId
    field: str = Field(min_length=1)
    old_value: str = ""
    new_value: str = ""
    actor: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    prev_hash: str
    entry_hash: str = Field(pattern=HASH_PATTERN)

    @field_validator("timestamp")
    @classmethod
    def check_timestamp_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp 必须包含时区")
        return value

    @field_validator("prev_hash")
    @classmethod
    def check_prev_hash(cls, value: str) -> str:
        if value == REVIEW_LOG_GENESIS:
            return value
        if len(value) == 64 and all(char in "0123456789abcdef" for char in value):
            return value
        raise ValueError("prev_hash 必须是 GENESIS 或 64 位小写 SHA-256")

    @model_validator(mode="after")
    def check_review_status_values(self) -> "ReviewLogEntry":
        if self.field == "review_status":
            allowed = {"draft", "pending", "approved", "rejected", "needs_fix", ""}
            if self.old_value not in allowed:
                raise ValueError(f"旧审核状态非法：{self.old_value}")
            if self.new_value not in allowed:
                raise ValueError(f"新审核状态非法：{self.new_value}")
        if self.old_value == self.new_value:
            raise ValueError("old_value 与 new_value 不能相同")
        return self


def compute_review_entry_hash(
    *,
    prev_hash: str,
    timestamp: str,
    seed_id: str,
    field: str,
    old_value: str,
    new_value: str,
    actor: str,
    reason: str,
) -> str:
    """计算审核日志的哈希链节点，写入方必须使用与校验器相同的字段顺序。"""
    payload = "|".join(
        [prev_hash, timestamp, seed_id, field, old_value, new_value, actor, reason]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
