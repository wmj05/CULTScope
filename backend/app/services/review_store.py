"""人工审核闭环：展示数据包、提交审核、补录历史、哈希链日志与写入回滚。"""

from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.schemas.knowledge import (
    REVIEW_LOG_GENESIS,
    compute_review_entry_hash,
    validate_status_transition,
)

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "knowledge"

HEADERS = {
    "cult_seed.csv": [
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
    ],
    "movie_criterion_evidence.csv": [
        "seed_id",
        "criterion_code",
        "source_id",
        "evidence_summary",
        "locator",
        "verification_status",
        "human_status",
        "confirmed_by",
        "confirmed_at",
        "added_by",
        "added_at",
    ],
    "movie_cult_tag_candidates.csv": [
        "seed_id",
        "tag_id",
        "evidence",
        "source_ids",
        "proposed_by",
        "proposed_at",
        "human_status",
        "confirmed_by",
        "confirmed_at",
    ],
    "movie_cult_tags.csv": [
        "seed_id",
        "tag_id",
        "origin",
        "confidence",
        "evidence",
        "source_ids",
        "rule_id",
        "annotator",
        "reviewed",
        "updated_at",
    ],
    "review_log.csv": [
        "timestamp",
        "seed_id",
        "field",
        "old_value",
        "new_value",
        "actor",
        "reason",
        "prev_hash",
        "entry_hash",
    ],
}

BACKFILL_ACTOR = "system-backfill"
BACKFILL_REASON = (
    "补录 3.2A 已发生的 draft→pending 变更；原始操作时间与操作人未知，按补录时刻记录"
)
FORBIDDEN_REVIEWERS = {"ai", "system", "system-backfill", "ai-draft"}
LOCK_FILENAME = ".review.lock"

# 只读 API 需要读取的完整知识库文件集合。
READ_FILES = (
    "cult_seed.csv",
    "cult_sources.csv",
    "cult_criteria.csv",
    "movie_criterion_evidence.csv",
    "cult_tags.csv",
    "movie_cult_tags.csv",
    "movie_cult_tag_candidates.csv",
    "review_log.csv",
)
TXN_DIRNAME = ".review_txn"
MANIFEST_NAME = "manifest.json"
COMMITTED_NAME = "committed"
RESTORED_NAME = "restored"
LOCK_TIMEOUT_SECONDS = 30.0


class ReviewError(RuntimeError):
    """审核提交被拒绝，知识库未被修改。"""


class WriteFailure(RuntimeError):
    """写入阶段故障；由事务负责回滚。"""


class _FileLock:
    """跨进程独占锁：同一时刻只允许一个审核写入者。

    Windows 使用 msvcrt 字节锁，其他平台使用 fcntl.flock。
    锁文件常驻 data 目录，进程退出时由操作系统自动释放。
    """

    def __init__(self, directory: Path, timeout: float = LOCK_TIMEOUT_SECONDS) -> None:
        self.path = directory / LOCK_FILENAME
        self.timeout = timeout
        self._handle = None

    def __enter__(self) -> "_FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self._acquire(handle)
            except OSError:
                if time.monotonic() >= deadline:
                    handle.close()
                    raise ReviewError(
                        f"获取审核锁超时（{self.timeout:.0f} 秒），"
                        "可能有其他审核进程正在写入"
                    ) from None
                time.sleep(0.05)
                continue
            self._handle = handle
            return self

    @staticmethod
    def _acquire(handle) -> None:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _release(handle) -> None:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def __exit__(self, *exc_info) -> None:
        if self._handle is None:
            return
        try:
            self._release(self._handle)
        finally:
            self._handle.close()
            self._handle = None


def _now() -> datetime:
    return datetime.now().astimezone()


def _iso(value: datetime) -> str:
    return value.isoformat()


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [
            {key: (value or "").strip() for key, value in row.items() if key is not None}
            for row in csv.DictReader(handle)
        ]


