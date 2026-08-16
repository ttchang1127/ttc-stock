"""Generate the standalone *_report.html pages from the pipeline's JSON.

The thirteen report pages in the repo root were written by hand and read no
data at all -- every figure was typed into the HTML. They were last touched on
2026-08-01 and had been drifting ever since: Alphabet's net cash still said
$78.3bn against a corrected $75.8bn, its 12-month Sortino still said 3.73
against 3.47, and neither would ever have caught up, because nothing was
maintaining them.

Worse than stale numbers, they carried claims nothing could check. Alphabet's
page and Microsoft's page both called their company "全美股第 1 大 OCF 現金流
巨獸"; only one of them can be, and on the data here it is Microsoft. Alphabet
claimed the portfolio's best 12-month Sortino at 3.73 while Intel's page
claimed the same title at 4.45.

So the split here is deliberate:

  Quantitative sections are generated from fundamentals.json, valuation.json,
  financial_health.json and financials.json. They cannot drift, because they
  are not stored.

  Narrative sections (the moat, the risks) are human-written and come from the
  thesis markdown rather than being duplicated here -- one source, edited in
  one place.

  Comparative claims are computed. A page may say "本組合第 2" because that is
  a rank over the fourteen companies in this vault and the rank is recomputed
  every build. It may not say "全美股第 1", because nothing here observes the
  whole US market. check_unverifiable_claims() reports any that survive in the
  narrative so they can be fixed at the source.

    python3 scripts/build_reports.py
    python3 scripts/build_reports.py --tickers NVDA GOOGL
"""

import argparse
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from risk_translations import load as load_translations, lookup as lookup_translation

REPO_ROOT = Path(__file__).resolve().parent.parent
THESIS_DIR = REPO_ROOT / "30_Analysis"

# The existing files use GOOG for Alphabet; keep every URL that already exists.
# Amazon never had a page, so it gets the obvious name.
SLUGS = {
    "AAPL": "aapl", "AMZN": "amzn", "ARM": "arm", "COHR": "cohr",
    "GOOGL": "goog", "INTC": "intc", "META": "meta", "MRVL": "mrvl",
    "MSFT": "msft", "NOK": "nok", "NVDA": "nvda", "ONDS": "onds",
    "TSLA": "tsla", "TSM": "tsm",
}

# Superlatives that no data in this vault can settle. Rankings over the
# fourteen tracked companies are fine and are generated; these are not.
UNVERIFIABLE = re.compile(
    r"全美股第 ?1|全球第 ?1|世界冠軍|史上最|無可匹敵|無與倫比|人類.{0,6}最")

# Plain-language definitions shown when a reader hovers, focuses, or taps a
# financial term. Thresholds describe this report's screening rules, not
# universal investment conclusions.
FINANCIAL_TERMS = {
    "現價 / 本益比": (
        "本益比（P/E）＝股價 ÷ 每股盈餘，代表市場願意為每 1 元當期盈餘支付多少倍價格。"
        "高倍數通常反映較高成長期待，也可能代表估值容錯率較低；應與同產業及公司自身歷史比較。"),
    "流動比率": (
        "流動資產 ÷ 流動負債，衡量一年內資產覆蓋一年內到期債務的能力。"
        "1.0 代表兩者相當；本頁低於 1.0 會警示，但仍須考慮產業的現金週轉特性。"),
    "現金比率": (
        "現金與短期投資 ÷ 流動負債。只用最接近現金的資產檢視短期償債能力，"
        "比流動比率更保守；過高也可能表示資金運用效率偏低。"),
    "負債佔資產": (
        "總負債 ÷ 總資產，衡量資產中有多少比例由負債支應。"
        "數值越高通常代表槓桿越高；本頁高於 60% 會警示，但仍應與同產業資本結構比較。"),
    "有息負債／淨值": (
        "會產生利息的負債 ÷ 股東權益，顯示公司以借款相對於自有資本融資的程度。"
        "數值越高，通常對利率與現金流變化越敏感。"),
    "利息保障倍數": (
        "營業利益（EBIT）÷ 利息費用，衡量本業獲利可支付幾倍利息。"
        "本頁低於 3 倍會警示；無債或利息極低時可能出現異常高值，需配合註記判讀。"),
    "ROIC": (
        "投入資本報酬率，衡量公司使用營運所需的債務與股東資本創造稅後營業利潤的效率。"
        "長期高於 WACC 通常表示公司正在創造經濟價值。"),
    "ROIC − WACC": (
        "ROIC 減去加權平均資本成本。正值表示投入資本報酬高於資金成本；負值表示尚未覆蓋。"
        "pp 是百分點，例如 12% − 8% = 4pp。"),
    "ROIC−WACC 價差": (
        "ROIC 減去 WACC 的百分點差距。正值越大，代表當期投入資本報酬高於資金成本的幅度越大。"),
    "FCF 利潤率": (
        "自由現金流 ÷ 營收，衡量每 1 元營收在支付營運與資本支出後還能保留多少現金。"
        "負值表示當期自由現金流為負。"),
    "應計比率": (
        "（淨利 − 營運現金流）÷ 平均總資產。正值過高代表會計利潤明顯超前現金流，"
        "需檢查應收款、存貨與一次性項目；本頁高於 10% 會警示。"),
    "Altman Z''": (
        "Altman Z-double-prime 是適用於非製造業的財務困境篩選模型。"
        "本頁以 >2.6 為安全區、1.1–2.6 為灰色區、<1.1 為危險區；它不是違約機率。"),
    "Piotroski（標準化 /9）": (
        "Piotroski F-Score 從獲利、槓桿／流動性與營運效率檢查最多 9 項財報訊號。"
        "本頁將可計算項目標準化到 9 分；高分不代表股價便宜。"),
    "F-Score（標準化）": (
        "Piotroski F-Score 的 9 分標準化結果。資料缺項時是依已計算項目換算，"
        "不表示原始 9 項都有資料。"),
    "Beneish M-Score": (
        "以八個會計指標篩選盈餘操縱型態的統計模型。高於 -1.78 本頁會警示，"
        "但不是舞弊指控；高速成長公司容易出現偽陽性，必須回查原始財報。"),
    "營收": "期間內銷售商品或服務所認列的收入，尚未扣除各類成本與費用。",
    "淨利": "營收扣除營業成本、業外收支、利息與所得稅後的最終會計利潤。",
    "毛利率": (
        "（營收 − 銷貨成本）÷ 營收，反映定價、產品組合與直接成本控制能力；"
        "應與同產業及公司自身歷史比較。"),
    "營運現金流": "核心營運活動實際流入或流出的現金，可用來對照淨利的現金含量。",
    "資本支出": "購置或建置廠房、設備等長期資產的現金支出，通常用於維持或擴充產能。",
    "自由現金流": (
        "本頁定義為營運現金流 − 資本支出，代表投資營運後可用於還債、回購、股利或再投資的現金。"),
    "總資產": "資產負債表上由公司控制、預期帶來未來經濟效益的資源總額。",
    "總負債": "公司對債權人與其他外部相對人的義務總額，不只包含會產生利息的借款。",
    "股東權益": "總資產減去總負債後歸屬股東的帳面淨值。",
    "DuPont 三因子拆解": (
        "將 ROE 拆為淨利率 × 資產週轉率 × 權益乘數，用來判斷股東報酬來自獲利、資產效率或槓桿。"),
    "蒙地卡羅 DCF": (
        "在成長率與 WACC 等假設上進行多次隨機模擬的現金流折現法。"
        "輸出是特定假設下的分佈，不是必然會達到的目標價。"),
    "P25 ~ P75 主流區間": (
        "蒙地卡羅結果的第 25 至第 75 百分位，中間 50% 模擬結果落在此區間；"
        "它反映假設分佈，不是統計上的置信區間。"),
    "中位數 P50": "蒙地卡羅結果的第 50 百分位，一半模擬值高於它、一半低於它；不等於目標價。",
    "相對現價": (
        "DCF 中位數相對目前股價的差幅。差距過大常表示模型假設與市場預期分歧，不應直接當作漲跌空間。"),
    "現價隱含 FCF 年成長率": (
        "在其他 DCF 假設不變時，反推出市場現價所要求的自由現金流年成長率，用來檢驗市場預期是否合理。"),
    "Sortino Ratio": (
        "超額報酬 ÷ 下行偏差，只將低於門檻報酬的波動視為風險。"
        "同期間、同頻率、同門檻下數值越高通常越好；不同口徑不可直接比較。"),
    "12 個月 Sortino": (
        "近 12 個月的 Sortino Ratio；本頁以含股息調整後日報酬、MAR=0 計算，衡量每單位下行風險對應的報酬。"),
    "近 3 年（週資料）": "以近 3 年含股息調整後週報酬計算的 Sortino Ratio，須與相同期間、頻率與門檻的結果比較。",
    "近 5 年（週資料）": "以近 5 年含股息調整後週報酬計算的 Sortino Ratio，涵蓋較多市場循環，但仍受期間選擇影響。",
    "近 12 個月（日資料 MAR=0）": "以近 12 個月含股息調整後日報酬、最低可接受報酬 MAR=0 計算的 Sortino Ratio。",
    "同期無風險門檻版本": (
        "以同期無風險利率作為最低可接受報酬的 Sortino Ratio，與 MAR=0 版本的口徑不同。"),
    "稀釋每股盈餘": (
        "淨利除以計入選擇權、可轉換證券等潛在稀釋效果後的加權平均股數。"),
    "現金與短期投資": (
        "現金、約當現金及流動性高的短期投資合計，是計算淨現金與企業價值的扣除項。"),
    "有息負債總額": (
        "借款、公司債、融資租賃等需支付利息的債務總額，不等於資產負債表的總負債。"),
    "淨現金": "現金與短期投資減去有息負債。正值表示現金超過有息負債；負值則是淨負債。",
    "庫藏股回購": (
        "公司使用現金買回自家股票的金額。回購可減少股數，但是否創造價值仍取決於回購價格。"),
    "現金股利": "公司以現金直接分配給股東的金額。",
    "股東總殖利率": (
        "（回購金額＋現金股利）÷ 市值，衡量當期透過回購與股利返還股東的比例；不包含股價漲跌。"),
    "EV/EBITDA": (
        "企業價值（EV）÷ 息稅折舊攤銷前利潤（EBITDA）。EV 約等於市值＋有息負債−現金與短期投資；"
        "數值表示企業總價值是當期 EBITDA 的幾倍。較低可能較便宜，也可能反映低成長或高風險；"
        "必須與同產業、相似資本密集度的公司比較，且 EBITDA 不等於現金流。"),
    "營收年增率": "本季營收相對上一年度同季的變化率，可排除多數季節性，但仍會受到併購、匯率與會計口徑改變影響。",
    "FCF 利潤率（單季）": "單季自由現金流 ÷ 單季營收。單季現金流波動通常較大，應搭配八季趨勢與全年數字判讀。",
    "稀釋股數年增率": "本季稀釋加權平均股數相對上一年度同季的變化；正值表示每股權益可能受到稀釋，負值通常反映淨回購。",
    "反向 DCF": (
        "固定其他估值假設後，反推出目前股價需要自由現金流達成的年成長率。"
        "它回答市場已經計入什麼，不是公司指引或預測。"),
    "情境預測": (
        "以明確假設建立悲觀、基準與樂觀路徑。此處是敏感度分析，不是管理層指引、分析師共識或目標價。"),
}


def term_label(label):
    """Return an accessible hover/focus/tap target for known finance terms."""
    shown = html.escape(label)
    explanation = FINANCIAL_TERMS.get(label)
    if not explanation:
        return shown
    escaped = html.escape(explanation, quote=True)
    aria = html.escape(f"{label}：{explanation}", quote=True)
    return (f'<span class="fin-term" tabindex="0" data-tooltip="{escaped}" '
            f'aria-label="{aria}">{shown}<span class="term-icon" '
            f'aria-hidden="true">i</span></span>')


# --------------------------------------------------------------------------
# data access

