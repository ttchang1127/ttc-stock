"""Do theme-ETF signals rank next month's winners?  A point-in-time back-test.

Every month-end the research ETFs (the frozen ``etf_holdings.THEME_ETFS``) are
ranked by each frozen signal below, and the ranking is compared with the
next month's return relative to the equal-weight average of the ETFs
available that month (rank correlation, "IC").  A signal that works shows a
positive mean IC both in the calibration years and in the holdout that
follows them.

Signals (frozen under ``SIGNAL_VERSION`` before any result is seen):

* price momentum 12-1 and 6-1 months: the A1 test on sector ETFs found no
  stable edge; industry/theme ETFs disperse more, so it is asked again here;
* constituent breadth: share of holdings above their 50-session average;
* participation: equal- minus cap-weighted 20-session constituent return;
* N-PORT net flows: the last three reported months of creations minus
  redemptions over net assets.  The sign is not assumed: flows are often
  read as contrarian.

Point in time: constituent weights and flows come from the N-PORT filing
with the latest *filing* date on or before the month-end
(``etf_holdings/history/``), so nothing is used before it was public.  Price
signals run from 2007; holdings signals only from the first archived
N-PORT (about 2019).  Limits, all stated in the output: the ETF list was
chosen in 2026 among funds that still exist; constituents that have since
delisted may have no price, which lowers coverage (months under 70%
coverage are skipped); results are research, not a trading rule.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

import etf_holdings
from backtest_sector_etf_momentum import BLOCK_MONTHS, block_bootstrap_mean
from jsonio import load_json, write_json

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "market_rotation_history" / "backtest" / "theme_etf_signals.json"
HISTORY_DIR = ROOT / "etf_holdings" / "history"
SIGNAL_VERSION = "theme-signals-1"
PRICE_START = "2006-01-01"
PRICE_HOLDOUT_START = "2016-01"
HOLDINGS_HOLDOUT_START = "2023-01"
MIN_ETFS = 6
MIN_COVERAGE_PCT = 70.0
MIN_CALIBRATION_MONTHS = 24
SIGNALS = (
    {"id": "momentum_12_1", "label": "價格動能：12 減 1 個月", "source": "price", "expected_sign": 1},
    {"id": "momentum_6_1", "label": "價格動能：6 減 1 個月", "source": "price", "expected_sign": 1},
    {"id": "breadth_50", "label": "成分廣度：站上 50 日均線比例", "source": "holdings", "expected_sign": 1},
    {"id": "participation_20", "label": "參與度：等權減市值加權 20 日報酬", "source": "holdings",
     "expected_sign": 1},
    {"id": "nport_flow_3m", "label": "N-PORT 近三個月淨申購占淨資產", "source": "holdings", "expected_sign": None},
)
VERDICTS = {
    "supported": "校準期與樣本外方向一致且區間不含 0",
    "partial_not_adoptable": "校準期有訊號，但樣本外不成立或樣本不足",
    "not_supported": "校準期就沒有穩定訊號",
    "insufficient_sample": "樣本不足，不做判定",
}


def pct(value, digits: int = 2):
    return None if value is None or not np.isfinite(value) else round(float(value) * 100, digits) + 0.0


def month_label(index: pd.DatetimeIndex) -> list[str]:
    return [stamp.strftime("%Y-%m") for stamp in index]


def forward_relative(monthly: pd.DataFrame) -> pd.DataFrame:
    """Next month's return minus the equal-weight mean of the ETFs priced in both months."""
    returns = monthly.pct_change(fill_method=None).shift(-1)
    return returns.sub(returns.mean(axis=1), axis=0)


def momentum(monthly: pd.DataFrame, lookback: int, skip: int = 1) -> pd.DataFrame:
    return monthly.shift(skip) / monthly.shift(lookback) - 1


def filing_at(history: dict | None, when: pd.Timestamp) -> dict | None:
    """The filing with the latest filing date on or before ``when``."""
    public = [row for row in (history or {}).get("filings", []) if row["filed"] <= when.date().isoformat()]
    return max(public, key=lambda row: (row["filed"], row["report_date"])) if public else None


