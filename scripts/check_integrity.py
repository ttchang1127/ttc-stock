"""Run every data-integrity check and fail the process if any of them does.

These checks existed only as copy-paste snippets in the maintenance SOP, which
meant nothing ran them unless a person remembered to. Three of them caught
mistakes that had already been committed, and two of those were already live:

    C-7a  valuation.json and financial_health.json disagreed about
          interest-bearing debt, putting TSMC's net cash $29bn too high and
          feeding that straight into its DCF.

    C-10  the scorecard measured ROIC against the previous discount rates
          after dcf_assumptions.json was re-derived and only half the pipeline
          was re-run. NVIDIA published +67.0pp against a true +62.2pp.

    C-11  TSMC's ordinary share count was multiplied by its ADR price,
          producing a $10.9tn market capitalisation, 123x revenue.

A check that runs only when someone thinks to run it is not a guard. This is
wired into the scheduled workflow ahead of the commit step, so data that fails
is never pushed.

    python3 scripts/check_integrity.py          # all checks
    python3 scripts/check_integrity.py --quiet  # only failures
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Registered by @check so the report always lists every one, including the
# ones that pass -- a silent run cannot be told apart from a run that did not
# happen.
CHECKS = []


def check(code, title):
    def register(fn):
        CHECKS.append((code, title, fn))
        return fn
    return register


def load(name):
    path = REPO_ROOT / name
    if not path.exists():
        raise FileNotFoundError(name)
    return json.loads(path.read_text())


def read(name):
    return (REPO_ROOT / name).read_text()


# --------------------------------------------------------------------------
# Each check returns (ok, detail). A check that cannot run its comparison is a
# failure, not a pass: missing inputs are exactly when a mistake slips through.

@check("C-1", "假資料產生器沒有復活")
def c1():
    hits = len(re.findall(r"Math\.sin|Math\.random|seedMap", read("dashboard.html")))
    return hits == 0, f"dashboard.html 命中 {hits} 次（預期 0）"


@check("C-2", "現役管線腳本沒有被寫死數字")
def c2():
    pattern = re.compile(
        r"^\s*(f[1-9]|total_assets|net_income|revenue)_?[a-z0-9]* *= *[0-9]", re.M)
    bad = [p.name for p in sorted((REPO_ROOT / "scripts").glob("*.py"))
           if pattern.search(p.read_text())]
    return not bad, f"寫死數字的腳本：{bad or '無'}"


@check("C-3", "每份 thesis 都有可追溯來源")
def c3():
    missing = [p.name for p in sorted((REPO_ROOT / "30_Analysis").glob("*_Master_Investment_Thesis_2026.md"))
               if "financials_accession:" not in p.read_text()]
    return not missing, f"缺 accession：{missing or '無'}"


@check("C-4", "thesis 的 F-Score 與 fundamentals.json 一致")
def c4():
    fund = load("fundamentals.json")["companies"]
    bad = []
    for path in sorted((REPO_ROOT / "30_Analysis").glob("*_Master_Investment_Thesis_2026.md")):
        ticker = path.name.split("_")[0]
        p = (fund.get(ticker) or {}).get("piotroski")
        if not p:
            continue
        m = re.search(r"Piotroski F-Score\*\*: \*\*(\d+) / (\d+)\*\*", path.read_text())
        if not m:
            bad.append(f"{ticker}(thesis 無 F-Score)")
        elif (int(m.group(1)), int(m.group(2))) != (p["score"], p["max_evaluated"]):
            bad.append(f"{ticker}({m.group(1)}/{m.group(2)} vs {p['score']}/{p['max_evaluated']})")
    return not bad, f"不一致：{bad or '無'}"


@check("C-5", "Sortino 使用調整後收盤價且有完整計算窗口")
def c5():
    bad = []
    prices = load("prices.json")
    if prices.get("series_price_field") != "Adj Close":
        bad.append("prices.json 未標示 Adj Close")
    fund = load("fundamentals.json")["companies"]
    for ticker, company in sorted(fund.items()):
        for key, years in (("3y", 3), ("5y", 5)):
            entry = (company.get("sortino") or {}).get(key) or {}
            if entry.get("value") is None:
                continue
            history_start = entry.get("history_start")
            window_end = entry.get("window_end")
            if not history_start or not window_end:
                bad.append(f"{ticker}/{key}(缺完整窗口證據)")
                continue
            cutoff = datetime.fromisoformat(window_end).replace(
                year=datetime.fromisoformat(window_end).year - years)
            if datetime.fromisoformat(history_start) > cutoff:
                bad.append(f"{ticker}/{key}(歷史未滿 {years} 年)")
    for path in sorted((REPO_ROOT / "30_Analysis").glob("*_Master_Investment_Thesis_2026.md")):
        for line in path.read_text().splitlines():
            if "Sortino Ratio（週資料）" in line and "週報酬" not in line and "資料不足" not in line:
                bad.append(path.name)
                break
    return not bad, f"口徑或窗口問題：{bad or '無'}"


@check("C-6", "健全度沒有把「資料不足」講成「健全」")
def c6():
    health = load("financial_health.json")["companies"]
    # Not a failure: this reports which companies are in that state so it can be
    # seen. It fails only if one of them is *not* labelled 資料不足.
    unlabelled = [t for t, v in health.items()
                  if not v["flags"] and not v["coverage"]["sufficient"]
                  and not v["coverage"].get("note")]
    listed = [t for t, v in health.items()
              if not v["flags"] and not v["coverage"]["sufficient"]]
    return not unlabelled, (f"無警示但資料不足且已標示：{listed or '無'}"
                            + (f"；未標示：{unlabelled}" if unlabelled else ""))


@check("C-7a", "valuation 與 financial_health 的有息負債一致")
def c7a():
    val = load("valuation.json")["companies"]
    health = load("financial_health.json")["companies"]
    bad = [t for t in val
           if health[t]["solvency"]["total_debt"] is not None
           and val[t]["multiples"]["total_debt"] != health[t]["solvency"]["total_debt"]]
    return not bad, f"不一致：{bad or '無'}"


@check("C-7b", "沒有第四支腳本自己組裝負債")
def c7b():
    allowed = {"fetch_xbrl_financials.py",     # 科目對照表，本來就要列標籤名
               "compute_financial_health.py",  # total_debt 的實作處
               "compute_fundamentals.py"}      # Piotroski 第 5 項用長期負債比
    concepts = re.compile(
        r"['\"](long_term_debt|debt_current|bonds_(?:non)?current|"
        r"finance_lease_\w+|convertible_debt_\w+)['\"]")
    bad = [p.name for p in sorted((REPO_ROOT / "scripts").glob("*.py"))
           if concepts.search(p.read_text()) and p.name not in allowed]
    return not bad, f"自行組裝負債：{bad or '無'}"


@check("C-7c", "兩個檔案的毛利率一致")
def c7c():
    """The same failure mode as C-7a: one metric, two files, two answers.

    compute_fundamentals.py fell back to revenue minus cost of sales when a
    filer does not tag GrossProfit; compute_financial_health.py did so only
    inside its Beneish indices. So Amazon, Alphabet, Meta and Coherent read
    50.29% / 59.65% / 82.00% / 35.17% on one page and 資料不足 on the other.
    """
    fund = load("fundamentals.json")["companies"]
    health = load("financial_health.json")["companies"]
    bad = [t for t in fund
           if fund[t].get("gross_margin") != health[t]["profitability"]["gross_margin"]]
    return not bad, f"不一致：{bad or '無'}"


@check("C-8", "每個算不出來的指標都有說明")
def c8():
    health = load("financial_health.json")["companies"]
    bad = []
    for t, v in health.items():
        sol, prof = v["solvency"], v["profitability"]
        if sol["interest_coverage"] is None and not sol["interest_coverage_note"]:
            bad.append(f"{t}/利息保障")
        if sol["total_debt"] is None and not sol["total_debt_note"]:
            bad.append(f"{t}/有息負債")
        if prof["roic"] is None and not prof["roic_note"]:
            bad.append(f"{t}/ROIC")
    return not bad, f"null 無說明：{bad or '無'}"


@check("C-13", "thesis 第六章沒有抄寫會過期的財務數字")
def c13():
    """第六章是人寫的判斷，update_thesis_financials.py 從不改它。

    所以數字一抄進去就凍住了。查核當下 13 家有 9 家的第六章本益比與同一頁
    第四節不符（COHR 824.2x vs 1188.6x，ARM 283.2x vs 333.8x），其中兩家的
    結論方向已經相反 —— NVDA 的「多頭優勢」寫著「現價 $200.75 較中位數
    $313.44 折價 36.0%」，而第五節同時寫著現價高於中位數 47.5%；MSFT 寫著
    「P/E 25.9x 高於 DCF 保守中位數」，實際已略低於中位數。

    另有三家把「現金與短期投資總額」寫成「淨現金」：NOK 的 €54.6 億實際淨
    現金只有 €10.5 億（有息負債 €44.1 億），差 5.2 倍。

    因此這裡不比對數值，而是禁止數值出現：要引用就寫「見第二節」，讓讀者
    看腳本重算過的那一份。年份、製程節點（2nm/18A）、規格（800G/1.6T）等
    不會隨財報變動的數字不在此列。
    """
    patterns = [
        (r"P/E[  ]?[\d.,]+ ?x|本益比[^。\n]{0,8}[\d.,]+ ?[x倍]", "本益比"),
        (r"現價[  ]?\$[\d.,]+", "現價"),
        (r"中位數[^。\n]{0,12}\$[\d.,]+|\$[\d.,]+[^。\n]{0,8}中位數", "DCF 中位數"),
        (r"(?:折價|溢價|高於中位數|低於中位數)[^。\n]{0,6}[\d.]+ ?%", "與中位數的價差"),
        (r"(?:毛利率|淨利率|ROE|ROIC|殖利率|Sortino[^。\n]{0,12})[^。\n]{0,10}[\d.]+ ?%",
         "利潤率／報酬率"),
        (r"F-Score[^。\n]{0,6}\d ?/ ?\d", "F-Score"),
        # Sortino 是裸數字而非百分比，上一條的 % 抓不到它。
        (r"Sortino[^。\n]{0,12}[\d]+\.[\d]+", "Sortino"),
        (r"(?:淨現金|淨負債|自由現金流|FCF|OCF|營運現金流|CapEx|資本支出|庫藏股|債務)"
         r"[^。\n]{0,16}[\$€][ ]?-?[\d.,]+[ ]?(?:億|百萬)?", "金額"),
    ]
    bad = []
    for path in sorted((REPO_ROOT / "30_Analysis").glob("*_Master_Investment_Thesis_2026.md")):
        text = path.read_text()
        m = re.search(r"^## .*六、.*$", text, re.M)
        if not m:
            continue
        section = text[m.start():].split("\n## ")[0]
        for line in section.split("\n"):
            # 說明「這裡先前寫著什麼、為什麼不再寫」的更正句需要引用舊值。
            if "先前寫" in line or line.lstrip().startswith(">"):
                continue
            for pattern, label in patterns:
                hit = re.search(pattern, line)
                if hit:
                    bad.append(f"{path.name.split('_')[0]}/{label}「{hit.group(0)}」")
                    break
    return not bad, f"第六章的過期數字：{bad or '無'}"


@check("C-9", "報告等於生成器輸出（未被手改、未過期）")
def c9():
    """Does every page on disk equal what the generator would produce now?

    The first version of this ran build_reports.py and then compared against
    git HEAD -- which destroys the evidence before looking at it. Regenerating
    overwrites a hand edit, so the check passed on a page whose price had been
    changed to $999.99 by hand. Verified by trying exactly that.

    So the working tree is snapshotted first, the generator runs, and the two
    are compared. That single comparison answers both questions at once: a
    difference means the page was either edited by hand or generated from data
    that has since moved.

    The build stamp is excluded, since it changes on every write even when no
    figure does.
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from build_reports import strip_stamp                    # noqa: PLC0415

    before = {p.name: p.read_text() for p in sorted(REPO_ROOT.glob("*_report.html"))}
    subprocess.run([sys.executable, "scripts/build_reports.py"],
                   cwd=REPO_ROOT, capture_output=True, check=False)

    bad = [name for name, old in before.items()
           if strip_stamp(old) != strip_stamp((REPO_ROOT / name).read_text())]
    missing = [p.name for p in sorted(REPO_ROOT.glob("*_report.html"))
               if p.name not in before]
    return not (bad or missing), (
        f"與生成器輸出不符：{bad or '無'}"
        + (f"；新產生：{missing}" if missing else "")
        + "（已忽略產生時間戳；不符者已被重新產生覆蓋）")


