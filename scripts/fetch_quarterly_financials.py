#!/usr/bin/env python3
"""Build comparable single-quarter trends from official SEC Company Facts.

US issuers file only three 10-Qs.  The fourth quarter is therefore derived,
metric by metric, as the 10-K full year minus the 10-Q nine-month cumulative
amount.  Weighted-average shares and diluted EPS are never derived this way;
those values are left null when the filer did not tag a standalone Q4 value.

Foreign private issuers generally furnish results on 6-K. Arm's filings carry
a consistent quarterly Company Facts series. Nokia and TSMC do not, so their
official IR quarterly reports are maintained in a separate, auditable source
file using each issuer's reporting currency and statutory reported basis.
"""

import argparse
import json
import os
import time
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
FINANCIALS_PATH = REPO_ROOT / "financials.json"
OUTPUT_PATH = REPO_ROOT / "quarterly_financials.json"
FOREIGN_QUARTERLY_PATH = REPO_ROOT / "foreign_quarterly_financials.json"
FOREIGN_IR_TICKERS = {"NOK", "TSM"}
FORMS = {"10-Q", "10-Q/A", "10-K", "10-K/A", "6-K", "6-K/A", "20-F", "20-F/A"}
OFFICIAL_RESULTS_URLS = {
    "ARM": "https://investors.arm.com/financials/quarterly-annual-results",
    "NOK": "https://www.nokia.com/about-us/investors/results-reports/",
    "TSM": "https://investor.tsmc.com/english/financial-reports",
}

CONCEPTS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "gross_profit": ["GrossProfit"],
    "cogs": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "diluted_eps": ["EarningsPerShareDiluted"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "diluted_shares": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
}

UNITS = {
    "diluted_eps": ("USD/shares", "USD / shares"),
    "diluted_shares": ("shares",),
}


def days_between(start, end):
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def sec_json(url):
    user_agent = os.environ.get("SEC_USER_AGENT", "Sec_kb Research gibon1127@gmail.com")
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)


def filing_url(cik, accession):
    if not accession:
        return None
    return (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
        f"{accession.replace('-', '')}/{accession}-index.html"
    )


def fact_rows(document, metric):
    facts = document.get("facts", {}).get("us-gaap", {})
    rows = []
    for priority, tag in enumerate(CONCEPTS[metric]):
        fact = facts.get(tag)
        if not fact:
            continue
        units = fact.get("units", {})
        allowed = UNITS.get(metric, ("USD",))
        for unit in allowed:
            for raw in units.get(unit, []):
                if raw.get("form") not in FORMS or not raw.get("start") or not raw.get("end"):
                    continue
                try:
                    span = days_between(raw["start"], raw["end"])
                except ValueError:
                    continue
                row = dict(raw)
                row.update({"tag": tag, "unit": unit, "span": span, "priority": priority})
                rows.append(row)
    return rows


def choose_by_end(rows, minimum, maximum):
    """Pick the best consolidated fact for each period end."""
    chosen = {}
    for row in rows:
        if not minimum <= row["span"] <= maximum:
            continue
        previous = chosen.get(row["end"])
        # Prefer the newest filing/restatement, then a framed (normally
        # consolidated, non-dimensional) fact, then the declared tag priority.
        score = (row.get("filed", ""), bool(row.get("frame")), -row["priority"])
        old_score = (
            previous.get("filed", ""), bool(previous.get("frame")), -previous["priority"]
        ) if previous else None
        if previous is None or score > old_score:
            chosen[row["end"]] = row
    return chosen


def q4_values(rows, allow_derivation=True):
    if not allow_derivation:
        return {}
    annuals = choose_by_end(
        (row for row in rows if row["form"].startswith(("10-K", "20-F"))), 300, 400
    )
    cumulative = list(choose_by_end(rows, 220, 310).values())
    result = {}
    for end, annual in annuals.items():
        prior = [row for row in cumulative if row["start"] == annual["start"] and row["end"] < end]
        if not prior:
            continue
        nine_month = max(prior, key=lambda row: row["end"])
        result[end] = {
            **annual,
            "val": annual["val"] - nine_month["val"],
            "derived": True,
            "derivation": "年度報告全年值減同一會計年度前三季累計值",
        }
    return result


