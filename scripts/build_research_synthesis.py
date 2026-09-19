#!/usr/bin/env python3
"""Build an evidence-led research synthesis for the 14 tracked stocks.

The output does not replace any SEC radar.  It joins existing, committed and
traceable data into four research workflows: earnings deltas, thesis evidence,
catalyst outcomes and peer comparison.  Missing consensus or internal
estimates remain explicit gaps; the builder never searches for or invents a
number to make a table look complete.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "research_synthesis.json"
DEFAULT_MARKDOWN = ROOT / "60_SEC_Filing_Radar" / "Research_Synthesis.md"
DEFAULT_GROUPS = ROOT / "research_peer_groups.json"

DISPLAY_TICKERS = [
    "NVDA", "TSM", "MSFT", "META", "AAPL", "AMZN", "ARM",
    "ONDS", "TSLA", "GOOG", "COHR", "MRVL", "INTC", "NOK",
]
DATA_TICKER = {"GOOG": "GOOGL"}
METRIC_DEFINITIONS = [
    ("revenue_yoy", "營收 YoY", "higher", "%"),
    ("gross_margin", "毛利率", "higher", "%"),
    ("operating_margin", "營業利益率", "higher", "%"),
    ("fcf_margin", "FCF 利潤率", "higher", "%"),
    ("diluted_shares_yoy", "稀釋股數 YoY", "lower", "%"),
    ("pe_ratio", "本益比", "lower", "x"),
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def metric_value(period: dict[str, Any] | None, metric: str) -> float | None:
    value = (period or {}).get("values", {}).get(metric)
    if isinstance(value, dict):
        value = value.get("value")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def percent_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in {None, 0}:
        return None
    return (current / previous - 1) * 100


def display_date(value: Any) -> str | None:
    text = str(value or "")
    return text[:10] or None


def generated_at(inputs: dict[str, Any]) -> str:
    candidates = []
    for name, payload in inputs.items():
        if name == "groups":
            candidates.append(payload.get("updated_at"))
            continue
        for key in ("generated_at", "updated_at", "as_of", "source_updated_at"):
            candidates.append(payload.get(key))
    days = [display_date(value) for value in candidates if display_date(value)]
    return max(days) if days else "unknown"


def company_metrics(quarterly: dict[str, Any], valuation: dict[str, Any]) -> dict[str, float | None]:
    periods = quarterly.get("periods") or []
    latest = periods[0] if periods else None
    year_ago = periods[4] if len(periods) > 4 else None
    revenue = metric_value(latest, "revenue")
    return {
        "revenue_yoy": percent_change(revenue, metric_value(year_ago, "revenue")),
        "gross_margin": (None if metric_value(latest, "gross_margin") is None
                         else metric_value(latest, "gross_margin") * 100),
        "operating_margin": (None if metric_value(latest, "operating_margin") is None
                             else metric_value(latest, "operating_margin") * 100),
        "fcf_margin": (None if revenue in {None, 0} or metric_value(latest, "free_cash_flow") is None
                       else metric_value(latest, "free_cash_flow") / revenue * 100),
        "diluted_shares_yoy": percent_change(
            metric_value(latest, "diluted_shares"), metric_value(year_ago, "diluted_shares")
        ),
        "pe_ratio": (valuation.get("multiples") or {}).get("pe_ratio"),
    }


def percentile(values: list[tuple[str, float]], ticker: str, direction: str) -> float | None:
    if len(values) < 3:
        return None
    target = next((value for name, value in values if name == ticker), None)
    if target is None:
        return None
    lower = sum(value < target for _, value in values)
    equal = sum(value == target for _, value in values)
    rank = lower + (equal - 1) / 2
    score = rank / (len(values) - 1) * 100
    return round(100 - score if direction == "lower" else score, 1)


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def peer_comparisons(metrics: dict[str, dict[str, float | None]], groups: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    minimum = int((groups.get("methodology") or {}).get("minimum_sample", 3))
    for ticker in DISPLAY_TICKERS:
        group_id = (groups.get("primary_group_by_ticker") or {}).get(ticker)
        group = (groups.get("groups") or {}).get(group_id, {}) if group_id else {}
        members = [member for member in group.get("members", []) if member in metrics]
        rows = []
        for metric_id, label, direction, unit in METRIC_DEFINITIONS:
            known = [(member, metrics[member].get(metric_id)) for member in members]
            known = [(member, float(value)) for member, value in known if value is not None]
            own = metrics.get(ticker, {}).get(metric_id)
            rows.append({
                "id": metric_id,
                "label": label,
                "value": own,
                "unit": unit,
                "direction": direction,
                "known_peer_count": len(known),
                "peer_median": median([value for _, value in known]),
                "favorable_percentile": percentile(known, ticker, direction),
                "status": "available" if own is not None and len(known) >= minimum else "insufficient",
            })
        available = [row for row in rows if row["favorable_percentile"] is not None]
        result[ticker] = {
            "status": "available" if group and available else "insufficient",
            "group_id": group_id,
            "group_label": group.get("label"),
            "members": members,
            "comparability": group.get("comparability"),
            "caveat": group.get("caveat") or "目前追蹤名單中沒有至少三家可比公司，不產生百分位。",
            "metrics": rows,
            "composite_percentile": (round(sum(row["favorable_percentile"] for row in available) / len(available), 1)
                                     if available else None),
            "coverage": {"known": len(available), "total": len(rows)},
        }
    return result


def evidence_ledger(company: dict[str, Any]) -> dict[str, Any]:
    periods = company.get("periods") or []
    if not periods:
        return {"status": "unavailable", "period_end": None, "source_url": None, "claims": [],
                "coverage": {"sourced": 0, "total": 0}}
    latest = periods[0]
    claims = []
    labels = {
        "revenue": "營收", "gross_margin": "毛利率", "operating_margin": "營業利益率",
        "free_cash_flow": "自由現金流", "diluted_shares": "稀釋股數",
    }
    for metric, label in labels.items():
        raw = (latest.get("values") or {}).get(metric)
        node = raw if isinstance(raw, dict) else {}
        derived_meta = {
            "gross_margin": ("%", True, "毛利 ÷ 營收"),
            "operating_margin": ("%", True, "營業利益 ÷ 營收"),
            "free_cash_flow": (company.get("currency"), True, "營運現金流 − 資本支出"),
        }.get(metric)
        claims.append({
            "claim_id": f"{latest.get('accession') or latest.get('period_end')}:{metric}",
            "metric": metric,
            "label": label,
            "value": metric_value(latest, metric),
            "unit": derived_meta[0] if derived_meta else (node.get("unit") or company.get("currency")),
            "tag": node.get("tag"),
            "derived": derived_meta[1] if derived_meta else bool(node.get("derived")),
            "derivation": derived_meta[2] if derived_meta else node.get("derivation"),
            "source_locator": (
                f"XBRL tag: {node.get('tag')}" if node.get("tag")
                else derived_meta[2] if derived_meta
                else f"{latest.get('form') or '官方財報'}已核對表格列：{label}"
            ),
            "source_url": latest.get("url") or company.get("official_results_url"),
            "source_form": latest.get("form"),
            "source_accession": latest.get("accession"),
            "source_date": latest.get("filing_date"),
        })
    sourced = sum(bool(row.get("source_url")) and row.get("value") is not None for row in claims)
    return {
        "status": "available",
        "period_end": latest.get("period_end"),
        "source_url": latest.get("url") or company.get("official_results_url"),
        "source_form": latest.get("form"),
        "source_accession": latest.get("accession"),
        "source_date": latest.get("filing_date"),
        "quality_notes": latest.get("quality_notes") or [],
        "claims": claims,
        "coverage": {"sourced": sourced, "total": len(claims)},
    }


def thesis_scorecard(status: dict[str, Any], config: dict[str, Any], next_event: dict[str, Any] | None) -> dict[str, Any]:
    definitions = {row.get("id"): row for row in config.get("theses", [])}
    previous = {row.get("id"): row for row in (status.get("previous") or {}).get("items", [])}
    rows = []
    for item in status.get("items", []):
        base = definitions.get(item.get("id"), {})
        prior = previous.get(item.get("id"), {})
        if prior and prior.get("status") != item.get("status"):
            trend = f"{prior.get('label', '前期')} → {item.get('label', '本期')}"
        else:
            trend = "狀態未變" if prior else "首次建立基準"
        rows.append({
            "id": item.get("id"), "title": item.get("title"),
            "original_expectation": base.get("rationale") or item.get("rationale"),
            "invalidation": item.get("invalidation"), "status": item.get("status"),
            "label": item.get("label"), "current_evidence": item.get("evidence"),
            "trend": trend, "source_url": status.get("url"), "source_period": status.get("period"),
        })
    return {
        "status": status.get("status", "unavailable"), "label": status.get("label", "資料不足"),
        "period": status.get("period"), "source_url": status.get("url"), "items": rows,
        "next_validation": next_event,
    }


def earnings_delta(card: dict[str, Any]) -> dict[str, Any]:
    post = card.get("post_event") or {}
    latest = post.get("latest_result") or {}
    rows = []
    for row in post.get("kpis") or []:
        rows.append({**row, "source_url": latest.get("source_url"), "source_period": latest.get("period_end")})
    guidance = (post.get("completed_guidance") or {}).get("record")
    positive = sum(row.get("state") == "improved" for row in rows)
    risks = sum(row.get("state") == "risk" for row in rows)
    conclusion = ("風險項目多於改善項目，先查原始申報與失效條件。" if risks > positive
                  else "改善項目多於風險項目，但仍需逐項核對來源與口徑。" if positive > risks
                  else "改善與風險訊號相近，維持中性驗證。")
    return {
        "status": "available" if rows else "unavailable", "latest_result": latest, "metrics": rows,
        "official_guidance_comparison": guidance,
        "prior_internal_estimate": {"status": "not_collected", "note": "尚未保存可追溯的財報前內部數值預估，不補猜。"},
        "consensus": {"status": "not_collected", "note": "目前沒有已授權且可稽核的機構共識來源，不以網路摘要補值。"},
        "conclusion": conclusion,
    }


def catalyst_log(
    card: dict[str, Any], calendar_company: dict[str, Any], quarterly_company: dict[str, Any]
) -> dict[str, Any]:
    upcoming = [dict(row, status="upcoming") for row in calendar_company.get("events", [])]
    completed = []
    guidance = ((card.get("post_event") or {}).get("completed_guidance") or {}).get("record")
    if guidance:
        actual_period = next(
            (row for row in quarterly_company.get("periods", [])
             if row.get("period_end") == guidance.get("period_end")),
            {},
        )
        completed.append({
            "status": "completed", "date": guidance.get("period_end"),
            "type": "earnings_guidance_validation", "title": f"{guidance.get('period')} 官方指引驗證",
            "expected": f"{guidance.get('low')}～{guidance.get('high')} {guidance.get('unit')}",
            "actual": f"{guidance.get('actual')} {guidance.get('unit')}",
            "outcome": guidance.get("outcome"), "outcome_label": guidance.get("outcome_label"),
            "source_url": guidance.get("guidance_source_url"),
            "actual_source_url": actual_period.get("url") or quarterly_company.get("official_results_url"),
        })
    return {"upcoming": upcoming, "completed": completed,
            "note": "已完成事件目前只收錄可由官方指引與正式實績閉環驗證者；其他事件不猜測結果。"}


def rotation_bridge(rotation: dict[str, Any], universe: dict[str, Any], companies: dict[str, Any]) -> dict[str, Any]:
    member_sector = {row.get("ticker"): row.get("sector") for row in universe.get("members", [])}
    by_sector: dict[str, list[dict[str, Any]]] = {}
    for ticker, company in companies.items():
        sector = member_sector.get(ticker)
        if not sector:
            continue
        by_sector.setdefault(sector, []).append({
            "ticker": ticker, "thesis_label": company["thesis_scorecard"].get("label"),
            "peer_group": company["peer_comparison"].get("group_label"),
            "peer_percentile": company["peer_comparison"].get("composite_percentile"),
            "evidence_period": company["evidence_ledger"].get("period_end"),
        })
    rows = []
    guidance = {
        "leading": "價格層領先且仍加速；下一步核對基本面是否同步改善，不能只因位於右上角追價。",
        "improving": "相對仍弱但動能回升；列入研究候選，等待財報與論點證據確認。",
        "weakening": "仍相對領先但動能降溫；優先檢查估值、指引與論點是否開始轉弱。",
        "lagging": "相對弱且動能惡化；區分市場冷卻與公司基本面失效，不由價格直接推論價值。",
    }
    for sector in rotation.get("sectors", []):
        tracked = sorted(by_sector.get(sector.get("key"), []), key=lambda row: row["ticker"])
        rows.append({
            "sector_key": sector.get("key"), "sector_name": sector.get("name_zh"),
            "quadrant": sector.get("quadrant"), "quadrant_zh": sector.get("quadrant_zh"),
            "rotation_score": sector.get("rotation_score"), "as_of": rotation.get("as_of"),
            "research_action": guidance.get(sector.get("quadrant")), "tracked_companies": tracked,
            "coverage_note": f"只連結 sec_kb 追蹤且屬於 S&P 500／Nasdaq-100 的 {len(tracked)} 家公司，不代表整個板塊基本面。",
        })
    return {"as_of": rotation.get("as_of"), "sectors": rows}


def build_payload(inputs: dict[str, Any]) -> dict[str, Any]:
    cards = {row.get("ticker"): row for row in inputs["earnings"].get("companies", [])}
    calendar = inputs["calendar"].get("companies", {})
    raw_metrics = {}
    for ticker in DISPLAY_TICKERS:
        data_ticker = DATA_TICKER.get(ticker, ticker)
        raw_metrics[ticker] = company_metrics(
            inputs["quarterly"].get("companies", {}).get(data_ticker, {}),
            inputs["valuation"].get("companies", {}).get(data_ticker, {}),
        )
    peers = peer_comparisons(raw_metrics, inputs["groups"])
    companies: dict[str, Any] = {}
    for ticker in DISPLAY_TICKERS:
        data_ticker = DATA_TICKER.get(ticker, ticker)
        quarterly = inputs["quarterly"].get("companies", {}).get(data_ticker, {})
        card = cards.get(ticker, {})
        next_event = next(
            (row for row in calendar.get(ticker, {}).get("events", [])
             if row.get("type") in {"earnings", "investor_event"}),
            None,
        )
        if not next_event and card.get("next_earnings"):
            next_event = {"type": "earnings", **card["next_earnings"]}
        companies[ticker] = {
            "ticker": ticker, "data_ticker": data_ticker,
            "evidence_ledger": evidence_ledger(quarterly),
            "earnings_delta": earnings_delta(card),
            "thesis_scorecard": thesis_scorecard(
                inputs["thesis_status"].get("companies", {}).get(data_ticker, {}),
                inputs["thesis_tracking"].get("companies", {}).get(data_ticker, {}), next_event,
            ),
            "catalyst_log": catalyst_log(card, calendar.get(ticker, {}), quarterly),
            "peer_comparison": peers[ticker],
        }
    bridge = rotation_bridge(inputs["rotation"], inputs["universe"], companies)
    return {
        "schema_version": 1, "generated_at": generated_at(inputs), "tracked_count": len(companies),
        "methodology": {
            "purpose": "把既有 SEC、財報、論點、事件與估值資料整理成可稽核的研究工作流，不新增無來源財務數字。",
            "source_rule": "每項最新財務證據保留官方來源、accession，以及 XBRL tag、推導公式或已核對官方表格列；缺值保持缺值。",
            "earnings_rule": "實際值比較前季、去年同期與公司官方指引；機構共識與內部預估沒有可靠來源時明列未收集。",
            "peer_rule": inputs["groups"].get("methodology"),
            "rotation_rule": "輪動是價格、廣度與成交參與代理；基本面橋接只調整研究優先度，不產生買賣指令。",
        },
        "source_dates": {
            "quarterly_financials": inputs["quarterly"].get("generated_at"),
            "earnings_verification": inputs["earnings"].get("generated_at"),
            "thesis_status": inputs["thesis_status"].get("updated_at"),
            "event_calendar": inputs["calendar"].get("generated_at"),
            "valuation": inputs["valuation"].get("generated_at") or inputs["valuation"].get("price_date"),
            "market_rotation": inputs["rotation"].get("as_of"),
            "peer_groups": inputs["groups"].get("updated_at"),
        },
        "companies": companies, "market_rotation_bridge": bridge,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "---", "title: 研究證據、財報差異與同業比較", "tags:", "  - research", "  - evidence", "---", "",
        "# 🔬 研究證據、財報差異與同業比較", "",
        "> 本頁整理既有官方資料，不新增無來源數字；同業百分位只涵蓋本庫人工設定的研究對照組。", "",
        "| 公司 | 最新證據期 | 來源覆蓋 | 財報差異摘要 | 論點 | 對照組／綜合百分位 | 下一驗證 |",
        "|---|---|---|---|---|---|---|",
    ]
    for ticker in DISPLAY_TICKERS:
        row = payload["companies"][ticker]
        evidence = row["evidence_ledger"]
        coverage = evidence["coverage"]
        peer = row["peer_comparison"]
        next_event = row["thesis_scorecard"].get("next_validation") or {}
        next_text = next_event.get("date") or "日期待確認"
        peer_text = (f"{peer.get('group_label')}／{peer.get('composite_percentile'):.1f}"
                     if peer.get("composite_percentile") is not None else "可比樣本不足")
        source = f"[原始來源]({evidence.get('source_url')})" if evidence.get("source_url") else "來源不足"
        lines.append(
            f"| **{ticker}** | {evidence.get('period_end') or '—'} | {coverage['sourced']}/{coverage['total']} {source} | "
            f"{row['earnings_delta'].get('conclusion')} | {row['thesis_scorecard'].get('label')} | {peer_text} | {next_text} |"
        )
    lines += [
        "", "## 閱讀限制", "",
        "- 同業比較只在目前 14 家追蹤個股的人工對照組中計算，不是全市場排名。",
        "- 機構共識與內部財報前預估尚無可稽核來源，因此明列未收集，不用網路摘要補值。",
        "- 輪動象限只決定下一步研究優先度，不構成交易訊號。",
        "- 完成事件只收錄能以官方指引和正式實績閉環核對者。", "",
        f"資料整合截至：{payload['generated_at']}", "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--groups", type=Path, default=DEFAULT_GROUPS)
    args = parser.parse_args()
    inputs = {
        "quarterly": load_json(ROOT / "quarterly_financials.json"),
        "valuation": load_json(ROOT / "valuation.json"),
        "earnings": load_json(ROOT / "earnings_verification_cards.json"),
        "thesis_tracking": load_json(ROOT / "investment_thesis_tracking.json"),
        "thesis_status": load_json(ROOT / "investment_thesis_status.json"),
        "calendar": load_json(ROOT / "company_event_calendar.json"),
        "rotation": load_json(ROOT / "market_rotation.json"),
        "universe": load_json(ROOT / "market_rotation_universe.json"),
        "groups": load_json(args.groups),
    }
    payload = build_payload(inputs)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(render_markdown(payload))
    print(f"Wrote {args.output.name} ({payload['tracked_count']} companies)")
    print(f"Wrote {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
