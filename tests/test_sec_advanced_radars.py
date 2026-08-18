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


if __name__ == "__main__":
    unittest.main()
