#!/usr/bin/env python3
"""Persist and compare objective investment-thesis states for 14 companies.

The configuration defines three measurable proxies per company.  This script
evaluates those rules against quarterly_financials.json, compares the result
with the last committed run, and records only genuine status changes.  A new
quarter with different numbers but unchanged supported/verify/invalidated
states does not create a notification.
"""

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "investment_thesis_tracking.json"
DEFAULT_QUARTERLY = REPO_ROOT / "quarterly_financials.json"
DEFAULT_OUTPUT = REPO_ROOT / "investment_thesis_status.json"

STATUS_LABELS = {
    "maintained": "論點維持",
    "needs-validation": "需要驗證",
    "partial-invalidated": "部分失效",
    "major-invalidated": "重大失效",
}
ITEM_LABELS = {"supported": "支持", "verify": "待驗證", "invalidated": "失效"}


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(path, fallback=None):
    path = Path(path)
    if not path.exists():
        return fallback
    return json.loads(path.read_text())


def metric_value(period, metric):
    value = (period or {}).get("values", {}).get(metric)
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("value")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def delta(current, previous, mode="percent"):
    if current is None or previous is None:
        return None
    if mode == "pp":
        return (current - previous) * 100
    if previous == 0:
        return None
    return (current / previous - 1) * 100


def trend_streak(periods, metric, mode="percent", threshold=0):
    direction = None
    comparisons = 0
    for index in range(min(len(periods) - 1, 7)):
        change = delta(
            metric_value(periods[index], metric),
            metric_value(periods[index + 1], metric),
            mode,
        )
        if change is None:
            break
        step = "up" if change > threshold else ("down" if change < -threshold else "flat")
        if step == "flat":
            break
        if direction is None:
            direction = step
        if step != direction:
            break
        comparisons += 1
    return {"direction": direction or "flat", "quarters": comparisons + 1 if comparisons else 1}


def signed_streak(periods, metric, direction):
    count = 0
    for period in periods:
        value = metric_value(period, metric)
        if value is None or (value <= 0 if direction == "positive" else value >= 0):
            break
        count += 1
    return count


def number(value, decimals=1):
    if value is None:
        return "—"
    return f"{value:,.{decimals}f}"


def signed(value, unit="%"):
    if value is None:
        return "—"
    return f"{'+' if value > 0 else ''}{number(value)}{unit}"


def amount(value, currency):
    if value is None:
        return "—"
    divisor, unit = (1e9, "B") if currency == "TWD" else (1e6, "M")
    return f"{number(value / divisor)}{unit}"


def item_state(thesis, latest, year_ago, periods, currency):
    status = "verify"
    evidence = "缺少足夠的當季或去年同期數字，暫時不能驗證。"
    metric = thesis["metric"]
    facts = {}
    if metric == "revenue_growth":
        revenue = metric_value(latest, "revenue")
        revenue_yoy = delta(revenue, metric_value(year_ago, "revenue"))
        streak = trend_streak(periods, "revenue", "percent", 1)
        declining = (
            streak["direction"] == "down"
            and streak["quarters"] >= int(thesis.get("invalidate_decline_quarters", 3))
        )
        if (revenue_yoy is not None and revenue_yoy <= thesis["invalidate_yoy"]) or declining:
            status = "invalidated"
        elif revenue_yoy is not None and revenue_yoy >= thesis["support_yoy"]:
            status = "supported"
        direction = "上升" if streak["direction"] == "up" else "下降"
        trend = f"連續 {streak['quarters']} 季{direction}" if streak["quarters"] >= 2 else "未形成連續方向"
        evidence = (
            f"{latest['period_end']} 缺可靠營收。" if revenue is None else
            f"{latest['period_end']} 營收 {currency} {amount(revenue, currency)}，"
            f"YoY {signed(revenue_yoy)}；{trend}。"
        )
        facts = {"revenue": revenue, "revenue_yoy": revenue_yoy, "streak": streak}
    elif metric in {"gross_margin", "operating_margin"}:
        margin = metric_value(latest, metric)
        margin_yoy = delta(margin, metric_value(year_ago, metric), "pp")
        streak = trend_streak(periods, metric, "pp", 0.5)
        decline_threshold = int(thesis.get("invalidate_decline_quarters", 0))
        negative_threshold = int(thesis.get("invalidate_negative_quarters", 0))
        declining = (
            decline_threshold > 0 and streak["direction"] == "down"
            and streak["quarters"] >= decline_threshold
        )
        negative_quarters = signed_streak(periods, metric, "negative") if negative_threshold else 0
        persistently_negative = negative_threshold > 0 and negative_quarters >= negative_threshold
        if margin is not None and (margin < thesis["invalidate_floor"] or declining or persistently_negative):
            status = "invalidated"
        elif margin is not None and margin >= thesis["support_floor"]:
            status = "supported"
        label = "毛利率" if metric == "gross_margin" else "營業利益率"
        direction = "上升" if streak["direction"] == "up" else "下降"
        trend = f"連續 {streak['quarters']} 季{direction}" if streak["quarters"] >= 2 else "未形成連續方向"
        evidence = (
            f"{latest['period_end']} 缺可靠{label}。" if margin is None else
            f"{latest['period_end']} {label} {number(margin * 100)}%，"
            f"YoY {signed(margin_yoy, 'pp')}；{trend}。"
        )
        facts = {
            "margin": margin, "margin_yoy_pp": margin_yoy, "streak": streak,
            "negative_quarters": negative_quarters,
        }
    elif metric == "cash_dilution":
        fcf = metric_value(latest, "free_cash_flow")
        shares = metric_value(latest, "diluted_shares")
        share_yoy = delta(shares, metric_value(year_ago, "diluted_shares"))
        positive_quarters = signed_streak(periods, "free_cash_flow", "positive")
        negative_quarters = signed_streak(periods, "free_cash_flow", "negative")
        negative_breach = negative_quarters >= int(thesis.get("invalidate_negative_fcf_quarters", 4))
        dilution_breach = share_yoy is not None and share_yoy >= thesis["invalidate_share_yoy"]
        if negative_breach or dilution_breach:
            status = "invalidated"
        elif (
            positive_quarters >= int(thesis.get("support_positive_fcf_quarters", 3))
            and (share_yoy is None or share_yoy <= 2)
        ):
            status = "supported"
        if fcf is None:
            fcf_text, fcf_streak = "FCF 缺值", "無法計算連續性"
        else:
            streak_count = positive_quarters if fcf > 0 else negative_quarters
            fcf_text = f"FCF {currency} {amount(fcf, currency)}"
            fcf_streak = f"連續 {streak_count} 季為{'正' if fcf > 0 else '負'}"
        share_text = "稀釋股數缺值" if shares is None else f"稀釋股數 YoY {signed(share_yoy)}"
        evidence = f"{latest['period_end']} {fcf_text}（{fcf_streak}）；{share_text}。"
        facts = {
            "free_cash_flow": fcf, "positive_fcf_quarters": positive_quarters,
            "negative_fcf_quarters": negative_quarters, "diluted_shares": shares,
            "share_yoy": share_yoy,
        }
    return {
        **thesis,
        "status": status,
        "label": ITEM_LABELS[status],
        "evidence": evidence,
        "facts": facts,
    }


