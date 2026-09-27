"""Monthly medium-term momentum across the SPDR sector ETFs.

The research states in market_rotation_research use 20/60-session windows
and showed almost no predictive power.  The academic evidence for industry
momentum (Moskowitz & Grinblatt 1999) is at 6-12 month look-backs held for
months, so this back-test asks the question at that horizon, on the ETFs
themselves:

* every month-end, rank the sector ETFs that already existed by their
  return from 12 (or 6) months ago to 1 month ago, and hold the top 3
  equally until the next rebalance;
* compare with holding every available sector ETF equally, and with SPY;
* charge 0.10% of every dollar traded.

The ETF price series are real, investable and complete (no sector SPDR has
closed), so unlike the constituent replay there is no survivorship bias in
the tested set.  The variants and the judging rules are frozen below
before any result is seen; returns from 2016 onward are the holdout.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from jsonio import write_json

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "market_rotation_history" / "backtest" / "sector_etf_momentum.json"
SECTOR_ETFS = {
    "XLB": "Materials", "XLC": "Communication Services", "XLE": "Energy", "XLF": "Financials",
    "XLI": "Industrials", "XLK": "Information Technology", "XLP": "Consumer Staples",
    "XLRE": "Real Estate", "XLU": "Utilities", "XLV": "Health Care", "XLY": "Consumer Discretionary",
}
MARKET = "SPY"
RISK_FREE = "^IRX"
START = "1998-12-01"
HOLDOUT_START = "2016-01"
TOP_N = 3
MIN_ELIGIBLE = 6
COST_PER_DOLLAR_TRADED = 0.001
MOMENTUM_VERSION = "etf-momentum-1"
VARIANTS = (
    {"id": "m12_1_monthly", "label": "12 減 1 個月動能，每月調整（主要）", "lookback": 12, "rebalance": 1,
     "absolute_filter": False},
    {"id": "m6_1_monthly", "label": "6 減 1 個月動能，每月調整", "lookback": 6, "rebalance": 1,
     "absolute_filter": False},
    {"id": "m12_1_quarterly", "label": "12 減 1 個月動能，每季調整", "lookback": 12, "rebalance": 3,
     "absolute_filter": False},
    {"id": "m12_1_absolute", "label": "12 減 1 個月動能，每月調整，輸給國庫券就改持有全部等權", "lookback": 12,
     "rebalance": 1, "absolute_filter": True},
)
# NBER business-cycle reference dates (peak month to trough month), used only
# to split results; https://www.nber.org/research/data/us-business-cycle-expansions-and-contractions
RECESSIONS = (("2001-03", "2001-11"), ("2007-12", "2009-06"), ("2020-02", "2020-04"))
BLOCK_MONTHS = 12
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 20260927


def momentum_scores(prices: pd.DataFrame, position: int, lookback: int) -> pd.Series:
    """Return from ``lookback`` months ago to 1 month ago, for ETFs priced at every point used."""
    if position - lookback < 0:
        return pd.Series(dtype=float)
    now, then, current = prices.iloc[position - 1], prices.iloc[position - lookback], prices.iloc[position]
    valid = now.notna() & then.notna() & current.notna()
    return (now[valid] / then[valid] - 1).sort_index()


def select(scores: pd.Series, rf_window: float | None, absolute: bool) -> list[str]:
    """Top N by score (ticker breaks ties); the absolute filter swaps weak picks for the whole set."""
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    picks = [ticker for ticker, _ in ranked[:TOP_N]]
    if absolute and rf_window is not None and any(scores[t] <= rf_window for t in picks):
        return sorted(scores.index)
    return picks


def simulate(prices: pd.DataFrame, rf_monthly: pd.Series, variant: dict) -> pd.DataFrame:
    """Monthly rows: the return earned over the month that ends at each date, and what was held."""
    returns = prices.pct_change(fill_method=None)
    rows, weights, held = [], pd.Series(dtype=float), []
    for position in range(len(prices) - 1):
        scores = momentum_scores(prices, position, variant["lookback"])
        rebalance = position % variant["rebalance"] == 0 or not held
        if len(scores) >= MIN_ELIGIBLE and rebalance:
            window = rf_monthly.iloc[position - variant["lookback"] + 1:position]
            rf_window = float(np.prod(1 + window) - 1) if len(window) else None
            held = select(scores, rf_window, variant["absolute_filter"])
            target = pd.Series(1 / len(held), index=held)
            traded = target.subtract(weights, fill_value=0).abs().sum()
            weights = target
        elif not held:
            continue
        else:
            traded = 0.0
        nxt = returns.iloc[position + 1]
        available = [t for t in prices.columns if pd.notna(prices.iloc[position][t]) and pd.notna(nxt[t])]
        if not available or any(t not in available for t in held):
            continue
        strategy = float((nxt[held] * weights[held]).sum()) - traded * COST_PER_DOLLAR_TRADED
        rows.append({"month": prices.index[position + 1].strftime("%Y-%m"), "strategy": strategy,
                     "equal_weight": float(nxt[available].mean()), "held": list(held),
                     "traded": float(traded)})
    return pd.DataFrame(rows)


def max_drawdown(monthly: pd.Series) -> float:
    level = (1 + monthly).cumprod()
    return float((level / level.cummax() - 1).min())


def block_bootstrap_mean(values: np.ndarray) -> tuple[float, float] | None:
    """90% interval of the mean monthly excess, resampling 12-month blocks (serial correlation)."""
    if len(values) < BLOCK_MONTHS * 2:
        return None
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    blocks = len(values) // BLOCK_MONTHS
    starts = rng.integers(0, len(values) - BLOCK_MONTHS + 1, size=(BOOTSTRAP_DRAWS, blocks))
    means = values[starts[:, :, None] + np.arange(BLOCK_MONTHS)].reshape(BOOTSTRAP_DRAWS, -1).mean(axis=1)
    return float(np.percentile(means, 5)), float(np.percentile(means, 95))


def pct(value, digits: int = 2):
    return None if value is None or not np.isfinite(value) else round(float(value) * 100, digits) + 0.0


def statistics(frame: pd.DataFrame, spy: pd.Series | None = None) -> dict:
    if frame.empty:
        return {"months": 0}
    excess = frame["strategy"] - frame["equal_weight"]
    years = len(frame) / 12
    cagr = lambda series: float((1 + series).prod() ** (1 / years) - 1)  # noqa: E731
    tracking = float(excess.std(ddof=1) * np.sqrt(12)) if len(frame) > 1 else None
    result = {
        "months": len(frame), "start": frame["month"].iloc[0], "end": frame["month"].iloc[-1],
        "strategy_cagr": pct(cagr(frame["strategy"])),
        "equal_weight_cagr": pct(cagr(frame["equal_weight"])),
        "excess_cagr_pp": pct(cagr(frame["strategy"]) - cagr(frame["equal_weight"])),
        "mean_monthly_excess_pp": pct(excess.mean(), 3),
        "tracking_error": pct(tracking),
        "information_ratio": (round(float(excess.mean() * 12 / tracking), 2) if tracking else None),
        "hit_rate": round(float((excess > 0).mean()) * 100, 1),
        "strategy_max_drawdown": pct(max_drawdown(frame["strategy"])),
        "equal_weight_max_drawdown": pct(max_drawdown(frame["equal_weight"])),
        "annual_turnover": round(float(frame["traded"].sum() / years), 2),
    }
    if spy is not None:
        aligned = spy.reindex(frame["month"]).to_numpy()
        if np.isfinite(aligned).all():
            result["spy_cagr"] = pct(float((1 + aligned).prod() ** (1 / years) - 1))
    return result


def in_recession(month: str) -> bool:
    return any(start <= month <= end for start, end in RECESSIONS)


def judge(calibration: dict, holdout: dict, interval: tuple[float, float] | None) -> dict:
    positive = lambda value: value is not None and value > 0  # noqa: E731
    criteria = {
        "calibration_beats_equal_weight": positive(calibration.get("excess_cagr_pp"))
        and positive(calibration.get("information_ratio")),
        "holdout_beats_equal_weight": positive(holdout.get("excess_cagr_pp"))
        and positive(holdout.get("information_ratio")),
        "interval_excludes_zero": bool(interval and interval[0] > 0),
        "drawdown_not_much_worse": (calibration.get("strategy_max_drawdown") is not None
                                    and calibration["strategy_max_drawdown"]
                                    >= calibration["equal_weight_max_drawdown"] - 5),
    }
    if not criteria["calibration_beats_equal_weight"]:
        verdict = "not_supported"
    elif all(criteria.values()):
        verdict = "supported"
    else:
        verdict = "partial"
    return {"criteria": criteria, "verdict": verdict}


def evaluate(prices: pd.DataFrame, rf_monthly: pd.Series, spy: pd.Series, variant: dict) -> dict:
    frame = simulate(prices, rf_monthly, variant)
    calibration = frame[frame["month"] < HOLDOUT_START]
    holdout = frame[frame["month"] >= HOLDOUT_START]
    excess = (calibration["strategy"] - calibration["equal_weight"]).to_numpy()
    interval = block_bootstrap_mean(excess)
    regimes = {
        "recession": statistics(frame[frame["month"].map(in_recession)]),
        "expansion": statistics(frame[~frame["month"].map(in_recession)]),
    }
    return {
        **{key: variant[key] for key in ("id", "label", "lookback", "rebalance", "absolute_filter")},
        "all": statistics(frame, spy),
        "calibration": statistics(calibration, spy),
        "holdout": statistics(holdout, spy),
        "calibration_mean_excess_interval_pp": [pct(v, 3) for v in interval] if interval else None,
        "by_business_cycle": {name: {k: stats.get(k) for k in ("months", "mean_monthly_excess_pp", "hit_rate")}
                              for name, stats in regimes.items()},
        **judge(statistics(calibration), statistics(holdout), interval),
    }


def latest_ranking(prices: pd.DataFrame, lookback: int = 12) -> dict:
    """Ranking at the last completed month-end (shown only for transparency)."""
    position = len(prices) - 1
    scores = momentum_scores(prices, position, lookback)
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return {"as_of": prices.index[position].strftime("%Y-%m-%d"), "lookback_months": lookback,
            "rows": [{"ticker": t, "sector": SECTOR_ETFS.get(t, t), "momentum_pct": pct(s),
                      "rank": rank} for rank, (t, s) in enumerate(ranked, start=1)]}


def run(prices: pd.DataFrame, rf_monthly: pd.Series, spy: pd.Series) -> dict:
    return {
        "version": MOMENTUM_VERSION,
        "status": "research",
        "history_quality": "etf_prices",
        "history_quality_meaning": "actual sector ETF total-return series (Adj Close); every tested ETF still "
                                   "trades, so the tested set has no survivorship bias; ETFs enter the ranking "
                                   "only once they have a full look-back",
        "method": {
            "top_n": TOP_N, "minimum_eligible_etfs": MIN_ELIGIBLE,
            "cost_per_dollar_traded": COST_PER_DOLLAR_TRADED,
            "benchmark": "equal weight of every sector ETF priced that month, rebalanced monthly",
            "holdout_from": HOLDOUT_START, "bootstrap": {"block_months": BLOCK_MONTHS, "draws": BOOTSTRAP_DRAWS,
                                                         "seed": BOOTSTRAP_SEED, "interval": "5th-95th"},
            "recessions": [list(r) for r in RECESSIONS],
        },
        "verdicts": {
            "supported": "校準期與樣本外都勝過等權，區間不含 0，回撤沒有明顯更差",
            "partial": "校準期勝過等權，但樣本外、區間或回撤至少一項未通過",
            "not_supported": "校準期就沒有勝過等權",
        },
        "variants": [evaluate(prices, rf_monthly, spy, variant) for variant in VARIANTS],
        "latest_ranking": latest_ranking(prices),
    }


def monthly(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.resample("ME").last()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    import yfinance as yf  # noqa: PLC0415  (CI only)

    tickers = sorted(SECTOR_ETFS) + [MARKET]
    data = yf.download(tickers, start=START, end=date.today().isoformat(), interval="1d",
                       auto_adjust=False, actions=False, group_by="column", progress=False, threads=True)
    closes = monthly(data["Adj Close"][tickers])
    # Drop the current, unfinished month: rankings use completed month-ends only.
    if closes.index[-1].to_period("M") == pd.Timestamp(date.today()).to_period("M"):
        closes = closes.iloc[:-1]
    irx = yf.download(RISK_FREE, start=START, end=date.today().isoformat(), interval="1d",
                      auto_adjust=False, actions=False, progress=False)["Close"]
    irx = irx.iloc[:, 0] if isinstance(irx, pd.DataFrame) else irx
    # ^IRX is the 13-week T-bill rate in percent per year; one month earns about a twelfth of it.
    rf_monthly = irx.resample("ME").last().reindex(closes.index).ffill() / 100 / 12
    prices = closes[sorted(SECTOR_ETFS)]
    spy = closes[MARKET].pct_change(fill_method=None)
    spy.index = spy.index.strftime("%Y-%m")
    result = run(prices, rf_monthly, spy)
    result["generated_at"] = pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")
    result["period"] = {"first_month": closes.index[0].strftime("%Y-%m"),
                        "last_month": closes.index[-1].strftime("%Y-%m")}
    write_json(args.output, result, indent=1)
    for variant in result["variants"]:
        print(f"  {variant['id']}: {variant['verdict']} | calibration excess "
              f"{variant['calibration'].get('excess_cagr_pp')}pp, holdout {variant['holdout'].get('excess_cagr_pp')}pp")


if __name__ == "__main__":
    sys.exit(main())
