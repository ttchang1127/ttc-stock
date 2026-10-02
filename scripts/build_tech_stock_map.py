"""Build a dated, company-level US-listed technology heat map.

The human-maintained taxonomy is an eligibility list, not a claim that an
index or a fund defines what technology is. Nasdaq's public quote pages
provide market caps and historical *unadjusted* closes. No missing market
cap is estimated from an ETF holding or a different share class.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from jsonio import write_json

ROOT = Path(__file__).resolve().parents[1]
TAXONOMY = ROOT / "tech_stock_taxonomy.json"
OUTPUT = ROOT / "tech_stock_map.json"
PERIODS = {"1d": 1, "1w": 5, "1m": 21, "3m": 63, "6m": 126}
SOX_2026_08 = set("AMD ADI AMAT ARM ASML ALAB AVGO COHR CRDO ENTG GFS INTC KLAC LRCX MTSI MRVL MCHP MU MPWR NVMI NVDA NXPI ON QRVO QCOM RMBS SWKS TSM TER TXN".split())
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ttc-stock research)", "Accept": "application/json"}


def check_taxonomy(config: dict) -> dict[str, dict]:
    definitions = {}
    for family in config["families"]:
        for group in family["groups"]:
            for ticker in group["tickers"]:
                if ticker in definitions:
                    raise ValueError(f"duplicate ticker in taxonomy: {ticker}")
                definitions[ticker] = {
                    "family_id": family["id"], "family": family["label"],
                    "group_id": group["id"], "group": group["label"],
                    "reason": group["reason"],
                }
    if not set(config["always_show"]) <= definitions.keys():
        raise ValueError("all always_show symbols must have a classification")
    if set(config.get("excluded_from_vgt", {})) & definitions.keys():
        raise ValueError("a deliberately excluded VGT member also has a map classification")
    if not config["minimum_market_cap_usd"] > 0:
        raise ValueError("market cap threshold must be positive")
    return definitions


def source_members(tickers: set[str], excluded: set[str] | None = None) -> tuple[dict[str, list[str]], dict[str, str], dict]:
    universe = json.loads((ROOT / "market_rotation_universe.json").read_text())
    vgt = json.loads((ROOT / "etf_holdings/VGT.json").read_text())
    vgt_members = {row["ticker"] for row in vgt["holdings"] if row.get("asset_category") == "EC" and row.get("ticker")}
    indexed = {row["ticker"]: row for row in universe["members"]}
    sources = {}
    names = {}
    for ticker in tickers:
        found = []
        if ticker in vgt_members:
            found.append("VGT")
        if ticker in SOX_2026_08:
            found.append("SOX 2026-08-03")
        for index in indexed.get(ticker, {}).get("indexes", []):
            found.append(index)
        sources[ticker] = found or ["人工補充"]
        names[ticker] = indexed.get(ticker, {}).get("name", "")
    for row in vgt["holdings"]:
        if row.get("ticker") in names and not names[row["ticker"]]:
            names[row["ticker"]] = row["name"]
    dates = {"vgt_report_date": vgt["report_date"], "vgt_filed": vgt["filed"],
             "index_universe_generated_at": universe["generated_at"], "sox_date": "2026-08-03"}
    return sources, names, {"dates": dates, "vgt_unclassified": sorted(vgt_members - tickers - (excluded or set()))}


def get_api(url: str) -> dict | None:
    for attempt in range(2):
        try:
            with urlopen(Request(url, headers=HEADERS), timeout=20) as response:
                value = json.load(response)
            return value.get("data") if value.get("status", {}).get("rCode") in (None, 200) else None
        except (OSError, ValueError, TimeoutError):
            if attempt == 0:
                time.sleep(0.7)
    return None


def parse_cap(value: str | None) -> int | None:
    if not value or value == "N/A":
        return None
    try:
        number = int(re.sub(r"[^\d]", "", value))
        return number if number > 0 else None
    except ValueError:
        return None


def quote(ticker: str, from_date: date, to_date: date) -> dict:
    base = f"https://api.nasdaq.com/api/quote/{ticker}"
    summary = get_api(f"{base}/summary?assetclass=stocks") or {}
    cap = parse_cap((summary.get("summaryData", {}).get("MarketCap") or {}).get("value"))
    args = urlencode({"assetclass": "stocks", "limit": 220,
                      "fromdate": from_date.isoformat(), "todate": to_date.isoformat()})
    history = get_api(f"{base}/historical?{args}") or {}
    closes = {}
    for row in (history.get("tradesTable") or {}).get("rows") or []:
        try:
            stamp = datetime.strptime(row["date"], "%m/%d/%Y").date().isoformat()
            price = float(row["close"].replace("$", "").replace(",", ""))
            if math.isfinite(price) and price > 0:
                closes[stamp] = price
        except (KeyError, ValueError, TypeError):
            continue
    return {"cap": cap, "closes": closes,
            "name": summary.get("additionalData", {}).get("CompanyName") if isinstance(summary.get("additionalData"), dict) else None}


def fetch_quotes(tickers: list[str], from_date: date, to_date: date, workers: int,
                 *, fetcher=quote, sleep=time.sleep) -> dict[str, dict]:
    """Retry incomplete Nasdaq quotes slowly before rejecting a dated snapshot."""
    def batch(symbols: list[str], concurrency: int) -> dict[str, dict]:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            pending = {executor.submit(fetcher, ticker, from_date, to_date): ticker for ticker in symbols}
            return {pending[future]: future.result() for future in as_completed(pending)}

    quotes = batch(tickers, max(1, min(16, workers)))
    for attempt in (1, 2):
        latest = max((max(row["closes"]) for row in quotes.values() if row["closes"]), default=None)
        incomplete = sorted(ticker for ticker, row in quotes.items()
                            if not row["cap"] or not row["closes"]
                            or (latest and max(row["closes"]) < latest))
        if not incomplete:
            break
        print(f"Nasdaq retry {attempt}/2: {len(incomplete)} incomplete quotes", flush=True)
        sleep(5 * attempt)
        for ticker, refreshed in batch(incomplete, 2).items():
            current = quotes[ticker]
            histories = (current["closes"], refreshed["closes"])
            quotes[ticker] = {
                "cap": refreshed["cap"] or current["cap"],
                "closes": max(histories, key=lambda rows: (max(rows, default=""), len(rows))),
                "name": refreshed["name"] or current["name"],
            }
    latest = max((max(row["closes"]) for row in quotes.values() if row["closes"]), default="none")
    print(f"Nasdaq coverage: {sum(bool(row['cap']) for row in quotes.values())}/{len(quotes)} caps, "
          f"{sum(bool(row['closes']) and max(row['closes']) == latest for row in quotes.values())}/{len(quotes)} "
          f"histories through {latest}", flush=True)
    return quotes


def returns(closes: dict[str, float], as_of: str) -> tuple[dict, bool | None]:
    dates = sorted(day for day in closes if day <= as_of)
    if not dates or dates[-1] != as_of:
        return {period: None for period in PERIODS}, None
    prices = [closes[day] for day in dates]
    values = {period: round((prices[-1] / prices[-1 - sessions] - 1) * 100, 2)
              if len(prices) > sessions else None for period, sessions in PERIODS.items()}
    ma50 = prices[-1] > sum(prices[-50:]) / 50 if len(prices) >= 50 else None
    return values, ma50


def aggregate(stocks: list[dict], key: str) -> list[dict]:
    buckets = defaultdict(list)
    for row in stocks:
        buckets[row[key + "_id"]].append(row)
    result = []
    for group_id, members in buckets.items():
        available = [m for m in members if m["returns"]["1m"] is not None]
        total = sum(m["market_cap_usd"] for m in available)
        count_up = sum(m["returns"]["1m"] > 0 for m in available)
        result.append({"id": group_id, "label": members[0][key], "count": len(members),
                       "priced": len(available), "market_cap_usd": sum(m["market_cap_usd"] for m in members),
                       "up_1m_pct": round(100 * count_up / len(available), 1) if available else None,
                       "equal_1m_pct": round(sum(m["returns"]["1m"] for m in available) / len(available), 2) if available else None,
                       "cap_weighted_1m_pct": round(sum(m["returns"]["1m"] * m["market_cap_usd"] for m in available) / total, 2) if total else None,
                       "above_ma50_pct": round(100 * sum(m["above_ma50"] is True for m in members if m["above_ma50"] is not None)
                                                / sum(m["above_ma50"] is not None for m in members), 1)
                                         if any(m["above_ma50"] is not None for m in members) else None})
    return sorted(result, key=lambda row: -row["market_cap_usd"])


def build(config: dict, quotes: dict[str, dict], *, generated_at: str | None = None) -> dict:
    definitions = check_taxonomy(config)
    sources, names, provenance = source_members(set(definitions), set(config.get("excluded_from_vgt", {})))
    dates = [max(q["closes"]) for q in quotes.values() if q.get("closes")]
    if not dates:
        raise ValueError("No historical prices available")
    as_of = max(dates)
    threshold = config["minimum_market_cap_usd"]
    always = set(config["always_show"])
    included, excluded = [], []
    for ticker, classification in definitions.items():
        quote_data = quotes.get(ticker, {})
        cap = quote_data.get("cap")
        if not cap or (cap < threshold and ticker not in always):
            excluded.append({"ticker": ticker, "reason": "缺少市值" if not cap else "市值未達門檻"})
            continue
        overrides = config.get("ticker_overrides", {}).get(ticker, {})
        series, above = returns(quote_data.get("closes", {}), as_of)
        included.append({"ticker": ticker, "name": names[ticker] or ticker, **classification,
                         "reason": overrides.get("reason", classification["reason"]),
                         "tags": overrides.get("tags", []), "sources": sources[ticker],
                         "market_cap_usd": cap, "returns": series, "above_ma50": above,
                         "quote_as_of": max(quote_data["closes"]) if quote_data.get("closes") else None,
                         "is_watchlist": ticker in always, "is_adjacent": classification["family_id"] == "adjacent",
                         "below_threshold": cap < threshold})
    included.sort(key=lambda row: -row["market_cap_usd"])
    priced_count = sum(row["returns"]["1m"] is not None for row in included)
    if len(included) < 40 or priced_count < max(40, .8 * len(included)):
        raise ValueError(f"Insufficient map coverage: {len(included)} companies, "
                         f"{priced_count} current prices")
    health = json.loads((ROOT / "etf_health.json").read_text())
    reference = [{"ticker": row["ticker"], "r5_pct": row["etf"]["r5_pct"],
                  "r20_pct": row["etf"]["r20_pct"], "r60_pct": row["etf"]["r60_pct"]}
                 for row in health["etfs"] if row["ticker"] in config["reference_etfs"]]
    return {"schema_version": 1, "taxonomy_version": config["version"],
            "generated_at": generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "as_of": as_of, "market_cap_as_of": as_of,
            "minimum_market_cap_usd": threshold,
            "price_source": "Nasdaq historical API, raw close (not dividend- or split-adjusted)",
            "cap_source": "Nasdaq quote summary, company market capitalization USD",
            "sources": provenance["dates"],
            "coverage": {"classified": len(definitions), "visible": len(included),
                         "priced": priced_count,
                         "vgt_pending_classification": len(provenance["vgt_unclassified"]),
                         "excluded": excluded},
            "period_sessions": PERIODS, "stocks": included,
            "families": aggregate(included, "family"), "groups": aggregate(included, "group"),
            "reference_etfs": {"as_of": health["as_of"], "items": reference}}


def reclassify_existing(config: dict, previous: dict) -> dict:
    """Apply taxonomy-only edits to the last dated snapshot without inventing new quotes."""
    definitions = check_taxonomy(config)
    old_candidates = {row["ticker"] for row in previous["stocks"]}
    old_candidates |= {row["ticker"] for row in previous["coverage"]["excluded"]}
    if set(definitions) != old_candidates or config["minimum_market_cap_usd"] != previous["minimum_market_cap_usd"]:
        raise ValueError("Candidate list or threshold changed: fresh price and market-cap fetch required")
    updated = json.loads(json.dumps(previous))
    updated["taxonomy_version"] = config["version"]
    updated["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for row in updated["stocks"]:
        classification = definitions[row["ticker"]]
        row.update(classification)
        override = config.get("ticker_overrides", {}).get(row["ticker"], {})
        row["reason"] = override.get("reason", classification["reason"])
        row["tags"] = override.get("tags", [])
        row["is_adjacent"] = classification["family_id"] == "adjacent"
    updated["families"] = aggregate(updated["stocks"], "family")
    updated["groups"] = aggregate(updated["stocks"], "group")
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--reclassify-existing", action="store_true",
                        help="Rebuild only classifications, requiring identical candidate list and threshold")
    args = parser.parse_args()
    config = json.loads(TAXONOMY.read_text())
    if args.reclassify_existing:
        updated = reclassify_existing(config, json.loads(args.output.read_text()))
        write_json(args.output, updated, indent=None)
        print(f"Reclassified {len(updated['stocks'])} companies as {config['version']}; quotes remain dated {updated['as_of']}")
        return
    tickers = sorted(check_taxonomy(config))
    today = date.today()
    start = today - timedelta(days=240)
    print(f"Fetching {len(tickers)} classified companies from Nasdaq", flush=True)
    quotes = fetch_quotes(tickers, start, today, args.workers)
    data = build(config, quotes)
    previous = json.loads(args.output.read_text()) if args.output.exists() else None
    if previous and previous["as_of"] > data["as_of"]:
        print(f"Keeping newer {args.output.name} ({previous['as_of']})")
        return
    # Temporary provider gaps must not silently remove an existing tile.
    if previous and (len(data["stocks"]) < 0.85 * len(previous["stocks"])
                     or data["coverage"]["priced"] < .85 * previous["coverage"]["priced"]):
        raise ValueError(f"New map lost more than 15% of its companies or prices "
                         f"({len(previous['stocks'])}/{previous['coverage']['priced']} previous, "
                         f"{len(data['stocks'])}/{data['coverage']['priced']} new); keeping published data")
    if previous:
        comparable = lambda item: {key: value for key, value in item.items() if key != "generated_at"}
        if comparable(previous) == comparable(data):
            print(f"{args.output.name} unchanged for {data['as_of']}")
            return
    write_json(args.output, data, indent=None)
    print(f"{data['as_of']}: {len(data['stocks'])} companies, {data['coverage']['priced']} priced; wrote {args.output.name}")


if __name__ == "__main__":
    main()
