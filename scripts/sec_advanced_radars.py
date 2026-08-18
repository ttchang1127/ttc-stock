#!/usr/bin/env python3
"""Build the advanced SEC filing, ownership, governance and enforcement radars."""

import argparse
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "sec_advanced_radars.json"
DEFAULT_DIR = ROOT / "60_SEC_Filing_Radar"
FINANCIALS = ROOT / "financials.json"

ACCOUNTING_FORMS = {"UPLOAD", "CORRESP"}
PROXY_FORMS = {"PRE 14A", "PRE 14C", "DEF 14A", "DEFA14A", "DEF 14C", "DEFR14A", "DEFM14A", "PREM14A", "PX14A6G"}
INSIDER_FORMS = {"3", "3/A", "4", "4/A", "5", "5/A", "144", "144/A"}
MA_FORMS = {"S-4", "S-4/A", "F-4", "F-4/A", "425", "SC TO-C", "SC TO-I", "SC TO-I/A", "SC TO-T", "SC TO-T/A", "SC 14D9", "SC 14D9/A", "SC 13E3", "SC 13E3/A"}
FINANCIAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "10-Q", "10-Q/A", "8-K", "8-K/A", "6-K", "6-K/A"}
ATTACHMENT_TYPES = ("EX-2", "EX-10", "EX-19", "EX-21", "EX-23", "EX-97", "EX-99")

SIGNAL_RULES = {
    "繼續經營": r"substantial doubt.{0,120}(?:ability|continue as a going concern)",
    "重大內控缺失": r"identified.{0,50}(?:a|one or more) material weakness|management concluded.{0,160}internal control.{0,80}(?:was|were) not effective|our internal control.{0,80}(?:was|were) not effective",
    "重述／不得信賴": r"(?:will|must|has|have|had) restat(?:e|ed)|financial statements.{0,100}should no longer be relied upon",
    "收入認列": r"revenue recognition|performance obligation",
    "客戶集中": r"customer concentration|significant customer|major customer",
    "減損": r"impairment|goodwill impairment",
    "訴訟／或有事項": r"litigation|legal proceedings|contingenc(?:y|ies)",
    "關係人交易": r"related party|related-party",
    "股份薪酬": r"stock-based compensation|share-based compensation",
    "債務／到期": r"debt maturit|covenant|liquidity requirement",
    "非 GAAP": r"non-gaap|non gaap",
    "部門報導": r"reportable segment|segment reporting",
    "XBRL 標記": r"xbrl|inline xbrl",
}

FORM_MEANINGS = {
    "UPLOAD": "SEC 審閱意見函；公開時通常已距審閱結束至少 20 個工作日，不是即時執法警報。",
    "CORRESP": "公司對 SEC 審閱意見的回覆；可用來看會計判斷與揭露如何被質疑。",
    "SC 13D": "持股超過 5% 且可能有影響控制意圖的受益所有權申報。",
    "SC 13G": "持股超過 5% 的被動型／免豁型受益所有權申報。",
    "DEF 14A": "正式代理委託書；含董事、高管薪酬、審計費用與股東提案。",
    "144": "關係人擬賣出受限制／控制證券的通知；是擬定出售，不等於已成交。",
}

ENFORCEMENT_FEEDS = {
    "litigation": "https://www.sec.gov/enforcement-litigation/litigation-releases/rss",
    "administrative": "https://www.sec.gov/enforcement-litigation/administrative-proceedings/rss",
    "suspension": "https://www.sec.gov/enforcement-litigation/trading-suspensions/rss",
}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch(url, accept="*/*"):
    request = urllib.request.Request(url, headers={
        "User-Agent": os.environ.get("SEC_USER_AGENT", "SecKBResearch user@example.com"),
        "Accept": accept,
    })
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read()


def html_text(raw):
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def full_submission_url(event):
    return event["index_url"].replace("-index.html", ".txt")


def parse_submission_documents(raw, event):
    text = raw.decode("utf-8", errors="replace")
    base = event["index_url"].rsplit("/", 1)[0] + "/"
    documents = []
    for block in re.findall(r"(?is)<DOCUMENT>(.*?)</DOCUMENT>", text):
        def field(name):
            match = re.search(rf"(?im)^<{name}>\s*([^\r\n<]+)", block)
            return match.group(1).strip() if match else ""
        form_type = field("TYPE")
        filename = field("FILENAME")
        description = field("DESCRIPTION")
        if not filename:
            continue
        documents.append({
            "type": form_type,
            "filename": filename,
            "description": description,
            "url": urllib.parse.urljoin(base, filename),
        })
    return documents


