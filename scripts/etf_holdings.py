"""ETF holdings from SEC Form N-PORT, for look-through exposure.

Vanguard ETFs (VGT, VOO) are share classes of mutual-fund series, so their
complete holdings reach the public through N-PORT: quarterly, about 60 days
after the period ends.  Every holdings file therefore carries its report
date and accession number; the page must show how old it is.

Steps:
1. ``company_tickers_mf.json`` maps the fund ticker to its trust CIK and
   series id;
2. EDGAR's filing list for that series id gives its NPORT-P filings.  If
   that list cannot be read, the trust's recent NPORT-P filings are scanned
   newest first through their small index headers until one names the
   series (a trust such as iShares files hundreds of N-PORTs, one per
   series, so scanning primary documents would not reach far enough);
3. each holding is mapped to a ticker: N-PORT's optional ``identifiers/
   ticker`` when it names a US listing, else an exact normalised name match
   against the rotation universe, else against SEC's own company list
   (``company_tickers.json``, whose conformed names follow the same style
   as N-PORT's).  Anything else stays unmapped and is reported as such,
   never guessed: a foreign listing's local code (``"CCO CN"``) is not
   read as a US ticker, which would name a different company.

Each filing also reports the fund's monthly sales, reinvestments and
redemptions for the three months of the period (N-PORT item B.6): real
creations and redemptions in dollars, not an estimate.  For the research
ETFs every past filing EDGAR lists is kept in a compact append-only history
(``etf_holdings/history/``: point-in-time weights and monthly flows), so a
back-test can use only what was public on each date.

Research funds (``THEME_ETFS``) are a frozen list: a new candidate needs a
new ``THEME_ETF_VERSION`` so earlier results stay comparable.

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
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SERIES_FEED_URL = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={series_id}"
                   "&type=NPORT-P&dateb=&owner=include&count=100&output=atom")
DOCUMENT_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/primary_doc.xml"
HEADER_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{dashed}-index-headers.html"
MAX_FILINGS_SCANNED = 400
MAPPING_VERSION = 3  # bump when mapping or parsed fields change so unchanged filings are re-read (3: flows)
MIN_HOLDINGS = 15
# All positions, % of net assets.  Reinvested securities-lending collateral is
# reported as a holding: TAN reached 134% in 2024-25, so only a gross error is
# caught here; the common-stock range below is the real check.
WEIGHT_RANGE = (90.0, 175.0)
EQUITY_WEIGHT_RANGE = (80.0, 102.0)  # common stock positions, % of net assets
EQUITY_CATEGORIES = {"EC"}
FLOW_FIELDS = ("sales", "reinvestment", "redemption")
HISTORY_SCHEMA_VERSION = 1
VALIDATION_VERSION = 2  # bump when validate() loosens, so filings skipped under older rules are retried
US_EXCHANGE_CODES = {"US", "UN", "UW", "UQ", "UA", "UP", "UR", "UV", "UF"}
NAME_NOISE = re.compile(r"\b(inc|incorporated|corp|corporation|co|cos|company|companies|ltd|plc|holdings?|group|"
                        r"class [a-z]|the|n\.?v|s\.?a|ag|se)\b")
NAME_SUFFIX = re.compile(r"\s*[/\\][a-z ]{1,5}[/\\]?\s*$")  # "Corp/DE", "Inc /MD/", "Corp /NEW", "Cos Inc/The"

THEME_ETF_VERSION = "theme-etf-1"
THEME_ETFS = {  # frozen research candidates: ticker -> theme label
    "SMH": "半導體", "SOXX": "半導體", "IGV": "軟體", "XBI": "生技",
    "KRE": "區域銀行", "XHB": "房屋建商", "ITA": "航太國防", "TAN": "太陽能",
    "URA": "鈾與核能", "XOP": "油氣開採", "XRT": "零售", "IYT": "運輸",
}


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


def series_feed(xml_text: str) -> list[dict]:
    """NPORT-P filings from EDGAR's Atom filing list for one series, newest first."""
    rows = []
    for entry in ET.fromstring(xml_text).iter():
        if local(entry.tag) != "entry":
            continue
        fields = {local(node.tag): (node.text or "").strip() for node in entry.iter()}
        terms = {node.get("term") for node in entry.iter() if local(node.tag) == "category"}
        if fields.get("filing-type", "") != "NPORT-P" and not (terms & {"NPORT-P"}):
            continue
        if fields.get("accession-number"):
            rows.append({"accession": fields["accession-number"], "filed": fields.get("filing-date", ""),
                         "report_date": fields.get("period-of-report", "")})
    return sorted(rows, key=lambda row: row["filed"], reverse=True)


