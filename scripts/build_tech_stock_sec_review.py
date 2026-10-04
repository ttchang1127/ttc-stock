"""Export a bounded public SEC review status from local inventory and review notes.

The input files live outside this public repository. Run manually after reviewing
new claims; the daily price refresh must not change editorial SEC status.
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path


LINK = re.compile(r"\[([^]]+)\]\((https://www\.sec\.gov/Archives/[^)]+)\)")
ACCESSION = re.compile(r"\b\d{10}-\d{2}-\d{6}\b")
ROW = re.compile(r"^\| ([A-Z][A-Z0-9.]*) \|")


def source(label, url, ticker, inventory):
    match = ACCESSION.search(label)
    if not match:
        raise ValueError(f"{ticker}: SEC link has no accession")
    filing = inventory.get((ticker, match.group()))
    if not filing or url not in [filing["url"], *(item["url"] for item in filing["originals"])]:
        raise ValueError(f"{ticker}: SEC link does not match inventory")
    if filing["review_status"] != "not_reviewed":
        raise ValueError(f"{ticker}: unexpected whole-filing review status")
    return {
        "form": filing["form"],
        "accession": filing["accession"],
        "filing_date": filing["filing_date"],
        "report_period": filing["report_date"] if filing["form"] in {"10-Q", "10-K", "20-F"} else None,
        "url": url,
    }


def build(notes_dir, inventory_path):
    raw = json.loads(inventory_path.read_text(encoding="utf-8"))
    filings = raw["filings"]
    inventory = {(item["ticker"], item["accession"]): item for item in filings}
    counts = Counter(item["ticker"] for item in filings)
    if len(inventory) != len(filings) or any(not count for count in counts.values()):
        raise ValueError("duplicate or missing inventory filing")
    if raw["errors"] or any(item["review_status"] != "not_reviewed" for item in filings):
        raise ValueError("inventory errors or review status changed")

    companies = {ticker: {"cached_filings": count, "document_review": "not_reviewed",
                          "representative_review": None} for ticker, count in sorted(counts.items())}
    for batch in range(1, 13):
        note = notes_dir / f"Tech_Stock_Map_SEC_STE-Jev_Review_Batch{batch}_2026-10-04.md"
        for line in note.read_text(encoding="utf-8").splitlines():
            if not ROW.match(line):
                continue
            fields = [part.strip() for part in line.strip("|").split("|")]
            if len(fields) != 6:
                raise ValueError(f"batch {batch}: malformed review row")
            ticker, revenue_claim, revenue_score, _, business_score, citations = fields
            if ticker not in companies or companies[ticker]["representative_review"] is not None:
                raise ValueError(f"{ticker}: missing inventory or duplicate review")
            missing_revenue = ticker in {"CYBR", "SAP"}
            if (revenue_score == "—") != missing_revenue or float(business_score) < 0.85:
                raise ValueError(f"{ticker}: unexpected review result")
            if not missing_revenue and float(revenue_score) < 0.85:
                raise ValueError(f"{ticker}: revenue support below review threshold")
            links = LINK.findall(citations)
            if len(links) != (1 if missing_revenue else 2):
                raise ValueError(f"{ticker}: expected exact SEC source links")
            sources = [source(label, url, ticker, inventory) for label, url in links]
            companies[ticker]["representative_review"] = {
                "revenue": {"status": "source_gap" if missing_revenue else "checked",
                            "claim": None if missing_revenue else revenue_claim,
                            "source": None if missing_revenue else sources[0]},
                "annual_business": {"status": "checked", "source": sources[-1]},
            }

    reviewed = sum(row["representative_review"] is not None for row in companies.values())
    claims = sum((review["revenue"]["status"] == "checked") + 1
                 for row in companies.values() if (review := row["representative_review"]))
    if (len(companies), len(filings), reviewed, claims) != (182, 885, 113, 224):
        raise ValueError("SEC public summary does not match reviewed source totals")
    companies["CBRS"]["coverage_exception"] = "截至查核日，SEC 索引未列可用 10-K；不可推定年報數字。"
    companies["CYBR"]["coverage_exception"] = "缺本輪可用的 SEC 季度收入來源；年報來源較舊。"
    companies["SAP"]["coverage_exception"] = "已取得的 6-K 無本輪可用季度營收表。"
    return {
        "schema_version": 1, "reviewed_at": raw["latest_run_as_of"],
        "scope": {"companies_cached": len(companies), "filings_cached": len(filings),
                  "representative_companies": reviewed, "representative_claims": claims,
                  "whole_filings_reviewed": 0},
        "limits": "代表性主張檢核非逐份申報分類；總營收與業務位置不等於 AI 專屬營收或投資評級。",
        "companies": companies,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notes-dir", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("tech_stock_sec_review.json"))
    args = parser.parse_args()
    result = build(args.notes_dir, args.inventory)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
