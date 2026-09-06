import importlib.util
import json
import pathlib
import tempfile
import unittest
from datetime import date


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_company_event_calendar.py"
SPEC = importlib.util.spec_from_file_location("build_company_event_calendar", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CompanyEventCalendarTests(unittest.TestCase):
    def setUp(self):
        self.holdings = {
            "holdings": [
                {"ticker": "NVDA", "shares": 1, "cost": 1},
                {"ticker": "VGT", "shares": 1, "cost": 1},
            ]
        }

    def test_window_is_inclusive_and_etfs_are_excluded(self):
        provider = {
            "NVDA": {
                "Earnings Date": ["2026-09-03", "2026-10-03", "2026-10-04"],
            },
            "AAPL": {"Dividend Date": "2026-09-10"},
        }
        payload = MODULE.build_calendar(
            date(2026, 9, 3), provider, {}, {"events": []}, self.holdings
        )
        self.assertEqual(payload["window"]["end"], "2026-10-03")
        self.assertEqual([row["date"] for row in payload["events"]],
                         ["2026-09-03", "2026-09-10", "2026-10-03"])
        self.assertEqual(payload["owned_stock_count"], 1)
        self.assertNotIn("VGT", payload["companies"])
        self.assertTrue(all(row["ticker"] != "VGT" for row in payload["events"]))

    def test_official_event_supersedes_same_provider_event(self):
        provider = {"NVDA": {"Dividend Date": "2026-09-10"}}
        official = {"events": [{
            "ticker": "NVDA", "date": "2026-09-10", "type": "dividend_payment",
            "title": "官方股息", "detail": "官方細節", "meaning": "官方意義",
            "source_label": "官方", "source_url": "https://example.com/official",
            "confidence": "official", "announced_at": "2026-09-01",
        }]}
        payload = MODULE.build_calendar(
            date(2026, 9, 3), provider, {}, official, self.holdings
        )
        self.assertEqual(len(payload["events"]), 1)
        self.assertEqual(payload["events"][0]["confidence"], "official")
        self.assertEqual(payload["events"][0]["title"], "官方股息")

    def test_provider_failure_retains_prior_rows_and_marks_stale(self):
        previous = {
            "companies": {
                "NVDA": {
                    "provider_events": [{
                        "ticker": "NVDA", "date": "2026-09-10", "type": "earnings",
                        "title": "預估財報公布日", "detail": "舊資料", "meaning": "需核對",
                        "source_label": "Yahoo Finance 行事曆",
                        "source_url": "https://finance.yahoo.com/quote/NVDA/calendar/",
                        "confidence": "estimated", "announced_at": None,
                    }],
                    "next_earnings_date": "2026-09-10",
                    "last_success_at": "2026-09-02",
                }
            }
        }
        payload = MODULE.build_calendar(
            date(2026, 9, 3), {}, {"NVDA": "timeout"}, {"events": []},
            self.holdings, previous,
        )
        self.assertEqual(payload["companies"]["NVDA"]["source_status"], "stale")
        self.assertEqual(payload["companies"]["NVDA"]["last_success_at"], "2026-09-02")
        self.assertEqual(payload["events"][0]["ticker"], "NVDA")
        self.assertEqual(payload["provider_failures"], {"NVDA": "timeout"})

    def test_markdown_explains_confidence_and_unpredictable_events(self):
        payload = MODULE.build_calendar(
            date(2026, 9, 3), {}, {}, {"events": []}, self.holdings
        )
        markdown = MODULE.render_markdown(payload)
        self.assertIn("官方已確認", markdown)
        self.assertIn("市場預估／市場資料", markdown)
        self.assertIn("Form 4、8-K／6-K、臨時募資與併購", markdown)
        self.assertIn("ETF 不納入", markdown)


if __name__ == "__main__":
    unittest.main()
