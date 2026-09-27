import pathlib
import sys
import unittest
from unittest import mock

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import backtest_theme_etfs as bt  # noqa: E402
import etf_holdings  # noqa: E402

ETFS = [f"E{n}" for n in range(8)]


def frames(months, seed, predictive):
    rng = np.random.default_rng(seed)
    index = pd.date_range("2008-01-31", periods=months, freq="ME")
    outcome = pd.DataFrame(rng.normal(0, 0.03, (months, len(ETFS))), index=index, columns=ETFS)
    noise = pd.DataFrame(rng.normal(0, 0.03, (months, len(ETFS))), index=index, columns=ETFS)
    return (outcome * predictive + noise), outcome


class EvaluateTests(unittest.TestCase):
    def test_a_predictive_signal_is_supported_and_noise_is_not(self):
        signal, outcome = frames(200, 1, predictive=1.0)
        result = bt.evaluate(signal, outcome, "2016-01", 1)
        self.assertEqual(result["verdict"], "supported")
        self.assertGreater(result["calibration"]["mean_ic"], 0.3)
        self.assertEqual(result["calibration"]["end"], "2015-11")
        self.assertEqual(result["holdout"]["start"], "2015-12", "the Dec signal's outcome is the first holdout month")
        noise, outcome = frames(200, 2, predictive=0.0)
        self.assertIn(bt.evaluate(noise, outcome, "2016-01", 1)["verdict"], ("not_supported",))

    def test_unsigned_hypothesis_accepts_a_consistent_negative_ic(self):
        signal, outcome = frames(200, 3, predictive=-1.0)
        result = bt.evaluate(signal, outcome, "2016-01", None)
        self.assertEqual(result["verdict"], "supported")
        self.assertLess(result["all"]["mean_ic"], 0)
        self.assertEqual(bt.evaluate(signal, outcome, "2016-01", 1)["verdict"], "not_supported",
                         "a wrong-signed result is not support for a signed hypothesis")

    def test_short_samples_are_not_judged(self):
        signal, outcome = frames(20, 4, predictive=1.0)
        self.assertEqual(bt.evaluate(signal, outcome, "2009-01", 1)["verdict"], "insufficient_sample")

    def test_forward_relative_is_next_month_minus_the_average(self):
        monthly = pd.DataFrame({"A": [100, 110, 121], "B": [100, 100, 100]},
                               index=pd.date_range("2020-01-31", periods=3, freq="ME"))
        rel = bt.forward_relative(monthly)
        self.assertAlmostEqual(rel.iloc[0]["A"], 0.05)
        self.assertAlmostEqual(rel.iloc[0]["B"], -0.05)
        self.assertTrue(rel.iloc[-1].isna().all(), "no outcome after the last month")


