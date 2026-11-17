"""电影数据读取与统计服务。

数据来源固定为 scripts/clean_movies.py 生成的清洗结果，不使用任何模拟数据。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

BACKEND_DIR = Path(__file__).resolve().parents[2]
CLEAN_CSV = BACKEND_DIR / "data" / "processed" / "cult_movies_clean.csv"

SAMPLE_NOTE = (
    "本页仅展示人工选定的 Cult 电影样本，用于探索性可视化，"
    "不代表邪典电影整体趋势，也不构成统计推断。"
)


def _is_missing(value: object) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _text(value: object, default: str = "") -> str:
    if _is_missing(value):
        return default
    text = str(value).strip()
    return text if text else default


def _optional_int(value: object) -> int | None:
    if _is_missing(value):
        return None
    return int(round(float(value)))


def _optional_float(value: object) -> float | None:
    if _is_missing(value):
        return None
    return float(value)


def _split(value: object) -> list[str]:
    text = _text(value)
    return [item.strip() for item in text.split("|") if item.strip()] if text else []


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def load_movies() -> list[dict]:
    """读取清洗后的 CSV，未生成时抛出 FileNotFoundError。"""
    if not CLEAN_CSV.exists():
        raise FileNotFoundError(
            f"清洗数据不存在：{CLEAN_CSV}，请先运行 scripts/clean_movies.py"
        )

    df = pd.read_csv(CLEAN_CSV, encoding="utf-8-sig")
    movies: list[dict] = []
    for _, row in df.iterrows():
        movies.append(
            {
                "seed_id": int(row["seed_id"]),
                "seed_title": _text(row["seed_title"]),
                "title": _text(row["matched_title"]) or _text(row["seed_title"]),
                "tmdb_id": int(row["tmdb_id"]),
                "release_date": _text(row["release_date"]),
                "release_year": int(row["release_year"]),
                "decade": _text(row["decade"]),
                "runtime": _optional_int(row["runtime"]),
                "vote_average": _optional_float(row["vote_average"]),
                "vote_count": _optional_int(row["vote_count"]),
                "popularity": _optional_float(row["popularity"]),
                "budget": _optional_float(row["budget"]),
                "revenue": _optional_float(row["revenue"]),
                "budget_known": _as_bool(row["budget_known"]),
                "revenue_known": _as_bool(row["revenue_known"]),
                "original_language": _text(row["original_language"], "unknown"),
                "genres": _split(row["genres"]),
                "directors": _split(row["directors"]),
                "keywords": _split(row["keywords"]),
                "production_companies": _split(row["production_companies"]),
                "overview": _text(row["overview"]),
                "tagline": _text(row["tagline"]),
            }
        )
    return movies


def sample_context(sample_size: int) -> dict:
    return {
        "sample_size": sample_size,
        "sample_label": f"{sample_size} 部人工选定的 Cult 电影探索样本",
        "note": SAMPLE_NOTE,
    }


def list_movies(decade: str | None = None, genre: str | None = None) -> dict:
    movies = load_movies()
    filtered = [
        movie
        for movie in movies
        if (not decade or movie["decade"] == decade)
        and (not genre or genre in movie["genres"])
    ]

    return {
        **sample_context(len(movies)),
        "total": len(filtered),
        "movies": filtered,
    }


def get_stats() -> dict:
    movies = load_movies()
    sample_size = len(movies)

    decade_counts: dict[str, int] = {}
    genre_counts: dict[str, int] = {}
    scatter: list[dict] = []

    for movie in movies:
        decade_counts[movie["decade"]] = decade_counts.get(movie["decade"], 0) + 1
        for genre in movie["genres"]:
            genre_counts[genre] = genre_counts.get(genre, 0) + 1

        if movie["vote_average"] is not None and movie["vote_count"] is not None:
            scatter.append(
                {
                    "title": movie["title"],
                    "vote_average": movie["vote_average"],
                    "vote_count": movie["vote_count"],
                    "decade": movie["decade"],
                    "genres": movie["genres"],
                }
            )

    decade_distribution = [
        {"decade": decade, "count": count}
        for decade, count in sorted(decade_counts.items())
    ]
    genre_distribution = [
        {"genre": genre, "count": count}
        for genre, count in sorted(
            genre_counts.items(), key=lambda item: (-item[1], item[0])
        )
    ]

    return {
        **sample_context(sample_size),
        "decade_distribution": decade_distribution,
        "genre_distribution": genre_distribution,
        "rating_scatter": scatter,
        "filters": {
            "decades": [item["decade"] for item in decade_distribution],
            "genres": [item["genre"] for item in genre_distribution],
        },
        "budget_known_count": sum(1 for movie in movies if movie["budget_known"]),
        "revenue_known_count": sum(1 for movie in movies if movie["revenue_known"]),
    }
