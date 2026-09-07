#!/usr/bin/env python3
"""Detect new segment periods and safely roll verified data into 8-period history.

Detection comes from quarterly_financials.json and analyzed Exhibit 99.1 releases.
Numbers are written only from the curated, official segment_driver_inputs.json
when period, source date, basis, input kind and the complete item set all match a
pre-approved profile.  Everything else fails closed into a review candidate.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CURRENT = ROOT / "segment_driver_inputs.json"
DEFAULT_HISTORY = ROOT / "segment_driver_history_inputs.json"
DEFAULT_QUARTERLY = ROOT / "quarterly_financials.json"
DEFAULT_EXHIBITS = ROOT / "exhibit_991_analysis.json"
DEFAULT_CONFIG = ROOT / "segment_driver_sync_config.json"
DEFAULT_OUTPUT = ROOT / "segment_driver_update_candidates.json"
DEFAULT_MARKDOWN = ROOT / "60_SEC_Filing_Radar" / "Segment_Driver_Update_Candidates.md"

DISPLAY_TICKERS = [
    "NVDA", "TSM", "MSFT", "META", "AAPL", "AMZN", "ARM",
    "ONDS", "TSLA", "GOOG", "COHR", "MRVL", "INTC", "NOK",
]
ALIASES = {"GOOG": "GOOGL"}
QUARTER_RE = re.compile(r"(?:\bQ[1-4]\b|\b[1-4]Q\b|第[一二三四1-4]季)", re.IGNORECASE)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def append_text(path: Path | None, text: str) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(text.rstrip() + "\n")


def write_github_output(path: Path | None, values: dict[str, Any]) -> None:
    target = path or (Path(os.environ["GITHUB_OUTPUT"]) if os.environ.get("GITHUB_OUTPUT") else None)
    if target:
        append_text(target, "\n".join(f"{key}={value}" for key, value in values.items()))


def parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def latest_quarter(quarterly: dict[str, Any], ticker: str) -> dict[str, Any] | None:
    company = (quarterly.get("companies") or {}).get(ALIASES.get(ticker, ticker)) or {}
    periods = company.get("periods") or []
    return max(periods, key=lambda row: row.get("period_end", ""), default=None)


def latest_new_exhibit(exhibits: dict[str, Any], ticker: str, latest_source_date: str) -> dict[str, Any] | None:
    rows = []
    for row in exhibits.get("filings") or []:
        filing_date = row.get("filing_date") or row.get("report_date") or ""
        categories = row.get("categories") or {}
        has_results = bool(categories.get("revenue") or categories.get("segments"))
        if row.get("ticker") == ticker and row.get("status") == "analyzed" and has_results \
                and filing_date > latest_source_date:
            rows.append(row)
    return max(rows, key=lambda row: (row.get("filing_date", ""), row.get("accession", "")), default=None)


def validate_current(current: dict[str, Any], profile: dict[str, Any], quarter: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    period_end = parse_date(quarter.get("period_end"))
    filing_date = parse_date(quarter.get("filing_date"))
    source_date = parse_date(current.get("source_date"))
    if not QUARTER_RE.search(str(current.get("period", ""))):
        reasons.append("period_not_quarter")
    if current.get("basis") != profile.get("accepted_basis"):
        reasons.append("basis_changed")
    if current.get("input_kind") != profile.get("input_kind"):
        reasons.append("input_kind_changed")
    expected_names = set((profile.get("items") or {}).keys())
    actual_names = {row.get("name") for row in current.get("items") or []}
    if actual_names != expected_names:
        reasons.append("item_set_changed")
    if current.get("coverage_status") not in {"complete", "reconciled"}:
        reasons.append("coverage_incomplete")
    source_url = str(current.get("source_url", ""))
    if not source_url.startswith("https://"):
        reasons.append("source_not_https")
    elif (urlparse(source_url).hostname or "").lower() not in set(profile.get("allowed_hosts") or []):
        reasons.append("source_host_changed")
    if not period_end or not filing_date or not source_date:
        reasons.append("date_missing")
    elif source_date < period_end or abs((source_date - filing_date).days) > 7:
        reasons.append("source_date_mismatch")
    items = current.get("items") or []
    if current.get("input_kind") == "amount":
        if any(row.get("current_revenue") is None for row in items):
            reasons.append("amount_missing")
    elif current.get("input_kind") == "share_of_total":
        if current.get("current_total_revenue") is None or any(row.get("current_share_pct") is None for row in items):
            reasons.append("share_or_total_missing")
    return list(dict.fromkeys(reasons))


def make_observation(current: dict[str, Any], profile: dict[str, Any], quarter: dict[str, Any],
                     canonical_basis: str) -> dict[str, Any]:
    item_keys = profile["items"]
    observation: dict[str, Any] = {
        "period": current["period"],
        "period_end": quarter["period_end"],
        "basis_id": profile["basis_id"],
        "basis": canonical_basis,
        "source_date": current["source_date"],
        "source_url": current["source_url"],
        "source_note": current.get("comparability_note"),
        "sync_origin": "verified_segment_driver_input",
        "items": [],
    }
    if current["input_kind"] == "share_of_total":
        observation["total_revenue"] = current["current_total_revenue"]
        if current.get("prior_total_revenue") is not None:
            observation["prior_year_total_revenue"] = current["prior_total_revenue"]
    elif all(row.get("prior_revenue") is not None for row in current["items"]):
        observation["prior_year_total_revenue"] = sum(float(row["prior_revenue"]) for row in current["items"])
    for row in current["items"]:
        item: dict[str, Any] = {"key": item_keys[row["name"]], "name": row["name"]}
        if current["input_kind"] == "share_of_total":
            item["share_pct"] = row["current_share_pct"]
        else:
            item["revenue"] = row["current_revenue"]
            if row.get("current_profit") is not None:
                item["profit"] = row["current_profit"]
        if row.get("is_elimination"):
            item["is_elimination"] = True
        observation["items"].append(item)
    return {key: value for key, value in observation.items() if value is not None}


REASON_LABELS = {
    "period_not_quarter": "目前正式分部表不是單季資料",
    "basis_changed": "揭露口徑與已核准白名單不同",
    "input_kind_changed": "金額／占比輸入型態改變",
    "item_set_changed": "分部名稱或項目集合改變",
    "coverage_incomplete": "官方表格尚未完整勾稽",
    "source_not_https": "缺少 HTTPS 官方來源",
    "source_host_changed": "來源網域不在公司 IR／SEC 白名單",
    "date_missing": "期間或來源日期缺漏",
    "source_date_mismatch": "來源日期無法與季度申報勾稽",
    "amount_missing": "至少一個分部缺官方金額",
    "share_or_total_missing": "平台占比或總營收缺值",
    "current_input_not_advanced": "單期分部輸入尚未更新到新季度",
    "awaiting_period_match": "Exhibit 99.1 已出現，但季度期末尚未確認",
}


def build(current_data: dict[str, Any], history_data: dict[str, Any], quarterly: dict[str, Any],
          exhibits: dict[str, Any], config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    expected = set(DISPLAY_TICKERS)
    for label, data in (("current", current_data), ("history", history_data), ("config", config)):
        actual = set((data.get("companies") or {}).keys())
        if actual != expected:
            raise ValueError(f"{label} 公司範圍不符；缺少 {sorted(expected - actual)}；多出 {sorted(actual - expected)}")
    history = copy.deepcopy(history_data)
    companies = []
    for ticker in DISPLAY_TICKERS:
        current = current_data["companies"][ticker]
        company_history = history["companies"][ticker]
        observations = company_history["observations"]
        latest = observations[-1]
        quarter = latest_quarter(quarterly, ticker)
        profile = config["companies"][ticker]
        source: dict[str, Any] | None = None
        status = "up_to_date"
        reason_codes: list[str] = []

        if quarter and quarter.get("period_end", "") > latest["period_end"]:
            source = {
                "kind": "quarterly_financials",
                "form": quarter.get("form"),
                "filing_date": quarter.get("filing_date"),
                "period_end": quarter.get("period_end"),
                "accession": quarter.get("accession"),
                "url": quarter.get("url"),
            }
            if current.get("source_date", "") <= latest.get("source_date", ""):
                reason_codes = ["current_input_not_advanced"]
            else:
                reason_codes = validate_current(current, profile, quarter)
            if reason_codes:
                status = "pending_review"
            else:
                observation = make_observation(current, profile, quarter, latest["basis"])
                observations.append(observation)
                company_history["observations"] = observations[-8:]
                latest = company_history["observations"][-1]
                status = "auto_synced"
        else:
            exhibit = latest_new_exhibit(exhibits, ticker, latest.get("source_date", ""))
            if exhibit:
                status = "pending_review"
                reason_codes = ["awaiting_period_match"]
                source = {
                    "kind": "exhibit_99_1", "form": exhibit.get("form"),
                    "filing_date": exhibit.get("filing_date"), "period_end": None,
                    "accession": exhibit.get("accession"),
                    "url": exhibit.get("exhibit_url") or exhibit.get("index_url"),
                }
            elif latest.get("sync_origin") == "verified_segment_driver_input":
                status = "auto_synced"

        target_end = (source or {}).get("period_end") or (source or {}).get("filing_date") or latest["period_end"]
        candidate_id = f"{ticker}:{target_end}:{status}"
        companies.append({
            "ticker": ticker,
            "name": company_history.get("name", ticker),
            "status": status,
            "candidate_id": candidate_id,
            "latest_history_period": latest["period"],
            "latest_history_period_end": latest["period_end"],
            "period_count": len(company_history["observations"]),
            "max_periods": 8,
            "current_input_period": current.get("period"),
            "current_input_source_date": current.get("source_date"),
            "detected_source": source,
            "reason_codes": reason_codes,
            "reasons": [REASON_LABELS[code] for code in reason_codes],
            "next_action": (
                "已以完整官方表格自動新增，並只保留最近 8 期。" if status == "auto_synced" else
                "核對官方分部表、期間與口徑後更新單期輸入；系統會在下次執行自動寫入。" if status == "pending_review" else
                "無需處理；等待下一份正式季度結果或 Exhibit 99.1。"
            ),
        })

    auto_managed = sum(row["status"] == "auto_synced" for row in companies)
    if auto_managed:
        source_dates = [row["source_date"] for company in history["companies"].values() for row in company["observations"]]
        history["updated_at"] = max(source_dates)
    pending = sum(row["status"] == "pending_review" for row in companies)
    payload = {
        "schema_version": 1,
        "updated_at": max(filter(None, [quarterly.get("generated_at"), current_data.get("updated_at")]), default=None),
        "tracked_count": len(companies),
        "pending_count": pending,
        "auto_synced_count": auto_managed,
        "methodology": {
            "detection": "監看 SEC／IR 季度資料與已解析 Exhibit 99.1；新期先建立候選。",
            "auto_sync": "只有期間、日期、官方來源、口徑、輸入型態與完整項目集合全部通過白名單才寫入。",
            "basis_guard": "新口徑或新分部名稱一律待覆核，不跨口徑計算趨勢。",
            "retention": "每家公司由舊到新只保留最近 8 期；來源 URL 與期末日隨觀察值保存。",
            "no_inference": "不得用成長率反推分部金額，也不得把公司總營收猜分配到分部。",
        },
        "companies": companies,
    }
    return payload, history


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "---", "title: 分部資料自動更新候選", "tags:", "  - sec", "  - segment", "  - automation", "---", "",
        "# 🔄 分部資料自動更新候選", "",
        f"> 更新：{payload['updated_at']}｜追蹤 {payload['tracked_count']} 家｜待覆核 {payload['pending_count']} 家。", "",
        "## 安全規則", "",
        f"- **偵測**：{payload['methodology']['detection']}",
        f"- **自動寫入**：{payload['methodology']['auto_sync']}",
        f"- **口徑防線**：{payload['methodology']['basis_guard']}",
        f"- **保留期數**：{payload['methodology']['retention']}",
        f"- **禁止推估**：{payload['methodology']['no_inference']}", "",
        "| 公司 | 狀態 | 歷史最新期 | 收錄 | 偵測來源 | 原因／下一步 |", "|---|---|---|---:|---|---|",
    ]
    labels = {"up_to_date": "✅ 已同步", "auto_synced": "🔄 本次自動新增", "pending_review": "⚠️ 待覆核"}
    for row in payload["companies"]:
        source = row.get("detected_source") or {}
        source_text = "—"
        if source:
            label = f"{source.get('form') or source.get('kind')} {source.get('filing_date') or ''}".strip()
            source_text = f"[{label}]({source['url']})" if str(source.get("url", "")).startswith("https://") else label
        reason = "；".join(row["reasons"]) or row["next_action"]
        lines.append(
            f"| {row['ticker']} | {labels[row['status']]} | {row['latest_history_period']} | "
            f"{row['period_count']}/8 | {source_text} | {reason} |"
        )
    return "\n".join(lines) + "\n"


def new_pending(payload: dict[str, Any], previous: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not previous:
        return []
    old = {row.get("candidate_id") for row in previous.get("companies") or [] if row.get("status") == "pending_review"}
    return [row for row in payload["companies"] if row["status"] == "pending_review" and row["candidate_id"] not in old]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current", type=Path, default=DEFAULT_CURRENT)
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--quarterly", type=Path, default=DEFAULT_QUARTERLY)
    parser.add_argument("--exhibits", type=Path, default=DEFAULT_EXHIBITS)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--alert-markdown", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    previous = load_json(args.output) if args.output.exists() else None
    payload, history = build(
        load_json(args.current), load_json(args.history), load_json(args.quarterly),
        load_json(args.exhibits), load_json(args.config),
    )
    pending = new_pending(payload, previous)
    args.history.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n")
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(render_markdown(payload))
    if pending:
        lines = ["## ⚠️ 分部資料待覆核", ""]
        lines += [f"- **{row['ticker']}｜{row['latest_history_period']}**：{'；'.join(row['reasons'])}。{row['next_action']}" for row in pending]
        append_text(args.alert_markdown, "\n".join(lines) + "\n")
        append_text(args.summary, "\n".join(lines) + "\n")
    digest = hashlib.sha256("|".join(sorted(row["candidate_id"] for row in pending)).encode()).hexdigest()[:12] if pending else "none"
    write_github_output(args.github_output, {
        "notify_count": len(pending), "critical_count": len(pending),
        "auto_synced_count": payload["auto_synced_count"], "batch_id": f"segment-sync-{digest}",
    })
    print(f"分部自動更新：{payload['tracked_count']} 家；自動管理 {payload['auto_synced_count']}；待覆核 {payload['pending_count']}；新通知 {len(pending)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
