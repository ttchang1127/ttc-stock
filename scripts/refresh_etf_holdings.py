"""Refresh the committed N-PORT holdings of the portfolio funds and the research ETFs.

Funds: those in portfolio_classification.json plus the frozen research list
``etf_holdings.THEME_ETFS``.  Run by the SEC filing workflow.  A fund file
changes only when SEC has a newer N-PORT for its series, or when the file
was mapped under an older ``MAPPING_VERSION``; a lookup or parsing problem
keeps the previous file, prints a workflow warning and is recorded in
etf_holdings/index.json, so a bad filing never replaces good data.

For the research ETFs, every NPORT-P that EDGAR lists for the series is
also kept in ``etf_holdings/history/{ETF}.json`` (point-in-time weights and
monthly flows).  The history only grows: an accession already recorded is
never re-read or replaced, and a filing that fails validation is listed
under ``skipped`` so it is not downloaded again every run.
Standard library only.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import etf_holdings
import sec_http
from jsonio import dumps, load_json, replace_texts

ROOT = Path(__file__).resolve().parent.parent
HOLDINGS_DIR = ROOT / "etf_holdings"


def fund_list(root: Path = ROOT) -> list[str]:
    portfolio = load_json(root / "portfolio_classification.json").get("funds_excluded", {})
    return sorted(set(portfolio) | set(etf_holdings.THEME_ETFS))


def empty_history(ticker: str) -> dict:
    return {"schema_version": etf_holdings.HISTORY_SCHEMA_VERSION, "etf": ticker,
            "source": "SEC Form N-PORT (NPORT-P)", "filings": [], "skipped": []}


def refresh_history(ticker: str, holdings_dir: Path, universe: dict, fund_index: dict, sec_names: dict,
                    fresh: dict | None, history_fetch) -> tuple[dict[Path, str], list[str]]:
    path = holdings_dir / "history" / f"{ticker}.json"
    history = load_json(path, None) or empty_history(ticker)
    entries = [etf_holdings.history_record(fresh)] if fresh else []
    known = ({row["accession"] for row in history["filings"]} | {row["accession"] for row in history["skipped"]}
             | {row["accession"] for row in entries})
    try:
        more, skipped = history_fetch(ticker, universe, fund_index, sec_names, known)
    except Exception as error:  # noqa: BLE001 - history is best effort; the latest file is already handled
        more, skipped = [], []
        message = f"::warning::{ticker} N-PORT history not extended: {type(error).__name__}: {error}"
    else:
        message = None
    merged = etf_holdings.merge_history(history, entries + more, skipped)
    if merged == history:
        return {}, [message] if message else []
    added = len(merged["filings"]) - len(history["filings"])
    messages = [f"{ticker}: history +{added} filing(s), {len(merged['filings'])} since "
                f"{merged['filings'][0]['report_date'] if merged['filings'] else '—'}"
                + (f", {len(skipped)} skipped" if skipped else "")]
    return {path: dumps(merged, indent=1)}, messages + ([message] if message else [])


def refresh(root: Path = ROOT, holdings_dir: Path = HOLDINGS_DIR, fetch=etf_holdings.fetch_latest,
            fund_index: dict | None = None, sec_names: dict | None = None,
            history_fetch=etf_holdings.fetch_history) -> tuple[dict[Path, str], list[str]]:
    funds = fund_list(root)
    universe = load_json(root / "market_rotation_universe.json")
    index_path = holdings_dir / "index.json"
    index = load_json(index_path, {"schema_version": 1, "funds": {}})
    texts, messages = {}, []
    if fund_index is None:
        fund_index = sec_http.get_json(etf_holdings.TICKERS_URL)
    if sec_names is None:
        try:
            sec_names = etf_holdings.sec_name_index(sec_http.get_json(etf_holdings.SEC_TICKERS_URL))
        except Exception as error:  # noqa: BLE001 - mapping without it would silently drop coverage
            return {}, [f"::warning::ETF holdings not refreshed: SEC company list unavailable "
                        f"({type(error).__name__}: {error}); previous files kept"]
    for ticker in funds:
        path = holdings_dir / f"{ticker}.json"
        current = load_json(path, None)
        entry = dict(index["funds"].get(ticker, {}))
        fresh = None
        try:
            current_mapping = current and current.get("mapping_version") == etf_holdings.MAPPING_VERSION
            fresh = fetch(ticker, universe, fund_index, current["accession"] if current_mapping else None,
                          sec_names)
        except Exception as error:  # noqa: BLE001 - keep the last good file, report the problem
            entry["error"] = f"{type(error).__name__}: {error}"
            messages.append(f"::warning::{ticker} holdings not refreshed: {entry['error']}")
        else:
            entry.pop("error", None)
            if fresh is None:
                messages.append(f"{ticker}: holdings for {current['report_date']} are still the newest")
            else:
                texts[path] = dumps(fresh, indent=1)
                entry.update({"accession": fresh["accession"], "report_date": fresh["report_date"],
                              "filed": fresh["filed"], "lookup": fresh.get("lookup"),
                              "mapping_version": fresh.get("mapping_version"), **fresh["summary"]})
                messages.append(f"{ticker}: holdings updated to {fresh['report_date']} ({fresh['accession']}), "
                                f"mapped {fresh['summary']['mapped_weight_pct']}%")
        if entry != index["funds"].get(ticker):
            index["funds"][ticker] = entry
            texts[index_path] = dumps(index, indent=1)
        if ticker in etf_holdings.THEME_ETFS:
            history_texts, history_messages = refresh_history(ticker, holdings_dir, universe, fund_index,
                                                              sec_names, fresh, history_fetch)
            texts.update(history_texts)
            messages.extend(history_messages)
    return texts, messages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    texts, messages = refresh(args.root, args.root / "etf_holdings")
    replace_texts(texts)
    for message in messages:
        print(message)


if __name__ == "__main__":
    main()
