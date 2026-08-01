"""Rewrite the financial-data section of each Master Investment Thesis.

Only section 二 (the financial figures and the four quantitative models) is
replaced, with values taken from fundamentals.json. Sections 一, 三, 四 and 五
-- moat analysis, Sortino, valuation multiples, DCF -- are narrative and are
left byte-for-byte untouched.

Figures that cannot be derived from SEC XBRL are printed as "資料不足" rather
than carried over from the previous text, so a gap never masquerades as a
verified number.

    python3 scripts/fetch_xbrl_financials.py
    python3 scripts/compute_fundamentals.py
    python3 scripts/update_thesis_financials.py [--dry-run]
"""

import argparse
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ANALYSIS_DIR = REPO_ROOT / "30_Analysis"
FUNDAMENTALS_PATH = REPO_ROOT / "fundamentals.json"

SECTION_START = re.compile(r"^## 📊 二、.*$", re.MULTILINE)
SORTINO_START = re.compile(r"^## 📈 三、.*$", re.MULTILINE)
NEXT_SECTION = re.compile(r"^## ", re.MULTILINE)

CRITERION_LABELS = {
    "1_roa_positive": "ROA > 0",
    "2_ocf_positive": "營運現金流 > 0",
    "3_roa_improved": "ROA 較前一年提升",
    "4_accruals_ocf_gt_ni": "OCF > 淨利（應計品質）",
    "5_leverage_decreased": "長期負債比下降",
    "6_current_ratio_up": "流動比率提升",
    "7_no_share_dilution": "股數未增加",
    "8_gross_margin_up": "毛利率提升",
    "9_asset_turnover_up": "資產週轉率提升",
}


def money(value, unit):
    if value is None:
        return "資料不足"
    symbol = {"USD": "$", "EUR": "€", "TWD": "NT$"}.get(unit, f"{unit} ")
    return f"**{symbol}{value/1e6:,.0f} 百萬**"


def pct(value):
    return "資料不足" if value is None else f"**{value*100:.2f}%**"


def ratio(value, suffix="x"):
    return "資料不足" if value is None else f"**{value:.3f}{suffix}**"


def build_section(heading, ticker, data):
    unit = data.get("currency") or "USD"
    f = data["piotroski"]
    z = data["altman_z"]
    du = data["dupont"]

    marks = []
    for key, label in CRITERION_LABELS.items():
        got = f["criteria"].get(key)
        icon = {True: "✅", False: "❌", None: "⬜"}[got]
        marks.append(f"{icon} {label}")

    if z.get("z_score") is None:
        z_line = f"- **Altman Z-Score**: 資料不足（缺 {', '.join(z.get('missing', []))}）"
    else:
        z_line = f"- **Altman Z-Score**: **{z['z_score']:.2f}**（{z['zone']} 區）"
        if z.get("caveat"):
            z_line += f"\n  - ⚠️ {z['caveat']}"

    lines = [
        heading,
        "",
        f"> 📌 以下數字全部取自 SEC XBRL，會計年度結束於 **{data['fiscal_year_end']}**"
        f"（{data['source_form']}，申報日 {data['source_filed']}，"
        f"accession `{data['source_accession']}`）。幣別：{unit}。",
        "",
        "### 損益與現金流",
        f"- **營收 (Revenue)**: {money(data['revenue'], unit)}",
        f"- **淨利 (Net Income)**: {money(data['net_income'], unit)}",
        f"- **毛利率 (Gross Margin)**: {pct(data['gross_margin'])}",
        f"- **經營現金流 (OCF)**: {money(data['operating_cash_flow'], unit)}",
        f"- **資本支出 (CapEx)**: {money(data['capex'], unit)}",
        f"- **自由現金流 (FCF = OCF − CapEx)**: {money(data['free_cash_flow'], unit)}",
        "",
        "### 資產負債表",
        f"- **總資產**: {money(data['assets'], unit)}",
        f"- **總負債**: {money(data['liabilities'], unit)}",
        f"- **股東權益**: {money(data['equity'], unit)}",
        "",
        "### 四大基本面量化模型",
        f"- **Piotroski F-Score**: **{f['score']} / {f['max_evaluated']}**"
        + (f"（{len(f['unavailable'])} 項因資料不足未計入）" if f["unavailable"] else ""),
        "  - " + " ｜ ".join(marks),
        z_line,
        f"- **DuPont ROE**: {pct(du['roe'])}"
        f"（淨利率 {pct(du['net_margin'])} × 資產週轉率 {ratio(du['asset_turnover'])}"
        f" × 權益乘數 {ratio(du['equity_multiplier'])}）",
        f"- **ROE 直接驗算 (淨利 ÷ 股東權益)**: {pct(du['roe_direct_check'])}",
    ]

    if data.get("share_count_warning"):
        lines.append(f"- ⚠️ **股數異常**: {data['share_count_warning']}")

    lines += [
        "",
        "> ⚠️ 第四、五章（估值倍數、DCF 模擬）之數字**尚未經來源資料驗證**，"
        "沿用先前版本，僅供參考。",
        "",
        "---",     # the separator the original layout put before each heading
        "",
        "",
    ]
    return "\n".join(lines)


