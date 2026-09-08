#!/usr/bin/env python3
"""Save capital-allocation snapshots and notify only meaningful transitions."""

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
RISK_STATES = {"risk", "pressure"}
POSITIVE_STATES = {"support"}


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


def compact_company(row: dict[str, Any]) -> dict[str, Any]:
    latest_fields = (
        "fiscal_year_end", "currency", "free_cash_flow", "fcf_margin", "fcf_conversion",
        "capex", "capex_intensity", "buybacks", "dividends_paid", "shareholder_returns",
        "payout_complete", "payout_to_fcf", "diluted_shares", "share_change",
        "share_comparable", "share_note", "total_debt", "debt_change",
        "cash_and_short_investments", "net_cash", "source",
    )
    return {
        "ticker": row.get("ticker"), "position": row.get("position"),
        "latest_period": row.get("latest_period"), "status": row.get("status"),
        "label": row.get("label"), "score": row.get("score"),
        "coverage": copy.deepcopy(row.get("coverage") or {}),
        "signals": copy.deepcopy(row.get("signals") or []),
        "latest": {key: copy.deepcopy((row.get("latest") or {}).get(key)) for key in latest_fields},
        "conclusion": row.get("conclusion"),
    }


def build_snapshot(cards: dict[str, Any], checked_at: str) -> dict[str, Any]:
    companies = {row["ticker"]: compact_company(row) for row in cards.get("companies", [])}
    return {
        "snapshot_id": stable_hash(companies), "captured_at": checked_at,
        "source_date": cards.get("updated_at"), "companies": companies,
    }


def transition_direction(before: str | None, after: str | None) -> tuple[str, bool]:
    if after in RISK_STATES and before not in RISK_STATES:
        return "risk", True
    if before in RISK_STATES and after not in RISK_STATES:
        return "improvement", False
    if after in POSITIVE_STATES and before not in POSITIVE_STATES:
        return "improvement", False
    if before in POSITIVE_STATES and after not in POSITIVE_STATES:
        return "risk", False
    if before == "unavailable" and after != "unavailable":
        return "neutral", False
    return "neutral", False


