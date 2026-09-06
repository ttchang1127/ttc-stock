import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_segment_driver_validation.py"
SPEC = importlib.util.spec_from_file_location("build_segment_driver_validation", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SegmentDriverValidationTests(unittest.TestCase):
    def test_calculates_growth_contribution_margin_and_concentration(self):
        company = MODULE.build_company("TEST", {
            "name": "Test",
            "period": "2026 Q2",
            "comparison_period": "2025 Q2",
            "basis": "可報導分部",
            "unit": "USD m",
            "source_date": "2026-07-01",
            "source_url": "https://www.sec.gov/example",
            "coverage_status": "complete",
            "comparability": "high",
            "items": [
                {"name": "Growth", "current_revenue": 150, "prior_revenue": 100, "current_profit": 30, "prior_profit": 10},
                {"name": "Drag", "current_revenue": 40, "prior_revenue": 50, "current_profit": -4, "prior_profit": 5},
            ],
        })
        growth, drag = company["items"]
        self.assertEqual(company["totals"]["yoy_pct"], 26.7)
        self.assertEqual(growth["growth_contribution_pct"], 125.0)
        self.assertEqual(drag["growth_contribution_pct"], -25.0)
        self.assertEqual(growth["margin_change_pp"], 10.0)
        self.assertEqual(drag["current_margin_pct"], -10.0)
        self.assertEqual(company["assessment"]["status"], "mixed_growth")
        self.assertEqual(company["concentration"]["status"], "high")

    def test_never_reverse_engineers_missing_prior_amount(self):
        company = MODULE.build_company("TEST", {
            "name": "Test",
            "period": "2026 Q2",
            "comparison_period": "2025 Q2",
            "basis": "新平台口徑",
            "unit": "USD bn",
            "source_date": "2026-07-01",
            "source_url": "https://example.com/ir",
            "coverage_status": "complete",
            "comparability": "medium",
            "items": [
                {"name": "A", "current_revenue": 90, "prior_revenue": None, "reported_yoy_pct": 100},
                {"name": "B", "current_revenue": 10, "prior_revenue": None, "reported_yoy_pct": 25},
            ],
        })
        self.assertIsNone(company["totals"]["prior_revenue"])
        self.assertIsNone(company["totals"]["yoy_pct"])
        self.assertIsNone(company["items"][0]["growth_contribution_pct"])
        self.assertEqual(company["items"][0]["yoy_basis"], "company_reported")
        self.assertIsNone(company["driver"])

    def test_share_input_is_explicitly_approximate(self):
        company = MODULE.build_company("TEST", {
            "name": "Test",
            "period": "2026 Q2",
            "comparison_period": "2025 Q2",
            "basis": "平台占比",
            "input_kind": "share_of_total",
            "unit": "TWD bn",
            "current_total_revenue": 200,
            "prior_total_revenue": 100,
            "source_date": "2026-07-01",
            "source_url": "https://example.com/ir",
            "coverage_status": "complete",
            "comparability": "medium",
            "items": [
                {"name": "A", "current_share_pct": 60, "prior_share_pct": 50},
                {"name": "B", "current_share_pct": 40, "prior_share_pct": 50},
            ],
        })
        self.assertTrue(company["approximate"])
        self.assertTrue(all(row["approximate"] for row in company["items"]))
        self.assertEqual(company["items"][0]["current_revenue"], 120.0)
        self.assertEqual(company["items"][0]["share_change_pp"], 10.0)


if __name__ == "__main__":
    unittest.main()
