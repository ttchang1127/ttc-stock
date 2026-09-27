"""Direct-equity exposure of the actual portfolio, joined to rotation states.

Plan chapters 22-23.  Answers "which sectors and industries do my stocks
really sit in, and what is the rotation state there?"  It never says how
much to buy or sell: every research action is a reading priority.

* only direct equities count; funds listed in portfolio_classification.json
  (VGT, VOO) are excluded from every denominator;
* weights use market value (shares x latest close), never cost;
* stocks outside the S&P 500 / Nasdaq-100 universe need a reviewed manual
  classification; anything unclassified makes the exposure incomplete;
* a price more than 3 market sessions behind blocks the conclusion.

Standard library only.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from market_calendar import market_session_lag
from market_rotation_contracts import GROUP_STATES

STALE_SESSIONS = 3
MAJORITY_SECTOR = 0.5
MEANINGFUL_WEIGHT_CHANGE = 0.02  # 2pp of direct-equity value
DETERIORATING = {"cooling", "clear_lagging"}
NOT_AN_ACTION = "研究優先度，不是買進、賣出或調整部位的指令"
PRIORITY_ORDER = {"data_blocked": 0, "review_now": 1, "monitor": 2}


def classify(universe: dict, overrides: dict) -> dict[str, dict]:
    """Ticker -> {sector, industry, source} from the universe, then reviewed overrides."""
    result = {row["ticker"]: {"sector": row["sector"], "industry": row["industry"],
                              "source": f"{row['classification']}（{'／'.join(row['indexes'])} 成分）"}
              for row in universe["members"]}
    for ticker, row in overrides.get("classification", {}).items():
        result[ticker] = {"sector": row["sector"], "industry": row["industry"],
                          "source": f"人工分類（覆核 {row['reviewed_at']}）：{row['reason']}"}
    return result


def hhi(weights: list[float]) -> float:
    return sum(weight * weight for weight in weights)


def effective_count(weights: list[float]) -> float | None:
    concentration = hhi(weights)
    return round(1 / concentration, 2) if concentration else None


def pct(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value * 100, digits) + 0.0


def group_lookup(registry: dict) -> dict[tuple[str, str], str]:
    ids = {}
    for row in registry["groups"]:
        for name in (row["name_en"], *row["aliases"]):
            ids[(row["group_type"], name)] = row["group_id"]
    return ids


def rotation_view(group: dict | None) -> dict:
    """The part of a research group record a holding needs."""
    if not group:
        return {"state": None, "state_label": "無研究資料", "pending": None, "risk_tags": [],
                "relative_20d": None, "own_return_20d": None, "top_contributor": None}
    state = group["state"]
    shown = state["confirmed"] or state["raw"]
    top = (group.get("concentration") or {}).get("top_contributor") or {}
    return {
        "state": shown,
        "state_label": GROUP_STATES.get(shown, shown),
        "confirmed": state["confirmed"] is not None,
        "days_in_state": state["days_in_state"],
        "pending": state["pending"],
        "pending_label": GROUP_STATES.get(state["pending"]) if state["pending"] else None,
        "risk_tags": group["risk_tags"],
        "relative_20d": group["evidence"]["RS20"],
        "own_return_20d": group["evidence"]["R20"],
        "top_contributor": top.get("ticker"),
        "single_issuer_dominance": (group.get("concentration") or {}).get("single_issuer_dominance", False),
    }


def research_action(position: dict) -> tuple[str, list[str]]:
    """Reading priority for one actual holding (plan 22.3, 22.7)."""
    if position["price_status"] != "ok":
        return "data_blocked", [f"股價資料{'過期' if position['price_status'] == 'stale' else '缺漏'}，不產生輪動判讀"]
    sector, industry = position["sector_rotation"], position["industry_rotation"]
    if sector["state"] is None:
        return "data_blocked", ["所屬板塊沒有研究層資料"]
    reasons = []
    for level, view in (("板塊", sector), ("次產業", industry)):
        if view["state"] in DETERIORATING and view.get("confirmed"):
            days = view.get("days_in_state")
            suffix = f"（{days} 個交易日）" if days else ""
            reasons.append(f"所屬{level}已確認「{view['state_label']}」{suffix}：覆核投資論點是否仍成立")
    if reasons:
        return "review_now", reasons
    for level, view in (("板塊", sector), ("次產業", industry)):
        if view.get("pending"):
            reasons.append(f"所屬{level}可能轉為「{view['pending_label']}」，待確認")
        if view.get("single_issuer_dominance") and view.get("top_contributor") == position["ticker"]:
            reasons.append(f"本身是所屬{level}強勢的最大貢獻者：板塊強勢主要靠它，不代表同業普遍走強")
        if "relative_only" in view.get("risk_tags", []):
            reasons.append(f"所屬{level}只是跌得比大盤少，本身仍在下跌")
    if sector["state"] == "confirmed_leading":
        reasons.append("所屬板塊已確認領先：留意估值與追價風險，強勢不代表風險消失")
    return "monitor", reasons or [f"所屬板塊目前「{sector['state_label']}」，沒有需要立即覆核的變化"]


def build_exposure(holdings: dict, prices: dict, universe: dict, overrides: dict, registry: dict,
                   research: dict | None, previous: dict | None = None,
                   names: dict[str, str] | None = None) -> dict:
    """``names`` maps group ids to display names (the v2 groups file's name_zh)."""
    names = names or {}
    classes = classify(universe, overrides)
    funds = set(overrides.get("funds_excluded", {}))
    ids = group_lookup(registry)
    groups = {row["group_id"]: row for row in (research or {}).get("data", {}).get("groups", [])}
    series = prices["series"]

    direct = [row for row in holdings["holdings"] if row["ticker"] not in funds]
    latest_dates = [series[row["ticker"]]["dates"][-1] for row in direct if row["ticker"] in series]
    reference = max(latest_dates) if latest_dates else None

    positions, unclassified = [], []
    for row in direct:
        ticker = row["ticker"]
        klass = classes.get(ticker)
        if klass is None:
            unclassified.append(ticker)
            continue
        data = series.get(ticker)
        price, price_date, status = None, None, "missing"
        if data and data["closes"]:
            price, price_date = data["closes"][-1], data["dates"][-1]
            lag = market_session_lag(date.fromisoformat(price_date), date.fromisoformat(reference))
            status = "stale" if lag > STALE_SESSIONS else "ok"
        sector_id = ids.get(("sector", klass["sector"]))
        industry_id = ids.get(("industry", klass["industry"]))
        positions.append({
            "ticker": ticker,
            "shares": row["shares"],
            "price": price,
            "price_date": price_date,
            "price_status": status,
            "market_value": round(row["shares"] * price, 2) if price is not None else None,
            "sector": klass["sector"],
            "sector_zh": names.get(sector_id, klass["sector"]),
            "sector_id": sector_id,
            "industry": klass["industry"],
            "industry_id": industry_id,
            "classification_source": klass["source"],
            "sector_rotation": rotation_view(groups.get(sector_id)),
            "industry_rotation": rotation_view(groups.get(industry_id)),
        })

    priced = [p for p in positions if p["market_value"] is not None]
    total = sum(p["market_value"] for p in priced)
    for position in positions:
        position["weight"] = pct(position["market_value"] / total) if position["market_value"] and total else None
        position["research_priority"], position["reasons"] = research_action(position)
        position["not_an_action"] = NOT_AN_ACTION

    def grouped(key: str) -> list[dict]:
        buckets: dict[str, dict] = {}
        for position in priced:
            bucket = buckets.setdefault(position[key], {
                "name": position[key], "name_zh": names.get(position[f"{key}_id"], position[key]),
                "group_id": position[f"{key}_id"], "value": 0.0, "tickers": [],
                "rotation": position[f"{key}_rotation"]})
            bucket["value"] += position["market_value"]
            bucket["tickers"].append(position["ticker"])
        rows = sorted(buckets.values(), key=lambda row: (-row["value"], row["name"]))
        for row in rows:
            row["weight"] = pct(row.pop("value") / total) if total else None
        return rows

    sectors, industries = grouped("sector"), grouped("industry")
    weights = [p["market_value"] / total for p in priced] if total else []
    ranked = sorted(priced, key=lambda p: -p["market_value"])
    review = []
    if sectors and sectors[0]["weight"] is not None and sectors[0]["weight"] > MAJORITY_SECTOR * 100:
        review.append(f"{sectors[0]['name_zh']} 占直接個股 {sectors[0]['weight']:.1f}%，超過一半："
                      "同一個板塊的輪動變化會同時影響多數持股")
    result = {
        "schema_version": 1,
        "scope": "direct_equities_only",
        "excluded_funds": sorted(funds & {row["ticker"] for row in holdings["holdings"]}),
        "currency": holdings.get("currency", "USD"),
        "holdings_updated_at": holdings.get("updated_at"),
        "price_as_of": reference,
        "research_as_of": (research or {}).get("as_of"),
        "coverage": {
            "total_positions": len(direct),
            "priced_positions": len(priced),
            "stale_positions": sorted(p["ticker"] for p in positions if p["price_status"] == "stale"),
            "unclassified": sorted(unclassified),
            "complete": len(priced) == len(direct) and not unclassified,
        },
        "issuer_concentration": {
            "top1": {"ticker": ranked[0]["ticker"], "weight": ranked[0]["weight"]} if ranked else None,
            "top3_weight": pct(sum(p["market_value"] for p in ranked[:3]) / total) if total else None,
            "effective_positions": effective_count(weights),
        },
        "sector_concentration": {
            "effective_sectors": effective_count([(row["weight"] or 0) / 100 for row in sectors]),
            "sectors": sectors,
        },
        "industries": industries,
        "positions": sorted(positions, key=lambda p: (PRIORITY_ORDER[p["research_priority"]],
                                                      -(p["market_value"] or 0), p["ticker"])),
        "needs_review": review,
        "changes": weight_changes(previous, positions, sectors),
        "not_an_action": NOT_AN_ACTION,
    }
    return result


def weight_changes(previous: dict | None, positions: list[dict], sectors: list[dict]) -> list[dict]:
    """Sector weight moves of at least 2pp, attributed to trades or price drift (plan 23.8)."""
    if not previous:
        return []
    before_shares = {p["ticker"]: p["shares"] for p in previous.get("positions", [])}
    now_shares = {p["ticker"]: p["shares"] for p in positions}
    cause = "holding_change" if before_shares != now_shares else "market_drift"
    before = {row["name"]: row["weight"] or 0 for row in previous.get("sector_concentration", {}).get("sectors", [])}
    changes = []
    for row in sectors:
        old, new = before.get(row["name"], 0.0), row["weight"] or 0.0
        if abs(new - old) >= MEANINGFUL_WEIGHT_CHANGE * 100:
            changes.append({"sector": row["name"], "from": old, "to": new, "delta_pp": round(new - old, 2),
                            "cause": cause, "tickers": row["tickers"]})
    for name, old in before.items():
        if name not in {row["name"] for row in sectors} and old >= MEANINGFUL_WEIGHT_CHANGE * 100:
            changes.append({"sector": name, "from": old, "to": 0.0, "delta_pp": -old, "cause": "holding_change",
                            "tickers": []})
    return changes


def holdings_by_group(exposure: dict) -> dict[str, list[str]]:
    """Group id -> tickers held directly in it (sector and industry)."""
    result: dict[str, list[str]] = {}
    for position in exposure.get("positions", []):
        for key in ("sector_id", "industry_id"):
            if position.get(key):
                result.setdefault(position[key], []).append(position["ticker"])
    return {key: sorted(value) for key, value in result.items()}


def summary_line(exposure: dict) -> str | None:
    """'資訊科技 73.1%（強勢降溫）' for the largest sector, or None."""
    sectors = exposure.get("sector_concentration", {}).get("sectors") or []
    if not sectors:
        return None
    top = sectors[0]
    return f"{top['name_zh']} {top['weight']:.1f}%（{top['rotation']['state_label']}）"


def action_counts(exposure: dict) -> dict[str, Any]:
    counts = {key: 0 for key in PRIORITY_ORDER}
    for position in exposure.get("positions", []):
        counts[position["research_priority"]] += 1
    return counts
