"""C-quality back-test of the market-rotation research states.

Question answered: after a sector's confirmed state switched to X, how did
the sector do versus the equal-weight market over the next 20/60/120
sessions?  Plan sections 15.2-15.12.

History quality C: today's constituents are replayed over past prices, so
companies that left the indexes are missing (survivorship bias).  Results
are for engineering checks, threshold sensitivity and sample sizes; they
are never labelled as validated.  A-quality evidence comes only from the
daily forward snapshots in market_rotation_history/.

Method (fixed before looking at results):
* states come from market_rotation_research, the same code the daily page
  uses; confirmation needs two sessions;
* an event is a confirmed-state entry after the warm-up; a re-entry into
  the same state within 10 sessions of leaving it is not independent;
* outcomes start at the confirmation session's close: sector and market
  equal-weight index levels (daily rebalanced) from t to t+h;
* excess = sector return - market return; MFE/MAE are the best/worst
  excess along the path; drawdown is the worst fall of the relative ratio
  from its running peak;
* the last ``holdout`` sessions are reported separately as out-of-sample.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from jsonio import write_json
from market_rotation_contracts import GROUP_STATES, MARKET_STATES
from market_rotation_history import universe_snapshot_id
from market_rotation_research import RULE_VERSION, by_group, state_history

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "market_rotation_history" / "backtest"
HORIZONS = (20, 60, 120)
WARMUP_SESSIONS = 150
HOLDOUT_SESSIONS = 126
REENTRY_GAP = 10
CONFIDENCE = ((60, "higher"), (30, "moderate"), (10, "exploratory"), (0, "insufficient"))


def confidence(count: int) -> str:
    return next(label for floor, label in CONFIDENCE if count >= floor)


def pct(value) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    return round(float(value) * 100, 2) + 0.0


def index_levels(daily: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    """Equal-weight index level from daily mean returns (first session = 1)."""
    return (1 + daily.fillna(0.0)).cumprod()


def outcome(sector_level: np.ndarray, market_level: np.ndarray, start: int, horizon: int) -> dict | None:
    end = start + horizon
    if end >= len(sector_level):
        return None
    sector_path = sector_level[start + 1:end + 1] / sector_level[start]
    market_path = market_level[start + 1:end + 1] / market_level[start]
    excess_path = sector_path - market_path
    ratio = np.concatenate([[1.0], sector_path / market_path])
    drawdown = ratio / np.maximum.accumulate(ratio) - 1
    return {
        "absolute": float(sector_path[-1] - 1),
        "excess": float(excess_path[-1]),
        "mfe": float(excess_path.max()),
        "mae": float(excess_path.min()),
        "max_relative_drawdown": float(drawdown.min()),
    }


def find_events(walk: pd.DataFrame, warmup: int) -> tuple[list[tuple[int, str]], int]:
    """(position, state) of independent confirmed-state entries, and skipped re-entries."""
    events, skipped = [], 0
    last_exit: dict[str, int] = {}
    previous = None
    for position, state in enumerate(walk["confirmed"]):
        state = state if isinstance(state, str) else None
        if state != previous:
            if previous is not None:
                last_exit[previous] = position
            # The first confirmed state has an unknown start: never an entry.
            if state is not None and previous is not None and position >= warmup:
                if position - last_exit.get(state, -REENTRY_GAP - 1) <= REENTRY_GAP:
                    skipped += 1
                else:
                    events.append((position, state))
            previous = state
    return events, skipped


def summarise(rows: list[dict], horizon: int) -> dict:
    values = [row[f"h{horizon}"] for row in rows if row.get(f"h{horizon}")]
    count = len(values)
    if not count:
        return {"events": 0, "confidence": confidence(0)}
    excess = np.array([v["excess"] for v in values])
    return {
        "events": count,
        "confidence": confidence(count),
        "median_excess": pct(np.median(excess)),
        "mean_excess": pct(excess.mean()),
        "win_rate": round(float((excess > 0).mean()) * 100, 1),
        "p10_excess": pct(np.percentile(excess, 10)),
        "p25_excess": pct(np.percentile(excess, 25)),
        "p75_excess": pct(np.percentile(excess, 75)),
        "median_absolute": pct(np.median([v["absolute"] for v in values])),
        "median_mfe": pct(np.median([v["mfe"] for v in values])),
        "median_mae": pct(np.median([v["mae"] for v in values])),
        "median_max_relative_drawdown": pct(np.median([v["max_relative_drawdown"] for v in values])),
    }


def durations(walks: dict[str, pd.DataFrame], warmup: int) -> dict:
    """Completed confirmed-state spells: median length and next-state shares."""
    lengths: dict[str, list[int]] = {}
    nexts: dict[str, dict[str, int]] = {}
    for walk in walks.values():
        states = [s if isinstance(s, str) else None for s in walk["confirmed"]]
        start = None
        for position in range(1, len(states)):
            if states[position] != states[position - 1]:
                if start is not None and states[position - 1] is not None:
                    lengths.setdefault(states[position - 1], []).append(position - start)
                    bucket = nexts.setdefault(states[position - 1], {})
                    bucket[states[position]] = bucket.get(states[position], 0) + 1
                start = position if position >= warmup else None
    result = {}
    for state, spells in sorted(lengths.items()):
        total = sum(nexts[state].values())
        result[state] = {
            "completed_spells": len(spells),
            "median_sessions": float(np.median(spells)),
            "next_state_share": {k: round(v / total * 100, 1) for k, v in sorted(nexts[state].items())},
        }
    return result


def forward_excess(levels: np.ndarray, market: np.ndarray, horizon: int) -> np.ndarray:
    """Sessions x groups: group return minus market return from t to t+h (NaN past the end)."""
    result = np.full(levels.shape, np.nan)
    result[:-horizon] = levels[horizon:] / levels[:-horizon] - (market[horizon:] / market[:-horizon])[:, None]
    return result


def in_sample(position: int, horizon: int, sample: str, holdout_start: int, total: int) -> bool:
    """Calibration outcomes must end before the holdout starts, so no holdout price informs them."""
    if sample == "calibration":
        return position + horizon < holdout_start
    if sample == "holdout":
        return position >= holdout_start and position + horizon < total
    return position + horizon < total


def collect_events(history: dict, dates: pd.DatetimeIndex, warmup: int, holdout_start: int) -> tuple[list, int]:
    panel = history["panel"]
    sector_levels = index_levels(by_group(panel.daily, panel.metadata["sector"]))
    market_level = index_levels(history["market"]["market_daily"]).to_numpy()
    market_confirmed = history["market_walk"]["confirmed"]
    events, skipped = [], 0
    for sector, walk in sorted(history["sector_walks"].items()):
        found, missed = find_events(walk, warmup)
        skipped += missed
        level = sector_levels[sector].to_numpy()
        for position, state in found:
            env = market_confirmed.iloc[position]
            row = {"date": dates[position].strftime("%Y-%m-%d"), "position": position, "sector": sector,
                   "state": state, "market_state": env if isinstance(env, str) else None,
                   "sample": "holdout" if position >= holdout_start else "calibration"}
            for horizon in HORIZONS:
                row[f"h{horizon}"] = outcome(level, market_level, position, horizon)
            events.append(row)
    return events, skipped


def baseline_excess(history: dict, warmup: int, holdout_start: int, horizon: int, sample: str,
                    market_filter: str | None = None) -> np.ndarray:
    """Every eligible sector-day's forward excess: what a state must beat to carry information."""
    panel = history["panel"]
    levels = index_levels(by_group(panel.daily, panel.metadata["sector"])).to_numpy()
    market = index_levels(history["market"]["market_daily"]).to_numpy()
    excess = forward_excess(levels, market, horizon)
    total = len(levels)
    rows = [position for position in range(warmup, total)
            if in_sample(position, horizon, sample, holdout_start, total)]
    if market_filter:
        confirmed = history["market_walk"]["confirmed"].to_numpy()
        rows = [position for position in rows if confirmed[position] == market_filter]
    values = excess[rows].ravel()
    return values[np.isfinite(values)]


