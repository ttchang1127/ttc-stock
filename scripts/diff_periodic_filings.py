#!/usr/bin/env python3
"""Compare the latest two comparable SEC periodic filings for each company.

Domestic issuers use the latest two 10-Q filings when available, falling back
to two 10-Ks.  Foreign private issuers use two 20-Fs because 6-K contents are
not standardized.  The output is paragraph-level navigation, not a semantic
or investment conclusion.
"""

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from fetch_sec import ITEM, clean_html_to_text, heading_positions, loose

ROOT = Path(__file__).resolve().parent.parent
DETAILS_PATH = ROOT / "sec_filing_details.json"
OUTPUT_PATH = ROOT / "filing_text_changes.json"
MIN_PARAGRAPH = 120
SAME = 0.60
REWRITTEN = 0.32
EXCERPT_CHARS = 760

SECTION_SPECS = {
    "10-Q": {
        "risk_factors": (
            "風險因素（Part II Item 1A）",
            ITEM("1a") + loose("risk factors") + r"[^\n]*|" + loose("risk factors") + r"(?=\n)",
            ITEM("2") + r"(?:unregistered|issuer purchases)[^\n]*|"
            + loose("unregistered sales of equity securities") + r"[^\n]*|"
            + loose("issuer purchases of equity securities") + r"[^\n]*",
        ),
        "management_discussion": (
            "MD&A 管理層討論（Part I Item 2）",
            ITEM("2") + r"management.{0,4}s[ \t]*discussion[^\n]*|"
            + r"management.{0,4}s[ \t]*discussion and analysis of financial condition[^\n]*",
            ITEM("3") + r"quantitative[^\n]*|" + ITEM("4") + r"controls[^\n]*|"
            + loose("quantitative and qualitative disclosures about market risk") + r"[^\n]*",
        ),
    },
    "10-K": {
        "risk_factors": (
            "風險因素（Item 1A）",
            ITEM("1a") + loose("risk factors") + r"[^\n]*|" + loose("risk factors") + r"(?=\n)",
            ITEM("1b") + r"unresolved[^\n]*|" + ITEM("2") + loose("propert") + r"[^\n]*",
        ),
        "management_discussion": (
            "MD&A 管理層討論（Item 7）",
            ITEM("7") + r"management.{0,4}s[ \t]*discussion[^\n]*",
            ITEM("7a") + r"quantitative[^\n]*|" + ITEM("8") + loose("financial statements") + r"[^\n]*",
        ),
    },
    "20-F": {
        "risk_factors": (
            "風險因素（Item 3.D）",
            ITEM("3") + r"d\.?[ \t]*" + loose("risk factors") + r"[^\n]*|" + loose("risk factors") + r"(?=\n)",
            ITEM("4") + loose("information on the company") + r"[^\n]*|"
            + loose("information on the company") + r"(?=\n)",
        ),
        "management_discussion": (
            "營運與財務回顧（Item 5）",
            ITEM("5") + loose("operating and financial") + r"[^\n]*|"
            + loose("operating and financial reviews and prospects") + r"(?=\n)|"
            + loose("operating and financial review") + r"(?=\n)",
            ITEM("6") + loose("directors") + r"[^\n]*|"
            + loose("directors, senior management and employees") + r"(?=\n)",
        ),
    },
}

TOPICS = {
    "流動性／債務": ("liquidity", "debt", "covenant", "borrow", "credit facility", "going concern"),
    "需求／客戶": ("demand", "customer", "revenue", "sales", "order", "backlog"),
    "庫存／供應鏈": ("inventory", "supply chain", "supplier", "foundry", "capacity", "shortage"),
    "毛利／成本": ("gross margin", "margin", "pricing", "cost", "profitability"),
    "法規／訴訟": ("regulation", "regulatory", "litigation", "legal proceeding", "export control", "tariff"),
    "資安／資料": ("cyber", "security breach", "data privacy", "information security"),
    "減損／商譽": ("impairment", "goodwill", "write-down", "write off"),
    "內部控制": ("internal control", "material weakness", "remediation", "disclosure control"),
}

