#!/usr/bin/env python3
"""Build a stock-oriented 13F radar from the SEC's complete quarterly data sets.

Unlike the legacy manager watch list, this scans every information-table row in
the two newest SEC data sets and then pivots the result around Sec_kb's tracked
stocks.  Since January 3, 2023, SEC VALUE is rounded to the nearest US dollar.
"""

import argparse
import csv
import io
import json
import os
import re
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "sec_13f_stock_radar.json"
DEFAULT_NOTE = ROOT / "60_SEC_Filing_Radar" / "Form13F_Stock_Radar.md"
LANDING = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"

# The SEC information table has issuer and class, but no exchange ticker.  Keep
# the mapping explicit and auditable; class filters prevent GOOG from being
# counted as GOOGL.  Matching is case-insensitive after whitespace cleanup.
SECURITY_MATCHERS = {
    "AAPL": [(r"^APPLE INC", None)],
    "AMZN": [(r"^AMAZON COM INC", None)],
    "ARM": [(r"^ARM HOLDINGS", None)],
    "COHR": [(r"^COHERENT CORP", None)],
    "GOOGL": [(r"^ALPHABET INC", r"CL A")],
    "INTC": [(r"^INTEL CORP", None)],
    "META": [(r"^META PLATFORMS", r"CL A")],
    "MRVL": [(r"^MARVELL TECHNOLOGY", None)],
    "MSFT": [(r"^MICROSOFT CORP", None)],
    "NOK": [(r"^NOKIA", r"SPON|ADR")],
    "NVDA": [(r"^NVIDIA CORP", None)],
    "ONDS": [(r"^ONDAS (?:HLDGS|HOLDINGS|INC)", None)],
    "TSLA": [(r"^TESLA INC", None)],
    "TSM": [(r"^TAIWAN SEMICONDUCTOR", r"SPON|ADR")],
}


def user_agent():
    return os.environ.get("SEC_USER_AGENT", "SecKBResearch user@example.com")


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": user_agent()})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def discover_datasets(count=2):
    html = fetch(LANDING).decode("utf-8", errors="replace")
    links = re.findall(r'href="([^"]+_form13f\.zip)"', html, re.IGNORECASE)
    urls = []
    for link in links:
        url = urllib.parse.urljoin(LANDING, link)
        if url not in urls:
            urls.append(url)
    if len(urls) < count:
        raise RuntimeError("SEC 13F landing page did not expose enough data-set links")
    return urls[:count]


def normalized(value):
    return re.sub(r"\s+", " ", str(value or "").strip().upper())


def ticker_for(row):
    issuer = normalized(row.get("NAMEOFISSUER"))
    title = normalized(row.get("TITLEOFCLASS"))
    for ticker, matchers in SECURITY_MATCHERS.items():
        for issuer_pattern, class_pattern in matchers:
            if re.search(issuer_pattern, issuer) and (
                class_pattern is None or re.search(class_pattern, title)
            ):
                return ticker
    return None


def tsv_rows(archive, name):
    text = io.TextIOWrapper(archive.open(name), encoding="utf-8-sig", errors="replace", newline="")
    yield from csv.DictReader(text, delimiter="\t")


def parse_dataset(data, url):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        submissions = {row["ACCESSION_NUMBER"]: row for row in tsv_rows(archive, "SUBMISSION.tsv")}
        covers = {row["ACCESSION_NUMBER"]: row for row in tsv_rows(archive, "COVERPAGE.tsv")}
        candidates = []
        for row in tsv_rows(archive, "INFOTABLE.tsv"):
            ticker = ticker_for(row)
            if not ticker:
                continue
            accession = row["ACCESSION_NUMBER"]
            submission = submissions.get(accession, {})
            cover = covers.get(accession, {})
            candidates.append({
                "ticker": ticker,
                "accession": accession,
                "filing_date": submission.get("FILING_DATE", ""),
                "period": submission.get("PERIODOFREPORT", cover.get("REPORTCALENDARORQUARTER", "")),
                "manager_cik": submission.get("CIK", ""),
                "manager": cover.get("FILINGMANAGER_NAME", "") or submission.get("CIK", ""),
                "issuer": row.get("NAMEOFISSUER", ""),
                "class": row.get("TITLEOFCLASS", ""),
                "cusip": row.get("CUSIP", ""),
                "shares": int(float(row.get("SSHPRNAMT") or 0)),
                "value_usd": int(float(row.get("VALUE") or 0)),
                "put_call": row.get("PUTCALL", ""),
                "amendment_type": cover.get("AMENDMENTTYPE", ""),
            })

    # A restatement supersedes the manager's earlier filing.  A NEW HOLDINGS
    # amendment supplements it, so keep older rows not repeated in the amendment.
    grouped_accessions = defaultdict(dict)
    for row in candidates:
        key = (row["manager_cik"], row["period"])
        grouped_accessions[key][row["accession"]] = row
    restatement_only = {}
    for key, accession_rows in grouped_accessions.items():
        latest = max(accession_rows.values(), key=lambda r: (r["filing_date"], r["accession"]))
        if normalized(latest["amendment_type"]) == "RESTATEMENT":
            restatement_only[key] = latest["accession"]

    deduped = {}
    for row in candidates:
        key = (row["manager_cik"], row["period"])
        if key in restatement_only and row["accession"] != restatement_only[key]:
            continue
        security_key = (row["ticker"], row["manager_cik"], row["period"], row["cusip"], row["put_call"])
        previous = deduped.get(security_key)
        if previous is None or (row["filing_date"], row["accession"]) > (previous["filing_date"], previous["accession"]):
            deduped[security_key] = row
    return {"url": url, "rows": list(deduped.values())}


