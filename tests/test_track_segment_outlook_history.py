import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "track_segment_outlook_history", ROOT / "scripts" / "track_segment_outlook_history.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def record(**updates):
    row = {
        "id": "TEST-2026Q3-CLOUD-REVENUE",
        "target_period": "2026 Q3", "target_period_end": "2026-09-30",
        "basis_id": "basis-a", "segment_key": "cloud", "segment_name": "Cloud",
        "metric": "revenue", "metric_label": "分部營收", "comparison": "range",
        "low": 100.0, "high": 110.0, "unit": "USD m", "target": "USD 100M～USD 110M",
        "source_date": "2026-07-01", "source_url": "https://example.com/outlook",
        "actual": None, "actual_display": "—", "actual_status": "pending_period",
        "actual_source_date": None, "actual_source_url": None,
        "outcome": "pending", "outcome_label": "等待實績",
        "thesis_title": "雲端維持成長", "thesis_impact": "neutral", "thesis_impact_label": "不改變",
    }
    row.update(updates)
    return row


def company(ticker="TEST", records=None, position="watchlist"):
    records = [record()] if records is None else records
    return {
        "ticker": ticker, "name": ticker, "position": position,
        "coverage_status": "available" if records else "no_comparable_segment_outlook",
        "note": "test", "review_url": "https://example.com", "signal": "pending", "label": "等待",
        "counts": {"records": len(records), "completed": 0, "pending": len(records), "not_comparable": 0, "success": 0, "miss": 0},
        "records": records,
    }


class SegmentOutlookHistoryTests(unittest.TestCase):
    def test_first_snapshot_is_baseline_and_same_snapshot_is_idempotent(self):
        snapshot = {"snapshot_id": "one", "captured_at": "2026-09-07", "source_date": "2026-09-07", "companies": {"TEST": company()}}
        payload, is_new = MODULE.build_history(copy.deepcopy(snapshot), {})
        self.assertTrue(is_new)
        self.assertEqual(payload["notify_count"], 0)
        self.assertEqual(payload["current"]["companies"]["TEST"]["comparison"]["status"], "baseline")
        repeated, is_new = MODULE.build_history(copy.deepcopy(snapshot), payload)
        self.assertFalse(is_new)
        self.assertEqual(repeated, payload)

    def test_new_guidance_and_withdrawal_are_detected(self):
        prior = company(records=[])
        current = company(records=[record()])
        comparison, notice = MODULE.compare_company(current, prior)
        self.assertTrue(comparison["notify"])
        self.assertIn("guidance_added", {row["kind"] for row in notice["changes"]})
        comparison, notice = MODULE.compare_company(prior, current)
        self.assertIn("guidance_withdrawn", {row["kind"] for row in notice["changes"]})
        self.assertTrue(notice["critical"])

    def test_range_raise_and_lower_are_classified(self):
        prior = company(records=[record()])
        raised = company(records=[record(low=105.0, high=115.0, target="USD 105M～USD 115M")])
        _, notice = MODULE.compare_company(raised, prior)
        self.assertEqual(notice["changes"][0]["kind"], "guidance_raised")
        lowered = company(records=[record(low=95.0, high=105.0, target="USD 95M～USD 105M")])
        _, notice = MODULE.compare_company(lowered, prior)
        self.assertEqual(notice["changes"][0]["kind"], "guidance_lowered")
        self.assertTrue(notice["critical"])

    def test_pending_to_met_or_missed_changes_thesis_direction(self):
        prior = company(records=[record()])
        met = company(records=[record(actual=115.0, actual_display="USD 115M", actual_status="segment_history",
                                      outcome="above", outcome_label="高於展望", thesis_impact="support", thesis_impact_label="支持")])
        _, notice = MODULE.compare_company(met, prior)
        change = notice["changes"][0]
        self.assertEqual(change["kind"], "outcome_completed")
        self.assertEqual(change["direction"], "improvement")
        self.assertIn("雲端維持成長", change["thesis_effect"])

        missed = company(records=[record(actual=90.0, actual_display="USD 90M", actual_status="segment_history",
                                         outcome="below", outcome_label="低於展望", thesis_impact="pressure", thesis_impact_label="形成壓力")])
        _, notice = MODULE.compare_company(missed, prior)
        self.assertTrue(notice["critical"])
        self.assertEqual(notice["direction"], "risk")

    def test_basis_break_is_critical_but_same_outcome_numeric_revision_is_quiet(self):
        prior = company(records=[record()])
        broken = company(records=[record(actual_status="basis_mismatch", outcome="not_comparable", outcome_label="口徑不可比")])
        _, notice = MODULE.compare_company(broken, prior)
        self.assertIn("basis_not_comparable", {row["kind"] for row in notice["changes"]})
        self.assertTrue(notice["critical"])

        old_done = company(records=[record(actual=115.0, actual_display="USD 115M", actual_status="segment_history", outcome="above", outcome_label="高於展望")])
        revised_same_bucket = company(records=[record(actual=116.0, actual_display="USD 116M", actual_status="segment_history", outcome="above", outcome_label="高於展望")])
        comparison, notice = MODULE.compare_company(revised_same_bucket, old_done)
        self.assertEqual(comparison["status"], "unchanged")
        self.assertIsNone(notice)

    def test_holding_notifications_are_sorted_first(self):
        old = {
            "HOLD": company("HOLD", records=[]),
            "WATCH": company("WATCH", records=[]),
        }
        current = {
            "WATCH": company("WATCH", records=[record(id="WATCH")]),
            "HOLD": company("HOLD", records=[record(id="HOLD")], position="holding"),
        }
        existing = {"current": {"snapshot_id": "old", "companies": old}, "history": []}
        snapshot = {"snapshot_id": "new", "captured_at": "2026-09-08", "source_date": "2026-09-08", "companies": current}
        payload, _ = MODULE.build_history(snapshot, existing)
        self.assertEqual([row["ticker"] for row in payload["notifications"]], ["HOLD", "WATCH"])

    def test_cli_writes_zero_notifications_on_identical_rerun(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            source = json.loads((ROOT / "segment_outlook_verification.json").read_text())
            (temp / "input.json").write_text(json.dumps(source))
            (temp / "holdings.json").write_text("[]")
            args = [
                "--input", str(temp / "input.json"), "--holdings", str(temp / "holdings.json"),
                "--history", str(temp / "history.json"), "--markdown", str(temp / "history.md"),
                "--github-output", str(temp / "output.txt"), "--checked-at", "2026-09-07",
            ]
            old_argv = sys.argv
            try:
                sys.argv = ["tracker", *args]
                MODULE.main()
                MODULE.main()
            finally:
                sys.argv = old_argv
            self.assertIn("notify_count=0", (temp / "output.txt").read_text())


if __name__ == "__main__":
    unittest.main()