def run_backtest(closes: pd.DataFrame, volumes: pd.DataFrame, metadata: pd.DataFrame,
                 warmup: int = WARMUP_SESSIONS, holdout: int = HOLDOUT_SESSIONS,
                 history: dict | None = None) -> dict:
    dates = closes.index
    if len(dates) < warmup + max(HORIZONS) + 20:
        raise ValueError(f"need at least {warmup + max(HORIZONS) + 20} sessions, found {len(dates)}")
    history = history or state_history(closes, volumes, metadata)
    holdout_start = len(dates) - holdout
    events, skipped = collect_events(history, dates, warmup, holdout_start)

    def split(rows, horizon, sample):
        return [e for e in rows if in_sample(e["position"], horizon, sample, holdout_start, len(dates))]

    by_state = {}
    for state in GROUP_STATES:
        rows = [e for e in events if e["state"] == state]
        if not rows:
            continue
        by_state[state] = {
            "all": {f"{h}d": summarise(rows, h) for h in HORIZONS},
            "calibration": {f"{h}d": summarise(split(rows, h, "calibration"), h) for h in HORIZONS},
            "holdout": {f"{h}d": summarise(split(rows, h, "holdout"), h) for h in HORIZONS},
            "by_market_state": {
                env: summarise([e for e in rows if e["market_state"] == env], 60)
                for env in MARKET_STATES if any(e["market_state"] == env for e in rows)
            },
        }

    baseline = {}
    for horizon in HORIZONS:
        values = baseline_excess(history, warmup, holdout_start, horizon, "all")
        baseline[f"{horizon}d"] = {"sector_days": len(values), "median_excess": pct(np.median(values)),
                                   "win_rate": round(float((values > 0).mean()) * 100, 1)}

    def compact(event):
        return {**{k: event[k] for k in ("date", "sector", "state", "market_state", "sample")},
                **{f"excess_{h}d": pct(event[f"h{h}"]["excess"]) if event[f"h{h}"] else None for h in HORIZONS}}

    return {
        "period": {"start": dates[0].strftime("%Y-%m-%d"), "end": dates[-1].strftime("%Y-%m-%d"),
                   "sessions": len(dates), "evaluation_start": dates[warmup].strftime("%Y-%m-%d"),
                   "holdout_start": dates[holdout_start].strftime("%Y-%m-%d")},
        "event_count": len(events),
        "reentries_not_counted": skipped,
        "by_state": by_state,
        "unconditional": baseline,
        "durations": durations(history["sector_walks"], warmup),
        "events": [compact(e) for e in events],
    }


