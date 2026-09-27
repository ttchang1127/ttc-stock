import json
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import backtest_sector_etf_momentum as momentum  # noqa: E402
import data_manifest  # noqa: E402

TICKERS = sorted(momentum.SECTOR_ETFS)


def market(months=330, persistence=0.0, seed=5, late=("XLRE", "XLC")):
    """Month-end prices for the 11 ETFs; ``persistence`` makes each ETF's drift last for a year."""
    rng = np.random.default_rng(seed)
    index = pd.date_range("1998-12-31", periods=months, freq="ME")
    returns = rng.normal(0.006, 0.05, (months, len(TICKERS)))
    if persistence:
        drift = np.repeat(rng.normal(0, 0.02, (months // 12 + 1, len(TICKERS))), 12, axis=0)[:months]
        returns += persistence * drift
    prices = pd.DataFrame(100 * np.cumprod(1 + returns, axis=0), index=index, columns=TICKERS)
    for ticker, start in zip(late, ("2015-10-31", "2018-06-30")):
        prices.loc[prices.index < start, ticker] = np.nan
    rf = pd.Series(0.02 / 12, index=index)
    spy = prices.mean(axis=1).pct_change()
    spy.index = spy.index.strftime("%Y-%m")
    return prices, rf, spy


class ScoringTests(unittest.TestCase):
    def test_score_skips_the_latest_month_and_needs_every_point(self):
        prices, _, _ = market()
        position = 20
        scores = momentum.momentum_scores(prices, position, 12)
        expected = prices.iloc[position - 1] / prices.iloc[position - 12] - 1
        pd.testing.assert_series_equal(scores, expected.dropna().sort_index(), check_names=False)
        self.assertNotIn("XLRE", scores.index, "an ETF without a full look-back is not ranked")

    def test_selection_is_deterministic_and_the_filter_falls_back_to_all(self):
        scores = pd.Series({"XLK": 0.2, "XLE": 0.2, "XLV": 0.1, "XLU": -0.05, "XLF": 0.0, "XLI": 0.01})
        self.assertEqual(momentum.select(scores, 0.01, False), ["XLE", "XLK", "XLV"])
        self.assertEqual(momentum.select(scores, 0.15, True), sorted(scores.index))


class SimulationTests(unittest.TestCase):
    def test_signals_never_use_future_prices(self):
        prices, rf, _ = market()
        full = momentum.simulate(prices, rf, momentum.VARIANTS[0])
        cut = momentum.simulate(prices.iloc[:200], rf.iloc[:200], momentum.VARIANTS[0])
        pd.testing.assert_frame_equal(full.iloc[:len(cut)].reset_index(drop=True), cut)

    def test_costs_and_quarterly_rebalancing(self):
        prices, rf, _ = market()
        monthly = momentum.simulate(prices, rf, momentum.VARIANTS[0])
        quarterly = momentum.simulate(prices, rf, momentum.VARIANTS[2])
        self.assertLess(quarterly["traded"].sum(), monthly["traded"].sum())
        changes = quarterly["held"].map(tuple).ne(quarterly["held"].map(tuple).shift())
        self.assertTrue(all(month[5:] in ("01", "04", "07", "10") for month in quarterly["month"][changes][1:]))
        with mock.patch.object(momentum, "COST_PER_DOLLAR_TRADED", 0.0):
            free = momentum.simulate(prices, rf, momentum.VARIANTS[0])
        self.assertTrue((free["strategy"] >= monthly["strategy"]).all())
        self.assertGreater((free["strategy"] - monthly["strategy"]).sum(), 0)

    def test_persistent_trends_are_detected_and_noise_is_not(self):
        prices, rf, spy = market(persistence=1.0)
        trend = momentum.evaluate(prices, rf, spy, momentum.VARIANTS[0])
        self.assertGreater(trend["calibration"]["excess_cagr_pp"], 0)
        self.assertIn(trend["verdict"], ("supported", "partial"))
        noise = momentum.evaluate(*market(seed=11), momentum.VARIANTS[0])
        self.assertLess(abs(noise["calibration"]["information_ratio"]), 0.6)


class OutputTests(unittest.TestCase):
    def test_every_frozen_variant_is_reported_with_a_known_verdict(self):
        self.assertEqual(momentum.MOMENTUM_VERSION, "etf-momentum-1",
                         "changing VARIANTS needs a new MOMENTUM_VERSION")
        result = momentum.run(*market())
        json.dumps(result, allow_nan=False)
        self.assertEqual([v["id"] for v in result["variants"]], [v["id"] for v in momentum.VARIANTS])
        for variant in result["variants"]:
            self.assertIn(variant["verdict"], result["verdicts"])
            self.assertEqual(variant["holdout"]["start"], momentum.HOLDOUT_START)
        self.assertEqual(result["status"], "research")
        self.assertEqual(len(result["latest_ranking"]["rows"]), 11)

    def test_verdict_rules(self):
        good = {"excess_cagr_pp": 1.0, "information_ratio": 0.3, "strategy_max_drawdown": -40,
                "equal_weight_max_drawdown": -38}
        bad = dict(good, excess_cagr_pp=-0.5)
        self.assertEqual(momentum.judge(good, good, (0.01, 0.2))["verdict"], "supported")
        self.assertEqual(momentum.judge(good, bad, (0.01, 0.2))["verdict"], "partial")
        self.assertEqual(momentum.judge(good, good, (-0.05, 0.2))["verdict"], "partial")
        self.assertEqual(momentum.judge(bad, good, (0.01, 0.2))["verdict"], "not_supported")

    def test_results_are_committed_only_by_the_backtest_workflow(self):
        manifest = data_manifest.load_manifest()
        path = "market_rotation_history/backtest/sector_etf_momentum.json"
        self.assertTrue(data_manifest.may_commit(path, "market-rotation-backtest", manifest))
        self.assertFalse(data_manifest.may_commit(path, "update-prices", manifest))


class MainTests(unittest.TestCase):
    """main() with a fake yfinance, in both column layouts yfinance has used."""

    def fake_download(self, multi_single):
        def download(tickers, start, end, **kwargs):
            index = pd.bdate_range(start, pd.Timestamp.today().normalize())
            rng = np.random.default_rng(1)
            if isinstance(tickers, str):
                values = np.full(len(index), 4.0)
                if multi_single:
                    columns = pd.MultiIndex.from_tuples([("Close", tickers)], names=["Price", "Ticker"])
                    return pd.DataFrame(values[:, None], index=index, columns=columns)
                return pd.DataFrame({"Close": values}, index=index)
            columns = pd.MultiIndex.from_product([["Adj Close", "Close"], tickers], names=["Price", "Ticker"])
            paths = 100 * np.cumprod(1 + rng.normal(0.0003, 0.01, (len(index), len(tickers))), axis=0)
            frame = pd.DataFrame(np.hstack([paths, paths]), index=index, columns=columns)
            frame.loc[frame.index < "2015-10-08", ("Adj Close", "XLRE")] = np.nan
            return frame
        return download

    def test_main_writes_a_complete_result(self):
        for multi_single in (False, True):
            fake = types.SimpleNamespace(download=self.fake_download(multi_single))
            with tempfile.TemporaryDirectory() as directory, \
                    mock.patch.dict(sys.modules, {"yfinance": fake}), \
                    mock.patch.object(sys, "argv", ["x", "--output", f"{directory}/out.json"]):
                momentum.main()
                result = json.loads(pathlib.Path(directory, "out.json").read_text())
            self.assertEqual(len(result["variants"]), len(momentum.VARIANTS))
            self.assertLess(result["period"]["last_month"], pd.Timestamp.today().strftime("%Y-%m"),
                            "the unfinished current month is never ranked")
            self.assertTrue(result["variants"][0]["holdout"]["months"] > 100)


if __name__ == "__main__":
    unittest.main()
