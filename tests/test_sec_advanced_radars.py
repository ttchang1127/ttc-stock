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

    def test_parses_13g_actual_holding_and_filing_basis(self):
        raw = b"""<html><body>SCHEDULE 13G (Amendment No. 14)
        CUSIP No. 037833100 December 31, 2023 (Date of Event Which Requires Filing of this Statement)
        [X] Rule 13d-1(b)
        (1) Names of reporting persons. BlackRock, Inc. (2) Check the appropriate box
        (5) Sole voting power 936,902,208 (6) Shared voting power 0
        (7) Sole dispositive power 1,043,713,019 (8) Shared dispositive power 0
        (9) Aggregate amount beneficially owned by each reporting person 1,043,713,019
        (11) Percent of class represented by amount in Row 9 6.7%
        Item 1. Issuer</body></html>"""
        facts = radars.parse_13dg_ownership(raw, "SC 13G/A")
        self.assertEqual(facts["aggregate_shares"], 1043713019)
        self.assertEqual(facts["percent_of_class"], 6.7)
        self.assertEqual(facts["sole_voting_power"], 936902208)
        self.assertEqual(facts["filing_basis"], "合格機構投資人")
        self.assertEqual(facts["event_date"], "December 31, 2023")
        self.assertEqual(facts["cusip"], "037833100")

    def test_parses_13d_multiple_reporters_and_item4(self):
        raw = b"""<html><body>SCHEDULE 13D May 31, 2024
        (Date of Event which Requires Filing of this Statement)
        1 NAME OF REPORTING PERSON Fund LLC 2 CHECK THE APPROPRIATE BOX
        7 SOLE VOTING POWER 0 8 SHARED VOTING POWER 7,215,286
        9 SOLE DISPOSITIVE POWER 0 10 SHARED DISPOSITIVE POWER 7,215,286
        11 AGGREGATE AMOUNT BENEFICIALLY OWNED BY EACH REPORTING PERSON 7,215,286
        13 PERCENT OF CLASS REPRESENTED BY AMOUNT IN ROW (11) 10.26%
        1 NAME OF REPORTING PERSON Jane Doe 2 CHECK THE APPROPRIATE BOX
        7 SOLE VOTING POWER 1,384,245 8 SHARED VOTING POWER 7,215,286
        9 SOLE DISPOSITIVE POWER 1,384,245 10 SHARED DISPOSITIVE POWER 7,215,286
        11 AGGREGATE AMOUNT BENEFICIALLY OWNED BY EACH REPORTING PERSON 8,599,531
        13 PERCENT OF CLASS REPRESENTED BY AMOUNT IN ROW (11) 12.23%
        ITEM 4. PURPOSE OF TRANSACTION. The reporting persons seek discussions with the board.
        ITEM 5. INTEREST IN SECURITIES OF THE ISSUER.</body></html>"""
        facts = radars.parse_13dg_ownership(raw, "SC 13D/A")
        self.assertEqual(len(facts["positions"]), 2)
        self.assertEqual(facts["aggregate_shares"], 8599531)
        self.assertEqual(facts["percent_of_class"], 12.23)
        self.assertIn("discussions with the board", facts["purpose_excerpt"])
        self.assertEqual(facts["filing_basis"], "主動型／可能影響控制")

    def test_parses_new_structured_schedule_and_exit_comment(self):
        raw = b"""<SEC-DOCUMENT><submissionType>SCHEDULE 13G/A</submissionType>
        <eventDateRequiresFilingThisStatement>03/13/2026</eventDateRequiresFilingThisStatement>
        <issuerCusipNumber>67066G104</issuerCusipNumber>
        <designateRulePursuantThisScheduleFiled>Rule 13d-1(b)</designateRulePursuantThisScheduleFiled>
        <coverPageHeaderReportingPersonDetails>
        <reportingPersonName>The Vanguard Group</reportingPersonName>
        <soleVotingPower>0</soleVotingPower><sharedVotingPower>0</sharedVotingPower>
        <soleDispositivePower>0</soleDispositivePower><sharedDispositivePower>0</sharedDispositivePower>
        <reportingPersonBeneficiallyOwnedAggregateNumberOfShares>0</reportingPersonBeneficiallyOwnedAggregateNumberOfShares>
        <classPercent>0</classPercent><comments>Internal realignment; related subsidiaries report separately.</comments>
        </coverPageHeaderReportingPersonDetails>
        <classOwnership5PercentOrLess>Y</classOwnership5PercentOrLess></SEC-DOCUMENT>"""
        facts = radars.parse_13dg_ownership(raw, "SCHEDULE 13G/A")
        self.assertEqual(facts["aggregate_shares"], 0)
        self.assertEqual(facts["percent_of_class"], 0)
        self.assertTrue(facts["threshold_exit"])
        self.assertEqual(facts["cusip"], "67066G104")
        self.assertIn("Internal realignment", facts["filing_comment"])
        self.assertIn("SCHEDULE 13G/A", radars.OWNERSHIP_FORMS)

    def test_compares_same_13dg_filer_without_mixing_owners(self):
        rows = [
            {"ticker": "ABC", "filing_date": "2024-01-01", "accession": "1",
             "reporting_persons": ["Fund A (CIK 0000000001)"],
             "ownership": {"data_status": "parsed", "aggregate_shares": 100, "percent_of_class": 6.0}},
            {"ticker": "ABC", "filing_date": "2024-02-01", "accession": "2",
             "reporting_persons": ["Fund B (CIK 0000000002)"],
             "ownership": {"data_status": "parsed", "aggregate_shares": 999, "percent_of_class": 9.0}},
            {"ticker": "ABC", "filing_date": "2024-03-01", "accession": "3",
             "reporting_persons": ["Fund A (CIK 0000000001)"],
             "ownership": {"data_status": "parsed", "aggregate_shares": 80, "percent_of_class": 4.8}},
        ]
        radars.add_ownership_changes(rows)
        change = rows[2]["ownership"]["change_from_prior"]
        self.assertEqual(change["shares"], -20)
        self.assertEqual(change["percentage_points"], -1.2)
        self.assertEqual(change["direction"], "減少")

    def test_split_scale_share_change_uses_percentage_direction(self):
        rows = [
            {"ticker": "XYZ", "filing_date": "2024-01-01", "accession": "1",
             "reporting_persons": ["Fund (CIK 0000000001)"],
             "ownership": {"data_status": "parsed", "cusips": ["123456789"], "aggregate_shares": 100, "percent_of_class": 6.0}},
            {"ticker": "XYZ", "filing_date": "2024-12-01", "accession": "2",
             "reporting_persons": ["Fund (CIK 0000000001)"],
             "ownership": {"data_status": "parsed", "cusips": ["123456789"], "aggregate_shares": 900, "percent_of_class": 5.5}},
        ]
        radars.add_ownership_changes(rows)
        change = rows[1]["ownership"]["change_from_prior"]
        self.assertEqual(change["direction"], "減少")
        self.assertFalse(change["shares_comparable"])
        self.assertIn("拆股", change["comparison_note"])

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
