#!/usr/bin/env python3
"""Build deterministic, source-linked change candidates since the last AI review.

The output is deliberately a draft.  Rules may identify a new risk, an
improvement, or evidence that could change a conclusion, but only a later
human/AI reading may copy an item into sec_daily_editorial.json.
"""

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ALERTS = REPO_ROOT / "sec_filing_alerts.json"
DEFAULT_DETAILS = REPO_ROOT / "sec_filing_details.json"
DEFAULT_ADVANCED = REPO_ROOT / "sec_advanced_radars.json"
DEFAULT_QUARTERLY = REPO_ROOT / "quarterly_financials.json"
DEFAULT_THESIS = REPO_ROOT / "investment_thesis_status.json"
DEFAULT_EDITORIAL = REPO_ROOT / "sec_daily_editorial.json"
DEFAULT_OUTPUT = REPO_ROOT / "sec_daily_change_candidates.json"
DEFAULT_MARKDOWN = REPO_ROOT / "60_SEC_Filing_Radar/SEC_Daily_Change_Candidates.md"

DISPLAY_TICKER = {"GOOGL": "GOOG"}
TYPE_LABELS = {
    "risk": "🔴 新增風險候選",
    "improvement": "🟢 改善候選",
    "conclusion": "🟡 結論變化候選",
}
TYPE_ORDER = {"risk": 0, "conclusion": 1, "improvement": 2}
THESIS_RISK = {
    "maintained": 0,
    "needs-validation": 1,
    "partial-invalidated": 2,
    "major-invalidated": 3,
}


def load_json(path, fallback=None):
    path = Path(path)
    if not path.exists():
        return fallback
    return json.loads(path.read_text())


def parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def is_after_review(event, editorial):
    reviewed = parse_time(editorial.get("reviewed_at"))
    for field in ("detected_at", "accepted_at"):
        timestamp = parse_time(event.get(field))
        if reviewed and timestamp and timestamp > reviewed:
            return True
    return str(event.get("filing_date") or "") > str(editorial.get("window_end") or "")


def metric_value(period, metric):
    value = (period or {}).get("values", {}).get(metric)
    if isinstance(value, dict):
        value = value.get("value")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def percent_change(current, prior):
    if current is None or prior in (None, 0):
        return None
    return (current / prior - 1) * 100


def signed(value, suffix="%"):
    if value is None:
        return "—"
    return f"{'+' if value > 0 else ''}{value:,.1f}{suffix}"


def compact_usd(value):
    if value is None:
        return "金額未完整解析"
    value = float(value)
    for divisor, unit in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= divisor:
            return f"${value / divisor:,.1f}{unit}"
    return f"${value:,.0f}"


def stable_id(kind, ticker, keys):
    raw = "|".join([kind, ticker, *sorted(str(key) for key in keys if key)])
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def make_candidate(kind, ticker, keys, headline, evidence, reason, sources,
                   detected_at, confidence="medium", filing_date=""):
    display = DISPLAY_TICKER.get(ticker, ticker)
    return {
        "id": stable_id(kind, display, keys),
        "ticker": display,
        "type": kind,
        "type_label": TYPE_LABELS[kind],
        "status": "pending_ai_review",
        "confidence": confidence,
        "headline": headline,
        "evidence": [text for text in evidence if text],
        "why_candidate": reason,
        "filing_date": filing_date,
        "detected_at": detected_at,
        "source_keys": sorted({str(key) for key in keys if key}),
        "sources": sources,
    }


def source_as_of(*payloads):
    values = []
    for payload in payloads:
        for key in ("updated_at", "generated_at"):
            if payload and payload.get(key):
                values.append(payload[key])
    return max(values) if values else ""


