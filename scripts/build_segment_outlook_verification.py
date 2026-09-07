#!/usr/bin/env python3
"""Build a source-traceable segment outlook versus actual verification card."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "segment_outlook_inputs.json"
DEFAULT_HISTORY = ROOT / "segment_driver_history.json"
DEFAULT_LINKAGE = ROOT / "segment_thesis_linkage.json"
DEFAULT_OUTPUT = ROOT / "segment_outlook_verification.json"
DEFAULT_MARKDOWN = ROOT / "60_SEC_Filing_Radar" / "Segment_Outlook_Verification.md"

DISPLAY_TICKERS = [
    "NVDA", "TSM", "MSFT", "META", "AAPL", "AMZN", "ARM",
    "ONDS", "TSLA", "GOOG", "COHR", "MRVL", "INTC", "NOK",
]
OUTCOME_LABELS = {
    "above": "高於展望", "within": "符合展望", "below": "低於展望",
    "met": "方向實現", "missed": "方向未實現", "pending": "等待實績",
    "not_comparable": "口徑不可比",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]


def format_value(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    if unit == "USD m":
        amount = f"{value / 1000:,.3f}".rstrip("0").rstrip(".")
        return f"USD {amount}B"
    if unit == "EUR m":
        amount = f"{value / 1000:,.3f}".rstrip("0").rstrip(".")
        return f"EUR {amount}B"
    if unit == "%":
        return f"{value:,.1f}%"
    decimals = 1 if abs(value) < 1000 or unit == "%" else 0
    return f"{value:,.{decimals}f} {unit}".strip()


def history_actual(record: dict[str, Any], company: dict[str, Any]) -> tuple[float | None, str, str | None, str | None]:
    if record.get("reported_actual") is not None:
        if not record.get("actual_source_url") or not record.get("actual_source_date"):
            raise ValueError(f"{record['id']} 手動實績缺官方來源或日期")
        return float(record["reported_actual"]), "official_result", record.get("actual_source_date"), record.get("actual_source_url")
    if record.get("verification_mode") == "manual_official_result":
        return None, "pending_official_result", None, None
    period = next((row for row in company.get("history", []) if row.get("period_end") == record.get("target_period_end")), None)
    if not period:
        return None, "pending_period", None, None
    if period.get("basis_id") != record.get("basis_id"):
        return None, "basis_mismatch", period.get("source_date"), period.get("source_url")
    item = next((row for row in period.get("items", []) if row.get("key") == record.get("segment_key")), None)
    if not item:
        return None, "segment_missing", period.get("source_date"), period.get("source_url")
    metric = record.get("metric")
    field = {"revenue": "revenue", "margin_pct": "margin_pct", "revenue_yoy_pct": "yoy_pct", "revenue_qoq_pct": "qoq_pct"}.get(metric)
    if not field or item.get(field) is None:
        return None, "metric_missing", period.get("source_date"), period.get("source_url")
    return float(item[field]), "segment_history", period.get("source_date"), period.get("source_url")


def outcome(record: dict[str, Any], actual: float | None, actual_status: str) -> str:
    if actual_status in {"basis_mismatch", "segment_missing", "metric_missing"}:
        return "not_comparable"
    if actual is None:
        return "pending"
    comparison = record.get("comparison")
    if comparison == "range":
        low, high = record.get("low"), record.get("high")
        if low is None or high is None or float(low) > float(high):
            raise ValueError(f"{record['id']} 指引區間無效")
        return "below" if actual < float(low) else ("above" if actual > float(high) else "within")
    if comparison == "increase_from":
        if record.get("baseline") is None:
            raise ValueError(f"{record['id']} 缺方向比較基準")
        return "met" if actual > float(record["baseline"]) else "missed"
    raise ValueError(f"{record['id']} 不支援比較方式 {comparison}")


def target_text(record: dict[str, Any]) -> str:
    unit = record.get("unit", "")
    if record.get("comparison") == "range":
        return f"{format_value(float(record['low']), unit)}～{format_value(float(record['high']), unit)}"
    return f"高於基準 {format_value(float(record['baseline']), unit)}"


def build_record(record: dict[str, Any], company: dict[str, Any], thesis_title: str | None) -> dict[str, Any]:
    for key in ("id", "target_period", "target_period_end", "basis_id", "segment_key", "segment_name", "metric", "metric_label", "comparison", "unit", "statement_zh", "source_date", "source_url"):
        if not record.get(key):
            raise ValueError(f"展望紀錄缺 {key}: {record.get('id', 'unknown')}")
    if not str(record["source_url"]).startswith("https://"):
        raise ValueError(f"{record['id']} 展望來源不是 HTTPS")
    if record["source_date"] > record["target_period_end"]:
        raise ValueError(f"{record['id']} 展望日期晚於目標期末，疑有後見偏誤")
    actual, actual_status, actual_date, actual_url = history_actual(record, company)
    if actual_date and actual_date < record["target_period_end"]:
        raise ValueError(f"{record['id']} 實績來源日期早於目標期末")
    result = outcome(record, actual, actual_status)
    if result in {"above", "within", "met"}:
        impact, impact_label = "support", "支持"
    elif result in {"below", "missed"}:
        impact, impact_label = "pressure", "形成壓力"
    else:
        impact, impact_label = "neutral", "不改變"
    reason = {
        "pending_period": "目標季度尚未收錄正式分部實績。",
        "pending_official_result": "需等待全年正式結果，季度進度不當成全年達標。",
        "basis_mismatch": "實績口徑與展望 basis_id 不同，已停止比較。",
        "segment_missing": "正式分部表沒有同名項目，不能用其他項目代替。",
        "metric_missing": "正式分部表未揭露相同指標，保留不可比。",
        "segment_history": "實績由已勾稽的分部歷史自動帶入。",
        "official_result": "實績由下一期公司官方結果人工核對。",
    }[actual_status]
    return {
        **record,
        "target": target_text(record),
        "actual": actual,
        "actual_display": format_value(actual, record.get("unit", "")),
        "actual_status": actual_status,
        "actual_source_date": actual_date,
        "actual_source_url": actual_url,
        "outcome": result,
        "outcome_label": OUTCOME_LABELS[result],
        "verification_note": reason,
        "thesis_title": thesis_title,
        "thesis_impact": impact,
        "thesis_impact_label": impact_label,
        "thesis_note": (
            f"此結果對「{thesis_title}」提供{impact_label}證據；相同實績已計入分部趨勢，不重複加分。"
            if thesis_title and impact != "neutral" else
            "等待同口徑實績或口徑覆核完成前，不改變既有投資論點。"
        ),
    }


def build_payload(inputs: dict[str, Any], history: dict[str, Any], linkage: dict[str, Any]) -> dict[str, Any]:
    history_by_ticker = {row["ticker"]: row for row in history.get("companies", [])}
    linkage_by_ticker = {row["ticker"]: row for row in linkage.get("companies", [])}
    companies = []
    for ticker in DISPLAY_TICKERS:
        config = (inputs.get("companies") or {}).get(ticker)
        segment_company = history_by_ticker.get(ticker)
        if not config or not segment_company:
            raise ValueError(f"{ticker} 缺展望設定或分部歷史")
        records_config = config.get("records", [])
        if config.get("status") not in {"available", "no_comparable_segment_outlook"}:
            raise ValueError(f"{ticker} 展望覆蓋狀態無效")
        if (config.get("status") == "available") != bool(records_config):
            raise ValueError(f"{ticker} 展望覆蓋狀態與紀錄不一致")
        revenue_thesis = next((row.get("title") for row in linkage_by_ticker.get(ticker, {}).get("linked_theses", []) if row.get("metric") == "revenue_growth"), None)
        records = [build_record(row, segment_company, revenue_thesis) for row in records_config]
        completed = [row for row in records if row["outcome"] in {"above", "within", "below", "met", "missed"}]
        pending = [row for row in records if row["outcome"] == "pending"]
        not_comparable = [row for row in records if row["outcome"] == "not_comparable"]
        misses = [row for row in completed if row["outcome"] in {"below", "missed"}]
        successes = [row for row in completed if row["outcome"] in {"above", "within", "met"}]
        if misses:
            signal, label = "pressure", "展望驗證形成壓力"
        elif successes:
            signal, label = "support", "已完成展望多數實現"
        elif pending:
            signal, label = "pending", "等待同口徑實績"
        else:
            signal, label = "unavailable", "沒有可比分部展望"
        fingerprints = [(row["id"], row["outcome"], row["actual"]) for row in records]
        companies.append({
            "ticker": ticker, "name": segment_company.get("name", ticker),
            "coverage_status": config.get("status"), "note": config.get("note"), "review_url": config.get("review_url"),
            "signal": signal, "label": label,
            "counts": {"records": len(records), "completed": len(completed), "pending": len(pending), "not_comparable": len(not_comparable), "success": len(successes), "miss": len(misses)},
            "latest_pending": pending[-1] if pending else None,
            "latest_completed": completed[-1] if completed else None,
            "records": records,
            "fingerprint": stable_hash(fingerprints),
        })
    counts = {
        "available_companies": sum(row["coverage_status"] == "available" for row in companies),
        "completed_records": sum(row["counts"]["completed"] for row in companies),
        "pending_records": sum(row["counts"]["pending"] for row in companies),
        "miss_records": sum(row["counts"]["miss"] for row in companies),
    }
    return {
        "schema_version": 1,
        "updated_at": max(filter(None, [inputs.get("updated_at"), history.get("updated_at"), linkage.get("updated_at")]), default=None),
        "tracked_count": len(companies), "counts": counts,
        "methodology": {
            "scope": "14 家個股；只有具官方來源、明確分部、期間與相同指標的展望才可驗證。",
            "outcomes": "實績高於上限／落在區間／低於下限，或方向實現／未實現；等待與口徑不可比分開標示。",
            "boundary": "公司總指引不代替分部指引；季度進度不當成全年結果；展望驗證不重複加入 SEC 證據分數。",
        },
        "companies": companies,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    counts = payload["counts"]
    lines = [
        "---", "title: 分部展望驗證卡", "tags:", "  - sec", "  - segment", "  - guidance", "---", "",
        "# 🎯 分部展望驗證卡", "",
        f"> 更新：{payload['updated_at']}｜有可比展望 {counts['available_companies']}/14 家｜已驗證 {counts['completed_records']} 項｜待驗證 {counts['pending_records']} 項｜未實現 {counts['miss_records']} 項。", "",
        "## 判讀規則", "",
        f"- **範圍**：{payload['methodology']['scope']}",
        f"- **結果**：{payload['methodology']['outcomes']}",
        f"- **限制**：{payload['methodology']['boundary']}", "",
    ]
    for company in payload["companies"]:
        lines += [f"## {company['ticker']}｜{company['label']}", "", f"- {company['note']}", f"- [公司官方展望頁]({company['review_url']})", ""]
        if not company["records"]:
            lines += ["- 目前沒有可與分部實績同口徑核對的紀錄。", ""]
            continue
        lines += ["| 目標期 | 分部／指標 | 管理層展望 | 後續實績 | 結果 | 論點影響 |", "|---|---|---:|---:|---|---|"]
        for row in company["records"]:
            lines.append(f"| {row['target_period']} | {row['segment_name']}／{row['metric_label']} | {row['target']} | {row['actual_display']} | {row['outcome_label']} | {row['thesis_impact_label']} |")
        lines += ["", *[f"- **{row['target_period']} {row['segment_name']}**：{row['verification_note']} [展望原文]({row['source_url']})" + (f"｜[實績原文]({row['actual_source_url']})" if row.get("actual_source_url") else "") for row in company["records"]], ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--linkage", type=Path, default=DEFAULT_LINKAGE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    args = parser.parse_args()
    payload = build_payload(load_json(args.inputs), load_json(args.history), load_json(args.linkage))
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(render_markdown(payload))
    counts = payload["counts"]
    print(f"分部展望驗證：{payload['tracked_count']} 家；可比 {counts['available_companies']} 家；已驗證 {counts['completed_records']}；待驗證 {counts['pending_records']}；未實現 {counts['miss_records']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
