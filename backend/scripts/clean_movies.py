"""阶段二：清洗阶段一采集的 TMDb 电影数据。

输入：data/processed/cult_movies.csv（只读，不覆盖原始文件）
输出：data/processed/cult_movies_clean.csv

用法（在 backend 目录下）：
    python scripts/clean_movies.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

BACKEND_DIR = Path(__file__).resolve().parents[1]
INPUT_CSV = BACKEND_DIR / "data" / "processed" / "cult_movies.csv"
OUTPUT_CSV = BACKEND_DIR / "data" / "processed" / "cult_movies_clean.csv"

TEXT_COLUMNS = [
    "matched_title",
    "release_date",
    "original_language",
    "genres",
    "directors",
    "keywords",
    "production_companies",
    "overview",
    "tagline",
]

NUMERIC_COLUMNS = [
    "runtime",
    "vote_average",
    "vote_count",
    "popularity",
]

OUTPUT_COLUMNS = [
    "seed_id",
    "seed_title",
    "seed_year",
    "match_status",
    "matched_title",
    "tmdb_id",
    "release_date",
    "release_year",
    "decade",
    "runtime",
    "vote_average",
    "vote_count",
    "popularity",
    "budget_raw",
    "revenue_raw",
    "budget",
    "revenue",
    "budget_known",
    "revenue_known",
    "original_language",
    "genres",
    "genre_count",
    "directors",
    "keywords",
    "keyword_count",
    "production_companies",
    "overview",
    "tagline",
    "fetched_at",
]


def split_multi(value: object) -> list[str]:
    """按 | 拆分多值字段，去空格、去空项、按大小写不敏感去重。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []

    items: list[str] = []
    seen: set[str] = set()
    for part in str(value).split("|"):
        name = part.strip()
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        items.append(name)
    return items


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    report: dict = {"input_rows": len(df)}

    # 1. 只保留 TMDb 匹配成功的记录
    df = df.copy()
    df = df[df["match_status"].eq("matched")]
    report["dropped_unmatched"] = report["input_rows"] - len(df)

    # 2. tmdb_id 缺失与重复处理
    missing_id = df["tmdb_id"].isna()
    report["dropped_missing_id"] = int(missing_id.sum())
    df = df[~missing_id]

    duplicated = df["tmdb_id"].duplicated(keep="first")
    report["duplicate_ids"] = sorted(df.loc[duplicated, "tmdb_id"].astype(int).unique().tolist())
    report["dropped_duplicates"] = int(duplicated.sum())
    df = df[~duplicated]

    df["tmdb_id"] = pd.to_numeric(df["tmdb_id"], errors="coerce").astype("Int64")

    # 3. release_date -> release_year / decade，缺失年份回退种子年份
    release_dt = pd.to_datetime(df["release_date"], errors="coerce")
    release_year = release_dt.dt.year
    fallback_year = pd.to_numeric(df["seed_year"], errors="coerce")
    report["year_fallback"] = int(release_year.isna().sum())
    release_year = release_year.fillna(fallback_year)

    invalid_year = release_year.isna()
    report["dropped_invalid_year"] = int(invalid_year.sum())
    df = df[~invalid_year].copy()
    release_year = release_year[~invalid_year]

    df["release_year"] = release_year.astype(int)
    df["decade"] = (df["release_year"] // 10 * 10).astype(str) + "s"
    df["release_date"] = release_dt[~invalid_year].dt.strftime("%Y-%m-%d").fillna("")

    # 4. 数值列统一转换，无法解析的置空（不填 0）
    for column in NUMERIC_COLUMNS:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df["runtime"] = df["runtime"].round().astype("Int64")
    df["vote_count"] = df["vote_count"].round().astype("Int64")

    # 5. 多值字段拆分清洗后重新拼接，便于后续统计
    genre_lists = df["genres"].map(split_multi)
    keyword_lists = df["keywords"].map(split_multi)
    df["genres"] = genre_lists.map(lambda items: "|".join(items))
    df["genre_count"] = genre_lists.map(len).astype(int)
    df["keywords"] = keyword_lists.map(lambda items: "|".join(items))
    df["keyword_count"] = keyword_lists.map(len).astype(int)

    # 6. budget / revenue 的 0 视为未知值：原始值保留，清洗值置空并加标记
    for column in ("budget", "revenue"):
        raw = pd.to_numeric(df[column], errors="coerce")
        known = raw.notna() & (raw > 0)
        report[f"{column}_zero"] = int((raw == 0).sum())
        report[f"{column}_missing"] = int(raw.isna().sum())
        df[f"{column}_raw"] = raw
        df[column] = raw.where(known)
        df[f"{column}_known"] = known

    # 7. 文本列缺失值处理
    df["matched_title"] = df["matched_title"].fillna(df["seed_title"])
    df["original_language"] = df["original_language"].fillna("unknown")
    df["directors"] = df["directors"].map(
        lambda value: "|".join(split_multi(value))
    )
    for column in ("overview", "tagline", "production_companies"):
        df[column] = df[column].fillna("")

    report["runtime_missing"] = int(df["runtime"].isna().sum())
    report["tagline_missing"] = int(df["tagline"].eq("").sum())

    df = df.sort_values(["release_year", "seed_id"]).reset_index(drop=True)
    report["output_rows"] = len(df)
    report["decade_counts"] = df["decade"].value_counts().sort_index().to_dict()
    report["genre_counts"] = (
        pd.Series([g for items in genre_lists for g in items]).value_counts().to_dict()
    )

    return df[OUTPUT_COLUMNS], report


def print_report(report: dict) -> None:
    print("\n========== 清洗完成 ==========")
    print(f"输入记录：{report['input_rows']} 行")
    print(f"丢弃非 matched：{report['dropped_unmatched']} 行")
    print(f"丢弃 tmdb_id 缺失：{report['dropped_missing_id']} 行")
    dup_ids = ", ".join(str(i) for i in report["duplicate_ids"]) or "无"
    print(f"重复 tmdb_id：{dup_ids}（删除 {report['dropped_duplicates']} 行）")
    print(f"release_year 回退 seed_year：{report['year_fallback']} 行")
    print(f"年份无效丢弃：{report['dropped_invalid_year']} 行")
    print(f"runtime 缺失：{report['runtime_missing']} 行")
    print(f"tagline 为空：{report['tagline_missing']} 行")
    print(
        "budget 为 0 视为未知："
        f"{report['budget_zero']} 行；缺失：{report['budget_missing']} 行"
    )
    print(
        "revenue 为 0 视为未知："
        f"{report['revenue_zero']} 行；缺失：{report['revenue_missing']} 行"
    )
    print(f"输出记录：{report['output_rows']} 行 × {len(OUTPUT_COLUMNS)} 列")
    print("\n年代分布：")
    for decade, count in report["decade_counts"].items():
        print(f"  {decade}: {count} 部")
    print("\n类型分布（按电影数）：")
    for genre, count in report["genre_counts"].items():
        print(f"  {genre}: {count} 部")


def main() -> int:
    if not INPUT_CSV.exists():
        print(f"[错误] 输入文件不存在：{INPUT_CSV}")
        print("请先运行 scripts/fetch_tmdb.py 完成阶段一采集。")
        return 2

    raw = pd.read_csv(INPUT_CSV, encoding="utf-8-sig")
    cleaned, report = clean(raw)

    if cleaned.empty:
        print("[错误] 清洗后没有有效记录，未写入输出文件。")
        return 1

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    cleaned.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    print(f"输入文件：{INPUT_CSV}")
    print(f"输出文件：{OUTPUT_CSV}")
    print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
