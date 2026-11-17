"""电影数据接口：列表筛选与统计聚合。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas.movie import MovieListResponse, StatsResponse
from app.services import movie_service

router = APIRouter(prefix="/api/movies", tags=["movies"])


def _load_or_500(loader):
    try:
        return loader()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("", response_model=MovieListResponse, summary="电影列表（可按年代、类型筛选）")
def list_movies(
    decade: str | None = Query(None, description="年代，例如 1970s"),
    genre: str | None = Query(None, description="类型名称，例如 恐怖"),
) -> dict:
    return _load_or_500(lambda: movie_service.list_movies(decade=decade, genre=genre))


@router.get("/stats", response_model=StatsResponse, summary="看板统计与筛选项")
def get_stats() -> dict:
    return _load_or_500(movie_service.get_stats)
