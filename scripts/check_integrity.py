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
from datetime import date

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


@check("C-5", "Sortino 有實際計算窗口")
def c5():
    bad = []
    for path in sorted((REPO_ROOT / "30_Analysis").glob("*_Master_Investment_Thesis_2026.md")):
        for line in path.read_text().splitlines():
            if "Sortino Ratio（週資料）" in line and "週報酬" not in line and "資料不足" not in line:
                bad.append(path.name)
                break
    return not bad, f"裸數值（無窗口說明）：{bad or '無'}"


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
