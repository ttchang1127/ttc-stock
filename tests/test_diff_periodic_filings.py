import importlib.util
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SCRIPT = ROOT / "scripts" / "diff_periodic_filings.py"
SPEC = importlib.util.spec_from_file_location("diff_periodic_filings", SCRIPT)
diffs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diffs)


class PeriodicFilingDiffTests(unittest.TestCase):
    def test_selects_same_form_pair_instead_of_mixing_10k_and_10q(self):
        periods = [
            {"form": "10-K", "filing_date": "2026-08-01", "accession": "k"},
            {"form": "10-Q", "filing_date": "2026-05-01", "accession": "q2"},
            {"form": "10-Q", "filing_date": "2026-02-01", "accession": "q1"},
        ]
        previous, latest = diffs.choose_pair(periods)
        self.assertEqual([previous["accession"], latest["accession"]], ["q1", "q2"])

    def test_extracts_quarterly_risk_and_mda_boundaries(self):
        long_risk = "Customer demand uncertainty may adversely affect our revenue and results. " * 5
        long_mda = "Revenue increased because customer demand and product volume improved. " * 5
        text = "\n".join([
            "Item 2. Management’s Discussion and Analysis of Financial Condition and Results of Operations",
            long_mda,
            "Item 3. Quantitative and Qualitative Disclosures About Market Risk",
            "Item 1A. Risk Factors",
            long_risk,
            "Item 2. Unregistered Sales of Equity Securities and Use of Proceeds",
            "The following table summarizes issuer purchases during the quarter.",
        ])
        specs = diffs.SECTION_SPECS["10-Q"]
        risk = diffs.extract_section(text, specs["risk_factors"][1], specs["risk_factors"][2])
        mda = diffs.extract_section(text, specs["management_discussion"][1], specs["management_discussion"][2])
        self.assertIn("Customer demand uncertainty", risk)
        self.assertIn("Revenue increased", mda)
        self.assertNotIn("Item 3", mda)

    def test_comparison_keeps_actual_excerpts_and_literal_language_signal(self):
        previous = (
            "Customer demand may vary and could adversely affect revenue, margins, and our "
            "financial condition over future reporting periods due to market volatility."
        )
        latest = (
            "Customer demand uncertainty has increased and could adversely affect revenue, "
            "margins, liquidity, and our financial condition over future reporting periods due "
            "to market volatility and export restrictions."
        )
        result = diffs.compare(previous, latest)
        self.assertEqual(result["modified_count"], 1)
        row = result["modified"][0]
        self.assertIn("Customer demand", row["previous_excerpt"])
        self.assertIn("has increased", row["latest_excerpt"])
        self.assertEqual(row["language_signal"]["code"], "possible_escalation")
        self.assertIn("流動性／債務", row["topics"])


if __name__ == "__main__":
    unittest.main()
