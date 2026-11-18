"""候选来源交叉验证测试；所有 CSV 均写入临时目录。"""

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

from scripts.validate_candidate_sources import (  # noqa: E402
    CANDIDATE_FIELDS,
    REVIEW_FIELDS,
    SOURCE_FIELDS,
    validate_candidate_review_files,
)

KNOWLEDGE_FIELDS = [
    "seed_id", "title", "original_title", "year", "tmdb_id", "imdb_id"
]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CandidateSourceValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.candidates_path = self.root / "candidates.csv"
        self.sources_path = self.root / "sources.csv"
        self.review_path = self.root / "review.csv"
        self.knowledge_path = self.root / "cult_seed.csv"
        self.criteria_path = self.root / "criteria.csv"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @staticmethod
    def _candidate(candidate_id: str, title: str, code: str) -> dict[str, str]:
        row = {
            "candidate_id": candidate_id,
            "title": title,
            "original_title": title,
            "year": "1977",
            "source_id": "CB01-S01",
            "source_title": "测试片单",
            "source_url": "https://example.com/list",
            "source_evidence": "测试证据，仅用于结构校验。",
            "inclusion_reason": "测试纳入理由",
            "candidate_criteria_codes": code,
            "tmdb_id": "",
            "imdb_id": "",
            "verification_status": "verified",
            "candidate_status": "staged",
            "notes": "临时测试候选",
        }
        return row

    @staticmethod
    def _source(
        candidate_id: str,
        source_id: str,
        role: str,
        publisher: str,
        url: str,
        codes: str = "",
        independence: str = "not_applicable",
        **changes: str,
    ) -> dict[str, str]:
        row = {
            "candidate_id": candidate_id,
            "source_id": source_id,
            "source_role": role,
            "source_title": "测试来源页面",
            "publisher": publisher,
            "source_url": url,
            "publication_date": "",
            "accessed_at": "2026-11-18",
            "language": "en",
            "reliability_tier": "T2",
            "evidence_summary": "测试证据摘要。",
            "locator": "测试段落",
            "supported_criteria": codes,
            "evidence_directness": "direct" if codes else "none",
            "independence_status": independence,
            "verification_status": "verified",
            "notes": "",
        }
        row.update(changes)
        return row

    @staticmethod
    def _review(
        candidate_id: str,
        second_status: str,
        codes: str,
        unsupported: str = "",
        status: str = "pending_human_review",
        **changes: str,
    ) -> dict[str, str]:
        row = {
            "candidate_id": candidate_id,
            "original_source_status": "verified",
            "second_source_status": second_status,
            "evidence_quality": "moderate",
            "supported_criteria": codes,
            "unsupported_criteria": unsupported,
            "review_recommendation": "priority_review",
            "reviewer": "",
            "review_status": status,
            "notes": "",
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
        sources: list[dict[str, str]],
        review: list[dict[str, str]],
    ):
        self._write(self.candidates_path, CANDIDATE_FIELDS, candidates)
        self._write(self.sources_path, SOURCE_FIELDS, sources)
        self._write(self.review_path, REVIEW_FIELDS, review)
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
            self.criteria_path,
            ["criterion_code", "name_zh", "name_en"],
            [
                {"criterion_code": code, "name_zh": code, "name_en": code}
                for code in ("C1", "C4", "C5", "C7")
            ],
        )
        before = {
            path: _digest(path)
            for path in (
                self.candidates_path,
                self.sources_path,
                self.review_path,
                self.knowledge_path,
                self.criteria_path,
            )
        }
        report, _ = validate_candidate_review_files(
            self.candidates_path,
            self.sources_path,
            self.review_path,
            self.knowledge_path,
            self.criteria_path,
        )
        for path, digest in before.items():
            self.assertEqual(_digest(path), digest, f"校验过程修改了 {path.name}")
        return report

    def _valid_fixture(self):
        candidates = [
            self._candidate("CB01-001", "House", "C5"),
            self._candidate("CB01-002", "Bad Timing", "C7"),
        ]
        sources = [
            self._source("CB01-001", "CB01-S01", "primary", "BFI", "https://example.com/list", "C5"),
            self._source("CB01-001", "CB01-S04", "second", "Criterion", "https://example.com/essay", "C1|C5", "independent"),
            self._source("CB01-002", "CB01-S01", "primary", "BFI", "https://example.com/list", "C7"),
        ]
        review = [
            self._review("CB01-001", "verified", "C1|C5"),
            self._review(
                "CB01-002", "not_found", "C7", status="needs_more_evidence",
                review_recommendation="not_recommended_yet",
            ),
        ]
        return candidates, sources, review

    def _codes(self, report) -> set[str]:
        return {issue.code for issue in report.issues}

    def test_valid_fixture_passes(self) -> None:
        report = self._run(*self._valid_fixture())
        self.assertTrue(report.is_valid, [issue.message for issue in report.issues])
        self.assertEqual(report.total_candidates, 2)
        self.assertEqual(report.second_verified, 1)
        self.assertEqual(report.second_not_found, 1)
        self.assertEqual(report.independent_second, 1)

    def test_missing_primary_source_is_error(self) -> None:
        candidates, sources, review = self._valid_fixture()
        sources = [row for row in sources if row["candidate_id"] != "CB01-002"]
        report = self._run(candidates, sources, review)
        self.assertIn("primary_missing", self._codes(report))

    def test_duplicate_primary_source_is_error(self) -> None:
        candidates, sources, review = self._valid_fixture()
        sources.append(
            self._source("CB01-002", "CB01-S02", "primary", "BFI", "https://example.com/other", "C7")
        )
        report = self._run(candidates, sources, review)
        self.assertIn("primary_duplicate", self._codes(report))

    def test_invalid_url_is_error(self) -> None:
        candidates, sources, review = self._valid_fixture()
        sources[1]["source_url"] = "example.com/essay"
        report = self._run(candidates, sources, review)
        self.assertIn("url", self._codes(report))

    def test_empty_publisher_is_error(self) -> None:
        candidates, sources, review = self._valid_fixture()
        sources[1]["publisher"] = ""
        report = self._run(candidates, sources, review)
        self.assertIn("source_required", self._codes(report))

    def test_second_source_with_primary_url_is_rejected(self) -> None:
        candidates, sources, review = self._valid_fixture()
        sources[1]["source_url"] = "https://example.com/list"
        report = self._run(candidates, sources, review)
        self.assertIn("same_source", self._codes(report))

    def test_same_publisher_cannot_be_independent(self) -> None:
        candidates, sources, review = self._valid_fixture()
        sources[1]["publisher"] = "BFI"
        report = self._run(candidates, sources, review)
        self.assertIn("same_publisher", self._codes(report))

    def test_verified_source_requires_access_date(self) -> None:
        candidates, sources, review = self._valid_fixture()
        sources[1]["accessed_at"] = ""
        report = self._run(candidates, sources, review)
        self.assertIn("missing_access", self._codes(report))

    def test_unknown_criterion_code_is_error(self) -> None:
        candidates, sources, review = self._valid_fixture()
        sources[1]["supported_criteria"] = "C9"
        report = self._run(candidates, sources, review)
        self.assertIn("criteria", self._codes(report))

    def test_review_cannot_claim_unsupported_criterion(self) -> None:
        candidates, sources, review = self._valid_fixture()
        review[1]["supported_criteria"] = "C4|C7"
        report = self._run(candidates, sources, review)
        self.assertIn("criteria_unsupported", self._codes(report))

    def test_review_must_record_supported_criterion(self) -> None:
        candidates, sources, review = self._valid_fixture()
        review[0]["supported_criteria"] = "C5"
        report = self._run(candidates, sources, review)
        self.assertIn("criteria_missing", self._codes(report))

    def test_second_source_verified_requires_row(self) -> None:
        candidates, sources, review = self._valid_fixture()
        review[1]["second_source_status"] = "verified"
        report = self._run(candidates, sources, review)
        self.assertIn("second_missing", self._codes(report))

    def test_missing_second_source_keeps_pending_state(self) -> None:
        candidates, sources, review = self._valid_fixture()
        review[1]["review_status"] = "pending_human_review"
        report = self._run(candidates, sources, review)
        self.assertIn("second_pending", self._codes(report))

    def test_approved_status_is_rejected(self) -> None:
        candidates, sources, review = self._valid_fixture()
        review[0]["review_status"] = "approved"
        report = self._run(candidates, sources, review)
        self.assertIn("formal_promotion", self._codes(report))

    def test_verified_status_rejects_unavailable_second_source(self) -> None:
        candidates, sources, review = self._valid_fixture()
        sources[1]["verification_status"] = "unavailable"
        sources[1]["independence_status"] = "unverified"
        report = self._run(candidates, sources, review)
        self.assertIn("second_missing", self._codes(report))
        self.assertFalse(report.is_valid)

    def test_unavailable_status_accepts_unavailable_second_source(self) -> None:
        candidates, sources, review = self._valid_fixture()
        sources[1]["verification_status"] = "unavailable"
        sources[1]["independence_status"] = "unverified"
        sources[1]["supported_criteria"] = ""
        sources[1]["evidence_directness"] = "none"
        review[0]["second_source_status"] = "unavailable"
        review[0]["review_status"] = "needs_more_evidence"
        review[0]["supported_criteria"] = "C5"
        report = self._run(candidates, sources, review)
        self.assertTrue(report.is_valid, [issue.message for issue in report.issues])
        self.assertEqual(report.second_verified, 0)
        self.assertEqual(report.second_unavailable, 1)
        self.assertEqual(report.independent_second, 0)

    def test_unavailable_status_accepts_missing_second_source(self) -> None:
        candidates, sources, review = self._valid_fixture()
        sources = [row for row in sources if row["candidate_id"] != "CB01-001" or row["source_role"] == "primary"]
        review[0]["second_source_status"] = "unavailable"
        review[0]["review_status"] = "needs_more_evidence"
        review[0]["supported_criteria"] = "C5"
        report = self._run(candidates, sources, review)
        self.assertTrue(report.is_valid, [issue.message for issue in report.issues])
        self.assertEqual(report.second_unavailable, 1)
        self.assertEqual(report.second_rows, 0)

    def test_not_found_status_rejects_existing_second_source(self) -> None:
        candidates, sources, review = self._valid_fixture()
        sources.append(
            self._source(
                "CB01-002", "CB01-S05", "second", "Criterion",
                "https://example.com/second", "", "unverified",
                verification_status="unavailable",
            )
        )
        report = self._run(candidates, sources, review)
        self.assertIn("second_conflict", self._codes(report))
        self.assertFalse(report.is_valid)

    def test_verified_status_passes_with_one_verified_among_multiple(self) -> None:
        candidates, sources, review = self._valid_fixture()
        sources.append(
            self._source(
                "CB01-001", "CB01-S05", "second", "The Independent",
                "https://example.com/unavailable", "", "unverified",
                verification_status="unavailable",
            )
        )
        report = self._run(candidates, sources, review)
        self.assertTrue(report.is_valid, [issue.message for issue in report.issues])
        self.assertEqual(report.second_rows, 2)
        self.assertEqual(report.second_verified, 1)
        self.assertEqual(report.independent_second, 1)

    def test_mixed_second_sources_count_only_verified(self) -> None:
        candidates, sources, review = self._valid_fixture()
        sources.append(
            self._source(
                "CB01-001", "CB01-S05", "second", "The Independent",
                "https://example.com/unavailable", "", "unverified",
                verification_status="unavailable",
            )
        )
        report = self._run(candidates, sources, review)
        self.assertEqual(report.second_verified, 1)
        self.assertEqual(report.second_unavailable, 0)
        self.assertEqual(report.independent_second, 1)
        self.assertEqual(report.independent_publishers, 1)
        self.assertEqual(report.independent_urls, 1)

    def test_unavailable_second_source_not_counted_as_independent(self) -> None:
        candidates, sources, review = self._valid_fixture()
        sources[1]["verification_status"] = "unavailable"
        sources[1]["independence_status"] = "independent"
        sources[1]["supported_criteria"] = ""
        sources[1]["evidence_directness"] = "none"
        review[0]["second_source_status"] = "unavailable"
        review[0]["review_status"] = "needs_more_evidence"
        review[0]["supported_criteria"] = "C5"
        report = self._run(candidates, sources, review)
        self.assertTrue(report.is_valid, [issue.message for issue in report.issues])
        self.assertEqual(report.independent_second, 0)
        self.assertEqual(report.independent_publishers, 0)
        self.assertEqual(report.independent_urls, 0)

    def test_production_files_validate_without_touching_knowledge(self) -> None:
        data = BACKEND_DIR / "data"
        knowledge = data / "knowledge" / "cult_seed.csv"
        identity = data / "knowledge" / "seed_identity_map.csv"
        criteria = data / "knowledge" / "cult_criteria.csv"
        candidates = data / "candidates" / "cult_candidates_batch01.csv"
        sources = data / "candidates" / "cult_candidate_sources_batch01.csv"
        review = data / "candidates" / "cult_candidate_review_batch01.csv"
        watched = [knowledge, identity, criteria, candidates, sources, review]
        before = {path: _digest(path) for path in watched}

        report, base_report = validate_candidate_review_files(
            candidates, sources, review, knowledge, criteria
        )

        for path, digest in before.items():
            self.assertEqual(_digest(path), digest, f"校验过程修改了 {path.name}")
        self.assertTrue(base_report.is_valid)
        self.assertTrue(report.is_valid, [issue.message for issue in report.issues])
        self.assertEqual(report.total_candidates, 20)
        self.assertEqual(report.primary_rows, 20)
        self.assertEqual(report.second_rows, 18)
        self.assertEqual(report.second_verified, 18)
        self.assertEqual(report.second_unavailable, 1)
        self.assertEqual(report.second_not_found, 1)
        self.assertEqual(
            report.second_verified + report.second_not_found + report.second_unavailable,
            20,
        )
        self.assertEqual(report.independent_second, 16)
        self.assertEqual(report.independent_publishers, 12)
        self.assertEqual(report.independent_urls, 14)
        self.assertEqual(report.criteria_supported, 26)
        self.assertEqual(report.pending_human_review, 15)
        self.assertEqual(report.needs_more_evidence, 5)
        self.assertEqual(report.approved, 0)
        self.assertEqual(
            report.criteria_distribution,
            {"C1": 4, "C4": 3, "C5": 14, "C7": 5},
        )
        self.assertEqual(report.pending_human_review + report.needs_more_evidence, 20)


if __name__ == "__main__":
    unittest.main()
