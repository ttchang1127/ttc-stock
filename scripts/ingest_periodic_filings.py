#!/usr/bin/env python3
"""Ingest tracked 10-Q, 8-K and 6-K filings into traceable Obsidian notes.

The importer is deliberately fail-closed.  A 10-Q is written only when Part I
Item 2 (MD&A), Part I Item 4 (Controls) and Part II Item 1A (Risk Factors) can
all be bounded by the filing's own headings.  An 8-K is written only when every
Item number reported by SEC can be located and separated.  A 6-K has no common
Item structure, so it receives a source note but no invented section split.

Raw HTML is cached under ``20_Filings/<ticker>/raw`` and remains gitignored.
The committed notes always link to SEC's official document and filing index.
"""

from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EVENTS = REPO_ROOT / "sec_filing_alerts.json"
DEFAULT_FINANCIALS = REPO_ROOT / "financials.json"
DEFAULT_STATUS = REPO_ROOT / "periodic_filing_ingest.json"
DEFAULT_NOTE = REPO_ROOT / "60_SEC_Filing_Radar" / "Periodic_Filing_Ingest.md"
TARGET_FORMS = {"10-Q", "10-Q/A", "8-K", "8-K/A", "6-K", "6-K/A"}
SCHEMA_VERSION = 2
PARSER_VERSION = 2


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def sec_headers() -> dict[str, str]:
    return {
        "User-Agent": os.environ.get("SEC_USER_AGENT", "SecKBResearch user@example.com"),
    }


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers=sec_headers())
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read()


