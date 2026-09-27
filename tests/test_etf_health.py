import json
import pathlib
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_etf_health  # noqa: E402
import etf_health  # noqa: E402
import etf_holdings  # noqa: E402
import record_etf_flows  # noqa: E402

DATES = pd.bdate_range(end="2026-09-25", periods=100)
THEMES = {"BRD": "廣泛", "NAR": "集中", "DWN": "下跌", "FLT": "持平", "THN": "資料少", "NEW": "未抓"}


def path(daily, start=100.0):
    return start * (1 + daily) ** np.arange(len(DATES))


def fund(rows, report="2026-06-30"):
    return {"fund_name": "Test", "report_date": report, "accession": "A1",
            "holdings": [{"ticker": t, "weight_pct": w, "asset_category": "EC", "name": t} for t, w in rows]
            + [{"ticker": None, "weight_pct": 1.0, "asset_category": "STIV", "name": "Cash"}]}


def market():
    columns = {"SPY": path(0.0005)}
    rows = {}
    # Broad: twelve holdings all rising.
    rows["BRD"] = [(f"B{n}", 100 / 12) for n in range(12)]
    for n in range(12):
        columns[f"B{n}"] = path(0.002 + n * 0.0001)
    columns["BRD"] = path(0.0022)
    # Narrow: one 60% holding up strongly, eleven small ones sliding.
    rows["NAR"] = [("N0", 60.0)] + [(f"N{n}", 40 / 11) for n in range(1, 12)]
    columns["N0"] = path(0.006)
    for n in range(1, 12):
        columns[f"N{n}"] = path(-0.001)
    columns["NAR"] = path(0.0033)
    # Down: everything falling.
    rows["DWN"] = [(f"D{n}", 100 / 12) for n in range(12)]
    for n in range(12):
        columns[f"D{n}"] = path(-0.002)
    columns["DWN"] = path(-0.002)
    # Flat.
    rows["FLT"] = [(f"F{n}", 100 / 12) for n in range(12)]
    for n in range(12):
        columns[f"F{n}"] = path(0.0001 if n % 2 else -0.0001)
    columns["FLT"] = path(0.0)
    # Thin: most weight in a foreign listing with no ticker, so coverage is low.
    rows["THN"] = [(f"T{n}", 3.0) for n in range(12)] + [(None, 60.0)]
    for n in range(12):
        columns[f"T{n}"] = path(0.003)
    columns["THN"] = path(0.003)
    closes = pd.DataFrame(columns, index=DATES)
    funds = {ticker: fund(rows[ticker]) for ticker in rows}
    funds["NEW"] = None
    return funds, closes


