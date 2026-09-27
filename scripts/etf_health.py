"""Constituent health of the research theme ETFs.

A theme ETF's price says whether the theme moved; its constituents say how.
The same +8% can come from most holdings rising together or from the top
three carrying the rest.  For every ETF in ``etf_holdings.THEME_ETFS``,
using its latest N-PORT holdings (weights are as of the report date) and
daily closes:

* breadth: share of constituents above their 20- and 50-session averages,
  weighted by holding and by issuer count;
* participation: cap-weighted vs equal-weighted 20-session constituent
  return (a negative spread means a few large holdings did the work);
* contribution: the three holdings that contributed most to the
  cap-weighted return, and their share of it;
* the ETF's own 5/20/60-session return and its 20-session return relative
  to SPY, which orders the table;
* money flows: the last three months of real creations minus redemptions
  from N-PORT (as % of net assets, two to five months old), and a daily
  estimate over 5/20 sessions from the recorded Yahoo shares outstanding
  or assets (``etf_flows_history/``).

The state labels are descriptive research labels, not tested signals: the
thresholds below are frozen under ``HEALTH_RULE_VERSION`` so that the daily
record (``etf_health_history/``, one append-only line per session) can be
tested later without moving the goalposts.

etf-health-2 (2026-09-27, before any record accumulated): "carried by a
few" needs the equal-weight return to lag the cap-weighted one as well as
the top three to dominate the move.  Under etf-health-1 a concentrated
30-stock fund (SOXX, SMH) with 83% of holdings above their averages and
equal = cap-weighted return was labelled carried, which contradicts the
label.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

import etf_holdings

SCHEMA_VERSION = 1
HEALTH_RULE_VERSION = "etf-health-2"
KNOWN_RULE_VERSIONS = {"etf-health-1", HEALTH_RULE_VERSION}
BENCHMARK = "SPY"
WINDOW = 20
LONG_WINDOW = 50
TREND_WINDOW = 60
THRESHOLDS = {
    "direction_r20": 0.02,        # ETF 20-session return beyond ±2% counts as a move
    "broad_breadth_up": 0.60,     # ≥60% of issuers above their 50-session average
    "broad_breadth_down": 0.40,   # ≤40% of issuers above their 50-session average
    "top3_share_max": 0.60,       # top three holdings carry at most 60% of the move
    "participation_gap": 0.02,    # equal- vs cap-weighted 20-session return gap that confirms a carried move
    "narrow_breadth_up": 0.50,    # below 50% of issuers above their 50-session average: few are rising
    "narrow_breadth_down": 0.50,  # above 50% still above their average: few are falling
    "min_coverage_pct": 70.0,     # priced common stock as % of the fund's common stock
    "min_priced": 10,
    "tracking_gap_pct": 3.0,      # constituent replay vs ETF 20-session return
    "holdings_age_days": 150,
}
STATES = {
    "broad_advance": "普遍上漲",
    "narrow_advance": "少數撐盤",
    "mixed": "持平或分歧",
    "narrow_decline": "少數拖累",
    "broad_decline": "普遍下跌",
    "data_limited": "資料不足",
}
FLAGS = {
    "stale_weights": "成分權重與 ETF 實際走勢差距大，申報後可能已調倉",
    "holdings_old": "N-PORT 持股超過 150 天",
    "low_coverage": "有報價的成分不到七成",
    "etf_price_missing": "ETF 本身缺少報價，方向改用成分重建報酬",
}


def pct(value: float | None, digits: int = 2) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    return round(float(value) * 100, digits) + 0.0


def trailing_return(series: pd.Series, sessions: int) -> float | None:
    values = series.dropna()
    if len(values) <= sessions:
        return None
    return float(values.iloc[-1] / values.iloc[-1 - sessions] - 1)


def constituent_table(fund: dict, closes: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Priced common-stock holdings, one row per ticker, with 20-session return and trend flags."""
    equity = [row for row in fund["holdings"]
              if row.get("asset_category") in etf_holdings.EQUITY_CATEGORIES and (row.get("weight_pct") or 0) > 0]
    weights: dict[str, float] = {}
    for row in equity:
        if row.get("ticker"):
            weights[row["ticker"]] = weights.get(row["ticker"], 0.0) + row["weight_pct"]
    equity_weight = sum(row["weight_pct"] for row in equity)
    rows = []
    for ticker, weight in weights.items():
        if ticker not in closes:
            continue
        series = closes[ticker]
        recent = series.iloc[-LONG_WINDOW:]
        if len(recent) < LONG_WINDOW or recent.isna().any() or len(series) <= WINDOW:
            continue
        last, before = series.iloc[-1], series.iloc[-1 - WINDOW]
        if not (np.isfinite(last) and np.isfinite(before) and before > 0):
            continue
        rows.append({"ticker": ticker, "weight_pct": weight, "r20": last / before - 1,
                     "above20": bool(last > recent.iloc[-WINDOW:].mean()),
                     "above50": bool(last > recent.mean())})
    table = pd.DataFrame(rows, columns=["ticker", "weight_pct", "r20", "above20", "above50"])
    coverage = {
        "holdings": len(fund["holdings"]),
        "common_stock": len(equity),
        "mapped": len(weights),
        "priced": len(table),
        "coverage_pct": round(table["weight_pct"].sum() / equity_weight * 100, 1) if equity_weight else 0.0,
    }
    return table, coverage


