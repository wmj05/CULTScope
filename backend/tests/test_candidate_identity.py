"""候选电影身份核验测试；所有 CSV 均写入临时目录，不访问网络。"""

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

from scripts.validate_candidate_identity import (  # noqa: E402
    CANDIDATE_FIELDS,
    IDENTITY_FIELDS,
    validate_identity_files,
)

KNOWLEDGE_FIELDS = [
    "seed_id", "title", "original_title", "year", "tmdb_id", "imdb_id"
]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CandidateIdentityValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.candidates_path = self.root / "candidates.csv"
        self.identity_path = self.root / "identity.csv"
        self.knowledge_path = self.root / "cult_seed.csv"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @staticmethod
    def _candidate(candidate_id: str, title: str, year: str) -> dict[str, str]:
        return {
            "candidate_id": candidate_id,
            "title": title,
            "original_title": title,
            "year": year,
            "source_id": "CB01-S01",
            "source_title": "测试片单",
            "source_url": "https://example.com/list",
            "source_evidence": "测试证据，仅用于结构校验。",
            "inclusion_reason": "测试纳入理由",
            "candidate_criteria_codes": "C5",
            "tmdb_id": "",
            "imdb_id": "",
            "verification_status": "verified",
            "candidate_status": "staged",
            "notes": "临时测试候选",
        }

    @staticmethod
    def _identity(
        candidate_id: str,
        title: str,
        year: str,
        status: str = "confirmed",
        tmdb_id: str = "84505",
        tmdb_title: str = "",
        tmdb_original_title: str = "",
        tmdb_release_date: str = "",
        tmdb_year: str = "",
        imdb_id: str = "tt2137121",
        method: str = "tmdb_search_details",
        notes: str = "",
        **changes: str,
    ) -> dict[str, str]:
        row = {
            "candidate_id": candidate_id,
            "candidate_title": title,
            "candidate_year": year,
            "tmdb_id": tmdb_id,
            "tmdb_title": tmdb_title or title,
            "tmdb_original_title": tmdb_original_title or title,
            "tmdb_release_date": tmdb_release_date or f"{year}-01-01",
            "tmdb_year": tmdb_year or year,
            "imdb_id": imdb_id,
            "tmdb_url": f"https://www.themoviedb.org/movie/{tmdb_id}" if tmdb_id else "",
            "imdb_url": f"https://www.imdb.com/title/{imdb_id}/" if imdb_id else "",
            "match_method": method,
            "match_status": status,
            "identity_evidence": "TMDb 搜索与详情一致，原始片名和上映年份相符。",
            "checked_at": "2026-11-18",
            "notes": notes,
        }
        row.update(changes)
        return row

    def _write(self, path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in fields})

    def _run(
        self,
        candidates: list[dict[str, str]],
        identity: list[dict[str, str]],
    ):
        self._write(self.candidates_path, CANDIDATE_FIELDS, candidates)
        self._write(self.identity_path, IDENTITY_FIELDS, identity)
        self._write(
            self.knowledge_path,
            KNOWLEDGE_FIELDS,
            [
                {
                    "seed_id": "CS-0001",
                    "title": "橡皮头",
                    "original_title": "Eraserhead",
                    "year": "1977",
                    "tmdb_id": "985",
                    "imdb_id": "tt0074486",
                },
                {
                    "seed_id": "CS-0005",
                    "title": "活死人黎明",
                    "original_title": "Dawn of the Dead",
                    "year": "1978",
                    "tmdb_id": "923",
                    "imdb_id": "tt0077402",
                },
            ],
        )
        before = {
            path: _digest(path)
            for path in (self.candidates_path, self.identity_path, self.knowledge_path)
        }
        report = validate_identity_files(
            self.candidates_path, self.identity_path, self.knowledge_path
        )
        for path, digest in before.items():
            self.assertEqual(_digest(path), digest, f"校验过程修改了 {path.name}")
        return report

    def _valid_fixture(self):
        candidates = [
            self._candidate("CB01-001", "Antiviral", "2012"),
            self._candidate("CB01-002", "Bad Timing", "1980"),
        ]
        identity = [
            self._identity(
                "CB01-001", "Antiviral", "2012",
                tmdb_id="84505", imdb_id="tt2137121",
                tmdb_release_date="2012-09-19",
            ),
            self._identity(
                "CB01-002", "Bad Timing", "1980",
                tmdb_id="11347", imdb_id="tt0080407",
                tmdb_release_date="1980-10-01",
            ),
        ]
        return candidates, identity

    def _codes(self, report) -> set[str]:
        return {issue.code for issue in report.issues}

    def test_valid_confirmed_row_passes(self) -> None:
        report = self._run(*self._valid_fixture())
        self.assertTrue(report.is_valid, [issue.message for issue in report.issues])
        self.assertEqual(report.confirmed, 2)
        self.assertEqual(report.tmdb_confirmed, 2)
        self.assertEqual(report.imdb_confirmed, 2)
        self.assertEqual(report.tmdb_id_missing, 0)
        self.assertEqual(report.imdb_id_missing, 0)

    def test_title_and_year_only_cannot_confirm(self) -> None:
        candidates, identity = self._valid_fixture()
        identity[0]["match_method"] = "tmdb_search_title_year"
        report = self._run(candidates, identity)
        self.assertIn("insufficient_identity", self._codes(report))
        self.assertFalse(report.is_valid)

    def test_original_title_mismatch_is_error(self) -> None:
        candidates, identity = self._valid_fixture()
        identity[0]["match_method"] = "tmdb_original_title"
        identity[0]["tmdb_original_title"] = "Different Original Title"
        report = self._run(candidates, identity)
        self.assertIn("original_title_mismatch", self._codes(report))

    def test_year_mismatch_is_error(self) -> None:
        candidates, identity = self._valid_fixture()
        identity[0]["tmdb_year"] = "2013"
        report = self._run(candidates, identity)
        self.assertIn("year_mismatch", self._codes(report))

    def test_imdb_conflict_for_same_tmdb_id_is_error(self) -> None:
        candidates, identity = self._valid_fixture()
        identity[1]["tmdb_id"] = "84505"
        identity[1]["tmdb_url"] = "https://www.themoviedb.org/movie/84505"
        identity[1]["imdb_id"] = "tt9999999"
        identity[1]["imdb_url"] = "https://www.imdb.com/title/tt9999999/"
        report = self._run(candidates, identity)
        self.assertIn("imdb_conflict", self._codes(report))
        self.assertIn("duplicate_tmdb", self._codes(report))
        self.assertFalse(report.is_valid)

    def test_duplicate_tmdb_id_is_error(self) -> None:
        candidates, identity = self._valid_fixture()
        identity[1]["tmdb_id"] = "84505"
        identity[1]["tmdb_url"] = "https://www.themoviedb.org/movie/84505"
        report = self._run(candidates, identity)
        self.assertIn("duplicate_tmdb", self._codes(report))

    def test_duplicate_imdb_id_is_error(self) -> None:
        candidates, identity = self._valid_fixture()
        identity[1]["imdb_id"] = "tt2137121"
        identity[1]["imdb_url"] = "https://www.imdb.com/title/tt2137121/"
        report = self._run(candidates, identity)
        self.assertIn("duplicate_imdb", self._codes(report))

    def test_existing_knowledge_duplicate_must_be_marked(self) -> None:
        candidates = [self._candidate("CB01-001", "Eraserhead", "1977")]
        identity = [
            self._identity(
                "CB01-001", "Eraserhead", "1977",
                tmdb_id="985", imdb_id="tt0074486",
            )
        ]
        report = self._run(candidates, identity)
        self.assertIn("duplicate_existing_required", self._codes(report))
        self.assertFalse(report.is_valid)

    def test_duplicate_existing_requires_knowledge_reference(self) -> None:
        candidates = [self._candidate("CB01-001", "Eraserhead", "1977")]
        identity = [
            self._identity(
                "CB01-001", "Eraserhead", "1977",
                status="duplicate_existing",
                tmdb_id="985", imdb_id="tt0074486",
                notes="与正式知识库重复",
            )
        ]
        report = self._run(candidates, identity)
        self.assertIn("duplicate_reference", self._codes(report))

    def test_unmatched_allows_empty_ids(self) -> None:
        candidates = [self._candidate("CB01-001", "Antiviral", "2012")]
        identity = [
            self._identity(
                "CB01-001", "Antiviral", "2012",
                status="unmatched", tmdb_id="", tmdb_title="",
                tmdb_original_title="", tmdb_release_date="", tmdb_year="",
                imdb_id="", method="tmdb_search_details",
                identity_evidence="TMDb 搜索无可靠匹配。",
            )
        ]
        report = self._run(candidates, identity)
        self.assertTrue(report.is_valid, [issue.message for issue in report.issues])
        self.assertEqual(report.unmatched, 1)
        self.assertEqual(report.tmdb_id_missing, 1)
        self.assertEqual(report.imdb_id_missing, 1)

    def test_needs_review_allows_empty_ids(self) -> None:
        candidates = [self._candidate("CB01-001", "Antiviral", "2012")]
        identity = [
            self._identity(
                "CB01-001", "Antiviral", "2012",
                status="needs_review", tmdb_id="", tmdb_title="",
                tmdb_original_title="", tmdb_release_date="", tmdb_year="",
                imdb_id="", method="tmdb_search_details",
                identity_evidence="存在多个同名候选，未自动选择。",
            )
        ]
        report = self._run(candidates, identity)
        self.assertTrue(report.is_valid, [issue.message for issue in report.issues])
        self.assertEqual(report.needs_review, 1)

    def test_each_candidate_requires_exactly_one_row(self) -> None:
        candidates, identity = self._valid_fixture()
        identity.append(dict(identity[1]))
        report = self._run(candidates, identity)
        self.assertIn("identity_duplicate", self._codes(report))

    def test_missing_identity_row_is_error(self) -> None:
        candidates, identity = self._valid_fixture()
        report = self._run(candidates, [identity[0]])
        self.assertIn("identity_missing", self._codes(report))

    def test_confirmed_requires_tmdb_fields(self) -> None:
        candidates, identity = self._valid_fixture()
        identity[0]["tmdb_id"] = ""
        identity[0]["tmdb_url"] = ""
        report = self._run(candidates, identity)
        self.assertIn("tmdb_required", self._codes(report))

    def test_production_identity_file_is_complete(self) -> None:
        data = BACKEND_DIR / "data"
        candidates = data / "candidates" / "cult_candidates_batch01.csv"
        identity = data / "candidates" / "cult_candidate_identity_batch01.csv"
        knowledge = data / "knowledge" / "cult_seed.csv"
        identity_map = data / "knowledge" / "seed_identity_map.csv"
        watched = [candidates, identity, knowledge, identity_map]
        before = {path: _digest(path) for path in watched}

        report = validate_identity_files(candidates, identity, knowledge)

        for path, digest in before.items():
            self.assertEqual(_digest(path), digest, f"校验过程修改了 {path.name}")
        self.assertTrue(report.is_valid, [issue.message for issue in report.issues])
        self.assertEqual(report.total_candidates, 20)
        self.assertEqual(report.identity_rows, 20)
        self.assertEqual(
            report.confirmed
            + report.needs_review
            + report.unmatched
            + report.conflict
            + report.duplicate_existing,
            20,
        )


if __name__ == "__main__":
    unittest.main()
