import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "build_long_term_radar", ROOT / "scripts" / "build_long_term_radar.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class LongTermRadarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payloads = {
            "quarterly": json.loads((ROOT / "quarterly_financials.json").read_text()),
            "health": json.loads((ROOT / "financial_health.json").read_text()),
            "valuation": json.loads((ROOT / "valuation.json").read_text()),
            "guidance": json.loads((ROOT / "guidance_history.json").read_text()),
            "thesis": json.loads((ROOT / "investment_thesis_status.json").read_text()),
            "capital": json.loads((ROOT / "capital_allocation_cards.json").read_text()),
        }
        cls.holdings = json.loads((ROOT / "portfolio_holdings.json").read_text())
        cls.payload = MODULE.build_payload(copy.deepcopy(cls.payloads), copy.deepcopy(cls.holdings))

    def company(self, ticker):
        return next(row for row in self.payload["companies"] if row["ticker"] == ticker)

    def test_covers_14_individual_stocks_and_exactly_seven_dimensions(self):
        self.assertEqual(self.payload["tracked_count"], 14)
        self.assertNotIn("VGT", {row["ticker"] for row in self.payload["companies"]})
        self.assertNotIn("VOO", {row["ticker"] for row in self.payload["companies"]})
        expected = [row["id"] for row in self.payload["dimension_order"]]
        for company in self.payload["companies"]:
            self.assertEqual([row["id"] for row in company["dimensions"]], expected)

    def test_scores_are_bounded_and_missing_values_are_not_neutral_filled(self):
        for company in self.payload["companies"]:
            for dimension in company["dimensions"]:
                if dimension["score"] is not None:
                    self.assertGreaterEqual(dimension["score"], 0)
                    self.assertLessEqual(dimension["score"], 100)
                for metric in dimension["metrics"]:
                    if metric["score"] is not None:
                        self.assertGreaterEqual(metric["score"], 0)
                        self.assertLessEqual(metric["score"], 100)
        aapl_execution = next(row for row in self.company("AAPL")["dimensions"] if row["id"] == "execution")
        guidance = next(row for row in aapl_execution["metrics"] if row["id"] == "guidance_delivery")
        self.assertIsNone(guidance["score"])
        self.assertEqual(guidance["display"], "資料不足")
        self.assertEqual(aapl_execution["coverage"], {"known": 1, "total": 2})

    def test_share_scaling_anomaly_remains_unscored(self):
        capital = next(row for row in self.company("ONDS")["dimensions"] if row["id"] == "capital_allocation")
        shares = next(row for row in capital["metrics"] if row["id"] == "share_change")
        self.assertIsNone(shares["score"])
        self.assertIn("XBRL 縮放", shares["note"])

    def test_growth_and_valuation_are_separate_dimensions(self):
        nvda = self.company("NVDA")
        scores = {row["id"]: row["score"] for row in nvda["dimensions"]}
        self.assertGreater(scores["growth"], scores["valuation"])
        self.assertEqual(nvda["coverage"], {"known": 7, "total": 7, "missing": []})

    def test_generated_json_is_deterministic(self):
        expected = json.loads((ROOT / "long_term_radar.json").read_text())
        self.assertEqual(self.payload, expected)

    def test_dashboard_and_automation_are_connected(self):
        dashboard = (ROOT / "dashboard.html").read_text()
        self.assertIn("page-radar", dashboard)
        self.assertIn("chartLongTermRadar", dashboard)
        self.assertIn("long_term_radar.json", dashboard)
        for workflow in ("update-prices.yml", "sec-filing-alerts.yml"):
            text = (ROOT / ".github" / "workflows" / workflow).read_text()
            self.assertIn("build_long_term_radar.py", text)
            self.assertIn("long_term_radar", text)


if __name__ == "__main__":
    unittest.main()