def implied_flows(history: list[dict], ticker: str) -> dict:
    """Estimated net flow over the last 5/20 recorded sessions, as % of the latest assets.

    Shares outstanding times the close when both days have shares; else the
    change in total assets beyond what the price change explains.
    """
    points = [row["etfs"].get(ticker) or {} for row in history]
    flows: list[float | None] = []
    for before, after in zip(points, points[1:]):
        if before.get("shares_outstanding") and after.get("shares_outstanding") and after.get("close"):
            flows.append((after["shares_outstanding"] - before["shares_outstanding"]) * after["close"])
        elif before.get("total_assets") and after.get("total_assets") and before.get("close") and after.get("close"):
            flows.append(after["total_assets"] - before["total_assets"] * after["close"] / before["close"])
        else:
            flows.append(None)
    last = points[-1] if points else {}
    assets = (last.get("shares_outstanding") or 0) * (last.get("close") or 0) or last.get("total_assets")
    result = {"sessions_recorded": len(points)}
    for window in (5, 20):
        recent = flows[-window:]
        known = [value for value in recent if value is not None]
        complete = len(recent) == window and len(known) == window
        result[f"flow_{window}d_pct"] = pct(sum(known) / assets) if complete and assets else None
    return result


def nport_flows(fund: dict) -> dict:
    months = [row for row in fund.get("monthly_flows") or [] if row.get("net_usd") is not None]
    assets = fund.get("net_assets_usd")
    if not months or not assets:
        return {"net_3m_pct": None, "months": None}
    return {"net_3m_pct": pct(sum(row["net_usd"] for row in months) / assets),
            "months": f"{months[0]['month']}～{months[-1]['month']}"}


def classify(direction: str, breadth50: float | None, top3_share: float | None, spread: float | None,
             limited: bool) -> str:
    """Descriptive state; ``spread`` is the equal- minus cap-weighted 20-session constituent return."""
    if limited:
        return "data_limited"
    if direction == "flat" or breadth50 is None:
        return "mixed"
    dominant = top3_share is not None and top3_share > THRESHOLDS["top3_share_max"]
    gap = THRESHOLDS["participation_gap"]
    if direction == "up":
        carried = dominant and spread is not None and spread <= -gap
        if carried or breadth50 < THRESHOLDS["narrow_breadth_up"]:
            return "narrow_advance"
        return "broad_advance" if breadth50 >= THRESHOLDS["broad_breadth_up"] else "mixed"
    dragged = dominant and spread is not None and spread >= gap
    if dragged or breadth50 > THRESHOLDS["narrow_breadth_down"]:
        return "narrow_decline"
    return "broad_decline" if breadth50 <= THRESHOLDS["broad_breadth_down"] else "mixed"


