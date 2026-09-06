#!/usr/bin/env python3
"""Build traceable pre/post earnings verification cards for 14 stocks.

The builder joins only committed, source-traceable inputs.  It does not fetch
analyst consensus and never invents missing guidance.  Pre-event cards use the
next discovered earnings date, unresolved company guidance and thesis
invalidation rules.  Post-event cards use the latest reported quarter, prior
quarter/year comparisons, the latest completed guidance backtest and the
persisted objective thesis state.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "earnings_verification_cards.json"
DEFAULT_MARKDOWN = ROOT / "60_SEC_Filing_Radar" / "Earnings_Verification_Cards.md"

DISPLAY_TICKERS = [
    "NVDA", "TSM", "MSFT", "META", "AAPL", "AMZN", "ARM",
    "ONDS", "TSLA", "GOOG", "COHR", "MRVL", "INTC", "NOK",
]
DATA_TICKER = {"GOOG": "GOOGL"}
GUIDANCE_FIELDS = [
    "period", "period_end", "low", "high", "actual",
    "guidance_date", "guidance_source_url",
]


def taipei_today() -> date:
    return datetime.now(ZoneInfo("Asia/Taipei")).date()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def metric_value(period: dict[str, Any] | None, metric: str) -> float | None:
    value = (period or {}).get("values", {}).get(metric)
    if isinstance(value, dict):
        value = value.get("value")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def percent_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in {None, 0}:
        return None
    return (current / previous - 1) * 100


def point_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return (current - previous) * 100


def metric_state(metric: str, value: float | None, yoy: float | None) -> tuple[str, str]:
    if value is None:
        return "unknown", "缺值，不能判斷"
    if metric == "revenue":
        if yoy is None:
            return "unknown", "缺去年同期，不能判斷 YoY"
        if yoy >= 10:
            return "improved", f"營收 YoY +{yoy:.1f}%"
        if yoy <= -10:
            return "risk", f"營收 YoY {yoy:.1f}%"
        return "stable", f"營收 YoY {yoy:+.1f}%"
    if metric in {"gross_margin", "operating_margin"}:
        label = "毛利率" if metric == "gross_margin" else "營業利益率"
        if yoy is None:
            return "unknown", f"缺去年同期，不能判斷{label}變化"
        if yoy >= 2:
            return "improved", f"{label} YoY +{yoy:.1f}pp"
        if yoy <= -2:
            return "risk", f"{label} YoY {yoy:.1f}pp"
        return "stable", f"{label} YoY {yoy:+.1f}pp"
    if metric == "free_cash_flow":
        return ("improved", "自由現金流為正") if value > 0 else ("risk", "自由現金流為負")
    if metric == "diluted_shares":
        if yoy is None:
            return "unknown", "缺去年同期，不能判斷稀釋"
        if yoy >= 10:
            return "risk", f"稀釋股數 YoY +{yoy:.1f}%"
        if yoy <= -2:
            return "improved", f"稀釋股數 YoY {yoy:.1f}%"
        return "stable", f"稀釋股數 YoY {yoy:+.1f}%"
    return "stable", "已取得數值"


def build_kpis(company: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    periods = company.get("periods") or []
    if not periods:
        return [], None
    latest = periods[0]
    prior = periods[1] if len(periods) > 1 else None
    year_ago = periods[4] if len(periods) > 4 else None
    definitions = [
        ("revenue", "營收", "amount"),
        ("gross_margin", "毛利率", "percent"),
        ("operating_margin", "營業利益率", "percent"),
        ("free_cash_flow", "自由現金流", "amount"),
        ("diluted_shares", "稀釋股數", "shares"),
    ]
    rows = []
    for key, label, display in definitions:
        value = metric_value(latest, key)
        prior_value = metric_value(prior, key)
        year_value = metric_value(year_ago, key)
        if display == "percent":
            qoq = point_change(value, prior_value)
            yoy = point_change(value, year_value)
        elif key == "free_cash_flow":
            # A percentage change that starts from zero/negative FCF or crosses
            # below zero is not economically meaningful.  Keep the actual amount
            # and state, but do not print an enormous rate that could mislead.
            qoq = percent_change(value, prior_value) if value is not None and value >= 0 and prior_value and prior_value > 0 else None
            yoy = percent_change(value, year_value) if value is not None and value >= 0 and year_value and year_value > 0 else None
        else:
            qoq = percent_change(value, prior_value)
            yoy = percent_change(value, year_value)
        state, interpretation = metric_state(key, value, yoy)
        rows.append({
            "metric": key,
            "label": label,
            "display": display,
            "value": value,
            "qoq": qoq,
            "yoy": yoy,
            "state": state,
            "interpretation": interpretation,
        })
    source = {
        "period_end": latest.get("period_end"),
        "filing_date": latest.get("filing_date"),
        "form": latest.get("form"),
        "accession": latest.get("accession"),
        "source_url": latest.get("url") or company.get("official_results_url"),
        "quality_notes": latest.get("quality_notes") or [],
        "currency": company.get("currency", "USD"),
        "source_basis": company.get("source_basis"),
    }
    return rows, source


def unresolved_guidance(company: dict[str, Any]) -> dict[str, Any]:
    rows = [dict(row) for row in (company.get("guidance") or []) if row.get("actual") is None]
    return {
        "status": company.get("guidance_status", "unavailable"),
        "rows": rows,
        "note": company.get("guidance_note"),
        "source_date": company.get("guidance_source_date"),
        "source_url": company.get("guidance_source_url"),
    }


def completed_guidance(company: dict[str, Any]) -> dict[str, Any]:
    records = company.get("records") or []
    if not records:
        return {
            "status": company.get("status", "unavailable"),
            "note": company.get("note"),
            "review_url": company.get("review_url"),
            "record": None,
        }
    raw = records[-1]
    row = dict(zip(GUIDANCE_FIELDS, raw))
    low, high, actual = row["low"], row["high"], row["actual"]
    if actual < low:
        outcome = "below"
        outcome_label = "低於指引"
    elif actual > high:
        outcome = "above"
        outcome_label = "高於指引"
    else:
        outcome = "within"
        outcome_label = "落在區間"
    midpoint = (low + high) / 2
    row.update({
        "metric": company.get("metric"),
        "unit": company.get("unit"),
        "comparison_basis": company.get("comparison_basis"),
        "outcome": outcome,
        "outcome_label": outcome_label,
        "vs_midpoint_pct": (actual / midpoint - 1) * 100 if midpoint else None,
    })
    return {"status": "available", "note": None, "review_url": None, "record": row}


def next_earnings(calendar_company: dict[str, Any], today: date) -> dict[str, Any] | None:
    target = calendar_company.get("next_earnings_date")
    if not target:
        return None
    event_date = date.fromisoformat(target)
    matching = next(
        (row for row in calendar_company.get("provider_events", [])
         if row.get("type") == "earnings" and row.get("date") == target),
        {},
    )
    return {
        "date": target,
        "days_until": (event_date - today).days,
        "confidence": matching.get("confidence", "estimated"),
        "source_label": matching.get("source_label"),
        "source_url": matching.get("source_url"),
        "source_status": calendar_company.get("source_status"),
        "last_success_at": calendar_company.get("last_success_at"),
    }


def thesis_card(company: dict[str, Any]) -> dict[str, Any]:
    current_items = company.get("items") or []
    prior_items = {row.get("id"): row for row in (company.get("previous") or {}).get("items", [])}
    items = []
    for row in current_items:
        prior = prior_items.get(row.get("id"), {})
        items.append({
            "id": row.get("id"),
            "title": row.get("title"),
            "status": row.get("status"),
            "label": row.get("label"),
            "previous_status": prior.get("status"),
            "previous_label": prior.get("label"),
            "changed_from_previous_quarter": bool(prior and prior.get("status") != row.get("status")),
            "evidence": row.get("evidence"),
            "invalidation": row.get("invalidation"),
        })
    return {
        "status": company.get("status", "unavailable"),
        "label": company.get("label", "資料不足"),
        "previous_status": (company.get("previous") or {}).get("status"),
        "previous_label": (company.get("previous") or {}).get("label"),
        "changed_from_previous_quarter": bool(
            company.get("previous") and
            company.get("status") != company.get("previous", {}).get("status")
        ),
        "counts": company.get("counts") or {},
        "items": items,
        "master_report": company.get("master_report"),
    }


def checkpoints(guidance: dict[str, Any], thesis: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    if guidance["rows"]:
        periods = []
        for row in guidance["rows"]:
            if row.get("period") not in periods:
                periods.append(row.get("period"))
        rows.append({
            "topic": "管理層指引",
            "question": f"實際結果是否落在 {'、'.join(periods)} 的官方指引區間？",
            "why": "指引只能與相同期間、相同口徑的實績比較。",
        })
    else:
        rows.append({
            "topic": "管理層指引",
            "question": "公司是否首次提供可比較的量化指引，或更新原有全年目標？",
            "why": "沒有量化區間時不計命中率，也不以市場共識補值。",
        })
    rows.extend([
        {
            "topic": "營運連續性",
            "question": "營收、毛利率與營業利益率是否延續八季方向？",
            "why": "單季驚喜可能只是季節性，需同時比較 QoQ 與 YoY。",
        },
        {
            "topic": "現金與每股品質",
            "question": "自由現金流是否改善，稀釋股數是否跨越 10% 風險門檻？",
            "why": "成長若沒有轉成現金或被稀釋，股東實際受益可能下降。",
        },
    ])
    invalidated = [row for row in thesis["items"] if row["status"] == "invalidated"]
    focus = invalidated or thesis["items"][:1]
    for row in focus[:1]:
        rows.append({
            "topic": f"論點：{row['title']}",
            "question": f"本季證據是否仍命中／接近失效條件：{row['invalidation']}",
            "why": row.get("evidence") or "依最新季度證據核對。",
        })
    return rows[:4]


def build_payload(today: date, inputs: dict[str, Any]) -> dict[str, Any]:
    calendar = inputs["calendar"]
    holdings = {
        row.get("ticker") for row in inputs["holdings"].get("holdings", [])
        if row.get("ticker") in DISPLAY_TICKERS
    }
    companies = []
    for display_ticker in DISPLAY_TICKERS:
        data_ticker = DATA_TICKER.get(display_ticker, display_ticker)
        quarterly_company = inputs["quarterly"].get("companies", {}).get(data_ticker, {})
        kpis, latest_result = build_kpis(quarterly_company)
        if latest_result and latest_result.get("filing_date"):
            latest_result["days_since_filing"] = (
                today - date.fromisoformat(latest_result["filing_date"])
            ).days
            latest_result["review_due"] = 0 <= latest_result["days_since_filing"] <= 14
        forward = unresolved_guidance(
            inputs["forward"].get("companies", {}).get(data_ticker, {})
        )
        history = completed_guidance(
            inputs["guidance_history"].get("companies", {}).get(data_ticker, {})
        )
        thesis = thesis_card(
            inputs["thesis_status"].get("companies", {}).get(data_ticker, {})
        )
        earnings = next_earnings(
            calendar.get("companies", {}).get(display_ticker, {}), today
        )
        pre_due = bool(earnings and 0 <= earnings["days_until"] <= 7)
        upcoming = bool(earnings and 0 <= earnings["days_until"] <= 30)
        post_due = bool(latest_result and latest_result.get("review_due"))
        risk_count = int((thesis.get("counts") or {}).get("invalidated", 0))
        position = "holding" if display_ticker in holdings else "watchlist"
        attention_score = (
            (100 if position == "holding" else 0)
            + (80 if post_due else 0)
            + ((14 - latest_result["days_since_filing"]) if post_due else 0)
            + (90 if pre_due else 0)
            + (50 if risk_count >= 2 else 30 if risk_count == 1 else 0)
            + (max(0, 30 - earnings["days_until"]) if upcoming else 0)
        )
        if post_due:
            phase = "post_review_due"
            phase_label = "財報後 14 天核對期"
        elif pre_due:
            phase = "preparation_due"
            phase_label = "財報前 7 天準備期"
        elif upcoming:
            phase = "upcoming"
            phase_label = "30 天內將公布"
        elif earnings:
            phase = "scheduled_later"
            phase_label = "已知日期，尚未進入 30 天"
        else:
            phase = "date_unavailable"
            phase_label = "財報日期待公告"
        companies.append({
            "ticker": display_ticker,
            "data_ticker": data_ticker,
            "name": calendar.get("companies", {}).get(display_ticker, {}).get("name"),
            "position": position,
            "attention_score": attention_score,
            "phase": phase,
            "phase_label": phase_label,
            "next_earnings": earnings,
            "pre_event": {
                "preparation_due": pre_due,
                "guidance": forward,
                "checkpoints": checkpoints(forward, thesis),
                "thesis": thesis,
            },
            "post_event": {
                "review_due": post_due,
                "latest_result": latest_result,
                "kpis": kpis,
                "completed_guidance": history,
                "thesis": thesis,
            },
        })

    companies.sort(key=lambda row: (
        -row["attention_score"],
        0 if row["position"] == "holding" else 1,
        row["next_earnings"]["days_until"] if row["next_earnings"] else 9999,
        row["ticker"],
    ))
    return {
        "schema_version": 1,
        "generated_at": today.isoformat(),
        "source_dates": {
            "event_calendar": calendar.get("generated_at"),
            "quarterly_financials": inputs["quarterly"].get("generated_at"),
            "forward_guidance": inputs["forward"].get("updated_at"),
            "guidance_history": inputs["guidance_history"].get("as_of"),
            "thesis_status": inputs["thesis_status"].get("updated_at"),
        },
        "methodology": {
            "pre_window_days": 7,
            "post_window_days": 14,
            "scope": "14 家個股；實際持股優先，ETF 不納入。",
            "guidance": "只使用公司 IR 或 SEC 原文建檔的管理層指引；不使用分析師共識。",
            "post_review": "比較最新季度與前季／去年同期，並引用既有投資論點規則；缺值不補猜。",
        },
        "tracked_count": len(companies),
        "holding_count": len(holdings),
        "preparation_due_count": sum(row["pre_event"]["preparation_due"] for row in companies),
        "post_review_due_count": sum(row["post_event"]["review_due"] for row in companies),
        "pending_guidance_company_count": sum(bool(row["pre_event"]["guidance"]["rows"]) for row in companies),
        "default_ticker": companies[0]["ticker"] if companies else None,
        "companies": companies,
    }


def format_number(value: float | None, decimals: int = 1) -> str:
    return "—" if value is None else f"{value:,.{decimals}f}"


def format_amount(value: float | None, currency: str) -> str:
    if value is None:
        return "—"
    divisor, suffix = (1e9, "B") if abs(value) >= 1e9 else (1e6, "M")
    return f"{currency} {format_number(value / divisor)}{suffix}"


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "---", "title: 財報前後驗證追蹤卡", "tags:", "  - earnings", "  - verification", "---", "",
        "# 🎯 財報前後驗證追蹤卡", "",
        f"> 更新日 **{payload['generated_at']}**｜財報前 7 天待準備 {payload['preparation_due_count']} 家｜"
        f"財報後 14 天待核對 {payload['post_review_due_count']} 家。", "",
        "| 優先 | 公司 | 身分 | 下一財報日 | 階段 | 最新已核對期 | 論點狀態 |",
        "|---:|---|---|---|---|---|---|",
    ]
    for index, row in enumerate(payload["companies"], 1):
        next_date = (row.get("next_earnings") or {}).get("date") or "待公告"
        latest = row["post_event"].get("latest_result") or {}
        thesis = row["post_event"]["thesis"]
        lines.append(
            f"| {index} | **{row['ticker']}** | {'實際持股' if row['position'] == 'holding' else '觀察名單'} | "
            f"{next_date} | {row['phase_label']} | {latest.get('period_end') or '—'} | {thesis.get('label') or '資料不足'} |"
        )
    for row in payload["companies"]:
        latest = row["post_event"].get("latest_result") or {}
        earnings = row.get("next_earnings") or {}
        lines += ["", f"## {row['ticker']}｜{row['phase_label']}", ""]
        if earnings:
            lines.append(
                f"- **下一財報日**：{earnings['date']}（{earnings['days_until']} 天後；"
                f"{('公司已確認' if earnings.get('confidence') == 'official' else '市場預估，仍可能變動')}）"
            )
        else:
            lines.append("- **下一財報日**：尚未取得可靠日期。")
        guidance = row["pre_event"]["guidance"]
        if guidance["rows"]:
            lines.append("- **待驗證管理層指引**：")
            for item in guidance["rows"]:
                low, high = item.get("low"), item.get("high")
                value = f"{format_number(low)}～{format_number(high)}" if low is not None and high is not None else format_number(low if low is not None else high)
                lines.append(f"  - {item['period']}｜{item['metric']}：{value} {item.get('unit') or ''}｜[官方來源]({item['source_url']})")
        else:
            lines.append(f"- **待驗證管理層指引**：{guidance.get('note') or '目前沒有可比量化區間；不以市場共識補值。'}")
        lines.append("- **財報前檢查題**：")
        for item in row["pre_event"]["checkpoints"]:
            lines.append(f"  - {item['topic']}：{item['question']}（{item['why']}）")
        lines.append(
            f"- **最近財報後核對**：{latest.get('period_end') or '—'}｜{latest.get('form') or '—'}｜"
            f"申報 {latest.get('filing_date') or '—'}"
            + (f"｜[原文]({latest['source_url']})" if latest.get("source_url") else "")
        )
        currency = latest.get("currency", "USD")
        for item in row["post_event"]["kpis"]:
            if item["display"] == "percent":
                value = f"{format_number(item['value'] * 100)}%" if item["value"] is not None else "—"
                yoy = f"{item['yoy']:+.1f}pp" if item["yoy"] is not None else "—"
            elif item["display"] == "shares":
                value = f"{format_number((item['value'] or 0) / 1e6)}M 股" if item["value"] is not None else "—"
                yoy = f"{item['yoy']:+.1f}%" if item["yoy"] is not None else "—"
            else:
                value = format_amount(item["value"], currency)
                yoy = f"{item['yoy']:+.1f}%" if item["yoy"] is not None else "—"
            lines.append(f"  - {item['label']}：{value}｜YoY {yoy}｜{item['interpretation']}")
        completed = row["post_event"]["completed_guidance"]
        if completed.get("record"):
            item = completed["record"]
            lines.append(
                f"- **最近可驗證指引**：{item['period']} {item['metric']}，"
                f"指引 {format_number(item['low'])}～{format_number(item['high'])} {item.get('unit') or ''}，"
                f"實際 {format_number(item['actual'])}，**{item['outcome_label']}**｜[指引原文]({item['guidance_source_url']})"
            )
        else:
            lines.append(f"- **最近可驗證指引**：{completed.get('note') or '無一致口徑可比資料。'}")
        thesis = row["post_event"]["thesis"]
        lines.append(f"- **客觀結論**：{thesis['label']}；這是財務代理條件判讀，不是買進／賣出建議。")
        for item in thesis["items"]:
            lines.append(f"  - {item['title']}：{item['label']}｜{item['evidence']}｜失效條件：{item['invalidation']}")
    lines += [
        "", "## 方法與限制", "",
        "- 財報前 7 天進入準備期；財報申報後 14 天標記為核對期。",
        "- 財報日期若標為市場預估，仍可能變動；必須等公司 IR 正式公告才能視為確認。",
        "- 指引只使用已建檔的公司官方區間；分析師共識、模型預測與新聞轉述不混入。",
        "- 財報後判讀只描述已公布數字、前季／去年同期變化與論點規則，不預測股價。",
        "- 只追蹤 14 家個股；ETF 不納入。", "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--today", help="YYYY-MM-DD；預設採 Asia/Taipei 日期")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--event-calendar", type=Path, default=ROOT / "company_event_calendar.json")
    parser.add_argument("--quarterly", type=Path, default=ROOT / "quarterly_financials.json")
    parser.add_argument("--forward", type=Path, default=ROOT / "forward_looking_inputs.json")
    parser.add_argument("--guidance-history", type=Path, default=ROOT / "guidance_history.json")
    parser.add_argument("--thesis-status", type=Path, default=ROOT / "investment_thesis_status.json")
    parser.add_argument("--holdings", type=Path, default=ROOT / "portfolio_holdings.json")
    args = parser.parse_args()

    today = date.fromisoformat(args.today) if args.today else taipei_today()
    inputs = {
        "calendar": load_json(args.event_calendar),
        "quarterly": load_json(args.quarterly),
        "forward": load_json(args.forward),
        "guidance_history": load_json(args.guidance_history),
        "thesis_status": load_json(args.thesis_status),
        "holdings": load_json(args.holdings),
    }
    payload = build_payload(today, inputs)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    args.output.write_text(serialized)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(render_markdown(payload))
    print(
        f"財報驗證卡：{payload['tracked_count']} 家；財報前待準備 "
        f"{payload['preparation_due_count']}；財報後待核對 {payload['post_review_due_count']}；"
        f"預設 {payload['default_ticker']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