@check("C-10", "三個檔案的 WACC 一致")
def c10():
    assume = load("dcf_assumptions.json")["companies"]
    health = load("financial_health.json")["companies"]
    val = load("valuation.json")["companies"]
    bad = [t for t, a in assume.items()
           if a["wacc"] is not None
           and not (a["wacc"] == health[t]["profitability"]["wacc"]
                    == val[t]["assumptions"]["wacc"])]
    return not bad, f"不一致：{bad or '無'}"


@check("C-11", "市值與股數基準合理")
def c11():
    fund = load("fundamentals.json")["companies"]
    # Arm licenses IP and Ondas has almost no revenue yet; both carry a high
    # multiple for a reason. Anything else above 40x means the share count and
    # the quoted price are not on the same basis.
    expected_high = {"ARM", "ONDS"}
    bad = [(t, round(v["market_cap"] / v["revenue"], 1)) for t, v in fund.items()
           if v.get("market_cap") and v.get("revenue")
           and v["market_cap"] / v["revenue"] > 40 and t not in expected_high]
    return not bad, f"市值/營收異常：{bad or '無'}"


@check("C-12", "沒有公司的財報過期未揭露")
def c12():
    health = load("financial_health.json")["companies"]
    # Staleness itself is allowed -- SEC may simply not have newer data. What is
    # not allowed is a stale company without the note that says so.
    bad = [t for t, v in health.items()
           if v["freshness"]["stale"] and not v["freshness"].get("note")]
    stale = [f"{t}({v['freshness']['months_old']}個月)"
             for t, v in health.items() if v["freshness"]["stale"]]
    return not bad, (f"過期但已揭露：{stale or '無'}"
                     + (f"；過期且未揭露：{bad}" if bad else ""))


@check("C-14", "DCF 假設日期完整且頁面會顯示年齡")
def c14():
    assumptions = load("dcf_assumptions.json")
    raw = assumptions.get("derived_at")
    try:
        derived = date.fromisoformat(raw)
    except (TypeError, ValueError):
        return False, f"derived_at 無效：{raw!r}"
    if derived > date.today():
        return False, f"derived_at 在未來：{raw}"
    stale_after = assumptions.get("stale_after_days")
    if not isinstance(stale_after, int) or stale_after <= 0:
        return False, f"stale_after_days 無效：{stale_after!r}"
    notes_without_date = [
        ticker for ticker, node in assumptions["companies"].items()
        if raw not in (node.get("note") or "")
    ]
    ui_missing = [
        name for name, marker in (
            ("build_reports.py", "assumption-age"),
            ("dashboard.html", "dcfAssumptionAge"),
        )
        if marker not in read("scripts/" + name if name.endswith(".py") else name)
    ]
    ok = not notes_without_date and not ui_missing
    return ok, (
        f"推導日 {raw}；提醒門檻 {stale_after} 天；"
        f"note 缺日期：{notes_without_date or '無'}；"
        f"頁面缺年齡標記：{ui_missing or '無'}")


@check("C-15", "14 家都有八季趨勢且頁面顯示新分析")
def c15():
    quarterly = load("quarterly_financials.json")["companies"]
    short = [f"{ticker}({len(node.get('periods', []))}期)"
             for ticker, node in sorted(quarterly.items())
             if len(node.get("periods", [])) < 8]
    markers = ["八季營運趨勢", "管理層指引 vs. 實際結果", "可追蹤風險矩陣", "分部與集中度分析"]
    missing = [f"{path.name}/{marker}" for path in sorted(REPO_ROOT.glob("*_report.html"))
               for marker in markers if marker not in path.read_text()]
    dashboard_missing = [marker for marker in ("查看公司八季數字", "slice(0, 8)")
                         if marker not in read("dashboard.html")]
    ok = len(quarterly) == 14 and not short and not missing and not dashboard_missing
    return ok, (f"公司 {len(quarterly)} 家；不足八季：{short or '無'}；"
                f"報告缺段落：{missing or '無'}；儀表板缺標記：{dashboard_missing or '無'}")


