import copy
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_segment_driver_history.py"
SPEC = importlib.util.spec_from_file_location("build_segment_driver_history", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SegmentDriverHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = json.loads((ROOT / "segment_driver_history_inputs.json").read_text())
        cls.payload = MODULE.build_payload(cls.inputs)

    def test_tracks_four_periods_for_all_14_stocks(self):
        self.assertEqual(self.payload["tracked_count"], 14)
        self.assertEqual(self.payload["period_count"], 56)
        self.assertEqual([row["ticker"] for row in self.payload["companies"]], MODULE.DISPLAY_TICKERS)
        self.assertTrue(all(len(row["history"]) == 4 for row in self.payload["companies"]))

    def test_basis_change_breaks_comparison(self):
        nvda = next(row for row in self.payload["companies"] if row["ticker"] == "NVDA")
        q1 = next(row for row in nvda["history"] if row["period"] == "FY2027 Q1")
        self.assertIsNone(q1["qoq_pct"])
        self.assertIsNone(q1["sequential_driver"])
        basis_break = next(row for row in nvda["transition_events"] if row["type"] == "basis_break")
        self.assertFalse(basis_break["comparable"])
        self.assertEqual(nvda["coverage"]["same_basis_run"], 2)

    def test_share_only_input_is_approximate_and_intel_hhi_is_disabled(self):
        by_ticker = {row["ticker"]: row for row in self.payload["companies"]}
        tsm = by_ticker["TSM"]["history"][-1]
        self.assertTrue(all(item["approximate"] for item in tsm["items"]))
        self.assertEqual(tsm["largest_share_pct"], 66.0)
        self.assertIsNone(by_ticker["INTC"]["history"][-1]["hhi"])

    def test_initial_backfill_and_unchanged_rerun_do_not_notify(self):
        self.assertEqual(MODULE.newest_alerts(self.payload, None), [])
        self.assertEqual(MODULE.newest_alerts(self.payload, self.payload), [])

    def test_only_new_latest_events_notify(self):
        previous = copy.deepcopy(self.payload)
        tsm = next(row for row in previous["companies"] if row["ticker"] == "TSM")
        latest_end = tsm["history"][-1]["period_end"]
        tsm["transition_events"] = [event for event in tsm["transition_events"] if event["to_period_end"] != latest_end]
        alerts = MODULE.newest_alerts(self.payload, previous)
        self.assertEqual({row["ticker"] for row in alerts}, {"TSM"})
        self.assertEqual({row["type"] for row in alerts}, {"concentration_jump", "offsetting_growth"})

    def test_generated_files_are_deterministic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = pathlib.Path(temp_dir)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--input", str(ROOT / "segment_driver_history_inputs.json"),
                 "--output", str(temp / "history.json"), "--markdown", str(temp / "history.md")],
                cwd=ROOT, text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((temp / "history.json").read_text()), json.loads((ROOT / "segment_driver_history.json").read_text()))
            self.assertEqual((temp / "history.md").read_text(), (ROOT / "60_SEC_Filing_Radar" / "Segment_Driver_History.md").read_text())


if __name__ == "__main__":
    unittest.main()
