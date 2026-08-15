#!/usr/bin/env python3
"""Build specialized 10-Q, Form 4, and fundraising/dilution SEC radars.

The general filing watcher owns scheduling and accession-number deduplication.
This module enriches selected filings from their primary SEC documents and
writes decision-friendly Obsidian notes.  Parsed details are cached by
accession number so routine checks do not repeatedly download old documents.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DETAILS = REPO_ROOT / "sec_filing_details.json"
DEFAULT_RADAR_DIR = REPO_ROOT / "60_SEC_Filing_Radar"

FORM4_FORMS = {"4", "4/A"}
OFFERING_FORMS = {
    "S-3", "S-3/A", "S-3ASR", "F-3", "F-3/A", "F-3ASR",
    "424B2", "424B3", "424B4", "424B5", "POS AM", "EFFECT",
}
FOREIGN_PRIVATE_ISSUERS = {"ARM", "NOK", "TSM"}
OFFERING_CLASSIFIER_VERSION = 3

TRANSACTION_CODES = {
    "A": "公司授予／獎勵",
    "C": "衍生證券轉換",
    "D": "向公司出售／移轉",
    "F": "以證券支付稅款或履約價",
    "G": "贈與",
    "J": "其他交易（看註腳）",
    "K": "股權交換／類似交易",
    "M": "衍生證券行使／轉換",
    "P": "公開市場或私下買入",
    "S": "公開市場或私下賣出",
    "V": "自願申報",
}


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style"}:
            self.ignored_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style"} and self.ignored_depth:
            self.ignored_depth -= 1

    def handle_data(self, data):
        if not self.ignored_depth:
            self.parts.append(data)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(path, fallback):
    path = Path(path)
    if not path.exists():
        return fallback
    return json.loads(path.read_text())


def fetch_document(url, attempts=3):
    user_agent = os.environ.get("SEC_USER_AGENT", "SecKBResearch user@example.com")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml,text/xml,*/*",
        },
    )
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError):
            if attempt + 1 == attempts:
                raise
            time.sleep(1.5 * (attempt + 1))


def raw_ownership_url(url):
    """Remove SEC's XSL display directory to reach the source Ownership XML."""
    return re.sub(r"/xsl[^/]+/", "/", url, flags=re.IGNORECASE)


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


def direct_child(element, name):
    return next((child for child in element if local_name(child.tag) == name), None)


def nested_text(element, *names):
    current = element
    for name in names:
        if current is None:
            return None
        current = direct_child(current, name)
    if current is None or current.text is None:
        return None
    value = current.text.strip()
    return value or None


def descendants(element, name):
    return [node for node in element.iter() if local_name(node.tag) == name]


def number(value):
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


def yes_no(value):
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    return None


