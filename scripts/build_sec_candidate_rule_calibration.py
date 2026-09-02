#!/usr/bin/env python3
"""Build deterministic candidate-rule quality statistics from AI reviews.

The calibration never deletes a filing.  A rule may only be marked for lower
display priority after at least five reviewed samples and an acceptance rate
of 20% or less.  Official events remain available in the underlying radars.
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REVIEWS = REPO_ROOT / "sec_daily_candidate_reviews.json"
DEFAULT_OUTPUT = REPO_ROOT / "sec_candidate_rule_calibration.json"
DEFAULT_MARKDOWN = REPO_ROOT / "60_SEC_Filing_Radar/SEC_Candidate_Rule_Calibration.md"
MIN_REVIEWED_SAMPLES = 5
LOW_ACCEPTANCE_RATE = 0.20

RULE_LABELS = {
    "form4_buy": "Form 4 主動買入",
    "form4_sell_10b5_1": "Form 4｜10b5-1 賣出",
    "form4_sell_mixed": "Form 4｜混合計畫賣出",
    "form4_sell_unplanned": "Form 4｜非 10b5-1 賣出",
    "form144_proposed_sale": "Form 144 擬售",
    "dilution_filing": "募資／潛在稀釋文件",
    "periodic_filing": "10-K／10-Q／20-F 定期財報",
    "major_current_report": "重大 8-K／6-K",
    "quarterly_fingerprint": "季度財務指紋變更",
    "thesis_fingerprint": "投資論點指紋變更",
    "ownership_change": "13D／13G 大股東變更",
    "sec_enforcement": "SEC 執法／停牌命中",
}

REJECTION_REASON_LABELS = {
    "preplanned_trade": "10b5-1 預先交易計畫",
    "proposed_not_completed": "只是擬售、尚未證明成交",
    "immaterial_relative_size": "相對持股／流通股規模過低",
    "insufficient_thesis_evidence": "不足以改變營運或投資論點",
}


def load_json(path):
    return json.loads(Path(path).read_text())


def build_calibration(reviews):
    grouped = defaultdict(list)
    reason_counts = Counter()
    for batch in reviews.get("batches", []):
        for decision in batch.get("decisions", []):
            rule_key = decision.get("rule_key")
            if not rule_key:
                continue
            grouped[rule_key].append(decision)
            if decision.get("disposition") == "rejected":
                reason_counts.update(decision.get("rejection_reasons", []))

    rules = {}
    for rule_key in sorted(grouped):
        decisions = grouped[rule_key]
        accepted = sum(row.get("disposition") == "accepted" for row in decisions)
        rejected = sum(row.get("disposition") == "rejected" for row in decisions)
        reviewed = accepted + rejected
        acceptance_rate = accepted / reviewed if reviewed else None
        enough_samples = reviewed >= MIN_REVIEWED_SAMPLES
        adjustment = "lower_priority" if (
            enough_samples and acceptance_rate is not None and acceptance_rate <= LOW_ACCEPTANCE_RATE
        ) else "none"
        if not enough_samples:
            reason = f"只有 {reviewed} 個已覆核樣本；至少 {MIN_REVIEWED_SAMPLES} 個樣本前不調整優先級。"
        elif adjustment == "lower_priority":
            reason = f"已覆核 {reviewed} 個樣本，採納率 {acceptance_rate:.0%} ≤ {LOW_ACCEPTANCE_RATE:.0%}，只降低顯示優先級、不刪除事件。"
        else:
            reason = f"已覆核 {reviewed} 個樣本，採納率 {acceptance_rate:.0%}，維持原優先級。"
        rules[rule_key] = {
            "label": RULE_LABELS.get(rule_key, rule_key),
            "reviewed_count": reviewed,
            "accepted_count": accepted,
            "rejected_count": rejected,
            "acceptance_rate": round(acceptance_rate, 4) if acceptance_rate is not None else None,
            "sample_status": "enough" if enough_samples else "insufficient",
            "priority_adjustment": adjustment,
            "reason": reason,
        }

    rejection_reasons = [{
        "key": key,
        "label": REJECTION_REASON_LABELS.get(key, key),
        "count": count,
    } for key, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))]
    reviewed_total = sum(row["reviewed_count"] for row in rules.values())
    accepted_total = sum(row["accepted_count"] for row in rules.values())
    return {
        "schema_version": 1,
        "generated_at": reviews.get("updated_at", ""),
        "minimum_samples_before_adjustment": MIN_REVIEWED_SAMPLES,
        "low_acceptance_rate_threshold": LOW_ACCEPTANCE_RATE,
        "policy": "樣本不足時不調整；達門檻後只降低候選顯示優先級，不刪除 SEC 事件或正式原文。",
        "reviewed_candidate_count": reviewed_total,
        "accepted_candidate_count": accepted_total,
        "rejected_candidate_count": reviewed_total - accepted_total,
        "acceptance_rate": round(accepted_total / reviewed_total, 4) if reviewed_total else None,
        "rules": rules,
        "rejection_reasons": rejection_reasons,
    }


def render_markdown(payload):
    rate = payload.get("acceptance_rate")
    rate_label = f"{rate:.0%}" if rate is not None else "—"
    lines = [
        "---", "title: SEC 候選規則品質校準", f"generated_at: {payload['generated_at']}",
        "tags:", "  - sec/daily", "  - quality/calibration", "---", "",
        "# SEC 候選規則品質校準", "",
        "> 本頁只校準候選的顯示優先級，不刪除 SEC 事件、官方原文或正式覆核紀錄。", "",
        f"- 已覆核：**{payload['reviewed_candidate_count']} 項**",
        f"- 採納：**{payload['accepted_candidate_count']} 項**",
        f"- 駁回：**{payload['rejected_candidate_count']} 項**",
        f"- 整體採納率：**{rate_label}**", "",
        f"> {payload['policy']}", "", "## 各規則命中率", "",
        "| 規則 | 覆核 | 採納 | 駁回 | 採納率 | 校準狀態 |", "|---|---:|---:|---:|---:|---|",
    ]
    for row in payload.get("rules", {}).values():
        row_rate = f"{row['acceptance_rate']:.0%}" if row.get("acceptance_rate") is not None else "—"
        status = "降低顯示優先級" if row.get("priority_adjustment") == "lower_priority" else (
            "樣本不足、不調整" if row.get("sample_status") == "insufficient" else "維持原優先級"
        )
        lines.append(
            f"| {row['label']} | {row['reviewed_count']} | {row['accepted_count']} | "
            f"{row['rejected_count']} | {row_rate} | {status} |"
        )
    lines += ["", "## 常見駁回原因", ""]
    lines += [f"- {row['label']}：**{row['count']} 次**" for row in payload.get("rejection_reasons", [])]
    if not payload.get("rejection_reasons"):
        lines.append("- 尚無駁回樣本。")
    return "\n".join(lines).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviews", type=Path, default=DEFAULT_REVIEWS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    args = parser.parse_args()
    payload = build_calibration(load_json(args.reviews))
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    args.markdown.write_text(render_markdown(payload))
    print(
        f"候選規則校準：{payload['reviewed_candidate_count']} 項已覆核，"
        f"{len(payload['rules'])} 類規則，"
        f"{sum(row['priority_adjustment'] == 'lower_priority' for row in payload['rules'].values())} 類降級"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
