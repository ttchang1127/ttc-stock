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
PRICE_ALIASES_REVERSE = {}

# Ordinary shares represented by one traded share, where they differ.
#
# The cover-page count is in ordinary shares while prices.json holds the quoted
# ADR price, so multiplying them directly answers a question nobody asked. TSMC
# came out at a $10.9tn market capitalisation -- 123x its revenue, against 25x
# for NVIDIA -- and that figure fed Altman Z, the WACC weights and the DCF's
# per-share value alike.
#
# This is a property of the security, not a judgement about the company: one
# TSMC ADR is five ordinary shares, published in the deposit agreement. Arm and
# Nokia also file 20-Fs and are also ADRs, but theirs are one-for-one and are
# left out rather than listed as 1, so the map contains only real exceptions.
ADR_ORDINARY_PER_SHARE = {"TSM": 5}


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


def gross_profit(period):
    """GrossProfit where tagged, otherwise revenue less cost of sales.

    Amazon, Alphabet, Meta and Coherent never tag GrossProfit, so their gross
    margin read 資料不足 and Piotroski criterion 8 went unscored -- shrinking
    their F-Score denominators for a figure their income statements do contain,
    just as two separate lines.
    """
    gp = val(period, "gross_profit")
    if gp is not None:
        return gp, "tag"
    rev, cogs = val(period, "revenue"), val(period, "cogs")
    if rev is None or cogs is None:
        return None, None
    return rev - cogs, "revenue_less_cogs"


def piotroski(cur, prev):
    """The nine Piotroski criteria, each computed or explicitly unavailable."""
    roa_cur = div(val(cur, "net_income"), val(cur, "assets"))
    roa_prev = div(val(prev, "net_income"), val(prev, "assets"))
    lev_cur = div(val(cur, "long_term_debt"), val(cur, "assets"))
    lev_prev = div(val(prev, "long_term_debt"), val(prev, "assets"))
    cr_cur = div(val(cur, "current_assets"), val(cur, "current_liabilities"))
    cr_prev = div(val(prev, "current_assets"), val(prev, "current_liabilities"))
    gm_cur = div(gross_profit(cur)[0], val(cur, "revenue"))
    gm_prev = div(gross_profit(prev)[0], val(prev, "revenue"))
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


def weekly_closes(dates, closes):
    """Last close of each ISO week, paired with that week's date."""
    weeks = {}
    for d, c in zip(dates, closes):
        y, w, _ = datetime.fromisoformat(d).isocalendar()
        weeks[(y, w)] = (d, c)          # later rows overwrite, leaving week-end
    return [weeks[k] for k in sorted(weeks)]


def sortino(prices, ticker, years, mar=0.0):
    """Annualised Sortino on weekly returns, measured against MAR (default 0).

    Sortino = (mean weekly return x 52) / (downside deviation x sqrt(52)),
    where downside deviation counts only returns below MAR. Returns None when
    the price history does not cover the window -- ARM listed in Sept 2023, so
    its 5-year figure cannot exist.
    """
    sym = PRICE_ALIASES_REVERSE.get(ticker, ticker)
    series = (prices or {}).get("series", {}).get(sym) or (prices or {}).get("series", {}).get(
        PRICE_ALIASES.get(ticker, ticker))
    if not series:
        return {"value": None, "reason": "無股價資料"}

    weekly = weekly_closes(series["dates"], series["closes"])
    if len(weekly) < 2:
        return {"value": None, "reason": "資料點不足"}

    last_date = datetime.fromisoformat(weekly[-1][0])
    cutoff = last_date.replace(year=last_date.year - years)
    window = [(d, c) for d, c in weekly if datetime.fromisoformat(d) >= cutoff]
    needed = int(52 * years * 0.9)      # allow for holidays and thin weeks
    if len(window) < needed:
        return {"value": None,
                "reason": "股價歷史不足 {} 年，僅 {} 週，起始 {}".format(
                    years, len(window), weekly[0][0])}

    rets = [window[i][1] / window[i - 1][1] - 1 for i in range(1, len(window))]
    downside = [min(r - mar, 0.0) ** 2 for r in rets]
    dd = (sum(downside) / len(downside)) ** 0.5
    if dd == 0:
        return {"value": None, "reason": "下行波動為零"}
    mean_excess = sum(r - mar for r in rets) / len(rets)
    value = (mean_excess * 52) / (dd * (52 ** 0.5))
    return {"value": round(value, 2), "weeks": len(rets),
            "window_start": window[0][0], "window_end": window[-1][0],
            "mar": mar, "basis": "weekly returns, annualised"}