def detect_signals(text):
    found = []
    for label, pattern in SIGNAL_RULES.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            start = max(0, match.start() - 110)
            end = min(len(text), match.end() + 170)
            found.append({"label": label, "snippet": text[start:end].strip()})
    return found


def normalize_cached_enrichment(row):
    """Apply current precision rules to cached snippets without re-downloading."""
    cleaned = dict(row)
    signals = []
    for signal in row.get("signals", []):
        pattern = SIGNAL_RULES.get(signal.get("label"))
        if pattern and re.search(pattern, signal.get("snippet", ""), re.IGNORECASE):
            signals.append(signal)
    cleaned["signals"] = signals
    cleaned["attachments"] = [
        item for item in row.get("attachments", [])
        if str(item.get("type", "")).upper().startswith(ATTACHMENT_TYPES)
    ]
    if cleaned.get("event", {}).get("form") not in {"DEF 14A", "DEFR14A", "DEFM14A", "PRE 14A"}:
        cleaned["metrics"] = {}
    else:
        cleaned["metrics"] = sanitize_proxy_metrics(cleaned.get("metrics", {}))
    return cleaned


def proxy_metrics(text):
    patterns = {
        "ceo_total_compensation_usd": r"(?:CEO|chief executive officer).{0,120}?total compensation.{0,80}?\$\s*([\d,]+)",
        "median_employee_compensation_usd": r"median employee.{0,120}?\$\s*([\d,]+)",
        "ceo_pay_ratio": r"(?:pay ratio|ratio of).{0,100}?([\d,.]+)\s*(?:to|:)\s*1",
        "audit_fees_usd": r"audit fees.{0,100}?\$\s*([\d,]+)",
    }
    metrics = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group(1).replace(",", "")
            try:
                metrics[key] = float(value)
            except ValueError:
                pass
    return sanitize_proxy_metrics(metrics)


def sanitize_proxy_metrics(metrics):
    cleaned = dict(metrics or {})
    for key in ("ceo_total_compensation_usd", "median_employee_compensation_usd", "audit_fees_usd"):
        if key in cleaned and cleaned[key] < 100_000:
            cleaned.pop(key)
    if cleaned.get("ceo_pay_ratio", 0) < 5:
        cleaned.pop("ceo_pay_ratio", None)
    if (
        cleaned.get("median_employee_compensation_usd") is not None
        and cleaned.get("ceo_total_compensation_usd") is not None
        and cleaned["median_employee_compensation_usd"] >= cleaned["ceo_total_compensation_usd"]
    ):
        cleaned.pop("median_employee_compensation_usd", None)
    return cleaned


def parse_form144(raw):
    root = ElementTree.fromstring(raw)
    values = {}
    for node in root.iter():
        name = node.tag.rsplit("}", 1)[-1]
        if node.text and name in {
            "nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold", "relationshipToIssuer",
            "noOfUnitsSold", "aggregateMarketValue", "noOfUnitsOutstanding", "approxSaleDate", "remarks",
        }:
            values.setdefault(name, []).append(node.text.strip())
    number = lambda name: sum(float(v.replace(",", "")) for v in values.get(name, []) if re.fullmatch(r"[\d,.]+", v))
    return {
        "reporter": (values.get("nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold") or ["—"])[0],
        "relationship": "、".join(values.get("relationshipToIssuer", [])) or "—",
        "planned_shares": number("noOfUnitsSold"),
        "planned_value_usd": number("aggregateMarketValue"),
        "shares_outstanding": max([float(v.replace(",", "")) for v in values.get("noOfUnitsOutstanding", [])] or [0]),
        "approx_sale_date": "、".join(values.get("approxSaleDate", [])) or "—",
        "remarks": " ".join(values.get("remarks", [])),
    }


def load_companies(path=FINANCIALS):
    raw = json.loads(Path(path).read_text())["companies"]
    result = {}
    for ticker, node in raw.items():
        result[ticker] = {
            "cik": str(node["cik"]).zfill(10),
            "name": node.get("entity_name") or ticker,
        }
    return result


def enrich_event(event, need_content=True):
    result = {"event": event, "signals": [], "attachments": [], "metrics": {}}
    if not need_content:
        return result
    raw = fetch(full_submission_url(event))
    documents = parse_submission_documents(raw, event)
    result["attachments"] = [d for d in documents if d["type"].upper().startswith(ATTACHMENT_TYPES)]
    text = html_text(raw)
    result["signals"] = detect_signals(text)
    result["metrics"] = proxy_metrics(text)
    return result


