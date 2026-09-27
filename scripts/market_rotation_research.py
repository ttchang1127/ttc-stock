"""Research layer for market rotation: absolute market environment, absolute
group states, concentration diagnostics and two-session confirmation.

The relative rotation score answers "which group is stronger than the
others"; it always has a winner, even when every group is falling.  This
module answers the questions the score cannot:

* is the market as a whole expanding, narrowing, rotating or retreating;
* has a group itself built a trend, or is it only falling less;
* is a group's strength broad, or carried by one company.

Every threshold below is the provisional back-test starting point written in
00_Meta/市場板塊族群輪動_初步計畫.md (sections 11.4, 13.3, 13.4, 14.5, 20.7,
21.7), not a validated rule; outputs are labelled ``rule_status: research``.

Pure pandas, no I/O.  Indicators are computed as whole time series, so the
daily builder (latest session) and the back-test (every session) share one
definition.  States only ever read data up to their own session.
"""

from __future__ import annotations

import math
import operator
from dataclasses import dataclass, field
from functools import reduce

import numpy as np
import pandas as pd

from market_rotation_contracts import GROUP_STATES, LEADERSHIP_TYPES, MARKET_STATES, RISK_TAGS

RULE_VERSION = "research-1.0"
FLAT_BAND = 0.0001  # ±1 bp counts as unchanged (plan 20.7)
CONFIRM_SESSIONS = 2
MIN_SECTOR_ISSUERS = 5
MIN_FORMAL_INDUSTRY_ISSUERS = 6
MIN_CLUE_INDUSTRY_ISSUERS = 3
MIN_CHILDREN_FOR_STRUCTURE = 3
TOP3_SHARE_MIN_ISSUERS = 6

SECTOR_STYLE = {
    "Information Technology": "growth_tech",
    "Communication Services": "growth_tech",
    "Consumer Discretionary": "growth_tech",
    "Industrials": "cyclical",
    "Materials": "cyclical",
    "Energy": "cyclical",
    "Consumer Staples": "defensive",
    "Health Care": "defensive",
    "Utilities": "defensive",
    "Financials": "financial_rate",
    "Real Estate": "financial_rate",
}
STRONG_STATES = {"confirmed_leading", "early_improvement"}
HOLDING_STATES = STRONG_STATES | {"cooling"}

THRESHOLDS = {
    "market": {
        "broad_expansion": "R20>0, R60>0, B20≥60%, B60≥55%, UDVR5≥1.1, ≥7 sectors R20>0; at least 5 of 6",
        "narrow_leadership": "R20>0 and at least 2 of: B20<50%, LWGAP≥3pp, ≤5 sectors R20>0",
        "broad_retreat": "R20<0, B20≤35%, B60≤40%, UDVR5≤0.8, ≤3 sectors R20>0; at least 4 of 5",
        "stabilizing": "R20<0 and at least 3 of: R5>0, ΔB20_5≥10pp, down-volume share falling, fewer 20-session lows",
        "rotation_divergence": "-3%≤R20≤3%, SDISP≥8pp, ≥2 sectors with A5≥0 and ≥2 with A5<0",
        "order": "insufficient_data > broad_expansion > broad_retreat > stabilizing > narrow_leadership "
                 "> rotation_divergence > neutral_mixed",
    },
    "group": {
        "confirmed_leading": "RS20>0 and RS60>0, plus 3 of 4: A5≥0, BPOS20≥60%, BMA20≥60%, P10≥60%",
        "cooling": "RS20>0, RS60>0, A5<0, and breadth or persistence below its value 5 sessions ago",
        "early_improvement": "RS20≤0, A5>0, and breadth above its value 5 sessions ago or P10≥50%",
        "unconfirmed_rebound": "RS20<0, RS60<0, A5>0",
        "clear_lagging": "RS20<0, RS60<0, A5≤0, plus 2 of 3: BPOS20<40%, BMA20<40%, P10<40%",
        "minimum_issuers": {"sector": MIN_SECTOR_ISSUERS, "industry_formal": MIN_FORMAL_INDUSTRY_ISSUERS},
    },
    "concentration": {
        "single_issuer_dominance": "group mean relative return > 0 and any of: median ≤ 0, mean without the top "
                                   "contributor ≤ 0, state falls from leading/improving without it, removal "
                                   "impact ≥ 3pp",
        "top3_positive_share": f"only for groups with at least {TOP3_SHARE_MIN_ISSUERS} issuers",
    },
    "confirmation": f"a new state must hold {CONFIRM_SESSIONS} consecutive sessions; insufficient-data sessions "
                    "freeze the previous confirmed state",
}