def single_quarter_flow(rows):
    """Turn Q1/6M/9M/FY cumulative cash-flow facts into single quarters."""
    direct = choose_by_end(rows, 60, 120)
    cumulative = {}
    for row in rows:
        if not 60 <= row["span"] <= 400:
            continue
        if row["span"] > 300 and not row["form"].startswith(("10-K", "20-F")):
            # Some 10-Q cash-flow tags include a trailing-twelve-month fact.
            # It is not a fiscal-year cumulative amount and must not be
            # subtracted from a three-month fact sharing the same start date.
            continue
        key = (row["start"], row["end"])
        previous = cumulative.get(key)
        score = (row.get("filed", ""), bool(row.get("frame")), -row["priority"])
        old_score = (
            previous.get("filed", ""), bool(previous.get("frame")), -previous["priority"]
        ) if previous else None
        if previous is None or score > old_score:
            cumulative[key] = row

    derived_result = {}
    by_start = {}
    for row in cumulative.values():
        by_start.setdefault(row["start"], []).append(row)
    for sequence in by_start.values():
        sequence.sort(key=lambda row: row["end"])
        previous = None
        for row in sequence:
            # SEC can carry unusual stub periods; only standard quarter/YTD
            # spans enter the public trend table.
            if row["span"] > 120 and previous is None:
                continue
            value = row["val"] if previous is None else row["val"] - previous["val"]
            derived = previous is not None
            candidate = {
                **row,
                "val": value,
                "derived": derived,
                "derivation": "本期累計值減前一期累計值" if derived else None,
            }
            existing = derived_result.get(row["end"])
            if existing is None or row.get("filed", "") > existing.get("filed", ""):
                derived_result[row["end"]] = candidate
            previous = row
    # A filer-provided standalone quarter is more direct than subtraction.
    # Use the cumulative derivation only where no 3-month fact exists.
    for end, row in derived_result.items():
        direct.setdefault(end, row)
    return direct


def metric_series(document, metric):
    rows = fact_rows(document, metric)
    if metric in {"operating_cash_flow", "capex"}:
        return single_quarter_flow(rows)
    direct = choose_by_end(rows, 60, 120)
    # Per-share figures and weighted average shares cannot be obtained by
    # subtracting annual from nine-month values.
    derived = q4_values(rows, allow_derivation=metric not in {"diluted_eps", "diluted_shares"})
    for end, row in derived.items():
        direct.setdefault(end, row)
    return direct


def fact_value(row):
    if row is None:
        return None
    return {
        "value": row["val"],
        "unit": row["unit"],
        "tag": row["tag"],
        "derived": bool(row.get("derived")),
        "derivation": row.get("derivation"),
    }


