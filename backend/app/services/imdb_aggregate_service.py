"""IMDb 聚合统计只读服务。

只读取 aggregate_imdb.py 生成的轻量 JSON，不触碰大型 IMDb CSV，
也不会触发下载、摄取或重新聚合。
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
AGGREGATE_JSON = BACKEND_DIR / "data" / "processed" / "large" / "imdb_aggregate.json"

_DRIVE_ABSOLUTE = re.compile(r"^[A-Za-z]:")
_PATH_SEPARATORS = re.compile(r"[\\/]")
EXTERNAL_PREFIX = "external:"

SCOPE_NOTE = (
    "本统计只代表当前 IMDb 公开数据快照的聚合结果，不代表全体电影的无偏估计；"
    "IMDb 评分仅作参考，不作为电影质量的唯一评价标准。"
)

REQUIRED_TOP_LEVEL = (
    "generated_at",
    "basics_input",
    "ratings_input",
    "aggregate_constraints",
    "coverage",
    "year_distribution",
    "genre_distribution",
    "rating_distribution",
    "votes_distribution",
    "year_rating_trend",
    "quality_flags",
    "duplicate_counts",
)

REQUIRED_SECTIONS = {
    "basics_input": ("sha256", "file_bytes", "label"),
    "ratings_input": ("sha256", "file_bytes", "label"),
    "aggregate_constraints": (
        "max_rows_per_table",
        "early_valid_year",
        "future_year_cutoff",
        "rating_bucket_width",
        "votes_bucket_definition",
        "duplicate_policy",
    ),
    "coverage": (
        "total_movies",
        "rated_movies",
        "unrated_movies",
        "coverage_ratio",
        "orphan_ratings",
    ),
    "year_distribution": ("per_year", "missing_year", "invalid_year", "future_year"),
    "quality_flags": ("invalid_ratings_skipped", "invalid_votes_skipped"),
    "duplicate_counts": ("basics_duplicate_tconst", "ratings_duplicate_tconst"),
}

COUNT_DISTRIBUTIONS = ("genre_distribution", "rating_distribution", "votes_distribution")


class AggregateUnavailable(RuntimeError):
    """聚合 JSON 缺失或无法读取。"""


class AggregateInvalid(RuntimeError):
    """聚合 JSON 结构不符合契约。"""


def _require_mapping(value: object, name: str) -> dict:
    if not isinstance(value, dict):
        raise AggregateInvalid(f"IMDb 聚合数据字段 {name} 必须是对象")
    return value


def _require_int_fields(block: dict, fields: tuple[str, ...], name: str) -> None:
    for field_name in fields:
        value = block[field_name]
        if not isinstance(value, int) or isinstance(value, bool):
            raise AggregateInvalid(
                f"IMDb 聚合数据 {name}.{field_name} 必须是整数"
            )


def _require_count_map(value: object, name: str) -> None:
    mapping = _require_mapping(value, name)
    for key, count in mapping.items():
        if not isinstance(key, str) or not isinstance(count, int) or isinstance(count, bool):
            raise AggregateInvalid(f"IMDb 聚合数据 {name} 必须是 字符串→整数 的映射")


def _require_number(value: object, name: str, *, allow_none: bool = False) -> None:
    """只接受有限数值；拒绝布尔、NaN、Infinity、-Infinity。"""
    if value is None and allow_none:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AggregateInvalid(f"IMDb 聚合数据 {name} 必须是有限数值")
    if not math.isfinite(value):
        raise AggregateInvalid(f"IMDb 聚合数据 {name} 必须是有限数值")


def _require_label(value: object, name: str) -> None:
    """校验输入来源标签，允许仓库相对路径或 external:<filename>。

    拒绝 Windows/Unix 绝对路径、UNC 路径、家目录缩写与路径穿越。
    错误信息只包含字段名，不回显原始值，避免泄露危险路径。
    """
    if not isinstance(value, str) or not value.strip():
        raise AggregateInvalid(f"IMDb 聚合数据 {name} 必须是非空字符串")
    label = value.strip()

    if label.startswith(EXTERNAL_PREFIX):
        filename = label[len(EXTERNAL_PREFIX):]
        if (
            not filename
            or filename in {".", ".."}
            or _PATH_SEPARATORS.search(filename)
        ):
            raise AggregateInvalid(
                f"IMDb 聚合数据 {name} 的 external 标签只允许文件名，不允许路径"
            )
        return

    if label.startswith(("/", "\\", "~")) or _DRIVE_ABSOLUTE.match(label):
        raise AggregateInvalid(f"IMDb 聚合数据 {name} 不允许绝对路径")

    if any(part == ".." for part in _PATH_SEPARATORS.split(label)):
        raise AggregateInvalid(f"IMDb 聚合数据 {name} 不允许路径穿越")


def _validate(payload: object) -> dict:
    data = _require_mapping(payload, "顶层")

    missing = [key for key in REQUIRED_TOP_LEVEL if key not in data]
    if missing:
        raise AggregateInvalid(f"IMDb 聚合数据缺少必需字段：{', '.join(missing)}")

    for section, fields in REQUIRED_SECTIONS.items():
        block = _require_mapping(data[section], section)
        absent = [field for field in fields if field not in block]
        if absent:
            raise AggregateInvalid(
                f"IMDb 聚合数据 {section} 缺少字段：{', '.join(absent)}"
            )

    generated_at = data["generated_at"]
    if not isinstance(generated_at, str) or not generated_at.strip():
        raise AggregateInvalid("IMDb 聚合数据 generated_at 无效")

    for name in COUNT_DISTRIBUTIONS:
        _require_count_map(data[name], name)

    # 输入来源标识
    for name in ("basics_input", "ratings_input"):
        block = data[name]
        if not isinstance(block["sha256"], str):
            raise AggregateInvalid(f"IMDb 聚合数据 {name}.sha256 必须是字符串")
        _require_int_fields(block, ("file_bytes",), name)
        _require_label(block["label"], f"{name}.label")

    # 统计口径
    constraints = data["aggregate_constraints"]
    _require_int_fields(
        constraints, ("early_valid_year", "future_year_cutoff"), "aggregate_constraints"
    )
    _require_number(
        constraints["rating_bucket_width"], "aggregate_constraints.rating_bucket_width"
    )
    if constraints["max_rows_per_table"] is not None:
        _require_int_fields(
            constraints, ("max_rows_per_table",), "aggregate_constraints"
        )
    if not isinstance(constraints["votes_bucket_definition"], list) or not all(
        isinstance(item, str) for item in constraints["votes_bucket_definition"]
    ):
        raise AggregateInvalid(
            "IMDb 聚合数据 aggregate_constraints.votes_bucket_definition 必须是字符串列表"
        )
    if not isinstance(constraints["duplicate_policy"], str):
        raise AggregateInvalid(
            "IMDb 聚合数据 aggregate_constraints.duplicate_policy 必须是字符串"
        )

    # 覆盖率
    coverage = data["coverage"]
    _require_int_fields(
        coverage,
        ("total_movies", "rated_movies", "unrated_movies", "orphan_ratings"),
        "coverage",
    )
    _require_number(coverage["coverage_ratio"], "coverage.coverage_ratio")

    # 年份分布
    year_distribution = data["year_distribution"]
    _require_int_fields(
        year_distribution,
        ("missing_year", "invalid_year", "future_year"),
        "year_distribution",
    )
    per_year = _require_mapping(
        year_distribution["per_year"], "year_distribution.per_year"
    )
    for year, bucket in per_year.items():
        bucket = _require_mapping(bucket, f"year_distribution.per_year.{year}")
        absent = [
            field
            for field in ("total_movies", "rated_movies")
            if field not in bucket
        ]
        if absent:
            raise AggregateInvalid(
                f"IMDb 聚合数据 year_distribution.per_year.{year} 缺少字段："
                f"{', '.join(absent)}"
            )
        _require_int_fields(
            bucket, ("total_movies", "rated_movies"), f"year_distribution.per_year.{year}"
        )

    # 年份评分趋势
    trend = _require_mapping(data["year_rating_trend"], "year_rating_trend")
    for year, entry in trend.items():
        entry = _require_mapping(entry, f"year_rating_trend.{year}")
        absent = [
            field
            for field in (
                "rated_count",
                "valid_rating_count",
                "valid_votes_count",
                "rating_mean",
                "votes_mean",
            )
            if field not in entry
        ]
        if absent:
            raise AggregateInvalid(
                f"IMDb 聚合数据 year_rating_trend.{year} 缺少字段：{', '.join(absent)}"
            )
        _require_int_fields(
            entry,
            ("rated_count", "valid_rating_count", "valid_votes_count"),
            f"year_rating_trend.{year}",
        )
        _require_number(
            entry["rating_mean"], f"year_rating_trend.{year}.rating_mean", allow_none=True
        )
        _require_number(
            entry["votes_mean"], f"year_rating_trend.{year}.votes_mean", allow_none=True
        )

    _require_int_fields(
        data["quality_flags"],
        ("invalid_ratings_skipped", "invalid_votes_skipped"),
        "quality_flags",
    )
    _require_int_fields(
        data["duplicate_counts"],
        ("basics_duplicate_tconst", "ratings_duplicate_tconst"),
        "duplicate_counts",
    )
    return data


def load_aggregates(path: Path | None = None) -> dict:
    """读取并校验聚合 JSON，返回可直接响应的字典。

    错误信息只包含文件名与字段名，不包含本机绝对路径或异常堆栈。
    """
    target = Path(path) if path is not None else AGGREGATE_JSON

    if not target.exists():
        raise AggregateUnavailable(
            "IMDb 聚合数据尚未生成（imdb_aggregate.json），请先运行离线聚合脚本"
        )

    try:
        with target.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise AggregateInvalid("IMDb 聚合数据格式损坏，无法解析") from exc
    except OSError as exc:
        raise AggregateUnavailable("IMDb 聚合数据无法读取") from exc

    data = _validate(payload)
    result = dict(data)
    result["scope_note"] = SCOPE_NOTE
    return result
