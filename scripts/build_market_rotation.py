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
import copy
import hashlib
import io
import json
import math
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
import yfinance as yf

from market_calendar import expected_latest_market_session, market_session_lag
from market_rotation_contracts import (
    QUADRANTS, check_parity, compute_dataset_id, dump_json, group_slug,
    validate_canonical, validate_registry, validate_v1, validate_v2,
)


ROOT = Path(__file__).resolve().parent.parent
UNIVERSE_PATH = ROOT / "market_rotation_universe.json"
OUTPUT_PATH = ROOT / "market_rotation.json"
REGISTRY_PATH = ROOT / "market_rotation_registry.json"

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

# Schema version 2 changes the file layout only; the formula stays v1.
VERSIONS = {
    "calculation": "rotation-score-v1",
    "classification": "gics-current-v1",
    "universe": "union-deduped-v1",
}
MIN_MEMBERS = {"sector": 5, "industry": 3}
GROUP_METRICS = (
    "return_5d", "return_20d", "return_60d", "relative_strength_5d",
    "relative_strength_20d", "relative_strength_60d", "acceleration_5d",
    "breadth_positive_20d", "breadth_above_ma20", "breadth",
    "dollar_volume_expansion", "persistence", "liquidity_weighted_return_20d",
    "leadership_gap",
)
STOCK_METRICS = (
    "return_5d", "return_20d", "return_60d", "relative_strength_20d", "dollar_volume_expansion",
)
ROLE_EVIDENCE = {
    "leader": ("metrics.relative_strength_20d", "metrics.acceleration_5d", "rotation_score"),
    "improver": ("metrics.acceleration_5d", "metrics.relative_strength_20d", "rotation_score"),
    "weakening": ("rotation_score", "metrics.acceleration_5d", "metrics.relative_strength_20d"),
    "broadest": ("metrics.breadth", "quadrant", "rotation_score"),
}
DEFAULT_CHART_SECTORS = 3
TOP_INDUSTRIES = 20

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


def planned_text(path: Path, payload: dict) -> str | None:
    """Text to write, or None when only ``generated_at`` would change."""
    text = dump_json(payload)
    if not path.exists():
        return text
    try:
        current = path.read_text()
        previous = json.loads(current)
    except (OSError, json.JSONDecodeError):
        return text
    if stable_payload(previous) != stable_payload(payload):
        return text
    # Generated market files are intentionally minified.  Hundreds of
    # constituents and trajectory points otherwise turn a small data change
    # into thousands of diff lines and waste review context.
    compact_previous = dump_json(previous)
    return compact_previous if current != compact_previous else None


def publish_artifacts(
    outputs: list[tuple[Path, dict, Callable[[dict], None] | None]],
) -> dict[Path, bool]:
    """Validate every payload first, then replace only the files that changed.

    Nothing on disk is touched unless all payloads pass their contracts and
    serialise without NaN/Infinity.  Changed files are staged beside their
    targets and swapped in with ``os.replace`` so a reader never sees a
    half-written file.
    """
    for path, payload, validate in outputs:
        if validate is not None:
            validate(payload)
    plans = [(path, planned_text(path, payload)) for path, payload, _ in outputs]
    staged: list[tuple[str, Path]] = []
    try:
        for path, text in plans:
            if text is None:
                continue
            handle = tempfile.NamedTemporaryFile(
                "w", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
                delete=False, encoding="utf-8",
            )
            with handle:
                handle.write(text)
            staged.append((handle.name, path))
        for temporary, path in staged:
            os.replace(temporary, path)
    finally:
        for temporary, _ in staged:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return {path: text is not None for path, text in plans}


def write_if_changed(path: Path, payload: dict, validate=None) -> bool:
    return publish_artifacts([(path, payload, validate)])[path]


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
    # "+ 0.0" folds -0.0 into 0.0 so a rounded zero never prints as "-0.0".
    return round(float(value), digits) + 0.0


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
    universe_daily = daily_returns.mean(axis=1).iloc[-10:]
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
        latest_close = closes.iloc[-1][tickers]
        has_ma = latest_close.notna() & sma20[tickers].notna()
        # Securities without a latest close or moving average leave the
        # denominator; counting them as "below" would understate breadth.
        above_ma = latest_close[has_ma] > sma20[tickers][has_ma]
        positive20 = r20[tickers].dropna() > 0
        group_daily = daily_returns[tickers].iloc[-10:].mean(axis=1)
        persistence = float((group_daily > universe_daily).mean())
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