def load(name):
    path = REPO_ROOT / name
    if not path.exists():
        raise SystemExit(f"{name} missing; run the earlier pipeline steps first")
    return json.loads(path.read_text())


def fmt_money(v, unit="USD", scale=1e6, suffix="M"):
    if v is None:
        return "資料不足"
    return f"${v / scale:,.0f}{suffix}" if unit == "USD" else f"{v / scale:,.0f}{suffix} {unit}"


def fmt_pct(v, places=2):
    return "資料不足" if v is None else f"{v * 100:.{places}f}%"


def fmt_num(v, places=2, suffix=""):
    return "資料不足" if v is None else f"{v:,.{places}f}{suffix}"


# --------------------------------------------------------------------------
# narrative, taken from the thesis rather than duplicated

def thesis_path(ticker):
    return THESIS_DIR / f"{ticker}_Master_Investment_Thesis_2026.md"


def split_sections(markdown):
    """Return {leading number: (heading, body)} for each `## ` section."""
    out = {}
    parts = re.split(r"^## ", markdown, flags=re.M)[1:]
    for part in parts:
        heading, _, body = part.partition("\n")
        num = re.search(r"[一二三四五六七]", heading)
        if num:
            out[num.group(0)] = (heading.strip(), body.strip())
    return out


def md_inline(text):
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    # Wiki links point at vault notes that do not exist on the public site.
    text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    return text


def md_to_html(body):
    """Render the subset of markdown the narrative sections actually use.

    An <li> stays open while its nested list is emitted, so a sub-list lands
    inside its parent item rather than as a sibling of it. `<ul>` directly
    inside `<ol>` is invalid even though browsers tolerate it, and it also
    restarted the numbering on every moat entry.
    """
    out, stack = [], []          # each level in stack has an <li> currently open

    def close_levels(target):
        while len(stack) > target:
            out.append("</li>")
            out.append(f"</{stack.pop()}>")

    for raw in body.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            continue
        # The thesis separates sections with a horizontal rule, which lands at
        # the end of every extracted body; it is a document divider, not content.
        if set(line.strip()) <= {"-", "*", "_"} and len(line.strip()) >= 3:
            continue
        if line.startswith("### "):
            close_levels(0)
            out.append(f'<h4 class="sub-heading">{md_inline(line[4:])}</h4>')
            continue
        if line.startswith("> "):
            close_levels(0)
            out.append(f'<p class="note">{md_inline(line[2:])}</p>')
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        ordered = re.match(r"^(\d+)\.\s+(.*)$", stripped)
        bullet = stripped.startswith("- ")
        if not (ordered or bullet):
            close_levels(0)
            out.append(f"<p>{md_inline(stripped)}</p>")
            continue

        tagname = "ol" if ordered else "ul"
        depth = 1 if indent == 0 else 2
        close_levels(depth)
        if len(stack) == depth and stack[-1] != tagname:
            close_levels(depth - 1)
        depth = min(depth, len(stack) + 1)      # no skipping a level
        content = md_inline(ordered.group(2) if ordered else stripped[2:])

        if len(stack) < depth:
            stack.append(tagname)
            out.append(f"<{tagname}><li>{content}")
        else:
            out.append(f"</li><li>{content}")

    close_levels(0)
    return "\n".join(out)


FILINGS_DIR = REPO_ROOT / "20_Filings"


def risk_source(ticker):
    """The most recent Item 1A / Item 3.D extract on file, if there is one.

    The risk chapter is written by a human and until now cited nothing. The
    filing text it summarises is in the vault -- fetch_sec.py splits it out --
    but nothing read it, so the section claiming to follow Item 1A had no way
    to be checked against Item 1A. This does not replace the narrative; it
    states which document it is a reading of, and links to SEC's own copy.
    """
    candidates = sorted(FILINGS_DIR.glob(f"{ticker}/sections/{ticker}_*_Item_*Risk_Factors.md"))
    if not candidates:
        return None
    latest = candidates[-1]
    text = latest.read_text()
    def field(name):
        m = re.search(rf"^{name}:\s*\"?([^\"\n]+)\"?\s*$", text, re.M)
        return m.group(1).strip() if m else None
    url = re.search(r"\[SEC 線上檢視器\]\(([^)]+)\)", text)
    # 10-K filers carry risk factors under Item 1A, 20-F filers under Item 3.D.
    # Naming the wrong item would misdescribe the very thing this block exists
    # to make checkable, so take it from the extract rather than assuming.
    slug = field("section") or ""
    item = "Item 3.D" if "3D" in slug else "Item 1A"
    return {
        "path": str(latest.relative_to(REPO_ROOT)),
        "year": field("year"),
        "form": field("form_type"),
        "item": item,
        "characters": int(field("characters") or 0),
        "sec_url": url.group(1) if url else None,
    }


def risk_provenance_html(ticker):
    src = risk_source(ticker)
    if not src:
        return ('<p class="note">⚠️ 本公司的 Item 1A 原文尚未成功拆解（申報文件的章節標題'
                '格式非標準），因此以下敘述目前無法對照原文。</p>')
    link = (f'<a href="{html.escape(src["sec_url"])}" target="_blank" rel="noopener">'
            f'SEC 官方原文</a>') if src["sec_url"] else "SEC 官方原文"
    return ('<p class="note">📄 本節為分析者從 <strong>{form} {item} 風險因素</strong>'
            '（{year} 年度，原文 {chars:,} 字元）中挑選並改寫的三項重點，'
            '<strong>不是原文摘要，也不是全部風險</strong>。原文拆解存於 <code>{path}</code>，'
            '完整內容請看 {link}。</p>'
            .format(form=html.escape(src["form"] or ""), item=src["item"],
                    year=html.escape(src["year"] or ""),
                    chars=src["characters"], path=html.escape(src["path"]), link=link))


def risk_change_html(entry):
    """What the company started and stopped warning about since last year."""
    if not entry:
        return ('<p class="note">尚未產生年度比對（risk_changes.json 不存在或未涵蓋本公司）。</p>')
    if entry.get("status") != "已比較":
        return ('<p class="note">⚠️ 無法比對：{}。年度比對需要至少兩個年度的原文拆解。</p>'
                .format(html.escape(entry.get("reason") or "原因不明")))

    store = load_translations()

    def entry_html(paragraph, sign, colour):
        """譯文在前、原文收在 <details> 裡。原文永遠附上，不被譯文取代。"""
        piece, zh = lookup_translation(store, paragraph)
        original = html.escape(" ".join(paragraph.split()))
        if zh:
            head = html.escape(zh)
            tail = ('<details style="margin-top:4px;"><summary style="color:#94a3b8; '
                    'cursor:pointer; font-size:0.85em;">原文</summary>'
                    f'<div style="color:#94a3b8; font-size:0.88em; margin-top:4px;">'
                    f'{original}</div></details>')
        else:
            # 新申報書一定會帶進沒翻過的段落。顯示原文並說明，不留白，
            # 也不用機器直譯充數。
            head = (html.escape(piece)
                    + ' <span style="color:#94a3b8; font-size:0.85em;">（尚未翻譯）</span>')
            tail = ""
        return (f'<li style="color:{colour}; margin:10px 0;">{sign} {head}{tail}</li>')

    def items(paras, sign, colour):
        if not paras:
            return f'<li style="color:#94a3b8;">{sign} 無</li>'
        shown = paras[:5]
        out = "".join(entry_html(p, sign, colour) for p in shown)
        if len(paras) > len(shown):
            out += (f'<li style="color:#94a3b8;">…另有 {len(paras) - len(shown)} 段，'
                    f'完整內容見原文拆解檔</li>')
        return out

    return (
        '<div class="metric-group">'
        + metric("上年度段落數", str(entry["paragraphs_previous"]))
        + metric("本年度段落數", str(entry["paragraphs_latest"]))
        + metric("新增", str(len(entry["added"])), "warn" if entry["added"] else "")
        + metric("刪除", str(len(entry["removed"])), "warn" if entry["removed"] else "")
        + '</div>'
        + f'<h4 class="sub-heading">＋ 本年度新增（FY{entry["previous_year"]} → FY{entry["latest_year"]}）</h4>'
        + f'<ul>{items(entry["added"], "＋", "#fbbf24")}</ul>'
        + '<h4 class="sub-heading">− 本年度不再列出</h4>'
        + f'<ul>{items(entry["removed"], "−", "#38bdf8")}</ul>'
        + f'<p class="note">{html.escape(entry["caveat"])} 判定方式：{html.escape(entry["basis"])}。'
          f'其餘 {entry["unchanged"]} 段沿用、{entry["reworded"]} 段改寫。</p>'
        + '<p class="note">🈯 中文為申報書原文段落開頭的譯文，收錄於 <code>risk_zh.json</code>，'
          '<strong>是轉述而非官方翻譯</strong>；每段都附「原文」可展開對照，判讀請以原文為準。'
          '譯文以原文的雜湊為鍵，申報書一改動，舊譯文即失效並顯示「尚未翻譯」。</p>')


def check_unverifiable_claims(ticker, sections):
    """Superlatives in the narrative that no data here can support."""
    found = []
    for key in ("一", "六"):
        if key not in sections:
            continue
        for line in sections[key][1].split("\n"):
            for m in UNVERIFIABLE.finditer(line):
                start = max(0, m.start() - 12)
                found.append(line.strip()[start:m.end() + 14])
    return found


# --------------------------------------------------------------------------
# comparative claims, computed rather than asserted

def build_ranks(fundamentals, health):
    """Rank each company within the vault on the metrics worth comparing."""
    def rank_on(getter, label, higher_better=True):
        rows = []
        for t in fundamentals:
            v = getter(t)
            if v is not None:
                rows.append((t, v))
        rows.sort(key=lambda r: -r[1] if higher_better else r[1])
        return {t: (i + 1, len(rows), v, label) for i, (t, v) in enumerate(rows)}

    f, h = fundamentals, health
    return {
        "ocf": rank_on(lambda t: f[t].get("operating_cash_flow"), "營運現金流"),
        "gross_margin": rank_on(lambda t: f[t].get("gross_margin"), "毛利率"),
        "roic": rank_on(lambda t: h[t]["profitability"]["roic"], "ROIC"),
        "spread": rank_on(lambda t: h[t]["profitability"]["roic_minus_wacc"], "ROIC−WACC 價差"),
        "sortino": rank_on(lambda t: f[t]["sortino"]["12m_daily"].get("value"),
                           "12 個月 Sortino"),
        "fscore": rank_on(lambda t: h[t]["piotroski"]["normalised_9"], "F-Score（標準化）"),
        "z2": rank_on(lambda t: h[t]["altman_z2"].get("z2_score"), "Altman Z''"),
    }


def rank_cards(ticker, ranks):
    cards = []
    for key in ("ocf", "gross_margin", "roic", "spread", "sortino", "fscore", "z2"):
        hit = ranks[key].get(ticker)
        if not hit:
            continue
        pos, total, value, label = hit
        if key in ("gross_margin",):
            shown = fmt_pct(value, 1)
        elif key in ("roic", "spread"):
            shown = fmt_pct(value, 1)
        elif key == "ocf":
            shown = fmt_money(value)
        else:
            shown = fmt_num(value)
        medal = "🥇" if pos == 1 else "🥈" if pos == 2 else "🥉" if pos == 3 else ""
        cards.append(
            f'<div class="rank-card"><div class="rank-label">{term_label(label)}</div>'
            f'<div class="rank-pos">{medal} 第 {pos} / {total}</div>'
            f'<div class="rank-val">{shown}</div></div>')
    return "\n".join(cards)


# --------------------------------------------------------------------------
# generated sections

def kpi(label, value, sub=""):
    return (f'<div class="kpi-box"><div class="kpi-label">{term_label(label)}</div>'
            f'<div class="kpi-val">{value}</div>'
            f'<div class="kpi-sub">{html.escape(sub)}</div></div>')


def metric(label, value, tone=""):
    cls = f"metric-card {tone}".strip()
    return (f'<div class="{cls}"><div class="title">{term_label(label)}</div>'
            f'<div class="value">{value}</div></div>')


