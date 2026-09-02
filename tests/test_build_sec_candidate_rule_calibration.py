import importlib.util
import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_sec_candidate_rule_calibration",
    ROOT / "scripts/build_sec_candidate_rule_calibration.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def decision(disposition, reason=None):
    return {
        "rule_key": "form144_proposed_sale",
        "disposition": disposition,
        "rejection_reasons": [reason] if reason else [],
    }


class CandidateRuleCalibrationTests(unittest.TestCase):
    def test_fewer_than_five_samples_never_changes_priority(self):
        reviews = {"updated_at": "2026-09-01T00:00:00+00:00", "batches": [{
            "decisions": [decision("rejected", "proposed_not_completed") for _ in range(4)],
        }]}
        payload = MODULE.build_calibration(reviews)
        rule = payload["rules"]["form144_proposed_sale"]
        self.assertEqual(rule["acceptance_rate"], 0)
        self.assertEqual(rule["sample_status"], "insufficient")
        self.assertEqual(rule["priority_adjustment"], "none")

    def test_five_low_acceptance_samples_only_lower_display_priority(self):
        reviews = {"updated_at": "2026-09-01T00:00:00+00:00", "batches": [{
            "decisions": [decision("accepted")] + [
                decision("rejected", "immaterial_relative_size") for _ in range(4)
            ],
        }]}
        payload = MODULE.build_calibration(reviews)
        rule = payload["rules"]["form144_proposed_sale"]
        self.assertEqual(rule["reviewed_count"], 5)
        self.assertEqual(rule["acceptance_rate"], 0.2)
        self.assertEqual(rule["priority_adjustment"], "lower_priority")
        self.assertIn("不刪除", payload["policy"])

    def test_current_review_history_is_counted_exactly(self):
        reviews = json.loads((ROOT / "sec_daily_candidate_reviews.json").read_text())
        payload = MODULE.build_calibration(reviews)
        self.assertEqual(payload["reviewed_candidate_count"], 5)
        self.assertEqual(payload["accepted_candidate_count"], 1)
        self.assertEqual(payload["rejected_candidate_count"], 4)
        self.assertEqual(len(payload["rules"]), 3)
        self.assertTrue(all(row["priority_adjustment"] == "none" for row in payload["rules"].values()))


if __name__ == "__main__":
    unittest.main()
