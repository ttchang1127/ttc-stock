#!/usr/bin/env python3
"""Link the latest verified segment trend to each company's thesis rules.

The linkage is deliberately narrow: segment revenue can support or pressure a
revenue-growth thesis, and disclosed segment profit can inform a margin thesis.
It never uses segment data to judge cash flow, dilution, valuation, or price.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HISTORY = ROOT / "segment_driver_history.json"
DEFAULT_THESIS = ROOT / "investment_thesis_status.json"
DEFAULT_UPDATES = ROOT / "segment_driver_update_candidates.json"
DEFAULT_OUTPUT = ROOT / "segment_thesis_linkage.json"
DEFAULT_MARKDOWN = ROOT / "60_SEC_Filing_Radar" / "Segment_Thesis_Linkage.md"

DISPLAY_TICKERS = [
    "NVDA", "TSM", "MSFT", "META", "AAPL", "AMZN", "ARM",
    "ONDS", "TSLA", "GOOG", "COHR", "MRVL", "INTC", "NOK",
]
ALIASES = {"GOOG": "GOOGL"}
EVENT_WEIGHTS = {
    "yoy_deceleration": -2,
    "qoq_direction_reversal": -3,
    "margin_drop": -2,
    "concentration_jump": -1,
    "offsetting_growth": -1,
    "driver_change": 0,
    "basis_break": 0,
}


def normalize_summary(value: Any) -> str:
    """Normalize event clauses so the dashboard never renders `。；`."""
    clauses = [part.strip().rstrip("。；") for part in str(value or "").split("；")]
    clauses = [part for part in clauses if part]
    return f"{'；'.join(clauses)}。" if clauses else ""


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def signed(value: float | None, suffix: str = "%") -> str:
    if value is None:
        return "—"
    return f"{value:+,.1f}{suffix}"


def growth_score(latest: dict[str, Any]) -> int:
    score = 0
    qoq = latest.get("qoq_pct")
    yoy = latest.get("total_yoy_pct")
    if qoq is not None:
        score += 3 if qoq >= 10 else (1 if qoq >= 0 else (-3 if qoq <= -10 else -1))
    if yoy is not None:
        score += 2 if yoy >= 20 else (1 if yoy >= 0 else (-2 if yoy <= -10 else -1))
    return score


def thesis_item_link(item: dict[str, Any], latest: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    metric = item.get("metric")
    event_types = {event.get("type") for event in events}
    if metric == "revenue_growth":
        negative = bool(event_types & {"yoy_deceleration", "qoq_direction_reversal"}) or (
            latest.get("qoq_pct") is not None and latest["qoq_pct"] < 0
        )
        positive = not negative and (
            (latest.get("qoq_pct") is not None and latest["qoq_pct"] > 0)
            or (latest.get("total_yoy_pct") is not None and latest["total_yoy_pct"] > 0)
        )
        impact = "pressure" if negative else ("support" if positive else "monitor")
        detail = (
            f"已收錄分部合計 QoQ {signed(latest.get('qoq_pct'))}、YoY {signed(latest.get('total_yoy_pct'))}；"
            "只代表本表已收錄且同口徑項目。"
        )
    elif metric in {"gross_margin", "operating_margin"}:
        changes = [
            row.get("margin_change_pp") for row in latest.get("items") or []
            if row.get("margin_change_pp") is not None and not row.get("is_elimination")
        ]
        if "margin_drop" in event_types:
            impact = "pressure"
        elif changes and max(changes) >= 3 and min(changes) >= 0:
            impact = "support"
        else:
            impact = "monitor"
        detail = (
            f"分部利益率最大變化 {signed(max(changes), 'pp')}、最小變化 {signed(min(changes), 'pp')}。"
            if changes else "本期分部表未提供可比較的分部利益率；不能用分部營收替代利益率。"
        )
    else:
        impact = "not_applicable"
        detail = "分部營收／利益資料不能直接驗證 FCF、稀釋、資本支出或每股價值。"
    labels = {
        "support": "支持", "pressure": "形成壓力", "monitor": "持續觀察",
        "not_applicable": "不直接驗證",
    }
    return {
        "id": item.get("id"), "title": item.get("title"), "metric": metric,
        "thesis_status": item.get("status"), "thesis_label": item.get("label"),
        "impact": impact, "impact_label": labels[impact], "detail": detail,
    }


def build_company(ticker: str, segment: dict[str, Any], thesis: dict[str, Any],
                  update: dict[str, Any] | None) -> dict[str, Any]:
    history = segment.get("history") or []
    if not history:
        raise ValueError(f"{ticker} 缺分部歷史")
    latest = history[-1]
    change = segment.get("latest_change") or {}
    events = change.get("events") or []
    update = update or {}
    comparable = bool(change.get("comparable"))
    pending = update.get("status") == "pending_review"
    score = growth_score(latest) + sum(EVENT_WEIGHTS.get(event.get("type"), 0) for event in events)
    score = max(-8, min(8, score))
    if pending:
        signal, label, score = "needs_review", "新一期待覆核", 0
    elif not comparable:
        signal, label, score = "needs_review", "口徑改變，暫不判斷", 0
    elif score >= 3:
        signal, label = "support", "分部趨勢提供支持"
    elif score <= -2:
        signal, label = "pressure", "分部趨勢形成壓力"
    else:
        signal, label = "mixed", "分部訊號混合／未達門檻"

    linked = [thesis_item_link(item, latest, events) for item in thesis.get("items") or []]
    pressure = [row for row in linked if row["impact"] == "pressure"]
    support = [row for row in linked if row["impact"] == "support"]
    event_evidence = [f"{event['label']}：{event['detail']}" for event in events]
    evidence = [
        f"{latest['period']} 已收錄分部合計 QoQ {signed(latest.get('qoq_pct'))}、YoY {signed(latest.get('total_yoy_pct'))}。",
        *(event_evidence or ["相較前季未觸發既定的分部重大轉折門檻。"]),
    ]
    if pending:
        evidence.insert(0, f"新一期尚未通過安全勾稽：{'；'.join(update.get('reasons') or ['原因待核對'])}。")
    alignment = (
        "對既有論點形成壓力" if pressure else
        "支持既有論點" if support else
        "目前不足以改變既有論點"
    )
    if pending or not comparable:
        alignment = "先完成口徑／數字覆核，不改變既有論點"
    conclusion = (
        f"{label}；{alignment}。分部證據分數 {score:+d}/8，只調整 SEC 證據權重，不直接改寫投資論點總狀態。"
    )
    fingerprint_source = {
        "ticker": ticker, "period_end": latest.get("period_end"), "basis_id": latest.get("basis_id"),
        "signal": signal, "score": score, "events": [event.get("id") for event in events],
        "update_status": update.get("status"),
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_source, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:20]
    return {
        "ticker": ticker,
        "name": segment.get("name", ticker),
        "period": latest.get("period"),
        "period_end": latest.get("period_end"),
        "basis_id": latest.get("basis_id"),
        "basis": latest.get("basis"),
        "source_date": latest.get("source_date"),
        "source_url": latest.get("source_url"),
        "signal": signal,
        "label": label,
        "score": score,
        "alignment": alignment,
        "conclusion": conclusion,
        "comparable": comparable,
        "pending_review": pending,
        "latest_change_summary": normalize_summary(change.get("summary")),
        "events": events,
        "evidence": evidence,
        "linked_theses": linked,
        "next_checks": [
            "下一季先確認分部名稱與 basis_id 是否相同；不同即切斷趨勢。",
            "核對主要成長驅動、分部占比與利益率是否連續兩期同向；單季變化不直接升降投資評等。",
        ],
        "fingerprint": fingerprint,
    }


def build_payload(history: dict[str, Any], thesis: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    segments = {row["ticker"]: row for row in history.get("companies") or []}
    update_rows = {row["ticker"]: row for row in updates.get("companies") or []}
    thesis_rows = thesis.get("companies") or {}
    companies = []
    for ticker in DISPLAY_TICKERS:
        data_ticker = ALIASES.get(ticker, ticker)
        if ticker not in segments or data_ticker not in thesis_rows:
            raise ValueError(f"{ticker} 缺分部或投資論點資料")
        companies.append(build_company(ticker, segments[ticker], thesis_rows[data_ticker], update_rows.get(ticker)))
    counts = {key: sum(row["signal"] == key for row in companies) for key in ("support", "pressure", "mixed", "needs_review")}
    return {
        "schema_version": 1,
        "updated_at": max(filter(None, [history.get("updated_at"), thesis.get("updated_at"), updates.get("updated_at")]), default=None),
        "tracked_count": len(companies),
        "counts": counts,
        "methodology": {
            "scope": "14 家個股；ETF 不納入。只連結同公司、同一期已核對的分部資料與現有三項投資論點。",
            "score": "分部證據分數 -8～+8：QoQ／YoY 方向加權，再扣除降速、轉負、利益率下降、集中上升與抵銷成長事件。",
            "boundary": "分部資料只能直接驗證營收成長與已揭露的分部利益率；不能驗證 FCF、稀釋、估值或股價。",
            "change_rule": "每日候選以 fingerprint 對照最近一次 AI 覆核；同一 fingerprint 不重複列出。",
        },
        "companies": companies,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    counts = payload["counts"]
    lines = [
        "---", "title: 分部趨勢與投資論點聯動", "tags:", "  - sec", "  - segment", "  - thesis", "---", "",
        "# 🧩 分部趨勢與投資論點聯動", "",
        f"> 更新：{payload['updated_at']}｜支持 {counts['support']}｜壓力 {counts['pressure']}｜混合 {counts['mixed']}｜待覆核 {counts['needs_review']}。", "",
        "## 判讀邊界", "",
        f"- **範圍**：{payload['methodology']['scope']}",
        f"- **計分**：{payload['methodology']['score']}",
        f"- **限制**：{payload['methodology']['boundary']}",
        f"- **變更通知**：{payload['methodology']['change_rule']}", "",
    ]
    for company in payload["companies"]:
        lines += [
            f"## {company['ticker']}｜{company['label']}", "",
            f"- **期間／口徑**：{company['period']}｜{company['basis']}",
            f"- **客觀結論**：{company['conclusion']}",
            f"- **最新變化**：{company['latest_change_summary']}",
            f"- **官方來源**：[原始分部表]({company['source_url']})", "",
            "| 投資論點 | 現有狀態 | 分部影響 | 可驗證內容 |", "|---|---|---|---|",
        ]
        for item in company["linked_theses"]:
            lines.append(f"| {item['title']} | {item['thesis_label']} | {item['impact_label']} | {item['detail']} |")
        lines += ["", "**下一季驗證**", "", *[f"- {text}" for text in company["next_checks"]], ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--thesis", type=Path, default=DEFAULT_THESIS)
    parser.add_argument("--updates", type=Path, default=DEFAULT_UPDATES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    args = parser.parse_args()
    payload = build_payload(load_json(args.history), load_json(args.thesis), load_json(args.updates))
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(render_markdown(payload))
    print(
        f"分部 × 論點聯動：{payload['tracked_count']} 家；支持 {payload['counts']['support']}；"
        f"壓力 {payload['counts']['pressure']}；混合 {payload['counts']['mixed']}；待覆核 {payload['counts']['needs_review']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
