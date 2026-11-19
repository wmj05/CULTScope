"""IMDb 离线聚合脚本的小样本测试。

所有夹具均在临时目录生成，不读取真实 IMDb 数据，也不修改任何正式数据。
覆盖：正常数据、多类型、缺失/异常年份、0.5 分桶边界、10.0 上界、
投票桶边界、缺失评分、无效票数、重复 ID、孤儿评分、空数据、max_rows、
危险输出路径、原子替换失败、年份分母（评分有效但票数无效、反之、都无效）。
"""

from __future__ import annotations

import csv
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

import scripts.aggregate_imdb as agg  # noqa: E402
from scripts.aggregate_imdb import (  # noqa: E402
    AggregateError,
    BASICS_COLUMNS,
    RATINGS_COLUMNS,
    EARLIEST_MOVIE_YEAR,
    aggregate,
    _rating_bucket,
    _votes_bucket,
    _assert_safe_output,
    _check_integrity,
)


BASICS_HEADER = list(BASICS_COLUMNS)
RATINGS_HEADER = list(RATINGS_COLUMNS)


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


class AggregateImdbTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.basics = self.root / "basics.csv"
        self.ratings = self.root / "ratings.csv"
        self.report = self.root / "aggregate.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, basics_rows, ratings_rows, **overrides):
        _write_csv(self.basics, BASICS_HEADER, basics_rows)
        _write_csv(self.ratings, RATINGS_HEADER, ratings_rows)
        params = {"dry_run": True}
        params.update(overrides)
        return aggregate(self.basics, self.ratings, self.report, **params)

    # ---------- 正常数据 ----------

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
        report = self._run(basics, ratings)
        cov = report["coverage"]
        self.assertEqual(cov["total_movies"], 3)
        self.assertEqual(cov["rated_movies"], 3)
        self.assertEqual(cov["unrated_movies"], 0)
        self.assertEqual(cov["coverage_ratio"], 1.0)
        self.assertEqual(report["genre_distribution"]["Drama"], 1)
        self.assertEqual(report["genre_distribution"]["Animation"], 1)
        self.assertEqual(report["genre_distribution"]["Comedy"], 1)
        # 年份 1994 趋势
        trend_94 = report["year_rating_trend"][1994]
        self.assertEqual(trend_94["rated_count"], 1)
        self.assertEqual(trend_94["valid_rating_count"], 1)
        self.assertEqual(trend_94["valid_votes_count"], 1)
        self.assertAlmostEqual(trend_94["rating_mean"], 8.7, places=4)
        self.assertAlmostEqual(trend_94["votes_mean"], 1000.0, places=2)

    # ---------- 多类型拆分 ----------

    def test_multi_genre_split(self) -> None:
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "2000", "", "100", "Drama,Comedy,Romance", "2026-11-18"],
            ["tt0000002", "movie", "B", "B", "0", "2000", "", "80", "Drama", "2026-11-18"],
        ]
        ratings = [
            ["tt0000001", "7.0", "100", "2026-11-18"],
            ["tt0000002", "6.5", "50", "2026-11-18"],
        ]
        report = self._run(basics, ratings)
        gd = report["genre_distribution"]
        self.assertEqual(gd["Drama"], 2)
        self.assertEqual(gd["Comedy"], 1)
        self.assertEqual(gd["Romance"], 1)

    # ---------- 缺失与异常年份 ----------

    def test_missing_and_abnormal_years(self) -> None:
        this_year_future = str(2026 + 2)  # 2028
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "1990", "", "100", "Drama", "2026-11-18"],
            ["tt0000002", "movie", "B", "B", "0", "", "", "80", "Comedy", "2026-11-18"],  # 缺失
            ["tt0000003", "movie", "C", "C", "0", this_year_future, "", "80", "Horror", "2026-11-18"],  # 未来
            ["tt0000004", "movie", "D", "D", "0", "1800", "", "80", "Sci-Fi", "2026-11-18"],  # 非法
        ]
        ratings = [
            ["tt0000001", "8.0", "200", "2026-11-18"],
            ["tt0000002", "7.0", "100", "2026-11-18"],  # 缺失年份但有评分
            ["tt0000003", "6.0", "50", "2026-11-18"],
            ["tt0000004", "5.5", "30", "2026-11-18"],
        ]
        report = self._run(basics, ratings)
        yd = report["year_distribution"]
        self.assertEqual(yd["missing_year"], 1)
        self.assertEqual(yd["future_year"], 1)
        self.assertEqual(yd["invalid_year"], 1)
        self.assertIn(1990, yd["per_year"])
        # 覆盖率总计仍为 4
        self.assertEqual(report["coverage"]["total_movies"], 4)
        # 缺失年份电影有评分，但不进入 year_rating_trend 的 1990/未来/非法 桶
        # 它的评分仍进入 rating_distribution
        self.assertIn("8.0-8.5", report["rating_distribution"])  # 8.0
        # 未来年份的电影不算有效年份，但它在 year_distribution.per_year 里？
        # 不，future_year 单独计数，不在 per_year
        self.assertNotIn(this_year_future, yd["per_year"])
        self.assertNotIn(1800, yd["per_year"])

    # ---------- 评分 0.5 分桶边界 ----------

    def test_rating_bucket_boundaries(self) -> None:
        # 所有关键边界：1.0 (1.0-1.5), 1.5 (1.5-2.0), ..., 9.5 (9.5-10.0), 10.0 (9.5-10.0)
        self.assertEqual(_rating_bucket(1.0), "1.0-1.5")
        self.assertEqual(_rating_bucket(1.49), "1.0-1.5")
        self.assertEqual(_rating_bucket(1.5), "1.5-2.0")
        self.assertEqual(_rating_bucket(9.5), "9.5-10.0")
        self.assertEqual(_rating_bucket(9.99), "9.5-10.0")
        self.assertEqual(_rating_bucket(10.0), "9.5-10.0")
        self.assertEqual(_rating_bucket(5.0), "5.0-5.5")

    # ---------- 10.0 上界 ----------

    def test_rating_10point_0_upper_bound(self) -> None:
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "2000", "", "100", "Drama", "2026-11-18"],
            ["tt0000002", "movie", "B", "B", "0", "2000", "", "80", "Drama", "2026-11-18"],
        ]
        ratings = [
            ["tt0000001", "10.0", "1000", "2026-11-18"],
            ["tt0000002", "0.5", "10", "2026-11-18"],  # 无效：<1.0
        ]
        report = self._run(basics, ratings)
        rd = report["rating_distribution"]
        self.assertEqual(rd.get("9.5-10.0"), 1)  # 10.0 归入此处
        self.assertEqual(report["quality_flags"]["invalid_ratings_skipped"], 1)

    # ---------- 投票桶边界 ----------

    def test_votes_bucket_boundaries(self) -> None:
        self.assertEqual(_votes_bucket(1), "1-10")
        self.assertEqual(_votes_bucket(10), "1-10")
        self.assertEqual(_votes_bucket(11), "11-100")
        self.assertEqual(_votes_bucket(100), "11-100")
        self.assertEqual(_votes_bucket(101), "101-1k")
        self.assertEqual(_votes_bucket(1000), "101-1k")
        self.assertEqual(_votes_bucket(1001), "1k-10k")
        self.assertEqual(_votes_bucket(10000), "1k-10k")
        self.assertEqual(_votes_bucket(10001), "10k-100k")
        self.assertEqual(_votes_bucket(100000), "10k-100k")
        self.assertEqual(_votes_bucket(100001), "100k-1M")
        self.assertEqual(_votes_bucket(1000000), "100k-1M")
        self.assertEqual(_votes_bucket(1000001), ">1M")
        self.assertEqual(_votes_bucket(0), "invalid")
        self.assertEqual(_votes_bucket(-5), "invalid")

    # ---------- 缺失评分 ----------

    def test_missing_rating_field(self) -> None:
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "2000", "", "100", "Drama", "2026-11-18"],
        ]
        # 评分缺失 + 票数有效
        ratings = [["tt0000001", "", "100", "2026-11-18"]]
        report = self._run(basics, ratings)
        trend = report["year_rating_trend"][2000]
        self.assertEqual(trend["rated_count"], 1)
        self.assertEqual(trend["valid_rating_count"], 0)
        self.assertEqual(trend["valid_votes_count"], 1)
        self.assertIsNone(trend["rating_mean"])  # 分母为 0
        self.assertAlmostEqual(trend["votes_mean"], 100.0, places=2)
        self.assertEqual(report["quality_flags"]["invalid_ratings_skipped"], 1)

    # ---------- 无效票数 ----------

    def test_invalid_votes_only(self) -> None:
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "2000", "", "100", "Drama", "2026-11-18"],
        ]
        ratings = [["tt0000001", "7.5", "0", "2026-11-18"]]  # votes=0 无效
        report = self._run(basics, ratings)
        trend = report["year_rating_trend"][2000]
        self.assertEqual(trend["rated_count"], 1)
        self.assertEqual(trend["valid_rating_count"], 1)
        self.assertEqual(trend["valid_votes_count"], 0)
        self.assertAlmostEqual(trend["rating_mean"], 7.5, places=4)
        self.assertIsNone(trend["votes_mean"])  # 分母为 0
        self.assertEqual(report["quality_flags"]["invalid_votes_skipped"], 1)

    # ---------- 两者都无效 ----------

    def test_both_rating_and_votes_invalid(self) -> None:
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "2000", "", "100", "Drama", "2026-11-18"],
        ]
        ratings = [["tt0000001", "99.9", "-1", "2026-11-18"]]  # 评分超界 + 负数票
        report = self._run(basics, ratings)
        trend = report["year_rating_trend"][2000]
        self.assertEqual(trend["rated_count"], 1)
        self.assertEqual(trend["valid_rating_count"], 0)
        self.assertEqual(trend["valid_votes_count"], 0)
        self.assertIsNone(trend["rating_mean"])
        self.assertIsNone(trend["votes_mean"])
        self.assertEqual(report["quality_flags"]["invalid_ratings_skipped"], 1)
        self.assertEqual(report["quality_flags"]["invalid_votes_skipped"], 1)

    # ---------- 重复 tconst（主表） ----------

    def test_duplicate_basics_tconst_first_wins(self) -> None:
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "1994", "", "142", "Drama", "2026-11-18"],
            ["tt0000001", "movie", "A2", "A2", "0", "2001", "", "100", "Animation", "2026-11-18"],  # 重复
        ]
        ratings = [["tt0000001", "8.0", "100", "2026-11-18"]]
        report = self._run(basics, ratings)
        self.assertEqual(report["coverage"]["total_movies"], 1)  # unique_tconst
        self.assertEqual(report["duplicate_counts"]["basics_duplicate_tconst"], 1)
        # first-wins：年份应是 1994（第一条），不是 2001
        self.assertIn(1994, report["year_distribution"]["per_year"])
        self.assertNotIn(2001, report["year_distribution"]["per_year"])
        self.assertIn("Drama", report["genre_distribution"])

    # ---------- 重复 tconst（评分表） ----------

    def test_duplicate_ratings_tconst_first_wins(self) -> None:
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "2000", "", "100", "Drama", "2026-11-18"],
        ]
        ratings = [
            ["tt0000001", "8.0", "100", "2026-11-18"],
            ["tt0000001", "2.0", "9999", "2026-11-18"],  # 重复：应被忽略
        ]
        report = self._run(basics, ratings)
        self.assertEqual(report["coverage"]["rated_movies"], 1)
        self.assertEqual(report["duplicate_counts"]["ratings_duplicate_tconst"], 1)
        # rating_distribution 应只有 8.0 的桶，不应有 2.0
        rd = report["rating_distribution"]
        self.assertEqual(sum(rd.values()), 1)

    # ---------- 孤儿评分 ----------

    def test_orphan_rating_counted(self) -> None:
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "2000", "", "100", "Drama", "2026-11-18"],
        ]
        ratings = [
            ["tt0000001", "8.0", "100", "2026-11-18"],
            ["tt9999999", "7.0", "50", "2026-11-18"],  # 孤儿
        ]
        report = self._run(basics, ratings)
        self.assertEqual(report["coverage"]["orphan_ratings"], 1)
        self.assertEqual(report["coverage"]["rated_movies"], 1)

    # ---------- 空数据 ----------

    def test_empty_datasets(self) -> None:
        report = self._run([], [])
        cov = report["coverage"]
        self.assertEqual(cov["total_movies"], 0)
        self.assertEqual(cov["rated_movies"], 0)
        self.assertEqual(cov["unrated_movies"], 0)
        self.assertEqual(cov["coverage_ratio"], 0.0)
        self.assertEqual(cov["orphan_ratings"], 0)

    def test_empty_ratings(self) -> None:
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "2000", "", "100", "Drama", "2026-11-18"],
        ]
        report = self._run(basics, [])
        self.assertEqual(report["coverage"]["total_movies"], 1)
        self.assertEqual(report["coverage"]["rated_movies"], 0)
        self.assertEqual(report["coverage"]["unrated_movies"], 1)

    # ---------- max_rows ----------

    def test_max_rows_limits_both_tables(self) -> None:
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "2000", "", "100", "Drama", "2026-11-18"],
            ["tt0000002", "movie", "B", "B", "0", "2000", "", "80", "Comedy", "2026-11-18"],
            ["tt0000003", "movie", "C", "C", "0", "2000", "", "90", "Horror", "2026-11-18"],
        ]
        ratings = [
            ["tt0000001", "8.0", "100", "2026-11-18"],
            ["tt0000002", "7.0", "50", "2026-11-18"],
            ["tt0000003", "6.0", "30", "2026-11-18"],
        ]
        report = self._run(basics, ratings, max_rows=2)
        # 只扫前 2 行
        self.assertEqual(report["coverage"]["total_movies"], 2)
        self.assertEqual(report["coverage"]["rated_movies"], 2)

    def test_max_rows_must_be_positive(self) -> None:
        with self.assertRaises(AggregateError):
            self._run([], [], max_rows=0)
        with self.assertRaises(AggregateError):
            self._run([], [], max_rows=-1)

    # ---------- 危险输出路径 ----------

    def test_dangerous_output_path_blocked(self) -> None:
        # 仓库内只允许 DEFAULT_OUTPUT
        fake_repo = tempfile.mkdtemp(prefix="fake-repo-")
        try:
            allowed = agg.DEFAULT_OUTPUT
            _assert_safe_output(allowed, allowed=allowed)  # 不应抛
            blocked = Path(fake_repo) / "backend" / "data" / "processed" / "large" / "other.json"
            # 用 mock patch REPO_ROOT 使 fake_repo 看起来像仓库
            with mock.patch.object(agg, "REPO_ROOT", Path(fake_repo)):
                with self.assertRaises(AggregateError):
                    _assert_safe_output(blocked, allowed=agg.DEFAULT_OUTPUT)
        finally:
            import shutil
            shutil.rmtree(fake_repo, ignore_errors=True)

    # ---------- 原子替换失败 ----------

    def test_atomic_write_preserves_old_on_failure(self) -> None:
        # 先写一个已有报告
        existing = {"generated_at": "old"}
        self.report.write_text(json.dumps(existing), encoding="utf-8")

        basics = [
            ["tt0000001", "movie", "A", "A", "0", "2000", "", "100", "Drama", "2026-11-18"],
        ]
        ratings = [["tt0000001", "8.0", "100", "2026-11-18"]]
        _write_csv(self.basics, BASICS_HEADER, basics)
        _write_csv(self.ratings, RATINGS_HEADER, ratings)

        # 模拟 os.replace 失败（例如权限问题）
        original_replace = os.replace

        def faily_replace(src, dst):
            # 仅在临时文件替换目标时报错
            if Path(dst) == self.report:
                raise OSError("模拟权限拒绝")
            return original_replace(src, dst)

        with mock.patch("os.replace", side_effect=faily_replace):
            with self.assertRaises(OSError):
                aggregate(self.basics, self.ratings, self.report, dry_run=False)

        # 旧文件应保留且内容不变
        self.assertTrue(self.report.exists())
        content = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertEqual(content["generated_at"], "old")

    # ---------- 完整性校验：年份合计 ----------

    def test_integrity_year_sum_fails(self) -> None:
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "2000", "", "100", "Drama", "2026-11-18"],
        ]
        ratings = [["tt0000001", "8.0", "100", "2026-11-18"]]
        report = self._run(basics, ratings)

        # 破坏 year_distribution：多算一条
        report["year_distribution"]["per_year"][2000]["total_movies"] = 5

        with self.assertRaises(AggregateError) as ctx:
            _check_integrity(
                {"year_counts": {2000: 1}, "missing_year": 0, "invalid_year": 0, "future_year": 0},
                {"valid_rating_total": 1, "valid_votes_total": 1, "year_trend": {}},
                report,
            )
        self.assertIn("年份分布合计", str(ctx.exception))

    # ---------- 完整性校验：分桶合计 ----------

    def test_integrity_rating_bucket_sum_fails(self) -> None:
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "2000", "", "100", "Drama", "2026-11-18"],
        ]
        ratings = [["tt0000001", "8.0", "100", "2026-11-18"]]
        report = self._run(basics, ratings)
        report["rating_distribution"]["7.5-8.0"] = 999  # 破坏

        with self.assertRaises(AggregateError) as ctx:
            _check_integrity(
                {"year_counts": {2000: 1}, "missing_year": 0, "invalid_year": 0, "future_year": 0},
                {"valid_rating_total": 1, "valid_votes_total": 1, "year_trend": report["year_rating_trend"]},
                report,
            )
        self.assertIn("评分分桶合计", str(ctx.exception))

    # ---------- 完整性校验：分母 <= rated_count ----------

    def test_integrity_trend_denominator_exceeds_rated(self) -> None:
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "2000", "", "100", "Drama", "2026-11-18"],
        ]
        ratings = [["tt0000001", "8.0", "100", "2026-11-18"]]
        report = self._run(basics, ratings)
        # 破坏：valid_rating_count > rated_count
        report["year_rating_trend"][2000]["valid_rating_count"] = 999

        with self.assertRaises(AggregateError) as ctx:
            _check_integrity(
                {"year_counts": {2000: 1}, "missing_year": 0, "invalid_year": 0, "future_year": 0},
                {"valid_rating_total": 1, "valid_votes_total": 1, "year_trend": report["year_rating_trend"]},
                report,
            )
        self.assertIn("valid_rating_count", str(ctx.exception))

    # ---------- 未评分电影 ----------

    def test_unrated_movies_counted(self) -> None:
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "2000", "", "100", "Drama", "2026-11-18"],
            ["tt0000002", "movie", "B", "B", "0", "2000", "", "80", "Comedy", "2026-11-18"],
        ]
        ratings = [["tt0000001", "8.0", "100", "2026-11-18"]]
        report = self._run(basics, ratings)
        self.assertEqual(report["coverage"]["total_movies"], 2)
        self.assertEqual(report["coverage"]["rated_movies"], 1)
        self.assertEqual(report["coverage"]["unrated_movies"], 1)

    # ---------- 完整性校验覆盖率合计 ----------

    def test_integrity_coverage_sum_fails(self) -> None:
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "2000", "", "100", "Drama", "2026-11-18"],
        ]
        ratings = [["tt0000001", "8.0", "100", "2026-11-18"]]
        report = self._run(basics, ratings)
        report["coverage"]["unrated_movies"] = 999  # 破坏

        with self.assertRaises(AggregateError) as ctx:
            _check_integrity(
                {"year_counts": {2000: 1}, "missing_year": 0, "invalid_year": 0, "future_year": 0},
                {"valid_rating_total": 1, "valid_votes_total": 1, "year_trend": report["year_rating_trend"]},
                report,
            )
        self.assertIn("覆盖率合计", str(ctx.exception))

    # ---------- future_year_cutoff 反映当前时间 ----------

    def test_constraints_reflect_current_year(self) -> None:
        report = self._run([], [])
        constraints = report["aggregate_constraints"]
        self.assertIsInstance(constraints["future_year_cutoff"], int)
        self.assertGreaterEqual(constraints["future_year_cutoff"], 2026)
        self.assertEqual(constraints["rating_bucket_width"], 0.5)
        self.assertEqual(constraints["duplicate_policy"], "first-wins")

    # ---------- 输出文件 JSON 可被解析 ----------

    def test_output_json_roundtrip(self) -> None:
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "2000", "", "100", "Drama", "2026-11-18"],
        ]
        ratings = [["tt0000001", "8.0", "100", "2026-11-18"]]
        _write_csv(self.basics, BASICS_HEADER, basics)
        _write_csv(self.ratings, RATINGS_HEADER, ratings)
        aggregate(self.basics, self.ratings, self.report, dry_run=False)
        self.assertTrue(self.report.exists())
        content = self.report.read_text(encoding="utf-8")
        parsed = json.loads(content)
        self.assertEqual(parsed["coverage"]["total_movies"], 1)
        self.assertIn("generated_at", parsed)

    # ---------- ratings 缺失有效评分但仍计入 rated_movies ----------

    def test_rated_count_uses_tconst_presence_not_validity(self) -> None:
        # 有 tconst 关联 = 有评分记录（即使评分无效）
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "2000", "", "100", "Drama", "2026-11-18"],
        ]
        ratings = [["tt0000001", "bad", "bad", "2026-11-18"]]  # 都无效
        report = self._run(basics, ratings)
        self.assertEqual(report["coverage"]["rated_movies"], 1)  # 关联到了 tconst
        self.assertEqual(report["coverage"]["unrated_movies"], 0)
        self.assertEqual(report["quality_flags"]["invalid_ratings_skipped"], 1)
        self.assertEqual(report["quality_flags"]["invalid_votes_skipped"], 1)

    # ---------- 覆盖率分母与合计 ----------

    def test_coverage_ratio_matches_denominator(self) -> None:
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "2000", "", "100", "Drama", "2026-11-18"],
            ["tt0000002", "movie", "B", "B", "0", "2001", "", "80", "Comedy", "2026-11-18"],
            ["tt0000003", "movie", "C", "C", "0", "2002", "", "60", "Horror", "2026-11-18"],
        ]
        ratings = [["tt0000001", "8.0", "100", "2026-11-18"]]
        report = self._run(basics, ratings)
        self.assertAlmostEqual(report["coverage"]["coverage_ratio"], round(1 / 3, 6), places=6)
        self.assertEqual(
            report["coverage"]["rated_movies"] + report["coverage"]["unrated_movies"],
            report["coverage"]["total_movies"],
        )

    # ---------- 有评分记录但评分无效：趋势均值为 null，且不进入评分分布 ----------

    def test_year_trend_null_mean_when_rating_invalid(self) -> None:
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "2000", "", "100", "Drama", "2026-11-18"],
        ]
        ratings = [["tt0000001", "bad", "100", "2026-11-18"]]
        report = self._run(basics, ratings)
        entry = report["year_rating_trend"][2000]
        self.assertEqual(entry["rated_count"], 1)
        self.assertEqual(entry["valid_rating_count"], 0)
        self.assertIsNone(entry["rating_mean"])
        self.assertEqual(entry["valid_votes_count"], 1)
        self.assertEqual(entry["votes_mean"], 100.0)
        self.assertEqual(report["rating_distribution"], {})
        self.assertEqual(report["votes_distribution"], {"11-100": 1})
        self.assertEqual(report["quality_flags"]["invalid_ratings_skipped"], 1)

    # ---------- 0 分不作为评分桶统计 ----------

    def test_zero_rating_excluded_from_buckets(self) -> None:
        basics = [
            ["tt0000001", "movie", "A", "A", "0", "2000", "", "100", "Drama", "2026-11-18"],
        ]
        ratings = [["tt0000001", "0.0", "100", "2026-11-18"]]
        report = self._run(basics, ratings)
        self.assertNotIn("0.0-0.5", report["rating_distribution"])
        self.assertEqual(report["rating_distribution"], {})
        self.assertEqual(report["quality_flags"]["invalid_ratings_skipped"], 1)


if __name__ == "__main__":
    unittest.main()
