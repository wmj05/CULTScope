"""Cult 知识库只读 API 的隔离测试。

所有请求都指向临时知识库目录，不读取也不修改生产 CSV。
"""

from __future__ import annotations

import csv
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.api import cult as cult_api  # noqa: E402
from app.main import app  # noqa: E402
from scripts.validate_knowledge import EXPECTED_HEADERS  # noqa: E402

FIXTURE_TIME = "2026-11-17T12:00:00+08:00"
CSV_FILES = tuple(EXPECTED_HEADERS)


class CultApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name) / "knowledge"
        self.data_dir.mkdir()
        self._write_fixture()
        app.dependency_overrides[cult_api.get_data_dir] = lambda: self.data_dir
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.client.close()
        self._tmp.cleanup()

    # ---------- 固定夹具 ----------

    def _write(self, filename: str, rows: list[dict[str, str]]) -> None:
        with (self.data_dir / filename).open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=EXPECTED_HEADERS[filename])
            writer.writeheader()
            writer.writerows(rows)

    def _write_fixture(self) -> None:
        self._write(
            "cult_seed.csv",
            [
                {
                    "seed_id": "CS-0001",
                    "title": "橡皮头",
                    "original_title": "Eraserhead",
                    "year": "1977",
                    "tmdb_id": "985",
                    "imdb_id": "tt0074486",
                    "candidate_source_ids": "S-001|S-002",
                    "cult_criteria_codes": "C1|C2|C5|C8",
                    "review_status": "pending",
                    "confidence": "",
                    "reviewer": "",
                    "reviewed_at": "",
                    "notes": "测试夹具",
                },
                {
                    "seed_id": "CS-0002",
                    "title": "粉红色的火烈鸟",
                    "original_title": "Pink Flamingos",
                    "year": "1972",
                    "tmdb_id": "692",
                    "imdb_id": "tt0069089",
                    "candidate_source_ids": "S-002|S-099",
                    "cult_criteria_codes": "C1|C4|C5",
                    "review_status": "pending",
                    "confidence": "",
                    "reviewer": "",
                    "reviewed_at": "",
                    "notes": "测试夹具",
                },
                {
                    "seed_id": "CS-0003",
                    "title": "洛基恐怖秀",
                    "original_title": "The Rocky Horror Picture Show",
                    "year": "1975",
                    "tmdb_id": "36685",
                    "imdb_id": "tt0073629",
                    "candidate_source_ids": "S-001|S-002",
                    "cult_criteria_codes": "C1|C2",
                    "review_status": "approved",
                    "confidence": "high",
                    "reviewer": "测试审核人",
                    "reviewed_at": FIXTURE_TIME,
                    "notes": "测试夹具",
                },
                {
                    "seed_id": "CS-0004",
                    "title": "德州电锯杀人狂",
                    "original_title": "The Texas Chain Saw Massacre",
                    "year": "1974",
                    "tmdb_id": "30497",
                    "imdb_id": "tt0072271",
                    "candidate_source_ids": "",
                    "cult_criteria_codes": "",
                    "review_status": "draft",
                    "confidence": "",
                    "reviewer": "",
                    "reviewed_at": "",
                    "notes": "测试夹具",
                },
            ],
        )
        self._write(
            "cult_sources.csv",
            [
                {
                    "source_id": "S-001",
                    "title": "测试 T1 来源",
                    "source_type": "institution",
                    "url": "https://example.test/s1",
                    "publisher": "测试机构",
                    "published_year": "",
                    "language": "en",
                    "reliability_tier": "T1",
                    "notes": "测试夹具",
                },
                {
                    "source_id": "S-002",
                    "title": "测试 T2 来源",
                    "source_type": "institution",
                    "url": "https://example.test/s2",
                    "publisher": "测试机构",
                    "published_year": "",
                    "language": "en",
                    "reliability_tier": "T2",
                    "notes": "测试夹具",
                },
                {
                    "source_id": "S-099",
                    "title": "测试 T3 来源",
                    "source_type": "media",
                    "url": "https://example.test/s99",
                    "publisher": "测试媒体",
                    "published_year": "",
                    "language": "en",
                    "reliability_tier": "T3",
                    "notes": "测试夹具",
                },
            ],
        )
        self._write(
            "cult_criteria.csv",
            [
                {
                    "criterion_code": code,
                    "name_zh": name,
                    "name_en": f"Criterion {code}",
                    "definition": f"{name}的测试定义，仅用于接口测试。",
                    "evidence_requirement": "测试证据要求，需包含可核查定位。",
                    "exclusion_note": "测试排除条件。",
                    "version": "1.0",
                }
                for code, name in [
                    ("C1", "午夜场与仪式化放映"),
                    ("C2", "商业失败后的二次流行"),
                    ("C4", "审查与争议"),
                    ("C5", "亚文化符号"),
                    ("C8", "实验叙事"),
                ]
            ],
        )
        self._write(
            "movie_criterion_evidence.csv",
            [
                self._evidence("CS-0001", "C1", "S-001", "confirmed"),
                self._evidence("CS-0001", "C5", "S-002", "confirmed"),
                self._evidence("CS-0001", "C2", "S-001", "pending"),
                self._evidence("CS-0001", "C8", "S-001", "rejected"),
                self._evidence("CS-0002", "C1", "S-002", "confirmed"),
                self._evidence("CS-0002", "C5", "S-002", "confirmed"),
                self._evidence("CS-0002", "C4", "S-099", "confirmed"),
                self._evidence("CS-0003", "C1", "S-001", "confirmed"),
                self._evidence("CS-0003", "C2", "S-002", "confirmed"),
            ],
        )
        self._write(
            "cult_tags.csv",
            [
                self._tag("aesthetic_surrealism", "超现实主义", "Surrealism", "aesthetic"),
                self._tag("aesthetic_low_fi", "低保真", "Low Fi", "aesthetic"),
                self._tag(
                    "reception_midnight_movie", "午夜场电影", "Midnight Movie", "reception"
                ),
                self._tag(
                    "theme_sexual_transgression",
                    "性越界",
                    "Sexual Transgression",
                    "theme",
                ),
            ],
        )
        self._write(
            "movie_cult_tags.csv",
            [
                self._formal_tag("CS-0001", "aesthetic_surrealism", "S-001"),
                self._formal_tag("CS-0003", "reception_midnight_movie", "S-001|S-002"),
                self._formal_tag("CS-0003", "theme_sexual_transgression", "S-002"),
            ],
        )
        self._write(
            "movie_cult_tag_candidates.csv",
            [
                self._candidate("CS-0001", "aesthetic_surrealism", "confirmed"),
                self._candidate("CS-0001", "aesthetic_low_fi", "pending"),
                self._candidate("CS-0003", "reception_midnight_movie", "confirmed"),
            ],
        )
        self._write("review_log.csv", [])

    def _evidence(
        self, seed_id: str, code: str, source_id: str, human_status: str
    ) -> dict[str, str]:
        confirmed = human_status in {"confirmed", "rejected"}
        return {
            "seed_id": seed_id,
            "criterion_code": code,
            "source_id": source_id,
            "evidence_summary": "测试证据摘要，仅用于接口测试。",
            "locator": "测试原文定位",
            "verification_status": "verified",
            "human_status": human_status,
            "confirmed_by": "测试审核人" if confirmed else "",
            "confirmed_at": FIXTURE_TIME if confirmed else "",
            "added_by": "TEST-FIXTURE",
            "added_at": FIXTURE_TIME,
        }

    def _tag(
        self, tag_id: str, label_zh: str, label_en: str, dimension: str
    ) -> dict[str, str]:
        return {
            "tag_id": tag_id,
            "label_zh": label_zh,
            "label_en": label_en,
            "dimension": dimension,
            "definition": f"{label_zh}的测试定义，仅用于接口测试。",
            "inclusion_criteria": "测试纳入条件。",
            "exclusion_criteria": "测试排除条件。",
            "status": "active",
            "version": "1.0",
        }

    def _formal_tag(self, seed_id: str, tag_id: str, sources: str) -> dict[str, str]:
        return {
            "seed_id": seed_id,
            "tag_id": tag_id,
            "origin": "manual",
            "confidence": "",
            "evidence": "测试正式标签证据。",
            "source_ids": sources,
            "rule_id": "",
            "annotator": "测试审核人",
            "reviewed": "true",
            "updated_at": FIXTURE_TIME,
        }

    def _candidate(self, seed_id: str, tag_id: str, status: str) -> dict[str, str]:
        confirmed = status == "confirmed"
        return {
            "seed_id": seed_id,
            "tag_id": tag_id,
            "evidence": "测试候选标签证据。",
            "source_ids": "S-001",
            "proposed_by": "TEST-FIXTURE",
            "proposed_at": FIXTURE_TIME,
            "human_status": status,
            "confirmed_by": "测试审核人" if confirmed else "",
            "confirmed_at": FIXTURE_TIME if confirmed else "",
        }

    # ---------- 请求工具 ----------

    def _get(self, path: str, expected: int = 200) -> dict:
        response = self.client.get(path)
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def _file_hashes(self) -> dict[str, str]:
        return {
            name: hashlib.sha256((self.data_dir / name).read_bytes()).hexdigest()
            for name in CSV_FILES
        }

    # ---------- 列表与搜索 ----------

    def test_default_list_returns_only_approved(self) -> None:
        data = self._get("/api/cult/movies")
        self.assertEqual(data["status"], "approved")
        self.assertEqual(data["total"], 1)
        movie = data["items"][0]
        self.assertEqual(movie["seed_id"], "CS-0003")
        self.assertEqual(movie["confirmed_criteria_count"], 2)
        self.assertEqual(movie["formal_tag_count"], 2)

    def test_pending_list_returns_cs0001_and_cs0002(self) -> None:
        data = self._get("/api/cult/movies?status=pending")
        self.assertEqual(data["total"], 2)
        self.assertEqual(
            {item["seed_id"] for item in data["items"]}, {"CS-0001", "CS-0002"}
        )

    def test_status_all_and_pagination(self) -> None:
        data = self._get("/api/cult/movies?status=all&limit=2&offset=2")
        self.assertEqual(data["total"], 4)
        self.assertEqual(
            [item["seed_id"] for item in data["items"]], ["CS-0003", "CS-0004"]
        )
        empty = self._get("/api/cult/movies?status=all&limit=2&offset=10")
        self.assertEqual(empty["items"], [])

    def test_search_by_chinese_english_and_id(self) -> None:
        chinese = self._get("/api/cult/movies?status=all&q=粉红")
        self.assertEqual(
            [item["seed_id"] for item in chinese["items"]], ["CS-0002"]
        )
        english = self._get("/api/cult/movies?q=rocky")
        self.assertEqual(
            [item["seed_id"] for item in english["items"]], ["CS-0003"]
        )
        by_id = self._get("/api/cult/movies?q=CS-0003")
        self.assertEqual(by_id["total"], 1)

    # ---------- 详情 ----------

    def test_cs0003_detail_is_approved(self) -> None:
        data = self._get("/api/cult/movies/CS-0003")
        self.assertEqual(data["review_status"], "approved")
        self.assertEqual(data["reviewer"], "测试审核人")
        self.assertIsNotNone(data["reviewed_at"])
        self.assertEqual(data["confirmed_criteria_count"], 2)
        self.assertEqual(data["formal_tag_count"], 2)
        self.assertEqual(data["candidate_tag_count"], 1)
        self.assertTrue(all(item["tier_eligible_confirmed"] for item in data["criteria"]))

    def test_cs0001_is_pending_with_two_eligible_criteria(self) -> None:
        data = self._get("/api/cult/movies/CS-0001")
        self.assertEqual(data["review_status"], "pending")
        self.assertEqual(data["reviewer"], "")
        self.assertEqual(data["confirmed_criteria_count"], 2)
        eligible = {
            item["criterion_code"]
            for item in data["criteria"]
            if item["tier_eligible_confirmed"]
        }
        self.assertEqual(eligible, {"C1", "C5"})
        pending = {
            item["criterion_code"]
            for item in data["criteria"]
            if not item["human_confirmed"]
        }
        self.assertIn("C2", pending)

    def test_cs0002_t3_evidence_is_not_threshold_eligible(self) -> None:
        data = self._get("/api/cult/movies/CS-0002")
        self.assertEqual(data["review_status"], "pending")
        self.assertEqual(data["confirmed_criteria_count"], 2)
        c4 = next(item for item in data["criteria"] if item["criterion_code"] == "C4")
        self.assertTrue(c4["human_confirmed"])
        self.assertFalse(c4["tier_eligible_confirmed"])
        self.assertEqual(c4["confirmed_evidence_count"], 1)
        self.assertEqual(c4["tier_eligible_evidence_count"], 0)

    # ---------- 证据 ----------

    def test_default_evidence_hides_pending_and_rejected(self) -> None:
        data = self._get("/api/cult/movies/CS-0001/evidence")
        self.assertFalse(data["include_pending"])
        self.assertEqual(data["total"], 2)
        self.assertEqual({item["criterion_code"] for item in data["items"]}, {"C1", "C5"})
        self.assertTrue(all(item["human_status"] == "confirmed" for item in data["items"]))

    def test_include_pending_keeps_statuses_separate(self) -> None:
        data = self._get("/api/cult/movies/CS-0001/evidence?include_pending=true")
        self.assertEqual(data["total"], 4)
        by_code = {item["criterion_code"]: item for item in data["items"]}
        self.assertEqual(by_code["C2"]["human_status"], "pending")
        self.assertFalse(by_code["C2"]["approved_threshold_eligible"])
        self.assertEqual(by_code["C8"]["human_status"], "rejected")
        self.assertTrue(by_code["C1"]["approved_threshold_eligible"])

    def test_t3_evidence_is_marked_ineligible(self) -> None:
        data = self._get("/api/cult/movies/CS-0002/evidence?include_pending=true")
        c4 = next(item for item in data["items"] if item["criterion_code"] == "C4")
        self.assertEqual(c4["source_tier"], "T3")
        self.assertEqual(c4["human_status"], "confirmed")
        self.assertFalse(c4["approved_threshold_eligible"])

    # ---------- 标签 ----------

    def test_default_tags_exclude_candidates(self) -> None:
        data = self._get("/api/cult/movies/CS-0001/tags")
        self.assertFalse(data["include_candidates"])
        self.assertEqual(data["formal_total"], 1)
        self.assertEqual(data["candidates"], [])
        self.assertEqual(data["formal"][0]["tag_id"], "aesthetic_surrealism")

    def test_include_candidates_does_not_mix_formal_list(self) -> None:
        data = self._get("/api/cult/movies/CS-0001/tags?include_candidates=true")
        self.assertEqual(data["formal_total"], 1)
        self.assertEqual(data["candidates_total"], 2)
        self.assertEqual([item["tag_id"] for item in data["formal"]], ["aesthetic_surrealism"])
        statuses = {item["tag_id"]: item["human_status"] for item in data["candidates"]}
        self.assertEqual(statuses["aesthetic_surrealism"], "confirmed")
        self.assertEqual(statuses["aesthetic_low_fi"], "pending")
        self.assertTrue(
            all(item["record_type"] == "candidate" for item in data["candidates"])
        )

    # ---------- 字典与统计 ----------

    def test_criteria_and_tag_dictionaries(self) -> None:
        criteria = self._get("/api/cult/criteria")
        self.assertEqual(criteria["total"], 5)
        self.assertEqual(
            {item["criterion_code"] for item in criteria["items"]},
            {"C1", "C2", "C4", "C5", "C8"},
        )
        tags = self._get("/api/cult/tags")
        self.assertEqual(tags["total"], 4)
        self.assertIn("inclusion_criteria", tags["items"][0])
        self.assertIn("exclusion_criteria", tags["items"][0])

    def test_stats_match_fixture(self) -> None:
        data = self._get("/api/cult/stats")
        self.assertEqual(data["movies_total"], 4)
        self.assertEqual(
            data["review_status_counts"],
            {
                "draft": 1,
                "pending": 2,
                "approved": 1,
                "rejected": 0,
                "needs_fix": 0,
            },
        )
        self.assertEqual(
            data["evidence"],
            {
                "scope": "all_movies",
                "total": 9,
                "confirmed": 7,
                "pending": 1,
                "rejected": 1,
            },
        )
        self.assertEqual(
            data["formal_tags"],
            {"scope": "all_movies", "total": 3, "manual": 3, "inferred": 0},
        )
        self.assertEqual(
            data["candidate_tags"],
            {
                "scope": "all_movies",
                "total": 3,
                "confirmed": 2,
                "pending": 1,
                "rejected": 0,
            },
        )
        self.assertEqual(
            data["approved_scope"],
            {
                "movies": 1,
                "evidence_confirmed": 2,
                "formal_tags": 2,
                "candidate_tags_confirmed": 1,
            },
        )
        self.assertIn("approved_scope", data["scope_note"])
        self.assertNotIn("NaN", str(data))

    # ---------- 异常 ----------

    def test_unknown_movie_returns_404(self) -> None:
        for path in (
            "/api/cult/movies/CS-9999",
            "/api/cult/movies/CS-9999/evidence",
            "/api/cult/movies/CS-9999/tags",
        ):
            self._get(path, expected=404)

    def test_invalid_query_parameters_return_422(self) -> None:
        for path in (
            "/api/cult/movies?status=bogus",
            "/api/cult/movies?limit=0",
            "/api/cult/movies?limit=201",
            "/api/cult/movies?offset=-1",
            "/api/cult/movies?q=",
        ):
            self._get(path, expected=422)

    def test_missing_csv_returns_safe_503(self) -> None:
        (self.data_dir / "cult_tags.csv").unlink()
        response = self.client.get("/api/cult/tags")
        self.assertEqual(response.status_code, 503)
        detail = response.json()["detail"]
        self.assertNotIn(str(self.data_dir), detail)
        self.assertNotIn("C:\\", detail)

    def test_corrupt_csv_returns_safe_503(self) -> None:
        with (self.data_dir / "cult_seed.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            handle.write("seed_id,title\nCS-0001,损坏数据\n")
        response = self.client.get("/api/cult/movies")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("C:\\", response.json()["detail"])

    def test_unfinished_transaction_returns_503(self) -> None:
        txn = self.data_dir / ".review_txn"
        txn.mkdir()
        response = self.client.get("/api/cult/movies")
        self.assertEqual(response.status_code, 503)
        self.assertIn("recover", response.json()["detail"])
        self.assertTrue(txn.is_dir())

    # ---------- 只读保证 ----------

    def test_requests_do_not_modify_knowledge_files(self) -> None:
        before = self._file_hashes()
        for path in (
            "/api/cult/movies",
            "/api/cult/movies?status=all",
            "/api/cult/movies/CS-0001",
            "/api/cult/movies/CS-0001/evidence?include_pending=true",
            "/api/cult/movies/CS-0001/tags?include_candidates=true",
            "/api/cult/criteria",
            "/api/cult/tags",
            "/api/cult/stats",
        ):
            self._get(path)
        self.assertEqual(before, self._file_hashes())
        self.assertFalse((self.data_dir / ".review_txn").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
