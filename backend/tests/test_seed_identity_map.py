"""seed_identity_map 的独立临时数据测试，不读取或覆盖生产 CSV。"""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts.build_seed_identity_map import (  # noqa: E402
    FIELDNAMES,
    IdentityMapError,
    generate_identity_map,
)

EXPLORE_FIELDS = ["seed_id", "title", "year", "note"]
KNOWLEDGE_FIELDS = [
    "seed_id",
    "title",
    "original_title",
    "year",
    "tmdb_id",
    "imdb_id",
    "candidate_source_ids",
    "cult_criteria_codes",
    "review_status",
    "confidence",
    "reviewer",
    "reviewed_at",
    "notes",
]
MOVIE_FIELDS = [
    "seed_id",
    "seed_title",
    "seed_year",
    "match_status",
    "matched_title",
    "tmdb_id",
    "imdb_id",
]


class SeedIdentityMapTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.explore_path = self.root / "seed_movies.csv"
        self.knowledge_path = self.root / "cult_seed.csv"
        self.movies_path = self.root / "cult_movies.csv"
        self.output_path = self.root / "seed_identity_map.csv"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @staticmethod
    def _explore(
        seed_id: str = "1", title: str = "Film", year: str = "2000"
    ) -> dict[str, str]:
        return {
            "seed_id": seed_id,
            "title": title,
            "year": year,
            "note": "临时测试种子",
        }

    @staticmethod
    def _knowledge(
        seed_id: str = "CS-0001",
        original_title: str = "Film",
        year: str = "2000",
        tmdb_id: str = "100",
        imdb_id: str = "tt0000100",
    ) -> dict[str, str]:
        row = {field: "" for field in KNOWLEDGE_FIELDS}
        row.update(
            seed_id=seed_id,
            title="译名",
            original_title=original_title,
            year=year,
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
            review_status="draft",
        )
        return row

    @staticmethod
    def _movie(
        seed_id: str = "1",
        title: str = "Film",
        year: str = "2000",
        tmdb_id: str = "100",
        imdb_id: str = "",
    ) -> dict[str, str]:
        return {
            "seed_id": seed_id,
            "seed_title": title,
            "seed_year": year,
            "match_status": "matched" if tmdb_id or imdb_id else "not_found",
            "matched_title": "译名" if tmdb_id or imdb_id else "",
            "tmdb_id": tmdb_id,
            "imdb_id": imdb_id,
        }

    @staticmethod
    def _auto_confirmed(**changes: str) -> dict[str, str]:
        row = {
            "explore_seed_id": "1",
            "knowledge_seed_id": "CS-0001",
            "tmdb_id": "100",
            "imdb_id": "tt0000100",
            "match_method": "tmdb_id",
            "match_status": "confirmed",
            "notes": "临时自动确认记录",
        }
        row.update(changes)
        return row

    def _write_csv(
        self, path: Path, fields: list[str], rows: list[dict[str, str]]
    ) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=fields, lineterminator="\n"
            )
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in fields})

    def _read_output(self) -> list[dict[str, str]]:
        with self.output_path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def _run(
        self,
        explore: list[dict[str, str]],
        knowledge: list[dict[str, str]],
        movies: list[dict[str, str]],
        *,
        existing: list[dict[str, str]] | None = None,
        write: bool = False,
    ) -> tuple[list[dict[str, str]], list[str]]:
        self._write_csv(self.explore_path, EXPLORE_FIELDS, explore)
        self._write_csv(self.knowledge_path, KNOWLEDGE_FIELDS, knowledge)
        self._write_csv(self.movies_path, MOVIE_FIELDS, movies)
        if existing is not None:
            self._write_csv(self.output_path, FIELDNAMES, existing)
        input_paths = [self.explore_path, self.knowledge_path, self.movies_path]
        before = {path: path.read_bytes() for path in input_paths}
        result = generate_identity_map(
            self.explore_path,
            self.knowledge_path,
            self.movies_path,
            self.output_path,
            write=write,
        )
        for path in input_paths:
            self.assertEqual(path.read_bytes(), before[path])
        return result

    def test_tmdb_id_match_is_confirmed(self) -> None:
        rows, anomalies = self._run(
            [self._explore()], [self._knowledge()], [self._movie()]
        )
        self.assertEqual(rows[0]["match_status"], "confirmed")
        self.assertEqual(rows[0]["match_method"], "tmdb_id")
        self.assertEqual(rows[0]["knowledge_seed_id"], "CS-0001")
        self.assertEqual(rows[0]["imdb_id"], "tt0000100")
        self.assertEqual(anomalies, [])

    def test_imdb_id_match_is_confirmed(self) -> None:
        rows, anomalies = self._run(
            [self._explore()],
            [self._knowledge(tmdb_id="", imdb_id="tt0000999")],
            [self._movie(tmdb_id="", imdb_id="tt0000999")],
        )
        self.assertEqual(rows[0]["match_status"], "confirmed")
        self.assertEqual(rows[0]["match_method"], "imdb_id")
        self.assertEqual(anomalies, [])

    def test_title_year_without_ids_needs_review(self) -> None:
        rows, _ = self._run(
            [self._explore()],
            [self._knowledge(tmdb_id="", imdb_id="")],
            [],
        )
        self.assertEqual(rows[0]["match_status"], "needs_review")
        self.assertEqual(rows[0]["match_method"], "title_year")
        self.assertEqual(rows[0]["knowledge_seed_id"], "CS-0001")

    def test_same_title_different_year_needs_review(self) -> None:
        rows, _ = self._run(
            [self._explore(year="2001")],
            [self._knowledge(year="2000", tmdb_id="", imdb_id="")],
            [],
        )
        self.assertEqual(rows[0]["match_status"], "needs_review")
        self.assertEqual(rows[0]["match_method"], "title_year_conflict")
        self.assertIn("年份不同", rows[0]["notes"])

    def test_id_conflict_is_not_confirmed(self) -> None:
        rows, _ = self._run(
            [self._explore()],
            [self._knowledge(tmdb_id="100")],
            [self._movie(tmdb_id="999")],
        )
        self.assertEqual(rows[0]["match_status"], "needs_review")
        self.assertEqual(rows[0]["match_method"], "id_conflict")
        self.assertIn("TMDb ID 冲突", rows[0]["notes"])

    def test_duplicate_stable_id_mapping_is_not_assigned(self) -> None:
        rows, anomalies = self._run(
            [self._explore("1"), self._explore("2")],
            [self._knowledge()],
            [self._movie("1"), self._movie("2")],
        )
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row["match_status"], "needs_review")
            self.assertEqual(row["match_method"], "duplicate_mapping")
            self.assertEqual(row["knowledge_seed_id"], "")
        self.assertEqual(len(anomalies), 2)

    def test_unmatched_movie(self) -> None:
        rows, anomalies = self._run(
            [self._explore(title="Other", year="2001")],
            [self._knowledge()],
            [self._movie(title="Other", year="2001", tmdb_id="999")],
        )
        self.assertEqual(rows[0]["match_status"], "unmatched")
        self.assertEqual(rows[0]["match_method"], "none")
        self.assertEqual(rows[0]["knowledge_seed_id"], "")
        self.assertEqual(len(anomalies), 1)

    def test_existing_manual_confirmation_is_preserved(self) -> None:
        manual = {
            "explore_seed_id": "1",
            "knowledge_seed_id": "CS-0001",
            "tmdb_id": "100",
            "imdb_id": "tt0000100",
            "match_method": "manual",
            "match_status": "confirmed",
            "notes": "人工确认：TEST-REVIEWER；版本已复核，不得自动覆盖",
        }
        rows, anomalies = self._run(
            [self._explore()],
            [
                self._knowledge(),
                self._knowledge(
                    seed_id="CS-0002",
                    tmdb_id="200",
                    imdb_id="tt0000200",
                ),
            ],
            [self._movie(tmdb_id="200", imdb_id="tt0000200")],
            existing=[manual],
            write=True,
        )
        self.assertEqual(rows, [manual])
        self.assertEqual(self._read_output(), [manual])
        self.assertTrue(any("已保留人工记录" in item for item in anomalies))

    def test_repeated_write_is_byte_identical(self) -> None:
        self._run(
            [self._explore()],
            [self._knowledge()],
            [self._movie()],
            write=True,
        )
        first = self.output_path.read_bytes()
        self._run(
            [self._explore()],
            [self._knowledge()],
            [self._movie()],
            write=True,
        )
        self.assertEqual(self.output_path.read_bytes(), first)
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_invalid_existing_duplicate_stops_without_overwrite(self) -> None:
        existing = [
            {
                "explore_seed_id": "1",
                "knowledge_seed_id": "CS-0001",
                "tmdb_id": "100",
                "imdb_id": "tt0000100",
                "match_method": "manual",
                "match_status": "confirmed",
                "notes": "人工记录 A",
            },
            {
                "explore_seed_id": "2",
                "knowledge_seed_id": "CS-0001",
                "tmdb_id": "100",
                "imdb_id": "tt0000100",
                "match_method": "manual",
                "match_status": "confirmed",
                "notes": "人工记录 B",
            },
        ]
        with self.assertRaises(IdentityMapError):
            self._run(
                [self._explore("1"), self._explore("2")],
                [self._knowledge()],
                [self._movie("1"), self._movie("2")],
                existing=existing,
                write=True,
            )
        self.assertEqual(self._read_output(), existing)

    def test_check_mode_does_not_create_output(self) -> None:
        self._run(
            [self._explore()], [self._knowledge()], [self._movie()], write=False
        )
        self.assertFalse(self.output_path.exists())

    def test_movie_seed_year_must_match_explore_seed_year(self) -> None:
        with self.assertRaisesRegex(IdentityMapError, "seed_year"):
            self._run(
                [self._explore(year="2000")],
                [self._knowledge()],
                [self._movie(year="1999")],
                write=True,
            )
        self.assertFalse(self.output_path.exists())

    def test_confirmed_knowledge_id_change_blocks_overwrite(self) -> None:
        old = self._auto_confirmed()
        with self.assertRaisesRegex(IdentityMapError, "知识库 ID"):
            self._run(
                [self._explore()],
                [self._knowledge(seed_id="CS-0002")],
                [self._movie()],
                existing=[old],
                write=True,
            )
        self.assertEqual(self._read_output(), [old])

    def test_confirmed_tmdb_id_change_blocks_overwrite(self) -> None:
        old = self._auto_confirmed()
        with self.assertRaisesRegex(IdentityMapError, "TMDb ID"):
            self._run(
                [self._explore()],
                [self._knowledge(tmdb_id="200")],
                [self._movie(tmdb_id="200")],
                existing=[old],
                write=True,
            )
        self.assertEqual(self._read_output(), [old])

    def test_confirmed_imdb_id_change_blocks_overwrite(self) -> None:
        old = self._auto_confirmed()
        with self.assertRaisesRegex(IdentityMapError, "IMDb ID"):
            self._run(
                [self._explore()],
                [self._knowledge(imdb_id="tt0000999")],
                [self._movie()],
                existing=[old],
                write=True,
            )
        self.assertEqual(self._read_output(), [old])

    def test_confirmed_status_change_blocks_overwrite(self) -> None:
        old = self._auto_confirmed()
        with self.assertRaisesRegex(IdentityMapError, "状态"):
            self._run(
                [self._explore()],
                [self._knowledge()],
                [],
                existing=[old],
                write=True,
            )
        self.assertEqual(self._read_output(), [old])

    def test_check_mode_reports_confirmed_difference_without_writing(self) -> None:
        old = self._auto_confirmed()
        rows, anomalies = self._run(
            [self._explore()],
            [self._knowledge(seed_id="CS-0002")],
            [self._movie()],
            existing=[old],
            write=False,
        )
        self.assertEqual(rows[0]["knowledge_seed_id"], "CS-0002")
        self.assertTrue(any("confirmed 差异" in item for item in anomalies))
        self.assertEqual(self._read_output(), [old])


if __name__ == "__main__":
    unittest.main()