@check("C-16", "管理層指引只能使用有來源的人工核對值")
def c16():
    inputs = load("forward_looking_inputs.json")["companies"]
    tracked = set(load("financials.json")["companies"])
    bad = []
    for ticker, company in sorted(inputs.items()):
        status = company.get("guidance_status")
        rows = company.get("guidance") or []
        if status not in {"available", "no_comparable_numeric_guidance"}:
            bad.append(f"{ticker}(指引狀態無效)")
        if status == "available" and not rows:
            bad.append(f"{ticker}(標示有指引但無資料)")
        if status == "no_comparable_numeric_guidance":
            if rows:
                bad.append(f"{ticker}(標示無可比指引但仍有資料)")
            if not company.get("guidance_note") or not company.get("guidance_source_url"):
                bad.append(f"{ticker}(無指引說明缺來源或原因)")
        for index, row in enumerate(rows, 1):
            if not row.get("period") or not row.get("metric") or not row.get("source_url"):
                bad.append(f"{ticker}#{index}(缺期間、指標或來源)")
            if row.get("low") is None and row.get("high") is None:
                bad.append(f"{ticker}#{index}(缺指引數值)")
            if (row.get("low") is not None and row.get("high") is not None
                    and row["low"] > row["high"]):
                bad.append(f"{ticker}#{index}(指引上下限顛倒)")
    missing = sorted(tracked - set(inputs))
    extra = sorted(set(inputs) - tracked)
    ok = not bad and not missing and not extra
    return ok, f"欄位錯誤：{bad or '無'}；缺公司：{missing or '無'}；多餘公司：{extra or '無'}"


@check("C-17", "分部數字有官方來源且結構可計算")
def c17():
    inputs = load("forward_looking_inputs.json")["companies"]
    bad = []
    covered = []
    for ticker, company in sorted(inputs.items()):
        segments = company.get("segments")
        if not segments:
            continue
        covered.append(ticker)
        if not all(segments.get(key) for key in ("period", "source_date", "source_url", "unit")):
            bad.append(f"{ticker}(缺期間、日期、單位或來源)")
        items = segments.get("items") or []
        if len(items) < 2:
            bad.append(f"{ticker}(分部不足 2 項)")
        for index, row in enumerate(items, 1):
            if not row.get("name") or row.get("revenue") is None:
                bad.append(f"{ticker}#{index}(缺名稱或營收)")
            elif not isinstance(row["revenue"], (int, float)) or row["revenue"] < 0:
                bad.append(f"{ticker}#{index}(營收格式無效)")
    return not bad, f"已覆蓋 {len(covered)} 家：{covered or '無'}；錯誤：{bad or '無'}"


@check("C-18", "14 家都有規則化客觀綜合評價")
def c18():
    markers = ["🧾 客觀綜合評價", "目前定位：", "財務體質", "營運趨勢",
               "指引執行", "估值壓力", "風險水位", "不是買進／賣出建議"]
    reports = sorted(REPO_ROOT.glob("*_report.html"))
    missing = [f"{path.name}/{marker}" for path in reports
               for marker in markers if marker not in path.read_text()]
    generator = read("scripts/build_reports.py")
    rule_missing = [marker for marker in ("objective_assessment_section", "guidance_outcome",
                                           "risk_matrix_data") if marker not in generator]
    ok = len(reports) == 14 and not missing and not rule_missing
    return ok, (f"報告 {len(reports)} 份；缺標記：{missing or '無'}；"
                f"產生器缺規則：{rule_missing or '無'}")


@check("C-19", "近三年指引回測有來源且口徑一致")
def c19():
    payload = load("guidance_history.json")
    companies = payload.get("companies") or {}
    fields = payload.get("record_fields") or []
    tracked = set(load("financials.json")["companies"])
    quarterly = load("quarterly_financials.json")["companies"]
    valid_statuses = {"available", "no_consistent_numeric_guidance", "different_cadence"}
    bad = []
    available = []
    record_count = 0
    if fields != ["period", "period_end", "low", "high", "actual",
                  "guidance_date", "guidance_source_url"]:
        bad.append("record_fields 格式錯誤")
    for ticker, company in sorted(companies.items()):
        status = company.get("status")
        records = company.get("records") or []
        if status not in valid_statuses:
            bad.append(f"{ticker}(狀態無效)")
            continue
        if status != "available":
            if records:
                bad.append(f"{ticker}(不可比較卻有回測列)")
            if not company.get("note") or not company.get("review_url"):
                bad.append(f"{ticker}(不可比較但缺原因或官方入口)")
            continue
        available.append(ticker)
        if len(records) < 4 or len(records) > 12:
            bad.append(f"{ticker}(樣本 {len(records)} 期)")
        if not all(company.get(key) for key in ("metric", "unit", "comparison_basis")):
            bad.append(f"{ticker}(缺指標、單位或比較口徑)")
        known_periods = {row.get("period_end") for row in quarterly.get(ticker, {}).get("periods", [])}
        period_nodes = {row.get("period_end"): row
                        for row in quarterly.get(ticker, {}).get("periods", [])}
        explicit_actual_sources = company.get("actual_sources") or {}
        seen = set()
        for index, raw in enumerate(records, 1):
            record_count += 1
            if not isinstance(raw, list) or len(raw) != len(fields):
                bad.append(f"{ticker}#{index}(欄位數錯誤)")
                continue
            row = dict(zip(fields, raw))
            period_key = (row.get("period"), row.get("period_end"))
            if period_key in seen:
                bad.append(f"{ticker}#{index}(期間重複)")
            seen.add(period_key)
            if (row.get("period_end") not in known_periods
                    and row.get("period_end") not in explicit_actual_sources):
                bad.append(f"{ticker}#{index}(找不到實績期末 {row.get('period_end')})")
            if not row.get("period") or not row.get("guidance_date") or not row.get("guidance_source_url"):
                bad.append(f"{ticker}#{index}(缺期間、日期或指引來源)")
            elif row["guidance_date"] > row["period_end"]:
                bad.append(f"{ticker}#{index}(指引日期晚於期末，疑有後見偏誤)")
            if not str(row.get("guidance_source_url") or "").startswith("https://"):
                bad.append(f"{ticker}#{index}(來源不是 HTTPS)")
            low, high, actual = row.get("low"), row.get("high"), row.get("actual")
            if not all(isinstance(value, (int, float)) for value in (low, high, actual)):
                bad.append(f"{ticker}#{index}(上下限或實績不是數字)")
            elif low > high:
                bad.append(f"{ticker}#{index}(上下限顛倒)")
            period_node = period_nodes.get(row.get("period_end")) or {}
            revenue_node = (period_node.get("values") or {}).get("revenue")
            if isinstance(revenue_node, dict) and revenue_node.get("unit") == "USD":
                official_bn = revenue_node.get("value") / 1_000_000_000
                if abs(actual - official_bn) > .001:
                    bad.append(f"{ticker}#{index}(實績 {actual} 與季度資料 {official_bn:.6f} 不符)")
    missing = sorted(tracked - set(companies))
    extra = sorted(set(companies) - tracked)
    ok = (payload.get("window_years") == 3 and not bad and not missing and not extra
          and len(available) == 9 and record_count == 107)
    return ok, (f"可回測 {len(available)} 家／{record_count} 期：{available}；"
                f"欄位錯誤：{bad or '無'}；缺公司：{missing or '無'}；多餘公司：{extra or '無'}")


@check("C-20", "14 家報告顯示近三年指引紀錄與樣本限制")
def c20():
    history = load("guidance_history.json")["companies"]
    missing = []
    for ticker, company in sorted(history.items()):
        slug = {"GOOGL": "goog"}.get(ticker, ticker.lower())
        path = REPO_ROOT / f"{slug}_report.html"
        if not path.exists():
            missing.append(f"{ticker}(缺報告)")
            continue
        page = path.read_text()
        for marker in ("近 3 年指引執行紀錄", "不計入命中率"):
            if marker == "不計入命中率" and company.get("status") == "available":
                continue
            if marker not in page:
                missing.append(f"{ticker}/{marker}")
        if company.get("status") == "available":
            for marker in ("可驗證樣本", "達標率", "平均相對中點", "展開近 3 年逐期紀錄"):
                if marker not in page:
                    missing.append(f"{ticker}/{marker}")
    generator = read("scripts/build_reports.py")
    rule_missing = [marker for marker in ("guidance_history_stats", "historical_guidance_section",
                                           "sample_count < 4") if marker not in generator]
    return not missing and not rule_missing, (f"頁面缺標記：{missing or '無'}；"
                                              f"產生器缺規則：{rule_missing or '無'}")


