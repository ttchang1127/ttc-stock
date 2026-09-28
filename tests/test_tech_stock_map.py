import json
import pathlib
import sys
import unittest

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

    def test_taxonomy_only_rebuild_rejects_a_new_candidate_without_quotes(self):
        config = json.loads(json.dumps(self.config))
        config["families"][0]["groups"][0]["tickers"].append("NEWTECH")
        with self.assertRaisesRegex(ValueError, "fresh price"):
            tech.reclassify_existing(config, self.map)


if __name__ == "__main__":
    unittest.main()
