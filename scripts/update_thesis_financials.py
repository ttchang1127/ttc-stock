"""Regenerate the quantitative sections of each Master Investment Thesis.

Sections 二 to 五 are rebuilt from the pipeline outputs:

    二  財報體檢與四大模型   fundamentals.json  (SEC XBRL)
    三  Sortino              fundamentals.json  (prices.json returns)
    四  估值倍數與籌碼面      valuation.json     (SEC XBRL + prices.json)
    五  DCF 蒙地卡羅          valuation.json     (+ dcf_assumptions.json)

Section 一 -- the moat and business narrative -- is never touched, nor is any
section beyond 五 (Apple carries a 六). Those are human judgement and no
script should be rewriting them.

Figures the sources cannot supply print 資料不足, and a DCF whose assumptions
are unset prints 假設未設定, so a gap never passes for a verified number.

    python3 scripts/fetch_xbrl_financials.py
    python3 scripts/compute_fundamentals.py
    python3 scripts/compute_valuation.py
    python3 scripts/update_thesis_financials.py [--dry-run]
"""

import argparse
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ANALYSIS_DIR = REPO_ROOT / "30_Analysis"
FUNDAMENTALS_PATH = REPO_ROOT / "fundamentals.json"

# The section emoji is not consistent across the notes -- Apple heads its
# valuation section with 📐 where the others use 🎲 -- so match on the numeral.
SECTION_START = re.compile(r"^## \S* ?二、.*$", re.MULTILINE)
SORTINO_START = re.compile(r"^## \S* ?三、.*$", re.MULTILINE)
MULTIPLES_START = re.compile(r"^## \S* ?四、.*$", re.MULTILINE)
DCF_START = re.compile(r"^## \S* ?五、.*$", re.MULTILINE)
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

    d12 = s.get("12m_daily") or {}
    if d12.get("value") is not None:
        d12_line = (f"- **近 12 個月 Sortino Ratio（日資料，MAR=0）**: **{d12['value']:.2f}**"
                    f"　（{d12['window_start']} ~ {d12['window_end']}，{d12['sessions']} 個交易日）")
        if d12.get("value_vs_riskfree") is not None:
            d12_line += (f"\n  - 若改以無風險利率為門檻（{d12['risk_free_annual']*100:.2f}%，"
                         f"{d12['risk_free_source']}）則為 **{d12['value_vs_riskfree']:.2f}**")
    else:
        d12_line = ("- **近 12 個月 Sortino Ratio（日資料）**: 資料不足"
                    f"（{d12.get('reason', '無資料')}）")

    return "\n".join([
        heading,
        "",
        "> 📌 由 `prices.json` 的實際收盤價計算。下行標準差只計入低於門檻報酬率 (MAR) 的期別，"
        "再年化為 `平均超額報酬 × N ÷ (下行標準差 × √N)`。"
        f"股價資料擷取於 {(prices_meta or {}).get('generated_at', '未知')[:10]}。",
        "",
        "**長期（週資料，MAR = 0）**",
        "",
        row("近 3 年", s.get("3y")),
        row("近 5 年", s.get("5y")),
        "",
        "**對照公開篩選器（日資料）**",
        "",
        d12_line,
        "",
        "> ℹ️ 三個數字衡量的是不同的東西，不能互相驗證：頻率（週／日）、期間（3年／5年／1年）"
        "與門檻報酬率都不同。12 個月日資料那組採 MAR=0，是為了與 PortfoliosLab 等公開網站"
        "的公布值可比對（實測 NVDA、TSLA 皆吻合）。",
        "",
        "---",
        "",
        "",
    ])


def build_multiples_section(heading, val_data, unit):
    m = val_data["multiples"]
    sym = {"USD": "$", "EUR": "€", "TWD": "NT$"}.get(unit, unit + " ")

    def cash(v):
        return "資料不足" if v is None else f"**{sym}{v/1e6:,.0f} 百萬**"

    def yld(v):
        return "資料不足" if v is None else f"**{v*100:.2f}%**"

    pe = "資料不足" if m["pe_ratio"] is None else f"**{m['pe_ratio']:.1f}x**"
    if m.get("pe_note"):
        pe += f"（{m['pe_note']}）"

    return "\n".join([
        heading, "",
        f"> 📌 本節全部由 SEC 財報數字與 `prices.json` 收盤價計算，"
        f"股價為 {val_data.get('price_date')} 之 {sym}{m['price']:,.2f}。", "",
        f"- **稀釋每股盈餘 (EPS)**: "
        + ("資料不足" if m["eps_diluted"] is None else f"**{sym}{m['eps_diluted']:,.2f}**"),
        f"- **本益比 (P/E)**: {pe}",
        f"- **現金與短期投資**: {cash(m['cash_and_st_investments'])}",
        f"- **總債務（長期＋一年內到期）**: {cash(m['total_debt'])}",
        f"- **淨現金 (Net Cash)**: {cash(m['net_cash'])}",
        f"- **庫藏股回購**: {cash(m['buybacks'])}　→ 回購殖利率 {yld(m['buyback_yield'])}",
        f"- **現金股利**: {cash(m['dividends_paid'])}　→ 股利殖利率 {yld(m['dividend_yield'])}",
        f"- **股東總殖利率 (Shareholder Yield)**: {yld(m['shareholder_yield'])}",
        "", "---", "", "",
    ])


