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
            f'<div class="rank-card"><div class="rank-label">{html.escape(label)}</div>'
            f'<div class="rank-pos">{medal} 第 {pos} / {total}</div>'
            f'<div class="rank-val">{shown}</div></div>')
    return "\n".join(cards)


# --------------------------------------------------------------------------
# generated sections

def kpi(label, value, sub=""):
    return (f'<div class="kpi-box"><div class="kpi-label">{html.escape(label)}</div>'
            f'<div class="kpi-val">{value}</div>'
            f'<div class="kpi-sub">{html.escape(sub)}</div></div>')


def metric(label, value, tone=""):
    cls = f"metric-card {tone}".strip()
    return (f'<div class="{cls}"><div class="title">{html.escape(label)}</div>'
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
border-radius:20px;padding:28px;box-shadow:var(--glow)}
.card-full{grid-column:1/-1}
.card h2{font-size:1.25rem;font-weight:800;margin-bottom:18px;color:#fff}
.card h3{font-size:1.05rem;font-weight:700;margin:18px 0 10px;color:#e5e7eb}
.sub-heading{font-size:.95rem;font-weight:700;margin:18px 0 8px;color:var(--accent)}
.card ul,.card ol{padding-left:1.25rem;margin:6px 0}
.card li{margin:6px 0;color:#d1d5db;font-size:.925rem}
.card p{color:#d1d5db;font-size:.925rem;margin:8px 0}
.note{font-size:.85rem;color:var(--text-muted);border-left:3px solid var(--accent);
padding-left:12px;margin:12px 0}
code{background:rgba(255,255,255,.08);padding:1px 6px;border-radius:5px;font-size:.85em}
.metric-group{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px}
.metric-card{background:rgba(0,0,0,.28);border:1px solid var(--card-border);
border-radius:14px;padding:14px 16px}
.metric-card.warn{border-color:rgba(251,191,36,.45);background:rgba(251,191,36,.08)}
.metric-card .title{font-size:.775rem;color:var(--text-muted)}
.metric-card .value{font-size:1.2rem;font-weight:800;color:#fff;margin-top:4px}
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
      <div class="hero-subtitle">財務健全度、估值與下行風險 — 全部數據由 SEC XBRL 與實際收盤價產生</div>
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
      <h2>🏅 本組合相對排名（{ctx['peer_count']} 家）</h2>
      <div class="rank-strip">{ctx['ranks']}</div>
      <p class="note">排名僅涵蓋本知識庫追蹤的 {ctx['peer_count']} 家公司，每次產生時重新計算。不代表全市場排名。</p>
    </div>

    <div class="card">
      <h2>📊 損益、現金流與資產負債</h2>
      <div class="metric-group">{ctx['financials']}</div>
      <h3>DuPont 三因子拆解</h3>
      <div class="chart-container"><canvas id="dupontChart"></canvas></div>
    </div>

    <div class="card">
      <h2>🎲 蒙地卡羅 DCF 估值分佈</h2>
      {ctx['dcf']}
      <div class="chart-container"><canvas id="dcfChart"></canvas></div>
    </div>

    <div class="card">
      <h2>📉 下行風險（Sortino Ratio）</h2>
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
      <p class="note">本節為人工撰寫的質化分析，來源為 30_Analysis 的 Master Thesis，非由財報數字產生。</p>
    </div>

    <div class="card card-full">
      <h2>🔎 資料來源與限制</h2>
      {ctx['provenance']}
    </div>
  </div>

  <footer>
    由 <code>scripts/build_reports.py</code> 於 {ctx['generated_at']} 產生。<br>
    本頁不含任何手動輸入的財務數字；質化章節除外，且已標示。<br>
    DCF 為特定假設下的推估，非事實，不構成投資建議。
  </footer>
</div>

<script>
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
        dcf_html = (
            '<div class="metric-group">'
            + metric("P25 ~ P75 主流區間", band)
            + metric("中位數 P50", median)
            + metric("相對現價", rel)
            + '</div>'
            + '<p class="note">假設：g={:.2%}、WACC={:.2%}、終端成長={:.1%}、{:,} 次模擬。{}</p>'
              .format(a["growth"], a["wacc"], a["terminal_growth"], a["simulations"],
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
        "health": health_section(h),
        "ranks": rank_cards(ticker, ranks),
        "peer_count": len(data["health"]),
        "financials": financials,
        "dcf": dcf_html,
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

    data = {
        "fundamentals": load("fundamentals.json")["companies"],
        "valuation": load("valuation.json")["companies"],
        "health": load("financial_health.json")["companies"],
        "financials": load("financials.json")["companies"],
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
