import copy
import importlib.util
import json
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sync_segment_driver_history.py"
SPEC = importlib.util.spec_from_file_location("sync_segment_driver_history", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SegmentDriverSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.current = json.loads((ROOT / "segment_driver_inputs.json").read_text())
        cls.history = json.loads((ROOT / "segment_driver_history_inputs.json").read_text())
        cls.quarterly = json.loads((ROOT / "quarterly_financials.json").read_text())
        cls.exhibits = json.loads((ROOT / "exhibit_991_analysis.json").read_text())
        cls.config = json.loads((ROOT / "segment_driver_sync_config.json").read_text())

    def build(self, current=None, history=None, quarterly=None, exhibits=None):
        return MODULE.build(
            copy.deepcopy(current or self.current), copy.deepcopy(history or self.history),
            copy.deepcopy(quarterly or self.quarterly), copy.deepcopy(exhibits or self.exhibits),
            copy.deepcopy(self.config),
        )

    def test_baseline_is_current_without_false_pending(self):
        payload, history = self.build()
        self.assertEqual(payload["tracked_count"], 14)
        self.assertEqual(payload["pending_count"], 0)
        self.assertTrue(all(row["status"] == "up_to_date" for row in payload["companies"]))
        self.assertEqual(history, self.history)

    def test_verified_new_quarter_rolls_in_and_keeps_eight(self):
        current = copy.deepcopy(self.current)
        history = copy.deepcopy(self.history)
        quarterly = copy.deepcopy(self.quarterly)
        nvda_current = current["companies"]["NVDA"]
        nvda_current.update({"period": "FY2027 Q3", "source_date": "2026-11-18",
                             "source_url": "https://nvidianews.nvidia.com/news/q3-fy27"})
        nvda_current["items"][0]["current_revenue"] = 99.0
        nvda_current["items"][1]["current_revenue"] = 8.0
        quarterly["companies"]["NVDA"]["periods"].insert(0, {
            "period_end": "2026-10-25", "filing_date": "2026-11-18", "form": "10-Q",
            "accession": "test", "url": "https://www.sec.gov/example", "values": {},
        })
        template = history["companies"]["NVDA"]["observations"][0]
        while len(history["companies"]["NVDA"]["observations"]) < 8:
            clone = copy.deepcopy(template)
            year = 2019 + len(history["companies"]["NVDA"]["observations"])
            clone["period"] = f"old-{year}"
            clone["period_end"] = f"{year}-01-01"
            history["companies"]["NVDA"]["observations"].insert(0, clone)
        history["companies"]["NVDA"]["observations"].sort(key=lambda row: row["period_end"])

        payload, updated = self.build(current=current, history=history, quarterly=quarterly)
        nvda = next(row for row in payload["companies"] if row["ticker"] == "NVDA")
        observations = updated["companies"]["NVDA"]["observations"]
        self.assertEqual(nvda["status"], "auto_synced")
        self.assertEqual(len(observations), 8)
        self.assertEqual(observations[-1]["period_end"], "2026-10-25")
        self.assertEqual(observations[-1]["basis_id"], "compute_platforms")
        self.assertEqual([row["key"] for row in observations[-1]["items"]], ["datacenter", "edge"])
        self.assertEqual(observations[-1]["sync_origin"], "verified_segment_driver_input")

        rerun, unchanged = MODULE.build(current, updated, quarterly, self.exhibits, self.config)
        rerun_nvda = next(row for row in rerun["companies"] if row["ticker"] == "NVDA")
        self.assertEqual(rerun_nvda["status"], "auto_synced")
        self.assertEqual(unchanged, updated)

    def test_basis_change_fails_closed_and_notifies_only_after_baseline(self):
        current = copy.deepcopy(self.current)
        quarterly = copy.deepcopy(self.quarterly)
        current["companies"]["NVDA"].update({
            "period": "FY2027 Q3", "source_date": "2026-11-18", "basis": "全新分部口徑",
        })
        quarterly["companies"]["NVDA"]["periods"].insert(0, {
            "period_end": "2026-10-25", "filing_date": "2026-11-18", "form": "10-Q",
            "accession": "test", "url": "https://www.sec.gov/example", "values": {},
        })
        payload, updated = self.build(current=current, quarterly=quarterly)
        nvda = next(row for row in payload["companies"] if row["ticker"] == "NVDA")
        self.assertEqual(nvda["status"], "pending_review")
        self.assertIn("basis_changed", nvda["reason_codes"])
        self.assertEqual(updated, self.history)
        self.assertEqual(MODULE.new_pending(payload, None), [])
        previous, _ = self.build()
        self.assertEqual([row["ticker"] for row in MODULE.new_pending(payload, previous)], ["NVDA"])

    def test_unapproved_source_host_fails_closed(self):
        current = copy.deepcopy(self.current)
        quarterly = copy.deepcopy(self.quarterly)
        current["companies"]["NVDA"].update({
            "period": "FY2027 Q3", "source_date": "2026-11-18",
            "source_url": "https://example.com/not-an-official-source",
        })
        quarterly["companies"]["NVDA"]["periods"].insert(0, {
            "period_end": "2026-10-25", "filing_date": "2026-11-18", "form": "10-Q",
            "accession": "test", "url": "https://www.sec.gov/example", "values": {},
        })
        payload, updated = self.build(current=current, quarterly=quarterly)
        nvda = next(row for row in payload["companies"] if row["ticker"] == "NVDA")
        self.assertIn("source_host_changed", nvda["reason_codes"])
        self.assertEqual(updated, self.history)

    def test_generated_baseline_matches_repository_files(self):
        payload, history = self.build()
        self.assertEqual(history, self.history)
        self.assertEqual(payload, json.loads((ROOT / "segment_driver_update_candidates.json").read_text()))
        self.assertEqual(
            MODULE.render_markdown(payload),
            (ROOT / "60_SEC_Filing_Radar" / "Segment_Driver_Update_Candidates.md").read_text(),
        )


if __name__ == "__main__":
    unittest.main()
