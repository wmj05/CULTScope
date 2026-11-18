"""IMDb 摄取脚本的小样本测试。

所有夹具均在临时目录中程序生成，不读取、不修改生产 CSV，
也不下载任何真实 IMDb 数据。
"""

from __future__ import annotations

import contextlib
import csv
import gzip
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import scripts.ingest_imdb as ingest_module  # noqa: E402
from scripts.ingest_imdb import (  # noqa: E402
    BASICS_MANIFEST_NAME,
    BASICS_OUTPUT_COLUMNS,
    BASICS_OUTPUT_NAME,
    RATINGS_MANIFEST_NAME,
    RATINGS_OUTPUT_COLUMNS,
    RATINGS_OUTPUT_NAME,
    IngestError,
    ingest_imdb,
    main,
)

BASICS_HEADER = [
    "tconst",
    "titleType",
    "primaryTitle",
    "originalTitle",
    "isAdult",
    "startYear",
    "endYear",
    "runtimeMinutes",
    "genres",
]

# 8 行：1 正常、1 剧集、1 短片、1 成人、1 全缺失、1 特殊字符、1 重复、1 非法数值
BASICS_ROWS = [
    ["tt0000001", "movie", "The Normal Film", "The Normal Film", "0", "1994", "\\N", "142", "Drama|Crime"],
    ["tt0000002", "tvSeries", "A Series", "A Series", "0", "2010", "2015", "45", "Drama"],
    ["tt0000003", "short", "A Short", "A Short", "0", "2001", "\\N", "12", "Comedy"],
    ["tt0000004", "movie", "An Adult Film", "An Adult Film", "1", "1999", "\\N", "90", "Adult"],
    ["tt0000005", "movie", "Missing Meta", "Missing Meta", "0", "\\N", "\\N", "\\N", "\\N"],
    ["tt0000006", "movie", 'The "Quote", Film', "千与千寻", "0", "2001", "\\N", "125", "Animation|Fantasy"],
    ["tt0000001", "movie", "Duplicate Entry", "Duplicate Entry", "0", "1994", "\\N", "100", "Drama"],
    ["tt0000008", "movie", "Bad Numbers", "Bad Numbers", "0", "abcd", "\\N", "-5", "Comedy"],
]

RATINGS_HEADER = ["tconst", "averageRating", "numVotes"]

# 8 行：2 正常、2 非保留电影、2 非法评分、1 重复、1 非法票数
RATINGS_ROWS = [
    ["tt0000001", "8.7", "1000"],
    ["tt0000002", "7.0", "500"],
    ["tt0000004", "7.5", "100"],
    ["tt0000005", "\\N", "50"],
    ["tt0000006", "11.0", "100"],
    ["tt0000001", "8.8", "2000"],
    ["tt0000008", "8.0", "0"],
    ["tt0000008", "7.2", "50"],
]

RETAINED_TCONSTS = {"tt0000001", "tt0000005", "tt0000006", "tt0000008"}
RETAINED_RATING_TCONSTS = {"tt0000001", "tt0000008"}