def series_of(document: ET.Element) -> str | None:
    for node in document.iter():
        if local(node.tag) == "seriesId" and node.text:
            return node.text.strip()
    return None


def series_in_header(header_text: str) -> set[str]:
    """Series ids named in a filing's index headers (``<SERIES-ID>``) or in an N-PORT body."""
    return set(re.findall(r"<(?:SERIES-ID|(?:\w+:)?seriesId)>\s*(S\d+)", header_text))


def normalise_name(name: str) -> str:
    lowered = NAME_SUFFIX.sub("", name.lower().strip())
    cleaned = re.sub(r"[^a-z0-9 ]", " ", lowered.replace("&", " and "))
    return re.sub(r"\s+", " ", NAME_NOISE.sub(" ", cleaned)).strip()


def sec_name_index(company_tickers: dict) -> dict[str, str]:
    """Normalised SEC conformed name -> ticker; the first (largest) listing wins for share classes."""
    index: dict[str, str] = {}
    rows = company_tickers.values() if isinstance(company_tickers, dict) else company_tickers
    for row in rows:
        ticker = str(row.get("ticker", "")).upper().replace("-", ".")
        name = normalise_name(str(row.get("title", "")))
        if ticker and name:
            index.setdefault(name, ticker)
    return index


def ticker_from_identifier(value: str | None) -> str | None:
    """'AAPL US' -> 'AAPL'; 'BRK/B US' -> 'BRK.B'; a foreign listing ('CCO CN') -> None."""
    if not value or value.strip().upper() in ("N/A", "NA", "NONE", "-", "0"):
        return None
    parts = value.strip().upper().split()
    if len(parts) > 1 and parts[1] not in US_EXCHANGE_CODES:
        return None
    symbol = parts[0].replace("/", ".")
    return symbol if re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", symbol) else None


def shift_month(period: str, months: int) -> str:
    year, month = map(int, period[:7].split("-"))
    index = year * 12 + month - 1 - months
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def monthly_flows(fund: ET.Element | None, report_date: str | None) -> list[dict]:
    """Item B.6: sales, reinvestment and redemptions for months 1-3 (month 3 ends on the report date)."""
    if fund is None or not report_date:
        return []
    rows = []
    for index in (1, 2, 3):
        node = next((item for item in fund.iter() if local(item.tag) == f"mon{index}Flow"), None)
        if node is None:
            continue
        values = {field: number(node.get(field) or text(node, field)) for field in FLOW_FIELDS}
        net = None
        if values["sales"] is not None and values["redemption"] is not None:
            net = values["sales"] + (values["reinvestment"] or 0) - values["redemption"]
        rows.append({"month": shift_month(report_date, 3 - index), "sales_usd": values["sales"],
                     "reinvestment_usd": values["reinvestment"], "redemptions_usd": values["redemption"],
                     "net_usd": net})
    return rows


def parse_nport(xml_text: str, universe: dict, sec_names: dict[str, str] | None = None) -> dict:
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
        if ticker is None and sec_names:
            ticker = sec_names.get(normalise_name(name))
            method = "sec_name" if ticker else None
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
        "monthly_flows": monthly_flows(fund, text(gen, "repPdDate")),
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
    equity = sum(row["weight_pct"] or 0 for row in parsed["holdings"] if row["asset_category"] in EQUITY_CATEGORIES)
    if not EQUITY_WEIGHT_RANGE[0] <= equity <= EQUITY_WEIGHT_RANGE[1]:
        problems.append(f"common stock weighs {equity:.1f}% of net assets")
    if not parsed["report_date"]:
        problems.append("missing report date")
    return problems


