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
import re
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
    # Borrowings. The IFRS list needs LongtermBorrowings for Nokia and TSMC,
    # neither of which uses the two tags originally listed here -- both were
    # coming back with no debt at all.
    "long_term_debt":      ("instant",  ["LongTermDebtNoncurrent", "LongTermDebt"],
                                        ["NoncurrentPortionOfNoncurrentBorrowings", "NoncurrentBorrowings",
                                         "LongtermBorrowings"]),
    # Bonds are a separate line under IFRS and are summed with borrowings
    # downstream, never substituted for them: TSMC carries $28.3bn of noncurrent
    # bonds against $1.0bn of noncurrent borrowings, so taking either one alone
    # is wrong by an order of magnitude. US filers fold bonds into LongTermDebt,
    # hence no us-gaap candidates.
    "bonds_noncurrent":    ("instant",  [], ["NoncurrentPortionOfNoncurrentBondsIssued"]),
    "bonds_current":       ("instant",  [], ["CurrentBondsIssuedAndCurrentPortionOfNoncurrentBondsIssued"]),
    # Finance leases are debt under both ASC 842 and IFRS 16. Arm has no
    # borrowings whatsoever -- its only debt-like obligations are leases -- so
    # without these its balance sheet is indistinguishable from one where the
    # tags are simply absent.
    "finance_lease_current":    ("instant", ["FinanceLeaseLiabilityCurrent"],
                                            ["CurrentLeaseLiabilities"]),
    "finance_lease_noncurrent": ("instant", ["FinanceLeaseLiabilityNoncurrent"],
                                            ["NoncurrentLeaseLiabilities"]),
    # Ondas reports its borrowings only as convertible debt. ConvertibleDebt* is
    # the roll-up concept; the narrower ConvertibleNotesPayableCurrent it also
    # tags is a component of it and would double-count if both were summed.
    "convertible_debt_current":    ("instant", ["ConvertibleDebtCurrent"], []),
    "convertible_debt_noncurrent": ("instant", ["ConvertibleDebtNoncurrent"], []),
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
    # Neither IFRS filer uses the short tag names: TSMC reports
    # PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities and
    # Nokia a combined PP&E-and-intangibles tag, so both came back with no
    # capex at all and therefore no free cash flow -- which also left their DCF
    # reporting 缺 FCF. Nokia's figure is the broader one: it includes
    # intangibles other than goodwill, so its FCF is the more conservative of
    # the two definitions. The tag actually used is recorded per period.
    "capex":               ("duration", ["PaymentsToAcquirePropertyPlantAndEquipment",
                                         "PaymentsToAcquireProductiveAssets"],
                                        ["PurchaseOfPropertyPlantAndEquipment",
                                         "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
                                         "PurchaseOfPropertyPlantAndEquipmentIntangibleAssetsOtherThanGoodwillInvestmentPropertyAndOtherNoncurrentAssets",
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
    "debt_current":        ("instant",  ["LongTermDebtCurrent", "DebtCurrent", "NotesPayableCurrent"],
                                        ["CurrentBorrowings", "ShorttermBorrowings",
                                         "CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings",
                                         "CurrentPortionOfLongtermBorrowings"]),
    "buybacks":            ("duration", ["PaymentsForRepurchaseOfCommonStock"],
                                        ["PaymentsToAcquireOrRedeemEntitysShares"]),
    "dividends_paid":      ("duration", ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"],
                                        ["DividendsPaidClassifiedAsFinancingActivities",
                                         "DividendsPaid"]),
    # Cost of debt and the effective tax rate, for a CAPM/WACC estimate.
    # Coherent moved from InterestExpense to InterestExpenseOperating after
    # FY2023. FinanceLeaseInterestExpense is deliberately last: it is only a
    # component, but for Arm it is the whole of the interest bill, since Arm has
    # no borrowings at all. Arm's InterestIncomeExpenseNonoperatingNet is not a
    # candidate -- it is net interest *income*, and treating it as an expense
    # would manufacture a coverage ratio out of money the company receives.
    "interest_expense":    ("duration", ["InterestExpense", "InterestExpenseDebt",
                                         "InterestExpenseOperating",
                                         "InterestExpenseNonoperating",
                                         "InterestIncomeExpenseNet",
                                         "FinanceLeaseInterestExpense"],
                                        ["InterestExpense", "FinanceCosts"]),
    "income_tax_expense":  ("duration", ["IncomeTaxExpenseBenefit"],
                                        ["IncomeTaxExpenseContinuingOperations"]),
    # Beneish M-Score inputs. Each index compares the current year against the
    # prior one, so every one of these needs two periods to be of any use.
    "receivables":         ("instant",  ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"],
                                        ["TradeAndOtherCurrentReceivables", "CurrentTradeReceivables"]),
    # Most filers here have migrated off PropertyPlantAndEquipmentNet to the
    # ASC 842 tag that folds finance-lease right-of-use assets in. Alphabet,
    # Meta, Tesla, Intel and Coherent tag only the newer one for their latest
    # year, so without it the asset quality index has no current period. Note
    # the "After" prefix: the sibling ...AccumulatedDepreciationAndAmortization
    # tag is the contra-account, not net book value.
    "ppe_net":             ("instant",  ["PropertyPlantAndEquipmentNet",
                                         "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization"],
                                        ["PropertyPlantAndEquipment"]),
    "lt_investments":      ("instant",  ["LongTermInvestments", "MarketableSecuritiesNoncurrent",
                                         "AvailableForSaleSecuritiesDebtSecuritiesNoncurrent"],
                                        ["NoncurrentFinancialAssets", "OtherNoncurrentFinancialAssets"]),
    # Beneish's depreciation index is defined on depreciation excluding
    # amortisation, so the narrow `Depreciation` tag is preferred where a filer
    # provides it; the combined D&A tags are the fallback for those that do not.
    # Which one was used is recorded per company in financial_health.json,
    # because the two are not interchangeable across companies.
    "depreciation":        ("duration", ["Depreciation",
                                         "DepreciationDepletionAndAmortization",
                                         "DepreciationAmortizationAndAccretionNet",
                                         "DepreciationAndAmortization"],
                                        ["DepreciationExpense",
                                         "DepreciationAndAmortisationExpense"]),
    "sga":                 ("duration", ["SellingGeneralAndAdministrativeExpense",
                                         "GeneralAndAdministrativeExpense"],
                                        ["SellingGeneralAndAdministrativeExpense",
                                         "AdministrativeExpense"]),
    # Cost of sales. Beneish's gross margin index needs it, and it also lets the
    # four filers that never tag GrossProfit (Amazon, Alphabet, Meta, Coherent)
    # have a gross margin at all, by subtraction.
    "cogs":                ("duration", ["CostOfRevenue", "CostOfGoodsAndServicesSold",
                                         "CostOfGoodsSold"],
                                        ["CostOfSales"]),
    "pretax_income":       ("duration",
                            ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                             "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
                            ["ProfitLossBeforeTax"]),
}

ANNUAL_FORMS = {"10-K", "20-F"}

# ---------------------------------------------------------------------------
# Fallback: read a filing's own XBRL when companyfacts has not ingested it.
#
# TSMC filed its FY2025 20-F on 2026-04-16, fully tagged -- SEC renders 169
# statements from it -- yet companyfacts carries exactly two facts from that
# accession, the cover-page share count and one buyback tag. The frames API
# returns 404 for the same period. So the vault sat on FY2024 for twenty
# months and reported a company 37% smaller than it is, and the note in the
# SOP said this could only be disclosed. That was wrong: the numbers are in
# the filing, and SEC's own rendered reports carry the element name beside
# every figure, so reading them is not layout guesswork.
#
# This runs only when companyfacts is behind the newest annual filing, and
# only after the parse agrees with companyfacts on the comparative years the
# filing restates -- thirteen of thirteen for TSMC. A parse that disagrees is
# refused rather than merged.

MONTH_NUMBER = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}