def parse_form4(xml_bytes):
    """Return normalized Form 4 transactions without inventing missing zeroes."""
    root = ElementTree.fromstring(xml_bytes)
    owners = []
    for owner in descendants(root, "reportingOwner"):
        name = nested_text(owner, "reportingOwnerId", "rptOwnerName")
        relationship = direct_child(owner, "reportingOwnerRelationship")
        roles = []
        if relationship is not None:
            if yes_no(nested_text(relationship, "isDirector")):
                roles.append("董事")
            if yes_no(nested_text(relationship, "isOfficer")):
                title = nested_text(relationship, "officerTitle")
                roles.append(f"高階主管（{title}）" if title else "高階主管")
            if yes_no(nested_text(relationship, "isTenPercentOwner")):
                roles.append("10% 大股東")
            if yes_no(nested_text(relationship, "isOther")):
                roles.append(nested_text(relationship, "otherText") or "其他")
        owners.append({"name": name or "未列名", "role": "、".join(roles) or "未註明"})

    reporter = "、".join(owner["name"] for owner in owners) or "未列名"
    role = "；".join(owner["role"] for owner in owners) or "未註明"
    xml_text = xml_bytes.decode("utf-8", errors="ignore")
    plan_flag = bool(re.search(r"10b5[\s-]*1", xml_text, flags=re.IGNORECASE))
    transactions = []

    def collect(tag, security_type):
        for tx in descendants(root, tag):
            shares = number(nested_text(tx, "transactionAmounts", "transactionShares", "value"))
            price = number(nested_text(tx, "transactionAmounts", "transactionPricePerShare", "value"))
            code = nested_text(tx, "transactionCoding", "transactionCode")
            explicit_plan = yes_no(nested_text(tx, "transactionCoding", "isRule10b5-1"))
            if explicit_plan is None:
                explicit_plan = yes_no(nested_text(tx, "transactionCoding", "is10b5-1"))
            transactions.append({
                "reporter": reporter,
                "role": role,
                "security_type": security_type,
                "security_title": nested_text(tx, "securityTitle", "value"),
                "transaction_date": nested_text(tx, "transactionDate", "value"),
                "code": code,
                "code_label": TRANSACTION_CODES.get(code, "未分類代碼" if code else "未提供"),
                "shares": shares,
                "price": price,
                "value": shares * price if shares is not None and price is not None else None,
                "acquired_disposed": nested_text(
                    tx, "transactionAmounts", "transactionAcquiredDisposedCode", "value"
                ),
                "shares_after": number(nested_text(
                    tx, "postTransactionAmounts", "sharesOwnedFollowingTransaction", "value"
                )),
                "ownership": nested_text(tx, "ownershipNature", "directOrIndirectOwnership", "value"),
                "rule_10b5_1": explicit_plan if explicit_plan is not None else plan_flag,
            })

    collect("nonDerivativeTransaction", "普通股／非衍生")
    collect("derivativeTransaction", "衍生證券")
    return {"owners": owners, "transactions": transactions}


def html_to_text(content):
    decoded = content.decode("utf-8", errors="ignore")
    parser = TextExtractor()
    parser.feed(decoded)
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def classify_offering(form, document_text):
    """Classify an offering document conservatively from its actual content."""
    text = document_text.lower()
    # The cover and summary identify the security actually being offered.
    # Searching the full prospectus causes false positives because risk factors
    # and indentures often mention every security the company could issue.
    lead = text[:60000]
    has_equity = any(term in lead for term in (
        "common stock", "ordinary shares", "american depositary shares", "adss",
    ))
    has_offering = any(term in lead for term in (
        "we are offering", "offering of", "offer and sale", "may offer", "prospectus supplement",
    ))
    has_convertible = any(term in lead for term in (
        "convertible senior notes", "convertible notes", "convertible debt",
        "mandatory convertible preferred stock",
    ))
    has_atm = any(term in lead for term in (
        "at-the-market offering", "at the market offering", "at-the-market sales agreement",
        "equity distribution agreement", "sales agreement prospectus",
    ))
    has_debt = any(term in lead for term in (
        "senior notes", "aggregate principal amount", "debt securities", "notes due",
    ))
    shelf_form = form.startswith("S-3") or form.startswith("F-3") or form == "POS AM"
    broad_shelf = shelf_form and (
        "from time to time" in lead
        and has_equity
        and any(term in lead for term in ("preferred stock", "debt securities", "warrants"))
    )

    def result(category, label, risk, dilution):
        return {
            "classifier_version": OFFERING_CLASSIFIER_VERSION,
            "category": category,
            "label": label,
            "risk": risk,
            "dilution": dilution,
        }

    if form == "EFFECT":
        return result(
            "registration_effective", "註冊生效通知",
            "不等於證券已經發行；需連同註冊聲明與後續 prospectus 判讀",
            "待後續文件確認",
        )
    if broad_shelf:
        return result(
            "shelf", "架上註冊",
            "先取得未來募資彈性，不代表立即發行；可能包含股權或債券",
            "可能稀釋，尚未發生",
        )
    if has_convertible:
        return result(
            "convertible", "可轉債募資",
            "若轉換為股票，可能增加流通股數並稀釋每股價值", "潛在股權稀釋",
        )
    if has_atm and has_equity:
        return result(
            "atm_equity", "ATM 股權發行",
            "公司可依協議分批賣股；實際稀釋取決於已售股數與價格", "可能直接稀釋",
        )
    # 424B2 commonly reports debt pricing.  Give an explicit debt offering
    # precedence over incidental equity references elsewhere on the cover.
    if has_debt:
        return result(
            "debt", "一般債券募資",
            "增加利息與償債負擔，但通常不直接增加流通股數", "非直接股權稀釋",
        )
    if has_equity and has_offering:
        return result(
            "equity", "股權發行／轉售",
            "若是公司新發行股票會直接稀釋；若僅既有股東轉售則未必",
            "需辨別新發行或轉售",
        )
    if shelf_form:
        return result(
            "shelf", "架上註冊",
            "先取得未來募資彈性，不代表立即發行；可能包含股權或債券",
            "可能稀釋，尚未發生",
        )
    return result(
        "review", "待人工判讀", "僅憑表單名稱無法可靠判斷證券種類與是否稀釋",
        "不確定",
    )


