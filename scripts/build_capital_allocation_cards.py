#!/usr/bin/env python3
"""Build source-traceable capital-allocation and shareholder-value cards."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from compute_financial_health import total_debt


ROOT = Path(__file__).resolve().parents[1]
DISPLAY_TICKERS = [
    "NVDA", "TSM", "MSFT", "META", "AAPL", "AMZN", "ARM",
    "ONDS", "TSLA", "GOOG", "COHR", "MRVL", "INTC", "NOK",
]
ALIASES = {"GOOG": "GOOGL"}
DIMENSION_LABELS = {
    "fcf": "現金創造", "payout": "股東回饋", "shares": "回購實效",
    "debt": "負債承擔", "capex": "再投資強度",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def value(period: dict[str, Any], key: str) -> float | None:
    node = period.get(key)
    return node.get("value") if isinstance(node, dict) else None


def unit(period: dict[str, Any]) -> str | None:
    for key in ("revenue", "operating_cash_flow", "assets"):
        node = period.get(key) or {}
        if node.get("unit") and node.get("unit") != "shares":
            return node["unit"]
    return None


def ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return current / previous - 1


def filing_url(cik: str, accession: str | None) -> str | None:
    if not accession:
        return None
    return (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
        f"{accession.replace('-', '')}/{accession}-index.html"
    )


def source_for_period(company: dict[str, Any], period: dict[str, Any]) -> dict[str, Any]:
    node = next((period.get(key) for key in (
        "revenue", "operating_cash_flow", "assets", "capex",
    ) if isinstance(period.get(key), dict) and period[key].get("accession")), {})
    accession = node.get("accession")
    return {
        "form": node.get("form"), "filed": node.get("filed"), "accession": accession,
        "url": filing_url(company.get("cik", "0"), accession),
    }


def share_series_quality(periods: list[dict[str, Any]]) -> tuple[bool, str | None]:
    shares = [(row.get("fiscal_year_end"), value(row, "diluted_shares")) for row in periods]
    known = [(date, amount) for date, amount in shares if amount not in (None, 0)]
    for (current_date, current), (prior_date, prior) in zip(known, known[1:]):
        multiple = current / prior
        if multiple > 20 or multiple < 0.05:
            return False, (
                f"{current_date} 與 {prior_date} 的稀釋加權平均股數相差 {max(multiple, 1 / multiple):,.1f} 倍，"
                "疑有拆股或 XBRL 縮放差異，停止跨期比較。"
            )
    return True, None


def annual_row(company: dict[str, Any], period: dict[str, Any], prior: dict[str, Any] | None,
               shares_valid: bool, share_note: str | None) -> dict[str, Any]:
    currency = unit(period)
    revenue = value(period, "revenue")
    ocf = value(period, "operating_cash_flow")
    capex = value(period, "capex")
    fcf = ocf - capex if ocf is not None and capex is not None else None
    buybacks = value(period, "buybacks")
    dividends = value(period, "dividends_paid")
    payout_complete = buybacks is not None and dividends is not None
    shareholder_returns = buybacks + dividends if payout_complete else None
    shares = value(period, "diluted_shares")
    prior_shares = value(prior, "diluted_shares") if prior else None
    share_change = pct_change(shares, prior_shares) if shares_valid else None
    debt, debt_note, debt_parts = total_debt(period)
    prior_debt = total_debt(prior)[0] if prior else None
    debt_change = pct_change(debt, prior_debt)
    cash = value(period, "cash")
    investments = value(period, "short_term_investments")
    net_cash = cash + (investments or 0) - debt if cash is not None and debt is not None else None
    return {
        "fiscal_year_end": period.get("fiscal_year_end"), "currency": currency,
        "revenue": revenue, "operating_cash_flow": ocf, "capex": capex, "free_cash_flow": fcf,
        "fcf_margin": ratio(fcf, revenue), "fcf_conversion": ratio(fcf, ocf),
        "capex_intensity": ratio(capex, revenue),
        "buybacks": buybacks, "dividends_paid": dividends,
        "shareholder_returns": shareholder_returns, "payout_complete": payout_complete,
        "payout_to_fcf": ratio(shareholder_returns, fcf) if fcf is not None and fcf > 0 else None,
        "diluted_shares": shares, "share_change": share_change,
        "share_comparable": shares_valid and shares is not None and prior_shares is not None,
        "share_note": share_note if not shares_valid else (
            None if shares is not None and prior_shares is not None else "缺本期或前期稀釋加權平均股數，無法判斷淨稀釋。"
        ),
        "total_debt": debt, "debt_change": debt_change, "debt_note": debt_note,
        "debt_components": {label: amount for label, amount in debt_parts},
        "cash_and_short_investments": cash + (investments or 0) if cash is not None else None,
        "net_cash": net_cash,
        "source": source_for_period(company, period),
    }


def signal(identifier: str, state: str, evidence: str, score: int = 0) -> dict[str, Any]:
    return {
        "id": identifier, "label": DIMENSION_LABELS[identifier], "state": state,
        "score": score, "evidence": evidence,
    }


def analyse(latest: dict[str, Any]) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    signals = []
    fcf = latest.get("free_cash_flow")
    conversion = latest.get("fcf_conversion")
    if fcf is None:
        signals.append(signal("fcf", "unavailable", "缺營運現金流或資本支出，無法計算 FCF。"))
    elif fcf < 0:
        signals.append(signal("fcf", "risk", "自由現金流為負，外部融資或現金存量的重要性提高。", -3))
    elif conversion is not None and conversion >= 0.7:
        signals.append(signal("fcf", "support", f"FCF 為正，且保留營運現金流的 {conversion:.0%}。", 3))
    elif conversion is not None and conversion < 0.3:
        signals.append(signal("fcf", "attention", f"FCF 為正，但資本支出後只保留營運現金流的 {conversion:.0%}。", 1))
    else:
        signals.append(signal("fcf", "support", "自由現金流為正。", 2))

    if not latest.get("payout_complete"):
        signals.append(signal("payout", "unavailable", "回購或股利 XBRL 標籤不完整，不把缺值當成 0。"))
    else:
        payout, coverage = latest.get("shareholder_returns"), latest.get("payout_to_fcf")
        if payout == 0:
            signals.append(signal("payout", "neutral", "未記錄現金回購或股利；現金保留在公司內部。"))
        elif coverage is None:
            signals.append(signal("payout", "risk" if fcf is not None and fcf < 0 else "attention",
                                  "已有回購／股利，但 FCF 非正，回饋來源需核對現金或融資。", -2 if fcf is not None and fcf < 0 else -1))
        elif coverage <= 1:
            signals.append(signal("payout", "support", f"回購加股利使用 FCF 的 {coverage:.0%}，目前由當年 FCF 覆蓋。", 1))
        elif coverage > 1.5:
            signals.append(signal("payout", "risk", f"回購加股利為 FCF 的 {coverage:.0%}，明顯超過當年 FCF。", -2))
        else:
            signals.append(signal("payout", "attention", f"回購加股利為 FCF 的 {coverage:.0%}，超過當年 FCF。", -1))

    share_change = latest.get("share_change")
    buybacks = latest.get("buybacks")
    if not latest.get("share_comparable"):
        signals.append(signal("shares", "unavailable", latest.get("share_note") or "缺可比稀釋股數。"))
    elif share_change <= -0.01:
        signals.append(signal("shares", "support", f"稀釋加權平均股數年減 {abs(share_change):.1%}；回購／股份變動的淨效果有利。", 2))
    elif share_change > 0.02:
        phrase = "即使有回購，仍未抵銷所有新增股份來源" if buybacks and buybacks > 0 else "淨稀釋明顯"
        signals.append(signal("shares", "risk", f"稀釋加權平均股數年增 {share_change:.1%}，{phrase}。", -2))
    elif share_change > 0.005:
        signals.append(signal("shares", "attention", f"稀釋加權平均股數年增 {share_change:.1%}；存在溫和淨稀釋。", -1))
    else:
        signals.append(signal("shares", "neutral", f"稀釋加權平均股數年變動 {share_change:+.1%}，大致持平。"))

    debt_change, net_cash = latest.get("debt_change"), latest.get("net_cash")
    if latest.get("total_debt") is None:
        signals.append(signal("debt", "unavailable", latest.get("debt_note") or "缺有息負債標籤。"))
    elif debt_change is not None and debt_change > 0.2 and fcf is not None and fcf < 0:
        signals.append(signal("debt", "risk", f"有息負債年增 {debt_change:.0%}，同時 FCF 為負。", -2))
    elif net_cash is not None and net_cash > 0:
        signals.append(signal("debt", "support", "現金及短期投資高於有息負債，維持淨現金。", 1))
    elif debt_change is not None and debt_change > 0.2:
        signals.append(signal("debt", "attention", f"有息負債年增 {debt_change:.0%}，需追蹤資金用途。", -1))
    else:
        signals.append(signal("debt", "neutral", "未見 FCF 為負且負債大幅增加的組合。"))

    capex_intensity = latest.get("capex_intensity")
    if capex_intensity is None:
        signals.append(signal("capex", "unavailable", "缺資本支出或營收，無法計算再投資強度。"))
    elif fcf is not None and fcf < 0 and capex_intensity >= 0.2:
        signals.append(signal("capex", "attention", f"資本支出為營收的 {capex_intensity:.1%}，且 FCF 為負；高投入尚未轉為當期現金。", -1))
    else:
        signals.append(signal("capex", "context", f"資本支出為營收的 {capex_intensity:.1%}；高低本身不代表投資成敗。"))

    known = sum(row["state"] != "unavailable" for row in signals)
    score = sum(row["score"] for row in signals)
    if known < 3:
        status, label = "insufficient", "資料不足，暫不判斷"
    elif score >= 3:
        status, label = "support", "資本配置支持股東價值"
    elif score <= -3:
        status, label = "pressure", "資本配置形成壓力"
    else:
        status, label = "neutral", "資本配置中性／需持續驗證"
    return signals, score, {"status": status, "label": label, "known_dimensions": known, "total_dimensions": 5}


def build_company(display_ticker: str, company: dict[str, Any], holdings: set[str]) -> dict[str, Any]:
    periods = company.get("periods", [])[:4]
    if not periods:
        raise ValueError(f"{display_ticker} 沒有年度財務資料")
    shares_valid, share_note = share_series_quality(periods)
    years = [annual_row(company, row, periods[index + 1] if index + 1 < len(periods) else None,
                        shares_valid, share_note) for index, row in enumerate(periods)]
    signals, score, conclusion = analyse(years[0])
    latest = years[0]
    return {
        "ticker": display_ticker, "data_ticker": ALIASES.get(display_ticker, display_ticker),
        "name": company.get("entity_name"), "position": "holding" if display_ticker in holdings else "watchlist",
        "currency": latest.get("currency"), "latest_period": latest.get("fiscal_year_end"),
        "status": conclusion["status"], "label": conclusion["label"], "score": score,
        "coverage": {"known": conclusion["known_dimensions"], "total": conclusion["total_dimensions"],
                     "missing": [row["label"] for row in signals if row["state"] == "unavailable"]},
        "signals": signals, "latest": latest, "years": years,
        "conclusion": (
            f"{conclusion['label']}；依 {conclusion['known_dimensions']}/5 個可判讀構面，"
            "只評估已公布現金流、股東回饋、淨股份效果、負債與資本支出，不推測管理層動機。"
        ),
    }


def build_payload(financials: dict[str, Any], holdings_payload: Any) -> dict[str, Any]:
    holding_rows = holdings_payload if isinstance(holdings_payload, list) else holdings_payload.get("holdings", [])
    holdings = {row["ticker"] for row in holding_rows if row.get("shares", 0)}
    companies = []
    for ticker in DISPLAY_TICKERS:
        data_ticker = ALIASES.get(ticker, ticker)
        company = financials.get("companies", {}).get(data_ticker)
        if not company:
            raise ValueError(f"缺 {ticker} 年度財務資料")
        companies.append(build_company(ticker, company, holdings))
    return {
        "schema_version": 1, "updated_at": financials.get("generated_at"),
        "tracked_count": len(companies),
        "summary": {
            "support": sum(row["status"] == "support" for row in companies),
            "neutral": sum(row["status"] == "neutral" for row in companies),
            "pressure": sum(row["status"] == "pressure" for row in companies),
            "insufficient": sum(row["status"] == "insufficient" for row in companies),
        },
        "methodology": {
            "scope": "14 家個股最近 4 個年度；ETF 不納入，實際持股優先。",
            "fcf": "自由現金流＝營運現金流－資本支出；FCF conversion＝FCF ÷ 營運現金流。",
            "payout": "股東回饋＝回購＋現金股利；任一 XBRL 標籤缺漏即不計合計，不把缺值當 0。",
            "shares": "用稀釋加權平均股數年變化檢驗所有股份來源的淨效果；不能單獨歸因於 SBC。跨期相差逾 20 倍即停止比較。",
            "debt": "有息負債沿用全站一致的非重疊組成；不同幣別不相加。",
            "boundary": "資本支出高低本身不代表投資成功；未取得一致的併購現金支出時保留資料缺口，不以殘差猜測。",
        },
        "companies": companies,
    }


def money(value_: float | None, currency: str | None) -> str:
    if value_ is None:
        return "—"
    amount = abs(value_)
    if amount >= 1e9:
        text = f"{amount / 1e9:,.2f}B"
    elif amount >= 1e6:
        text = f"{amount / 1e6:,.1f}M"
    else:
        text = f"{amount:,.0f}"
    return f"{'-' if value_ < 0 else ''}{currency or ''} {text}".strip()


def percent(value_: float | None) -> str:
    return "—" if value_ is None else f"{value_:.1%}"


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "---", "title: 資本配置與股東價值追蹤卡", "tags:", "  - capital-allocation", "  - shareholder-value", "---", "",
        "# 🧭 資本配置與股東價值追蹤卡", "",
        f"> 更新：{payload['updated_at']}｜支持 {summary['support']}｜中性 {summary['neutral']}｜壓力 {summary['pressure']}｜資料不足 {summary['insufficient']}。", "",
        "## 判讀規則", "",
        *[f"- **{key}**：{text}" for key, text in payload["methodology"].items()], "",
    ]
    for company in payload["companies"]:
        latest = company["latest"]
        lines += [
            f"## {company['ticker']}｜{company['label']}", "",
            f"> {'實際持股' if company['position'] == 'holding' else '觀察名單'}｜年度 {company['latest_period']}｜可判讀 {company['coverage']['known']}/5｜分數 {company['score']:+d}", "",
            f"- **FCF**：{money(latest['free_cash_flow'], company['currency'])}；FCF margin {percent(latest['fcf_margin'])}；資本支出／營收 {percent(latest['capex_intensity'])}。",
            f"- **股東回饋**：回購 {money(latest['buybacks'], company['currency'])}；股利 {money(latest['dividends_paid'], company['currency'])}；回饋／FCF {percent(latest['payout_to_fcf'])}。",
            f"- **股份與負債**：稀釋股數 YoY {percent(latest['share_change'])}；有息負債 {money(latest['total_debt'], company['currency'])}；淨現金 {money(latest['net_cash'], company['currency'])}。",
        ]
        lines.extend(f"- **{row['label']}｜{row['state']}**：{row['evidence']}" for row in company["signals"])
        source = latest.get("source") or {}
        if source.get("url"):
            lines.append(f"- [年度申報原文（{source.get('form')}／{source.get('accession')}）]({source['url']})")
        lines += ["", "| 年度 | FCF | Capex／營收 | 回購 | 股利 | 稀釋股數 YoY | 有息負債 |", "|---|---:|---:|---:|---:|---:|---:|"]
        for row in company["years"]:
            lines.append(
                f"| {row['fiscal_year_end']} | {money(row['free_cash_flow'], row['currency'])} | {percent(row['capex_intensity'])} | "
                f"{money(row['buybacks'], row['currency'])} | {money(row['dividends_paid'], row['currency'])} | "
                f"{percent(row['share_change'])} | {money(row['total_debt'], row['currency'])} |"
            )
        lines += ["", f"> {company['conclusion']}", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--financials", type=Path, default=ROOT / "financials.json")
    parser.add_argument("--holdings", type=Path, default=ROOT / "portfolio_holdings.json")
    parser.add_argument("--output", type=Path, default=ROOT / "capital_allocation_cards.json")
    parser.add_argument("--markdown", type=Path, default=ROOT / "60_SEC_Filing_Radar/Capital_Allocation_Cards.md")
    args = parser.parse_args()
    payload = build_payload(load_json(args.financials), load_json(args.holdings))
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(render_markdown(payload))
    print(f"資本配置卡：{payload['tracked_count']} 家；{payload['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
