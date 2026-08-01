"""Propose DCF growth and discount rates from data, for review before use.

Growth and WACC are judgements, so this script does not write
dcf_assumptions.json. It derives candidate values, shows the working, and
prints a JSON block to paste in. A human still decides what goes in the file.

What is derived rather than assumed:

    beta            regressed from 3 years of weekly returns against SPY
    risk-free       ^IRX 13-week T-bill, trailing 12-month mean, from prices.json
    cost of debt    interest expense / average total debt, per the filings
    tax rate        income tax expense / pre-tax income, per the filings
    capital weights market cap vs total debt
    growth          revenue CAGR over the fiscal years SEC has published

The one genuine assumption is the equity risk premium, set below and applied
uniformly. It is stated rather than buried because every cost of equity here
moves with it.

    python3 scripts/estimate_dcf_inputs.py
    python3 scripts/estimate_dcf_inputs.py --tickers AAPL ARM
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FINANCIALS_PATH = REPO_ROOT / "financials.json"
FUNDAMENTALS_PATH = REPO_ROOT / "fundamentals.json"
PRICES_PATH = REPO_ROOT / "prices.json"

# The single judgement input. Damodaran's implied US ERP has sat around
# 4-5.5% for the last decade; 5.0% is a mid-range, widely used figure.
EQUITY_RISK_PREMIUM = 0.050

# Growth is capped because a DCF compounds it for ten years. A company cannot
# outgrow the economy forever, and an uncapped historical CAGR from a company
# mid-hypergrowth produces a valuation that says more about the arithmetic
# than the business.
GROWTH_CAP = 0.25
GROWTH_FLOOR = 0.02

PRICE_ALIASES = {"GOOGL": "GOOG"}
MARKET_SYMBOL = "SPY"


def weekly(dates, closes):
    weeks = {}
    for d, c in zip(dates, closes):
        y, w, _ = datetime.fromisoformat(d).isocalendar()
        weeks[(y, w)] = (d, c)
    return [weeks[k] for k in sorted(weeks)]


def beta_vs_market(prices, ticker, years=3):
    sym = PRICE_ALIASES.get(ticker, ticker)
    stock = prices["series"].get(sym)
    market = prices["series"].get(MARKET_SYMBOL)
    if not stock or not market:
        return None, "缺股價或市場指數"

    sw, mw = dict(weekly(stock["dates"], stock["closes"])), dict(weekly(market["dates"], market["closes"]))
    common = sorted(set(sw) & set(mw))
    if not common:
        return None, "無重疊交易週"
    cutoff = datetime.fromisoformat(common[-1]).replace(
        year=datetime.fromisoformat(common[-1]).year - years).isoformat()[:10]
    common = [d for d in common if d >= cutoff]
    if len(common) < 60:
        return None, f"重疊資料僅 {len(common)} 週，不足以估計 beta"

    rs = [sw[common[i]] / sw[common[i - 1]] - 1 for i in range(1, len(common))]
    rm = [mw[common[i]] / mw[common[i - 1]] - 1 for i in range(1, len(common))]
    mean_s, mean_m = sum(rs) / len(rs), sum(rm) / len(rm)
    cov = sum((a - mean_s) * (b - mean_m) for a, b in zip(rs, rm)) / len(rs)
    var = sum((b - mean_m) ** 2 for b in rm) / len(rm)
    if var == 0:
        return None, "市場變異數為零"
    return cov / var, f"{len(rs)} 週，對 {MARKET_SYMBOL}"


def revenue_cagr(periods):
    """CAGR across the fiscal years SEC has published for this filer."""
    rows = [(p["fiscal_year_end"], p.get("revenue", {}).get("value"))
            for p in periods if p.get("revenue")]
    rows = [(d, v) for d, v in rows if v and v > 0]
    if len(rows) < 3:
        return None, None, f"僅 {len(rows)} 個年度有營收，不足以推算 CAGR"
    rows.sort()
    first, last = rows[0], rows[-1]
    span_years = (datetime.fromisoformat(last[0]) - datetime.fromisoformat(first[0])).days / 365.25
    if span_years < 2:
        return None, None, "年度區間過短"
    cagr = (last[1] / first[1]) ** (1 / span_years) - 1
    return cagr, f"{first[0]} → {last[0]}（{span_years:.1f} 年）", None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+")
    args = parser.parse_args()

    fin = json.loads(FINANCIALS_PATH.read_text())["companies"]
    fund = json.loads(FUNDAMENTALS_PATH.read_text())["companies"]
    prices = json.loads(PRICES_PATH.read_text())

    rf_vals = prices.get("risk_free", {}).get("values") or []
    rf = (sum(rf_vals[-252:]) / len(rf_vals[-252:]) / 100) if rf_vals else None

    tickers = args.tickers or sorted(fin)
    proposals = {}

    print(f"市場風險溢酬 (ERP，唯一的判斷輸入): {EQUITY_RISK_PREMIUM*100:.1f}%")
    print(f"無風險利率 (^IRX 近 12 個月平均): {rf*100:.3f}%\n" if rf else "無風險利率: 缺\n")
    print("{:7s}{:>7s}{:>9s}{:>9s}{:>9s}{:>9s}  {}".format(
        "ticker", "beta", "Ke", "Kd(稅後)", "WACC", "營收CAGR", "備註"))

    for t in tickers:
        company = fin.get(t)
        if not company or not company["periods"]:
            continue
        cur = company["periods"][0]
        f = fund.get(t, {})

        b, b_note = beta_vs_market(prices, t)
        cagr, cagr_span, cagr_err = revenue_cagr(company["periods"])

        # Cost of equity via CAPM.
        ke = (rf + b * EQUITY_RISK_PREMIUM) if (rf is not None and b is not None) else None

        # After-tax cost of debt from the filings.
        def v(k):
            e = cur.get(k)
            return e["value"] if e else None
        debt = (v("long_term_debt") or 0) + (v("debt_current") or 0)
        interest = abs(v("interest_expense")) if v("interest_expense") else None
        kd = (interest / debt) if interest and debt else None
        tax = None
        if v("income_tax_expense") is not None and v("pretax_income"):
            tax = v("income_tax_expense") / v("pretax_income")
            tax = min(max(tax, 0.0), 0.35)          # ignore one-off tax anomalies
        kd_after = kd * (1 - tax) if kd is not None and tax is not None else kd

        mcap = f.get("market_cap")
        wacc = None
        if ke is not None and mcap:
            if kd_after is not None and debt:
                total = mcap + debt
                wacc = ke * (mcap / total) + kd_after * (debt / total)
            else:
                wacc = ke                            # no meaningful debt

        growth = None
        if cagr is not None:
            growth = min(max(cagr, GROWTH_FLOOR), GROWTH_CAP)

        proposals[t] = {
            "growth": None if growth is None else round(growth, 4),
            "wacc": None if wacc is None else round(wacc, 4),
            "beta": None if b is None else round(b, 3),
            "raw_revenue_cagr": None if cagr is None else round(cagr, 4),
            "cagr_span": cagr_span, "cagr_error": cagr_err,
            "cost_of_equity": None if ke is None else round(ke, 4),
            "cost_of_debt_after_tax": None if kd_after is None else round(kd_after, 4),
            "effective_tax_rate": None if tax is None else round(tax, 4),
            "beta_note": b_note,
        }

        fmt = lambda x, s="%": ("n/a" if x is None else
                                (f"{x*100:.2f}%" if s == "%" else f"{x:.2f}"))
        capped = "" if (cagr is None or growth is None or abs(cagr - growth) < 1e-9) \
            else f"CAGR {cagr*100:.1f}% 已裁切至 {growth*100:.1f}%"
        print("{:7s}{:>7s}{:>9s}{:>9s}{:>9s}{:>9s}  {}".format(
            t, fmt(b, "n"), fmt(ke), fmt(kd_after), fmt(wacc),
            fmt(cagr), capped or (cagr_err or "")))

    print("\n貼進 dcf_assumptions.json 的 companies（僅供參考，請自行判斷後再採用）：")
    print(json.dumps({t: {"growth": p["growth"], "wacc": p["wacc"]}
                      for t, p in proposals.items()}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
