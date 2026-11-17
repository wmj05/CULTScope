"""第三阶段 3.0 + 3.1 的知识库校验与旧接口回归测试。

运行方式（在 backend 目录下）：
    python -m unittest discover -s tests -p "test_*.py" -v
"""

from __future__ import annotations

import csv
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.schemas.knowledge import compute_review_entry_hash  # noqa: E402
from app.services.review_store import (  # noqa: E402
    ReviewError,
    backfill_draft_to_pending,
    recover_pending_transaction,
    submit_review,
)
from scripts import review_knowledge as review_cli  # noqa: E402
from scripts.validate_knowledge import EXPECTED_HEADERS, validate_knowledge  # noqa: E402

KNOWLEDGE_DIR = BACKEND_DIR / "data" / "knowledge"

EXPECTED_SEEDS = {
    "CS-0001": (985, "tt0074486", "橡皮头"),
    "CS-0002": (692, "tt0069089", "粉红色的火烈鸟"),
    "CS-0003": (36685, "tt0073629", "洛基恐怖秀"),
    "CS-0004": (30497, "tt0072271", "德州电锯杀人狂"),
    "CS-0005": (923, "tt0077402", "活死人黎明"),
    "CS-0006": (837, "tt0086541", "录影带谋杀案"),
    "CS-0007": (1694, "tt0089885", "活跳尸"),
    "CS-0008": (793, "tt0090756", "蓝丝绒"),
    "CS-0009": (765, "tt0092991", "鬼玩人2"),
    "CS-0010": (550, "tt0137523", "搏击俱乐部"),
    "CS-0011": (141, "tt0246578", "死亡幻觉"),
    "CS-0012": (503919, "tt7984734", "灯塔"),
}

EXPECTED_TITLES = {title for _, _, title in EXPECTED_SEEDS.values()}

FIXTURE_TIME = "2026-11-17T00:00:00+08:00"

PILOT_FIXTURE_SEEDS = {
    "CS-0001": ("S-008", "C1|C2"),
    "CS-0002": ("S-009|S-011", "C4|C7"),
    "CS-0003": ("S-005|S-006", "C1|C2|C3|C6"),
}

PILOT_FIXTURE_EVIDENCE = [
    ("CS-0001", "C1", "S-008"),
    ("CS-0001", "C2", "S-008"),
    ("CS-0002", "C4", "S-011"),
    ("CS-0002", "C7", "S-011"),
]


def read_csv_rows(directory: Path, filename: str) -> list[dict[str, str]]:
    with (directory / filename).open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        return list(csv.DictReader(handle))


def reset_pilot_fixture(data_dir: Path) -> None:
    """把临时副本规范化为与生产审核进度无关的固定夹具。

    只改写临时目录；12 部电影中除试点之外的种子还原为 draft，试点电影
    还原为 pending，证据、候选标签、正式标签和日志均由测试自建。
    """

    def write(filename: str, rows: list[dict[str, str]]) -> None:
        with (data_dir / filename).open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=EXPECTED_HEADERS[filename])
            writer.writeheader()
            writer.writerows(rows)

    seeds = read_csv_rows(data_dir, "cult_seed.csv")
    for row in seeds:
        config = PILOT_FIXTURE_SEEDS.get(row["seed_id"])
        if config:
            row.update(
                candidate_source_ids=config[0],
                cult_criteria_codes=config[1],
                review_status="pending",
                confidence="unknown",
                reviewer="",
                reviewed_at="",
            )
        else:
            row.update(
                candidate_source_ids="",
                cult_criteria_codes="",
                review_status="draft",
                confidence="unknown",
                reviewer="",
                reviewed_at="",
            )
    write("cult_seed.csv", seeds)

    write(
        "movie_criterion_evidence.csv",
        [
            {
                "seed_id": seed_id,
                "criterion_code": code,
                "source_id": source_id,
                "evidence_summary": "测试夹具：仅用于验证审核规则，不代表真实研究证据。",
                "locator": "测试定位",
                "verification_status": "verified",
                "human_status": "pending",
                "confirmed_by": "",
                "confirmed_at": "",
                "added_by": "TEST-FIXTURE",
                "added_at": FIXTURE_TIME,
            }
            for seed_id, code, source_id in PILOT_FIXTURE_EVIDENCE
        ],
    )
    write("movie_cult_tags.csv", [])
    write(
        "movie_cult_tag_candidates.csv",
        [
            {
                "seed_id": "CS-0001",
                "tag_id": "aesthetic_surrealism",
                "evidence": "测试夹具：候选标签仅用于验证审核流程。",
                "source_ids": "S-008",
                "proposed_by": "TEST-FIXTURE",
                "proposed_at": FIXTURE_TIME,
                "human_status": "pending",
                "confirmed_by": "",
                "confirmed_at": "",
            }
        ],
    )
    write("review_log.csv", [])



class KnowledgeValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name) / "knowledge"
        shutil.copytree(KNOWLEDGE_DIR, self.data_dir)
        reset_pilot_fixture(self.data_dir)
        backfill_draft_to_pending(
            self.data_dir, now=datetime.fromisoformat(FIXTURE_TIME)
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ---------- CSV 夹具工具 ----------

    def _read(self, filename: str) -> list[dict[str, str]]:
        with (self.data_dir / filename).open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            return list(csv.DictReader(handle))

    def _write(self, filename: str, rows: list[dict[str, str]]) -> None:
        with (self.data_dir / filename).open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=EXPECTED_HEADERS[filename])
            writer.writeheader()
            writer.writerows(rows)

    def _update(
        self, filename: str, key: str, value: str, **changes: str
    ) -> None:
        rows = self._read(filename)
        matched = False
        for row in rows:
            if row[key] == value:
                row.update(changes)
                matched = True
        self.assertTrue(matched, f"{filename} 中未找到 {key}={value}")
        self._write(filename, rows)

    def _append(self, filename: str, values: dict[str, str]) -> None:
        row = {column: "" for column in EXPECTED_HEADERS[filename]}
        row.update(values)
        rows = self._read(filename)
        rows.append(row)
        self._write(filename, rows)

    def _make_approved(self, with_evidence: bool = True) -> None:
        self._update(
            "cult_seed.csv",
            "seed_id",
            "CS-0001",
            candidate_source_ids="S-001",
            cult_criteria_codes="C1|C2",
            review_status="approved",
            confidence="high",
            reviewer="TEST-FIXTURE",
            reviewed_at=FIXTURE_TIME,
        )
        if not with_evidence:
            self._write("movie_criterion_evidence.csv", [])
            return
        # 不依赖生产库中 CS-0001 已有的证据行。
        remaining = [
            row
            for row in self._read("movie_criterion_evidence.csv")
            if row["seed_id"] != "CS-0001"
        ]
        self._write("movie_criterion_evidence.csv", remaining)
        for code in ("C1", "C2"):
            self._append(
                "movie_criterion_evidence.csv",
                {
                    "seed_id": "CS-0001",
                    "criterion_code": code,
                    "source_id": "S-001",
                    "evidence_summary": "测试夹具：仅用于验证审核规则，不代表真实研究证据。",
                    "locator": "测试定位",
                    "verification_status": "verified",
                    "human_status": "confirmed",
                    "confirmed_by": "TEST-FIXTURE",
                    "confirmed_at": FIXTURE_TIME,
                    "added_by": "TEST-FIXTURE",
                    "added_at": FIXTURE_TIME,
                },
            )

    def _log_row(
        self,
        prev_hash: str,
        timestamp: str,
        *,
        seed_id: str = "CS-0001",
        field: str = "review_status",
        old_value: str = "draft",
        new_value: str = "pending",
        actor: str = "TEST-FIXTURE",
        reason: str = "测试日志，仅用于验证哈希链",
    ) -> dict[str, str]:
        entry_hash = compute_review_entry_hash(
            prev_hash=prev_hash,
            timestamp=timestamp,
            seed_id=seed_id,
            field=field,
            old_value=old_value,
            new_value=new_value,
            actor=actor,
            reason=reason,
        )
        return {
            "timestamp": timestamp,
            "seed_id": seed_id,
            "field": field,
            "old_value": old_value,
            "new_value": new_value,
            "actor": actor,
            "reason": reason,
            "prev_hash": prev_hash,
            "entry_hash": entry_hash,
        }

    # ---------- 生产数据基线 ----------

    def test_production_knowledge_base_is_valid_and_honest(self) -> None:
        """只验证生产库的结构与诚实性，不锁定当前审核进度。"""
        report = validate_knowledge(KNOWLEDGE_DIR)
        self.assertTrue(report.ok, [str(issue) for issue in report.errors])

        seeds = {
            row["seed_id"]: row
            for row in read_csv_rows(KNOWLEDGE_DIR, "cult_seed.csv")
        }
        evidence = read_csv_rows(KNOWLEDGE_DIR, "movie_criterion_evidence.csv")
        sources = {
            row["source_id"]: row
            for row in read_csv_rows(KNOWLEDGE_DIR, "cult_sources.csv")
        }
        formal_tags = read_csv_rows(KNOWLEDGE_DIR, "movie_cult_tags.csv")
        candidates = read_csv_rows(KNOWLEDGE_DIR, "movie_cult_tag_candidates.csv")
        log_rows = read_csv_rows(KNOWLEDGE_DIR, "review_log.csv")

        self.assertEqual(report.stats["seeds"], 12)
        self.assertEqual(set(seeds), set(EXPECTED_SEEDS))
        self.assertEqual(
            report.stats["approved"]
            + report.stats["pending"]
            + report.stats["draft"],
            12,
        )
        # 统计值必须与实际行数一致，而不是固定为某个历史数字。
        self.assertEqual(report.stats["evidence"], len(evidence))
        self.assertEqual(report.stats["movie_tags"], len(formal_tags))
        self.assertEqual(report.stats["review_log"], len(log_rows))
        self.assertEqual(report.stats["tag_candidates"], len(candidates))
        self.assertEqual(
            report.stats["evidence_confirmed"]
            + report.stats["evidence_human_pending"]
            + report.stats["evidence_human_rejected"],
            len(evidence),
        )

        forbidden = {"ai", "system", "system-backfill", "ai-draft"}
        for seed_id, row in seeds.items():
            status = row["review_status"]
            reviewer = row["reviewer"].lower()
            self.assertNotIn("ai-draft", reviewer)
            if status == "approved":
                self.assertTrue(reviewer, f"{seed_id} approved 缺少 reviewer")
                self.assertTrue(row["reviewed_at"], f"{seed_id} approved 缺少 reviewed_at")
                self.assertNotIn(reviewer, forbidden)
                self.assertTrue(row["candidate_source_ids"])
                self.assertTrue(row["cult_criteria_codes"])
            else:
                self.assertEqual(row["reviewer"], "")
                self.assertEqual(row["reviewed_at"], "")
                if status == "draft":
                    self.assertEqual(row["candidate_source_ids"], "")
                    self.assertEqual(row["cult_criteria_codes"], "")
                else:
                    self.assertTrue(row["candidate_source_ids"])
                    self.assertTrue(row["cult_criteria_codes"])

        for row in evidence:
            self.assertIn(row["seed_id"], seeds)
            if row["human_status"] == "pending":
                self.assertEqual(row["confirmed_by"], "")
                self.assertEqual(row["confirmed_at"], "")
            else:
                self.assertTrue(row["confirmed_by"])
                self.assertTrue(row["confirmed_at"])
                self.assertNotIn("ai-draft", row["confirmed_by"].lower())

        manual = {
            (row["seed_id"], row["tag_id"])
            for row in formal_tags
            if row["origin"] == "manual"
            and row["reviewed"].strip().lower() in {"true", "1", "yes", "y"}
        }
        for row in candidates:
            if row["human_status"] == "pending":
                self.assertEqual(row["confirmed_by"], "")
                self.assertEqual(row["confirmed_at"], "")
            else:
                self.assertTrue(row["confirmed_by"])
                self.assertTrue(row["confirmed_at"])
            if row["human_status"] == "confirmed":
                self.assertIn((row["seed_id"], row["tag_id"]), manual)

        # CS-0003 的一致性：只检查已记录审核结论是否满足门槛。
        cs3 = seeds["CS-0003"]
        declared = {code for code in cs3["cult_criteria_codes"].split("|") if code}
        supported = {
            row["criterion_code"]
            for row in evidence
            if row["seed_id"] == "CS-0003"
            and row["criterion_code"] in declared
            and row["verification_status"] == "verified"
            and row["human_status"] == "confirmed"
            and sources.get(row["source_id"], {}).get("reliability_tier") in {"T1", "T2"}
        }
        if cs3["review_status"] == "approved":
            self.assertGreaterEqual(len(supported), 2)
            self.assertTrue(cs3["reviewer"])
            self.assertTrue(cs3["reviewed_at"])

    def test_production_external_ids_match_real_tmdb_values(self) -> None:
        rows = {row["seed_id"]: row for row in self._read("cult_seed.csv")}
        self.assertEqual(set(rows), set(EXPECTED_SEEDS))
        for seed_id, (tmdb_id, imdb_id, title) in EXPECTED_SEEDS.items():
            self.assertEqual(int(rows[seed_id]["tmdb_id"]), tmdb_id)
            self.assertEqual(rows[seed_id]["imdb_id"], imdb_id)
            self.assertEqual(rows[seed_id]["title"], title)

    # ---------- 唯一性与外键 ----------

    def test_duplicate_seed_id_is_rejected(self) -> None:
        duplicate = dict(self._read("cult_seed.csv")[0])
        duplicate.update(
            {"seed_id": "CS-0001", "title": "重复种子", "tmdb_id": "999999", "imdb_id": ""}
        )
        self._append("cult_seed.csv", duplicate)

        report = validate_knowledge(self.data_dir)
        errors = [issue for issue in report.errors if issue.field == "seed_id"]
        self.assertTrue(errors)
        self.assertIn("重复", errors[0].message)
        self.assertGreater(errors[0].line, 0)

    def test_duplicate_tmdb_id_is_rejected(self) -> None:
        duplicate = dict(self._read("cult_seed.csv")[0])
        duplicate.update(
            {"seed_id": "CS-9999", "title": "重复 TMDb", "tmdb_id": "985", "imdb_id": ""}
        )
        self._append("cult_seed.csv", duplicate)

        report = validate_knowledge(self.data_dir)
        errors = [issue for issue in report.errors if issue.field == "tmdb_id"]
        self.assertTrue(errors)
        self.assertIn("重复", errors[0].message)

    def test_invalid_source_reference_is_rejected(self) -> None:
        self._update(
            "cult_seed.csv", "seed_id", "CS-0001", candidate_source_ids="S-999"
        )
        report = validate_knowledge(self.data_dir)
        self.assertTrue(
            any(
                issue.field == "candidate_source_ids" and "S-999" in issue.message
                for issue in report.errors
            )
        )

    def test_invalid_criterion_reference_is_rejected(self) -> None:
        criteria = [
            row for row in self._read("cult_criteria.csv") if row["criterion_code"] != "C8"
        ]
        self._write("cult_criteria.csv", criteria)
        self._update("cult_seed.csv", "seed_id", "CS-0001", cult_criteria_codes="C8")

        report = validate_knowledge(self.data_dir)
        self.assertTrue(
            any(
                issue.field == "cult_criteria_codes" and "C8" in issue.message
                for issue in report.errors
            )
        )

    # ---------- approved 审核规则 ----------

    def test_approved_requires_two_supported_criteria(self) -> None:
        self._make_approved(with_evidence=False)
        report = validate_knowledge(self.data_dir)
        self.assertTrue(
            any(
                issue.field == "cult_criteria_codes"
                and "至少需要两条" in issue.message
                for issue in report.errors
            )
        )

    def test_approved_with_two_evidenced_criteria_passes(self) -> None:
        self._make_approved(with_evidence=True)
        report = validate_knowledge(self.data_dir)
        self.assertTrue(report.ok, [str(issue) for issue in report.errors])

    def test_approved_with_unverified_evidence_is_rejected(self) -> None:
        self._make_approved(with_evidence=True)
        self._update(
            "movie_criterion_evidence.csv",
            "seed_id",
            "CS-0001",
            verification_status="unverified",
        )
        report = validate_knowledge(self.data_dir)
        self.assertTrue(
            any(
                issue.field == "cult_criteria_codes"
                and "至少需要两条" in issue.message
                for issue in report.errors
            )
        )

    def test_invalid_verification_status_is_rejected(self) -> None:
        self._append(
            "movie_criterion_evidence.csv",
            {
                "seed_id": "CS-0001",
                "criterion_code": "C1",
                "source_id": "S-001",
                "evidence_summary": "测试夹具：核实状态枚举校验。",
                "locator": "测试定位",
                "verification_status": "maybe",
                "added_by": "TEST-FIXTURE",
                "added_at": FIXTURE_TIME,
            },
        )
        report = validate_knowledge(self.data_dir)
        self.assertTrue(
            any(
                issue.field == "verification_status" and issue.severity == "error"
                for issue in report.issues
            )
        )

    def test_disputed_evidence_produces_warning(self) -> None:
        self._append(
            "movie_criterion_evidence.csv",
            {
                "seed_id": "CS-0001",
                "criterion_code": "C1",
                "source_id": "S-001",
                "evidence_summary": "测试夹具：来源冲突需人工裁定。",
                "locator": "测试定位",
                "verification_status": "disputed",
                "added_by": "TEST-FIXTURE",
                "added_at": FIXTURE_TIME,
            },
        )
        report = validate_knowledge(self.data_dir)
        self.assertTrue(report.ok, [str(issue) for issue in report.errors])
        self.assertTrue(
            any(
                issue.field == "verification_status"
                and issue.severity == "warning"
                and "disputed" in issue.message
                for issue in report.warnings
            )
        )

    def test_invalid_review_status_is_rejected(self) -> None:
        self._update("cult_seed.csv", "seed_id", "CS-0001", review_status="published")
        report = validate_knowledge(self.data_dir)
        self.assertTrue(
            any(
                issue.field == "review_status" and issue.severity == "error"
                for issue in report.issues
            )
        )

    # ---------- 文化标签 ----------

    def test_manual_tag_requires_evidence(self) -> None:
        self._append(
            "movie_cult_tags.csv",
            {
                "seed_id": "CS-0001",
                "tag_id": "aesthetic_body_horror",
                "origin": "manual",
                "source_ids": "S-001",
                "annotator": "TEST-FIXTURE",
                "reviewed": "true",
                "updated_at": FIXTURE_TIME,
            },
        )
        report = validate_knowledge(self.data_dir)
        self.assertTrue(
            any("人工标签必须填写 evidence" in issue.message for issue in report.errors)
        )

    def test_inferred_tag_requires_rule_id(self) -> None:
        self._append(
            "movie_cult_tags.csv",
            {
                "seed_id": "CS-0001",
                "tag_id": "aesthetic_body_horror",
                "origin": "inferred",
                "confidence": "0.6",
                "updated_at": FIXTURE_TIME,
            },
        )
        report = validate_knowledge(self.data_dir)
        self.assertTrue(
            any("推断标签必须填写 rule_id" in issue.message for issue in report.errors)
        )

    def test_inferred_tag_cannot_duplicate_manual_tag(self) -> None:
        base = {
            "seed_id": "CS-0001",
            "tag_id": "aesthetic_body_horror",
            "reviewed": "true",
            "updated_at": FIXTURE_TIME,
        }
        self._append(
            "movie_cult_tags.csv",
            {
                **base,
                "origin": "manual",
                "evidence": "测试夹具：人工标注证据。",
                "source_ids": "S-001",
                "annotator": "TEST-FIXTURE",
            },
        )
        self._append(
            "movie_cult_tags.csv",
            {
                **base,
                "origin": "inferred",
                "confidence": "0.8",
                "rule_id": "rule_test_fixture",
            },
        )
        report = validate_knowledge(self.data_dir)
        self.assertTrue(
            any("推断结果不得覆盖人工标注" in issue.message for issue in report.errors)
        )

    def test_invalid_tag_reference_is_rejected(self) -> None:
        self._append(
            "movie_cult_tags.csv",
            {
                "seed_id": "CS-0001",
                "tag_id": "unknown_tag",
                "origin": "manual",
                "evidence": "测试夹具：标签引用测试。",
                "source_ids": "S-001",
                "annotator": "TEST-FIXTURE",
                "reviewed": "true",
                "updated_at": FIXTURE_TIME,
            },
        )
        report = validate_knowledge(self.data_dir)
        self.assertTrue(
            any(
                issue.field == "tag_id" and "标签不存在" in issue.message
                for issue in report.errors
            )
        )

    # ---------- 人工确认与 approved 规则 ----------

    def test_approved_requires_human_confirmed_evidence(self) -> None:
        """正文 verified 但没有人工确认时，不能计入 approved。"""
        self._make_approved(with_evidence=False)
        for code in ("C1", "C2"):
            self._append(
                "movie_criterion_evidence.csv",
                {
                    "seed_id": "CS-0001",
                    "criterion_code": code,
                    "source_id": "S-008",
                    "evidence_summary": "测试夹具：已核对正文但未人工确认。",
                    "locator": "测试定位",
                    "verification_status": "verified",
                    "human_status": "pending",
                    "added_by": "TEST-FIXTURE",
                    "added_at": FIXTURE_TIME,
                },
            )
        report = validate_knowledge(self.data_dir)
        self.assertFalse(report.ok)
        self.assertTrue(
            any(
                issue.field == "cult_criteria_codes"
                and "经人工确认" in issue.message
                for issue in report.errors
            )
        )

    def test_confirmed_candidate_requires_formal_tag(self) -> None:
        self._update(
            "movie_cult_tag_candidates.csv",
            "tag_id",
            "aesthetic_surrealism",
            human_status="confirmed",
            confirmed_by="TEST-FIXTURE",
            confirmed_at=FIXTURE_TIME,
        )
        report = validate_knowledge(self.data_dir)
        self.assertTrue(
            any(
                issue.field == "human_status" and "必须提升" in issue.message
                for issue in report.errors
            )
        )

    def test_pending_candidate_cannot_exist_in_formal_tags(self) -> None:
        self._append(
            "movie_cult_tags.csv",
            {
                "seed_id": "CS-0001",
                "tag_id": "aesthetic_surrealism",
                "origin": "manual",
                "evidence": "测试夹具：候选尚未确认却写入正式集合。",
                "source_ids": "S-008",
                "annotator": "TEST-FIXTURE",
                "reviewed": "true",
                "updated_at": FIXTURE_TIME,
            },
        )
        report = validate_knowledge(self.data_dir)
        self.assertTrue(
            any(
                issue.field == "human_status"
                and "已存在于正式人工标注集合" in issue.message
                for issue in report.errors
            )
        )

    def test_confirmed_candidate_with_formal_tag_passes(self) -> None:
        self._update(
            "movie_cult_tag_candidates.csv",
            "tag_id",
            "aesthetic_surrealism",
            human_status="confirmed",
            confirmed_by="TEST-FIXTURE",
            confirmed_at=FIXTURE_TIME,
        )
        self._append(
            "movie_cult_tags.csv",
            {
                "seed_id": "CS-0001",
                "tag_id": "aesthetic_surrealism",
                "origin": "manual",
                "evidence": "测试夹具：候选已人工确认并提升。",
                "source_ids": "S-008",
                "annotator": "TEST-FIXTURE",
                "reviewed": "true",
                "updated_at": FIXTURE_TIME,
            },
        )
        report = validate_knowledge(self.data_dir)
        self.assertTrue(report.ok, [str(issue) for issue in report.errors])
        self.assertEqual(report.stats["tag_candidates_confirmed"], 1)
        self.assertEqual(report.stats["manual_tags"], 1)

    # ---------- 审核日志 ----------

    def test_valid_review_log_chain_passes(self) -> None:
        first = self._log_row("GENESIS", "2026-11-17T00:00:00+08:00")
        second = self._log_row(
            first["entry_hash"], "2026-11-17T01:00:00+08:00"
        )
        self._write("review_log.csv", [first, second])

        report = validate_knowledge(self.data_dir)
        self.assertEqual(
            [issue for issue in report.errors if issue.file == "review_log.csv"], []
        )

    def test_review_log_hash_chain_is_checked(self) -> None:
        first = self._log_row("GENESIS", "2026-11-17T00:00:00+08:00")
        second = self._log_row(
            first["entry_hash"], "2026-11-17T01:00:00+08:00"
        )
        second["entry_hash"] = "0" * 64
        self._write("review_log.csv", [first, second])

        report = validate_knowledge(self.data_dir)
        self.assertTrue(
            any(
                issue.field == "entry_hash" and "哈希校验失败" in issue.message
                for issue in report.errors
            )
        )

    def test_review_log_timestamp_order_is_checked(self) -> None:
        first = self._log_row("GENESIS", "2026-11-17T02:00:00+08:00")
        second = self._log_row(
            first["entry_hash"], "2026-11-17T01:00:00+08:00"
        )
        self._write("review_log.csv", [first, second])

        report = validate_knowledge(self.data_dir)
        self.assertTrue(
            any(
                issue.field == "timestamp" and "追加写入顺序" in issue.message
                for issue in report.errors
            )
        )