def aggregate(datasets):
    all_rows = [row for dataset in datasets for row in dataset["rows"] if not row["put_call"]]
    def period_key(value):
        try:
            return datetime.strptime(value, "%d-%b-%Y")
        except ValueError:
            return datetime.min
    periods = sorted({row["period"] for row in all_rows if row["period"]}, key=period_key, reverse=True)
    period_rows = {period: [row for row in all_rows if row["period"] == period] for period in periods[:2]}
    stocks = {}
    for ticker in SECURITY_MATCHERS:
        snapshots = []
        for period in periods[:2]:
            rows = [row for row in period_rows[period] if row["ticker"] == ticker]
            by_manager = defaultdict(lambda: {"shares": 0, "value_usd": 0, "manager": "", "cik": ""})
            for row in rows:
                holder = by_manager[row["manager_cik"]]
                holder["manager"] = row["manager"]
                holder["cik"] = row["manager_cik"]
                holder["shares"] += row["shares"]
                holder["value_usd"] += row["value_usd"]
            holders = sorted(by_manager.values(), key=lambda h: h["shares"], reverse=True)
            snapshots.append({
                "period": period,
                "manager_count": len(holders),
                "shares": sum(h["shares"] for h in holders),
                "value_usd": sum(h["value_usd"] for h in holders),
                "top_holders": holders[:10],
            })
        current = snapshots[0] if snapshots else None
        previous = snapshots[1] if len(snapshots) > 1 else None
        if current and previous:
            current["shares_change"] = current["shares"] - previous["shares"]
            current["shares_change_pct"] = (
                current["shares_change"] / previous["shares"] * 100 if previous["shares"] else None
            )
            current_names = {h["cik"] for h in current["top_holders"]}
            previous_names = {h["cik"] for h in previous["top_holders"]}
            current["new_top_holders"] = sorted(current_names - previous_names)
            current["exited_top_holders"] = sorted(previous_names - current_names)
        stocks[ticker] = {"snapshots": snapshots}
    return {"periods": periods[:2], "stocks": stocks}


def render_note(result):
    lines = [
        "---", "title: 完整 13F 股票導向持股分析", f"updated_at: {result['updated_at']}",
        "tags:", "  - sec/13f", "  - ownership/institutional", "---", "",
        "# 🏛️ 完整 13F 股票導向持股分析", "",
        "逐列掃描 SEC 最新兩期完整 Form 13F 資料集，不只追蹤少數知名基金。", "",
        "| 公司 | 報告期 | 申報機構數 | 合計股數 | 季變化 | 申報市值 USD |", "|---|---|---:|---:|---:|---:|",
    ]
    for ticker, node in result["stocks"].items():
        snapshots = node["snapshots"]
        if not snapshots:
            lines.append(f"| **{ticker}** | — | 0 | — | — | — |")
            continue
        row = snapshots[0]
        change = row.get("shares_change_pct")
        change_text = "—" if change is None else f"{change:+.1f}%"
        lines.append(
            f"| **{ticker}** | {row['period']} | {row['manager_count']:,} | {row['shares']:,} | "
            f"{change_text} | ${row['value_usd']:,.0f} |"
        )
    lines += ["", "## 各股最新期前五大申報機構", ""]
    for ticker, node in result["stocks"].items():
        snapshots = node["snapshots"]
        holders = snapshots[0].get("top_holders", [])[:5] if snapshots else []
        holder_text = "；".join(
            f"{holder['manager']} {holder['shares']:,} 股" for holder in holders
        ) or "本期未命中"
        lines.append(f"- **{ticker}**：{holder_text}")
    lines += [
        "", "## 數字代表什麼", "",
        "- **申報機構數**：本期 13F 中報告持有該股的不同 manager CIK 數。",
        "- **合計股數**：所有申報機構的 long common-share 股數加總；put/call 不混入股數。",
        "- **季變化**：最新報告期與前一報告期的合計股數差；不是申報日後的即時持股。",
        "- **申報市值**：SEC VALUE 欄位；自 2023-01-03 起為四捨五入到整數美元（更早格式才是千美元）。",
        "- **前大持有人**：依申報股數排序；同一最終受益人若由多個 manager CIK 申報，合計值可能含關係機構／共同投資裁量的重疊。",
        "", "> 13F 通常在季底後 45 天內申報，有明顯時滯；且只包含 13F 證券清單的多頭與選擇權欄位，不是機構的完整投資組合。", "",
        f"> 資料來源：[SEC Form 13F Data Sets]({LANDING})。", "",
    ]
    return "\n".join(lines)


def build(output=DEFAULT_OUTPUT, note=DEFAULT_NOTE):
    urls = discover_datasets(2)
    parsed = [parse_dataset(fetch(url), url) for url in urls]
    result = aggregate(parsed)
    result.update({
        "schema_version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "SEC Form 13F quarterly data sets; complete information-table scan",
        "dataset_urls": urls,
    })
    Path(output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    Path(note).parent.mkdir(parents=True, exist_ok=True)
    Path(note).write_text(render_note(result) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--note", type=Path, default=DEFAULT_NOTE)
    parser.add_argument("--render-existing", action="store_true", help="Render note from existing JSON without downloading data sets")
    args = parser.parse_args()
    if args.render_existing:
        result = json.loads(args.output.read_text())
        args.note.parent.mkdir(parents=True, exist_ok=True)
        args.note.write_text(render_note(result) + "\n")
        print(f"13F 筆記已由現有 JSON 重建：{len(result['stocks'])} 家")
        return
    result = build(args.output, args.note)
    print(f"13F 已更新：{len(result['stocks'])} 家；報告期 {', '.join(result['periods'])}")


if __name__ == "__main__":
    main()
