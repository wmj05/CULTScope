"""候选审核资料包与入库预检测试；全部使用临时目录，不触碰生产数据。"""

from __future__ import annotations

import csv
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import scripts.build_candidate_review_packets as packet_builder  # noqa: E402
from scripts.build_candidate_review_packets import (  # noqa: E402
    DEFAULT_CANDIDATES,
    DEFAULT_IDENTITY,
    DEFAULT_REVIEW,
    DEFAULT_SOURCES,
    HUMAN_FIELDS,
    PACKET_FIELDS,
    PacketWriteError,
    build_from_files,
    build_packet_rows,
    inspect_human_records,
    summarize,
    write_packets,
)
from scripts.precheck_candidate_promotion import (  # noqa: E402
    prepare_precheck_packets,
    precheck_candidates,
)
from scripts.validate_candidate_identity import IDENTITY_FIELDS  # noqa: E402
from scripts.validate_candidate_sources import (  # noqa: E402
    REVIEW_FIELDS,
    SOURCE_FIELDS,
)
from scripts.validate_cult_candidates import CANDIDATE_FIELDS  # noqa: E402

KNOWLEDGE_FIELDS = [
    "seed_id", "title", "original_title", "year", "tmdb_id", "imdb_id"
]
CRITERIA_ROWS = [
    {"criterion_code": f"C{index}", "name_zh": f"标准{index}", "name_en": f"C{index}"}
    for index in range(1, 9)
]
PROTECTED_FILES = [
    DEFAULT_CANDIDATES,
    DEFAULT_SOURCES,
    DEFAULT_REVIEW,
    DEFAULT_IDENTITY,
    BACKEND_DIR / "data" / "knowledge" / "cult_seed.csv",
    BACKEND_DIR / "data" / "knowledge" / "cult_sources.csv",
    BACKEND_DIR / "data" / "knowledge" / "cult_criteria.csv",
    BACKEND_DIR / "data" / "knowledge" / "movie_criterion_evidence.csv",
    BACKEND_DIR / "data" / "knowledge" / "review_log.csv",
    BACKEND_DIR / "data" / "knowledge" / "seed_identity_map.csv",
]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _candidate(candidate_id: str, title: str, year: str = "1980") -> dict[str, str]:
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


def _source(
    candidate_id: str,
    source_id: str,
    role: str,
    publisher: str,
    url: str,
    codes: str = "",
    verification: str = "verified",
    independence: str = "not_applicable",
) -> dict[str, str]:
    return {
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
        "verification_status": verification,
        "notes": "",
    }


def _review(
    candidate_id: str,
    status: str = "pending_human_review",
    second: str = "verified",
    quality: str = "strong",
    codes: str = "C5",
    unsupported: str = "",
) -> dict[str, str]:
    return {
        "candidate_id": candidate_id,
        "original_source_status": "verified",
        "second_source_status": second,
        "evidence_quality": quality,
        "supported_criteria": codes,
        "unsupported_criteria": unsupported,
        "review_recommendation": "priority_review",
        "reviewer": "",
        "review_status": status,
        "notes": "临时测试审核记录",
    }


def _identity(
    candidate_id: str,
    title: str,
    year: str,
    tmdb_id: str,
    imdb_id: str,
    status: str = "confirmed",
) -> dict[str, str]:
    return {
        "candidate_id": candidate_id,
        "candidate_title": title,
        "candidate_year": year,
        "tmdb_id": tmdb_id,
        "tmdb_title": title,
        "tmdb_original_title": title,
        "tmdb_release_date": f"{year}-01-01",
        "tmdb_year": year,
        "imdb_id": imdb_id,
        "tmdb_url": f"https://www.themoviedb.org/movie/{tmdb_id}",
        "imdb_url": f"https://www.imdb.com/title/{imdb_id}/",
        "match_method": "tmdb_website_wikidata",
        "match_status": status,
        "identity_evidence": "测试身份证据。",
        "checked_at": "2026-11-18",
        "notes": "",
    }


