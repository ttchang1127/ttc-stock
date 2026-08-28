import importlib.util
import pathlib
import tempfile
import unittest
from unittest import mock

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "ingest_periodic_filings.py"
SPEC = importlib.util.spec_from_file_location("ingest_periodic_filings", SCRIPT)
ingest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ingest)


def paragraph(label, count):
    return "\n".join(f"{label} evidence sentence number {index} with filing detail." for index in range(count))


def valid_10q_text():
    return "\n".join([
        "PART I",
        "Item 1. Financial Statements",
        paragraph("financial statement", 90),
        "Item 2. Management's Discussion and Analysis of Financial Condition and Results of Operations",
        paragraph("management discussion", 55),
        "Item 3. Quantitative and Qualitative Disclosures About Market Risk",
        paragraph("market risk", 20),
        "Item 4. Controls and Procedures",
        paragraph("controls conclusion", 15),
        "PART II",
        "Item 1. Legal Proceedings",
        paragraph("legal proceedings", 20),
        "Item 1A. Risk Factors",
        paragraph("risk factor", 8),
        "Item 2. Unregistered Sales of Equity Securities and Use of Proceeds",
        paragraph("other information", 20),
    ])


def event(form="10-Q", items=None):
    return {
        "ticker": "TEST", "cik": "0000000001", "form": form,
        "filing_date": "2026-08-20", "report_date": "2026-06-30",
        "accepted_at": "2026-08-20T20:00:00Z",
        "accession": "0000000001-26-000123",
        "url": "https://www.sec.gov/Archives/test.htm",
        "index_url": "https://www.sec.gov/Archives/test-index.html",
        "items": items or [], "items_summary": "測試 Item",
    }


class PeriodicFilingIngestTests(unittest.TestCase):
    def test_10q_extracts_three_required_sections(self):
        sections, errors = ingest.extract_10q_sections(valid_10q_text())
        self.assertEqual(errors, [])
        self.assertEqual(set(sections), {
            "PartI_Item2_MD_and_A", "PartI_Item4_Controls", "PartII_Item1A_Risk_Factors",
        })
        self.assertTrue(sections["PartI_Item2_MD_and_A"].startswith("Item 2."))
        self.assertNotIn("Item 3.", sections["PartI_Item2_MD_and_A"])

    def test_10q_missing_required_boundary_fails_closed(self):
        source = valid_10q_text().replace("Item 1A. Risk Factors", "Risk discussion")
        sections, errors = ingest.extract_10q_sections(source)
        self.assertEqual(sections, {})
        self.assertIn("Part I／Part II", errors[0])

    def test_10q_ignores_multiline_table_of_contents_items(self):
        contents = "\n".join([
            "PART I - FINANCIAL INFORMATION",
            "Item 2.",
            "Management Discussion and Analysis",
            "54",
            "Item 4.",
            "Controls and Procedures",
            "62",
            "PART II - OTHER INFORMATION",
            "63",
        ])
        source = contents + "\n" + valid_10q_text().replace("PART I\n", "", 1)
        sections, errors = ingest.extract_10q_sections(source)
        self.assertEqual(errors, [])
        self.assertGreater(len(sections["PartI_Item4_Controls"]), 250)
        self.assertNotIn("PART II", sections["PartI_Item4_Controls"])
        self.assertNotIn("\n62\n", sections["PartI_Item4_Controls"])

    def test_8k_uses_sec_item_sequence_and_signature_boundary(self):
        source = "\n".join([
            "Item 2.02 Results of Operations and Financial Condition",
            paragraph("earnings release", 4),
            "Item 9.01 Financial Statements and Exhibits",
            "4.1",
            paragraph("exhibit detail", 4),
            "SIGNATURES",
            "Authorized signature",
        ])
        sections, errors = ingest.extract_8k_sections(source, ["2.02", "9.01"])
        self.assertEqual(errors, [])
        self.assertEqual(set(sections), {"Item_2_02", "Item_9_01"})
        self.assertNotIn("SIGNATURES", sections["Item_9_01"])

    def test_8k_missing_reported_item_fails_closed(self):
        source = "Item 2.02 Results of Operations\n" + paragraph("results", 8)
        sections, errors = ingest.extract_8k_sections(source, ["2.02", "9.01"])
        self.assertEqual(sections, {})
        self.assertIn("Item 9.01", errors[0])

    def test_ingest_does_not_write_markdown_when_10q_split_fails(self):
        bad_html = "<html><body><p>PART I</p><p>short filing without sections</p></body></html>"
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            ingest, "download", return_value=bad_html.encode()
        ):
            root = pathlib.Path(directory)
            result = ingest.ingest_event(event(), "Test Company", root)
            self.assertEqual(result["status"], "review_required")
            self.assertEqual(list(root.rglob("*.md")), [])

    def test_successful_ingest_is_accession_traceable_and_idempotent(self):
        html = "<html><body>" + valid_10q_text().replace("\n", "<br>") + "</body></html>"
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            ingest, "download", return_value=html.encode()
        ):
            root = pathlib.Path(directory)
            first = ingest.ingest_event(event(), "Test Company", root)
            second = ingest.ingest_event(event(), "Test Company", root)
            self.assertEqual(first["status"], "ingested")
            self.assertEqual(second["status"], "already_ingested")
            self.assertEqual(len(first["sections"]), 3)
            note = (root / first["note"]).read_text()
            self.assertIn('accession_number: "0000000001-26-000123"', note)
            self.assertIn("fail_closed", note)


if __name__ == "__main__":
    unittest.main()
