#!/usr/bin/env python3
"""Freeze pre-earnings cards, close them after results, and notify real changes.

Daily countdowns are deliberately excluded from the snapshot fingerprint.  A
new history entry is created only when a phase boundary, official guidance,
reported quarter, KPI state, or thesis state changes.  The first run creates a
baseline and never backfills a fictional pre-earnings card.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
MAX_HISTORY = 48
MAX_CYCLES = 112
PHASE_LABELS = {
    "preparation_due": "財報前 7 天準備期",
    "post_review_due": "財報後 14 天核對期",
    "upcoming": "30 天內將公布",
    "scheduled_later": "已知日期，尚未進入 30 天",
    "date_unavailable": "財報日期待公告",
}


def load_json(path: Path, default: Any = None) -> Any:
    return json.loads(path.read_text()) if path.is_file() else default


def stable_hash(value: Any, length: int = 16) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:length]


def checked_at_now() -> str:
    return datetime.now(ZoneInfo("Asia/Taipei")).isoformat(timespec="seconds")


def normalize_checked_at(value: str | None) -> str:
    if not value:
        return checked_at_now()
    if len(value) == 10:
        return f"{value}T00:00:00+08:00"
    return value


def compact_guidance(guidance: dict[str, Any]) -> dict[str, Any]:
    fields = ("period", "metric", "low", "high", "unit", "source_date", "source_url")
    return {
        "status": guidance.get("status"),
        "note": guidance.get("note"),
        "rows": [{key: row.get(key) for key in fields} for row in guidance.get("rows", [])],
    }


def compact_thesis(thesis: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": thesis.get("status"),
        "label": thesis.get("label"),
        "items": [{
            "id": item.get("id"), "title": item.get("title"),
            "status": item.get("status"), "label": item.get("label"),
            "evidence": item.get("evidence"), "invalidation": item.get("invalidation"),
        } for item in thesis.get("items", [])],
    }


def compact_card(row: dict[str, Any]) -> dict[str, Any]:
    earnings = row.get("next_earnings") or {}
    pre = row.get("pre_event") or {}
    post = row.get("post_event") or {}
    latest = post.get("latest_result") or {}
    completed = (post.get("completed_guidance") or {}).get("record")
    return {
        "ticker": row.get("ticker"),
        "position": row.get("position"),
        "phase": row.get("phase"),
        "phase_label": row.get("phase_label") or PHASE_LABELS.get(row.get("phase")),
        "next_earnings": {
            "date": earnings.get("date"), "confidence": earnings.get("confidence"),
            "source_label": earnings.get("source_label"), "source_url": earnings.get("source_url"),
            "source_status": earnings.get("source_status"),
        } if earnings else None,
        "guidance": compact_guidance(pre.get("guidance") or {}),
        "checkpoints": [{key: item.get(key) for key in ("topic", "question", "why")}
                        for item in pre.get("checkpoints", [])],
        "latest_result": {
            "period_end": latest.get("period_end"), "filing_date": latest.get("filing_date"),
            "form": latest.get("form"), "accession": latest.get("accession"),
            "source_url": latest.get("source_url"), "currency": latest.get("currency"),
        } if latest else None,
        "kpis": [{key: item.get(key) for key in
                  ("metric", "label", "display", "value", "qoq", "yoy", "state", "interpretation")}
                 for item in post.get("kpis", [])],
        "completed_guidance": copy.deepcopy(completed),
        "thesis": compact_thesis(post.get("thesis") or pre.get("thesis") or {}),
    }


def build_snapshot(cards: dict[str, Any], checked_at: str) -> dict[str, Any]:
    companies = {row["ticker"]: compact_card(row) for row in cards.get("companies", [])}
    core = {"source_date": cards.get("generated_at"), "companies": companies}
    return {
        "snapshot_id": stable_hash(companies),
        "captured_at": checked_at,
        **core,
    }


def result_key(card: dict[str, Any]) -> tuple[Any, ...] | None:
    row = card.get("latest_result")
    return (row.get("period_end"), row.get("accession"), row.get("filing_date")) if row else None


def guidance_key(card: dict[str, Any]) -> str:
    return stable_hash(card.get("guidance") or {})


def completed_key(card: dict[str, Any]) -> tuple[Any, ...] | None:
    row = card.get("completed_guidance")
    return (row.get("period"), row.get("metric"), row.get("actual"), row.get("outcome")) if row else None


def compare_company(current: dict[str, Any], previous: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if not previous:
        return {"status": "baseline", "notify": False, "label": "首次建立比較基準", "reasons": []}, None

    reasons: list[str] = []
    kinds: list[str] = []
    direction = "neutral"
    critical = False
    previous_phase, current_phase = previous.get("phase"), current.get("phase")
    if current_phase == "preparation_due" and previous_phase != "preparation_due":
        kinds.append("preparation")
        reasons.append(f"進入財報前 7 天準備期；預定日 {(current.get('next_earnings') or {}).get('date') or '待公告'}")
    if result_key(current) != result_key(previous) and result_key(current):
        kinds.append("result")
        latest = current["latest_result"]
        reasons.append(f"取得新季度 {latest.get('period_end') or '期末待確認'}（{latest.get('form') or '財報'}）")
    elif current_phase == "post_review_due" and previous_phase != "post_review_due":
        kinds.append("post_review")
        reasons.append("進入財報後 14 天核對期")

    current_earnings = current.get("next_earnings") or {}
    previous_earnings = previous.get("next_earnings") or {}
    if (current_earnings.get("date") != previous_earnings.get("date") and
            current_earnings.get("confidence") == "official"):
        kinds.append("schedule")
        reasons.append(f"財報日由 {previous_earnings.get('date') or '待公告'} 改為官方確認 {current_earnings.get('date')}")
    elif (current_earnings.get("confidence") == "official" and
          previous_earnings.get("confidence") != "official"):
        kinds.append("schedule")
        reasons.append(f"財報日 {current_earnings.get('date')} 已由公司正式確認")

    if guidance_key(current) != guidance_key(previous):
        kinds.append("guidance")
        before_count = len((previous.get("guidance") or {}).get("rows", []))
        after_count = len((current.get("guidance") or {}).get("rows", []))
        reasons.append(f"待驗證官方指引更新（{before_count} → {after_count} 項）")

    prior_kpis = {row.get("metric"): row for row in previous.get("kpis", [])}
    for row in current.get("kpis", []):
        prior = prior_kpis.get(row.get("metric"))
        if not prior or prior.get("state") == row.get("state"):
            continue
        kinds.append("financial")
        label = row.get("label") or row.get("metric")
        reasons.append(f"{label}：{prior.get('interpretation') or prior.get('state')} → {row.get('interpretation') or row.get('state')}")
        if row.get("state") == "risk" and prior.get("state") != "risk":
            direction, critical = "risk", True
        elif prior.get("state") == "risk" or row.get("state") == "improved":
            if direction != "risk":
                direction = "improvement"

    old_thesis, new_thesis = previous.get("thesis") or {}, current.get("thesis") or {}
    if old_thesis.get("status") != new_thesis.get("status"):
        kinds.append("conclusion")
        reasons.append(f"客觀結論：{old_thesis.get('label') or '資料不足'} → {new_thesis.get('label') or '資料不足'}")
        if new_thesis.get("status") in {"partial-invalidated", "major-invalidated"}:
            direction, critical = "risk", True
        elif old_thesis.get("status") in {"partial-invalidated", "major-invalidated"}:
            if direction != "risk":
                direction = "improvement"
    prior_items = {item.get("id"): item for item in old_thesis.get("items", [])}
    for item in new_thesis.get("items", []):
        prior = prior_items.get(item.get("id"))
        if not prior or prior.get("status") == item.get("status"):
            continue
        kinds.append("thesis")
        reasons.append(f"論點「{item.get('title')}」：{prior.get('label')} → {item.get('label')}")
        if item.get("status") == "invalidated":
            direction, critical = "risk", True
        elif prior.get("status") == "invalidated" and direction != "risk":
            direction = "improvement"

    if completed_key(current) != completed_key(previous) and completed_key(current):
        kinds.append("guidance_result")
        completed = current["completed_guidance"]
        reasons.append(f"新增指引驗證：{completed.get('period')} {completed.get('metric')}為「{completed.get('outcome_label')}」")
        if completed.get("outcome") == "below":
            direction, critical = "risk", True
        elif completed.get("outcome") == "above" and direction != "risk":
            direction = "improvement"

    kinds = list(dict.fromkeys(kinds))
    notify = bool(reasons)
    if not notify:
        comparison = {"status": "unchanged", "notify": False, "label": "沒有需通知的實質變化", "reasons": []}
        return comparison, None
    label = "新增風險" if direction == "risk" else "新增改善" if direction == "improvement" else "驗證狀態更新"
    comparison = {"status": "changed", "notify": True, "label": label, "direction": direction,
                  "kinds": kinds, "critical": critical, "reasons": reasons}
    notification = {"ticker": current["ticker"], **comparison}
    return comparison, notification


def cycle_differences(pre: dict[str, Any], post: dict[str, Any]) -> list[str]:
    _, notification = compare_company(post, pre)
    return (notification or {}).get("reasons", [])


def update_cycles(snapshot: dict[str, Any], existing_cycles: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    cycles = copy.deepcopy(existing_cycles)
    changed = False
    for ticker, card in snapshot["companies"].items():
        open_cycle = next((row for row in cycles if row.get("ticker") == ticker and row.get("status") == "waiting_result"), None)
        latest_key = result_key(card)
        if open_cycle and latest_key and latest_key != tuple(open_cycle["pre"].get("baseline_result_key") or (None, None, None)):
            post = {
                "captured_at": snapshot["captured_at"], "latest_result": copy.deepcopy(card.get("latest_result")),
                "kpis": copy.deepcopy(card.get("kpis", [])), "completed_guidance": copy.deepcopy(card.get("completed_guidance")),
                "thesis": copy.deepcopy(card.get("thesis")),
            }
            post_card = {**copy.deepcopy(card), **post}
            open_cycle.update({"status": "completed", "post": post,
                               "differences": cycle_differences(open_cycle["pre"]["card"], post_card)})
            changed = True
            open_cycle = None

        if card.get("phase") != "preparation_due":
            continue
        if open_cycle:
            scheduled = (card.get("next_earnings") or {}).get("date")
            if scheduled and scheduled != open_cycle.get("latest_scheduled_earnings_date"):
                open_cycle.setdefault("schedule_revisions", []).append({
                    "observed_at": snapshot["captured_at"],
                    "before": open_cycle.get("latest_scheduled_earnings_date"), "after": scheduled,
                })
                open_cycle["latest_scheduled_earnings_date"] = scheduled
                changed = True
            continue
        scheduled = (card.get("next_earnings") or {}).get("date")
        cycle = {
            "cycle_id": stable_hash({"ticker": ticker, "scheduled": scheduled, "captured": snapshot["captured_at"]}, 20),
            "ticker": ticker, "position": card.get("position"), "status": "waiting_result",
            "scheduled_earnings_date": scheduled, "latest_scheduled_earnings_date": scheduled,
            "schedule_revisions": [],
            "pre": {
                "captured_at": snapshot["captured_at"], "baseline_result_key": list(latest_key or (None, None, None)),
                "card": copy.deepcopy(card),
            },
            "post": None, "differences": [],
        }
        cycles.insert(0, cycle)
        changed = True
    cycles.sort(key=lambda row: (row.get("pre", {}).get("captured_at") or "", row.get("ticker") or ""), reverse=True)
    return cycles[:MAX_CYCLES], changed


def compact_history_entry(snapshot: dict[str, Any], notifications: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot.get("snapshot_id"),
        "captured_at": snapshot.get("captured_at"),
        "source_date": snapshot.get("source_date"),
        "notify_count": len(notifications or []),
        "notifications": copy.deepcopy(notifications or []),
    }


def build_history(snapshot: dict[str, Any], existing: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    existing = existing or {}
    previous = existing.get("current")
    cycles, cycles_changed = update_cycles(snapshot, existing.get("cycles", []))
    legacy_history = existing.get("history", [])
    needs_compaction = any("companies" in row for row in legacy_history)
    compacted_history = [
        compact_history_entry(row, row.get("notifications", [])) if "companies" in row else copy.deepcopy(row)
        for row in legacy_history
    ]
    if previous and previous.get("snapshot_id") == snapshot["snapshot_id"]:
        if not cycles_changed and not needs_compaction:
            return existing, False
        migrated = copy.deepcopy(existing)
        migrated["history"] = compacted_history[:MAX_HISTORY]
        migrated["cycles"] = cycles
        return migrated, True

    notifications = []
    prior_companies = (previous or {}).get("companies", {})
    for ticker, card in snapshot["companies"].items():
        comparison, notification = compare_company(card, prior_companies.get(ticker))
        card["comparison"] = comparison
        if notification:
            notifications.append(notification)
    notifications.sort(key=lambda row: (not row.get("critical"), row.get("ticker")))
    history = [compact_history_entry(snapshot, notifications)]
    history.extend(row for row in compacted_history if row.get("snapshot_id") != snapshot["snapshot_id"])
    previous_id = (previous or {}).get("snapshot_id")
    payload = {
        "schema_version": 1,
        "updated_at": snapshot["captured_at"],
        "current_snapshot_id": snapshot["snapshot_id"],
        "previous_snapshot_id": previous_id,
        "batch_id": stable_hash({"previous": previous_id, "current": snapshot["snapshot_id"]}, 12),
        "notify_count": len(notifications),
        "critical_count": sum(bool(row.get("critical")) for row in notifications),
        "notification_policy": "首次只建基準；之後只通知財報前／後階段、新季度、官方指引、KPI 風險／改善、指引驗證與論點結論變化。每日倒數與未跨狀態的數值波動不通知。",
        "notifications": notifications,
        "current": snapshot,
        "history": history[:MAX_HISTORY],
        "cycles": cycles,
    }
    return payload, True


def render_markdown(payload: dict[str, Any]) -> str:
    current = payload["current"]
    lines = [
        "---", "title: 財報驗證歷史與差異通知", "tags:", "  - earnings", "  - verification-history", "---", "",
        "# 🔔 財報驗證歷史與差異通知", "",
        f"> 更新 **{payload['updated_at']}**｜快照 `{payload['current_snapshot_id']}`｜本次通知 {payload['notify_count']} 項。", "",
        "## 本次真正需要注意的變化", "",
    ]
    if payload.get("notifications"):
        for row in payload["notifications"]:
            lines.append(f"- **{row['ticker']}｜{row['label']}**")
            lines.extend(f"  - {reason}" for reason in row["reasons"])
    elif payload.get("previous_snapshot_id"):
        lines.append("- 相較前次快照，沒有需要通知的實質變化；每日倒數與未跨狀態的數值波動不重複提醒。")
    else:
        lines.append("- 首次建立比較基準，不發通知，也不回填不存在的財報前判斷。")
    lines.extend(["", "## 目前 14 家狀態", "", "| 公司 | 類別 | 階段 | 下一財報 | 最新結果 | 相較前次 |", "|---|---|---|---|---|---|"])
    for ticker, row in current["companies"].items():
        comparison = row.get("comparison") or {}
        lines.append(f"| **{ticker}** | {'實際持股' if row.get('position') == 'holding' else '觀察名單'} | {row.get('phase_label') or '—'} | {(row.get('next_earnings') or {}).get('date') or '待公告'} | {(row.get('latest_result') or {}).get('period_end') or '—'} | {comparison.get('label') or '—'} |")
    lines.extend(["", "## 財報前凍結／財報後結案紀錄", ""])
    if not payload.get("cycles"):
        lines.append("- 尚未有公司進入財報前 7 天準備期；因此沒有凍結快照。系統不回填過去不存在的判斷。")
    for cycle in payload.get("cycles", []):
        pre = cycle["pre"]
        post = cycle.get("post")
        lines.append(f"### {cycle['ticker']}｜{cycle['scheduled_earnings_date'] or '日期待公告'}｜{'已完成核對' if post else '等待新季度'}")
        lines.append(f"- 財報前凍結：{pre['captured_at']}；基準季度 {(pre['card'].get('latest_result') or {}).get('period_end') or '—'}。")
        if post:
            lines.append(f"- 財報後核對：{post['captured_at']}；新季度 {(post.get('latest_result') or {}).get('period_end') or '—'}。")
            lines.extend(f"  - {reason}" for reason in cycle.get("differences", []))
        else:
            lines.append("- 尚未取得不同於基準季度的新財報；保留原始條件等待核對。")
        lines.append("")
    lines.extend(["## 通知原則", "", payload["notification_policy"], "",
                  "> 本頁保存的是當時可取得資料與後續差異，不是股價預測、買進或賣出建議。ETF 不納入。", ""])
    return "\n".join(lines)


def append_alert(path: Path, payload: dict[str, Any]) -> None:
    if not payload.get("notifications"):
        return
    lines = ["", "## 🎯 財報驗證差異", ""]
    for row in payload["notifications"]:
        lines.append(f"- **{row['ticker']}｜{row['label']}**")
        lines.extend(f"  - {reason}" for reason in row["reasons"])
    lines.extend(["", "> 只通知驗證階段與客觀證據的實質改變；不是買進／賣出建議。", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write("\n".join(lines))


def append_summary(path: Path, payload: dict[str, Any], is_new: bool) -> None:
    if not is_new:
        return
    with path.open("a") as handle:
        handle.write("\n".join(["", "## Earnings verification history", "",
                                f"- Snapshot: `{payload['current_snapshot_id']}`",
                                f"- Meaningful changes: {payload['notify_count']}",
                                f"- Frozen cycles: {len(payload['cycles'])}", ""]))


def write_github_output(path: Path, payload: dict[str, Any], is_new: bool) -> None:
    path.write_text("\n".join([
        f"notify_count={payload.get('notify_count', 0) if is_new else 0}",
        f"critical_count={payload.get('critical_count', 0) if is_new else 0}",
        f"batch_id={payload.get('batch_id', 'none')}",
        f"snapshot_id={payload.get('current_snapshot_id', 'none')}", "",
    ]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "earnings_verification_cards.json")
    parser.add_argument("--output", type=Path, default=ROOT / "earnings_verification_history.json")
    parser.add_argument("--markdown", type=Path, default=ROOT / "60_SEC_Filing_Radar/Earnings_Verification_History.md")
    parser.add_argument("--checked-at")
    parser.add_argument("--alert-markdown", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    cards = load_json(args.input, {})
    checked_at = normalize_checked_at(args.checked_at or cards.get("generated_at"))
    snapshot = build_snapshot(cards, checked_at)
    payload, is_new = build_history(snapshot, load_json(args.output, {}))
    if is_new or not args.output.is_file():
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    if is_new or not args.markdown.is_file():
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(payload))
    if args.alert_markdown and is_new:
        append_alert(args.alert_markdown, payload)
    if args.summary:
        append_summary(args.summary, payload, is_new)
    if args.github_output:
        write_github_output(args.github_output, payload, is_new)
    print(f"財報驗證歷史：{snapshot['snapshot_id']}；新快照 {int(is_new)}；通知 {payload.get('notify_count', 0) if is_new else 0}；循環 {len(payload.get('cycles', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