def summarise(parsed: dict) -> dict:
    weights = [row["weight_pct"] or 0 for row in parsed["holdings"]]
    mapped = sum(row["weight_pct"] or 0 for row in parsed["holdings"] if row["ticker"])
    top10 = sum(sorted(weights, reverse=True)[:10])
    shares = [w / 100 for w in weights if w > 0]
    hhi = sum(w * w for w in shares)
    equity = [row for row in parsed["holdings"] if row["asset_category"] in EQUITY_CATEGORIES]
    by_method: dict[str, float] = {}
    for row in parsed["holdings"]:
        if row["mapping"]:
            by_method[row["mapping"]] = round(by_method.get(row["mapping"], 0) + (row["weight_pct"] or 0), 2)
    return {
        "holdings_count": len(parsed["holdings"]),
        "weight_total_pct": round(sum(weights), 2),
        "equity_weight_pct": round(sum(row["weight_pct"] or 0 for row in equity), 2),
        "equity_mapped_weight_pct": round(sum(row["weight_pct"] or 0 for row in equity if row["ticker"]), 2),
        "mapped_by": dict(sorted(by_method.items())),
        "mapped_weight_pct": round(mapped, 2),
        "unmapped_weight_pct": round(sum(weights) - mapped, 2),
        "top10_weight_pct": round(top10, 2),
        "effective_holdings": round(1 / hhi, 1) if hhi else None,
    }


def candidate_filings(ids: dict) -> tuple[list[dict], str]:
    """NPORT-P filings to try, and how they were found ('series_feed' or 'trust_scan')."""
    try:
        rows = series_feed(sec_http.get_text(SERIES_FEED_URL.format(series_id=ids["series_id"]),
                                             accept="application/atom+xml,application/xml,*/*"))
        if rows:
            return rows, "series_feed"
    except Exception:  # noqa: BLE001 - fall back to scanning the trust's own filing list
        pass
    submissions = sec_http.get_json(SUBMISSIONS_URL.format(cik=ids["cik"]))
    return nport_filings(submissions)[:MAX_FILINGS_SCANNED], "trust_scan"


def read_filing(ticker: str, ids: dict, filing: dict, lookup: str, universe: dict,
                sec_names: dict[str, str] | None) -> dict | None:
    """The validated holdings record of one filing; None when it reports another series."""
    url = DOCUMENT_URL.format(cik=ids["cik"], accession=filing["accession"].replace("-", ""))
    document = sec_http.get_text(url, accept="application/xml,text/xml,*/*")
    if series_of(ET.fromstring(document)) != ids["series_id"]:
        return None
    parsed = parse_nport(document, universe, sec_names)
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
        "lookup": lookup,
        "mapping_version": MAPPING_VERSION,
        **{key: parsed[key] for key in ("fund_name", "registrant", "report_date", "period_end",
                                       "net_assets_usd", "monthly_flows")},
        "summary": summarise(parsed),
        "holdings": parsed["holdings"],
    }


def fetch_latest(ticker: str, universe: dict, fund_index: dict, known_accession: str | None = None,
                 sec_names: dict[str, str] | None = None) -> dict | None:
    """Newest validated N-PORT holdings for ``ticker``; None when ``known_accession`` is still the newest."""
    ids = find_series(fund_index, ticker)
    filings, lookup = candidate_filings(ids)
    for filing in filings:
        if lookup == "trust_scan":
            plain = filing["accession"].replace("-", "")
            header = sec_http.get_text(HEADER_URL.format(cik=ids["cik"], accession=plain,
                                                         dashed=filing["accession"]))
            if ids["series_id"] not in series_in_header(header):
                continue
        if filing["accession"] == known_accession:
            return None
        record = read_filing(ticker, ids, filing, lookup, universe, sec_names)
        if record is not None:
            return record
    raise LookupError(f"no NPORT-P for {ticker} ({ids['series_id']}) via {lookup}")