def missing_components(row: dict) -> list[str]:
    return [metric for metric in SCORE_WEIGHTS if finite(row.get(metric)) is None]


def unranked_groups(rows: list[dict], group_type: str, id_of: Callable[[str], str]) -> list[dict]:
    """Groups left out of the ranking because a score component is missing.

    Missing weight is never redistributed to the remaining components, so the
    same score always means the same formula.
    """
    found = [
        {"group_id": id_of(row["key"]), "group_type": group_type, "name_en": row["key"],
         "missing_components": missing}
        for row in rows if (missing := missing_components(row))
    ]
    return sorted(found, key=lambda item: item["group_id"])


def score_rows(rows: list[dict], tie_key: Callable[[str], str] = group_slug) -> list[dict]:
    rows = [row for row in rows if not missing_components(row)]
    frame = pd.DataFrame(rows)
    if frame.empty:
        return []
    for metric in SCORE_WEIGHTS:
        frame[f"rank_{metric}"] = frame[metric].rank(pct=True, method="average") * 100
    frame["rotation_score"] = sum(
        frame[f"rank_{metric}"] * weight for metric, weight in SCORE_WEIGHTS.items()
    )
    return sorted(
        frame_to_clean_records(frame, rows),
        key=lambda item: (-item["rotation_score"], tie_key(item["key"])),
    )


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
        source["quadrant"], source["quadrant_zh"] = None, None
        for metric in (
            "return_5d", "return_20d", "return_60d", "relative_strength_5d",
            "relative_strength_20d", "relative_strength_60d", "acceleration_5d",
            "breadth_positive_20d", "breadth_above_ma20", "breadth",
            "dollar_volume_expansion", "persistence", "liquidity_weighted_return_20d",
            "leadership_gap",
        ):
            source[metric] = pct(source.get(metric))
        # Classify on the published (rounded) axes so a point drawn at 0.00
        # always carries the non-negative quadrant the page explains.
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


def rank_stock_rows(rows: list[dict]) -> list[dict]:
    """Strongest relative return first; missing values last; ticker breaks ties."""
    return sorted(rows, key=lambda item: (
        item["relative_strength_20d"] is None,
        -(item["relative_strength_20d"] or 0.0),
        item["ticker"],
    ))


class Registry:
    """Committed stable ids for groups and securities.

    Ids come from this version-controlled table, not from today's names: a
    known name or alias always resolves to its recorded id, and only unseen
    names get a new slug id (with a short hash if the slug is taken).
    """

    def __init__(self, data: dict | None = None):
        self.data = copy.deepcopy(data) if data else {"schema_version": 1, "groups": [], "securities": []}
        self.group_ids = {
            (row["group_type"], name): row["group_id"]
            for row in self.data["groups"] for name in (row["name_en"], *row["aliases"])
        }
        self.stock_ids = {
            name: row["stock_id"]
            for row in self.data["securities"] for name in (row["ticker"], *row["aliases"])
        }

    @staticmethod
    def new_id(prefix: str, name: str, taken: set[str]) -> str:
        base = f"{prefix}:{group_slug(name) or 'unnamed'}"
        digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
        candidate, length = base, 6
        while candidate in taken:
            candidate, length = f"{base}-{digest[:length]}", length + 2
        return candidate

    def group_id(self, group_type: str, name: str) -> str:
        key = (group_type, name)
        if key not in self.group_ids:
            identifier = self.new_id(group_type, name, {row["group_id"] for row in self.data["groups"]})
            self.data["groups"].append(
                {"group_id": identifier, "group_type": group_type, "name_en": name, "aliases": []})
            self.group_ids[key] = identifier
        return self.group_ids[key]

    def stock_id(self, ticker: str) -> str:
        if ticker not in self.stock_ids:
            identifier = self.new_id("security", ticker, {row["stock_id"] for row in self.data["securities"]})
            self.data["securities"].append({"stock_id": identifier, "ticker": ticker, "aliases": []})
            self.stock_ids[ticker] = identifier
        return self.stock_ids[ticker]

    def register_universe(self, members: list[dict]) -> None:
        # Sorted so new ids (and any collision suffix) never depend on row order.
        for group_type in ("sector", "industry"):
            for name in sorted({row[group_type] for row in members}):
                self.group_id(group_type, name)
        for ticker in sorted(row["ticker"] for row in members):
            self.stock_id(ticker)

    def payload(self) -> dict:
        return {
            "schema_version": 1,
            "groups": sorted(self.data["groups"], key=lambda row: row["group_id"]),
            "securities": sorted(self.data["securities"], key=lambda row: row["stock_id"]),
        }