@check("C-21", "進階 SEC 八類雷達資料與口徑完整")
def c21():
    advanced = load("sec_advanced_radars.json")
    thirteen_f = load("sec_13f_stock_radar.json")
    tracked = set(load("financials.json")["companies"])
    minimums = {
        "footnotes": 14, "accounting_review": 1, "ownership_13dg": 1,
        "governance": 1, "insiders": 14,
    }
    bad_counts = {
        key: len(advanced.get(key, [])) for key, minimum in minimums.items()
        if len(advanced.get(key, [])) < minimum
    }
    bad_13f = []
    if len(thirteen_f.get("periods", [])) != 2:
        bad_13f.append("不是兩個報告期")
    if set(thirteen_f.get("stocks", {})) != tracked:
        bad_13f.append("公司覆蓋不是 14 家")
    for ticker, node in thirteen_f.get("stocks", {}).items():
        for snapshot in node.get("snapshots", []):
            if "value_usd" not in snapshot or "value_usd_thousands" in snapshot:
                bad_13f.append(f"{ticker} VALUE 單位欄位錯誤")
    merger_rows = advanced.get("mergers", [])
    merger_deals = advanced.get("merger_deals", [])
    merger_window = advanced.get("merger_window", {})
    bad_mergers = []
    if merger_window.get("years") != 3:
        bad_mergers.append("不是最近 3 年")
    cutoff = merger_window.get("cutoff", "")
    if not cutoff or any(row.get("event", {}).get("filing_date", "") < cutoff for row in merger_rows):
        bad_mergers.append("含時間窗外文件")
    if not merger_deals:
        bad_mergers.append("沒有合併後交易")
    if sum(deal.get("document_count", 0) for deal in merger_deals) != len(merger_rows):
        bad_mergers.append("交易文件數無法對帳")
    if merger_window.get("deal_count") != len(merger_deals):
        bad_mergers.append("交易宗數欄位不一致")
    if merger_window.get("document_count") != len(merger_rows):
        bad_mergers.append("文件數欄位不一致")
    bad_ownership = []
    for row in advanced.get("ownership_13dg", []):
        facts = row.get("ownership", {})
        if facts.get("data_status") not in {"parsed", "threshold_exit"}:
            bad_ownership.append(f"{row.get('ticker')}/{row.get('accession')} 未解析實際持股")
        percent = facts.get("percent_of_class")
        shares = facts.get("aggregate_shares")
        if percent is not None and not 0 <= percent <= 100:
            bad_ownership.append(f"{row.get('ticker')}/{row.get('accession')} 持股比例超界")
        if shares is not None and shares < 0:
            bad_ownership.append(f"{row.get('ticker')}/{row.get('accession')} 持股數為負")
    ownership_snapshot = advanced.get("ownership_snapshot", [])
    if not ownership_snapshot:
        bad_ownership.append("缺少最新狀態總覽")
    snapshot_keys = set()
    for item in ownership_snapshot:
        key = (item.get("ticker"), item.get("owner_key"), tuple(item.get("cusips", [])))
        if key in snapshot_keys:
            bad_ownership.append(f"{item.get('ticker')}/{item.get('owner_key')} 最新狀態重複")
        snapshot_keys.add(key)
        if item.get("status") not in {"above_5", "exit", "realignment", "unknown"}:
            bad_ownership.append(f"{item.get('ticker')}/{item.get('owner_key')} 狀態無效")
        if item.get("history_count") != len(item.get("history", [])):
            bad_ownership.append(f"{item.get('ticker')}/{item.get('owner_key')} 歷史數量不一致")
    ownership_timeline = advanced.get("ownership_timeline", [])
    if len(ownership_timeline) != len(advanced.get("ownership_13dg", [])):
        bad_ownership.append("異動時間軸沒有逐份對應 13D/G 文件")
    timeline_accessions = set()
    for event in ownership_timeline:
        accession = event.get("accession")
        if not accession or accession in timeline_accessions:
            bad_ownership.append(f"{event.get('ticker')}/{accession or '無 accession'} 時間軸重複")
        timeline_accessions.add(accession)
        if event.get("importance") not in {"high", "watch", "routine"}:
            bad_ownership.append(f"{event.get('ticker')}/{accession} 警報級別無效")
        if not event.get("event_label") or not event.get("interpretation"):
            bad_ownership.append(f"{event.get('ticker')}/{accession} 缺少事件解讀")
    required_notes = [
        "Footnotes_Attachments_Radar.md", "Accounting_Review_Radar.md",
        "Schedule13DG_Ownership_Radar.md", "Governance_Compensation_Radar.md",
        "Insider_Forms_345144_Radar.md", "Mergers_Tender_Radar.md",
        "SEC_Enforcement_Radar.md", "Form13F_Stock_Radar.md",
    ]
    missing_notes = [name for name in required_notes if not (REPO_ROOT / "60_SEC_Filing_Radar" / name).exists()]
    page = read("dashboard.html")
    missing_ui = [marker for marker in ("secAdvancedCategory", "secAdvancedTicker",
                                         "secAdvancedInterpretation", "secAdvancedActual",
                                         "SEC_ADVANCED_INTERPRETATIONS", "目前實際申報內容",
                                         "secAdvancedForm4Facts", "advanced.merger_deals",
                                         "secOwnershipOverview", "renderSecOwnershipOverview",
                                         "大股東最新狀態總覽", "申報主體重整顯示 0 股時",
                                         "secOwnershipTimeline", "renderSecOwnershipTimeline",
                                         "大股東異動時間軸與警報", "顏色表示閱讀優先度",
                                         "secCoreShortcuts", "setSecCoreTicker",
                                         "同步切換①八季數字、②重要申報、③ Form 4",
                                         "secCompanyBrief", "renderSecCompanyBrief",
                                         "單公司 SEC 綜合判讀", "SEC 證據分數／100",
                                         "目前建議動作", "判讀信心", "支持證據", "風險證據",
                                         "什麼會改變結論", "實際稀釋股數 YoY", "不是買進／賣出指令",
                                         "重要文件本身只提高閱讀優先度，不預設多空",
                                         "secUpdateBrief", "renderSecUpdateBrief",
                                         "今天有什麼變化", "不是資料停更",
                                         "括號數字代表什麼", "合併後的交易宗數",
                                         "不受上方最近 7／14 日篩選影響")
                  if marker not in page]
    ok = (not advanced.get("errors") and not bad_counts and not bad_13f and not bad_mergers and not bad_ownership
          and not missing_notes and not missing_ui)
    return ok, (f"回填不足：{bad_counts or '無'}；13F：{bad_13f or '無'}；"
                f"併購：{bad_mergers or '無'}；13D/G：{bad_ownership or '無'}；"
                f"缺筆記：{missing_notes or '無'}；缺畫面：{missing_ui or '無'}；"
                f"解析錯誤：{advanced.get('errors') or '無'}")


@check("C-22", "10-K／10-Q 文字差異可追溯且不跨表單")
def c22():
    changes = load("filing_text_changes.json")
    tracked = set(load("financials.json")["companies"])
    companies = changes.get("companies", {})
    bad = []
    if set(companies) != tracked:
        bad.append("公司覆蓋不是 14 家")
    compared = 0
    unavailable = []
    for ticker, company in companies.items():
        if company.get("status") != "compared":
            unavailable.append(ticker)
            if company.get("status") not in {"unavailable", "insufficient"}:
                bad.append(f"{ticker} 非可比較狀態未安全保留缺值")
            sections = company.get("sections", {})
            if company.get("status") == "unavailable" and (
                not sections or any(not row.get("reason") for row in sections.values())
            ):
                bad.append(f"{ticker} 不可比較但缺章節原因")
            continue
        compared += 1
        if company.get("previous", {}).get("form") != company.get("latest", {}).get("form"):
            bad.append(f"{ticker} 混用不同表單")
        sections = [row for row in company.get("sections", {}).values() if row.get("status") == "compared"]
        if not sections:
            bad.append(f"{ticker} 沒有可靠章節")
        for section in sections:
            for row in section.get("added", []) + section.get("removed", []):
                if not row.get("excerpt"):
                    bad.append(f"{ticker} 缺實際摘錄")
            for row in section.get("modified", []):
                if not row.get("previous_excerpt") or not row.get("latest_excerpt"):
                    bad.append(f"{ticker} 改寫缺前後摘錄")
    if compared < len(tracked) - 2:
        bad.append(f"只有 {compared} 家可比較；不可比較：{unavailable}")
    page = read("dashboard.html")
    workflow = read(".github/workflows/sec-filing-alerts.yml")
    markers = ("secTextDiff", "renderSecTextDiff", "10-K／10-Q 文字差異雷達",
               "不再列出」不等於風險已消失", "filing_text_changes.json")
    missing = [marker for marker in markers if marker not in page]
    if "scripts/diff_periodic_filings.py" not in workflow or "filing_text_changes.json" not in workflow:
        missing.append("每日 workflow")
    return not bad and not missing, f"資料問題：{bad or '無'}；缺畫面／自動化：{missing or '無'}"