def fund_health(ticker: str, fund: dict, closes: pd.DataFrame, as_of: date,
                flows_history: list[dict] | None = None) -> dict:
    table, coverage = constituent_table(fund, closes)
    flags = []
    etf_series = closes[ticker] if ticker in closes else pd.Series(dtype=float)
    etf = {"r5": trailing_return(etf_series, 5), "r20": trailing_return(etf_series, WINDOW),
           "r60": trailing_return(etf_series, TREND_WINDOW)}
    bench = trailing_return(closes[BENCHMARK], WINDOW) if BENCHMARK in closes else None
    etf["rs20"] = etf["r20"] - bench if etf["r20"] is not None and bench is not None else None
    etf_values = etf_series.dropna()
    etf["above_ma50"] = (bool(etf_values.iloc[-1] > etf_values.iloc[-LONG_WINDOW:].mean())
                         if len(etf_values) >= LONG_WINDOW else None)

    cw = ew = spread = gap = top3_share = None
    breadth = {"above_ma20_weighted_pct": None, "above_ma50_weighted_pct": None, "above_ma50_equal_pct": None}
    contributors: list[dict] = []
    breadth50 = None
    if len(table):
        w = table["weight_pct"] / table["weight_pct"].sum()
        contribution = w * table["r20"]
        cw, ew = float(contribution.sum()), float(table["r20"].mean())
        spread = ew - cw
        breadth50 = float(table["above50"].mean())
        breadth = {"above_ma20_weighted_pct": pct(float((w * table["above20"]).sum()), 1),
                   "above_ma50_weighted_pct": pct(float((w * table["above50"]).sum()), 1),
                   "above_ma50_equal_pct": pct(breadth50, 1)}
        order = contribution.sort_values(ascending=cw < 0).index[:3]
        if abs(cw) >= 0.01:
            top3_share = float(contribution.loc[order].sum() / cw)
        contributors = [{"ticker": table.at[i, "ticker"], "weight_pct": round(float(table.at[i, "weight_pct"]), 2),
                         "r20_pct": pct(table.at[i, "r20"]), "contribution_pp": pct(contribution.at[i])}
                        for i in order]
        if etf["r20"] is not None:
            gap = abs(cw - etf["r20"])
            if gap * 100 > THRESHOLDS["tracking_gap_pct"]:
                flags.append("stale_weights")

    move = etf["r20"] if etf["r20"] is not None else cw
    if etf["r20"] is None:
        flags.append("etf_price_missing")
    limit = THRESHOLDS["direction_r20"]
    direction = "flat" if move is None or abs(move) < limit else ("up" if move > 0 else "down")
    limited = (move is None or coverage["coverage_pct"] < THRESHOLDS["min_coverage_pct"]
               or coverage["priced"] < THRESHOLDS["min_priced"])
    if coverage["coverage_pct"] < THRESHOLDS["min_coverage_pct"]:
        flags.append("low_coverage")
    report = fund.get("report_date")
    if report and (as_of - date.fromisoformat(report)).days > THRESHOLDS["holdings_age_days"]:
        flags.append("holdings_old")
    return {
        "ticker": ticker,
        "theme": etf_holdings.THEME_ETFS.get(ticker, ticker),
        "fund_name": fund.get("fund_name"),
        "holdings_report_date": report,
        "holdings_accession": fund.get("accession"),
        "state": classify(direction, breadth50, top3_share, spread, limited),
        "direction": direction,
        "etf": {"r5_pct": pct(etf["r5"]), "r20_pct": pct(etf["r20"]), "r60_pct": pct(etf["r60"]),
                "rs20_pct": pct(etf["rs20"]), "above_ma50": etf["above_ma50"]},
        "constituents": coverage,
        "breadth": breadth,
        "returns": {"cap_weighted_r20_pct": pct(cw), "equal_weighted_r20_pct": pct(ew),
                    "equal_minus_cap_pp": pct(spread), "tracking_gap_pp": pct(gap)},
        "concentration": {"top3_share_pct": pct(top3_share, 1), "top_contributors": contributors},
        "flows": {"nport": nport_flows(fund), "estimated": implied_flows(flows_history or [], ticker)},
        "flags": sorted(flags),
    }


