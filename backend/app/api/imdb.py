"""IMDb 聚合统计只读接口。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.schemas.imdb import ImdbAggregatesResponse
from app.services import imdb_aggregate_service

router = APIRouter(prefix="/api/imdb", tags=["imdb"])


def get_aggregate_path() -> Path:
    """测试可通过 dependency_overrides 指向临时聚合 JSON。"""
    return imdb_aggregate_service.AGGREGATE_JSON


@router.get(
    "/aggregates",
    response_model=ImdbAggregatesResponse,
    summary="IMDb 聚合统计（只读快照）",
)
def get_imdb_aggregates(path: Path = Depends(get_aggregate_path)) -> dict:
    try:
        return imdb_aggregate_service.load_aggregates(path)
    except (
        imdb_aggregate_service.AggregateUnavailable,
        imdb_aggregate_service.AggregateInvalid,
    ) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