def pipe(value):
    return str(value if value not in {None, ""} else "—").replace("|", "\\|").replace("\n", " ")


def fmt_number(value, decimals=0):
    if value is None:
        return "—"
    if decimals:
        return f"{value:,.{decimals}f}"
    return f"{value:,.0f}"


def event_sort_key(event):
    return event.get("filing_date", ""), event.get("accepted_at", "")


def latest_quarterly_rows(fetched):
    rows = []
    for ticker, events in sorted(fetched.items()):
        quarterly = sorted(
            (event for event in events if event["form"] in {"10-Q", "10-Q/A"}),
            key=event_sort_key,
            reverse=True,
        )
        if quarterly:
            rows.append({"ticker": ticker, "status": "filed", "event": quarterly[0]})
        elif ticker in FOREIGN_PRIVATE_ISSUERS or any(
                event["form"] in {"20-F", "20-F/A"} for event in events):
            rows.append({"ticker": ticker, "status": "foreign", "event": None})
        else:
            rows.append({"ticker": ticker, "status": "missing", "event": None})
    return rows


def render_quarterly_radar(fetched, checked_at):
    lines = [
        "---", "title: 10-Q 季報雷達", f"updated_at: {checked_at}", "tags:",
        "  - sec/10-q", "  - filings/quarterly", "---", "", "# 📊 10-Q 季報雷達", "",
        "顯示每家美國申報公司的最新 10-Q；日期與連結直接取自 SEC。",
        "這裡追蹤的是申報是否到位，不代表已完成財務數字的 QoQ／YoY 分析。", "",
        "| 公司 | 最新季報 | 申報日 | 報告期末 | 狀態 | SEC 原文 |",
        "|---|---|---|---|---|---|",
    ]
    for row in latest_quarterly_rows(fetched):
        event = row["event"]
        if row["status"] == "filed":
            lines.append(
                f"| **{row['ticker']}** | {event['form']} | {pipe(event['filing_date'])} | "
                f"{pipe(event['report_date'])} | ✅ 已申報 | [原文]({event['url']}) |"
            )
        elif row["status"] == "foreign":
            lines.append(
                f"| **{row['ticker']}** | — | — | — | 🌍 外國私人發行人，通常改看 6-K／20-F | — |"
            )
        else:
            lines.append(f"| **{row['ticker']}** | — | — | — | ⚠️ 近期清單未找到 10-Q | — |")
    lines += [
        "", "## 如何判讀", "",
        "- 先看「報告期末」確認是哪一季，再用「申報日」判斷資訊新鮮度。",
        "- `10-Q/A` 是修正版；應搭配原始 10-Q 比較修正內容。",
        "- ARM、NOK、TSM 為外國私人發行人，通常以 20-F 年報與 6-K 即時資料取代 10-Q。",
        "", f"> 最後檢查：`{checked_at}`", "",
    ]
    return "\n".join(lines)


