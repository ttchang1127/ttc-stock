#!/usr/bin/env python3
"""Build 4-8 period segment history and one-time transition alerts.

The curated input contains only official absolute amounts or company-reported
mix percentages.  This builder never reverse-engineers a missing amount from a
growth percentage, and never compares observations across a reporting-basis
change.  Alert delivery is computed against the previous generated payload but
is not persisted in the deterministic output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "segment_driver_history_inputs.json"
DEFAULT_OUTPUT = ROOT / "segment_driver_history.json"
DEFAULT_MARKDOWN = ROOT / "60_SEC_Filing_Radar" / "Segment_Driver_History.md"

DISPLAY_TICKERS = [
    "NVDA", "TSM", "MSFT", "META", "AAPL", "AMZN", "ARM",
    "ONDS", "TSLA", "GOOG", "COHR", "MRVL", "INTC", "NOK",
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def rounded(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


def pct_change(current: float | None, prior: float | None) -> float | None:
    if current is None or prior in {None, 0}:
        return None
    return (current / prior - 1) * 100


def margin(profit: float | None, revenue: float | None) -> float | None:
    if profit is None or revenue in {None, 0}:
        return None
    return profit / revenue * 100


def event_id(ticker: str, to_period_end: str, kind: str, item_key: str = "") -> str:
    return f"{ticker}:{to_period_end}:{kind}:{item_key or '-'}"


def validate_inputs(data: dict[str, Any]) -> None:
    companies = data.get("companies") or {}
    if set(companies) != set(DISPLAY_TICKERS):
        missing = sorted(set(DISPLAY_TICKERS) - set(companies))
        extra = sorted(set(companies) - set(DISPLAY_TICKERS))
        raise ValueError(f"公司範圍不符；缺少 {missing}；多出 {extra}")
    for ticker, company in companies.items():
        observations = company.get("observations") or []
        if not 4 <= len(observations) <= 8:
            raise ValueError(f"{ticker} 歷史期數必須為 4～8，實際 {len(observations)}")
        period_ends = [row.get("period_end") for row in observations]
        if any(not value for value in period_ends) or period_ends != sorted(period_ends):
            raise ValueError(f"{ticker} period_end 必須完整且由舊到新排序")
        if len(set(period_ends)) != len(period_ends):
            raise ValueError(f"{ticker} period_end 重複")
        for index, observation in enumerate(observations, 1):
            for key in ("period", "period_end", "basis_id", "basis", "source_url", "source_date", "items"):
                if not observation.get(key):
                    raise ValueError(f"{ticker}#{index} 缺少 {key}")
            if not str(observation["source_url"]).startswith("https://"):
                raise ValueError(f"{ticker}#{index} 官方來源必須為 HTTPS")
            items = observation["items"]
            if len(items) < 2:
                raise ValueError(f"{ticker}#{index} 至少需要兩個項目")
            seen: set[str] = set()
            for item in items:
                item_key = item.get("key")
                if not item_key or not item.get("name") or item_key in seen:
                    raise ValueError(f"{ticker}#{index} 項目 key／name 缺漏或重複")
                seen.add(item_key)
                if item.get("revenue") is None and item.get("share_pct") is None:
                    raise ValueError(f"{ticker}#{index}:{item_key} 缺官方金額或占比")
            if any(item.get("share_pct") is not None for item in items) and observation.get("total_revenue") is None:
                raise ValueError(f"{ticker}#{index} 以占比輸入時必須有 total_revenue")


def build_observation(company: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    total = raw.get("total_revenue")
    items = []
    for item in raw["items"]:
        approximate = item.get("revenue") is None
        revenue = item.get("revenue")
        if revenue is None:
            revenue = float(total) * float(item["share_pct"]) / 100
        items.append({
            "key": item["key"],
            "name": item["name"],
            "revenue": rounded(float(revenue)),
            "profit": item.get("profit"),
            "margin_pct": rounded(margin(item.get("profit"), float(revenue)), 1),
            "share_pct": rounded(float(item["share_pct"]), 1) if item.get("share_pct") is not None else None,
            "is_elimination": bool(item.get("is_elimination")),
            "approximate": approximate,
        })
    if total is None:
        total = sum(float(item["revenue"]) for item in items)
    total = float(total)
    concentration_applicable = company.get("concentration_applicable", True)
    positive_total = sum(
        float(item["revenue"]) for item in items
        if not item["is_elimination"] and float(item["revenue"]) >= 0
    )
    business = [item for item in items if not item["is_elimination"]]
    for item in business:
        if item["share_pct"] is None and concentration_applicable and positive_total:
            item["share_pct"] = rounded(float(item["revenue"]) / positive_total * 100, 1)
    largest = max(business, key=lambda item: item["share_pct"] or -1, default=None)
    shares = [item["share_pct"] for item in business if item["share_pct"] is not None]
    hhi = rounded(sum(value ** 2 for value in shares), 0) if concentration_applicable and shares else None
    prior_year_total = raw.get("prior_year_total_revenue")
    reported_yoy = raw.get("reported_total_yoy_pct")
    total_yoy = pct_change(total, float(prior_year_total)) if prior_year_total not in {None, 0} else reported_yoy
    return {
        "period": raw["period"],
        "period_end": raw["period_end"],
        "basis_id": raw["basis_id"],
        "basis": raw["basis"],
        "source_url": raw["source_url"],
        "source_date": raw["source_date"],
        "source_note": raw.get("source_note"),
        "derived": bool(raw.get("derived")),
        "derivation_note": raw.get("derivation_note"),
        "total_revenue": rounded(total),
        "total_yoy_pct": rounded(float(total_yoy), 1) if total_yoy is not None else None,
        "total_yoy_basis": "calculated" if prior_year_total not in {None, 0} else (
            "company_reported" if reported_yoy is not None else "unavailable"
        ),
        "qoq_pct": None,
        "largest_item": largest["name"] if largest else None,
        "largest_item_key": largest["key"] if largest else None,
        "largest_share_pct": largest["share_pct"] if largest else None,
        "hhi": hhi,
        "sequential_driver": None,
        "sequential_drag": None,
        "items": items,
    }


def add_sequential_metrics(current: dict[str, Any], prior: dict[str, Any]) -> None:
    if current["basis_id"] != prior["basis_id"]:
        return
    current["qoq_pct"] = rounded(pct_change(current["total_revenue"], prior["total_revenue"]), 1)
    prior_items = {item["key"]: item for item in prior["items"]}
    total_delta = current["total_revenue"] - prior["total_revenue"]
    candidates = []
    for item in current["items"]:
        previous = prior_items.get(item["key"])
        if not previous:
            continue
        delta = item["revenue"] - previous["revenue"]
        item["qoq_delta"] = rounded(delta)
        item["qoq_pct"] = rounded(pct_change(item["revenue"], previous["revenue"]), 1)
        item["share_change_pp"] = rounded(item["share_pct"] - previous["share_pct"], 1) \
            if item["share_pct"] is not None and previous["share_pct"] is not None else None
        item["margin_change_pp"] = rounded(item["margin_pct"] - previous["margin_pct"], 1) \
            if item["margin_pct"] is not None and previous["margin_pct"] is not None else None
        item["growth_contribution_pct"] = rounded(delta / total_delta * 100, 1) if total_delta else None
        if not item["is_elimination"]:
            candidates.append(item)
    positive = [item for item in candidates if item.get("qoq_delta", 0) > 0]
    negative = [item for item in candidates if item.get("qoq_delta", 0) < 0]
    driver = max(positive, key=lambda item: item["qoq_delta"], default=None)
    drag = min(negative, key=lambda item: item["qoq_delta"], default=None)
    if driver:
        current["sequential_driver"] = {
            "key": driver["key"], "name": driver["name"],
            "revenue_delta": driver["qoq_delta"],
            "growth_contribution_pct": driver["growth_contribution_pct"],
        }
    if drag:
        current["sequential_drag"] = {
            "key": drag["key"], "name": drag["name"],
            "revenue_delta": drag["qoq_delta"],
            "growth_contribution_pct": drag["growth_contribution_pct"],
        }


def transition_events(ticker: str, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for index in range(1, len(history)):
        prior, current = history[index - 1], history[index]
        common = {
            "ticker": ticker,
            "from_period": prior["period"],
            "to_period": current["period"],
            "from_period_end": prior["period_end"],
            "to_period_end": current["period_end"],
        }
        if current["basis_id"] != prior["basis_id"]:
            events.append({
                **common,
                "id": event_id(ticker, current["period_end"], "basis_break"),
                "type": "basis_break", "severity": "info", "comparable": False,
                "label": "揭露口徑中斷",
                "detail": f"{prior['basis']} → {current['basis']}；不跨口徑計算 QoQ 或轉折。",
            })
            continue
        prior_driver = prior.get("sequential_driver")
        current_driver = current.get("sequential_driver")
        if prior_driver and current_driver and prior_driver["key"] != current_driver["key"]:
            events.append({
                **common,
                "id": event_id(ticker, current["period_end"], "driver_change", current_driver["key"]),
                "type": "driver_change", "severity": "attention", "comparable": True,
                "label": "主要季增驅動更換",
                "detail": f"{prior_driver['name']} → {current_driver['name']}。",
            })
        prior_yoy, current_yoy = prior.get("total_yoy_pct"), current.get("total_yoy_pct")
        if prior_yoy is not None and current_yoy is not None and current_yoy - prior_yoy <= -10:
            events.append({
                **common,
                "id": event_id(ticker, current["period_end"], "yoy_deceleration"),
                "type": "yoy_deceleration", "severity": "warning", "comparable": True,
                "label": "整體 YoY 明顯降速",
                "detail": f"{prior_yoy:+.1f}% → {current_yoy:+.1f}%（{current_yoy - prior_yoy:+.1f}pp）。",
            })
        if prior.get("qoq_pct") is not None and current.get("qoq_pct") is not None \
                and prior["qoq_pct"] >= 0 > current["qoq_pct"]:
            events.append({
                **common,
                "id": event_id(ticker, current["period_end"], "qoq_direction_reversal"),
                "type": "qoq_direction_reversal", "severity": "warning", "comparable": True,
                "label": "合計營收由季增轉季減",
                "detail": f"QoQ {prior['qoq_pct']:+.1f}% → {current['qoq_pct']:+.1f}%。",
            })
        current_items = {item["key"]: item for item in current["items"]}
        prior_items = {item["key"]: item for item in prior["items"]}
        for key in sorted(current_items.keys() & prior_items.keys()):
            item = current_items[key]
            share_change = item.get("share_change_pp")
            if share_change is not None and share_change >= 5:
                events.append({
                    **common,
                    "id": event_id(ticker, current["period_end"], "concentration_jump", key),
                    "type": "concentration_jump", "severity": "warning", "comparable": True,
                    "label": "單一項目占比明顯上升",
                    "detail": f"{item['name']} 占比季增 {share_change:+.1f}pp 至 {item['share_pct']:.1f}%。",
                })
            margin_change = item.get("margin_change_pp")
            if margin_change is not None and margin_change <= -3:
                events.append({
                    **common,
                    "id": event_id(ticker, current["period_end"], "margin_drop", key),
                    "type": "margin_drop", "severity": "warning", "comparable": True,
                    "label": "分部利益率明顯下降",
                    "detail": f"{item['name']} 利益率季減 {margin_change:+.1f}pp 至 {item['margin_pct']:.1f}%。",
                })
        driver = current.get("sequential_driver")
        if driver and driver.get("growth_contribution_pct") is not None and driver["growth_contribution_pct"] > 100:
            events.append({
                **common,
                "id": event_id(ticker, current["period_end"], "offsetting_growth", driver["key"]),
                "type": "offsetting_growth", "severity": "attention", "comparable": True,
                "label": "其他項目抵銷主要成長",
                "detail": f"{driver['name']} 占合計季增 {driver['growth_contribution_pct']:.1f}%；高於 100% 代表其他項目合計衰退。",
            })
    return events


def build_company(ticker: str, company: dict[str, Any]) -> dict[str, Any]:
    history = [build_observation(company, raw) for raw in company["observations"]]
    for index in range(1, len(history)):
        add_sequential_metrics(history[index], history[index - 1])
    events = transition_events(ticker, history)
    latest = history[-1]
    latest_events = [event for event in events if event["to_period_end"] == latest["period_end"]]
    same_basis_run = 1
    for index in range(len(history) - 1, 0, -1):
        if history[index]["basis_id"] != history[index - 1]["basis_id"]:
            break
        same_basis_run += 1
    return {
        "ticker": ticker,
        "name": company.get("name", ticker),
        "unit": company["unit"],
        "coverage": {
            "period_count": len(history), "target_periods": 4, "max_periods": 8,
            "same_basis_run": same_basis_run,
            "status": "complete" if len(history) >= 4 else "insufficient",
        },
        "history": history,
        "transition_events": events,
        "latest_change": {
            "from_period": history[-2]["period"], "to_period": latest["period"],
            "comparable": history[-2]["basis_id"] == latest["basis_id"],
            "events": latest_events,
            "summary": "；".join(event["detail"] for event in latest_events) if latest_events else "相較前季未觸發重大分部轉折門檻。",
        },
    }


def build_payload(data: dict[str, Any]) -> dict[str, Any]:
    validate_inputs(data)
    companies = [build_company(ticker, data["companies"][ticker]) for ticker in DISPLAY_TICKERS]
    all_events = [event for company in companies for event in company["transition_events"]]
    return {
        "schema_version": 1,
        "updated_at": data["updated_at"],
        "tracked_count": len(companies),
        "period_count": sum(len(company["history"]) for company in companies),
        "transition_event_count": len(all_events),
        "methodology": {
            "scope": "14 家個股；每家公司最近 4～8 期；ETF 不納入。",
            "sequential_driver": "同口徑相鄰季度中，營收絕對增量最大的正成長項目；不是獲利貢獻。",
            "alerts": "只對最新季度新增事件通知：驅動更換、YoY 降速至少 10pp、季增轉季減、占比上升至少 5pp、分部利益率下降至少 3pp，或主要驅動貢獻高於 100%。",
            "basis_guardrail": "basis_id 不同即標示口徑中斷；不跨口徑計算 QoQ、成長驅動或轉折。",
            "derivation_guardrail": "只接受官方絕對金額、官方占比與明示的年度減累計算術；不以成長率反推缺失金額。",
        },
        "companies": companies,
    }


def fmt(value: float | None, suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{value:+,.1f}{suffix}"


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "---", "title: 分部成長驅動歷史與轉折通知", "tags:", "  - sec", "  - segment", "  - trend", "---", "",
        "# 📈 分部成長驅動歷史與轉折通知", "",
        f"> 更新：{payload['updated_at']}｜{payload['methodology']['scope']}｜共 {payload['period_count']} 個官方觀察期。", "",
        "## 判讀規則", "",
        f"- **季增驅動**：{payload['methodology']['sequential_driver']}",
        f"- **轉折通知**：{payload['methodology']['alerts']}",
        f"- **口徑防線**：{payload['methodology']['basis_guardrail']}",
        f"- **缺值防線**：{payload['methodology']['derivation_guardrail']}", "",
    ]
    for company in payload["companies"]:
        coverage = company["coverage"]
        lines += [
            f"## {company['ticker']}｜{company['name']}", "",
            f"- **收錄**：{coverage['period_count']}/8 期；最新同口徑連續 {coverage['same_basis_run']} 期。",
            f"- **相較前季**：{company['latest_change']['summary']}", "",
            "| 期間 | 合計營收 | QoQ | YoY | 最大項目／占比 | 季增驅動 | HHI | 來源 |",
            "|---|---:|---:|---:|---|---|---:|---|",
        ]
        for row in company["history"]:
            driver = row.get("sequential_driver")
            driver_text = "—" if not driver else f"{driver['name']}（{fmt(driver['growth_contribution_pct'], '%')}）"
            source_label = "官方表格（年度減累計）" if row.get("derived") else "官方表格"
            lines.append(
                f"| {row['period']} | {row['total_revenue']:,.2f} {company['unit']} | {fmt(row['qoq_pct'], '%')} | "
                f"{fmt(row['total_yoy_pct'], '%')} | {row['largest_item'] or '—'} / {fmt(row['largest_share_pct'], '%')} | "
                f"{driver_text} | {row['hhi'] if row['hhi'] is not None else '—'} | [{source_label}]({row['source_url']}) |"
            )
        latest_events = company["latest_change"]["events"]
        lines += ["", "**最新轉折事件**", ""]
        lines += [f"- {event['label']}：{event['detail']}" for event in latest_events] or ["- 相較前季未觸發重大轉折門檻。"]
        lines.append("")
    return "\n".join(lines)


def append_text(path: Path | None, text: str) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(text.rstrip() + "\n")


def write_github_output(path: Path | None, values: dict[str, Any]) -> None:
    target = path or (Path(os.environ["GITHUB_OUTPUT"]) if os.environ.get("GITHUB_OUTPUT") else None)
    if not target:
        return
    append_text(target, "\n".join(f"{key}={value}" for key, value in values.items()))


def newest_alerts(payload: dict[str, Any], previous: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not previous:
        return []
    old_ids = {
        event["id"]
        for company in previous.get("companies") or []
        for event in company.get("transition_events") or []
    }
    alerts = []
    for company in payload["companies"]:
        latest_end = company["history"][-1]["period_end"]
        alerts.extend(
            event for event in company["transition_events"]
            if event["to_period_end"] == latest_end
            and event["id"] not in old_ids
            and event["type"] != "basis_break"
        )
    return alerts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--alert-markdown", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    previous = load_json(args.output) if args.output.exists() else None
    payload = build_payload(load_json(args.input))
    alerts = newest_alerts(payload, previous)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(render_markdown(payload))
    digest = hashlib.sha256("|".join(sorted(event["id"] for event in alerts)).encode()).hexdigest()[:12] if alerts else "none"
    if alerts:
        lines = ["## 📈 分部成長驅動轉折", ""]
        lines += [f"- **{event['ticker']}｜{event['label']}**：{event['detail']}" for event in alerts]
        append_text(args.alert_markdown, "\n".join(lines) + "\n")
        append_text(args.summary, "\n".join(lines) + "\n")
    write_github_output(args.github_output, {
        "notify_count": len(alerts),
        "critical_count": sum(event["severity"] == "warning" for event in alerts),
        "batch_id": f"segment-{digest}",
    })
    print(
        f"分部歷史：{payload['tracked_count']} 家／{payload['period_count']} 期；"
        f"轉折 {payload['transition_event_count']}；本次新通知 {len(alerts)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
