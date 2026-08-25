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
OWNERSHIP_FORMS = {
    "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A",
    "SCHEDULE 13D", "SCHEDULE 13D/A", "SCHEDULE 13G", "SCHEDULE 13G/A",
}
MA_FORMS = {"S-4", "S-4/A", "F-4", "F-4/A", "425", "SC TO-C", "SC TO-I", "SC TO-I/A", "SC TO-T", "SC TO-T/A", "SC 14D9", "SC 14D9/A", "SC 13E3", "SC 13E3/A"}
MA_REGISTRATION_FORMS = {"S-4", "S-4/A", "F-4", "F-4/A"}
MA_COMMUNICATION_FORMS = {"425"}
MA_TENDER_FORMS = {"SC TO-C", "SC TO-I", "SC TO-I/A", "SC TO-T", "SC TO-T/A", "SC 14D9", "SC 14D9/A"}
MA_GOING_PRIVATE_FORMS = {"SC 13E3", "SC 13E3/A"}
MERGER_WINDOW_YEARS = 3
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


def fetch(url, accept="*/*", max_bytes=None):
    headers = {
        "User-Agent": os.environ.get("SEC_USER_AGENT", "SecKBResearch user@example.com"),
        "Accept": accept,
    }
    if max_bytes:
        headers["Range"] = f"bytes=0-{max_bytes - 1}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read(max_bytes) if max_bytes else response.read()


def html_text(raw):
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _ownership_number(text, label, percent=False):
    """Read the first disclosed number after a Schedule 13D/G row label."""
    match = re.search(label, text, re.IGNORECASE)
    if not match:
        return None
    tail = text[match.end():match.end() + 180]
    tail = re.sub(r"^\s*(?:(?:\(SEE INSTRUCTIONS\))|(?:\(\d+\))|:)+\s*", "", tail, flags=re.IGNORECASE)
    number = re.search(r"([\d][\d,]*(?:\.\d+)?)\s*(%)?", tail)
    if not number or (percent and number.group(2) != "%"):
        return None
    value = float(number.group(1).replace(",", ""))
    return value if percent else int(value)


def _ownership_event_date(text):
    match = re.search(
        r"([A-Z][a-z]+\s+\d{1,2},\s+\d{4})\s*-*\s*\(Date of Event (?:Which|which) Requires Filing of this Statement\)",
        text,
    )
    return match.group(1) if match else ""


def _ownership_cusips(text):
    values = []
    for marker in re.finditer(r"CUSIP", text, re.IGNORECASE):
        segment = text[marker.end():marker.end() + 120].upper()
        for match in re.finditer(r"\b([0-9A-Z]{6})[\s-]*([0-9A-Z]{3})\b", segment):
            value = match.group(1) + match.group(2)
            if sum(character.isdigit() for character in value) < 2:
                continue
            if value not in values:
                values.append(value)
    return values


def _ownership_filing_basis(text, form):
    if form.startswith(("SC 13D", "SCHEDULE 13D")):
        return "主動型／可能影響控制"
    rules = (
        (r"(?:\[\s*[Xx]\s*\]|☒)\s*Rule\s+13d-[1l]\s*\(b\)", "合格機構投資人"),
        (r"(?:\[\s*[Xx]\s*\]|☒)\s*Rule\s+13d-[1l]\s*\(c\)", "被動投資人"),
        (r"(?:\[\s*[Xx]\s*\]|☒)\s*Rule\s+13d-[1l]\s*\(d\)", "豁免投資人"),
    )
    for pattern, label in rules:
        if re.search(pattern, text, re.IGNORECASE):
            return label
    return "13G 簡式申報（細分類未辨識）"


def _xml_tag(block, tag):
    match = re.search(rf"<{tag}(?:\s[^>]*)?>(.*?)</{tag}>", block, re.IGNORECASE | re.DOTALL)
    return html_text(match.group(1)) if match else ""


def _xml_number(block, tag, integer=False):
    value = _xml_tag(block, tag).replace(",", "").replace("%", "").strip()
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        return None
    return int(float(value)) if integer else float(value)


def parse_structured_13dg(raw, form):
    """Parse the XML Schedule 13D/G schema introduced by the SEC in late 2024."""
    source = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    positions = []
    for block in re.findall(
        r"<coverPageHeaderReportingPersonDetails(?:\s[^>]*)?>(.*?)</coverPageHeaderReportingPersonDetails>",
        source,
        re.IGNORECASE | re.DOTALL,
    ):
        position = {
            "reporting_person": _xml_tag(block, "reportingPersonName") or "申報人未辨識",
            "aggregate_shares": _xml_number(block, "reportingPersonBeneficiallyOwnedAggregateNumberOfShares", integer=True),
            "percent_of_class": _xml_number(block, "classPercent"),
            "sole_voting_power": _xml_number(block, "soleVotingPower", integer=True),
            "shared_voting_power": _xml_number(block, "sharedVotingPower", integer=True),
            "sole_dispositive_power": _xml_number(block, "soleDispositivePower", integer=True),
            "shared_dispositive_power": _xml_number(block, "sharedDispositivePower", integer=True),
            "comments": _xml_tag(block, "comments"),
        }
        if position["aggregate_shares"] is not None or position["percent_of_class"] is not None:
            positions.append(position)
    # Structured Schedule 13D uses reportingPersons/reportingPersonInfo and
    # different field names from the structured Schedule 13G cover page.
    if not positions:
        for block in re.findall(
            r"<reportingPersonInfo(?:\s[^>]*)?>(.*?)</reportingPersonInfo>",
            source,
            re.IGNORECASE | re.DOTALL,
        ):
            position = {
                "reporting_person": _xml_tag(block, "reportingPersonName") or "申報人未辨識",
                "aggregate_shares": _xml_number(block, "aggregateAmountOwned", integer=True),
                "percent_of_class": _xml_number(block, "percentOfClass"),
                "sole_voting_power": _xml_number(block, "soleVotingPower", integer=True),
                "shared_voting_power": _xml_number(block, "sharedVotingPower", integer=True),
                "sole_dispositive_power": _xml_number(block, "soleDispositivePower", integer=True),
                "shared_dispositive_power": _xml_number(block, "sharedDispositivePower", integer=True),
                "comments": _xml_tag(block, "commentContent"),
            }
            if position["aggregate_shares"] is not None or position["percent_of_class"] is not None:
                positions.append(position)
    if not positions and "<item4>" in source:
        block = re.search(r"<item4>(.*?)</item4>", source, re.IGNORECASE | re.DOTALL).group(1)
        positions.append({
            "reporting_person": _xml_tag(source, "filingPersonName") or "申報群組",
            "aggregate_shares": _xml_number(block, "amountBeneficiallyOwned", integer=True),
            "percent_of_class": _xml_number(block, "classPercent"),
            "sole_voting_power": _xml_number(block, "solePowerOrDirectToVote", integer=True),
            "shared_voting_power": _xml_number(block, "sharedPowerOrDirectToVote", integer=True),
            "sole_dispositive_power": _xml_number(block, "solePowerOrDirectToDispose", integer=True),
            "shared_dispositive_power": _xml_number(block, "sharedPowerOrDirectToDispose", integer=True),
        })
    representative = max(
        positions,
        key=lambda item: (item.get("percent_of_class") if item.get("percent_of_class") is not None else -1,
                          item.get("aggregate_shares") if item.get("aggregate_shares") is not None else -1),
        default={},
    )
    rule = _xml_tag(source, "designateRulePursuantThisScheduleFiled")
    basis = "主動型／可能影響控制" if form.startswith("SCHEDULE 13D") else {
        "Rule 13d-1(b)": "合格機構投資人",
        "Rule 13d-1(c)": "被動投資人",
        "Rule 13d-1(d)": "豁免投資人",
    }.get(rule, "13G 簡式申報（細分類未辨識）")
    purpose = (_xml_tag(source, "transactionPurpose") or _xml_tag(source, "purposeOfTransaction")
               or _xml_tag(source, "purposeOfTransactions"))
    threshold_exit = bool(re.search(
        r"<classOwnership5PercentOrLess>\s*Y\s*</classOwnership5PercentOrLess>", source, re.IGNORECASE
    ))
    date_below_5 = _xml_tag(source, "date5PercentOwnership")
    if date_below_5 and not re.search(r"^(?:not applicable|n/?a|none)\.?$", date_below_5, re.IGNORECASE):
        threshold_exit = True
    cusips = []
    for value in re.findall(r"<issuerCusip(?:Number)?>(.*?)</issuerCusip(?:Number)?>", source, re.IGNORECASE | re.DOTALL):
        value = re.sub(r"[^0-9A-Z]", "", html_text(value).upper())
        if value and value not in cusips:
            cusips.append(value)
    return {
        "schema_version": 4 if form.startswith("SCHEDULE 13D") else 3,
        "event_date": _xml_tag(source, "eventDateRequiresFilingThisStatement"),
        "cusip": cusips[0] if cusips else "",
        "cusips": cusips,
        "filing_basis": basis,
        "aggregate_shares": representative.get("aggregate_shares"),
        "percent_of_class": representative.get("percent_of_class"),
        "sole_voting_power": representative.get("sole_voting_power"),
        "shared_voting_power": representative.get("shared_voting_power"),
        "sole_dispositive_power": representative.get("sole_dispositive_power"),
        "shared_dispositive_power": representative.get("shared_dispositive_power"),
        "positions": positions,
        "threshold_exit": threshold_exit,
        "purpose_excerpt": purpose[:900],
        "filing_comment": representative.get("comments", ""),
        "data_status": "parsed" if representative else ("threshold_exit" if threshold_exit else "unavailable"),
    }