def prepare_market_data(
    universe: dict, closes: pd.DataFrame, volumes: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    yahoo_to_member = {row["yahoo_ticker"]: row for row in universe["members"]}
    # Zero, negative or infinite quotes are source errors, not prices.  Treat
    # them as missing before any return, breadth or volume calculation.
    closes = closes.apply(pd.to_numeric, errors="coerce")
    closes = closes.where(np.isfinite(closes) & (closes > 0))
    volumes = volumes.apply(pd.to_numeric, errors="coerce")
    volumes = volumes.where(np.isfinite(volumes) & (volumes >= 0))
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
    unavailable = sorted(
        row["ticker"] for row in universe["members"] if row["ticker"] not in metadata.index
    )
    return closes, volumes, metadata, unavailable


def stock_records(
    closes: pd.DataFrame, volumes: pd.DataFrame, metadata: pd.DataFrame,
    benchmark_20d: float, registry: Registry,
) -> list[dict]:
    r5 = horizon_return(closes, 5)
    r20 = horizon_return(closes, 20)
    r60 = horizon_return(closes, 60)
    dv = closes * volumes
    recent = dv.iloc[-5:].mean()
    prior = dv.iloc[-25:-5].mean()
    expansion = recent / prior - 1
    records = []
    for ticker, meta in metadata.iterrows():
        metrics = {
            "return_5d": pct(r5.get(ticker)),
            "return_20d": pct(r20.get(ticker)),
            "return_60d": pct(r60.get(ticker)),
            "relative_strength_20d": pct(r20.get(ticker) - benchmark_20d),
            "dollar_volume_expansion": pct(expansion.get(ticker)),
        }
        flags = []
        if metrics["relative_strength_20d"] is None:
            flags.append("missing_return_20d")
        if metrics["dollar_volume_expansion"] is None:
            flags.append("missing_volume")
        records.append({
            "stock_id": registry.stock_id(ticker),
            "ticker": ticker,
            "yahoo_ticker": meta["yahoo_ticker"],
            "name": meta["name"],
            "sector_id": registry.group_id("sector", meta["sector"]),
            "sector_name_en": meta["sector"],
            "industry_id": registry.group_id("industry", meta["industry"]),
            "industry_name_en": meta["industry"],
            "indexes": list(meta["indexes"]),
            "classification": meta["classification"],
            "metrics": metrics,
            "quality_flags": flags,
        })
    return sorted(records, key=lambda row: row["stock_id"])


def stock_selection(stocks: list[dict], sector_id: str) -> tuple[list[str], list[str]]:
    candidates = [
        {"stock_id": row["stock_id"], "ticker": row["ticker"],
         "relative_strength_20d": row["metrics"]["relative_strength_20d"]}
        for row in stocks if row["sector_id"] == sector_id
    ]
    ranked = [row for row in rank_stock_rows(candidates) if row["relative_strength_20d"] is not None]
    return ([row["stock_id"] for row in ranked[:5]],
            [row["stock_id"] for row in reversed(ranked[-5:])])


def industry_parents(metadata: pd.DataFrame, registry: Registry) -> dict[str, str]:
    parents = {}
    for industry, sectors in metadata.groupby("industry")["sector"]:
        counts = sectors.value_counts()
        top = sorted(counts[counts == counts.max()].index, key=lambda name: registry.group_id("sector", name))
        parents[industry] = registry.group_id("sector", top[0])
    return parents


def group_record(
    row: dict, rank: int, group_type: str, registry: Registry,
    parent: str | None, selection: tuple[list[str], list[str]] | None,
) -> dict:
    return {
        "group_id": registry.group_id(group_type, row["key"]),
        "group_type": group_type,
        "parent_group_id": parent,
        "name_en": row["name"],
        "name_zh": row["name_zh"],
        "member_count": row["member_count"],
        "rank": rank,
        "metrics": {metric: row[metric] for metric in GROUP_METRICS},
        "ranks": {metric: row[f"rank_{metric}"] for metric in SCORE_WEIGHTS},
        "rotation_score": row["rotation_score"],
        "score_change_5d": row["score_change_5d"],
        "quadrant": row["quadrant"],
        "trajectory": row["trajectory"],
        "leader_stock_ids": selection[0] if selection else None,
        "laggard_stock_ids": selection[1] if selection else None,
    }


def select_roles(sectors: list[dict]) -> dict[str, str | None]:
    """Fixed, testable home-page roles; an empty quadrant yields None, never a stand-in."""
    def best(rows, key):
        return min(rows, key=key)["group_id"] if rows else None

    in_quadrant = {name: [g for g in sectors if g["quadrant"] == name] for name in QUADRANTS}
    return {
        "leader": best(in_quadrant["leading"], lambda g: (-g["rotation_score"], g["group_id"])),
        "improver": best(in_quadrant["improving"], lambda g: (
            -g["metrics"]["acceleration_5d"], -g["rotation_score"], g["group_id"])),
        "weakening": best(in_quadrant["weakening"], lambda g: (-g["rotation_score"], g["group_id"])),
        "broadest": best(sectors, lambda g: (
            -g["metrics"]["breadth"], -g["rotation_score"], g["group_id"])),
    }


def calculate_canonical(
    universe: dict, closes: pd.DataFrame, volumes: pd.DataFrame, registry_data: dict | None = None,
) -> tuple[dict, dict]:
    """The only place rotation numbers are calculated.

    Returns the in-memory canonical model and the (possibly extended) id
    registry.  Serialisers may rename, split or reference fields but never
    recompute them.
    """
    registry = Registry(registry_data)
    registry.register_universe(universe["members"])
    sector_id = lambda name: registry.group_id("sector", name)  # noqa: E731
    industry_id = lambda name: registry.group_id("industry", name)  # noqa: E731

    closes, volumes, metadata, unavailable = prepare_market_data(universe, closes, volumes)
    sector_raw, benchmark = raw_group_metrics(closes, volumes, metadata, "sector", MIN_MEMBERS["sector"])
    industry_raw, _ = raw_group_metrics(closes, volumes, metadata, "industry", MIN_MEMBERS["industry"])
    sectors = score_rows(sector_raw, tie_key=sector_id)
    industries = score_rows(industry_raw, tie_key=industry_id)
    sector_previous = metrics_for_date(closes, volumes, metadata, "sector", MIN_MEMBERS["sector"], -6)
    industry_previous = metrics_for_date(closes, volumes, metadata, "industry", MIN_MEMBERS["industry"], -6)
    add_score_changes(sectors, sector_previous)
    add_score_changes(industries, industry_previous)
    add_trajectories(sectors, closes, volumes, metadata, "sector", MIN_MEMBERS["sector"])
    add_trajectories(industries, closes, volumes, metadata, "industry", MIN_MEMBERS["industry"])

    stocks = stock_records(closes, volumes, metadata, benchmark["return_20d"], registry)
    parents = industry_parents(metadata, registry)
    groups = [
        group_record(row, rank, "sector", registry, None, stock_selection(stocks, sector_id(row["key"])))
        for rank, row in enumerate(sectors, start=1)
    ] + [
        group_record(row, rank, "industry", registry, parents[row["key"]], None)
        for rank, row in enumerate(industries, start=1)
    ]
    latest = closes.index[-1].strftime("%Y-%m-%d")
    canonical = {
        "as_of": latest,
        "versions": dict(VERSIONS),
        "universe": {
            "description": "S&P 500 + Nasdaq-100 securities, overlapping tickers de-duplicated",
            "counts": dict(universe["counts"]),
        },
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
            "unranked_groups": (unranked_groups(sector_raw, "sector", sector_id)
                                + unranked_groups(industry_raw, "industry", industry_id)),
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
        "groups": groups,
        "stocks": stocks,
        "roles": select_roles([g for g in groups if g["group_type"] == "sector"]),
    }
    validate_canonical(canonical)
    return canonical, registry.payload()


def serialize_v1(canonical: dict, generated_at: str) -> dict:
    """Rebuild the legacy market_rotation.json shape; no stable ids or envelope."""
    stocks = {row["stock_id"]: row for row in canonical["stocks"]}

    def stock_row(stock_id: str) -> dict:
        stock = stocks[stock_id]
        return {"ticker": stock["ticker"], "name": stock["name"],
                **{metric: stock["metrics"][metric] for metric in STOCK_METRICS}}

    def group_row(group: dict) -> dict:
        row = {"key": group["name_en"], "name": group["name_en"], "name_zh": group["name_zh"],
               "member_count": group["member_count"]}
        row.update({metric: group["metrics"][metric] for metric in GROUP_METRICS})
        row.update({f"rank_{metric}": group["ranks"][metric] for metric in SCORE_WEIGHTS})
        row.update({
            "rotation_score": group["rotation_score"],
            "quadrant": group["quadrant"],
            "quadrant_zh": QUADRANTS[group["quadrant"]],
            "score_change_5d": group["score_change_5d"],
            "trajectory": copy.deepcopy(group["trajectory"]),
        })
        if group["group_type"] == "sector":
            row["leaders"] = [stock_row(ref) for ref in group["leader_stock_ids"]]
            row["laggards"] = [stock_row(ref) for ref in group["laggard_stock_ids"]]
        return row

    coverage = copy.deepcopy(canonical["coverage"])
    coverage["unranked_groups"] = [
        {"type": row["group_type"], "key": row["name_en"], "missing_components": row["missing_components"]}
        for row in coverage["unranked_groups"]
    ]
    groups = canonical["groups"]
    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "as_of": canonical["as_of"],
        "methodology": copy.deepcopy(canonical["methodology"]),
        "sources": copy.deepcopy(canonical["sources"]),
        "coverage": coverage,
        "benchmark": copy.deepcopy(canonical["benchmark"]),
        "sectors": [group_row(g) for g in groups if g["group_type"] == "sector"],
        "industries": [group_row(g) for g in groups if g["group_type"] == "industry"],
    }


