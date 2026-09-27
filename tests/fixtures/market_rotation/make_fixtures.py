"""Regenerate the deterministic market-rotation fixture inputs.

The CSV/JSON inputs are committed; this script only documents how they were
made.  It uses fixed arithmetic paths and no random numbers.  Regenerating
must reproduce byte-identical files.
"""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SESSIONS = 120
START = date(2026, 1, 2)

# (sector, industries, base / previous-5 / latest-5 daily growth, volume path)
SECTORS = (
    ("Information Technology", ("Semiconductors", "Application Software"),
     (0.004, 0.002, 0.006), "expand"),
    ("Industrials", ("Aerospace & Defense", "Rail Transportation"),
     (-0.004, -0.006, 0.004), "flat"),
    ("Health Care", ("Biotechnology", "Health Care Equipment"),
     (0.004, 0.006, -0.002), "flat"),
    ("Energy", ("Integrated Oil & Gas", "Oil & Gas Drilling"),
     (-0.004, -0.002, -0.006), "contract"),
)
PREFIX = {"Information Technology": "TEC", "Industrials": "IND",
          "Health Care": "HLT", "Energy": "ENE"}


def sessions() -> list[date]:
    days, value = [], START
    while len(days) < SESSIONS:
        if value.weekday() < 5:
            days.append(value)
        value += timedelta(days=1)
    return days


def growth_for(session: int, path: tuple[float, float, float]) -> float:
    base, previous, latest = path
    if session >= SESSIONS - 5:
        return latest
    if session >= SESSIONS - 10:
        return previous
    return base


def volume_multiplier(session: int, path: str) -> float:
    if session < SESSIONS - 5:
        return 1.0
    return {"expand": 1.5, "contract": 0.6, "flat": 1.0}[path]


def build() -> tuple[dict, list[list], list[list]]:
    members, closes, volumes = [], {}, {}
    for sector, industries, path, volume_path in SECTORS:
        for number in range(6):
            ticker = f"{PREFIX[sector]}{number}"
            members.append({
                "ticker": ticker,
                "yahoo_ticker": ticker,
                "name": f"{sector} Fixture {number}",
                "sector": sector,
                "industry": industries[number // 3],
                "indexes": ["S&P 500"],
                "classification": "GICS",
            })
            # Spread members symmetrically around the sector path so leader and
            # laggard order is known without changing the sector average.
            tilt = (number - 2.5) * 0.0004
            price, series, volume_series = 100.0 + number, [], []
            for session in range(SESSIONS):
                if session:
                    price *= 1 + growth_for(session, path) + tilt
                series.append(round(price, 6))
                volume_series.append(int(1_000_000 * (1 + number / 10)
                                         * volume_multiplier(session, volume_path)))
            closes[ticker], volumes[ticker] = series, volume_series
    tickers = [row["ticker"] for row in members]
    days = sessions()
    close_rows = [["date", *tickers]] + [
        [day.isoformat(), *(closes[t][i] for t in tickers)] for i, day in enumerate(days)
    ]
    volume_rows = [["date", *tickers]] + [
        [day.isoformat(), *(volumes[t][i] for t in tickers)] for i, day in enumerate(days)
    ]
    universe = {
        "schema_version": 1,
        "generated_at": "2026-01-01T00:00:00+00:00",
        "counts": {"sp500_securities": len(members), "nasdaq100_securities": 0,
                   "combined_securities": len(members)},
        "members": members,
    }
    return universe, close_rows, volume_rows


def write_csv(path: Path, rows: list[list]) -> None:
    with path.open("w", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)


def main() -> None:
    universe, close_rows, volume_rows = build()
    target = HERE / "quadrants"
    target.mkdir(exist_ok=True)
    (target / "universe.json").write_text(
        json.dumps(universe, ensure_ascii=False, indent=1) + "\n")
    write_csv(target / "closes.csv", close_rows)
    write_csv(target / "volumes.csv", volume_rows)


if __name__ == "__main__":
    main()