# Only the primary statements. The note-level reports that follow them tag the
# same concepts under dimensions -- by segment, by equity component, by
# instrument -- and this parser reads values, not contexts, so a note table
# would attribute a component to the consolidated concept. Left unfiltered,
# 22 of TSMC's comparative figures disagreed with companyfacts for exactly
# that reason. The statement of changes in equity is excluded on the same
# grounds: every one of its columns is a dimension.
# Anchored at the start: a primary statement is titled "CONSOLIDATED STATEMENTS
# OF ..."; a note carries a topic prefix, as in "INCOME TAX - Analysis of
# Deferred Income Tax Assets ... in Consolidated Statements ...". Matching
# anywhere in the title pulled three of TSMC's notes in, and one of them
# overwrote the balance sheet's deferred tax assets with a dimensional
# component.
PRIMARY_STATEMENT = re.compile(
    r"^\s*(consolidated\s+|condensed\s+)*(statements?\s+of\s+"
    r"(financial position|profit or loss|income|operations|comprehensive|"
    r"cash flows)|balance sheets?)", re.I)


def http_text(url):
    req = urllib.request.Request(url, headers=SEC_HEADERS)
    with urllib.request.urlopen(req) as resp:
        return resp.read().decode("utf-8", "ignore")


def parse_rendered_report(html):
    """{(taxonomy, tag): {(period_end, unit): value}} from one R#.htm."""
    scale = 1e6 if re.search(r"in Millions", html, re.I) else (
            1e3 if re.search(r"in Thousands", html, re.I) else 1)
    columns, facts = None, {}

    for row in re.findall(r"<tr[^>]*>.*?</tr>", html, re.S):
        headers = re.findall(r'<th class="th"[^>]*>(.*?)</th>', row, re.S)
        if columns is None and len(headers) > 1:
            parsed = []
            for th in headers:
                divs = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", d)).strip()
                        for d in re.findall(r"<div>(.*?)</div>", th, re.S)]
                m = re.match(r"([A-Z][a-z]{2})\.?\s+(\d{1,2}),\s*(\d{4})",
                             divs[0]) if divs else None
                if not m:
                    parsed.append(None)
                    continue
                end = "{}-{:02d}-{:02d}".format(
                    m.group(3), MONTH_NUMBER[m.group(1)], int(m.group(2)))
                unit = next((re.match(r"([A-Z]{3})", d).group(1) for d in divs[1:]
                             if re.match(r"[A-Z]{3}\b", d)), None)
                parsed.append((end, unit))
            if any(parsed):
                columns = parsed
            continue

        ref = re.search(r"defref_([A-Za-z0-9\-]+)_([A-Za-z0-9_]+)", row)
        if not ref or columns is None:
            continue
        key = (ref.group(1), ref.group(2))
        for i, cell in enumerate(re.findall(r'<td class="num[p]?"[^>]*>(.*?)</td>',
                                            row, re.S)):
            if i >= len(columns) or columns[i] is None:
                continue
            txt = re.sub(r"<[^>]+>", "", cell).replace(",", "").replace("$", "").strip()
            negative = txt.startswith("(") and txt.endswith(")")
            txt = txt.strip("()").strip()
            if not re.fullmatch(r"-?\d+(\.\d+)?", txt or "x"):
                continue
            facts.setdefault(key, {})[columns[i]] = (
                float(txt) * scale * (-1 if negative else 1))
    return facts


