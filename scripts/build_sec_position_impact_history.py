#!/usr/bin/env python3
"""Build deterministic portfolio-impact snapshots and meaningful change alerts."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DISPLAY_TICKER = {"GOOGL": "GOOG"}
DATA_TICKER = {"GOOG": "GOOGL"}
CORE_HOLDINGS = {"ARM", "COHR", "GOOG", "INTC", "MRVL", "NOK", "NVDA", "TSLA"}
MAX_HISTORY = 60

TIER_SCORES = {"general": 16, "important": 28, "dilution": 28,
               "ownership": 28, "enforcement": 40, "financial": 28,
               "thesis": 28}
TONE_SCORES = {"risk": 32, "caution": 18, "positive": 8}
CANDIDATE_SCORES = {
    "risk": {"high": 40, "medium": 34, "low": 24},
    "conclusion": {"high": 36, "medium": 30, "low": 20},
    "improvement": {"high": 20, "medium": 16, "low": 12},
}
REVIEWED_SCORES = {"risk": 40, "conclusion": 35, "improvement": 18}
LEVELS = {
    "high": {"label": "高影響", "min": 70},
    "medium": {"label": "中影響", "min": 45},
    "low": {"label": "低影響", "min": 0},
}


def load_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text())


def data_ticker(ticker: str) -> str:
    return DATA_TICKER.get(ticker, ticker)


def display_ticker(ticker: str) -> str:
    return DISPLAY_TICKER.get(ticker, ticker)


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def latest_source_time(*values: str | None) -> str:
    parsed = [item for item in (parse_iso(value) for value in values) if item]
    return max(parsed).isoformat().replace("+00:00", "Z") if parsed else ""


def stable_hash(value: Any, length: int = 16) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:length]


def weight_score(weight: float) -> int:
    return 35 if weight >= 15 else 28 if weight >= 10 else 20 if weight >= 5 else 12 if weight >= 2 else 6


def drawdown_score(pnl_pct: float) -> int:
    return 25 if pnl_pct <= -30 else 20 if pnl_pct <= -20 else 12 if pnl_pct <= -10 else 6 if pnl_pct < 0 else 0


def impact_level(score: int) -> str:
    return "high" if score >= 70 else "medium" if score >= 45 else "low"


def metric(period: dict[str, Any] | None, name: str) -> float | None:
    value = (period or {}).get("values", {}).get(name)
    if isinstance(value, dict):
        value = value.get("value")
    return float(value) if isinstance(value, (int, float)) else None


def percent_change(current: float | None, previous: float | None, *, points: bool = False) -> float | None:
    if current is None or previous is None:
        return None
    if points:
        return (current - previous) * 100
    return (current / previous - 1) * 100 if previous else None


def streak(periods: list[dict[str, Any]], name: str, *, points: bool = False, threshold: float = 0) -> tuple[str, int]:
    direction = ""
    comparisons = 0
    for index in range(min(len(periods) - 1, 7)):
        change = percent_change(metric(periods[index], name), metric(periods[index + 1], name), points=points)
        if change is None:
            break
        step = "up" if change > threshold else "down" if change < -threshold else "flat"
        if step == "flat":
            break
        if not direction:
            direction = step
        if step != direction:
            break
        comparisons += 1
    return direction or "flat", comparisons + 1 if comparisons else 1


def quarterly_alerts(company: dict[str, Any]) -> tuple[list[str], str]:
    periods = company.get("periods", [])[:8]
    if not periods:
        return [], "unavailable"
    latest = periods[0]
    previous = periods[1] if len(periods) > 1 else None
    year_ago = periods[4] if len(periods) > 4 else None
    revenue = metric(latest, "revenue")
    gross_margin = metric(latest, "gross_margin")
    operating_margin = metric(latest, "operating_margin")
    free_cash_flow = metric(latest, "free_cash_flow")
    diluted_shares = metric(latest, "diluted_shares")
    revenue_yoy = percent_change(revenue, metric(year_ago, "revenue"))
    gross_yoy = percent_change(gross_margin, metric(year_ago, "gross_margin"), points=True)
    share_yoy = percent_change(diluted_shares, metric(year_ago, "diluted_shares"))
    revenue_streak = streak(periods, "revenue", threshold=1)
    gross_streak = streak(periods, "gross_margin", points=True, threshold=0.5)
    operating_streak = streak(periods, "operating_margin", points=True, threshold=0.5)
    negative_operating = next((index for index, row in enumerate(periods)
                               if metric(row, "operating_margin") is None or metric(row, "operating_margin") >= 0), len(periods))
    negative_fcf = next((index for index, row in enumerate(periods)
                         if metric(row, "free_cash_flow") is None or metric(row, "free_cash_flow") >= 0), len(periods))
    previous_fcf = metric(previous, "free_cash_flow")
    alerts: list[str] = []
    if revenue_streak[0] == "down" and revenue_streak[1] >= 3:
        alerts.append("營收連續下降")
    if revenue_yoy is not None and revenue_yoy <= -10:
        alerts.append("營收年減超過 10%")
    if gross_streak[0] == "down" and gross_streak[1] >= 3:
        alerts.append("毛利率連續惡化")
    if gross_yoy is not None and gross_yoy <= -2:
        alerts.append("毛利率年減至少 2pp")
    if operating_streak[0] == "down" and operating_streak[1] >= 3:
        alerts.append("營業利益率連續惡化")
    if negative_operating >= 3:
        alerts.append("營業利益率連續為負")
    if free_cash_flow is not None and free_cash_flow < 0 and previous_fcf is not None and previous_fcf >= 0:
        alerts.append("FCF 由正轉負")
    elif negative_fcf >= 3:
        alerts.append("FCF 連續為負")
    if share_yoy is not None and share_yoy >= 10:
        alerts.append("稀釋股數年增至少 10%")
    fingerprint = stable_hash({
        "accession": latest.get("accession"), "values": [revenue, gross_margin, operating_margin, free_cash_flow, diluted_shares],
        "alerts": alerts,
    })
    return alerts, fingerprint


def crossed_threshold(before: float, after: float, thresholds: tuple[float, ...]) -> float | None:
    for threshold in thresholds:
        if (before < threshold <= after) or (after < threshold <= before):
            return threshold
    return None


def build_snapshot(
    holdings_payload: dict[str, Any],
    prices: dict[str, Any],
    alerts: dict[str, Any],
    candidates: dict[str, Any],
    editorial: dict[str, Any],
    thesis_status: dict[str, Any],
    advanced: dict[str, Any],
    quarterly: dict[str, Any],
) -> dict[str, Any]:
    holdings = holdings_payload.get("holdings", [])
    price_series = prices.get("series", {})
    priced: dict[str, dict[str, Any]] = {}
    price_dates: list[str] = []
    total_value = 0.0
    missing_prices: list[str] = []
    for holding in holdings:
        ticker = holding["ticker"]
        series = price_series.get(ticker, {})
        closes = series.get("closes", [])
        dates = series.get("dates", [])
        if closes:
            price = float(closes[-1])
            price_date = dates[-1] if dates else ""
        else:
            price = float(holding["cost"])
            price_date = ""
            missing_prices.append(ticker)
        value = float(holding["shares"]) * price
        total_value += value
        priced[ticker] = {"price": price, "price_date": price_date, "market_value": value}
        if price_date:
            price_dates.append(price_date)

    filing_dates = [row.get("filing_date", "") for row in alerts.get("events", []) if row.get("filing_date")]
    as_of = max(price_dates + filing_dates) if price_dates or filing_dates else date.today().isoformat()
    cutoff = (date.fromisoformat(as_of) - timedelta(days=13)).isoformat()
    editorial_rows = {row.get("ticker"): row for row in editorial.get("companies", [])}
    reviewed_changes = editorial.get("comparison", {}).get("changes", [])
    ownership_rows = advanced.get("ownership_timeline", [])
    enforcement_rows = advanced.get("enforcement", [])

    rows: list[dict[str, Any]] = []
    for holding in holdings:
        ticker = holding["ticker"]
        if ticker not in CORE_HOLDINGS:
            continue
        source_ticker = data_ticker(ticker)
        market = priced[ticker]
        cost_basis = float(holding["shares"]) * float(holding["cost"])
        pnl_pct = (market["market_value"] / cost_basis - 1) * 100 if cost_basis else 0.0
        weight_pct = market["market_value"] / total_value * 100 if total_value else 0.0
        event_score = 6
        event_reason = f"近 14 日無新申報"
        event_kind = "quiet"
        evidence_keys: list[str] = []

        def consider(score: int, kind: str, reason: str, keys: list[str]) -> None:
            nonlocal event_score, event_reason, event_kind
            evidence_keys.extend(key for key in keys if key)
            if score > event_score:
                event_score, event_kind, event_reason = score, kind, reason

        recent = [row for row in alerts.get("events", [])
                  if row.get("ticker") == source_ticker and cutoff <= row.get("filing_date", "") <= as_of]
        if recent:
            consider(TIER_SCORES["general"], "general", f"近期一般申報 {len(recent)} 份",
                     [row.get("accession", "") for row in recent])
        important = [row for row in recent if row.get("severity") in {"critical", "high"}
                     and row.get("group") != "內部人持股"]
        if important:
            consider(TIER_SCORES["important"], "important", f"重大／重要申報 {len(important)} 份",
                     [row.get("accession", "") for row in important])
        dilution = [row for row in recent if row.get("group") == "募資／稀釋"]
        if dilution:
            consider(TIER_SCORES["dilution"], "dilution", f"潛在稀釋申報 {len(dilution)} 份",
                     [row.get("accession", "") for row in dilution])

        ownership = [row for row in ownership_rows if display_ticker(row.get("ticker", "")) == ticker
                     and row.get("filing_date") and 0 <= (date.fromisoformat(as_of) - date.fromisoformat(row["filing_date"])).days <= 90
                     and row.get("importance") == "high"]
        if ownership:
            consider(TIER_SCORES["ownership"], "ownership", f"90 日內重大 13D／13G {len(ownership)} 項",
                     [row.get("accession", "") for row in ownership])
        enforcement = [row for row in enforcement_rows
                       if display_ticker((row.get("event") or {}).get("ticker") or row.get("ticker", "")) == ticker]
        if enforcement:
            consider(TIER_SCORES["enforcement"], "enforcement", f"SEC 執法／停牌 {len(enforcement)} 項",
                     [(row.get("event") or {}).get("accession") or row.get("url", "") for row in enforcement])

        thesis = thesis_status.get("companies", {}).get(source_ticker, {})
        invalidated = int((thesis.get("counts") or {}).get("invalidated", 0))
        financial_alerts, financial_fingerprint = quarterly_alerts(quarterly.get("companies", {}).get(source_ticker, {}))
        if financial_alerts:
            consider(TIER_SCORES["financial"], "financial", f"八季財務警報 {len(financial_alerts)} 項",
                     [financial_fingerprint])
        if invalidated:
            consider(TIER_SCORES["thesis"], "thesis", f"投資論點失效 {invalidated}/3",
                     [thesis.get("fingerprint", "")])

        company_candidates = [row for row in candidates.get("candidates", [])
                              if display_ticker(row.get("ticker", "")) == ticker]
        for row in company_candidates:
            score = CANDIDATE_SCORES.get(row.get("type"), {}).get(row.get("confidence"), 10)
            if row.get("display_priority") == "low":
                score = max(6, score - 6)
            consider(score, "candidate", f"待 AI 覆核：{row.get('headline') or '規則候選'}",
                     [row.get("id", "")])

        for change in reviewed_changes:
            if display_ticker(change.get("ticker", "")) != ticker:
                continue
            consider(REVIEWED_SCORES.get(change.get("type"), 18), "reviewed",
                     f"已覆核：{change.get('summary') or '正式判讀出現變化'}",
                     [f"{editorial.get('reviewed_at', '')}:{change.get('type', '')}:{change.get('summary', '')}"])

        editorial_row = editorial_rows.get(ticker, {})
        tone_score = TONE_SCORES.get(editorial_row.get("tone"), 0)
        consider(tone_score, "editorial", f"目前綜合判讀：{editorial_row.get('status') or '維持追蹤'}",
                 [f"{editorial.get('reviewed_at', '')}:{ticker}:{editorial_row.get('tone', '')}:{editorial_row.get('status', '')}"])

        position_points = weight_score(weight_pct)
        drawdown_points = drawdown_score(pnl_pct)
        total_score = min(100, event_score + position_points + drawdown_points)
        rows.append({
            "ticker": ticker,
            "total_score": total_score,
            "event_score": event_score,
            "position_score": position_points,
            "drawdown_score": drawdown_points,
            "level": impact_level(total_score),
            "weight_pct": round(weight_pct, 4),
            "pnl_pct": round(pnl_pct, 4),
            "market_value": round(market["market_value"], 2),
            "current_price": market["price"],
            "price_date": market["price_date"],
            "event_kind": event_kind,
            "event_reason": event_reason,
            "event_fingerprint": stable_hash(sorted(set(evidence_keys))),
        })

    rows.sort(key=lambda row: (-row["total_score"], -row["event_score"], -row["weight_pct"], row["ticker"]))
    core = {
        "as_of": as_of,
        "price_date": max(price_dates) if price_dates else "",
        "portfolio_market_value": round(total_value, 2),
        "missing_prices": sorted(missing_prices),
        "rows": rows,
    }
    source_time = latest_source_time(
        prices.get("generated_at"), alerts.get("updated_at"), candidates.get("generated_at"),
        editorial.get("reviewed_at"), thesis_status.get("updated_at"), advanced.get("generated_at"),
        quarterly.get("generated_at"),
    )
    return {"snapshot_id": stable_hash(core), "captured_at": source_time, **core}


def compare_rows(current: dict[str, Any], previous: dict[str, Any] | None) -> list[dict[str, Any]]:
    prior_rows = {row["ticker"]: row for row in (previous or {}).get("rows", [])}
    notifications: list[dict[str, Any]] = []
    for row in current["rows"]:
        prior = prior_rows.get(row["ticker"])
        if not prior:
            row["comparison"] = {"status": "baseline", "notify": False, "score_delta": None,
                                 "label": "首次建立比較基準", "reasons": []}
            continue
        delta = row["total_score"] - prior["total_score"]
        reasons: list[str] = []
        level_changed = row["level"] != prior["level"]
        event_changed = row["event_score"] != prior["event_score"]
        weight_cross = crossed_threshold(prior["weight_pct"], row["weight_pct"], (5, 10, 15))
        drawdown_cross = crossed_threshold(prior["pnl_pct"], row["pnl_pct"], (-30, -20, -10))
        if level_changed:
            reasons.append(f"影響等級 {LEVELS[prior['level']]['label']} → {LEVELS[row['level']]['label']}")
        if event_changed:
            reasons.append(f"SEC 訊號 {prior['event_score']} → {row['event_score']}")
        if weight_cross is not None:
            reasons.append(f"持股比重跨越 {weight_cross:g}%（{prior['weight_pct']:.1f}% → {row['weight_pct']:.1f}%）")
        if drawdown_cross is not None:
            reasons.append(f"未實現損益跨越 {drawdown_cross:g}%（{prior['pnl_pct']:+.1f}% → {row['pnl_pct']:+.1f}%）")
        if abs(delta) >= 10:
            reasons.append(f"總分變動 {delta:+d} 分")
        notify = level_changed or event_changed or weight_cross is not None or drawdown_cross is not None or abs(delta) >= 10
        if notify:
            label = "影響升高" if delta > 0 else "影響下降" if delta < 0 else "結論變化"
        elif delta:
            label = f"小幅{'升高' if delta > 0 else '下降'}，未跨通知門檻"
        else:
            label = "無實質變化"
        comparison = {
            "status": "changed" if notify else "unchanged",
            "notify": notify,
            "score_delta": delta,
            "previous_score": prior["total_score"],
            "previous_level": prior["level"],
            "label": label,
            "reasons": reasons,
        }
        row["comparison"] = comparison
        if notify:
            notifications.append({"ticker": row["ticker"], "label": label,
                                  "previous_score": prior["total_score"], "current_score": row["total_score"],
                                  "score_delta": delta, "previous_level": prior["level"],
                                  "current_level": row["level"], "reasons": reasons,
                                  "event_reason": row["event_reason"]})
    return notifications


def build_history(snapshot: dict[str, Any], existing: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    existing = existing or {}
    current = existing.get("current")
    if current and current.get("snapshot_id") == snapshot["snapshot_id"]:
        return existing, False
    notifications = compare_rows(snapshot, current)
    history = [snapshot]
    history.extend(row for row in existing.get("history", []) if row.get("snapshot_id") != snapshot["snapshot_id"])
    history = history[:MAX_HISTORY]
    batch_id = stable_hash({"previous": (current or {}).get("snapshot_id"), "current": snapshot["snapshot_id"]}, 12)
    payload = {
        "schema_version": 1,
        "updated_at": snapshot["captured_at"],
        "current_snapshot_id": snapshot["snapshot_id"],
        "previous_snapshot_id": (current or {}).get("snapshot_id"),
        "batch_id": batch_id,
        "notify_count": len(notifications),
        "critical_count": sum(row["current_level"] == "high" and row["score_delta"] > 0 for row in notifications),
        "notification_policy": "只通知等級改變、SEC 訊號分數改變、總分至少變動 10 分，或持股比重／回撤跨越明確門檻；小幅價格波動不通知。",
        "notifications": notifications,
        "current": snapshot,
        "history": history,
    }
    return payload, True


def render_markdown(payload: dict[str, Any]) -> str:
    current = payload["current"]
    lines = [
        "# 實際持股部位影響歷史", "",
        f"> 更新：{payload.get('updated_at') or '—'}｜分數資料日：{current.get('as_of') or '—'}｜快照 `{current['snapshot_id']}`", "",
        "## 本次真正需要注意的變化", "",
    ]
    if payload.get("notifications"):
        for row in payload["notifications"]:
            reasons = "；".join(row["reasons"])
            lines.append(f"- **{row['ticker']}｜{row['label']}**：{row['previous_score']} → {row['current_score']}（{row['score_delta']:+d}）；{reasons}。")
    elif payload.get("previous_snapshot_id"):
        lines.append("- 本次沒有跨越通知門檻的變化；小幅價格波動不重複提醒。")
    else:
        lines.append("- 首次建立比較基準，不發通知；下一個不同快照才開始比較。")
    lines.extend(["", "## 目前排序", "", "| 排名 | 公司 | 總分 | SEC | 部位 | 回撤 | 等級 | 相較前次 |", "|---:|---|---:|---:|---:|---:|---|---|"])
    for index, row in enumerate(current["rows"], 1):
        comparison = row["comparison"]
        delta = "基準" if comparison["score_delta"] is None else f"{comparison['score_delta']:+d}"
        lines.append(f"| {index} | {row['ticker']} | {row['total_score']} | {row['event_score']} | {row['position_score']} | {row['drawdown_score']} | {LEVELS[row['level']]['label']} | {delta}｜{comparison['label']} |")
    lines.extend(["", "## 通知門檻", "", payload["notification_policy"], "",
                  "> 本分數只決定每日閱讀優先順序，不是公司評等、預期報酬或買賣建議。待 AI 覆核候選只提高閱讀優先度，不當成事實結論。", ""])
    return "\n".join(lines)


def append_alert(path: Path, payload: dict[str, Any]) -> None:
    if not payload.get("notifications"):
        return
    lines = ["", "## 💼 實際持股部位影響變化", ""]
    for row in payload["notifications"]:
        lines.append(f"- **{row['ticker']}｜{row['label']}**：{row['previous_score']} → {row['current_score']}（{row['score_delta']:+d}）")
        for reason in row["reasons"]:
            lines.append(f"  - {reason}")
        lines.append(f"  - 目前主要依據：{row['event_reason']}")
    lines.extend(["", "> 這是閱讀優先度變化，不是買進／賣出建議。", ""])
    with path.open("a") as handle:
        handle.write("\n".join(lines))


def append_summary(path: Path, payload: dict[str, Any], is_new: bool) -> None:
    if not is_new:
        return
    lines = ["", "## Portfolio impact snapshot", "",
             f"- Snapshot: `{payload['current_snapshot_id']}`",
             f"- Meaningful changes: {payload['notify_count']}",
             f"- Price date: {payload['current'].get('price_date') or 'missing'}", ""]
    with path.open("a") as handle:
        handle.write("\n".join(lines))


def write_github_output(path: Path, payload: dict[str, Any], is_new: bool) -> None:
    notify_count = payload.get("notify_count", 0) if is_new else 0
    critical_count = payload.get("critical_count", 0) if is_new else 0
    path.write_text("\n".join([
        f"notify_count={notify_count}", f"critical_count={critical_count}",
        f"batch_id={payload.get('batch_id', 'none')}",
        f"snapshot_id={payload.get('current_snapshot_id', 'none')}", "",
    ]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "sec_position_impact_history.json")
    parser.add_argument("--markdown", type=Path, default=ROOT / "60_SEC_Filing_Radar/SEC_Position_Impact_History.md")
    parser.add_argument("--alert-markdown", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    snapshot = build_snapshot(
        load_json(ROOT / "portfolio_holdings.json", {}), load_json(ROOT / "prices.json", {}),
        load_json(ROOT / "sec_filing_alerts.json", {}), load_json(ROOT / "sec_daily_change_candidates.json", {}),
        load_json(ROOT / "sec_daily_editorial.json", {}), load_json(ROOT / "investment_thesis_status.json", {}),
        load_json(ROOT / "sec_advanced_radars.json", {}), load_json(ROOT / "quarterly_financials.json", {}),
    )
    existing = load_json(args.output, {})
    payload, is_new = build_history(snapshot, existing)
    if is_new or not args.output.is_file():
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    if is_new or not args.markdown.is_file():
        args.markdown.write_text(render_markdown(payload))
    if args.alert_markdown and is_new:
        append_alert(args.alert_markdown, payload)
    if args.summary:
        append_summary(args.summary, payload, is_new)
    if args.github_output:
        write_github_output(args.github_output, payload, is_new)
    print(f"部位影響快照：{snapshot['snapshot_id']}；新快照 {int(is_new)}；通知 {payload.get('notify_count', 0) if is_new else 0} 項")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
