"""ETF holdings from SEC Form N-PORT, for look-through exposure.

Vanguard ETFs (VGT, VOO) are share classes of mutual-fund series, so their
complete holdings reach the public through N-PORT: quarterly, about 60 days
after the period ends.  Every holdings file therefore carries its report
date and accession number; the page must show how old it is.

Steps:
1. ``company_tickers_mf.json`` maps the fund ticker to its trust CIK and
   series id;
2. the trust's recent NPORT-P filings are read newest first until one
   reports that series (a trust files one N-PORT per series);
3. each holding is mapped to a ticker: N-PORT's optional ``identifiers/
   ticker`` (``"AAPL US"`` style), else an exact normalised name match
   against the rotation universe; anything else stays unmapped and is
   reported as such, never guessed.

Parsing ignores XML namespaces so a schema-version bump does not silently
drop holdings.  Standard library only (SEC access through sec_http).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

import sec_http

TICKERS_URL = "https://www.sec.gov/files/company_tickers_mf.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
DOCUMENT_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/primary_doc.xml"
MAX_FILINGS_SCANNED = 80
MIN_HOLDINGS = 50
WEIGHT_RANGE = (90.0, 102.0)  # percent of net assets held in the listed positions
NAME_NOISE = re.compile(r"\b(inc|incorporated|corp|corporation|co|company|ltd|plc|holdings?|group|class [a-z]|"
                        r"the|n\.?v|s\.?a|ag|se|/the)\b")


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def child(node: ET.Element, name: str) -> ET.Element | None:
    return next((item for item in node if local(item.tag) == name), None)


def text(node: ET.Element | None, name: str) -> str | None:
    found = child(node, name) if node is not None else None
    return found.text.strip() if found is not None and found.text else None


def number(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "", "N/A") else None
    except ValueError:
        return None


def find_series(fund_index: dict, ticker: str) -> dict:
    """{cik, series_id, class_id} for a fund ticker from company_tickers_mf.json."""
    fields = fund_index["fields"]
    for row in fund_index["data"]:
        record = dict(zip(fields, row))
        if str(record.get("symbol", "")).upper() == ticker.upper():
            return {"cik": int(record["cik"]), "series_id": record["seriesId"], "class_id": record["classId"]}
    raise KeyError(f"{ticker} not found in company_tickers_mf.json")


def nport_filings(submissions: dict) -> list[dict]:
    """Recent NPORT-P filings of a trust, newest first."""
    recent = submissions["filings"]["recent"]
    rows = [{"accession": acc, "filed": filed, "report_date": report}
            for form, acc, filed, report in zip(recent["form"], recent["accessionNumber"], recent["filingDate"],
                                               recent.get("reportDate", [""] * len(recent["form"])))
            if form == "NPORT-P"]
    return sorted(rows, key=lambda row: row["filed"], reverse=True)


def series_of(document: ET.Element) -> str | None:
    for node in document.iter():
        if local(node.tag) == "seriesId" and node.text:
            return node.text.strip()
    return None


def normalise_name(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9 ]", " ", name.lower().replace("&", " and "))
    return re.sub(r"\s+", " ", NAME_NOISE.sub(" ", cleaned)).strip()


def ticker_from_identifier(value: str | None) -> str | None:
    """'AAPL US' -> 'AAPL'; 'BRK/B US' -> 'BRK.B'; exchange suffix dropped."""
    if not value or value.strip().upper() in ("N/A", "NA", "NONE", "-", "0"):
        return None
    symbol = value.strip().split()[0].upper().replace("/", ".")
    return symbol if re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", symbol) else None


def parse_nport(xml_text: str, universe: dict) -> dict:
    root = ET.fromstring(xml_text)
    gen = next((node for node in root.iter() if local(node.tag) == "genInfo"), None)
    fund = next((node for node in root.iter() if local(node.tag) == "fundInfo"), None)
    by_name = {}
    known = {row["ticker"] for row in universe["members"]}
    for row in universe["members"]:
        by_name.setdefault(normalise_name(row["name"]), row["ticker"])
    holdings = []
    for item in root.iter():
        if local(item.tag) != "invstOrSec":
            continue
        name = text(item, "name") or text(item, "title") or ""
        identifiers = child(item, "identifiers")
        isin = ticker_raw = None
        if identifiers is not None:
            for node in identifiers:
                if local(node.tag) == "isin":
                    isin = node.get("value")
                elif local(node.tag) == "ticker":
                    ticker_raw = node.get("value")
        ticker = ticker_from_identifier(ticker_raw)
        method = "nport_ticker" if ticker else None
        if ticker is None:
            ticker = by_name.get(normalise_name(name))
            method = "name_match" if ticker else None
        holdings.append({
            "ticker": ticker,
            "mapping": method,
            "in_universe": ticker in known if ticker else False,
            "name": name,
            "cusip": text(item, "cusip"),
            "isin": isin,
            "weight_pct": number(text(item, "pctVal")),
            "value_usd": number(text(item, "valUSD")),
            "asset_category": text(item, "assetCat"),
        })
    holdings.sort(key=lambda row: -(row["weight_pct"] or 0))
    return {
        "fund_name": text(gen, "seriesName"),
        "registrant": text(gen, "regName"),
        "series_id": series_of(root),
        "report_date": text(gen, "repPdDate"),
        "period_end": text(gen, "repPdEnd"),
        "net_assets_usd": number(text(fund, "netAssets")),
        "holdings": holdings,
    }


def validate(parsed: dict, series_id: str) -> list[str]:
    problems = []
    if parsed["series_id"] != series_id:
        problems.append(f"series {parsed['series_id']} is not {series_id}")
    if len(parsed["holdings"]) < MIN_HOLDINGS:
        problems.append(f"only {len(parsed['holdings'])} holdings")
    total = sum(row["weight_pct"] or 0 for row in parsed["holdings"])
    if not WEIGHT_RANGE[0] <= total <= WEIGHT_RANGE[1]:
        problems.append(f"holdings weights sum to {total:.1f}% of net assets")
    if not parsed["report_date"]:
        problems.append("missing report date")
    return problems


def summarise(parsed: dict) -> dict:
    weights = [row["weight_pct"] or 0 for row in parsed["holdings"]]
    mapped = sum(row["weight_pct"] or 0 for row in parsed["holdings"] if row["ticker"])
    top10 = sum(sorted(weights, reverse=True)[:10])
    shares = [w / 100 for w in weights if w > 0]
    hhi = sum(w * w for w in shares)
    return {
        "holdings_count": len(parsed["holdings"]),
        "weight_total_pct": round(sum(weights), 2),
        "mapped_weight_pct": round(mapped, 2),
        "unmapped_weight_pct": round(sum(weights) - mapped, 2),
        "top10_weight_pct": round(top10, 2),
        "effective_holdings": round(1 / hhi, 1) if hhi else None,
    }


def fetch_latest(ticker: str, universe: dict, fund_index: dict, known_accession: str | None = None) -> dict | None:
    """Newest validated N-PORT holdings for ``ticker``; None when ``known_accession`` is still the newest."""
    ids = find_series(fund_index, ticker)
    submissions = sec_http.get_json(SUBMISSIONS_URL.format(cik=ids["cik"]))
    for filing in nport_filings(submissions)[:MAX_FILINGS_SCANNED]:
        if filing["accession"] == known_accession:
            return None
        url = DOCUMENT_URL.format(cik=ids["cik"], accession=filing["accession"].replace("-", ""))
        document = sec_http.get_text(url, accept="application/xml,text/xml,*/*")
        if series_of(ET.fromstring(document)) != ids["series_id"]:
            continue
        parsed = parse_nport(document, universe)
        problems = validate(parsed, ids["series_id"])
        if problems:
            raise ValueError(f"{ticker} N-PORT {filing['accession']}: " + "; ".join(problems))
        return {
            "schema_version": 1,
            "etf": ticker,
            "source": "SEC Form N-PORT (NPORT-P)",
            "cik": ids["cik"],
            "series_id": ids["series_id"],
            "accession": filing["accession"],
            "filed": filing["filed"],
            "source_url": url,
            **{key: parsed[key] for key in ("fund_name", "registrant", "report_date", "period_end",
                                           "net_assets_usd")},
            "summary": summarise(parsed),
            "holdings": parsed["holdings"],
        }
    raise LookupError(f"no NPORT-P for {ticker} ({ids['series_id']}) in the last {MAX_FILINGS_SCANNED} filings")


def look_through(fund_value: float, holdings: dict[str, Any]) -> dict[str, float]:
    """Dollar exposure per ticker through one fund; unmapped weight under '__unmapped__'."""
    result: dict[str, float] = {}
    for row in holdings["holdings"]:
        weight = (row["weight_pct"] or 0) / 100
        key = row["ticker"] or "__unmapped__"
        result[key] = result.get(key, 0.0) + fund_value * weight
    return result