def role_cards(roles: dict[str, str | None]) -> list[dict]:
    """Merge roles held by the same group into one card with at most three evidence fields.

    Each role's primary evidence is taken before any role's secondary field,
    so a merged "leader + broadest" card still shows breadth.
    """
    held: dict[str, list[str]] = {}
    for role in ROLE_EVIDENCE:
        if roles.get(role) is not None:
            held.setdefault(roles[role], []).append(role)
    cards = []
    for group_id, group_roles in held.items():
        evidence: list[dict] = []
        for depth in range(max(len(ROLE_EVIDENCE[role]) for role in group_roles)):
            for role in group_roles:
                fields = ROLE_EVIDENCE[role]
                item = {"group_id": group_id, "field": fields[depth]} if depth < len(fields) else None
                if item and item not in evidence and len(evidence) < 3:
                    evidence.append(item)
        cards.append({"group_id": group_id, "roles": group_roles, "evidence": evidence})
    return cards


def serialize_v2(canonical: dict, generated_at: str) -> dict[str, dict]:
    """Split the canonical model into summary / groups / stocks sharing one dataset_id."""
    dataset_id = compute_dataset_id(canonical)
    sectors = [g for g in canonical["groups"] if g["group_type"] == "sector"]
    industries = [g for g in canonical["groups"] if g["group_type"] == "industry"]

    def envelope(name: str, data: dict) -> dict:
        return {
            "schema_name": f"market-rotation-{name}",
            "schema_version": 2,
            "dataset_id": dataset_id,
            "as_of": canonical["as_of"],
            "generated_at": generated_at,
            "versions": dict(canonical["versions"]),
            "data": data,
        }

    summary = {
        "status": "ready",
        "coverage": copy.deepcopy(canonical["coverage"]),
        "benchmark": copy.deepcopy(canonical["benchmark"]),
        "methodology": copy.deepcopy(canonical["methodology"]),
        "comparison_sets": {
            "sector": {"label": f"板塊內百分位｜比較{len(sectors)}大板塊", "count": len(sectors)},
            "industry": {"label": "次產業內百分位｜比較全部合格次產業", "count": len(industries),
                         "display_top_n": TOP_INDUSTRIES},
        },
        "defaults": {
            "chart_group_ids": [g["group_id"] for g in sectors[:DEFAULT_CHART_SECTORS]],
            "top_industry_ids": [g["group_id"] for g in industries[:TOP_INDUSTRIES]],
        },
        "roles": dict(canonical["roles"]),
        "cards": role_cards(canonical["roles"]),
    }
    return {
        "summary": envelope("summary", summary),
        "groups": envelope("groups", {"sectors": copy.deepcopy(sectors),
                                      "industries": copy.deepcopy(industries)}),
        "stocks": envelope("stocks", {"stocks": copy.deepcopy(canonical["stocks"])}),
    }