ESCALATION = (
    "materially increased", "has increased", "have increased", "increasing risk",
    "substantial doubt", "material weakness", "more likely", "significantly adversely",
)
EASING = (
    "no material changes", "not material", "no longer", "has decreased",
    "have decreased", "remediated", "resolved", "less likely",
)


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch_html(url, attempts=3):
    headers = {
        "User-Agent": os.environ.get("SEC_USER_AGENT", "SecKBResearch user@example.com"),
        "Accept": "text/html,application/xhtml+xml",
    }
    request = urllib.request.Request(url, headers=headers)
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return response.read().decode("utf-8", errors="ignore")
        except (urllib.error.URLError, TimeoutError):
            if attempt + 1 == attempts:
                raise
            time.sleep(1.5 * (attempt + 1))


def extract_section(text, start_pattern, end_pattern):
    candidates = []
    starts = heading_positions(text, start_pattern)
    ends = heading_positions(text, end_pattern)
    for start in starts:
        following = [end for end in ends if end > start]
        if not following:
            continue
        body = text[start:following[0]].strip()
        if len(body) >= 80:
            candidates.append(body)
    return max(candidates, key=len) if candidates else None


def normalize(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def paragraphs(text):
    if not text:
        return []
    raw = [normalize(line) for line in text.splitlines() if normalize(line)]
    out, buffer = [], ""
    for line in raw:
        if re.fullmatch(r"(?:item|part)\s+[0-9ivx\.a-z\- ]+", line, re.I):
            continue
        buffer = f"{buffer} {line}".strip() if buffer else line
        if line.endswith((".", "?", "!", ";", '"', "”")):
            if len(buffer) >= MIN_PARAGRAPH:
                out.append(buffer)
            buffer = ""
    if len(buffer) >= MIN_PARAGRAPH:
        out.append(buffer)
    if not out and len(normalize(text)) >= 50:
        out.append(normalize(text))
    return out


def words(text):
    return set(re.findall(r"[a-z]{4,}", text.lower()))


def similarity(left, right):
    a, b = words(left), words(right)
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def topics_for(*texts):
    haystack = " ".join(texts).lower()
    return [label for label, terms in TOPICS.items() if any(term in haystack for term in terms)]


def language_signal(previous, latest):
    old = previous.lower()
    new = latest.lower()
    escalation = [phrase for phrase in ESCALATION if phrase in new and phrase not in old]
    easing = [phrase for phrase in EASING if phrase in new and phrase not in old]
    if escalation and not easing:
        return {"code": "possible_escalation", "label": "可能升高措辭", "triggers": escalation}
    if easing and not escalation:
        return {"code": "possible_easing", "label": "可能緩和措辭", "triggers": easing}
    return {"code": "rewritten", "label": "大幅改寫", "triggers": escalation + easing}


def excerpt(text):
    value = normalize(text)
    return value if len(value) <= EXCERPT_CHARS else value[:EXCERPT_CHARS - 1].rstrip() + "…"


def compare(previous, latest):
    old = paragraphs(previous)
    new = paragraphs(latest)
    pairs = sorted(
        ((similarity(old_text, new_text), old_index, new_index)
         for old_index, old_text in enumerate(old)
         for new_index, new_text in enumerate(new)),
        reverse=True,
    )
    used_old, used_new, matched = set(), set(), []
    for score, old_index, new_index in pairs:
        if score < REWRITTEN:
            break
        if old_index in used_old or new_index in used_new:
            continue
        used_old.add(old_index)
        used_new.add(new_index)
        matched.append((score, old_index, new_index))
    unchanged = 0
    modified = []
    for score, old_index, new_index in matched:
        old_text, new_text = old[old_index], new[new_index]
        signal = language_signal(old_text, new_text)
        if score >= SAME and signal["code"] == "rewritten":
            unchanged += 1
            continue
        modified.append({
            "similarity": round(score, 3),
            "previous_excerpt": excerpt(old_text),
            "latest_excerpt": excerpt(new_text),
            "topics": topics_for(old_text, new_text),
            "language_signal": signal,
        })
    added = [{
        "excerpt": excerpt(text), "topics": topics_for(text),
        "language_signal": language_signal("", text),
    } for index, text in enumerate(new) if index not in used_new]
    removed = [{
        "excerpt": excerpt(text), "topics": topics_for(text),
        "language_signal": {"code": "removed", "label": "不再列出", "triggers": []},
    } for index, text in enumerate(old) if index not in used_old]
    return {
        "paragraphs_previous": len(old),
        "paragraphs_latest": len(new),
        "unchanged": unchanged,
        "modified_count": len(modified),
        "added_count": len(added),
        "removed_count": len(removed),
        "modified": modified[:8],
        "added": added[:8],
        "removed": removed[:8],
    }


def choose_pair(periods):
    for form in ("10-Q", "20-F", "10-K"):
        rows = [row for row in periods if row.get("form") == form]
        if len(rows) >= 2:
            rows.sort(key=lambda row: (row.get("filing_date", ""), row.get("accession", "")), reverse=True)
            return rows[1], rows[0]
    return None


def filing_meta(row):
    return {key: row.get(key) for key in (
        "accession", "form", "filing_date", "report_date", "url", "index_url"
    )}


def compare_company(ticker, node):
    pair = choose_pair(node.get("periods", []))
    if not pair:
        return {
            "status": "insufficient",
            "reason": "沒有兩份同類型的 10-Q、20-F 或 10-K 可比較。",
        }
    previous, latest = pair
    form = latest["form"]
    try:
        previous_text = clean_html_to_text(fetch_html(previous["url"]))
        time.sleep(0.13)
        latest_text = clean_html_to_text(fetch_html(latest["url"]))
    except (urllib.error.URLError, TimeoutError) as exc:
        return {
            "status": "fetch_error", "reason": f"SEC 原文讀取失敗：{type(exc).__name__}",
            "previous": filing_meta(previous), "latest": filing_meta(latest),
        }
    sections = {}
    for key, (label, start, end) in SECTION_SPECS[form].items():
        old_section = extract_section(previous_text, start, end)
        new_section = extract_section(latest_text, start, end)
        if not old_section or not new_section:
            sections[key] = {
                "status": "unavailable", "label": label,
                "reason": "至少一份文件未可靠辨識章節邊界，已保留缺值。",
            }
            continue
        sections[key] = {"status": "compared", "label": label, **compare(old_section, new_section)}
    return {
        "status": "compared" if any(row["status"] == "compared" for row in sections.values()) else "unavailable",
        "comparison_basis": "同公司、同表單類型的最近兩份週期申報",
        "caveat": "段落重組、表格排版或跨期數字更新可能被判為文字變化；可能升高／緩和只代表指定措辭新增，不代表風險事實已改變。",
        "previous": filing_meta(previous),
        "latest": filing_meta(latest),
        "sections": sections,
    }


def selected_accessions(details):
    result = {}
    for ticker, node in details.get("quarterly", {}).items():
        pair = choose_pair(node.get("periods", []))
        result[ticker] = [row.get("accession") for row in pair] if pair else []
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--details", type=Path, default=DETAILS_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    details = json.loads(args.details.read_text())
    selected = selected_accessions(details)
    previous_payload = json.loads(args.output.read_text()) if args.output.exists() else {}
    if (not args.force and not args.tickers
            and previous_payload.get("selected_accessions") == selected
            and set(previous_payload.get("companies", {})) == set(selected)):
        print("Periodic filing pairs unchanged; keeping existing text-change snapshot.")
        return 0
    tickers = args.tickers or sorted(details.get("quarterly", {}))
    companies = dict(previous_payload.get("companies", {})) if args.tickers else {}
    for ticker in tickers:
        companies[ticker] = compare_company(ticker, details.get("quarterly", {}).get(ticker, {}))
        print(f"{ticker:6s} {companies[ticker]['status']}", flush=True)
        time.sleep(0.13)
    payload = {
        "schema_version": 1,
        "generated_at": now_utc(),
        "source": "SEC EDGAR official filing HTML; paragraph-level comparison",
        "thresholds": {"same": SAME, "rewritten": REWRITTEN, "min_paragraph_chars": MIN_PARAGRAPH},
        "selected_accessions": selected,
        "companies": companies,
    }
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {args.output.relative_to(ROOT)} ({len(companies)} companies)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