def build_company(ticker, cik, document):
    series = {metric: metric_series(document, metric) for metric in CONCEPTS}
    period_ends = sorted(series["revenue"], reverse=True)[:12]
    periods = []
    for end in period_ends:
        revenue_row = series["revenue"][end]
        values = {metric: fact_value(rows.get(end)) for metric, rows in series.items()}
        if values["gross_profit"] is None and values["revenue"] and values["cogs"]:
            values["gross_profit"] = {
                "value": values["revenue"]["value"] - values["cogs"]["value"],
                "unit": values["revenue"]["unit"],
                "tag": "Revenue minus CostOfRevenue",
                "derived": True,
                "derivation": "營收減營業成本",
            }
        revenue = values["revenue"]["value"] if values["revenue"] else None
        gross = values["gross_profit"]["value"] if values["gross_profit"] else None
        operating = values["operating_income"]["value"] if values["operating_income"] else None
        ocf = values["operating_cash_flow"]["value"] if values["operating_cash_flow"] else None
        capex = values["capex"]["value"] if values["capex"] else None
        quality_notes = []
        net_income = values["net_income"]["value"] if values["net_income"] else None
        eps = values["diluted_eps"]["value"] if values["diluted_eps"] else None
        if net_income not in {None, 0} and eps not in {None, 0} and (net_income > 0) != (eps > 0):
            values["diluted_eps"] = None
            quality_notes.append("稀釋 EPS 與淨利方向矛盾，疑為申報標籤問題，已保留缺值。")
        values["gross_margin"] = gross / revenue if revenue not in {None, 0} and gross is not None else None
        values["operating_margin"] = operating / revenue if revenue not in {None, 0} and operating is not None else None
        values["free_cash_flow"] = ocf - capex if ocf is not None and capex is not None else None
        periods.append({
            "period_end": end,
            "filing_date": revenue_row.get("filed"),
            "form": revenue_row.get("form"),
            "accession": revenue_row.get("accn"),
            "url": filing_url(cik, revenue_row.get("accn")),
            "q4_derived": bool(revenue_row.get("derived")),
            "quality_notes": quality_notes,
            "values": values,
        })
    share_values = [
        period["values"]["diluted_shares"]["value"]
        for period in periods[:8] if period["values"].get("diluted_shares")
    ]
    if share_values:
        ordered = sorted(share_values)
        median = ordered[len(ordered) // 2]
        for period in periods:
            shares = period["values"].get("diluted_shares")
            if shares and median and not 0.05 <= shares["value"] / median <= 20:
                period["values"]["diluted_shares"] = None
                period["quality_notes"].append(
                    "稀釋加權平均股數與相鄰季度差距超過 20 倍，疑為 XBRL 縮放問題，已保留缺值。"
                )
    return {
        "status": "available" if len(periods) >= 4 else "limited",
        "reason": None if len(periods) >= 4 else "SEC Company Facts 可比單季資料少於 4 期",
        "currency": "USD",
        "source_basis": "SEC Company Facts；金額為 USD。",
        "official_results_url": OFFICIAL_RESULTS_URLS.get(ticker),
        "periods": periods,
    }


def load_foreign_quarterly():
    """Load and validate official-IR facts that SEC Company Facts cannot supply."""
    source = json.loads(FOREIGN_QUARTERLY_PATH.read_text())
    companies = source.get("companies", {})
    missing = sorted(FOREIGN_IR_TICKERS - set(companies))
    if missing:
        raise SystemExit(f"Foreign quarterly source missing: {', '.join(missing)}")
    for ticker in sorted(FOREIGN_IR_TICKERS):
        company = companies[ticker]
        periods = company.get("periods", [])
        if len(periods) < 8:
            raise SystemExit(f"{ticker} foreign source needs 8 periods for four-quarter YoY")
        if company.get("currency") not in {"EUR", "TWD"}:
            raise SystemExit(f"{ticker} foreign source has invalid reporting currency")
        if periods != sorted(periods, key=lambda row: row["period_end"], reverse=True):
            raise SystemExit(f"{ticker} foreign periods are not newest-first")
        for period in periods:
            values = period.get("values", {})
            required = {"revenue", "gross_margin", "operating_margin", "diluted_eps",
                        "operating_cash_flow", "free_cash_flow"}
            absent = sorted(required - set(values))
            if absent:
                raise SystemExit(
                    f"{ticker} {period.get('period_end')} missing metrics: {', '.join(absent)}"
                )
            url = period.get("url", "")
            allowed_host = "nokia.com" if ticker == "NOK" else "investor.tsmc.com"
            if allowed_host not in url:
                raise SystemExit(f"{ticker} {period.get('period_end')} has non-official URL")
    return companies


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", nargs="*", help="只更新指定代號，其他公司保留")
    args = parser.parse_args()
    annual = json.loads(FINANCIALS_PATH.read_text())
    foreign_quarterly = load_foreign_quarterly()
    previous = json.loads(OUTPUT_PATH.read_text()) if OUTPUT_PATH.exists() else None
    requested = set(args.tickers or annual["companies"])
    companies = dict(previous.get("companies", {})) if previous and args.tickers else {}

    for ticker, company in sorted(annual["companies"].items()):
        if ticker not in requested:
            continue
        if ticker in FOREIGN_IR_TICKERS:
            companies[ticker] = foreign_quarterly[ticker]
            print(f"  {ticker:6s} {len(companies[ticker]['periods'])} official IR quarters")
            continue
        cik = str(company["cik"]).zfill(10)
        document = sec_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
        companies[ticker] = build_company(ticker, cik, document)
        print(f"  {ticker:6s} {len(companies[ticker]['periods'])} comparable quarters")
        time.sleep(0.12)

    missing = sorted(set(annual["companies"]) - set(companies))
    if missing:
        raise SystemExit(f"Refusing partial quarterly output; missing: {', '.join(missing)}")
    comparable = [ticker for ticker, row in companies.items() if len(row.get("periods", [])) >= 4]
    if len(comparable) < 8:
        raise SystemExit(f"Refusing suspicious quarterly output; only {len(comparable)} companies have four periods")

    stable = {
        "source": "SEC XBRL Company Facts API；Nokia 與 TSMC 官方 IR 季報",
        "methodology": {
            "q4": "10-K／20-F 全年流量減同一會計年度前三季累計；EPS 與加權平均稀釋股數不相減。",
            "foreign_issuers": "6-K／20-F 無一致 SEC 單季 Company Facts 時，採公司官方 IR 的 IFRS／TIFRS reported 數字並保留原幣；不做匯率換算。",
        },
        "companies": companies,
    }
    if previous and {k: previous.get(k) for k in stable} == stable:
        print("No quarterly facts changed; leaving quarterly_financials.json unchanged.")
        return
    stable["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    OUTPUT_PATH.write_text(json.dumps(stable, ensure_ascii=False, indent=1) + "\n")
    print(f"Wrote {OUTPUT_PATH.name}: {len(comparable)} companies with at least four periods")


if __name__ == "__main__":
    main()