def write_gzip_tsv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    """按 IMDb 原始格式写 Tab 分隔文件：不做引号转义，字段内不含 Tab。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        handle.write("\t".join(header) + "\n")
        for row in rows:
            handle.write("\t".join(row) + "\n")


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class IngestImdbTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.basics_path = self.root / "fixtures" / "title.basics.tsv.gz"
        self.ratings_path = self.root / "fixtures" / "title.ratings.tsv.gz"
        self.output_dir = self.root / "out" / "large"
        self.manifest_dir = self.root / "out" / "manifests"
        write_gzip_tsv(self.basics_path, BASICS_HEADER, BASICS_ROWS)
        write_gzip_tsv(self.ratings_path, RATINGS_HEADER, RATINGS_ROWS)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, **overrides) -> dict:
        params = {
            "basics_path": self.basics_path,
            "ratings_path": self.ratings_path,
            "output_dir": self.output_dir,
            "manifest_dir": self.manifest_dir,
            "ingest_date": "2026-01-01",
            "downloaded_at": None,
            "dry_run": False,
            "git_commit": "testcommit",
        }
        params.update(overrides)
        return ingest_imdb(**params)

    def _titles(self) -> list[dict[str, str]]:
        return read_csv_rows(self.output_dir / BASICS_OUTPUT_NAME)

    def _ratings(self) -> list[dict[str, str]]:
        return read_csv_rows(self.output_dir / RATINGS_OUTPUT_NAME)

    def _output_paths(self) -> dict[str, Path]:
        return {
            BASICS_OUTPUT_NAME: self.output_dir / BASICS_OUTPUT_NAME,
            RATINGS_OUTPUT_NAME: self.output_dir / RATINGS_OUTPUT_NAME,
            BASICS_MANIFEST_NAME: self.manifest_dir / BASICS_MANIFEST_NAME,
            RATINGS_MANIFEST_NAME: self.manifest_dir / RATINGS_MANIFEST_NAME,
        }

    def _snapshot_hashes(self) -> dict[str, str]:
        return {name: file_sha256(path) for name, path in self._output_paths().items()}

    def _snapshot_bytes(self) -> dict[str, bytes]:
        return {name: path.read_bytes() for name, path in self._output_paths().items()}

    def _assert_no_transaction_files(self) -> None:
        for directory in (self.output_dir, self.manifest_dir):
            if not directory.exists():
                continue
            leftovers = sorted(
                entry.name
                for entry in directory.iterdir()
                if entry.name.endswith(".tmp") or ".bak-" in entry.name
            )
            self.assertEqual(leftovers, [], f"目录残留事务文件：{directory}")

    def _failing_replace(self, fail_name: str):
        def fake_replace(staged: Path, target: Path) -> None:
            if Path(target).name == fail_name:
                raise OSError(f"injected replace failure: {fail_name}")
            os.replace(staged, target)

        return fake_replace

    def _run_with_replace_failure(self, fail_name: str) -> None:
        with mock.patch.object(
            ingest_module, "_replace", side_effect=self._failing_replace(fail_name)
        ):
            with self.assertRaises(IngestError):
                self._run()

    # 1. 正常电影记录
    def test_keeps_only_movie_records(self) -> None:
        report = self._run()
        titles = self._titles()
        self.assertEqual({row["tconst"] for row in titles}, RETAINED_TCONSTS)
        self.assertEqual(report["basics"]["retained_rows"], 4)
        self.assertEqual(report["basics"]["raw_rows"], 8)

    # 2. 非 movie 类型过滤
    def test_excludes_tv_series_and_short(self) -> None:
        report = self._run()
        tconsts = {row["tconst"] for row in self._titles()}
        self.assertNotIn("tt0000002", tconsts)
        self.assertNotIn("tt0000003", tconsts)
        self.assertEqual(report["basics"]["excluded_title_type"], 2)
        self.assertEqual(report["basics"]["title_type_counts"]["tvSeries"], 1)
        self.assertEqual(report["basics"]["title_type_counts"]["short"], 1)

    # 3. 成人内容过滤
    def test_excludes_adult_titles(self) -> None:
        report = self._run()
        self.assertNotIn("tt0000004", {row["tconst"] for row in self._titles()})
        self.assertEqual(report["basics"]["excluded_adult"], 1)

    # 4. 缺失年份和片长
    def test_missing_year_and_runtime_become_empty(self) -> None:
        report = self._run()
        rows = {row["tconst"]: row for row in self._titles()}
        self.assertEqual(rows["tt0000005"]["start_year"], "")
        self.assertEqual(rows["tt0000005"]["runtime_minutes"], "")
        self.assertEqual(rows["tt0000008"]["start_year"], "")
        self.assertEqual(rows["tt0000008"]["runtime_minutes"], "")
        self.assertEqual(report["basics"]["missing_start_year"], 1)
        self.assertEqual(report["basics"]["invalid_start_year"], 1)
        self.assertEqual(report["basics"]["missing_runtime"], 1)
        self.assertEqual(report["basics"]["invalid_runtime"], 1)

    # 5. 引号、逗号、非英文片名
    def test_preserves_quotes_commas_and_non_english_titles(self) -> None:
        self._run()
        rows = {row["tconst"]: row for row in self._titles()}
        self.assertEqual(rows["tt0000006"]["primary_title"], 'The "Quote", Film')
        self.assertEqual(rows["tt0000006"]["original_title"], "千与千寻")
        self.assertEqual(rows["tt0000006"]["genres"], "Animation|Fantasy")

    # 6. 重复 IMDb ID
    def test_duplicate_tconst_kept_once(self) -> None:
        report = self._run()
        titles = self._titles()
        duplicates = [row for row in titles if row["tconst"] == "tt0000001"]
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0]["primary_title"], "The Normal Film")
        self.assertEqual(report["basics"]["duplicate_tconst"], 1)

    # 7. 无效评分与投票数
    def test_excludes_invalid_ratings_and_votes(self) -> None:
        report = self._run()
        ratings = self._ratings()
        self.assertEqual({row["tconst"] for row in ratings}, RETAINED_RATING_TCONSTS)
        self.assertEqual(report["ratings"]["excluded_invalid_rating"], 2)
        self.assertEqual(report["ratings"]["excluded_invalid_votes"], 1)
        self.assertEqual(report["ratings"]["duplicate_tconst"], 1)
        values = {row["tconst"]: row["average_rating"] for row in ratings}
        self.assertEqual(values["tt0000001"], "8.7")
        self.assertEqual(values["tt0000008"], "7.2")

    # 8. 评分表存在非电影 ID
    def test_ratings_are_filtered_by_retained_movies(self) -> None:
        report = self._run()
        tconsts = {row["tconst"] for row in self._ratings()}
        self.assertNotIn("tt0000002", tconsts)
        self.assertNotIn("tt0000004", tconsts)
        self.assertEqual(report["ratings"]["excluded_orphan"], 2)
        self.assertEqual(
            report["ratings"]["excluded_rows"],
            report["ratings"]["raw_rows"] - report["ratings"]["retained_rows"],
        )

    # 9. 电影没有评分
    def test_movie_without_rating_is_allowed(self) -> None:
        report = self._run()
        titles = {row["tconst"] for row in self._titles()}
        ratings = {row["tconst"] for row in self._ratings()}
        self.assertIn("tt0000005", titles)
        self.assertNotIn("tt0000005", ratings)
        self.assertEqual(report["ratings"]["retained_rows"], 2)

    # 10. dry-run 不产生输出
    def test_dry_run_writes_nothing(self) -> None:
        report = self._run(dry_run=True)
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["basics"]["retained_rows"], 4)
        self.assertEqual(report["ratings"]["retained_rows"], 2)
        self.assertFalse(self.output_dir.exists())
        self.assertFalse(self.manifest_dir.exists())

    # 11. 输入损坏
    def test_corrupted_input_raises_without_outputs(self) -> None:
        self.basics_path.write_bytes(b"this is not gzip")
        with self.assertRaises(IngestError):
            self._run()
        self.assertFalse((self.output_dir / BASICS_OUTPUT_NAME).exists())
        self.assertFalse((self.output_dir / RATINGS_OUTPUT_NAME).exists())
        self.assertFalse((self.manifest_dir / BASICS_MANIFEST_NAME).exists())
        self.assertFalse((self.manifest_dir / RATINGS_MANIFEST_NAME).exists())

    # 11b. 缺少必需列
    def test_missing_required_column_raises(self) -> None:
        write_gzip_tsv(
            self.basics_path,
            [column for column in BASICS_HEADER if column != "genres"],
            [row[:-1] for row in BASICS_ROWS],
        )
        with self.assertRaises(IngestError):
            self._run()

    # 12. 重复运行结果一致
    def test_repeated_runs_are_byte_identical(self) -> None:
        self._run()
        first_titles = (self.output_dir / BASICS_OUTPUT_NAME).read_bytes()
        first_ratings = (self.output_dir / RATINGS_OUTPUT_NAME).read_bytes()
        first_basics_manifest = (self.manifest_dir / BASICS_MANIFEST_NAME).read_bytes()

        self._run()

        self.assertEqual((self.output_dir / BASICS_OUTPUT_NAME).read_bytes(), first_titles)
        self.assertEqual((self.output_dir / RATINGS_OUTPUT_NAME).read_bytes(), first_ratings)
        self.assertEqual(
            (self.manifest_dir / BASICS_MANIFEST_NAME).read_bytes(),
            first_basics_manifest,
        )

    # 13. 自定义输入输出路径
    def test_custom_paths(self) -> None:
        custom_basics = self.root / "custom" / "basics.tsv.gz"
        custom_ratings = self.root / "custom" / "ratings.tsv.gz"
        custom_output = self.root / "custom-out" / "nested"
        custom_manifest = self.root / "custom-manifest"
        write_gzip_tsv(custom_basics, BASICS_HEADER, BASICS_ROWS)
        write_gzip_tsv(custom_ratings, RATINGS_HEADER, RATINGS_ROWS)

        report = self._run(
            basics_path=custom_basics,
            ratings_path=custom_ratings,
            output_dir=custom_output,
            manifest_dir=custom_manifest,
        )

        self.assertTrue((custom_output / BASICS_OUTPUT_NAME).exists())
        self.assertTrue((custom_output / RATINGS_OUTPUT_NAME).exists())
        self.assertTrue((custom_manifest / BASICS_MANIFEST_NAME).exists())
        self.assertTrue((custom_manifest / RATINGS_MANIFEST_NAME).exists())
        self.assertEqual(report["basics"]["retained_rows"], 4)

    # 14. 禁止写入受保护目录
    def test_refuses_protected_output_directories(self) -> None:
        for protected in ("knowledge", "candidates"):
            with self.subTest(protected=protected):
                with self.assertRaises(IngestError):
                    self._run(output_dir=BACKEND_DIR / "data" / protected)
        with self.assertRaises(IngestError):
            self._run(manifest_dir=BACKEND_DIR / "data" / "knowledge")

    # 15. 输出表头与规划一致
    def test_output_headers_match_plan(self) -> None:
        self._run()
        with (self.output_dir / BASICS_OUTPUT_NAME).open(
            "r", encoding="utf-8", newline=""
        ) as handle:
            self.assertEqual(next(csv.reader(handle)), BASICS_OUTPUT_COLUMNS)
        with (self.output_dir / RATINGS_OUTPUT_NAME).open(
            "r", encoding="utf-8", newline=""
        ) as handle:
            self.assertEqual(next(csv.reader(handle)), RATINGS_OUTPUT_COLUMNS)

    # 16. manifest 字段与真实哈希
    def test_manifest_fields_and_hashes(self) -> None:
        self._run()
        basics_manifest = json.loads(
            (self.manifest_dir / BASICS_MANIFEST_NAME).read_text(encoding="utf-8")
        )
        ratings_manifest = json.loads(
            (self.manifest_dir / RATINGS_MANIFEST_NAME).read_text(encoding="utf-8")
        )

        required = {
            "source",
            "dataset",
            "official_url",
            "downloaded_at",
            "sha256",
            "file_bytes",
            "raw_rows",
            "retained_rows",
            "excluded_rows",
            "filter_rules",
            "script_version",
            "git_commit",
        }
        self.assertTrue(required.issubset(basics_manifest))
        self.assertTrue(required.issubset(ratings_manifest))

        self.assertEqual(basics_manifest["sha256"], file_sha256(self.basics_path))
        self.assertEqual(basics_manifest["file_bytes"], self.basics_path.stat().st_size)
        self.assertEqual(basics_manifest["raw_rows"], 8)
        self.assertEqual(basics_manifest["retained_rows"], 4)
        self.assertEqual(basics_manifest["excluded_rows"], 4)
        self.assertEqual(ratings_manifest["raw_rows"], 8)
        self.assertEqual(ratings_manifest["retained_rows"], 2)
        self.assertEqual(ratings_manifest["excluded_rows"], 6)
        self.assertIsNone(basics_manifest["downloaded_at"])
        self.assertEqual(basics_manifest["git_commit"], "testcommit")
        self.assertEqual(basics_manifest["script_version"], "0.1.0")
        self.assertEqual(
            basics_manifest["output_sha256"],
            file_sha256(self.output_dir / BASICS_OUTPUT_NAME),
        )

    # 17. 命令行 --help
    def test_cli_help_exits_zero(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            with self.assertRaises(SystemExit) as raised:
                main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--dry-run", buffer.getvalue())

    # 18. 命令行参数校验：非法日期
    def test_invalid_ingest_date_raises(self) -> None:
        with self.assertRaises(IngestError):
            self._run(ingest_date="2026-13-40")

    # 19. 第二个 CSV 替换失败且无旧输出
    def test_failure_on_second_csv_leaves_no_outputs(self) -> None:
        self._run_with_replace_failure(RATINGS_OUTPUT_NAME)
        for name, path in self._output_paths().items():
            self.assertFalse(path.exists(), name)
        self._assert_no_transaction_files()

    # 20. 第一份 manifest 替换失败且无旧输出
    def test_failure_on_first_manifest_leaves_no_outputs(self) -> None:
        self._run_with_replace_failure(BASICS_MANIFEST_NAME)
        for name, path in self._output_paths().items():
            self.assertFalse(path.exists(), name)
        self._assert_no_transaction_files()

    # 21. 第二份 manifest 替换失败且无旧输出
    def test_failure_on_second_manifest_leaves_no_outputs(self) -> None:
        self._run_with_replace_failure(RATINGS_MANIFEST_NAME)
        for name, path in self._output_paths().items():
            self.assertFalse(path.exists(), name)
        self._assert_no_transaction_files()

    # 22. 四个旧输出存在时，任一提交失败都恢复原内容与 SHA-256
    def test_failure_restores_existing_outputs(self) -> None:
        self._run()
        before_bytes = self._snapshot_bytes()
        before_hashes = self._snapshot_hashes()

        changed_rows = [list(row) for row in BASICS_ROWS]
        changed_rows[0][2] = "Changed Title"
        write_gzip_tsv(self.basics_path, BASICS_HEADER, changed_rows)

        for fail_name in (
            RATINGS_OUTPUT_NAME,
            BASICS_MANIFEST_NAME,
            RATINGS_MANIFEST_NAME,
        ):
            with self.subTest(fail_name=fail_name):
                self._run_with_replace_failure(fail_name)
                self.assertEqual(self._snapshot_bytes(), before_bytes)
                self.assertEqual(self._snapshot_hashes(), before_hashes)
                self._assert_no_transaction_files()

    # 23. manifest 写入（暂存）失败时不覆盖旧输出
    def test_manifest_staging_failure_keeps_existing_outputs(self) -> None:
        self._run()
        before_bytes = self._snapshot_bytes()
        with mock.patch.object(
            ingest_module, "_stage_json", side_effect=OSError("injected disk failure")
        ):
            with self.assertRaises(OSError):
                self._run()
        self.assertEqual(self._snapshot_bytes(), before_bytes)
        self._assert_no_transaction_files()

    # 24. 输入损坏时旧输出保持不变
    def test_corrupted_input_keeps_existing_outputs(self) -> None:
        self._run()
        before_bytes = self._snapshot_bytes()
        self.basics_path.write_bytes(b"broken gzip payload")
        with self.assertRaises(IngestError):
            self._run()
        self.assertEqual(self._snapshot_bytes(), before_bytes)
        self._assert_no_transaction_files()

    # 25. 仓库内非本脚本管理的路径一律拒绝
    def test_rejects_repo_paths_outside_managed_dirs(self) -> None:
        cases = [
            {"output_dir": BACKEND_DIR.parent},
            {"output_dir": BACKEND_DIR / "frontend"},
            {"output_dir": BACKEND_DIR / "data" / "processed"},
            {"manifest_dir": BACKEND_DIR / "data" / "raw" / "tmdb"},
            {"manifest_dir": BACKEND_DIR / "data" / "candidates" / "nested"},
        ]
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(IngestError):
                    self._run(**case)

    # 26. 成功运行不残留临时文件或备份
    def test_successful_run_leaves_no_transaction_files(self) -> None:
        self._run()
        self._assert_no_transaction_files()

    # 27. 提交失败且回滚恢复失败时，保留最后一份备份，不自动删除
    def test_restore_failure_keeps_backup(self) -> None:
        self._run()
        before_bytes = self._snapshot_bytes()
        before_hashes = self._snapshot_hashes()
        real_replace = os.replace

        def fake_replace(src, dst) -> None:
            src_path = Path(src)
            dst_path = Path(dst)
            if ".bak-" in src_path.name and dst_path.name == RATINGS_OUTPUT_NAME:
                raise OSError("injected restore failure")
            if dst_path.name == RATINGS_OUTPUT_NAME and src_path.name.endswith(".tmp"):
                raise OSError("injected commit failure")
            real_replace(src, dst)

        with mock.patch.object(ingest_module.os, "replace", side_effect=fake_replace):
            with self.assertRaises(IngestError) as caught:
                self._run()

        message = str(caught.exception)

        # 恢复成功的主表与两份清单保持原内容、原 SHA-256
        for name in (
            BASICS_OUTPUT_NAME,
            BASICS_MANIFEST_NAME,
            RATINGS_MANIFEST_NAME,
        ):
            path = self._output_paths()[name]
            self.assertEqual(path.read_bytes(), before_bytes[name], name)
            self.assertEqual(file_sha256(path), before_hashes[name], name)

        # 恢复失败的目标没有正式输出，但备份必须保留且内容不变
        self.assertFalse((self.output_dir / RATINGS_OUTPUT_NAME).exists())
        backups = sorted(
            entry
            for entry in self.output_dir.iterdir()
            if ".bak-" in entry.name and RATINGS_OUTPUT_NAME in entry.name
        )
        self.assertEqual(len(backups), 1, "恢复失败的备份必须保留")
        backup = backups[0]
        self.assertEqual(backup.read_bytes(), before_bytes[RATINGS_OUTPUT_NAME])
        self.assertEqual(file_sha256(backup), before_hashes[RATINGS_OUTPUT_NAME])

        # 错误信息列出未恢复目标与保留的备份路径，并提示人工恢复
        self.assertIn(str(self.output_dir / RATINGS_OUTPUT_NAME), message)
        self.assertIn(str(backup), message)
        self.assertIn("人工", message)


if __name__ == "__main__":
    unittest.main()
