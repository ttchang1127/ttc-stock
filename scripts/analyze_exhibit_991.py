#!/usr/bin/env python3
"""Build source-traceable earnings cards from SEC 8-K Exhibit 99.1 files.

Eligibility is deliberately narrow: the filing must be an 8-K/8-K/A whose SEC
submissions metadata reports Item 2.02, and its official filing index must list
exactly one document with type EX-99.1.  Evidence is copied verbatim into seven
reading categories; missing categories stay missing and no value is inferred.
"""

from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EVENTS = REPO_ROOT / "sec_filing_alerts.json"
DEFAULT_FINANCIALS = REPO_ROOT / "financials.json"
DEFAULT_OUTPUT = REPO_ROOT / "exhibit_991_analysis.json"
DEFAULT_RADAR = REPO_ROOT / "60_SEC_Filing_Radar" / "Exhibit_991_Earnings_Radar.md"
SCHEMA_VERSION = 1
PARSER_VERSION = 1
MAX_EVIDENCE = 2

CATEGORIES = {
    "revenue": {
        "label": "營收",
        "meaning": "本期營運規模及其年增／季增線索；需連同期間與單位閱讀。",
        "patterns": (r"\bnet sales\b", r"\brevenues?\b"),
        "exclude_patterns": (r"\bdeferred revenue\b",),
        "boost_patterns": (r"\brecord\b", r"\byear over year\b", r"\bY/Y\b", r"\bgrowth\b"),
        "numeric": True,
    },
    "gross_margin": {
        "label": "毛利率",
        "meaning": "產品組合、定價與成本效率；GAAP 與 non-GAAP 不可混用。",
        "patterns": (r"\bgross margins?\b",),
        "numeric": True,
    },
    "eps": {
        "label": "每股盈餘（EPS）",
        "meaning": "每股獲利；需分清 basic／diluted、GAAP／non-GAAP。",
        "patterns": (
            r"\bearnings per share\b", r"\bEPS\b",
            r"\bnet income \(loss\) per share\b",
        ),
        "numeric": True,
    },
    "segments": {
        "label": "分部／市場營收",
        "meaning": "辨識成長由哪些事業、產品或終端市場驅動。",
        "patterns": (
            r"\bsegment\b", r"\bbusiness unit\b", r"\bend markets?\b",
            r"\brevenue by\b", r"\bmarket revenue\b",
        ),
        "required_patterns": (r"\brevenues?\b", r"\bnet sales\b"),
        "exclude_patterns": (r"\bforward-looking statements?\b",),
        "max_chars": 600,
        "numeric": True,
    },
    "guidance": {
        "label": "下一季／全年指引",
        "meaning": "管理層對未來期間的官方展望，不等於保證或分析師共識。",
        "patterns": (
            r"\bguidance\b", r"\boutlook\b", r"\bexpect(?:s|ed)?\b",
            r"\bforecast\b", r"\banticipated\b",
        ),
        "exclude_patterns": (r"\bquantitative reconciliation\b",),
        "boost_patterns": (r"\bexpected to be between\b", r"\brevenue target\b", r"\braises?\b"),
        "max_chars": 700,
        "numeric": True,
    },
    "management": {
        "label": "管理層關鍵語句",
        "meaning": "管理層對驅動因素與策略的原話；屬公司陳述，不是獨立驗證。",
        "patterns": (
            r"\bchief executive officer\b", r"\bchief financial officer\b",
            r"\bCEO\b", r"\bCFO\b", r"\bsaid\b", r"\bcommented\b",
        ),
        "numeric": False,
    },
    "risks": {
        "label": "風險／前瞻聲明限制",
        "meaning": "附件明確提到的風險、逆風或前瞻聲明限制；安全港文字是警語，不代表風險已發生。",
        "patterns": (
            r"\brisks?\b", r"\bheadwinds?\b", r"\buncertain(?:ty|ties)?\b",
            r"\bpressure\b", r"\btariffs?\b",
            r"\bconstraints?\b",
        ),
        "max_chars": 1200,
        "numeric": False,
    },
}


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def sec_headers() -> dict[str, str]:
    return {"User-Agent": os.environ.get("SEC_USER_AGENT", "SecKBResearch user@example.com")}


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers=sec_headers())
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read()


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temp_name = handle.name
    os.replace(temp_name, path)


