"""阶段一采集脚本：种子 CSV -> TMDb 搜索/详情/关键词 -> JSON + CSV。

用法（在 backend 目录下）：
    python scripts/fetch_tmdb.py --dry-run
    python scripts/fetch_tmdb.py
    python scripts/fetch_tmdb.py --limit 3 --refresh
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

# 保证从任意目录运行都能 import app 包
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings  # noqa: E402
from scripts.tmdb_client import TmdbClient, TmdbError  # noqa: E402

# Windows 控制台默认编码可能不是 UTF-8，避免打印中文报错
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_SEED = Path(__file__).with_name("seed_movies.csv")
RAW_JSON = BACKEND_DIR / "data" / "raw" / "movies_raw.json"
PROCESSED_CSV = BACKEND_DIR / "data" / "processed" / "cult_movies.csv"
MATCH_REPORT_CSV = BACKEND_DIR / "data" / "processed" / "match_report.csv"

CSV_COLUMNS = [
    "seed_id",
    "seed_title",
    "seed_year",
    "match_status",
    "matched_title",
    "tmdb_id",
    "release_date",
    "runtime",
    "vote_average",
    "vote_count",
    "popularity",
    "budget",
    "revenue",
    "original_language",
    "genres",
    "directors",
    "keywords",
    "keyword_count",
    "production_companies",
    "overview",
    "tagline",
    "fetched_at",
]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从 TMDb 采集 CULTScope 种子电影数据")
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED, help="种子 CSV 路径")
    parser.add_argument("--limit", type=int, default=None, help="只采集前 N 部，便于试跑")
    parser.add_argument("--refresh", action="store_true", help="忽略本地缓存，重新采集")
    parser.add_argument("--dry-run", action="store_true", help="只打印采集计划，不发起网络请求")
    parser.add_argument("--year-tolerance", type=int, default=1, help="匹配时允许的年份误差")
    return parser.parse_args()


def load_seed(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"种子文件不存在：{path}")

    df = pd.read_csv(path, encoding="utf-8-sig")
    missing = {"title", "year"} - set(df.columns)
    if missing:
        raise ValueError(f"种子 CSV 缺少必要列：{', '.join(sorted(missing))}")

    df = df.dropna(subset=["title", "year"]).copy()
    try:
        df["year"] = df["year"].astype(int)
    except (TypeError, ValueError) as exc:
        raise ValueError("种子 CSV 的 year 列必须全部是整数年份") from exc

    if "seed_id" not in df.columns:
        df.insert(0, "seed_id", range(1, len(df) + 1))
    return df


def normalize_title(text: str) -> str:
    """去掉空格、标点和大小写差异，便于比较片名。"""
    return re.sub(r"[^0-9a-z]+", "", str(text).casefold())


def parse_year(release_date: str | None) -> int | None:
    if release_date and len(release_date) >= 4 and release_date[:4].isdigit():
        return int(release_date[:4])
    return None


def pick_best_match(
    results: list[dict],
    title: str,
    year: int,
    tolerance: int,
) -> dict | None:
    """在搜索结果中选出片名一致、年份接近的那一条。"""
    target = normalize_title(title)

    for item in results:
        names = {
            normalize_title(item.get("title", "")),
            normalize_title(item.get("original_title", "")),
        }
        if target not in names:
            continue

        release_year = parse_year(item.get("release_date"))
        if release_year is not None and abs(release_year - year) <= tolerance:
            return item

    return None


def find_match(
    client: TmdbClient,
    title: str,
    year: int,
    tolerance: int,
) -> tuple[dict | None, str]:
    """先带年份搜索，未命中再放宽年份搜索一次。

    返回 (匹配结果, 状态)，状态为 matched / ambiguous / not_found。
    """
    results = client.search_movie(title, year)
    match = pick_best_match(results, title, year, tolerance)
    if match:
        return match, "matched"

    broader_results = client.search_movie(title)
    match = pick_best_match(broader_results, title, year, tolerance)
    if match:
        return match, "matched"

    if results or broader_results:
        return None, "ambiguous"
    return None, "not_found"


def fetch_movie_entry(client: TmdbClient, row: pd.Series, tolerance: int) -> dict:
    """采集单部电影，任何失败都转成带状态的结果，不中断整批任务。"""
    title = str(row["title"]).strip()
    year = int(row["year"])
    seed_id = int(row["seed_id"])

    entry: dict = {
        "seed_id": seed_id,
        "seed_title": title,
        "seed_year": year,
        "match_status": "error",
        "matched_title": "",
        "tmdb_id": None,
        "fetched_at": now_iso(),
        "error": "",
        "movie": None,
    }

    try:
        match, status = find_match(client, title, year, tolerance)
    except TmdbError as exc:
        entry["error"] = str(exc)
        return entry

    if not match:
        entry["match_status"] = status
        return entry

    entry["matched_title"] = match.get("title", "")
    entry["tmdb_id"] = match.get("id")

    try:
        detail = client.movie_detail(int(match["id"]))
    except TmdbError as exc:
        entry["error"] = str(exc)
        return entry

    entry["match_status"] = "matched"
    entry["movie"] = detail
    return entry


def load_existing(raw_path: Path) -> dict[str, dict]:
    """读取上次采集结果，用于断点续跑。"""
    if not raw_path.exists():
        return {}

    try:
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("[警告] 已有 JSON 无法解析，本次将全量采集")
        return {}

    entries = payload.get("movies", []) if isinstance(payload, dict) else []
    return {
        entry["seed_title"]: entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("seed_title")
    }


def ordered_entries(df: pd.DataFrame, results: dict[str, dict]) -> list[dict]:
    """按种子 CSV 的顺序整理结果，避免残留旧数据。"""
    return [results[str(row["title"]).strip()] for _, row in df.iterrows()
            if str(row["title"]).strip() in results]


def save_raw(raw_path: Path, entries: list[dict]) -> None:
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": now_iso(),
        "source": "TMDb API v3",
        "movie_count": len(entries),
        "movies": entries,
    }
    raw_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def flatten_entry(entry: dict) -> dict:
    """把嵌套的 TMDb JSON 拍平成一行表格数据。"""
    movie = entry.get("movie") or {}
    keywords = (movie.get("keywords") or {}).get("keywords") or []
    crew = (movie.get("credits") or {}).get("crew") or []

    return {
        "seed_id": entry.get("seed_id"),
        "seed_title": entry.get("seed_title"),
        "seed_year": entry.get("seed_year"),
        "match_status": entry.get("match_status"),
        "matched_title": movie.get("title", entry.get("matched_title", "")),
        "tmdb_id": movie.get("id", entry.get("tmdb_id")),
        "release_date": movie.get("release_date", ""),
        "runtime": movie.get("runtime"),
        "vote_average": movie.get("vote_average"),
        "vote_count": movie.get("vote_count"),
        "popularity": movie.get("popularity"),
        "budget": movie.get("budget"),
        "revenue": movie.get("revenue"),
        "original_language": movie.get("original_language", ""),
        "genres": "|".join(g.get("name", "") for g in movie.get("genres") or []),
        "directors": "|".join(
            sorted({p.get("name", "") for p in crew if p.get("job") == "Director"})
        ),
        "keywords": "|".join(k.get("name", "") for k in keywords),
        "keyword_count": len(keywords),
        "production_companies": "|".join(
            c.get("name", "") for c in movie.get("production_companies") or []
        ),
        "overview": movie.get("overview", ""),
        "tagline": movie.get("tagline", ""),
        "fetched_at": entry.get("fetched_at", ""),
    }


def save_tables(entries: list[dict]) -> None:
    PROCESSED_CSV.parent.mkdir(parents=True, exist_ok=True)

    matched_rows = [
        flatten_entry(entry) for entry in entries if entry.get("match_status") == "matched"
    ]
    pd.DataFrame(matched_rows, columns=CSV_COLUMNS).to_csv(
        PROCESSED_CSV, index=False, encoding="utf-8-sig"
    )

    report_rows = [
        {
            "seed_id": entry.get("seed_id"),
            "seed_title": entry.get("seed_title"),
            "seed_year": entry.get("seed_year"),
            "match_status": entry.get("match_status"),
            "matched_title": entry.get("matched_title"),
            "tmdb_id": entry.get("tmdb_id"),
            "error": entry.get("error", ""),
        }
        for entry in entries
    ]
    pd.DataFrame(report_rows).to_csv(
        MATCH_REPORT_CSV, index=False, encoding="utf-8-sig"
    )


def main() -> int:
    args = parse_args()

    try:
        seed_df = load_seed(args.seed)
    except (FileNotFoundError, ValueError) as exc:
        print(f"[错误] {exc}")
        return 2

    # --limit 只限制本次采集范围；保存时仍按完整种子排序，避免覆盖其他缓存
    df = seed_df.head(args.limit) if args.limit else seed_df

    print(f"种子文件：{args.seed}")
    print(f"待处理电影：{len(df)} 部")
    print(f"TMDb Token：{'已配置' if settings.tmdb_bearer_token else '未配置'}")

    if args.dry_run:
        print("\n[dry-run] 采集计划：")
        for _, row in df.iterrows():
            print(f"  {int(row['seed_id']):>2}. {row['title']} ({int(row['year'])})")
        print("\n[dry-run] 未发起任何网络请求。")
        return 0

    try:
        client = TmdbClient(
            bearer_token=settings.tmdb_bearer_token,
            base_url=settings.tmdb_api_base,
            language=settings.tmdb_language,
        )
    except TmdbError as exc:
        print(f"[错误] {exc}")
        return 2

    results = {} if args.refresh else load_existing(RAW_JSON)
    RAW_JSON.parent.mkdir(parents=True, exist_ok=True)

    try:
        for _, row in df.iterrows():
            title = str(row["title"]).strip()
            cached = results.get(title)

            if cached and cached.get("match_status") == "matched":
                print(f"跳过（本地已有）：{title}")
                continue

            print(f"采集：{title} ({int(row['year'])}) ...")
            entry = fetch_movie_entry(client, row, args.year_tolerance)
            results[title] = entry
            save_raw(RAW_JSON, ordered_entries(seed_df, results))

            status = entry["match_status"]
            if status == "matched":
                print(f"  匹配成功：{entry['matched_title']} (TMDb ID {entry['tmdb_id']})")
            else:
                print(f"  未完成：{status} {entry.get('error', '')}".rstrip())

            time.sleep(0.3)  # 主动限速，避免触发 TMDb 频率限制
    except KeyboardInterrupt:
        print("\n[中断] 已保存当前进度，下次运行会自动续跑。")
        save_tables(ordered_entries(seed_df, results))
        return 130

    entries = ordered_entries(seed_df, results)
    save_raw(RAW_JSON, entries)
    save_tables(entries)

    matched = sum(1 for e in entries if e.get("match_status") == "matched")
    print("\n========== 采集完成 ==========")
    print(f"总计 {len(entries)} 部，匹配成功 {matched} 部")
    print(f"原始 JSON：{RAW_JSON}")
    print(f"扁平 CSV：{PROCESSED_CSV}")
    print(f"匹配报告：{MATCH_REPORT_CSV}")

    return 0 if matched else 1


if __name__ == "__main__":
    raise SystemExit(main())