def parse_13dg_ownership(raw, form=""):
    """Extract verifiable beneficial-ownership facts from a Schedule 13D/G filing."""
    source = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    if re.search(r"<submissionType>SCHEDULE\s+13[DG]", source, re.IGNORECASE):
        return parse_structured_13dg(raw, form)
    text = html_text(raw)
    positions = []
    reporter_labels = list(re.finditer(r"NAMES?\s+OF\s+REPORTING\s+PERSONS?\.?", text, re.IGNORECASE))
    for index, label in enumerate(reporter_labels):
        end = reporter_labels[index + 1].start() if index + 1 < len(reporter_labels) else len(text)
        block = text[label.start():end]
        name_tail = block[label.end() - label.start():]
        name_match = re.match(
            r"\s*(.*?)(?=(?:\(\s*2\s*\)|\b2)\s*CHECK\s+THE\s+APPROPRIATE\s+BOX)",
            name_tail,
            re.IGNORECASE,
        )
        name = re.sub(r"\s+", " ", name_match.group(1)).strip(" .;:-") if name_match else ""
        name = re.split(r"\bI\.?R\.?S\.?\s+(?:IDENTIFICATION|ID)", name, flags=re.IGNORECASE)[0].strip()
        position = {
            "reporting_person": name or "申報人未辨識",
            "aggregate_shares": _ownership_number(block, r"AGGREGATE\s+AMOUNT\s+BENEFICIALLY\s+OWNED\s+BY\s+EACH\s+REPORTING\s+PERSON"),
            "percent_of_class": _ownership_number(block, r"PERCENT\s+OF\s+CLASS\s+REPRESENTED\s+BY\s+AMOUNT\s+IN\s+ROW(?:\s*\(?\d+\)?)?", percent=True),
            "sole_voting_power": _ownership_number(block, r"SOLE\s+(?:POWER\s+TO\s+VOTE(?:\s+OR\s+TO\s+DIRECT\s+THE\s+VOTE)?|VOTING\s+POWER)"),
            "shared_voting_power": _ownership_number(block, r"SHARED\s+(?:POWER\s+TO\s+VOTE(?:\s+OR\s+TO\s+DIRECT\s+THE\s+VOTE)?|VOTING\s+POWER)"),
            "sole_dispositive_power": _ownership_number(block, r"SOLE\s+(?:POWER\s+TO\s+DISPOSE(?:\s+OR\s+TO\s+DIRECT\s+THE\s+DISPOSITION\s+OF)?|DISPOSITIVE\s+POWER)"),
            "shared_dispositive_power": _ownership_number(block, r"SHARED\s+(?:POWER\s+TO\s+DISPOSE(?:\s+OR\s+TO\s+DIRECT\s+THE\s+DISPOSITION\s+OF)?|DISPOSITIVE\s+POWER)"),
        }
        if position["aggregate_shares"] is not None or position["percent_of_class"] is not None:
            positions.append(position)

    # Some institutional 13G filings disclose the same facts only in Item 4.
    if not positions:
        item_match = re.search(r"Item\s+4\.?\s+Ownership\s+(.*?)(?=Item\s+5\.)", text, re.IGNORECASE)
        block = item_match.group(1) if item_match else text
        position = {
            "reporting_person": "申報群組",
            "aggregate_shares": _ownership_number(block, r"Amount\s+beneficially\s+owned"),
            "percent_of_class": _ownership_number(block, r"Percent\s+of\s+class", percent=True),
            "sole_voting_power": _ownership_number(block, r"Sole\s+power\s+to\s+vote(?:\s+or\s+to\s+direct\s+the\s+vote)?"),
            "shared_voting_power": _ownership_number(block, r"Shared\s+power\s+to\s+vote(?:\s+or\s+to\s+direct\s+the\s+vote)?"),
            "sole_dispositive_power": _ownership_number(block, r"Sole\s+power\s+to\s+dispose(?:\s+or\s+to\s+direct\s+the\s+disposition\s+of)?"),
            "shared_dispositive_power": _ownership_number(block, r"Shared\s+power\s+to\s+dispose(?:\s+or\s+to\s+direct\s+the\s+disposition\s+of)?"),
        }
        if position["aggregate_shares"] is not None or position["percent_of_class"] is not None:
            positions.append(position)

    representative = max(
        positions,
        key=lambda item: (item.get("percent_of_class") or -1, item.get("aggregate_shares") or -1),
        default={},
    )
    purpose_match = re.search(
        r"Item\s+4\.?\s+Purpose\s+of\s+(?:the\s+)?Transaction\.?\s+(.*?)(?=Item\s+5\.)",
        text,
        re.IGNORECASE,
    )
    purpose = re.sub(r"\s+", " ", purpose_match.group(1)).strip() if purpose_match else ""
    if len(purpose) > 900:
        purpose = purpose[:900].rsplit(" ", 1)[0] + "…"
    threshold_exit = bool(re.search(
        r"Item\s+5\.?\s+Ownership\s+of\s+(?:Five|5)\s+Percent\s+or\s+Less.*?(?:\[\s*[Xx]\s*\]|☒)",
        text,
        re.IGNORECASE,
    ))
    cusips = _ownership_cusips(text)
    return {
        "schema_version": 3,
        "event_date": _ownership_event_date(text),
        "cusip": cusips[0] if cusips else "",
        "cusips": cusips,
        "filing_basis": _ownership_filing_basis(text, form),
        "aggregate_shares": representative.get("aggregate_shares"),
        "percent_of_class": representative.get("percent_of_class"),
        "sole_voting_power": representative.get("sole_voting_power"),
        "shared_voting_power": representative.get("shared_voting_power"),
        "sole_dispositive_power": representative.get("sole_dispositive_power"),
        "shared_dispositive_power": representative.get("shared_dispositive_power"),
        "positions": positions,
        "threshold_exit": threshold_exit,
        "purpose_excerpt": purpose,
        "data_status": "parsed" if representative else ("threshold_exit" if threshold_exit else "unavailable"),
    }


