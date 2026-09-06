#!/usr/bin/env python3
"""Build source-traceable segment operating and growth-driver validation.

The input is intentionally curated from official tables because SEC Company
Facts does not preserve reliable segment contexts.  The builder performs only
arithmetic transformations: revenue mix, year-over-year change, growth
contribution, segment margin and concentration.  Missing comparable amounts
remain missing; reported growth rates are never used to reverse-engineer them.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "segment_driver_inputs.json"
DEFAULT_OUTPUT = ROOT / "segment_driver_validation.json"
DEFAULT_MARKDOWN = ROOT / "60_SEC_Filing_Radar" / "Segment_Driver_Validation.md"

DISPLAY_TICKERS = [
    "NVDA", "TSM", "MSFT", "META", "AAPL", "AMZN", "ARM",
    "ONDS", "TSLA", "GOOG", "COHR", "MRVL", "INTC", "NOK",
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def round_or_none(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


def growth_pct(current: float | None, prior: float | None) -> float | None:
    if current is None or prior in {None, 0}:
        return None
    return (current / prior - 1) * 100


def margin_pct(profit: float | None, revenue: float | None) -> float | None:
    if profit is None or revenue in {None, 0}:
        return None
    return profit / revenue * 100


def concentration_label(hhi: float | None, largest_share: float | None) -> tuple[str, str]:
    if hhi is None or largest_share is None:
        return "not_applicable", "不適用"
    if hhi >= 2500 or largest_share >= 65:
        return "high", "高度集中"
    if hhi >= 1500 or largest_share >= 45:
        return "medium", "中度集中"
    return "low", "較分散"


def amount_label(value: float | None, unit: str, approximate: bool = False) -> str:
    if value is None:
        return "—"
    prefix = "約 " if approximate else ""
    return f"{prefix}{value:,.2f} {unit}".rstrip("0").rstrip(".")


def build_company(ticker: str, source: dict[str, Any]) -> dict[str, Any]:
    input_kind = source.get("input_kind", "amount")
    approximate = input_kind == "share_of_total"
    rows: list[dict[str, Any]] = []

    for raw in source.get("items") or []:
        if input_kind == "share_of_total":
            current_share = float(raw["current_share_pct"])
            prior_share = float(raw["prior_share_pct"])
            current = float(source["current_total_revenue"]) * current_share / 100
            prior = float(source["prior_total_revenue"]) * prior_share / 100
        else:
            current = raw.get("current_revenue")
            prior = raw.get("prior_revenue")
            current = float(current) if current is not None else None
            prior = float(prior) if prior is not None else None
            current_share = None
            prior_share = None
        delta = current - prior if current is not None and prior is not None else None
        current_margin = margin_pct(raw.get("current_profit"), current)
        prior_margin = margin_pct(raw.get("prior_profit"), prior)
        rows.append({
            "name": raw["name"],
            "is_elimination": bool(raw.get("is_elimination")),
            "current_revenue": round_or_none(current),
            "prior_revenue": round_or_none(prior),
            "revenue_delta": round_or_none(delta),
            "yoy_pct": round_or_none(
                growth_pct(current, prior)
                if prior not in {None, 0}
                else raw.get("reported_yoy_pct"),
                1,
            ),
            "yoy_basis": "calculated" if prior not in {None, 0} else (
                "company_reported" if raw.get("reported_yoy_pct") is not None else "unavailable"
            ),
            "current_share_pct": current_share,
            "prior_share_pct": prior_share,
            "share_change_pp": round_or_none(current_share - prior_share, 1)
            if current_share is not None and prior_share is not None else None,
            "current_profit": raw.get("current_profit"),
            "prior_profit": raw.get("prior_profit"),
            "current_margin_pct": round_or_none(current_margin, 1),
            "prior_margin_pct": round_or_none(prior_margin, 1),
            "margin_change_pp": round_or_none(current_margin - prior_margin, 1)
            if current_margin is not None and prior_margin is not None else None,
            "approximate": approximate,
        })

    total_current = source.get("current_total_revenue")
    total_prior = source.get("prior_total_revenue")
    if total_current is None:
        values = [row["current_revenue"] for row in rows]
        total_current = sum(value for value in values if value is not None)
    if total_prior is None and all(row["prior_revenue"] is not None for row in rows):
        total_prior = sum(row["prior_revenue"] for row in rows)
    total_current = float(total_current) if total_current is not None else None
    total_prior = float(total_prior) if total_prior is not None else None
    total_delta = total_current - total_prior if total_current is not None and total_prior is not None else None
    total_yoy = growth_pct(total_current, total_prior)

    positive_current = sum(
        row["current_revenue"] for row in rows
        if not row["is_elimination"] and row["current_revenue"] is not None and row["current_revenue"] >= 0
    )
    concentration_applicable = source.get("concentration_applicable", True)
    for row in rows:
        if row["current_share_pct"] is None and concentration_applicable and positive_current:
            revenue = row["current_revenue"]
            row["current_share_pct"] = round(revenue / positive_current * 100, 1) if revenue is not None and revenue >= 0 else None
        elif row["current_share_pct"] is not None:
            row["current_share_pct"] = round(row["current_share_pct"], 1)
        if row["prior_share_pct"] is not None:
            row["prior_share_pct"] = round(row["prior_share_pct"], 1)
        if total_delta not in {None, 0} and row["revenue_delta"] is not None:
            row["growth_contribution_pct"] = round(row["revenue_delta"] / total_delta * 100, 1)
        else:
            row["growth_contribution_pct"] = None

    business_rows = [row for row in rows if not row["is_elimination"]]
    positive_deltas = [row for row in business_rows if row["revenue_delta"] is not None and row["revenue_delta"] > 0]
    negative_deltas = [row for row in business_rows if row["revenue_delta"] is not None and row["revenue_delta"] < 0]
    driver = max(positive_deltas, key=lambda row: row["revenue_delta"], default=None)
    drag = min(negative_deltas, key=lambda row: row["revenue_delta"], default=None)
    shares = [row["current_share_pct"] for row in business_rows if row["current_share_pct"] is not None]
    largest = max(business_rows, key=lambda row: row["current_share_pct"] or -1, default=None) if shares else None
    hhi = round(sum(share ** 2 for share in shares), 0) if concentration_applicable and shares else None
    concentration_status, concentration_text = concentration_label(
        hhi, largest.get("current_share_pct") if largest else None
    )

    if total_yoy is not None and total_yoy < 0:
        status, label = "decline", "分部合計轉弱"
    elif total_yoy is not None and drag:
        status, label = "mixed_growth", "成長但內部分化"
    elif total_yoy is not None and total_yoy >= 0 and (
        (driver and (driver.get("growth_contribution_pct") or 0) >= 70)
        or concentration_status == "high"
    ):
        status, label = "concentrated_growth", "成長但驅動集中"
    elif total_yoy is not None and total_yoy >= 0:
        status, label = "broad_growth", "成長較廣泛"
    elif any((row.get("yoy_pct") or 0) > 0 for row in rows):
        status, label = "directional_concentrated_growth", "方向向上但貢獻待補"
    else:
        status, label = "insufficient", "可比資料不足"

    confidence = source.get("comparability", "low")
    if source.get("coverage_status") not in {"complete", "reconciled"} and confidence == "high":
        confidence = "medium"
    if approximate and confidence == "high":
        confidence = "medium"
    confidence_label = {"high": "高", "medium": "中", "low": "低"}.get(confidence, "低")

    positives = []
    risks = []
    if driver:
        contribution = driver.get("growth_contribution_pct")
        suffix = f"，占合計增量 {contribution:.1f}%" if contribution is not None else ""
        positives.append(f"最大成長來源為 {driver['name']}：YoY {driver['yoy_pct']:+.1f}%{suffix}。")
    else:
        reported = max(business_rows, key=lambda row: row.get("yoy_pct") or -1, default=None)
        if reported and reported.get("yoy_pct") is not None:
            positives.append(f"公司直接公布 {reported['name']} YoY {reported['yoy_pct']:+.1f}%，但無同口徑前期金額可算貢獻。")
    if drag:
        risks.append(f"{drag['name']} 營收 YoY {drag['yoy_pct']:+.1f}%，形成內部拖累。")
    if concentration_status == "high" and largest:
        risks.append(f"{largest['name']} 占目前已揭露營收 {largest['current_share_pct']:.1f}%，{concentration_text}。")
    loss_rows = [row for row in business_rows if row.get("current_margin_pct") is not None and row["current_margin_pct"] < 0]
    for row in loss_rows[:2]:
        risks.append(f"{row['name']} 分部利益率 {row['current_margin_pct']:.1f}%，仍為虧損。")
    margin_drops = [row for row in business_rows if row.get("margin_change_pp") is not None and row["margin_change_pp"] <= -2]
    for row in margin_drops[:2]:
        risks.append(f"{row['name']} 分部利益率 YoY {row['margin_change_pp']:+.1f}pp。")
    if source.get("comparability_note"):
        risks.append(source["comparability_note"])

    next_checks = []
    if driver:
        next_checks.append(f"下期先確認 {driver['name']} 是否仍是最大增量來源，且成長率未明顯降速。")
    elif business_rows:
        next_checks.append(f"下期等待 {business_rows[0]['name']} 等新口徑前期絕對值，補算成長貢獻。")
    if largest and concentration_applicable:
        next_checks.append(f"追蹤 {largest['name']} 占比是否由 {largest['current_share_pct']:.1f}% 繼續上升，以及其他業務能否分散風險。")
    profit_rows = [row for row in business_rows if row.get("current_margin_pct") is not None]
    if profit_rows:
        weakest = min(profit_rows, key=lambda row: row["current_margin_pct"])
        next_checks.append(f"追蹤 {weakest['name']} 利益率能否由 {weakest['current_margin_pct']:.1f}% 改善；營收成長不能替代獲利驗證。")
    else:
        next_checks.append("公司未按此口徑揭露分部利益；必須另用公司毛利率、營業利益率與 FCF 驗證成長品質。")

    return {
        "ticker": ticker,
        "name": source.get("name", ticker),
        "period": source["period"],
        "comparison_period": source.get("comparison_period"),
        "basis": source["basis"],
        "unit": source["unit"],
        "source_date": source["source_date"],
        "source_url": source["source_url"],
        "basis_change_source_url": source.get("basis_change_source_url"),
        "coverage_status": source.get("coverage_status"),
        "coverage_note": source.get("coverage_note"),
        "comparability": source.get("comparability"),
        "comparability_note": source.get("comparability_note"),
        "approximate": approximate,
        "totals": {
            "current_revenue": round_or_none(total_current),
            "prior_revenue": round_or_none(total_prior),
            "revenue_delta": round_or_none(total_delta),
            "yoy_pct": round_or_none(total_yoy, 1),
        },
        "concentration": {
            "applicable": concentration_applicable,
            "status": concentration_status,
            "label": concentration_text,
            "hhi": hhi,
            "largest_item": largest["name"] if largest else None,
            "largest_share_pct": largest.get("current_share_pct") if largest else None,
        },
        "driver": {
            "name": driver["name"],
            "revenue_delta": driver["revenue_delta"],
            "growth_contribution_pct": driver["growth_contribution_pct"],
        } if driver else None,
        "drag": {
            "name": drag["name"],
            "revenue_delta": drag["revenue_delta"],
            "growth_contribution_pct": drag["growth_contribution_pct"],
        } if drag else None,
        "assessment": {
            "status": status,
            "label": label,
            "confidence": confidence,
            "confidence_label": confidence_label,
            "positive_evidence": positives,
            "risk_evidence": risks,
            "next_checks": next_checks,
        },
        "items": rows,
    }


def validate_inputs(data: dict[str, Any]) -> None:
    companies = data.get("companies") or {}
    if set(companies) != set(DISPLAY_TICKERS):
        missing = sorted(set(DISPLAY_TICKERS) - set(companies))
        extra = sorted(set(companies) - set(DISPLAY_TICKERS))
        raise ValueError(f"公司範圍不符；缺少 {missing}；多出 {extra}")
    for ticker, source in companies.items():
        for key in ("period", "basis", "unit", "source_date", "source_url", "items"):
            if not source.get(key):
                raise ValueError(f"{ticker} 缺少 {key}")
        if len(source["items"]) < 2:
            raise ValueError(f"{ticker} 至少需要兩個項目")
        for index, row in enumerate(source["items"], 1):
            if not row.get("name"):
                raise ValueError(f"{ticker}#{index} 缺名稱")
            if source.get("input_kind") == "share_of_total":
                for key in ("current_share_pct", "prior_share_pct"):
                    if row.get(key) is None:
                        raise ValueError(f"{ticker}#{index} 缺 {key}")
            elif row.get("current_revenue") is None:
                raise ValueError(f"{ticker}#{index} 缺 current_revenue")


def build_payload(data: dict[str, Any]) -> dict[str, Any]:
    validate_inputs(data)
    companies = [build_company(ticker, data["companies"][ticker]) for ticker in DISPLAY_TICKERS]
    exact = sum(1 for row in companies if row["driver"] and not row["approximate"])
    return {
        "schema_version": 1,
        "updated_at": data["updated_at"],
        "tracked_count": len(companies),
        "exact_growth_contribution_count": exact,
        "approximate_growth_contribution_count": sum(1 for row in companies if row["approximate"]),
        "direction_only_count": sum(1 for row in companies if not row["driver"]),
        "methodology": {
            "scope": "14 家個股；ETF 不納入",
            "comparison": "優先比較同口徑去年同期；沒有前期絕對值時只顯示公司直接公布的 YoY。",
            "growth_contribution": "分部營收增量 ÷ 已收錄分部合計營收增量；負值代表抵銷公司成長。",
            "concentration": "HHI 為各分部營收占比平方和；>=2500 或單一項目 >=65% 標為高度集中。",
            "guardrail": "營收成長不等於獲利或股價上漲；口徑變動、收購與內部交易會降低信心並顯示警語。",
        },
        "companies": companies,
    }


def fmt(value: float | None, suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{value:+,.1f}{suffix}" if suffix else f"{value:,.2f}"


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "---", "title: 分部營運與成長驅動驗證", "tags:", "  - sec", "  - segment", "  - earnings-verification", "---", "",
        "# 🧭 分部營運與成長驅動驗證", "",
        f"> 更新：{payload['updated_at']}｜{payload['methodology']['scope']}｜可精確計算成長貢獻 {payload['exact_growth_contribution_count']} 家。", "",
        "## 怎麼看", "",
        f"- **成長貢獻**：{payload['methodology']['growth_contribution']}",
        f"- **集中度**：{payload['methodology']['concentration']}",
        f"- **限制**：{payload['methodology']['guardrail']}", "",
    ]
    for company in payload["companies"]:
        totals = company["totals"]
        assessment = company["assessment"]
        lines += [
            f"## {company['ticker']}｜{company['name']}", "",
            f"- **判讀**：{assessment['label']}（信心：{assessment['confidence_label']}）",
            f"- **期間／口徑**：{company['period']} vs {company['comparison_period'] or '無可比期'}；{company['basis']}",
            f"- **合計營收變化**：{fmt(totals['yoy_pct'], '%')}｜[官方來源]({company['source_url']})",
            "", "| 分部／營收來源 | 本期 | 前期 | YoY | 成長貢獻 | 占比 | 利益率／YoY變化 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for row in company["items"]:
            current = amount_label(row["current_revenue"], company["unit"], row["approximate"])
            prior = amount_label(row["prior_revenue"], company["unit"], row["approximate"])
            yoy = fmt(row["yoy_pct"], "%")
            contribution = fmt(row["growth_contribution_pct"], "%")
            share = fmt(row["current_share_pct"], "%")
            margin = fmt(row["current_margin_pct"], "%")
            if row["margin_change_pp"] is not None:
                margin += f" / {fmt(row['margin_change_pp'], 'pp')}"
            lines.append(f"| {row['name']} | {current} | {prior} | {yoy} | {contribution} | {share} | {margin} |")
        lines += ["", "**支持證據**", ""]
        lines += [f"- {item}" for item in assessment["positive_evidence"]] or ["- 可比支持證據不足。"]
        lines += ["", "**風險／限制**", ""]
        lines += [f"- {item}" for item in assessment["risk_evidence"]] or ["- 本期未觸發分部層級風險；仍需搭配公司整體現金流與估值。"]
        lines += ["", "**下期驗證**", ""]
        lines += [f"- {item}" for item in assessment["next_checks"]]
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    args = parser.parse_args()
    payload = build_payload(load_json(args.input))
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(render_markdown(payload))
    print(
        f"分部成長驅動：{payload['tracked_count']} 家；精確貢獻 "
        f"{payload['exact_growth_contribution_count']}；約數 {payload['approximate_growth_contribution_count']}；"
        f"僅方向 {payload['direction_only_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
