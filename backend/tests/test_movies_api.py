"""TMDb 电影只读 API 的隔离测试。

所有请求都指向临时目录中的夹具 CSV，不读取也不修改真实 TMDb 数据；
不依赖网络、TMDb Token 或任何下载任务。
"""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.schemas.movie import Movie, MovieListResponse, StatsResponse  # noqa: E402
from app.services import movie_service  # noqa: E402

LIST_ENDPOINT = "/api/movies"
STATS_ENDPOINT = "/api/movies/stats"

# 客户端契约：内部数据不可用时只返回固定文案，不透传异常原文
EXPECTED_UNAVAILABLE_DETAIL = "电影数据暂时不可用，请稍后重试"

HEADERS = [
    "seed_id",
    "seed_title",
    "matched_title",
    "tmdb_id",
    "release_date",
    "release_year",
    "decade",
    "runtime",
    "vote_average",
    "vote_count",
    "popularity",
    "budget",
    "revenue",
    "budget_known",
    "revenue_known",
    "original_language",
    "genres",
    "directors",
    "keywords",
    "production_companies",
    "overview",
    "tagline",
]


def _movie(
    seed_id: str,
    seed_title: str,
    matched_title: str,
    tmdb_id: str,
    release_date: str,
    year: str,
    decade: str,
    genres: str,
    directors: str,
    vote_average: str,
    vote_count: str,
    budget: str = "0",
    revenue: str = "0",
    budget_known: str = "False",
    revenue_known: str = "False",
) -> dict[str, str]:
    return {
        "seed_id": seed_id,
        "seed_title": seed_title,
        "matched_title": matched_title,
        "tmdb_id": tmdb_id,
        "release_date": release_date,
        "release_year": year,
        "decade": decade,
        "runtime": "90",
        "vote_average": vote_average,
        "vote_count": vote_count,
        "popularity": "5.5",
        "budget": budget,
        "revenue": revenue,
        "budget_known": budget_known,
        "revenue_known": revenue_known,
        "original_language": "en",
        "genres": genres,
        "directors": directors,
        "keywords": "cult",
        "production_companies": "Indie Films",
        "overview": "测试夹具",
        "tagline": "fixture",
    }


FIXTURE_ROWS = [
    _movie(
        "1",
        "Eraserhead",
        "橡皮头",
        "985",
        "1977-03-19",
        "1977",
        "1970s",
        "恐怖|奇幻",
        "大卫·林奇",
        "7.4",
        "1200",
        budget="100000",
        revenue="7000000",
        budget_known="True",
        revenue_known="True",
    ),
    _movie(
        "2",
        "The Rocky Horror Picture Show",
        "洛基恐怖秀",
        "36685",
        "1975-08-14",
        "1975",
        "1970s",
        "喜剧|音乐",
        "吉姆·沙曼",
        "7.4",
        "900",
    ),
    _movie(
        "3",
        "Blade Runner",
        "银翼杀手",
        "78",
        "1982-06-25",
        "1982",
        "1980s",
        "科幻|惊悚",
        "雷德利·斯科特",
        "8.1",
        "8000",
    ),
    _movie(
        "4",
        "Unrated Fixture",
        "无评分夹具",
        "999999",
        "1995-01-01",
        "1995",
        "1990s",
        "剧情",
        "测试导演",
        "",
        "",
    ),
]


class MoviesApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        self.csv_path = self.data_dir / "cult_movies_clean.csv"
        self._write_fixture(self.csv_path)
        self._patch = mock.patch.object(movie_service, "CLEAN_CSV", self.csv_path)
        self._patch.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self._patch.stop()
        self._tmp.cleanup()

    # ---------- 固定夹具 ----------

    @staticmethod
    def _write_fixture(path: Path) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=HEADERS)
            writer.writeheader()
            writer.writerows(FIXTURE_ROWS)

    def _assert_no_internal_leak(self, text: str) -> None:
        lowered = text.lower()
        for marker in (str(self.data_dir).lower(), "c:\\", "users", "traceback", ".csv"):
            self.assertNotIn(marker, lowered)

    # ---------- 正常响应 ----------

    def test_list_returns_sample_and_schema_fields(self) -> None:
        response = self.client.get(LIST_ENDPOINT)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), set(MovieListResponse.model_fields))
        self.assertEqual(body["sample_size"], len(FIXTURE_ROWS))
        self.assertEqual(body["total"], len(FIXTURE_ROWS))
        self.assertEqual(len(body["movies"]), len(FIXTURE_ROWS))
        self.assertIn(f"{len(FIXTURE_ROWS)} 部", body["sample_label"])
        self.assertTrue(body["note"])

        first = body["movies"][0]
        self.assertEqual(set(first), set(Movie.model_fields))
        self.assertEqual(first["title"], "橡皮头")
        self.assertEqual(first["seed_title"], "Eraserhead")
        self.assertEqual(first["release_year"], 1977)
        self.assertEqual(first["decade"], "1970s")
        self.assertEqual(first["genres"], ["恐怖", "奇幻"])
        self.assertEqual(first["directors"], ["大卫·林奇"])
        self.assertIsInstance(first["budget_known"], bool)
        self.assertEqual(first["vote_average"], 7.4)

    def test_decade_filter(self) -> None:
        body = self.client.get(LIST_ENDPOINT, params={"decade": "1970s"}).json()

        self.assertEqual(body["total"], 2)
        self.assertEqual(body["sample_size"], len(FIXTURE_ROWS))
        self.assertEqual([movie["seed_id"] for movie in body["movies"]], [1, 2])

    def test_genre_filter(self) -> None:
        body = self.client.get(LIST_ENDPOINT, params={"genre": "科幻"}).json()

        self.assertEqual(body["total"], 1)
        self.assertEqual([movie["title"] for movie in body["movies"]], ["银翼杀手"])

    def test_combined_filter(self) -> None:
        body = self.client.get(
            LIST_ENDPOINT, params={"decade": "1970s", "genre": "音乐"}
        ).json()

        self.assertEqual(body["total"], 1)
        self.assertEqual([movie["seed_id"] for movie in body["movies"]], [2])

    def test_no_match_returns_empty_list(self) -> None:
        body = self.client.get(LIST_ENDPOINT, params={"genre": "不存在的类型"}).json()

        self.assertEqual(body["total"], 0)
        self.assertEqual(body["movies"], [])

    def test_stats_returns_distributions_and_filters(self) -> None:
        response = self.client.get(STATS_ENDPOINT)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), set(StatsResponse.model_fields))
        self.assertEqual(body["sample_size"], len(FIXTURE_ROWS))

        decades = {
            item["decade"]: item["count"] for item in body["decade_distribution"]
        }
        self.assertEqual(decades, {"1970s": 2, "1980s": 1, "1990s": 1})

        genres = {item["genre"]: item["count"] for item in body["genre_distribution"]}
        self.assertEqual(
            genres,
            {"恐怖": 1, "奇幻": 1, "喜剧": 1, "音乐": 1, "科幻": 1, "惊悚": 1, "剧情": 1},
        )

        # 缺失评分或票数的电影不进入散点图
        self.assertEqual(len(body["rating_scatter"]), 3)
        self.assertEqual(
            [point["title"] for point in body["rating_scatter"]],
            ["橡皮头", "洛基恐怖秀", "银翼杀手"],
        )
        self.assertEqual(body["filters"]["decades"], ["1970s", "1980s", "1990s"])
        self.assertCountEqual(
            body["filters"]["genres"],
            ["恐怖", "奇幻", "喜剧", "音乐", "科幻", "惊悚", "剧情"],
        )

    def test_sample_size_consistent_across_endpoints(self) -> None:
        list_body = self.client.get(LIST_ENDPOINT).json()
        stats_body = self.client.get(STATS_ENDPOINT).json()

        self.assertEqual(list_body["sample_size"], stats_body["sample_size"])
        self.assertEqual(list_body["total"], len(list_body["movies"]))
        self.assertEqual(
            stats_body["filters"]["decades"],
            [item["decade"] for item in stats_body["decade_distribution"]],
        )
        self.assertEqual(
            sum(item["count"] for item in stats_body["decade_distribution"]),
            stats_body["sample_size"],
        )

    # ---------- 异常与脱敏 ----------

    def test_missing_csv_returns_sanitized_error_on_both_endpoints(self) -> None:
        missing = self.data_dir / "missing_cult_movies_clean.csv"
        with mock.patch.object(movie_service, "CLEAN_CSV", missing):
            for endpoint in (LIST_ENDPOINT, STATS_ENDPOINT):
                with self.subTest(endpoint=endpoint):
                    response = self.client.get(endpoint)
                    self.assertEqual(response.status_code, 500)
                    self.assertEqual(
                        response.json()["detail"], EXPECTED_UNAVAILABLE_DETAIL
                    )
                    self._assert_no_internal_leak(response.text)
                    self.assertNotIn(missing.name, response.text)

    def test_unreadable_csv_returns_sanitized_error_on_both_endpoints(self) -> None:
        failure = PermissionError(f"读取失败：{self.csv_path}")
        with mock.patch.object(movie_service.pd, "read_csv", side_effect=failure):
            for endpoint in (LIST_ENDPOINT, STATS_ENDPOINT):
                with self.subTest(endpoint=endpoint):
                    response = self.client.get(endpoint)
                    self.assertEqual(response.status_code, 500)
                    self.assertEqual(
                        response.json()["detail"], EXPECTED_UNAVAILABLE_DETAIL
                    )
                    self._assert_no_internal_leak(response.text)

    def test_corrupt_csv_does_not_expose_paths_or_traceback(self) -> None:
        self.csv_path.write_bytes(b"\x00\x01 not,a,valid\ncsv")

        with TestClient(app, raise_server_exceptions=False) as client:
            for endpoint in (LIST_ENDPOINT, STATS_ENDPOINT):
                with self.subTest(endpoint=endpoint):
                    response = client.get(endpoint)
                    self.assertEqual(response.status_code, 500)
                    self._assert_no_internal_leak(response.text)


if __name__ == "__main__":
    unittest.main()
