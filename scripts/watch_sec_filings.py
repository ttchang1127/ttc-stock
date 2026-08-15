#!/usr/bin/env python3
"""Watch SEC submissions for the 14 companies tracked by Sec_kb.

The watcher compares accession numbers with a committed state file.  The first
run establishes a baseline without alerting; later runs emit a Markdown alert
for genuinely new filings and keep an Obsidian-readable event log.

    python3 scripts/watch_sec_filings.py --initialize
    python3 scripts/watch_sec_filings.py
"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE = REPO_ROOT / ".github" / "sec-filing-state.json"
DEFAULT_EVENTS = REPO_ROOT / "sec_filing_alerts.json"
DEFAULT_NOTE = REPO_ROOT / "60_SEC_Filing_Radar" / "SEC_Filing_Alerts.md"
DEFAULT_FINANCIALS = REPO_ROOT / "financials.json"
DEFAULT_DETAILS = REPO_ROOT / "sec_filing_details.json"
DEFAULT_RADAR_DIR = REPO_ROOT / "60_SEC_Filing_Radar"

FORM_GROUPS = {
    "年度財報": {"10-K", "10-K/A", "20-F", "20-F/A"},
    "季度財報": {"10-Q", "10-Q/A"},
    "重大事件": {"8-K", "8-K/A", "6-K", "6-K/A"},
    "內部人持股": {"3", "3/A", "4", "4/A", "5", "5/A", "144", "144/A"},
    "股東會／代理委託": {"DEF 14A", "DEFA14A", "DEF 14C", "DEFR14A"},
    "募資／稀釋": {
        "S-3", "S-3/A", "S-3ASR", "F-3", "F-3/A", "F-3ASR",
        "424B2", "424B3", "424B4", "424B5", "POS AM", "EFFECT",
    },
}
WATCHED_FORMS = set().union(*FORM_GROUPS.values())

CRITICAL_8K_ITEMS = {
    "1.01", "1.02", "2.01", "2.02", "2.03", "2.04", "2.05", "2.06",
    "3.01", "3.02", "3.03", "4.01", "4.02", "5.02",
}
ITEM_LABELS = {
    "1.01": "重大合約", "1.02": "重大合約終止", "2.01": "收購／處分",
    "2.02": "財報／業績", "2.03": "新增重大債務", "2.04": "債務觸發事件",
    "2.05": "重組／裁員", "2.06": "重大減損", "3.01": "下市風險",
    "3.02": "未註冊股權發行", "3.03": "股東權利變更", "4.01": "更換會計師",
    "4.02": "財報不得再依賴／重述", "5.02": "董事／高管異動",
    "5.03": "章程修訂", "7.01": "Reg FD／簡報", "8.01": "其他重大事項",
    "9.01": "附件／財務報表",
}
SEVERITY_LABELS = {"critical": "🔴 重大", "high": "🟠 重要", "medium": "🔵 留意"}
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2}


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def company_ciks(path=DEFAULT_FINANCIALS):
    companies = json.loads(Path(path).read_text())["companies"]
    return {ticker: str(node["cik"]).zfill(10) for ticker, node in sorted(companies.items())}


def fetch_submissions(cik, attempts=3):
    user_agent = os.environ.get(
        "SEC_USER_AGENT",
        "SecKBResearch user@example.com",
    )
    request = urllib.request.Request(
        f"https://data.sec.gov/submissions/CIK{cik}.json",
        headers={"User-Agent": user_agent, "Accept": "application/json"},
    )
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt + 1 == attempts:
                raise
            time.sleep(1.5 * (attempt + 1))


def normalize_items(raw):
    if isinstance(raw, list):
        values = raw
    elif isinstance(raw, str):
        values = raw.split(",")
    else:
        values = []
    return [str(value).strip() for value in values if str(value).strip()]


def form_group(form):
    return next((group for group, forms in FORM_GROUPS.items() if form in forms), "其他")


def classify(form, items):
    group = form_group(form)
    if group in {"年度財報", "季度財報", "募資／稀釋"}:
        return "critical"
    if form.startswith("8-K") and CRITICAL_8K_ITEMS.intersection(items):
        return "critical"
    if group == "重大事件":
        return "high"
    return "medium"


def item_summary(items):
    if not items:
        return "未提供 Item 分類"
    return "、".join(f"{item} {ITEM_LABELS.get(item, '')}".strip() for item in items)


def extract_filings(ticker, cik, payload):
    recent = payload["filings"]["recent"]
    rows = []
    count = len(recent["form"])
    items_column = recent.get("items", [""] * count)
    accepted_column = recent.get("acceptanceDateTime", [""] * count)
    report_column = recent.get("reportDate", [""] * count)
    for index in range(count):
        form = recent["form"][index]
        if form not in WATCHED_FORMS:
            continue
        accession = recent["accessionNumber"][index]
        primary = recent["primaryDocument"][index]
        clean = accession.replace("-", "")
        items = normalize_items(items_column[index] if index < len(items_column) else "")
        rows.append({
            "ticker": ticker,
            "cik": cik,
            "accession": accession,
            "form": form,
            "group": form_group(form),
            "severity": classify(form, items),
            "filing_date": recent["filingDate"][index],
            "accepted_at": accepted_column[index] if index < len(accepted_column) else "",
            "report_date": report_column[index] if index < len(report_column) else "",
            "items": items,
            "items_summary": item_summary(items),
            "primary_document": primary,
            "url": (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{clean}/{primary}"
            ),
            "index_url": (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{clean}/"
                f"{accession}-index.html"
            ),
        })
    return rows


def load_json(path, fallback):
    path = Path(path)
    if not path.exists():
        return fallback
    return json.loads(path.read_text())


def pipe(value):
    return str(value or "—").replace("|", "\\|").replace("\n", " ")


def sorted_events(events):
    return sorted(
        events,
        key=lambda event: (
            event.get("filing_date", ""), event.get("accepted_at", ""),
            -SEVERITY_ORDER.get(event.get("severity"), 9),
        ),
        reverse=True,
    )


def render_table(events, limit=100):
    lines = [
        "| 重要性 | 公司 | 申報 | 日期 | 事件／Item | SEC 原文 |",
        "|---|---|---|---|---|---|",
    ]
    for event in sorted_events(events)[:limit]:
        lines.append(
            "| {severity} | **{ticker}** | {form} | {date} | {summary} | "
            "[原文]({url}) |".format(
                severity=SEVERITY_LABELS.get(event["severity"], event["severity"]),
                ticker=pipe(event["ticker"]), form=pipe(event["form"]),
                date=pipe(event["filing_date"]), summary=pipe(event["items_summary"]),
                url=event["url"],
            )
        )
    return lines


def render_alert(events, errors, checked_at):
    if not events:
        lines = ["## SEC 即時申報偵測", "", "✅ 本次沒有新申報。"]
    else:
        lines = [
            "## SEC 新申報通知", "",
            f"偵測時間：`{checked_at}`；新申報：**{len(events)}** 筆。", "",
            *render_table(events), "",
            "> 此通知只代表 SEC 出現新申報，不等同投資建議；請以 SEC 原文判讀。",
        ]
    if errors:
        lines += ["", "### 查詢警告", ""] + [f"- {ticker}: {message}" for ticker, message in errors]
    return "\n".join(lines) + "\n"


def render_note(history, checked_at, company_count):
    events = history.get("events", [])
    lines = [
        "---", "title: SEC 即時申報雷達", f"updated_at: {checked_at}",
        "tags:", "  - sec/alerts", "  - filings/realtime", "---", "",
        "# 🚨 SEC 即時申報雷達", "",
        f"追蹤 **{company_count} 家公司**；由 SEC submissions API 依 accession number 去重。",
        "GitHub Actions 每 30 分鐘檢查一次；重大／重要申報會建立 GitHub Issue 通知，"
        "Form 4／144 等留意級申報則收進雷達，避免通知轟炸。", "",
        "## 最新申報", "",
    ]
    if events:
        lines += render_table(events, limit=200)
    else:
        lines.append("基準已建立；尚未偵測到基準之後的新申報。")
    lines += [
        "", "## 監控範圍", "",
        "10-K／20-F、10-Q、8-K／6-K、Form 3／4／5／144、DEF 14A、"
        "S-3／F-3／424B 等募資文件。", "",
        "> Schedule 13D／13G 是由外部大股東申報，不一定出現在發行公司的 submissions feed，"
        "目前不宣稱完整覆蓋。", "",
    ]
    return "\n".join(lines)


def write_github_output(path, values):
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def github_warning(title, message):
    if os.environ.get("GITHUB_ACTIONS"):
        safe_title = title.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        safe_message = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::warning title={safe_title}::{safe_message}")


def update_state(ciks, fetched, state, initializing=False):
    """Return unseen filings and replace each successful ticker's SEC snapshot."""
    new_events = []
    for ticker, filings in fetched.items():
        known = set((state.get("companies", {}).get(ticker) or {}).get("seen_accessions", []))
        if not initializing:
            new_events.extend(event for event in filings if event["accession"] not in known)
        state.setdefault("companies", {})[ticker] = {
            "cik": ciks[ticker],
            "seen_accessions": [event["accession"] for event in filings],
        }
    return new_events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initialize", action="store_true", help="Establish baseline without alerting")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--note", type=Path, default=DEFAULT_NOTE)
    parser.add_argument("--financials", type=Path, default=DEFAULT_FINANCIALS)
    parser.add_argument("--details", type=Path, default=DEFAULT_DETAILS)
    parser.add_argument("--radar-dir", type=Path, default=DEFAULT_RADAR_DIR)
    parser.add_argument("--alert-markdown", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--github-output", type=Path, default=os.environ.get("GITHUB_OUTPUT"))
    parser.add_argument("--baseline-days", type=int, default=14)
    args = parser.parse_args()

    checked_at = now_utc()
    ciks = company_ciks(args.financials)
    state_exists = args.state.exists()
    initializing = args.initialize or not state_exists
    state = load_json(args.state, {"schema_version": 1, "companies": {}})
    fetched = {}
    errors = []
    for index, (ticker, cik) in enumerate(ciks.items()):
        try:
            fetched[ticker] = extract_filings(ticker, cik, fetch_submissions(cik))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as exc:
            message = f"{type(exc).__name__}: {exc}"
            errors.append((ticker, message))
            print(f"  ⚠️ {ticker:6s} {message}", file=sys.stderr, flush=True)
            github_warning(f"{ticker} SEC 查詢失敗", message)
        if index + 1 < len(ciks):
            time.sleep(0.12)

    if initializing and errors:
        raise SystemExit("建立基準時有查詢失敗，拒絕寫入不完整狀態")
    if not fetched:
        raise SystemExit("所有 SEC 查詢均失敗")

    new_events = update_state(ciks, fetched, state, initializing=initializing)

    history = load_json(args.events, {"schema_version": 1, "events": []})
    if initializing:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=args.baseline_days)).date().isoformat()
        baseline = [
            dict(event, detected_at=checked_at, baseline=True)
            for filings in fetched.values() for event in filings
            if event["filing_date"] >= cutoff
        ]
        history["events"] = sorted_events(baseline)[:500]
    elif new_events:
        existing = {event["accession"] for event in history.get("events", [])}
        additions = [
            dict(event, detected_at=checked_at, baseline=False)
            for event in new_events if event["accession"] not in existing
        ]
        history["events"] = sorted_events(additions + history.get("events", []))[:500]

    should_write = initializing or bool(new_events)
    if should_write:
        state["schema_version"] = 1
        state["updated_at"] = checked_at
        state["source"] = "SEC submissions API"
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
        history["schema_version"] = 1
        history["updated_at"] = checked_at
        history["source"] = "SEC submissions API; accession-number deduplicated"
        args.events.write_text(json.dumps(history, indent=2, ensure_ascii=False) + "\n")
        args.note.parent.mkdir(parents=True, exist_ok=True)
        args.note.write_text(render_note(history, checked_at, len(ciks)) + "\n")
        from sec_specialized_radars import update_radars
        radar_result = update_radars(
            fetched,
            details_path=args.details,
            radar_dir=args.radar_dir,
            checked_at=checked_at,
        )
        print(
            "專項雷達已更新："
            f"Form 4 交易 {radar_result['form4_transactions']} 筆；"
            f"募資文件 {radar_result['offering_documents']} 份；"
            f"解析警告 {len(radar_result['errors'])}"
        )

    alert = render_alert(new_events, errors, checked_at)
    if args.alert_markdown:
        args.alert_markdown.write_text(alert)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as handle:
            handle.write(alert)

    batch_source = "\n".join(sorted(event["accession"] for event in new_events))
    batch_id = hashlib.sha256(batch_source.encode()).hexdigest()[:10] if batch_source else "none"
    critical = sum(event["severity"] == "critical" for event in new_events)
    notify_count = sum(event["severity"] in {"critical", "high"} for event in new_events)
    write_github_output(args.github_output, {
        "initialized": str(initializing).lower(),
        "new_count": len(new_events),
        "critical_count": critical,
        "notify_count": notify_count,
        "batch_id": batch_id,
    })
    print(f"已檢查 {len(fetched)}/{len(ciks)} 家；新申報 {len(new_events)}；查詢警告 {len(errors)}")
    if initializing:
        print(f"基準已建立：{args.state.relative_to(REPO_ROOT)}")
    for event in sorted_events(new_events):
        print(f"  {SEVERITY_LABELS[event['severity']]} {event['ticker']:6s} "
              f"{event['form']:8s} {event['filing_date']} {event['accession']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
