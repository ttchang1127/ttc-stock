"""Derive the valuation sections from SEC data plus an explicit assumptions file.

Two different kinds of number live here and they are kept apart deliberately:

  Section 四 (multiples, net cash, shareholder yield) is arithmetic on figures
  the filings already contain, so it is computed unconditionally.

  Section 五 (DCF) depends on a growth rate and a discount rate. Those are
  judgements, not facts, so they come from dcf_assumptions.json and nowhere
  else. A company whose assumptions are null is reported as 假設未設定 -- the
  script never substitutes a default, because a plausible-looking intrinsic
  value built on an invented growth rate is exactly the failure this vault is
  recovering from.

The Monte Carlo is seeded, so the same inputs always produce the same
distribution and a diff means an input actually changed.

    python3 scripts/compute_valuation.py
"""

import argparse
import json
import random
from datetime import datetime, timezone
from pathlib import Path

# Net cash here and net debt in the health scorecard must be the same number.
# They were not: this file summed only long_term_debt and debt_current, which
# for TSMC picks up $2.8bn of borrowings and misses $28.3bn of bonds, so its
# "net cash" was overstated by that much and fed straight into the DCF.
from compute_financial_health import total_debt

REPO_ROOT = Path(__file__).resolve().parent.parent
FUNDAMENTALS_PATH = REPO_ROOT / "fundamentals.json"
FINANCIALS_PATH = REPO_ROOT / "financials.json"
ASSUMPTIONS_PATH = REPO_ROOT / "dcf_assumptions.json"
OUTPUT_PATH = REPO_ROOT / "valuation.json"

# Past this gap between the model and the quote, the model is reporting its
# own assumptions rather than a view on the price. Stated here so the
# threshold is arguable rather than buried.
DIVERGENCE_LIMIT = 0.50


def val(period, concept):
    entry = (period or {}).get(concept)
    return entry["value"] if entry else None


def percentile(sorted_values, q):
    if not sorted_values:
        return None
    idx = (len(sorted_values) - 1) * q
    lo, hi = int(idx), min(int(idx) + 1, len(sorted_values) - 1)
    frac = idx - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def multiples(fund, period):
    """Section 四: everything here is arithmetic on reported figures."""
    price = fund.get("price_used")
    shares = fund.get("shares_outstanding") or fund.get("diluted_shares")
    ni = fund.get("net_income")
    diluted = fund.get("diluted_shares")

    eps = (ni / diluted) if ni is not None and diluted else None
    pe = (price / eps) if price and eps and eps > 0 else None

    cash = val(period, "cash") or 0
    sti = val(period, "short_term_investments") or 0
    debt, debt_note, _ = total_debt(period)
    has_cash = val(period, "cash") is not None
    net_cash = (cash + sti - (debt or 0)) if has_cash else None

    buybacks = val(period, "buybacks")
    dividends = val(period, "dividends_paid")
    market_cap = fund.get("market_cap")
    by = (buybacks / market_cap) if buybacks is not None and market_cap else None
    dy = (dividends / market_cap) if dividends is not None and market_cap else None
    total_yield = None
    if by is not None or dy is not None:
        total_yield = (by or 0) + (dy or 0)

    return {
        "price": price, "shares_used": shares,
        "eps_diluted": None if eps is None else round(eps, 4),
        "pe_ratio": None if pe is None else round(pe, 1),
        "pe_note": None if eps is None or eps > 0 else "EPS 為負，本益比無意義",
        "cash_and_st_investments": (cash + sti) if has_cash else None,
        "total_debt": debt,
        "total_debt_note": debt_note,
        "net_cash": net_cash,
        "buybacks": buybacks, "dividends_paid": dividends,
        "buyback_yield": None if by is None else round(by, 5),
        "dividend_yield": None if dy is None else round(dy, 5),
        "shareholder_yield": None if total_yield is None else round(total_yield, 5),
    }


def fcf_margins(periods):
    """FCF as a share of revenue, newest first, for every year both exist."""
    out = []
    for p in periods:
        rev = val(p, "revenue")
        ocf, capex = val(p, "operating_cash_flow"), val(p, "capex")
        if rev and ocf is not None and capex is not None:
            out.append((p["fiscal_year_end"], (ocf - capex) / rev))
    return out


def normalised_base_fcf(periods):
    """Median FCF margin applied to the latest year's revenue.

    A single year of FCF is a fragile base when capex is lumpy, and several of
    these companies are mid-buildout: Amazon's FY2025 FCF margin was 1.1%
    against its own 3.1% median, so its base was a third of normal and a 10-year
    projection then compounded the depressed figure. Microsoft is 20.2% against
    29.1%, Meta 22.9% against 30.1%.

    Scaling the median *margin* by current revenue rather than taking a median
    of past FCF keeps the company's current size; a plain median would drag a
    fast-growing company back to what it earned years ago.

    Returns None when there are too few years to have a median worth the name,
    or when the median margin is negative -- for a company that has never
    converted revenue to cash, this is not a normalisation problem and the
    DCF is excluded elsewhere anyway.
    """
    margins = fcf_margins(periods)
    if len(margins) < 3:
        return None, None, "可用年數不足 3 年，無法常態化"
    values = sorted(m for _, m in margins)
    mid = len(values) // 2
    median = values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2
    if median <= 0:
        return None, median, "歷年 FCF 利潤率中位數為負，常態化無意義"
    revenue = val(periods[0], "revenue")
    if not revenue:
        return None, median, "缺當期營收"
    return median * revenue, median, None


