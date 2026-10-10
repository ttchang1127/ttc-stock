"""Entry gating and immutable price-only matching for the 2026-10-10 pilot."""

import importlib.util
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "prepare_tech_stock_validation_entry",
    ROOT / "scripts" / "prepare_tech_stock_validation_entry.py",
)
entry_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry_tool)


class EntryPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frozen = json.loads((ROOT / "tech_stock_validation_20261010.json").read_text())
        days = [d.strftime("%Y-%m-%d") for d in pd.bdate_range(end="2026-10-09", periods=22)]
        cls.prior_days = days
        cls.series = {}
        for position, ticker in enumerate(cls.frozen["candidate_pool"]["visible_tickers"]
                                          + ["SPY", "VGT"]):
            cls.series[ticker] = [
                {"date": day, "adj_close": float(100 + position + i),
                 "close": float(100 + position + i), "dividend": 0.0, "split": 0.0}
                for i, day in enumerate(days + ["2026-10-12"])
            ]

    def test_pre_freeze_close_does_not_create_entry(self):
        series = {ticker: rows[:-1] for ticker, rows in self.series.items()}
        observed = datetime(2026, 10, 11, tzinfo=timezone.utc)
        self.assertIsNone(entry_tool.build_entry(self.frozen, series, observed))

    def test_first_close_matches_unique_same_family_controls(self):
        observed = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
        result = entry_tool.build_entry(self.frozen, self.series, observed)
        self.assertEqual(result["entry_date"], "2026-10-12")
        self.assertEqual(result["momentum_dates"]["end"], "2026-10-09")
        self.assertEqual(len(result["cases"]), 8)
        controls = [case["control_ticker"] for case in result["cases"]]
        self.assertEqual(len(controls), len(set(controls)))
        self.assertTrue(all(case["status"] == "ready" for case in result["cases"]))
        self.assertIsNone(result["outcomes_20d"])

    def test_missing_signal_entry_price_keeps_case(self):
        series = {ticker: list(rows) for ticker, rows in self.series.items()}
        series["AMD"] = series["AMD"][:-1]
        observed = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
        result = entry_tool.build_entry(self.frozen, series, observed)
        amd = next(case for case in result["cases"] if case["ticker"] == "AMD")
        self.assertEqual(amd["status"], "entry_price_missing")
        self.assertIsNone(amd["entry_adj_close"])
        self.assertEqual(len(result["cases"]), 8)


if __name__ == "__main__":
    unittest.main()