def pct(value, digits: int = 2):
    """Fraction -> rounded percent; None for missing or non-finite values."""
    if value is None:
        return None
    value = float(value)
    if not math.isfinite(value):
        return None
    return round(value * 100, digits) + 0.0


def num(value, digits: int = 4):
    if value is None:
        return None
    value = float(value)
    if not math.isfinite(value):
        return None
    return round(value, digits) + 0.0


def issuer_of(metadata: pd.DataFrame) -> pd.Series:
    """Ticker -> issuer key.  Dual share classes share a company name."""
    return metadata["name"].astype(str)


def representatives(metadata: pd.DataFrame) -> list[str]:
    """One ticker per issuer (alphabetically first) for breadth counts."""
    issuers = issuer_of(metadata)
    return sorted(issuers.groupby(issuers).apply(lambda group: sorted(group.index)[0]))


def by_group(frame: pd.DataFrame, mapping: pd.Series, how: str = "mean") -> pd.DataFrame:
    """Dates x tickers -> dates x groups (NaN-skipping)."""
    columns = frame.columns[frame.columns.isin(mapping.index)]
    grouped = frame[columns].T.groupby(mapping.reindex(columns))
    result = grouped.mean() if how == "mean" else grouped.sum(min_count=1)
    return result.T


def directional_volume(up: pd.DataFrame, down: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """UDVR and directional share with the plan's zero-volume rules (20.7)."""
    ratio = up / down.where(down > 0)
    ratio = ratio.mask((down <= 0) & (up <= 0))
    total = up + down
    share = (up - down) / total.where(total > 0)
    return ratio, share


@dataclass
class Panel:
    """Ticker-level indicator frames shared by every aggregate."""

    closes: pd.DataFrame
    volumes: pd.DataFrame
    metadata: pd.DataFrame
    reps: list[str] = field(init=False)

    def __post_init__(self):
        closes = self.closes
        self.reps = [ticker for ticker in representatives(self.metadata) if ticker in closes]
        self.ret = {k: closes / closes.shift(k) - 1 for k in (5, 20, 60, 120)}
        self.daily = closes.pct_change(fill_method=None)
        sma20 = closes.rolling(20, min_periods=15).mean()
        sma60 = closes.rolling(60, min_periods=45).mean()
        self.above20 = (closes > sma20).astype(float).where(closes.notna() & sma20.notna())
        self.above60 = (closes > sma60).astype(float).where(closes.notna() & sma60.notna())
        self.positive20 = (self.ret[20] > 0).astype(float).where(self.ret[20].notna())
        self.valid20 = self.ret[20].notna().astype(float)
        self.dollar_volume = closes * self.volumes
        self.liquidity = self.dollar_volume.rolling(20, min_periods=1).mean()
        high20 = closes.rolling(20, min_periods=20).max()
        low20 = closes.rolling(20, min_periods=20).min()
        self.new_high = (closes >= high20).astype(float).where(high20.notna())
        self.new_low = (closes <= low20).astype(float).where(low20.notna())
        issuers = issuer_of(self.metadata)
        issuer_daily = by_group(self.daily, issuers)
        issuer_volume = by_group(self.dollar_volume, issuers, how="sum")
        self.issuer_up = issuer_volume.where(issuer_daily > FLAT_BAND, 0.0).where(issuer_volume.notna())
        self.issuer_down = issuer_volume.where(issuer_daily < -FLAT_BAND, 0.0).where(issuer_volume.notna())
        self.issuer_sector = self.metadata.groupby(issuers)["sector"].first()
        self.issuer_industry = self.metadata.groupby(issuers)["industry"].first()


def market_series(panel: Panel) -> pd.DataFrame:
    """Absolute market evidence for every session (plan 11.2)."""
    reps = panel.reps
    out = pd.DataFrame(index=panel.closes.index)
    for k in (5, 20, 60, 120):
        out[f"R{k}"] = panel.ret[k].mean(axis=1)
    out["B20"] = panel.above20[reps].mean(axis=1)
    out["B60"] = panel.above60[reps].mean(axis=1)
    out["P20"] = panel.positive20[reps].mean(axis=1)
    out["dB20_5"] = out["B20"] - out["B20"].shift(5)
    out["new_highs"] = panel.new_high[reps].sum(axis=1, min_count=1)
    out["new_lows"] = panel.new_low[reps].sum(axis=1, min_count=1)
    out["NHNL"] = out["new_highs"] - out["new_lows"]
    total_volume = panel.dollar_volume.sum(axis=1, min_count=1)
    out["DV5_20"] = total_volume.rolling(5).mean() / total_volume.shift(5).rolling(20).mean() - 1
    up5 = panel.issuer_up.sum(axis=1, min_count=1).rolling(5).sum()
    down5 = panel.issuer_down.sum(axis=1, min_count=1).rolling(5).sum()
    ratio, share = directional_volume(up5.to_frame(), down5.to_frame())
    out["UDVR5"] = ratio.iloc[:, 0]
    out["DVS5"] = share.iloc[:, 0]
    out["down_share5"] = down5 / (up5 + down5).where((up5 + down5) > 0)
    weights = panel.liquidity.where(panel.ret[20].notna() & (panel.liquidity > 0))
    weighted = (panel.ret[20] * weights).sum(axis=1, min_count=1) / weights.sum(axis=1, min_count=1)
    out["LWGAP"] = weighted - out["R20"]
    out["market_daily"] = panel.daily.mean(axis=1)
    return out


def group_series(panel: Panel, market: pd.DataFrame, field_name: str,
                 members: dict[str, list[str]] | None = None) -> dict[str, pd.DataFrame]:
    """Per-group evidence frames (dates x groups) for ``field_name`` groups.

    ``members`` optionally overrides membership (used to recompute a group
    without its top contributor); returns use every security, breadth and
    issuer counts use one ticker per issuer.
    """
    if members is None:
        mapping = panel.metadata[field_name]
    else:
        mapping = pd.Series({ticker: group for group, tickers in members.items() for ticker in tickers})
    rep_mapping = mapping[mapping.index.isin(panel.reps)]
    frames: dict[str, pd.DataFrame] = {}
    for k in (5, 20, 60, 120):
        frames[f"R{k}"] = by_group(panel.ret[k], mapping)
        frames[f"RS{k}"] = frames[f"R{k}"].sub(market[f"R{k}"], axis=0)
    frames["A5"] = frames["RS5"] - frames["RS5"].shift(5)
    group_daily = by_group(panel.daily, mapping)
    frames["P10"] = group_daily.gt(market["market_daily"], axis=0).astype(float).rolling(10).mean()
    frames["BPOS20"] = by_group(panel.positive20, rep_mapping)
    frames["BMA20"] = by_group(panel.above20, rep_mapping)
    frames["issuers"] = by_group(panel.valid20, rep_mapping, how="sum").fillna(0)
    frames["breadth"] = (frames["BPOS20"] + frames["BMA20"]) / 2
    weights = panel.liquidity.where(panel.ret[20].notna() & (panel.liquidity > 0))
    weighted = by_group(panel.ret[20] * weights, mapping, how="sum") / by_group(weights, mapping, how="sum")
    frames["LWGAP"] = weighted - frames["R20"]
    volume = by_group(panel.dollar_volume, mapping, how="sum")
    frames["volume_expansion"] = volume.rolling(5).mean() / volume.shift(5).rolling(20).mean() - 1
    if members is None:
        issuer_group = panel.issuer_sector if field_name == "sector" else panel.issuer_industry
        up = by_group(panel.issuer_up, issuer_group, how="sum").rolling(5).sum()
        down = by_group(panel.issuer_down, issuer_group, how="sum").rolling(5).sum()
        frames["UDVR5"], frames["DVS5"] = directional_volume(up, down)
    return frames


def market_checks(row: pd.Series, sector_r20: pd.Series, sector_a5: pd.Series,
                  previous: pd.Series | None) -> dict[str, dict]:
    """Criteria of every market state for one session, each marked pass/fail."""
    positive_sectors = int((sector_r20 > 0).sum())

    def check(code, value, passed, display=None):
        return {"code": code, "value": value, "passed": bool(passed), "display": display}

    r5, r20, r60 = row["R5"], row["R20"], row["R60"]
    b20, b60, udvr = row["B20"], row["B60"], row["UDVR5"]
    down_share_falling = (previous is not None and pd.notna(previous.get("down_share5"))
                          and pd.notna(row["down_share5"]) and row["down_share5"] < previous["down_share5"])
    lows_falling = (previous is not None and pd.notna(previous.get("new_lows"))
                    and pd.notna(row["new_lows"]) and row["new_lows"] < previous["new_lows"])
    improving = int((sector_a5 >= 0).sum())
    weakening = int((sector_a5 < 0).sum())
    sdisp = (sector_r20.quantile(0.75) - sector_r20.quantile(0.25)) if len(sector_r20) else np.nan
    gt = lambda a, b: pd.notna(a) and a > b  # noqa: E731
    ge = lambda a, b: pd.notna(a) and a >= b  # noqa: E731
    lt = lambda a, b: pd.notna(a) and a < b  # noqa: E731
    le = lambda a, b: pd.notna(a) and a <= b  # noqa: E731
    return {
        "broad_expansion": {"required": 5, "checks": [
            check("R20>0", pct(r20), gt(r20, 0)), check("R60>0", pct(r60), gt(r60, 0)),
            check("B20≥60%", pct(b20), ge(b20, 0.60)), check("B60≥55%", pct(b60), ge(b60, 0.55)),
            check("UDVR5≥1.1", num(udvr, 3), ge(udvr, 1.1)),
            check("≥7 sectors R20>0", positive_sectors, positive_sectors >= 7)]},
        "broad_retreat": {"required": 4, "checks": [
            check("R20<0", pct(r20), lt(r20, 0)), check("B20≤35%", pct(b20), le(b20, 0.35)),
            check("B60≤40%", pct(b60), le(b60, 0.40)), check("UDVR5≤0.8", num(udvr, 3), le(udvr, 0.8)),
            check("≤3 sectors R20>0", positive_sectors, positive_sectors <= 3)]},
        "stabilizing": {"required": 3, "gate": check("R20<0", pct(r20), lt(r20, 0)), "checks": [
            check("R5>0", pct(r5), gt(r5, 0)), check("ΔB20_5≥10pp", pct(row["dB20_5"]), ge(row["dB20_5"], 0.10)),
            check("down-volume share falling", pct(row["down_share5"]), down_share_falling),
            check("fewer 20-session lows", num(row["new_lows"], 0), lows_falling)]},
        "narrow_leadership": {"required": 2, "gate": check("R20>0", pct(r20), gt(r20, 0)), "checks": [
            check("B20<50%", pct(b20), lt(b20, 0.50)), check("LWGAP≥3pp", pct(row["LWGAP"]), ge(row["LWGAP"], 0.03)),
            check("≤5 sectors R20>0", positive_sectors, positive_sectors <= 5)]},
        "rotation_divergence": {"required": 3, "checks": [
            check("-3%≤R20≤3%", pct(r20), pd.notna(r20) and -0.03 <= r20 <= 0.03),
            check("SDISP≥8pp", pct(sdisp), ge(sdisp, 0.08)),
            check("≥2 sectors A5≥0 and ≥2 A5<0", f"{improving}/{weakening}", improving >= 2 and weakening >= 2)]},
    }


def market_raw_state(checks: dict[str, dict], has_data: bool) -> str:
    if not has_data:
        return "insufficient_data"
    for state in ("broad_expansion", "broad_retreat", "stabilizing", "narrow_leadership", "rotation_divergence"):
        spec = checks[state]
        if "gate" in spec and not spec["gate"]["passed"]:
            continue
        if sum(item["passed"] for item in spec["checks"]) >= spec["required"]:
            return state
    return "neutral_mixed"


def market_states(market: pd.DataFrame, sectors: dict[str, pd.DataFrame]) -> tuple[pd.Series, list[dict]]:
    """Raw market state and its criteria for every session."""
    states, all_checks = [], []
    required = ["R5", "R20", "R60", "B20", "B60", "UDVR5", "dB20_5"]
    for position, (day, row) in enumerate(market.iterrows()):
        previous = market.iloc[position - 5] if position >= 5 else None
        sector_r20 = sectors["R20"].loc[day].dropna()
        sector_a5 = sectors["A5"].loc[day].dropna()
        checks = market_checks(row, sector_r20, sector_a5, previous)
        has_data = all(pd.notna(row[name]) for name in required) and len(sector_r20) >= 8
        states.append(market_raw_state(checks, has_data))
        all_checks.append(checks)
    return pd.Series(states, index=market.index), all_checks


def group_raw_states(frames: dict[str, pd.DataFrame], min_issuers: int,
                     clue_issuers: int | None = None) -> pd.DataFrame:
    """Mutually exclusive group states in the plan's priority order (13.3)."""
    rs20, rs60, a5 = frames["RS20"], frames["RS60"], frames["A5"]
    bpos, bma, p10, breadth = frames["BPOS20"], frames["BMA20"], frames["P10"], frames["breadth"]
    breadth_prior, p10_prior = breadth.shift(5), p10.shift(5)
    missing = reduce(operator.or_, (frame.isna() for frame in
                                    (rs20, rs60, a5, bpos, bma, p10, breadth_prior, p10_prior)))
    leading_votes = ((a5 >= 0).astype(int) + (bpos >= 0.6).astype(int)
                     + (bma >= 0.6).astype(int) + (p10 >= 0.6).astype(int))
    lagging_votes = (bpos < 0.4).astype(int) + (bma < 0.4).astype(int) + (p10 < 0.4).astype(int)
    trend = (rs20 > 0) & (rs60 > 0)
    down = (rs20 < 0) & (rs60 < 0)
    conditions = [
        missing | (frames["issuers"] < (clue_issuers or min_issuers)),
        frames["issuers"] < min_issuers,
        trend & (leading_votes >= 3),
        trend & (a5 < 0) & ((breadth < breadth_prior) | (p10 < p10_prior)),
        (rs20 <= 0) & (a5 > 0) & ((breadth > breadth_prior) | (p10 >= 0.5)),
        down & (a5 > 0),
        down & (a5 <= 0) & (lagging_votes >= 2),
    ]
    choices = ["insufficient_data", "small_sample_clue", "confirmed_leading", "cooling",
               "early_improvement", "unconfirmed_rebound", "clear_lagging"]
    values = np.select([c.to_numpy() for c in conditions], choices, default="neutral_mixed")
    return pd.DataFrame(values, index=rs20.index, columns=rs20.columns)


def confirm(raw: pd.Series, sessions: int = CONFIRM_SESSIONS) -> pd.DataFrame:
    """Two-session confirmation walk over one raw-state series (plan 11.5, 13.5).

    Only earlier sessions are read.  ``insufficient_data`` freezes the
    confirmed state and the pending count; a still-running first state is
    marked ``since_is_lower_bound`` because its real start predates the data.
    """
    rows = []
    confirmed = since = pending = None
    pending_days = 0
    lower_bound = False
    for day, state in raw.items():
        if state in ("insufficient_data", None):
            pass
        elif confirmed is None:
            confirmed, since, lower_bound = state, day, True
        elif state == confirmed:
            pending, pending_days = None, 0
        elif state == pending:
            pending_days += 1
            if pending_days >= sessions:
                confirmed, since, lower_bound = state, day, False
                pending, pending_days = None, 0
        else:
            pending, pending_days = state, 1
        rows.append({"raw": state, "confirmed": confirmed, "pending": pending,
                     "pending_days": pending_days, "since": since, "since_is_lower_bound": lower_bound})
    frame = pd.DataFrame(rows, index=raw.index, dtype=object)
    positions = pd.Series(range(len(frame)), index=frame.index)
    frame["days_in_state"] = [
        None if day is None else position - positions[day] + 1
        for position, day in zip(positions, frame["since"])
    ]
    return frame


def confirm_frame(raw: pd.DataFrame, sessions: int = CONFIRM_SESSIONS) -> dict[str, pd.DataFrame]:
    return {group: confirm(raw[group], sessions) for group in raw.columns}


def missing(value) -> bool:
    return value is None or (not isinstance(value, str) and pd.isna(value))


def state_record(walk: pd.DataFrame, labels: dict[str, str]) -> dict:
    last = {key: (None if missing(value) else value) for key, value in walk.iloc[-1].items()}
    since = last["since"]
    return {
        "raw": last["raw"],
        "raw_label": labels.get(last["raw"]),
        "confirmed": last["confirmed"],
        "confirmed_label": labels.get(last["confirmed"]),
        "pending": last["pending"],
        "pending_label": labels.get(last["pending"]),
        "pending_days": int(last["pending_days"]),
        "confirm_sessions": CONFIRM_SESSIONS,
        "since": since.strftime("%Y-%m-%d") if since is not None else None,
        "since_is_lower_bound": bool(last["since_is_lower_bound"]),
        "days_in_state": int(last["days_in_state"]) if last["days_in_state"] is not None else None,
    }


def leadership(sector_rs20: pd.Series) -> dict:
    """Leadership modifier: the style shared by at least two of the top three sectors."""
    ranked = sector_rs20.dropna().sort_values(ascending=False)
    top = [name for name in ranked.index[:3] if ranked[name] > 0]
    styles = pd.Series([SECTOR_STYLE.get(name, "none") for name in top], dtype=object)
    counts = styles.value_counts()
    style = counts.index[0] if len(counts) and counts.iloc[0] >= 2 and counts.index[0] != "none" else "none"
    return {"type": style, "label": LEADERSHIP_TYPES[style], "top_sectors": top}


def concentration(panel: Panel, market: pd.DataFrame, field_name: str, group: str,
                  full_state: str, min_issuers: int) -> dict:
    """Is the group's latest 20-session strength carried by one company? (plan 14.5)"""
    day = panel.closes.index[-1]
    issuers = issuer_of(panel.metadata)
    tickers = [t for t in panel.metadata.index[panel.metadata[field_name] == group] if t in panel.closes]
    reps = [t for t in tickers if t in panel.reps]
    relative = (panel.ret[20].loc[day, reps] - market.loc[day, "R20"]).dropna()
    n = len(relative)
    result = {"basis": "one ticker per issuer; 20-session return relative to the combined universe",
              "issuers": n, "mean_relative_20d": None, "median_relative_20d": None,
              "top_contributor": None, "top1_removal_impact_pp": None, "mean_without_top1": None,
              "state_without_top1": None, "top3_positive_share": None, "single_issuer_dominance": False,
              "reasons": []}
    if n == 0:
        return result
    mean, median = float(relative.mean()), float(relative.median())
    result["mean_relative_20d"], result["median_relative_20d"] = pct(mean), pct(median)
    positive = relative[relative > 0].sort_values(ascending=False)
    if n >= TOP3_SHARE_MIN_ISSUERS and positive.sum() > 0:
        result["top3_positive_share"] = pct(positive.iloc[:3].sum() / positive.sum(), 1)
    if mean <= 0 or n < 2:
        return result
    top = relative.sort_values(ascending=False).index[0]
    rest = relative.drop(top)
    without = float(rest.mean())
    result["top_contributor"] = {"ticker": top, "issuer": issuers[top], "relative_20d": pct(relative[top])}
    result["top1_removal_impact_pp"] = pct(mean - without)
    result["mean_without_top1"] = pct(without)

    drop = set(issuers[issuers == issuers[top]].index)
    remaining = {group: [t for t in tickers if t not in drop]}
    frames = group_series(panel, market, field_name, members=remaining)
    state_without = group_raw_states(frames, max(min_issuers - 1, 2)).iloc[-1][group]
    result["state_without_top1"] = state_without

    reasons = []
    if median <= 0:
        reasons.append("median_not_positive")
    if without <= 0:
        reasons.append("negative_without_top1")
    if (full_state in STRONG_STATES and state_without not in HOLDING_STATES
            and state_without not in ("insufficient_data", "small_sample_clue")):
        reasons.append("state_falls_without_top1")
    if mean - without >= 0.03:
        reasons.append("removal_impact_ge_3pp")
    result["reasons"] = reasons
    result["single_issuer_dominance"] = bool(reasons)
    return result


def risk_tags(evidence: dict, state: dict, concentration_row: dict, small: bool) -> list[str]:
    tags = []
    positive = evidence["RS20"] is not None and evidence["RS20"] > 0
    if positive and evidence["R20"] is not None and evidence["R20"] < 0:
        tags.append("relative_only")
    if positive and concentration_row["single_issuer_dominance"]:
        tags.append("single_issuer_dominance")
    if positive and ((evidence["BPOS20"] is not None and evidence["BPOS20"] < 50)
                     or (evidence["LWGAP"] is not None and evidence["LWGAP"] >= 3)):
        tags.append("liquidity_concentration")
    if positive and ((evidence["DVS5"] is not None and evidence["DVS5"] <= 0)
                     or (evidence["volume_expansion"] is not None and evidence["volume_expansion"] <= 0)):
        tags.append("volume_unconfirmed")
    if small:
        tags.append("small_sample")
    if state["pending"] is not None:
        tags.append("pending_change")
    return tags


def latest_evidence(frames: dict[str, pd.DataFrame], group: str) -> dict:
    day = frames["RS20"].index[-1]
    value = lambda name, position=-1: frames[name][group].iloc[position]  # noqa: E731
    evidence = {name: pct(value(name)) for name in (
        "R20", "RS5", "RS20", "RS60", "RS120", "A5", "BPOS20", "BMA20", "P10", "LWGAP", "volume_expansion")}
    evidence["breadth_5d_ago"] = pct(frames["breadth"][group].iloc[-6]) if len(frames["breadth"]) > 5 else None
    evidence["P10_5d_ago"] = pct(frames["P10"][group].iloc[-6]) if len(frames["P10"]) > 5 else None
    evidence["issuers"] = int(frames["issuers"].loc[day, group])
    if "DVS5" in frames:
        evidence["DVS5"] = num(value("DVS5"), 3)
        evidence["UDVR5"] = num(value("UDVR5"), 3)
    else:
        evidence["DVS5"] = evidence["UDVR5"] = None
    return evidence


def market_record(market: pd.DataFrame, walk: pd.DataFrame, checks: dict, sectors: dict[str, pd.DataFrame],
                  panel: Panel, coverage_pct: float) -> dict:
    row = market.iloc[-1]
    day = market.index[-1]
    indexes = {}
    for index_name in ("S&P 500", "Nasdaq-100"):
        tickers = [t for t in panel.metadata.index if index_name in panel.metadata.loc[t, "indexes"]]
        reps = [t for t in tickers if t in panel.reps]
        indexes[index_name] = {
            "securities": len(tickers),
            "return_20d": pct(panel.ret[20].loc[day, tickers].mean()) if tickers else None,
            "breadth_above_ma20": pct(panel.above20.loc[day, reps].mean()) if reps else None,
        }
    both = indexes["S&P 500"], indexes["Nasdaq-100"]
    gap = {key: (round(both[1][key] - both[0][key], 2) if None not in (both[0][key], both[1][key]) else None)
           for key in ("return_20d", "breadth_above_ma20")}
    state = state_record(walk, MARKET_STATES)
    shown = state["confirmed"] or state["raw"]
    spec = checks.get(shown)
    return {
        "evidence": {
            "R5": pct(row["R5"]), "R20": pct(row["R20"]), "R60": pct(row["R60"]), "R120": pct(row["R120"]),
            "B20": pct(row["B20"]), "B60": pct(row["B60"]), "P20": pct(row["P20"]), "dB20_5": pct(row["dB20_5"]),
            "new_highs": num(row["new_highs"], 0), "new_lows": num(row["new_lows"], 0),
            "NHNL": num(row["NHNL"], 0), "DV5_20": pct(row["DV5_20"]), "UDVR5": num(row["UDVR5"], 3),
            "DVS5": num(row["DVS5"], 3), "LWGAP": pct(row["LWGAP"]),
            "sectors_positive_20d": int((sectors["R20"].iloc[-1] > 0).sum()),
            "SDISP": pct(sectors["R20"].iloc[-1].quantile(0.75) - sectors["R20"].iloc[-1].quantile(0.25)),
            "SBR": pct(sectors["BMA20"].iloc[-1].median()),
        },
        "indexes": indexes,
        "nasdaq_minus_sp500": gap,
        "state": state,
        "leadership": leadership(sectors["RS20"].iloc[-1]),
        "confidence": "high" if coverage_pct >= 95 else "low",
        "checks": {name: spec for name, spec in checks.items()},
        "shown_state_checks": spec,
    }


def children_structure(industry_states: dict[str, str], parents: dict[str, str], formal: set[str],
                       sector: str) -> dict:
    """Child-industry confirmation for a sector (plan 21.7)."""
    children = [name for name in formal if parents.get(name) == sector]
    counts = {state: 0 for state in ("confirmed_leading", "early_improvement", "cooling", "clear_lagging")}
    for name in children:
        if industry_states[name] in counts:
            counts[industry_states[name]] += 1
    if len(children) < MIN_CHILDREN_FOR_STRUCTURE:
        return {"formal_child_count": len(children), **counts, "child_confirmation_pct": None,
                "structure": "insufficient_children"}
    share = (counts["confirmed_leading"] + counts["early_improvement"]) / len(children)
    structure = "broad" if share >= 0.6 else "mixed" if share >= 0.3 else "concentrated"
    return {"formal_child_count": len(children), **counts, "child_confirmation_pct": pct(share, 1),
            "structure": structure}


def compute_research(closes: pd.DataFrame, volumes: pd.DataFrame, metadata: pd.DataFrame,
                     coverage_pct: float, industry_parents: dict[str, str]) -> dict:
    """Latest-session research record built from full indicator histories."""
    panel = Panel(closes, volumes, metadata)
    market = market_series(panel)
    sectors = group_series(panel, market, "sector")
    industries = group_series(panel, market, "industry")
    market_raw, checks = market_states(market, sectors)
    market_walk = confirm(market_raw)
    sector_walks = confirm_frame(group_raw_states(sectors, MIN_SECTOR_ISSUERS))
    industry_walks = confirm_frame(group_raw_states(
        industries, MIN_FORMAL_INDUSTRY_ISSUERS, clue_issuers=MIN_CLUE_INDUSTRY_ISSUERS))

    industry_state = {name: walk.iloc[-1]["confirmed"] or walk.iloc[-1]["raw"]
                      for name, walk in industry_walks.items()}
    formal = {name for name in industries["issuers"].columns
              if industries["issuers"][name].iloc[-1] >= MIN_FORMAL_INDUSTRY_ISSUERS}

    groups = []
    for field_name, frames, walks, min_issuers in (
            ("sector", sectors, sector_walks, MIN_SECTOR_ISSUERS),
            ("industry", industries, industry_walks, MIN_FORMAL_INDUSTRY_ISSUERS)):
        for name in sorted(walks):
            walk = walks[name]
            state = state_record(walk, GROUP_STATES)
            if state["raw"] == "insufficient_data" and state["confirmed"] is None:
                continue
            evidence = latest_evidence(frames, name)
            shown = state["confirmed"] or state["raw"]
            conc = concentration(panel, market, field_name, name, shown, min_issuers)
            record = {
                "group_type": field_name,
                "name_en": name,
                "evidence": evidence,
                "state": state,
                "concentration": conc,
                "risk_tags": risk_tags(evidence, state, conc, evidence["issuers"] < min_issuers),
            }
            if field_name == "sector":
                record["children"] = children_structure(industry_state, industry_parents, formal, name)
            else:
                parent = industry_parents.get(name)
                parent_r20 = sectors["R20"][parent].iloc[-1] if parent in sectors["R20"] else np.nan
                record["relative_to_parent_20d"] = pct(frames["R20"][name].iloc[-1] - parent_r20)
                record["formal"] = name in formal
            groups.append(record)

    return {
        "rule_version": RULE_VERSION,
        "rule_status": "research",
        "as_of": closes.index[-1].strftime("%Y-%m-%d"),
        "history_basis": {
            "sessions": len(closes),
            "start": closes.index[0].strftime("%Y-%m-%d"),
            "note": "States are recomputed each run from the downloaded price window with today's universe; "
                    "a state still running at the window start has since_is_lower_bound=true.",
        },
        "market": market_record(market, market_walk, checks[-1], sectors, panel, coverage_pct),
        "groups": groups,
        "labels": {"market_states": MARKET_STATES, "group_states": GROUP_STATES, "risk_tags": RISK_TAGS,
                   "leadership": LEADERSHIP_TYPES},
        "thresholds": THRESHOLDS,
    }


def state_history(closes: pd.DataFrame, volumes: pd.DataFrame, metadata: pd.DataFrame,
                  confirm_sessions: int = CONFIRM_SESSIONS) -> dict:
    """Every session's market and sector states plus the series a back-test needs."""
    panel = Panel(closes, volumes, metadata)
    market = market_series(panel)
    sectors = group_series(panel, market, "sector")
    market_raw, _ = market_states(market, sectors)
    return {
        "panel": panel,
        "market": market,
        "sectors": sectors,
        "market_walk": confirm(market_raw, confirm_sessions),
        "sector_walks": confirm_frame(group_raw_states(sectors, MIN_SECTOR_ISSUERS), confirm_sessions),
    }