class PointInTimeTests(unittest.TestCase):
    HISTORY = {"filings": [
        {"accession": "A", "report_date": "2026-03-31", "filed": "2026-05-28", "weights": {"X": 50.0}},
        {"accession": "B", "report_date": "2026-06-30", "filed": "2026-08-28", "weights": {"X": 60.0}}]}

    def test_filings_count_from_their_filing_date(self):
        self.assertEqual(bt.filing_at(self.HISTORY, pd.Timestamp("2026-07-31"))["accession"], "A",
                         "June holdings were not public until August 28")
        self.assertEqual(bt.filing_at(self.HISTORY, pd.Timestamp("2026-08-31"))["accession"], "B")
        self.assertIsNone(bt.filing_at(self.HISTORY, pd.Timestamp("2026-04-30")))

    def test_holdings_signals_use_priced_weights_and_skip_thin_coverage(self):
        days = pd.bdate_range("2026-01-01", "2026-09-30")
        rising = pd.Series(np.linspace(100, 150, len(days)), index=days)
        falling = pd.Series(np.linspace(150, 100, len(days)), index=days)
        daily = pd.DataFrame({f"U{n}": rising for n in range(8)} | {f"D{n}": falling for n in range(4)})
        weights = {f"U{n}": 5.0 for n in range(8)} | {f"D{n}": 15.0 for n in range(4)}
        thin = {"U0": 10.0, "MISSING": 90.0}
        flows = [{"month": m, "net_usd": 10.0} for m in ("2026-04", "2026-05", "2026-06")]
        histories = {
            "OK": {"filings": [{"accession": "A", "report_date": "2026-06-30", "filed": "2026-07-15",
                                "equity_weight_pct": 100.0, "net_assets_usd": 300.0, "monthly_flows": flows,
                                "weights": weights}]},
            "THIN": {"filings": [{"accession": "B", "report_date": "2026-06-30", "filed": "2026-07-15",
                                  "equity_weight_pct": 100.0, "net_assets_usd": 100.0, "monthly_flows": [],
                                  "weights": thin}]}}
        month_ends = pd.date_range("2026-06-30", "2026-09-30", freq="ME")
        signals, coverage = bt.holdings_signals(histories, daily, month_ends)
        self.assertTrue(np.isnan(signals["breadth_50"].at[month_ends[0], "OK"]), "not public at June end")
        self.assertAlmostEqual(signals["breadth_50"].at[month_ends[-1], "OK"], 8 / 12)
        self.assertGreater(signals["participation_20"].at[month_ends[-1], "OK"], 0,
                           "the many small risers beat the heavy fallers")
        self.assertAlmostEqual(signals["nport_flow_3m"].at[month_ends[-1], "OK"], 0.1)
        self.assertEqual(coverage.at[month_ends[-1], "THIN"], 10.0)
        self.assertTrue(np.isnan(signals["breadth_50"].at[month_ends[-1], "THIN"]))


class RunTests(unittest.TestCase):
    def test_run_reports_every_frozen_signal_and_its_limits(self):
        rng = np.random.default_rng(5)
        index = pd.date_range("2006-01-31", periods=240, freq="ME")
        monthly = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0.005, 0.05, (240, len(ETFS))), axis=0)),
                               index=index, columns=ETFS)
        lists = {"list-1": tuple(ETFS[:6]), "list-2": tuple(ETFS)}
        with mock.patch.object(etf_holdings, "THEME_ETF_LISTS", lists), \
                mock.patch.object(etf_holdings, "THEME_ETF_VERSION", "list-2"):
            result = bt.run(monthly, {}, None)
        self.assertEqual(result["etf_list_version"], "list-2")
        self.assertEqual(result["etfs"], ETFS)
        self.assertEqual([row["etf_list_version"] for row in result["earlier_lists"]], ["list-1"],
                         "an earlier list's result stays on record")
        self.assertEqual(result["earlier_lists"][0]["etfs"], ETFS[:6])
        self.assertEqual(len(result["earlier_lists"][0]["signals"]), len(bt.SIGNALS))
        self.assertEqual([row["id"] for row in result["signals"]], [spec["id"] for spec in bt.SIGNALS])
        self.assertEqual(result["status"], "research")
        by_id = {row["id"]: row for row in result["signals"]}
        self.assertIn(by_id["momentum_12_1"]["verdict"], bt.VERDICTS)
        self.assertGreater(by_id["momentum_12_1"]["all"]["months"], 150)
        self.assertEqual(by_id["breadth_50"]["verdict"], "insufficient_sample", "no N-PORT history given")
        self.assertTrue(result["limitations"])

    def test_signal_list_is_frozen_under_its_version(self):
        self.assertEqual(bt.SIGNAL_VERSION, "theme-signals-1")
        self.assertEqual([spec["id"] for spec in bt.SIGNALS], [
            "momentum_12_1", "momentum_6_1", "breadth_50", "participation_20", "nport_flow_3m"],
            "changing the candidates needs a new SIGNAL_VERSION")


if __name__ == "__main__":
    unittest.main()
