"""电影接口的响应数据结构。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Movie(BaseModel):
    seed_id: int
    seed_title: str
    title: str
    tmdb_id: int
    release_date: str
    release_year: int
    decade: str
    runtime: int | None = None
    vote_average: float | None = None
    vote_count: int | None = None
    popularity: float | None = None
    budget: float | None = None
    revenue: float | None = None
    budget_known: bool
    revenue_known: bool
    original_language: str
    genres: list[str] = Field(default_factory=list)
    directors: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    production_companies: list[str] = Field(default_factory=list)
    overview: str = ""
    tagline: str = ""


class DecadeCount(BaseModel):
    decade: str
    count: int


class GenreCount(BaseModel):
    genre: str
    count: int


class ScatterPoint(BaseModel):
    title: str
    vote_average: float
    vote_count: int
    decade: str
    genres: list[str] = Field(default_factory=list)


class FilterOptions(BaseModel):
    decades: list[str] = Field(default_factory=list)
    genres: list[str] = Field(default_factory=list)


class SampleContext(BaseModel):
    sample_size: int
    sample_label: str
    note: str


class MovieListResponse(SampleContext):
    total: int
    movies: list[Movie] = Field(default_factory=list)


class StatsResponse(SampleContext):
    decade_distribution: list[DecadeCount] = Field(default_factory=list)
    genre_distribution: list[GenreCount] = Field(default_factory=list)
    rating_scatter: list[ScatterPoint] = Field(default_factory=list)
    filters: FilterOptions
    budget_known_count: int
    revenue_known_count: int