def history_record(record: dict) -> dict:
    """Compact point-in-time entry: mapped common-stock weights and monthly flows of one filing."""
    weights: dict[str, float] = {}
    for row in record["holdings"]:
        if row.get("ticker") and row.get("asset_category") in EQUITY_CATEGORIES and row.get("weight_pct"):
            weights[row["ticker"]] = round(weights.get(row["ticker"], 0.0) + row["weight_pct"], 4)
    summary = record.get("summary") or {}
    return {
        "accession": record["accession"],
        "report_date": record["report_date"],
        "filed": record["filed"],
        "net_assets_usd": record.get("net_assets_usd"),
        "monthly_flows": record.get("monthly_flows", []),
        "equity_weight_pct": summary.get("equity_weight_pct"),
        "equity_mapped_weight_pct": summary.get("equity_mapped_weight_pct"),
        "weights": dict(sorted(weights.items())),
    }


def fetch_history(ticker: str, universe: dict, fund_index: dict, sec_names: dict[str, str] | None,
                  known: set[str]) -> tuple[list[dict], list[dict]]:
    """(new history entries, skipped filings) for every listed NPORT-P not in ``known``.

    Only the per-series filing list is used: scanning a whole trust's index
    for years of filings would take thousands of requests.
    """
    ids = find_series(fund_index, ticker)
    filings, lookup = candidate_filings(ids)
    if lookup != "series_feed":
        return [], []
    entries, skipped = [], []
    for filing in filings:
        if filing["accession"] in known:
            continue
        try:
            record = read_filing(ticker, ids, filing, lookup, universe, sec_names)
        except (ValueError, ET.ParseError) as error:
            skipped.append({"accession": filing["accession"], "filed": filing["filed"], "reason": str(error)[:300],
                            "validation_version": VALIDATION_VERSION})
            continue
        if record is None:
            skipped.append({"accession": filing["accession"], "filed": filing["filed"], "reason": "other series",
                            "validation_version": VALIDATION_VERSION})
            continue
        entries.append(history_record(record))
    return entries, skipped


def retry_skipped(history: dict) -> set[str]:
    """Skipped accessions judged under an older VALIDATION_VERSION, to be read again."""
    return {row["accession"] for row in history.get("skipped", [])
            if row.get("validation_version", 1) != VALIDATION_VERSION}


def merge_history(history: dict, entries: list[dict], skipped: list[dict]) -> dict:
    """Append new entries (never replace an existing accession), ordered by report date then filing date.

    ``skipped`` is bookkeeping, not data: a retried filing that now passes
    leaves it, and one that fails again is recorded under the current rules.
    """
    seen = {row["accession"] for row in history["filings"]}
    filings = history["filings"] + [row for row in entries if row["accession"] not in seen]
    recorded = {row["accession"] for row in filings}
    fresh = {row["accession"]: row for row in skipped if row["accession"] not in recorded}
    kept = [row for row in history["skipped"] if row["accession"] not in recorded and row["accession"] not in fresh]
    kept += list(fresh.values())
    return {**history, "filings": sorted(filings, key=lambda row: (row["report_date"], row["filed"])),
            "skipped": sorted(kept, key=lambda row: (row["filed"], row["accession"]))}


def validate_history(history: dict) -> list[str]:
    problems = []
    accessions = [row["accession"] for row in history.get("filings", [])]
    if len(accessions) != len(set(accessions)):
        problems.append(f"{history.get('etf')}: duplicate accession in history")
    keys = [(row["report_date"], row["filed"]) for row in history.get("filings", [])]
    if keys != sorted(keys):
        problems.append(f"{history.get('etf')}: history is not ordered by report date")
    for row in history.get("filings", []):
        total = sum(row.get("weights", {}).values())
        if total > 102.5:
            problems.append(f"{history.get('etf')} {row['accession']}: weights sum to {total:.1f}%")
    return problems


def look_through(fund_value: float, holdings: dict[str, Any]) -> dict[str, float]:
    """Dollar exposure per ticker through one fund; unmapped weight under '__unmapped__'."""
    result: dict[str, float] = {}
    for row in holdings["holdings"]:
        weight = (row["weight_pct"] or 0) / 100
        key = row["ticker"] or "__unmapped__"
        result[key] = result.get(key, 0.0) + fund_value * weight
    return result