def read_snapshot(directory: Path | None = None) -> dict[str, list[dict[str, str]]]:
    """在审核锁保护下读取全部知识库 CSV（只读）。

    写入者持有同一把锁；若存在未完成事务，拒绝读取而不是自动恢复，
    避免只读接口触发写入或返回跨文件不一致的数据。
    """
    target = Path(directory) if directory is not None else DATA_DIR
    with _FileLock(target):
        if (target / TXN_DIRNAME).exists():
            raise ReviewError(
                "知识库存在未完成事务，请先运行 review_knowledge.py recover"
            )
        return {name: _read_rows(target / name) for name in READ_FILES}


def _write_rows(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=header)
            writer.writeheader()
            for row in rows:
                writer.writerow({column: row.get(column, "") for column in header})
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        _fsync_directory(path.parent)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _fsync_directory(directory: Path) -> None:
    """同步目录项，使文件的创建/替换/删除在 POSIX 上更可能持久化。

    Windows 的 Python 标准库无法对目录句柄执行 fsync；NTFS 依赖其自身
    元数据日志，因此这里明确跳过，不宣称获得与 POSIX 同等的持久性。
    """
    if os.name == "nt":
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write_bytes_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".bak")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        _fsync_directory(path.parent)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _write_text_atomic(path: Path, content: str) -> None:
    _write_bytes_atomic(path, content.encode("utf-8"))


def _read_manifest(txn: Path) -> dict:
    path = txn / MANIFEST_NAME
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReviewError(f"事务清单损坏，需人工检查：{path}（{exc}）") from exc


def _begin_transaction(directory: Path, filenames: list[str]) -> Path:
    """先落盘 preparing 清单，再写备份，最后切到 applying。

    这样“清单缺失”只可能来自清单创建前的崩溃，或清单被意外删除；
    写入数据文件必然发生在 phase=applying 之后。
    """
    txn = directory / TXN_DIRNAME
    if txn.exists():
        raise ReviewError("检测到未完成的提交事务，请先执行恢复")
    txn.mkdir(parents=True)
    files: list[dict[str, Any]] = []
    for name in filenames:
        files.append({"name": name, "existed": (directory / name).exists()})
    manifest = {
        "version": 2,
        "phase": "preparing",
        "created_at": _iso(_now()),
        "files": files,
    }
    _write_text_atomic(
        txn / MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2)
    )

    backup_dir = txn / "backup"
    backup_dir.mkdir()
    for entry in files:
        if entry["existed"]:
            _write_bytes_atomic(
                backup_dir / entry["name"],
                (directory / entry["name"]).read_bytes(),
            )

    manifest["phase"] = "applying"
    _write_text_atomic(
        txn / MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2)
    )
    return txn


def _verify_backups(txn: Path, manifest: dict) -> None:
    """恢复前一次性确认全部备份存在，避免恢复一半才发现缺失。"""
    missing = [
        entry["name"]
        for entry in manifest.get("files", [])
        if entry.get("existed") and not (txn / "backup" / entry["name"]).exists()
    ]
    if missing:
        raise ReviewError(
            f"恢复失败：事务备份缺失 {missing}，拒绝自动恢复，请人工检查"
        )


def _restore_from_txn(directory: Path, txn: Path) -> None:
    """按事务清单恢复原始字节；不读取后删除备份，可安全重复执行。"""
    manifest = _read_manifest(txn)
    for entry in manifest.get("files", []):
        name = entry["name"]
        target = directory / name
        backup = txn / "backup" / name
        if entry.get("existed"):
            if not backup.exists():
                raise ReviewError(f"恢复失败：事务备份缺失 {name}")
            _write_bytes_atomic(target, backup.read_bytes())
        else:
            target.unlink(missing_ok=True)
            _fsync_directory(target.parent)


def _txn_payload_files(txn: Path) -> list[str]:
    """事务目录中除清单及其临时文件之外的残留文件。"""
    payload: list[str] = []
    for path in txn.rglob("*"):
        if path.is_file() and not path.name.startswith(MANIFEST_NAME):
            payload.append(str(path.relative_to(txn)))
    return payload


def _remove_backups(txn: Path) -> None:
    shutil.rmtree(txn / "backup", ignore_errors=True)
    _fsync_directory(txn)