def health_section(h):
    liq, sol = h["liquidity"], h["solvency"]
    prof, cfq = h["profitability"], h["cash_flow_quality"]
    z2, fs, m = h["altman_z2"], h["piotroski"], h["beneish_m"]

    def tone_if(cond):
        return "warn" if cond else ""

    cards = [
        metric("流動比率", fmt_num(liq["current_ratio"]),
               tone_if(liq["current_ratio"] is not None and liq["current_ratio"] < 1)),
        metric("現金比率", fmt_num(liq["cash_ratio"])),
        metric("負債佔資產", fmt_pct(sol["liabilities_to_assets"], 1),
               tone_if((sol["liabilities_to_assets"] or 0) > 0.60)),
        metric("有息負債／淨值", fmt_num(sol["debt_to_equity"])),
        metric("利息保障倍數",
               "資料不足" if sol["interest_coverage"] is None
               else fmt_num(sol["interest_coverage"], 1, "x"),
               tone_if(sol["interest_coverage"] is not None and sol["interest_coverage"] < 3)),
        metric("ROIC", fmt_pct(prof["roic"], 1)),
        metric("ROIC − WACC",
               "資料不足" if prof["roic_minus_wacc"] is None
               else f"{prof['roic_minus_wacc'] * 100:+.1f}pp",
               tone_if((prof["roic_minus_wacc"] or 0) < 0)),
        metric("FCF 利潤率", fmt_pct(cfq["fcf_margin"], 1),
               tone_if((cfq["fcf_margin"] or 0) < 0)),
        metric("應計比率",
               "資料不足" if cfq["accrual_ratio"] is None
               else f"{cfq['accrual_ratio'] * 100:+.1f}%",
               tone_if((cfq["accrual_ratio"] or 0) > 0.10)),
        metric("Altman Z''",
               "資料不足" if z2.get("z2_score") is None
               else f"{z2['z2_score']:.2f}（{z2['zone']}）",
               tone_if(z2.get("zone") in ("grey", "distress"))),
        metric("Piotroski（標準化 /9）", fmt_num(fs["normalised_9"], 1)),
        metric("Beneish M-Score",
               "資料不足" if m.get("m_score") is None else fmt_num(m["m_score"]),
               tone_if(m.get("flagged"))),
    ]

    flags = h["flags"]
    if flags:
        items = "\n".join(
            f'<li><strong>{html.escape(f["dimension"])}</strong>：{html.escape(f["detail"])}</li>'
            for f in flags)
        flag_html = f'<div class="flag-box"><h4>⚠️ 觸發 {len(flags)} 項門檻</h4><ul>{items}</ul></div>'
    else:
        cov = h["coverage"]
        if cov["sufficient"]:
            flag_html = ('<div class="flag-box ok"><h4>✅ 未觸發任何門檻</h4>'
                         f'<p>{cov["computed"]} / {cov["total"]} 項指標均已計算。</p></div>')
        else:
            flag_html = ('<div class="flag-box"><h4>⚠️ 資料不足，無法判定</h4>'
                         f'<p>{html.escape(cov["note"])}：'
                         f'{html.escape("、".join(cov["unavailable"]))}</p></div>')

    return f'<div class="metric-group">{"".join(cards)}</div>{flag_html}'


def qvalue(period, metric):
    """Read both SEC fact objects and official-IR scalar quarterly values."""
    value = (period.get("values") or {}).get(metric)
    return value.get("value") if isinstance(value, dict) else value


def compact_money(value, currency="USD"):
    if value is None:
        return "—"
    absolute = abs(value)
    if absolute >= 1e12:
        shown = f"{value / 1e12:,.2f}T"
    elif absolute >= 1e9:
        shown = f"{value / 1e9:,.2f}B"
    elif absolute >= 1e6:
        shown = f"{value / 1e6:,.1f}M"
    else:
        shown = f"{value:,.0f}"
    return f"{currency} {shown}"


def quarter_metrics(company):
    """Normalise the newest eight comparable quarters and add YoY fields."""
    periods = (company or {}).get("periods", [])[:8]
    result = []
    for index, period in enumerate(periods):
        revenue = qvalue(period, "revenue")
        fcf = qvalue(period, "free_cash_flow")
        row = {
            "period": period,
            "revenue": revenue,
            "gross_margin": qvalue(period, "gross_margin"),
            "operating_margin": qvalue(period, "operating_margin"),
            "fcf": fcf,
            "fcf_margin": fcf / revenue if revenue not in {None, 0} and fcf is not None else None,
            "shares": qvalue(period, "diluted_shares"),
        }
        if index + 4 < len(periods):
            prior = periods[index + 4]
            prior_revenue = qvalue(prior, "revenue")
            prior_shares = qvalue(prior, "diluted_shares")
            row["revenue_yoy"] = (
                revenue / prior_revenue - 1
                if revenue is not None and prior_revenue not in {None, 0} else None)
            row["shares_yoy"] = (
                row["shares"] / prior_shares - 1
                if row["shares"] is not None and prior_shares not in {None, 0} else None)
            prior_fcf = qvalue(prior, "free_cash_flow")
            row["prior_fcf_margin"] = (
                prior_fcf / prior_revenue
                if prior_revenue not in {None, 0} and prior_fcf is not None else None)
            row["prior_gross_margin"] = qvalue(prior, "gross_margin")
            row["prior_operating_margin"] = qvalue(prior, "operating_margin")
        result.append(row)
    return result


def trend_score(rows):
    """Return a transparent directional score based on the latest YoY quarter."""
    if not rows:
        return "資料不足", 0, []
    latest = rows[0]
    checks = []

    def add(label, value, threshold):
        if value is None:
            checks.append((label, None))
        elif value > threshold:
            checks.append((label, 1))
        elif value < -threshold:
            checks.append((label, -1))
        else:
            checks.append((label, 0))

    add("營收年增", latest.get("revenue_yoy"), .03)
    gm = latest.get("gross_margin")
    pgm = latest.get("prior_gross_margin")
    add("毛利率年變化", gm - pgm if gm is not None and pgm is not None else None, .01)
    om = latest.get("operating_margin")
    pom = latest.get("prior_operating_margin")
    add("營業利益率年變化", om - pom if om is not None and pom is not None else None, .01)
    fm = latest.get("fcf_margin")
    pfm = latest.get("prior_fcf_margin")
    add("FCF 利潤率年變化", fm - pfm if fm is not None and pfm is not None else None, .02)
    shares = latest.get("shares_yoy")
    checks.append(("股數年變化", None if shares is None else (-1 if shares > .05 else 1 if shares < -.01 else 0)))
    usable = [score for _, score in checks if score is not None]
    score = sum(usable)
    label = "改善" if score >= 2 else "轉弱" if score <= -2 else "持平／分歧"
    return label, score, checks


def quarterly_trend_section(company):
    rows = quarter_metrics(company)
    currency = (company or {}).get("currency") or "USD"
    label, score, checks = trend_score(rows)
    tone = "ok" if label == "改善" else "warn" if label == "轉弱" else ""
    summary = metric("八季營運方向", label, tone)
    latest = rows[0] if rows else {}
    summary += metric("營收年增率", fmt_pct(latest.get("revenue_yoy"), 1))
    summary += metric("FCF 利潤率（單季）", fmt_pct(latest.get("fcf_margin"), 1))
    summary += metric("稀釋股數年增率", fmt_pct(latest.get("shares_yoy"), 1),
                      "warn" if (latest.get("shares_yoy") or 0) > .05 else "")

    body = []
    for row in rows:
        period = row["period"]
        notes = period.get("quality_notes") or []
        note = (f'<span class="data-warning" tabindex="0" title="{html.escape("；".join(notes), quote=True)}" '
                f'aria-label="資料提醒：{html.escape("；".join(notes), quote=True)}">⚠</span>') if notes else ""
        source = html.escape(period.get("url") or "", quote=True)
        period_label = html.escape(period.get("period_end") or "")
        if source:
            period_label = f'<a href="{source}" target="_blank" rel="noopener">{period_label}</a>'
        body.append(
            "<tr>"
            f"<td>{period_label} {note}</td>"
            f"<td>{compact_money(row['revenue'], currency)}</td>"
            f"<td>{fmt_pct(row.get('revenue_yoy'), 1)}</td>"
            f"<td>{fmt_pct(row.get('gross_margin'), 1)}</td>"
            f"<td>{fmt_pct(row.get('operating_margin'), 1)}</td>"
            f"<td>{fmt_pct(row.get('fcf_margin'), 1)}</td>"
            f"<td>{fmt_pct(row.get('shares_yoy'), 1)}</td>"
            "</tr>")
    if not body:
        return '<p class="note">尚無可比較的單季資料。</p>'
    method = "、".join(f"{name}={'+' if value == 1 else '−' if value == -1 else '0' if value == 0 else '缺'}"
                      for name, value in checks)
    return (
        f'<div class="metric-group">{summary}</div>'
        '<div class="table-scroll"><table class="analysis-table"><thead><tr>'
        '<th>財報期末</th><th>營收</th><th>YoY</th><th>毛利率</th><th>營業利益率</th>'
        '<th>FCF 利潤率</th><th>稀釋股數 YoY</th></tr></thead><tbody>'
        + "".join(body) + '</tbody></table></div>'
        f'<p class="note">方向分數 {score:+d}：{html.escape(method)}。營收 ±3%、毛利率／營業利益率 ±1pp、'
        'FCF 利潤率 ±2pp、股數增加逾 5% 為警戒；這是可解釋的篩選訊號，不是投資評等。</p>')


def guidance_outcome(item):
    low, high, actual = item.get("low"), item.get("high"), item.get("actual")
    if actual is None or (low is None and high is None):
        return "待實績"
    if low is not None and actual < low:
        return "低於指引"
    if high is not None and actual > high:
        return "高於指引"
    return "落在區間"


def guidance_history_records(history):
    """Expand the compact, audited history rows into named dictionaries."""
    fields = (history or {}).get("record_fields") or [
        "period", "period_end", "low", "high", "actual",
        "guidance_date", "guidance_source_url"]
    records = []
    for raw in (history or {}).get("records") or []:
        if isinstance(raw, dict):
            records.append(raw)
        elif isinstance(raw, list) and len(raw) == len(fields):
            records.append(dict(zip(fields, raw)))
    return records


def guidance_history_stats(history):
    records = [row for row in guidance_history_records(history)
               if row.get("actual") is not None]
    outcomes = [guidance_outcome(row) for row in records]
    mid_surprises = []
    for row in records:
        low, high, actual = row.get("low"), row.get("high"), row.get("actual")
        if low is not None and high is not None and (low + high):
            midpoint = (low + high) / 2
            mid_surprises.append(actual / midpoint - 1)
    return {
        "count": len(records),
        "above": outcomes.count("高於指引"),
        "within": outcomes.count("落在區間"),
        "below": outcomes.count("低於指引"),
        "avg_mid_surprise": (sum(mid_surprises) / len(mid_surprises)
                             if mid_surprises else None),
    }


