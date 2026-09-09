#!/usr/bin/env python3
"""Build a source-traceable seven-dimension long-term investment radar."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DISPLAY_TICKERS = [
    "NVDA", "TSM", "MSFT", "META", "AAPL", "AMZN", "ARM",
    "ONDS", "TSLA", "GOOG", "COHR", "MRVL", "INTC", "NOK",
]
ALIASES = {"GOOG": "GOOGL"}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def period_value(period: dict[str, Any] | None, key: str) -> float | None:
    if not period:
        return None
    node = (period.get("values") or {}).get(key)
    if isinstance(node, dict):
        return finite(node.get("value"))
    return finite(node)


def ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return current / previous - 1


def piecewise(value: float | None, points: list[tuple[float, float]]) -> float | None:
    """Linearly map an observed value to 0..100 using explicit breakpoints."""
    if value is None:
        return None
    if value <= points[0][0]:
        return points[0][1]
    if value >= points[-1][0]:
        return points[-1][1]
    for (left_x, left_y), (right_x, right_y) in zip(points, points[1:]):
        if left_x <= value <= right_x:
            fraction = (value - left_x) / (right_x - left_x)
            return left_y + fraction * (right_y - left_y)
    raise AssertionError("breakpoints must be ordered")


def metric(identifier: str, label: str, value: float | None, display: str,
           score: float | None, source: str, note: str, weight: float = 1) -> dict[str, Any]:
    return {
        "id": identifier, "label": label, "value": value, "display": display,
        "score": None if score is None else round(score), "weight": weight,
        "source": source, "note": note,
    }


def dimension(identifier: str, label: str, metrics: list[dict[str, Any]]) -> dict[str, Any]:
    known = [row for row in metrics if row["score"] is not None]
    weight = sum(row["weight"] for row in known)
    score = round(sum(row["score"] * row["weight"] for row in known) / weight) if weight else None
    return {
        "id": identifier, "label": label, "score": score,
        "coverage": {"known": len(known), "total": len(metrics)},
        "metrics": metrics,
    }


def percent(value: float | None, digits: int = 1, signed: bool = False) -> str:
    if value is None:
        return "資料不足"
    prefix = "+" if signed and value > 0 else ""
    return f"{prefix}{value * 100:.{digits}f}%"


def percentage_points(value: float | None, digits: int = 1, signed: bool = False) -> str:
    if value is None:
        return "資料不足"
    prefix = "+" if signed and value > 0 else ""
    return f"{prefix}{value * 100:.{digits}f}pp"


def multiple(value: float | None) -> str:
    return "資料不足" if value is None else f"{value:.1f}x"


def compact_amount(value: float | None, currency: str | None) -> str:
    if value is None:
        return "資料不足"
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        amount = f"{absolute / 1_000_000_000:.1f}B"
    elif absolute >= 1_000_000:
        amount = f"{absolute / 1_000_000:.1f}M"
    else:
        amount = f"{absolute:,.0f}"
    return f"{currency or ''} {amount}".strip()


def trend_state(signal: float | None, threshold: float) -> tuple[str, str]:
    if signal is None:
        return "unknown", "資料不足"
    if signal > threshold:
        return "improving", "改善"
    if signal < -threshold:
        return "deteriorating", "惡化"
    return "stable", "持平"


def trend_metric(identifier: str, label: str, frequency: str,
                 points: list[dict[str, Any]], latest_display: str,
                 change_display: str, signal: float | None, threshold: float,
                 note: str) -> dict[str, Any]:
    state, state_label = trend_state(signal, threshold)
    strength = None if signal is None or threshold == 0 else signal / threshold
    return {
        "id": identifier,
        "label": label,
        "frequency": frequency,
        "state": state,
        "state_label": state_label,
        "latest_display": latest_display,
        "change_display": change_display,
        "signal_strength": None if strength is None else round(strength, 3),
        "note": note,
        "points": points,
    }


def period_point(period: dict[str, Any], value: float | None, display: str) -> dict[str, Any]:
    return {"period": period.get("period_end"), "value": value, "display": display}


def build_trends(periods: list[dict[str, Any]], capital: dict[str, Any],
                 currency: str | None) -> dict[str, Any]:
    """Build source-value trends; these are not historical radar scores."""
    quarter_window = periods[:8]

    revenue_points = []
    for index, period in reversed(list(enumerate(quarter_window))):
        value = pct_change(
            period_value(period, "revenue"),
            period_value(periods[index + 4], "revenue") if index + 4 < len(periods) else None,
        )
        revenue_points.append(period_point(period, value, percent(value, signed=True)))
    revenue_yoy = revenue_points[-1]["value"] if revenue_points else None
    prior_revenue_yoy = revenue_points[-2]["value"] if len(revenue_points) > 1 else None
    revenue_change = (
        revenue_yoy - prior_revenue_yoy
        if revenue_yoy is not None and prior_revenue_yoy is not None else None
    )
    revenue_change_display = (
        "缺少前季可比 YoY"
        if revenue_change is None else f"較前季 YoY {percentage_points(revenue_change, signed=True)}"
    )
    trends = [trend_metric(
        "revenue_yoy", "營收成長", "quarterly", revenue_points,
        percent(revenue_yoy, signed=True), revenue_change_display,
        revenue_change, .02,
        "最多八季營收年增率；箭頭比較本季 YoY 與前季 YoY，判斷成長加速或減速。",
    )]

    def margin_trend(identifier: str, label: str, key: str, threshold: float) -> dict[str, Any]:
        points = [
            period_point(period, period_value(period, key), percent(period_value(period, key)))
            for period in reversed(quarter_window)
        ]
        latest = period_value(periods[0], key) if periods else None
        year_ago = period_value(periods[4], key) if len(periods) > 4 else None
        change = latest - year_ago if latest is not None and year_ago is not None else None
        change_display = (
            "缺少去年同期資料"
            if change is None else f"較去年同期 {percentage_points(change, signed=True)}"
        )
        return trend_metric(
            identifier, label, "quarterly", points, percent(latest), change_display,
            change, threshold, "最多八季實際比率；箭頭以最新季對去年同期的百分點變化判定。",
        )

    trends.extend([
        margin_trend("gross_margin", "毛利率", "gross_margin", .01),
        margin_trend("operating_margin", "營業利益率", "operating_margin", .01),
    ])
    fcf_points = []
    for period in reversed(quarter_window):
        value = ratio(period_value(period, "free_cash_flow"), period_value(period, "revenue"))
        fcf_points.append(period_point(period, value, percent(value)))
    latest_fcf_margin = ratio(
        period_value(periods[0], "free_cash_flow"), period_value(periods[0], "revenue")
    ) if periods else None
    year_ago_fcf_margin = ratio(
        period_value(periods[4], "free_cash_flow"), period_value(periods[4], "revenue")
    ) if len(periods) > 4 else None
    fcf_change = (
        latest_fcf_margin - year_ago_fcf_margin
        if latest_fcf_margin is not None and year_ago_fcf_margin is not None else None
    )
    trends.append(trend_metric(
        "fcf_margin", "FCF 利潤率", "quarterly", fcf_points,
        percent(latest_fcf_margin),
        "缺少去年同期資料" if fcf_change is None else f"較去年同期 {percentage_points(fcf_change, signed=True)}",
        fcf_change, .02,
        "最多八季自由現金流除以同季營收；現金流季間波動較大，以 2pp 作為方向門檻。",
    ))

    share_points = []
    for index, period in reversed(list(enumerate(quarter_window))):
        value = pct_change(
            period_value(period, "diluted_shares"),
            period_value(periods[index + 4], "diluted_shares") if index + 4 < len(periods) else None,
        )
        share_points.append(period_point(period, value, percent(value, signed=True)))
    latest_share_yoy = share_points[-1]["value"] if share_points else None
    share_display = (
        "缺少去年同期股數"
        if latest_share_yoy is None else f"YoY {percent(latest_share_yoy, signed=True)}；股數下降較有利"
    )
    trends.append(trend_metric(
        "diluted_shares_yoy", "稀釋股數", "quarterly", share_points,
        percent(latest_share_yoy, signed=True), share_display,
        None if latest_share_yoy is None else -latest_share_yoy, .005,
        "最多八季稀釋加權平均股數年增率；採反向判讀，股數下降為改善。",
    ))

    years = capital.get("years") or []
    annual_points = []
    for year in reversed(years[:4]):
        net_cash = finite(year.get("net_cash"))
        display = (
            "資料不足" if net_cash is None else
            f"{'淨現金' if net_cash >= 0 else '淨負債'} {compact_amount(net_cash, year.get('currency') or currency)}"
        )
        annual_points.append({
            "period": year.get("fiscal_year_end"), "value": net_cash, "display": display,
        })
    latest_net_cash = annual_points[-1]["value"] if annual_points else None
    prior_net_cash = annual_points[-2]["value"] if len(annual_points) > 1 else None
    net_cash_change = (
        latest_net_cash - prior_net_cash
        if latest_net_cash is not None and prior_net_cash is not None else None
    )
    scale = max(abs(latest_net_cash or 0), abs(prior_net_cash or 0), 1)
    net_cash_signal = None if net_cash_change is None else net_cash_change / scale
    latest_net_cash_display = (
        "資料不足" if latest_net_cash is None else
        f"{'淨現金' if latest_net_cash >= 0 else '淨負債'} {compact_amount(latest_net_cash, currency)}"
    )
    net_cash_change_display = (
        "缺少前一年度資料" if net_cash_change is None else
        f"較前一年 {'增加' if net_cash_change >= 0 else '減少'} {compact_amount(net_cash_change, currency)}"
    )
    trends.append(trend_metric(
        "net_cash", "財務壓力（年度）", "annual", annual_points,
        latest_net_cash_display, net_cash_change_display, net_cash_signal, .05,
        "年度現金及短期投資減有息負債；受限於可靠來源頻率，不標示成季度趨勢。",
    ))

    counts = {state: sum(row["state"] == state for row in trends)
              for state in ("improving", "stable", "deteriorating", "unknown")}
    improving = [row for row in trends if row["state"] == "improving"]
    deteriorating = [row for row in trends if row["state"] == "deteriorating"]
    strongest = max(improving, key=lambda row: row.get("signal_strength") or 0, default=None)
    weakest = min(deteriorating, key=lambda row: row.get("signal_strength") or 0, default=None)
    return {
        "basis": "五項季度指標最多八季；財務壓力使用最多四個會計年度。這些是實際數值趨勢，不是歷史雷達分數。",
        "summary": {
            "counts": counts,
            "strongest_improvement": strongest.get("label") if strongest else None,
            "main_deterioration": weakest.get("label") if weakest else None,
        },
        "metrics": trends,
    }


def growth_dimension(periods: list[dict[str, Any]]) -> dict[str, Any]:
    latest = periods[0] if periods else None
    year_ago = periods[4] if len(periods) > 4 else None
    three_years_ago = periods[12] if len(periods) > 12 else None
    revenue = period_value(latest, "revenue")
    yoy = pct_change(revenue, period_value(year_ago, "revenue"))
    old_revenue = period_value(three_years_ago, "revenue")
    cagr = (revenue / old_revenue) ** (1 / 3) - 1 if revenue and old_revenue and old_revenue > 0 else None
    recent = list(reversed(periods[:8]))
    changes = [pct_change(period_value(row, "revenue"), period_value(previous, "revenue"))
               for previous, row in zip(recent, recent[1:])]
    known_changes = [value for value in changes if value is not None]
    positive_ratio = (sum(value > 0 for value in known_changes) / len(known_changes)) if known_changes else None
    return dimension("growth", "成長持續性", [
        metric("revenue_yoy", "最近一季營收 YoY", yoy, percent(yoy, signed=True),
               piecewise(yoy, [(-.20, 0), (0, 35), (.10, 55), (.20, 70), (.40, 90), (.60, 100)]),
               "quarterly_financials.json", "同一公司最近季度與四季前比較。", 1.5),
        metric("revenue_cagr_3y", "季度營收三年 CAGR", cagr, percent(cagr, signed=True),
               piecewise(cagr, [(-.20, 0), (0, 35), (.10, 55), (.20, 70), (.40, 90), (.60, 100)]),
               "quarterly_financials.json", "使用約十二季前的同季營收；不足十三期即保留缺值。"),
        metric("positive_quarter_ratio", "近八季季增穩定度", positive_ratio,
               "資料不足" if positive_ratio is None else f"{sum(value > 0 for value in known_changes)}/{len(known_changes)} 次季增",
               piecewise(positive_ratio, [(0, 0), (.5, 50), (.75, 75), (1, 100)]),
               "quarterly_financials.json", "最近八季相鄰季度的營收增加比例；可能含季節性。"),
    ])


def profitability_dimension(periods: list[dict[str, Any]], health: dict[str, Any]) -> dict[str, Any]:
    latest = periods[0] if periods else None
    year_ago = periods[4] if len(periods) > 4 else None
    gross = period_value(latest, "gross_margin")
    operating = period_value(latest, "operating_margin")
    gross_delta = None if gross is None else gross - period_value(year_ago, "gross_margin") if period_value(year_ago, "gross_margin") is not None else None
    spread = finite((health.get("profitability") or {}).get("roic_minus_wacc"))
    return dimension("profitability", "獲利能力與護城河", [
        metric("gross_margin", "最新毛利率", gross, percent(gross),
               piecewise(gross, [(0, 10), (.2, 30), (.4, 55), (.6, 80), (.8, 100)]),
               "quarterly_financials.json", "高毛利率常反映產品組合或定價能力，但仍需同業比較。"),
        metric("operating_margin", "最新營業利益率", operating, percent(operating),
               piecewise(operating, [(-.2, 0), (0, 30), (.1, 50), (.2, 70), (.35, 90), (.5, 100)]),
               "quarterly_financials.json", "衡量本業扣除營業費用後的獲利能力。", 1.25),
        metric("gross_margin_yoy", "毛利率 YoY 變化", gross_delta, percentage_points(gross_delta, signed=True),
               piecewise(gross_delta, [(-.10, 0), (-.05, 20), (0, 55), (.05, 80), (.10, 100)]),
               "quarterly_financials.json", "百分點變化；改善不代表絕對毛利率已足夠。"),
        metric("roic_spread", "ROIC − WACC", spread, percentage_points(spread, signed=True),
               piecewise(spread, [(-.20, 0), (0, 40), (.10, 65), (.25, 85), (.50, 100)]),
               "financial_health.json", "正值表示目前估計的投入資本報酬高於資金成本。", 1.5),
    ])


def cash_flow_dimension(periods: list[dict[str, Any]], health: dict[str, Any]) -> dict[str, Any]:
    latest = periods[0] if periods else None
    revenue = period_value(latest, "revenue")
    fcf = period_value(latest, "free_cash_flow")
    fcf_margin = ratio(fcf, revenue)
    recent_fcf = [period_value(row, "free_cash_flow") for row in periods[:8]]
    known_fcf = [value for value in recent_fcf if value is not None]
    positive_ratio = (sum(value > 0 for value in known_fcf) / len(known_fcf)) if known_fcf else None
    quality = health.get("cash_flow_quality") or {}
    ocf_to_income = finite(quality.get("ocf_to_net_income"))
    accrual = finite(quality.get("accrual_ratio"))
    return dimension("cash_flow", "現金流品質", [
        metric("quarterly_fcf_margin", "最新季度 FCF 利潤率", fcf_margin, percent(fcf_margin),
               piecewise(fcf_margin, [(-.20, 0), (0, 35), (.10, 55), (.25, 80), (.40, 95), (.60, 100)]),
               "quarterly_financials.json", "自由現金流除以同季營收。", 1.5),
        metric("positive_fcf_ratio", "近八季正 FCF", positive_ratio,
               "資料不足" if positive_ratio is None else f"{sum(value > 0 for value in known_fcf)}/{len(known_fcf)} 季為正",
               piecewise(positive_ratio, [(0, 0), (.5, 50), (1, 100)]),
               "quarterly_financials.json", "只判斷正負，不把缺值當成負值。"),
        metric("ocf_to_net_income", "營業現金流／淨利", ocf_to_income, multiple(ocf_to_income),
               piecewise(ocf_to_income, [(0, 0), (.5, 35), (.8, 65), (1, 85), (1.2, 100)]),
               "financial_health.json", "接近或高於 1 通常代表獲利有現金支撐。"),
        metric("accrual_ratio", "應計比率", accrual, percent(accrual, signed=True),
               piecewise(accrual, [(-.10, 100), (0, 90), (.05, 70), (.10, 45), (.15, 20), (.25, 0)]),
               "financial_health.json", "越低越好；過高代表淨利明顯超前營運現金流。"),
    ])


def resilience_dimension(health: dict[str, Any]) -> dict[str, Any]:
    liquidity = health.get("liquidity") or {}
    solvency = health.get("solvency") or {}
    current = finite(liquidity.get("current_ratio"))
    coverage = finite(solvency.get("interest_coverage"))
    liabilities = finite(solvency.get("liabilities_to_assets"))
    leverage = finite(solvency.get("net_debt_to_ebit"))
    return dimension("resilience", "財務韌性", [
        metric("current_ratio", "流動比率", current, multiple(current),
               piecewise(current, [(.5, 10), (1, 40), (1.5, 60), (2, 75), (3, 90), (5, 100)]),
               "financial_health.json", "衡量流動資產覆蓋流動負債的能力。"),
        metric("interest_coverage", "利息保障倍數", coverage, multiple(coverage),
               piecewise(coverage, [(-5, 0), (0, 5), (1, 20), (3, 50), (8, 75), (20, 90), (50, 100)]),
               "financial_health.json", "EBIT 除以利息費用；負值或低於 1 代表壓力較高。", 1.25),
        metric("liabilities_to_assets", "負債占資產", liabilities, percent(liabilities),
               piecewise(liabilities, [(.2, 95), (.3, 85), (.5, 60), (.7, 35), (.9, 10), (1, 0)]),
               "financial_health.json", "採反向計分；不等同只有有息負債。"),
        metric("net_debt_to_ebit", "淨負債／EBIT", leverage, multiple(leverage),
               piecewise(leverage, [(-1, 100), (0, 90), (1, 75), (2, 60), (3, 45), (5, 20), (8, 0)]),
               "financial_health.json", "負值代表淨現金；本站缺折舊攤銷時以 EBIT 為分母。"),
    ])


def capital_dimension(card: dict[str, Any]) -> dict[str, Any]:
    state_scores = {"support": 90, "neutral": 65, "context": 55, "attention": 35, "risk": 10}
    signals = {row.get("id"): row for row in card.get("signals", [])}
    latest = card.get("latest") or {}
    shares = signals.get("shares") or {}
    payout = signals.get("payout") or {}
    raw_score = finite(card.get("score"))
    share_change = finite(latest.get("share_change"))
    return dimension("capital_allocation", "股東價值與稀釋", [
        metric("share_change", "稀釋股數 YoY", share_change, percent(share_change, signed=True),
               piecewise(share_change, [(-.05, 100), (-.01, 85), (0, 70), (.005, 60), (.02, 50), (.05, 30), (.10, 10), (.20, 0)]),
               "capital_allocation_cards.json", shares.get("evidence") or "缺可比稀釋股數。", 1.75),
        metric("shareholder_return", "股東回饋品質", None, payout.get("evidence") or "資料不足",
               state_scores.get(payout.get("state")), "capital_allocation_cards.json",
               "依回購、股利是否由自由現金流覆蓋評分。"),
        metric("capital_score", "資本配置綜合訊號", raw_score,
               "資料不足" if raw_score is None else f"{raw_score:+.0f} 分（原始 -7～+7 參考區間）",
               piecewise(raw_score, [(-7, 0), (-3, 25), (0, 50), (3, 70), (7, 100)]),
               "capital_allocation_cards.json", card.get("label") or "資料不足", 1.25),
    ])


def execution_dimension(guidance: dict[str, Any], thesis: dict[str, Any]) -> dict[str, Any]:
    records = guidance.get("records") or []
    completed = [row for row in records if isinstance(row, list) and len(row) >= 5
                 and finite(row[2]) is not None and finite(row[4]) is not None]
    outcomes = []
    for row in completed:
        low, actual = finite(row[2]), finite(row[4])
        if low is None or actual is None:
            continue
        if actual >= low:
            outcomes.append(100.0)
        elif low > 0:
            shortfall = (low - actual) / low
            outcomes.append(piecewise(shortfall, [(0, 70), (.05, 50), (.10, 25), (.20, 0)]) or 0)
    guidance_score = sum(outcomes) / len(outcomes) if outcomes else None
    items = thesis.get("items") or []
    thesis_map = {"supported": 100, "verify": 50, "invalidated": 0}
    thesis_scores = [thesis_map[row.get("status")] for row in items if row.get("status") in thesis_map]
    thesis_score = sum(thesis_scores) / len(thesis_scores) if thesis_scores else None
    guidance_display = "資料不足" if guidance_score is None else (
        f"{sum(score == 100 for score in outcomes)}/{len(outcomes)} 次達標"
    )
    thesis_display = "資料不足" if thesis_score is None else (
        f"支持 {sum(row.get('status') == 'supported' for row in items)}／"
        f"待驗證 {sum(row.get('status') == 'verify' for row in items)}／"
        f"失效 {sum(row.get('status') == 'invalidated' for row in items)}"
    )
    return dimension("execution", "管理層執行與揭露", [
        metric("guidance_delivery", "歷史數字指引達成", guidance_score, guidance_display,
               guidance_score, "guidance_history.json",
               "實績落在或高於官方區間視為達標；沒有一致數字指引即保留缺值。", 1.5),
        metric("thesis_evidence", "投資論點實績證據", thesis_score, thesis_display,
               thesis_score, "investment_thesis_status.json",
               "由最新季報對既定論點與失效條件的機械式驗證結果計分。"),
    ])


def valuation_dimension(valuation: dict[str, Any]) -> dict[str, Any]:
    multiples = valuation.get("multiples") or {}
    price = finite(multiples.get("price"))
    shares = finite(multiples.get("shares_used"))
    market_cap = price * shares if price is not None and shares is not None else None
    base_fcf = finite(valuation.get("base_fcf"))
    fcf_yield = ratio(base_fcf, market_cap)
    pe = finite(multiples.get("pe_ratio"))
    divergence = finite(valuation.get("divergence_vs_price"))
    warning = valuation.get("credibility_warning")
    dcf_score = None if warning else piecewise(divergence, [(-.50, 0), (-.25, 25), (0, 55), (.25, 75), (.50, 90), (1, 100)])
    return dimension("valuation", "估值安全邊際", [
        metric("dcf_margin", "DCF 中位數相對現價", divergence, percent(divergence, signed=True),
               dcf_score, "valuation.json",
               warning or "正值代表 DCF 中位估值高於現價；結果高度依賴成長與 WACC 假設。", 1.25),
        metric("fcf_yield", "常態化 FCF 收益率", fcf_yield, percent(fcf_yield),
               piecewise(fcf_yield, [(-.05, 0), (0, 15), (.02, 35), (.04, 55), (.06, 70), (.10, 90), (.15, 100)]),
               "valuation.json", "常態化自由現金流除以目前市值。", 1.25),
        metric("pe", "本益比", pe, "資料不足" if pe is None else f"{pe:.1f}x",
               piecewise(pe, [(10, 95), (15, 85), (25, 70), (40, 50), (60, 30), (100, 10), (200, 0)]),
               "valuation.json", "負 EPS 不顯示本益比；高成長公司仍須搭配成長率判讀。"),
    ])


def build_company(ticker: str, payloads: dict[str, Any], holdings: set[str],
                  score_updated_at: str | None) -> dict[str, Any]:
    data_ticker = ALIASES.get(ticker, ticker)
    quarterly = payloads["quarterly"].get("companies", {}).get(data_ticker) or {}
    periods = quarterly.get("periods") or []
    health = payloads["health"].get("companies", {}).get(data_ticker) or {}
    valuation = payloads["valuation"].get("companies", {}).get(data_ticker) or {}
    guidance = payloads["guidance"].get("companies", {}).get(data_ticker) or {}
    thesis = payloads["thesis"].get("companies", {}).get(data_ticker) or {}
    capital = next((row for row in payloads["capital"].get("companies", []) if row.get("ticker") == ticker), {})
    dimensions = [
        growth_dimension(periods), profitability_dimension(periods, health),
        cash_flow_dimension(periods, health), resilience_dimension(health),
        capital_dimension(capital), execution_dimension(guidance, thesis),
        valuation_dimension(valuation),
    ]
    known = [row["score"] for row in dimensions if row["score"] is not None]
    overall = round(sum(known) / len(known)) if known else None
    if overall is None:
        overall_label = "資料不足"
    elif overall >= 80:
        overall_label = "長期體質強"
    elif overall >= 65:
        overall_label = "長期體質穩健"
    elif overall >= 50:
        overall_label = "優劣混合，需聚焦弱項"
    else:
        overall_label = "長期風險偏高"
    flags = []
    for row in health.get("flags") or []:
        flags.append({"source": "financial_health.json", "label": row.get("dimension"), "detail": row.get("detail")})
    for row in thesis.get("items") or []:
        if row.get("status") == "invalidated":
            flags.append({"source": "investment_thesis_status.json", "label": "論點失效", "detail": row.get("evidence")})
    if capital.get("status") == "pressure":
        flags.append({"source": "capital_allocation_cards.json", "label": "資本配置壓力", "detail": capital.get("conclusion")})
    if valuation.get("credibility_warning"):
        flags.append({"source": "valuation.json", "label": "DCF 可信度", "detail": valuation["credibility_warning"]})
    name = (health.get("entity_name") or capital.get("name") or ticker)
    return {
        "ticker": ticker, "data_ticker": data_ticker, "name": name,
        "position": "holding" if ticker in holdings else "watchlist",
        "latest_period": periods[0].get("period_end") if periods else None,
        "score_basis": {
            "quarterly_period": periods[0].get("period_end") if periods else None,
            "quarterly_filed": periods[0].get("filing_date") if periods else None,
            "annual_period": health.get("fiscal_year_end") or capital.get("latest_period"),
            "price_date": valuation.get("price_date"),
            "score_updated_at": score_updated_at,
        },
        "overall_score": overall, "overall_label": overall_label,
        "coverage": {"known": len(known), "total": len(dimensions),
                     "missing": [row["label"] for row in dimensions if row["score"] is None]},
        "dimensions": dimensions,
        "trends": build_trends(periods, capital, quarterly.get("currency") or capital.get("currency")),
        "red_flags": flags,
    }


def build_payload(payloads: dict[str, Any], holdings_payload: Any) -> dict[str, Any]:
    holding_rows = holdings_payload if isinstance(holdings_payload, list) else holdings_payload.get("holdings", [])
    holdings = {row.get("ticker") for row in holding_rows if finite(row.get("shares")) and row["shares"] > 0}
    source_dates = {
        "quarterly_generated": payloads["quarterly"].get("generated_at"),
        "financial_health_generated": payloads["health"].get("generated_at"),
        "valuation_generated": payloads["valuation"].get("generated_at"),
        "guidance_as_of": payloads["guidance"].get("as_of"),
        "thesis_updated": payloads["thesis"].get("updated_at"),
        "capital_allocation_updated": payloads["capital"].get("updated_at"),
    }
    known_source_dates = [str(value) for value in source_dates.values() if value]
    score_updated_at = max((value[:10] for value in known_source_dates), default=None)
    companies = [build_company(ticker, payloads, holdings, score_updated_at) for ticker in DISPLAY_TICKERS]
    return {
        "schema_version": 1,
        "generated_at": score_updated_at,
        "source_dates": source_dates,
        "tracked_count": len(companies),
        "methodology": {
            "direction": "七個角全部統一為 0～100 分，分數越高代表該構面對長期投資越有利。",
            "missing": "缺值不補 0 或 50；構面分數只平均已知子指標，並顯示覆蓋率。",
            "comparison": "以公司自身最新財報、四季前、約十二季前，以及全站一致的年度健全度／估值資料計算；不是產業排名。",
            "boundary": "雷達圖是資料整理工具，不是買賣建議；重大警示獨立列示，不會被其他高分抵銷。",
        },
        "dimension_order": [
            {"id": "growth", "label": "成長持續性"},
            {"id": "profitability", "label": "獲利能力與護城河"},
            {"id": "cash_flow", "label": "現金流品質"},
            {"id": "resilience", "label": "財務韌性"},
            {"id": "capital_allocation", "label": "股東價值與稀釋"},
            {"id": "execution", "label": "管理層執行與揭露"},
            {"id": "valuation", "label": "估值安全邊際"},
        ],
        "companies": companies,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quarterly", type=Path, default=ROOT / "quarterly_financials.json")
    parser.add_argument("--health", type=Path, default=ROOT / "financial_health.json")
    parser.add_argument("--valuation", type=Path, default=ROOT / "valuation.json")
    parser.add_argument("--guidance", type=Path, default=ROOT / "guidance_history.json")
    parser.add_argument("--thesis", type=Path, default=ROOT / "investment_thesis_status.json")
    parser.add_argument("--capital", type=Path, default=ROOT / "capital_allocation_cards.json")
    parser.add_argument("--holdings", type=Path, default=ROOT / "portfolio_holdings.json")
    parser.add_argument("--output", type=Path, default=ROOT / "long_term_radar.json")
    args = parser.parse_args()
    payloads = {
        "quarterly": load_json(args.quarterly), "health": load_json(args.health),
        "valuation": load_json(args.valuation), "guidance": load_json(args.guidance),
        "thesis": load_json(args.thesis), "capital": load_json(args.capital),
    }
    payload = build_payload(payloads, load_json(args.holdings))
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(f"長期投資雷達：{payload['tracked_count']} 家，資料日期 {payload['generated_at']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
