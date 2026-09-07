#!/usr/bin/env python3
"""Track segment-outlook revisions and outcomes without duplicate alerts.

The first run only establishes a baseline.  Later runs notify when management
adds, raises, lowers, revises, or removes a comparable segment outlook; when a
pending item becomes above/within/below (or met/missed); or when an accounting
basis change makes the comparison invalid.  Re-running the same snapshot is
idempotent and produces zero workflow notifications.
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
GOOD_OUTCOMES = {"above", "within", "met"}
BAD_OUTCOMES = {"below", "missed"}


def load_json(path: Path, default: Any = None) -> Any:
    return json.loads(path.read_text()) if path.is_file() else default


def stable_hash(value: Any, length: int = 16) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()[:length]


def normalize_checked_at(value: str | None) -> str:
    if not value:
        return datetime.now(ZoneInfo("Asia/Taipei")).isoformat(timespec="seconds")
    if len(value) == 10:
        return f"{value}T00:00:00+08:00"
    return value


def position_tickers(holdings: Any) -> set[str]:
    rows = holdings if isinstance(holdings, list) else (holdings or {}).get("holdings", [])
    return {str(row.get("ticker", "")).upper() for row in rows if row.get("shares", 0) and row.get("ticker")}


def compact_record(row: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "id", "outlook_period", "target_period", "target_period_end", "basis_id",
        "segment_key", "segment_name", "metric", "metric_label", "comparison",
        "low", "high", "baseline", "unit", "statement_zh", "source_date", "source_url",
        "target", "actual", "actual_display", "actual_status", "actual_source_date",
        "actual_source_url", "outcome", "outcome_label", "verification_note",
        "thesis_title", "thesis_impact", "thesis_impact_label", "thesis_note",
    )
    return {key: copy.deepcopy(row.get(key)) for key in fields}


def compact_company(row: dict[str, Any], positions: set[str]) -> dict[str, Any]:
    ticker = row.get("ticker")
    return {
        "ticker": ticker,
        "name": row.get("name"),
        "position": "holding" if ticker in positions else "watchlist",
        "coverage_status": row.get("coverage_status"),
        "note": row.get("note"),
        "review_url": row.get("review_url"),
        "signal": row.get("signal"),
        "label": row.get("label"),
        "counts": copy.deepcopy(row.get("counts") or {}),
        "records": [compact_record(item) for item in row.get("records", [])],
    }


def build_snapshot(data: dict[str, Any], holdings: Any, checked_at: str) -> dict[str, Any]:
    positions = position_tickers(holdings)
    companies = {row["ticker"]: compact_company(row, positions) for row in data.get("companies", [])}
    return {
        "snapshot_id": stable_hash(companies),
        "captured_at": checked_at,
        "source_date": data.get("updated_at"),
        "companies": companies,
    }


def record_key(row: dict[str, Any]) -> tuple[Any, ...]:
    """Logical key survives a source-side record-id revision."""
    return (row.get("target_period_end"), row.get("segment_key"), row.get("metric"))


def target_numbers(row: dict[str, Any]) -> tuple[Any, ...]:
    return (row.get("comparison"), row.get("low"), row.get("high"), row.get("baseline"), row.get("unit"))


def target_change(current: dict[str, Any], previous: dict[str, Any]) -> tuple[str | None, str | None, str]:
    if target_numbers(current) == target_numbers(previous):
        return None, None, "neutral"
    before, after = previous.get("target") or "—", current.get("target") or "—"
    if current.get("comparison") == previous.get("comparison") == "range":
        old_low, old_high = previous.get("low"), previous.get("high")
        new_low, new_high = current.get("low"), current.get("high")
        if None not in (old_low, old_high, new_low, new_high):
            if new_low > old_low and new_high > old_high:
                return "guidance_raised", f"上修分部展望：{before} → {after}", "improvement"
            if new_low < old_low and new_high < old_high:
                return "guidance_lowered", f"下修分部展望：{before} → {after}", "risk"
    return "guidance_revised", f"調整分部展望：{before} → {after}", "neutral"


def thesis_effect(row: dict[str, Any]) -> str:
    title = row.get("thesis_title")
    if not title:
        return "目前沒有可直接連結的投資論點。"
    impact = row.get("thesis_impact_label") or "不改變"
    return f"對投資論點「{title}」：{impact}。"


def change_item(kind: str, row: dict[str, Any], reason: str, direction: str = "neutral",
                critical: bool = False) -> dict[str, Any]:
    return {
        "kind": kind,
        "record_id": row.get("id"),
        "target_period": row.get("target_period"),
        "segment_name": row.get("segment_name"),
        "metric_label": row.get("metric_label"),
        "direction": direction,
        "critical": critical,
        "reason": reason,
        "thesis_effect": thesis_effect(row),
        "source_url": row.get("actual_source_url") or row.get("source_url"),
    }


def compare_company(current: dict[str, Any], previous: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if not previous:
        return {"status": "baseline", "notify": False, "label": "首次建立比較基準", "changes": []}, None

    changes: list[dict[str, Any]] = []
    if current.get("coverage_status") != previous.get("coverage_status"):
        if current.get("coverage_status") == "available":
            reason, direction = "新增可與正式分部實績核對的管理層展望。", "neutral"
        else:
            reason, direction = "原可比展望目前撤除或不再符合分部同口徑核對條件。", "risk"
        dummy = (current.get("records") or previous.get("records") or [{}])[0]
        changes.append(change_item("coverage_changed", dummy, reason, direction, direction == "risk"))

    current_by_key = {record_key(row): row for row in current.get("records", [])}
    previous_by_key = {record_key(row): row for row in previous.get("records", [])}
    for key, row in current_by_key.items():
        old = previous_by_key.get(key)
        descriptor = f"{row.get('target_period')} {row.get('segment_name')}／{row.get('metric_label')}"
        if not old:
            changes.append(change_item(
                "guidance_added", row,
                f"新增分部展望：{descriptor}，管理層目標 {row.get('target') or '—'}。",
                "risk" if row.get("outcome") in BAD_OUTCOMES else "neutral",
                row.get("outcome") in BAD_OUTCOMES,
            ))
            continue

        if row.get("basis_id") != old.get("basis_id"):
            changes.append(change_item(
                "basis_changed", row,
                f"比較口徑改變：{old.get('basis_id') or '未標示'} → {row.get('basis_id') or '未標示'}；舊值不直接續接。",
                "risk", True,
            ))

        kind, reason, direction = target_change(row, old)
        if kind:
            changes.append(change_item(kind, row, f"{descriptor}｜{reason}", direction, direction == "risk"))

        old_outcome, new_outcome = old.get("outcome"), row.get("outcome")
        if old_outcome != new_outcome:
            actual = row.get("actual_display") or "—"
            if old_outcome == "pending" and new_outcome == "not_comparable":
                changes.append(change_item(
                    "basis_not_comparable", row,
                    f"{descriptor} 由等待實績轉為口徑不可比；停止硬比並保留缺值。",
                    "risk", True,
                ))
            elif old_outcome == "pending":
                direction = "risk" if new_outcome in BAD_OUTCOMES else "improvement" if new_outcome in GOOD_OUTCOMES else "neutral"
                changes.append(change_item(
                    "outcome_completed", row,
                    f"{descriptor} 完成核對：展望 {row.get('target') or '—'}，實績 {actual}，結果為「{row.get('outcome_label') or new_outcome}」。",
                    direction, new_outcome in BAD_OUTCOMES,
                ))
            else:
                direction = "risk" if new_outcome in BAD_OUTCOMES | {"not_comparable"} else "improvement" if new_outcome in GOOD_OUTCOMES else "neutral"
                changes.append(change_item(
                    "outcome_revised", row,
                    f"{descriptor} 驗證結果修正：{old.get('outcome_label') or old_outcome} → {row.get('outcome_label') or new_outcome}。",
                    direction, new_outcome in BAD_OUTCOMES | {"not_comparable"},
                ))

    for key, row in previous_by_key.items():
        if key in current_by_key:
            continue
        descriptor = f"{row.get('target_period')} {row.get('segment_name')}／{row.get('metric_label')}"
        changes.append(change_item(
            "guidance_withdrawn", row,
            f"撤回或移除分部展望：{descriptor}（原目標 {row.get('target') or '—'}）；需核對公司是否正式撤回或改變揭露方式。",
            "risk", True,
        ))

    if not changes:
        comparison = {"status": "unchanged", "notify": False, "label": "沒有需通知的實質變化", "changes": []}
        return comparison, None

    critical = any(item["critical"] for item in changes)
    directions = {item["direction"] for item in changes}
    direction = "risk" if "risk" in directions else "improvement" if "improvement" in directions else "neutral"
    label = "新增風險" if direction == "risk" else "新增改善" if direction == "improvement" else "展望狀態更新"
    comparison = {
        "status": "changed", "notify": True, "label": label,
        "direction": direction, "critical": critical, "changes": changes,
    }
    notification = {
        "ticker": current["ticker"], "position": current.get("position"),
        **comparison,
    }
    return comparison, notification


def history_entry(snapshot: dict[str, Any], notifications: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot["snapshot_id"], "captured_at": snapshot["captured_at"],
        "source_date": snapshot.get("source_date"), "notify_count": len(notifications),
        "notifications": copy.deepcopy(notifications),
    }


def build_history(snapshot: dict[str, Any], existing: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    existing = existing or {}
    previous = existing.get("current")
    if previous and previous.get("snapshot_id") == snapshot["snapshot_id"]:
        return existing, False

    notifications = []
    prior_companies = (previous or {}).get("companies", {})
    for ticker, company in snapshot["companies"].items():
        comparison, notification = compare_company(company, prior_companies.get(ticker))
        company["comparison"] = comparison
        if notification:
            notifications.append(notification)
    notifications.sort(key=lambda row: (
        row.get("position") != "holding", not row.get("critical"), row.get("ticker") or "",
    ))
    previous_id = (previous or {}).get("snapshot_id")
    entries = [history_entry(snapshot, notifications)]
    entries.extend(copy.deepcopy(row) for row in existing.get("history", []) if row.get("snapshot_id") != snapshot["snapshot_id"])
    payload = {
        "schema_version": 1,
        "updated_at": snapshot["captured_at"],
        "current_snapshot_id": snapshot["snapshot_id"],
        "previous_snapshot_id": previous_id,
        "batch_id": stable_hash({"previous": previous_id, "current": snapshot["snapshot_id"]}, 12),
        "notify_count": len(notifications),
        "critical_count": sum(bool(row.get("critical")) for row in notifications),
        "notification_policy": "首次只建立基準；之後只通知新增、上修、下修、調整、撤回、口徑不可比及等待轉成達標／未達標。相同資料重跑與結果區間未改變的數值修訂不重複通知；實際持股優先。",
        "notifications": notifications,
        "current": snapshot,
        "history": entries[:MAX_HISTORY],
    }
    return payload, True


def render_markdown(payload: dict[str, Any]) -> str:
    current = payload["current"]
    lines = [
        "---", "title: 分部展望變更與達標通知", "tags:", "  - segment", "  - guidance", "  - alert", "---", "",
        "# 🔔 分部展望變更與達標通知", "",
        f"> 更新 **{payload['updated_at']}**｜快照 `{payload['current_snapshot_id']}`｜本次通知 {payload['notify_count']} 項；其中需優先覆核 {payload['critical_count']} 項。", "",
        "## 本次真正需要注意的變化", "",
    ]
    if payload.get("notifications"):
        for row in payload["notifications"]:
            position = "實際持股" if row.get("position") == "holding" else "觀察名單"
            lines.append(f"- **{row['ticker']}｜{position}｜{row['label']}**")
            for item in row.get("changes", []):
                lines.append(f"  - {item['reason']} {item['thesis_effect']}")
    elif payload.get("previous_snapshot_id"):
        lines.append("- 相較前次快照沒有實質變化；相同資料不重複提醒。")
    else:
        lines.append("- 首次建立比較基準，不補發既有展望或既有達標結果的歷史通知。")
    lines += ["", "## 目前 14 家狀態", "", "| 公司 | 類別 | 可比展望 | 已驗證 | 待驗證 | 相較前次 |", "|---|---|---:|---:|---:|---|"]
    for ticker, row in current["companies"].items():
        counts = row.get("counts") or {}
        comparison = row.get("comparison") or {}
        lines.append(
            f"| **{ticker}** | {'實際持股' if row.get('position') == 'holding' else '觀察名單'} | "
            f"{'有' if row.get('coverage_status') == 'available' else '無'} | {counts.get('completed', 0)} | "
            f"{counts.get('pending', 0)} | {comparison.get('label') or '—'} |"
        )
    lines += ["", "## 通知原則", "", payload["notification_policy"], "",
              "> 這是官方展望與同口徑實績的證據追蹤，不是買進、賣出或目標價建議。", ""]
    return "\n".join(lines)


def append_alert(path: Path, payload: dict[str, Any]) -> None:
    if not payload.get("notifications"):
        return
    lines = ["", "## 🎯 分部展望變更與達標", ""]
    for row in payload["notifications"]:
        position = "實際持股優先" if row.get("position") == "holding" else "觀察名單"
        lines.append(f"- **{row['ticker']}｜{position}｜{row['label']}**")
        for item in row.get("changes", []):
            lines.append(f"  - {item['reason']} {item['thesis_effect']}")
    lines += ["", "> 只通知實質變化；相同快照不重複開 Issue。", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write("\n".join(lines))


def append_summary(path: Path, payload: dict[str, Any], is_new: bool) -> None:
    if not is_new:
        return
    with path.open("a") as handle:
        handle.write("\n".join([
            "", "## Segment outlook changes", "",
            f"- Snapshot: `{payload['current_snapshot_id']}`",
            f"- Meaningful changes: {payload['notify_count']}",
            f"- Critical reviews: {payload['critical_count']}", "",
        ]))


def write_github_output(path: Path, payload: dict[str, Any], is_new: bool) -> None:
    path.write_text("\n".join([
        f"notify_count={payload.get('notify_count', 0) if is_new else 0}",
        f"critical_count={payload.get('critical_count', 0) if is_new else 0}",
        f"batch_id={payload.get('batch_id', 'none')}",
        f"snapshot_id={payload.get('current_snapshot_id', 'none')}", "",
    ]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "segment_outlook_verification.json")
    parser.add_argument("--holdings", type=Path, default=ROOT / "portfolio_holdings.json")
    parser.add_argument("--history", type=Path, default=ROOT / "segment_outlook_history.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown", type=Path, default=ROOT / "60_SEC_Filing_Radar/Segment_Outlook_History.md")
    parser.add_argument("--checked-at")
    parser.add_argument("--alert-markdown", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    output = args.output or args.history
    source = load_json(args.input, {})
    checked_at = normalize_checked_at(args.checked_at or source.get("updated_at"))
    snapshot = build_snapshot(source, load_json(args.holdings, []), checked_at)
    payload, is_new = build_history(snapshot, load_json(args.history, {}))
    if is_new or not output.is_file():
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    if is_new or not args.markdown.is_file():
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(payload))
    if args.alert_markdown and is_new:
        append_alert(args.alert_markdown, payload)
    if args.summary:
        append_summary(args.summary, payload, is_new)
    if args.github_output:
        write_github_output(args.github_output, payload, is_new)
    print(
        f"分部展望歷史：{snapshot['snapshot_id']}；新快照 {int(is_new)}；"
        f"通知 {payload.get('notify_count', 0) if is_new else 0}；需覆核 {payload.get('critical_count', 0) if is_new else 0}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
