import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_sec_position_impact_history",
    ROOT / "scripts/build_sec_position_impact_history.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def sample_inputs(price=100, tone="caution"):
    holdings = {"holdings": [
        {"ticker": "ARM", "shares": 10, "cost": 100},
        {"ticker": "VOO", "shares": 10, "cost": 100},
    ]}
    prices = {
        "generated_at": "2026-09-02T23:00:00+00:00",
        "series": {
            "ARM": {"dates": ["2026-09-02"], "closes": [price]},
            "VOO": {"dates": ["2026-09-02"], "closes": [100]},
        },
    }
    alerts = {"updated_at": "2026-09-02T08:00:00+00:00", "events": []}
    candidates = {"generated_at": "2026-09-02T08:00:00+00:00", "candidates": []}
    editorial = {
        "reviewed_at": "2026-09-02T12:00:00+08:00",
        "comparison": {"changes": []},
        "companies": [{"ticker": "ARM", "tone": tone, "status": tone}],
    }
    thesis = {"updated_at": "2026-09-02T08:00:00+00:00", "companies": {"ARM": {"counts": {"invalidated": 0}}}}
    advanced = {"ownership_timeline": [], "enforcement": []}
    quarterly = {"companies": {"ARM": {"periods": []}}}
    return holdings, prices, alerts, candidates, editorial, thesis, advanced, quarterly


class PositionImpactHistoryTests(unittest.TestCase):
    def snapshot(self, price=100, tone="caution"):
        return MODULE.build_snapshot(*sample_inputs(price, tone))

    def test_first_snapshot_is_baseline_without_notification(self):
        payload, is_new = MODULE.build_history(self.snapshot(), None)
        self.assertTrue(is_new)
        self.assertEqual(payload["notify_count"], 0)
        self.assertIsNone(payload["previous_snapshot_id"])
        self.assertEqual(payload["current"]["rows"][0]["comparison"]["status"], "baseline")

    def test_small_price_move_does_not_notify(self):
        first, _ = MODULE.build_history(self.snapshot(100), None)
        second, _ = MODULE.build_history(self.snapshot(101), first)
        row = second["current"]["rows"][0]
        self.assertEqual(row["comparison"]["score_delta"], 0)
        self.assertFalse(row["comparison"]["notify"])
        self.assertEqual(second["notify_count"], 0)

    def test_drawdown_threshold_crossing_notifies_even_below_ten_points(self):
        first, _ = MODULE.build_history(self.snapshot(95), None)
        second, _ = MODULE.build_history(self.snapshot(89), first)
        row = second["current"]["rows"][0]
        self.assertTrue(row["comparison"]["notify"])
        self.assertTrue(any("-10%" in reason for reason in row["comparison"]["reasons"]))
        self.assertEqual(second["notify_count"], 1)

    def test_sec_signal_change_notifies_and_is_idempotent(self):
        first, _ = MODULE.build_history(self.snapshot(100, "caution"), None)
        second, is_new = MODULE.build_history(self.snapshot(100, "risk"), first)
        self.assertTrue(is_new)
        self.assertEqual(second["notify_count"], 1)
        row = second["current"]["rows"][0]
        self.assertIn("SEC 訊號 18 → 32", row["comparison"]["reasons"])
        same, repeated = MODULE.build_history(self.snapshot(100, "risk"), second)
        self.assertFalse(repeated)
        self.assertEqual(same, second)


if __name__ == "__main__":
    unittest.main()