def _finish_committed_txn(txn: Path) -> None:
    """已提交：保留新数据，最后才删 committed 标记。"""
    _remove_backups(txn)
    (txn / MANIFEST_NAME).unlink(missing_ok=True)
    _fsync_directory(txn)
    (txn / COMMITTED_NAME).unlink(missing_ok=True)
    _fsync_directory(txn)
    shutil.rmtree(txn, ignore_errors=True)
    _fsync_directory(txn.parent)


def _finish_restored_txn(txn: Path) -> None:
    """已恢复：数据已是原始状态，最后才删 restored 标记。"""
    _remove_backups(txn)
    (txn / MANIFEST_NAME).unlink(missing_ok=True)
    _fsync_directory(txn)
    (txn / RESTORED_NAME).unlink(missing_ok=True)
    _fsync_directory(txn)
    shutil.rmtree(txn, ignore_errors=True)
    _fsync_directory(txn.parent)


def _finish_preparing_txn(txn: Path) -> None:
    """preparing 阶段尚未改写任何数据文件，可安全清理。"""
    _remove_backups(txn)
    (txn / MANIFEST_NAME).unlink(missing_ok=True)
    _fsync_directory(txn)
    shutil.rmtree(txn, ignore_errors=True)
    _fsync_directory(txn.parent)


def _finish_empty_txn(txn: Path) -> None:
    shutil.rmtree(txn, ignore_errors=True)
    _fsync_directory(txn.parent)


def _recover_locked(directory: Path) -> bool:
    """恢复未完成事务；返回是否执行了回滚。调用方必须已持有文件锁。"""
    txn = directory / TXN_DIRNAME
    if not txn.exists():
        return False
    if (txn / COMMITTED_NAME).exists():
        _finish_committed_txn(txn)
        return False
    if (txn / RESTORED_NAME).exists():
        _finish_restored_txn(txn)
        return False
    if not (txn / MANIFEST_NAME).exists():
        if _txn_payload_files(txn):
            raise ReviewError(
                "事务目录缺少清单但仍有备份/标记文件，无法证明处于哪个阶段；"
                "拒绝自动清理或恢复，请人工检查 "
                f"{txn}"
            )
        _finish_empty_txn(txn)
        return False
    manifest = _read_manifest(txn)
    if manifest.get("phase", "applying") == "preparing":
        _finish_preparing_txn(txn)
        return False
    _verify_backups(txn, manifest)
    _restore_from_txn(directory, txn)
    _write_text_atomic(txn / RESTORED_NAME, "restored\n")
    _finish_restored_txn(txn)
    return True



def recover_pending_transaction(data_dir: str | Path) -> bool:
    """可重复执行的崩溃恢复入口；返回是否回滚了未提交事务。"""
    directory = Path(data_dir)
    with _FileLock(directory):
        return _recover_locked(directory)


def _require_valid(directory: Path) -> None:
    from scripts.validate_knowledge import validate_knowledge

    report = validate_knowledge(directory)
    if not report.ok:
        details = "；".join(str(issue) for issue in report.errors[:5])
        raise ReviewError(f"提交后的知识库未通过校验：{details}")


def _validate_proposed(directory: Path, proposed: dict[str, list[dict[str, str]]]) -> None:
    """在临时副本中写入拟提交结果，先通过校验器再落盘。"""
    with tempfile.TemporaryDirectory(prefix="cultscope-review-") as temporary:
        staging = Path(temporary) / "knowledge"
        shutil.copytree(
            directory,
            staging,
            ignore=shutil.ignore_patterns(LOCK_FILENAME, TXN_DIRNAME),
        )
        for filename, rows in proposed.items():
            _write_rows(staging / filename, HEADERS[filename], rows)
        _require_valid(staging)