def clean_html_to_text(source: str) -> str:
    text = re.sub(r"<style[^>]*>.*?</style>", "", source, flags=re.I | re.S)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.I | re.S)
    text = re.sub(
        r"</?(div|p|tr|h[1-6]|li|br|table|section|article)[^>]*>",
        "\n", text, flags=re.I,
    )
    text = re.sub(r"</?(td|th)[^>]*>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]", " ", text)
    text = text.replace("\u200b", "").replace("\ufeff", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def loose(value: str) -> str:
    """Match text whose letters may be separated by spaces in iXBRL output."""
    return "".join(
        r"[ \t]+" if char == " " else re.escape(char) + r"[ \t]*"
        for char in value
    )


def item_pattern(number: str) -> str:
    escaped = re.escape(number).replace(r"\.", r"[ \t]*\.[ \t]*")
    return r"item[ \t]*" + escaped + r"[\.\:\-–—]?[ \t]*[^\n]*"


def heading_positions(text: str, pattern: str) -> list[tuple[int, int]]:
    """Return line-start headings, excluding obvious table-of-contents rows."""
    found = []
    for match in re.finditer(pattern, text, re.I):
        if "\n" in match.group(0):
            continue
        if text.rfind("\n", 0, match.start()) + 1 != match.start():
            continue
        following_lines = [
            line.strip()
            for line in text[match.end():].splitlines()
            if line.strip()
        ][:2]
        # SEC iXBRL tables of contents commonly render an Item heading, its
        # title, then a page number on the next line.  Looking only at the
        # immediate next line caused those entries to be mistaken for the
        # actual body heading and could swallow most of a filing.
        if any(
            re.fullmatch(r"(?:[0-9]{1,4}\.?|[ivxlIVXL]{1,8}|[\-–—])", line)
            for line in following_lines
        ):
            continue
        found.append((match.start(), match.end()))
    return found


def first_heading(text: str, pattern: str, after: int = 0) -> tuple[int, int] | None:
    return next((row for row in heading_positions(text, pattern) if row[0] >= after), None)


def bounded_section(
    text: str,
    start_pattern: str,
    end_pattern: str | None,
    *,
    min_chars: int,
) -> str | None:
    for start, _ in heading_positions(text, start_pattern):
        if end_pattern is None:
            body = text[start:].strip()
        else:
            end = first_heading(text, end_pattern, start + 1)
            if not end:
                continue
            body = text[start:end[0]].strip()
        if len(body) >= min_chars:
            return body
    return None


def ten_q_part_ranges(text: str) -> tuple[str, str] | None:
    part_one_pattern = r"part[ \t]+i(?!i)[\.\:\-–—]?[ \t]*[^\n]*"
    part_two_pattern = r"part[ \t]+ii(?!i)[\.\:\-–—]?[ \t]*[^\n]*"
    part_twos = heading_positions(text, part_two_pattern)
    for part_one, _ in heading_positions(text, part_one_pattern):
        for part_two, _ in part_twos:
            if part_two <= part_one:
                continue
            first = text[part_one:part_two]
            second = text[part_two:]
            if len(first) < 5_000 or len(second) < 1_000:
                continue
            if not heading_positions(first, item_pattern("2")):
                continue
            if not heading_positions(first, item_pattern("4")):
                continue
            if not heading_positions(second, item_pattern("1A")):
                continue
            return first, second
    return None


def extract_10q_sections(text: str) -> tuple[dict[str, str], list[str]]:
    ranges = ten_q_part_ranges(text)
    if not ranges:
        return {}, ["無法可靠辨識 Part I／Part II 邊界"]
    part_one, part_two = ranges
    specs = [
        ("PartI_Item2_MD_and_A", "Part I Item 2. MD&A 管理層討論與分析",
         part_one, item_pattern("2"), item_pattern("3"), 1_500),
        ("PartI_Item4_Controls", "Part I Item 4. Controls and Procedures 控制與程序",
         part_one, item_pattern("4"), None, 250),
        ("PartII_Item1A_Risk_Factors", "Part II Item 1A. Risk Factors 風險因素",
         part_two, item_pattern("1A"), item_pattern("2"), 120),
    ]
    sections = {}
    errors = []
    for slug, title, region, start, end, minimum in specs:
        body = bounded_section(region, start, end, min_chars=minimum)
        if body is None:
            errors.append(f"{title} 找不到可靠邊界或內容過短")
        else:
            sections[slug] = body
    return sections, errors


def extract_8k_sections(text: str, item_numbers: list[str]) -> tuple[dict[str, str], list[str]]:
    normalized = []
    for item in item_numbers:
        value = str(item).strip().upper()
        if re.fullmatch(r"\d+\.\d{2}", value) and value not in normalized:
            normalized.append(value)
    if not normalized:
        return {}, ["SEC submissions 未提供可驗證的 8-K Item 編號"]

    starts = {}
    for number in normalized:
        matches = heading_positions(text, item_pattern(number))
        if not matches:
            return {}, [f"Item {number} 找不到行首標題"]
        starts[number] = matches

    # Select one monotonically increasing heading chain.  This rejects a table
    # of contents or cross-reference instead of silently slicing from it.
    chain = []
    cursor = 0
    for number in normalized:
        match = next((row for row in starts[number] if row[0] >= cursor), None)
        if not match:
            return {}, [f"Item {number} 無法與前一 Item 建立有效順序"]
        chain.append((number, match[0]))
        cursor = match[0] + 1

    signature = first_heading(text, r"signatures?[ \t]*[^\n]*", chain[-1][1] + 1)
    sections = {}
    errors = []
    for index, (number, start) in enumerate(chain):
        end = chain[index + 1][1] if index + 1 < len(chain) else (signature[0] if signature else len(text))
        body = text[start:end].strip()
        if len(body) < 60:
            errors.append(f"Item {number} 內容過短，拒絕寫入")
        else:
            sections[f"Item_{number.replace('.', '_')}"] = body
    return sections, errors


def safe_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")


def filing_stem(event: dict) -> str:
    ticker = safe_component(event["ticker"].upper())
    report_date = safe_component(event.get("report_date") or event["filing_date"])
    form = safe_component(event["form"].replace("-", ""))
    accession_suffix = safe_component(event["accession"].replace("-", "")[-6:])
    return f"{ticker}_{report_date}_{form}_{accession_suffix}"


def yaml_string(value) -> str:
    return json.dumps("" if value is None else str(value), ensure_ascii=False)


def company_names(financials_path: Path) -> dict[str, str]:
    companies = load_json(financials_path, {}).get("companies", {})
    return {
        ticker: row.get("entity_name") or ticker
        for ticker, row in companies.items()
    }


def section_title(form: str, slug: str) -> str:
    titles = {
        "PartI_Item2_MD_and_A": "Part I Item 2. MD&A 管理層討論與分析",
        "PartI_Item4_Controls": "Part I Item 4. Controls and Procedures 控制與程序",
        "PartII_Item1A_Risk_Factors": "Part II Item 1A. Risk Factors 風險因素",
    }
    if slug in titles:
        return titles[slug]
    number = slug.removeprefix("Item_").replace("_", ".")
    return f"Item {number} 原文"


def render_section_note(event: dict, company_name: str, stem: str, slug: str, body: str) -> str:
    title = section_title(event["form"], slug)
    return f'''---
ticker: {event["ticker"]}
form_type: {yaml_string(event["form"])}
report_date: {event.get("report_date") or event["filing_date"]}
filing_date: {event["filing_date"]}
accession_number: {yaml_string(event["accession"])}
section: {yaml_string(slug)}
source_url: {yaml_string(event["url"])}
characters: {len(body)}
tags:
  - sec/{event["form"].lower().replace("-", "")}_section
  - company/{event["ticker"].lower()}
---

# {company_name} ({event["ticker"]})｜{title}

- **所屬申報**：[[{stem}|{event["ticker"]} {event["report_date"]} {event["form"]}]]
- **SEC accession**：`{event["accession"]}`
- **官方原文**：[SEC 原始文件]({event["url"]})
- **抽取原則**：只在表單內可驗證的 Item 邊界成立時寫入；本頁未經摘要或改寫。

---

## 📄 章節原文

{body}
'''


def render_main_note(event: dict, company_name: str, stem: str, sections: dict[str, str]) -> str:
    section_links = "\n".join(
        f"- [[sections/{stem}_{slug}|{section_title(event['form'], slug)}]]"
        for slug in sections
    ) or "- 本表單沒有統一可驗證的 Item 拆分；不產生猜測章節。"
    raw_name = f"{stem}_raw.html"
    report_kind = {
        "10-Q": "季度報告", "10-Q/A": "季度報告修正版",
        "8-K": "重大事件即時申報", "8-K/A": "重大事件即時申報修正版",
        "6-K": "外國私人發行人重大資訊", "6-K/A": "外國私人發行人重大資訊修正版",
    }.get(event["form"], "SEC 申報")
    return f'''---
ticker: {event["ticker"]}
company_name: {yaml_string(company_name)}
cik: {yaml_string(event.get("cik"))}
form_type: {yaml_string(event["form"])}
filing_date: {event["filing_date"]}
report_date: {event.get("report_date") or event["filing_date"]}
accepted_at: {yaml_string(event.get("accepted_at"))}
accession_number: {yaml_string(event["accession"])}
sec_url: {yaml_string(event["url"])}
sec_index_url: {yaml_string(event.get("index_url"))}
raw_file: {yaml_string("raw/" + raw_name)}
ingest_mode: fail_closed
ingest_parser_version: {PARSER_VERSION}
tags:
  - sec/{event["form"].lower().replace("-", "")}
  - company/{event["ticker"].lower()}
  - periodic_filing
---

# {company_name} ({event["ticker"]})｜{event["report_date"]} {event["form"]}

## 📌 申報基本資訊

- **表單／性質**：{event["form"]}（{report_kind}）
- **報告期末／事件日**：`{event.get("report_date") or event["filing_date"]}`
- **SEC 申報日**：`{event["filing_date"]}`
- **SEC accession**：`{event["accession"]}`
- **SEC Item**：{event.get("items_summary") or "未提供 Item 分類"}
- **官方完整原文**：[主要文件]({event["url"]})｜[申報索引頁]({event.get("index_url") or event["url"]})
- **本機原始 HTML 快取**：`raw/{raw_name}`（不進 Git；可由本腳本依 accession 重建）

## 📚 已驗證章節

{section_links}

## 🧭 閱讀說明

本筆記只整理來源、日期、表單與可驗證的原文章節，不將 SEC 文件重要性直接解讀為利多或利空。若章節邊界不能可靠辨識，入庫器會停止該份 filing 並列入人工覆核，不會輸出猜測內容。

## 🔗 關聯筆記

- [[{event["ticker"]}_Company_Profile|{event["ticker"]} 公司主頁]]
'''


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temp_name = handle.name
    os.replace(temp_name, path)


def selected_events(events_path: Path) -> list[dict]:
    rows = load_json(events_path, {}).get("events", [])
    by_accession = {}
    for row in rows:
        if row.get("form") in TARGET_FORMS and row.get("accession") and row.get("url"):
            by_accession[row["accession"]] = row
    return sorted(
        by_accession.values(),
        key=lambda row: (row.get("filing_date", ""), row.get("accepted_at", ""), row["accession"]),
    )


def expected_section_slugs(event: dict) -> set[str] | None:
    if event["form"].startswith("10-Q"):
        return {
            "PartI_Item2_MD_and_A", "PartI_Item4_Controls",
            "PartII_Item1A_Risk_Factors",
        }
    if event["form"].startswith("8-K"):
        numbers = {
            str(item).strip() for item in event.get("items", [])
            if re.fullmatch(r"\d+\.\d{2}", str(item).strip())
        }
        if not numbers:
            return None
        return {f"Item_{number.replace('.', '_')}" for number in numbers}
    return set()


def active_section_paths(filing_dir: Path, stem: str) -> list[Path]:
    return sorted((filing_dir / "sections").glob(f"{stem}_*.md"))


def remove_active_notes(root: Path, filing_dir: Path, main_path: Path, stem: str) -> list[str]:
    """Remove only accession-scoped generated notes after a failed reparse."""
    removed = []
    for path in [main_path, *active_section_paths(filing_dir, stem)]:
        if path.is_file():
            path.unlink()
            removed.append(str(path.relative_to(root)))
    return removed


def existing_ingest_is_complete(event: dict, main_path: Path, section_paths: list[Path]) -> bool:
    if not main_path.is_file():
        return False
    note = main_path.read_text()
    required_markers = (
        f'accession_number: "{event["accession"]}"',
        f'sec_url: "{event["url"]}"',
        f"ingest_parser_version: {PARSER_VERSION}",
    )
    if any(marker not in note for marker in required_markers):
        return False
    expected = expected_section_slugs(event)
    if expected is None:
        return False
    actual = {path.stem.removeprefix(main_path.stem + "_") for path in section_paths}
    if actual != expected:
        return False
    return all(event["accession"] in path.read_text() for path in section_paths)


def ingest_event(event: dict, company_name: str, root: Path) -> dict:
    stem = filing_stem(event)
    filing_dir = root / "20_Filings" / event["ticker"]
    raw_path = filing_dir / "raw" / f"{stem}_raw.html"
    main_path = filing_dir / f"{stem}.md"
    expected_note = str(main_path.relative_to(root))
    existing_section_paths = active_section_paths(filing_dir, stem)
    if existing_ingest_is_complete(event, main_path, existing_section_paths):
        existing_sections = [str(path.relative_to(root)) for path in existing_section_paths]
        return {
            "ticker": event["ticker"], "form": event["form"], "accession": event["accession"],
            "filing_date": event["filing_date"], "report_date": event.get("report_date"),
            "status": "already_ingested", "note": expected_note, "expected_note": expected_note,
            "sections": existing_sections,
            "source_url": event["url"], "errors": [], "removed_stale_notes": [],
        }

    try:
        payload = download(event["url"])
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        removed = remove_active_notes(root, filing_dir, main_path, stem)
        return {
            "ticker": event["ticker"], "form": event["form"], "accession": event["accession"],
            "filing_date": event["filing_date"], "report_date": event.get("report_date"),
            "status": "download_failed", "note": None, "expected_note": expected_note,
            "sections": [], "source_url": event["url"],
            "errors": [f"{type(exc).__name__}: {exc}"], "removed_stale_notes": removed,
        }
    source = payload.decode("utf-8", errors="ignore")
    text = clean_html_to_text(source)
    if len(text) < 300:
        errors = [f"清理後原文僅 {len(text)} 字元，拒絕入庫"]
        sections = {}
    elif event["form"].startswith("10-Q"):
        sections, errors = extract_10q_sections(text)
    elif event["form"].startswith("8-K"):
        sections, errors = extract_8k_sections(text, event.get("items") or [])
    else:
        sections, errors = {}, []

    if errors:
        removed = remove_active_notes(root, filing_dir, main_path, stem)
        return {
            "ticker": event["ticker"], "form": event["form"], "accession": event["accession"],
            "filing_date": event["filing_date"], "report_date": event.get("report_date"),
            "status": "review_required", "note": None, "expected_note": expected_note,
            "sections": [], "source_url": event["url"],
            "errors": errors, "removed_stale_notes": removed,
        }

    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(payload)
    rendered_sections = {}
    for slug, body in sections.items():
        path = filing_dir / "sections" / f"{stem}_{slug}.md"
        rendered_sections[path] = render_section_note(event, company_name, stem, slug, body)
    # Write section files first and the accession-indexing main note last.  The
    # main note therefore serves as the idempotency marker for a complete set.
    for path, content in rendered_sections.items():
        atomic_write(path, content)
    removed = []
    for path in active_section_paths(filing_dir, stem):
        if path not in rendered_sections:
            path.unlink()
            removed.append(str(path.relative_to(root)))
    atomic_write(main_path, render_main_note(event, company_name, stem, sections))
    return {
        "ticker": event["ticker"], "form": event["form"], "accession": event["accession"],
        "filing_date": event["filing_date"], "report_date": event.get("report_date"),
        "status": "ingested", "note": expected_note, "expected_note": expected_note,
        "sections": [str(path.relative_to(root)) for path in rendered_sections],
        "source_url": event["url"], "errors": [], "removed_stale_notes": removed,
        "source_sha256": hashlib.sha256(payload).hexdigest(),
    }


def render_status_note(status: dict) -> str:
    rows = status.get("filings", [])
    pending = [row for row in rows if row["status"] in {"review_required", "download_failed"}]
    completed = [row for row in rows if row["status"] in {"ingested", "already_ingested"}]
    lines = [
        "---", "title: 10-Q／8-K／6-K 自動入庫狀態", f"updated_at: {status['updated_at']}",
        "tags:", "  - sec/periodic-ingest", "---", "", "# 📥 10-Q／8-K／6-K 自動入庫狀態", "",
        "本頁記錄完整主筆記與安全章節拆分結果。10-Q／8-K 任一必要邊界失敗時，該 filing 不寫入 Markdown；6-K 因沒有統一 Item 架構，只建立可追溯主筆記。", "",
        f"- 已完成／既有：**{len(completed)}** 份", f"- 待人工覆核／下載失敗：**{len(pending)}** 份", "",
    ]
    if pending:
        lines += ["## ⚠️ 待人工覆核", ""]
        for row in pending:
            removed = row.get("removed_stale_notes") or []
            cleanup = f"；已移除舊版輸出 {len(removed)} 份" if removed else ""
            lines.append(
                f"- **{row['ticker']}｜{row['form']}｜{row['filing_date']}**｜`{row['accession']}`｜"
                f"{'；'.join(row['errors'])}{cleanup}｜[SEC 原文]({row['source_url']})"
            )
        lines.append("")
    lines += ["## ✅ 已建立的筆記", ""]
    if completed:
        for row in sorted(completed, key=lambda item: (item["filing_date"], item["accession"]), reverse=True):
            link = row.get("note") or ""
            lines.append(
                f"- **{row['ticker']}｜{row['form']}｜{row['filing_date']}**｜`{row['accession']}`｜"
                f"[[{link.removesuffix('.md')}|主筆記]]｜章節 {len(row.get('sections') or [])} 篇"
            )
    else:
        lines.append("- 尚未建立筆記。")
    lines += ["", "## 判讀規則", "", "- `ingested`：本次完成且所有必要邊界通過。", "- `already_ingested`：相同 accession 的完整主筆記已存在。", "- `review_required`：邊界不可靠；未寫入該 filing 的 Markdown。", "- `download_failed`：SEC 原文暫時無法取得；下次重試。", ""]
    return "\n".join(lines)


def write_summary(path: Path | None, status: dict, heading: str = "10-Q／8-K／6-K 自動入庫") -> None:
    if not path:
        return
    pending = [row for row in status["filings"] if row["status"] in {"review_required", "download_failed"}]
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n## {heading}\n\n")
        handle.write(f"處理 {len(status['filings'])} 份；待人工覆核／下載失敗 {len(pending)} 份。\n")
        for row in pending:
            removed = row.get("removed_stale_notes") or []
            cleanup = f"；已移除舊版輸出 {len(removed)} 份" if removed else ""
            handle.write(
                f"- {row['ticker']} {row['form']} `{row['accession']}`："
                f"{'；'.join(row['errors'])}{cleanup}\n"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--financials", type=Path, default=DEFAULT_FINANCIALS)
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--note", type=Path, default=DEFAULT_NOTE)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--alert-markdown", type=Path)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args()

    events = selected_events(args.events)
    names = company_names(args.financials)
    results = []
    for event in events:
        result = ingest_event(event, names.get(event["ticker"], event["ticker"]), args.root)
        results.append(result)
        icon = "✅" if result["status"] in {"ingested", "already_ingested"} else "⚠️"
        print(f"  {icon} {event['ticker']:6s} {event['form']:6s} {event['accession']} {result['status']}")

    status = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": now_utc(),
        "source": "SEC filing alerts + official primary filing documents",
        "methodology": "fail-closed heading boundaries; accession-deduplicated",
        "filings": results,
    }
    atomic_write(args.status, json.dumps(status, indent=2, ensure_ascii=False) + "\n")
    atomic_write(args.note, render_status_note(status))
    write_summary(args.summary, status)
    pending = [row for row in results if row["status"] in {"review_required", "download_failed"}]
    write_summary(args.alert_markdown, status, "SEC 定期申報入庫覆核")
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as handle:
            handle.write(f"pending_count={len(pending)}\n")
            handle.write(f"processed_count={len(results)}\n")
    print(f"已處理 {len(results)} 份；待人工覆核／下載失敗 {len(pending)} 份")
    return 2 if pending else 0


if __name__ == "__main__":
    raise SystemExit(main())