def search_13dg(ticker, company, years=3):
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=365 * years + 1)
    query = {
        "q": company["name"],
        "forms": "SC 13D,SC 13D/A,SC 13G,SC 13G/A",
        "dateRange": "custom", "startdt": start.isoformat(), "enddt": end.isoformat(),
        "from": "0", "size": "100",
    }
    url = "https://efts.sec.gov/LATEST/search-index?" + urllib.parse.urlencode(query)
    payload = json.loads(fetch(url, "application/json"))
    rows = {}
    cik_marker = f"CIK {company['cik']}"
    ticker_marker = f"({ticker})"
    for hit in payload.get("hits", {}).get("hits", []):
        source = hit.get("_source", {})
        if source.get("sequence") != 1 or source.get("form") not in {"SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A"}:
            continue
        names = source.get("display_names", [])
        if not any(cik_marker in name or ticker_marker in name for name in names):
            continue
        accession = source.get("adsh", "")
        clean = accession.replace("-", "")
        owners = [name for name in names if cik_marker not in name and ticker_marker not in name]
        rows[accession] = {
            "ticker": ticker, "form": source.get("form"), "filing_date": source.get("file_date"),
            "accession": accession, "reporting_persons": owners,
            "meaning": FORM_MEANINGS["SC 13D" if source.get("form", "").startswith("SC 13D") else "SC 13G"],
            "url": f"https://www.sec.gov/Archives/edgar/data/{int(company['cik'])}/{clean}/{accession}-index.html",
        }
    return list(rows.values())


def enforcement_matches(companies):
    aliases = {}
    for ticker, company in companies.items():
        base = re.sub(r"\b(INC|CORPORATION|CORP|PLC|LIMITED|LTD|HOLDINGS|COMPANY)\b", "", company["name"].upper())
        base = re.sub(r"\s+", " ", base).strip()
        aliases[ticker] = [company["name"], base] if len(base) >= 5 else [company["name"]]
    rows = []
    for category, url in ENFORCEMENT_FEEDS.items():
        raw = fetch(url, "application/rss+xml")
        # Some SEC RSS titles contain a literal ampersand (for example a legal
        # entity named "A & Co.") even though XML requires it to be escaped.
        raw = re.sub(br"&(?!#\d+;|#x[0-9A-Fa-f]+;|[A-Za-z][A-Za-z0-9]+;)", b"&amp;", raw)
        root = ElementTree.fromstring(raw)
        for item in root.findall(".//item"):
            title = item.findtext("title", "")
            description = html_text(item.findtext("description", ""))
            haystack = f"{title} {description}".lower()
            matched = []
            for ticker, names in aliases.items():
                if any(re.search(rf"\b{re.escape(name.lower())}\b", haystack) for name in names):
                    matched.append(ticker)
            if matched:
                rows.append({
                    "category": category, "tickers": matched, "title": title,
                    "date": item.findtext("pubDate", ""), "url": item.findtext("link", ""),
                })
    return rows


def event_rows(fetched, forms, limit_per_ticker):
    rows = []
    for ticker, events in sorted(fetched.items()):
        chosen = sorted((e for e in events if e["form"] in forms), key=lambda e: (e["filing_date"], e.get("accepted_at", "")), reverse=True)
        rows.extend(chosen[:limit_per_ticker])
    return rows


def render_simple_note(title, tag, intro, rows, checked_at):
    lines = ["---", f"title: {title}", f"updated_at: {checked_at}", "tags:", f"  - {tag}", "---", "", f"# {title}", "", intro, "",
             "| 日期 | 公司 | 表單 | 重點／意義 | SEC |", "|---|---|---|---|---|"]
    for row in rows:
        event = row.get("event", row)
        labels = [signal["label"] for signal in row.get("signals", [])]
        attachments = row.get("attachments", [])
        detail = "、".join(labels[:5]) or FORM_MEANINGS.get(event.get("form"), event.get("items_summary", "請開啟原文判讀"))
        if attachments:
            detail += f"；重要附件 {len(attachments)} 份"
        lines.append(f"| {event.get('filing_date', '—')} | **{event.get('ticker', '—')}** | {event.get('form', '—')} | {detail} | [原文]({event.get('url', event.get('index_url', '#'))}) |")
    if not rows:
        lines.append("| — | — | — | 目前沒有命中的追蹤公司資料 | — |")
    lines += ["", f"> 最後檢查：`{checked_at}`。關鍵字命中是閱讀導航，不等於會計結論或利多／利空。", ""]
    return "\n".join(lines)