# Candidate variants are frozen here before any result is seen (plan 15.10):
# adding one later needs a new SENSITIVITY_VERSION, and every result -- also
# the failures -- is published.
SENSITIVITY_VERSION = "sensitivity-1"
VARIANTS = (
    {"id": "baseline", "label": "目前規則：合併股票池、連續 2 日確認",
     "universe": None, "confirm": 2, "market_filter": None},
    {"id": "confirm3", "label": "連續 3 日才確認（延遲換取較少假訊號？）",
     "universe": None, "confirm": 3, "market_filter": None},
    {"id": "sp500", "label": "只用 S&P 500 成分與基準（計畫第 16.3 節）",
     "universe": "S&P 500", "confirm": 2, "market_filter": None},
    {"id": "expansion_only", "label": "只在市場「廣泛擴張」時使用狀態訊號",
     "universe": None, "confirm": 2, "market_filter": "broad_expansion"},
)
PRIMARY_HORIZON = 60
MIN_EVENTS = 30
MIN_HOLDOUT_EVENTS = 5
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20260927


def bootstrap_interval(values: np.ndarray, reference: float) -> tuple[float, float] | None:
    """90% interval of median(values) - reference, resampling independent events."""
    if len(values) < 2:
        return None
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws = rng.choice(values, size=(BOOTSTRAP_DRAWS, len(values)), replace=True)
    medians = np.median(draws, axis=1) - reference
    return float(np.percentile(medians, 5)), float(np.percentile(medians, 95))


def state_excess(events: list[dict], state: str, horizon: int, sample: str, holdout_start: int, total: int,
                 market_filter: str | None) -> np.ndarray:
    values = [e[f"h{horizon}"]["excess"] for e in events
              if e["state"] == state and e[f"h{horizon}"]
              and in_sample(e["position"], horizon, sample, holdout_start, total)
              and (market_filter is None or e["market_state"] == market_filter)]
    return np.array(values)