def dcf_per_share(base_fcf, net_cash, shares, growth, wacc, years, tg):
    """The deterministic DCF the Monte Carlo draws around."""
    if wacc <= tg:
        return None
    pv, fcf = 0.0, base_fcf
    for year in range(1, years + 1):
        fcf *= (1 + growth)
        pv += fcf / ((1 + wacc) ** year)
    pv += fcf * (1 + tg) / (wacc - tg) / ((1 + wacc) ** years)
    return (pv + (net_cash or 0)) / shares


def implied_growth(price, base_fcf, net_cash, shares, wacc, years, tg):
    """The FCF growth rate at which this DCF would equal the market price.

    This is the honest way to present a valuation whose output is nowhere near
    the quote. Saying Coherent is "worth $5.63" against a $379 price asserts a
    98% mispricing; saying the price implies a given decade of FCF growth hands
    the reader something they can actually judge. Value per share rises
    monotonically with growth, so a bisection is exact enough.
    """
    if not shares or base_fcf is None or base_fcf <= 0 or wacc <= tg:
        return {"value": None, "reason": "基期 FCF 或折現率不適用"}
    lo, hi = -0.60, 2.00

    def f(g):
        return dcf_per_share(base_fcf, net_cash, shares, g, wacc, years, tg)

    if f(lo) > price:
        return {"value": None,
                "reason": "即使 FCF 永久萎縮 60%，模型值仍高於現價"}
    if f(hi) < price:
        return {"value": None,
                "reason": "即使 FCF 年增 200%，模型值仍低於現價；"
                          "現價無法由本組假設下的 DCF 解釋"}
    for _ in range(80):
        mid = (lo + hi) / 2
        if f(mid) < price:
            lo = mid
        else:
            hi = mid
    return {"value": round((lo + hi) / 2, 4)}


