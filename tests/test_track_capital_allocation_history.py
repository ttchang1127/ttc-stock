import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "track_capital_allocation_history", ROOT / "scripts" / "track_capital_allocation_history.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def company(ticker="TEST", position="watchlist", period="2025-12-31", status="neutral", signal_state="neutral"):
    label = {"support": "資本配置支持股東價值", "pressure": "資本配置形成壓力", "neutral": "資本配置中性／需持續驗證"}[status]
    return {
        "ticker": ticker, "position": position, "latest_period": period,
        "status": status, "label": label, "score": 0,
        "coverage": {"known": 5, "total": 5, "missing": []},
        "signals": [{"id": "fcf", "label": "現金創造", "state": signal_state, "score": 0, "evidence": "測試證據"}],
        "latest": {"fiscal_year_end": period, "currency": "USD", "free_cash_flow": 10, "source": {"url": "https://example.com"}},
        "conclusion": label,
    }


class CapitalAllocationHistoryTests(unittest.TestCase):
    def test_first_run_is_silent_and_same_snapshot_is_idempotent(self):
        snapshot = {"snapshot_id": "one", "captured_at": "2026-09-08", "source_date": "2026-09-08", "companies": {"TEST": company()}}
        payload, is_new = MODULE.build_history(copy.deepcopy(snapshot), {})
        self.assertTrue(is_new)
        self.assertEqual(payload["notify_count"], 0)
        self.assertEqual(payload["current"]["companies"]["TEST"]["comparison"]["status"], "baseline")
        repeated, is_new = MODULE.build_history(copy.deepcopy(snapshot), payload)
        self.assertFalse(is_new)
        self.assertEqual(repeated, payload)

    def test_new_risk_and_improvement_are_classified(self):
        prior = company(status="support", signal_state="support")
        current = company(status="pressure", signal_state="risk")
        comparison, notice = MODULE.compare_company(current, prior)
        self.assertEqual(comparison["direction"], "risk")
        self.assertTrue(notice["critical"])
        recovered = company(status="support", signal_state="support")
        comparison, notice = MODULE.compare_company(recovered, current)
        self.assertEqual(comparison["direction"], "improvement")
        self.assertFalse(notice["critical"])

    def test_new_year_notifies_but_plain_numeric_change_does_not(self):
        prior = company(period="2025-12-31")
        current = company(period="2026-12-31")
        _, notice = MODULE.compare_company(current, prior)
        self.assertIn("new_annual_period", {row["kind"] for row in notice["changes"]})
        numeric = copy.deepcopy(prior)
        numeric["latest"]["free_cash_flow"] = 11
        comparison, notice = MODULE.compare_company(numeric, prior)
        self.assertEqual(comparison["status"], "unchanged")
        self.assertIsNone(notice)

    def test_holding_notifications_sort_first(self):
        previous = {"HOLD": company("HOLD"), "WATCH": company("WATCH")}
        current = {
            "WATCH": company("WATCH", status="pressure", signal_state="risk"),
            "HOLD": company("HOLD", position="holding", status="pressure", signal_state="risk"),
        }
        existing = {"current": {"snapshot_id": "old", "companies": previous}, "history": []}
        snapshot = {"snapshot_id": "new", "captured_at": "2026-09-09", "source_date": "2026-09-09", "companies": current}
        payload, _ = MODULE.build_history(snapshot, existing)
        self.assertEqual([row["ticker"] for row in payload["notifications"]], ["HOLD", "WATCH"])


if __name__ == "__main__":
    unittest.main()