def add_ownership_changes(rows):
    """Compare amendments only with the same issuer and reporting filer."""
    previous = {}
    for row in sorted(rows, key=lambda item: (item.get("filing_date", ""), item.get("accession", ""))):
        reporters = "|".join(row.get("reporting_persons", []))
        cik = re.search(r"CIK\s+(\d+)", reporters, re.IGNORECASE)
        facts = row.get("ownership", {})
        facts.pop("change_from_prior", None)
        security_key = tuple(facts.get("cusips", [])) or (facts.get("cusip", ""),)
        key = (row.get("ticker", ""), cik.group(1) if cik else reporters.lower(), security_key)
        prior = previous.get(key)
        if prior and facts.get("data_status") == "parsed" and prior["facts"].get("data_status") == "parsed":
            shares = facts.get("aggregate_shares")
            prior_shares = prior["facts"].get("aggregate_shares")
            percent = facts.get("percent_of_class")
            prior_percent = prior["facts"].get("percent_of_class")
            share_change = shares - prior_shares if shares is not None and prior_shares is not None else None
            point_change = percent - prior_percent if percent is not None and prior_percent is not None else None
            share_ratio = shares / prior_shares if shares is not None and prior_shares not in (None, 0) else None
            internal_realignment = "internal realignment" in facts.get("filing_comment", "").lower()
            threshold_zero = facts.get("threshold_exit") and shares == 0
            shares_comparable = not (threshold_zero or (share_ratio is not None and (share_ratio >= 4 or share_ratio <= 0.25)))
            if internal_realignment:
                comparison_note = "申報人註明內部重整後改由相關實體分開申報；0 股不等於整個機構集團清倉"
            elif threshold_zero:
                comparison_note = "本申報顯示降至 5% 以下且持股為 0；請由原文確認是否涉及申報主體調整"
            elif not shares_comparable:
                comparison_note = "股數疑受拆股／併股影響，方向以持股比例判讀"
            elif facts.get("threshold_exit"):
                comparison_note = "本申報已降至 5% 申報門檻以下"
            else:
                comparison_note = ""
            signal = point_change if point_change is not None else share_change
            facts["change_from_prior"] = {
                "previous_filing_date": prior["date"],
                "shares": share_change,
                "percentage_points": round(point_change, 4) if point_change is not None else None,
                "direction": "增加" if signal is not None and signal > 0 else ("減少" if signal is not None and signal < 0 else "持平"),
                "shares_comparable": shares_comparable,
                "comparison_note": comparison_note,
            }
        if facts.get("data_status") in {"parsed", "threshold_exit"}:
            previous[key] = {"date": row.get("filing_date", ""), "facts": facts}
    return rows


def ownership_group_key(row):
    reporters = "|".join(row.get("reporting_persons", []))
    cik = re.search(r"CIK\s+(\d+)", reporters, re.IGNORECASE)
    facts = row.get("ownership", {})
    security_key = tuple(facts.get("cusips", [])) or (facts.get("cusip", ""),)
    return row.get("ticker", ""), cik.group(1) if cik else reporters.lower(), security_key


def build_ownership_snapshot(rows):
    """Collapse filing history to the latest known state per issuer, filer and CUSIP."""
    groups = {}
    for row in rows:
        groups.setdefault(ownership_group_key(row), []).append(row)
    snapshot = []
    for (ticker, owner_key, security_key), history in groups.items():
        history = sorted(
            history,
            key=lambda item: (item.get("filing_date", ""), item.get("accession", "")),
            reverse=True,
        )
        latest = history[0]
        facts = latest.get("ownership", {})
        shares = facts.get("aggregate_shares")
        percent = facts.get("percent_of_class")
        comment = facts.get("filing_comment", "")
        if shares == 0 and "internal realignment" in comment.lower():
            status = "realignment"
            status_label = "申報主體重整"
        elif facts.get("threshold_exit") or (percent is not None and percent < 5):
            status = "exit"
            status_label = "已降至 5% 以下"
        elif percent is not None and percent >= 5:
            status = "above_5"
            status_label = "最新申報仍 ≥5%"
        else:
            status = "unknown"
            status_label = "狀態待確認"
        compact_history = []
        for item in history:
            item_facts = item.get("ownership", {})
            compact_history.append({
                "filing_date": item.get("filing_date", ""),
                "event_date": item_facts.get("event_date", ""),
                "form": item.get("form", ""),
                "accession": item.get("accession", ""),
                "aggregate_shares": item_facts.get("aggregate_shares"),
                "percent_of_class": item_facts.get("percent_of_class"),
                "threshold_exit": item_facts.get("threshold_exit", False),
                "url": item.get("url", ""),
            })
        snapshot.append({
            "ticker": ticker,
            "owner_key": owner_key,
            "reporting_persons": latest.get("reporting_persons", []),
            "cusips": list(security_key) if any(security_key) else [],
            "latest_filing_date": latest.get("filing_date", ""),
            "event_date": facts.get("event_date", ""),
            "form": latest.get("form", ""),
            "accession": latest.get("accession", ""),
            "url": latest.get("url", ""),
            "filing_basis": facts.get("filing_basis", ""),
            "aggregate_shares": shares,
            "percent_of_class": percent,
            "sole_voting_power": facts.get("sole_voting_power"),
            "shared_voting_power": facts.get("shared_voting_power"),
            "change_from_prior": facts.get("change_from_prior"),
            "purpose_excerpt": facts.get("purpose_excerpt", ""),
            "filing_comment": comment,
            "status": status,
            "status_label": status_label,
            "active_13d": "13D" in latest.get("form", ""),
            "history_count": len(compact_history),
            "history": compact_history,
        })
    status_order = {"above_5": 0, "realignment": 1, "exit": 2, "unknown": 3}
    return sorted(
        snapshot,
        key=lambda item: (
            status_order[item["status"]],
            -(item["percent_of_class"] if item["percent_of_class"] is not None else -1),
            item["ticker"], item["owner_key"], item["cusips"],
        ),
    )


def ownership_form_family(form):
    """Return the economic filing family while ignoring SEC naming variants."""
    form = (form or "").upper()
    if "13D" in form:
        return "13D"
    if "13G" in form:
        return "13G"
    return ""