def historical_guidance_section(company, history):
    status = (history or {}).get("status")
    records = guidance_history_records(history)
    if status != "available" or not records:
        status_label = ("無一致季度區間" if status == "no_consistent_numeric_guidance"
                        else "週期／口徑不同" if status == "different_cadence"
                        else "尚無可驗證歷史")
        note = html.escape((history or {}).get("note") or
                           "未形成可用相同口徑比較的歷史樣本。")
        url = (history or {}).get("review_url")
        link = (f' <a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener">'
                '查看官方資料庫</a>' if url else "")
        return (f'<div class="coverage-box"><strong>{status_label}</strong>'
                f'<p>{note}{link}；不計入命中率，也不視為未達標。</p></div>')

    stats = guidance_history_stats(history)
    count = stats["count"]
    target_rate = (stats["above"] + stats["within"]) / count if count else None
    above_rate = stats["above"] / count if count else None
    below_rate = stats["below"] / count if count else None
    cards = "".join([
        metric("可驗證樣本", f"{count} 期"),
        metric("達標率", fmt_pct(target_rate, 1)),
        metric("高於區間", fmt_pct(above_rate, 1)),
        metric("低於區間", fmt_pct(below_rate, 1), "warn" if below_rate else ""),
        metric("平均相對中點", fmt_pct(stats["avg_mid_surprise"], 1)),
    ])

    actual_sources = {
        period.get("period_end"): period.get("url")
        for period in (company or {}).get("periods") or []
    }
    actual_sources.update((history or {}).get("actual_sources") or {})
    rows = []
    for row in reversed(records):
        low, high, actual = row.get("low"), row.get("high"), row.get("actual")
        result = guidance_outcome(row)
        midpoint = ((low + high) / 2 if low is not None and high is not None else None)
        surprise = (actual / midpoint - 1
                    if actual is not None and midpoint not in {None, 0} else None)
        guidance_url = row.get("guidance_source_url")
        source_label = "指引"
        if guidance_url:
            source_label = (f'<a href="{html.escape(guidance_url, quote=True)}" target="_blank" '
                            f'rel="noopener">指引</a>')
        actual_url = actual_sources.get(row.get("period_end"))
        actual_label = "實績"
        if actual_url:
            actual_label = (f'<a href="{html.escape(actual_url, quote=True)}" target="_blank" '
                            f'rel="noopener">實績</a>')
        guide = (f"{low:,.3f}～{high:,.3f}" if low is not None and high is not None
                 else "—")
        tone = "warn" if result == "低於指引" else "ok" if result == "高於指引" else ""
        rows.append(
            f'<tr class="{tone}"><td><strong>{html.escape(row.get("period") or "")}</strong>'
            f'<small class="source-date">期末 {html.escape(row.get("period_end") or "")}</small></td>'
            f'<td>{guide}</td><td>{actual:,.3f}</td><td>{html.escape(result)}</td>'
            f'<td>{fmt_pct(surprise, 1)}</td><td>{source_label} · {actual_label}'
            f'<small class="source-date">發布 {html.escape(row.get("guidance_date") or "")}</small></td></tr>')
    basis = html.escape(((history or {}).get("comparison_basis") or "").rstrip("。"))
    derived_note = ("；其中部分區間由官方分部指引加總，表中已標明方法"
                    if (history or {}).get("derived") else "")
    return (
        f'<div class="metric-group">{cards}</div>'
        f'<p class="note">主比較指標：{html.escape((history or {}).get("metric") or "")}（'
        f'{html.escape((history or {}).get("unit") or "")}）。{basis}{derived_note}。'
        '「達標」＝落在區間或高於上限；平均相對中點為各期（實績 ÷ 指引中點 − 1）的簡單平均。</p>'
        f'<details class="guidance-history"><summary>展開近 3 年逐期紀錄（{count} 期）</summary>'
        '<div class="table-scroll"><table class="analysis-table"><thead><tr>'
        '<th>期間</th><th>當時指引</th><th>後續實績</th><th>結果</th><th>相對中點</th><th>官方來源</th>'
        '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div></details>')


def guidance_section(company, inputs, history):
    guidance = (inputs or {}).get("guidance") or []
    current_html = ""
    if not guidance:
        status = (inputs or {}).get("guidance_status")
        if status == "no_comparable_numeric_guidance":
            url = (inputs or {}).get("guidance_source_url")
            source_date = (inputs or {}).get("guidance_source_date")
            link = (f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener">'
                    f'查看 {html.escape(source_date or "最近一期")} 官方發布</a>' if url else "")
            note = html.escape((inputs or {}).get("guidance_note") or
                               "最近一期官方發布未提供可直接比較的量化區間。")
            current_html = (
                '<div class="coverage-box"><strong>本期無可比量化指引</strong>'
                f'<p>{note} {link}</p></div>')
        else:
            latest = ((company or {}).get("periods") or [{}])[0]
            url = latest.get("url") or (company or {}).get("official_results_url")
            link = (f' <a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener">查看最近一期官方結果</a>'
                    if url else "")
            current_html = (
                '<div class="coverage-box"><strong>尚未建檔數字指引</strong>'
                '<p>本庫不把歷史成長率或模型推估冒充管理層指引。完成來源核對前，達標率維持缺值。'
                f'{link}</p></div>')
    else:
        rows = []
        for item in guidance:
            low, high, actual = item.get("low"), item.get("high"), item.get("actual")
            result = guidance_outcome(item)
            guide = (f"{low:,.2f}～{high:,.2f}" if low is not None and high is not None
                     else f"{(low if low is not None else high):,.2f}")
            source = item.get("source_url")
            metric_name = html.escape(item.get("metric") or "")
            if source:
                metric_name = f'<a href="{html.escape(source, quote=True)}" target="_blank" rel="noopener">{metric_name}</a>'
            source_date = html.escape(item.get("source_date") or "")
            if source_date:
                metric_name += f'<small class="source-date">來源 {source_date}</small>'
            rows.append(f'<tr><td>{html.escape(item.get("period") or "")}</td><td>{metric_name}</td>'
                        f'<td>{guide} {html.escape(item.get("unit") or "")}</td>'
                        f'<td>{"—" if actual is None else f"{actual:,.2f}"}</td><td>{html.escape(result)}</td></tr>')
        current_html = ('<div class="table-scroll"><table class="analysis-table"><thead><tr>'
                        '<th>期間</th><th>指標／來源</th><th>管理層指引</th><th>實際</th><th>結果</th>'
                        '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>'
                        '<p class="note">只收錄公司正式發布且可連回原始來源的數字指引；模型預測不列入達標率。</p>')
    return ('<h3 class="analysis-subtitle">最近一期</h3>' + current_html
            + '<h3 class="analysis-subtitle">近 3 年指引執行紀錄</h3>'
            + historical_guidance_section(company, history))


def scenario_section(fund, val, currency):
    assumptions = val.get("assumptions") or {}
    base_growth = assumptions.get("growth")
    terminal = assumptions.get("terminal_growth")
    revenue = fund.get("revenue")
    margin = val.get("fcf_margin_median")
    if None in {base_growth, terminal, revenue, margin}:
        return '<p class="note">成長率、營收或常態化 FCF 利潤率資料不足，無法建立情境。</p>'
    configurations = [
        ("悲觀", max(-.05, base_growth * .70), max(-.30, margin - .03), "warn"),
        ("基準", base_growth, margin, ""),
        ("樂觀", min(.35, base_growth * 1.30), min(.70, margin + .03), "ok"),
    ]
    rows = []
    for name, start_growth, fcf_margin, tone in configurations:
        projected = revenue
        values = {}
        for year in range(1, 6):
            growth = start_growth + (terminal - start_growth) * ((year - 1) / 4)
            projected *= 1 + growth
            if year in {1, 3, 5}:
                values[year] = projected
        rows.append(
            f'<tr class="{tone}"><td><strong>{name}</strong></td><td>{start_growth:.1%} → {terminal:.1%}</td>'
            f'<td>{fcf_margin:.1%}</td><td>{compact_money(values[1], currency)}</td>'
            f'<td>{compact_money(values[3], currency)}</td><td>{compact_money(values[5], currency)}</td>'
            f'<td>{compact_money(values[5] * fcf_margin, currency)}</td></tr>')
    implied = (val.get("implied_growth") or {}).get("value")
    reverse = "無法求解" if implied is None else f"{implied:.1%}／年"
    return (
        '<div class="metric-group">'
        + metric("反向 DCF", reverse, "warn" if implied is not None and implied > base_growth else "")
        + metric("模型基準成長", f"{base_growth:.1%}／年")
        + metric("常態化 FCF 利潤率", f"{margin:.1%}") + '</div>'
        '<div class="table-scroll"><table class="analysis-table"><thead><tr>'
        '<th>情境</th><th>營收成長路徑</th><th>FCF 利潤率</th><th>第 1 年營收</th>'
        '<th>第 3 年營收</th><th>第 5 年營收</th><th>第 5 年 FCF</th></tr></thead><tbody>'
        + "".join(rows) + '</tbody></table></div>'
        '<p class="note">試算規則：悲觀／樂觀起始成長率為基準的 70%／130%，五年內線性收斂至終端成長率；'
        'FCF 利潤率為歷史中位數 ±3pp。這是敏感度範圍，不是公司指引或目標價。</p>')


def status_badge(level):
    labels = {"high": "警戒", "medium": "留意", "low": "正常", "unknown": "資料不足"}
    return f'<span class="risk-status {level}">{labels[level]}</span>'


def risk_matrix_data(h, rows, val, risk_change):
    latest = rows[0] if rows else {}
    liq, sol = h["liquidity"], h["solvency"]
    cfq = h["cash_flow_quality"]
    risk_rows = []

    current = liq.get("current_ratio")
    leverage = sol.get("liabilities_to_assets")
    if current is None and leverage is None:
        level = "unknown"
    else:
        level = "high" if ((current is not None and current < 1) or (leverage or 0) > .70) else "low"
    risk_rows.append(("短期償債／槓桿", level,
                      f"流動比率 {fmt_num(current)}；負債佔資產 {fmt_pct(leverage, 1)}",
                      "流動比率 <1 或負債佔資產 >70%"))

    fcf_margin = cfq.get("fcf_margin")
    conversion = cfq.get("ocf_to_net_income")
    if fcf_margin is None and conversion is None:
        level = "unknown"
    else:
        level = "high" if (fcf_margin is not None and fcf_margin < 0) else "medium" if conversion is not None and conversion < .8 else "low"
    risk_rows.append(("現金流品質", level,
                      f"FCF 利潤率 {fmt_pct(fcf_margin, 1)}；OCF／淨利 {fmt_num(conversion)}",
                      "FCF 為負，或 OCF／淨利 <0.8"))

    share_growth = latest.get("shares_yoy")
    level = "unknown" if share_growth is None else "high" if share_growth > .10 else "medium" if share_growth > .05 else "low"
    risk_rows.append(("股權稀釋", level, f"稀釋股數 YoY {fmt_pct(share_growth, 1)}",
                      "年增 >5% 留意；>10% 警戒"))

    revenue_yoy = latest.get("revenue_yoy")
    om = latest.get("operating_margin")
    pom = latest.get("prior_operating_margin")
    margin_delta = om - pom if om is not None and pom is not None else None
    if revenue_yoy is None and margin_delta is None:
        level = "unknown"
    else:
        level = "high" if (revenue_yoy is not None and revenue_yoy < 0 and margin_delta is not None and margin_delta < 0) else "medium" if (revenue_yoy or 0) < 0 else "low"
    risk_rows.append(("營運動能", level,
                      f"營收 YoY {fmt_pct(revenue_yoy, 1)}；營業利益率年變化 {'—' if margin_delta is None else f'{margin_delta * 100:+.1f}pp'}",
                      "營收與營業利益率同時惡化"))

    implied = (val.get("implied_growth") or {}).get("value")
    base = (val.get("assumptions") or {}).get("growth")
    spread = implied - base if implied is not None and base is not None else None
    level = "unknown" if spread is None else "high" if spread > .10 else "medium" if spread > .05 else "low"
    risk_rows.append(("估值期待", level,
                      f"現價隱含成長 {fmt_pct(implied, 1)}；模型基準 {fmt_pct(base, 1)}",
                      "隱含成長高出基準 >5pp 留意；>10pp 警戒"))

    def change_count(value):
        return value if isinstance(value, int) else len(value or [])

    added = change_count((risk_change or {}).get("added"))
    reworded = change_count((risk_change or {}).get("reworded"))
    rc_status = (risk_change or {}).get("status")
    level = "unknown" if rc_status != "已比較" else "medium" if added else "low"
    risk_rows.append(("SEC 風險文字變化", level, f"新增 {added} 段；改寫 {reworded} 段",
                      "新增段落須回看原文；文字變化不等於機率"))

    return risk_rows