@check("C-23", "SEC 每日閱讀排序與八季趨勢圖完整")
def c23():
    quarterly = load("quarterly_financials.json")
    editorial = load("sec_daily_editorial.json")
    tracked = set(load("financials.json")["companies"])
    companies = quarterly.get("companies", {})
    bad = []
    if set(companies) != tracked:
        bad.append("八季資料公司覆蓋不是 14 家")
    short = [ticker for ticker, company in companies.items() if len(company.get("periods", [])) < 8]
    if short:
        bad.append(f"不足八季：{short}")
    editorial_companies = editorial.get("companies", [])
    editorial_tickers = {row.get("ticker") for row in editorial_companies}
    display_tickers = {"GOOG" if ticker == "GOOGL" else ticker for ticker in tracked}
    if editorial_tickers != display_tickers:
        bad.append("人工每日重點公司覆蓋不是 14 家")
    if sorted(row.get("rank") for row in editorial_companies) != list(range(1, 15)):
        bad.append("人工每日重點排名不是 1～14")
    incomplete_editorial = [row.get("ticker") for row in editorial_companies
                            if not row.get("summary") or len(row.get("evidence", [])) < 3
                            or not row.get("watch") or not row.get("source_url")]
    if incomplete_editorial:
        bad.append(f"人工每日重點不完整：{incomplete_editorial}")
    if editorial.get("schema_version") != 3:
        bad.append("人工每日重點不是含比較基準與 AI 覆蓋基準的 schema 3")
    expected_holdings = {"ARM", "COHR", "GOOG", "INTC", "MRVL", "NOK", "NVDA", "TSLA"}
    if set(editorial.get("portfolio_order", [])) != expected_holdings:
        bad.append("實際持股分組與個人持股部位明細不一致")
    comparison = editorial.get("comparison", {})
    if not isinstance(comparison.get("changes"), list) or not comparison.get("method"):
        bad.append("缺前次判讀比較基準")
    invalid_changes = [row for row in comparison.get("changes", [])
                       if row.get("type") not in {"risk", "improvement", "conclusion"}
                       or not row.get("summary")]
    if invalid_changes:
        bad.append("前次判讀變化含無效類型或缺摘要")
    incomplete_coverage = [row.get("ticker") for row in editorial_companies
                           if not isinstance(row.get("coverage"), dict)
                           or "ownership_accession" not in row["coverage"]
                           or not row["coverage"].get("quarterly_key")
                           or not row["coverage"].get("thesis_fingerprint")
                           or not isinstance(row["coverage"].get("enforcement_keys"), list)]
    if incomplete_coverage:
        bad.append(f"AI 覆蓋基準不完整：{incomplete_coverage}")
    page = read("dashboard.html")
    markers = (
        "secReadingRank", "secReadingRankRows", "renderSecReadingRank",
        "核心持股每日閱讀排序", "排序只決定每日閱讀先後",
        "secEditorial", "renderSecEditorial", "人工消化後的每日綜合重點",
        "目前實際持股閱讀順序", "人工稿不會假裝即時自動判讀",
        "sec_daily_editorial.json", "merger_stock_consideration",
        "本區只列出閱讀先後，不建立待辦或人工列管",
        "AI 已讀，已記錄重點", "secAiEditorialStatus", "有新資料，待 AI 重讀",
        "event.detected_at", "quarterly_key", "thesis_fingerprint", "ownership_accession", "enforcement_keys",
        "若覆核後偵測到新增或覆蓋指紋改變",
        "renderSecEditorialChanges", "相較前次判讀有什麼改變", "未變項目不重複列出",
        "SEC_OWNED_TICKERS", "實際持股｜優先看部位風險", "觀察名單", "secHoldingPosition",
        "secCrossCompany", "secCrossCompanyRows", "renderSecCrossCompany",
        "營收 YoY<br>#1＝成長最高", "毛利率<br>#1＝最高", "FCF 率<br>#1＝最高",
        "稀釋股數 YoY<br>#1＝風險最高", "估值警戒<br>#1＝不確定性最高",
        "跨幣別只比較比率、不直接比較金額", "fetch('valuation.json'",
        "secQuarterlyDiagnosis", "secQuarterlyTrendAnalysis", "renderSecQuarterlyDiagnosis",
        "八季財務趨勢自動判讀", "營收連降至少 3 季或 YoY ≤ -10%",
        "八季財務警報", "已提高每日閱讀排序",
        "chartSecQuarterly", "setSecQuarterlyMetric", "renderSecQuarterlyChart",
        "gross_margin", "operating_margin", "free_cash_flow", "diluted_shares",
        "橫軸每一格是一個財報季度", "缺值會留白，不以 0 補值",
    )
    missing = [marker for marker in markers if marker not in page]
    return not bad and not missing, f"資料問題：{bad or '無'}；缺畫面：{missing or '無'}"


@check("C-24", "14 家投資論點與失效條件可驗證")
def c24():
    tracking = load("investment_thesis_tracking.json")
    tracked = set(load("financials.json")["companies"])
    companies = tracking.get("companies", {})
    bad = []
    if set(companies) != tracked:
        bad.append("論點追蹤公司覆蓋不是 14 家")
    allowed_metrics = {"revenue_growth", "gross_margin", "operating_margin", "cash_dilution"}
    for ticker, company in companies.items():
        theses = company.get("theses", [])
        if len(theses) != 3:
            bad.append(f"{ticker} 不是 3 項論點")
        if len({row.get("id") for row in theses}) != len(theses):
            bad.append(f"{ticker} 論點 id 重複")
        report = company.get("master_report", "")
        if not report or not (REPO_ROOT / report).exists():
            bad.append(f"{ticker} Master Thesis 不存在")
        for row in theses:
            if row.get("metric") not in allowed_metrics:
                bad.append(f"{ticker}/{row.get('id')} 指標無效")
            if not all(row.get(field) for field in ("id", "title", "rationale", "invalidation")):
                bad.append(f"{ticker}/{row.get('id')} 缺文字定義")
            metric = row.get("metric")
            required = {
                "revenue_growth": ("support_yoy", "invalidate_yoy", "invalidate_decline_quarters"),
                "gross_margin": ("support_floor", "invalidate_floor"),
                "operating_margin": ("support_floor", "invalidate_floor"),
                "cash_dilution": ("support_positive_fcf_quarters", "invalidate_negative_fcf_quarters", "invalidate_share_yoy"),
            }.get(metric, ())
            if any(field not in row for field in required):
                bad.append(f"{ticker}/{row.get('id')} 缺數字門檻")
            if metric in {"gross_margin", "operating_margin"} and not any(
                    field in row for field in ("invalidate_decline_quarters", "invalidate_negative_quarters")):
                bad.append(f"{ticker}/{row.get('id')} 缺利潤率連續性門檻")
    page = read("dashboard.html")
    markers = (
        "investment_thesis_tracking.json", "secThesisTracker", "renderSecThesisTracker",
        "secInvestmentThesisSnapshot", "secInvestmentThesisAnalysis",
        "投資論點與失效條件追蹤卡", "最近四季論點狀態歷史",
        "🟢 論點維持", "🔵 需要驗證", "🟡 部分失效", "🔴 重大失效",
        "0 項失效且至少 2 項支持＝論點維持", "狀態變化或任何失效項目會提高每日閱讀排序",
    )
    missing = [marker for marker in markers if marker not in page]
    return not bad and not missing, f"資料問題：{bad or '無'}；缺畫面／排序串接：{missing or '無'}"


