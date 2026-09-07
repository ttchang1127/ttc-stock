import copy
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_segment_thesis_linkage.py"
SPEC = importlib.util.spec_from_file_location("build_segment_thesis_linkage", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SegmentThesisLinkageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.history = json.loads((ROOT / "segment_driver_history.json").read_text())
        cls.thesis = json.loads((ROOT / "investment_thesis_status.json").read_text())
        cls.updates = json.loads((ROOT / "segment_driver_update_candidates.json").read_text())
        cls.payload = MODULE.build_payload(cls.history, cls.thesis, cls.updates)

    def test_tracks_14_stocks_and_links_only_supported_metrics(self):
        self.assertEqual(self.payload["tracked_count"], 14)
        self.assertEqual(sum(self.payload["counts"].values()), 14)
        self.assertEqual([row["ticker"] for row in self.payload["companies"]], MODULE.DISPLAY_TICKERS)
        for company in self.payload["companies"]:
            self.assertEqual(len(company["linked_theses"]), 3)
            cash = next(row for row in company["linked_theses"] if row["metric"] == "cash_dilution")
            self.assertEqual(cash["impact"], "not_applicable")
            self.assertIn("不能直接驗證", cash["detail"])
            self.assertTrue(company["source_url"].startswith("https://"))

    def test_objective_thresholds_distinguish_support_and_pressure(self):
        by_ticker = {row["ticker"]: row for row in self.payload["companies"]}
        self.assertEqual(by_ticker["NVDA"]["signal"], "support")
        self.assertEqual(by_ticker["ARM"]["signal"], "pressure")
        self.assertTrue(any(row["impact"] == "pressure" for row in by_ticker["ARM"]["linked_theses"]))
        self.assertTrue(any(event["type"] == "qoq_direction_reversal" for event in by_ticker["ARM"]["events"]))

    def test_basis_change_and_pending_update_never_change_thesis(self):
        history = copy.deepcopy(self.history)
        nvda = next(row for row in history["companies"] if row["ticker"] == "NVDA")
        nvda["latest_change"]["comparable"] = False
        nvda["latest_change"]["events"] = [{"id": "basis", "type": "basis_break", "label": "口徑中斷", "detail": "測試"}]
        payload = MODULE.build_payload(history, self.thesis, self.updates)
        result = next(row for row in payload["companies"] if row["ticker"] == "NVDA")
        self.assertEqual(result["signal"], "needs_review")
        self.assertIn("不改變既有論點", result["alignment"])

        updates = copy.deepcopy(self.updates)
        update = next(row for row in updates["companies"] if row["ticker"] == "NVDA")
        update.update({"status": "pending_review", "reasons": ["新口徑"]})
        payload = MODULE.build_payload(self.history, self.thesis, updates)
        result = next(row for row in payload["companies"] if row["ticker"] == "NVDA")
        self.assertTrue(result["pending_review"])
        self.assertEqual(result["score"], 0)

    def test_generated_files_are_deterministic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = pathlib.Path(temp_dir)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--output", str(temp / "linkage.json"),
                 "--markdown", str(temp / "linkage.md")],
                cwd=ROOT, text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((temp / "linkage.json").read_text()),
                             json.loads((ROOT / "segment_thesis_linkage.json").read_text()))
            self.assertEqual((temp / "linkage.md").read_text(),
                             (ROOT / "60_SEC_Filing_Radar" / "Segment_Thesis_Linkage.md").read_text())


if __name__ == "__main__":
    unittest.main()
