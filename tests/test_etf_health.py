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
        patcher = mock.patch.object(etf_holdings, "THEME_ETFS", THEMES)
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

    def test_missing_benchmark_is_an_error(self):
        funds, closes = market()
        with self.assertRaises(ValueError):
            etf_health.compute(funds, closes.drop(columns="SPY"), "x")


class BuildTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(etf_holdings, "THEME_ETFS", THEMES)
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

    def fetch(self, closes=None):
        def run(tickers, start, end):
            self.requested.append(tickers)
            return self.closes if closes is None else closes
        return run

    def test_writes_once_and_skips_an_identical_rerun(self):
        written, message = build_etf_health.build(self.output, self.holdings, self.fetch(), date(2026, 9, 25))
        self.assertTrue(written, message)
        self.assertIn("SPY", self.requested[0])
        self.assertIn("N0", self.requested[0])
        self.assertNotIn(None, self.requested[0])
        first = self.output.read_text()
        written, message = build_etf_health.build(self.output, self.holdings, self.fetch(), date(2026, 9, 25))
        self.assertFalse(written)
        self.assertIn("unchanged", message)
        self.assertEqual(self.output.read_text(), first)

    def test_an_older_session_never_replaces_a_newer_file(self):
        build_etf_health.build(self.output, self.holdings, self.fetch(), date(2026, 9, 25))
        written, message = build_etf_health.build(self.output, self.holdings, self.fetch(self.closes.iloc[:-3]),
                                                  date(2026, 9, 25))
        self.assertFalse(written)
        self.assertIn("newer", message)

    def test_unpriced_benchmark_exits_75_and_keeps_the_file(self):
        with self.assertRaises(SystemExit) as raised:
            build_etf_health.build(self.output, self.holdings, self.fetch(self.closes.drop(columns="SPY")),
                                   date(2026, 9, 25))
        self.assertEqual(raised.exception.code, 75)
        self.assertFalse(self.output.exists())

    def test_yahoo_symbols_round_trip(self):
        self.assertEqual(build_etf_health.yahoo("BRK.B"), "BRK-B")


class FrozenListTests(unittest.TestCase):
    def test_theme_list_is_frozen_under_its_version(self):
        self.assertEqual(etf_holdings.THEME_ETF_VERSION, "theme-etf-1")
        self.assertEqual(sorted(etf_holdings.THEME_ETFS), sorted(
            ["SMH", "SOXX", "IGV", "XBI", "KRE", "XHB", "ITA", "TAN", "URA", "XOP", "XRT", "IYT"]),
            "changing the list needs a new THEME_ETF_VERSION")


if __name__ == "__main__":
    unittest.main()