def filing_candidates(alerts, details, advanced, editorial):
    events = [event for event in alerts.get("events", []) if is_after_review(event, editorial)]
    form144_by_ticker = {}
    advanced_144 = {
        row.get("event", {}).get("accession"): row.get("form144", {})
        for row in advanced.get("insiders", []) if row.get("form144")
    }
    candidates = []
    used_accessions = set()

    for event in events:
        ticker, form, accession = event.get("ticker"), event.get("form", ""), event.get("accession")
        if not ticker or not accession:
            continue
        source = [{"label": f"SEC {form}", "url": event.get("url") or event.get("index_url")}]
        if form == "144":
            form144_by_ticker.setdefault(ticker, []).append(event)
            continue
        if form in {"4", "4/A"}:
            transactions = [
                row for row in details.get("form4", {}).get(accession, {}).get("transactions", [])
                if row.get("code") in {"P", "S"}
            ]
            if not transactions:
                continue
            buys = [row for row in transactions if row.get("code") == "P"]
            sells = [row for row in transactions if row.get("code") == "S"]
            if buys:
                value = sum(float(row.get("value") or 0) for row in buys)
                candidates.append(make_candidate(
                    "improvement", ticker, [accession],
                    f"Form 4 出現 {len(buys)} 列主動買入，列為改善候選",
                    [f"已知買入金額合計 {compact_usd(value)}。",
                     "交易代碼 P 代表公開市場或私下買入；仍需核對占持股與薪酬規模。"],
                    "內部人主動投入資金可能支持信心，但不能單獨推論股價。",
                    source, event.get("detected_at") or event.get("accepted_at"), "medium", event.get("filing_date", ""),
                ))
            if sells:
                planned = sum(row.get("rule_10b5_1") is True for row in sells)
                value = sum(float(row.get("value") or 0) for row in sells)
                candidates.append(make_candidate(
                    "risk", ticker, [accession],
                    f"Form 4 出現 {len(sells)} 列賣出，列為風險候選",
                    [f"已知賣出金額合計 {compact_usd(value)}；其中 {planned}/{len(sells)} 列標示 10b5-1。",
                     "10b5-1 是預先安排交易，訊號強度低於臨時主動賣出。"],
                    "內部人賣出需看計畫屬性、持股比例與交易規模，不直接等於看空。",
                    source, event.get("detected_at") or event.get("accepted_at"),
                    "low" if planned == len(sells) else "medium", event.get("filing_date", ""),
                ))
            used_accessions.add(accession)
            continue

        classification = details.get("offerings", {}).get(accession, {})
        if event.get("group") == "募資／稀釋" and classification.get("category") not in {None, "debt", "other"}:
            candidates.append(make_candidate(
                "risk", ticker, [accession],
                f"{form} 被分類為「{classification.get('label', '潛在稀釋')}」",
                [classification.get("dilution"), classification.get("risk")],
                "這是潛在稀釋文件；是否真正稀釋仍取決於發行、轉股或交易完成條件。",
                source, event.get("detected_at") or event.get("accepted_at"), "high", event.get("filing_date", ""),
            ))
            used_accessions.add(accession)
            continue

        if form.startswith(("10-K", "10-Q", "20-F")):
            candidates.append(make_candidate(
                "conclusion", ticker, [accession], f"新 {form} 需要重讀財務與風險結論",
                [event.get("items_summary") or "定期財報已申報。"],
                "新定期財報可能同時改變營收、利潤、現金流、稀釋與風險結論。",
                source, event.get("detected_at") or event.get("accepted_at"), "high", event.get("filing_date", ""),
            ))
            used_accessions.add(accession)
            continue

        if form.startswith(("8-K", "6-K")) and event.get("severity") in {"critical", "high"}:
            candidates.append(make_candidate(
                "conclusion", ticker, [accession], f"重大 {form} 可能改變既有結論",
                [event.get("items_summary") or "重大事件文件需讀取原文。"],
                "文件重要性只提高重讀優先級，不預設為利多或利空。",
                source, event.get("detected_at") or event.get("accepted_at"), "medium", event.get("filing_date", ""),
            ))
            used_accessions.add(accession)

    for ticker, rows in form144_by_ticker.items():
        accessions = [row["accession"] for row in rows]
        facts = [advanced_144.get(accession, {}) for accession in accessions]
        parsed_facts = [fact for fact in facts if fact]
        planned_shares = sum(float(fact.get("planned_shares") or 0) for fact in parsed_facts)
        planned_value = sum(float(fact.get("planned_value_usd") or 0) for fact in parsed_facts)
        reporters = sorted({fact.get("reporter") for fact in parsed_facts if fact.get("reporter")})
        sources = [{"label": "SEC Form 144", "url": row.get("url") or row.get("index_url")} for row in rows]
        candidates.append(make_candidate(
            "risk", ticker, accessions,
            f"新增 {len(rows)} 份 Form 144 擬售通知，列為低強度風險候選",
            [f"已解析擬售 {planned_shares:,.0f} 股、申報估值 {compact_usd(planned_value)}。" if parsed_facts else "擬售股數／金額尚未完整解析。",
             f"申報人：{'、'.join(reporters)}。" if reporters else "申報人需開啟原文核對。",
             "Form 144 是擬售意向，不等於已成交；需等待後續 Form 4 或市場交易確認。"],
            "集中或大額擬售可能增加供給壓力，但證據強度低於已完成的非 10b5-1 賣出。",
            sources, max((row.get("detected_at") or row.get("accepted_at") or "" for row in rows), default=""),
            "low", max((row.get("filing_date", "") for row in rows), default=""),
        ))
        used_accessions.update(accessions)
    return candidates, used_accessions


