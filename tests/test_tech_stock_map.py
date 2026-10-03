import json
import pathlib
import sys
import tempfile
import unittest
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_tech_stock_map as tech  # noqa: E402


class TechnologyMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / "tech_stock_taxonomy.json").read_text())
        cls.map = json.loads((ROOT / "tech_stock_map.json").read_text())

    def test_company_identity_and_owned_positions_survive_filter(self):
        definitions = tech.check_taxonomy(self.config)
        stocks = {row["ticker"]: row for row in self.map["stocks"]}
        self.assertEqual(len(stocks), len(self.map["stocks"]))
        self.assertNotIn("GOOG", stocks, "Alphabet share classes must not double-count market cap")
        self.assertTrue(set(self.config["always_show"]) <= stocks.keys())
        for ticker, row in stocks.items():
            self.assertIn(ticker, definitions)
            self.assertEqual(row["group_id"], definitions[ticker]["group_id"])
            self.assertTrue(row["reason"])
            self.assertTrue(row["sources"])
            self.assertGreater(row["market_cap_usd"], 0)
            if row["market_cap_usd"] < self.config["minimum_market_cap_usd"]:
                self.assertTrue(row["is_watchlist"], ticker)

    def test_dated_prices_and_group_breadth_are_consistent(self):
        self.assertEqual(self.map["coverage"]["visible"], len(self.map["stocks"]))
        self.assertGreaterEqual(self.map["coverage"]["priced"], 40)
        for row in self.map["stocks"]:
            if row["quote_as_of"] != self.map["as_of"]:
                self.assertTrue(all(value is None for value in row["returns"].values()))
            self.assertEqual(set(row["returns"]), set(tech.PERIODS))
        self.assertEqual(sum(group["count"] for group in self.map["families"]), len(self.map["stocks"]))
        self.assertEqual(sum(group["count"] for group in self.map["groups"]), len(self.map["stocks"]))

    def test_missing_or_old_history_has_no_performance(self):
        closes = {f"2026-09-{day:02d}": 100 + day for day in range(1, 27)}
        numbers, _ = tech.returns(closes, "2026-09-27")
        self.assertTrue(all(value is None for value in numbers.values()))
        numbers, above = tech.returns(closes, "2026-09-26")
        self.assertEqual(numbers["1d"], round((126 / 125 - 1) * 100, 2))
        self.assertIsNone(numbers["6m"])
        self.assertIsNone(above)

    def test_duplicate_classification_is_rejected(self):
        config = json.loads(json.dumps(self.config))
        config["families"][1]["groups"][0]["tickers"].append("NVDA")
        with self.assertRaisesRegex(ValueError, "duplicate ticker"):
            tech.check_taxonomy(config)

    def test_incomplete_nasdaq_quote_is_retried_without_losing_good_data(self):
        calls = {"AAPL": 0, "NVDA": 0}

        def fetcher(ticker, _start, _end):
            calls[ticker] += 1
            if ticker == "AAPL" and calls[ticker] == 1:
                return {"cap": None, "closes": {}, "name": None}
            return {"cap": 1_000_000_000_000, "closes": {"2026-10-01": 100.0}, "name": ticker}

        quotes = tech.fetch_quotes(["AAPL", "NVDA"], date(2026, 3, 1), date(2026, 10, 2), 2,
                                   fetcher=fetcher, sleep=lambda _: None)
        self.assertEqual(calls, {"AAPL": 2, "NVDA": 1})
        self.assertEqual(quotes["AAPL"]["closes"], {"2026-10-01": 100.0})

    def test_retry_uses_newer_history_and_preserves_known_cap(self):
        calls = {"AAPL": 0}

        def fetcher(ticker, _start, _end):
            if ticker == "NVDA":
                return {"cap": 2_000_000_000_000, "closes": {"2026-10-01": 110.0}, "name": ticker}
            calls[ticker] += 1
            if calls[ticker] == 1:
                return {"cap": 1_000_000_000_000, "closes": {"2026-09-25": 90.0}, "name": ticker}
            return {"cap": None, "closes": {"2026-10-01": 100.0}, "name": None}

        quotes = tech.fetch_quotes(["AAPL", "NVDA"], date(2026, 3, 1), date(2026, 10, 2), 2,
                                   fetcher=fetcher, sleep=lambda _: None)
        self.assertEqual(calls["AAPL"], 2)
        self.assertEqual(quotes["AAPL"]["cap"], 1_000_000_000_000)
        self.assertEqual(max(quotes["AAPL"]["closes"]), "2026-10-01")

    def test_taxonomy_only_rebuild_rejects_a_new_candidate_without_quotes(self):
        config = json.loads(json.dumps(self.config))
        config["families"][0]["groups"][0]["tickers"].append("NEWTECH")
        with self.assertRaisesRegex(ValueError, "fresh price"):
            tech.reclassify_existing(config, self.map)

    def test_history_records_full_candidate_pool_and_observation_limits(self):
        quotes = {"NVDA": {"cap": 1_000_000_000_000,
                           "closes": {self.map["as_of"]: 100.0}}}
        record = tech.history_snapshot(self.config, quotes, self.map)
        self.assertEqual(len(record["candidates"]), self.map["coverage"]["classified"])
        self.assertEqual(record["first_observed_at"], self.map["generated_at"])
        self.assertEqual(record["candidates"]["NVDA"]["raw_close_usd"], 100.0)
        self.assertEqual(record["candidates"]["NVDA"]["market_cap_usd"], 1_000_000_000_000)
        missing = next(t for t in record["candidates"] if t not in quotes)
        self.assertIn("market_cap", record["candidates"][missing]["missing"])
        self.assertIn("not adjusted", record["price_basis"])

    def test_history_keeps_first_observation_and_rejects_backfill(self):
        first = {"as_of": "2026-10-02", "first_observed_at": "2026-10-03T01:00:00+00:00",
                 "candidates": {"NVDA": {"market_cap_usd": 100}}}
        with tempfile.TemporaryDirectory() as temporary:
            history = pathlib.Path(temporary)
            texts, message = tech.plan_history_snapshot(first, history)
            self.assertIn("recorded", message)
            for path, content in texts.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            rerun = {**first, "first_observed_at": "2026-10-03T02:00:00+00:00"}
            self.assertFalse(tech.plan_history_snapshot(rerun, history)[0])
            changed = {**first, "candidates": {"NVDA": {"market_cap_usd": 200}}}
            self.assertIn("kept first", tech.plan_history_snapshot(changed, history)[1])
            older = {**first, "as_of": "2026-10-01"}
            with self.assertRaisesRegex(ValueError, "refusing to backfill"):
                tech.plan_history_snapshot(older, history)
            self.assertEqual(json.loads(next(history.glob("*/*.json")).read_text()), first)


if __name__ == "__main__":
    unittest.main()
