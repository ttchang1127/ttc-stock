"""Build etf_health.json: constituent health of the research theme ETFs.

Run by the daily market refresh after the rotation build.  Reads the
committed N-PORT holdings (etf_holdings/{ETF}.json, refreshed by the SEC
workflow), downloads about 100 sessions of closes for the ETFs, SPY and
every mapped constituent, and writes the research file.  A run that cannot
price SPY, or whose latest session is older than the file already
published, leaves the file untouched; a rerun on the same session with the
same numbers does not rewrite it.  Each session is also appended once to
etf_health_history/YYYY-MM.jsonl, in the same atomic write.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

import etf_health
import etf_holdings
import jsonl_history
import record_etf_flows
from jsonio import dumps, load_json, replace_texts

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "etf_health.json"
HOLDINGS_DIR = ROOT / "etf_holdings"
FLOWS_DIR = ROOT / "etf_flows_history"
HEALTH_HISTORY_DIR = ROOT / "etf_health_history"
CALENDAR_DAYS = 150


def load_funds(holdings_dir: Path) -> dict[str, dict | None]:
    return {ticker: load_json(holdings_dir / f"{ticker}.json", None) for ticker in etf_holdings.THEME_ETFS}


def tickers_to_price(funds: dict[str, dict | None]) -> list[str]:
    wanted = set(etf_holdings.THEME_ETFS) | {etf_health.BENCHMARK}
    for fund in funds.values():
        for row in (fund or {}).get("holdings", []):
            if row.get("ticker") and row.get("asset_category") in etf_holdings.EQUITY_CATEGORIES:
                wanted.add(row["ticker"])
    return sorted(wanted)


def yahoo(ticker: str) -> str:
    return ticker.replace(".", "-")


def download(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    from build_market_rotation import fetch_market_data  # noqa: PLC0415 - pulls in yfinance (CI only)

    closes, _ = fetch_market_data([yahoo(t) for t in tickers], start, end)
    back = {yahoo(t): t for t in tickers}
    closes = closes.rename(columns=lambda column: back.get(column, column))
    closes.index = pd.to_datetime(closes.index)
    return closes.sort_index()


def unchanged(previous: dict | None, payload: dict) -> bool:
    if not previous:
        return False
    strip = lambda data: {key: value for key, value in data.items() if key != "generated_at"}  # noqa: E731
    return strip(previous) == strip(payload)


def build(output: Path, holdings_dir: Path, fetch=download, today: date | None = None,
          flows_dir: Path = FLOWS_DIR, history_dir: Path = HEALTH_HISTORY_DIR) -> tuple[bool, str]:
    """(written, message); raises SystemExit(75) when the prices are unusable."""
    funds = load_funds(holdings_dir)
    tickers = tickers_to_price(funds)
    end = (today or date.today()) + timedelta(days=1)
    closes = fetch(tickers, end - timedelta(days=CALENDAR_DAYS), end)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        payload = etf_health.compute(funds, closes, generated_at, record_etf_flows.read_history(flows_dir))
    except ValueError as error:
        print(f"::warning::ETF health not rebuilt: {error}", file=sys.stderr)
        raise SystemExit(75) from error
    problems = etf_health.validate(payload)
    if problems:
        raise ValueError("etf_health.json failed validation: " + "; ".join(problems))
    previous = load_json(output, None)
    if previous and previous.get("as_of", "") > payload["as_of"]:
        return False, f"kept {output.name}: published {previous['as_of']} is newer than {payload['as_of']}"
    texts, status, history_message = jsonl_history.plan_append(etf_health.snapshot(payload), history_dir)
    if status in ("conflict", "out_of_order"):
        history_message = "::warning::" + history_message
    if not unchanged(previous, payload):
        texts[output] = dumps(payload, indent=1)
    replace_texts(texts)
    if output not in texts:
        return False, f"{output.name} unchanged for {payload['as_of']}; {history_message}"
    states = ", ".join(f"{row['ticker']} {etf_health.STATES[row['state']]}" for row in payload["etfs"])
    return True, f"ETF health {payload['as_of']}: {states or 'no holdings yet'}; {history_message}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--holdings-dir", type=Path, default=HOLDINGS_DIR)
    parser.add_argument("--flows-dir", type=Path, default=FLOWS_DIR)
    parser.add_argument("--history-dir", type=Path, default=HEALTH_HISTORY_DIR)
    args = parser.parse_args()
    _, message = build(args.output, args.holdings_dir, flows_dir=args.flows_dir, history_dir=args.history_dir)
    print(message)


if __name__ == "__main__":
    main()
