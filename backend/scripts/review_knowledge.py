"""CULTScope 人工审核 CLI。

用法：
    python scripts/review_knowledge.py show CS-0001
    python scripts/review_knowledge.py review CS-0001
    python scripts/review_knowledge.py backfill

本工具不会自动批准任何电影；所有结论都需要审核人逐条输入确认。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.review_store import (  # noqa: E402
    DATA_DIR,
    ReviewError,
    backfill_draft_to_pending,
    load_packet,
    recover_pending_transaction,
    submit_review,
)

# CLI 输入键 → submit_review() 接受的审核决定枚举。
_DECISION_MAP = {
    "p": "pending",
    "a": "approved",
    "r": "rejected",
    "n": "needs_fix",
    "q": "quit",
}


def _print_packet(packet: dict) -> None:
    seed = packet["seed"]
    print("=" * 78)
    print(f"{seed['seed_id']}  {seed['title']}（{seed['original_title']}，{seed['year']}）")
    print(f"TMDb {seed['tmdb_id']} / IMDb {seed['imdb_id']}")
    print(f"当前状态：{seed['review_status']}   reviewer：{seed['reviewer'] or '（空）'}")
    print(f"候选来源：{seed['candidate_source_ids'] or '（空）'}")
    print(f"候选标准：{seed['cult_criteria_codes'] or '（空）'}")

    print("\n--- Cult 认定标准 ---")
    for criterion in packet["criteria"]:
        print(f"[{criterion['criterion_code']}] {criterion['name_zh']}")
        print(f"  定义：{criterion['definition']}")
        print(f"  纳入要求：{criterion['evidence_requirement']}")
        print(f"  排除条件：{criterion['exclusion_note']}")

    print("\n--- 证据 ---")
    if not packet["evidence"]:
        print("（无）")
    for row in packet["evidence"]:
        print(
            f"[{row['criterion_code']}] {row['source_id']} / {row['source_tier']}"
            f"  {row['source_title']}"
        )
        print(f"  摘要：{row['evidence_summary']}")
        print(f"  定位：{row['locator']}")
        print(f"  正文核对：{row['verification_status']}   人工状态：{row['human_status']}")
        print(f"  链接：{row['source_url']}")

    print("\n--- 候选文化标签 ---")
    if not packet["tag_candidates"]:
        print("（无）")
    for row in packet["tag_candidates"]:
        print(f"[{row['tag_id']}] 当前人工状态：{row['human_status']}")
        print(f"  定义：{row['tag_definition']}")
        print(f"  纳入条件：{row['tag_inclusion']}")
        print(f"  排除条件：{row['tag_exclusion']}")
        print(f"  证据：{row['evidence']}（来源 {row['source_ids']}）")
    print("=" * 78)


def _ask_choice(prompt: str, choices: dict[str, str]) -> str:
    while True:
        answer = input(prompt).strip().lower()
        if answer in choices:
            return answer
        print(f"请输入 {', '.join(sorted(choices))} 之一。")


def _confirm_packet(packet: dict) -> tuple[dict, dict, str]:
    evidence_decisions: dict[tuple[str, str], str] = {}
    for row in packet["evidence"]:
        answer = _ask_choice(
            f"证据 {row['criterion_code']} / {row['source_id']}："
            "[y] 确认支持 / [n] 驳回 / [s] 跳过：",
            {"y": "confirmed", "n": "rejected", "s": "skip"},
        )
        if answer != "s":
            evidence_decisions[(row["criterion_code"], row["source_id"])] = {
                "y": "confirmed",
                "n": "rejected",
            }[answer]

    tag_decisions: dict[str, str] = {}
    for row in packet["tag_candidates"]:
        answer = _ask_choice(
            f"候选标签 {row['tag_id']}：[y] 确认入库 / [n] 驳回 / [s] 跳过：",
            {"y": "confirmed", "n": "rejected", "s": "skip"},
        )
        if answer != "s":
            tag_decisions[row["tag_id"]] = {"y": "confirmed", "n": "rejected"}[answer]

    decision = _DECISION_MAP[
        _ask_choice(
            "本次审核决定：[p] 保持 pending 保存进度 / [a] approved / "
            "[r] rejected / [n] needs_fix / [q] 取消：",
            _DECISION_MAP,
        )
    ]
    return evidence_decisions, tag_decisions, decision


def command_show(seed_id: str) -> int:
    _print_packet(load_packet(DATA_DIR, seed_id))
    return 0


def command_review(seed_id: str) -> int:
    packet = load_packet(DATA_DIR, seed_id)
    _print_packet(packet)

    reviewer = input("请输入真实审核人姓名（不可使用 AI/系统占位名）：").strip()
    evidence_decisions, tag_decisions, decision = _confirm_packet(packet)
    if decision == "quit":
        print("已取消，未写入任何内容。")
        return 1

    reason = input("请输入审核理由：").strip()
    print("\n提交预览：")
    print(f"  电影：{seed_id}")
    print(f"  决定：{decision}")
    print(f"  确认证据：{len(evidence_decisions)} 条；确认/驳回标签：{len(tag_decisions)} 个")
    print(f"  审核人：{reviewer or '（空）'}")
    print("注意：approved 需要至少两条经人工确认、正文核实且由 T1/T2 来源支持的标准。")
    if input("确认写入？请输入 CONFIRM：" ).strip() != "CONFIRM":
        print("未确认，已取消。")
        return 1

    try:
        result = submit_review(
            DATA_DIR,
            seed_id,
            reviewer=reviewer,
            decision=decision,
            reason=reason,
            evidence_decisions=evidence_decisions,
            tag_decisions=tag_decisions,
        )
    except ReviewError as exc:
        print(f"提交被拒绝：{exc}")
        return 1

    print("\n提交成功：")
    print(f"  review_status：{result['review_status']}")
    print(f"  reviewer：{result['reviewer'] or '（空）'}")
    print(f"  reviewed_at：{result['reviewed_at'] or '（空）'}")
    print(f"  写入日志：{result['log_entries']} 条")
    return 0


def command_backfill() -> int:
    try:
        count = backfill_draft_to_pending(DATA_DIR)
    except ReviewError as exc:
        print(f"补录失败：{exc}")
        return 1
    print(f"补录完成：新增 {count} 条 draft→pending 日志（无历史记录时不重复写入）")
    return 0


def command_recover() -> int:
    try:
        recovered = recover_pending_transaction(DATA_DIR)
    except ReviewError as exc:
        print(f"恢复失败：{exc}")
        return 1
    if recovered:
        print("已按事务清单回滚未完成的提交。")
    else:
        print("没有需要恢复的未完成事务。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CULTScope 人工审核工具")
    subparsers = parser.add_subparsers(dest="command", required=True)
    show_parser = subparsers.add_parser("show", help="展示审核数据包")
    show_parser.add_argument("seed_id")
    review_parser = subparsers.add_parser("review", help="交互式人工审核")
    review_parser.add_argument("seed_id")
    subparsers.add_parser("backfill", help="补录已发生的 draft→pending")
    subparsers.add_parser("recover", help="恢复未完成的提交事务")

    args = parser.parse_args(argv)
    try:
        if args.command == "show":
            return command_show(args.seed_id)
        if args.command == "review":
            return command_review(args.seed_id)
        if args.command == "recover":
            return command_recover()
        return command_backfill()
    except (EOFError, KeyboardInterrupt):
        print("\n已中止，未写入任何内容。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
