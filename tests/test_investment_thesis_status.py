import copy
import importlib.util
import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "track_investment_thesis_status.py"
SPEC = importlib.util.spec_from_file_location("track_investment_thesis_status", SCRIPT)
tracker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tracker)


class InvestmentThesisStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / "investment_thesis_tracking.json").read_text())
        cls.quarterly = json.loads((ROOT / "quarterly_financials.json").read_text())

    def test_baseline_covers_all_companies_without_notification(self):
        output, batch = tracker.build_status(
            self.config, self.quarterly, {}, "2026-08-27T04:00:00+00:00"
        )
        self.assertTrue(batch["baseline"])
        self.assertEqual(batch["changed_count"], 0)
        self.assertEqual(set(output["companies"]), set(self.config["companies"]))
        self.assertTrue(all(len(row["items"]) == 3 for row in output["companies"].values()))
        self.assertTrue(all(len(row["history"]) == 4 for row in output["companies"].values()))

    def test_numeric_refresh_without_status_change_does_not_notify(self):
        previous, _ = tracker.build_status(
            self.config, self.quarterly, {}, "2026-08-27T04:00:00+00:00"
        )
        refreshed = copy.deepcopy(self.quarterly)
        revenue = refreshed["companies"]["NVDA"]["periods"][0]["values"]["revenue"]
        if isinstance(revenue, dict):
            revenue["value"] *= 1.001
        else:
            refreshed["companies"]["NVDA"]["periods"][0]["values"]["revenue"] *= 1.001
        output, batch = tracker.build_status(
            self.config, refreshed, previous, "2026-08-28T04:00:00+00:00"
        )
        self.assertFalse(batch["baseline"])
        self.assertEqual(batch["changed_count"], 0)
        self.assertNotEqual(
            output["companies"]["NVDA"]["fingerprint"],
            previous["companies"]["NVDA"]["fingerprint"],
        )

    def test_item_and_overall_change_records_exact_evidence(self):
        previous, _ = tracker.build_status(
            self.config, self.quarterly, {}, "2026-08-27T04:00:00+00:00"
        )
        changed = copy.deepcopy(self.quarterly)
        revenue = changed["companies"]["NVDA"]["periods"][0]["values"]["revenue"]
        if isinstance(revenue, dict):
            revenue["value"] = 1
        else:
            changed["companies"]["NVDA"]["periods"][0]["values"]["revenue"] = 1
        output, batch = tracker.build_status(
            self.config, changed, previous, "2026-08-28T04:00:00+00:00"
        )
        nvda = next(row for row in batch["changes"] if row["ticker"] == "NVDA")
        self.assertEqual(nvda["before_label"], "論點維持")
        self.assertEqual(nvda["after_label"], "部分失效")
        self.assertEqual(nvda["item_changes"][0]["before_label"], "支持")
        self.assertEqual(nvda["item_changes"][0]["after_label"], "失效")
        self.assertIn("YoY", nvda["item_changes"][0]["evidence"])
        self.assertTrue(nvda["source_url"].startswith("https://www.sec.gov/"))
        self.assertTrue(output["companies"]["NVDA"]["statusChanged"])

    def test_alert_contains_transition_evidence_and_source(self):
        batch = {
            "baseline": False, "changed_count": 1,
            "changes": [{
                "ticker": "TEST", "before_label": "論點維持", "after_label": "部分失效",
                "item_changes": [{
                    "title": "營收成長", "before_label": "支持", "after_label": "失效",
                    "evidence": "營收 YoY -5.0%", "after_status": "invalidated",
                    "invalidation": "營收 YoY ≤ 0%",
                }],
                "source_url": "https://www.sec.gov/example",
            }],
        }
        alert = tracker.render_alert(batch)
        self.assertIn("論點維持 → 部分失效", alert)
        self.assertIn("支持 → 失效", alert)
        self.assertIn("營收 YoY -5.0%", alert)
        self.assertIn("門檻：營收 YoY ≤ 0%", alert)
        self.assertIn("https://www.sec.gov/example", alert)


if __name__ == "__main__":
    unittest.main()
