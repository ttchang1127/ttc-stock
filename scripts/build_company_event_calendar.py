#!/usr/bin/env python3
"""Build a transparent rolling 30-day calendar for the 14 tracked stocks.

Official overrides win.  Yahoo Finance is only a discovery/estimate layer for
earnings and corporate-action dates; those rows are never labelled official.
When one symbol fails, its previous provider snapshot is retained and marked
stale instead of silently erasing known events.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "company_event_calendar.json"
DEFAULT_MARKDOWN = ROOT / "60_SEC_Filing_Radar" / "Company_Event_Calendar.md"
DEFAULT_OVERRIDES = ROOT / "company_event_overrides.json"
DEFAULT_HOLDINGS = ROOT / "portfolio_holdings.json"

TRACKED = {
    "NVDA": "NVIDIA",
    "TSM": "台積電",
    "MSFT": "Microsoft",
    "META": "Meta",
    "AAPL": "Apple",
    "AMZN": "Amazon",
    "ARM": "Arm",
    "ONDS": "Ondas",
    "TSLA": "Tesla",
    "GOOG": "Alphabet",
    "COHR": "Coherent",
    "MRVL": "Marvell",
    "INTC": "Intel",
    "NOK": "Nokia",
}

PROVIDER_FIELDS = {
    "Earnings Date": "earnings",
    "Ex-Dividend Date": "ex_dividend",
    "Dividend Date": "dividend_payment",
}

TYPE_DEFAULTS = {
    "earnings": (
        "預估財報公布日",
        "財報日可能調整；應優先核對營收、毛利率、自由現金流與管理層指引是否改變。",
    ),
    "ex_dividend": (
        "除息日",
        "自除息日起買進通常無法取得本次股利；價格可能機械式調整，不等於基本面轉弱。",
    ),
    "dividend_record": (
        "股利登記日",
        "用來確認本次股利領取資格；不是新的營運訊號。",
    ),
    "dividend_payment": (
        "股利發放日",
        "股息支付或入帳日期；不應重複視為一筆額外投資報酬。",
    ),
    "shareholder_meeting": (
        "股東會",
        "應查看董事選舉、薪酬、增發授權及其他表決案。",
    ),
    "sec_deadline": (
        "SEC 法定申報期限",
        "這是最晚申報日，不是公司承諾的公布日；公司可提早送件。",
    ),
    "investor_event": (
        "投資人活動",
        "留意管理層是否更新需求、供給、資本支出或財測措辭。",
    ),
}


def parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def date_values(value: Any) -> list[date]:
    values = value if isinstance(value, (list, tuple)) else [value]
    parsed = [parse_date(item) for item in values]
    return [item for item in parsed if item]


def provider_events(ticker: str, raw: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    events: list[dict[str, Any]] = []
    next_earnings = None
    for field, event_type in PROVIDER_FIELDS.items():
        dates = sorted(set(date_values(raw.get(field))))
        if event_type == "earnings" and dates:
            next_earnings = dates[0].isoformat()
        for event_date in dates:
            title, meaning = TYPE_DEFAULTS[event_type]
            events.append({
                "ticker": ticker,
                "date": event_date.isoformat(),
                "type": event_type,
                "title": title,
                "detail": "第三方市場資料日期；公司尚未公告時可能變更。",
                "meaning": meaning,
                "source_label": "Yahoo Finance 行事曆",
                "source_url": f"https://finance.yahoo.com/quote/{ticker}/calendar/",
                "confidence": "estimated" if event_type == "earnings" else "provider",
                "announced_at": None,
            })
    return events, next_earnings


def fetch_provider() -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    import yfinance as yf  # Imported only for the live path; tests stay offline.

    rows: dict[str, dict[str, Any]] = {}
    failures: dict[str, str] = {}
    for ticker in TRACKED:
        try:
            value = yf.Ticker(ticker).calendar
            if value is None:
                value = {}
            if not isinstance(value, dict):
                value = value.to_dict() if hasattr(value, "to_dict") else {}
            rows[ticker] = value
        except Exception as exc:  # Provider failure must remain visible in output.
            failures[ticker] = f"{type(exc).__name__}: {exc}"
    return rows, failures


def load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return fallback


def merge_events(provider: list[dict[str, Any]], official: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Official evidence supersedes a provider row of the same company/type/date.
    merged = {(row["ticker"], row["type"], row["date"]): row for row in provider}
    for row in official:
        merged[(row["ticker"], row["type"], row["date"])] = row
    return list(merged.values())


def event_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return row["ticker"], row["type"], row["date"]


def build_calendar(
    today: date,
    provider_rows: dict[str, dict[str, Any]],
    failures: dict[str, str],
    overrides: dict[str, Any],
    holdings: dict[str, Any],
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    end = today + timedelta(days=30)
    owned = {
        row.get("ticker") for row in holdings.get("holdings", [])
        if row.get("ticker") in TRACKED
    }
    official = [
        dict(row) for row in overrides.get("events", [])
        if row.get("ticker") in TRACKED and parse_date(row.get("date"))
    ]
    previous_companies = (previous or {}).get("companies", {})
    all_provider: list[dict[str, Any]] = []
    companies: dict[str, Any] = {}

    for ticker, name in TRACKED.items():
        prior = previous_companies.get(ticker, {})
        if ticker in provider_rows:
            rows, next_earnings = provider_events(ticker, provider_rows[ticker])
            source_status = "fresh"
            last_success_at = today.isoformat()
        else:
            rows = [dict(row) for row in prior.get("provider_events", [])]
            next_earnings = prior.get("next_earnings_date")
            source_status = "stale" if rows or prior else "unavailable"
            last_success_at = prior.get("last_success_at")
        all_provider.extend(rows)
        companies[ticker] = {
            "name": name,
            "position": "holding" if ticker in owned else "watchlist",
            "source_status": source_status,
            "last_success_at": last_success_at,
            "source_error": failures.get(ticker),
            "next_earnings_date": next_earnings,
            "provider_events": rows,
            "events": [],
        }

    merged = merge_events(all_provider, official)
    visible: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in merged:
        event_date = parse_date(row.get("date"))
        if not event_date or not (today <= event_date <= end):
            continue
        key = event_key(row)
        if key in seen:
            continue
        seen.add(key)
        item = dict(row)
        item["days_until"] = (event_date - today).days
        item["position"] = companies[row["ticker"]]["position"]
        item["company_name"] = TRACKED[row["ticker"]]
        visible.append(item)

    visible.sort(key=lambda row: (
        row["date"],
        0 if row["position"] == "holding" else 1,
        row["ticker"],
        row["type"],
    ))
    for row in visible:
        companies[row["ticker"]]["events"].append(row)

    return {
        "schema_version": 1,
        "generated_at": today.isoformat(),
        "window": {
            "start": today.isoformat(),
            "end": end.isoformat(),
            "days": 30,
            "inclusive": True,
        },
        "methodology": {
            "scope": "14 家個股；ETF 不納入事件日曆或個股曝險。",
            "official_priority": "公司 IR 或 SEC 原文優先，且覆蓋同日同類型的市場資料列。",
            "provider_role": "Yahoo Finance 只補充日期探索；預估財報日不冒充公司正式公告。",
            "unpredictable": "Form 4、8-K／6-K、臨時募資與併購通常無法事前排程，送件後由 SEC 雷達即時補充。",
        },
        "tracked_count": len(TRACKED),
        "owned_stock_count": len(owned),
        "event_count": len(visible),
        "holding_event_count": sum(row["position"] == "holding" for row in visible),
        "provider_failures": failures,
        "events": visible,
        "companies": companies,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    confidence = {"official": "官方已確認", "estimated": "市場預估", "provider": "市場資料"}
    position = {"holding": "實際持股", "watchlist": "觀察名單"}
    lines = [
        "---", "title: 個股未來 30 天事件日曆", "tags:", "  - sec", "  - event-calendar", "---", "",
        "# 🗓 個股未來 30 天事件日曆", "",
        f"> 視窗：**{payload['window']['start']} ～ {payload['window']['end']}（含首尾）**｜"
        f"{payload['event_count']} 件已知事件，其中 {payload['holding_event_count']} 件涉及實際持股。", "",
        "| 日期 | 公司 | 類別 | 事件 | 身分 | 可信度 | 實際意義 | 來源 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in payload["events"]:
        source = f"[{row.get('source_label', '來源')}]({row.get('source_url', '#')})"
        lines.append(
            f"| {row['date']} | **{row['ticker']}** | {TYPE_DEFAULTS.get(row['type'], ('公司事件', ''))[0]} | "
            f"{row['title']}：{row.get('detail', '')} | {position[row['position']]} | "
            f"{confidence.get(row.get('confidence'), row.get('confidence', '未知'))} | {row.get('meaning', '')} | {source} |"
        )
    if not payload["events"]:
        lines.append("| — | — | — | 目前沒有可事前排程的事件 | — | — | 不代表期間內不會出現臨時申報 | — |")
    quiet_owned = [
        ticker for ticker, row in payload["companies"].items()
        if row["position"] == "holding" and not row["events"]
    ]
    lines += [
        "", "## 閱讀規則", "",
        f"- **本期無已知事件的實際持股**：{'、'.join(quiet_owned) if quiet_owned else '無'}。空白不代表沒有風險。",
        "- **官方已確認**：公司 IR 或 SEC 原文；若與市場資料同日同類型，官方來源優先。",
        "- **市場預估／市場資料**：只用於日期探索，財報日期尤其可能變動，需等公司正式公告。",
        "- **無法事前排程**：Form 4、8-K／6-K、臨時募資與併購通常要等申報發生後，改由 SEC 雷達接手。",
        "- **範圍**：只追蹤 14 家個股；ETF 不納入事件日曆或個股曝險。", "",
        f"資料生成日：{payload['generated_at']}", "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--today", help="YYYY-MM-DD; defaults to local date")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES)
    parser.add_argument("--holdings", type=Path, default=DEFAULT_HOLDINGS)
    parser.add_argument("--provider-json", type=Path, help="Offline provider fixture")
    args = parser.parse_args()

    today = date.fromisoformat(args.today) if args.today else date.today()
    overrides = load_json(args.overrides, {"events": []})
    holdings = load_json(args.holdings, {"holdings": []})
    previous = load_json(args.output, None)
    if args.provider_json:
        provider_rows = load_json(args.provider_json, {})
        failures = {}
    else:
        provider_rows, failures = fetch_provider()

    payload = build_calendar(today, provider_rows, failures, overrides, holdings, previous)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not args.output.exists() or args.output.read_text() != serialized:
        args.output.write_text(serialized)
        print(f"updated {args.output}: {payload['event_count']} events")
    else:
        print(f"unchanged {args.output}: {payload['event_count']} events")
    markdown = render_markdown(payload)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    if not args.markdown.exists() or args.markdown.read_text() != markdown:
        args.markdown.write_text(markdown)
        print(f"updated {args.markdown}")
    if failures:
        print("provider fallback: " + ", ".join(sorted(failures)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