def normalize_text(value: str) -> str:
    value = html_lib.unescape(value)
    value = re.sub(r"[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


class FilingIndexParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_cell = False
        self.current_cell: list[str] = []
        self.current_href: str | None = None
        self.current_row: list[dict] = []
        self.rows: list[list[dict]] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"td", "th"}:
            self.in_cell = True
            self.current_cell = []
            self.current_href = None
        elif tag.lower() == "a" and self.in_cell:
            self.current_href = dict(attrs).get("href")

    def handle_data(self, data):
        if self.in_cell:
            self.current_cell.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"td", "th"} and self.in_cell:
            self.current_row.append({
                "text": normalize_text("".join(self.current_cell)),
                "href": self.current_href,
            })
            self.in_cell = False
        elif tag == "tr":
            if self.current_row:
                self.rows.append(self.current_row)
            self.current_row = []


def official_exhibit_991(index_html: str, index_url: str) -> dict | None:
    parser = FilingIndexParser()
    parser.feed(index_html)
    matches = []
    for row in parser.rows:
        values = [cell["text"].upper() for cell in row]
        if "EX-99.1" not in values:
            continue
        link_cell = next((cell for cell in row if cell.get("href")), None)
        if not link_cell:
            continue
        url = urllib.parse.urljoin(index_url, link_cell["href"])
        parsed = urllib.parse.urlparse(url)
        index_path = urllib.parse.urlparse(index_url).path
        accession_dir = index_path.rsplit("/", 1)[0] + "/"
        if parsed.scheme != "https" or parsed.netloc.lower() != "www.sec.gov":
            continue
        if not parsed.path.startswith(accession_dir):
            continue
        matches.append({
            "url": url,
            "document": link_cell["text"],
            "description": row[1]["text"] if len(row) > 1 else "EX-99.1",
            "type": "EX-99.1",
        })
    unique = {row["url"]: row for row in matches}
    return next(iter(unique.values())) if len(unique) == 1 else None


class EvidenceParser(HTMLParser):
    BLOCKS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self):
        super().__init__()
        self.block_tag: str | None = None
        self.block_data: list[str] = []
        self.in_cell = False
        self.cell_data: list[str] = []
        self.row: list[str] = []
        self.blocks: list[dict] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self.BLOCKS and self.block_tag is None:
            self.block_tag = tag
            self.block_data = []
        elif tag in {"td", "th"}:
            self.in_cell = True
            self.cell_data = []
        elif tag == "br":
            if self.in_cell:
                self.cell_data.append(" ")
            elif self.block_tag:
                self.block_data.append(" ")

    def handle_data(self, data):
        if self.in_cell:
            self.cell_data.append(data)
        elif self.block_tag:
            self.block_data.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"td", "th"} and self.in_cell:
            self.row.append(normalize_text("".join(self.cell_data)))
            self.in_cell = False
        elif tag == "tr":
            text = " | ".join(cell for cell in self.row if cell)
            if text:
                self.blocks.append({"kind": "table_row", "text": text})
            self.row = []
        elif tag == self.block_tag:
            text = normalize_text("".join(self.block_data))
            if text:
                self.blocks.append({"kind": self.block_tag, "text": text})
            self.block_tag = None
            self.block_data = []


def evidence_blocks(source_html: str) -> list[dict]:
    parser = EvidenceParser()
    parser.feed(source_html)
    seen = set()
    output = []
    for block in parser.blocks:
        text = block["text"]
        key = text.casefold()
        if len(text) < 20 or key in seen:
            continue
        seen.add(key)
        output.append(block)
    return output


def has_number(text: str) -> bool:
    return bool(re.search(r"(?:\$|€|£)?\(?\d[\d,.]*\)?(?:\s*(?:%|bps|million|billion|thousand))?", text, re.I))


def extract_category_evidence(blocks: list[dict], config: dict) -> list[dict]:
    patterns = [re.compile(pattern, re.I) for pattern in config["patterns"]]
    required = [re.compile(pattern, re.I) for pattern in config.get("required_patterns", ())]
    excluded = [re.compile(pattern, re.I) for pattern in config.get("exclude_patterns", ())]
    boosts = [re.compile(pattern, re.I) for pattern in config.get("boost_patterns", ())]
    candidates = []
    for position, block in enumerate(blocks):
        text = block["text"]
        if not any(pattern.search(text) for pattern in patterns):
            continue
        if required and not any(pattern.search(text) for pattern in required):
            continue
        if any(pattern.search(text) for pattern in excluded):
            continue
        if len(text) > config.get("max_chars", 10_000):
            continue
        if config["numeric"] and not has_number(text):
            continue
        score = 0
        score += 4 if block["kind"] in {"li", "h1", "h2", "h3"} else 0
        score += 3 if has_number(text) else 0
        score += 2 if len(text) <= 420 else 0
        score += 1 if block["kind"] == "table_row" else 0
        score += 5 * sum(bool(pattern.search(text)) for pattern in boosts)
        candidates.append((score, -position, block))
    candidates.sort(reverse=True, key=lambda row: (row[0], row[1]))
    return [dict(row[2], excerpt=row[2]["text"][:900].rstrip()) for row in candidates[:MAX_EVIDENCE]]


