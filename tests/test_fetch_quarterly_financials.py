import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "quarterly", ROOT / "scripts" / "fetch_quarterly_financials.py"
)
quarterly = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quarterly)


def row(start, end, value, form="10-Q", filed="2026-01-01", frame=None):
    return {
        "start": start, "end": end, "val": value, "form": form,
        "filed": filed, "frame": frame, "priority": 0, "tag": "Example",
        "unit": "USD", "span": quarterly.days_between(start, end),
    }


class QuarterlyFinancialTests(unittest.TestCase):
    def test_q4_is_annual_minus_nine_months(self):
        rows = [
            row("2025-01-01", "2025-09-30", 90),
            row("2025-01-01", "2025-12-31", 130, form="10-K"),
        ]
        result = quarterly.q4_values(rows)
        self.assertEqual(result["2025-12-31"]["val"], 40)
        self.assertTrue(result["2025-12-31"]["derived"])

    def test_cash_flow_prefers_reported_single_quarter_over_ttm(self):
        rows = [
            row("2026-01-01", "2026-03-31", 20, frame="CY2026Q1"),
            row("2026-01-01", "2026-06-30", 50),
            row("2026-04-01", "2026-06-30", 30, frame="CY2026Q2"),
            row("2025-07-01", "2026-06-30", 160),
        ]
        result = quarterly.single_quarter_flow(rows)
        self.assertEqual(result["2026-06-30"]["val"], 30)
        self.assertFalse(result["2026-06-30"].get("derived", False))

    def test_eps_and_shares_are_not_q4_subtracted(self):
        rows = [
            row("2025-01-01", "2025-09-30", 3),
            row("2025-01-01", "2025-12-31", 5, form="10-K"),
        ]
        self.assertEqual(quarterly.q4_values(rows, allow_derivation=False), {})


if __name__ == "__main__":
    unittest.main()
