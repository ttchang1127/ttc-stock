"""Compute fundamental metrics from financials.json and write fundamentals.json.

Replaces the previous approach, where scripts asserted their conclusions --
`f1 = 1 ... f9 = 1` with a justifying comment beside each -- rather than
comparing anything. Every figure here is derived from SEC XBRL data, and any
criterion whose inputs are missing is reported as null instead of being
awarded a point.

    python3 scripts/fetch_xbrl_financials.py     # first: pull the raw data
    python3 scripts/compute_fundamentals.py      # then: derive the metrics

Metrics: Piotroski F-Score (per-criterion detail), Altman Z-Score, DuPont ROE
decomposition, and the margin/return ratios the analysis notes quote.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FINANCIALS_PATH = REPO_ROOT / "financials.json"
PRICES_PATH = REPO_ROOT / "prices.json"
OUTPUT_PATH = REPO_ROOT / "fundamentals.json"

# Vault notes use GOOG on the dashboard but GOOGL in the filings tree.
PRICE_ALIASES = {"GOOGL": "GOOG"}


def val(period, concept):
    entry = period.get(concept)
    return entry["value"] if entry else None


def div(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


def gt(a, b):
    """Strictly greater, or None when either side is unavailable."""
    if a is None or b is None:
        return None
    return a > b


def piotroski(cur, prev):
    """The nine Piotroski criteria, each computed or explicitly unavailable."""
    roa_cur = div(val(cur, "net_income"), val(cur, "assets"))
    roa_prev = div(val(prev, "net_income"), val(prev, "assets"))
    lev_cur = div(val(cur, "long_term_debt"), val(cur, "assets"))
    lev_prev = div(val(prev, "long_term_debt"), val(prev, "assets"))
    cr_cur = div(val(cur, "current_assets"), val(cur, "current_liabilities"))
    cr_prev = div(val(prev, "current_assets"), val(prev, "current_liabilities"))
    gm_cur = div(val(cur, "gross_profit"), val(cur, "revenue"))
    gm_prev = div(val(prev, "gross_profit"), val(prev, "revenue"))
    at_cur = div(val(cur, "revenue"), val(cur, "assets"))
    at_prev = div(val(prev, "revenue"), val(prev, "assets"))

    tests = {
        "1_roa_positive":        gt(roa_cur, 0),
        "2_ocf_positive":        gt(val(cur, "operating_cash_flow"), 0),
        "3_roa_improved":        gt(roa_cur, roa_prev),
        "4_accruals_ocf_gt_ni":  gt(val(cur, "operating_cash_flow"), val(cur, "net_income")),
        "5_leverage_decreased":  None if lev_cur is None or lev_prev is None else lev_cur < lev_prev,
        "6_current_ratio_up":    gt(cr_cur, cr_prev),
        "7_no_share_dilution":   None if val(cur, "diluted_shares") is None
                                 or val(prev, "diluted_shares") is None
                                 else val(cur, "diluted_shares") <= val(prev, "diluted_shares"),
        "8_gross_margin_up":     gt(gm_cur, gm_prev),
        "9_asset_turnover_up":   gt(at_cur, at_prev),
    }
    scored = sum(1 for v in tests.values() if v is True)
    unavailable = [k for k, v in tests.items() if v is None]
    return {
        "criteria": tests,
        "score": scored,
        "max_evaluated": len(tests) - len(unavailable),
        "unavailable": unavailable,
    }


def altman_z(cur, market_cap):
    """Original Altman Z for public manufacturers.

    Z = 1.2*X1 + 1.4*X2 + 3.3*X3 + 0.6*X4 + 1.0*X5
    Returns None when any input is missing rather than substituting a guess.
    """
    assets = val(cur, "assets")
    wc = None
    if val(cur, "current_assets") is not None and val(cur, "current_liabilities") is not None:
        wc = val(cur, "current_assets") - val(cur, "current_liabilities")
    x1 = div(wc, assets)
    x2 = div(val(cur, "retained_earnings"), assets)
    x3 = div(val(cur, "operating_income"), assets)
    x4 = div(market_cap, val(cur, "liabilities"))
    x5 = div(val(cur, "revenue"), assets)
    if None in (x1, x2, x3, x4, x5):
        return {"z_score": None,
                "missing": [n for n, v in zip("X1 X2 X3 X4 X5".split(), [x1, x2, x3, x4, x5]) if v is None]}
    z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5
    zone = "safe" if z > 2.99 else ("grey" if z >= 1.81 else "distress")
    # Altman calibrated Z on leveraged manufacturers. For an asset-light company
    # with a large market cap and little debt, X4 (market cap / liabilities) runs
    # away and Z reaches double or triple digits -- that reflects the valuation
    # multiple, not solvency. Flag it so the number is not read as a health score.
    x4_share = (0.6 * x4 / z) if z else None
    caveat = None
    if x4_share is not None and x4_share > 0.7:
        caveat = ("X4 (市值/總負債) 占 Z 值 {:.0%}，此分數主要反映高市值與低負債，"
                  "而非償債能力；Altman Z 對輕資產公司不適用".format(x4_share))
    return {"z_score": round(z, 2), "zone": zone,
            "market_cap_dominated": caveat is not None, "caveat": caveat,
            "components": {"X1": round(x1, 4), "X2": round(x2, 4), "X3": round(x3, 4),
                           "X4": round(x4, 4), "X5": round(x5, 4)}}


def dupont(cur):
    rev, assets, equity = val(cur, "revenue"), val(cur, "assets"), val(cur, "equity")
    ni = val(cur, "net_income")
    nm, at, em = div(ni, rev), div(rev, assets), div(assets, equity)
    roe = None if None in (nm, at, em) else nm * at * em
    return {
        "net_margin": None if nm is None else round(nm, 4),
        "asset_turnover": None if at is None else round(at, 4),
        "equity_multiplier": None if em is None else round(em, 4),
        "roe": None if roe is None else round(roe, 4),
        "roe_direct_check": None if div(ni, equity) is None else round(div(ni, equity), 4),
    }


def latest_price(prices, ticker):
    sym = PRICE_ALIASES.get(ticker, ticker)
    series = prices.get("companies", prices.get("series", {})).get(sym) if prices else None
    if not series:
        return None, None
    return series["closes"][-1], series["dates"][-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+")
    args = parser.parse_args()

    if not FINANCIALS_PATH.exists():
        raise SystemExit("financials.json missing; run scripts/fetch_xbrl_financials.py first")
    fin = json.loads(FINANCIALS_PATH.read_text())
    prices = json.loads(PRICES_PATH.read_text()) if PRICES_PATH.exists() else None

    tickers = args.tickers or sorted(fin["companies"])
    results = {}

    print(f"{'ticker':7s}{'FY結束':13s}{'F-Score':>10s}{'Altman Z':>11s}{'ROE':>9s}{'毛利率':>9s}")
    for ticker in tickers:
        company = fin["companies"].get(ticker)
        if not company or len(company["periods"]) < 1:
            print(f"  {ticker:6s} 無資料")
            continue
        cur = company["periods"][0]
        prev = company["periods"][1] if len(company["periods"]) > 1 else {}

        price, price_date = latest_price(prices, ticker)
        diluted = val(cur, "diluted_shares")
        outstanding = (company.get("shares_outstanding") or {}).get("value")
        # Prefer the cover-page count for market cap; some filers mis-scale the
        # weighted-average diluted tag (Ondas by a factor of ~2,000).
        shares_for_cap = outstanding or diluted
        market_cap = price * shares_for_cap if price and shares_for_cap else None
        share_mismatch = None
        if diluted and outstanding:
            ratio = max(diluted, outstanding) / min(diluted, outstanding)
            if ratio > 5:
                share_mismatch = ("diluted={:,} 與 dei 流通股數={:,} 相差 {:.0f} 倍，"
                                  "已改用 dei 計算市值".format(diluted, outstanding, ratio))

        f = piotroski(cur, prev)
        z = altman_z(cur, market_cap)
        du = dupont(cur)
        gm = div(val(cur, "gross_profit"), val(cur, "revenue"))

        results[ticker] = {
            "cik": company["cik"],
            "entity_name": company["entity_name"],
            "taxonomy": company["taxonomy"],
            "fiscal_year_end": cur["fiscal_year_end"],
            "prior_fiscal_year_end": prev.get("fiscal_year_end"),
            "currency": (cur.get("revenue") or {}).get("unit"),
            "source_form": (cur.get("revenue") or {}).get("form"),
            "source_accession": (cur.get("revenue") or {}).get("accession"),
            "source_filed": (cur.get("revenue") or {}).get("filed"),
            "revenue": val(cur, "revenue"),
            "net_income": val(cur, "net_income"),
            "operating_cash_flow": val(cur, "operating_cash_flow"),
            "capex": val(cur, "capex"),
            "free_cash_flow": (None if val(cur, "operating_cash_flow") is None or val(cur, "capex") is None
                               else val(cur, "operating_cash_flow") - val(cur, "capex")),
            "assets": val(cur, "assets"),
            "liabilities": val(cur, "liabilities"),
            "equity": val(cur, "equity"),
            "diluted_shares": diluted,
            "shares_outstanding": outstanding,
            "shares_basis_for_market_cap": "dei_outstanding" if outstanding else "diluted",
            "share_count_warning": share_mismatch,
            "price_used": price,
            "price_date": price_date,
            "market_cap": market_cap,
            "gross_margin": None if gm is None else round(gm, 4),
            "piotroski": f,
            "altman_z": z,
            "dupont": du,
        }

        zs = z.get("z_score")
        f_txt = "{}/{}".format(f["score"], f["max_evaluated"])
        z_txt = "n/a" if zs is None else "{:.2f}".format(zs)
        roe_txt = "n/a" if du["roe"] is None else "{:.1f}%".format(du["roe"] * 100)
        gm_txt = "n/a" if gm is None else "{:.1f}%".format(gm * 100)
        print("{:7s}{:13s}{:>10s}{:>11s}{:>9s}{:>9s}".format(
            ticker, cur["fiscal_year_end"], f_txt, z_txt, roe_txt, gm_txt))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "financials_generated_at": fin.get("generated_at"),
        "source": "Derived from SEC XBRL Company Facts; prices from prices.json",
        "companies": results,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    print(f"\nWrote {OUTPUT_PATH.relative_to(REPO_ROOT)} ({len(results)} companies)")


if __name__ == "__main__":
    main()