def v2_paths(output: Path) -> dict[str, Path]:
    return {name: output.with_name(f"market_rotation_{name}.json") for name in ("summary", "groups", "stocks")}


def build_outputs(canonical: dict, registry: dict, generated_at: str) -> dict[str, dict]:
    """Serialise every artifact and run all batch gates before anything is written.

    Returns {"v1", "summary", "groups", "stocks", "registry"} payloads that
    already passed their contracts, cross-file references and v1/v2 parity.
    """
    v1 = serialize_v1(canonical, generated_at)
    v2 = serialize_v2(canonical, generated_at)
    validate_v1(v1)
    validate_v2(v2["summary"], v2["groups"], v2["stocks"])
    check_parity(v1, v2["summary"], v2["groups"], v2["stocks"])
    validate_registry(registry)
    return {"v1": v1, **v2, "registry": registry}


def publish_outputs(outputs: dict[str, dict], output: Path, registry_path: Path) -> dict[str, bool]:
    """Replace v1, the three v2 files and the registry as one validated batch."""
    targets = {"v1": output, **v2_paths(output), "registry": registry_path}
    changed = publish_artifacts([(targets[name], outputs[name], None) for name in targets])
    return {name: changed[path] for name, path in targets.items()}


def build_payload(
    universe: dict, closes: pd.DataFrame, volumes: pd.DataFrame, registry: dict | None = None,
) -> dict:
    """Compatibility wrapper: the legacy v1 payload, serialised from the canonical model."""
    canonical, _ = calculate_canonical(universe, closes, volumes, registry)
    return serialize_v1(canonical, utc_now())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=Path, default=UNIVERSE_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH,
                        help="v1 file; v2 summary/groups/stocks are written beside it.")
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
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
    registry = json.loads(args.registry.read_text()) if args.registry.exists() else None
    canonical, registry = calculate_canonical(universe, closes, volumes, registry)
    actual_session = date.fromisoformat(canonical["as_of"])
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
    outputs = build_outputs(canonical, registry, utc_now())
    changed = publish_outputs(outputs, args.output, args.registry)
    payload = outputs["v1"]
    print(
        f"Market rotation: {payload['as_of']}, "
        f"{payload['coverage']['priced_securities']}/{payload['coverage']['universe_securities']} "
        f"securities, {len(payload['sectors'])} sectors, {len(payload['industries'])} industries, "
        f"dataset {outputs['summary']['dataset_id'][7:19]} "
        f"({', '.join(name for name, moved in changed.items() if moved) or 'unchanged'})"
    )


if __name__ == "__main__":
    main()
