"""Prospective sector-state ledger; never turns C-quality replay into A outcomes."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from market_rotation_history import validate_history

ROOT = Path(__file__).resolve().parent.parent
PROTOCOL = ROOT / "market_rotation_forward_protocol.json"
OUTPUT = ROOT / "market_rotation_forward_status.json"


def read_snapshots(history_dir: Path) -> tuple[dict, list[dict]]:
    problems = validate_history(history_dir)
    if problems:
        raise ValueError("A-history integrity failed: " + "; ".join(problems))
    index = json.loads((history_dir / "index.json").read_text())
    rows = []
    for month in index["months"]:
        path = history_dir / month["path"]
        rows.extend(json.loads(line) for line in path.read_text().splitlines() if line.strip())
    return index, rows


def verify_baseline(protocol: dict, rows: list[dict]) -> None:
    matches = [row for row in rows if row["as_of"] == protocol["baseline_as_of"]]
    if len(matches) != 1:
        raise ValueError("Frozen baseline session missing or duplicated")
    baseline = matches[0]
    digest = hashlib.sha256(json.dumps(baseline, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    if digest != protocol["baseline_record_sha256"]:
        raise ValueError("Frozen baseline content changed")
    states = {key: value["confirmed_state"] for key, value in baseline["groups"].items()
              if key in protocol["sector_etfs"]}
    if states != protocol["baseline_states"]:
        raise ValueError("Frozen sector set or states changed")


def collect_events(protocol: dict, rows: list[dict], old: dict, observed_at: str) -> list[dict]:
    previous = dict(protocol["baseline_states"])
    existing = {event["id"]: event for event in old.get("events", [])}
    events = []
    for row in rows:
        if row["as_of"] <= protocol["baseline_as_of"]:
            continue
        if row["history_quality"] != "A" or row["research_rules"] != protocol["research_rules"]:
            raise ValueError("Incompatible post-freeze snapshot")
        for sector in sorted(protocol["sector_etfs"]):
            new_state = row["groups"][sector]["confirmed_state"]
            if new_state != previous[sector]:
                event_id = f"{row['as_of']}:{sector}:{new_state}"
                event = copy.deepcopy(existing[event_id]) if event_id in existing else {
                    "id": event_id, "signal_as_of": row["as_of"], "sector": sector,
                    "from_state": previous[sector], "state": new_state,
                    "etf": protocol["sector_etfs"][sector],
                    "dataset_id": row["dataset_id"], "first_seen_at_utc": observed_at,
                    "entry": {"status": "pending"},
                    "outcomes": {"20d": {"status": "pending"}, "60d": {"status": "pending"}},
                }
                if event["dataset_id"] != row["dataset_id"] or event["from_state"] != previous[sector]:
                    raise ValueError("Frozen event conflicts with A snapshot")
                if event_id in existing and "eligibility_confirmed_at_utc" not in event:
                    # The event was present in a prior committed daily run. Do not
                    # use its first observation as a same-run executable signal.
                    event["eligibility_confirmed_at_utc"] = observed_at
                events.append(event)
            previous[sector] = new_state
    if not set(existing).issubset({event["id"] for event in events}):
        raise ValueError("Previously frozen event disappeared")
    return events


def price_outcomes(event: dict, closes: pd.DataFrame) -> None:
    """Fix first eligible common-session entry; never slide past missing ETF data."""
    if event["entry"]["status"] in ("missing", "fixed"):
        pass
    elif event["entry"]["status"] == "pending":
        if "eligibility_confirmed_at_utc" not in event:
            return
        if event["etf"] not in closes or closes[event["etf"]].isna().all():
            return
        confirmed_date = datetime.fromisoformat(event["eligibility_confirmed_at_utc"].replace("Z", "+00:00"))
        confirmed_date = confirmed_date.astimezone(ZoneInfo("America/New_York")).date()
        earliest = max(confirmed_date.isoformat(), event["signal_as_of"])
        eligible = closes.loc[closes.index.strftime("%Y-%m-%d") > earliest]
        if eligible.empty:
            return
        day, row = eligible.index[0], eligible.iloc[0]
        event["entry"] = {"status": "fixed" if pd.notna(row[event["etf"]]) else "missing",
                          "date": day.strftime("%Y-%m-%d"), "etf_adj_close": None if pd.isna(row[event["etf"]]) else float(row[event["etf"]]),
                          "spy_adj_close": float(row["SPY"])}
    if event["entry"]["status"] != "fixed":
        return
    after = closes.loc[closes.index.strftime("%Y-%m-%d") >= event["entry"]["date"]]
    entry_etf, entry_spy = event["entry"]["etf_adj_close"], event["entry"]["spy_adj_close"]
    for horizon in (20, 60):
        key = f"{horizon}d"
        if event["outcomes"][key]["status"] != "pending" or len(after) <= horizon:
            continue
        path = after.iloc[1:horizon + 1]
        target = path.iloc[-1]
        if path[event["etf"]].isna().any():
            event["outcomes"][key] = {"status": "missing", "target_date": path.index[-1].strftime("%Y-%m-%d")}
            continue
        relative = (path[event["etf"]] / entry_etf - path["SPY"] / entry_spy) * 100
        event["outcomes"][key] = {
            "status": "mature", "target_date": path.index[-1].strftime("%Y-%m-%d"),
            "etf_return_pct": round((target[event["etf"]] / entry_etf - 1) * 100, 4),
            "spy_return_pct": round((target["SPY"] / entry_spy - 1) * 100, 4),
            "excess_pp": round(float(relative.iloc[-1]), 4),
            "max_adverse_excess_pp": round(float(min(0, relative.min())), 4),
        }


def build(protocol: dict, index: dict, rows: list[dict], old: dict, observed_at: str,
          closes: pd.DataFrame | None = None) -> dict:
    if old and old.get("protocol_version") != protocol["version"]:
        raise ValueError("Published forward ledger uses a different frozen protocol")
    verify_baseline(protocol, rows)
    events = collect_events(protocol, rows, old, observed_at)
    if closes is not None:
        for event in events:
            price_outcomes(event, closes)
    return {
        "schema_version": 1, "protocol_version": protocol["version"],
        "history_as_of": index["last_as_of"], "a_snapshot_count": index["snapshot_count"],
        "baseline_as_of": protocol["baseline_as_of"], "events": events,
        "event_count": len(events),
        "matured_20d": sum(event["outcomes"]["20d"]["status"] == "mature" for event in events),
        "matured_60d": sum(event["outcomes"]["60d"]["status"] == "mature" for event in events),
        "status": "results_available" if any(event["outcomes"]["20d"]["status"] == "mature" for event in events)
                  else "pending_outcomes",
    }


def fetch_prices(events: list[dict]) -> pd.DataFrame | None:
    if not events:
        return None
    import yfinance as yf
    symbols = sorted({"SPY", *(event["etf"] for event in events)})
    data = yf.download(symbols, start=min(event["signal_as_of"] for event in events),
                       auto_adjust=True, progress=False, threads=False)
    if data.empty:
        raise ValueError("Adjusted ETF prices unavailable")
    closes = data["Close"] if isinstance(data.columns, pd.MultiIndex) else data[["Close"]].rename(columns={"Close": symbols[0]})
    closes.index = pd.DatetimeIndex(closes.index).tz_localize(None)
    closes = closes.sort_index()
    if "SPY" not in closes or closes["SPY"].isna().all():
        raise ValueError("SPY reference prices unavailable")
    for symbol in symbols:
        if symbol not in closes:
            closes[symbol] = float("nan")
    return closes.loc[closes["SPY"].notna()].copy()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-dir", type=Path, default=ROOT / "market_rotation_history")
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--offline", action="store_true", help="Do not fetch prices; maintain event ledger only")
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text())
    index, rows = read_snapshots(args.history_dir)
    old = json.loads(args.output.read_text()) if args.output.exists() else {}
    observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    events = collect_events(protocol, rows, old, observed_at)
    price_source_status = "not_needed" if not events else "offline" if args.offline else "available"
    try:
        closes = None if args.offline else fetch_prices(events)
    except (ValueError, OSError, KeyError) as exc:
        print(f"::warning::Forward ETF price source unavailable ({type(exc).__name__}); events remain pending")
        closes = None
        price_source_status = "unavailable"
    result = build(protocol, index, rows, old, observed_at, closes)
    result["price_source_status"] = price_source_status
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if not args.output.exists() or args.output.read_text() != text:
        args.output.write_text(text)
    print(f"A snapshots {result['a_snapshot_count']}; prospective events {result['event_count']}; mature 20d {result['matured_20d']}, 60d {result['matured_60d']}")


if __name__ == "__main__":
    main()