class HealthTests(unittest.TestCase):
    def setUp(self):
        for name, value in (("THEME_ETFS", THEMES), ("THEME_ETF_LISTS", {"test-list": tuple(THEMES)}),
                            ("THEME_ETF_VERSION", "test-list")):
            patcher = mock.patch.object(etf_holdings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        funds, closes = market()
        self.payload = etf_health.compute(funds, closes, "2026-09-26T00:00:00+00:00")
        self.rows = {row["ticker"]: row for row in self.payload["etfs"]}

    def test_states_tell_broad_from_carried_moves(self):
        states = {ticker: row["state"] for ticker, row in self.rows.items()}
        self.assertEqual(states, {"BRD": "broad_advance", "NAR": "narrow_advance", "DWN": "broad_decline",
                                  "FLT": "mixed", "THN": "data_limited"})
        self.assertEqual(self.payload["unavailable"], [{"ticker": "NEW", "theme": "未抓", "reason": "尚無 N-PORT 持股檔"}])
        self.assertEqual(etf_health.validate(self.payload), [])
        self.assertEqual(self.payload["label"], "research")

    def test_carried_move_shows_in_contribution_and_spread(self):
        narrow = self.rows["NAR"]
        self.assertEqual(narrow["concentration"]["top_contributors"][0]["ticker"], "N0")
        self.assertGreater(narrow["concentration"]["top3_share_pct"], 60)
        self.assertLess(narrow["returns"]["equal_minus_cap_pp"], 0, "equal weight lags when one stock carries")
        self.assertEqual(narrow["breadth"]["above_ma50_equal_pct"], round(100 / 12, 1))
        broad = self.rows["BRD"]
        self.assertEqual(broad["breadth"]["above_ma50_equal_pct"], 100.0)
        self.assertLessEqual(broad["concentration"]["top3_share_pct"], 60)

    def test_a_concentrated_fund_with_broad_participation_is_not_carried(self):
        # SOXX on 2026-09-25: top three made 64% of the move, but 83% of holdings were above their
        # 50-session average and equal weight matched cap weight.
        self.assertEqual(etf_health.classify("up", 0.83, 0.64, -0.0006, False), "broad_advance")
        self.assertEqual(etf_health.classify("up", 0.83, 0.64, -0.03, False), "narrow_advance")
        self.assertEqual(etf_health.classify("up", 0.55, 0.30, 0.0, False), "mixed")
        self.assertEqual(etf_health.classify("down", 0.47, 0.52, -0.038, False), "mixed")
        self.assertEqual(etf_health.classify("down", 0.30, 0.70, 0.03, False), "narrow_decline")
        self.assertEqual(etf_health.classify("down", 0.12, 0.54, -0.003, False), "broad_decline")

    def test_coverage_counts_unpriced_weight(self):
        thin = self.rows["THN"]
        self.assertEqual(thin["constituents"]["priced"], 12)
        self.assertAlmostEqual(thin["constituents"]["coverage_pct"], 37.5, places=1)
        self.assertIn("low_coverage", thin["flags"])
        self.assertEqual(self.rows["BRD"]["constituents"]["coverage_pct"], 100.0, "cash is not counted as stock")

    def test_rows_are_ranked_by_relative_strength(self):
        rs = [row["etf"]["rs20_pct"] for row in self.payload["etfs"]]
        self.assertEqual(rs, sorted(rs, reverse=True))
        self.assertEqual(self.payload["as_of"], "2026-09-25")

    def test_old_holdings_and_drifted_weights_are_flagged(self):
        funds, closes = market()
        funds["BRD"]["report_date"] = "2026-01-31"
        closes["BRD"] = path(-0.002)
        row = next(r for r in etf_health.compute(funds, closes, "x")["etfs"] if r["ticker"] == "BRD")
        self.assertIn("holdings_old", row["flags"])
        self.assertIn("stale_weights", row["flags"])
        self.assertEqual(row["direction"], "down", "direction follows the ETF itself")

    def test_validation_catches_contract_breaks(self):
        broken = json.loads(json.dumps(self.payload))
        broken["etfs"][0]["state"] = "moon"
        broken["unavailable"] = []
        broken["label"] = "signal"
        problems = etf_health.validate(broken)
        self.assertTrue(any("unknown state" in p for p in problems))
        self.assertTrue(any("frozen list" in p for p in problems))
        self.assertTrue(any("research" in p for p in problems))

    def test_nport_flows_are_net_creations_over_net_assets(self):
        funds, closes = market()
        funds["BRD"]["net_assets_usd"] = 1000.0
        funds["BRD"]["monthly_flows"] = [
            {"month": "2026-04", "net_usd": 30.0}, {"month": "2026-05", "net_usd": -10.0},
            {"month": "2026-06", "net_usd": None}]
        row = next(r for r in etf_health.compute(funds, closes, "x")["etfs"] if r["ticker"] == "BRD")
        self.assertEqual(row["flows"]["nport"], {"net_3m_pct": 2.0, "months": "2026-04～2026-05"})
        self.assertIsNone(self.rows["NAR"]["flows"]["nport"]["net_3m_pct"])

    def test_estimated_flows_need_a_full_window(self):
        def day(n, shares, close=10.0, assets=None):
            return {"as_of": f"2026-09-{n:02d}", "etfs": {"BRD": {"shares_outstanding": shares, "close": close,
                                                                  "total_assets": assets}}}
        history = [day(n, 100 + n) for n in range(1, 7)]  # five intervals, +1 share each at $10
        flows = etf_health.implied_flows(history, "BRD")
        self.assertEqual(flows["flow_5d_pct"], round(50 / (106 * 10) * 100, 2))
        self.assertIsNone(flows["flow_20d_pct"], "20 sessions not recorded yet")
        by_assets = [day(1, None, 10.0, 1000.0), day(2, None, 11.0, 1150.0)]
        self.assertEqual(etf_health.implied_flows(by_assets * 1, "BRD")["sessions_recorded"], 2)
        flows = etf_health.implied_flows(by_assets + [day(3, None, 11.0, 1150.0)] * 4, "BRD")
        self.assertEqual(flows["flow_5d_pct"], round(50 / 1150 * 100, 2), "asset growth beyond the price move")
        stale = [day(n, 12.5e6, 106.0, 15.7e9 + n * 1e8) for n in range(1, 7)]
        # IGV 2026-09-25: 12.5m shares x $106 is $1.3bn, but assets were $15.7bn.
        self.assertEqual(etf_health.implied_flows(stale, "BRD")["flow_5d_pct"], round(5e8 / 16.3e9 * 100, 2),
                         "stale share counts fall back to assets")
        gap = history[:3] + [day(4, None)] + history[4:]
        self.assertIsNone(etf_health.implied_flows(gap, "BRD")["flow_5d_pct"], "a missing day is not a zero")

    def test_missing_benchmark_is_an_error(self):
        funds, closes = market()
        with self.assertRaises(ValueError):
            etf_health.compute(funds, closes.drop(columns="SPY"), "x")


class ConstituentMapTests(unittest.TestCase):
    def setUp(self):
        for name, value in (("THEME_ETFS", THEMES), ("THEME_ETF_LISTS", {"test-list": tuple(THEMES)}),
                            ("THEME_ETF_VERSION", "test-list")):
            patcher = mock.patch.object(etf_holdings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.funds, self.closes = market()
        self.detail = etf_health.constituents(self.funds, self.closes, "x")

    def test_holdings_are_listed_until_80_percent_of_the_fund(self):
        narrow = self.detail["etfs"]["NAR"]["holdings"]
        self.assertEqual(narrow[0]["ticker"], "N0")
        self.assertEqual(narrow[0]["weight_pct"], 60.0)
        self.assertGreaterEqual(narrow[-1]["cumulative_pct"], 80.0)
        self.assertLess(narrow[-2]["cumulative_pct"], 80.0, "stops at the first holding that reaches 80%")
        self.assertEqual(len(narrow), 7)
        self.assertEqual(etf_health.validate_constituents(self.detail), [])
        self.assertNotIn("NEW", self.detail["etfs"], "funds without holdings are left out")

    def test_unmapped_holdings_are_listed_by_name_without_returns(self):
        thin = self.detail["etfs"]["THN"]["holdings"]
        self.assertIsNone(thin[0]["ticker"], "the 60% foreign line comes first")
        self.assertEqual(thin[0]["returns"]["1d"], None)
        self.assertEqual(thin[1]["ticker"][0], "T")

    def test_period_returns_need_enough_sessions_and_a_current_price(self):
        row = self.detail["etfs"]["BRD"]["holdings"][0]
        close = self.closes[row["ticker"]]
        self.assertEqual(row["returns"]["1m"], round((close.iloc[-1] / close.iloc[-22] - 1) * 100, 2))
        self.assertEqual(row["returns"]["1d"], round((close.iloc[-1] / close.iloc[-2] - 1) * 100, 2))
        self.assertIsNone(row["returns"]["6m"], "100 sessions cannot give a 126-session return")
        stale = self.closes.copy()
        stale.iloc[-1, stale.columns.get_loc(row["ticker"])] = np.nan
        self.assertEqual(etf_health.period_returns(stale[row["ticker"]])["1d"], None,
                         "a missing latest close is not carried forward")
        self.assertEqual(set(self.detail["etfs"]["BRD"]["returns"]), set(etf_health.MAP_PERIODS))


class BuildTests(unittest.TestCase):
    def setUp(self):
        for name, value in (("THEME_ETFS", THEMES), ("THEME_ETF_LISTS", {"test-list": tuple(THEMES)}),
                            ("THEME_ETF_VERSION", "test-list")):
            patcher = mock.patch.object(etf_holdings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = pathlib.Path(self.directory.name)
        self.holdings = self.root / "etf_holdings"
        self.holdings.mkdir()
        self.funds, self.closes = market()
        for ticker, data in self.funds.items():
            if data:
                (self.holdings / f"{ticker}.json").write_text(json.dumps(data))
        self.output = self.root / "etf_health.json"
        self.requested = []

    def build(self, fetch, today):
        return build_etf_health.build(self.output, self.holdings, fetch, today, flows_dir=self.root / "flows",
                                      history_dir=self.root / "history")

    def fetch(self, closes=None):
        def run(tickers, start, end):
            self.requested.append(tickers)
            return self.closes if closes is None else closes
        return run

    def test_writes_once_and_skips_an_identical_rerun(self):
        written, message = self.build(self.fetch(), date(2026, 9, 25))
        self.assertTrue(written, message)
        self.assertIn("SPY", self.requested[0])
        self.assertIn("N0", self.requested[0])
        self.assertNotIn(None, self.requested[0])
        first = self.output.read_text()
        written, message = self.build(self.fetch(), date(2026, 9, 25))
        self.assertFalse(written)
        self.assertIn("unchanged", message)
        self.assertEqual(self.output.read_text(), first)
        detail = json.loads((self.root / "etf_constituents.json").read_text())
        self.assertEqual(detail["as_of"], "2026-09-25")
        self.assertIn("NAR", detail["etfs"])
        lines = (self.root / "history" / "2026-09.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 1, "one snapshot per session, even across reruns")
        record = json.loads(lines[0])
        self.assertEqual(record["as_of"], "2026-09-25")
        self.assertEqual(record["rule_version"], etf_health.HEALTH_RULE_VERSION)
        self.assertEqual(record["etfs"]["NAR"]["state"], "narrow_advance")
        self.assertNotIn("NEW", record["etfs"], "funds without holdings are not recorded")

    def test_an_older_session_never_replaces_a_newer_file(self):
        self.build(self.fetch(), date(2026, 9, 25))
        written, message = self.build(self.fetch(self.closes.iloc[:-3]),
                                                  date(2026, 9, 25))
        self.assertFalse(written)
        self.assertIn("newer", message)
        self.assertEqual(len((self.root / "history" / "2026-09.jsonl").read_text().splitlines()), 1)

    def test_unpriced_benchmark_exits_75_and_keeps_the_file(self):
        with self.assertRaises(SystemExit) as raised:
            self.build(self.fetch(self.closes.drop(columns="SPY")),
                                   date(2026, 9, 25))
        self.assertEqual(raised.exception.code, 75)
        self.assertFalse(self.output.exists())

    def test_yahoo_symbols_round_trip(self):
        self.assertEqual(build_etf_health.yahoo("BRK.B"), "BRK-B")


class FlowRecordTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(etf_holdings, "THEME_ETFS", {"AAA": "a", "BBB": "b"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder = pathlib.Path(self.directory.name)

    def record(self, as_of, shares=100.0):
        return record_etf_flows.snapshot(as_of, {"AAA": 10.0, "BBB": float("nan")},
                                         {"AAA": {"sharesOutstanding": shares, "totalAssets": None}}, "t")

    def write(self, texts):
        for path, text in texts.items():
            path.write_text(text)

    def test_append_only_one_line_per_session(self):
        first = self.record("2026-09-24")
        self.assertEqual(first["etfs"]["BBB"], {"close": None, "shares_outstanding": None, "total_assets": None})
        texts, status, _ = record_etf_flows.plan_append(first, self.folder)
        self.assertEqual(status, "appended")
        self.write(texts)
        self.assertEqual(record_etf_flows.plan_append(first, self.folder)[1], "unchanged")
        self.assertEqual(record_etf_flows.plan_append(self.record("2026-09-24", 101.0), self.folder)[1], "conflict")
        texts, status, _ = record_etf_flows.plan_append(self.record("2026-10-01"), self.folder)
        self.write(texts)
        self.assertEqual(record_etf_flows.plan_append(self.record("2026-09-30"), self.folder)[1], "out_of_order")
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ["2026-09.jsonl", "2026-10.jsonl"])
        self.assertEqual([row["as_of"] for row in record_etf_flows.read_history(self.folder)],
                         ["2026-09-24", "2026-10-01"])
        self.assertEqual(record_etf_flows.validate_history(self.folder), [])


class FrozenListTests(unittest.TestCase):
    def test_theme_lists_are_frozen_under_their_versions(self):
        first = ["SMH", "SOXX", "IGV", "XBI", "KRE", "XHB", "ITA", "TAN", "URA", "XOP", "XRT", "IYT"]
        self.assertEqual(sorted(etf_holdings.THEME_ETF_LISTS["theme-etf-1"]), sorted(first),
                         "a published list is never edited")
        self.assertEqual(etf_holdings.THEME_ETF_VERSION, "theme-etf-2")
        self.assertEqual(sorted(etf_holdings.THEME_ETFS), sorted(first + [
            "XME", "GDX", "XES", "XPH", "IHI", "KIE", "COPX", "LIT", "SKYY", "CIBR", "JETS", "BOTZ", "PAVE"]),
            "changing the list needs a new THEME_ETF_VERSION")
        self.assertTrue(set(etf_holdings.THEME_ETF_LISTS["theme-etf-1"]) <= set(etf_holdings.THEME_ETFS),
                        "the current list covers every earlier list, so earlier results can be rerun")
        self.assertTrue(all(ticker in etf_holdings.THEME_LABELS for ticker in etf_holdings.THEME_ETFS))

    def test_a_file_from_an_earlier_list_still_validates(self):
        payload = {"label": "research", "rule_version": etf_health.HEALTH_RULE_VERSION,
                   "etf_list_version": "theme-etf-1", "unavailable": [],
                   "etfs": [{"ticker": t, "state": "mixed", "direction": "flat", "flags": [],
                             "constituents": {"coverage_pct": 90.0}, "breadth": {}}
                            for t in etf_holdings.THEME_ETF_LISTS["theme-etf-1"]]}
        self.assertEqual(etf_health.validate(payload), [])
        payload["etf_list_version"] = "theme-etf-9"
        self.assertTrue(etf_health.validate(payload))


if __name__ == "__main__":
    unittest.main()