def risk_matrix_section(h, rows, val, risk_change):
    risk_rows = risk_matrix_data(h, rows, val, risk_change)

    body = "".join(f'<tr><td><strong>{name}</strong></td><td>{status_badge(level)}</td>'
                   f'<td>{evidence}</td><td>{trigger}</td></tr>'
                   for name, level, evidence, trigger in risk_rows)
    return ('<div class="table-scroll"><table class="analysis-table"><thead><tr>'
            '<th>風險</th><th>狀態</th><th>目前證據</th><th>觸發規則／下次檢查</th>'
            '</tr></thead><tbody>' + body + '</tbody></table></div>'
            '<p class="note">狀態只依表內規則分類，不估計主觀違約機率；黃色或紅色都應回到原始申報查證。</p>')


def assessment_badge(label, level):
    return f'<span class="risk-status {level}">{html.escape(label)}</span>'


def objective_assessment_section(fund, h, val, quarterly_company, inputs, history, risk_change):
    """Build a deterministic five-part assessment from already displayed evidence."""
    quarter_rows = quarter_metrics(quarterly_company)
    latest = quarter_rows[0] if quarter_rows else {}
    assessments = []

    current = h["liquidity"].get("current_ratio")
    leverage = h["solvency"].get("liabilities_to_assets")
    fcf_margin = h["cash_flow_quality"].get("fcf_margin")
    roic_spread = h["profitability"].get("roic_minus_wacc")
    financial_checks = []
    for value, good, bad in (
            (current, lambda x: x >= 1.5, lambda x: x < 1),
            (leverage, lambda x: x <= .50, lambda x: x > .70),
            (fcf_margin, lambda x: x >= .10, lambda x: x < 0),
            (roic_spread, lambda x: x >= .05, lambda x: x < 0)):
        if value is not None:
            financial_checks.append(1 if good(value) else -1 if bad(value) else 0)
    financial_score = sum(financial_checks)
    if len(financial_checks) < 2:
        financial_label, financial_level = "資料不足", "unknown"
    elif financial_score >= 3:
        financial_label, financial_level = "強", "low"
    elif financial_score >= 1:
        financial_label, financial_level = "穩健", "low"
    elif financial_score == 0:
        financial_label, financial_level = "普通／分歧", "medium"
    else:
        financial_label, financial_level = "需留意", "high"
    financial_evidence = (
        f"流動比率 {fmt_num(current)}；負債佔資產 {fmt_pct(leverage, 1)}；"
        f"FCF 利潤率 {fmt_pct(fcf_margin, 1)}；ROIC−WACC {fmt_pct(roic_spread, 1)}")
    assessments.append(("財務體質", financial_label, financial_level, financial_evidence,
                        "流動性、槓桿、FCF 與資本報酬共 4 項計分"))

    trend_label, trend_value, _ = trend_score(quarter_rows)
    trend_level = "low" if trend_label == "改善" else "high" if trend_label == "轉弱" else "medium"
    if not quarter_rows:
        trend_level = "unknown"
    revenue_yoy = latest.get("revenue_yoy")
    operating_margin = latest.get("operating_margin")
    prior_operating_margin = latest.get("prior_operating_margin")
    margin_delta = (operating_margin - prior_operating_margin
                    if operating_margin is not None and prior_operating_margin is not None else None)
    trend_evidence = (
        f"八季方向分數 {trend_value:+d}；營收 YoY {fmt_pct(revenue_yoy, 1)}；"
        f"營業利益率年變化 {'—' if margin_delta is None else f'{margin_delta * 100:+.1f}pp'}")
    assessments.append(("營運趨勢", trend_label, trend_level, trend_evidence,
                        "分數 ≥+2 改善；≤−2 轉弱；其餘持平／分歧"))

    history_status = (history or {}).get("status")
    history_stats = guidance_history_stats(history)
    sample_count = history_stats["count"]
    above = history_stats["above"]
    within = history_stats["within"]
    below = history_stats["below"]
    target_rate = (above + within) / sample_count if sample_count else None
    if history_status == "no_consistent_numeric_guidance":
        guidance_label, guidance_level = "無一致區間", "unknown"
        guidance_evidence = "近 3 年未持續提供可直接比較的季度量化區間"
    elif history_status == "different_cadence":
        guidance_label, guidance_level = "口徑不同", "unknown"
        guidance_evidence = "年度／季度目標或指標口徑不同，不混算命中率"
    elif sample_count < 4:
        guidance_label, guidance_level = "樣本不足", "unknown"
        guidance_evidence = f"近 3 年只有 {sample_count} 期可驗證樣本"
    elif below == 0 and above / sample_count >= .50:
        guidance_label, guidance_level = "持續達標／偏保守", "low"
        guidance_evidence = (f"近 3 年 {sample_count} 期：高於 {above}、區間內 {within}、"
                             f"低於 {below}；達標率 {target_rate:.1%}")
    elif below / sample_count <= .10:
        guidance_label, guidance_level = "穩定達標", "low"
        guidance_evidence = (f"近 3 年 {sample_count} 期：高於 {above}、區間內 {within}、"
                             f"低於 {below}；達標率 {target_rate:.1%}")
    elif below / sample_count <= .25:
        guidance_label, guidance_level = "大致可信", "medium"
        guidance_evidence = (f"近 3 年 {sample_count} 期：高於 {above}、區間內 {within}、"
                             f"低於 {below}；達標率 {target_rate:.1%}")
    else:
        guidance_label, guidance_level = "需留意", "high"
        guidance_evidence = (f"近 3 年 {sample_count} 期：高於 {above}、區間內 {within}、"
                             f"低於 {below}；達標率 {target_rate:.1%}")
    assessments.append(("指引執行", guidance_label, guidance_level, guidance_evidence,
                        "回溯 3 年；達標＝區間內或高於；無一致區間不評分"))

    implied = (val.get("implied_growth") or {}).get("value")
    base_growth = (val.get("assumptions") or {}).get("growth")
    spread = implied - base_growth if implied is not None and base_growth is not None else None
    price = (val.get("multiples") or {}).get("price")
    dcf_median = (val.get("dcf") or {}).get("p50")
    dcf_gap = price / dcf_median - 1 if price is not None and dcf_median else None
    if spread is None and dcf_gap is None:
        valuation_label, valuation_level = "資料不足", "unknown"
    elif ((spread is not None and spread > .10) or (dcf_gap is not None and dcf_gap > .30)):
        valuation_label, valuation_level = "高", "high"
    elif ((spread is not None and spread > .05) or (dcf_gap is not None and dcf_gap > .10)):
        valuation_label, valuation_level = "中", "medium"
    else:
        valuation_label, valuation_level = "低", "low"
    valuation_evidence = (
        f"隱含成長 {fmt_pct(implied, 1)} vs. 模型基準 {fmt_pct(base_growth, 1)}；"
        f"現價相對 DCF P50 {'—' if dcf_gap is None else f'{dcf_gap:+.0%}'}")
    assessments.append(("估值壓力", valuation_label, valuation_level, valuation_evidence,
                        "隱含成長高基準 >5pp 或現價高 P50 >10% 起列中等"))

    # 營運與估值已各自列為獨立面向，風險水位不重複計入這兩列。
    matrix = [row for row in risk_matrix_data(h, quarter_rows, val, risk_change)
              if row[0] not in {"營運動能", "估值期待"}]
    counts = {level: sum(1 for _, item_level, _, _ in matrix if item_level == level)
              for level in ("high", "medium", "low", "unknown")}
    if counts["high"]:
        risk_label, risk_level = "高", "high"
    elif counts["medium"]:
        risk_label, risk_level = "中", "medium"
    elif counts["low"]:
        risk_label, risk_level = ("低（有缺值）" if counts["unknown"] else "低"), "low"
    else:
        risk_label, risk_level = "資料不足", "unknown"
    risk_evidence = (f"警戒 {counts['high']}；留意 {counts['medium']}；正常 {counts['low']}；"
                     f"資料不足 {counts['unknown']}")
    assessments.append(("風險水位", risk_label, risk_level, risk_evidence,
                        "償債、現金流、稀釋、SEC 文字任一警戒＝高；否則有留意＝中"))

    if financial_level == "low" and trend_level == "low" and valuation_level == "high":
        positioning = "基本面強、營運改善，但市場期待與估值壓力偏高"
    elif financial_level == "low" and trend_level == "low" and valuation_level == "low":
        positioning = "基本面與營運趨勢正向，模型顯示的估值壓力較低"
    elif trend_level == "high" or risk_level == "high":
        positioning = "營運或風險訊號需優先查證，尚不宜只依長期故事下結論"
    else:
        positioning = "財務、營運與估值訊號分歧，需依後續財報確認方向"

    body = "".join(
        f'<tr><td><strong>{name}</strong></td><td>{assessment_badge(label, level)}</td>'
        f'<td>{evidence}</td><td>{rule}</td></tr>'
        for name, label, level, evidence, rule in assessments)
    return (
        f'<div class="assessment-summary"><strong>目前定位：{html.escape(positioning)}</strong>'
        '<p>公司品質與股價合理性分開判讀；狀態由下列固定規則產生，不是買進／賣出建議。</p></div>'
        '<div class="table-scroll"><table class="analysis-table assessment-table"><thead><tr>'
        '<th>面向</th><th>狀態</th><th>目前證據</th><th>判定方式</th>'
        '</tr></thead><tbody>' + body + '</tbody></table></div>'
        '<p class="assessment-conclusion"><strong>中長期判讀：</strong>'
        f'財務體質為「{html.escape(financial_label)}」、八季營運為「{html.escape(trend_label)}」、'
        f'指引執行為「{html.escape(guidance_label)}」、估值壓力為「{html.escape(valuation_label)}」、'
        f'風險水位為「{html.escape(risk_label)}」。正向情境需由後續營收、利潤率、FCF 與指引持續驗證；'
        '若營運轉弱、現金流惡化、稀釋升高或實績持續低於指引，原有長期判斷就需要下修。</p>'
        '<p class="note">這是財報與估值資料的規則化摘要；競爭優勢、產業週期、法規及管理層執行力仍須搭配護城河與核心風險章節閱讀。</p>')


def operating_context_section(sections, quarterly_company, inputs):
    keywords = re.compile(r"分部|業務|產品|客戶|供應商|集中|地區|市場|訂單|backlog|RPO", re.I)
    clues = []
    for key in ("一", "六"):
        body = sections.get(key, (None, ""))[1]
        for line in body.splitlines():
            clean = re.sub(r"^\s*[-*]\s*", "", line).strip()
            if clean and keywords.search(clean) and clean not in clues:
                clues.append(clean)
    clue_html = ("<ul>" + "".join(f"<li>{md_inline(item)}</li>" for item in clues[:6]) + "</ul>"
                 if clues else '<p class="note">Master Thesis 尚未整理可顯示的分部或集中度線索。</p>')
    structured = (inputs or {}).get("segments") or {}
    items = structured.get("items") or []
    if items:
        unit = structured.get("unit") or ""
        total = sum(item.get("revenue") or 0 for item in items)
        rows = []
        for item in items:
            revenue = item.get("revenue")
            operating_income = item.get("operating_income")
            margin = item.get("operating_margin")
            if margin is None and operating_income is not None and revenue:
                margin = operating_income / revenue * 100
            share = revenue / total if revenue is not None and total else None
            rows.append(
                '<tr>'
                f'<td><strong>{html.escape(item.get("name") or "")}</strong></td>'
                f'<td>{"—" if revenue is None else f"{revenue:,.2f}"} {html.escape(unit)}</td>'
                f'<td>{fmt_pct(share, 1)}</td>'
                f'<td>{"—" if operating_income is None else f"{operating_income:,.2f} {html.escape(unit)}"}</td>'
                f'<td>{"—" if margin is None else f"{margin:.1f}%"}</td>'
                '</tr>')
        source = structured.get("source_url")
        source_label = html.escape(structured.get("source_date") or "官方來源")
        source_link = (f'<a href="{html.escape(source, quote=True)}" target="_blank" rel="noopener">'
                       f'{source_label} 官方表格</a>' if source else source_label)
        note = structured.get("note")
        structured_html = (
            '<div class="coverage-box"><strong>已核對官方分部／營收來源資料</strong>'
            f'<p>{html.escape(structured.get("period") or "")}；'
            f'{html.escape(structured.get("basis") or "公司揭露口徑")}；{source_link}。'
            '占比依本表已收錄營收加總計算，不等於長期獲利貢獻。</p></div>'
            '<div class="table-scroll"><table class="analysis-table"><thead><tr>'
            '<th>分部／營收來源</th><th>營收</th><th>表內營收占比</th><th>營業利益</th><th>營業利益率</th>'
            '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>')
        if note:
            structured_html += f'<p class="note">⚠️ {html.escape(note)}</p>'
    else:
        source = ((quarterly_company or {}).get("official_results_url")
                  or (((quarterly_company or {}).get("periods") or [{}])[0].get("url")))
        source_link = (f'<a href="{html.escape(source, quote=True)}" target="_blank" rel="noopener">公司官方財報頁</a>'
                       if source else "最近一期申報連結")
        structured_html = (
            '<div class="coverage-box"><strong>尚無可安全拆分的結構化分部數字</strong>'
            '<p>SEC Company Facts 不含可靠的分部 context，本庫不把合併數字拆成猜測值。'
            f'待逐公司從附註核對；來源入口：{source_link}。</p></div>')
    return structured_html + '<h3>已整理的營運／集中度線索</h3>' + clue_html


