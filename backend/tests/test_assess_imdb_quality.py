"""IMDb 质量评估脚本的离线小样本测试。

所有夹具均在临时目录生成，不读取真实 IMDb 数据，也不修改任何正式数据。
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import scripts.assess_imdb_quality as quality_module  # noqa: E402
from scripts.assess_imdb_quality import (  # noqa: E402
    QualityError,
    BASICS_COLUMNS,
    RATINGS_COLUMNS,
    assess,
    main,
)


BASICS_HEADER = list(BASICS_COLUMNS)
RATINGS_HEADER = list(RATINGS_COLUMNS)


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


class AssessImdbQualityTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.basics = self.root / "imdb_titles_movies.csv"
        self.ratings = self.root / "imdb_ratings.csv"
        self.report = self.root / "imdb_quality_report.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _assess(self, basics_rows, ratings_rows, **overrides):
        _write_csv(self.basics, BASICS_HEADER, basics_rows)
        _write_csv(self.ratings, RATINGS_HEADER, ratings_rows)
        params = {"dry_run": True}
        params.update(overrides)
        return assess(self.basics, self.ratings, self.report, **params)

    # ---------- 既有测试：保留并适配新字段 ----------

    def test_normal_dataset(self) -> None:
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "1994", "", "142", "Drama", "2026-11-18"],
            ["tt0000002", "movie", "B", "B", "0", "2001", "", "125", "Animation", "2026-11-18"],
            ["tt0000003", "movie", "C", "C", "0", "2010", "2015", "90", "Comedy", "2026-11-18"],
        ]
        ratings = [
            ["tt0000001", "8.7", "1000", "2026-11-18"],
            ["tt0000002", "7.5", "500", "2026-11-18"],
            ["tt0000003", "6.0", "50", "2026-11-18"],
        ]
        report = self._assess(basics, ratings)
        self.assertEqual(report["basics"]["rows_total"], 3)
        self.assertEqual(report["basics"]["unique_tconst"], 3)
        self.assertEqual(report["ratings"]["rows_total"], 3)
        self.assertEqual(report["basics"]["rating_coverage_ratio"], 1.0)
        # 票数桶：50 -> 11-100；500/1000 -> 101-1k 边界
        votes = report["ratings"]["votes_bucket_histogram"]
        self.assertEqual(votes["11-100"], 1)   # 50
        self.assertEqual(votes["101-1k"], 2)  # 500 + 1000

    def test_missing_basics_fields(self) -> None:
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "", "", "142", "Drama", "2026-11-18"],
            ["tt0000002", "movie", "B", "B", "0", "2001", "", "", "", "2026-11-18"],
            ["tt0000003", "movie", "C", "C", "0", "2010", "2015", "0", "Comedy", "2026-11-18"],
        ]
        ratings = [["tt0000001", "8.7", "1000", "2026-11-18"]]
        report = self._assess(basics, ratings)
        self.assertEqual(report["basics"]["missing_start_year"], 1)
        self.assertEqual(report["basics"]["missing_runtime"], 1)
        self.assertEqual(report["basics"]["missing_genres"], 1)
        self.assertEqual(report["basics"]["zero_runtime"], 1)
        self.assertEqual(report["basics"]["missing_end_year"], 2)

    def test_abnormal_years(self) -> None:
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "1800", "", "142", "Drama", "2026-11-18"],
            ["tt0000002", "movie", "B", "B", "0", "9999", "", "125", "Animation", "2026-11-18"],
            ["tt0000003", "movie", "C", "C", "0", "notyear", "", "90", "Comedy", "2026-11-18"],
            ["tt0000004", "movie", "D", "D", "0", "2020", "", "90", "Comedy", "2026-11-18"],
        ]
        report = self._assess(basics, [])
        self.assertEqual(report["basics"]["invalid_start_year"], 2)
        self.assertEqual(report["basics"]["future_start_year"], 1)

    def test_duplicate_tconst(self) -> None:
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "1994", "", "142", "Drama", "2026-11-18"],
            ["tt0000001", "movie", "A dup", "A dup", "0", "1994", "", "142", "Drama", "2026-11-18"],
            ["tt0000002", "movie", "B", "B", "0", "2001", "", "125", "Animation", "2026-11-18"],
        ]
        ratings = [
            ["tt0000001", "8.7", "1000", "2026-11-18"],
            ["tt0000001", "9.0", "2000", "2026-11-18"],
            ["tt0000002", "7.5", "500", "2026-11-18"],
        ]
        report = self._assess(basics, ratings)
        self.assertEqual(report["basics"]["duplicate_tconst"], 1)
        self.assertEqual(report["ratings"]["duplicate_tconst"], 1)

    def test_invalid_ratings_and_votes(self) -> None:
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "1994", "", "142", "Drama", "2026-11-18"],
            ["tt0000002", "movie", "B", "B", "0", "2001", "", "125", "Animation", "2026-11-18"],
            ["tt0000003", "movie", "C", "C", "0", "2010", "", "90", "Comedy", "2026-11-18"],
            ["tt0000004", "movie", "D", "D", "0", "2015", "", "90", "Action", "2026-11-18"],
            ["tt0000005", "movie", "E", "E", "0", "2020", "", "90", "Drama", "2026-11-18"],
        ]
        ratings = [
            ["tt0000001", "8.7", "1000", "2026-11-18"],
            ["tt0000002", "", "500", "2026-11-18"],
            ["tt0000003", "15.0", "50", "2026-11-18"],
            ["tt0000004", "6.0", "0", "2026-11-18"],
            ["tt0000005", "7.5", "abc", "2026-11-18"],
        ]
        report = self._assess(basics, ratings)
        self.assertEqual(report["ratings"]["invalid_rating"], 1)
        self.assertEqual(report["ratings"]["rating_out_of_range"], 1)
        self.assertEqual(report["ratings"]["votes_out_of_range"], 1)
        self.assertEqual(report["ratings"]["invalid_votes"], 1)

    def test_orphan_ratings(self) -> None:
        basics = [["tt0000001", "movie", "A", "A", "0", "1994", "", "142", "Drama", "2026-11-18"]]
        ratings = [
            ["tt0000001", "8.7", "1000", "2026-11-18"],
            ["tt9999999", "7.0", "100", "2026-11-18"],
        ]
        report = self._assess(basics, ratings)
        self.assertEqual(report["ratings"]["orphan_count"], 1)

    def test_partial_coverage(self) -> None:
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "1994", "", "142", "Drama", "2026-11-18"],
            ["tt0000002", "movie", "B", "B", "0", "2001", "", "125", "Animation", "2026-11-18"],
            ["tt0000003", "movie", "C", "C", "0", "2010", "", "90", "Comedy", "2026-11-18"],
        ]
        ratings = [["tt0000001", "8.7", "1000", "2026-11-18"]]
        report = self._assess(basics, ratings)
        self.assertAlmostEqual(report["basics"]["rating_coverage_ratio"], 1 / 3, places=6)

    def test_empty_data_frames(self) -> None:
        _write_csv(self.basics, BASICS_HEADER, [])
        _write_csv(self.ratings, RATINGS_HEADER, [])
        report = assess(self.basics, self.ratings, self.report, dry_run=True)
        self.assertEqual(report["basics"]["rows_total"], 0)
        self.assertEqual(report["ratings"]["rows_total"], 0)
        self.assertIsNone(report["ratings"]["rating_min"])
        self.assertEqual(report["basics"]["rating_coverage_ratio"], 0.0)

    def test_report_is_written(self) -> None:
        basics = [["tt0000001", "movie", "A", "A", "0", "1994", "", "142", "Drama", "2026-11-18"]]
        ratings = [["tt0000001", "8.7", "1000", "2026-11-18"]]
        self._assess(basics, ratings, dry_run=False)
        self.assertTrue(self.report.exists())
        saved = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertEqual(saved["basics"]["rows_total"], 1)
        self.assertIn("generated_at", saved)
        self.assertIn("sha256", saved["basics_input"])

    def test_dry_run_writes_nothing(self) -> None:
        basics = [["tt0000001", "movie", "A", "A", "0", "1994", "", "142", "Drama", "2026-11-18"]]
        ratings = [["tt0000001", "8.7", "1000", "2026-11-18"]]
        self._assess(basics, ratings, dry_run=True)
        self.assertFalse(self.report.exists())

    def test_missing_file_returns_nonzero(self) -> None:
        missing = self.root / "not_exists.csv"
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = main([
                "--basics", str(missing),
                "--ratings", str(missing),
                "--output", str(self.report),
                "--dry-run",
            ])
        self.assertEqual(code, 1)
        self.assertIn("[错误]", stderr.getvalue())

    def test_cli_help_exits_zero(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                main(["--help"])
        self.assertEqual(caught.exception.code, 0)

    # ---------- 新增：3.5.3A.1 边界/保护/隐私测试 ----------

    def test_max_rows_one(self) -> None:
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "1994", "", "142", "Drama", "2026-11-18"],
            ["tt0000002", "movie", "B", "B", "0", "2001", "", "125", "Animation", "2026-11-18"],
        ]
        ratings = [
            ["tt0000001", "8.7", "1000", "2026-11-18"],
            ["tt0000002", "7.5", "500", "2026-11-18"],
        ]
        report = self._assess(basics, ratings, max_rows=1)
        self.assertEqual(report["basics"]["rows_total"], 1)
        self.assertEqual(report["basics"]["unique_tconst"], 1)
        self.assertEqual(report["ratings"]["rows_total"], 1)
        self.assertEqual(report["assessment_constraints"]["max_rows_per_table"], 1)

    def test_max_rows_two(self) -> None:
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "1994", "", "142", "Drama", "2026-11-18"],
            ["tt0000002", "movie", "B", "B", "0", "2001", "", "125", "Animation", "2026-11-18"],
            ["tt0000003", "movie", "C", "C", "0", "2010", "", "90", "Comedy", "2026-11-18"],
        ]
        ratings = [["tt0000001", "8.7", "1000", "2026-11-18"]]
        report = self._assess(basics, ratings, max_rows=2)
        self.assertEqual(report["basics"]["rows_total"], 2)
        self.assertEqual(report["ratings"]["rows_total"], 1)

    def test_max_rows_zero_is_rejected(self) -> None:
        basics = [["tt0000001", "movie", "A", "A", "0", "1994", "", "142", "Drama", "2026-11-18"]]
        ratings = [["tt0000001", "8.7", "1000", "2026-11-18"]]
        with self.assertRaises(QualityError):
            self._assess(basics, ratings, max_rows=0)

    def test_max_rows_negative_is_rejected(self) -> None:
        basics = [["tt0000001", "movie", "A", "A", "0", "1994", "", "142", "Drama", "2026-11-18"]]
        ratings = [["tt0000001", "8.7", "1000", "2026-11-18"]]
        with self.assertRaises(QualityError):
            self._assess(basics, ratings, max_rows=-1)

    def test_cli_max_rows_nonpositive_returns_two(self) -> None:
        self._assess(
            [["tt0000001", "movie", "A", "A", "0", "1994", "", "142", "Drama", "2026-11-18"]],
            [["tt0000001", "8.7", "1000", "2026-11-18"]],
            dry_run=True,
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = main([
                "--basics", str(self.basics),
                "--ratings", str(self.ratings),
                "--output", str(self.report),
                "--max-rows", "0",
                "--dry-run",
            ])
        self.assertEqual(code, 2)
        self.assertIn("--max-rows", stderr.getvalue())

    def test_rejects_overwriting_imdb_csv(self) -> None:
        """仓库内默认 IMDb CSV 不得作为 --output。

        不从本测试写入生产 CSV，仅验证 QualityError 被抛出。
        """
        with self.assertRaises(QualityError) as caught:
            assess(
                self.basics,
                self.ratings,
                quality_module.DEFAULT_BASICS,
                dry_run=False,
            )
        self.assertIn("输出路径不在允许范围", str(caught.exception))

    def test_rejects_overwriting_knowledge(self) -> None:
        knowledge_root = quality_module.BACKEND_DIR / "data" / "knowledge" / "test_report.json"
        with self.assertRaises(QualityError) as caught:
            assess(
                self.basics,
                self.ratings,
                knowledge_root,
                dry_run=False,
            )
        self.assertIn("输出路径不在允许范围", str(caught.exception))

    def test_accepts_repo_root_default_output(self) -> None:
        # dry-run 跳过输出路径检查；用临时夹具验证 assess 正常执行
        self._assess(
            [["tt0000001", "movie", "A", "A", "0", "1994", "", "142", "Drama", "2026-11-18"]],
            [["tt0000001", "8.7", "1000", "2026-11-18"]],
            dry_run=True,
        )
        # 验证 _assert_safe_output 对 DEFAULT_OUTPUT 放行（用 dry_run=False 绕过写文件）
        # 直接调用内部函数验证
        from scripts.assess_imdb_quality import _assert_safe_output
        _assert_safe_output(quality_module.DEFAULT_OUTPUT)  # 不应抛异常

        # 同时验证非允许路径在非 dry-run 下被拒绝
        with self.assertRaises(QualityError):
            _assert_safe_output(quality_module.DEFAULT_BASICS)

    def test_repo_relative_path_privacy(self) -> None:
        """仓库内路径写入报告时使用相对路径。

        用一个真实临时目录伪装为仓库根，不触碰生产数据。
        """
        from unittest import mock
        fake_repo = Path(tempfile.mkdtemp(prefix="fake-repo-"))
        try:
            fake_path = fake_repo / "backend" / "data" / "processed" / "large" / "imdb_titles_movies.csv"
            with mock.patch.object(quality_module, "REPO_ROOT", fake_repo):
                label = quality_module._safe_input_label(fake_path)
            self.assertEqual(label.replace("\\", "/"), "backend/data/processed/large/imdb_titles_movies.csv")
            self.assertNotIn("C:\\", label)
            self.assertNotIn("Users", label)
        finally:
            import shutil as _shutil
            _shutil.rmtree(fake_repo, ignore_errors=True)

    def test_external_input_path_label_is_filename_only(self) -> None:
        """仓库外路径只保留 external:<filename>，不泄露绝对路径。"""
        from unittest import mock
        fake_repo = Path(tempfile.mkdtemp(prefix="fake-repo-"))
        try:
            external_path = Path(tempfile.gettempdir()) / "secret_basics.csv"
            with mock.patch.object(quality_module, "REPO_ROOT", fake_repo):
                label = quality_module._safe_input_label(external_path)
            self.assertEqual(label, "external:secret_basics.csv")
        finally:
            import shutil as _shutil
            _shutil.rmtree(fake_repo, ignore_errors=True)

    def test_external_input_path_privacy(self) -> None:
        """仓库外输入路径只保留 external:<filename>，不泄露绝对路径。"""
        self._assess([["tt0000001", "movie", "A", "A", "0", "1994", "", "142", "Drama", "2026-11-18"]],
                    [["tt0000001", "8.7", "1000", "2026-11-18"]],
                    dry_run=False)
        saved = json.loads(self.report.read_text(encoding="utf-8"))
        basics_file = saved["basics"]["file"]
        self.assertTrue(basics_file.startswith("external:"))
        self.assertEqual(basics_file, "external:" + self.basics.name)
        self.assertNotIn("Users", json.dumps(saved))
        self.assertNotIn("C:\\", json.dumps(saved))

    def test_atomic_write_preserves_existing_on_oserror(self) -> None:
        """模拟 os.replace 失败：旧报告文件保持不变，临时文件清理。"""
        old_content = '{"stale": true}\n'
        self.report.write_text(old_content, encoding="utf-8")

        self._assess([["tt0000001", "movie", "A", "A", "0", "1994", "", "142", "Drama", "2026-11-18"]],
                    [["tt0000001", "8.7", "1000", "2026-11-18"]],
                    dry_run=True)

        import unittest.mock as mock

        def fake_replace(src, dst):
            raise OSError("injected replace failure")

        with mock.patch.object(os, "replace", side_effect=fake_replace):
            with self.assertRaises(Exception):
                assess(self.basics, self.ratings, self.report)

        self.assertEqual(self.report.read_text(encoding="utf-8"), old_content)
        leftovers = [p for p in self.report.parent.iterdir() if p.name.endswith(".part")]
        self.assertEqual(leftovers, [])

    def test_atomic_write_succeeds_normally(self) -> None:
        """正常写入不会残留 .part。"""
        self._assess([["tt0000001", "movie", "A", "A", "0", "1994", "", "142", "Drama", "2026-11-18"]],
                    [["tt0000001", "8.7", "1000", "2026-11-18"]],
                    dry_run=False)
        self.assertTrue(self.report.exists())
        leftovers = [p for p in self.report.parent.iterdir() if p.name.endswith(".part")]
        self.assertEqual(leftovers, [])

    # ---------- 辅助 ----------

    def _basic_default(self) -> Path:
        return quality_module.DEFAULT_BASICS

    def _rating_default(self) -> Path:
        return quality_module.DEFAULT_RATINGS


if __name__ == "__main__":
    unittest.main()
