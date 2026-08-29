#!/usr/bin/env python3
"""Build a fail-closed official earnings-call and prepared-remarks radar.

Only text hosted by a company IR site, or linked by that site and explicitly
allow-listed in earnings_call_sources.json, is analyzed.  Audio is never
machine-transcribed here.  Short verbatim excerpts are classified as a reading
index; missing categories stay missing and no sentiment or investment rating is
inferred.
"""

from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import io
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

from pypdf import PdfReader

try:
    from curl_cffi import requests as curl_requests
except ImportError:  # Unit tests and non-network readers do not require it.
    curl_requests = None

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "earnings_call_sources.json"
DEFAULT_OUTPUT = REPO_ROOT / "earnings_call_analysis.json"
DEFAULT_EXHIBIT = REPO_ROOT / "exhibit_991_analysis.json"
DEFAULT_QUARTERLY = REPO_ROOT / "quarterly_financials.json"
DEFAULT_RADAR = REPO_ROOT / "60_SEC_Filing_Radar" / "Earnings_Call_Radar.md"
SCHEMA_VERSION = 2
PARSER_VERSION = 14
MAX_EVIDENCE = 1
MAX_EXCERPT_WORDS = 22
ANALYZABLE_STATUSES = {"analyzed", "analyzed_cached"}

SOURCE_TYPES = {
    "full_transcript": {
        "label": "完整官方逐字稿",
        "meaning": "包含管理層發言與分析師問答，可分開閱讀兩種證據。",
    },
    "prepared_remarks": {
        "label": "官方 Prepared Remarks",
        "meaning": "只包含管理層事先講稿，不含即席追問，不能代替完整電話會議。",
    },
    "webcast_replay": {
        "label": "僅官方影音／回放",
        "meaning": "可聆聽原始會議，但沒有可驗證的官方文字，因此不產生關鍵字摘錄。",
    },
}

CATEGORIES = {
    "demand_growth": {
        "label": "需求與成長驅動",
        "meaning": "管理層談到的需求、採用、訂單、backlog 或成長來源；屬公司陳述。",
        "patterns": (
            r"\bdemand\b", r"\bgrowth\b", r"\badoption\b", r"\bbacklog\b",
            r"\b(?:commercial|total|cloud|company|our) bookings\b|\bbookings (?:grew|growth|increased|declined|were|of)\b",
            r"\bpipeline\b",
        ),
        "weights": (3, 1, 3, 4, 4, 3),
        "section": "prepared",
    },
    "margin_cost": {
        "label": "利潤率與成本壓力",
        "meaning": "毛利率、營業利益率、成本、費用或折舊的方向與原因。",
        "patterns": (r"\bgross margins?\b", r"\boperating margins?\b", r"\bcosts?\b", r"\bexpenses?\b", r"\bdepreciation\b"),
        "weights": (4, 4, 1, 1, 2),
        "section": "prepared",
    },
    "capital_supply": {
        "label": "資本支出、產能與供應",
        "meaning": "CapEx、資料中心、產能、供給限制與擴產線索。",
        "patterns": (
            r"\bcapex\b", r"\bcapital expenditures?\b", r"\bcapacity\b", r"\bsupply\b",
            r"\b(?:build|expand|invest|spend|construct)\w*\b.{0,80}\bdata centers?\b",
            r"\bdata centers?\b.{0,80}\b(?:capacity|investment|infrastructure|construction|spend)\b",
        ),
        "weights": (4, 4, 2, 2, 3, 3),
        "section": "prepared",
    },
    "guidance": {
        "label": "指引與未來展望",
        "meaning": "管理層對下一季或全年展望；是前瞻聲明，不是保證。",
        "patterns": (
            r"\bguidance\b", r"\b(?:our|financial|business|revenue|margin|supply) outlook\b",
            r"\bwe expect\b", r"\bforecast\b", r"\banticipated\b",
        ),
        "weights": (4, 4, 1, 3, 2),
        "exclude_patterns": (
            r"\bbefore I move to outlook\b", r"\bin line with guidance\b",
            r"\b(?:end|conclude) with (?:some )?commentary on (?:our )?outlook\b",
            r"\bturning to (?:our )?outlook\b",
            r"\b(?:versus|better than|compared (?:with|to))\b.{0,80}\bguidance\b",
        ),
        "section": "prepared",
    },
    "confidence": {
        "label": "管理層信心與限定語",
        "meaning": "信心、可見度或保留語氣的原話；不能單獨當作業績證明。",
        "patterns": (r"\bconfiden(?:t|ce)\b", r"\bvisibility\b", r"\bencouraged\b", r"\bconviction\b", r"\buncertain\b"),
        "weights": (2, 3, 2, 3, 2),
        "exclude_patterns": (r"\blenders?\b.{0,100}\bconfidence\b",),
        "section": "prepared",
    },
    "risks": {
        "label": "逆風與風險",
        "meaning": "管理層明確提到的逆風、壓力、限制或不確定性；不代表風險一定發生。",
        "patterns": (r"\bheadwinds?\b", r"\brisks?\b", r"\bpressure\b", r"\bconstraints?\b", r"\btariffs?\b", r"\bsoftness\b"),
        "weights": (4, 1, 3, 3, 4, 4),
        "exclude_patterns": (
            r"\bforward-looking statements?\b", r"\bactual results (?:may |could |to )?differ\b",
            r"\bsubject to (?:a number of )?(?:significant )?risks? and uncertainties\b",
            r"\brefer to\b.{0,160}\b(?:form 10-k|annual report|sec filings?)\b",
            r"\brisk factors?\b.{0,160}\b(?:annual report|form 20-f|sec filings?)\b",
            r"\brisk production\b",
        ),
        "section": "prepared",
    },
    "analyst_questions": {
        "label": "分析師追問",
        "meaning": "只取完整逐字稿 Q&A 區段中的問題線索，用來辨識市場最關心的假設。",
        "patterns": (r"\bcan you\b", r"\bcould you\b", r"\bhow should\b", r"\bwhat (?:is|are|do|does)\b", r"\bhelp us\b", r"\bwalk us through\b"),
        "weights": (2, 2, 3, 2, 3, 3),
        "context_patterns": (
            r"\brevenue\b", r"\bmargins?\b", r"\bdemand\b", r"\bgrowth\b", r"\bcapex\b",
            r"\bcapital expenditures?\b", r"\bsupply\b", r"\bcosts?\b", r"\bcapacity\b", r"\bguidance\b",
        ),
        "require_question_mark": True,
        "section": "q_and_a",
    },
}