def render_form4_radar(rows, errors, checked_at):
    lines = [
        "---", "title: Form 4 內部人交易雷達", f"updated_at: {checked_at}", "tags:",
        "  - sec/form-4", "  - insiders", "---", "", "# 🕵️ Form 4 內部人交易雷達", "",
        "直接解析 SEC Ownership XML。`P`／`S` 才是公開市場或私下買賣；",
        "`A`、`M`、`F`、`G` 等常是薪酬、履約、扣稅或贈與，不能一律解讀成主動買賣。", "",
        "| 申報日 | 公司 | 申報人／身分 | 代碼與意義 | 股數 | 單價 | 交易金額 | 取得／處分 | 10b5-1 | SEC |",
        "|---|---|---|---|---:|---:|---:|---|---|---|",
    ]
    for row in sorted(rows, key=lambda value: (
            value["event"].get("filing_date", ""), value["transaction"].get("transaction_date") or ""
            ), reverse=True)[:200]:
        event = row["event"]
        tx = row["transaction"]
        ad = {"A": "取得", "D": "處分"}.get(tx.get("acquired_disposed"), tx.get("acquired_disposed") or "—")
        plan = "是" if tx.get("rule_10b5_1") is True else ("否／未註明" if tx.get("rule_10b5_1") is False else "—")
        code = tx.get("code") or "—"
        lines.append(
            f"| {pipe(event['filing_date'])} | **{pipe(event['ticker'])}** | "
            f"{pipe(tx.get('reporter'))}／{pipe(tx.get('role'))} | `{pipe(code)}` {pipe(tx.get('code_label'))} | "
            f"{fmt_number(tx.get('shares'))} | {fmt_number(tx.get('price'), 2)} | "
            f"{fmt_number(tx.get('value'), 0)} | {pipe(ad)} | {plan} | [原文]({event['url']}) |"
        )
    if not rows:
        lines.append("| — | — | — | 尚無可解析交易 | — | — | — | — | — | — |")
    lines += [
        "", "## 交易代碼速查", "",
        "| 代碼 | SEC 定義的實務意義 | 判讀重點 |", "|---|---|---|",
        "| `P` | 公開市場或私下買入 | 通常最接近內部人主動加碼 |",
        "| `S` | 公開市場或私下賣出 | 需看 10b5-1、持股比例與是否為例行處分 |",
        "| `A` | 公司授予或獎勵 | 多屬薪酬，不是自掏腰包買入 |",
        "| `M`／`C` | 選擇權行使或衍生證券轉換 | 常與同日賣出一起出現，需合併判讀 |",
        "| `F` | 用股票支付稅款或履約價 | 常是 vesting 扣稅，不宜直接視為看空 |",
        "| `G` | 贈與 | 所有權轉移，不代表市場買賣 |",
        "", "> 金額只在股數與單價都由 SEC 文件提供時才計算；缺值保留為「—」，不以 0 代替。",
    ]
    if errors:
        lines += ["", "## 解析警告", ""] + [f"- {pipe(error)}" for error in errors]
    lines += ["", f"> 最後檢查：`{checked_at}`", ""]
    return "\n".join(lines)


