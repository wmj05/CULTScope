"""IMDb 聚合统计只读接口的响应结构。

字段与 scripts/aggregate_imdb.py 产出的 imdb_aggregate.json 契约保持一致，
仅额外补充 scope_note 说明统计口径。
"""

from __future__ import annotations

from pydantic import BaseModel


class ImdbInputSource(BaseModel):
    """聚合输入文件的可审计标识（不包含本机绝对路径）。"""

    sha256: str
    file_bytes: int
    label: str


class ImdbCoverage(BaseModel):
    total_movies: int
    rated_movies: int
    unrated_movies: int
    coverage_ratio: float
    orphan_ratings: int


class ImdbYearBucket(BaseModel):
    total_movies: int
    rated_movies: int


class ImdbYearDistribution(BaseModel):
    per_year: dict[str, ImdbYearBucket]
    missing_year: int
    invalid_year: int
    future_year: int


class ImdbYearTrendEntry(BaseModel):
    """某年份的评分趋势。

    rating_mean 的分母是 valid_rating_count，votes_mean 的分母是
    valid_votes_count；分母为 0 时对应均值为 null。
    """

    rated_count: int
    valid_rating_count: int
    valid_votes_count: int
    rating_mean: float | None = None
    votes_mean: float | None = None


class ImdbQualityFlags(BaseModel):
    invalid_ratings_skipped: int
    invalid_votes_skipped: int


class ImdbDuplicateCounts(BaseModel):
    basics_duplicate_tconst: int
    ratings_duplicate_tconst: int


class ImdbAggregateConstraints(BaseModel):
    max_rows_per_table: int | None = None
    early_valid_year: int
    future_year_cutoff: int
    rating_bucket_width: float
    votes_bucket_definition: list[str]
    duplicate_policy: str


class ImdbAggregatesResponse(BaseModel):
    generated_at: str
    basics_input: ImdbInputSource
    ratings_input: ImdbInputSource
    aggregate_constraints: ImdbAggregateConstraints
    coverage: ImdbCoverage
    year_distribution: ImdbYearDistribution
    genre_distribution: dict[str, int]
    rating_distribution: dict[str, int]
    votes_distribution: dict[str, int]
    year_rating_trend: dict[str, ImdbYearTrendEntry]
    quality_flags: ImdbQualityFlags
    duplicate_counts: ImdbDuplicateCounts
    scope_note: str