EXHIBIT_CATEGORY_MAP = {
    "demand_growth": ("revenue", "segments", "management"),
    "margin_cost": ("gross_margin",),
    "capital_supply": (),
    "guidance": ("guidance",),
    "confidence": ("management",),
    "risks": ("risks",),
    "analyst_questions": (),
}


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = handle.name
    os.replace(temporary, path)


def request_headers() -> dict[str, str]:
    return {
        "User-Agent": os.environ.get("SEC_USER_AGENT", "SecKBResearch user@example.com"),
        "Accept-Encoding": "identity",
    }


def download(url: str, timeout: int = 25) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers=request_headers())
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get_content_type()
        return response.read(), content_type


def download_browser_impersonated(
    url: str, timeout: int = 45, referer: str | None = None,
) -> tuple[bytes, str]:
    """Fetch official IR material from CDNs that reject urllib TLS fingerprints."""
    if curl_requests is None:
        raise urllib.error.URLError("缺少 curl_cffi，無法下載受 CDN 保護的官方 IR 材料")
    headers = {
        "Accept": "application/pdf,text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "identity",
    }
    if referer:
        headers["Referer"] = referer
    try:
        response = curl_requests.get(
            url, headers=headers, impersonate="chrome", timeout=timeout, allow_redirects=True,
        )
        response.raise_for_status()
    except Exception as exc:  # Normalize curl_cffi errors for the fail-closed caller.
        raise urllib.error.URLError(str(exc)) from exc
    content_type = response.headers.get("content-type", "application/octet-stream")
    return response.content, content_type.split(";", 1)[0].strip().lower()


def download_for_config(url: str, config: dict, timeout: int = 25) -> tuple[bytes, str]:
    if config.get("fetch_strategy") == "browser_impersonation":
        return download_browser_impersonated(url, max(timeout, 45), config.get("landing_url"))
    return download(url, timeout)


def probe_url(url: str) -> dict:
    """Check a replay link without treating anti-bot responses as proof it is dead."""
    request = urllib.request.Request(url, headers=request_headers(), method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return {"status": "reachable", "http_status": response.status}
    except urllib.error.HTTPError as exc:
        return {"status": "unverified", "http_status": exc.code, "reason": f"HTTP {exc.code}"}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"status": "unverified", "reason": type(exc).__name__}