def provenance_section(t, fund, h, val):
    fresh = h["freshness"]
    rows = [
        ("財報來源", f'{h["source_form"]}，accession <code>{html.escape(h["source_accession"] or "")}</code>'
                     f'，申報日 {h["source_filed"]}'),
        ("會計年度結束", f'{fresh["fiscal_year_end"]}（距今 {fresh["months_old"]} 個月）'),
        ("幣別", h["currency"] or "資料不足"),
        ("股價", f'{fund.get("price_date")} 收盤 ${fund.get("price_used"):,.2f}'
                 if fund.get("price_used") else "資料不足"),
        ("指標覆蓋", f'{h["coverage"]["computed"]} / {h["coverage"]["total"]}'),
    ]
    notes = []
    if fresh.get("stale"):
        notes.append(fresh["note"])
    for key, node in (("有息負債", h["solvency"].get("total_debt_note")),
                      ("利息保障倍數", h["solvency"].get("interest_coverage_note")),
                      ("ROIC", h["profitability"].get("roic_note")),
                      ("毛利率", "由「營收 − 銷貨成本」推導"
                       if fund.get("gross_margin_basis") == "revenue_less_cogs" else None),
                      ("Beneish M-Score", h["beneish_m"].get("reason")
                       or h["beneish_m"].get("growth_caveat")),
                      ("DCF 基期", val.get("base_fcf_caveat"))):
        if node:
            notes.append(f"{key}：{node}")

    row_html = "".join(
        f'<tr><th>{html.escape(k)}</th><td>{v}</td></tr>' for k, v in rows)
    note_html = ""
    if notes:
        note_html = ("<h4 class=\"sub-heading\">資料限制</h4><ul>"
                     + "".join(f"<li>{html.escape(n)}</li>" for n in notes) + "</ul>")
    return f'<table class="prov-table">{row_html}</table>{note_html}'


# --------------------------------------------------------------------------
# page

STYLE = """
:root{--bg-dark:#070a12;--card-bg:rgba(17,24,39,.75);--card-border:rgba(255,255,255,.08);
--text-main:#f3f4f6;--text-muted:#9ca3af;--accent:#38bdf8;--accent-2:#a855f7;
--ok:#10b981;--warn:#fbbf24;--glow:0 12px 40px 0 rgba(0,0,0,.45)}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Outfit','Noto Sans TC',sans-serif;
background:radial-gradient(circle at 50% -10%,#1e3a8a,var(--bg-dark) 75%);
color:var(--text-main);min-height:100vh;padding:24px;line-height:1.6}
.container{max-width:1400px;margin:0 auto}
.top-nav{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;
padding:16px 28px;background:rgba(15,23,42,.85);backdrop-filter:blur(16px);
border:1px solid var(--card-border);border-radius:18px;margin-bottom:24px}
.nav-brand{font-size:1.1rem;font-weight:800;color:#fff}
.nav-links{display:flex;gap:10px;flex-wrap:wrap}
.nav-btn{color:var(--text-muted);text-decoration:none;font-size:.875rem;font-weight:600;
padding:8px 16px;border-radius:10px;background:rgba(255,255,255,.04);
border:1px solid var(--card-border);transition:all .2s}
.nav-btn:hover{color:#fff;background:var(--accent);border-color:transparent}
.hero-card{background:linear-gradient(135deg,rgba(56,189,248,.18),rgba(30,58,138,.8));
border:1px solid rgba(56,189,248,.35);border-radius:24px;padding:36px;box-shadow:var(--glow);
margin-bottom:28px;display:grid;grid-template-columns:1.6fr 1.4fr;gap:28px;align-items:center}
@media(max-width:900px){.hero-card{grid-template-columns:1fr}}
.hero-title h1{font-size:2.1rem;font-weight:800;letter-spacing:-.5px;margin-bottom:8px}
.hero-subtitle{font-size:1rem;color:#cbd5e1;margin-bottom:16px}
.badge-sec{display:inline-flex;align-items:center;gap:8px;background:rgba(16,185,129,.15);
border:1px solid rgba(16,185,129,.3);color:#34d399;padding:6px 14px;border-radius:12px;
font-size:.8rem;font-weight:700}
.hero-kpis{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}
.kpi-box{background:rgba(0,0,0,.3);border:1px solid var(--card-border);border-radius:16px;padding:16px}
.kpi-label{font-size:.775rem;color:var(--text-muted)}
.kpi-val{font-size:1.35rem;font-weight:800;color:#fff;margin-top:4px}
.kpi-sub{font-size:.75rem;color:var(--accent);margin-top:2px}
.section-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(620px,1fr));gap:26px;margin-bottom:28px}
@media(max-width:700px){.section-grid{grid-template-columns:1fr}}
.card{background:var(--card-bg);backdrop-filter:blur(12px);border:1px solid var(--card-border);
border-radius:20px;padding:28px;box-shadow:var(--glow);min-width:0}
.card-full{grid-column:1/-1}
.card h2{font-size:1.25rem;font-weight:800;margin-bottom:18px;color:#fff}
.card h3{font-size:1.05rem;font-weight:700;margin:18px 0 10px;color:#e5e7eb}
.sub-heading{font-size:.95rem;font-weight:700;margin:18px 0 8px;color:var(--accent)}
.card ul,.card ol{padding-left:1.25rem;margin:6px 0}
.card li{margin:6px 0;color:#d1d5db;font-size:.925rem}
.card p{color:#d1d5db;font-size:.925rem;margin:8px 0}
.note{font-size:.85rem;color:var(--text-muted);border-left:3px solid var(--accent);
padding-left:12px;margin:12px 0}
code{background:rgba(255,255,255,.08);padding:1px 6px;border-radius:5px;font-size:.85em;overflow-wrap:anywhere}
.metric-group{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px}
.metric-card{background:rgba(0,0,0,.28);border:1px solid var(--card-border);
border-radius:14px;padding:14px 16px}
.metric-card.warn{border-color:rgba(251,191,36,.45);background:rgba(251,191,36,.08)}
.metric-card .title{font-size:.775rem;color:var(--text-muted)}
.metric-card .value{font-size:1.2rem;font-weight:800;color:#fff;margin-top:4px}
.fin-term{display:inline-flex;align-items:center;gap:5px;color:inherit;cursor:help;
position:relative;border-bottom:1px dotted rgba(148,163,184,.7);outline:none}
.fin-term:focus-visible{color:#fff;border-bottom-color:var(--accent)}
.term-icon{display:inline-grid;place-items:center;width:15px;height:15px;border-radius:50%;
font:700 10px/1 'Outfit',sans-serif;color:var(--accent);border:1px solid rgba(56,189,248,.55);
background:rgba(56,189,248,.08);flex:0 0 auto}
.tooltip-hint{font-size:.82rem;color:var(--text-muted);margin:8px 0 14px}
.finance-tooltip{position:fixed;z-index:9999;width:min(360px,calc(100vw - 32px));
padding:12px 14px;border-radius:12px;border:1px solid rgba(56,189,248,.45);
background:rgba(2,6,23,.98);box-shadow:0 14px 38px rgba(0,0,0,.55);color:#e5e7eb;
font:400 .86rem/1.55 'Noto Sans TC','Outfit',sans-serif;pointer-events:none}
.term-guide{margin-top:14px;padding:12px 14px;border-radius:12px;
background:rgba(56,189,248,.07);border:1px solid rgba(56,189,248,.2)}
.term-guide p{margin:5px 0 0;font-size:.82rem;color:var(--text-muted)}
.assumption-age-note{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:12px 0;
padding:9px 12px;border-radius:10px;background:rgba(56,189,248,.07);
border:1px solid rgba(56,189,248,.2);font-size:.82rem;color:#cbd5e1}
.assumption-age{font-weight:700;color:#7dd3fc}
.assumption-age.stale{color:#fbbf24}
.rank-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
.rank-card{background:rgba(0,0,0,.28);border:1px solid var(--card-border);
border-radius:14px;padding:12px 14px}
.rank-label{font-size:.75rem;color:var(--text-muted)}
.rank-pos{font-size:1.05rem;font-weight:800;color:var(--accent);margin-top:2px}
.rank-val{font-size:.85rem;color:#e5e7eb}
.flag-box{margin-top:18px;background:rgba(251,191,36,.08);border:1px solid rgba(251,191,36,.35);
border-radius:14px;padding:16px 18px}
.flag-box.ok{background:rgba(16,185,129,.08);border-color:rgba(16,185,129,.35)}
.flag-box h4{font-size:.95rem;margin-bottom:8px;color:#fff}
.prov-table{width:100%;border-collapse:collapse;font-size:.875rem}
.prov-table th{text-align:left;color:var(--text-muted);font-weight:600;padding:7px 12px 7px 0;
white-space:nowrap;vertical-align:top;width:130px}
.prov-table td{padding:7px 0;color:#e5e7eb}
.table-scroll{overflow-x:auto;margin-top:16px;border:1px solid var(--card-border);border-radius:14px}
.analysis-table{width:100%;border-collapse:collapse;min-width:820px;font-size:.84rem}
.analysis-table th{padding:11px 12px;text-align:left;color:var(--text-muted);background:rgba(2,6,23,.65);
font-weight:700;white-space:nowrap}
.analysis-table td{padding:11px 12px;border-top:1px solid var(--card-border);color:#e5e7eb;vertical-align:top}
.analysis-table a{color:#7dd3fc;text-decoration:none}.analysis-table a:hover{text-decoration:underline}
.source-date{display:block;margin-top:2px;color:var(--text-muted);font-size:.72rem;font-weight:400}
.analysis-table tr.warn td{background:rgba(251,191,36,.05)}
.analysis-table tr.ok td{background:rgba(16,185,129,.04)}
.coverage-box{padding:15px 17px;border-radius:14px;background:rgba(56,189,248,.07);
border:1px solid rgba(56,189,248,.25);margin-bottom:14px}
.coverage-box strong{color:#e0f2fe}.coverage-box p{margin:5px 0 0}
.coverage-box a{color:#7dd3fc}
.analysis-subtitle{font-size:1rem;color:#e0f2fe;margin:18px 0 10px}
.analysis-subtitle:first-child{margin-top:0}
.guidance-history{margin-top:14px;border:1px solid var(--card-border);border-radius:14px;
background:rgba(2,6,23,.3);overflow:hidden}
.guidance-history summary{padding:13px 16px;color:#7dd3fc;font-weight:750;cursor:pointer;
list-style-position:inside}
.guidance-history[open] summary{border-bottom:1px solid var(--card-border)}
.guidance-history .table-scroll{margin:0;border:0;border-radius:0}
.assessment-summary{padding:17px 19px;border-radius:14px;background:linear-gradient(135deg,rgba(56,189,248,.11),rgba(168,85,247,.08));border:1px solid rgba(125,211,252,.24);margin-bottom:16px}
.assessment-summary strong{color:#e0f2fe;font-size:1.05rem}.assessment-summary p{margin:5px 0 0;color:#cbd5e1}
.assessment-conclusion{margin-top:16px;padding:15px 17px;border-left:3px solid var(--accent);background:rgba(2,6,23,.38);border-radius:0 12px 12px 0;color:#dbeafe}
.risk-status{display:inline-block;padding:3px 9px;border-radius:999px;font-size:.75rem;font-weight:800}
.risk-status.low{color:#6ee7b7;background:rgba(16,185,129,.13)}
.risk-status.medium{color:#fde68a;background:rgba(251,191,36,.13)}
.risk-status.high{color:#fca5a5;background:rgba(239,68,68,.14)}
.risk-status.unknown{color:#cbd5e1;background:rgba(148,163,184,.12)}
.data-warning{display:inline-grid;place-items:center;width:21px;height:21px;margin-left:4px;border-radius:50%;
color:#fbbf24;border:1px solid rgba(251,191,36,.55);cursor:help;font-size:.76rem;vertical-align:middle}
.chart-container{position:relative;height:320px;margin-top:8px}
footer{text-align:center;color:var(--text-muted);font-size:.8rem;padding:28px 0}
"""