def risk_free_annual(prices, since_date):
    """Mean 13-week T-bill yield over the window, as a decimal (0.037 = 3.7%)."""
    rf = (prices or {}).get("risk_free")
    if not rf:
        return None
    vals = [v for d, v in zip(rf["dates"], rf["values"]) if d >= since_date]
    if not vals:
        return None
    return sum(vals) / len(vals) / 100.0


def sortino_daily_12m(prices, ticker):
    """Sortino on 12 months of daily returns, for comparison with public screeners.

    The headline value uses MAR = 0. That was determined empirically, not
    assumed: PortfoliosLab's own documentation describes a risk-free MAR, but
    its published figures only reproduce at MAR = 0 -- NVDA 0.76 against 0.75
    computed, TSLA 0.36 against 0.36. Using the risk-free rate instead gives
    0.60 and 0.24, which match nothing they publish.

    The risk-free variant is reported alongside as value_vs_riskfree, since it
    is the textbook definition and the more conservative reading.

    This is a different measurement from the 3/5-year weekly figures, not a
    correction of them: frequency, window and MAR all differ.
    """
    sym = PRICE_ALIASES.get(ticker, ticker)
    series = (prices or {}).get("series", {}).get(sym)
    if not series:
        return {"value": None, "reason": "無股價資料"}

    last = datetime.fromisoformat(series["dates"][-1])
    cutoff = last.replace(year=last.year - 1).isoformat()[:10]
    window = [(d, c) for d, c in zip(series["dates"], series["closes"]) if d >= cutoff]
    if len(window) < 200:                    # a trading year is ~252 sessions
        return {"value": None,
                "reason": "股價歷史不足 12 個月，僅 {} 個交易日".format(len(window))}

    rets = [window[i][1] / window[i - 1][1] - 1 for i in range(1, len(window))]

    def annualised(mar_daily):
        dd = (sum(min(r - mar_daily, 0.0) ** 2 for r in rets) / len(rets)) ** 0.5
        if dd == 0:
            return None
        mean_excess = sum(r - mar_daily for r in rets) / len(rets)
        return (mean_excess * 252) / (dd * (252 ** 0.5))

    headline = annualised(0.0)
    if headline is None:
        return {"value": None, "reason": "下行波動為零"}

    rf_annual = risk_free_annual(prices, cutoff)
    vs_rf = None
    if rf_annual is not None:
        vs_rf = annualised((1 + rf_annual) ** (1 / 252) - 1)

    return {"value": round(headline, 2), "sessions": len(rets),
            "window_start": window[0][0], "window_end": window[-1][0],
            "mar": 0.0, "mar_note": "MAR=0，與 PortfoliosLab 等公開篩選器一致",
            "value_vs_riskfree": None if vs_rf is None else round(vs_rf, 2),
            "risk_free_annual": None if rf_annual is None else round(rf_annual, 5),
            "risk_free_source": "^IRX 13週美國國庫券，期間平均",
            "basis": "daily returns, annualised"}


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
        reported_shares = outstanding or diluted
        adr_ratio = ADR_ORDINARY_PER_SHARE.get(ticker)
        shares_for_cap = (reported_shares / adr_ratio
                          if reported_shares and adr_ratio else reported_shares)
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
        gp, gp_basis = gross_profit(cur)
        gm = div(gp, val(cur, "revenue"))

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
            "shares_for_market_cap": shares_for_cap,
            "adr_ordinary_per_share": adr_ratio,
            "adr_note": None if not adr_ratio else
                        "申報股數為普通股，股價為 ADR 報價；已除以 {} 換算為 ADR 當量股數"
                        .format(adr_ratio),
            "share_count_warning": share_mismatch,
            "price_used": price,
            "price_date": price_date,
            "market_cap": market_cap,
            "gross_profit": gp,
            "gross_margin": None if gm is None else round(gm, 4),
            "gross_margin_basis": gp_basis,
            "piotroski": f,
            "altman_z": z,
            "dupont": du,
            "sortino": {"3y": sortino(prices, ticker, 3),
                        "5y": sortino(prices, ticker, 5),
                        "12m_daily": sortino_daily_12m(prices, ticker)},
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