def snapshot(company, config, offset=0):
    periods = company.get("periods", [])[offset:offset + 8]
    if not periods:
        return None
    latest = periods[0]
    year_ago = periods[4] if len(periods) > 4 else None
    currency = company.get("currency", "USD")
    items = [item_state(thesis, latest, year_ago, periods, currency) for thesis in config["theses"]]
    counts = {key: sum(item["status"] == key for item in items) for key in ITEM_LABELS}
    if counts["invalidated"] >= 2:
        status = "major-invalidated"
    elif counts["invalidated"] == 1:
        status = "partial-invalidated"
    elif counts["supported"] >= 2:
        status = "maintained"
    else:
        status = "needs-validation"
    fingerprint_source = {
        "period": latest.get("period_end"), "accession": latest.get("accession"),
        "status": status,
        "items": [{"id": item["id"], "status": item["status"], "facts": item["facts"]} for item in items],
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_source, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:20]
    return {
        "status": status,
        "label": STATUS_LABELS[status],
        "items": items,
        "counts": counts,
        "period": latest.get("period_end"),
        "url": latest.get("url"),
        "accession": latest.get("accession"),
        "fingerprint": fingerprint,
    }


def compare_company(ticker, previous, current, checked_at):
    if not previous:
        return None
    before_items = {item["id"]: item for item in previous.get("items", [])}
    item_changes = []
    for item in current.get("items", []):
        prior = before_items.get(item["id"])
        if prior and prior.get("status") != item.get("status"):
            item_changes.append({
                "id": item["id"], "title": item["title"],
                "before_status": prior.get("status"), "before_label": prior.get("label"),
                "after_status": item.get("status"), "after_label": item.get("label"),
                "evidence": item.get("evidence"), "invalidation": item.get("invalidation"),
            })
    overall_changed = previous.get("status") != current.get("status")
    if not overall_changed and not item_changes:
        return None
    return {
        "ticker": ticker,
        "detected_at": checked_at,
        "previous_period": previous.get("period"),
        "period": current.get("period"),
        "before_status": previous.get("status"),
        "before_label": previous.get("label", STATUS_LABELS.get(previous.get("status"), "—")),
        "after_status": current.get("status"),
        "after_label": current.get("label"),
        "overall_changed": overall_changed,
        "item_changes": item_changes,
        "source_url": current.get("url"),
        "fingerprint": current.get("fingerprint"),
    }