def render(ticker, ctx):
    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="description" content="{html.escape(ctx['name'])}（{ticker}）財務健全度與估值報告，數據由 SEC XBRL 產生。">
<title>{html.escape(ctx['name'])}（{ticker}）財務健全度與估值報告</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700;800&family=Noto+Sans+TC:wght@400;500;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>{STYLE}</style>
</head>
<body>
<div class="container">

  <nav class="top-nav">
    <div class="nav-brand">🔍 {html.escape(ctx['name'])}（{ticker}）投資報告</div>
    <div class="nav-links">
      <a class="nav-btn" href="dashboard.html">📊 返回儀表板</a>
      {ctx['peer_links']}
      <a class="nav-btn" href="https://github.com/ttchang1127/ttc-stock">🐙 GitHub</a>
    </div>
  </nav>

  <div class="hero-card">
    <div class="hero-title">
      <h1>{html.escape(ctx['name'])}（{ticker}）</h1>
      <div class="hero-subtitle">財務健全度、估值與下行風險 — 歷史合併數據由 SEC XBRL 產生；指引與分部均附公司官方來源</div>
      <div class="tooltip-hint">ⓘ 滑鼠移到帶 i 的金融名詞，或用鍵盤聚焦，即可查看定義與判讀方法。</div>
      <div class="badge-sec">🛡️ {ctx['form']} · accession {html.escape(ctx['accession'])} · FY{ctx['fye']}</div>
    </div>
    <div class="hero-kpis">{ctx['hero']}</div>
  </div>

  <div class="section-grid">
    <div class="card">
      <h2>🏛️ 一、經濟護城河</h2>
      {ctx['moat']}
      <p class="note">本節為人工撰寫的質化分析，來源為 30_Analysis 的 Master Thesis，非由財報數字產生。</p>
    </div>

    <div class="card">
      <h2>📈 六年營收與自由現金流趨勢</h2>
      <div class="chart-container"><canvas id="trendChart"></canvas></div>
    </div>

    <div class="card card-full">
      <h2>🩺 財務健全度總覽</h2>
      {ctx['health']}
    </div>

    <div class="card card-full">
      <h2>📅 八季營運趨勢</h2>
      {ctx['quarterly_trend']}
    </div>

    <div class="card card-full">
      <h2>🎯 管理層指引 vs. 實際結果</h2>
      {ctx['guidance']}
    </div>

    <div class="card card-full">
      <h2>🧭 {term_label("情境預測")}與{term_label("反向 DCF")}</h2>
      {ctx['scenarios']}
    </div>

    <div class="card card-full">
      <h2>🚦 可追蹤風險矩陣</h2>
      {ctx['risk_matrix']}
    </div>

    <div class="card card-full">
      <h2>🧾 客觀綜合評價</h2>
      {ctx['objective_assessment']}
    </div>

    <div class="card card-full">
      <h2>🧩 分部與集中度分析</h2>
      {ctx['operating_context']}
    </div>

    <div class="card card-full">
      <h2>🏅 本組合相對排名（{ctx['peer_count']} 家）</h2>
      <div class="rank-strip">{ctx['ranks']}</div>
      <p class="note">排名僅涵蓋本知識庫追蹤的 {ctx['peer_count']} 家公司，每次產生時重新計算。不代表全市場排名。</p>
    </div>

    <div class="card">
      <h2>📊 損益、現金流與資產負債</h2>
      <div class="metric-group">{ctx['financials']}</div>
      <h3>{term_label("DuPont 三因子拆解")}</h3>
      <div class="chart-container"><canvas id="dupontChart"></canvas></div>
    </div>

    <div class="card">
      <h2>🎲 {term_label("蒙地卡羅 DCF")} 估值分佈</h2>
      {ctx['dcf']}
      {ctx['assumption_age']}
      <div class="chart-container"><canvas id="dcfChart"></canvas></div>
      <div class="term-guide"><strong>延伸估值名詞：{term_label("EV/EBITDA")}</strong>
        <p>目前報告尚未顯示此數值：本庫有公司缺少可一致計算 EBITDA 的 SEC 科目，因此不以不完整資料進行跨公司比較。</p>
      </div>
    </div>

    <div class="card">
      <h2>📉 下行風險（{term_label("Sortino Ratio")}）</h2>
      <div class="metric-group">{ctx['sortino']}</div>
      <p class="note">三個數字的頻率、期間與門檻報酬率都不同，衡量的是不同的東西，不能互相驗證。</p>
    </div>

    <div class="card">
      <h2>💵 籌碼面與股東資本回饋</h2>
      <div class="metric-group">{ctx['yield']}</div>
    </div>

    <div class="card card-full">
      <h2>⚠️ 核心風險因素</h2>
      {ctx['risks']}
      {ctx['risk_provenance']}
    </div>

    <div class="card card-full">
      <h2>🔄 風險因素的年度變化</h2>
      {ctx['risk_changes']}
    </div>

    <div class="card card-full">
      <h2>🔎 資料來源與限制</h2>
      {ctx['provenance']}
    </div>
  </div>

  <footer>
    由 <code>scripts/build_reports.py</code> 於 {ctx['generated_at']} 產生。<br>
    歷史合併財務由 SEC XBRL 產生；管理層指引與分部表為人工逐筆核對官方來源，均附日期與連結。<br>
    DCF 為特定假設下的推估，非事實，不構成投資建議。
  </footer>
</div>

<div id="financeTooltip" class="finance-tooltip" role="tooltip" hidden></div>

<script>
const financeTooltip = document.getElementById('financeTooltip');
let activeFinanceTerm = null;

function placeFinanceTooltip(event) {{
  if (!activeFinanceTerm || financeTooltip.hidden) return;
  const pad = 12;
  const rect = financeTooltip.getBoundingClientRect();
  const anchor = activeFinanceTerm.getBoundingClientRect();
  const pointerX = event && Number.isFinite(event.clientX)
    ? event.clientX : anchor.left + anchor.width / 2;
  const pointerY = event && Number.isFinite(event.clientY)
    ? event.clientY : anchor.bottom;
  let left = pointerX + 14;
  let top = pointerY + 16;
  if (left + rect.width > window.innerWidth - pad) left = window.innerWidth - rect.width - pad;
  if (top + rect.height > window.innerHeight - pad) top = pointerY - rect.height - 14;
  financeTooltip.style.left = Math.max(pad, left) + 'px';
  financeTooltip.style.top = Math.max(pad, top) + 'px';
}}

function showFinanceTooltip(term, event) {{
  activeFinanceTerm = term;
  financeTooltip.textContent = term.dataset.tooltip;
  financeTooltip.hidden = false;
  placeFinanceTooltip(event);
}}

function hideFinanceTooltip(term) {{
  if (term && term !== activeFinanceTerm) return;
  financeTooltip.hidden = true;
  activeFinanceTerm = null;
}}

document.querySelectorAll('.fin-term').forEach(term => {{
  term.addEventListener('pointerenter', event => showFinanceTooltip(term, event));
  term.addEventListener('pointermove', placeFinanceTooltip);
  term.addEventListener('pointerleave', () => hideFinanceTooltip(term));
  term.addEventListener('focus', event => showFinanceTooltip(term, event));
  term.addEventListener('blur', () => hideFinanceTooltip(term));
  term.addEventListener('click', event => {{
    if (activeFinanceTerm === term && !financeTooltip.hidden) hideFinanceTooltip(term);
    else showFinanceTooltip(term, event);
  }});
}});
document.addEventListener('keydown', event => {{
  if (event.key === 'Escape') hideFinanceTooltip();
}});
window.addEventListener('scroll', () => hideFinanceTooltip(), {{ passive: true }});

function updateAssumptionAges() {{
  document.querySelectorAll('.assumption-age[data-derived]').forEach(el => {{
    const raw = el.dataset.derived;
    const staleAfter = Number(el.dataset.staleAfter || 90);
    const derived = new Date(raw + 'T00:00:00Z');
    if (Number.isNaN(derived.getTime())) {{
      el.textContent = '推導日期格式異常';
      el.classList.add('stale');
      return;
    }}
    const days = Math.max(0, Math.floor((Date.now() - derived.getTime()) / 86400000));
    let age = days + ' 天前';
    if (days >= 365) age = Math.floor(days / 365) + ' 年 '
      + Math.floor((days % 365) / 30) + ' 個月前';
    else if (days >= 30) age = Math.floor(days / 30) + ' 個月前';
    el.textContent = '推導於 ' + raw + '（' + age + '）';
    el.classList.toggle('stale', days >= staleAfter);
    el.title = days >= staleAfter
      ? '已超過 ' + staleAfter + ' 天未重新推導；這是提醒，不會自動改變假設。'
      : '尚未超過 ' + staleAfter + ' 天提醒門檻。';
  }});
}}
updateAssumptionAges();

Chart.defaults.color = '#9ca3af';
Chart.defaults.borderColor = 'rgba(255,255,255,.07)';
const noLegend = {{ plugins: {{ legend: {{ labels: {{ color: '#d1d5db' }} }} }},
                   maintainAspectRatio: false, responsive: true }};

new Chart(document.getElementById('trendChart'), {{
  type: 'bar',
  data: {{
    labels: {ctx['trend_labels']},
    datasets: [
      {{ label: '營收', data: {ctx['trend_revenue']}, backgroundColor: 'rgba(56,189,248,.55)' }},
      {{ label: '自由現金流', data: {ctx['trend_fcf']}, type: 'line',
         borderColor: '#a855f7', backgroundColor: '#a855f7', tension: .3 }}
    ]
  }},
  options: {{ ...noLegend, scales: {{ y: {{ ticks: {{ callback: v => v + 'M' }} }} }} }}
}});

new Chart(document.getElementById('dupontChart'), {{
  type: 'bar',
  data: {{
    labels: ['淨利率 (%)', '資產週轉率 (x)', '權益乘數 (x)'],
    datasets: [{{ label: 'DuPont 三因子', data: {ctx['dupont_data']},
                 backgroundColor: ['#38bdf8', '#10b981', '#fbbf24'] }}]
  }},
  options: noLegend
}});

