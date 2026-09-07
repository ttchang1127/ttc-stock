import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_segment_outlook_verification",
    ROOT / "scripts" / "build_segment_outlook_verification.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class SegmentOutlookVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = json.loads((ROOT / "segment_outlook_inputs.json").read_text())
        cls.history = json.loads((ROOT / "segment_driver_history.json").read_text())
        cls.linkage = json.loads((ROOT / "segment_thesis_linkage.json").read_text())

    def build(self, inputs=None, history=None):
        return MODULE.build_payload(inputs or self.inputs, history or self.history, self.linkage)

    def test_covers_14_stocks_without_using_company_total_guidance(self):
        payload = self.build()
        self.assertEqual(payload["tracked_count"], 14)
        self.assertEqual(payload["counts"]["available_companies"], 2)
        self.assertEqual({row["ticker"] for row in payload["companies"]}, set(MODULE.DISPLAY_TICKERS))
        amazon = next(row for row in payload["companies"] if row["ticker"] == "AMZN")
        self.assertEqual(amazon["coverage_status"], "no_comparable_segment_outlook")
        self.assertEqual(amazon["records"], [])
        self.assertIn("總淨銷售額", amazon["note"])

    def test_completed_and_pending_records_are_distinct_and_traceable(self):
        payload = self.build()
        self.assertEqual(payload["counts"]["completed_records"], 4)
        self.assertEqual(payload["counts"]["pending_records"], 3)
        msft = next(row for row in payload["companies"] if row["ticker"] == "MSFT")
        self.assertEqual([row["outcome"] for row in msft["records"][:3]], ["above"] * 3)
        self.assertEqual([row["outcome"] for row in msft["records"][3:]], ["pending"] * 2)
        self.assertEqual(msft["records"][0]["actual_display"], "USD 37.847B")
        self.assertTrue(all(row["source_url"].startswith("https://") for row in msft["records"]))
        self.assertTrue(all("不重複加分" in row["thesis_note"] for row in msft["records"][:3]))

    def test_basis_mismatch_fails_closed(self):
        history = copy.deepcopy(self.history)
        msft = next(row for row in history["companies"] if row["ticker"] == "MSFT")
        msft["history"][-1]["basis_id"] = "changed_basis"
        payload = self.build(history=history)
        company = next(row for row in payload["companies"] if row["ticker"] == "MSFT")
        self.assertEqual(company["records"][0]["outcome"], "not_comparable")
        self.assertEqual(company["records"][0]["actual"], None)
        self.assertIn("停止比較", company["records"][0]["verification_note"])

    def test_manual_actual_requires_official_result_source(self):
        inputs = copy.deepcopy(self.inputs)
        row = inputs["companies"]["NOK"]["records"][0]
        row.pop("actual_source_url")
        with self.assertRaisesRegex(ValueError, "缺官方來源"):
            self.build(inputs=inputs)

    def test_outlook_published_after_target_period_is_rejected(self):
        inputs = copy.deepcopy(self.inputs)
        inputs["companies"]["MSFT"]["records"][0]["source_date"] = "2026-07-01"
        with self.assertRaisesRegex(ValueError, "後見偏誤"):
            self.build(inputs=inputs)

    def test_generated_files_are_deterministic(self):
        payload = self.build()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.json"
            markdown = Path(tmp) / "out.md"
            output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            markdown.write_text(MODULE.render_markdown(payload))
            self.assertEqual(json.loads(output.read_text()), payload)
            self.assertIn("公司總指引不代替分部指引", markdown.read_text())
            self.assertIn("FY2027 Q1", markdown.read_text())


if __name__ == "__main__":
    unittest.main()