def classify_ownership_event(row, prior=None):
    """Turn one filing and its same-owner predecessor into a readable alert."""
    facts = row.get("ownership", {})
    prior_facts = prior.get("ownership", {}) if prior else {}
    form = row.get("form", "")
    family = ownership_form_family(form)
    prior_family = ownership_form_family(prior.get("form", "")) if prior else ""
    percent = facts.get("percent_of_class")
    prior_percent = prior_facts.get("percent_of_class")
    shares = facts.get("aggregate_shares")
    prior_shares = prior_facts.get("aggregate_shares")
    point_change = percent - prior_percent if percent is not None and prior_percent is not None else None
    share_change = shares - prior_shares if shares is not None and prior_shares is not None else None
    change = facts.get("change_from_prior") or {}
    shares_comparable = change.get("shares_comparable", True)
    comparison_note = change.get("comparison_note", "")
    share_change_ratio = (
        share_change / prior_shares
        if shares_comparable and share_change is not None and prior_shares not in (None, 0)
        else None
    )
    internal_realignment = "internal realignment" in facts.get("filing_comment", "").lower()
    crossed_below = bool(facts.get("threshold_exit")) or (
        prior_percent is not None and prior_percent >= 5 and percent is not None and percent < 5
    )
    crossed_above = (
        prior_percent is not None and prior_percent < 5 and percent is not None and percent >= 5
    )
    initial_form = "/A" not in form.upper() and "AMEND" not in form.upper()

    if internal_realignment:
        event_type, event_label, importance = "realignment", "申報主體重整", "watch"
        interpretation = "申報人註明內部重整或拆分申報主體；0 股不可直接解讀為整個機構集團清倉。"
    elif prior and prior_family == "13G" and family == "13D":
        event_type, event_label, importance = "active_transition", "13G→13D 主動介入", "high"
        interpretation = "申報性質由被動／豁免型轉為 13D；應優先閱讀 Item 4 是否涉及董事會、資本配置或控制權。"
    elif crossed_below:
        event_type, event_label, importance = "threshold_exit", "降至 5% 以下", "high"
        interpretation = "最新申報已低於 5% 門檻；這不一定代表完全清倉，也不應把申報主體調整當成賣出。"
    elif crossed_above:
        event_type, event_label, importance = "threshold_entry", "升破 5% 門檻", "high"
        interpretation = "持股比例由門檻下升至至少 5%，成為需揭露的受益所有權人；不代表全部持股都在本期買入。"
    elif family == "13D":
        event_type, event_label, importance = "active_13d", "13D 主動型申報", "high"
        interpretation = "這是可能影響公司控制、治理或策略的主動型申報；需搭配 Item 4 原文判讀具體目的。"
    elif prior is None and initial_form and percent is not None and percent >= 5:
        event_type, event_label, importance = "new_threshold", "新進／首次達門檻", "high"
        interpretation = "這是觀察窗內首份非修正版且持股至少 5% 的申報；不表示全部持股都在申報日前才買入。"
    elif prior is None:
        event_type, event_label, importance = "first_observed", "觀察窗首筆", "routine"
        interpretation = "缺少同申報人與同 CUSIP 的更早可比文件，只能視為觀察窗首筆，不能推論新進或增減持。"
    elif point_change is not None and abs(point_change) >= 2:
        direction = "增加" if point_change > 0 else "減少"
        event_type, event_label, importance = f"major_{'increase' if point_change > 0 else 'decrease'}", f"持股比例大幅{direction}", "high"
        interpretation = "持股比例變動至少 2 個百分點，列為重大閱讀事件；比例也可能受公司流通股數變動影響。"
    elif point_change is not None and abs(point_change) >= 0.5:
        direction = "增加" if point_change > 0 else "減少"
        event_type, event_label, importance = f"{'increase' if point_change > 0 else 'decrease'}", f"持股比例{direction}", "watch"
        interpretation = "持股比例變動 0.5 至 2 個百分點，值得留意；不能僅憑比例變化斷定實際買入或賣出。"
    elif point_change not in (None, 0):
        direction = "增加" if point_change > 0 else "減少"
        event_type, event_label, importance = f"small_{'increase' if point_change > 0 else 'decrease'}", f"持股比例小幅{direction}", "routine"
        interpretation = "持股比例變動小於 0.5 個百分點，屬例行追蹤；仍可能同時受到分母變化影響。"
    elif share_change_ratio is not None and abs(share_change_ratio) >= 0.25:
        direction = "增加" if share_change_ratio > 0 else "減少"
        event_type, event_label, importance = f"major_share_{'increase' if share_change_ratio > 0 else 'decrease'}", f"可比股數大幅{direction}", "high"
        interpretation = "可比持股數變動至少 25%，但缺少可靠持股比例比較；應開啟原文核對交易與股本變化。"
    elif share_change_ratio is not None and abs(share_change_ratio) >= 0.1:
        direction = "增加" if share_change_ratio > 0 else "減少"
        event_type, event_label, importance = f"share_{'increase' if share_change_ratio > 0 else 'decrease'}", f"可比股數{direction}", "watch"
        interpretation = "可比持股數變動 10% 至 25%，但缺少可靠持股比例比較；需搭配公司股本變化判讀。"
    elif not shares_comparable:
        event_type, event_label, importance = "not_comparable", "股數尺度不可比", "watch"
        interpretation = comparison_note or "股數可能受拆股、併股或申報主體變化影響，方向應以持股比例與原文為準。"
    else:
        event_type, event_label, importance = "stable", "持股大致持平", "routine"
        interpretation = "相較前次沒有達到警示門檻的變動，列為例行追蹤；不代表申報日至今持倉未變。"

    return {
        "event_type": event_type,
        "event_label": event_label,
        "importance": importance,
        "importance_label": {"high": "🔴 重大", "watch": "🟡 留意", "routine": "🟢 一般"}[importance],
        "previous_filing_date": prior.get("filing_date", "") if prior else "",
        "share_change": share_change,
        "percentage_points": round(point_change, 4) if point_change is not None else None,
        "shares_comparable": shares_comparable,
        "comparison_note": comparison_note,
        "interpretation": interpretation,
    }


def build_ownership_timeline(rows):
    """Build newest-first, same-owner 13D/G changes for dashboard alerts."""
    groups = {}
    for row in rows:
        groups.setdefault(ownership_group_key(row), []).append(row)
    timeline = []
    for (ticker, owner_key, security_key), history in groups.items():
        history = sorted(history, key=lambda item: (item.get("filing_date", ""), item.get("accession", "")))
        prior = None
        for row in history:
            facts = row.get("ownership", {})
            event = classify_ownership_event(row, prior)
            timeline.append({
                "ticker": ticker,
                "owner_key": owner_key,
                "reporting_persons": row.get("reporting_persons", []),
                "cusips": list(security_key) if any(security_key) else [],
                "filing_date": row.get("filing_date", ""),
                "event_date": facts.get("event_date", ""),
                "form": row.get("form", ""),
                "accession": row.get("accession", ""),
                "url": row.get("url", ""),
                "aggregate_shares": facts.get("aggregate_shares"),
                "percent_of_class": facts.get("percent_of_class"),
                **event,
            })
            if facts.get("data_status") in {"parsed", "threshold_exit"}:
                prior = row
    rank = {"high": 0, "watch": 1, "routine": 2}
    return sorted(
        timeline,
        key=lambda item: (item["filing_date"], -rank[item["importance"]], item["ticker"], item["owner_key"]),
        reverse=True,
    )


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