def normalize_text(value: str) -> str:
    value = html_lib.unescape(value).replace("\x00", " ")
    value = re.sub(r"[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def allowed_url(url: str, allowed_hosts: list[str]) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in {host.lower() for host in allowed_hosts}


def organization_domain(hostname: str | None) -> str:
    parts = (hostname or "").lower().split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else (hostname or "").lower()


def verify_provenance(config: dict) -> tuple[dict, list[str]]:
    """Verify same-company hosting or the official landing-page-to-CDN chain."""
    landing_url = config.get("landing_url") or ""
    material_url = config.get("material_url") or ""
    landing_host = urllib.parse.urlparse(landing_url).hostname
    material_host = urllib.parse.urlparse(material_url).hostname
    if organization_domain(landing_host) == organization_domain(material_host):
        return {"status": "official_host", "landing_host": landing_host, "material_host": material_host}, []
    try:
        landing_payload, _ = download_for_config(landing_url, config)
        landing_html = html_lib.unescape(landing_payload.decode("utf-8", errors="ignore"))
        parser = LinkHTMLParser()
        parser.feed(landing_html)
        linked_urls = {
            urllib.parse.urljoin(landing_url, href)
            for href, _ in parser.links
        }
        if material_url in linked_urls:
            return {"status": "official_page_link", "landing_host": landing_host, "material_host": material_host}, []
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        pass
    verified_on = config.get("provenance_verified_on")
    note = config.get("provenance_note")
    try:
        age = (datetime.now(timezone.utc).date() - datetime.strptime(verified_on or "", "%Y-%m-%d").date()).days
    except ValueError:
        age = 9999
    if note and 0 <= age <= 180:
        return {
            "status": "manual_official_page_attestation", "verified_on": verified_on,
            "landing_host": landing_host, "material_host": material_host, "note": note,
        }, []
    return {}, ["跨網域材料未能由官方 IR 發現頁驗證，且沒有 180 天內人工覆核紀錄"]


class TextHTMLParser(HTMLParser):
    BLOCKS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th"}

    def __init__(self):
        super().__init__()
        self.depth = 0
        self.buffer: list[str] = []
        self.blocks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.BLOCKS:
            if self.depth == 0:
                self.buffer = []
            self.depth += 1
        elif tag.lower() == "br" and self.depth:
            self.buffer.append(" ")

    def handle_data(self, data):
        if self.depth:
            self.buffer.append(data)

    def handle_endtag(self, tag):
        if tag.lower() in self.BLOCKS and self.depth:
            self.depth -= 1
            if self.depth == 0:
                text = normalize_text("".join(self.buffer))
                if len(text) >= 20:
                    self.blocks.append(text)


class LinkHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.href: str | None = None
        self.text: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self.href = dict(attrs).get("href")
            self.text = []

    def handle_data(self, data):
        if self.href is not None:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.href is not None:
            self.links.append((self.href, normalize_text(" ".join(self.text))))
            self.href = None
            self.text = []


def period_key(value: str) -> tuple[int, int] | None:
    value = normalize_text(urllib.parse.unquote(value))
    patterns = (
        r"(?:FY\s*)?(20\d{2})\D{0,12}Q([1-4])",
        r"Q([1-4])\D{0,12}(?:FY\s*)?(20\d{2})",
        r"([1-4])Q(\d{2})",
    )
    for index, pattern in enumerate(patterns):
        match = re.search(pattern, value, re.I)
        if not match:
            continue
        first, second = (int(item) for item in match.groups())
        if index == 0:
            return first, second
        if index == 1:
            return second, first
        return 2000 + second, first
    return None


def discover_newer_material(config: dict, previous: dict | None = None) -> dict:
    """Find explicitly newer transcript/remarks links without auto-promoting them."""
    previous = previous or {}
    current_key = period_key(config.get("period", ""))
    if not current_key:
        return {"status": "unverified", "reason": "目前期間格式無法比較", "newer_candidates": []}
    try:
        payload, content_type = download_for_config(config["landing_url"], config, timeout=10)
        if content_type not in {"text/html", "application/xhtml+xml"}:
            return {"status": "unverified", "reason": "IR 發現頁不是 HTML", "newer_candidates": []}
        parser = LinkHTMLParser()
        parser.feed(payload.decode("utf-8", errors="ignore"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError) as exc:
        current = {"status": "unverified", "reason": type(exc).__name__, "newer_candidates": []}
        old = previous.get("discovery", {})
        return old if old.get("status") == "unverified" and not old.get("newer_candidates") else current
    candidates = {}
    for href, label in parser.links:
        url = urllib.parse.urljoin(config["landing_url"], href)
        descriptor = f"{label} {url}"
        if not re.search(r"\b(?:earnings call transcript|conference transcript|prepared remarks|transcript)\b", descriptor, re.I):
            continue
        if not allowed_url(url, config["allowed_hosts"]):
            continue
        candidate_key = period_key(descriptor)
        if candidate_key and candidate_key > current_key and url != config.get("material_url"):
            candidates[url] = {"period_key": f"{candidate_key[0]} Q{candidate_key[1]}", "label": label or "官方文字材料", "url": url}
    return {"status": "checked", "newer_candidates": list(candidates.values())[:5]}


def source_blocks(payload: bytes, content_type: str, url: str) -> list[dict]:
    is_pdf = content_type == "application/pdf" or payload.startswith(b"%PDF") or url.lower().endswith(".pdf")
    raw_blocks: list[str] = []
    if is_pdf:
        reader = PdfReader(io.BytesIO(payload))
        for page in reader.pages:
            text = page.extract_text() or ""
            raw_blocks.extend(re.split(r"\n{2,}|(?<=[.!?])\s+(?=[A-Z])", text))
    else:
        parser = TextHTMLParser()
        parser.feed(payload.decode("utf-8", errors="ignore"))
        raw_blocks = parser.blocks

    result = []
    seen = set()
    section = "prepared"
    for raw in raw_blocks:
        text = normalize_text(raw)
        heading = re.sub(r"[^a-z&]+", " ", text.casefold()).strip()
        if (re.search(r"\bQUESTION\s+AND\s+ANSWER\s+(?:SESSION|SECTION)\b", text)
                or re.match(r"^(?:question[- ]and[- ]answer|questions? and answers?|q\s*&\s*a)\b", text, re.I)
                or re.search(r"\b(?:go|move over) to Q\s*&\s*A\b", text, re.I)
                or re.search(r"\b(?:will|we(?:'|’)ll) now take (?:your|some) questions\b", text, re.I)
                or re.search(r"\b(?:our|your) first question comes from(?: the line of)?\b", text, re.I)
                or heading in {
            "question and answer session", "question and answer section",
            "questions and answers", "q & a", "q a",
        }):
            section = "q_and_a"
        key = text.casefold()
        if len(text) < 28 or key in seen:
            continue
        seen.add(key)
        result.append({"section": section, "text": text})
    return result


def short_excerpt(text: str, limit: int = MAX_EXCERPT_WORDS) -> str:
    words = text.split()
    return " ".join(words[:limit]) + ("…" if len(words) > limit else "")


def short_excerpt_around(text: str, char_position: int, limit: int = MAX_EXCERPT_WORDS) -> str:
    words = list(re.finditer(r"\S+", text))
    if len(words) <= limit:
        return text
    match_index = next(
        (index for index, word in enumerate(words) if word.start() <= char_position < word.end()),
        0,
    )
    start = max(0, min(match_index - 6, len(words) - limit))
    excerpt = " ".join(word.group(0) for word in words[start:start + limit])
    if start:
        excerpt = "…" + excerpt
    if start + limit < len(words):
        excerpt += "…"
    return excerpt


def extract_evidence(blocks: list[dict], config: dict) -> list[dict]:
    patterns = [re.compile(pattern, re.I) for pattern in config["patterns"]]
    weights = config.get("weights", (1,) * len(patterns))
    exclude_patterns = [re.compile(pattern, re.I) for pattern in config.get("exclude_patterns", ())]
    context_patterns = [re.compile(pattern, re.I) for pattern in config.get("context_patterns", ())]
    candidates = []
    for position, block in enumerate(blocks):
        if config.get("section") and block["section"] != config["section"]:
            continue
        if any(pattern.search(block["text"]) for pattern in exclude_patterns):
            continue
        if context_patterns and not any(pattern.search(block["text"]) for pattern in context_patterns):
            continue
        if config.get("require_question_mark") and "?" not in block["text"]:
            continue
        matches = [
            (weight, match)
            for pattern, weight in zip(patterns, weights)
            if (match := pattern.search(block["text"]))
        ]
        if not matches:
            continue
        score = sum(weight for weight, _ in matches) * 5 + (2 if any(char.isdigit() for char in block["text"]) else 0)
        score += 2 if 45 <= len(block["text"]) <= 420 else 0
        strongest = max(matches, key=lambda item: (item[0], -item[1].start()))[1]
        candidates.append((score, -position, block, strongest.start()))
    candidates.sort(reverse=True, key=lambda item: (item[0], item[1]))
    return [
        {"excerpt": short_excerpt_around(item[2]["text"], item[3]), "section": item[2]["section"]}
        for item in candidates[:MAX_EVIDENCE]
    ]


def document_identity_errors(blocks: list[dict], config: dict) -> list[str]:
    """Fail closed when configured company/period markers are absent from text."""
    patterns = config.get("identity_patterns", [])
    if not patterns:
        return ["來源未設定公司與期間身分驗證規則"]
    document = " ".join(block["text"] for block in blocks)
    missing = [pattern for pattern in patterns if not re.search(pattern, document, re.I)]
    return [f"官方文字未辨識公司／期間標記：{pattern}" for pattern in missing]


def card_path(root: Path, ticker: str, period: str) -> Path:
    safe_period = re.sub(r"[^A-Za-z0-9]+", "_", period).strip("_")
    return root / "20_Filings" / ticker / "analysis" / f"{ticker}_{safe_period}_Earnings_Call.md"


def exhibit_comparison(ticker: str, categories: dict, exhibit: dict) -> dict:
    rows = [row for row in exhibit.get("filings", []) if row.get("ticker") == ticker and row.get("status") == "analyzed"]
    if not rows:
        return {
            "status": "unavailable",
            "overlap_topics": [],
            "call_only_topics": [],
            "meaning": "沒有同公司可比的嚴格 Exhibit 99.1 卡，因此不推測兩份資料差異。",
        }
    row = sorted(rows, key=lambda item: (item.get("filing_date", ""), item.get("accession", "")), reverse=True)[0]
    overlap, call_only = [], []
    for key, evidence in categories.items():
        if not evidence:
            continue
        mapped = EXHIBIT_CATEGORY_MAP[key]
        if mapped and any(row.get("categories", {}).get(category) for category in mapped):
            overlap.append(key)
        else:
            call_only.append(key)
    return {
        "status": "topic_coverage_only",
        "exhibit_url": row.get("exhibit_url"),
        "filing_date": row.get("filing_date"),
        "overlap_topics": overlap,
        "call_only_topics": call_only,
        "meaning": "只比較兩份來源是否覆蓋同類主題；不代表內容一致、相反、利多或利空。",
    }


def source_freshness(config: dict, quarterly_company: dict | None) -> dict:
    latest = sorted(
        (quarterly_company or {}).get("periods", []),
        key=lambda item: (item.get("filing_date", ""), item.get("period_end", "")),
        reverse=True,
    )
    latest = latest[0] if latest else {}
    filing_date = latest.get("filing_date")
    call_date = config.get("call_date")
    result = {
        "status": "current",
        "latest_financial_period": latest.get("period_end"),
        "latest_financial_filing_date": filing_date,
        "meaning": "法說會日期未落後最新財務申報超過 45 天。",
    }
    if not filing_date or not call_date:
        result.update(status="unknown", meaning="缺少可比較日期，無法驗證來源是否仍為最新一期。")
        return result
    try:
        lag_days = (datetime.strptime(filing_date, "%Y-%m-%d") - datetime.strptime(call_date, "%Y-%m-%d")).days
    except ValueError:
        result.update(status="unknown", meaning="日期格式無法可靠比較，保留待覆核。")
        return result
    result["lag_days"] = lag_days
    if lag_days > 45:
        result.update(
            status="stale",
            meaning="法說會來源比最新財務申報早超過 45 天，可能仍是上一期；請更新官方來源後再當作最新卡閱讀。",
        )
    return result


def render_card(row: dict) -> str:
    sections = []
    for key, definition in CATEGORIES.items():
        evidence = row["categories"].get(key, [])
        sections += [f"## {definition['label']}", "", f"> **怎麼讀**：{definition['meaning']}", ""]
        sections.append(f"> {evidence[0]['excerpt']}" if evidence else "- **官方文字未可靠辨識此項；保留缺值。**")
        sections.append("")
    source = SOURCE_TYPES[row["source_type"]]
    provenance_label = {
        "official_host": "材料與 IR 頁屬同一公司網域",
        "official_page_link": "程式已在官方 IR 頁驗證材料直連",
        "manual_official_page_attestation": "官方頁受阻，採 180 天內人工官方連結覆核",
    }.get(row.get("provenance", {}).get("status"), "來源鏈尚未驗證")
    comparison = row["exhibit_comparison"]
    return f'''---
ticker: {row["ticker"]}
call_date: {row["call_date"]}
period: "{row["period"]}"
source_type: {row["source_type"]}
source_url: "{row["material_url"]}"
source_sha256: "{row["source_sha256"]}"
parser_version: {PARSER_VERSION}
tags:
  - earnings-call
  - company/{row["ticker"].lower()}
---

# {row["company_name"]} ({row["ticker"]})｜{row["period"]} Earnings Call 閱讀卡

## 來源與限制

- **會議日期**：{row["call_date"]}
- **文字類型**：{source["label"]}。{source["meaning"]}
- **官方來源**：[文字材料]({row["material_url"]})｜[IR 發現頁]({row["landing_url"]})
- **來源鏈驗證**：{provenance_label}
- **證據覆蓋**：{row["coverage"]["found"]}/{row["coverage"]["total"]} 類；這是閱讀索引，不是評分。
- **方法限制**：每類只保留最多 {MAX_EXCERPT_WORDS} 個英文單字的短摘錄。未命中保留缺值；不把語氣關鍵字轉成投資建議。

{chr(10).join(sections)}
## 與 Exhibit 99.1 的主題覆蓋比較

{comparison["meaning"]}

## 客觀閱讀結論

本卡只整理官方電話會議文字中的可追溯證據。完整逐字稿可讀管理層發言與 Q&A；Prepared Remarks 不含分析師追問，不能視為完整會議。
'''


def cached_analysis(base: dict, previous: dict, path: Path, error: Exception) -> dict | None:
    if (
        previous.get("status") not in ANALYZABLE_STATUSES
        or previous.get("period") != base["period"]
        or previous.get("material_url") != base["material_url"]
        or not path.is_file()
    ):
        return None
    preserved = {
        key: previous.get(key)
        for key in (
            "categories", "coverage", "q_and_a_available", "source_sha256",
            "exhibit_comparison", "card", "last_verified_at",
        )
    }
    return {
        **base, **preserved, "status": "analyzed_cached",
        "errors": [f"本次下載失敗，保留上次已驗證卡：{type(error).__name__}"],
    }


def row_fingerprint(parser_version: int | None, row: dict) -> str:
    material = {
        "parser_version": parser_version,
        "period": row.get("period"),
        "call_date": row.get("call_date"),
        "material_url": row.get("material_url"),
        "source_type": row.get("source_type"),
        "source_sha256": row.get("source_sha256"),
        "status": row.get("status"),
        "freshness": row.get("freshness"),
        "categories": row.get("categories"),
        "q_and_a_available": row.get("q_and_a_available"),
        "exhibit_comparison": row.get("exhibit_comparison"),
        "link_check": row.get("link_check"),
        "provenance": row.get("provenance"),
        "discovery": row.get("discovery"),
    }
    return hashlib.sha256(
        json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
def analyze_company(
    ticker: str, config: dict, exhibit: dict, root: Path, previous: dict | None = None,
) -> dict:
    previous = previous or {}
    path = card_path(root, ticker, config["period"])
    base = {
        "ticker": ticker,
        "company_name": config["company_name"],
        "period": config["period"],
        "call_date": config["call_date"],
        "landing_url": config["landing_url"],
        "material_url": config.get("material_url") or None,
        "allowed_hosts": config["allowed_hosts"],
        "source_type": config["source_type"],
        "source_label": SOURCE_TYPES[config["source_type"]]["label"],
        "source_meaning": SOURCE_TYPES[config["source_type"]]["meaning"],
        "note": config.get("note", ""),
        "expected_card": str(path.relative_to(root)),
    }
    url = config.get("material_url") or ""
    landing_url = config.get("landing_url") or ""
    if not landing_url or not allowed_url(landing_url, config["allowed_hosts"]):
        if path.is_file():
            path.unlink()
        return {
            **base, "status": "review_required", "categories": {},
            "coverage": {"found": 0, "total": len(CATEGORIES)},
            "errors": ["IR 發現頁不是該公司的 HTTPS 明確允許主機"],
        }
    if not url or not allowed_url(url, config["allowed_hosts"]):
        if path.is_file():
            path.unlink()
        reason = "官方 IR 頁尚未可靠解析出本期材料直連" if not url else "材料主機不在該公司的明確允許清單"
        return {
            **base, "status": "review_required", "categories": {},
            "coverage": {"found": 0, "total": len(CATEGORIES)}, "errors": [reason],
        }
    provenance, provenance_errors = verify_provenance(config)
    if provenance_errors:
        if path.is_file():
            path.unlink()
        return {
            **base, "status": "review_required", "categories": {}, "provenance": provenance,
            "coverage": {"found": 0, "total": len(CATEGORIES)}, "errors": provenance_errors,
        }
    base["provenance"] = provenance
    if config["source_type"] == "webcast_replay":
        if path.is_file():
            path.unlink()
        link_check = probe_url(url)
        if (
            link_check.get("status") == "unverified"
            and previous.get("status") == "replay_only"
            and previous.get("material_url") == url
            and previous.get("link_check", {}).get("status") == "unverified"
        ):
            link_check = previous["link_check"]
        return {
            **base, "status": "replay_only", "categories": {},
            "coverage": {"found": 0, "total": len(CATEGORIES)}, "errors": [],
            "link_check": link_check,
        }
    try:
        payload, content_type = download_for_config(url, config)
        blocks = source_blocks(payload, content_type, url)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        cached = cached_analysis(base, previous, path, exc)
        if cached:
            return cached
        errors = [f"{type(exc).__name__}: {exc}"]
        if (
            previous.get("status") == "download_failed"
            and previous.get("period") == base["period"]
            and previous.get("material_url") == base["material_url"]
            and previous.get("errors")
        ):
            errors = previous["errors"]
        return {
            **base, "status": "download_failed", "categories": {},
            "coverage": {"found": 0, "total": len(CATEGORIES)},
            "errors": errors,
        }
    if len(blocks) < 12:
        if path.is_file():
            path.unlink()
        return {
            **base, "status": "review_required", "categories": {},
            "coverage": {"found": 0, "total": len(CATEGORIES)},
            "errors": [f"只辨識到 {len(blocks)} 個文字區塊，拒絕產生分析卡"],
        }
    identity_errors = document_identity_errors(blocks, config)
    if identity_errors:
        if path.is_file():
            path.unlink()
        return {
            **base, "status": "review_required", "categories": {},
            "coverage": {"found": 0, "total": len(CATEGORIES)}, "errors": identity_errors,
        }
    q_and_a_available = config["source_type"] == "full_transcript" and any(
        block["section"] == "q_and_a" for block in blocks
    )
    if config["source_type"] == "full_transcript" and not q_and_a_available:
        if path.is_file():
            path.unlink()
        return {
            **base, "status": "review_required", "categories": {},
            "coverage": {"found": 0, "total": len(CATEGORIES)},
            "errors": ["登錄為完整逐字稿，但未可靠辨識 Q&A 區段"],
        }
    categories = {key: extract_evidence(blocks, definition) for key, definition in CATEGORIES.items()}
    if config["source_type"] == "prepared_remarks":
        categories["analyst_questions"] = []
    comparison = exhibit_comparison(ticker, categories, exhibit)
    row = {
        **base, "status": "analyzed", "categories": categories,
        "coverage": {"found": sum(bool(value) for value in categories.values()), "total": len(CATEGORIES)},
        "q_and_a_available": q_and_a_available,
        "source_sha256": hashlib.sha256(payload).hexdigest(),
        "exhibit_comparison": comparison, "errors": [],
    }
    row["last_verified_at"] = (
        previous.get("last_verified_at")
        if previous.get("source_sha256") == row["source_sha256"] and previous.get("last_verified_at")
        else now_utc()
    )
    atomic_write(path, render_card(row))
    row["card"] = str(path.relative_to(root))
    return row


def render_radar(status: dict) -> str:
    rows = list(status["companies"].values())
    analyzed = [row for row in rows if row["status"] in ANALYZABLE_STATUSES]
    replay = [row for row in rows if row["status"] == "replay_only"]
    pending = [row for row in rows if row["status"] not in ANALYZABLE_STATUSES | {"replay_only"}]
    lines = [
        "---", "title: 官方 Earnings Call 與 Prepared Remarks 雷達", f"updated_at: {status['updated_at']}",
        "tags:", "  - earnings-call", "  - investor-relations", "---", "",
        "# 🎙️ 官方 Earnings Call／Prepared Remarks 雷達", "",
        "只收公司 IR 官方頁或由官方頁連出的明確允許主機；不使用第三方逐字稿，不對影音自動轉錄。短摘錄是閱讀索引，不是情緒分數或投資建議。", "",
        f"- 可分析官方文字：**{len(analyzed)} 家**", f"- 僅官方影音／回放：**{len(replay)} 家**",
        f"- 待覆核／下載失敗：**{len(pending)} 家**", "", "## 14 家最新狀態", "",
        "| 公司 | 期間／日期 | 官方資料型態 | 狀態 | 入口 |", "|---|---|---|---|---|",
    ]
    status_labels = {"analyzed": "✅ 已建立文字卡", "analyzed_cached": "⚠️ 本次下載失敗；顯示上次驗證卡", "replay_only": "🎧 僅影音", "review_required": "⚠️ 待覆核", "download_failed": "⚠️ 下載失敗"}
    for row in rows:
        link = f"[[{row['card'].removesuffix('.md')}|閱讀卡]]" if row.get("card") else f"[官方來源]({row.get('material_url') or row['landing_url']})"
        freshness = "；⏳ 來源可能過期" if row.get("freshness", {}).get("status") == "stale" else ""
        newer = "；🆕 發現較新官方候選" if row.get("discovery", {}).get("newer_candidates") else ""
        lines.append(f"| **{row['ticker']}** | {row['period']}／{row['call_date']} | {row['source_label']} | {status_labels[row['status']]}{freshness}{newer} | {link} |")
    lines += ["", "## 每個欄位怎麼讀", ""]
    for definition in CATEGORIES.values():
        lines.append(f"- **{definition['label']}**：{definition['meaning']}")
    lines += ["", "## 重要限制", "", "- Prepared Remarks 沒有分析師追問，不能與完整逐字稿等量齊觀。", "- 僅影音公司不產生文字判讀；需要人工聆聽官方回放。", "- 與 Exhibit 99.1 只比較主題有無覆蓋，不判定兩份內容一致或矛盾。", ""]
    return "\n".join(lines)


def write_outputs(path: Path | None, heading: str, lines: list[str]) -> None:
    if not path:
        return
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n## {heading}\n\n")
        handle.write("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--exhibit", type=Path, default=DEFAULT_EXHIBIT)
    parser.add_argument("--quarterly", type=Path, default=DEFAULT_QUARTERLY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--radar", type=Path, default=DEFAULT_RADAR)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--alert-markdown", type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    config = load_json(args.config, {})
    exhibit = load_json(args.exhibit, {})
    quarterly = load_json(args.quarterly, {}).get("companies", {})
    previous_payload = load_json(args.output, {})
    previous = previous_payload.get("companies", {})
    previous_parser_version = previous_payload.get("parser_version")
    results = {}
    for ticker, company in config.get("companies", {}).items():
        previous_row = previous.get(ticker, {})
        row = analyze_company(ticker, company, exhibit, args.root, previous_row)
        row["discovery"] = discover_newer_material(company, previous_row)
        row["freshness"] = source_freshness(company, quarterly.get(ticker))
        old_fingerprint = row_fingerprint(previous_parser_version, previous_row)
        new_fingerprint = row_fingerprint(PARSER_VERSION, row)
        row["changed"] = not previous_row or old_fingerprint != new_fingerprint
        results[ticker] = row
        print(f"  {'✅' if row['status'] == 'analyzed' else '⚠️'} {ticker:6s} {row['status']}")
    changed = [row for row in results.values() if row["changed"]]
    persisted_results = {
        ticker: {key: value for key, value in row.items() if key != "changed"}
        for ticker, row in results.items()
    }
    status = {
        "schema_version": SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "updated_at": now_utc() if changed or not previous_payload.get("updated_at") else previous_payload["updated_at"],
        "source": "Official company investor-relations pages and explicitly allow-listed linked hosts",
        "methodology": "Official text only; no audio transcription; short verbatim evidence; missing stays missing; no sentiment score",
        "source_types": SOURCE_TYPES,
        "categories": {key: {"label": value["label"], "meaning": value["meaning"]} for key, value in CATEGORIES.items()},
        "companies": persisted_results,
    }
    atomic_write(args.output, json.dumps(status, ensure_ascii=False, indent=2) + "\n")
    atomic_write(args.radar, render_radar(status))

    pending = [row for row in results.values() if row["status"] not in {"analyzed", "replay_only"}]
    pending = [row for row in pending if row["status"] not in ANALYZABLE_STATUSES]
    analyzed = [row for row in results.values() if row["status"] in ANALYZABLE_STATUSES]
    changed_pending = [row for row in changed if row["status"] not in ANALYZABLE_STATUSES | {"replay_only"}]
    stale = [row for row in results.values() if row["freshness"]["status"] == "stale"]
    newer = [row for row in results.values() if row.get("discovery", {}).get("newer_candidates")]
    changed_attention = [
        row for row in changed
        if row["status"] not in ANALYZABLE_STATUSES | {"replay_only"}
        or row.get("discovery", {}).get("newer_candidates")
    ]
    summary_lines = [f"官方文字可分析 {len(analyzed)} 家；待覆核／下載失敗 {len(pending)} 家；來源可能過期 {len(stale)} 家；較新官方材料候選 {len(newer)} 家；本次狀態或來源變更 {len(changed)} 家。"]
    summary_lines.extend(f"- {row['ticker']}：{'；'.join(row['errors'])}" for row in pending)
    write_outputs(args.summary, "官方 Earnings Call／Prepared Remarks 雷達", summary_lines)
    if changed:
        alert_lines = ["官方 Earnings Call 雷達需要閱讀："]
        alert_lines.extend(f"- {row['ticker']}：來源或狀態有變更（{row['status']}）" for row in changed)
        alert_lines.extend(f"- {row['ticker']}：{'；'.join(row['errors'])}" for row in changed_pending)
        alert_lines.extend(f"- {row['ticker']}：官方 IR 頁出現較新文字材料候選，需核對並更新來源登錄" for row in newer if row in changed)
        write_outputs(args.alert_markdown, "Earnings Call／Prepared Remarks", alert_lines)
    if args.github_output:
        batch_source = "|".join(
            f"{row['ticker']}:{row_fingerprint(PARSER_VERSION, row)}"
            for row in changed
        ) or "no-change"
        batch_id = hashlib.sha256(batch_source.encode()).hexdigest()[:12]
        with args.github_output.open("a", encoding="utf-8") as handle:
            handle.write(f"earnings_call_pending_count={len(pending)}\n")
            handle.write(f"earnings_call_changed_pending_count={len(changed_pending)}\n")
            handle.write(f"earnings_call_changed_attention_count={len(changed_attention)}\n")
            handle.write(f"earnings_call_new_source_count={len(newer)}\n")
            handle.write(f"earnings_call_changed_count={len(changed)}\n")
            handle.write(f"earnings_call_analyzed_count={len(analyzed)}\n")
            handle.write(f"earnings_call_stale_count={len(stale)}\n")
            handle.write(f"earnings_call_batch_id={batch_id}\n")
    return 2 if pending else 0


if __name__ == "__main__":
    raise SystemExit(main())