@check("C-25", "投資論點狀態快照、日誌與通知完整")
def c25():
    tracking = load("investment_thesis_tracking.json")
    quarterly = load("quarterly_financials.json")
    status = load("investment_thesis_status.json")
    tracked = set(tracking.get("companies", {}))
    companies = status.get("companies", {})
    bad = []
    pending = []
    if set(companies) != tracked:
        bad.append("狀態快照公司覆蓋不是 14 家")
    from track_investment_thesis_status import snapshot  # noqa: PLC0415
    for ticker in sorted(tracked):
        current = companies.get(ticker, {})
        expected = snapshot(
            quarterly.get("companies", {}).get(ticker, {}),
            tracking["companies"][ticker],
        )
        same_input = expected and current.get("fingerprint") == expected.get("fingerprint")
        if expected and not same_input:
            pending.append(ticker)
            continue
        if not expected or current.get("status") != expected.get("status"):
            bad.append(f"{ticker} 綜合狀態不是最新計算結果")
        current_items = {row.get("id"): row.get("status") for row in current.get("items", [])}
        expected_items = {row.get("id"): row.get("status") for row in (expected or {}).get("items", [])}
        if current_items != expected_items:
            bad.append(f"{ticker} 分項狀態不是最新計算結果")
        if len(current.get("history", [])) != 4:
            bad.append(f"{ticker} 沒有四季狀態歷史")
    batches = status.get("update_batches", [])
    if not batches or not all(field in batches[0] for field in (
            "checked_at", "previous_checked_at", "baseline", "changed_count", "changes")):
        bad.append("缺少可稽核的最新檢查批次")
    page = read("dashboard.html")
    sec_workflow = read(".github/workflows/sec-filing-alerts.yml")
    deploy_workflow = read(".github/workflows/deploy-pages.yml")
    markers = (
        "investment_thesis_status.json", "secInvestmentThesisForTicker",
        "投資論點狀態變更", "狀態變更日誌", "單純數值更新但分類不變不重複通知",
        "GitHub Issue 只在分類真的改變時建立",
    )
    missing = [marker for marker in markers if marker not in page]
    workflow_markers = (
        "track_investment_thesis_status.py", "Compare investment thesis states",
        "steps.thesis.outputs.notify_count", "investment_thesis_status.json",
        "SEC / Thesis Alert",
    )
    missing += [f"SEC workflow:{marker}" for marker in workflow_markers if marker not in sec_workflow]
    if '"SEC filing alerts"' not in deploy_workflow:
        missing.append("Pages workflow:SEC filing alerts")
    return not bad and not missing, (
        f"資料問題：{bad or '無'}；待中午狀態批次：{pending or '無'}；"
        f"缺畫面／自動化：{missing or '無'}"
    )


@check("C-26", "10-Q／8-K 入庫可追溯且章節邊界安全")
def c26():
    from ingest_periodic_filings import (  # noqa: PLC0415
        PARSER_VERSION as periodic_parser_version,
        SCHEMA_VERSION as periodic_schema_version,
    )
    alerts = load("sec_filing_alerts.json")
    status = load("periodic_filing_ingest.json")
    target_forms = {"10-Q", "10-Q/A", "8-K", "8-K/A", "6-K", "6-K/A"}
    expected = {
        row["accession"]: row for row in alerts.get("events", [])
        if row.get("form") in target_forms and row.get("accession") and row.get("url")
    }
    rows = status.get("filings", [])
    actual = {row.get("accession"): row for row in rows}
    bad = []
    if status.get("schema_version") != periodic_schema_version:
        bad.append(
            f"periodic_filing_ingest schema 不是 {periodic_schema_version}"
        )
    if len(actual) != len(rows):
        bad.append("入庫狀態有重複 accession")
    if set(actual) != set(expected):
        bad.append("入庫狀態未完整覆蓋目前雷達的定期申報")

    required_10q = {
        "PartI_Item2_MD_and_A", "PartI_Item4_Controls",
        "PartII_Item1A_Risk_Factors",
    }
    for accession, row in sorted(actual.items()):
        source = expected.get(accession, {})
        if row.get("status") in {"review_required", "download_failed"}:
            if row.get("note") or row.get("sections"):
                bad.append(f"{accession} 覆核失敗卻仍列出筆記")
            if not row.get("errors"):
                bad.append(f"{accession} 覆核失敗但沒有原因")
            expected_note = REPO_ROOT / str(row.get("expected_note") or "")
            stale_sections = list(
                (expected_note.parent / "sections").glob(f"{expected_note.stem}_*.md")
            ) if row.get("expected_note") else []
            if expected_note.is_file() or stale_sections:
                bad.append(f"{accession} 覆核失敗但舊版 Markdown 仍在現役路徑")
            continue
        if row.get("status") not in {"ingested", "already_ingested"}:
            bad.append(f"{accession} 狀態不合法：{row.get('status')}")
            continue
        note_path = REPO_ROOT / str(row.get("note") or "")
        if not note_path.is_file():
            bad.append(f"{accession} 缺主筆記")
            continue
        note = note_path.read_text()
        for marker in (
            accession, source.get("url", ""),
            f"ingest_parser_version: {periodic_parser_version}",
        ):
            if marker and marker not in note:
                bad.append(f"{accession} 主筆記缺可追溯欄位：{marker}")

        section_paths = [REPO_ROOT / path for path in row.get("sections", [])]
        for path in section_paths:
            if not path.is_file() or accession not in path.read_text():
                bad.append(f"{accession} 章節不存在或缺 accession：{path.name}")
        form = row.get("form", "")
        slugs = {path.stem.split(note_path.stem + "_", 1)[-1] for path in section_paths}
        if form.startswith("10-Q"):
            if slugs != required_10q:
                bad.append(f"{accession} 10-Q 必要章節不是 3 篇")
            controls = next((path for path in section_paths if path.stem.endswith("PartI_Item4_Controls")), None)
            if controls and re.search(r"^PART\s+II\b", controls.read_text(), re.M | re.I):
                bad.append(f"{accession} Controls 跨入 Part II")
        elif form.startswith("8-K"):
            expected_items = {
                str(item).strip() for item in source.get("items", [])
                if re.fullmatch(r"\d+\.\d{2}", str(item).strip())
            }
            if len(section_paths) != len(expected_items):
                bad.append(f"{accession} 8-K Item 數與 SEC submissions 不一致")
        elif form.startswith("6-K") and section_paths:
            bad.append(f"{accession} 6-K 不應猜測 Item 章節")

    workflow = read(".github/workflows/sec-filing-alerts.yml")
    workflow_markers = (
        "ingest_periodic_filings.py", "periodic_filing_ingest.json",
        "20_Filings/", "steps.ingest.outputs.pending_count",
        "Require manual review for unsafe filing boundaries",
    )
    missing = [marker for marker in workflow_markers if marker not in workflow]
    if "Periodic_Filing_Ingest" not in read("00_Home.md"):
        missing.append("00_Home:Periodic_Filing_Ingest")
    return not bad and not missing, f"資料問題：{bad or '無'}；缺自動化／入口：{missing or '無'}"


