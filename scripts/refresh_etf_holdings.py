"""Refresh the committed N-PORT holdings of the funds in portfolio_classification.json.

Run by the SEC filing workflow.  A fund file changes only when SEC has a
newer N-PORT for its series; a lookup or parsing problem keeps the previous
file, prints a workflow warning and is recorded in etf_holdings/index.json,
so a bad filing never replaces good data.  Standard library only.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import etf_holdings
import sec_http
from jsonio import dumps, load_json, replace_texts

ROOT = Path(__file__).resolve().parent.parent
HOLDINGS_DIR = ROOT / "etf_holdings"


def refresh(root: Path = ROOT, holdings_dir: Path = HOLDINGS_DIR, fetch=etf_holdings.fetch_latest,
            fund_index: dict | None = None) -> tuple[dict[Path, str], list[str]]:
    funds = sorted(load_json(root / "portfolio_classification.json").get("funds_excluded", {}))
    universe = load_json(root / "market_rotation_universe.json")
    index_path = holdings_dir / "index.json"
    index = load_json(index_path, {"schema_version": 1, "funds": {}})
    texts, messages = {}, []
    if fund_index is None:
        fund_index = sec_http.get_json(etf_holdings.TICKERS_URL)
    for ticker in funds:
        path = holdings_dir / f"{ticker}.json"
        current = load_json(path, None)
        entry = dict(index["funds"].get(ticker, {}))
        try:
            fresh = fetch(ticker, universe, fund_index, current["accession"] if current else None)
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
                              "filed": fresh["filed"], **fresh["summary"]})
                messages.append(f"{ticker}: holdings updated to {fresh['report_date']} ({fresh['accession']}), "
                                f"mapped {fresh['summary']['mapped_weight_pct']}%")
        if entry != index["funds"].get(ticker):
            index["funds"][ticker] = entry
            texts[index_path] = dumps(index, indent=1)
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
