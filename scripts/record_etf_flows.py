"""Append today's shares outstanding and assets of the research ETFs.

N-PORT reports real monthly creations and redemptions, but two to five
months late.  For a current read this records, once per market session,
what Yahoo Finance shows for each research ETF: shares outstanding, total
assets and the close.  Daily flows are then estimated from the changes
(``etf_health.implied_flows``).  Yahoo's figures carry no date of their
own and are not always refreshed daily, so the estimate is labelled as
such; the history only starts on the first run (it cannot be back-filled)
and is append-only: one line per session in ``etf_flows_history/YYYY-MM.jsonl``.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import etf_holdings
from jsonio import dumps, replace_texts

ROOT = Path(__file__).resolve().parent.parent
FLOWS_DIR = ROOT / "etf_flows_history"
SOURCE = "Yahoo Finance (yfinance Ticker.info), 每次排程觀察值"


def finite(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) and number > 0 else None


def snapshot(as_of: str, closes: dict[str, float | None], info: dict[str, dict], recorded_at: str) -> dict:
    etfs = {}
    for ticker in sorted(etf_holdings.THEME_ETFS):
        data = info.get(ticker) or {}
        etfs[ticker] = {"close": finite(closes.get(ticker)),
                        "shares_outstanding": finite(data.get("sharesOutstanding")),
                        "total_assets": finite(data.get("totalAssets"))}
    return {"as_of": as_of, "recorded_at": recorded_at, "source": SOURCE, "etfs": etfs}


def read_history(directory: Path) -> list[dict]:
    rows = []
    for path in sorted(directory.glob("*.jsonl")):
        rows.extend(json.loads(line) for line in path.read_text().splitlines() if line.strip())
    return rows


def plan_append(record: dict, directory: Path) -> tuple[dict[Path, str], str, str]:
    """(texts, status, message); status is appended / unchanged / conflict / out_of_order."""
    history = read_history(directory)
    same = next((row for row in history if row["as_of"] == record["as_of"]), None)
    if same is not None:
        if same["etfs"] == record["etfs"]:
            return {}, "unchanged", f"flows for {record['as_of']} already recorded"
        return {}, "conflict", f"flows for {record['as_of']} already recorded with other values; kept the first"
    if history and history[-1]["as_of"] > record["as_of"]:
        return {}, "out_of_order", f"{record['as_of']} is older than the last record {history[-1]['as_of']}"
    path = directory / f"{record['as_of'][:7]}.jsonl"
    existing = path.read_text() if path.exists() else ""
    return {path: existing + dumps(record)}, "appended", f"flows recorded for {record['as_of']}"


def validate_history(directory: Path) -> list[str]:
    problems = []
    dates = []
    for path in sorted(directory.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if not row["as_of"].startswith(path.stem):
                problems.append(f"{path.name}: {row['as_of']} is in the wrong month file")
            dates.append(row["as_of"])
    if dates != sorted(set(dates)):
        problems.append("etf_flows_history dates are duplicated or out of order")
    return problems


def fetch(today: date) -> tuple[str, dict[str, float | None], dict[str, dict]]:
    import yfinance as yf  # noqa: PLC0415 - CI only

    tickers = sorted(etf_holdings.THEME_ETFS)
    frame = yf.download(tickers, start=(today - timedelta(days=10)).isoformat(),
                        end=(today + timedelta(days=1)).isoformat(), interval="1d", auto_adjust=False,
                        actions=False, group_by="column", progress=False, threads=True)
    closes = frame["Close"].dropna(how="all")
    if closes.empty:
        raise ValueError("no ETF closes")
    last = closes.index[-1]
    info = {}
    for ticker in tickers:
        try:
            info[ticker] = yf.Ticker(ticker).info or {}
        except Exception:  # noqa: BLE001 - one missing quote page must not lose the others
            info[ticker] = {}
    return last.date().isoformat(), closes.iloc[-1].to_dict(), info


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--flows-dir", type=Path, default=FLOWS_DIR)
    args = parser.parse_args()
    as_of, closes, info = fetch(date.today())
    record = snapshot(as_of, closes, info, datetime.now(timezone.utc).isoformat(timespec="seconds"))
    texts, status, message = plan_append(record, args.flows_dir)
    replace_texts(texts)
    missing = [ticker for ticker, row in record["etfs"].items()
               if row["shares_outstanding"] is None and row["total_assets"] is None]
    print(("::warning::" if status in ("conflict", "out_of_order") else "") + message)
    if missing:
        print(f"::warning::Yahoo shows neither shares outstanding nor assets for {', '.join(missing)}")


if __name__ == "__main__":
    main()
