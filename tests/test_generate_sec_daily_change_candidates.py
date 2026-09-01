import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "generate_sec_daily_change_candidates",
    ROOT / "scripts/generate_sec_daily_change_candidates.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DailyChangeCandidateTests(unittest.TestCase):
    def setUp(self):
        self.editorial = {
            "reviewed_at": "2026-08-30T19:35:00+08:00",
            "window_end": "2026-08-30",
            "portfolio_order": ["ARM", "COHR"],
            "companies": [
                {"ticker": "ARM", "coverage": {
                    "quarterly_key": "old-quarter", "thesis_fingerprint": "old-thesis",
                    "ownership_accession": None, "enforcement_keys": [],
                }},
                {"ticker": "COHR", "coverage": {
                    "quarterly_key": "", "thesis_fingerprint": "same-thesis",
                    "ownership_accession": None, "enforcement_keys": [],
                }},
            ],
        }

    def test_detected_time_after_review_catches_same_filing_date(self):
        event = {
            "filing_date": "2026-08-30",
            "detected_at": "2026-08-31T01:00:00+00:00",
        }
        self.assertTrue(MODULE.is_after_review(event, self.editorial))

    def test_planned_form4_sale_and_form144_are_low_strength_risks(self):
        alerts = {"events": [
            {"ticker": "ARM", "form": "4", "accession": "form4", "filing_date": "2026-08-31",
             "detected_at": "2026-09-01T01:00:00+00:00", "url": "https://www.sec.gov/form4"},
            {"ticker": "COHR", "form": "144", "accession": "form144", "filing_date": "2026-08-31",
             "detected_at": "2026-09-01T01:00:00+00:00", "url": "https://www.sec.gov/form144"},
        ]}
        details = {"form4": {"form4": {"transactions": [
            {"code": "S", "value": 2_500_000, "rule_10b5_1": True},
        ]}}}
        advanced = {"insiders": [{"event": {"accession": "form144"}, "form144": {
            "planned_shares": 1000, "planned_value_usd": 250000, "reporter": "Officer A",
        }}]}
        rows, used = MODULE.filing_candidates(alerts, details, advanced, self.editorial)
        self.assertEqual({row["type"] for row in rows}, {"risk"})
        self.assertTrue(all(row["confidence"] == "low" for row in rows))
        self.assertIn("form4", used)
        self.assertIn("form144", used)
        form144 = next(row for row in rows if "Form 144" in row["headline"])
        self.assertIn("不等於已成交", " ".join(form144["evidence"]))

    def test_quarterly_and_thesis_fingerprint_changes_create_review_candidates(self):
        quarterly = {"generated_at": "2026-09-01T00:00:00+00:00", "companies": {"ARM": {
            "periods": [{
                "accession": "new-quarter", "period_end": "2026-06-30", "filing_date": "2026-08-31",
                "form": "10-Q", "url": "https://www.sec.gov/quarter",
                "values": {"revenue": 100, "gross_margin": 0.50, "free_cash_flow": 10, "diluted_shares": 100},
            }] + [{}, {}, {}] + [{"values": {"revenue": 80, "diluted_shares": 90}}],
        }}}
        quarter_rows = MODULE.quarterly_candidates(quarterly, self.editorial, set())
        self.assertEqual(len(quarter_rows), 1)
        self.assertEqual(quarter_rows[0]["type"], "conclusion")
        self.assertTrue(any("營收 YoY +25.0%" in text for text in quarter_rows[0]["evidence"]))

        thesis = {"updated_at": "2026-09-01T02:00:00+00:00", "change_log": [{
            "ticker": "ARM", "detected_at": "2026-09-01T02:00:00+00:00",
            "before_status": "maintained", "after_status": "needs-validation",
            "before_label": "成立", "after_label": "需驗證", "item_changes": [],
        }], "companies": {"ARM": {
            "fingerprint": "new-thesis", "label": "需驗證", "period": "2026-06-30",
            "url": "https://www.sec.gov/quarter",
        }}}
        thesis_rows = MODULE.thesis_candidates(thesis, self.editorial)
        self.assertEqual(thesis_rows[0]["type"], "risk")
        self.assertEqual(thesis_rows[0]["confidence"], "high")

    def test_payload_is_deterministic_and_marked_as_draft(self):
        empty = {"updated_at": "2026-09-01T00:00:00+00:00"}
        quarterly = {"generated_at": "2026-09-01T00:00:00+00:00", "companies": {}}
        thesis = {"updated_at": "2026-09-01T00:00:00+00:00", "companies": {}, "change_log": []}
        first = MODULE.build_payload({**empty, "events": []}, {}, {**empty, "insiders": []},
                                     quarterly, thesis, self.editorial)
        second = MODULE.build_payload({**empty, "events": []}, {}, {**empty, "insiders": []},
                                      quarterly, thesis, self.editorial)
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "no_new_candidates")
        markdown = MODULE.render_markdown(first)
        self.assertIn("待 AI 覆核候選", markdown)
        self.assertIn("不是最終判讀", markdown)


if __name__ == "__main__":
    unittest.main()
