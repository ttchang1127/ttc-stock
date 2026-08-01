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

REPO_ROOT = Path(__file__).resolve().parent.parent
FUNDAMENTALS_PATH = REPO_ROOT / "fundamentals.json"
FINANCIALS_PATH = REPO_ROOT / "financials.json"
ASSUMPTIONS_PATH = REPO_ROOT / "dcf_assumptions.json"
OUTPUT_PATH = REPO_ROOT / "valuation.json"


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
    debt_nc = val(period, "long_term_debt") or 0
    debt_c = val(period, "debt_current") or 0
    has_cash = val(period, "cash") is not None
    net_cash = (cash + sti - debt_nc - debt_c) if has_cash else None

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
        "total_debt": debt_nc + debt_c,
        "net_cash": net_cash,
        "buybacks": buybacks, "dividends_paid": dividends,
        "buyback_yield": None if by is None else round(by, 5),
        "dividend_yield": None if dy is None else round(dy, 5),
        "shareholder_yield": None if total_yield is None else round(total_yield, 5),
    }


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
    print("{:7s}{:>9s}{:>12s}{:>11s}{:>11s}  {}".format(
        "ticker", "P/E", "淨現金(M)", "現價", "DCF中位數", "狀態"))

    for ticker in tickers:
        fund = fundamentals.get(ticker)
        if not fund:
            continue
        period = (financials.get(ticker) or {}).get("periods", [{}])[0]
        m = multiples(fund, period)

        assume = assumptions["companies"].get(ticker, {})
        growth, wacc = assume.get("growth"), assume.get("wacc")
        base_fcf = fund.get("free_cash_flow")
        shares = fund.get("shares_outstanding") or fund.get("diluted_shares")

        # A single year of FCF is a fragile base when capex is lumpy. Amazon's
        # FY2025 capex consumed almost all of operating cash flow, leaving an
        # FCF that a 10-year projection then compounds. The previous note said
        # it used "常態化 FCF" for exactly this reason; flag it rather than let
        # the depressed base pass unremarked.
        ocf = fund.get("operating_cash_flow")
        fcf_caveat = None
        if base_fcf is not None and ocf and ocf > 0:
            share = base_fcf / ocf
            if base_fcf <= 0:
                fcf_caveat = ("基期自由現金流為負（資本支出超過營運現金流），"
                              "單一年度 FCF 無法作為 DCF 外推基礎，需改用常態化 FCF")
            elif share < 0.25:
                fcf_caveat = ("基期 FCF 僅為營運現金流的 {:.0%}（資本支出年度異常偏高），"
                              "以單一年度 FCF 外推會低估價值，建議改用常態化 FCF"
                              .format(share))

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
            "base_fcf_caveat": fcf_caveat,
        }

        nc = m["net_cash"]
        print("{:7s}{:>9s}{:>12s}{:>11s}{:>11s}  {}".format(
            ticker,
            "n/a" if m["pe_ratio"] is None else "{:.1f}x".format(m["pe_ratio"]),
            "n/a" if nc is None else "{:,.0f}".format(nc / 1e6),
            "n/a" if m["price"] is None else "${:,.2f}".format(m["price"]),
            "n/a" if not dcf or "p50" not in dcf else "${:,.2f}".format(dcf["p50"]),
            status))

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