def _apply_transaction(
    directory: Path,
    proposed: dict[str, list[dict[str, str]]],
    fail_after: int | None = None,
) -> None:
    """双阶段提交：先落盘清单与备份，再改写；异常回滚，进程崩溃由恢复流程接管。"""
    _require_valid(directory)
    txn = _begin_transaction(directory, list(proposed))
    try:
        for index, (filename, rows) in enumerate(proposed.items(), start=1):
            _write_rows(directory / filename, HEADERS[filename], rows)
            if fail_after is not None and index >= fail_after:
                raise WriteFailure(f"注入写入失败：第 {index} 个文件（{filename}）")
        _require_valid(directory)
    except Exception:
        _restore_from_txn(directory, txn)
        _write_text_atomic(txn / RESTORED_NAME, "restored\n")
        _finish_restored_txn(txn)
        raise
    _write_text_atomic(txn / COMMITTED_NAME, "committed\n")
    _finish_committed_txn(txn)


def _next_prev_hash(log_rows: list[dict[str, str]]) -> str:
    return log_rows[-1]["entry_hash"] if log_rows else REVIEW_LOG_GENESIS


def _make_log_rows(
    entries: list[dict[str, str]],
    log_rows: list[dict[str, str]],
    base_time: datetime,
) -> list[dict[str, str]]:
    prev_hash = _next_prev_hash(log_rows)
    new_rows: list[dict[str, str]] = []
    for index, entry in enumerate(entries, start=1):
        timestamp = _iso(base_time + timedelta(microseconds=index))
        payload = {
            "timestamp": timestamp,
            "seed_id": entry["seed_id"],
            "field": entry["field"],
            "old_value": entry["old_value"],
            "new_value": entry["new_value"],
            "actor": entry["actor"],
            "reason": entry["reason"],
        }
        entry_hash = compute_review_entry_hash(prev_hash=prev_hash, **payload)
        new_rows.append({**payload, "prev_hash": prev_hash, "entry_hash": entry_hash})
        prev_hash = entry_hash
    return new_rows


def load_packet(data_dir: str | Path, seed_id: str) -> dict[str, Any]:
    """组装人工审核展示所需的数据包；读取前先恢复未完成事务。"""
    directory = Path(data_dir)
    with _FileLock(directory):
        _recover_locked(directory)
        return _load_packet_locked(directory, seed_id)


def _load_packet_locked(directory: Path, seed_id: str) -> dict[str, Any]:
    seeds = {row["seed_id"]: row for row in _read_rows(directory / "cult_seed.csv")}
    seed = seeds.get(seed_id)
    if seed is None:
        raise ReviewError(f"电影不存在：{seed_id}")

    criteria = {row["criterion_code"]: row for row in _read_rows(directory / "cult_criteria.csv")}
    sources = {row["source_id"]: row for row in _read_rows(directory / "cult_sources.csv")}
    tags = {row["tag_id"]: row for row in _read_rows(directory / "cult_tags.csv")}
    evidence = [
        row for row in _read_rows(directory / "movie_criterion_evidence.csv")
        if row["seed_id"] == seed_id
    ]
    candidates = [
        row for row in _read_rows(directory / "movie_cult_tag_candidates.csv")
        if row["seed_id"] == seed_id
    ]
    for row in evidence:
        row["source_tier"] = sources.get(row["source_id"], {}).get("reliability_tier", "?")
        row["source_title"] = sources.get(row["source_id"], {}).get("title", "")
        row["source_url"] = sources.get(row["source_id"], {}).get("url", "")
    for row in candidates:
        row["tag_definition"] = tags.get(row["tag_id"], {}).get("definition", "")
        row["tag_inclusion"] = tags.get(row["tag_id"], {}).get("inclusion_criteria", "")
        row["tag_exclusion"] = tags.get(row["tag_id"], {}).get("exclusion_criteria", "")
    return {
        "seed": seed,
        "criteria": [
            criteria[code]
            for code in [part for part in seed["cult_criteria_codes"].split("|") if part]
            if code in criteria
        ],
        "evidence": evidence,
        "tag_candidates": candidates,
    }


def _check_reviewer(reviewer: str) -> str:
    name = reviewer.strip()
    if not name:
        raise ReviewError("必须填写真实 reviewer")
    if name.lower() in FORBIDDEN_REVIEWERS or "ai-draft" in name.lower():
        raise ReviewError("reviewer 必须是真实人工审核者，不能使用 AI/系统占位名")
    return name


