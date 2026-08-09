#!/usr/bin/env python3
"""Report annual SEC filings that have not entered 20_Filings yet.

This is deliberately read-only. It does not download a filing, split sections,
or update any JSON. The scheduled workflow uses it as an early-warning signal
so a new 10-K or 20-F is visible in the run summary while the decision to ingest
and review the filing remains with a person.

    python3 scripts/check_new_annual_filings.py
    python3 scripts/check_new_annual_filings.py --tickers NVDA TSM
"""

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from fetch_xbrl_financials import DEFAULT_TICKERS, SEC_HEADERS

REPO_ROOT = Path(__file__).resolve().parent.parent
ANNUAL_FORMS = {"10-K", "20-F"}
ACCESSION_RE = re.compile(r'^accession_number:\s*["\']?([^"\'\s]+)', re.MULTILINE)


def local_accessions(ticker):
    """Return annual-report accessions already represented by vault notes."""
    out = set()
    filings_dir = REPO_ROOT / "20_Filings" / ticker
    for path in filings_dir.glob(f"{ticker}_*.md"):
        match = ACCESSION_RE.search(path.read_text(errors="replace"))
        if match:
            out.add(match.group(1))
    return out


def company_ciks():
    data = json.loads((REPO_ROOT / "financials.json").read_text())["companies"]
    return {ticker: str(node["cik"]).zfill(10) for ticker, node in data.items()}


def latest_annual_filing(cik):
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    req = urllib.request.Request(url, headers=SEC_HEADERS)
    with urllib.request.urlopen(req, timeout=30) as response:
        recent = json.loads(response.read().decode("utf-8"))["filings"]["recent"]
    for form, accession, filed, report, document in zip(
            recent["form"], recent["accessionNumber"], recent["filingDate"],
            recent["reportDate"], recent["primaryDocument"]):
        if form in ANNUAL_FORMS:
            clean = accession.replace("-", "")
            filing_url = (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{clean}/{document}")
            return {
                "form": form,
                "accession": accession,
                "filed": filed,
                "report_date": report,
                "url": filing_url,
            }
    return None


def github_warning(title, message):
    if os.environ.get("GITHUB_ACTIONS"):
        safe_title = title.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        safe_message = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::warning title={safe_title}::{safe_message}")


def write_summary(rows, errors):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = ["## SEC 年報偵測", ""]
    if rows:
        lines += [
            "發現尚未進入 20_Filings/ 的年度申報：",
            "",
            "| 代號 | 表格 | 申報日 | 報告期 | Accession |",
            "|---|---|---|---|---|",
        ]
        for ticker, filing in rows:
            lines.append(
                f"| {ticker} | {filing['form']} | {filing['filed']} | "
                f"{filing['report_date']} | [{filing['accession']}]({filing['url']}) |")
    else:
        lines.append("✅ 沒有發現尚未進入知識庫的新 10-K／20-F。")
    if errors:
        lines += ["", "### 查詢警告", ""]
        lines += [f"- {ticker}: {message}" for ticker, message in errors]
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    args = parser.parse_args()

    ciks = company_ciks()
    new_filings = []
    errors = []

    for index, raw_ticker in enumerate(args.tickers):
        ticker = raw_ticker.upper()
        cik = ciks.get(ticker)
        if not cik:
            errors.append((ticker, "financials.json 沒有 CIK"))
            github_warning(f"{ticker} 年報偵測失敗", "financials.json 沒有 CIK")
            continue
        try:
            filing = latest_annual_filing(cik)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as exc:
            message = f"{type(exc).__name__}: {exc}"
            errors.append((ticker, message))
            github_warning(f"{ticker} 年報偵測失敗", message)
            continue
        if not filing:
            message = "SEC submissions 沒有 10-K／20-F"
            errors.append((ticker, message))
            github_warning(f"{ticker} 年報偵測失敗", message)
        elif filing["accession"] not in local_accessions(ticker):
            new_filings.append((ticker, filing))
            message = (
                f"{filing['form']} filed {filing['filed']} "
                f"({filing['accession']}) 尚未進入 20_Filings/{ticker}")
            github_warning(f"{ticker} 有新年度申報", message)
            print(f"  ⚠️ {ticker:6s} {message}")
        else:
            print(
                f"  ✅ {ticker:6s} 最新 {filing['form']} {filing['accession']} 已在知識庫")
        if index + 1 < len(args.tickers):
            time.sleep(0.12)

    write_summary(new_filings, errors)
    print()
    print(f"新申報：{len(new_filings)}；查詢警告：{len(errors)}；"
          f"已檢查：{len(args.tickers)}")
    # A notification must not block the independent market-data refresh.
    # Network/query failures are surfaced as warnings and in the job summary.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