def evaluate_variant(history: dict, dates: pd.DatetimeIndex, variant: dict, warmup: int, holdout: int) -> dict:
    holdout_start = len(dates) - holdout
    events, _ = collect_events(history, dates, warmup, holdout_start)
    flt = variant["market_filter"]
    samples = {}
    for sample in ("calibration", "holdout"):
        block = {}
        for horizon in HORIZONS:
            base = baseline_excess(history, warmup, holdout_start, horizon, sample, flt)
            lead = state_excess(events, "confirmed_leading", horizon, sample, holdout_start, len(dates), flt)
            lag = state_excess(events, "clear_lagging", horizon, sample, holdout_start, len(dates), flt)
            base_median = float(np.median(base)) if len(base) else None
            row = {
                "baseline_sector_days": len(base),
                "baseline_median": pct(base_median),
                "baseline_p10": pct(np.percentile(base, 10)) if len(base) else None,
                "leading_events": len(lead),
                "leading_median": pct(np.median(lead)) if len(lead) else None,
                "leading_p10": pct(np.percentile(lead, 10)) if len(lead) else None,
                "lagging_events": len(lag),
                "lagging_median": pct(np.median(lag)) if len(lag) else None,
            }
            row["leading_edge_pp"] = (round(row["leading_median"] - row["baseline_median"], 2)
                                      if len(lead) and base_median is not None else None)
            row["lagging_edge_pp"] = (round(row["baseline_median"] - row["lagging_median"], 2)
                                      if len(lag) and base_median is not None else None)
            if sample == "calibration" and horizon == PRIMARY_HORIZON:
                interval = bootstrap_interval(lead, base_median) if base_median is not None else None
                row["leading_edge_interval_pp"] = [pct(v) for v in interval] if interval else None
            block[f"{horizon}d"] = row
        samples[sample] = block
    return {**{k: variant[k] for k in ("id", "label")}, "samples": samples,
            **judge(samples)}


def judge(samples: dict) -> dict:
    """Plan 15.11 conditions that a price back-test can check; never adopts a rule by itself."""
    cal = samples["calibration"][f"{PRIMARY_HORIZON}d"]
    hold = samples["holdout"][f"{PRIMARY_HORIZON}d"]
    positive = lambda value: value is not None and value > 0  # noqa: E731
    enough_holdout = hold["leading_events"] >= MIN_HOLDOUT_EVENTS and hold["lagging_events"] >= MIN_HOLDOUT_EVENTS
    interval = cal.get("leading_edge_interval_pp")
    horizons = sum(positive(samples["calibration"][f"{h}d"]["leading_edge_pp"]) for h in HORIZONS)
    criteria = {
        "enough_events": cal["leading_events"] >= MIN_EVENTS and cal["lagging_events"] >= MIN_EVENTS,
        "expected_direction": positive(cal["leading_edge_pp"]) and positive(cal["lagging_edge_pp"]),
        "holds_out_of_sample": (positive(hold["leading_edge_pp"]) and positive(hold["lagging_edge_pp"])
                                if enough_holdout else None),
        "downside_not_worse": (cal["leading_p10"] is not None and cal["baseline_p10"] is not None
                               and cal["leading_p10"] >= cal["baseline_p10"]),
        "interval_excludes_zero": bool(interval and interval[0] is not None and interval[0] > 0),
        "more_than_one_horizon": horizons >= 2,
    }
    if not criteria["enough_events"]:
        verdict = "insufficient_sample"
    elif not criteria["expected_direction"]:
        verdict = "not_supported"
    elif all(value is True for value in criteria.values()):
        verdict = "supported_pending_a_b_history"
    else:
        verdict = "partial_not_adoptable"
    return {"criteria": criteria, "verdict": verdict}