@check("C-27", "8-K Exhibit 99.1 分析卡可追溯且不補猜測值")
def c27():
    from analyze_exhibit_991 import (  # noqa: PLC0415
        CATEGORIES, MAX_EVIDENCE, PARSER_VERSION, SCHEMA_VERSION, eligible_events,
    )
    status = load("exhibit_991_analysis.json")
    expected = {row["accession"]: row for row in eligible_events(REPO_ROOT / "sec_filing_alerts.json")}
    rows = status.get("filings", [])
    actual = {row.get("accession"): row for row in rows}
    bad = []
    if status.get("schema_version") != SCHEMA_VERSION:
        bad.append(f"schema 不是 {SCHEMA_VERSION}")
    if status.get("parser_version") != PARSER_VERSION:
        bad.append(f"parser 不是 {PARSER_VERSION}")
    if len(actual) != len(rows):
        bad.append("狀態有重複 accession")
    if set(actual) != set(expected):
        bad.append("沒有完整覆蓋 Item 2.02 的 8-K／8-K-A")

    analyzed = 0
    pending = 0
    for accession, row in sorted(actual.items()):
        expected_card = REPO_ROOT / str(row.get("expected_card") or "")
        if row.get("status") != "analyzed":
            pending += 1
            if not row.get("errors"):
                bad.append(f"{accession} 待覆核但沒有原因")
            if expected_card.is_file():
                bad.append(f"{accession} 待覆核但仍留有舊分析卡")
            continue
        analyzed += 1
        exhibit_url = str(row.get("exhibit_url") or "")
        compact = accession.replace("-", "")
        if (not exhibit_url.startswith("https://www.sec.gov/Archives/edgar/data/")
                or f"/{compact}/" not in exhibit_url):
            bad.append(f"{accession} Exhibit 不是同 accession 的 SEC HTTPS 來源")
        if not re.fullmatch(r"[0-9a-f]{64}", str(row.get("source_sha256") or "")):
            bad.append(f"{accession} 缺附件 SHA-256")
        categories = row.get("categories") or {}
        if set(categories) != set(CATEGORIES):
            bad.append(f"{accession} 七類證據欄位不完整")
            continue
        found = sum(bool(items) for items in categories.values())
        if row.get("coverage") != {"found": found, "total": len(CATEGORIES)}:
            bad.append(f"{accession} 證據覆蓋數無法對帳")
        card_path = REPO_ROOT / str(row.get("card") or "")
        if not card_path.is_file():
            bad.append(f"{accession} 缺分析卡")
            continue
        card = card_path.read_text()
        for marker in (accession, exhibit_url, f"parser_version: {PARSER_VERSION}", "保留缺值"):
            if marker not in card:
                bad.append(f"{accession} 分析卡缺追溯標記：{marker}")
        for key, items in categories.items():
            if len(items) > MAX_EVIDENCE:
                bad.append(f"{accession}/{key} 證據超過 {MAX_EVIDENCE} 則")
            for item in items:
                excerpt = item.get("excerpt") or ""
                if not excerpt or excerpt not in card:
                    bad.append(f"{accession}/{key} 證據未原文寫入分析卡")

    workflow = read(".github/workflows/sec-filing-alerts.yml")
    workflow_markers = (
        "analyze_exhibit_991.py", "exhibit_991_analysis.json",
        "Exhibit_991_Earnings_Radar.md", "exhibit_991_pending_count",
        "Require manual review for unsafe filing boundaries",
    )
    missing = [marker for marker in workflow_markers if marker not in workflow]
    if "Exhibit_991_Earnings_Radar" not in read("00_Home.md"):
        missing.append("00_Home:Exhibit_991_Earnings_Radar")
    page = read("dashboard.html")
    ui_markers = (
        "secExhibit991", "renderSecExhibit991", "exhibit_991_analysis.json",
        "⑧ Exhibit 99.1", "本附件未可靠辨識此項；保留缺值",
        "本卡是官方附件的原文閱讀索引，不是投資評分",
    )
    missing += [f"dashboard:{marker}" for marker in ui_markers if marker not in page]
    ok = not bad and not missing
    return ok, (f"已分析 {analyzed}；待覆核 {pending}；"
                f"資料問題：{bad or '無'}；缺自動化／入口：{missing or '無'}")


@check("C-28", "官方 Earnings Call 雷達區分逐字稿、講稿與影音")
def c28():
    from track_earnings_calls import (  # noqa: PLC0415
        ANALYZABLE_STATUSES, CATEGORIES, HISTORY_QUARTERS, MAX_EVIDENCE,
        MAX_EXCERPT_WORDS, PARSER_VERSION, SCHEMA_VERSION, TREND_STATES,
        allowed_url, period_key,
    )
    config = load("earnings_call_sources.json")
    status = load("earnings_call_analysis.json")
    expected = set(load("financials.json").get("companies", {}))
    configured = set(config.get("companies", {}))
    companies = status.get("companies", {})
    bad = []
    if configured != expected or set(companies) != expected:
        bad.append("來源登錄或輸出未完整覆蓋 14 家公司")
    if status.get("schema_version") != SCHEMA_VERSION or status.get("parser_version") != PARSER_VERSION:
        bad.append("schema／parser 版本不一致")
    if status.get("history_quarters") != HISTORY_QUARTERS or status.get("trend_states") != TREND_STATES:
        bad.append("四季比較方法或狀態定義與程式不一致")
    for ticker, row in companies.items():
        company_config = config.get("companies", {}).get(ticker, {})
        expected_card = REPO_ROOT / str(row.get("expected_card") or "")
        if row.get("allowed_hosts") != company_config.get("allowed_hosts"):
            bad.append(f"{ticker} 儀表板官方主機白名單與來源登錄不一致")
        discovery = row.get("discovery", {})
        if discovery.get("status") not in {"checked", "unverified"}:
            bad.append(f"{ticker} 缺最新官方材料探索狀態")
        current_period_key = period_key(company_config.get("period", ""))
        for candidate in discovery.get("newer_candidates", []):
            if (
                not allowed_url(candidate.get("url", ""), company_config.get("allowed_hosts", []))
                or not period_key(candidate.get("period_key", ""))
                or not current_period_key
                or period_key(candidate["period_key"]) <= current_period_key
            ):
                bad.append(f"{ticker} 較新材料候選未通過期間或主機驗證")
        if company_config.get("source_type") != "webcast_replay" and not company_config.get("identity_patterns"):
            bad.append(f"{ticker} 文字來源缺公司／期間身分驗證規則")
        if row.get("status") in ANALYZABLE_STATUSES:
            configured_history = company_config.get("history", [])
            history = row.get("history", [])
            history_coverage = row.get("history_coverage", {})
            if len(configured_history) != HISTORY_QUARTERS - 1:
                bad.append(f"{ticker} 未登錄最近 {HISTORY_QUARTERS} 季官方文字來源")
            if len(history) != HISTORY_QUARTERS:
                bad.append(f"{ticker} 四季歷史輸出不是 {HISTORY_QUARTERS} 季")
            available = sum(item.get("status") in ANALYZABLE_STATUSES for item in history)
            if history_coverage != {
                "available": available, "expected": HISTORY_QUARTERS,
                "status": "complete" if available == HISTORY_QUARTERS and len(history) == HISTORY_QUARTERS else "partial",
                "meaning": "只比較公司官方文字；缺季保留缺值，不以第三方逐字稿或影音轉錄補齊。",
            }:
                bad.append(f"{ticker} 四季文字覆蓋狀態無法對帳")
            if history_coverage.get("status") != "complete":
                bad.append(f"{ticker} 最近四季官方文字尚未完整")
            for quarter in history:
                if quarter.get("status") not in ANALYZABLE_STATUSES:
                    continue
                if not allowed_url(quarter.get("material_url", ""), quarter.get("allowed_hosts", [])):
                    bad.append(f"{ticker}/{quarter.get('period')} 歷史材料未通過 HTTPS 主機白名單")
                quarter_categories = quarter.get("categories") or {}
                if set(quarter_categories) != set(CATEGORIES):
                    bad.append(f"{ticker}/{quarter.get('period')} 七類歷史證據不完整")
                    continue
                quarter_found = sum(bool(items) for items in quarter_categories.values())
                if quarter.get("coverage") != {"found": quarter_found, "total": len(CATEGORIES)}:
                    bad.append(f"{ticker}/{quarter.get('period')} 歷史覆蓋數無法對帳")
                if not re.fullmatch(r"[0-9a-f]{64}", str(quarter.get("source_sha256") or "")):
                    bad.append(f"{ticker}/{quarter.get('period')} 缺官方材料 SHA-256")
                quarter_card = REPO_ROOT / str(quarter.get("card") or "")
                if not quarter_card.is_file():
                    bad.append(f"{ticker}/{quarter.get('period')} 缺歷史閱讀卡")
                    continue
                quarter_card_text = quarter_card.read_text()
                for items in quarter_categories.values():
                    for item in items:
                        excerpt = item.get("excerpt") or ""
                        if len(excerpt.rstrip("…").split()) > MAX_EXCERPT_WORDS or excerpt not in quarter_card_text:
                            bad.append(f"{ticker}/{quarter.get('period')} 歷史摘錄限制或追溯失敗")
            comparisons = row.get("quarter_comparisons", [])
            if len(comparisons) != max(0, len(history) - 1):
                bad.append(f"{ticker} 季度比較數量錯誤")
            for index, comparison in enumerate(comparisons):
                if (comparison.get("current_period") != history[index].get("period")
                        or comparison.get("previous_period") != history[index + 1].get("period")):
                    bad.append(f"{ticker} 季度比較期間順序錯誤")
                topics = comparison.get("topics", {})
                if set(topics) != set(CATEGORIES) or any(
                    topic.get("state") not in TREND_STATES for topic in topics.values()
                ):
                    bad.append(f"{ticker} 季度比較主題或狀態不完整")
            if row.get("provenance", {}).get("status") not in {
                "official_host", "official_page_link", "manual_official_page_attestation",
            }:
                bad.append(f"{ticker} 可分析文字缺官方來源鏈驗證")
            if row.get("status") == "analyzed_cached" and not row.get("errors"):
                bad.append(f"{ticker} 使用快取卡但沒有下載失敗原因")
            if not re.fullmatch(r"[0-9a-f]{64}", str(row.get("source_sha256") or "")):
                bad.append(f"{ticker} 缺官方材料 SHA-256")
            categories = row.get("categories") or {}
            if set(categories) != set(CATEGORIES):
                bad.append(f"{ticker} 七類證據欄位不完整")
                continue
            found = sum(bool(items) for items in categories.values())
            if row.get("coverage") != {"found": found, "total": len(CATEGORIES)}:
                bad.append(f"{ticker} 證據覆蓋數無法對帳")
            if not expected_card.is_file():
                bad.append(f"{ticker} 缺閱讀卡")
                continue
            card = expected_card.read_text()
            for items in categories.values():
                if len(items) > MAX_EVIDENCE:
                    bad.append(f"{ticker} 單類證據超量")
                for item in items:
                    excerpt = item.get("excerpt") or ""
                    if len(excerpt.rstrip("…").split()) > MAX_EXCERPT_WORDS or excerpt not in card:
                        bad.append(f"{ticker} 短摘錄限制或卡片追溯失敗")
        elif row.get("status") == "replay_only":
            if row.get("history") or row.get("quarter_comparisons"):
                bad.append(f"{ticker} 僅影音來源不應產生四季文字比較")
            if row.get("history_coverage", {}).get("status") != "not_applicable":
                bad.append(f"{ticker} 僅影音來源未標示四季比較不適用")
            if row.get("provenance", {}).get("status") not in {
                "official_host", "official_page_link", "manual_official_page_attestation",
            }:
                bad.append(f"{ticker} 影音來源缺官方來源鏈驗證")
            if row.get("link_check", {}).get("status") not in {"reachable", "unverified"}:
                bad.append(f"{ticker} 影音連結沒有探測狀態")
            if expected_card.is_file():
                bad.append(f"{ticker} 僅影音卻保留文字卡")
        else:
            if not row.get("errors"):
                bad.append(f"{ticker} 待覆核但沒有原因")
            if expected_card.is_file():
                bad.append(f"{ticker} 待覆核卻保留舊卡")

    workflow = read(".github/workflows/sec-filing-alerts.yml")
    required = (
        "track_earnings_calls.py", "earnings_call_analysis.json", "earnings_call_sources.json",
        "Earnings_Call_Radar.md", "earnings_call_changed_count",
        "earnings_call_changed_attention_count", "pypdf>=6,<7", "curl_cffi>=0.13,<0.14",
    )
    missing = [f"workflow:{marker}" for marker in required if marker not in workflow]
    for workflow_path in (".github/workflows/update-prices.yml", ".github/workflows/sec-13f-radar.yml"):
        if "pypdf>=6,<7" not in read(workflow_path):
            missing.append(f"{workflow_path}:pypdf>=6,<7")
    if "Earnings_Call_Radar" not in read("00_Home.md"):
        missing.append("00_Home:Earnings_Call_Radar")
    page = read("dashboard.html")
    ui_markers = (
        "secEarningsCall", "renderSecEarningsCall", "earnings_call_analysis.json",
        "⑨ Earnings Call", "僅官方影音／回放", "第三方逐字稿",
        "最近四季法說趨勢比較", "本季新增命中", "連續兩季命中",
        "本季未再命中", "資料不足", "不等於風險消失",
    )
    missing += [f"dashboard:{marker}" for marker in ui_markers if marker not in page]
    return not bad and not missing, f"資料問題：{bad or '無'}；缺自動化／入口：{missing or '無'}"


