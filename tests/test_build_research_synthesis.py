import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "build_research_synthesis", ROOT / "scripts" / "build_research_synthesis.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class ResearchSynthesisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = {
            "quarterly": json.loads((ROOT / "quarterly_financials.json").read_text()),
            "valuation": json.loads((ROOT / "valuation.json").read_text()),
            "earnings": json.loads((ROOT / "earnings_verification_cards.json").read_text()),
            "thesis_tracking": json.loads((ROOT / "investment_thesis_tracking.json").read_text()),
            "thesis_status": json.loads((ROOT / "investment_thesis_status.json").read_text()),
            "calendar": json.loads((ROOT / "company_event_calendar.json").read_text()),
            "rotation": json.loads((ROOT / "market_rotation.json").read_text()),
            "universe": json.loads((ROOT / "market_rotation_universe.json").read_text()),
            "groups": json.loads((ROOT / "research_peer_groups.json").read_text()),
        }
        cls.payload = MODULE.build_payload(copy.deepcopy(cls.inputs))

    def test_covers_exactly_fourteen_stocks(self):
        self.assertEqual(self.payload["tracked_count"], 14)
        self.assertEqual(set(self.payload["companies"]), set(MODULE.DISPLAY_TICKERS))
        self.assertNotIn("VGT", self.payload["companies"])

    def test_evidence_claims_keep_source_and_derivation(self):
        for ticker, company in self.payload["companies"].items():
            evidence = company["evidence_ledger"]
            for claim in evidence["claims"]:
                if claim["value"] is None:
                    continue
                self.assertTrue(claim["source_url"].startswith("https://"), ticker)
                self.assertTrue(claim["source_date"], ticker)
                self.assertTrue(claim["source_locator"], f"{ticker}/{claim['metric']}")
            self.assertEqual(
                evidence["coverage"]["sourced"],
                sum(claim["value"] is not None and bool(claim["source_url"]) for claim in evidence["claims"]),
            )

    def test_earnings_delta_does_not_invent_consensus_or_internal_estimate(self):
        for company in self.payload["companies"].values():
            delta = company["earnings_delta"]
            self.assertEqual(delta["consensus"]["status"], "not_collected")
            self.assertEqual(delta["prior_internal_estimate"]["status"], "not_collected")
        nvda = self.payload["companies"]["NVDA"]["earnings_delta"]
        self.assertTrue(nvda["metrics"])
        self.assertEqual(nvda["official_guidance_comparison"]["outcome"], "above")

    def test_thesis_scorecard_preserves_expectation_evidence_and_invalidation(self):
        nvda = self.payload["companies"]["NVDA"]["thesis_scorecard"]
        self.assertEqual(len(nvda["items"]), 3)
        for item in nvda["items"]:
            self.assertTrue(item["original_expectation"])
            self.assertTrue(item["current_evidence"])
            self.assertTrue(item["invalidation"])
            self.assertTrue(item["trend"])
        self.assertEqual(nvda["next_validation"]["type"], "earnings")

    def test_peer_percentiles_require_an_explicit_comparison_group(self):
        nvda = self.payload["companies"]["NVDA"]["peer_comparison"]
        self.assertEqual(nvda["status"], "available")
        self.assertGreaterEqual(len(nvda["members"]), 3)
        for metric in nvda["metrics"]:
            if metric["favorable_percentile"] is not None:
                self.assertGreaterEqual(metric["favorable_percentile"], 0)
                self.assertLessEqual(metric["favorable_percentile"], 100)
        for ticker in ("ONDS", "TSLA"):
            self.assertEqual(self.payload["companies"][ticker]["peer_comparison"]["status"], "insufficient")

    def test_rotation_bridge_matches_all_eleven_sectors(self):
        bridge = self.payload["market_rotation_bridge"]
        self.assertEqual(bridge["as_of"], self.inputs["rotation"]["as_of"])
        self.assertEqual(len(bridge["sectors"]), 11)
        self.assertEqual(
            {row["sector_key"] for row in bridge["sectors"]},
            {row["key"] for row in self.inputs["rotation"]["sectors"]},
        )

    def test_generated_output_and_pages_are_connected(self):
        expected = json.loads((ROOT / "research_synthesis.json").read_text())
        self.assertEqual(self.payload, expected)
        dashboard = (ROOT / "dashboard.html").read_text()
        rotation = (ROOT / "market_rotation.html").read_text()
        self.assertIn("research_synthesis.json", dashboard)
        self.assertIn("renderSecResearchSynthesis", dashboard)
        self.assertIn("safeResearchUrl", dashboard)
        self.assertIn("investor.tsmc.com", dashboard)
        self.assertIn("研究證據、財報差異與同業比較", dashboard)
        self.assertIn("renderResearchBridge", rotation)
        self.assertIn("輪動 → 基本面驗證橋接", rotation)
        for workflow in ("update-prices.yml", "sec-filing-alerts.yml"):
            text = (ROOT / ".github" / "workflows" / workflow).read_text()
            self.assertIn("build_research_synthesis.py", text)
            self.assertIn("research_synthesis.json", text)


if __name__ == "__main__":
    unittest.main()