def merger_content_excerpt(raw, limit=720):
    """Return a verifiable deal passage instead of only describing the form type."""
    text = html_text(raw)
    patterns = (
        r"(?:entered into|executed|announced).{0,180}(?:agreement and plan of merger|merger agreement|business combination agreement)",
        r"(?:agreement and plan of merger|business combination agreement).{0,260}(?:acquisition|merger|transaction)",
        r"(?:item 4\.?\s+terms of the transaction).{0,520}",
        r"(?:offer to purchase).{0,360}(?:shares|securities|company)",
        r"(?:proposed transaction).{0,160}(?:between|with).{0,260}",
        r"(?:proposed merger|proposed acquisition|proposed transaction).{0,300}",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        start = max(0, match.start() - 240)
        end = min(len(text), match.end() + 480)
        excerpt = text[start:end].strip()
        if len(excerpt) > limit:
            excerpt = excerpt[:limit].rsplit(" ", 1)[0] + "…"
        return excerpt
    return ""


def merger_cutoff(checked_at, years=MERGER_WINDOW_YEARS):
    """Return an exact calendar-year cutoff, including the cutoff date."""
    as_of = datetime.fromisoformat(str(checked_at).replace("Z", "+00:00")).date()
    try:
        return as_of.replace(year=as_of.year - years)
    except ValueError:  # Feb. 29 -> Feb. 28
        return as_of.replace(year=as_of.year - years, day=28)


def merger_form_class(form):
    if form in MA_REGISTRATION_FORMS:
        return "合併／交換要約註冊"
    if form in MA_COMMUNICATION_FORMS:
        return "交易溝通"
    if form in MA_TENDER_FORMS:
        return "公開收購"
    if form in MA_GOING_PRIVATE_FORMS:
        return "私有化"
    return "其他交易文件"


def merger_document_relevant(row):
    """S-4/F-4 also cover debt exchanges; require deal language for those forms."""
    event = row.get("event", {})
    form = event.get("form", "")
    if form in MA_COMMUNICATION_FORMS | MA_TENDER_FORMS | MA_GOING_PRIVATE_FORMS:
        return True
    if form not in MA_REGISTRATION_FORMS:
        return False
    excerpt = row.get("content_excerpt", "").lower()
    strong_deal_phrases = (
        "agreement and plan of merger", "merger agreement", "business combination agreement",
        "acquisition of", "to acquire", "company being acquired", "cash and stock transaction",
        "merge with and into", "proposed acquisition",
    )
    return any(phrase in excerpt for phrase in strong_deal_phrases)


def _clean_party(value):
    value = re.sub(r"\s+", " ", value or "").strip(" ,.;:()")
    value = re.sub(r"^(?:the|a|an)\s+", "", value, flags=re.IGNORECASE)
    return value[:90]


def _party_slug(value):
    return re.sub(r"[^a-z0-9]+", "-", (value or "unknown").lower()).strip("-")[:55]


def _tracked_brand(ticker, companies):
    entity = companies.get(ticker, {}).get("name", ticker)
    return _clean_party(re.split(r"\s+", entity)[0].title())


def extract_merger_parties(row, companies):
    """Extract the tracked-side acquirer and counterparty from a verified excerpt."""
    event = row.get("event", {})
    ticker = event.get("ticker", "")
    text = row.get("content_excerpt", "")
    if not text:
        return None

    match = re.search(
        r"acquisition of\s+([A-Z][A-Za-z0-9&.' -]{1,80}?)\s+by\s+([A-Z][A-Za-z0-9&.' -]{1,80}?)(?=\s*(?:under|pursuant|subject|according|[,(.;]))",
        text,
    )
    if match:
        target = _clean_party(match.group(1))
        acquirer = _clean_party(match.group(2))
        brand = _tracked_brand(ticker, companies)
        if brand.lower() in acquirer.lower():
            acquirer = brand
        return {"target": target, "acquirer": acquirer}

    company_to_acquire = re.search(
        r"(?:the Company|[A-Z][A-Za-z0-9&.' -]{1,60})\s+to acquire\s+([A-Z][A-Za-z0-9&.' -]{1,80}?)(?=\s*(?:on|under|pursuant|,|\.))",
        text,
    )
    if company_to_acquire:
        return {"target": _clean_party(company_to_acquire.group(1)),
                "acquirer": _tracked_brand(ticker, companies)}

    aliases = []
    for legal_name, alias in re.findall(
        r"([A-Za-z][A-Za-z0-9&.,' -]{1,90}?)\s*\([“\"]([^”\"]{2,45})[”\"]\)", text
    ):
        alias = _clean_party(alias)
        if re.search(r"agreement|company|merger|transaction|surviving|sub\b", alias, re.IGNORECASE):
            continue
        aliases.append((alias, _clean_party(legal_name)))
    brand = _tracked_brand(ticker, companies)
    tracked = next((pair for pair in aliases if brand.lower() in pair[0].lower()
                    or brand.lower() in pair[1].lower()), None)
    other = next((pair for pair in aliases if pair != tracked), None)
    if tracked and other:
        tracked_name = tracked[0]
        other_name = other[0]
        tracked_pattern = re.escape(tracked_name)
        other_pattern = re.escape(other_name)
        tracked_is_target = bool(re.search(
            rf"(?:acquisition of|acquire)\s+{tracked_pattern}\b|"
            rf"{tracked_pattern}.{{0,100}}(?:acquisition by|acquired by|to be acquired by)\s+{other_pattern}\b|"
            rf"{other_pattern}.{{0,100}}(?:will acquire|to acquire)\s+{tracked_pattern}\b",
            text, re.IGNORECASE,
        ))
        if tracked_is_target:
            return {"target": tracked_name, "acquirer": other_name}
        return {"target": other_name, "acquirer": tracked_name}
    return None


def merger_procedural_status(latest_document):
    """Describe only the last visible SEC procedure, not the deal's current outcome."""
    event = latest_document.get("event", {})
    form = event.get("form", "")
    text = (latest_document.get("content_excerpt") or "").lower()
    if re.search(r"(?:transaction|merger|acquisition).{0,80}(?:terminated|cancelled|abandoned)", text):
        return "文件顯示交易已終止"
    if re.search(r"(?:transaction|merger|acquisition).{0,80}(?:completed|consummated|closed)", text):
        return "文件顯示交易已完成"
    if form.endswith("/A") and form in MA_REGISTRATION_FORMS:
        return "合併註冊文件已修訂"
    if form in MA_REGISTRATION_FORMS:
        return "合併註冊文件已提交"
    if form in MA_TENDER_FORMS:
        return "公開收購程序更新"
    if form in MA_GOING_PRIVATE_FORMS:
        return "私有化程序更新"
    return "交易溝通／進度更新"


def build_merger_deals(rows, companies, checked_at, years=MERGER_WINDOW_YEARS):
    cutoff = merger_cutoff(checked_at, years)
    relevant = [
        dict(row, document_class=merger_form_class(row.get("event", {}).get("form", "")))
        for row in rows
        if row.get("event", {}).get("filing_date", "") >= cutoff.isoformat()
        and merger_document_relevant(row)
    ]
    relevant.sort(key=lambda row: (row["event"].get("filing_date", ""),
                                   row["event"].get("accepted_at", "")))

    groups = {}
    unresolved = []
    for row in relevant:
        parties = extract_merger_parties(row, companies)
        if not parties:
            unresolved.append(row)
            continue
        ticker = row["event"]["ticker"]
        key = f"{ticker}:{_party_slug(parties['acquirer'])}:{_party_slug(parties['target'])}"
        group = groups.setdefault(key, {"ticker": ticker, "parties": parties, "rows": []})
        group["rows"].append(row)

    # Communications may omit the parties. Attach them only when one nearby,
    # already-verified deal for the same ticker makes the match unambiguous.
    for row in unresolved:
        filing_date = datetime.fromisoformat(row["event"]["filing_date"]).date()
        candidates = []
        for key, group in groups.items():
            if group["ticker"] != row["event"]["ticker"]:
                continue
            distances = [abs((filing_date - datetime.fromisoformat(item["event"]["filing_date"]).date()).days)
                         for item in group["rows"]]
            if distances and min(distances) <= 180:
                candidates.append((min(distances), key))
        if len(candidates) == 1:
            groups[candidates[0][1]]["rows"].append(row)
        else:
            ticker = row["event"]["ticker"]
            key = f"{ticker}:unresolved:{row['event']['accession']}"
            groups[key] = {"ticker": ticker, "parties": None, "rows": [row]}

    deals = []
    for deal_id, group in groups.items():
        documents = sorted(group["rows"], key=lambda row: (
            row["event"].get("filing_date", ""), row["event"].get("accepted_at", "")))
        latest = documents[-1]
        parties = group["parties"]
        forms = list(dict.fromkeys(row["event"].get("form", "") for row in documents))
        excerpts = [row.get("content_excerpt", "") for row in reversed(documents)
                    if row.get("content_excerpt")]
        deals.append({
            "deal_id": deal_id,
            "ticker": group["ticker"],
            "deal_name": (f"{parties['acquirer']} 收購 {parties['target']}"
                          if parties else f"{group['ticker']} 待確認交易"),
            "acquirer": parties["acquirer"] if parties else None,
            "target": parties["target"] if parties else None,
            "first_filing_date": documents[0]["event"].get("filing_date"),
            "latest_filing_date": latest["event"].get("filing_date"),
            "last_procedural_status": merger_procedural_status(latest),
            "document_count": len(documents),
            "verified_excerpt_count": sum(bool(row.get("content_excerpt")) for row in documents),
            "forms": forms,
            "latest_excerpt": excerpts[0] if excerpts else "",
            "latest_url": latest["event"].get("url"),
            "documents": [{
                "filing_date": row["event"].get("filing_date"),
                "form": row["event"].get("form"),
                "accession": row["event"].get("accession"),
                "document_class": row.get("document_class"),
                "content_excerpt": row.get("content_excerpt", ""),
                "url": row["event"].get("url"),
            } for row in reversed(documents)],
        })
    deals.sort(key=lambda deal: deal["latest_filing_date"], reverse=True)
    relevant.sort(key=lambda row: row["event"].get("filing_date", ""), reverse=True)
    return relevant, deals, {
        "years": years,
        "cutoff": cutoff.isoformat(),
        "as_of": str(checked_at)[:10],
        "document_count": len(relevant),
        "deal_count": len(deals),
    }


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


def enrich_merger_event(event):
    raw = fetch(event["url"], "text/html,application/xhtml+xml", max_bytes=600_000)
    return {
        "event": event,
        "signals": [],
        "attachments": [],
        "metrics": {},
        "content_excerpt": merger_content_excerpt(raw),
    }


def search_13dg(ticker, company, years=3):
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=365 * years + 1)
    query = {
        "q": company["name"],
        "forms": ",".join(sorted(OWNERSHIP_FORMS)),
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
        if source.get("sequence") != 1 or source.get("form") not in OWNERSHIP_FORMS:
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
            "meaning": FORM_MEANINGS["SC 13D" if "13D" in source.get("form", "") else "SC 13G"],
            "url": f"https://www.sec.gov/Archives/edgar/data/{int(company['cik'])}/{clean}/{accession}-index.html",
        }
    return list(rows.values())