new Chart(document.getElementById('dcfChart'), {{
  type: 'bar',
  data: {{
    labels: {ctx['dcf_labels']},
    datasets: [{{ label: '每股價值 (USD)', data: {ctx['dcf_data']},
                 backgroundColor: {ctx['dcf_colors']} }}]
  }},
  options: noLegend
}});
</script>
</body>
</html>
"""


def build_context(ticker, data, ranks, peers):
    fund = data["fundamentals"][ticker]
    h = data["health"][ticker]
    v = data["valuation"][ticker]
    periods = data["financials"][ticker]["periods"]
    quarterly_company = data["quarterly"].get(ticker) or {}
    forward_inputs = data["forward_inputs"].get(ticker) or {}
    guidance_history = data["guidance_history"].get(ticker) or {}
    sections = split_sections(thesis_path(ticker).read_text()) \
        if thesis_path(ticker).exists() else {}

    m = v["multiples"]
    dcf = v.get("dcf") or {}
    prof = h["profitability"]

    hero = "".join([
        kpi("現價 / 本益比",
            f'${m["price"]:,.2f}' if m["price"] else "資料不足",
            f'P/E {m["pe_ratio"]:.1f}x' if m["pe_ratio"] else (m.get("pe_note") or "")),
        kpi("ROIC − WACC",
            f'{prof["roic_minus_wacc"] * 100:+.1f}pp' if prof["roic_minus_wacc"] is not None
            else "資料不足",
            prof.get("value_creation") or ""),
        kpi("Altman Z''",
            f'{h["altman_z2"]["z2_score"]:.2f}' if h["altman_z2"].get("z2_score") is not None
            else "資料不足",
            f'{h["altman_z2"].get("zone", "")} 區（>2.6 安全）'),
        kpi("健全度警示",
            f'{h["flag_count"]} 項' if h["coverage"]["sufficient"] else "資料不足",
            "未觸發門檻" if h["flag_count"] == 0 and h["coverage"]["sufficient"]
            else f'{h["coverage"]["computed"]}/{h["coverage"]["total"]} 項可計算'),
    ])

    financials = "".join([
        metric("營收", fmt_money(fund.get("revenue"))),
        metric("淨利", fmt_money(fund.get("net_income"))),
        metric("毛利率", fmt_pct(fund.get("gross_margin"))),
        metric("營運現金流", fmt_money(fund.get("operating_cash_flow"))),
        metric("資本支出", fmt_money(fund.get("capex"))),
        metric("自由現金流", fmt_money(fund.get("free_cash_flow"))),
        metric("總資產", fmt_money(fund.get("assets"))),
        metric("總負債", fmt_money(h["solvency"].get("total_liabilities"))),
        metric("股東權益", fmt_money(fund.get("equity"))),
    ])

    if dcf.get("p50"):
        gap = (dcf["p50"] / m["price"] - 1) * 100 if m.get("price") else None
        a = v["assumptions"]
        band = "${:,.2f} ~ ${:,.2f}".format(dcf["p25"], dcf["p75"])
        median = "${:,.2f}".format(dcf["p50"])
        rel = "資料不足" if gap is None else "{:+.0f}%".format(gap)
        implied = (v.get("implied_growth") or {}).get("value")
        implied_txt = ("{:.1%}".format(implied) if implied is not None
                       else "無解")
        warn = v.get("credibility_warning")
        dcf_html = (
            '<div class="metric-group">'
            + metric("P25 ~ P75 主流區間", band)
            + metric("中位數 P50", median, "warn" if warn else "")
            + metric("相對現價", rel, "warn" if warn else "")
            + metric("現價隱含 FCF 年成長率", implied_txt)
            + '</div>')
        if warn:
            dcf_html += ('<div class="flag-box"><h4>🚨 中位數不宜當作目標價</h4>'
                         '<p>{}</p></div>'.format(html.escape(warn)))
        dcf_html += (
            '<p class="note">假設：g={:.2%}、WACC={:.2%}、終端成長={:.1%}、{:,} 次模擬。'
            '基期＝{}。{}</p>'
            .format(a["growth"], a["wacc"], a["terminal_growth"], a["simulations"],
                    html.escape(v.get("base_fcf_basis") or ""),
                    html.escape(a.get("note") or "")))
        labels = ["P5", "P25", "P50", "P75", "P95", "現價"]
        vals = [dcf["p5"], dcf["p25"], dcf["p50"], dcf["p75"], dcf["p95"], m["price"]]
        colors = ["#334155", "#38bdf8", "#a855f7", "#38bdf8", "#334155", "#10b981"]
    else:
        dcf_html = f'<p class="note">DCF 狀態：{html.escape(v["dcf_status"])}。本節不呈現估值數字。</p>'
        labels, vals, colors = ["現價"], [m.get("price")], ["#10b981"]

    s = fund["sortino"]

    def sortino_card(label, node):
        if node.get("value") is None:
            return metric(label, "資料不足")
        return metric(label, fmt_num(node["value"]))

    sortino = "".join([
        sortino_card("近 3 年（週資料）", s["3y"]),
        sortino_card("近 5 年（週資料）", s["5y"]),
        sortino_card("近 12 個月（日資料 MAR=0）", s["12m_daily"]),
        metric("同期無風險門檻版本",
               fmt_num(s["12m_daily"].get("value_vs_riskfree"))
               if s["12m_daily"].get("value_vs_riskfree") is not None else "資料不足"),
    ])

    yield_html = "".join([
        metric("稀釋每股盈餘", f'${m["eps_diluted"]:,.2f}' if m["eps_diluted"] else "資料不足"),
        metric("現金與短期投資", fmt_money(m.get("cash_and_st_investments"))),
        metric("有息負債總額", fmt_money(m.get("total_debt"))),
        metric("淨現金", fmt_money(m.get("net_cash"))),
        metric("庫藏股回購", fmt_money(m.get("buybacks"))),
        metric("現金股利", fmt_money(m.get("dividends_paid"))),
        metric("股東總殖利率", fmt_pct(m.get("shareholder_yield"))),
    ])

    # Oldest first, so the trend reads left to right.
    trend = list(reversed(periods))
    tl, tr, tf = [], [], []
    for p in trend:
        rev = (p.get("revenue") or {}).get("value")
        ocf = (p.get("operating_cash_flow") or {}).get("value")
        cap = (p.get("capex") or {}).get("value")
        if rev is None:
            continue
        tl.append(p["fiscal_year_end"][:4])
        tr.append(round(rev / 1e6))
        tf.append(round((ocf - cap) / 1e6) if ocf is not None and cap is not None else None)

    du = fund["dupont"]
    peer_links = "".join(
        f'<a class="nav-btn" href="{SLUGS[p]}_report.html">{p}</a>' for p in peers)
    derived_at = data["assumptions"].get("derived_at")
    stale_after = data["assumptions"].get("stale_after_days", 90)
    if derived_at:
        assumption_age = (
            '<p class="assumption-age-note">🕒 DCF 假設年齡：'
            f'<time class="assumption-age" datetime="{html.escape(derived_at)}" '
            f'data-derived="{html.escape(derived_at)}" data-stale-after="{stale_after}">'
            f'推導於 {html.escape(derived_at)}</time>'
            f'<span>超過 {stale_after} 天只顯示提醒，不會自動重推。</span></p>')
    else:
        assumption_age = (
            '<p class="assumption-age-note">⚠️ DCF 假設缺少推導日期，無法判斷新鮮度。</p>')

    return {
        "name": data["financials"][ticker]["entity_name"],
        "form": h["source_form"] or "10-K",
        "accession": h["source_accession"] or "",
        "fye": h["fiscal_year_end"],
        "hero": hero,
        "moat": md_to_html(sections["一"][1]) if "一" in sections
                else "<p>本公司尚無質化分析章節。</p>",
        "risks": md_to_html(sections["六"][1]) if "六" in sections
                 else "<p>本公司尚無風險因素章節（Master Thesis 未撰寫此節）。</p>",
        "risk_provenance": risk_provenance_html(ticker),
        "risk_changes": risk_change_html(data["risk_changes"].get(ticker)),
        "health": health_section(h),
        "quarterly_trend": quarterly_trend_section(quarterly_company),
        "guidance": guidance_section(quarterly_company, forward_inputs, guidance_history),
        "scenarios": scenario_section(fund, v, h.get("currency") or "USD"),
        "risk_matrix": risk_matrix_section(
            h, quarter_metrics(quarterly_company), v, data["risk_changes"].get(ticker)),
        "objective_assessment": objective_assessment_section(
            fund, h, v, quarterly_company, forward_inputs, guidance_history,
            data["risk_changes"].get(ticker)),
        "operating_context": operating_context_section(sections, quarterly_company, forward_inputs),
        "ranks": rank_cards(ticker, ranks),
        "peer_count": len(data["health"]),
        "financials": financials,
        "dcf": dcf_html,
        "assumption_age": assumption_age,
        "sortino": sortino,
        "yield": yield_html,
        "provenance": provenance_section(ticker, fund, h, v),
        "peer_links": peer_links,
        "trend_labels": json.dumps(tl),
        "trend_revenue": json.dumps(tr),
        "trend_fcf": json.dumps(tf),
        "dupont_data": json.dumps([
            round((du["net_margin"] or 0) * 100, 2),
            du["asset_turnover"], du["equity_multiplier"]]),
        "dcf_labels": json.dumps(labels),
        "dcf_data": json.dumps(vals),
        "dcf_colors": json.dumps(colors),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+")
    args = parser.parse_args()

    risk_changes = {}
    path = REPO_ROOT / "risk_changes.json"
    if path.exists():
        risk_changes = json.loads(path.read_text())["companies"]

    data = {
        "risk_changes": risk_changes,
        "forward_inputs": (load("forward_looking_inputs.json").get("companies", {})
                           if (REPO_ROOT / "forward_looking_inputs.json").exists() else {}),
        "guidance_history": (load("guidance_history.json").get("companies", {})
                             if (REPO_ROOT / "guidance_history.json").exists() else {}),
        "assumptions": load("dcf_assumptions.json"),
        "fundamentals": load("fundamentals.json")["companies"],
        "valuation": load("valuation.json")["companies"],
        "health": load("financial_health.json")["companies"],
        "financials": load("financials.json")["companies"],
        "quarterly": load("quarterly_financials.json")["companies"],
    }
    ranks = build_ranks(data["fundamentals"], data["health"])
    tickers = args.tickers or [t for t in SLUGS if t in data["health"]]

    all_claims = []
    written = 0
    for ticker in tickers:
        if ticker not in data["health"]:
            print(f"  {ticker:6s} 略過（無資料）")
            continue
        peers = [p for p in ("NVDA", "TSM", "GOOGL", "MSFT") if p != ticker][:3]
        ctx = build_context(ticker, data, ranks, peers)
        out = REPO_ROOT / f"{SLUGS[ticker]}_report.html"
        page = render(ticker, ctx)
        # The build stamp changes every run, so writing unconditionally would
        # show all fourteen files as modified even when no figure moved. Compare
        # everything except the stamp, the same way fetch_price_history.py
        # avoids committing prices.json on a quiet day.
        if out.exists() and strip_stamp(out.read_text()) == strip_stamp(page):
            print(f"  {ticker:6s} -> {out.name:20s} 無變更")
            continue
        out.write_text(page)
        written += 1

        sections = split_sections(thesis_path(ticker).read_text()) \
            if thesis_path(ticker).exists() else {}
        claims = check_unverifiable_claims(ticker, sections)
        all_claims += [(ticker, c) for c in claims]
        print(f"  {ticker:6s} -> {out.name:20s} "
              f"{h_flags(data['health'][ticker])}"
              f"{'  ⚠️ ' + str(len(claims)) + ' 處無法驗證的宣稱' if claims else ''}")

    print(f"\n{written} / {len(tickers)} 份報告有變更並已寫入")
    if all_claims:
        print(f"\n以下宣稱本庫資料無法佐證，請在 30_Analysis 的 Master Thesis 中修正"
              f"（報告會原樣呈現）：")
        for ticker, c in all_claims:
            print(f"  {ticker:6s} …{c}…")


STAMP = re.compile(r"於 \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC 產生")


def strip_stamp(page):
    return STAMP.sub("於 <stamp> 產生", page)


def h_flags(h):
    if not h["coverage"]["sufficient"]:
        return f'資料不足 {h["coverage"]["computed"]}/{h["coverage"]["total"]}'
    return f'{h["flag_count"]} 項警示' if h["flag_count"] else '無警示'


if __name__ == "__main__":
    main()
