import importlib.util
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "track_earnings_verification_history.py"
SPEC = importlib.util.spec_from_file_location("track_earnings_verification_history", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def cards(phase="scheduled_later", period="2026-06-30", state="stable", thesis="maintained",
          days_until=40, days_since=40, generated_at="2026-09-06"):
    return {
        "generated_at": generated_at,
        "companies": [{
            "ticker": "NVDA", "position": "holding", "phase": phase,
            "phase_label": MODULE.PHASE_LABELS[phase],
            "next_earnings": {
                "date": "2026-10-01", "days_until": days_until,
                "confidence": "estimated", "source_label": "市場日曆",
                "source_url": "https://example.com/calendar", "source_status": "fresh",
            },
            "pre_event": {
                "guidance": {"status": "available", "rows": [{
                    "period": "Q3", "metric": "營收", "low": 10, "high": 12,
                    "unit": "USD bn", "source_date": "2026-08-20",
                    "source_url": "https://www.sec.gov/guidance",
                }]},
                "checkpoints": [{"topic": "營收", "question": "是否達標？", "why": "驗證成長"}],
            },
            "post_event": {
                "latest_result": {
                    "period_end": period, "filing_date": "2026-08-20",
                    "days_since_filing": days_since, "form": "10-Q",
                    "accession": f"acc-{period}", "source_url": "https://www.sec.gov/result",
                    "currency": "USD",
                },
                "kpis": [{
                    "metric": "revenue", "label": "營收", "display": "amount", "value": 10,
                    "qoq": 1, "yoy": -12 if state == "risk" else 5,
                    "state": state, "interpretation": "營收年減" if state == "risk" else "營收穩定",
                }],
                "completed_guidance": {"record": {
                    "period": "Q2", "metric": "營收", "actual": 10,
                    "outcome": "within", "outcome_label": "落在區間",
                }},
                "thesis": {
                    "status": thesis, "label": "部分失效" if thesis == "partial-invalidated" else "論點維持",
                    "items": [{
                        "id": "growth", "title": "成長", "status": "invalidated" if thesis == "partial-invalidated" else "supported",
                        "label": "失效" if thesis == "partial-invalidated" else "支持",
                        "evidence": "季度證據", "invalidation": "營收年減",
                    }],
                },
            },
        }],
    }


class EarningsVerificationHistoryTests(unittest.TestCase):
    def test_first_run_is_baseline_and_countdowns_do_not_change_fingerprint(self):
        first = MODULE.build_snapshot(cards(days_until=40, days_since=20), "2026-09-06T12:00:00+08:00")
        later = MODULE.build_snapshot(cards(days_until=39, days_since=21), "2026-09-07T12:00:00+08:00")
        self.assertEqual(first["snapshot_id"], later["snapshot_id"])
        payload, changed = MODULE.build_history(first, {})
        self.assertTrue(changed)
        self.assertEqual(payload["notify_count"], 0)
        self.assertIsNone(payload["previous_snapshot_id"])
        self.assertEqual(payload["current"]["companies"]["NVDA"]["comparison"]["status"], "baseline")
        same, changed = MODULE.build_history(later, payload)
        self.assertFalse(changed)
        self.assertEqual(same, payload)

    def test_same_semantics_refreshes_source_date_without_new_history_or_notification(self):
        first = MODULE.build_snapshot(cards(), "2026-09-06T00:00:00+08:00")
        payload, _ = MODULE.build_history(first, {})
        later = MODULE.build_snapshot(
            cards(generated_at="2026-09-08"), "2026-09-08T00:00:00+08:00",
        )

        refreshed, changed = MODULE.build_history(later, payload)

        self.assertTrue(changed)
        self.assertEqual(refreshed["current_snapshot_id"], payload["current_snapshot_id"])
        self.assertEqual(len(refreshed["history"]), len(payload["history"]))
        self.assertEqual(refreshed["current"]["source_date"], "2026-09-08")
        self.assertEqual(refreshed["updated_at"], "2026-09-08T00:00:00+08:00")
        self.assertEqual(refreshed["notify_count"], 0)
        self.assertEqual(refreshed["notifications"], [])

    def test_freezes_pre_card_then_closes_cycle_on_new_result(self):
        baseline = MODULE.build_snapshot(cards(), "2026-09-01T12:00:00+08:00")
        history, _ = MODULE.build_history(baseline, {})
        pre = MODULE.build_snapshot(cards(phase="preparation_due", days_until=6), "2026-09-25T12:00:00+08:00")
        history, changed = MODULE.build_history(pre, history)
        self.assertTrue(changed)
        self.assertEqual(history["notify_count"], 1)
        self.assertIn("進入財報前 7 天準備期", history["notifications"][0]["reasons"][0])
        self.assertEqual(history["cycles"][0]["status"], "waiting_result")
        self.assertEqual(history["cycles"][0]["pre"]["card"]["phase"], "preparation_due")

        post_cards = cards(phase="post_review_due", period="2026-09-30", state="risk",
                           thesis="partial-invalidated", days_until=90, days_since=2)
        post = MODULE.build_snapshot(post_cards, "2026-10-03T12:00:00+08:00")
        history, changed = MODULE.build_history(post, history)
        self.assertTrue(changed)
        self.assertEqual(history["cycles"][0]["status"], "completed")
        self.assertEqual(history["cycles"][0]["post"]["latest_result"]["period_end"], "2026-09-30")
        reasons = history["notifications"][0]["reasons"]
        self.assertTrue(any("取得新季度" in reason for reason in reasons))
        self.assertTrue(any("客觀結論" in reason for reason in reasons))
        self.assertTrue(history["notifications"][0]["critical"])
        self.assertEqual(history["critical_count"], 1)
        self.assertNotIn("companies", history["history"][0])

    def test_alert_is_only_written_for_real_notification(self):
        baseline = MODULE.build_snapshot(cards(), "2026-09-01T12:00:00+08:00")
        history, _ = MODULE.build_history(baseline, {})
        with tempfile.TemporaryDirectory() as temp_dir:
            path = pathlib.Path(temp_dir) / "alert.md"
            MODULE.append_alert(path, history)
            self.assertFalse(path.exists())
            changed = MODULE.build_snapshot(cards(phase="preparation_due"), "2026-09-25T12:00:00+08:00")
            history, _ = MODULE.build_history(changed, history)
            MODULE.append_alert(path, history)
            self.assertIn("財報驗證差異", path.read_text())


if __name__ == "__main__":
    unittest.main()