def _evidence_index(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    index: dict[tuple[str, str], dict[str, str]] = {}
    duplicates: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["criterion_code"], row["source_id"])
        if key in index:
            duplicates.add(key)
        index[key] = row
    if duplicates:
        raise ReviewError(f"证据存在重复行，无法确定审核对象：{sorted(duplicates)}")
    return index


def _candidate_index(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    duplicates: set[str] = set()
    for row in rows:
        tag_id = row["tag_id"]
        if tag_id in index:
            duplicates.add(tag_id)
        index[tag_id] = row
    if duplicates:
        raise ReviewError(f"候选标签存在重复行，无法确定审核对象：{sorted(duplicates)}")
    return index


def submit_review(
    data_dir: str | Path,
    seed_id: str,
    *,
    reviewer: str,
    decision: str,
    reason: str,
    evidence_decisions: dict[tuple[str, str], str] | None = None,
    tag_decisions: dict[str, str] | None = None,
    allow_override: bool = False,
    fail_after: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """提交一次人工审核。

    - decision=pending 表示保存进度，不填写 reviewer/reviewed_at；
    - approved 必须满足 T1/T2、verified、human confirmed 与两条标准；
    - 默认拒绝覆盖已有 confirmed/rejected 人工结论；
    - 持跨进程锁写入，并先恢复未完成事务；
    - 任何校验或写入失败都不会留下部分修改。
    """
    directory = Path(data_dir)
    reviewer = _check_reviewer(reviewer)
    reason = reason.strip()
    if not reason:
        raise ReviewError("必须填写审核理由")
    if decision not in {"pending", "approved", "rejected", "needs_fix"}:
        raise ReviewError(f"非法审核决定：{decision}")

    with _FileLock(directory):
        _recover_locked(directory)
        return _submit_review_locked(
            directory,
            seed_id,
            reviewer=reviewer,
            decision=decision,
            reason=reason,
            evidence_decisions=evidence_decisions,
            tag_decisions=tag_decisions,
            allow_override=allow_override,
            fail_after=fail_after,
            now=now,
        )


def _submit_review_locked(
    directory: Path,
    seed_id: str,
    *,
    reviewer: str,
    decision: str,
    reason: str,
    evidence_decisions: dict[tuple[str, str], str] | None,
    tag_decisions: dict[str, str] | None,
    allow_override: bool,
    fail_after: int | None,
    now: datetime | None,
) -> dict[str, Any]:
    evidence_rows = _read_rows(directory / "movie_criterion_evidence.csv")
    candidate_rows = _read_rows(directory / "movie_cult_tag_candidates.csv")
    movie_tag_rows = _read_rows(directory / "movie_cult_tags.csv")
    log_rows = _read_rows(directory / "review_log.csv")
    seed_rows = _read_rows(directory / "cult_seed.csv")
    sources = {row["source_id"]: row for row in _read_rows(directory / "cult_sources.csv")}

    seed = next((row for row in seed_rows if row["seed_id"] == seed_id), None)
    if seed is None:
        raise ReviewError(f"电影不存在：{seed_id}")

    base_time = now or _now()
    stamp = _iso(base_time)
    seed_evidence = [row for row in evidence_rows if row["seed_id"] == seed_id]
    evidence_index = _evidence_index(seed_evidence)
    seed_candidates = [row for row in candidate_rows if row["seed_id"] == seed_id]
    candidate_index = _candidate_index(seed_candidates)
    manual_pairs = {
        (row["seed_id"], row["tag_id"])
        for row in movie_tag_rows
        if row["origin"] == "manual"
    }

    log_entries: list[dict[str, str]] = []
    changed = 0

    for key, value in (evidence_decisions or {}).items():
        row = evidence_index.get(key)
        if row is None:
            raise ReviewError(f"证据不存在：{key}")
        if value not in {"confirmed", "rejected"}:
            raise ReviewError(f"非法证据人工状态：{value}")
        old = row["human_status"] or "pending"
        if old == value:
            raise ReviewError(f"重复提交：证据 {key[0]}/{key[1]} 已经是 {value}")
        if old in {"confirmed", "rejected"} and not allow_override:
            raise ReviewError(
                f"证据 {key[0]}/{key[1]} 已有人工结论 {old}，拒绝覆盖；"
                "如确需修改请显式允许覆盖"
            )
        row["human_status"] = value
        row["confirmed_by"] = reviewer
        row["confirmed_at"] = stamp
        changed += 1
        log_entries.append(
            {
                "seed_id": seed_id,
                "field": f"evidence:{key[0]}:{key[1]}:human_status",
                "old_value": old,
                "new_value": value,
                "actor": reviewer,
                "reason": reason,
            }
        )

    for tag_id, value in (tag_decisions or {}).items():
        row = candidate_index.get(tag_id)
        if row is None:
            raise ReviewError(f"候选标签不存在：{tag_id}")
        if value not in {"confirmed", "rejected"}:
            raise ReviewError(f"非法候选标签人工状态：{value}")
        old = row["human_status"] or "pending"
        if old == value:
            raise ReviewError(f"重复提交：候选标签 {tag_id} 已经是 {value}")
        if old in {"confirmed", "rejected"} and not allow_override:
            raise ReviewError(
                f"候选标签 {tag_id} 已有人工结论 {old}，拒绝覆盖；"
                "如确需修改请显式允许覆盖"
            )
        pair = (seed_id, tag_id)
        if value == "confirmed" and pair in manual_pairs:
            raise ReviewError(f"正式人工标注已存在：{seed_id} / {tag_id}")
        if value == "rejected" and pair in manual_pairs:
            raise ReviewError(f"正式人工标注已存在，不能驳回：{seed_id} / {tag_id}")
        row["human_status"] = value
        row["confirmed_by"] = reviewer
        row["confirmed_at"] = stamp
        changed += 1
        log_entries.append(
            {
                "seed_id": seed_id,
                "field": f"tag_candidate:{tag_id}:human_status",
                "old_value": old,
                "new_value": value,
                "actor": reviewer,
                "reason": reason,
            }
        )
        if value == "confirmed":
            movie_tag_rows.append(
                {
                    "seed_id": seed_id,
                    "tag_id": tag_id,
                    "origin": "manual",
                    "confidence": "",
                    "evidence": row["evidence"],
                    "source_ids": row["source_ids"],
                    "rule_id": "",
                    "annotator": reviewer,
                    "reviewed": "true",
                    "updated_at": stamp,
                }
            )
            log_entries.append(
                {
                    "seed_id": seed_id,
                    "field": f"tag:{tag_id}:add",
                    "old_value": "",
                    "new_value": "manual",
                    "actor": reviewer,
                    "reason": reason,
                }
            )

    current_status = seed["review_status"]
    status_changed = decision != current_status
    if not status_changed and decision != "pending":
        raise ReviewError(f"重复提交：review_status 已经是 {decision}")
    if status_changed:
        try:
            validate_status_transition(current_status, decision)
        except ValueError as exc:
            raise ReviewError(str(exc)) from exc
        seed["review_status"] = decision
        changed += 1
        log_entries.append(
            {
                "seed_id": seed_id,
                "field": "review_status",
                "old_value": current_status,
                "new_value": decision,
                "actor": reviewer,
                "reason": reason,
            }
        )
    if not changed:
        raise ReviewError("重复提交：本次没有需要保存的变更")

    if decision in {"approved", "rejected", "needs_fix"}:
        if seed["reviewer"] != reviewer:
            log_entries.append(
                {
                    "seed_id": seed_id,
                    "field": "reviewer",
                    "old_value": seed["reviewer"],
                    "new_value": reviewer,
                    "actor": reviewer,
                    "reason": reason,
                }
            )
        seed["reviewer"] = reviewer
        seed["reviewed_at"] = stamp
    elif decision == "pending":
        if seed["reviewer"] or seed["reviewed_at"]:
            log_entries.append(
                {
                    "seed_id": seed_id,
                    "field": "reviewer",
                    "old_value": seed["reviewer"],
                    "new_value": "",
                    "actor": reviewer,
                    "reason": "退回待审状态，清除上一轮审核人",
                }
            )
        seed["reviewer"] = ""
        seed["reviewed_at"] = ""

    if decision == "approved":
        strong_sources = [
            source_id
            for source_id in [part for part in seed["candidate_source_ids"].split("|") if part]
            if sources.get(source_id, {}).get("reliability_tier") in {"T1", "T2"}
        ]
        if not strong_sources:
            raise ReviewError("approved 至少需要一个有效的 T1/T2 候选来源")
        declared = {part for part in seed["cult_criteria_codes"].split("|") if part}
        supported = {
            row["criterion_code"]
            for row in seed_evidence
            if row["criterion_code"] in declared
            and row["verification_status"] == "verified"
            and row["human_status"] == "confirmed"
            and sources.get(row["source_id"], {}).get("reliability_tier") in {"T1", "T2"}
        }
        if len(supported) < 2:
            raise ReviewError(
                "approved 至少需要两条经人工确认、经正文核实且由 T1/T2 来源支持的 Cult 标准；"
                f"当前 {len(supported)} 条"
            )
        if not seed["reviewer"] or not seed["reviewed_at"]:
            raise ReviewError("approved 必须填写真实 reviewer 与 reviewed_at")

    proposed = {
        "cult_seed.csv": seed_rows,
        "movie_criterion_evidence.csv": evidence_rows,
        "movie_cult_tag_candidates.csv": candidate_rows,
        "movie_cult_tags.csv": movie_tag_rows,
        "review_log.csv": log_rows
        + _make_log_rows(log_entries, log_rows, base_time),
    }
    _validate_proposed(directory, proposed)
    try:
        _apply_transaction(directory, proposed, fail_after=fail_after)
    except WriteFailure as exc:
        raise ReviewError(f"写入失败，已回滚：{exc}") from exc
    return {
        "seed_id": seed_id,
        "review_status": seed["review_status"],
        "reviewer": seed["reviewer"],
        "reviewed_at": seed["reviewed_at"],
        "log_entries": len(log_entries),
        "evidence_confirmed": sum(
            1 for row in seed_evidence if row["human_status"] == "confirmed"
        ),
        "tags_confirmed": sum(
            1 for row in seed_candidates if row["human_status"] == "confirmed"
        ),
    }


def backfill_draft_to_pending(
    data_dir: str | Path,
    *,
    now: datetime | None = None,
    fail_after: int | None = None,
) -> int:
    """补录已发生的 draft→pending；持跨进程锁，幂等，不伪造原始时间与操作人。"""
    directory = Path(data_dir)
    with _FileLock(directory):
        _recover_locked(directory)
        return _backfill_locked(directory, now=now, fail_after=fail_after)


def _backfill_locked(
    directory: Path,
    *,
    now: datetime | None,
    fail_after: int | None,
) -> int:
    seed_rows = _read_rows(directory / "cult_seed.csv")
    log_rows = _read_rows(directory / "review_log.csv")

    logged = {
        row["seed_id"]
        for row in log_rows
        if row["field"] == "review_status"
        and row["old_value"] == "draft"
        and row["new_value"] == "pending"
    }
    targets = [
        row["seed_id"]
        for row in seed_rows
        if row["review_status"] == "pending" and row["seed_id"] not in logged
    ]
    if not targets:
        return 0

    base_time = now or _now()
    entries = [
        {
            "seed_id": seed_id,
            "field": "review_status",
            "old_value": "draft",
            "new_value": "pending",
            "actor": BACKFILL_ACTOR,
            "reason": BACKFILL_REASON,
        }
        for seed_id in sorted(targets)
    ]
    proposed = {
        "review_log.csv": log_rows + _make_log_rows(entries, log_rows, base_time),
    }
    _validate_proposed(directory, proposed)
    try:
        _apply_transaction(directory, proposed, fail_after=fail_after)
    except WriteFailure as exc:
        raise ReviewError(f"补录写入失败，已回滚：{exc}") from exc
    return len(targets)
