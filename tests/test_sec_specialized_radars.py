import importlib.util
import pathlib
import unittest


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "sec_specialized_radars.py"
SPEC = importlib.util.spec_from_file_location("sec_specialized_radars", SCRIPT)
radars = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(radars)


FORM4_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<ownershipDocument>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>DOE JANE</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>0</isDirector><isOfficer>1</isOfficer>
      <officerTitle>CFO</officerTitle><isTenPercentOwner>0</isTenPercentOwner>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-08-14</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode><isRule10b5-1>1</isRule10b5-1></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>100</value></transactionShares>
        <transactionPricePerShare><value>25.50</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts><sharesOwnedFollowingTransaction><value>900</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
      <ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""


class Form4Tests(unittest.TestCase):
    def test_converts_sec_xsl_display_url_to_raw_xml(self):
        url = "https://www.sec.gov/Archives/edgar/data/1/abc/xslF345X06/ownership.xml"
        self.assertEqual(
            radars.raw_ownership_url(url),
            "https://www.sec.gov/Archives/edgar/data/1/abc/ownership.xml",
        )

    def test_parses_reporter_transaction_and_10b51(self):
        result = radars.parse_form4(FORM4_XML)
        tx = result["transactions"][0]
        self.assertEqual(tx["reporter"], "DOE JANE")
        self.assertEqual(tx["role"], "高階主管（CFO）")
        self.assertEqual(tx["code"], "S")
        self.assertEqual(tx["shares"], 100)
        self.assertEqual(tx["price"], 25.50)
        self.assertEqual(tx["value"], 2550)
        self.assertEqual(tx["shares_after"], 900)
        self.assertTrue(tx["rule_10b5_1"])

    def test_missing_numbers_remain_missing_not_zero(self):
        xml = FORM4_XML.replace(b"<value>100</value>", b"").replace(b"<value>25.50</value>", b"")
        tx = radars.parse_form4(xml)["transactions"][0]
        self.assertIsNone(tx["shares"])
        self.assertIsNone(tx["price"])
        self.assertIsNone(tx["value"])


class OfferingClassificationTests(unittest.TestCase):
    def test_atm_equity(self):
        result = radars.classify_offering(
            "424B5", "We are offering common stock under an at-the-market sales agreement."
        )
        self.assertEqual(result["category"], "atm_equity")

    def test_convertible_notes(self):
        result = radars.classify_offering(
            "424B5", "Offering of convertible senior notes due 2031."
        )
        self.assertEqual(result["category"], "convertible")

    def test_mandatory_convertible_preferred_beats_incidental_atm_reference(self):
        result = radars.classify_offering(
            "424B5",
            "We are offering Series B Mandatory Convertible Preferred Stock. "
            "The company separately maintains an equity distribution agreement.",
        )
        self.assertEqual(result["category"], "convertible")

    def test_plain_debt_is_not_direct_dilution(self):
        result = radars.classify_offering(
            "424B5", "We are offering $500 million aggregate principal amount of senior notes due 2034."
        )
        self.assertEqual(result["category"], "debt")
        self.assertEqual(result["dilution"], "非直接股權稀釋")

    def test_shelf_registration_is_not_treated_as_issued(self):
        result = radars.classify_offering(
            "S-3ASR", "This registration statement covers securities that we may offer in the future."
        )
        self.assertEqual(result["category"], "shelf")
        self.assertIn("尚未發生", result["dilution"])


class QuarterlyTests(unittest.TestCase):
    def test_selects_latest_10q_and_marks_foreign_issuer(self):
        old = {"form": "10-Q", "filing_date": "2026-05-01", "accepted_at": "", "ticker": "ONDS"}
        new = {"form": "10-Q", "filing_date": "2026-08-01", "accepted_at": "", "ticker": "ONDS"}
        foreign = {"form": "20-F", "filing_date": "2026-03-01", "accepted_at": "", "ticker": "TSM"}
        rows = radars.latest_quarterly_rows({"ONDS": [old, new], "TSM": [foreign]})
        self.assertEqual(rows[0]["event"], new)
        self.assertEqual(rows[1]["status"], "foreign")


if __name__ == "__main__":
    unittest.main()
