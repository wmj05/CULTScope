"""IMDb 聚合统计只读 API 的隔离测试。

所有请求都指向临时 JSON 夹具，不读取也不修改真实 IMDb 聚合文件与 CSV。
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.api import imdb as imdb_api  # noqa: E402
from app.main import app  # noqa: E402
from app.services import imdb_aggregate_service  # noqa: E402

ENDPOINT = "/api/imdb/aggregates"

EXPECTED_KEYS = {
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
    "scope_note",
}


def _payload() -> dict:
    """与 aggregate_imdb.py 输出契约一致的紧凑夹具。"""
    return {
        "generated_at": "2026-11-18T07:40:45.500036+00:00",
        "basics_input": {
            "sha256": "a" * 64,
            "file_bytes": 68123456,
            "label": "backend/data/processed/large/imdb_titles_movies.csv",
        },
        "ratings_input": {
            "sha256": "b" * 64,
            "file_bytes": 10351234,
            "label": "backend/data/processed/large/imdb_ratings.csv",
        },
        "aggregate_constraints": {
            "max_rows_per_table": None,
            "early_valid_year": 1877,
            "future_year_cutoff": 2027,
            "rating_bucket_width": 0.5,
            "votes_bucket_definition": [
                "invalid",
                "1-10",
                "11-100",
                "101-1k",
                "1k-10k",
                "10k-100k",
                "100k-1M",
                ">1M",
            ],
            "duplicate_policy": "first-wins",
        },
        "coverage": {
            "total_movies": 3,
            "rated_movies": 2,
            "unrated_movies": 1,
            "coverage_ratio": 0.666667,
            "orphan_ratings": 0,
        },
        "year_distribution": {
            "per_year": {
                "1994": {"total_movies": 2, "rated_movies": 1},
                "2000": {"total_movies": 1, "rated_movies": 1},
            },
            "missing_year": 0,
            "invalid_year": 0,
            "future_year": 0,
        },
        "genre_distribution": {"Drama": 2, "Comedy": 1},
        "rating_distribution": {"7.5-8.0": 1, "9.5-10.0": 1},
        "votes_distribution": {"1-10": 1, "1k-10k": 1},
        "year_rating_trend": {
            "1994": {
                "rated_count": 1,
                "valid_rating_count": 1,
                "valid_votes_count": 0,
                "rating_mean": 8.7,
                "votes_mean": None,
            },
            "2000": {
                "rated_count": 1,
                "valid_rating_count": 1,
                "valid_votes_count": 1,
                "rating_mean": 9.6,
                "votes_mean": 2500.0,
            },
        },
        "quality_flags": {"invalid_ratings_skipped": 0, "invalid_votes_skipped": 1},
        "duplicate_counts": {
            "basics_duplicate_tconst": 0,
            "ratings_duplicate_tconst": 0,
        },
    }


class ImdbApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        self.aggregate_path = self.tmp_dir / "imdb_aggregate.json"
        self._write_payload(_payload())
        app.dependency_overrides[imdb_api.get_aggregate_path] = (
            lambda: self.aggregate_path
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.client.close()
        self._tmp.cleanup()

    # ---------- 夹具工具 ----------

    def _write_payload(self, payload: dict) -> None:
        self.aggregate_path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    def _sha256(self) -> str:
        return hashlib.sha256(self.aggregate_path.read_bytes()).hexdigest()

    def _assert_no_path_leak(self, response) -> None:
        text = response.text
        self.assertNotIn("Traceback", text)
        self.assertNotIn("C:\\", text)
        self.assertNotIn(self.tmp_dir.name, text)

    # ---------- 正常读取 ----------

    def test_returns_aggregate_payload(self) -> None:
        response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 200)
        body = response.json()

        self.assertEqual(body["generated_at"], "2026-11-18T07:40:45.500036+00:00")
        self.assertEqual(
            body["basics_input"]["label"],
            "backend/data/processed/large/imdb_titles_movies.csv",
        )
        self.assertEqual(body["coverage"]["total_movies"], 3)
        self.assertEqual(body["coverage"]["coverage_ratio"], 0.666667)
        self.assertEqual(body["year_distribution"]["per_year"]["1994"]["rated_movies"], 1)
        self.assertEqual(body["genre_distribution"]["Drama"], 2)
        self.assertEqual(body["rating_distribution"]["9.5-10.0"], 1)
        self.assertEqual(body["votes_distribution"]["1k-10k"], 1)
        self.assertIsNone(body["year_rating_trend"]["1994"]["votes_mean"])
        self.assertEqual(body["year_rating_trend"]["2000"]["votes_mean"], 2500.0)
        self.assertEqual(body["quality_flags"]["invalid_votes_skipped"], 1)
        self.assertEqual(body["duplicate_counts"]["basics_duplicate_tconst"], 0)

    def test_response_contract_keys(self) -> None:
        body = self.client.get(ENDPOINT).json()
        self.assertEqual(set(body.keys()), EXPECTED_KEYS)
        self.assertEqual(
            set(body["coverage"].keys()),
            {
                "total_movies",
                "rated_movies",
                "unrated_movies",
                "coverage_ratio",
                "orphan_ratings",
            },
        )
        self.assertEqual(
            set(body["aggregate_constraints"].keys()),
            {
                "max_rows_per_table",
                "early_valid_year",
                "future_year_cutoff",
                "rating_bucket_width",
                "votes_bucket_definition",
                "duplicate_policy",
            },
        )
        self.assertEqual(
            set(body["year_rating_trend"]["2000"].keys()),
            {
                "rated_count",
                "valid_rating_count",
                "valid_votes_count",
                "rating_mean",
                "votes_mean",
            },
        )
        self.assertEqual(
            set(body["year_distribution"]["per_year"]["2000"].keys()),
            {"total_movies", "rated_movies"},
        )

    def test_scope_note_explains_snapshot(self) -> None:
        body = self.client.get(ENDPOINT).json()
        note = body["scope_note"]
        self.assertIn("快照", note)
        self.assertIn("无偏估计", note)

    # ---------- 缺失 / 损坏 ----------

    def test_missing_file_returns_503(self) -> None:
        self.aggregate_path.unlink()
        response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 503)
        self.assertIn("尚未生成", response.json()["detail"])
        self._assert_no_path_leak(response)

    def test_unreadable_file_returns_503(self) -> None:
        # 用同名目录模拟“存在但无法读取”，覆盖 OSError 分支且不触碰真实数据
        self.aggregate_path.unlink()
        self.aggregate_path.mkdir()
        response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 503)
        self.assertIn("无法读取", response.json()["detail"])
        self._assert_no_path_leak(response)

    def test_internal_error_returns_500_without_leaking_details(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)
        try:
            with mock.patch.object(
                imdb_aggregate_service,
                "load_aggregates",
                side_effect=RuntimeError(f"boom at {self.aggregate_path}"),
            ):
                response = client.get(ENDPOINT)
        finally:
            client.close()
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("boom", response.text)
        self._assert_no_path_leak(response)

    def test_corrupt_json_returns_503(self) -> None:
        self.aggregate_path.write_text("{not valid json", encoding="utf-8")
        response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 503)
        self.assertIn("格式损坏", response.json()["detail"])
        self._assert_no_path_leak(response)

    def test_top_level_list_returns_503(self) -> None:
        self.aggregate_path.write_text("[]", encoding="utf-8")
        response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 503)
        self.assertIn("顶层", response.json()["detail"])

    # ---------- 契约不符合 ----------

    def test_missing_top_level_field_returns_503(self) -> None:
        payload = _payload()
        payload.pop("coverage")
        self._write_payload(payload)
        response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 503)
        self.assertIn("coverage", response.json()["detail"])

    def test_missing_nested_field_returns_503(self) -> None:
        payload = _payload()
        del payload["coverage"]["coverage_ratio"]
        self._write_payload(payload)
        response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 503)
        self.assertIn("coverage_ratio", response.json()["detail"])

    def test_missing_year_trend_field_returns_503(self) -> None:
        payload = _payload()
        del payload["year_rating_trend"]["2000"]["valid_votes_count"]
        self._write_payload(payload)
        response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 503)
        self.assertIn("valid_votes_count", response.json()["detail"])

    def test_invalid_field_type_returns_503(self) -> None:
        payload = _payload()
        payload["coverage"]["total_movies"] = "many"
        self._write_payload(payload)
        response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 503)
        self.assertIn("total_movies", response.json()["detail"])

    def test_non_numeric_rating_mean_returns_503(self) -> None:
        payload = _payload()
        payload["year_rating_trend"]["2000"]["rating_mean"] = "high"
        self._write_payload(payload)
        response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 503)
        self.assertIn("rating_mean", response.json()["detail"])

    # ---------- 非有限数值 ----------

    def test_nan_coverage_ratio_returns_503(self) -> None:
        payload = _payload()
        payload["coverage"]["coverage_ratio"] = float("nan")
        self._write_payload(payload)
        response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 503)
        detail = response.json()["detail"]
        self.assertIn("coverage_ratio", detail)
        self.assertIn("有限数值", detail)
        self.assertNotIn("NaN", detail)

    def test_positive_infinity_rating_mean_returns_503(self) -> None:
        payload = _payload()
        payload["year_rating_trend"]["2000"]["rating_mean"] = float("inf")
        self._write_payload(payload)
        response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 503)
        self.assertIn("rating_mean", response.json()["detail"])
        self._assert_no_path_leak(response)

    def test_negative_infinity_votes_mean_returns_503(self) -> None:
        payload = _payload()
        payload["year_rating_trend"]["1994"]["votes_mean"] = float("-inf")
        self._write_payload(payload)
        response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 503)
        self.assertIn("votes_mean", response.json()["detail"])

    def test_nan_rating_bucket_width_returns_503(self) -> None:
        payload = _payload()
        payload["aggregate_constraints"]["rating_bucket_width"] = float("nan")
        self._write_payload(payload)
        response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 503)
        self.assertIn("rating_bucket_width", response.json()["detail"])

    def test_finite_float_values_accepted(self) -> None:
        payload = _payload()
        payload["coverage"]["coverage_ratio"] = 0.5
        payload["aggregate_constraints"]["rating_bucket_width"] = 0.25
        payload["year_rating_trend"]["2000"]["rating_mean"] = 7.25
        payload["year_rating_trend"]["1994"]["votes_mean"] = 12.5
        self._write_payload(payload)
        response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["coverage"]["coverage_ratio"], 0.5)
        self.assertEqual(body["year_rating_trend"]["2000"]["rating_mean"], 7.25)

    def test_null_means_remain_supported(self) -> None:
        payload = _payload()
        payload["year_rating_trend"]["2000"]["rating_mean"] = None
        payload["year_rating_trend"]["2000"]["votes_mean"] = None
        self._write_payload(payload)
        response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 200)
        entry = response.json()["year_rating_trend"]["2000"]
        self.assertIsNone(entry["rating_mean"])
        self.assertIsNone(entry["votes_mean"])

    # ---------- 输入标签路径安全 ----------

    def test_windows_absolute_label_returns_503(self) -> None:
        payload = _payload()
        payload["basics_input"]["label"] = "C:\\Users\\alice\\imdb_titles_movies.csv"
        self._write_payload(payload)
        response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 503)
        detail = response.json()["detail"]
        self.assertIn("basics_input.label", detail)
        self.assertNotIn("alice", detail)
        self.assertNotIn("Users", detail)
        self._assert_no_path_leak(response)

    def test_unix_absolute_label_returns_503(self) -> None:
        payload = _payload()
        payload["ratings_input"]["label"] = "/home/alice/imdb_ratings.csv"
        self._write_payload(payload)
        response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 503)
        detail = response.json()["detail"]
        self.assertIn("ratings_input.label", detail)
        self.assertNotIn("alice", detail)

    def test_unc_label_returns_503(self) -> None:
        payload = _payload()
        payload["basics_input"]["label"] = "\\\\server\\share\\imdb.csv"
        self._write_payload(payload)
        response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 503)
        self.assertIn("basics_input.label", response.json()["detail"])

    def test_traversal_label_returns_503(self) -> None:
        for label in ("../outside.csv", "..\\..\\Windows\\system32\\config", "a/../../b.csv"):
            payload = _payload()
            payload["basics_input"]["label"] = label
            self._write_payload(payload)
            response = self.client.get(ENDPOINT)
            self.assertEqual(response.status_code, 503, msg=label)
            self.assertIn("basics_input.label", response.json()["detail"])

    def test_external_filename_label_accepted(self) -> None:
        payload = _payload()
        payload["basics_input"]["label"] = "external:imdb_titles_movies.csv"
        payload["ratings_input"]["label"] = "external:imdb_ratings.csv"
        self._write_payload(payload)
        response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["basics_input"]["label"], "external:imdb_titles_movies.csv"
        )

    def test_external_label_with_path_returns_503(self) -> None:
        for label in ("external:../a.csv", "external:sub/a.csv", "external:..", "external:"):
            payload = _payload()
            payload["ratings_input"]["label"] = label
            self._write_payload(payload)
            response = self.client.get(ENDPOINT)
            self.assertEqual(response.status_code, 503, msg=label)
            self.assertIn("ratings_input.label", response.json()["detail"])

    def test_backslash_relative_label_accepted(self) -> None:
        # 真实 JSON 在 Windows 上生成的标签使用反斜杠分隔的仓库相对路径
        payload = _payload()
        payload["basics_input"]["label"] = (
            "backend\\data\\processed\\large\\imdb_titles_movies.csv"
        )
        self._write_payload(payload)
        response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.json()["basics_input"]["label"].startswith("backend\\data")
        )

    # ---------- 只读特性 ----------

    def test_write_methods_are_rejected(self) -> None:
        for method in ("post", "put", "patch", "delete"):
            response = getattr(self.client, method)(ENDPOINT)
            self.assertEqual(response.status_code, 405, msg=method)

    def test_aggregate_file_is_not_modified(self) -> None:
        before = self._sha256()
        self.client.get(ENDPOINT)
        self.client.get(ENDPOINT)
        self.assertEqual(self._sha256(), before)

    def test_response_payload_is_a_copy(self) -> None:
        # 修改返回值不应影响后续请求（每次请求重新读取文件）
        first = self.client.get(ENDPOINT).json()
        first["coverage"]["total_movies"] = 999999
        second = self.client.get(ENDPOINT).json()
        self.assertEqual(second["coverage"]["total_movies"], 3)

    # ---------- 无路径 / 异常信息泄漏 ----------

    def test_success_response_hides_paths(self) -> None:
        response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 200)
        self._assert_no_path_leak(response)

    def test_error_detail_hides_paths(self) -> None:
        self.aggregate_path.unlink()
        response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 503)
        detail = response.json()["detail"]
        self.assertNotIn(str(self.tmp_dir), detail)
        self._assert_no_path_leak(response)

    # ---------- 不影响既有 API ----------

    def test_existing_routes_unaffected(self) -> None:
        paths = {route.path for route in app.routes}
        self.assertIn(ENDPOINT, paths)
        self.assertIn("/api/movies", paths)
        self.assertIn("/api/movies/stats", paths)
        self.assertIn("/api/cult/stats", paths)

        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")

        movies = self.client.get("/api/movies/stats")
        self.assertEqual(movies.status_code, 200)
        self.assertIn("decade_distribution", movies.json())

    # ---------- 服务层直测（不经过 HTTP） ----------

    def test_service_returns_scope_note(self) -> None:
        data = imdb_aggregate_service.load_aggregates(self.aggregate_path)
        self.assertEqual(data["scope_note"], imdb_aggregate_service.SCOPE_NOTE)
        self.assertEqual(data["coverage"]["rated_movies"], 2)

    def test_service_does_not_mutate_source_payload(self) -> None:
        payload = _payload()
        self._write_payload(payload)
        data = imdb_aggregate_service.load_aggregates(self.aggregate_path)
        # 只在返回副本上补充 scope_note，不改动磁盘上的原始契约
        self.assertNotIn("scope_note", payload)
        self.assertIn("scope_note", data)
        on_disk = json.loads(self.aggregate_path.read_text(encoding="utf-8"))
        self.assertNotIn("scope_note", on_disk)

    def test_service_rejects_nested_bucket_contract_break(self) -> None:
        payload = copy.deepcopy(_payload())
        payload["year_distribution"]["per_year"]["2000"] = {"total_movies": 1}
        self._write_payload(payload)
        response = self.client.get(ENDPOINT)
        self.assertEqual(response.status_code, 503)
        self.assertIn("rated_movies", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
