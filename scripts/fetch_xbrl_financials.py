"""Pull audited financials straight from SEC XBRL and write financials.json.

The analysis scripts in this vault used to carry hand-typed figures, several of
them marked "approximate", and derived ratios inherited the error. SEC publishes
every filer's tagged financials as structured JSON, so nothing here needs to be
transcribed by a human or a model.

    https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json

Two taxonomies appear in this portfolio: US filers report under `us-gaap`,
while foreign private issuers filing 20-F may report under `ifrs-full`
(NOK and TSM do). Tag names differ between them, so each concept below lists
candidates for both and the first one carrying annual data wins.

Usage:
    python3 scripts/fetch_xbrl_financials.py
    python3 scripts/fetch_xbrl_financials.py --tickers NVDA TSM
"""

import argparse
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "financials.json"

# SEC requires a genuine contact address; anonymous or fake agents get throttled.
SEC_HEADERS = {"User-Agent": "Sec_kb Research gibon1127@gmail.com"}

DEFAULT_TICKERS = [
    "AAPL", "AMZN", "ARM", "COHR", "GOOGL", "INTC", "META",
    "MRVL", "MSFT", "NOK", "NVDA", "ONDS", "TSLA", "TSM",
]

# kind: "instant" for balance-sheet items, "duration" for flows over a year.
CONCEPTS = {
    "assets":              ("instant",  ["Assets"], ["Assets"]),
    "liabilities":         ("instant",  ["Liabilities"], ["Liabilities"]),
    "equity":              ("instant",  ["StockholdersEquity",
                                         "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
                                        ["Equity", "EquityAttributableToOwnersOfParent"]),
    "current_assets":      ("instant",  ["AssetsCurrent"], ["CurrentAssets"]),
    "current_liabilities": ("instant",  ["LiabilitiesCurrent"], ["CurrentLiabilities"]),
    "long_term_debt":      ("instant",  ["LongTermDebtNoncurrent", "LongTermDebt"],
                                        ["NoncurrentPortionOfNoncurrentBorrowings", "NoncurrentBorrowings"]),
    "revenue":             ("duration", ["Revenues",
                                         "RevenueFromContractWithCustomerExcludingAssessedTax"],
                                        ["Revenue", "RevenueFromContractsWithCustomers"]),
    "net_income":          ("duration", ["NetIncomeLoss"], ["ProfitLoss"]),
    "gross_profit":        ("duration", ["GrossProfit"], ["GrossProfit"]),
    # Altman Z needs retained earnings and EBIT on top of the balance sheet.
    "retained_earnings":   ("instant",  ["RetainedEarningsAccumulatedDeficit"],
                                        ["RetainedEarnings"]),
    "operating_income":    ("duration", ["OperatingIncomeLoss"],
                                        ["ProfitLossFromOperatingActivities"]),
    "operating_cash_flow": ("duration", ["NetCashProvidedByUsedInOperatingActivities"],
                                        ["CashFlowsFromUsedInOperatingActivities"]),
    # NVIDIA books capex under PaymentsToAcquireProductiveAssets, not the more
    # common PropertyPlantAndEquipment tag.
    "capex":               ("duration", ["PaymentsToAcquirePropertyPlantAndEquipment",
                                         "PaymentsToAcquireProductiveAssets"],
                                        ["PurchaseOfPropertyPlantAndEquipment",
                                         "AcquisitionOfPropertyPlantAndEquipment"]),
    "diluted_shares":      ("duration", ["WeightedAverageNumberOfDilutedSharesOutstanding"],
                                        ["WeightedAverageNumberOfDilutedSharesOutstanding"]),
    # Net cash and shareholder yield for the valuation section.
    "cash":                ("instant",  ["CashAndCashEquivalentsAtCarryingValue"],
                                        ["CashAndCashEquivalents"]),
    # NVIDIA reports no ShortTermInvestments line; its current securities sit in
    # the maturity-bucketed AvailableForSale tag, which is the last resort here
    # because it is a narrower concept than the first two.
    "short_term_investments": ("instant", ["ShortTermInvestments", "MarketableSecuritiesCurrent",
                                           "AvailableForSaleSecuritiesDebtMaturitiesWithinOneYearFairValue"],
                                          ["CurrentFinancialAssetsAtFairValueThroughProfitOrLoss"]),
    "debt_current":        ("instant",  ["LongTermDebtCurrent", "DebtCurrent"],
                                        ["CurrentBorrowings", "ShorttermBorrowings"]),
    "buybacks":            ("duration", ["PaymentsForRepurchaseOfCommonStock"],
                                        ["PaymentsToAcquireOrRedeemEntitysShares"]),
    "dividends_paid":      ("duration", ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"],
                                        ["DividendsPaidClassifiedAsFinancingActivities",
                                         "DividendsPaid"]),
    # Cost of debt and the effective tax rate, for a CAPM/WACC estimate.
    "interest_expense":    ("duration", ["InterestExpense", "InterestExpenseDebt",
                                         "InterestExpenseNonoperating",
                                         "InterestIncomeExpenseNet"],
                                        ["InterestExpense", "FinanceCosts"]),
    "income_tax_expense":  ("duration", ["IncomeTaxExpenseBenefit"],
                                        ["IncomeTaxExpenseContinuingOperations"]),
    "pretax_income":       ("duration",
                            ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                             "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
                            ["ProfitLossBeforeTax"]),
}

ANNUAL_FORMS = {"10-K", "20-F"}


def http_json(url):
    req = urllib.request.Request(url, headers=SEC_HEADERS)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ticker_cik_map():
    data = http_json("https://www.sec.gov/files/company_tickers.json")
    return {v["ticker"]: str(v["cik_str"]).zfill(10) for v in data.values()}


def ranked_units(units):
    """Yield (unit, rows) with USD first, then other currencies, then the rest.

    TSM tags the same figures in both TWD and USD; without a stable preference
    the currency depends on which tag happened to be processed last.
    """
    names = sorted(units, key=lambda n: (n != "USD", len(n) != 3, n))
    return [(n, units[n]) for n in names]


def annual_values(facts, tags, kind):
    """Return {fiscal_year_end: value} merged across every candidate tag.

    Filers migrate between tags over time -- Apple and Microsoft moved from
    `Revenues` to `RevenueFromContractWithCustomerExcludingAssessedTax`, so the
    old tag stops receiving data while still holding a decade of history.
    Taking the first tag that has *any* data therefore lands on a stale fiscal
    year (Microsoft resolved to FY2010 that way). Merge all candidates and let
    the most recently filed value win for each period.
    """
    picked = {}
    for tag in tags:
        if tag not in facts:
            continue
        for unit, rows in ranked_units(facts[tag]["units"]):
            for r in rows:
                if r.get("form") not in ANNUAL_FORMS:
                    continue
                if kind == "duration":
                    if not r.get("start"):
                        continue
                    span = (datetime.fromisoformat(r["end"]) - datetime.fromisoformat(r["start"])).days
                    if not 300 <= span <= 400:  # a full year, not a quarter
                        continue
                prev = picked.get(r["end"])
                # Never trade a USD figure for a local-currency one. Otherwise a
                # strictly newer filing wins, so restatements supersede; on an
                # equal filing date the earlier candidate tag holds, which makes
                # the tag list a priority order. That matters where candidates
                # are alternative concepts rather than a renamed one -- short-term
                # investments falls back to a maturity-bucketed tag that must not
                # displace a company's primary one.
                if prev is not None:
                    if prev["unit"] == "USD" and unit != "USD":
                        continue
                    if not (unit == "USD" and prev["unit"] != "USD") \
                       and r.get("filed", "") <= prev["filed"]:
                        continue
                picked[r["end"]] = {"val": r["val"], "filed": r.get("filed", ""),
                                    "form": r["form"], "accn": r.get("accn", ""),
                                    "tag": tag, "unit": unit}
    if not picked:
        return None, None, {}
    latest = max(picked)
    return picked[latest]["tag"], picked[latest]["unit"], picked


def build_ticker(ticker, cik):
    facts_doc = http_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
    taxonomies = facts_doc["facts"]
    taxonomy = "us-gaap" if "us-gaap" in taxonomies else "ifrs-full"
    facts = taxonomies.get(taxonomy, {})

    collected = {}
    for concept, (kind, gaap_tags, ifrs_tags) in CONCEPTS.items():
        tags = gaap_tags if taxonomy == "us-gaap" else ifrs_tags
        tag, unit, by_year = annual_values(facts, tags, kind)
        if by_year:
            collected[concept] = {"tag": tag, "unit": unit, "by_fiscal_year_end": by_year}

    # Cover-page share count, tagged under `dei` rather than the accounting
    # taxonomy. Ondas tags WeightedAverageNumberOfDilutedSharesOutstanding as
    # 221,769 against a real float of ~496M, which would put its market cap at
    # $1.7M; the cover page is the reliable basis for market capitalisation.
    shares_outstanding = None
    dei = taxonomies.get("dei", {}).get("EntityCommonStockSharesOutstanding")
    if dei:
        rows = [r for u in dei["units"].values() for r in u if r.get("end")]
        if rows:
            newest = max(rows, key=lambda r: (r.get("end", ""), r.get("filed", "")))
            shares_outstanding = {"value": newest["val"], "as_of": newest["end"],
                                  "tag": "dei:EntityCommonStockSharesOutstanding"}

    # The fiscal years we can actually report on: those with a revenue figure.
    year_ends = sorted(collected.get("revenue", {}).get("by_fiscal_year_end", {}), reverse=True)
    if not year_ends:
        year_ends = sorted(collected.get("net_income", {}).get("by_fiscal_year_end", {}), reverse=True)

    periods = []
    for end in year_ends[:6]:                    # latest FY, prior FY for F-Score,
                                                 # and enough history for a CAGR
        row = {"fiscal_year_end": end}
        for concept, payload in collected.items():
            hit = payload["by_fiscal_year_end"].get(end)
            if hit:
                row[concept] = {"value": hit["val"], "unit": hit["unit"],
                                "tag": hit["tag"], "form": hit["form"],
                                "accession": hit["accn"], "filed": hit["filed"]}
        periods.append(row)

    return {"cik": cik, "entity_name": facts_doc.get("entityName", ticker),
            "taxonomy": taxonomy, "shares_outstanding": shares_outstanding,
            "periods": periods}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    args = parser.parse_args()

    cik_map = ticker_cik_map()
    companies, failed = {}, []

    for ticker in args.tickers:
        cik = cik_map.get(ticker)
        if not cik:
            failed.append(f"{ticker} (no CIK)")
            print(f"  {ticker:6s} FAILED - not in SEC ticker index")
            continue
        try:
            entry = build_ticker(ticker, cik)
        except Exception as exc:                  # noqa: BLE001 - report and continue
            failed.append(f"{ticker} ({type(exc).__name__})")
            print(f"  {ticker:6s} FAILED - {type(exc).__name__}: {exc}")
            time.sleep(0.15)
            continue

        companies[ticker] = entry
        latest = entry["periods"][0] if entry["periods"] else {}
        rev = latest.get("revenue", {}).get("value")
        got = sum(1 for k in CONCEPTS if k in latest)
        print(f"  {ticker:6s} {entry['taxonomy']:9s} FY{latest.get('fiscal_year_end','?')}  "
              f"{got}/{len(CONCEPTS)} 科目  "
              f"營收 {rev/1e6:,.0f}M" if rev else f"  {ticker:6s} {entry['taxonomy']}")
        time.sleep(0.15)                          # stay well under SEC's rate limit

    if not companies:
        raise SystemExit("No companies fetched; refusing to overwrite financials.json")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "SEC XBRL Company Facts API (data.sec.gov/api/xbrl/companyfacts)",
        "companies": companies,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"\nWrote {OUTPUT_PATH.relative_to(REPO_ROOT)} "
          f"({len(companies)} companies, {size_kb:.1f} KB)")
    if failed:
        print(f"Missing: {', '.join(failed)}")


if __name__ == "__main__":
    main()