def render_ownership_note(rows, checked_at):
    lines = ["---", "title: 13D／13G 大股東雷達", f"updated_at: {checked_at}", "tags:", "  - sec/ownership", "---", "", "# 🐘 13D／13G 大股東雷達", "",
             "由 SEC EDGAR 全文索引搜尋發行人，不依賴公司 submissions feed。", "", "| 日期 | 公司 | 表單 | 申報人 | 代表意義 |", "|---|---|---|---|---|"]
    for row in sorted(rows, key=lambda r: r["filing_date"], reverse=True):
        lines.append(f"| {row['filing_date']} | **{row['ticker']}** | [{row['form']}]({row['url']}) | {'、'.join(row['reporting_persons']) or '—'} | {row['meaning']} |")
    lines += ["", "> 13D／13G 的 5% 是受益所有權申報門檻；修正案常是持股比例、資金來源或目的改變，需開原文比對。", ""]
    return "\n".join(lines)


def render_insider_note(rows, checked_at):
    lines = ["---", "title: Form 144＋3／4／5 彙總", f"updated_at: {checked_at}", "tags:", "  - sec/insiders", "---", "", "# 👤 Form 144＋3／4／5 彙總", "",
             "| 申報日 | 公司 | 表單 | 數字／意義 | SEC |", "|---|---|---|---|---|"]
    for row in rows:
        event = row["event"]
        if row.get("form144"):
            item = row["form144"]
            pct = item["planned_shares"] / item["shares_outstanding"] * 100 if item["shares_outstanding"] else None
            detail = f"{item['reporter']}；擬售 {item['planned_shares']:,.0f} 股／${item['planned_value_usd']:,.0f}"
            if pct is not None:
                detail += f"，約占流通股 {pct:.3f}%"
            if "tax" in item["remarks"].lower():
                detail += "；備註指向扣稅用途"
        else:
            detail = FORM_MEANINGS.get(event["form"], "初始持股／交易／延後申報；需搭配交易代碼判讀。")
        lines.append(f"| {event['filing_date']} | **{event['ticker']}** | {event['form']} | {detail} | [原文]({event['url']}) |")
    lines += ["", "> Form 144 是擬售通知，Form 4 才是已發生的內部人持股變動；兩者不應重複當成兩次賣出。", ""]
    return "\n".join(lines)


def render_enforcement_note(rows, checked_at):
    labels = {"litigation": "訴訟發布", "administrative": "行政程序", "suspension": "交易停牌"}
    lines = ["---", "title: SEC 執法與停牌通知", f"updated_at: {checked_at}", "tags:", "  - sec/enforcement", "---", "", "# ⚖️ SEC 執法與停牌通知", "", "| 日期 | 公司 | 類別 | 標題 |", "|---|---|---|---|"]
    for row in rows:
        lines.append(f"| {row['date']} | **{'、'.join(row['tickers'])}** | {labels[row['category']]} | [{row['title']}]({row['url']}) |")
    if not rows:
        lines.append("| — | — | — | 目前 SEC RSS 沒有命中追蹤公司 |")
    lines += ["", "> 來源是 SEC 訴訟發布、行政程序與交易停牌 RSS；同名實體可能誤命中，開啟原文確認法律實體。", ""]
    return "\n".join(lines)


