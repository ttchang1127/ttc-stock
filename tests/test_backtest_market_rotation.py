import json
import pathlib
import sys
import unittest

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import backtest_market_rotation as backtest  # noqa: E402
import data_manifest  # noqa: E402
from test_market_rotation_research import SECTORS, synthetic_market  # noqa: E402


def regime_market(sessions=520, seed=3):
    """Sectors whose drift switches every 40 sessions, so states change."""
    closes, volumes, metadata = synthetic_market({}, sessions=sessions)
    rng = np.random.default_rng(seed)
    for sector in SECTORS:
        columns = [c for c in closes.columns if metadata.loc[c, "sector"] == sector]
        drift = np.repeat(rng.normal(0, 0.003, sessions // 40 + 1), 40)[:sessions]
        closes[columns] = closes[columns].mul(np.cumprod(1 + drift), axis=0)
    return closes, volumes, metadata


class OutcomeTests(unittest.TestCase):
    def test_excess_path_and_relative_drawdown(self):
        sector = np.array([100, 110, 99, 121.0])
        market = np.array([100, 100, 100, 110.0])
        result = backtest.outcome(sector, market, 0, 3)
        self.assertAlmostEqual(result["absolute"], 0.21)
        self.assertAlmostEqual(result["excess"], 0.11)
        self.assertAlmostEqual(result["mfe"], 0.11)
        self.assertAlmostEqual(result["mae"], -0.01)
        self.assertAlmostEqual(result["max_relative_drawdown"], 0.99 / 1.10 - 1)
        self.assertIsNone(backtest.outcome(sector, market, 1, 3), "window past the data end")

    def test_confidence_follows_event_counts(self):
        self.assertEqual([backtest.confidence(n) for n in (0, 9, 10, 29, 30, 60)],
                         ["insufficient", "insufficient", "exploratory", "exploratory", "moderate", "higher"])


class EventTests(unittest.TestCase):
    def walk(self, states):
        return pd.DataFrame({"confirmed": states})

    def test_seed_state_and_warmup_are_never_events(self):
        events, _ = backtest.find_events(self.walk(["a", "a", "b", "b", "c"]), warmup=3)
        self.assertEqual(events, [(4, "c")])

    def test_quick_reentry_is_not_independent(self):
        states = ["a"] * 3 + ["b"] * 3 + ["a"] * 3 + ["b"] * 15 + ["c"] * 12 + ["b"]
        events, skipped = backtest.find_events(self.walk(states), warmup=0)
        self.assertEqual(events, [(3, "b"), (24, "c"), (36, "b")])
        self.assertEqual(skipped, 2)


class BacktestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = backtest.run_backtest(*regime_market())

    def test_results_are_finite_and_split_into_calibration_and_holdout(self):
        json.dumps(self.result, allow_nan=False)
        self.assertGreater(self.result["event_count"], 20)
        samples = {event["sample"] for event in self.result["events"]}
        self.assertEqual(samples, {"calibration", "holdout"})
        holdout = self.result["period"]["holdout_start"]
        for event in self.result["events"]:
            self.assertEqual(event["sample"] == "holdout", event["date"] >= holdout)
            self.assertGreaterEqual(event["date"], self.result["period"]["evaluation_start"])

    def test_every_state_summary_reports_downside_not_only_win_rate(self):
        for state, block in self.result["by_state"].items():
            summary = block["all"]["60d"]
            if summary["events"]:
                for key in ("median_excess", "win_rate", "p10_excess", "median_mae",
                            "median_max_relative_drawdown", "confidence"):
                    self.assertIn(key, summary, state)

    def test_too_short_history_is_refused(self):
        closes, volumes, metadata = regime_market(sessions=200)
        with self.assertRaises(ValueError):
            backtest.run_backtest(closes, volumes, metadata)

    def test_methodology_is_labelled_c_quality_research(self):
        universe = json.loads((ROOT / "market_rotation_universe.json").read_text())
        method = backtest.methodology(universe, "research-1.0")
        self.assertEqual((method["history_quality"], method["status"]), ("C", "research"))
        self.assertIn("survivorship", method["history_quality_meaning"])

    def test_only_the_backtest_workflow_commits_results(self):
        manifest = data_manifest.load_manifest()
        path = "market_rotation_history/backtest/sector_results.json"
        self.assertTrue(data_manifest.may_commit(path, "market-rotation-backtest", manifest))
        self.assertFalse(data_manifest.may_commit(path, "update-prices", manifest))
        self.assertTrue(data_manifest.may_commit("market_rotation_history/2026/2026-10.jsonl",
                                                 "update-prices", manifest))


if __name__ == "__main__":
    unittest.main()