def build_status(config, quarterly, previous_output, checked_at):
    prior_companies = (previous_output or {}).get("companies", {})
    initializing = not bool(prior_companies)
    companies = {}
    changes = []
    for ticker, company_config in sorted(config["companies"].items()):
        quarterly_company = quarterly.get("companies", {}).get(ticker, {})
        quarterly_history = [
            row for offset in range(4)
            if (row := snapshot(quarterly_company, company_config, offset)) is not None
        ]
        if not quarterly_history:
            continue
        current = dict(quarterly_history[0])
        current["history"] = quarterly_history
        current["previous"] = quarterly_history[1] if len(quarterly_history) > 1 else None
        change = None if initializing else compare_company(ticker, prior_companies.get(ticker), current, checked_at)
        if change:
            changes.append(change)
        current["overallStatusChanged"] = bool(change and change["overall_changed"])
        current["itemStatusChanged"] = bool(change and change["item_changes"])
        current["statusChanged"] = bool(change)
        current["latestChange"] = change
        current["queueAlert"] = current["counts"]["invalidated"] > 0 or bool(change)
        current["priority"] = 96 if current["status"] == "major-invalidated" else (
            89 if current["status"] == "partial-invalidated" else (74 if change else 0)
        )
        current["master_report"] = company_config.get("master_report")
        current["config_updated_at"] = config.get("updated_at")
        companies[ticker] = current

    batch = {
        "checked_at": checked_at,
        "previous_checked_at": (previous_output or {}).get("updated_at", ""),
        "baseline": initializing,
        "changed_count": len(changes),
        "critical_count": sum(
            change["after_status"] == "major-invalidated"
            or any(item["after_status"] == "invalidated" for item in change["item_changes"])
            for change in changes
        ),
        "changed_tickers": [change["ticker"] for change in changes],
        "changes": changes,
    }
    old_batches = [
        row for row in (previous_output or {}).get("update_batches", [])
        if row.get("checked_at") != checked_at
    ]
    old_log = (previous_output or {}).get("change_log", [])
    return {
        "schema_version": 1,
        "updated_at": checked_at,
        "source_updated_at": quarterly.get("updated_at"),
        "source": "quarterly_financials.json + investment_thesis_tracking.json; status-change snapshots",
        "method": config.get("method"),
        "companies": companies,
        "change_log": [*changes, *old_log][:240],
        "update_batches": [batch, *old_batches][:60],
    }, batch


def render_alert(batch):
    lines = ["", "## 投資論點狀態變更", ""]
    if batch["baseline"]:
        lines.append("✅ 已建立 14 家投資論點狀態基準；基準不產生通知。")
    elif not batch["changes"]:
        lines.append("✅ 本次沒有任何論點狀態改變；數值更新但分類不變時不通知。")
    else:
        lines += [
            f"本次有 **{batch['changed_count']} 家**公司的投資論點狀態改變。", "",
            "| 公司 | 綜合狀態 | 分項變化 | 最新證據 | 原文 |",
            "|---|---|---|---|---|",
        ]
        for change in batch["changes"]:
            item_text = "；".join(
                f"{item['title']}：{item['before_label']} → {item['after_label']}"
                for item in change["item_changes"]
            ) or "分項未變，綜合門檻改變"
            evidence = "；".join(
                f"{item['evidence']}；門檻：{item.get('invalidation', '請核對規則設定')}"
                for item in change["item_changes"]
            ) or "請核對季度數字"
            url = change.get("source_url") or ""
            source = f"[原文]({url})" if url else "—"
            lines.append(
                f"| **{change['ticker']}** | {change['before_label']} → {change['after_label']} | "
                f"{item_text.replace('|', '／')} | {evidence.replace('|', '／')} | {source} |"
            )
        lines += [
            "",
            "> 這是量化代理條件的狀態變更，不是買進／賣出建議。請以季度原文核對產品、市占與管理層說明。",
        ]
    return "\n".join(lines) + "\n"


def append_text(path, text):
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(text)


def write_github_output(path, values):
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--quarterly", type=Path, default=DEFAULT_QUARTERLY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--initialize", action="store_true", help="Replace prior state with a notification-free baseline")
    parser.add_argument("--checked-at", default="")
    parser.add_argument("--alert-markdown", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--github-output", type=Path, default=os.environ.get("GITHUB_OUTPUT"))
    args = parser.parse_args()

    checked_at = args.checked_at or now_utc()
    config = load_json(args.config)
    quarterly = load_json(args.quarterly)
    if not config or not quarterly:
        raise SystemExit("缺少投資論點設定或季度財務資料")
    previous_output = {} if args.initialize else load_json(args.output, {})
    output, batch = build_status(config, quarterly, previous_output, checked_at)
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    alert = render_alert(batch)
    append_text(args.alert_markdown, alert)
    append_text(args.summary, alert)

    change_source = "\n".join(
        f"{row['ticker']}:{row['fingerprint']}" for row in batch["changes"]
    )
    batch_id = hashlib.sha256(change_source.encode()).hexdigest()[:10] if change_source else "none"
    write_github_output(args.github_output, {
        "notify_count": batch["changed_count"],
        "critical_count": batch["critical_count"],
        "batch_id": batch_id,
    })
    print(
        f"投資論點狀態：{len(output['companies'])} 家；"
        f"變更 {batch['changed_count']} 家；重大通知 {batch['critical_count']} 家"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