def run_sensitivity(closes: pd.DataFrame, volumes: pd.DataFrame, metadata: pd.DataFrame,
                    warmup: int = WARMUP_SESSIONS, holdout: int = HOLDOUT_SESSIONS,
                    baseline_history: dict | None = None) -> dict:
    results = []
    for variant in VARIANTS:
        if variant["universe"]:
            members = [t for t in closes.columns if variant["universe"] in metadata.loc[t, "indexes"]]
            data = (closes[members], volumes[members], metadata.loc[members])
        else:
            data = (closes, volumes, metadata)
        reuse = baseline_history if (variant["universe"] is None and variant["confirm"] == 2) else None
        history = reuse or state_history(*data, confirm_sessions=variant["confirm"])
        results.append(evaluate_variant(history, closes.index, variant, warmup, holdout))
    return {
        "version": SENSITIVITY_VERSION,
        "primary_horizon_sessions": PRIMARY_HORIZON,
        "compared_states": ["confirmed_leading", "clear_lagging"],
        "edge_definition": "leading: state median excess minus the same sample's all-sector-day median; "
                           "lagging: all-sector-day median minus the state median (positive = the state "
                           "separates as expected)",
        "sample_rule": f"calibration outcomes end before the last {holdout} sessions; holdout entries start "
                       "inside them",
        "bootstrap": {"draws": BOOTSTRAP_DRAWS, "seed": BOOTSTRAP_SEED, "interval": "5th-95th percentile"},
        "verdicts": {
            "supported_pending_a_b_history": "價格回測條件都符合；仍須在 A／B 級歷史重現才可採用",
            "partial_not_adoptable": "方向符合，但樣本外、下行風險、區間或期間一致性至少一項未通過",
            "not_supported": "校準期方向就不符合預期",
            "insufficient_sample": "事件數不足",
        },
        "variants": results,
    }


def methodology(universe: dict, rule_version: str) -> dict:
    return {
        "history_quality": "C",
        "history_quality_meaning": "current-constituent approximation: today's S&P 500 + Nasdaq-100 members "
                                   "replayed over past prices; survivorship bias; not a validated result",
        "status": "research",
        "rule_version": rule_version,
        "universe_snapshot_id": universe_snapshot_id(universe),
        "group_level": "sector",
        "benchmark": "combined-universe equal-weight index, daily rebalanced",
        "horizons_sessions": list(HORIZONS),
        "warmup_sessions": WARMUP_SESSIONS,
        "holdout_sessions": HOLDOUT_SESSIONS,
        "reentry_gap_sessions": REENTRY_GAP,
        "event": "confirmed-state entry (two-session confirmation); outcomes from the confirmation close",
        "confidence_by_events": {label: floor for floor, label in CONFIDENCE},
        "adoption": "a state may drop the research label only after the plan's section 15.11 conditions hold "
                    "on B- or A-quality history",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--universe", type=Path, default=ROOT / "market_rotation_universe.json")
    parser.add_argument("--registry", type=Path, default=ROOT / "market_rotation_registry.json")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--days", type=int, default=1900, help="calendar days of prices to download")
    args = parser.parse_args()

    import build_market_rotation as builder  # noqa: PLC0415  (pulls yfinance; CI only)

    universe = json.loads(args.universe.read_text())
    end = date.today() + timedelta(days=1)
    tickers = [row["yahoo_ticker"] for row in universe["members"]]
    print(f"Fetching {len(tickers)} securities for {args.days} days...")
    closes, volumes = builder.fetch_market_data(tickers, end - timedelta(days=args.days), end)
    closes, volumes, metadata, unavailable = builder.prepare_market_data(universe, closes, volumes)
    history = state_history(closes, volumes, metadata)
    result = run_backtest(closes, volumes, metadata, history=history)
    sensitivity = run_sensitivity(closes, volumes, metadata, baseline_history=history)
    registry = json.loads(args.registry.read_text())
    ids = {row["name_en"]: row["group_id"] for row in registry["groups"] if row["group_type"] == "sector"}
    for event in result["events"]:
        event["group_id"] = ids.get(event["sector"])
    payload = {
        "schema_version": 1,
        "generated_at": builder.utc_now(),
        "methodology": methodology(universe, RULE_VERSION),
        "coverage": {"priced_securities": len(closes.columns), "unavailable_tickers": unavailable},
        **result,
    }
    write_json(args.output_dir / "sector_results.json", payload, indent=None)
    write_json(args.output_dir / "sensitivity.json", {
        "schema_version": 1, "generated_at": payload["generated_at"], "methodology": payload["methodology"],
        "period": result["period"], **sensitivity}, indent=1)
    for variant in sensitivity["variants"]:
        print(f"  {variant['id']}: {variant['verdict']}")
    print(f"Back-test {result['period']['start']}..{result['period']['end']}: {result['event_count']} events "
          f"({result['reentries_not_counted']} re-entries not counted)")


if __name__ == "__main__":
    sys.exit(main())
