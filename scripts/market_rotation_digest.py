"""Daily market-rotation digest: only what changed since the previous session.

Plan chapter 17 and sections 35.8-35.9.  Compares the latest A-quality
snapshot with earlier ones and reports:

* P1: the confirmed market state changed;
* P2: a sector's (or formal industry's) confirmed state changed, the
  market's leadership type changed, or a concentration risk appeared or
  cleared after holding two sessions;
* P3: a state change is pending (first session only), shown on the page
  but never notified.

Rank or score moves, another day in the same state and one-day blips are
not events.  The first snapshot, or a change of rule version, only sets a
silent baseline.  Event ids are stable, so reruns never notify twice.

Standard library only.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from market_rotation_contracts import GROUP_STATES, LEADERSHIP_TYPES, MARKET_STATES, RISK_TAGS

RISK_EVENTS = ("single_issuer_dominance", "relative_only", "liquidity_concentration")
FORMAL_INDUSTRY_ISSUERS = 6
HEADLINE_LIMIT = 5
SCOPE_ORDER = {"market": 0, "sector": 1, "industry": 2}
NOT_A_SIGNAL = "輪動是研究排序，不是買賣訊號"


def event_id(current: dict, scope: str, entity: str, change: str, before: Any, after: Any) -> str:
    material = [current["calculation_version"], current["research_rules"], scope, entity, change,
                before, after, current["as_of"]]
    return "rot-" + hashlib.sha256(json.dumps(material, ensure_ascii=False).encode()).hexdigest()[:16]


def label(state: str | None, labels: dict) -> str:
    return labels.get(state, state) if state else "—"


def group_evidence(row: dict) -> dict:
    return {key: row.get(key) for key in ("RS20", "RS60", "A5", "BPOS20", "BMA20", "R20")}


def build_events(current: dict, previous: list[dict], names: dict[str, dict],
                 holdings: dict[str, list[str]]) -> list[dict]:
    prev = previous[-1]
    before2 = previous[-2] if len(previous) >= 2 else None
    events = []

    def add(priority, scope, entity, change, before, after, text, evidence=None, related=None):
        events.append({
            "event_id": event_id(current, scope, entity, change, before, after),
            "priority": priority,
            "scope": scope,
            "entity_id": entity,
            "name": names.get(entity, {}).get("name_zh", entity) if scope != "market" else "整體市場",
            "change_type": change,
            "from_state": before,
            "to_state": after,
            "as_of": current["as_of"],
            "compared_with": prev["as_of"],
            "text": text,
            "evidence": evidence or {},
            "related_holdings": related or [],
        })

    market, market_prev = current["market"], prev["market"]
    if market["confirmed_state"] != market_prev["confirmed_state"] and market["confirmed_state"]:
        add("P1", "market", "market", "conclusion_changed", market_prev["confirmed_state"],
            market["confirmed_state"],
            f"市場狀態由「{label(market_prev['confirmed_state'], MARKET_STATES)}」確認轉為"
            f"「{label(market['confirmed_state'], MARKET_STATES)}」",
            {key: market["evidence"].get(key) for key in ("R20", "B20", "B60", "UDVR5", "sectors_positive_20d")})
    if market["leadership"] != market_prev["leadership"]:
        add("P2", "market", "leadership", "conclusion_changed", market_prev["leadership"], market["leadership"],
            f"領漲類型由「{label(market_prev['leadership'], LEADERSHIP_TYPES)}」變為"
            f"「{label(market['leadership'], LEADERSHIP_TYPES)}」")
    if market["pending_state"] and market["pending_state"] != market_prev["pending_state"]:
        add("P3", "market", "market", "pending_change", market["confirmed_state"], market["pending_state"],
            f"市場可能轉為「{label(market['pending_state'], MARKET_STATES)}」（待確認第 1／2 日）")

    for group_id, row in sorted(current["groups"].items()):
        scope = group_id.split(":")[0]
        if scope == "industry" and (row.get("issuers") or 0) < FORMAL_INDUSTRY_ISSUERS:
            continue
        before = prev["groups"].get(group_id)
        if before is None:
            continue
        name = names.get(group_id, {}).get("name_zh", group_id)
        related = holdings.get(group_id, [])
        if row["confirmed_state"] != before["confirmed_state"] and row["confirmed_state"]:
            add("P2", scope, group_id, "conclusion_changed", before["confirmed_state"], row["confirmed_state"],
                f"{name}由「{label(before['confirmed_state'], GROUP_STATES)}」確認轉為"
                f"「{label(row['confirmed_state'], GROUP_STATES)}」", group_evidence(row), related)
        if row["pending_state"] and row["pending_state"] != before.get("pending_state"):
            add("P3", scope, group_id, "pending_change", row["confirmed_state"], row["pending_state"],
                f"{name}可能轉為「{label(row['pending_state'], GROUP_STATES)}」（待確認第 1／2 日）",
                group_evidence(row), related)
        if scope != "sector" or before2 is None or group_id not in before2["groups"]:
            continue
        older = before2["groups"][group_id]
        for tag in RISK_EVENTS:
            now, then, earlier = (tag in row["risk_tags"], tag in before["risk_tags"], tag in older["risk_tags"])
            if now and then and not earlier:
                add("P2", scope, group_id, "new_risk", None, tag,
                    f"{name}出現「{RISK_TAGS[tag]}」（已連續 2 個交易日）", group_evidence(row), related)
            elif not now and not then and earlier:
                add("P2", scope, group_id, "risk_resolved", tag, None,
                    f"{name}的「{RISK_TAGS[tag]}」已解除（已連續 2 個交易日）", group_evidence(row), related)

    return sorted(events, key=lambda e: (e["priority"], SCOPE_ORDER[e["scope"]], not e["related_holdings"],
                                         e["entity_id"], e["change_type"]))


def headline(research: dict, groups: dict) -> str:
    """One deterministic sentence (plan 35.8), with one limitation chosen per 35.9."""
    data = research["data"]
    market = data["market"]
    state = market["state"]["confirmed"] or market["state"]["raw"]
    lead = market["leadership"]
    r20 = market["evidence"]["R20"]
    sectors = groups["data"]["sectors"]
    by_id = {row["group_id"]: row for row in data["groups"]}
    text = (f"截至 {research['as_of']}，市場狀態「{MARKET_STATES.get(state, state)}」"
            f"（{lead['label']}），合併股票池近 20 日{'上漲' if r20 >= 0 else '下跌'} {abs(r20):.2f}%。")
    if not sectors:
        return text
    leader = sectors[0]
    evidence = by_id.get(leader["group_id"], {}).get("evidence", {})
    text += f"{leader['name_zh']}為相對領先代表（{leader['metrics']['relative_strength_20d']:+.2f}pp）"
    improving = [row for row in sectors
                 if row["metrics"]["relative_strength_20d"] < 0 < row["metrics"]["acceleration_5d"]]
    if improving:
        best = max(improving, key=lambda row: (row["metrics"]["acceleration_5d"], row["group_id"]))
        text += f"；{best['name_zh']}的 5 日相對動能改善最快，但 20 日仍落後。"
    else:
        text += "；目前沒有「仍落後但動能改善」的板塊。"
    def below(key, threshold, inclusive=False):
        value = evidence.get(key)
        return value is not None and (value <= threshold if inclusive else value < threshold)

    if market["confidence"] != "high":
        limit = "資料涵蓋率偏低，結論信心較低。"
    elif below("R20", 0):
        limit = f"{leader['name_zh']}本身近 20 日仍在下跌，領先只代表跌得較少。"
    elif below("RS60", 0, inclusive=True):
        limit = f"{leader['name_zh']}的 60 日相對強弱尚未轉正。"
    elif below("BPOS20", 50):
        limit = f"{leader['name_zh']}廣度僅 {evidence['BPOS20']:.0f}%，領先仍偏集中。"
    elif below("DVS5", 0, inclusive=True):
        limit = f"{leader['name_zh']}的上漲成交額尚未占優，成交方向未確認。"
    else:
        limit = NOT_A_SIGNAL + "。"
    return text + limit


def build_digest(current: dict | None, previous: list[dict], names: dict[str, dict],
                 holdings: dict[str, list[str]], research: dict | None, groups: dict | None,
                 previous_digest: dict | None) -> dict:
    """Digest for the latest snapshot; ``previous`` holds earlier snapshots, oldest first."""
    digest = {
        "schema_version": 1,
        "as_of": current["as_of"] if current else (research or {}).get("as_of"),
        "compared_with": previous[-1]["as_of"] if previous else None,
        "rule_version": current["research_rules"] if current else None,
        "headline": headline(research, groups) if research and groups else None,
        "status": None,
        "headline_count": 0,
        "event_count": 0,
        "notify_count": 0,
        "batch_id": None,
        "events": [],
        "not_a_signal": NOT_A_SIGNAL,
    }
    if current is None:
        digest["status"] = "awaiting_history"
        return digest
    if not previous:
        digest["status"] = "baseline"
        return digest
    prev = previous[-1]
    if (prev["calculation_version"], prev["research_rules"]) != (current["calculation_version"],
                                                                  current["research_rules"]):
        digest["status"] = "baseline_after_rule_change"
        return digest
    events = build_events(current, previous, names, holdings)
    notable = [e for e in events if e["priority"] in ("P1", "P2")]
    digest.update({
        "status": "changes_detected" if notable else "no_change",
        "event_count": len(events),
        "headline_count": min(len(notable), HEADLINE_LIMIT),
        "events": events,
    })
    if notable:
        digest["batch_id"] = f"rotation-{current['as_of']}-" + hashlib.sha256(
            "|".join(e["event_id"] for e in notable).encode()).hexdigest()[:8]
    already = previous_digest and previous_digest.get("batch_id") == digest["batch_id"]
    digest["notify_count"] = 0 if already else len(notable)
    return digest


def alert_markdown(digest: dict, exposure: dict | None, page_url: str) -> str:
    notable = [e for e in digest["events"] if e["priority"] in ("P1", "P2")]
    lines = [f"## 市場輪動變化｜{digest['as_of']}（比較 {digest['compared_with']}）", ""]
    if digest.get("headline"):
        lines += [digest["headline"], ""]
    for event in notable:
        holders = f"｜你的持股：{'、'.join(event['related_holdings'])}" if event["related_holdings"] else ""
        lines.append(f"- **{event['priority']}** {event['text']}{holders}")
    if exposure:
        review = [p for p in exposure.get("positions", []) if p["research_priority"] == "review_now"]
        if review:
            lines += ["", "### 需要覆核的持股", ""]
            lines += [f"- {p['ticker']}：{'；'.join(p['reasons'])}" for p in review]
    lines += ["", f"詳見輪動頁：{page_url}", "", f"> {NOT_A_SIGNAL}；門檻為回測起點、仍在研究中。", ""]
    return "\n".join(lines)