class ReviewServiceTest(unittest.TestCase):
    """人工审核提交、状态迁移、日志哈希链与写入回滚。"""

    LOG_FILES = (
        "cult_seed.csv",
        "movie_criterion_evidence.csv",
        "movie_cult_tag_candidates.csv",
        "movie_cult_tags.csv",
        "review_log.csv",
    )

    CHILD_SUBMIT = """
import sys
sys.path.insert(0, r"{backend}")
from app.services.review_store import submit_review

result = submit_review(
    r"{data_dir}",
    "{seed_id}",
    reviewer="审核员A",
    decision="pending",
    reason="并发测试",
    evidence_decisions={{("{criterion}", "{source}"): "confirmed"}},
)
print(result["evidence_confirmed"])
"""

    CHILD_CRASH = """
import os
import sys
from pathlib import Path

sys.path.insert(0, r"{backend}")
from app.services import review_store as rs

target = str(Path(r"{data_dir}"))
original = rs._write_rows


def crashing_write(path, header, rows):
    original(path, header, rows)
    if str(path).startswith(target) and Path(path).name == "movie_criterion_evidence.csv":
        os._exit(9)


rs._write_rows = crashing_write
rs.submit_review(
    r"{data_dir}",
    "CS-0001",
    reviewer="审核员A",
    decision="pending",
    reason="崩溃测试",
    evidence_decisions={{("C1", "S-008"): "confirmed"}},
)
"""

    CHILD_RECOVERY_CRASH = """
import os
import sys
from pathlib import Path

sys.path.insert(0, r"{backend}")
from app.services import review_store as rs

target = Path(r"{data_dir}")
original = rs._write_bytes_atomic
count = {{"n": 0}}
names = {{"cult_seed.csv", "movie_criterion_evidence.csv", "movie_cult_tag_candidates.csv"}}


def crashing_write(path, content):
    original(path, content)
    path = Path(path)
    if path.parent == target and path.name in names:
        count["n"] += 1
        if count["n"] == 2:
            os._exit(9)


rs._write_bytes_atomic = crashing_write
rs.recover_pending_transaction(r"{data_dir}")
"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name) / "knowledge"
        shutil.copytree(KNOWLEDGE_DIR, self.data_dir)
        # 与生产审核进度解耦：固定夹具 + 三条 draft→pending 历史。
        reset_pilot_fixture(self.data_dir)
        backfill_draft_to_pending(self.data_dir, now=self._t(0))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ---------- 工具 ----------

    @staticmethod
    def _t(hour: int) -> datetime:
        return datetime(2026, 11, 17, hour, 0, 0, tzinfo=timezone(timedelta(hours=8)))

    def _read(self, filename: str) -> list[dict[str, str]]:
        with (self.data_dir / filename).open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            return list(csv.DictReader(handle))

    def _write(self, filename: str, rows: list[dict[str, str]]) -> None:
        with (self.data_dir / filename).open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=EXPECTED_HEADERS[filename])
            writer.writeheader()
            writer.writerows(rows)

    def _seed(self, seed_id: str) -> dict[str, str]:
        return next(row for row in self._read("cult_seed.csv") if row["seed_id"] == seed_id)

    def _make_applying_txn(self, names: list[str]) -> tuple[Path, dict[str, bytes]]:
        txn = self.data_dir / ".review_txn"
        backup = txn / "backup"
        backup.mkdir(parents=True)
        originals: dict[str, bytes] = {}
        files = []
        for name in names:
            content = (self.data_dir / name).read_bytes()
            originals[name] = content
            (backup / name).write_bytes(content)
            files.append({"name": name, "existed": True})
        (txn / "manifest.json").write_text(
            json.dumps({"version": 2, "phase": "applying", "files": files}),
            encoding="utf-8",
        )
        return txn, originals

    # ---------- 提交校验 ----------

    def test_partial_evidence_confirmation_keeps_pending(self) -> None:
        result = submit_review(
            self.data_dir,
            "CS-0001",
            reviewer="审核员A",
            decision="pending",
            reason="先确认 C1 证据，其余待复核",
            evidence_decisions={("C1", "S-008"): "confirmed"},
            now=self._t(12),
        )
        self.assertEqual(result["review_status"], "pending")
        self.assertEqual(result["evidence_confirmed"], 1)
        evidence = {
            (row["criterion_code"], row["source_id"]): row
            for row in self._read("movie_criterion_evidence.csv")
            if row["seed_id"] == "CS-0001"
        }
        self.assertEqual(evidence[("C1", "S-008")]["human_status"], "confirmed")
        self.assertEqual(evidence[("C1", "S-008")]["confirmed_by"], "审核员A")
        self.assertEqual(evidence[("C2", "S-008")]["human_status"], "pending")
        self.assertEqual(self._seed("CS-0001")["reviewer"], "")
        self.assertTrue(validate_knowledge(self.data_dir).ok)

    def test_duplicate_submission_is_rejected(self) -> None:
        submit_review(
            self.data_dir,
            "CS-0001",
            reviewer="审核员A",
            decision="pending",
            reason="确认 C1",
            evidence_decisions={("C1", "S-008"): "confirmed"},
            now=self._t(12),
        )
        with self.assertRaises(ReviewError) as ctx:
            submit_review(
                self.data_dir,
                "CS-0001",
                reviewer="审核员A",
                decision="pending",
                reason="重复确认 C1",
                evidence_decisions={("C1", "S-008"): "confirmed"},
                now=self._t(13),
            )
        self.assertIn("重复提交", str(ctx.exception))

    def test_illegal_status_transition_is_rejected(self) -> None:
        with self.assertRaises(ReviewError) as ctx:
            submit_review(
                self.data_dir,
                "CS-0004",
                reviewer="审核员A",
                decision="approved",
                reason="测试越级迁移",
                now=self._t(12),
            )
        self.assertIn("非法状态迁移", str(ctx.exception))
        self.assertEqual(self._seed("CS-0004")["review_status"], "draft")

    def test_reviewer_cannot_be_ai_placeholder(self) -> None:
        with self.assertRaises(ReviewError) as ctx:
            submit_review(
                self.data_dir,
                "CS-0001",
                reviewer="AI-draft (CULTScope)",
                decision="pending",
                reason="测试占位审核人",
                evidence_decisions={("C1", "S-008"): "confirmed"},
                now=self._t(12),
            )
        self.assertIn("真实人工审核者", str(ctx.exception))

    def test_approved_with_one_confirmed_criterion_is_rejected(self) -> None:
        with self.assertRaises(ReviewError) as ctx:
            submit_review(
                self.data_dir,
                "CS-0001",
                reviewer="审核员A",
                decision="approved",
                reason="仅确认一条标准",
                evidence_decisions={("C1", "S-008"): "confirmed"},
                now=self._t(12),
            )
        self.assertIn("至少需要两条", str(ctx.exception))
        # 失败不得留下部分修改
        self.assertEqual(self._seed("CS-0001")["review_status"], "pending")
        evidence = {
            (row["criterion_code"], row["source_id"]): row
            for row in self._read("movie_criterion_evidence.csv")
        }
        self.assertEqual(evidence[("C1", "S-008")]["human_status"], "pending")

    def test_t3_only_evidence_cannot_support_approved(self) -> None:
        with self.assertRaises(ReviewError) as ctx:
            submit_review(
                self.data_dir,
                "CS-0002",
                reviewer="审核员A",
                decision="approved",
                reason="仅确认 T3 媒体来源",
                evidence_decisions={
                    ("C4", "S-011"): "confirmed",
                    ("C7", "S-011"): "confirmed",
                },
                now=self._t(12),
            )
        self.assertIn("至少需要两条", str(ctx.exception))
        self.assertEqual(self._seed("CS-0002")["review_status"], "pending")

    def test_approved_with_two_criteria_writes_valid_log_chain(self) -> None:
        result = submit_review(
            self.data_dir,
            "CS-0001",
            reviewer="审核员A",
            decision="approved",
            reason="两条 T1 来源证据均已人工确认",
            evidence_decisions={
                ("C1", "S-008"): "confirmed",
                ("C2", "S-008"): "confirmed",
            },
            now=self._t(12),
        )
        self.assertEqual(result["review_status"], "approved")
        self.assertEqual(result["reviewer"], "审核员A")
        self.assertTrue(result["reviewed_at"])
        seed = self._seed("CS-0001")
        self.assertEqual(seed["review_status"], "approved")
        self.assertEqual(seed["reviewer"], "审核员A")

        report = validate_knowledge(self.data_dir)
        self.assertTrue(report.ok, [str(issue) for issue in report.errors])
        log_rows = self._read("review_log.csv")
        self.assertEqual(len(log_rows), 3 + result["log_entries"])
        self.assertTrue(
            any(
                row["field"] == "review_status"
                and row["seed_id"] == "CS-0001"
                and row["new_value"] == "approved"
                for row in log_rows
            )
        )
        self.assertEqual({row["actor"] for row in log_rows[-result["log_entries"]:]}, {"审核员A"})

    def test_confirmed_tag_is_promoted_to_formal_tags(self) -> None:
        result = submit_review(
            self.data_dir,
            "CS-0001",
            reviewer="审核员A",
            decision="pending",
            reason="确认超现实主义标签",
            tag_decisions={"aesthetic_surrealism": "confirmed"},
            now=self._t(12),
        )
        self.assertEqual(result["tags_confirmed"], 1)
        formal = [
            row
            for row in self._read("movie_cult_tags.csv")
            if row["tag_id"] == "aesthetic_surrealism"
        ]
        self.assertEqual(len(formal), 1)
        self.assertEqual(formal[0]["origin"], "manual")
        self.assertEqual(formal[0]["annotator"], "审核员A")
        self.assertEqual(formal[0]["reviewed"], "true")
        candidate = next(
            row
            for row in self._read("movie_cult_tag_candidates.csv")
            if row["tag_id"] == "aesthetic_surrealism"
        )
        self.assertEqual(candidate["human_status"], "confirmed")
        self.assertEqual(candidate["confirmed_by"], "审核员A")
        self.assertTrue(validate_knowledge(self.data_dir).ok)
        self.assertTrue(
            any(
                row["field"] == "tag:aesthetic_surrealism:add"
                for row in self._read("review_log.csv")
            )
        )

    def test_backfill_is_idempotent_and_marks_unknown_origin(self) -> None:
        self._write("review_log.csv", [])
        first = backfill_draft_to_pending(self.data_dir, now=self._t(1))
        second = backfill_draft_to_pending(self.data_dir, now=self._t(2))
        self.assertEqual(first, 3)
        self.assertEqual(second, 0)

        rows = self._read("review_log.csv")
        self.assertEqual(len(rows), 3)
        self.assertEqual({row["actor"] for row in rows}, {"system-backfill"})
        for row in rows:
            self.assertEqual(row["old_value"], "draft")
            self.assertEqual(row["new_value"], "pending")
            self.assertIn("未知", row["reason"])
        self.assertTrue(validate_knowledge(self.data_dir).ok)

    def test_concurrent_submissions_are_serialized(self) -> None:
        processes = []
        for criterion in ("C1", "C2"):
            code = self.CHILD_SUBMIT.format(
                backend=str(BACKEND_DIR),
                data_dir=str(self.data_dir),
                seed_id="CS-0001",
                criterion=criterion,
                source="S-008",
            )
            processes.append(
                subprocess.Popen(
                    [sys.executable, "-c", code],
                    cwd=str(BACKEND_DIR),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )

        outputs = []
        for process in processes:
            out, err = process.communicate(timeout=90)
            self.assertEqual(process.returncode, 0, err)
            outputs.append(out.strip())
        self.assertEqual(sorted(outputs), ["1", "2"])

        evidence = {
            (row["criterion_code"], row["source_id"]): row
            for row in self._read("movie_criterion_evidence.csv")
            if row["seed_id"] == "CS-0001"
        }
        self.assertEqual(evidence[("C1", "S-008")]["human_status"], "confirmed")
        self.assertEqual(evidence[("C2", "S-008")]["human_status"], "confirmed")
        report = validate_knowledge(self.data_dir)
        self.assertTrue(report.ok, [str(issue) for issue in report.errors])
        self.assertEqual(report.stats["review_log"], 5)
        self.assertFalse((self.data_dir / ".review_txn").exists())

    def test_process_crash_is_recovered_from_manifest(self) -> None:
        before = {
            name: (self.data_dir / name).read_bytes() for name in self.LOG_FILES
        }
        code = self.CHILD_CRASH.format(
            backend=str(BACKEND_DIR), data_dir=str(self.data_dir)
        )
        process = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(BACKEND_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=90,
        )
        self.assertEqual(process.returncode, 9, process.stderr)
        txn = self.data_dir / ".review_txn"
        self.assertTrue(txn.exists())
        self.assertTrue(
            any(
                (self.data_dir / name).read_bytes() != content
                for name, content in before.items()
            )
        )

        self.assertTrue(recover_pending_transaction(self.data_dir))
        for name, content in before.items():
            self.assertEqual((self.data_dir / name).read_bytes(), content, name)
        self.assertFalse(txn.exists())
        # 恢复流程可重复执行：第二次为 no-op。
        self.assertFalse(recover_pending_transaction(self.data_dir))
        for name, content in before.items():
            self.assertEqual((self.data_dir / name).read_bytes(), content, name)
        self.assertTrue(validate_knowledge(self.data_dir).ok)

        # 恢复后仍可正常提交。
        submit_review(
            self.data_dir,
            "CS-0001",
            reviewer="审核员A",
            decision="pending",
            reason="恢复后提交",
            evidence_decisions={("C1", "S-008"): "confirmed"},
            now=self._t(12),
        )
        self.assertTrue(validate_knowledge(self.data_dir).ok)

    def test_committed_transaction_is_not_rolled_back(self) -> None:
        txn = self.data_dir / ".review_txn"
        backup_dir = txn / "backup"
        backup_dir.mkdir(parents=True)
        original = (self.data_dir / "cult_seed.csv").read_bytes()
        (backup_dir / "cult_seed.csv").write_bytes(original)
        (txn / "manifest.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "files": [{"name": "cult_seed.csv", "existed": True}],
                }
            ),
            encoding="utf-8",
        )
        (txn / "committed").write_text("committed\n", encoding="utf-8")
        committed = original + b"\r\n"
        (self.data_dir / "cult_seed.csv").write_bytes(committed)

        self.assertFalse(recover_pending_transaction(self.data_dir))
        self.assertEqual(
            (self.data_dir / "cult_seed.csv").read_bytes(), committed
        )
        self.assertFalse(txn.exists())

    def test_crash_during_recovery_preserves_backups_and_resumes(self) -> None:
        names = [
            "cult_seed.csv",
            "movie_criterion_evidence.csv",
            "movie_cult_tag_candidates.csv",
        ]
        txn, originals = self._make_applying_txn(names)
        for name in names:
            (self.data_dir / name).write_bytes(b"PARTIAL COMMIT\n")

        code = self.CHILD_RECOVERY_CRASH.format(
            backend=str(BACKEND_DIR), data_dir=str(self.data_dir)
        )
        process = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(BACKEND_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=90,
        )
        self.assertEqual(process.returncode, 9, process.stderr)

        # 恢复在第二个文件处中断：清单、全部备份、原始状态仍必须保留。
        self.assertTrue((txn / "manifest.json").exists())
        self.assertFalse((txn / "committed").exists())
        self.assertFalse((txn / "restored").exists())
        for name in names:
            self.assertTrue((txn / "backup" / name).exists())

        self.assertTrue(recover_pending_transaction(self.data_dir))
        for name in names:
            self.assertEqual((self.data_dir / name).read_bytes(), originals[name])
        self.assertFalse(txn.exists())
        self.assertTrue(validate_knowledge(self.data_dir).ok)
        self.assertFalse(recover_pending_transaction(self.data_dir))

    def test_missing_manifest_with_payload_is_refused(self) -> None:
        txn = self.data_dir / ".review_txn"
        backup_dir = txn / "backup"
        backup_dir.mkdir(parents=True)
        (backup_dir / "cult_seed.csv").write_bytes(b"backup-only\n")
        before = (self.data_dir / "cult_seed.csv").read_bytes()

        with self.assertRaises(ReviewError) as ctx:
            recover_pending_transaction(self.data_dir)
        self.assertIn("拒绝自动清理", str(ctx.exception))
        self.assertTrue((txn / "manifest.json").parent.exists())
        self.assertTrue((backup_dir / "cult_seed.csv").exists())
        self.assertEqual((self.data_dir / "cult_seed.csv").read_bytes(), before)

    def test_missing_manifest_with_only_empty_dirs_is_cleaned(self) -> None:
        txn = self.data_dir / ".review_txn"
        (txn / "backup").mkdir(parents=True)
        before = (self.data_dir / "cult_seed.csv").read_bytes()

        self.assertFalse(recover_pending_transaction(self.data_dir))
        self.assertFalse(txn.exists())
        self.assertEqual((self.data_dir / "cult_seed.csv").read_bytes(), before)

    def test_preparing_phase_is_cleaned_without_touching_data(self) -> None:
        txn = self.data_dir / ".review_txn"
        backup_dir = txn / "backup"
        backup_dir.mkdir(parents=True)
        (backup_dir / "cult_seed.csv").write_bytes(b"partial backup\n")
        (txn / "manifest.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "phase": "preparing",
                    "files": [{"name": "cult_seed.csv", "existed": True}],
                }
            ),
            encoding="utf-8",
        )
        before = (self.data_dir / "cult_seed.csv").read_bytes()

        self.assertFalse(recover_pending_transaction(self.data_dir))
        self.assertFalse(txn.exists())
        self.assertEqual((self.data_dir / "cult_seed.csv").read_bytes(), before)

    def test_missing_backup_is_refused_before_any_restore(self) -> None:
        txn = self.data_dir / ".review_txn"
        backup_dir = txn / "backup"
        backup_dir.mkdir(parents=True)
        (backup_dir / "cult_seed.csv").write_bytes(
            (self.data_dir / "cult_seed.csv").read_bytes()
        )
        files = [
            {"name": "cult_seed.csv", "existed": True},
            {"name": "movie_criterion_evidence.csv", "existed": True},
        ]
        (txn / "manifest.json").write_text(
            json.dumps({"version": 2, "phase": "applying", "files": files}),
            encoding="utf-8",
        )
        for name in ("cult_seed.csv", "movie_criterion_evidence.csv"):
            (self.data_dir / name).write_bytes(b"PARTIAL\n")
        partial = {
            name: (self.data_dir / name).read_bytes()
            for name in ("cult_seed.csv", "movie_criterion_evidence.csv")
        }

        with self.assertRaises(ReviewError) as ctx:
            recover_pending_transaction(self.data_dir)
        self.assertIn("备份缺失", str(ctx.exception))
        # 预检失败时不得先恢复已存在备份的文件。
        for name, content in partial.items():
            self.assertEqual((self.data_dir / name).read_bytes(), content)
        self.assertTrue((txn / "manifest.json").exists())
        self.assertTrue((backup_dir / "cult_seed.csv").exists())

    def test_committed_without_manifest_keeps_new_data(self) -> None:
        txn = self.data_dir / ".review_txn"
        backup_dir = txn / "backup"
        backup_dir.mkdir(parents=True)
        original = (self.data_dir / "cult_seed.csv").read_bytes()
        (backup_dir / "cult_seed.csv").write_bytes(original)
        (txn / "committed").write_text("committed\n", encoding="utf-8")
        committed = original + b"\r\n"
        (self.data_dir / "cult_seed.csv").write_bytes(committed)

        self.assertFalse(recover_pending_transaction(self.data_dir))
        self.assertEqual((self.data_dir / "cult_seed.csv").read_bytes(), committed)
        self.assertFalse(txn.exists())

    def test_restored_marker_cleanup_does_not_touch_data(self) -> None:
        txn = self.data_dir / ".review_txn"
        backup_dir = txn / "backup"
        backup_dir.mkdir(parents=True)
        original = (self.data_dir / "cult_seed.csv").read_bytes()
        (backup_dir / "cult_seed.csv").write_bytes(original)
        (txn / "restored").write_text("restored\n", encoding="utf-8")
        current = original + b"\r\n"
        (self.data_dir / "cult_seed.csv").write_bytes(current)

        self.assertFalse(recover_pending_transaction(self.data_dir))
        self.assertEqual((self.data_dir / "cult_seed.csv").read_bytes(), current)
        self.assertFalse(txn.exists())

    def test_duplicate_tag_submission_is_rejected(self) -> None:
        submit_review(
            self.data_dir,
            "CS-0001",
            reviewer="审核员A",
            decision="pending",
            reason="确认标签",
            tag_decisions={"aesthetic_surrealism": "confirmed"},
            now=self._t(12),
        )
        with self.assertRaises(ReviewError) as ctx:
            submit_review(
                self.data_dir,
                "CS-0001",
                reviewer="审核员A",
                decision="pending",
                reason="重复确认标签",
                tag_decisions={"aesthetic_surrealism": "confirmed"},
                now=self._t(13),
            )
        self.assertIn("重复提交", str(ctx.exception))

        with self.assertRaises(ReviewError) as ctx:
            submit_review(
                self.data_dir,
                "CS-0001",
                reviewer="审核员A",
                decision="pending",
                reason="覆盖已确认标签",
                tag_decisions={"aesthetic_surrealism": "rejected"},
                now=self._t(14),
            )
        self.assertIn("拒绝覆盖", str(ctx.exception))

    def test_confirmed_evidence_cannot_be_overwritten_by_default(self) -> None:
        submit_review(
            self.data_dir,
            "CS-0001",
            reviewer="审核员A",
            decision="pending",
            reason="确认 C1",
            evidence_decisions={("C1", "S-008"): "confirmed"},
            now=self._t(12),
        )
        with self.assertRaises(ReviewError) as ctx:
            submit_review(
                self.data_dir,
                "CS-0001",
                reviewer="审核员A",
                decision="pending",
                reason="尝试驳回已确认证据",
                evidence_decisions={("C1", "S-008"): "rejected"},
                now=self._t(13),
            )
        self.assertIn("拒绝覆盖", str(ctx.exception))
        evidence = {
            (row["criterion_code"], row["source_id"]): row
            for row in self._read("movie_criterion_evidence.csv")
        }
        self.assertEqual(evidence[("C1", "S-008")]["human_status"], "confirmed")

    def test_confirmed_evidence_can_be_overridden_explicitly(self) -> None:
        submit_review(
            self.data_dir,
            "CS-0001",
            reviewer="审核员A",
            decision="pending",
            reason="确认 C1",
            evidence_decisions={("C1", "S-008"): "confirmed"},
            now=self._t(12),
        )
        submit_review(
            self.data_dir,
            "CS-0001",
            reviewer="审核员B",
            decision="pending",
            reason="发现定位错误，显式更正",
            evidence_decisions={("C1", "S-008"): "rejected"},
            allow_override=True,
            now=self._t(13),
        )
        evidence = {
            (row["criterion_code"], row["source_id"]): row
            for row in self._read("movie_criterion_evidence.csv")
        }
        self.assertEqual(evidence[("C1", "S-008")]["human_status"], "rejected")
        self.assertEqual(evidence[("C1", "S-008")]["confirmed_by"], "审核员B")
        self.assertTrue(
            any(
                row["field"] == "evidence:C1:S-008:human_status"
                and row["old_value"] == "confirmed"
                and row["new_value"] == "rejected"
                for row in self._read("review_log.csv")
            )
        )
        self.assertTrue(validate_knowledge(self.data_dir).ok)

    def test_write_failure_rolls_back_all_files(self) -> None:
        before = {
            name: (self.data_dir / name).read_bytes() for name in self.LOG_FILES
        }
        with self.assertRaises(ReviewError) as ctx:
            submit_review(
                self.data_dir,
                "CS-0001",
                reviewer="审核员A",
                decision="pending",
                reason="注入写入失败",
                evidence_decisions={("C1", "S-008"): "confirmed"},
                fail_after=3,
                now=self._t(12),
            )
        self.assertIn("写入失败，已回滚", str(ctx.exception))
        for name, content in before.items():
            self.assertEqual((self.data_dir / name).read_bytes(), content, name)
        self.assertFalse((self.data_dir / ".review_txn").exists())
        self.assertTrue(validate_knowledge(self.data_dir).ok)


class LegacyApiRegressionTest(unittest.TestCase):
    """启动真实 uvicorn 子进程，回归第二阶段两个接口。"""

    @classmethod
    def setUpClass(cls) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(cls.port),
            ],
            cwd=str(BACKEND_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        deadline = time.time() + 20
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                    f"{cls.base_url}/api/health", timeout=1
                ) as response:
                    if response.status == 200:
                        return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                time.sleep(0.3)
        cls.process.terminate()
        raise RuntimeError(f"回归测试服务器启动失败：{last_error}")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.process.terminate()
        try:
            cls.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.process.kill()

    def _get(self, path: str) -> dict:
        with urllib.request.urlopen(f"{self.base_url}{path}", timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_existing_movie_endpoints_are_unchanged(self) -> None:
        movies = self._get("/api/movies")
        stats = self._get("/api/movies/stats")
        filtered = self._get("/api/movies?decade=1980s")

        self.assertEqual(movies["sample_size"], 12)
        self.assertEqual(movies["total"], 12)
        self.assertEqual(len(movies["movies"]), 12)
        self.assertEqual({movie["title"] for movie in movies["movies"]}, EXPECTED_TITLES)

        self.assertEqual(stats["sample_size"], 12)
        self.assertEqual(
            stats["sample_label"], "12 部人工选定的 Cult 电影探索样本"
        )
        decades = {
            item["decade"]: item["count"] for item in stats["decade_distribution"]
        }
        self.assertEqual(
            decades, {"1970s": 5, "1980s": 4, "1990s": 1, "2000s": 1, "2010s": 1}
        )
        self.assertEqual(stats["budget_known_count"], 12)
        self.assertEqual(stats["revenue_known_count"], 12)
        self.assertEqual(filtered["total"], 4)


class ReviewCliTest(unittest.TestCase):
    """CLI 输入键与 submit_review() 枚举之间的映射回归测试。"""

    def _packet(self) -> dict:
        return {
            "seed": {
                "seed_id": "CS-0001",
                "title": "橡皮头",
                "original_title": "Eraserhead",
                "year": "1977",
                "tmdb_id": "985",
                "imdb_id": "tt0074486",
                "candidate_source_ids": "S-008",
                "cult_criteria_codes": "C1|C2",
                "review_status": "pending",
                "reviewer": "",
            },
            "criteria": [
                {
                    "criterion_code": "C1",
                    "name_zh": "虚构标准",
                    "definition": "仅用于 CLI 映射测试。",
                    "evidence_requirement": "测试要求",
                    "exclusion_note": "测试排除",
                }
            ],
            "evidence": [
                {
                    "criterion_code": "C1",
                    "source_id": "S-008",
                    "source_tier": "T1",
                    "source_title": "测试来源",
                    "evidence_summary": "测试摘要",
                    "locator": "测试定位",
                    "verification_status": "verified",
                    "human_status": "pending",
                    "source_url": "https://example.invalid/test",
                },
                {
                    "criterion_code": "C2",
                    "source_id": "S-008",
                    "source_tier": "T1",
                    "source_title": "测试来源",
                    "evidence_summary": "测试摘要",
                    "locator": "测试定位",
                    "verification_status": "verified",
                    "human_status": "pending",
                    "source_url": "https://example.invalid/test",
                },
            ],
            "tag_candidates": [
                {
                    "tag_id": "aesthetic_surrealism",
                    "human_status": "pending",
                    "tag_definition": "测试标签定义",
                    "tag_inclusion": "测试纳入",
                    "tag_exclusion": "测试排除",
                    "evidence": "测试标签证据",
                    "source_ids": ["S-008"],
                }
            ],
        }

    def _result(self) -> dict:
        return {
            "review_status": "pending",
            "reviewer": "",
            "reviewed_at": "",
            "log_entries": 1,
        }

    def test_decision_keys_map_to_service_enums(self) -> None:
        expected = {
            "p": "pending",
            "a": "approved",
            "r": "rejected",
            "n": "needs_fix",
        }
        for key, decision in expected.items():
            with self.subTest(key=key):
                with patch.object(
                    review_cli, "load_packet", return_value=self._packet()
                ), patch.object(
                    review_cli, "submit_review", return_value=self._result()
                ) as submit, patch(
                    "builtins.input",
                    side_effect=["审核员A", "y", "s", "s", key, "测试理由", "CONFIRM"],
                ), patch("builtins.print"):
                    self.assertEqual(review_cli.command_review("CS-0001"), 0)
                self.assertEqual(submit.call_args.kwargs["decision"], decision)

    def test_q_cancels_without_writing(self) -> None:
        with patch.object(
            review_cli, "load_packet", return_value=self._packet()
        ), patch.object(review_cli, "submit_review") as submit, patch(
            "builtins.input",
            side_effect=["审核员A", "y", "s", "s", "q"],
        ), patch("builtins.print"):
            self.assertEqual(review_cli.command_review("CS-0001"), 1)
        submit.assert_not_called()

    def test_invalid_decision_is_reprompted(self) -> None:
        with patch.object(
            review_cli, "load_packet", return_value=self._packet()
        ), patch.object(
            review_cli, "submit_review", return_value=self._result()
        ) as submit, patch(
            "builtins.input",
            side_effect=["审核员A", "y", "s", "s", "x", "a", "测试理由", "CONFIRM"],
        ), patch("builtins.print"):
            self.assertEqual(review_cli.command_review("CS-0001"), 0)
        submit.assert_called_once()
        self.assertEqual(submit.call_args.kwargs["decision"], "approved")

    def test_invalid_evidence_choice_is_reprompted(self) -> None:
        with patch.object(
            review_cli, "load_packet", return_value=self._packet()
        ), patch.object(
            review_cli, "submit_review", return_value=self._result()
        ) as submit, patch(
            "builtins.input",
            side_effect=["审核员A", "x", "y", "s", "s", "p", "测试理由", "CONFIRM"],
        ), patch("builtins.print"):
            self.assertEqual(review_cli.command_review("CS-0001"), 0)
        self.assertEqual(
            submit.call_args.kwargs["evidence_decisions"],
            {("C1", "S-008"): "confirmed"},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