def monte_carlo_dcf(base_fcf, net_cash, shares, growth, wacc, cfg, rng):
    """Section 五. Returns per-share intrinsic value percentiles."""
    years = cfg["projection_years"]
    tg = cfg["terminal_growth"]
    n = cfg["simulations"]
    g_sigma = abs(growth) * cfg["growth_relative_sigma"]
    w_sigma = wacc * cfg["wacc_relative_sigma"]

    values, rejected = [], 0
    for _ in range(n):
        g = rng.gauss(growth, g_sigma)
        w = rng.gauss(wacc, w_sigma)
        # A discount rate at or below terminal growth makes the perpetuity
        # diverge; drop the draw rather than emit an infinite valuation.
        if w <= tg + 1e-6:
            rejected += 1
            continue
        pv, fcf = 0.0, base_fcf
        for year in range(1, years + 1):
            fcf *= (1 + g)
            pv += fcf / ((1 + w) ** year)
        terminal = fcf * (1 + tg) / (w - tg)
        pv += terminal / ((1 + w) ** years)
        equity = pv + (net_cash or 0)
        values.append(equity / shares)

    if not values:
        return {"error": "所有模擬皆因 WACC ≤ 終端成長率而無效"}
    values.sort()
    return {
        "simulations_run": len(values),
        "simulations_rejected": rejected,
        "mean": round(sum(values) / len(values), 2),
        "p5": round(percentile(values, 0.05), 2),
        "p25": round(percentile(values, 0.25), 2),
        "p50": round(percentile(values, 0.50), 2),
        "p75": round(percentile(values, 0.75), 2),
        "p95": round(percentile(values, 0.95), 2),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+")
    args = parser.parse_args()

    for path in (FUNDAMENTALS_PATH, FINANCIALS_PATH, ASSUMPTIONS_PATH):
        if not path.exists():
            raise SystemExit(f"{path.name} missing; run the earlier pipeline steps first")

    fundamentals = json.loads(FUNDAMENTALS_PATH.read_text())["companies"]
    financials = json.loads(FINANCIALS_PATH.read_text())["companies"]
    assumptions = json.loads(ASSUMPTIONS_PATH.read_text())
    cfg = assumptions["defaults"]

    tickers = args.tickers or sorted(fundamentals)
    results = {}
    print("{:7s}{:>9s}{:>11s}{:>11s}{:>9s}{:>10s}  {}".format(
        "ticker", "P/E", "現價", "DCF中位數", "偏離", "隱含成長", "狀態"))

    for ticker in tickers:
        fund = fundamentals.get(ticker)
        if not fund:
            continue
        period = (financials.get(ticker) or {}).get("periods", [{}])[0]
        m = multiples(fund, period)

        assume = assumptions["companies"].get(ticker, {})
        growth, wacc = assume.get("growth"), assume.get("wacc")
        reported_fcf = fund.get("free_cash_flow")
        shares = fund.get("shares_outstanding") or fund.get("diluted_shares")
        periods = (financials.get(ticker) or {}).get("periods", [])

        normalised, median_margin, norm_reason = normalised_base_fcf(periods)
        base_fcf, base_basis = reported_fcf, "當期自由現金流"
        fcf_caveat = None
        if normalised is not None and reported_fcf is not None:
            base_fcf, base_basis = normalised, "常態化自由現金流（歷年 FCF 利潤率中位數 × 當期營收）"
            ratio = reported_fcf / normalised if normalised else None
            if ratio is not None and abs(ratio - 1) > 0.15:
                fcf_caveat = ("當期 FCF {:,.0f}M 為常態化基準 {:,.0f}M 的 {:.0%}"
                              "（歷年 FCF 利潤率中位數 {:.1%}）。基期採常態化值，"
                              "以免單一年度的資本支出高峰被外推十年"
                              .format(reported_fcf / 1e6, normalised / 1e6, ratio, median_margin))
        elif norm_reason and reported_fcf is not None and reported_fcf > 0:
            fcf_caveat = f"基期採當期 FCF：{norm_reason}"

        dcf, status = None, ""
        if growth is None or wacc is None:
            status = "假設未設定"
        elif base_fcf is None:
            status = "缺 FCF"
        elif not shares:
            status = "缺股數"
        elif base_fcf <= 0:
            status = "FCF 為負，DCF 不適用"
        else:
            rng = random.Random(cfg["random_seed"] + sum(ord(c) for c in ticker))
            dcf = monte_carlo_dcf(base_fcf, m["net_cash"], shares, growth, wacc, cfg, rng)
            status = "已計算"

        # What growth the quote implies, and whether the model's answer is far
        # enough from the quote that the inputs are the likelier explanation.
        implied, divergence, credibility = None, None, None
        if dcf and dcf.get("p50") and m.get("price"):
            implied = implied_growth(m["price"], base_fcf, m["net_cash"], shares,
                                     wacc, cfg["projection_years"], cfg["terminal_growth"])
            divergence = dcf["p50"] / m["price"] - 1
            if abs(divergence) > DIVERGENCE_LIMIT:
                credibility = (
                    "中位數 ${:,.2f} 與現價 ${:,.2f} 相差 {:+.0%}，超過 ±{:.0%} 門檻。"
                    "這個幅度通常反映假設不適用，而非市場錯價 —— "
                    "請以下方的隱含成長率判讀，不要把中位數當成目標價"
                    .format(dcf["p50"], m["price"], divergence, DIVERGENCE_LIMIT))

        results[ticker] = {
            "currency": fund.get("currency"),
            "fiscal_year_end": fund.get("fiscal_year_end"),
            "price_date": fund.get("price_date"),
            "multiples": m,
            "assumptions": {"growth": growth, "wacc": wacc,
                            "terminal_growth": cfg["terminal_growth"],
                            "projection_years": cfg["projection_years"],
                            "simulations": cfg["simulations"],
                            "note": assume.get("note")},
            "dcf": dcf,
            "dcf_status": status,
            "base_fcf": base_fcf,
            "base_fcf_basis": base_basis,
            "base_fcf_reported": reported_fcf,
            "base_fcf_normalised": normalised,
            "fcf_margin_median": None if median_margin is None else round(median_margin, 4),
            "base_fcf_caveat": fcf_caveat,
            "implied_growth": implied,
            "divergence_vs_price": None if divergence is None else round(divergence, 4),
            "divergence_limit": DIVERGENCE_LIMIT,
            "credibility_warning": credibility,
        }

        ig = (implied or {}).get("value")
        print("{:7s}{:>9s}{:>11s}{:>11s}{:>9s}{:>10s}  {}".format(
            ticker,
            "n/a" if m["pe_ratio"] is None else "{:.1f}x".format(m["pe_ratio"]),
            "n/a" if m["price"] is None else "${:,.2f}".format(m["price"]),
            "n/a" if not dcf or "p50" not in dcf else "${:,.2f}".format(dcf["p50"]),
            "n/a" if divergence is None else "{:+.0%}".format(divergence),
            "n/a" if ig is None else "{:.1%}".format(ig),
            ("⚠️ " if credibility else "") + status))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "assumptions_source": "dcf_assumptions.json (human-maintained)",
        "defaults": cfg,
        "companies": results,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    print(f"\nWrote {OUTPUT_PATH.relative_to(REPO_ROOT)} ({len(results)} companies)")


if __name__ == "__main__":
    main()