def search_13dg_with_retry(ticker, company, years=3, attempts=3):
    """Retry transient EFTS failures without silently returning an empty company."""
    last_error = None
    for attempt in range(attempts):
        try:
            return search_13dg(ticker, company, years)
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.75 * (attempt + 1))
    raise last_error


def enrich_ownership_rows(rows, previous_rows=None, errors=None):
    """Attach immutable filing facts, reusing already parsed accessions."""
    errors = errors if errors is not None else []
    cached = {
        row.get("accession"): row.get("ownership")
        for row in (previous_rows or [])
        if (row.get("accession")
            and row.get("ownership", {}).get("schema_version") >= (4 if row.get("form", "").startswith("SCHEDULE 13D") else 3)
            and row.get("ownership", {}).get("data_status") in {"parsed", "threshold_exit"})
    }
    for row in rows:
        if cached.get(row.get("accession")):
            row["ownership"] = cached[row["accession"]]
            continue
        try:
            raw_url = row["url"].replace("-index.html", ".txt")
            row["ownership"] = parse_13dg_ownership(fetch(raw_url, max_bytes=2_500_000), row.get("form", ""))
            time.sleep(0.11)
        except Exception as exc:
            row["ownership"] = {"data_status": "unavailable", "positions": []}
            errors.append(f"13D/G facts {row.get('accession', '—')}: {type(exc).__name__}: {exc}")
    return add_ownership_changes(rows)


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