def eligible_events(events_path: Path) -> list[dict]:
    rows = load_json(events_path, {}).get("events", [])
    unique = {}
    for row in rows:
        items = {str(item).strip() for item in row.get("items", [])}
        if row.get("form") in {"8-K", "8-K/A"} and "2.02" in items and row.get("index_url"):
            unique[row["accession"]] = row
    return sorted(unique.values(), key=lambda row: (row["filing_date"], row["accession"]))


def safe_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")


def card_path(root: Path, event: dict) -> Path:
    suffix = event["accession"].replace("-", "")[-6:]
    stem = f"{event['ticker']}_{event.get('report_date') or event['filing_date']}_8K_{suffix}"
    return root / "20_Filings" / event["ticker"] / "analysis" / f"{safe_component(stem)}_Exhibit_99_1.md"


def render_card(row: dict, company_name: str) -> str:
    sections = []
    for key, config in CATEGORIES.items():
        evidence = row["categories"][key]
        sections += [f"## {config['label']}", "", f"> **怎麼讀**：{config['meaning']}", ""]
        if evidence:
            for item in evidence:
                sections += [f"> {item['excerpt']}", ""]
        else:
            sections += ["- **本附件未可靠辨識此項；保留缺值，不以其他來源或推估補齊。**", ""]
    coverage = row["coverage"]
    return f'''---
ticker: {row["ticker"]}
form_type: {row["form"]}
filing_date: {row["filing_date"]}
report_date: {row.get("report_date") or row["filing_date"]}
accession_number: "{row["accession"]}"
exhibit_type: EX-99.1
source_url: "{row["exhibit_url"]}"
parser_version: {PARSER_VERSION}
coverage: {coverage["found"]}/{coverage["total"]}
tags:
  - sec/exhibit991
  - company/{row["ticker"].lower()}
  - earnings-card
---

# {company_name} ({row["ticker"]})｜Exhibit 99.1 財報分析卡

## 來源與使用限制

- **SEC 申報**：{row["form"]}｜`{row["filing_date"]}`｜`{row["accession"]}`
- **官方來源**：[Exhibit 99.1]({row["exhibit_url"]})｜[申報索引]({row["index_url"]})
- **證據覆蓋**：**{coverage["found"]}/{coverage["total"]} 類**；這是閱讀索引，不是評分。
- **判讀限制**：以下保留附件原文，不自行換算幣別、不把 non-GAAP 當 GAAP、不把公司指引當保證；未辨識項目保留缺值，也不因關鍵字未命中就宣稱該項不存在。

{chr(10).join(sections)}
## 客觀閱讀結論

本卡只回答「公司在官方附件中說了什麼、證據在哪裡」。投資判斷仍需把本卡與 10-Q、八季財務趨勢、稀釋雷達及風險因素交叉閱讀。
'''


def analyze_event(event: dict, company_name: str, root: Path) -> dict:
    path = card_path(root, event)
    base = {
        "ticker": event["ticker"], "form": event["form"],
        "filing_date": event["filing_date"], "report_date": event.get("report_date"),
        "accession": event["accession"], "index_url": event["index_url"],
        "expected_card": str(path.relative_to(root)),
    }
    def failure(status: str, errors: list[str], exhibit_url: str | None = None) -> dict:
        removed = []
        if path.is_file():
            path.unlink()
            removed.append(str(path.relative_to(root)))
        row = {**base, "status": status, "errors": errors, "removed_stale_cards": removed}
        if exhibit_url:
            row["exhibit_url"] = exhibit_url
        return row

    try:
        index_payload = download(event["index_url"])
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return failure("download_failed", [f"index: {type(exc).__name__}: {exc}"])
    exhibit = official_exhibit_991(index_payload.decode("utf-8", errors="ignore"), event["index_url"])
    if not exhibit:
        return failure("review_required", ["官方 filing index 未找到唯一的 EX-99.1"])
    try:
        payload = download(exhibit["url"])
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return failure(
            "download_failed", [f"exhibit: {type(exc).__name__}: {exc}"], exhibit["url"]
        )
    source = payload.decode("utf-8", errors="ignore")
    blocks = evidence_blocks(source)
    if len(blocks) < 5:
        return failure(
            "review_required",
            [f"附件只辨識到 {len(blocks)} 個文字區塊，拒絕產生分析卡"],
            exhibit["url"],
        )
    categories = {key: extract_category_evidence(blocks, config) for key, config in CATEGORIES.items()}
    found = sum(bool(value) for value in categories.values())
    row = {
        **base, "status": "analyzed", "exhibit_url": exhibit["url"],
        "exhibit_document": exhibit["document"], "categories": categories,
        "coverage": {"found": found, "total": len(CATEGORIES)},
        "source_sha256": hashlib.sha256(payload).hexdigest(), "errors": [],
        "removed_stale_cards": [],
    }
    atomic_write(path, render_card(row, company_name))
    row["card"] = str(path.relative_to(root))
    return row


