import importlib.util
import pathlib
import unittest
from datetime import date


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_earnings_verification_cards.py"
SPEC = importlib.util.spec_from_file_location("build_earnings_verification_cards", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def period(period_end, revenue, margin, operating_margin, fcf, shares, filing_date):
    return {
        "period_end": period_end,
        "filing_date": filing_date,
        "form": "10-Q",
        "url": "https://www.sec.gov/example",
        "values": {
            "revenue": revenue,
            "gross_margin": margin,
            "operating_margin": operating_margin,
            "free_cash_flow": fcf,
            "diluted_shares": shares,
        },
    }


class EarningsVerificationCardTests(unittest.TestCase):
    def test_builds_pre_and_post_closed_loop_without_etfs(self):
        inputs = {
            "calendar": {
                "generated_at": "2026-09-06",
                "companies": {
                    ticker: {
                        "name": ticker,
                        "next_earnings_date": "2026-09-10" if ticker == "NVDA" else None,
                        "provider_events": [{
                            "type": "earnings", "date": "2026-09-10",
                            "confidence": "estimated", "source_label": "市場日曆",
                            "source_url": "https://example.com/calendar",
                        }] if ticker == "NVDA" else [],
                    } for ticker in MODULE.DISPLAY_TICKERS
                },
            },
            "quarterly": {
                "generated_at": "2026-09-06",
                "companies": {
                    "NVDA": {
                        "currency": "USD",
                        "periods": [
                            period("2026-07-31", 120, .6, .3, 10, 100, "2026-09-01"),
                            period("2026-04-30", 100, .58, .28, -2, 98, "2026-05-20"),
                            period("2026-01-31", 90, .57, .27, 5, 97, "2026-02-20"),
                            period("2025-10-31", 85, .56, .26, 4, 96, "2025-11-20"),
                            period("2025-07-31", 80, .55, .25, -1, 90, "2025-08-20"),
                        ],
                    }
                },
            },
            "forward": {
                "updated_at": "2026-09-01", "companies": {"NVDA": {
                    "guidance_status": "available", "guidance": [{
                        "period": "Q3", "metric": "營收", "low": 130, "high": 140,
                        "unit": "USD bn", "actual": None,
                        "source_url": "https://www.sec.gov/guidance",
                    }],
                }},
            },
            "guidance_history": {
                "as_of": "2026-09-01", "companies": {"NVDA": {
                    "metric": "營收", "unit": "USD bn", "comparison_basis": "same",
                    "records": [["Q2", "2026-07-31", 110, 115, 120, "2026-05-01", "https://www.sec.gov/old"]],
                }},
            },
            "thesis_status": {
                "updated_at": "2026-09-01", "companies": {"NVDA": {
                    "status": "maintained", "label": "論點維持", "counts": {"supported": 1},
                    "items": [{"id": "growth", "title": "成長", "status": "supported", "label": "支持", "evidence": "營收成長", "invalidation": "營收轉負"}],
                }},
            },
            "holdings": {"holdings": [{"ticker": "NVDA"}, {"ticker": "VGT"}]},
        }
        payload = MODULE.build_payload(date(2026, 9, 6), inputs)
        nvda = next(row for row in payload["companies"] if row["ticker"] == "NVDA")
        self.assertEqual(payload["tracked_count"], 14)
        self.assertEqual(payload["holding_count"], 1)
        self.assertNotIn("VGT", {row["ticker"] for row in payload["companies"]})
        self.assertTrue(nvda["pre_event"]["preparation_due"])
        self.assertTrue(nvda["post_event"]["review_due"])
        self.assertEqual(nvda["post_event"]["completed_guidance"]["record"]["outcome"], "above")
        fcf = next(row for row in nvda["post_event"]["kpis"] if row["metric"] == "free_cash_flow")
        self.assertIsNone(fcf["qoq"])
        self.assertIsNone(fcf["yoy"])

    def test_markdown_explains_windows_and_limits(self):
        payload = {
            "generated_at": "2026-09-06", "preparation_due_count": 0,
            "post_review_due_count": 0, "companies": [],
        }
        markdown = MODULE.render_markdown(payload)
        self.assertIn("財報前 7 天", markdown)
        self.assertIn("財報申報後 14 天", markdown)
        self.assertIn("分析師共識", markdown)
        self.assertIn("ETF 不納入", markdown)


if __name__ == "__main__":
    unittest.main()