def render_ownership_note(rows, checked_at, snapshot=None, timeline=None):
    snapshot = snapshot if snapshot is not None else build_ownership_snapshot(rows)
    timeline = timeline if timeline is not None else build_ownership_timeline(rows)
    lines = ["---", "title: 13D／13G 大股東雷達", f"updated_at: {checked_at}", "tags:", "  - sec/ownership", "---", "", "# 🐘 13D／13G 大股東雷達", "",
             "由 SEC EDGAR 全文索引搜尋發行人，並直接解析申報原文的受益持股數與持股比例。", "",
             "## 最新狀態總覽", "",
             "每列只保留同公司、同申報 CIK、同 CUSIP 的最新文件；這是『最新已知申報狀態』，不是即時持倉。", "",
             "| 公司 | 最新申報人 | CUSIP | 最新持股 | 狀態 | 性質 | 申報日 | 歷史 |",
             "|---|---|---|---|---|---|---|---|"]
    for item in snapshot:
        shares = item.get("aggregate_shares")
        percent = item.get("percent_of_class")
        holding = "／".join(part for part in (
            f"{shares:,.0f} 股" if shares is not None else "",
            f"{percent:.2f}%" if percent is not None else "",
        ) if part) or "未可靠辨識"
        nature = "13D 主動型" if item.get("active_13d") else item.get("filing_basis", "13G")
        lines.append(
            f"| **{item['ticker']}** | {'、'.join(item.get('reporting_persons', [])) or '—'} | "
            f"{', '.join(item.get('cusips', [])) or '—'} | {holding} | {item['status_label']} | {nature} | "
            f"[{item['latest_filing_date']}]({item['url']}) | {item['history_count']} 份 |"
        )
    lines += ["", "## 大股東異動時間軸與警報", "",
              "紅／黃／綠代表閱讀優先度，不代表利多或利空。紅色包括跨越 5% 門檻、13D 主動申報、13G 轉 13D，或持股比例變動至少 2 個百分點；黃色包括 0.5 至低於 2 個百分點的變動與申報主體重整。", "",
              "| 申報日 | 公司 | 申報人 | 關注度 | 異動事件 | 最新持股 | 較前次 | 客觀解讀 | SEC |",
              "|---|---|---|---|---|---|---|---|---|"]
    for event in timeline:
        shares = event.get("aggregate_shares")
        percent = event.get("percent_of_class")
        holding = "／".join(part for part in (
            f"{shares:,.0f} 股" if shares is not None else "",
            f"{percent:.2f}%" if percent is not None else "",
        ) if part) or "未可靠辨識"
        changes = []
        share_change = event.get("share_change")
        points = event.get("percentage_points")
        if share_change is not None and event.get("shares_comparable", True):
            changes.append(f"{share_change:+,.0f} 股")
        if points is not None:
            changes.append(f"{points:+.2f}pp")
        if not changes:
            changes.append("無前期可比" if not event.get("previous_filing_date") else "未達警示門檻")
        lines.append(
            f"| {event['filing_date']} | **{event['ticker']}** | {'、'.join(event.get('reporting_persons', [])) or '—'} | "
            f"{event['importance_label']} | {event['event_label']} | {holding} | {'／'.join(changes)} | "
            f"{event['interpretation']} | [原文]({event['url']}) |"
        )
    lines += ["", "## 完整申報歷史", "", "| 日期 | 公司 | 表單 | 申報人 | 實際受益持股 | 較前次同申報人 | 性質／重點 |", "|---|---|---|---|---|---|---|"]
    for row in sorted(rows, key=lambda r: r["filing_date"], reverse=True):
        facts = row.get("ownership", {})
        if facts.get("data_status") == "parsed":
            shares = facts.get("aggregate_shares")
            percent = facts.get("percent_of_class")
            holding_parts = []
            if shares is not None:
                holding_parts.append(f"{shares:,.0f} 股")
            if percent is not None:
                holding_parts.append(f"{percent:.2f}%")
            holding = "／".join(holding_parts) or "原文未可靠辨識"
            if len(facts.get("positions", [])) > 1:
                holding = "逐申報人最高 " + holding
            if facts.get("threshold_exit"):
                holding += "（已降至 5% 以下）"
        elif facts.get("threshold_exit"):
            holding = "已降至 5% 以下（原文勾選）"
        else:
            holding = "原文未可靠辨識"
        change = facts.get("change_from_prior")
        if change:
            shares = change.get("shares")
            points = change.get("percentage_points")
            change_text = change["direction"]
            if shares is not None and change.get("shares_comparable", True):
                change_text += f" {shares:+,.0f} 股"
            if points is not None:
                change_text += f"／{points:+.2f}pp"
            if change.get("comparison_note"):
                change_text += f"；{change['comparison_note']}"
        else:
            change_text = "無同申報人前期可比"
        purpose = facts.get("purpose_excerpt", "")
        detail = facts.get("filing_basis", row["meaning"])
        if purpose:
            detail += f"；Item 4：{purpose[:180]}{'…' if len(purpose) > 180 else ''}"
        elif facts.get("filing_comment"):
            comment = facts["filing_comment"]
            detail += f"；申報備註：{comment[:180]}{'…' if len(comment) > 180 else ''}"
        lines.append(f"| {row['filing_date']} | **{row['ticker']}** | [{row['form']}]({row['url']}) | {'、'.join(row['reporting_persons']) or '—'} | {holding} | {change_text} | {detail} |")
    lines += ["", "> 持股數與比例取自該份 SEC 申報，不是即時持倉；『較前次』只比較同公司、同一申報 CIK 的既有 13D／13G 文件。13D 的 Item 4 摘錄用來辨識投資目的，仍應開原文閱讀完整上下文。", ""]
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


def render_merger_note(deals, window, checked_at):
    lines = [
        "---", "title: 併購／公開收購雷達", f"updated_at: {checked_at}", "tags:",
        "  - sec/ma", "---", "", "# 🤝 併購／公開收購雷達", "",
        f"只保留 `{window['cutoff']}` 起最近 {window['years']} 年、且由表單與內文共同確認的交易文件。",
        "S-4／F-4 可能只是債券交換要約，沒有合併／收購內文者不納入。", "",
        "| 最後申報 | 公司 | 交易 | 最後可見程序 | 文件 | SEC |",
        "|---|---|---|---|---|---|",
    ]
    for deal in deals:
        forms = "、".join(deal["forms"])
        lines.append(
            f"| {deal['latest_filing_date']} | **{deal['ticker']}** | {deal['deal_name']} | "
            f"{deal['last_procedural_status']} | {deal['document_count']} 份（{forms}） | "
            f"[最新原文]({deal['latest_url']}) |"
        )
    if not deals:
        lines.append("| — | — | — | 最近三年沒有經內文確認的交易 | — | — |")
    lines += [
        "", "> 一列是一宗交易，不是一份文件。同案的 S-4／F-4、425、SC TO、SC 14D9、SC 13E3 已合併。",
        "> 「最後可見程序」只描述最後一份 SEC 文件，不代表交易截至今日仍處於該狀態；請看日期與最新原文。", "",
    ]
    return "\n".join(lines)


def refresh_merger_excerpts(output=DEFAULT_OUTPUT, radar_dir=DEFAULT_DIR):
    """Enrich existing M&A rows without rebuilding or truncating other radar history."""
    output = Path(output)
    payload = json.loads(output.read_text())
    updated = 0
    errors = []
    checked_at = utc_now()
    cutoff = merger_cutoff(checked_at)
    for row in payload.get("mergers", []):
        event = row.get("event", {})
        if not event.get("url") or event.get("filing_date", "") < cutoff.isoformat():
            continue
        try:
            row["content_excerpt"] = merger_content_excerpt(
                fetch(event["url"], "text/html,application/xhtml+xml", max_bytes=600_000)
            )
            updated += bool(row["content_excerpt"])
            time.sleep(0.11)
        except Exception as exc:
            errors.append(f"M&A {event.get('accession', '—')}: {type(exc).__name__}: {exc}")
    relevant, deals, window = build_merger_deals(
        payload.get("mergers", []), load_companies(), checked_at
    )
    payload["mergers"] = relevant
    payload["merger_deals"] = deals
    payload["merger_window"] = window
    payload["merger_excerpts_updated_at"] = utc_now()
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    radar_dir = Path(radar_dir)
    radar_dir.mkdir(parents=True, exist_ok=True)
    (radar_dir / "Mergers_Tender_Radar.md").write_text(
        render_merger_note(deals, window, checked_at) + "\n"
    )
    return {"documents": len(relevant), "deals": len(deals), "updated": updated, "errors": errors}


def refresh_ownership_facts(output=DEFAULT_OUTPUT, radar_dir=DEFAULT_DIR):
    """Refresh 13D/G search results and facts without rebuilding other radars."""
    output = Path(output)
    payload = json.loads(output.read_text())
    errors = []
    previous_rows = payload.get("ownership_13dg", [])
    rows = []
    for ticker, company in sorted(load_companies().items()):
        try:
            rows.extend(search_13dg_with_retry(ticker, company))
        except Exception as exc:
            errors.append(f"13D/G {ticker}: {type(exc).__name__}: {exc}")
            rows.extend(row for row in previous_rows if row.get("ticker") == ticker)
        time.sleep(0.11)
    enrich_ownership_rows(rows, previous_rows=previous_rows, errors=errors)
    payload["schema_version"] = max(payload.get("schema_version", 1), 3)
    payload["ownership_13dg"] = rows
    snapshot = build_ownership_snapshot(rows)
    timeline = build_ownership_timeline(rows)
    payload["ownership_snapshot"] = snapshot
    payload["ownership_timeline"] = timeline
    payload["ownership_facts_updated_at"] = utc_now()
    payload["errors"] = [
        item for item in payload.get("errors", [])
        if not item.startswith(("13D/G ", "13D/G facts "))
    ] + errors
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    radar_dir = Path(radar_dir)
    radar_dir.mkdir(parents=True, exist_ok=True)
    checked_at = payload["ownership_facts_updated_at"]
    (radar_dir / "Schedule13DG_Ownership_Radar.md").write_text(
        render_ownership_note(rows, checked_at, snapshot, timeline) + "\n"
    )
    parsed = sum(row.get("ownership", {}).get("data_status") in {"parsed", "threshold_exit"} for row in rows)
    return {"documents": len(rows), "parsed": parsed, "errors": errors}


