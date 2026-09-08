import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "build_capital_allocation_cards", ROOT / "scripts" / "build_capital_allocation_cards.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class CapitalAllocationCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.financials = json.loads((ROOT / "financials.json").read_text())
        cls.holdings = json.loads((ROOT / "portfolio_holdings.json").read_text())
        cls.payload = MODULE.build_payload(cls.financials, cls.holdings)

    def test_covers_14_stocks_without_etfs_and_prioritises_holdings(self):
        tickers = {row["ticker"] for row in self.payload["companies"]}
        self.assertEqual(len(tickers), 14)
        self.assertNotIn("VGT", tickers)
        self.assertNotIn("VOO", tickers)
        nok = next(row for row in self.payload["companies"] if row["ticker"] == "NOK")
        self.assertEqual(nok["position"], "holding")
        self.assertEqual(nok["currency"], "EUR")

    def test_fcf_and_shareholder_returns_reconcile(self):
        nvda = next(row for row in self.payload["companies"] if row["ticker"] == "NVDA")
        latest = nvda["latest"]
        self.assertEqual(latest["free_cash_flow"], latest["operating_cash_flow"] - latest["capex"])
        self.assertEqual(latest["shareholder_returns"], latest["buybacks"] + latest["dividends_paid"])
        self.assertAlmostEqual(latest["payout_to_fcf"], latest["shareholder_returns"] / latest["free_cash_flow"])

    def test_missing_payout_component_is_not_assumed_zero(self):
        amazon = next(row for row in self.payload["companies"] if row["ticker"] == "AMZN")
        self.assertIsNone(amazon["latest"]["dividends_paid"])
        self.assertIsNone(amazon["latest"]["shareholder_returns"])
        payout = next(row for row in amazon["signals"] if row["id"] == "payout")
        self.assertEqual(payout["state"], "unavailable")

    def test_share_scaling_anomaly_fails_closed(self):
        ondas = next(row for row in self.payload["companies"] if row["ticker"] == "ONDS")
        self.assertFalse(ondas["latest"]["share_comparable"])
        self.assertIsNone(ondas["latest"]["share_change"])
        self.assertIn("XBRL 縮放", ondas["latest"]["share_note"])

    def test_debt_uses_shared_non_overlapping_definition(self):
        nvda_financial = self.financials["companies"]["NVDA"]["periods"][0]
        expected, _, _ = MODULE.total_debt(nvda_financial)
        nvda = next(row for row in self.payload["companies"] if row["ticker"] == "NVDA")
        self.assertEqual(nvda["latest"]["total_debt"], expected)

    def test_generated_files_are_deterministic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            output, markdown = temp / "cards.json", temp / "cards.md"
            payload = MODULE.build_payload(copy.deepcopy(self.financials), copy.deepcopy(self.holdings))
            output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            markdown.write_text(MODULE.render_markdown(payload))
            self.assertEqual(json.loads(output.read_text()), json.loads((ROOT / "capital_allocation_cards.json").read_text()))
            self.assertEqual(markdown.read_text(), (ROOT / "60_SEC_Filing_Radar/Capital_Allocation_Cards.md").read_text())


if __name__ == "__main__":
    unittest.main()