def company_names(path: Path) -> dict[str, str]:
    companies = load_json(path, {}).get("companies", {})
    return {ticker: row.get("entity_name") or ticker for ticker, row in companies.items()}


def render_radar(status: dict) -> str:
    rows = status["filings"]
    completed = [row for row in rows if row["status"] == "analyzed"]
    pending = [row for row in rows if row["status"] != "analyzed"]
    lines = [
        "---", "title: Exhibit 99.1 財報分析卡雷達", f"updated_at: {status['updated_at']}",
        "tags:", "  - sec/exhibit991", "---", "", "# 📊 Exhibit 99.1 財報分析卡雷達", "",
        "僅處理 SEC metadata 同時具備 **8-K／8-K/A、Item 2.02、唯一 EX-99.1** 的申報。數字與語句保留附件原文；未辨識欄位維持缺值。", "",
        f"- 已建立：**{len(completed)}** 份", f"- 待覆核／下載失敗：**{len(pending)}** 份", "",
        "## 已建立分析卡", "",
    ]
    for row in sorted(completed, key=lambda item: (item["filing_date"], item["accession"]), reverse=True):
        lines.append(
            f"- **{row['ticker']}｜{row['filing_date']}**｜證據 {row['coverage']['found']}/{row['coverage']['total']} 類｜"
            f"[[{row['card'].removesuffix('.md')}|分析卡]]｜[EX-99.1]({row['exhibit_url']})"
        )
    if not completed:
        lines.append("- 尚無符合條件的附件。")
    if pending:
        lines += ["", "## 待人工覆核", ""]
        for row in pending:
            lines.append(
                f"- **{row['ticker']}｜{row['filing_date']}**｜`{row['accession']}`｜"
                f"{'；'.join(row['errors'])}｜[申報索引]({row['index_url']})"
            )
    lines += ["", "## 七類證據代表什麼", ""]
    for config in CATEGORIES.values():
        lines.append(f"- **{config['label']}**：{config['meaning']}")
    lines.append("")
    return "\n".join(lines)


def write_summary(path: Path | None, status: dict) -> None:
    if not path:
        return
    pending = [row for row in status["filings"] if row["status"] != "analyzed"]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n## Exhibit 99.1 財報分析卡\n\n")
        handle.write(f"符合條件 {len(status['filings'])} 份；待覆核／下載失敗 {len(pending)} 份。\n")
        for row in pending:
            handle.write(
                f"- {row['ticker']} `{row['accession']}`：{'；'.join(row['errors'])}｜"
                f"[SEC 申報索引]({row['index_url']})\n"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--financials", type=Path, default=DEFAULT_FINANCIALS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--radar", type=Path, default=DEFAULT_RADAR)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--alert-markdown", type=Path)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args()

    names = company_names(args.financials)
    results = []
    for event in eligible_events(args.events):
        row = analyze_event(event, names.get(event["ticker"], event["ticker"]), args.root)
        results.append(row)
        print(f"  {'✅' if row['status'] == 'analyzed' else '⚠️'} {event['ticker']:6s} {event['accession']} {row['status']}")
    status = {
        "schema_version": SCHEMA_VERSION, "parser_version": PARSER_VERSION,
        "updated_at": now_utc(), "source": "SEC filing index + official EX-99.1",
        "methodology": "8-K Item 2.02 only; exact EX-99.1; verbatim evidence; no inferred values",
        "categories": {key: {"label": row["label"], "meaning": row["meaning"]} for key, row in CATEGORIES.items()},
        "filings": results,
    }
    atomic_write(args.output, json.dumps(status, indent=2, ensure_ascii=False) + "\n")
    atomic_write(args.radar, render_radar(status))
    write_summary(args.summary, status)
    write_summary(args.alert_markdown, status)
    pending = [row for row in results if row["status"] != "analyzed"]
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as handle:
            handle.write(f"exhibit_991_pending_count={len(pending)}\n")
            handle.write(f"exhibit_991_analyzed_count={len(results) - len(pending)}\n")
    print(f"符合條件 {len(results)} 份；已分析 {len(results) - len(pending)}；待覆核 {len(pending)}")
    return 2 if pending else 0


if __name__ == "__main__":
    raise SystemExit(main())