def filing_facts(cik, accession):
    """Every statement-level fact in one filing, from SEC's rendered reports."""
    base = "https://www.sec.gov/Archives/edgar/data/{}/{}/".format(
        int(cik), accession.replace("-", ""))
    summary = http_text(base + "FilingSummary.xml")
    wanted = [re.search(r"<HtmlFileName>(R\d+\.htm)</HtmlFileName>", rep)
              for rep in re.findall(r"<Report[^>]*>.*?</Report>", summary, re.S)
              if PRIMARY_STATEMENT.search(
                  (re.search(r"<ShortName>([^<]*)</ShortName>", rep) or
                   re.search(r"()", "")).group(1))]
    facts = {}
    for name in [m.group(1) for m in wanted if m]:
        try:
            page = http_text(base + name)
        except Exception:                      # noqa: BLE001 - one bad report
            continue                           # should not lose the others
        for key, values in parse_rendered_report(page).items():
            # First statement to report a concept for a period wins. Reports are
            # ordered statements-first, so this is a second guard against a note
            # restating a consolidated figure with one of its components.
            slot = facts.setdefault(key, {})
            for period, value in values.items():
                slot.setdefault(period, value)
        time.sleep(0.12)
    return facts


def agrees_with_companyfacts(parsed, raw_facts, taxonomy, exclude_end, tags_used):
    """Check the parse against the years companyfacts already covers.

    The filing restates its prior years, and those are values already held from
    a source we trust. If the two disagree the parse is misreading the table --
    a wrong column, a wrong scale -- and merging it would put invented figures
    into the vault under a real accession number.

    The comparison goes against raw companyfacts rather than the picked values,
    because the two disagree about *currency*, not about the numbers: TSMC's
    filing presents comparative years in TWD only while companyfacts resolves
    to USD. Matching on the filing's own unit is what makes the check possible
    at all -- against the picked values it finds nothing to compare.
    """
    compared, mismatched, signs = 0, [], {}
    for (tax, tag), values in parsed.items():
        # Only the concepts this vault actually reads. Validating all 170 tags
        # a filing renders drags in items whose statement context differs from
        # the one companyfacts resolved -- translation differences appear in
        # both profit or loss and other comprehensive income under the same
        # element name -- and none of them is a figure we would merge.
        if tax != taxonomy or tag not in tags_used:
            continue
        rows_by_unit = (raw_facts.get(tag) or {}).get("units", {})
        for (end, unit), value in values.items():
            if end == exclude_end or unit not in rows_by_unit:
                continue
            rows = [r for r in rows_by_unit[unit]
                    if r.get("end") == end and r.get("form") in ANNUAL_FORMS]
            if not rows:
                continue
            known = max(rows, key=lambda r: r.get("filed", ""))["val"]
            if known == 0:
                continue
            # The rendered report shows what the presentation linkbase displays,
            # and a negated label flips the sign of an expense: finance costs
            # render as (10,495.4) where the underlying fact is +10,495.4. The
            # comparative years therefore do more than confirm the parse -- they
            # establish the sign convention for each element, which is then
            # applied to the year being merged.
            compared += 1
            if abs(value - known) / abs(known) <= 0.001:
                signs.setdefault(tag, set()).add(1)
            elif abs(-value - known) / abs(known) <= 0.001:
                signs.setdefault(tag, set()).add(-1)
            else:
                mismatched.append((tag, end, unit, value, known))

    # A tag whose comparatives disagree about their own sign was not read
    # consistently, so it cannot be trusted for the new year either.
    for tag, seen in signs.items():
        if len(seen) > 1:
            mismatched.append((tag, "sign", "", sorted(seen), "不一致"))
    return compared, mismatched, {tag: seen.pop() for tag, seen in signs.items()
                                  if len(seen) == 1}



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



