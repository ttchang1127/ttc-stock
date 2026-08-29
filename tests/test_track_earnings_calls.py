import importlib.util
import pathlib
import tempfile
import unittest
from unittest import mock


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "track_earnings_calls.py"
SPEC = importlib.util.spec_from_file_location("track_earnings_calls", SCRIPT)
tracker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tracker)


def transcript_html():
    paragraphs = [
        "Management Discussion Section with prepared comments for investors and the official quarterly earnings call.",
        "Customer demand and adoption remained strong while our backlog grew during the quarter.",
        "Gross margin reflected higher costs and depreciation expense from infrastructure investments.",
        "We increased capital expenditures and data center capacity to address supply constraints.",
        "For the next quarter, we expect revenue growth under the outlook provided today.",
        "We are confident in the pipeline although visibility remains limited in several markets.",
        "Tariff pressure and supply constraints remain important risks and potential headwinds.",
        "Revenue performance included several products and geographic markets discussed by management.",
        "Operating expenses include research investment and additional infrastructure depreciation.",
        "The company continues to invest while monitoring costs and available manufacturing capacity.",
        "Question and Answer Session",
        "Can you help us understand what is driving demand and how should investors think about capacity?",
        "Management responded that supply planning depends on customer schedules and market conditions.",
    ]
    return ("<html><body>" + "".join(f"<p>{text}</p>" for text in paragraphs) + "</body></html>").encode()


class EarningsCallTrackerTests(unittest.TestCase):
    def test_url_allowlist_requires_exact_https_host(self):
        self.assertTrue(tracker.allowed_url("https://ir.example.com/call.pdf", ["ir.example.com"]))
        self.assertFalse(tracker.allowed_url("http://ir.example.com/call.pdf", ["ir.example.com"]))
        self.assertFalse(tracker.allowed_url("https://ir.example.com.evil.test/call.pdf", ["ir.example.com"]))

    def test_full_transcript_preserves_short_evidence_and_q_and_a(self):
        config = {
            "company_name": "Example Inc.", "period": "2026 Q2", "call_date": "2026-07-01",
            "landing_url": "https://ir.example.com/", "material_url": "https://ir.example.com/call.html",
            "source_type": "full_transcript", "allowed_hosts": ["ir.example.com"],
        }
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            tracker, "download", return_value=(transcript_html(), "text/html")
        ):
            root = pathlib.Path(directory)
            row = tracker.analyze_company("TEST", config, {"filings": []}, root)
            self.assertEqual(row["status"], "analyzed")
            self.assertTrue(row["q_and_a_available"])
            self.assertEqual(set(row["categories"]), set(tracker.CATEGORIES))
            self.assertTrue(row["categories"]["analyst_questions"])
            self.assertTrue(all(
                item["section"] == "prepared"
                for key, evidence in row["categories"].items() if key != "analyst_questions"
                for item in evidence
            ))
            self.assertTrue(all(
                len(item["excerpt"].rstrip("…").split()) <= tracker.MAX_EXCERPT_WORDS
                for evidence in row["categories"].values() for item in evidence
            ))
            self.assertTrue((root / row["card"]).is_file())

    def test_prepared_remarks_never_claims_analyst_questions(self):
        config = {
            "company_name": "Example Inc.", "period": "2026 Q2", "call_date": "2026-07-01",
            "landing_url": "https://ir.example.com/", "material_url": "https://ir.example.com/remarks.html",
            "source_type": "prepared_remarks", "allowed_hosts": ["ir.example.com"],
        }
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            tracker, "download", return_value=(transcript_html(), "text/html")
        ):
            row = tracker.analyze_company("TEST", config, {"filings": []}, pathlib.Path(directory))
            self.assertEqual(row["status"], "analyzed")
            self.assertFalse(row["q_and_a_available"])
            self.assertEqual(row["categories"]["analyst_questions"], [])

    def test_replay_only_removes_stale_text_card(self):
        config = {
            "company_name": "Example Inc.", "period": "2026 Q2", "call_date": "2026-07-01",
            "landing_url": "https://ir.example.com/", "material_url": "https://ir.example.com/replay",
            "source_type": "webcast_replay", "allowed_hosts": ["ir.example.com"],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            stale = tracker.card_path(root, "TEST", config["period"])
            stale.parent.mkdir(parents=True)
            stale.write_text("stale")
            row = tracker.analyze_company("TEST", config, {"filings": []}, root)
            self.assertEqual(row["status"], "replay_only")
            self.assertFalse(stale.exists())

    def test_freshness_flags_source_after_newer_financial_filing(self):
        config = {"call_date": "2026-01-01"}
        company = {"periods": [{"period_end": "2026-06-30", "filing_date": "2026-07-31"}]}
        result = tracker.source_freshness(config, company)
        self.assertEqual(result["status"], "stale")
        self.assertGreater(result["lag_days"], 45)


if __name__ == "__main__":
    unittest.main()