def build_dcf_section(heading_text, val_data, unit):
    a = val_data["assumptions"]
    d = val_data.get("dcf")
    sym = {"USD": "$", "EUR": "€", "TWD": "NT$"}.get(unit, unit + " ")
    status = val_data.get("dcf_status")

    # Rewrite the heading so the assumptions it advertises match what was run.
    if a["growth"] is not None and a["wacc"] is not None:
        heading = (f"## 🎲 五、 DCF 蒙地卡羅 {a['simulations']:,} 次估值模擬 "
                   f"(g={a['growth']*100:.1f}%, WACC={a['wacc']*100:.1f}%, "
                   f"終端成長={a['terminal_growth']*100:.1f}%)")
    else:
        heading = "## 🎲 五、 DCF 蒙地卡羅估值模擬（假設未設定）"

    lines = [heading, ""]

    if not d or "p50" not in d:
        lines += [
            f"> ⚠️ **本節未計算**：{status}。",
            "",
            "DCF 需要成長率 (g) 與折現率 (WACC)，兩者皆為判斷而非可從 SEC 推導的事實，"
            "因此必須由人填入 `dcf_assumptions.json`。"
            if status == "假設未設定" else
            f"原因：{status}。腳本不會以假設值代替缺漏資料。",
        ]
        if val_data.get("base_fcf_caveat"):
            lines += ["", f"> ⚠️ {val_data['base_fcf_caveat']}"]
        lines += ["", "---", "", ""]
        return "\n".join(lines)

    lines += [
        f"> 📌 假設來源：`dcf_assumptions.json`（{a.get('note') or '無說明'}）。"
        f"基期自由現金流 {sym}{val_data['base_fcf']/1e6:,.0f} 百萬，"
        f"預測 {a['projection_years']} 年後接終端價值，"
        f"共 {d['simulations_run']:,} 次有效模擬"
        + (f"（{d['simulations_rejected']:,} 次因 WACC ≤ 終端成長率而剔除）"
           if d["simulations_rejected"] else "") + "。",
        "",
        "| 分位 | P5 | P25 | P50 (中位數) | P75 | P95 |",
        "|---|---|---|---|---|---|",
        f"| 每股內在價值 | {sym}{d['p5']:,.2f} | {sym}{d['p25']:,.2f} | "
        f"**{sym}{d['p50']:,.2f}** | {sym}{d['p75']:,.2f} | {sym}{d['p95']:,.2f} |",
        "",
        f"- **平均內在價值**: **{sym}{d['mean']:,.2f}**",
        f"- **50% 主流估值區間 (P25 ~ P75)**: **{sym}{d['p25']:,.2f} ~ {sym}{d['p75']:,.2f}**",
    ]

    price = val_data["multiples"]["price"]
    if price and d["p50"]:
        gap = (price / d["p50"] - 1) * 100
        where = "高於" if gap > 0 else "低於"
        lines.append(f"- **現價 {sym}{price:,.2f} 相對中位數**: {where}中位數 **{abs(gap):.1f}%**")

    implied = (val_data.get("implied_growth") or {}).get("value")
    if implied is not None:
        lines.append(
            f"- **現價隱含的 FCF 年成長率**: **{implied:.1%}**"
            f"（在 WACC {a['wacc']:.2%} 與同組終端假設下，讓模型值等於現價所需的成長率）")
    elif (val_data.get("implied_growth") or {}).get("reason"):
        lines.append(f"- **現價隱含的 FCF 年成長率**: 無解 —— "
                     f"{val_data['implied_growth']['reason']}")

    if val_data.get("base_fcf_caveat"):
        lines += ["", f"> ⚠️ {val_data['base_fcf_caveat']}"]

    # A median far from the quote is nearly always the assumptions talking, not
    # a mispricing. Say so beside the number rather than letting the percentile
    # table read as a price target.
    if val_data.get("credibility_warning"):
        lines += ["", f"> 🚨 **{val_data['credibility_warning']}**"]

    lines += [
        "",
        "> ⚠️ DCF 結果完全取決於上述假設。改變 g 或 WACC 會顯著改變結論，"
        "此處數值僅代表「在該組假設下」的推估，不構成投資建議。",
        "", "---", "", "",
    ]
    return "\n".join(lines)


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
    val_path = REPO_ROOT / "valuation.json"
    valuations = json.loads(val_path.read_text())["companies"] if val_path.exists() else {}

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

        # Sections 三, 四 and 五 are regenerated too. Replace them last-first so
        # earlier offsets stay valid while later sections are being rewritten.
        vdata = valuations.get(ticker)
        unit = data.get("currency") or "USD"

        if vdata:
            d_start = DCF_START.search(new_text)
            if d_start:
                d_next = NEXT_SECTION.search(new_text, d_start.end())
                d_end = d_next.start() if d_next else len(new_text)
                new_text = (new_text[:d_start.start()]
                            + build_dcf_section(d_start.group(0), vdata, unit)
                            + new_text[d_end:])

            m_start = MULTIPLES_START.search(new_text)
            if m_start:
                m_next = NEXT_SECTION.search(new_text, m_start.end())
                m_end = m_next.start() if m_next else len(new_text)
                new_text = (new_text[:m_start.start()]
                            + build_multiples_section(m_start.group(0), vdata, unit)
                            + new_text[m_end:])

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
