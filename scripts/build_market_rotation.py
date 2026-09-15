"""Build the standalone S&P 500 + Nasdaq-100 market-rotation dataset.

The browser must not download hundreds of quotes, and ``prices.json`` is kept
small for the portfolio dashboard.  This script therefore fetches the broad
universe at build time, reduces it to auditable sector/industry indicators and
writes only the aggregates used by ``market_rotation.html``.

Price and volume describe market preference, not fund-flow accounting.  The
output deliberately calls the result a rotation *proxy* and records coverage
so a partial Yahoo response cannot silently look complete.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf


ROOT = Path(__file__).resolve().parent.parent
UNIVERSE_PATH = ROOT / "market_rotation_universe.json"
OUTPUT_PATH = ROOT / "market_rotation.json"

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NASDAQ100_URL = "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies"

SECTOR_ZH = {
    "Communication Services": "通訊服務",
    "Consumer Discretionary": "非必需消費",
    "Consumer Staples": "必需消費",
    "Energy": "能源",
    "Financials": "金融",
    "Health Care": "醫療保健",
    "Industrials": "工業",
    "Information Technology": "資訊科技",
    "Materials": "原物料",
    "Real Estate": "房地產",
    "Utilities": "公用事業",
}

ICB_TO_GICS = {
    "Technology": "Information Technology",
    "Telecommunications": "Communication Services",
    "Consumer Discretionary": "Consumer Discretionary",
    "Consumer Staples": "Consumer Staples",
    "Energy": "Energy",
    "Financials": "Financials",
    "Health Care": "Health Care",
    "Industrials": "Industrials",
    "Basic Materials": "Materials",
    "Real Estate": "Real Estate",
    "Utilities": "Utilities",
}

SCORE_WEIGHTS = {
    "relative_strength_20d": 0.20,
    "relative_strength_60d": 0.15,
    "acceleration_5d": 0.15,
    "breadth": 0.25,
    "dollar_volume_expansion": 0.15,
    "persistence": 0.10,
}

NEW_YORK = ZoneInfo("America/New_York")
# Give Yahoo two hours after the regular 16:00 ET close before declaring the
# current session missing.  The scheduled job normally runs later than this.
MARKET_DATA_CUTOFF = time(18, 0)


def observed_fixed_holiday(value: date) -> date:
    if value.weekday() == 5:
        return value - timedelta(days=1)
    if value.weekday() == 6:
        return value + timedelta(days=1)
    return value


def nth_weekday(year: int, month: int, weekday: int, number: int) -> date:
    value = date(year, month, 1)
    value += timedelta(days=(weekday - value.weekday()) % 7)
    return value + timedelta(weeks=number - 1)


def last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        value = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        value = date(year, month + 1, 1) - timedelta(days=1)
    return value - timedelta(days=(value.weekday() - weekday) % 7)


def easter_sunday(year: int) -> date:
    """Return Gregorian Easter using the anonymous computus algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    length = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * length) // 451
    month = (h + length - 7 * m + 114) // 31
    day = (h + length - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def nyse_holidays(year: int) -> set[date]:
    """Regular full-day NYSE holidays; exceptional closures stay explicit."""
    holidays = {
        observed_fixed_holiday(date(year, 1, 1)),
        nth_weekday(year, 1, 0, 3),   # Martin Luther King Jr. Day
        nth_weekday(year, 2, 0, 3),   # Washington's Birthday
        easter_sunday(year) - timedelta(days=2),
        last_weekday(year, 5, 0),     # Memorial Day
        observed_fixed_holiday(date(year, 7, 4)),
        nth_weekday(year, 9, 0, 1),   # Labor Day
        nth_weekday(year, 11, 3, 4),  # Thanksgiving
        observed_fixed_holiday(date(year, 12, 25)),
    }
    if year >= 2022:
        holidays.add(observed_fixed_holiday(date(year, 6, 19)))
    return holidays


# Add one-off national days of mourning or emergency closures here after an
# official exchange announcement.  Keeping the override visible is safer than
# silently treating every federal holiday as an equity-market closure.
EXTRA_MARKET_CLOSURES: set[date] = set()


def is_market_session(value: date) -> bool:
    holidays = set().union(*(
        nyse_holidays(year) for year in range(value.year - 1, value.year + 2)
    ))
    return value.weekday() < 5 and value not in holidays and value not in EXTRA_MARKET_CLOSURES


def previous_market_session(value: date) -> date:
    candidate = value
    while not is_market_session(candidate):
        candidate -= timedelta(days=1)
    return candidate


def expected_latest_market_session(now: datetime | None = None) -> date:
    """Latest NYSE session whose regular close should be available from Yahoo."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    market_now = current.astimezone(NEW_YORK)
    candidate = market_now.date()
    if market_now.timetz().replace(tzinfo=None) < MARKET_DATA_CUTOFF:
        candidate -= timedelta(days=1)
    return previous_market_session(candidate)


def market_session_lag(actual: date, expected: date) -> int:
    if actual >= expected:
        return 0
    lag = 0
    candidate = actual + timedelta(days=1)
    while candidate <= expected:
        if is_market_session(candidate):
            lag += 1
        candidate += timedelta(days=1)
    return lag


def require_fresh_market_data(actual: date, expected: date) -> None:
    if actual < expected:
        lag = market_session_lag(actual, expected)
        raise ValueError(
            f"Market data is stale: latest session {actual.isoformat()}, expected "
            f"{expected.isoformat()} ({lag} market session{'s' if lag != 1 else ''} behind)"
        )


def require_latest_session_coverage(
    closes: pd.DataFrame, expected: date, universe_size: int, minimum: float = 0.90
) -> None:
    matching = [index for index in closes.index if pd.Timestamp(index).date() == expected]
    priced = int(closes.loc[matching[-1]].notna().sum()) if matching else 0
    required = math.ceil(universe_size * minimum)
    if priced < required:
        raise ValueError(
            f"Latest-session coverage is partial: {priced}/{universe_size} securities "
            f"have prices for {expected.isoformat()}, need at least {required} ({minimum:.0%})"
        )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch_html(url: str) -> str:
    request = Request(url, headers={"User-Agent": "ttc-stock market rotation research/1.0"})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def find_table(html: str, required: set[str]) -> pd.DataFrame:
    for table in pd.read_html(io.StringIO(html)):
        columns = {str(value) for value in table.columns}
        if required.issubset(columns):
            return table
    raise ValueError(f"No table contains required columns: {sorted(required)}")


def yahoo_symbol(symbol: str) -> str:
    return symbol.replace(".", "-")


def build_universe() -> dict:
    sp = find_table(
        fetch_html(SP500_URL),
        {"Symbol", "Security", "GICS Sector", "GICS Sub-Industry"},
    )
    ndx = find_table(
        fetch_html(NASDAQ100_URL),
        {"Ticker", "Company", "ICB Industry[1]", "ICB Subsector[1]"},
    )

    members: dict[str, dict] = {}
    for row in sp.to_dict("records"):
        ticker = str(row["Symbol"]).strip().upper()
        members[ticker] = {
            "ticker": ticker,
            "yahoo_ticker": yahoo_symbol(ticker),
            "name": str(row["Security"]).strip(),
            "sector": str(row["GICS Sector"]).strip(),
            "industry": str(row["GICS Sub-Industry"]).strip(),
            "indexes": ["S&P 500"],
            "classification": "GICS",
        }

    for row in ndx.to_dict("records"):
        ticker = str(row["Ticker"]).strip().upper()
        if ticker in members:
            members[ticker]["indexes"].append("Nasdaq-100")
            continue
        icb_sector = str(row["ICB Industry[1]"]).strip()
        sector = ICB_TO_GICS.get(icb_sector, icb_sector)
        members[ticker] = {
            "ticker": ticker,
            "yahoo_ticker": yahoo_symbol(ticker),
            "name": str(row["Company"]).strip(),
            "sector": sector,
            "industry": str(row["ICB Subsector[1]"]).strip(),
            "indexes": ["Nasdaq-100"],
            "classification": "ICB mapped to GICS sector",
        }

    if len(sp) < 490 or len(ndx) < 95 or len(members) < 500:
        raise ValueError(
            f"Constituent tables look incomplete: S&P={len(sp)}, Nasdaq-100={len(ndx)}, "
            f"combined={len(members)}"
        )

    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "sources": {
            "sp500": SP500_URL,
            "nasdaq100": NASDAQ100_URL,
            "classification_note": (
                "S&P 500 members use GICS. Nasdaq-100-only members use ICB with "
                "top-level sectors mapped to the closest GICS sector."
            ),
        },
        "counts": {
            "sp500_securities": int(len(sp)),
            "nasdaq100_securities": int(len(ndx)),
            "combined_securities": len(members),
        },
        "members": sorted(members.values(), key=lambda row: row["ticker"]),
    }


def stable_payload(payload: dict) -> dict:
    value = dict(payload)
    value.pop("generated_at", None)
    return value


def write_if_changed(path: Path, payload: dict) -> bool:
    if path.exists():
        try:
            previous = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            previous = None
        if previous is not None and stable_payload(previous) == stable_payload(payload):
            # Generated market files are intentionally minified.  Hundreds of
            # constituents and trajectory points otherwise turn a small data
            # change into thousands of diff lines and waste review context.
            compact_previous = json.dumps(
                previous, ensure_ascii=False, separators=(",", ":")
            ) + "\n"
            if path.read_text() != compact_previous:
                path.write_text(compact_previous)
                return True
            return False
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    return True


def refresh_universe(path: Path = UNIVERSE_PATH) -> dict:
    try:
        payload = build_universe()
    except Exception as error:
        if not path.exists():
            raise
        print(f"Universe refresh failed; using committed fallback ({error})")
        return json.loads(path.read_text())
    changed = write_if_changed(path, payload)
    print(
        f"Universe: {payload['counts']['combined_securities']} securities "
        f"({'updated' if changed else 'unchanged'})"
    )
    if not changed:
        return json.loads(path.read_text())
    return payload


def chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for offset in range(0, len(values), size):
        yield values[offset:offset + size]


def field_frame(frame: pd.DataFrame, field: str, tickers: list[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    if isinstance(frame.columns, pd.MultiIndex):
        if field not in frame.columns.get_level_values(0):
            return pd.DataFrame(index=frame.index)
        result = frame[field].copy()
    else:
        if field not in frame:
            return pd.DataFrame(index=frame.index)
        result = frame[[field]].copy()
        result.columns = tickers[:1]
    if isinstance(result, pd.Series):
        result = result.to_frame(name=tickers[0])
    return result


def fetch_market_data(
    yahoo_tickers: list[str], start: date, end: date, batch_size: int = 80
) -> tuple[pd.DataFrame, pd.DataFrame]:
    close_parts = []
    volume_parts = []
    for number, batch in enumerate(chunks(yahoo_tickers, batch_size), start=1):
        frame = yf.download(
            batch,
            start=start.isoformat(),
            end=end.isoformat(),
            interval="1d",
            auto_adjust=False,
            actions=False,
            group_by="column",
            threads=True,
            progress=False,
        )
        close = field_frame(frame, "Adj Close", batch)
        volume = field_frame(frame, "Volume", batch)
        close_parts.append(close)
        volume_parts.append(volume)
        good = int(close.notna().any().sum()) if not close.empty else 0
        print(f"  batch {number}: {good}/{len(batch)} tickers")

    closes = pd.concat(close_parts, axis=1).sort_index() if close_parts else pd.DataFrame()
    volumes = pd.concat(volume_parts, axis=1).sort_index() if volume_parts else pd.DataFrame()
    closes = closes.loc[:, ~closes.columns.duplicated()].apply(pd.to_numeric, errors="coerce")
    volumes = volumes.loc[:, ~volumes.columns.duplicated()].apply(pd.to_numeric, errors="coerce")
    return closes, volumes


def finite(value, digits: int = 4):
    if value is None or pd.isna(value) or not math.isfinite(float(value)):
        return None
    return round(float(value), digits)


def pct(value):
    result = finite(value * 100 if value is not None else None, 2)
    return result


def weighted_mean(values: pd.Series, weights: pd.Series):
    valid = values.notna() & weights.notna() & (weights > 0)
    if not valid.any():
        return None
    return float((values[valid] * weights[valid]).sum() / weights[valid].sum())


def horizon_return(closes: pd.DataFrame, periods: int, offset: int = 0) -> pd.Series:
    end = closes.iloc[-1 - offset]
    start_position = -1 - offset - periods
    if abs(start_position) > len(closes):
        return pd.Series(index=closes.columns, dtype=float)
    return end / closes.iloc[start_position] - 1


def raw_group_metrics(
    closes: pd.DataFrame,
    volumes: pd.DataFrame,
    metadata: pd.DataFrame,
    group_field: str,
    min_members: int,
) -> tuple[list[dict], dict]:
    if len(closes) < 75:
        raise ValueError(f"Need at least 75 market sessions, found {len(closes)}")

    r5 = horizon_return(closes, 5)
    r20 = horizon_return(closes, 20)
    r60 = horizon_return(closes, 60)
    previous5 = horizon_return(closes, 5, offset=5)
    benchmark = {
        "return_5d": float(r5.mean()),
        "return_20d": float(r20.mean()),
        "return_60d": float(r60.mean()),
        "previous_5d": float(previous5.mean()),
    }
    benchmark["relative_acceleration"] = (
        benchmark["return_5d"] - benchmark["previous_5d"]
    )

    sma20 = closes.rolling(20, min_periods=15).mean().iloc[-1]
    daily_returns = closes.pct_change(fill_method=None)
    dollar_volume = closes * volumes
    current_weights = dollar_volume.iloc[-20:].mean()
    volume_recent = dollar_volume.iloc[-5:].sum(axis=1).mean()
    volume_prior = dollar_volume.iloc[-25:-5].sum(axis=1).mean()

    rows = []
    grouped = metadata.groupby(group_field, sort=True)
    for group_name, group_meta in grouped:
        tickers = [ticker for ticker in group_meta.index if ticker in closes]
        valid20 = r20[tickers].dropna()
        if len(valid20) < min_members:
            continue
        group_r5 = float(r5[tickers].mean())
        group_r20 = float(valid20.mean())
        group_r60 = float(r60[tickers].mean())
        group_previous5 = float(previous5[tickers].mean())
        rel5 = group_r5 - benchmark["return_5d"]
        previous_rel5 = group_previous5 - benchmark["previous_5d"]
        above_ma = (closes.iloc[-1][tickers] > sma20[tickers]).dropna()
        positive20 = (r20[tickers] > 0).dropna()
        group_daily = daily_returns[tickers].mean(axis=1)
        universe_daily = daily_returns.mean(axis=1)
        persistence = float((group_daily.iloc[-10:] > universe_daily.iloc[-10:]).mean())
        group_recent = dollar_volume[tickers].iloc[-5:].sum(axis=1).mean()
        group_prior = dollar_volume[tickers].iloc[-25:-5].sum(axis=1).mean()
        volume_expansion = (group_recent / group_prior - 1) if group_prior else None
        liquid_return = weighted_mean(r20[tickers], current_weights[tickers])

        rows.append({
            "key": str(group_name),
            "name": str(group_name),
            "name_zh": SECTOR_ZH.get(str(group_name), str(group_name)),
            "member_count": len(tickers),
            "return_5d": group_r5,
            "return_20d": group_r20,
            "return_60d": group_r60,
            "relative_strength_5d": rel5,
            "relative_strength_20d": group_r20 - benchmark["return_20d"],
            "relative_strength_60d": group_r60 - benchmark["return_60d"],
            "acceleration_5d": rel5 - previous_rel5,
            "breadth_positive_20d": float(positive20.mean()),
            "breadth_above_ma20": float(above_ma.mean()),
            "breadth": float((positive20.mean() + above_ma.mean()) / 2),
            "dollar_volume_expansion": float(volume_expansion) if volume_expansion is not None else None,
            "persistence": persistence,
            "liquidity_weighted_return_20d": liquid_return,
            "leadership_gap": (liquid_return - group_r20) if liquid_return is not None else None,
        })
    benchmark["dollar_volume_expansion"] = (
        float(volume_recent / volume_prior - 1) if volume_prior else None
    )
    return rows, benchmark


def score_rows(rows: list[dict]) -> list[dict]:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return []
    for metric in SCORE_WEIGHTS:
        frame[f"rank_{metric}"] = frame[metric].rank(pct=True, method="average") * 100
    frame["rotation_score"] = sum(
        frame[f"rank_{metric}"] * weight for metric, weight in SCORE_WEIGHTS.items()
    )
    return sorted(frame_to_clean_records(frame, rows), key=lambda item: item["rotation_score"], reverse=True)


def frame_to_clean_records(frame: pd.DataFrame, source_rows: list[dict]) -> list[dict]:
    """Convert score-frame rows while retaining the percent conversions above."""
    # score_rows constructs its display rows before this helper so rebuild those
    # directly; keeping this helper small makes NaN cleanup explicit.
    result = []
    by_key = {row["key"]: row for row in source_rows}
    for scored in frame.to_dict("records"):
        source = dict(by_key[scored["key"]])
        for metric in SCORE_WEIGHTS:
            source[f"rank_{metric}"] = finite(scored[f"rank_{metric}"], 1)
        source["rotation_score"] = finite(scored["rotation_score"], 1)
        x = source["relative_strength_20d"]
        y = source["acceleration_5d"]
        if x >= 0 and y >= 0:
            source["quadrant"], source["quadrant_zh"] = "leading", "領先"
        elif x < 0 <= y:
            source["quadrant"], source["quadrant_zh"] = "improving", "改善"
        elif x >= 0 > y:
            source["quadrant"], source["quadrant_zh"] = "weakening", "轉弱"
        else:
            source["quadrant"], source["quadrant_zh"] = "lagging", "落後"
        for metric in (
            "return_5d", "return_20d", "return_60d", "relative_strength_5d",
            "relative_strength_20d", "relative_strength_60d", "acceleration_5d",
            "breadth_positive_20d", "breadth_above_ma20", "breadth",
            "dollar_volume_expansion", "persistence", "liquidity_weighted_return_20d",
            "leadership_gap",
        ):
            source[metric] = pct(source.get(metric))
        source["score_change_5d"] = None
        result.append(source)
    return result


def metrics_for_date(
    closes: pd.DataFrame,
    volumes: pd.DataFrame,
    metadata: pd.DataFrame,
    group_field: str,
    min_members: int,
    end_position: int,
) -> list[dict]:
    end = len(closes) + end_position + 1 if end_position < 0 else end_position + 1
    sliced_close = closes.iloc[:end]
    sliced_volume = volumes.reindex(sliced_close.index).iloc[:end]
    rows, _ = raw_group_metrics(sliced_close, sliced_volume, metadata, group_field, min_members)
    return score_rows(rows)


def add_score_changes(current: list[dict], previous: list[dict]) -> None:
    previous_by_key = {row["key"]: row for row in previous}
    for row in current:
        before = previous_by_key.get(row["key"])
        row["score_change_5d"] = (
            finite(row["rotation_score"] - before["rotation_score"], 1) if before else None
        )


def add_trajectories(
    current: list[dict], closes: pd.DataFrame, volumes: pd.DataFrame,
    metadata: pd.DataFrame, group_field: str, min_members: int,
) -> None:
    trails = {row["key"]: [] for row in current}
    for offset in range(-10, 0):
        dated = metrics_for_date(closes, volumes, metadata, group_field, min_members, offset)
        date_value = closes.index[offset].strftime("%Y-%m-%d")
        for row in dated:
            if row["key"] in trails:
                trails[row["key"]].append({
                    "date": date_value,
                    "x": row["relative_strength_20d"],
                    "y": row["acceleration_5d"],
                    "score": row["rotation_score"],
                })
    for row in current:
        row["trajectory"] = trails[row["key"]]


def add_stock_leaders(
    sectors: list[dict], closes: pd.DataFrame, volumes: pd.DataFrame,
    metadata: pd.DataFrame, benchmark_20d: float,
) -> None:
    r5 = horizon_return(closes, 5)
    r20 = horizon_return(closes, 20)
    r60 = horizon_return(closes, 60)
    dv = closes * volumes
    recent = dv.iloc[-5:].mean()
    prior = dv.iloc[-25:-5].mean()
    expansion = recent / prior - 1
    for sector in sectors:
        candidates = metadata[metadata["sector"] == sector["key"]]
        rows = []
        for ticker, meta in candidates.iterrows():
            if ticker not in closes or pd.isna(r20.get(ticker)):
                continue
            rows.append({
                "ticker": ticker,
                "name": meta["name"],
                "return_5d": pct(r5.get(ticker)),
                "return_20d": pct(r20.get(ticker)),
                "return_60d": pct(r60.get(ticker)),
                "relative_strength_20d": pct(r20.get(ticker) - benchmark_20d),
                "dollar_volume_expansion": pct(expansion.get(ticker)),
            })
        rows.sort(key=lambda item: item["relative_strength_20d"] or -999, reverse=True)
        sector["leaders"] = rows[:5]
        sector["laggards"] = list(reversed(rows[-5:]))


def build_payload(universe: dict, closes: pd.DataFrame, volumes: pd.DataFrame) -> dict:
    yahoo_to_member = {row["yahoo_ticker"]: row for row in universe["members"]}
    usable = [ticker for ticker in closes if closes[ticker].notna().sum() >= 75]
    closes = closes[usable].dropna(how="all")
    volumes = volumes.reindex(index=closes.index, columns=usable)
    canonical = {ticker: yahoo_to_member[ticker]["ticker"] for ticker in usable if ticker in yahoo_to_member}
    closes = closes[list(canonical)].rename(columns=canonical)
    volumes = volumes[list(canonical)].rename(columns=canonical)
    members = {row["ticker"]: row for row in universe["members"]}
    metadata = pd.DataFrame([members[ticker] for ticker in closes.columns]).set_index("ticker")

    if len(closes.columns) < math.ceil(universe["counts"]["combined_securities"] * 0.90):
        raise ValueError(
            f"Only {len(closes.columns)}/{universe['counts']['combined_securities']} securities "
            "have 75 sessions; refusing to publish partial rotation data"
        )

    sector_raw, benchmark = raw_group_metrics(closes, volumes, metadata, "sector", 5)
    industry_raw, _ = raw_group_metrics(closes, volumes, metadata, "industry", 3)
    sectors = score_rows(sector_raw)
    industries = score_rows(industry_raw)
    sector_previous = metrics_for_date(closes, volumes, metadata, "sector", 5, -6)
    industry_previous = metrics_for_date(closes, volumes, metadata, "industry", 3, -6)
    add_score_changes(sectors, sector_previous)
    add_score_changes(industries, industry_previous)
    add_trajectories(sectors, closes, volumes, metadata, "sector", 5)
    add_trajectories(industries, closes, volumes, metadata, "industry", 3)
    add_stock_leaders(sectors, closes, volumes, metadata, benchmark["return_20d"])

    unavailable = sorted(
        row["ticker"] for row in universe["members"] if row["ticker"] not in metadata.index
    )
    latest = closes.index[-1].strftime("%Y-%m-%d")
    payload = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "as_of": latest,
        "methodology": {
            "label": "價格與成交額市場偏好代理指標（非實際資金淨流入）",
            "universe": "S&P 500 + Nasdaq-100 securities, overlapping tickers de-duplicated",
            "price_field": "Yahoo Finance Adj Close; split and dividend adjusted",
            "score_weights": {key: int(value * 100) for key, value in SCORE_WEIGHTS.items()},
            "score_meaning": "Cross-sectional percentile score from 0 to 100; relative ranking, not valuation.",
            "quadrant": {
                "x": "20-session equal-weight relative return versus the combined universe",
                "y": "5-session relative-return acceleration versus the preceding 5 sessions",
                "trail": "10 latest market sessions",
            },
            "breadth": "Average of positive 20-session return share and share above 20-session moving average.",
            "volume": "Latest 5-session aggregate traded-dollar average versus the preceding 20 sessions.",
            "leadership_gap": "20-session dollar-liquidity-weighted return minus equal-weight return; not market-cap weighting.",
        },
        "sources": {
            "prices": "Yahoo Finance via yfinance",
            "sp500_constituents": SP500_URL,
            "nasdaq100_constituents": NASDAQ100_URL,
        },
        "coverage": {
            "universe_securities": universe["counts"]["combined_securities"],
            "priced_securities": len(closes.columns),
            "coverage_pct": round(len(closes.columns) / universe["counts"]["combined_securities"] * 100, 1),
            "unavailable_tickers": unavailable,
            "start": closes.index[0].strftime("%Y-%m-%d"),
            "end": latest,
        },
        "benchmark": {
            "name": "合併股票池等權基準",
            "return_5d": pct(benchmark["return_5d"]),
            "return_20d": pct(benchmark["return_20d"]),
            "return_60d": pct(benchmark["return_60d"]),
            "dollar_volume_expansion": pct(benchmark["dollar_volume_expansion"]),
        },
        "sectors": sectors,
        "industries": industries,
    }
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=Path, default=UNIVERSE_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--skip-universe-refresh", action="store_true")
    parser.add_argument("--days", type=int, default=320)
    parser.add_argument("--batch-size", type=int, default=80)
    parser.add_argument(
        "--expected-session",
        type=date.fromisoformat,
        help="Override the latest required market session (YYYY-MM-DD) for replay/testing.",
    )
    parser.add_argument(
        "--allow-stale",
        action="store_true",
        help="Allow an explicitly requested historical/backfill output to be written.",
    )
    args = parser.parse_args()

    if args.skip_universe_refresh:
        universe = json.loads(args.universe.read_text())
    else:
        universe = refresh_universe(args.universe)

    tickers = [row["yahoo_ticker"] for row in universe["members"]]
    end = date.today() + timedelta(days=1)
    start = end - timedelta(days=args.days)
    expected_session = args.expected_session or expected_latest_market_session()
    print(f"Fetching {len(tickers)} securities from {start} through {end}...")
    closes, volumes = fetch_market_data(tickers, start, end, args.batch_size)
    if not args.allow_stale:
        try:
            require_latest_session_coverage(
                closes, expected_session, universe["counts"]["combined_securities"]
            )
        except ValueError as error:
            print(
                f"{error}; refusing to replace {args.output.name}. "
                "Retry after the quote source publishes the adjusted closes.",
                file=sys.stderr,
            )
            raise SystemExit(75) from error
    payload = build_payload(universe, closes, volumes)
    actual_session = date.fromisoformat(payload["as_of"])
    if not args.allow_stale:
        try:
            require_fresh_market_data(actual_session, expected_session)
        except ValueError as error:
            print(
                f"{error}; refusing to replace {args.output.name}. "
                "Retry after the quote source publishes the adjusted close.",
                file=sys.stderr,
            )
            raise SystemExit(75) from error
    changed = write_if_changed(args.output, payload)
    print(
        f"Market rotation: {payload['as_of']}, "
        f"{payload['coverage']['priced_securities']}/{payload['coverage']['universe_securities']} "
        f"securities, {len(payload['sectors'])} sectors, {len(payload['industries'])} industries "
        f"({'updated' if changed else 'unchanged'})"
    )


if __name__ == "__main__":
    main()