def quarterly_candidates(quarterly, editorial, used_accessions):
    editorial_rows = {row.get("ticker"): row for row in editorial.get("companies", [])}
    candidates = []
    for ticker, entry in editorial_rows.items():
        data_ticker = "GOOGL" if ticker == "GOOG" else ticker
        periods = quarterly.get("companies", {}).get(data_ticker, {}).get("periods", [])
        if not periods:
            continue
        latest = periods[0]
        key = "|".join(str(latest.get(field) or "") for field in ("accession", "period_end", "filing_date"))
        if key == entry.get("coverage", {}).get("quarterly_key"):
            continue
        accession = latest.get("accession")
        if accession and accession in used_accessions:
            continue
        year_ago = periods[4] if len(periods) > 4 else None
        revenue = metric_value(latest, "revenue")
        revenue_yoy = percent_change(revenue, metric_value(year_ago, "revenue"))
        gross_margin = metric_value(latest, "gross_margin")
        fcf = metric_value(latest, "free_cash_flow")
        shares_yoy = percent_change(metric_value(latest, "diluted_shares"), metric_value(year_ago, "diluted_shares"))
        evidence = [
            f"財報期末 {latest.get('period_end')}；營收 YoY {signed(revenue_yoy)}。",
            f"毛利率 {signed(gross_margin * 100) if gross_margin is not None else '—'}；FCF {'為正' if fcf is not None and fcf > 0 else ('為負' if fcf is not None else '缺值')}。",
            f"稀釋股數 YoY {signed(shares_yoy)}。",
        ]
        candidates.append(make_candidate(
            "conclusion", data_ticker, [accession or key],
            f"最新季度數字已變更，需要重算財務連續性與結論",
            evidence, "季度指紋與上次 AI 覆核基準不同；規則只列候選，不自行改寫結論。",
            [{"label": f"{latest.get('form') or '季度財報'} 原文", "url": latest.get("url")}],
            quarterly.get("generated_at", ""), "high", latest.get("filing_date", ""),
        ))
    return candidates


def thesis_candidates(thesis, editorial):
    reviewed = parse_time(editorial.get("reviewed_at"))
    recent_changes = {}
    for change in thesis.get("change_log", []):
        detected = parse_time(change.get("detected_at"))
        if reviewed and detected and detected > reviewed:
            recent_changes[change.get("ticker")] = change
    editorial_rows = {"GOOGL" if row.get("ticker") == "GOOG" else row.get("ticker"): row for row in editorial.get("companies", [])}
    candidates = []
    for ticker, current in thesis.get("companies", {}).items():
        entry = editorial_rows.get(ticker)
        if not entry or current.get("fingerprint") == entry.get("coverage", {}).get("thesis_fingerprint"):
            continue
        change = recent_changes.get(ticker)
        if change:
            before, after = change.get("before_status"), change.get("after_status")
            kind = "risk" if THESIS_RISK.get(after, 1) > THESIS_RISK.get(before, 1) else (
                "improvement" if THESIS_RISK.get(after, 1) < THESIS_RISK.get(before, 1) else "conclusion"
            )
            evidence = [
                f"綜合狀態：{change.get('before_label', '—')} → {change.get('after_label', '—')}。",
                *[f"{row.get('title')}：{row.get('before_label')} → {row.get('after_label')}；{row.get('evidence')}" for row in change.get("item_changes", [])],
            ]
            detected_at = change.get("detected_at") or thesis.get("updated_at", "")
        else:
            kind = "conclusion"
            evidence = [f"目前規則化狀態：{current.get('label', '—')}；期末 {current.get('period', '—')}。"]
            detected_at = thesis.get("updated_at", "")
        candidates.append(make_candidate(
            kind, ticker, [current.get("fingerprint")],
            "投資論點狀態或量化證據指紋已改變",
            evidence, "需由 AI 讀取最新季度證據後，決定是否改寫正式綜合結論。",
            [{"label": "最新季度原文", "url": current.get("url")}],
            detected_at, "high" if change else "medium", current.get("period", ""),
        ))
    return candidates