def latest_annual_filing(cik):
    """The newest 10-K or 20-F in EDGAR, whether or not companyfacts has it."""
    doc = http_json(f"https://data.sec.gov/submissions/CIK{cik}.json")
    recent = doc.get("filings", {}).get("recent", {})
    for i, form in enumerate(recent.get("form", [])):
        if form in ANNUAL_FORMS:
            return {"form": form,
                    "accession": recent["accessionNumber"][i],
                    "filed": recent["filingDate"][i],
                    "report_date": recent["reportDate"][i]}
    return None


def merge_filing_facts(collected, raw_facts, taxonomy, cik, latest, newest_known):
    """Add the missing fiscal year from the filing's own rendered reports.

    Only the period companyfacts lacks is merged; everything it already holds
    stays as it was, so this can never quietly restate an existing figure.
    """
    end = latest["report_date"]
    print(f"    companyfacts 最新為 FY{newest_known}，EDGAR 已有 FY{end} 的 "
          f"{latest['form']}；改由該申報的 XBRL 補齊")
    try:
        facts = filing_facts(cik, latest["accession"])
    except Exception as exc:                    # noqa: BLE001 - report, do not merge
        print(f"    [!] 讀取申報 XBRL 失敗：{type(exc).__name__}: {exc}")
        return {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"}

    # Every candidate, not only the tag companyfacts happened to resolve: TSMC's
    # companyfacts data uses `Revenue` while its FY2025 filing uses
    # `RevenueFromContractsWithCustomers`, and matching on the resolved tag
    # alone silently left revenue -- and therefore the whole fiscal year -- out.
    idx = 1 if taxonomy == "us-gaap" else 2
    candidates = {concept: spec[idx] for concept, spec in CONCEPTS.items()}
    tags_used = {tag for tags in candidates.values() for tag in tags}
    compared, mismatched, signs = agrees_with_companyfacts(
        facts, raw_facts, taxonomy, end, tags_used)
    if mismatched:
        print(f"    [!] 解析結果與 companyfacts 的比較年度不符 {len(mismatched)} 項，"
              f"拒絕合併：{mismatched[:2]}")
        return {"status": "rejected", "compared": compared,
                "mismatched": len(mismatched)}
    if compared < 5:
        print(f"    [!] 只有 {compared} 項可交叉驗證，不足以確認解析正確，拒絕合併")
        return {"status": "rejected", "compared": compared,
                "reason": "可交叉驗證的項目不足"}

    added = []
    for concept, payload in collected.items():
        for tag in candidates.get(concept, []):
            values = facts.get((taxonomy, tag)) or {}
            unit = next((u for u in ("USD", payload["unit"]) if (end, u) in values), None)
            if unit is None:
                continue
            payload["by_fiscal_year_end"][end] = {
                "val": values[(end, unit)] * signs.get(tag, 1), "unit": unit,
                "tag": tag, "form": latest["form"],
                "accn": latest["accession"], "filed": latest["filed"]}
            added.append(concept)
            break

    print(f"    已補齊 FY{end}：{len(added)} 個科目"
          f"（{compared} 項比較年度交叉驗證相符）")
    return {"status": "merged", "fiscal_year_end": end,
            "accession": latest["accession"], "form": latest["form"],
            "concepts_added": sorted(added), "cross_checked": compared,
            "source": "SEC 申報自身的 XBRL 渲染報表（companyfacts 尚未收錄）"}


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

    for payload in collected.values():
        payload["taxonomy"] = taxonomy

    newest_known = max(collected.get("revenue", {}).get("by_fiscal_year_end", {}) or [""])
    fallback_note = None
    latest = latest_annual_filing(cik)
    if latest and latest["report_date"] > newest_known:
        fallback_note = merge_filing_facts(collected, facts, taxonomy, cik,
                                           latest, newest_known)

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
            "filing_fallback": fallback_note, "periods": periods}


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

    previous = None
    if OUTPUT_PATH.exists():
        try:
            previous = json.loads(OUTPUT_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            previous = None

    if previous and args.tickers:
        # An explicit subset means "refresh these", not "these are all there is".
        # Merge so that `--tickers NVDA` updates NVDA and leaves the rest alone.
        merged = dict(previous.get("companies", {}))
        merged.update(companies)
        companies = merged

    if previous:
        # Losing a company to a transient SEC error would delete a filer's whole
        # financial history on the next run, and every derived file would follow.
        # This matters now that a scheduled job runs it unattended: refuse the
        # write rather than persist a partial fetch.
        lost = sorted(set(previous.get("companies", {})) - set(companies))
        if lost:
            raise SystemExit(
                "Refusing to overwrite financials.json: {} present in the existing "
                "file but missing from this fetch ({}). Re-run; if it persists, the "
                "filer or the API has changed and needs looking at."
                .format(", ".join(lost), ", ".join(failed) or "no error reported"))

        # generated_at moves on every run, so writing unconditionally would make
        # the scheduled job commit daily even when no filer has reported since.
        if previous.get("companies") == companies:
            print(f"\nNo new filings; leaving {OUTPUT_PATH.relative_to(REPO_ROOT)} "
                  f"unchanged (fetched {previous.get('generated_at', 'unknown')}).")
            if failed:
                print(f"Missing: {', '.join(failed)}")
            return

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