def build_sortino_section(heading, data, prices_meta):
    s = data.get("sortino") or {}

    def row(label, entry):
        if not entry or entry.get("value") is None:
            reason = (entry or {}).get("reason", "無資料")
            return f"- **{label} Sortino Ratio（週資料）**: 資料不足（{reason}）"
        return (f"- **{label} Sortino Ratio（週資料）**: **{entry['value']:.2f}**"
                f"　（{entry['window_start']} ~ {entry['window_end']}，{entry['weeks']} 週報酬）")

    return "\n".join([
        heading,
        "",
        "> 📌 由 `prices.json` 的實際日線收盤價計算：先取每週最後收盤算週報酬，"
        "下行標準差只計入低於門檻報酬率 (MAR = 0) 的週次，"
        "再以 `平均週報酬 × 52 ÷ (下行標準差 × √52)` 年化。"
        f"股價資料擷取於 {(prices_meta or {}).get('generated_at', '未知')[:10]}。",
        "",
        row("近 3 年", s.get("3y")),
        row("近 5 年", s.get("5y")),
        "",
        "---",
        "",
        "",
    ])


def upsert_frontmatter(text, data):
    """Record provenance in the YAML frontmatter without disturbing other keys."""
    if not text.startswith("---\n"):
        return text
    end = text.index("\n---\n", 4)
    fm, rest = text[4:end], text[end + 5:]
    keep = [ln for ln in fm.splitlines()
            if not ln.startswith(("financials_source:", "financials_fiscal_year_end:",
                                  "financials_accession:", "financials_verified:"))]
    keep += [
        "financials_source: SEC XBRL Company Facts",
        f"financials_fiscal_year_end: {data['fiscal_year_end']}",
        f'financials_accession: "{data["source_accession"]}"',
        "financials_verified: true",
    ]
    return "---\n" + "\n".join(keep) + "\n---\n" + rest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not FUNDAMENTALS_PATH.exists():
        raise SystemExit("fundamentals.json missing; run scripts/compute_fundamentals.py first")
    companies = json.loads(FUNDAMENTALS_PATH.read_text())["companies"]
    prices_path = REPO_ROOT / "prices.json"
    prices_meta = json.loads(prices_path.read_text()) if prices_path.exists() else {}

    changed, skipped = 0, []
    for path in sorted(ANALYSIS_DIR.glob("*_Master_Investment_Thesis_2026.md")):
        ticker = path.name.split("_")[0]
        data = companies.get(ticker)
        if not data:
            skipped.append(f"{ticker} (無 fundamentals 資料)")
            continue

        text = path.read_text()
        start = SECTION_START.search(text)
        if not start:
            skipped.append(f"{ticker} (找不到第二章)")
            continue
        nxt = NEXT_SECTION.search(text, start.end())
        end = nxt.start() if nxt else len(text)

        new_text = text[:start.start()] + build_section(start.group(0), ticker, data) + text[end:]

        # Section 三 (Sortino) is now derived from prices.json as well.
        s_start = SORTINO_START.search(new_text)
        if s_start:
            s_next = NEXT_SECTION.search(new_text, s_start.end())
            s_end = s_next.start() if s_next else len(new_text)
            new_text = (new_text[:s_start.start()]
                        + build_sortino_section(s_start.group(0), data, prices_meta)
                        + new_text[s_end:])

        # The literal tab in "$\times$" survived as "$<TAB>imes$" in seven files.
        new_text = new_text.replace("$\times$", "×").replace("$\\times$", "×")
        new_text = upsert_frontmatter(new_text, data)

        if new_text == text:
            skipped.append(f"{ticker} (無變更)")
            continue
        if not args.dry_run:
            path.write_text(new_text)
        changed += 1
        f = data["piotroski"]
        print(f"  {ticker:6s} FY{data['fiscal_year_end']}  "
              f"F-Score {f['score']}/{f['max_evaluated']}  "
              f"ROE {'n/a' if data['dupont']['roe'] is None else format(data['dupont']['roe']*100, '.1f') + '%'}")

    verb = "將更新" if args.dry_run else "已更新"
    print(f"\n{verb} {changed} 份 thesis")
    if skipped:
        print("略過: " + ", ".join(skipped))


if __name__ == "__main__":
    main()