def holdings_signals(histories: dict[str, dict], daily: pd.DataFrame,
                     month_ends: pd.DatetimeIndex) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Breadth, participation and flow signals per month-end, and the coverage behind them."""
    daily = daily.sort_index()
    ma50 = daily.rolling(50, min_periods=50).mean()
    r20 = daily / daily.shift(20) - 1
    tickers = sorted(histories)
    frames = {name: pd.DataFrame(np.nan, index=month_ends, columns=tickers)
              for name in ("breadth_50", "participation_20", "nport_flow_3m")}
    coverage = pd.DataFrame(np.nan, index=month_ends, columns=tickers)
    for month_end in month_ends:
        sessions = daily.index[daily.index <= month_end]
        if not len(sessions):
            continue
        day = sessions[-1]
        for ticker in tickers:
            filing = filing_at(histories[ticker], month_end)
            if filing is None:
                continue
            flows = [row["net_usd"] for row in filing.get("monthly_flows", []) if row.get("net_usd") is not None]
            if len(flows) == 3 and filing.get("net_assets_usd"):
                frames["nport_flow_3m"].at[month_end, ticker] = sum(flows) / filing["net_assets_usd"]
            weights = pd.Series(filing["weights"], dtype=float)
            weights = weights[weights.index.isin(daily.columns)]
            if weights.empty:
                coverage.at[month_end, ticker] = 0.0
                continue
            close, average, change = daily.loc[day, weights.index], ma50.loc[day, weights.index], r20.loc[day, weights.index]
            priced = close.notna() & average.notna() & change.notna()
            total = filing.get("equity_weight_pct") or float(pd.Series(filing["weights"]).sum())
            covered = float(weights[priced].sum() / total * 100) if total else 0.0
            coverage.at[month_end, ticker] = covered
            if covered < MIN_COVERAGE_PCT or priced.sum() < 10:
                continue
            w = weights[priced] / weights[priced].sum()
            frames["breadth_50"].at[month_end, ticker] = float((close[priced] > average[priced]).mean())
            frames["participation_20"].at[month_end, ticker] = float(change[priced].mean() - (w * change[priced]).sum())
    return frames, coverage


def monthly_ic(signal: pd.DataFrame, outcome: pd.DataFrame) -> pd.Series:
    rows = {}
    for month in signal.index.intersection(outcome.index):
        pair = pd.concat([signal.loc[month], outcome.loc[month]], axis=1, keys=["s", "o"]).dropna()
        if len(pair) >= MIN_ETFS and pair["s"].nunique() > 1 and pair["o"].nunique() > 1:
            rows[month] = pair["s"].rank().corr(pair["o"].rank())
    return pd.Series(rows, dtype=float).sort_index()


def top_minus_average(signal: pd.DataFrame, outcome: pd.DataFrame, top: int = 3) -> pd.Series:
    """Mean next-month relative return of the top-ranked ETFs (already relative to the equal-weight mean)."""
    rows = {}
    for month in signal.index.intersection(outcome.index):
        pair = pd.concat([signal.loc[month], outcome.loc[month]], axis=1, keys=["s", "o"]).dropna()
        if len(pair) >= MIN_ETFS:
            rows[month] = float(pair.nlargest(top, "s")["o"].mean())
    return pd.Series(rows, dtype=float).sort_index()


def summarise(ic: pd.Series, spread: pd.Series) -> dict:
    if ic.empty:
        return {"months": 0}
    values = ic.to_numpy()
    std = float(values.std(ddof=1)) if len(values) > 1 else None
    interval = block_bootstrap_mean(values)
    return {
        "months": int(len(values)),
        "start": ic.index[0].strftime("%Y-%m"),
        "end": ic.index[-1].strftime("%Y-%m"),
        "mean_ic": round(float(values.mean()), 3),
        "t_stat": round(float(values.mean() / std * np.sqrt(len(values))), 2) if std else None,
        "positive_months_pct": pct(float((values > 0).mean()), 1),
        "mean_ic_interval": [round(interval[0], 3), round(interval[1], 3)] if interval else None,
        "top3_minus_average_pp": pct(float(spread.reindex(ic.index).mean()), 3) if not spread.empty else None,
    }


def judge(calibration: dict, holdout: dict, expected_sign: int | None) -> tuple[str, dict]:
    if calibration.get("months", 0) < MIN_CALIBRATION_MONTHS or not calibration.get("mean_ic_interval"):
        return "insufficient_sample", {}
    low, high = calibration["mean_ic_interval"]
    sign = expected_sign if expected_sign is not None else (1 if calibration["mean_ic"] > 0 else -1)
    criteria = {
        "calibration_interval_excludes_zero": bool(low > 0 if sign > 0 else high < 0),
        "calibration_sign_as_expected": expected_sign is None or np.sign(calibration["mean_ic"]) == expected_sign,
        "holdout_enough_months": holdout.get("months", 0) >= BLOCK_MONTHS * 2,
        "holdout_same_sign": holdout.get("mean_ic") is not None and np.sign(holdout["mean_ic"]) == sign,
    }
    criteria = {key: bool(value) for key, value in criteria.items()}
    if not (criteria["calibration_interval_excludes_zero"] and criteria["calibration_sign_as_expected"]):
        return "not_supported", criteria
    if criteria["holdout_enough_months"] and criteria["holdout_same_sign"]:
        return "supported", criteria
    return "partial_not_adoptable", criteria


def evaluate(signal: pd.DataFrame, outcome: pd.DataFrame, holdout_start: str, expected_sign: int | None) -> dict:
    ic = monthly_ic(signal, outcome)
    spread = top_minus_average(signal, outcome)
    cut = pd.Timestamp(holdout_start + "-01")
    # The last calibration month's outcome is the month before the holdout starts.
    calibration, holdout = ic[ic.index < cut - pd.offsets.MonthEnd(1)], ic[ic.index >= cut - pd.offsets.MonthEnd(1)]
    stats = {"calibration": summarise(calibration, spread), "holdout": summarise(holdout, spread),
             "all": summarise(ic, spread)}
    verdict, criteria = judge(stats["calibration"], stats["holdout"], expected_sign)
    return {**stats, "verdict": verdict, "criteria": criteria,
            "ic_by_month": {stamp.strftime("%Y-%m"): round(float(value), 3) for stamp, value in ic.items()}}


def evaluate_list(version: str, monthly: pd.DataFrame, histories: dict[str, dict],
                  holdings: dict[str, pd.DataFrame], coverage: pd.DataFrame) -> dict:
    """Every frozen signal over one frozen ETF list (columns absent from the prices are left out)."""
    tickers = [ticker for ticker in etf_holdings.THEME_ETF_LISTS[version] if ticker in monthly.columns]
    monthly = monthly[tickers]
    outcome = forward_relative(monthly)
    price_signals = {"momentum_12_1": momentum(monthly, 12), "momentum_6_1": momentum(monthly, 6)}
    results = []
    for spec in SIGNALS:
        holdout = PRICE_HOLDOUT_START if spec["source"] == "price" else HOLDINGS_HOLDOUT_START
        if spec["source"] == "price":
            frame = price_signals[spec["id"]]
        else:
            frame = holdings[spec["id"]].reindex(columns=tickers) if spec["id"] in holdings else None
        if frame is None:
            results.append({**spec, "holdout_start": holdout, "verdict": "insufficient_sample",
                            "calibration": {"months": 0}, "holdout": {"months": 0}, "all": {"months": 0},
                            "criteria": {}, "ic_by_month": {}})
            continue
        results.append({**spec, "holdout_start": holdout, **evaluate(frame, outcome, holdout, spec["expected_sign"])})
    covered = (coverage.reindex(columns=tickers).stack() if not coverage.empty else pd.Series(dtype=float))
    return {
        "etf_list_version": version,
        "etfs": tickers,
        "holdings_coverage": {
            "etf_months": int(covered.notna().sum()),
            "etf_months_usable": int((covered >= MIN_COVERAGE_PCT).sum()),
            "median_pct": round(float(covered.median()), 1) if covered.notna().any() else None,
        },
        "filings_per_etf": {ticker: len(histories[ticker].get("filings", []))
                            for ticker in tickers if ticker in histories},
        "signals": results,
    }


def run(monthly: pd.DataFrame, histories: dict[str, dict], daily: pd.DataFrame | None) -> dict:
    """The current list in full, and every earlier frozen list re-evaluated so its result stays on record."""
    holdings, coverage = ({}, pd.DataFrame())
    if daily is not None and histories:
        holdings, coverage = holdings_signals(histories, daily, monthly.index)
    current = evaluate_list(etf_holdings.THEME_ETF_VERSION, monthly, histories, holdings, coverage)
    earlier = []
    for version in etf_holdings.THEME_ETF_LISTS:
        if version == etf_holdings.THEME_ETF_VERSION:
            continue
        result = evaluate_list(version, monthly, histories, holdings, coverage)
        earlier.append({"etf_list_version": version, "etfs": result["etfs"],
                        "signals": [{key: signal[key] for key in ("id", "label", "verdict", "calibration", "holdout")}
                                    for signal in result["signals"]]})
    return {
        "status": "research",
        "history_quality": "point_in_time_nport",
        "version": SIGNAL_VERSION,
        **current,
        "outcome": "下個月報酬減去當月可得 ETF 的等權平均（相對報酬）",
        "min_coverage_pct": MIN_COVERAGE_PCT,
        "verdicts": VERDICTS,
        "limitations": [
            "ETF 清單在 2026 年選定，全是仍存在的基金（選樣偏誤）",
            "已下市成分可能抓不到報價；涵蓋率不到 70% 的月份不計",
            "成分權重與資金流以申報日為準，但 N-PORT 本身落後約 60 天",
            "N-PORT 存檔約從 2019 年開始，持股類訊號樣本期短",
            "第二份清單是在第一份清單沒有訊號之後才擴大的；兩份結果並列，不挑較好的一份",
        ],
        "earlier_lists": earlier,
    }


def load_histories(directory: Path) -> dict[str, dict]:
    return {ticker: history for ticker in etf_holdings.THEME_ETFS
            if (history := load_json(directory / f"{ticker}.json", None))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--history-dir", type=Path, default=HISTORY_DIR)
    args = parser.parse_args()
    import yfinance as yf  # noqa: PLC0415  (CI only)
    from build_market_rotation import fetch_market_data  # noqa: PLC0415

    tickers = sorted(etf_holdings.THEME_ETFS)
    data = yf.download(tickers, start=PRICE_START, end=date.today().isoformat(), interval="1d",
                       auto_adjust=False, actions=False, group_by="column", progress=False, threads=True)
    monthly = data["Adj Close"][tickers].resample("ME").last()
    if monthly.index[-1].to_period("M") == pd.Timestamp(date.today()).to_period("M"):
        monthly = monthly.iloc[:-1]  # completed months only
    histories = load_histories(args.history_dir)
    daily = None
    if histories:
        first = min(row["filed"] for history in histories.values() for row in history["filings"])
        constituents = sorted({ticker for history in histories.values() for row in history["filings"]
                               for ticker in row["weights"]})
        start = (pd.Timestamp(first) - pd.Timedelta(days=120)).date()
        closes, _ = fetch_market_data([t.replace(".", "-") for t in constituents], start, date.today())
        back = {t.replace(".", "-"): t for t in constituents}
        daily = closes.rename(columns=lambda column: back.get(column, column))
        daily.index = pd.to_datetime(daily.index)
    result = run(monthly, histories, daily)
    result["generated_at"] = pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")
    result["period"] = {"first_month": monthly.index[0].strftime("%Y-%m"),
                        "last_month": monthly.index[-1].strftime("%Y-%m")}
    write_json(args.output, result, indent=1)
    for signal in result["signals"]:
        print(f"  {signal['id']}: {signal['verdict']} | calibration IC {signal['calibration'].get('mean_ic')}, "
              f"holdout IC {signal['holdout'].get('mean_ic')}")


if __name__ == "__main__":
    sys.exit(main())