def ownership_and_enforcement_candidates(advanced, editorial, used_accessions):
    editorial_rows = {"GOOGL" if row.get("ticker") == "GOOG" else row.get("ticker"): row for row in editorial.get("companies", [])}
    candidates = []
    for row in advanced.get("ownership_timeline", []):
        ticker, accession = row.get("ticker"), row.get("accession")
        baseline = editorial_rows.get(ticker, {}).get("coverage", {}).get("ownership_accession")
        if not ticker or not accession or accession == baseline or accession in used_accessions:
            continue
        if str(row.get("filing_date") or "") <= str(editorial.get("window_end") or ""):
            continue
        event_type = row.get("event_type", "")
        kind = "risk" if any(word in event_type for word in ("decrease", "exit")) else (
            "improvement" if any(word in event_type for word in ("increase", "entry")) else "conclusion"
        )
        candidates.append(make_candidate(
            kind, ticker, [accession], f"{row.get('form')} 大股東狀態出現新變化",
            [row.get("event_label"), row.get("interpretation")],
            "持股比例也可能受流通股數變化影響，需讀取原表與前次申報。",
            [{"label": f"SEC {row.get('form')}", "url": row.get("url")}],
            advanced.get("updated_at", ""), "medium", row.get("filing_date", ""),
        ))
        used_accessions.add(accession)

    covered = {
        ticker: set(entry.get("coverage", {}).get("enforcement_keys", []))
        for ticker, entry in editorial_rows.items()
    }
    for row in advanced.get("enforcement", []):
        event = row.get("event", {})
        ticker = event.get("ticker") or row.get("ticker")
        key = event.get("accession") or row.get("url") or f"{row.get('date')}|{row.get('title')}"
        if not ticker or key in covered.get(ticker, set()):
            continue
        candidates.append(make_candidate(
            "risk", ticker, [key], "SEC 執法／停牌來源出現新命中",
            [row.get("title") or event.get("items_summary"), row.get("interpretation")],
            "執法或停牌屬高優先級風險來源，需核對官方通知與涉案主體。",
            [{"label": "SEC 官方來源", "url": event.get("url") or row.get("url")}],
            advanced.get("updated_at", ""), "high", event.get("filing_date") or row.get("date", ""),
        ))
    return candidates


def build_payload(alerts, details, advanced, quarterly, thesis, editorial):
    candidates, used = filing_candidates(alerts, details, advanced, editorial)
    candidates += quarterly_candidates(quarterly, editorial, used)
    candidates += thesis_candidates(thesis, editorial)
    candidates += ownership_and_enforcement_candidates(advanced, editorial, used)
    owned = set(editorial.get("portfolio_order", []))
    # Stable passes keep holdings and candidate type as the primary order while
    # sorting ISO dates newest-first inside each group.
    candidates.sort(key=lambda row: (row["ticker"], row["id"]))
    candidates.sort(
        key=lambda row: str(row.get("filing_date") or row.get("detected_at") or ""),
        reverse=True,
    )
    candidates.sort(key=lambda row: TYPE_ORDER[row["type"]])
    candidates.sort(key=lambda row: 0 if row["ticker"] in owned else 1)
    counts = {kind: sum(row["type"] == kind for row in candidates) for kind in TYPE_LABELS}
    return {
        "schema_version": 1,
        "generated_at": source_as_of(alerts, advanced, quarterly, thesis),
        "editorial_reviewed_at": editorial.get("reviewed_at"),
        "editorial_window_end": editorial.get("window_end"),
        "status": "pending_ai_review" if candidates else "no_new_candidates",
        "candidate_count": len(candidates),
        "company_count": len({row["ticker"] for row in candidates}),
        "counts": counts,
        "method": "規則只建立候選：新風險、改善或可能改變結論；不得自動寫入正式 AI 判讀。",
        "candidates": candidates,
    }


