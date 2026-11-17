"""Cult 知识库只读接口。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.schemas.cult import (
    CultCriteriaResponse,
    CultEvidenceResponse,
    CultMovieDetail,
    CultMovieListResponse,
    CultMovieTagsResponse,
    CultStatsResponse,
    CultTagsDictionaryResponse,
)
from app.services import cult_service, review_store

router = APIRouter(prefix="/api/cult", tags=["cult"])

CultQueryStatus = Literal[
    "approved", "pending", "draft", "rejected", "needs_fix", "all"
]


def get_data_dir() -> Path:
    """测试可通过 dependency_overrides 指向临时知识库目录。"""
    return review_store.DATA_DIR


def _run(action):
    try:
        return action()
    except cult_service.MovieNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (cult_service.KnowledgeDataError, review_store.ReviewError) as exc:
        raise HTTPException(
            status_code=503, detail=f"知识库暂时不可用：{exc}"
        ) from exc


@router.get("/movies", response_model=CultMovieListResponse, summary="Cult 电影列表")
def list_cult_movies(
    status: CultQueryStatus = Query("approved", description="审核状态；all 表示全部"),
    q: str | None = Query(None, min_length=1, max_length=100, description="中文名、英文名或 ID"),
    limit: int = Query(50, ge=1, le=200, description="每页数量"),
    offset: int = Query(0, ge=0, description="偏移量"),
    data_dir: Path = Depends(get_data_dir),
) -> dict:
    return _run(
        lambda: cult_service.list_movies(
            status=status, q=q, limit=limit, offset=offset, data_dir=data_dir
        )
    )


@router.get(
    "/movies/{seed_id}", response_model=CultMovieDetail, summary="Cult 电影详情"
)
def get_cult_movie(
    seed_id: str, data_dir: Path = Depends(get_data_dir)
) -> dict:
    return _run(lambda: cult_service.get_movie(seed_id, data_dir=data_dir))


@router.get(
    "/movies/{seed_id}/evidence",
    response_model=CultEvidenceResponse,
    summary="电影证据（默认仅人工确认）",
)
def list_cult_evidence(
    seed_id: str,
    include_pending: bool = Query(
        False, description="true 时返回 pending/rejected 证据，并保留人工状态"
    ),
    data_dir: Path = Depends(get_data_dir),
) -> dict:
    return _run(
        lambda: cult_service.list_evidence(
            seed_id, include_pending=include_pending, data_dir=data_dir
        )
    )


@router.get(
    "/movies/{seed_id}/tags",
    response_model=CultMovieTagsResponse,
    summary="电影文化标签（正式与候选严格分离）",
)
def list_cult_tags(
    seed_id: str,
    include_candidates: bool = Query(
        False, description="true 时额外返回候选标签，不并入正式列表"
    ),
    data_dir: Path = Depends(get_data_dir),
) -> dict:
    return _run(
        lambda: cult_service.list_movie_tags(
            seed_id, include_candidates=include_candidates, data_dir=data_dir
        )
    )


@router.get("/criteria", response_model=CultCriteriaResponse, summary="Cult 认定标准字典")
def list_cult_criteria(data_dir: Path = Depends(get_data_dir)) -> dict:
    return _run(lambda: cult_service.list_criteria(data_dir=data_dir))


@router.get("/tags", response_model=CultTagsDictionaryResponse, summary="文化标签字典")
def list_cult_tag_dictionary(data_dir: Path = Depends(get_data_dir)) -> dict:
    return _run(lambda: cult_service.list_tag_dictionary(data_dir=data_dir))


@router.get("/stats", response_model=CultStatsResponse, summary="知识库动态统计")
def get_cult_stats(data_dir: Path = Depends(get_data_dir)) -> dict:
    return _run(lambda: cult_service.get_stats(data_dir=data_dir))
