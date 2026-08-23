import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sec_advanced_radars.py"
SPEC = importlib.util.spec_from_file_location("sec_advanced_radars", SCRIPT)
radars = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(radars)


class AdvancedRadarTests(unittest.TestCase):
    def test_submission_attachment_index(self):
        event = {"index_url": "https://www.sec.gov/Archives/edgar/data/1/abc/acc-index.html"}
        raw = b"""<DOCUMENT>\n<TYPE>EX-99.1\n<FILENAME>earnings.htm\n<DESCRIPTION>Earnings release\n</DOCUMENT>"""
        documents = radars.parse_submission_documents(raw, event)
        self.assertEqual(documents[0]["type"], "EX-99.1")
        self.assertEqual(documents[0]["url"], "https://www.sec.gov/Archives/edgar/data/1/abc/earnings.htm")

    def test_form144_sums_multiple_planned_sales(self):
        xml = b"""<edgarSubmission><formData>
        <issuerInfo><nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold>Jane Doe</nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold><relationshipToIssuer>Director</relationshipToIssuer></issuerInfo>
        <securitiesInformation><noOfUnitsSold>100</noOfUnitsSold><aggregateMarketValue>1200</aggregateMarketValue><noOfUnitsOutstanding>10000</noOfUnitsOutstanding><approxSaleDate>08/18/2026</approxSaleDate></securitiesInformation>
        <securitiesInformation><noOfUnitsSold>50</noOfUnitsSold><aggregateMarketValue>600</aggregateMarketValue><noOfUnitsOutstanding>10000</noOfUnitsOutstanding></securitiesInformation>
        <remarks>Sale for tax withholding.</remarks></formData></edgarSubmission>"""
        result = radars.parse_form144(xml)
        self.assertEqual(result["planned_shares"], 150)
        self.assertEqual(result["planned_value_usd"], 1800)
        self.assertEqual(result["shares_outstanding"], 10000)

    def test_detects_financial_risk_signals(self):
        result = radars.detect_signals("The company identified a material weakness and substantial doubt about its ability to continue as a going concern.")
        self.assertEqual({row["label"] for row in result}, {"繼續經營", "重大內控缺失"})

    def test_extracts_concrete_merger_passage(self):
        raw = b"""<html><body>Amazon and Globalstar entered into an Agreement and Plan of Merger
        that provides for the acquisition of Globalstar by Amazon, subject to shareholder approval.
        Each share will receive the consideration described below.</body></html>"""
        excerpt = radars.merger_content_excerpt(raw)
        self.assertIn("acquisition of Globalstar by Amazon", excerpt)
        self.assertIn("shareholder approval", excerpt)

    def test_s4_debt_exchange_is_not_treated_as_merger(self):
        row = {
            "event": {"form": "S-4"},
            "content_excerpt": "Exchange offer for new senior notes due 2035 and related guarantees.",
        }
        self.assertFalse(radars.merger_document_relevant(row))

    def test_groups_documents_into_one_recent_deal(self):
        def row(filing_date, form, accession, excerpt):
            return {"event": {
                "ticker": "AMZN", "filing_date": filing_date, "accepted_at": filing_date,
                "form": form, "accession": accession, "url": f"https://www.sec.gov/{accession}",
            }, "content_excerpt": excerpt}

        rows = [
            row("2026-04-14", "425", "a", "Amazon announced the acquisition of Globalstar by Amazon under a definitive merger agreement."),
            row("2026-08-14", "S-4/A", "b", "The agreement and plan of merger provides for the acquisition of Globalstar by Amazon."),
            row("2024-04-26", "S-4", "debt", "Exchange offer for new senior notes due 2052."),
            row("2022-06-28", "425", "old", "The acquisition of Coherent by II-VI was approved."),
        ]
        documents, deals, window = radars.build_merger_deals(
            rows, {"AMZN": {"name": "AMAZON COM INC"}}, "2026-08-23T00:00:00+00:00"
        )
        self.assertEqual(window["cutoff"], "2023-08-23")
        self.assertEqual(len(documents), 2)
        self.assertEqual(len(deals), 1)
        self.assertEqual(deals[0]["deal_name"], "Amazon 收購 Globalstar")
        self.assertEqual(deals[0]["document_count"], 2)
        self.assertEqual(deals[0]["last_procedural_status"], "合併註冊文件已修訂")

    def test_detects_when_tracked_company_is_the_target(self):
        row = {"event": {"ticker": "COHR"}, "content_excerpt": (
            'Coherent, Inc. (“Coherent”) announced its pending acquisition by '
            'II-VI Incorporated (“II-VI”) pursuant to the merger agreement.'
        )}
        parties = radars.extract_merger_parties(
            row, {"COHR": {"name": "Coherent Corp."}}
        )
        self.assertEqual(parties, {"target": "Coherent", "acquirer": "II-VI"})


if __name__ == "__main__":
    unittest.main()