def _packet(**overrides: str) -> dict[str, str]:
    row = {
        "candidate_id": "CB01-001",
        "title": "Test Movie",
        "original_title": "Test Movie",
        "year": "1980",
        "review_group": "A",
        "identity_status": "confirmed",
        "tmdb_id": "1234",
        "imdb_id": "tt1234567",
        "primary_source": "BFI｜测试片单｜https://example.com/list",
        "second_source_status": "verified",
        "independent_source_count": "1",
        "supported_criteria": "C5|C7",
        "evidence_quality": "strong",
        "evidence_summary": "第一来源与第二来源均支持 C5 与 C7。",
        "evidence_gaps": "无结构性证据缺口",
        "current_review_status": "pending_human_review",
        "recommended_action": "human_review",
        "human_decision": "",
        "human_reviewer": "",
        "human_reviewed_at": "",
        "human_review_reason": "",
        "human_approved_criteria": "",
    }
    row.update(overrides)
    return row


def _approved(packet: dict[str, str], **overrides: str) -> dict[str, str]:
    packet.update(
        {
            "human_decision": "approve",
            "human_reviewer": "wmj",
            "human_reviewed_at": "2026-11-18T10:00:00+08:00",
            "human_review_reason": "已核对原始段落，采信 C5 与 C7。",
            "human_approved_criteria": "C5|C7",
        }
    )
    packet.update(overrides)
    return packet


def _sources_for(candidate_id: str = "CB01-001") -> list[dict[str, str]]:
    return [
        _source(
            candidate_id, "CB01-S01", "primary", "BFI",
            "https://example.com/list", "C5|C7",
        ),
        _source(
            candidate_id, "CB01-S02", "second", "Senses of Cinema",
            "https://example.com/second", "C5|C7", independence="independent",
        ),
    ]


def _precheck(packet: dict[str, str], **kwargs: object):
    identity_rows = kwargs.pop("identity_rows", None) or [
        _identity("CB01-001", "Test Movie", "1980", "1234", "tt1234567")
    ]
    knowledge_rows = kwargs.pop("knowledge_rows", None) or [
        _identity("CS-9999", "Other Movie", "1990", "9999", "tt9999999")
    ]
    source_rows = kwargs.pop("source_rows", None) or _sources_for()
    return precheck_candidates(
        [packet], source_rows, identity_rows, knowledge_rows, CRITERIA_ROWS
    )


def _write_fixture(root: Path) -> dict[str, Path]:
    paths = {
        "candidates": root / "candidates.csv",
        "sources": root / "sources.csv",
        "review": root / "review.csv",
        "identity": root / "identity.csv",
        "packets": root / "packets.csv",
    }
    _write(
        paths["candidates"],
        CANDIDATE_FIELDS,
        [
            _candidate("CB01-001", "Alpha"),
            _candidate("CB01-002", "Beta"),
            _candidate("CB01-003", "Gamma"),
        ],
    )
    _write(
        paths["sources"],
        SOURCE_FIELDS,
        _sources_for("CB01-001")
        + [
            _source(
                "CB01-002", "CB01-S01", "primary", "BFI",
                "https://example.com/beta", "C7",
            ),
            _source(
                "CB01-002", "CB01-S02", "second", "Kinoeye",
                "https://example.com/beta-second", "",
                verification="unavailable", independence="independent",
            ),
            _source(
                "CB01-003", "CB01-S01", "primary", "BFI",
                "https://example.com/gamma", "C5",
            ),
            _source(
                "CB01-003", "CB01-S02", "second", "Paste Magazine",
                "https://example.com/gamma-second", "C5",
                independence="independent",
            ),
        ],
    )
    _write(
        paths["review"],
        REVIEW_FIELDS,
        [
            _review("CB01-001"),
            _review(
                "CB01-002", status="needs_more_evidence",
                second="unavailable", quality="insufficient",
                codes="", unsupported="C7",
            ),
            _review("CB01-003", quality="moderate"),
        ],
    )
    _write(
        paths["identity"],
        IDENTITY_FIELDS,
        [
            _identity("CB01-001", "Alpha", "1980", "1234", "tt1234567"),
            _identity("CB01-002", "Beta", "1981", "2234", "tt2234567"),
            _identity(
                "CB01-003", "Gamma", "1982", "3234", "tt3234567",
                status="needs_review",
            ),
        ],
    )
    return paths


class ReviewPacketTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.candidates_path = self.root / "candidates.csv"
        self.sources_path = self.root / "sources.csv"
        self.review_path = self.root / "review.csv"
        self.identity_path = self.root / "identity.csv"
        self.packets_path = self.root / "packets.csv"

        _write(
            self.candidates_path,
            CANDIDATE_FIELDS,
            [
                _candidate("CB01-001", "Alpha"),
                _candidate("CB01-002", "Beta"),
                _candidate("CB01-003", "Gamma"),
            ],
        )
        _write(
            self.sources_path,
            SOURCE_FIELDS,
            _sources_for("CB01-001")
            + [
                _source(
                    "CB01-002", "CB01-S01", "primary", "BFI",
                    "https://example.com/beta", "C7",
                ),
                _source(
                    "CB01-002", "CB01-S02", "second", "Kinoeye",
                    "https://example.com/beta-second", "",
                    verification="unavailable", independence="independent",
                ),
                _source(
                    "CB01-003", "CB01-S01", "primary", "BFI",
                    "https://example.com/gamma", "C5",
                ),
                _source(
                    "CB01-003", "CB01-S02", "second", "Paste Magazine",
                    "https://example.com/gamma-second", "C5",
                    independence="independent",
                ),
            ],
        )
        _write(
            self.review_path,
            REVIEW_FIELDS,
            [
                _review("CB01-001"),
                _review(
                    "CB01-002", status="needs_more_evidence",
                    second="unavailable", quality="insufficient",
                    codes="", unsupported="C7",
                ),
                _review("CB01-003", quality="moderate"),
            ],
        )
        _write(
            self.identity_path,
            IDENTITY_FIELDS,
            [
                _identity("CB01-001", "Alpha", "1980", "1234", "tt1234567"),
                _identity("CB01-002", "Beta", "1981", "2234", "tt2234567"),
                _identity(
                    "CB01-003", "Gamma", "1982", "3234", "tt3234567",
                    status="needs_review",
                ),
            ],
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _build(self) -> list[dict[str, str]]:
        return build_from_files(
            self.candidates_path,
            self.sources_path,
            self.review_path,
            self.identity_path,
        )

    def test_each_candidate_has_exactly_one_packet(self) -> None:
        packets = self._build()
        self.assertEqual(3, len(packets))
        ids = [packet["candidate_id"] for packet in packets]
        self.assertEqual(3, len(set(ids)))
        self.assertEqual({"CB01-001", "CB01-002", "CB01-003"}, set(ids))
        self.assertEqual(set(PACKET_FIELDS), set(packets[0]))

    def test_packet_links_identity_and_sources(self) -> None:
        packets = {packet["candidate_id"]: packet for packet in self._build()}
        first = packets["CB01-001"]
        self.assertEqual("1234", first["tmdb_id"])
        self.assertEqual("tt1234567", first["imdb_id"])
        self.assertIn("BFI", first["primary_source"])
        self.assertIn("https://example.com/list", first["primary_source"])
        self.assertEqual("verified", first["second_source_status"])
        self.assertEqual("1", first["independent_source_count"])
        self.assertIn("Senses of Cinema", first["evidence_summary"])
        second = packets["CB01-002"]
        self.assertEqual("unavailable", second["second_source_status"])
        self.assertEqual("0", second["independent_source_count"])

    def test_review_groups_and_actions_match_source_data(self) -> None:
        packets = {packet["candidate_id"]: packet for packet in self._build()}
        self.assertEqual("A", packets["CB01-001"]["review_group"])
        self.assertEqual("C", packets["CB01-002"]["review_group"])
        self.assertEqual("collect_more_evidence", packets["CB01-002"]["recommended_action"])
        self.assertEqual("B", packets["CB01-003"]["review_group"])
        self.assertEqual("identity_review", packets["CB01-003"]["recommended_action"])

    def test_summary_matches_source_data(self) -> None:
        summary = summarize(self._build())
        self.assertEqual(3, summary["total"])
        self.assertEqual({"A": 1, "B": 1, "C": 1}, summary["groups"])
        self.assertEqual(1, summary["identity_pending"])
        self.assertEqual(1, summary["evidence_pending"])
        self.assertEqual(0, summary["human_decisions"])

    def test_generation_is_idempotent(self) -> None:
        packets = self._build()
        self.assertTrue(write_packets(self.packets_path, packets))
        first = _digest(self.packets_path)
        self.assertFalse(write_packets(self.packets_path, packets))
        self.assertEqual(first, _digest(self.packets_path))

    def test_human_fields_are_never_autofilled(self) -> None:
        packets = self._build()
        for packet in packets:
            self.assertEqual("", packet["human_decision"])
            self.assertEqual("", packet["human_reviewer"])
            self.assertEqual("", packet["human_reviewed_at"])
            self.assertEqual("", packet["human_review_reason"])
            self.assertEqual("", packet["human_approved_criteria"])

    def test_production_files_unchanged(self) -> None:
        before = {path: _digest(path) for path in PROTECTED_FILES}
        packets = build_from_files(
            DEFAULT_CANDIDATES, DEFAULT_SOURCES, DEFAULT_REVIEW, DEFAULT_IDENTITY
        )
        write_packets(self.packets_path, packets)
        identity_rows = _read_rows(DEFAULT_IDENTITY)
        source_rows = _read_rows(DEFAULT_SOURCES)
        knowledge_rows = _read_rows(
            BACKEND_DIR / "data" / "knowledge" / "cult_seed.csv"
        )
        precheck_candidates(
            packets, source_rows, identity_rows, knowledge_rows, CRITERIA_ROWS
        )
        after = {path: _digest(path) for path in PROTECTED_FILES}
        self.assertEqual(before, after)


class PromotionPrecheckTest(unittest.TestCase):
    def test_approved_packet_passes_all_checks(self) -> None:
        report = _precheck(_approved(_packet()))
        self.assertEqual(1, report.passed)
        self.assertEqual(1, report.approved)

    def test_blank_human_decision_blocks(self) -> None:
        candidate = _precheck(_packet()).candidates[0]
        checks = {check.code: check.ok for check in candidate.checks}
        self.assertFalse(candidate.passed)
        self.assertFalse(checks["human_approval"])

    def test_approve_without_reviewer_blocks(self) -> None:
        candidate = _precheck(_approved(_packet(), human_reviewer="")).candidates[0]
        checks = {check.code: check.ok for check in candidate.checks}
        self.assertFalse(candidate.passed)
        self.assertFalse(checks["human_audit"])
        self.assertIn("缺少审核人", "；".join(candidate.blocked_reasons))

    def test_approve_without_date_blocks(self) -> None:
        candidate = _precheck(_approved(_packet(), human_reviewed_at="")).candidates[0]
        checks = {check.code: check.ok for check in candidate.checks}
        self.assertFalse(candidate.passed)
        self.assertFalse(checks["human_audit"])
        self.assertIn("缺少审核日期", "；".join(candidate.blocked_reasons))

    def test_identity_needs_review_blocks(self) -> None:
        packet = _approved(_packet(identity_status="needs_review"))
        identity_rows = [
            _identity(
                "CB01-001", "Test Movie", "1980", "1234", "tt1234567",
                status="needs_review",
            )
        ]
        candidate = _precheck(packet, identity_rows=identity_rows).candidates[0]
        checks = {check.code: check.ok for check in candidate.checks}
        self.assertFalse(candidate.passed)
        self.assertFalse(checks["identity"])

    def test_insufficient_evidence_blocks_approval(self) -> None:
        for quality in ("weak", "insufficient"):
            candidate = _precheck(
                _approved(_packet(evidence_quality=quality))
            ).candidates[0]
            checks = {check.code: check.ok for check in candidate.checks}
            self.assertFalse(candidate.passed)
            self.assertFalse(checks["evidence_rules"])

    def test_single_criterion_approval_blocks(self) -> None:
        packet = _approved(
            _packet(
                supported_criteria="C5",
                human_approved_criteria="C5",
            )
        )
        candidate = _precheck(packet).candidates[0]
        checks = {check.code: check.ok for check in candidate.checks}
        self.assertFalse(candidate.passed)
        self.assertFalse(checks["human_audit"])
        self.assertFalse(checks["evidence_rules"])

    def test_duplicate_with_knowledge_base_blocks(self) -> None:
        knowledge_rows = [
            {
                "seed_id": "CS-0001",
                "title": "Test Movie",
                "original_title": "Test Movie",
                "year": "1980",
                "tmdb_id": "1234",
                "imdb_id": "tt1234567",
            }
        ]
        candidate = _precheck(
            _approved(_packet()), knowledge_rows=knowledge_rows
        ).candidates[0]
        checks = {check.code: check.ok for check in candidate.checks}
        self.assertFalse(candidate.passed)
        self.assertFalse(checks["duplicate_existing"])

    def test_identity_id_conflict_blocks(self) -> None:
        identity_rows = [
            _identity("CB01-001", "Test Movie", "1980", "1234", "tt1234567"),
            _identity("CB01-002", "Another Movie", "1990", "1234", "tt7654321"),
        ]
        candidate = _precheck(
            _approved(_packet()), identity_rows=identity_rows
        ).candidates[0]
        checks = {check.code: check.ok for check in candidate.checks}
        self.assertFalse(candidate.passed)
        self.assertFalse(checks["identity_conflict"])

    def test_precheck_does_not_modify_packet(self) -> None:
        packet = _approved(_packet())
        snapshot = dict(packet)
        _precheck(packet)
        self.assertEqual(snapshot, packet)

    def test_stats_match_packets(self) -> None:
        packets = [
            _packet(candidate_id="CB01-001", review_group="A"),
            _packet(candidate_id="CB01-002", review_group="C"),
            _packet(candidate_id="CB01-003", review_group="B",
                    identity_status="needs_review"),
        ]
        report = precheck_candidates(
            packets,
            _sources_for("CB01-001"),
            [
                _identity("CB01-001", "Test Movie", "1980", "1234", "tt1234567"),
                _identity("CB01-002", "Test Movie", "1980", "1235", "tt1234568"),
                _identity("CB01-003", "Test Movie", "1980", "1236", "tt1234569"),
            ],
            [],
            CRITERIA_ROWS,
        )
        self.assertEqual(3, report.total)
        self.assertEqual({"A": 1, "B": 1, "C": 1}, report.groups)
        self.assertEqual({"未填写": 3}, report.decisions)
        self.assertEqual(0, report.passed)


class HumanFieldProtectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.paths = _write_fixture(self.root)
        fresh = build_from_files(
            self.paths["candidates"],
            self.paths["sources"],
            self.paths["review"],
            self.paths["identity"],
        )
        write_packets(self.paths["packets"], fresh)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _rows(self) -> list[dict[str, str]]:
        return _read_rows(self.paths["packets"])

    def _build(self, existing: bool = True) -> list[dict[str, str]]:
        return build_from_files(
            self.paths["candidates"],
            self.paths["sources"],
            self.paths["review"],
            self.paths["identity"],
            existing_rows=self._rows() if existing else None,
        )

    def _record(self, candidate_id: str, **values: str) -> None:
        rows = self._rows()
        for row in rows:
            if row["candidate_id"] == candidate_id:
                row.update(values)
        _write(self.paths["packets"], PACKET_FIELDS, rows)

    def test_regeneration_preserves_human_fields_by_candidate_id(self) -> None:
        self._record(
            "CB01-001",
            human_decision="approve",
            human_reviewer="reviewer-a",
            human_reviewed_at="2026-11-18T10:00:00+08:00",
            human_review_reason="已核对原始段落",
            human_approved_criteria="C5|C7",
        )
        self._record(
            "CB01-002",
            human_decision="reject",
            human_reviewer="reviewer-b",
            human_reviewed_at="2026-11-18",
            human_review_reason="证据不足",
        )
        rows = self._rows()
        _write(self.paths["packets"], PACKET_FIELDS, list(reversed(rows)))

        packets = {row["candidate_id"]: row for row in self._build()}
        self.assertEqual("approve", packets["CB01-001"]["human_decision"])
        self.assertEqual("reviewer-a", packets["CB01-001"]["human_reviewer"])
        self.assertEqual("C5|C7", packets["CB01-001"]["human_approved_criteria"])
        self.assertEqual("reject", packets["CB01-002"]["human_decision"])
        self.assertEqual("reviewer-b", packets["CB01-002"]["human_reviewer"])
        self.assertEqual("", packets["CB01-003"]["human_decision"])

    def test_write_with_human_records_is_noop_when_derived_data_unchanged(self) -> None:
        self._record("CB01-001", human_decision="approve", human_reviewer="reviewer-a")
        before = _digest(self.paths["packets"])
        self.assertFalse(write_packets(self.paths["packets"], self._build(existing=False)))
        self.assertEqual(before, _digest(self.paths["packets"]))
        self.assertEqual("approve", self._rows()[0]["human_decision"])

    def test_derived_change_keeps_human_fields(self) -> None:
        self._record("CB01-001", human_decision="defer", human_reviewer="reviewer-a")
        review_rows = _read_rows(self.paths["review"])
        for row in review_rows:
            if row["candidate_id"] == "CB01-001":
                row["evidence_quality"] = "moderate"
        _write(self.paths["review"], REVIEW_FIELDS, review_rows)

        self.assertTrue(write_packets(self.paths["packets"], self._build(existing=False)))
        packets = {row["candidate_id"]: row for row in self._rows()}
        self.assertEqual("moderate", packets["CB01-001"]["evidence_quality"])
        self.assertEqual("defer", packets["CB01-001"]["human_decision"])
        self.assertEqual("reviewer-a", packets["CB01-001"]["human_reviewer"])

    def test_unknown_existing_candidate_blocks_write(self) -> None:
        rows = self._rows()
        extra = dict(rows[0])
        extra["candidate_id"] = "CB01-099"
        rows.append(extra)
        _write(self.paths["packets"], PACKET_FIELDS, rows)
        with self.assertRaises(PacketWriteError):
            self._build()

    def test_duplicate_existing_candidate_blocks_write(self) -> None:
        rows = self._rows()
        rows.append(dict(rows[0]))
        _write(self.paths["packets"], PACKET_FIELDS, rows)
        with self.assertRaises(PacketWriteError):
            self._build()

    def test_title_change_blocks_decision_rebinding(self) -> None:
        self._record("CB01-001", human_decision="approve", human_reviewer="reviewer-a")
        rows = self._rows()
        for row in rows:
            if row["candidate_id"] == "CB01-001":
                row["title"] = "Another Movie"
        _write(self.paths["packets"], PACKET_FIELDS, rows)
        with self.assertRaises(PacketWriteError):
            self._build()

    def test_program_filled_human_fields_are_refused(self) -> None:
        packets = self._build(existing=False)
        packets[0]["human_decision"] = "approve"
        with self.assertRaises(PacketWriteError):
            write_packets(self.paths["packets"], packets)

    def test_inspection_lists_records_without_writing(self) -> None:
        self._record(
            "CB01-002",
            human_decision="request_more_evidence",
            human_reviewer="reviewer-b",
            human_reviewed_at="2026-11-18",
        )
        before = _digest(self.paths["packets"])
        result = inspect_human_records(self.paths["packets"])
        self.assertEqual(before, _digest(self.paths["packets"]))
        self.assertEqual(1, len(result["records"]))
        self.assertEqual("CB01-002", result["records"][0]["candidate_id"])
        self.assertEqual(
            "request_more_evidence", result["records"][0]["human_decision"]
        )
        self.assertEqual([], result["errors"])

    def test_precheck_recomputes_stale_packet_fields_without_writing(self) -> None:
        rows = self._rows()
        for row in rows:
            if row["candidate_id"] == "CB01-003":
                row["identity_status"] = "confirmed"
        _write(self.paths["packets"], PACKET_FIELDS, rows)
        before = _digest(self.paths["packets"])

        packets, stale = prepare_precheck_packets(
            self.paths["candidates"],
            self.paths["sources"],
            self.paths["review"],
            self.paths["identity"],
            self.paths["packets"],
        )
        self.assertIn("CB01-003", stale)
        fresh = {row["candidate_id"]: row for row in packets}
        self.assertEqual("needs_review", fresh["CB01-003"]["identity_status"])
        self.assertEqual(before, _digest(self.paths["packets"]))

        report = precheck_candidates(
            packets,
            _read_rows(self.paths["sources"]),
            _read_rows(self.paths["identity"]),
            [],
            CRITERIA_ROWS,
        )
        target = next(
            item for item in report.candidates if item.candidate_id == "CB01-003"
        )
        checks = {check.code: check.ok for check in target.checks}
        self.assertFalse(checks["identity"])


    def test_failed_replace_keeps_original_and_cleans_temp(self) -> None:
        self._record(
            "CB01-001",
            human_decision="approve",
            human_reviewer="reviewer-a",
            human_reviewed_at="2026-11-18",
            human_review_reason="已核对",
            human_approved_criteria="C5|C7",
        )
        review_rows = _read_rows(self.paths["review"])
        for row in review_rows:
            if row["candidate_id"] == "CB01-001":
                row["evidence_quality"] = "moderate"
        _write(self.paths["review"], REVIEW_FIELDS, review_rows)
        before = _digest(self.paths["packets"])

        with mock.patch(
            "scripts.build_candidate_review_packets.os.replace",
            side_effect=OSError("模拟替换失败"),
        ):
            with self.assertRaises(OSError):
                write_packets(self.paths["packets"], self._build(existing=False))

        self.assertEqual(before, _digest(self.paths["packets"]))
        self.assertEqual([], list(self.root.glob("*.tmp")))

    def test_concurrent_modification_is_refused(self) -> None:
        self._record(
            "CB01-001",
            human_decision="approve",
            human_reviewer="reviewer-a",
            human_reviewed_at="2026-11-18",
            human_review_reason="已核对",
            human_approved_criteria="C5|C7",
        )
        review_rows = _read_rows(self.paths["review"])
        for row in review_rows:
            if row["candidate_id"] == "CB01-001":
                row["evidence_quality"] = "moderate"
        _write(self.paths["review"], REVIEW_FIELDS, review_rows)

        original_verify = packet_builder._verify_temp_packet

        def tamper(temp_path: Path, expected: list[dict[str, str]]) -> None:
            self.paths["packets"].write_bytes(
                self.paths["packets"].read_bytes() + b"\n"
            )
            original_verify(temp_path, expected)

        with mock.patch(
            "scripts.build_candidate_review_packets._verify_temp_packet",
            side_effect=tamper,
        ):
            with self.assertRaises(PacketWriteError) as caught:
                write_packets(self.paths["packets"], self._build(existing=False))
        self.assertIn("其他进程修改", str(caught.exception))

    def test_atomic_replace_preserves_human_fields(self) -> None:
        self._record(
            "CB01-001",
            human_decision="approve",
            human_reviewer="reviewer-a",
            human_reviewed_at="2026-11-18T10:00:00+08:00",
            human_review_reason="已核对原始段落",
            human_approved_criteria="C5|C7",
        )
        review_rows = _read_rows(self.paths["review"])
        for row in review_rows:
            if row["candidate_id"] == "CB01-001":
                row["evidence_quality"] = "moderate"
        _write(self.paths["review"], REVIEW_FIELDS, review_rows)

        self.assertTrue(
            write_packets(self.paths["packets"], self._build(existing=False))
        )
        packets = {row["candidate_id"]: row for row in self._rows()}
        first = packets["CB01-001"]
        self.assertEqual("moderate", first["evidence_quality"])
        self.assertEqual("approve", first["human_decision"])
        self.assertEqual("reviewer-a", first["human_reviewer"])
        self.assertEqual("2026-11-18T10:00:00+08:00", first["human_reviewed_at"])
        self.assertEqual("已核对原始段落", first["human_review_reason"])
        self.assertEqual("C5|C7", first["human_approved_criteria"])

    def test_human_record_blocks_year_change(self) -> None:
        self._record("CB01-001", human_decision="approve", human_reviewer="reviewer-a")
        candidate_rows = _read_rows(self.paths["candidates"])
        for row in candidate_rows:
            if row["candidate_id"] == "CB01-001":
                row["year"] = "1981"
        _write(self.paths["candidates"], CANDIDATE_FIELDS, candidate_rows)

        with self.assertRaises(PacketWriteError) as caught:
            self._build()
        message = str(caught.exception)
        self.assertIn("year", message)
        self.assertIn("1980", message)
        self.assertIn("1981", message)

    def test_human_record_blocks_tmdb_and_imdb_change(self) -> None:
        self._record("CB01-001", human_decision="approve", human_reviewer="reviewer-a")
        identity_rows = _read_rows(self.paths["identity"])
        for row in identity_rows:
            if row["candidate_id"] == "CB01-001":
                row["tmdb_id"] = "1235"
                row["imdb_id"] = "tt1234568"
        _write(self.paths["identity"], IDENTITY_FIELDS, identity_rows)

        with self.assertRaises(PacketWriteError) as caught:
            self._build()
        message = str(caught.exception)
        self.assertIn("tmdb_id", message)
        self.assertIn("imdb_id", message)

    def test_no_human_record_allows_update_and_is_idempotent(self) -> None:
        review_rows = _read_rows(self.paths["review"])
        for row in review_rows:
            if row["candidate_id"] == "CB01-001":
                row["evidence_quality"] = "moderate"
        _write(self.paths["review"], REVIEW_FIELDS, review_rows)

        self.assertTrue(
            write_packets(self.paths["packets"], self._build(existing=False))
        )
        first = _digest(self.paths["packets"])
        packets = {row["candidate_id"]: row for row in self._rows()}
        self.assertEqual("moderate", packets["CB01-001"]["evidence_quality"])
        self.assertEqual("", packets["CB01-001"]["human_decision"])

        self.assertFalse(
            write_packets(self.paths["packets"], self._build(existing=False))
        )
        self.assertEqual(first, _digest(self.paths["packets"]))


if __name__ == "__main__":
    unittest.main()
