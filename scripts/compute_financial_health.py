"""Compute a financial-health scorecard and write financial_health.json.

compute_fundamentals.py covers four models -- Piotroski, Altman Z, DuPont and
gross margin -- which between them measure trend, bankruptcy risk and return
decomposition. None of them measures whether the balance sheet is sound, so
this adds the three dimensions that were missing entirely (liquidity, solvency,
cash-flow quality) plus the two fixes the existing metrics needed:

  Altman Z''  The original Z was calibrated on leveraged manufacturers in 1968.
              Its X4 is market cap / total liabilities, which for an asset-light
              company with a large multiple runs away and drags Z into triple
              digits; across this portfolio 11 of 14 companies were flagged
              market-cap-dominated and 3 could not be computed, so the metric
              carried no information at all. Z'' drops X5 and uses *book* equity
              in X4, which is what makes it applicable to non-manufacturers.

  ROIC-WACC   Every company already has a WACC in dcf_assumptions.json, used
              only for discounting. Comparing it against ROIC is the test of
              whether the business earns more than the capital it consumes --
              the single most discriminating figure in this portfolio.

Two rules carried over from the rest of the pipeline: a missing input is
reported as null with a reason, never defaulted; and no composite score is
invented. The verdict is a list of named flags against stated thresholds, so a
reader can disagree with a threshold without the whole number becoming opaque.

    python3 scripts/fetch_xbrl_financials.py     # raw SEC data
    python3 scripts/compute_fundamentals.py      # the original four models
    python3 scripts/compute_financial_health.py  # this script
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FINANCIALS_PATH = REPO_ROOT / "financials.json"
FUNDAMENTALS_PATH = REPO_ROOT / "fundamentals.json"
ASSUMPTIONS_PATH = REPO_ROOT / "dcf_assumptions.json"
OUTPUT_PATH = REPO_ROOT / "financial_health.json"

# Thresholds are conventional screening levels, not house rules, and are echoed
# into the output so the JSON is self-describing.
THRESHOLDS = {
    "current_ratio_min": 1.0,
    "liabilities_to_assets_max": 0.60,
    "interest_coverage_min": 3.0,
    "accrual_ratio_max": 0.10,
    "altman_z2_safe": 2.6,
    "altman_z2_distress": 1.1,
}


def val(period, concept):
    entry = (period or {}).get(concept)
    return entry["value"] if entry else None


def tag(period, concept):
    entry = (period or {}).get(concept)
    return entry["tag"] if entry else None


def div(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


def rnd(x, places=4):
    return None if x is None else round(x, places)


def total_liabilities(cur):
    """Reported Liabilities, or Assets - Equity when the filer omits the tag.

    Amazon and Intel do not tag `Liabilities` at all, which is why Altman Z was
    unavailable for them. The identity is exact, but `equity` resolves to
    StockholdersEquity where available, so any non-controlling interest lands on
    the liabilities side of the fallback. Report which basis was used.
    """
    reported = val(cur, "liabilities")
    if reported is not None:
        return reported, "tag", None
    assets, equity = val(cur, "assets"), val(cur, "equity")
    if assets is None or equity is None:
        return None, None, "缺 Liabilities 標籤，且無法由 Assets − Equity 推導"
    return (assets - equity, "assets_minus_equity",
            "filer 未標記 Liabilities，改以 Assets − Equity 推導；"
            "若存在非控制權益會被計入負債側，數值略為高估")


def total_debt(cur):
    """Interest-bearing debt, or None when the filer tags neither component.

    Returning 0 here would be the more convenient answer and the wrong one:
    ARM, Nokia, Ondas and TSMC tag neither LongTermDebt nor DebtCurrent under
    the concept lists in fetch_xbrl_financials.py, and a debt-to-equity of 0.00
    for a company with convertible notes outstanding reads as a clean balance
    sheet rather than as absent data.
    """
    ltd, sd = val(cur, "long_term_debt"), val(cur, "debt_current")
    if ltd is None and sd is None:
        return None, "未取得 LongTermDebt / DebtCurrent 標籤，無法計算有息負債"
    parts = []
    if ltd is None:
        parts.append("長期負債")
    if sd is None:
        parts.append("一年內到期負債")
    note = None if not parts else "缺 {} 標籤，有息負債僅為部分加總".format("、".join(parts))
    return (ltd or 0) + (sd or 0), note


def liquidity(cur):
    ca, cl = val(cur, "current_assets"), val(cur, "current_liabilities")
    cash, sti = val(cur, "cash"), val(cur, "short_term_investments")
    assets = val(cur, "assets")
    wc = None if ca is None or cl is None else ca - cl
    liquid = None if cash is None else cash + (sti or 0)
    return {
        "current_ratio": rnd(div(ca, cl), 2),
        "cash_ratio": rnd(div(liquid, cl), 2),
        "working_capital": wc,
        "working_capital_to_assets": rnd(div(wc, assets)),
        # Quick ratio needs inventory, which fetch_xbrl_financials.py does not
        # collect; cash ratio is the stricter measure reported in its place.
        "quick_ratio": None,
        "quick_ratio_reason": "未擷取存貨科目 (InventoryNet)，速動比率無法計算",
    }


def solvency(cur):
    debt, debt_note = total_debt(cur)
    liab, liab_basis, liab_note = total_liabilities(cur)
    assets, equity = val(cur, "assets"), val(cur, "equity")
    cash, sti = val(cur, "cash"), val(cur, "short_term_investments")
    ebit = val(cur, "operating_income")
    interest = val(cur, "interest_expense")

    net_debt = None
    if debt is not None and cash is not None:
        net_debt = debt - cash - (sti or 0)

    coverage = None
    coverage_note = None
    if ebit is not None and interest not in (None, 0):
        coverage = ebit / abs(interest)
        if ebit < 0:
            coverage_note = "營業利益為負，倍數僅表示虧損相對利息的規模，不代表償付能力"
    elif interest is None:
        coverage_note = "未取得利息費用標籤，無法計算利息保障倍數"

    return {
        "total_debt": debt,
        "total_debt_note": debt_note,
        "total_liabilities": liab,
        "liabilities_basis": liab_basis,
        "liabilities_note": liab_note,
        "net_debt": net_debt,
        "debt_to_equity": rnd(div(debt, equity), 3),
        "liabilities_to_assets": rnd(div(liab, assets), 4),
        "equity_to_assets": rnd(div(equity, assets), 4),
        "interest_coverage": rnd(coverage, 1),
        "interest_coverage_note": coverage_note,
        "interest_expense_tag": tag(cur, "interest_expense"),
        # EBITDA needs depreciation and amortisation, which are not collected;
        # EBIT is the available denominator and is the more conservative one.
        "net_debt_to_ebit": rnd(div(net_debt, ebit) if (ebit or 0) > 0 else None, 2),
        "net_debt_to_ebit_note": "以 EBIT 為分母（未擷取折舊攤銷，無法計算 EBITDA）",
    }


def profitability(cur, wacc):
    rev, assets, equity = val(cur, "revenue"), val(cur, "assets"), val(cur, "equity")
    ni, ebit = val(cur, "net_income"), val(cur, "operating_income")
    gp = val(cur, "gross_profit")
    tax, pretax = val(cur, "income_tax_expense"), val(cur, "pretax_income")
    cash, sti = val(cur, "cash"), val(cur, "short_term_investments")
    cl = val(cur, "current_liabilities")
    debt, _ = total_debt(cur)

    etr = div(tax, pretax)
    etr_note = None
    if etr is not None:
        clamped = min(max(etr, 0.0), 0.50)
        # A pre-tax loss flips the ratio's sign and a tax benefit can push it
        # past 100%, either of which would turn NOPAT into nonsense. Only say so
        # when the clamp actually moved the rate materially; Ondas at -0.4% is
        # arithmetic noise, not a tax anomaly worth a paragraph.
        if abs(clamped - etr) > 0.01:
            etr_note = ("有效稅率 {:.1%} 落在合理區間外（通常來自稅務優惠、遞延稅資產認列"
                        "或稅前虧損），已夾在 0%~50% 以計算 NOPAT".format(etr))
        etr = clamped

    nopat = None if ebit is None or etr is None else ebit * (1 - etr)

    # Invested capital, operating side: what the business actually employs.
    #
    #   IC = 總資產 − 流動負債 + 一年內到期有息負債 − 現金與短期投資
    #
    # The financing-side alternative (debt + equity - cash) is reported beside
    # it but is not used, for two reasons. It needs the debt tags, which are
    # absent for ARM, Nokia, Ondas and TSMC, so a quarter of the portfolio would
    # have no ROIC at all. And its denominator contains book equity, which years
    # of buybacks shrink -- Apple's ROIC reads 102% on that basis against 81% on
    # this one, a gap that measures the capital structure rather than the
    # business. The two definitions differ by up to 45% across this portfolio,
    # so they are kept apart rather than used interchangeably.
    ca_less_cash = None
    if assets is not None and cl is not None:
        ca_less_cash = assets - cl + (val(cur, "debt_current") or 0) - (cash or 0) - (sti or 0)

    invested_fin = None
    if debt is not None and equity is not None and cash is not None:
        invested_fin = debt + equity - cash - (sti or 0)

    invested = ca_less_cash
    invested_note = None
    if invested is None:
        invested_note = "缺總資產或流動負債科目，投入資本無法計算"
    elif val(cur, "debt_current") is None:
        # Phrased without a direction: a smaller denominator inflates a positive
        # ROIC but makes a negative one look worse, and Ondas is negative.
        invested_note = ("缺一年內到期負債標籤，短期有息負債未加回投入資本，"
                         "分母略為低估、ROIC 絕對值略為放大")

    roic = div(nopat, invested) if (invested or 0) > 0 else None
    roic_note = invested_note
    if roic is not None and rev and invested / rev < 0.20:
        roic_note = ("投入資本僅為營收的 {:.0%}，分母極小使 ROIC 對單一年度的"
                     "營業利益波動高度敏感".format(invested / rev))

    spread = None if roic is None or wacc is None else roic - wacc
    if spread is None:
        verdict = None
    elif spread > 0.02:
        verdict = "創造價值"
    elif spread >= 0:
        verdict = "約略打平"
    else:
        verdict = "毀滅價值"

    return {
        "gross_margin": rnd(div(gp, rev)),
        "operating_margin": rnd(div(ebit, rev)),
        "net_margin": rnd(div(ni, rev)),
        "roa": rnd(div(ni, assets)),
        "roe": rnd(div(ni, equity)),
        "effective_tax_rate": rnd(etr),
        "effective_tax_rate_note": etr_note,
        "nopat": None if nopat is None else round(nopat),
        "invested_capital": None if invested is None else round(invested),
        "invested_capital_basis": "營運側：總資產 − 流動負債 + 一年內到期負債 − 現金與短期投資",
        "invested_capital_financing_side": None if invested_fin is None else round(invested_fin),
        "roic": rnd(roic),
        "roic_note": roic_note,
        "wacc": wacc,
        "wacc_source": "dcf_assumptions.json",
        "roic_minus_wacc": rnd(spread),
        "value_creation": verdict,
    }


def cash_flow_quality(cur, prev):
    ni, ocf = val(cur, "net_income"), val(cur, "operating_cash_flow")
    capex, rev = val(cur, "capex"), val(cur, "revenue")
    assets, assets_prev = val(cur, "assets"), val(prev, "assets")

    fcf = None if ocf is None or capex is None else ocf - capex
    avg_assets = None
    if assets is not None and assets_prev is not None:
        avg_assets = (assets + assets_prev) / 2
    elif assets is not None:
        avg_assets = assets

    # Sloan (1996): the portion of earnings not backed by operating cash. A
    # large positive figure means profit is being recognised ahead of collection.
    accrual = div(None if ni is None or ocf is None else ni - ocf, avg_assets)

    return {
        "free_cash_flow": fcf,
        "fcf_margin": rnd(div(fcf, rev)),
        "ocf_to_net_income": rnd(div(ocf, ni) if (ni or 0) > 0 else None, 3),
        "ocf_to_net_income_note": None if (ni or 0) > 0 else "淨利為負或缺漏，比率無意義",
        "accrual_ratio": rnd(accrual),
        "accrual_ratio_basis": "(淨利 − 營運現金流) ÷ 平均總資產，Sloan (1996)",
        "capex_to_ocf": rnd(div(capex, ocf) if (ocf or 0) > 0 else None, 3),
        "capex_intensity": rnd(div(capex, rev)),
    }


def altman_z2(cur):
    """Altman Z'' -- the four-variable form for non-manufacturers.

    Z'' = 6.56*X1 + 3.26*X2 + 6.72*X3 + 1.05*X4

    X5 (asset turnover) is dropped because it is industry-specific, and X4 uses
    book equity rather than market capitalisation. Both changes exist precisely
    to make the score reflect solvency instead of the valuation multiple.
    Zones: > 2.6 safe, 1.1-2.6 grey, < 1.1 distress.
    """
    assets = val(cur, "assets")
    ca, cl = val(cur, "current_assets"), val(cur, "current_liabilities")
    liab, liab_basis, liab_note = total_liabilities(cur)
    wc = None if ca is None or cl is None else ca - cl

    x1 = div(wc, assets)
    x2 = div(val(cur, "retained_earnings"), assets)
    x3 = div(val(cur, "operating_income"), assets)
    x4 = div(val(cur, "equity"), liab)

    missing = [n for n, v in zip(("X1", "X2", "X3", "X4"), (x1, x2, x3, x4)) if v is None]
    if missing:
        return {"z2_score": None, "missing": missing,
                "formula": "6.56*X1 + 3.26*X2 + 6.72*X3 + 1.05*X4"}

    z = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4
    zone = ("safe" if z > THRESHOLDS["altman_z2_safe"]
            else "distress" if z < THRESHOLDS["altman_z2_distress"] else "grey")
    return {
        "z2_score": round(z, 2),
        "zone": zone,
        "formula": "6.56*X1 + 3.26*X2 + 6.72*X3 + 1.05*X4",
        "thresholds": {"safe": THRESHOLDS["altman_z2_safe"],
                       "distress": THRESHOLDS["altman_z2_distress"]},
        "components": {"X1_working_capital_to_assets": rnd(x1),
                       "X2_retained_earnings_to_assets": rnd(x2),
                       "X3_ebit_to_assets": rnd(x3),
                       "X4_book_equity_to_liabilities": rnd(x4)},
        "liabilities_basis": liab_basis,
        "liabilities_note": liab_note,
    }


def piotroski_normalised(fund):
    """Rescale F-Score to a constant denominator so companies are comparable.

    TSMC scores 7/7 and NVIDIA 4/9 in fundamentals.json. Read as printed, TSMC
    looks like a clean sweep against a weak result; the denominators differ
    because criteria whose inputs are missing are excluded rather than failed.
    """
    p = (fund or {}).get("piotroski") or {}
    score, evaluated = p.get("score"), p.get("max_evaluated")
    if score is None or not evaluated:
        return {"score": score, "max_evaluated": evaluated, "normalised_9": None}
    return {
        "score": score,
        "max_evaluated": evaluated,
        "unavailable": p.get("unavailable", []),
        "normalised_9": round(score / evaluated * 9, 1),
        "comparable": evaluated == 9,
        "note": None if evaluated == 9 else
                "{} 項因資料不足未納入評分，原始分數與 9 項全評的公司不可直接比較"
                .format(9 - evaluated),
    }


def raise_flags(liq, sol, prof, cfq, z2):
    """Named threshold breaches. No weighting, no composite number."""
    flags = []
    t = THRESHOLDS

    cr = liq["current_ratio"]
    if cr is not None and cr < t["current_ratio_min"]:
        flags.append({"dimension": "流動性", "severity": "warn",
                      "detail": "流動比率 {:.2f} 低於 {:.1f}，流動負債大於流動資產"
                                .format(cr, t["current_ratio_min"])})

    la = sol["liabilities_to_assets"]
    if la is not None and la > t["liabilities_to_assets_max"]:
        flags.append({"dimension": "償債能力", "severity": "warn",
                      "detail": "負債佔資產 {:.0%}，高於 {:.0%}"
                                .format(la, t["liabilities_to_assets_max"])})

    ic = sol["interest_coverage"]
    if ic is not None and ic < t["interest_coverage_min"]:
        flags.append({"dimension": "償債能力", "severity": "warn",
                      "detail": "利息保障倍數 {:.1f}x 低於 {:.0f}x".format(
                          ic, t["interest_coverage_min"])
                                + ("（營業利益為負）" if ic < 0 else "")})

    sp = prof["roic_minus_wacc"]
    if sp is not None and sp < 0:
        flags.append({"dimension": "資本效率", "severity": "warn",
                      "detail": "ROIC {:.1%} 低於 WACC {:.2%}，價差 {:+.1f}pp，"
                                "投入資本未賺回其成本"
                                .format(prof["roic"], prof["wacc"], sp * 100)})

    fm = cfq["fcf_margin"]
    if fm is not None and fm < 0:
        flags.append({"dimension": "現金流品質", "severity": "warn",
                      "detail": "自由現金流為負，FCF 利潤率 {:.1%}".format(fm)})

    ar = cfq["accrual_ratio"]
    if ar is not None and ar > t["accrual_ratio_max"]:
        flags.append({"dimension": "現金流品質", "severity": "warn",
                      "detail": "應計比率 {:+.1%} 高於 {:.0%}，淨利明顯超前營運現金流"
                                .format(ar, t["accrual_ratio_max"])})

    z = z2.get("z2_score")
    if z is not None and z2["zone"] == "distress":
        flags.append({"dimension": "破產風險", "severity": "fail",
                      "detail": "Altman Z'' {:.2f} 低於 {:.1f}，落在危險區"
                                .format(z, t["altman_z2_distress"])})
    elif z is not None and z2["zone"] == "grey":
        flags.append({"dimension": "破產風險", "severity": "warn",
                      "detail": "Altman Z'' {:.2f} 落在 {:.1f}~{:.1f} 灰色區"
                                .format(z, t["altman_z2_distress"], t["altman_z2_safe"])})

    return flags


def coverage(liq, sol, prof, cfq, z2, fscore):
    """How much of the scorecard could actually be computed.

    Without this, a company whose inputs are half missing looks identical to a
    clean one: Coherent raises no flags, but only because its ROIC, Z'' and
    interest coverage are all unavailable. An empty flag list means "nothing
    breached", which is only the same as "healthy" when the checks ran.
    """
    checks = {
        "流動比率": liq["current_ratio"],
        "負債佔資產": sol["liabilities_to_assets"],
        "利息保障倍數": sol["interest_coverage"],
        "有息負債/淨值": sol["debt_to_equity"],
        "ROIC": prof["roic"],
        "ROIC−WACC": prof["roic_minus_wacc"],
        "FCF 利潤率": cfq["fcf_margin"],
        "應計比率": cfq["accrual_ratio"],
        "Altman Z''": z2.get("z2_score"),
        "F-Score": fscore["normalised_9"],
    }
    missing = [k for k, v in checks.items() if v is None]
    return {
        "computed": len(checks) - len(missing),
        "total": len(checks),
        "unavailable": missing,
        "sufficient": len(missing) <= 2,
        "note": None if len(missing) <= 2 else
                "{} / {} 項指標因缺少 XBRL 標籤無法計算，未觸發警示不等於財務健全"
                .format(len(missing), len(checks)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+")
    args = parser.parse_args()

    for path in (FINANCIALS_PATH, FUNDAMENTALS_PATH, ASSUMPTIONS_PATH):
        if not path.exists():
            raise SystemExit(f"{path.name} missing; run the earlier pipeline steps first")

    fin = json.loads(FINANCIALS_PATH.read_text())
    fundamentals = json.loads(FUNDAMENTALS_PATH.read_text())["companies"]
    assumptions = json.loads(ASSUMPTIONS_PATH.read_text())["companies"]

    tickers = args.tickers or sorted(fin["companies"])
    results = {}

    header = ("{:6s}{:>7s}{:>8s}{:>8s}{:>9s}{:>9s}{:>8s}{:>8s}{:>7s}  {}".format(
        "ticker", "流動比", "負債率", "利息x", "ROIC", "價差", "應計率", "Z''", "F(9)", "警示"))
    print(header)
    print("-" * (len(header) + 8))

    for ticker in tickers:
        company = fin["companies"].get(ticker)
        if not company or not company["periods"]:
            print(f"{ticker:6s} 無資料")
            continue
        cur = company["periods"][0]
        prev = company["periods"][1] if len(company["periods"]) > 1 else {}
        wacc = (assumptions.get(ticker) or {}).get("wacc")

        liq = liquidity(cur)
        sol = solvency(cur)
        prof = profitability(cur, wacc)
        cfq = cash_flow_quality(cur, prev)
        z2 = altman_z2(cur)
        fscore = piotroski_normalised(fundamentals.get(ticker))
        flags = raise_flags(liq, sol, prof, cfq, z2)
        cov = coverage(liq, sol, prof, cfq, z2, fscore)

        results[ticker] = {
            "entity_name": company["entity_name"],
            "taxonomy": company["taxonomy"],
            "fiscal_year_end": cur["fiscal_year_end"],
            "prior_fiscal_year_end": prev.get("fiscal_year_end"),
            "currency": (cur.get("revenue") or {}).get("unit"),
            "source_form": (cur.get("revenue") or {}).get("form"),
            "source_accession": (cur.get("revenue") or {}).get("accession"),
            "source_filed": (cur.get("revenue") or {}).get("filed"),
            "liquidity": liq,
            "solvency": sol,
            "profitability": prof,
            "cash_flow_quality": cfq,
            "altman_z2": z2,
            "piotroski": fscore,
            "flags": flags,
            "flag_count": len(flags),
            "coverage": cov,
        }

        def cell(x, fmt, scale=1):
            return "n/a" if x is None else fmt.format(x * scale)

        print("{:6s}{:>7s}{:>8s}{:>8s}{:>9s}{:>9s}{:>8s}{:>8s}{:>7s}  {}".format(
            ticker,
            cell(liq["current_ratio"], "{:.2f}"),
            cell(sol["liabilities_to_assets"], "{:.0f}%", 100),
            cell(sol["interest_coverage"], "{:.0f}x"),
            cell(prof["roic"], "{:.1f}%", 100),
            cell(prof["roic_minus_wacc"], "{:+.1f}pp", 100),
            cell(cfq["accrual_ratio"], "{:+.1f}%", 100),
            cell(z2.get("z2_score"), "{:.2f}"),
            cell(fscore["normalised_9"], "{:.1f}"),
            "⚠️ {}".format(len(flags)) if flags
            else ("—" if cov["sufficient"] else "資料不足 {}/{}".format(
                cov["computed"], cov["total"]))))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "financials_generated_at": fin.get("generated_at"),
        "source": "Derived from SEC XBRL Company Facts; WACC from dcf_assumptions.json",
        "thresholds": THRESHOLDS,
        "companies": results,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n")
    print(f"\nWrote {OUTPUT_PATH.relative_to(REPO_ROOT)} ({len(results)} companies)")


if __name__ == "__main__":
    main()
