"""Cult 候选暂存校验测试；所有 CSV 均位于临时目录。"""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts.validate_cult_candidates import (  # noqa: E402
    CANDIDATE_FIELDS,
    can_enter_knowledge_review,
    validate_candidate_files,
)

KNOWLEDGE_FIELDS = [
    "seed_id", "title", "original_title", "year", "tmdb_id", "imdb_id"
]


class CultCandidateValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.candidates_path = self.root / "candidates.csv"
        self.knowledge_path = self.root / "cult_seed.csv"
        self.criteria_path = self.root / "cult_criteria.csv"
        self.identity_path = self.root / "seed_identity_map.csv"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @staticmethod
    def _candidate(**changes: str) -> dict[str, str]:
        row = {
            "candidate_id": "CB01-001",
            "title": "House",
            "original_title": "Hausu",
            "year": "1977",
            "source_id": "CB01-S01",
            "source_title": "测试来源",
            "source_url": "https://example.com/cult-list",
            "source_evidence": "测试证据，仅用于结构校验。",
            "inclusion_reason": "测试纳入理由",
            "candidate_criteria_codes": "C5",
            "tmdb_id": "",
            "imdb_id": "",
            "verification_status": "verified",
            "candidate_status": "staged",
            "notes": "临时测试候选",
        }
        row.update(changes)
        return row

    def _write(self, path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def _run(self, candidates: list[dict[str, str]]):
        self._write(self.candidates_path, CANDIDATE_FIELDS, candidates)
        self._write(
            self.knowledge_path,
            KNOWLEDGE_FIELDS,
            [{
                "seed_id": "CS-0001",
                "title": "橡皮头",
                "original_title": "Eraserhead",
                "year": "1977",
                "tmdb_id": "985",
                "imdb_id": "tt0074486",
            }],
        )
        self._write(
            self.criteria_path, ["criterion_code"], [{"criterion_code": "C5"}]
        )
        original_identity = (
            "explore_seed_id,knowledge_seed_id,match_status\n"
            "1,CS-0001,confirmed\n"
        ).encode("utf-8")
        self.identity_path.write_bytes(original_identity)
        report = validate_candidate_files(
            self.candidates_path, self.knowledge_path, self.criteria_path
        )
        self.assertEqual(self.identity_path.read_bytes(), original_identity)
        return report

    def test_valid_verified_candidate(self) -> None:
        candidate = self._candidate()
        report = self._run([candidate])
        self.assertTrue(report.is_valid)
        self.assertEqual(report.verified, 1)
        self.assertEqual(report.duplicates, 0)
        self.assertTrue(can_enter_knowledge_review(candidate))

    def test_candidate_id_must_be_unique(self) -> None:
        report = self._run([
            self._candidate(),
            self._candidate(title="Other", original_title="Other", year="1980"),
        ])
        self.assertTrue(any(issue.code == "candidate_id" for issue in report.errors))

    def test_verified_candidate_requires_complete_source(self) -> None:
        report = self._run([
            self._candidate(source_title="", source_evidence="")
        ])
        codes = {issue.code for issue in report.errors}
        self.assertIn("source_required", codes)
        self.assertIn("missing_evidence", codes)

    def test_url_format_is_validated(self) -> None:
        report = self._run([self._candidate(source_url="not-a-url")])
        self.assertTrue(any(issue.code == "url" for issue in report.errors))

    def test_year_must_be_valid_and_not_future(self) -> None:
        report = self._run([self._candidate(year="3026")])
        self.assertTrue(any(issue.code == "year" for issue in report.errors))

    def test_existing_sample_title_year_duplicate_is_rejected(self) -> None:
        report = self._run([
            self._candidate(title="Eraserhead", original_title="Eraserhead")
        ])
        self.assertEqual(report.duplicates, 1)
        self.assertFalse(report.is_valid)

    def test_same_title_different_year_is_warning_not_duplicate(self) -> None:
        report = self._run([
            self._candidate(
                title="Eraserhead", original_title="Eraserhead", year="1978"
            )
        ])
        self.assertEqual(report.duplicates, 0)
        self.assertTrue(report.is_valid)
        self.assertTrue(any(
            issue.code == "same_title_different_year" for issue in report.issues
        ))

    def test_unverified_candidate_cannot_enter_knowledge_review(self) -> None:
        candidate = self._candidate(
            verification_status="unverified",
            source_evidence="",
            notes="测试：页面当前无法访问",
        )
        report = self._run([candidate])
        self.assertTrue(report.is_valid)
        self.assertEqual(report.unverified, 1)
        self.assertFalse(can_enter_knowledge_review(candidate))

    def test_unverified_candidate_ids_must_be_empty(self) -> None:
        candidate = self._candidate(
            verification_status="unverified",
            source_evidence="",
            notes="测试：来源尚未核验",
            tmdb_id="123",
        )
        report = self._run([candidate])
        self.assertTrue(any(issue.code == "unverified_ids" for issue in report.errors))
        self.assertFalse(can_enter_knowledge_review(candidate))

    def test_candidate_cannot_be_promoted_to_formal_status(self) -> None:
        candidate = self._candidate(
            verification_status="unverified",
            candidate_status="approved",
            source_evidence="",
            notes="测试：不得直接批准",
        )
        report = self._run([candidate])
        self.assertTrue(any(issue.code == "formal_promotion" for issue in report.errors))
        self.assertFalse(can_enter_knowledge_review(candidate))

    def test_validation_leaves_identity_map_unchanged(self) -> None:
        before = self.identity_path.read_bytes() if self.identity_path.exists() else None
        self._run([self._candidate()])
        after = self.identity_path.read_bytes()
        if before is not None:
            self.assertEqual(after, before)
        self.assertIn(b"CS-0001", after)


if __name__ == "__main__":
    unittest.main()
