#!/usr/bin/env python3
"""Probe whether Yahoo has published the latest expected adjusted close.

The broad rotation download is expensive.  This lightweight SPY probe lets the
scheduled workflow wait or defer before downloading hundreds of securities.
Exit status 75 means the source is temporarily stale, not that other SEC work
should fail.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

from build_market_rotation import expected_latest_market_session, market_session_lag


TEMPORARILY_STALE = 75


def adjusted_close(frame: pd.DataFrame, symbol: str) -> pd.Series:
    if frame.empty or "Adj Close" not in frame:
        return pd.Series(dtype=float)
    values = frame["Adj Close"]
    if isinstance(values, pd.DataFrame):
        if symbol in values.columns:
            values = values[symbol]
        elif len(values.columns) == 1:
            values = values.iloc[:, 0]
        else:
            return pd.Series(dtype=float)
    return pd.to_numeric(values, errors="coerce").dropna()


def fetch_latest_session(symbol: str, expected: date) -> date | None:
    frame = yf.download(
        symbol,
        start=(expected - timedelta(days=14)).isoformat(),
        end=(datetime.now(timezone.utc).date() + timedelta(days=2)).isoformat(),
        interval="1d",
        auto_adjust=False,
        actions=False,
        progress=False,
    )
    values = adjusted_close(frame, symbol)
    if values.empty:
        return None
    return values.index[-1].date()


def append_github_output(path: Path | None, values: dict[str, str]) -> None:
    if path is None:
        return
    with path.open("a") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="SPY")
    parser.add_argument("--expected-session", type=date.fromisoformat)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    expected = args.expected_session or expected_latest_market_session()
    latest = fetch_latest_session(args.symbol, expected)
    fresh = latest is not None and latest >= expected
    lag = market_session_lag(latest, expected) if latest is not None else "unknown"
    append_github_output(
        args.github_output,
        {
            "expected_session": expected.isoformat(),
            "latest_session": latest.isoformat() if latest else "unavailable",
            "lag_sessions": str(lag),
            "fresh": str(fresh).lower(),
        },
    )

    if fresh:
        print(
            f"Market source ready: {args.symbol} adjusted close {latest.isoformat()} "
            f"meets expected session {expected.isoformat()}."
        )
        return 0
    print(
        f"Market source stale: {args.symbol} adjusted close "
        f"{latest.isoformat() if latest else 'unavailable'}, expected {expected.isoformat()} "
        f"({lag} sessions behind)."
    )
    return TEMPORARILY_STALE


if __name__ == "__main__":
    raise SystemExit(main())