def rebuild_ownership_views(output=DEFAULT_OUTPUT, radar_dir=DEFAULT_DIR):
    """Rebuild snapshot/timeline from cached filings without calling SEC."""
    output = Path(output)
    payload = json.loads(output.read_text())
    rows = add_ownership_changes(payload.get("ownership_13dg", []))
    snapshot = build_ownership_snapshot(rows)
    timeline = build_ownership_timeline(rows)
    payload["schema_version"] = max(payload.get("schema_version", 1), 3)
    payload["ownership_13dg"] = rows
    payload["ownership_snapshot"] = snapshot
    payload["ownership_timeline"] = timeline
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    checked_at = payload.get("ownership_facts_updated_at", payload.get("updated_at", ""))
    radar_dir = Path(radar_dir)
    radar_dir.mkdir(parents=True, exist_ok=True)
    (radar_dir / "Schedule13DG_Ownership_Radar.md").write_text(
        render_ownership_note(rows, checked_at, snapshot, timeline) + "\n"
    )
    return {"documents": len(rows), "holders": len(snapshot), "events": len(timeline)}


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
    cache = {"schema_version": 3, "updated_at": checked_at, "source": "SEC EDGAR submissions, EFTS and enforcement RSS"}

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
    existing_mergers = {
        row.get("event", {}).get("accession"): row
        for row in previous.get("mergers", [])
        if row.get("event", {}).get("accession")
    }
    candidate_events = {
        event["accession"]: event for event in event_rows(fetched, MA_FORMS, 50)
    }
    for accession, row in existing_mergers.items():
        candidate_events.setdefault(accession, row["event"])
    raw_mergers = []
    cutoff = merger_cutoff(checked_at)
    for event in sorted(candidate_events.values(), key=lambda item: item.get("filing_date", ""), reverse=True):
        if event.get("filing_date", "") < cutoff.isoformat():
            continue
        cached_row = existing_mergers.get(event["accession"])
        if cached_row and cached_row.get("content_excerpt"):
            cached = dict(cached_row)
            cached["event"] = event
            raw_mergers.append(cached)
            continue
        try:
            raw_mergers.append(enrich_merger_event(event))
            time.sleep(0.11)
        except Exception as exc:
            errors.append(f"M&A {event['accession']}: {type(exc).__name__}: {exc}")
            raw_mergers.append({"event": event, "signals": [], "attachments": [], "content_excerpt": ""})
    mergers, merger_deals, merger_window = build_merger_deals(
        raw_mergers, companies, checked_at
    )

    previous_ownership = list(previous.get("ownership_13dg", []))
    ownership = list(previous_ownership) if not include_external else []
    enforcement = list(previous.get("enforcement", [])) if not include_external else []
    if include_external:
        for ticker, company in sorted(companies.items()):
            try:
                ownership.extend(search_13dg_with_retry(ticker, company))
            except Exception as exc:
                errors.append(f"13D/G {ticker}: {type(exc).__name__}: {exc}")
                ownership.extend(row for row in previous_ownership if row.get("ticker") == ticker)
            time.sleep(0.11)
        ownership = enrich_ownership_rows(ownership, previous_ownership, errors)
        try:
            enforcement = enforcement_matches(companies)
        except Exception as exc:
            errors.append(f"enforcement: {type(exc).__name__}: {exc}")

    ownership_snapshot = build_ownership_snapshot(ownership)
    ownership_timeline = build_ownership_timeline(ownership)
    cache.update({"footnotes": footnotes, "accounting_review": accounting, "ownership_13dg": ownership,
                  "ownership_snapshot": ownership_snapshot,
                  "ownership_timeline": ownership_timeline,
                  "governance": governance, "insiders": insiders, "mergers": mergers,
                  "merger_deals": merger_deals, "merger_window": merger_window,
                  "enforcement": enforcement, "errors": errors})
    output.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n")
    radar_dir = Path(radar_dir)
    radar_dir.mkdir(parents=True, exist_ok=True)
    notes = {
        "Footnotes_Attachments_Radar.md": render_simple_note("📎 財報附註／附件雷達", "sec/footnotes", "索引財報主文的風險關鍵字與 EX-2／10／19／21／97／99 等重要附件。", footnotes, checked_at),
        "Accounting_Review_Radar.md": render_simple_note("🧮 UPLOAD／CORRESP 會計審閱雷達", "sec/accounting-review", "UPLOAD 是 SEC 意見函，CORRESP 是公司回覆；兩者成對閱讀才能看出審閱問題與解法。", accounting, checked_at),
        "Governance_Compensation_Radar.md": render_simple_note("🏛️ DEF 14A 治理與薪酬分析", "sec/governance", "追蹤正式／預備代理委託書、審計費用、CEO 薪酬、中位員工薪酬與 pay ratio；正則無法穩定辨識的數字保留缺值。", governance, checked_at),
        "Mergers_Tender_Radar.md": render_merger_note(merger_deals, merger_window, checked_at),
        "Schedule13DG_Ownership_Radar.md": render_ownership_note(
            ownership, checked_at, ownership_snapshot, ownership_timeline
        ),
        "Insider_Forms_345144_Radar.md": render_insider_note(insiders, checked_at),
        "SEC_Enforcement_Radar.md": render_enforcement_note(enforcement, checked_at),
    }
    for filename, content in notes.items():
        (radar_dir / filename).write_text(content + "\n")
    counts = {key: len(cache[key]) for key in ("footnotes", "accounting_review", "ownership_13dg", "governance", "insiders", "enforcement")}
    counts["mergers"] = len(merger_deals)
    counts["merger_documents"] = len(mergers)
    return {"counts": counts, "errors": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, default=ROOT / "sec_filing_alerts.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--radar-dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--no-external", action="store_true")
    parser.add_argument("--refresh-merger-excerpts-only", action="store_true",
                        help="只補既有併購列的可驗證原文摘錄，不重建其他雷達")
    parser.add_argument("--refresh-ownership-facts-only", action="store_true",
                        help="只補既有 13D／13G 的實際持股數字，不重建其他雷達")
    parser.add_argument("--rebuild-ownership-views-only", action="store_true",
                        help="只用既有 13D／13G 資料重建最新總覽與異動時間軸，不連線 SEC")
    args = parser.parse_args()
    if args.refresh_merger_excerpts_only:
        print(json.dumps(refresh_merger_excerpts(args.output, args.radar_dir), ensure_ascii=False))
        return
    if args.refresh_ownership_facts_only:
        print(json.dumps(refresh_ownership_facts(args.output, args.radar_dir), ensure_ascii=False))
        return
    if args.rebuild_ownership_views_only:
        print(json.dumps(rebuild_ownership_views(args.output, args.radar_dir), ensure_ascii=False))
        return
    events = json.loads(args.events.read_text()).get("events", [])
    fetched = {}
    for event in events:
        fetched.setdefault(event["ticker"], []).append(event)
    result = update_radars(fetched, args.output, args.radar_dir, include_external=not args.no_external)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