def render_markdown(payload):
    lines = [
        "---", "title: SEC 每日變更候選稿", f"generated_at: {payload['generated_at']}",
        f"editorial_reviewed_at: {payload['editorial_reviewed_at']}", "tags:", "  - sec/daily",
        "  - ai/review-pending", "---", "", "# SEC 每日變更候選稿", "",
        "> 本頁由規則自動產生，只是待 AI 覆核候選，不是最終判讀、利多／利空或買賣建議。", "",
        f"- 候選：**{payload['candidate_count']} 項／{payload['company_count']} 家**",
        f"- 新增風險候選：**{payload['counts']['risk']}**",
        f"- 改善候選：**{payload['counts']['improvement']}**",
        f"- 結論變化候選：**{payload['counts']['conclusion']}**", "",
    ]
    if not payload["candidates"]:
        lines.append("目前沒有晚於上次 AI 覆核基準的新候選。")
    for index, row in enumerate(payload["candidates"], 1):
        lines += [f"## {index}. {row['type_label']}｜{row['ticker']}", "", row["headline"], ""]
        lines += [f"- {text}" for text in row["evidence"]]
        lines += [f"- **為何列入**：{row['why_candidate']}", f"- **證據強度**：{row['confidence']}"]
        links = "｜".join(f"[{source['label']}]({source['url']})" for source in row["sources"] if source.get("url")) or "—"
        lines += [f"- **官方來源**：{links}", ""]
    return "\n".join(lines).rstrip() + "\n"


def render_alert(payload, candidate_ids=None):
    candidates = payload["candidates"]
    if candidate_ids is not None:
        candidate_ids = set(candidate_ids)
        candidates = [row for row in candidates if row["id"] in candidate_ids]
    if not candidates:
        return ""
    company_count = len({row["ticker"] for row in candidates})
    lines = ["", "## 每日變更候選稿（待 AI 覆核）", "",
             f"本批新增 **{len(candidates)} 項／{company_count} 家**候選；規則結果不是最終判讀。", ""]
    for row in candidates[:12]:
        url = next((source.get("url") for source in row["sources"] if source.get("url")), "")
        source = f"[原文]({url})" if url else "原文缺值"
        lines.append(f"- {row['type_label']} **{row['ticker']}**：{row['headline']}（{source}）")
    return "\n".join(lines) + "\n"


def append_text(path, content):
    if path and content:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(content)


def write_github_output(path, values):
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alerts", type=Path, default=DEFAULT_ALERTS)
    parser.add_argument("--details", type=Path, default=DEFAULT_DETAILS)
    parser.add_argument("--advanced", type=Path, default=DEFAULT_ADVANCED)
    parser.add_argument("--quarterly", type=Path, default=DEFAULT_QUARTERLY)
    parser.add_argument("--thesis", type=Path, default=DEFAULT_THESIS)
    parser.add_argument("--editorial", type=Path, default=DEFAULT_EDITORIAL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--alert-markdown", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--github-output", type=Path, default=os.environ.get("GITHUB_OUTPUT"))
    args = parser.parse_args()

    inputs = [load_json(path, {}) for path in (args.alerts, args.details, args.advanced, args.quarterly, args.thesis, args.editorial)]
    if not inputs[-1].get("reviewed_at"):
        raise SystemExit("sec_daily_editorial.json 缺 reviewed_at，不能建立覆核後候選")
    previous = load_json(args.output, {})
    previous_ids = {row.get("id") for row in previous.get("candidates", []) if row.get("id")}
    payload = build_payload(*inputs)
    current_ids = {row["id"] for row in payload["candidates"]}
    new_ids = current_ids - previous_ids
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    args.markdown.write_text(render_markdown(payload))
    alert = render_alert(payload, new_ids)
    append_text(args.alert_markdown, alert)
    append_text(args.summary, alert)
    batch_source = "\n".join(sorted(new_ids))
    batch_id = hashlib.sha256(batch_source.encode()).hexdigest()[:10] if batch_source else "none"
    write_github_output(args.github_output, {
        "candidate_count": payload["candidate_count"],
        "notify_count": len(new_ids),
        "risk_count": payload["counts"]["risk"],
        "candidate_batch_id": batch_id,
    })
    print(
        f"每日變更候選稿：{payload['candidate_count']} 項／{payload['company_count']} 家；"
        f"本批新增 {len(new_ids)} 項；待 AI 覆核"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
