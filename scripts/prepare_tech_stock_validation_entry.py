"""Freeze forward-validation entry and price-only controls after the first eligible close.

Run after a US market close: python scripts/prepare_tech_stock_validation_entry.py
No output artifact is written until both benchmarks have an adjusted close after
the cohort freeze. The dated artifact preserves the queried prices and missing rows.
"""

import argparse
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf


ROOT = Path(__file__).resolve().parent.parent
FROZEN = ROOT / "tech_stock_validation_20261010.json"
OUTPUT_DIR = ROOT / "research" / "tech_stock_validation"
NEW_YORK = ZoneInfo("America/New_York")


def fetch_prices(tickers, end_exclusive):
    series = {}
    for offset in range(0, len(tickers), 20):
        batch = tickers[offset:offset + 20]
        frame = yf.download(
            batch, start="2026-08-20", end=end_exclusive, interval="1d",
            auto_adjust=False, actions=True, progress=False, threads=False,
            timeout=20, group_by="ticker",
        )
        for ticker in batch:
            try:
                part = frame[ticker] if isinstance(frame.columns, pd.MultiIndex) else frame
                part = part.dropna(subset=["Adj Close", "Close"])
                series[ticker] = [
                    {"date": day.strftime("%Y-%m-%d"),
                     "adj_close": round(float(row["Adj Close"]), 6),
                     "close": round(float(row["Close"]), 6),
                     "dividend": round(float(row.get("Dividends", 0) or 0), 6),
                     "split": round(float(row.get("Stock Splits", 0) or 0), 6)}
                    for day, row in part.iterrows()
                ]
            except (KeyError, TypeError, ValueError):
                series[ticker] = []
    return series


def build_entry(frozen, series, observed_at):
    freeze_date = frozen["frozen_at"][:10]
    spy_dates = {r["date"] for r in series.get("SPY", []) if r["adj_close"] > 0}
    vgt_dates = {r["date"] for r in series.get("VGT", []) if r["adj_close"] > 0}
    eligible = sorted(day for day in spy_dates & vgt_dates if day > freeze_date)
    if not eligible:
        return None
    entry_date = eligible[0]
    # Reject a still-forming or just-closed session; Yahoo may publish provisional bars.
    observed_ny = observed_at.astimezone(NEW_YORK)
    if date.fromisoformat(entry_date) >= observed_ny.date():
        return None
    common_prior = sorted(day for day in spy_dates & vgt_dates if day < entry_date)
    if len(common_prior) < 22:
        raise ValueError("Fewer than 22 common SPY/VGT sessions before entry")
    momentum_start, momentum_end = common_prior[-22], common_prior[-1]
    cards = {row["ticker"] for row in frozen["signal_cohort"]}
    pool = frozen["candidate_pool"]["visible_tickers"]
    if len(pool) != frozen["candidate_pool"]["count"] or not cards <= set(pool):
        raise ValueError("Frozen cohort is internally inconsistent")
    snapshot_path = ROOT / frozen["source_snapshot"]["path"]
    if hashlib.sha256(snapshot_path.read_bytes()).hexdigest() != frozen["source_snapshot"]["sha256"]:
        raise ValueError("Frozen source snapshot hash mismatch")
    snapshot = json.loads(snapshot_path.read_text())
    prices = {ticker: {row["date"]: row for row in series.get(ticker, [])}
              for ticker in set(pool) | {"SPY", "VGT"}}

    def momentum(ticker):
        prior = prices[ticker].get(momentum_start)
        recent = prices[ticker].get(momentum_end)
        if not prior or not recent or prior["adj_close"] <= 0 or recent["adj_close"] <= 0:
            return None
        return recent["adj_close"] / prior["adj_close"] - 1

    controls = {ticker: momentum(ticker) for ticker in pool if ticker not in cards}
    used = set()
    cases = []
    for signal in frozen["signal_cohort"]:
        ticker = signal["ticker"]
        family = signal["family_id"]
        signal_momentum = momentum(ticker)
        eligible_controls = [other for other in controls
                             if other not in used and controls[other] is not None
                             and snapshot["candidates"][other]["family_id"] == family]
        matched = (min(eligible_controls,
                       key=lambda other: (abs(controls[other] - signal_momentum), other))
                   if signal_momentum is not None and eligible_controls else None)
        if matched:
            used.add(matched)
        cases.append({
            "ticker": ticker, "family_id": family,
            "entry_adj_close": prices[ticker].get(entry_date, {}).get("adj_close"),
            "pre_entry_21d_adjusted_return": signal_momentum,
            "control_ticker": matched,
            "control_entry_adj_close": (prices[matched].get(entry_date, {}).get("adj_close")
                                        if matched else None),
            "control_pre_entry_21d_adjusted_return": controls.get(matched),
            "status": ("entry_price_missing" if entry_date not in prices[ticker]
                       else "no_match" if matched is None
                       else "control_entry_price_missing" if entry_date not in prices[matched]
                       else "ready"),
        })
    retained_series = {ticker: [row for row in series.get(ticker, []) if row["date"] <= entry_date]
                       for ticker in sorted(prices)}
    digest = hashlib.sha256(json.dumps(retained_series, sort_keys=True,
                                       separators=(",", ":")).encode()).hexdigest()
    return {
        "schema_version": 1, "study_id": frozen["study_id"],
        "frozen_sha256": hashlib.sha256(FROZEN.read_bytes()).hexdigest(),
        "entry_date": entry_date, "observed_at_utc": observed_at.isoformat(),
        "source": "Yahoo Finance via yfinance Adj Close; auto_adjust=False; actions=True",
        "source_query_start": "2026-08-20", "source_series_sha256": digest,
        "momentum_dates": {"start": momentum_start, "end": momentum_end,
                           "sessions": 21},
        "matching": "same frozen family; nearest absolute 21-session adjusted return; "
                    "ticker alphabetical tie-break; without replacement in frozen card order",
        "benchmarks": {ticker: prices[ticker][entry_date]["adj_close"]
                       for ticker in ("SPY", "VGT")},
        "cost_sensitivity_bps_per_side": [0, 10, 25],
        "cases": cases, "source_series": retained_series,
        "outcomes_20d": None, "outcomes_60d": None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-json", type=Path, help="Existing source capture, for reproducible checks")
    args = parser.parse_args()
    frozen = json.loads(FROZEN.read_text())
    now = datetime.now(timezone.utc)
    if args.source_json:
        source = json.loads(args.source_json.read_text())
        series = source["series"]
    else:
        if now.astimezone(NEW_YORK).date() <= date.fromisoformat(frozen["frozen_at"][:10]):
            print("pending: first post-freeze US market close has not occurred")
            return
        tickers = frozen["candidate_pool"]["visible_tickers"] + ["SPY", "VGT"]
        series = fetch_prices(tickers, (now.astimezone(NEW_YORK).date() + timedelta(days=1)).isoformat())
    entry = build_entry(frozen, series, now)
    if entry is None:
        print("pending: no verified post-freeze SPY/VGT common adjusted close")
        return
    path = OUTPUT_DIR / f"entry_{entry['entry_date']}.json"
    if path.exists():
        raise SystemExit(f"Entry already frozen: {path}; refusing to overwrite")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n")
    print(f"froze {len(entry['cases'])} cases and controls: {path}")


if __name__ == "__main__":
    main()