def compare_company(current: dict[str, Any], previous: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if not previous:
        return {"status": "baseline", "notify": False, "label": "首次建立比較基準", "changes": []}, None

    changes = []
    overall_direction = "neutral"
    critical = False
    if current.get("latest_period") != previous.get("latest_period"):
        changes.append({
            "kind": "new_annual_period", "direction": "neutral", "critical": False,
            "reason": f"新增年度 {current.get('latest_period')}（前次 {previous.get('latest_period') or '—'}），資本配置已重新核對。",
        })

    if current.get("status") != previous.get("status"):
        direction, is_critical = transition_direction(previous.get("status"), current.get("status"))
        changes.append({
            "kind": "conclusion_changed", "direction": direction, "critical": is_critical,
            "reason": f"綜合結論：{previous.get('label') or '資料不足'} → {current.get('label') or '資料不足'}。",
        })
        overall_direction, critical = direction, critical or is_critical

    prior_signals = {row.get("id"): row for row in previous.get("signals", [])}
    for row in current.get("signals", []):
        prior = prior_signals.get(row.get("id"))
        if not prior or prior.get("state") == row.get("state"):
            continue
        direction, is_critical = transition_direction(prior.get("state"), row.get("state"))
        changes.append({
            "kind": f"{row.get('id')}_changed", "dimension": row.get("id"),
            "direction": direction, "critical": is_critical,
            "reason": f"{row.get('label')}：{prior.get('state')} → {row.get('state')}；{row.get('evidence')}",
        })
        critical = critical or is_critical
        if direction == "risk":
            overall_direction = "risk"
        elif direction == "improvement" and overall_direction != "risk":
            overall_direction = "improvement"

    if not changes:
        comparison = {"status": "unchanged", "notify": False, "label": "沒有需通知的實質變化", "changes": []}
        return comparison, None
    label = "新增風險" if overall_direction == "risk" else "新增改善" if overall_direction == "improvement" else "年度資料更新"
    comparison = {
        "status": "changed", "notify": True, "label": label,
        "direction": overall_direction, "critical": critical, "changes": changes,
    }
    return comparison, {"ticker": current["ticker"], "position": current.get("position"), **comparison}


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
        comparison, notice = compare_company(company, prior_companies.get(ticker))
        company["comparison"] = comparison
        if notice:
            notifications.append(notice)
    notifications.sort(key=lambda row: (
        row.get("position") != "holding", not row.get("critical"), row.get("ticker") or "",
    ))
    previous_id = (previous or {}).get("snapshot_id")
    history = [history_entry(snapshot, notifications)]
    history.extend(copy.deepcopy(row) for row in existing.get("history", []) if row.get("snapshot_id") != snapshot["snapshot_id"])
    payload = {
        "schema_version": 1, "updated_at": snapshot["captured_at"],
        "current_snapshot_id": snapshot["snapshot_id"], "previous_snapshot_id": previous_id,
        "batch_id": stable_hash({"previous": previous_id, "current": snapshot["snapshot_id"]}, 12),
        "notify_count": len(notifications),
        "critical_count": sum(bool(row.get("critical")) for row in notifications),
        "notification_policy": "首次只建立基準；之後只通知新年度、五項構面跨狀態及綜合結論改變。單純數值變動但未跨門檻不通知，相同快照重跑輸出 0；實際持股優先。",
        "notifications": notifications, "current": snapshot, "history": history[:MAX_HISTORY],
    }
    return payload, True


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "---", "title: 資本配置變更與股東價值通知", "tags:", "  - capital-allocation", "  - alert", "---", "",
        "# 🔔 資本配置變更與股東價值通知", "",
        f"> 更新 **{payload['updated_at']}**｜本次通知 {payload['notify_count']}｜需優先覆核 {payload['critical_count']}。", "",
        "## 本次真正需要注意的變化", "",
    ]
    if payload.get("notifications"):
        for row in payload["notifications"]:
            lines.append(f"- **{row['ticker']}｜{'實際持股' if row.get('position') == 'holding' else '觀察名單'}｜{row['label']}**")
            lines.extend(f"  - {item['reason']}" for item in row.get("changes", []))
    elif payload.get("previous_snapshot_id"):
        lines.append("- 相較前次沒有跨門檻或結論變化；不重複提醒單純數值波動。")
    else:
        lines.append("- 首次建立比較基準，不補發既有年度狀態的歷史通知。")
    lines += ["", "## 目前 14 家狀態", "", "| 公司 | 類別 | 年度 | 結論 | 可判讀 | 相較前次 |", "|---|---|---|---|---:|---|"]
    for ticker, row in payload["current"]["companies"].items():
        coverage = row.get("coverage") or {}
        comparison = row.get("comparison") or {}
        lines.append(
            f"| **{ticker}** | {'實際持股' if row.get('position') == 'holding' else '觀察名單'} | "
            f"{row.get('latest_period') or '—'} | {row.get('label') or '—'} | {coverage.get('known', 0)}/{coverage.get('total', 5)} | {comparison.get('label') or '—'} |"
        )
    lines += ["", "## 通知原則", "", payload["notification_policy"], "",
              "> 這是已公布財務資料的規則化判讀，不是管理層動機推測或買賣建議。", ""]
    return "\n".join(lines)


def append_alert(path: Path, payload: dict[str, Any]) -> None:
    if not payload.get("notifications"):
        return
    lines = ["", "## 🧭 資本配置與股東價值變化", ""]
    for row in payload["notifications"]:
        priority = "實際持股優先" if row.get("position") == "holding" else "觀察名單"
        lines.append(f"- **{row['ticker']}｜{priority}｜{row['label']}**")
        lines.extend(f"  - {item['reason']}" for item in row.get("changes", []))
    lines += ["", "> 只通知跨門檻或結論改變；相同快照不重複開 Issue。", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write("\n".join(lines))


def append_summary(path: Path, payload: dict[str, Any], is_new: bool) -> None:
    if not is_new:
        return
    with path.open("a") as handle:
        handle.write("\n".join([
            "", "## Capital allocation changes", "",
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
    parser.add_argument("--input", type=Path, default=ROOT / "capital_allocation_cards.json")
    parser.add_argument("--history", type=Path, default=ROOT / "capital_allocation_history.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown", type=Path, default=ROOT / "60_SEC_Filing_Radar/Capital_Allocation_History.md")
    parser.add_argument("--checked-at")
    parser.add_argument("--alert-markdown", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    output = args.output or args.history
    cards = load_json(args.input, {})
    checked_at = normalize_checked_at(args.checked_at or cards.get("updated_at"))
    snapshot = build_snapshot(cards, checked_at)
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
        f"資本配置歷史：{snapshot['snapshot_id']}；新快照 {int(is_new)}；"
        f"通知 {payload.get('notify_count', 0) if is_new else 0}；需覆核 {payload.get('critical_count', 0) if is_new else 0}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