def render_offering_radar(rows, errors, checked_at):
    lines = [
        "---", "title: 募資與稀釋雷達", f"updated_at: {checked_at}", "tags:",
        "  - sec/offering", "  - dilution", "---", "", "# 💧 募資與稀釋雷達", "",
        "以 SEC 文件內文判別證券種類，而不是看到 `424B` 就一律標成增發。",
        "「註冊」或 `EFFECT` 只代表發行工具可用／生效，不等於股票已實際售出。", "",
        "| 日期 | 公司 | 表單 | 分類 | 稀釋判斷 | 判讀重點 | SEC 原文 |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in sorted(rows, key=lambda value: event_sort_key(value["event"]), reverse=True)[:150]:
        event = row["event"]
        result = row["classification"]
        lines.append(
            f"| {pipe(event['filing_date'])} | **{pipe(event['ticker'])}** | {pipe(event['form'])} | "
            f"{pipe(result['label'])} | {pipe(result['dilution'])} | {pipe(result['risk'])} | "
            f"[原文]({event['url']}) |"
        )
    if not rows:
        lines.append("| — | — | — | 尚無文件 | — | — | — |")
    lines += [
        "", "## 優先級", "",
        "1. **ATM／新股發行**：可能直接增加流通股數；再查已售股數、平均售價與所得款項。",
        "2. **可轉債**：先增加債務，未來轉換時可能稀釋；需看轉換價、上限與避險交易。",
        "3. **一般債券**：通常不直接稀釋，但提高利息與到期償債壓力。",
        "4. **架上註冊／EFFECT**：是募資準備動作；等後續 prospectus supplement 才能確認實際發行。",
        "", "> 本雷達不估算稀釋百分比；只有在文件揭露且能可靠取得實際新發行股數時，才適合計算。",
    ]
    if errors:
        lines += ["", "## 解析警告", ""] + [f"- {pipe(error)}" for error in errors]
    lines += ["", f"> 最後檢查：`{checked_at}`", ""]
    return "\n".join(lines)


def update_radars(fetched, details_path=DEFAULT_DETAILS, radar_dir=DEFAULT_RADAR_DIR, checked_at=None):
    """Refresh all specialized radars from fetched submission metadata."""
    checked_at = checked_at or utc_now()
    details_path = Path(details_path)
    radar_dir = Path(radar_dir)
    cache = load_json(details_path, {"schema_version": 1, "form4": {}, "offerings": {}})
    cache.setdefault("form4", {})
    cache.setdefault("offerings", {})
    form4_rows = []
    offering_rows = []
    form4_errors = []
    offering_errors = []

    for ticker, events in sorted(fetched.items()):
        form4_events = sorted(
            (event for event in events if event["form"] in FORM4_FORMS),
            key=event_sort_key,
            reverse=True,
        )[:8]
        for event in form4_events:
            accession = event["accession"]
            parsed = cache["form4"].get(accession)
            if parsed is None:
                try:
                    parsed = parse_form4(fetch_document(raw_ownership_url(event["url"])))
                    cache["form4"][accession] = parsed
                    time.sleep(0.12)
                except (urllib.error.URLError, TimeoutError, ElementTree.ParseError) as exc:
                    form4_errors.append(f"{ticker} {accession}: {type(exc).__name__}: {exc}")
                    continue
            for transaction in parsed.get("transactions", []):
                form4_rows.append({"event": event, "transaction": transaction})

        offering_events = sorted(
            (event for event in events if event["form"] in OFFERING_FORMS),
            key=event_sort_key,
            reverse=True,
        )[:10]
        for event in offering_events:
            accession = event["accession"]
            result = cache["offerings"].get(accession)
            if result is None or result.get("classifier_version") != OFFERING_CLASSIFIER_VERSION:
                try:
                    text = html_to_text(fetch_document(event["url"]))
                    result = classify_offering(event["form"], text)
                    cache["offerings"][accession] = result
                    time.sleep(0.12)
                except (urllib.error.URLError, TimeoutError) as exc:
                    offering_errors.append(f"{ticker} {accession}: {type(exc).__name__}: {exc}")
                    continue
            offering_rows.append({"event": event, "classification": result})

    cache["schema_version"] = 1
    cache["updated_at"] = checked_at
    cache["source"] = "SEC primary documents; keyed by accession number"
    details_path.parent.mkdir(parents=True, exist_ok=True)
    details_path.write_text(json.dumps(cache, indent=2, ensure_ascii=False) + "\n")
    radar_dir.mkdir(parents=True, exist_ok=True)
    (radar_dir / "Quarterly_10Q_Radar.md").write_text(
        render_quarterly_radar(fetched, checked_at) + "\n"
    )
    (radar_dir / "Form4_Insider_Radar.md").write_text(
        render_form4_radar(form4_rows, form4_errors, checked_at) + "\n"
    )
    (radar_dir / "Dilution_Offering_Radar.md").write_text(
        render_offering_radar(offering_rows, offering_errors, checked_at) + "\n"
    )
    return {
        "form4_transactions": len(form4_rows),
        "offering_documents": len(offering_rows),
        "errors": form4_errors + offering_errors,
    }