def update_radars(fetched, output=DEFAULT_OUTPUT, radar_dir=DEFAULT_DIR, checked_at=None, include_external=True):
    checked_at = checked_at or utc_now()
    companies = load_companies()
    errors = []
    output = Path(output)
    previous = json.loads(output.read_text()) if output.exists() else {}
    existing = {}
    for category in ("footnotes", "accounting_review", "governance"):
        for row in previous.get(category, []):
            event = row.get("event", {})
            if event.get("accession"):
                existing[event["accession"]] = row
    existing_insiders = {
        row.get("event", {}).get("accession"): row
        for row in previous.get("insiders", []) if row.get("event", {}).get("accession")
    }
    cache = {"schema_version": 1, "updated_at": checked_at, "source": "SEC EDGAR submissions, EFTS and enforcement RSS"}

    def enrich_many(events, content=True):
        rows = []
        for event in events:
            if event["accession"] in existing:
                cached = normalize_cached_enrichment(existing[event["accession"]])
                cached["event"] = event
                rows.append(cached)
                continue
            try:
                rows.append(enrich_event(event, content))
                if content:
                    time.sleep(0.11)
            except Exception as exc:
                errors.append(f"{event['ticker']} {event['accession']}: {type(exc).__name__}: {exc}")
                rows.append({"event": event, "signals": [], "attachments": []})
        return rows

    footnotes = enrich_many(event_rows(fetched, FINANCIAL_FORMS, 2))
    accounting = enrich_many(event_rows(fetched, ACCOUNTING_FORMS, 6))
    governance = enrich_many(event_rows(fetched, PROXY_FORMS, 3))
    for row in governance:
        if row["event"]["form"] not in {"DEF 14A", "DEFR14A", "DEFM14A", "PRE 14A"}:
            row["metrics"] = {}

    insiders = []
    for event in event_rows(fetched, INSIDER_FORMS, 12):
        if event["accession"] in existing_insiders:
            cached = dict(existing_insiders[event["accession"]])
            cached["event"] = event
            insiders.append(cached)
            continue
        row = {"event": event}
        if event["form"] in {"144", "144/A"}:
            try:
                raw_url = re.sub(r"/xsl[^/]+/", "/", event["url"], flags=re.IGNORECASE)
                row["form144"] = parse_form144(fetch(raw_url))
                time.sleep(0.11)
            except Exception as exc:
                errors.append(f"144 {event['accession']}: {type(exc).__name__}: {exc}")
        insiders.append(row)
    mergers = enrich_many(event_rows(fetched, MA_FORMS, 8), False)

    ownership = []
    enforcement = []
    if include_external:
        for ticker, company in sorted(companies.items()):
            try:
                ownership.extend(search_13dg(ticker, company))
            except Exception as exc:
                errors.append(f"13D/G {ticker}: {type(exc).__name__}: {exc}")
            time.sleep(0.11)
        try:
            enforcement = enforcement_matches(companies)
        except Exception as exc:
            errors.append(f"enforcement: {type(exc).__name__}: {exc}")

    cache.update({"footnotes": footnotes, "accounting_review": accounting, "ownership_13dg": ownership,
                  "governance": governance, "insiders": insiders, "mergers": mergers,
                  "enforcement": enforcement, "errors": errors})
    output.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n")
    radar_dir = Path(radar_dir)
    radar_dir.mkdir(parents=True, exist_ok=True)
    notes = {
        "Footnotes_Attachments_Radar.md": render_simple_note("📎 財報附註／附件雷達", "sec/footnotes", "索引財報主文的風險關鍵字與 EX-2／10／19／21／97／99 等重要附件。", footnotes, checked_at),
        "Accounting_Review_Radar.md": render_simple_note("🧮 UPLOAD／CORRESP 會計審閱雷達", "sec/accounting-review", "UPLOAD 是 SEC 意見函，CORRESP 是公司回覆；兩者成對閱讀才能看出審閱問題與解法。", accounting, checked_at),
        "Governance_Compensation_Radar.md": render_simple_note("🏛️ DEF 14A 治理與薪酬分析", "sec/governance", "追蹤正式／預備代理委託書、審計費用、CEO 薪酬、中位員工薪酬與 pay ratio；正則無法穩定辨識的數字保留缺值。", governance, checked_at),
        "Mergers_Tender_Radar.md": render_simple_note("🤝 併購／公開收購雷達", "sec/ma", "S-4／F-4、425、SC TO、SC 14D9 與 SC 13E3 提供交易條件、對價、程序與公平性意見線索。", mergers, checked_at),
        "Schedule13DG_Ownership_Radar.md": render_ownership_note(ownership, checked_at),
        "Insider_Forms_345144_Radar.md": render_insider_note(insiders, checked_at),
        "SEC_Enforcement_Radar.md": render_enforcement_note(enforcement, checked_at),
    }
    for filename, content in notes.items():
        (radar_dir / filename).write_text(content + "\n")
    return {"counts": {key: len(cache[key]) for key in ("footnotes", "accounting_review", "ownership_13dg", "governance", "insiders", "mergers", "enforcement")}, "errors": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, default=ROOT / "sec_filing_alerts.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--radar-dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--no-external", action="store_true")
    args = parser.parse_args()
    events = json.loads(args.events.read_text()).get("events", [])
    fetched = {}
    for event in events:
        fetched.setdefault(event["ticker"], []).append(event)
    result = update_radars(fetched, args.output, args.radar_dir, include_external=not args.no_external)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