def compute(funds: dict[str, dict | None], closes: pd.DataFrame, generated_at: str,
            flows_history: list[dict] | None = None) -> dict:
    """Health of every research ETF; ``funds`` maps ticker -> holdings file (None when not fetched yet)."""
    if BENCHMARK not in closes or closes[BENCHMARK].dropna().empty:
        raise ValueError(f"{BENCHMARK} has no closes")
    as_of_ts = closes[BENCHMARK].dropna().index[-1]
    closes = closes.loc[:as_of_ts]
    as_of = as_of_ts.date()
    rows, unavailable = [], []
    for ticker in sorted(funds):
        fund = funds[ticker]
        if not fund:
            unavailable.append({"ticker": ticker, "theme": etf_holdings.THEME_ETFS.get(ticker, ticker),
                                "reason": "尚無 N-PORT 持股檔"})
            continue
        usable = [row for row in flows_history or [] if row["as_of"] <= as_of.isoformat()]
        rows.append(fund_health(ticker, fund, closes, as_of, usable))
    rows.sort(key=lambda row: (row["etf"]["rs20_pct"] is None, -(row["etf"]["rs20_pct"] or 0), row["ticker"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "label": "research",
        "generated_at": generated_at,
        "as_of": as_of.isoformat(),
        "rule_version": HEALTH_RULE_VERSION,
        "etf_list_version": etf_holdings.THEME_ETF_VERSION,
        "benchmark": BENCHMARK,
        "benchmark_r20_pct": pct(trailing_return(closes[BENCHMARK], WINDOW)),
        "thresholds": THRESHOLDS,
        "states": STATES,
        "flags": FLAGS,
        "note": ("描述性研究標籤，門檻尚未經回測驗證；成分權重取自各 ETF 最近一次 SEC N-PORT 申報，"
                 "申報後的調倉不反映。外國掛牌、無美國報價的成分計入未涵蓋比例。"
                 "資金流：N-PORT 為實際申購減贖回（落後 2～5 個月）；每日估計來自 Yahoo 流通股數或資產規模，"
                 "Yahoo 不一定每天更新。"),
        "etfs": rows,
        "unavailable": unavailable,
    }


def snapshot(payload: dict[str, Any]) -> dict:
    """Compact daily record for etf_health_history/: enough to test the labels later."""
    etfs = {}
    for row in payload["etfs"]:
        flows = row.get("flows") or {}
        etfs[row["ticker"]] = {
            "state": row["state"],
            "direction": row["direction"],
            "r20_pct": row["etf"]["r20_pct"],
            "rs20_pct": row["etf"]["rs20_pct"],
            "above_ma50_equal_pct": row["breadth"]["above_ma50_equal_pct"],
            "above_ma50_weighted_pct": row["breadth"]["above_ma50_weighted_pct"],
            "equal_minus_cap_pp": row["returns"]["equal_minus_cap_pp"],
            "top3_share_pct": row["concentration"]["top3_share_pct"],
            "coverage_pct": row["constituents"]["coverage_pct"],
            "holdings_report_date": row["holdings_report_date"],
            "nport_net_3m_pct": (flows.get("nport") or {}).get("net_3m_pct"),
            "estimated_flow_20d_pct": (flows.get("estimated") or {}).get("flow_20d_pct"),
        }
    return {"as_of": payload["as_of"], "rule_version": payload["rule_version"],
            "etf_list_version": payload["etf_list_version"], "benchmark_r20_pct": payload["benchmark_r20_pct"],
            "etfs": etfs}


def validate(payload: dict[str, Any]) -> list[str]:
    problems = []
    if payload.get("label") != "research":
        problems.append("label must stay 'research'")
    if payload.get("rule_version") not in KNOWN_RULE_VERSIONS:
        problems.append(f"unknown rule_version {payload.get('rule_version')}")
    listed = [row["ticker"] for row in payload.get("etfs", [])] + \
             [row["ticker"] for row in payload.get("unavailable", [])]
    if sorted(listed) != sorted(etf_holdings.THEME_ETFS):
        problems.append(f"ETFs {sorted(listed)} are not the frozen list {sorted(etf_holdings.THEME_ETFS)}")
    for row in payload.get("etfs", []):
        name = row.get("ticker")
        if row.get("state") not in STATES:
            problems.append(f"{name}: unknown state {row.get('state')}")
        if not set(row.get("flags", [])) <= set(FLAGS):
            problems.append(f"{name}: unknown flags {row.get('flags')}")
        coverage = row.get("constituents", {}).get("coverage_pct")
        if coverage is None or not 0 <= coverage <= 100.05:
            problems.append(f"{name}: coverage {coverage} outside 0-100")
        for key, value in row.get("breadth", {}).items():
            if value is not None and not 0 <= value <= 100:
                problems.append(f"{name}: {key} {value} outside 0-100")
        if row.get("state") not in ("data_limited", "mixed") and row.get("direction") == "flat":
            problems.append(f"{name}: a flat ETF cannot be labelled {row.get('state')}")
    return problems
