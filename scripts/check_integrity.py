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