@check("C-29", "每日變更候選稿可重現、可追溯且不冒充 AI 判讀")
def c29():
    data = load("sec_daily_change_candidates.json")
    editorial = load("sec_daily_editorial.json")
    bad = []
    if data.get("schema_version") != 1:
        bad.append("schema_version 不是 1")
    if data.get("editorial_reviewed_at") != editorial.get("reviewed_at"):
        bad.append("AI 覆核基準與正式人工稿不一致")
    candidates = data.get("candidates", [])
    if data.get("candidate_count") != len(candidates):
        bad.append("candidate_count 與明細數不一致")
    if data.get("company_count") != len({row.get("ticker") for row in candidates}):
        bad.append("company_count 與明細公司數不一致")
    if len({row.get("id") for row in candidates}) != len(candidates):
        bad.append("候選 ID 重複")
    expected_counts = {
        kind: sum(row.get("type") == kind for row in candidates)
        for kind in ("risk", "improvement", "conclusion")
    }
    if data.get("counts") != expected_counts:
        bad.append("候選分類計數不一致")
    for row in candidates:
        ticker = row.get("ticker") or "未知"
        if row.get("type") not in expected_counts:
            bad.append(f"{ticker} 候選類型不在允許清單")
        if row.get("status") != "pending_ai_review":
            bad.append(f"{ticker} 候選未標示待 AI 覆核")
        if row.get("confidence") not in {"low", "medium", "high"}:
            bad.append(f"{ticker} 證據強度無效")
        if not row.get("source_keys") or not row.get("sources"):
            bad.append(f"{ticker} 缺來源鍵或官方來源")
        if not row.get("headline") or not row.get("why_candidate"):
            bad.append(f"{ticker} 缺候選摘要或列入原因")

    with tempfile.TemporaryDirectory() as temp_dir:
        temp = pathlib.Path(temp_dir)
        result = subprocess.run([
            sys.executable, str(REPO_ROOT / "scripts/generate_sec_daily_change_candidates.py"),
            "--output", str(temp / "candidates.json"),
            "--markdown", str(temp / "candidates.md"),
            "--github-output", str(temp / "github-output"),
        ], cwd=REPO_ROOT, text=True, capture_output=True, check=False)
        if result.returncode:
            bad.append(f"候選稿重建失敗：{result.stderr.strip() or result.stdout.strip()}")
        else:
            rebuilt = json.loads((temp / "candidates.json").read_text())
            if rebuilt != data:
                bad.append("現存候選稿無法由目前來源確定性重建")
            markdown = (temp / "candidates.md").read_text()
            if "待 AI 覆核候選" not in markdown or "不是最終判讀" not in markdown:
                bad.append("Obsidian 候選稿缺非最終判讀警語")

    sec_workflow = read(".github/workflows/sec-filing-alerts.yml")
    price_workflow = read(".github/workflows/update-prices.yml")
    dashboard = read("dashboard.html")
    home = read("00_Home.md")
    markers = {
        "SEC workflow": (sec_workflow, (
            "generate_sec_daily_change_candidates.py", "steps.candidates.outputs.notify_count",
            "candidate_batch_id", "sec_daily_change_candidates.json", "SEC_Daily_Change_Candidates.md",
        )),
        "價格 workflow": (price_workflow, (
            "generate_sec_daily_change_candidates.py", "sec_daily_change_candidates",
            "SEC_Daily_Change_Candidates",
        )),
        "dashboard": (dashboard, (
            "secChangeCandidates", "renderSecChangeCandidates", "sec_daily_change_candidates.json",
            "待 AI 閱讀官方原文的候選稿", "Form 144 只代表擬售意向",
        )),
        "00_Home": (home, ("SEC_Daily_Change_Candidates", "SEC_Daily_Editorial")),
    }
    missing = [f"{label}:{marker}" for label, (text, required) in markers.items()
               for marker in required if marker not in text]
    return not bad and not missing, f"資料問題：{bad or '無'}；缺自動化／畫面：{missing or '無'}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true", help="只印出失敗項")
    args = parser.parse_args()

    failures = []
    for code, title, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as exc:                # noqa: BLE001 - a check that
            ok, detail = False, (               # cannot run has not passed
                f"檢查本身發生錯誤：{type(exc).__name__}: {exc}")
        if not ok:
            failures.append(code)
        if not args.quiet or not ok:
            print(f"  {'✅' if ok else '❌'} {code:6s} {title:32s} {detail}")

    print()
    if failures:
        print(f"❌ {len(failures)} / {len(CHECKS)} 項檢查未通過：{', '.join(failures)}")
        return 1
    print(f"✅ {len(CHECKS)} 項檢查全部通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
