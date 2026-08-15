import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class DashboardSecTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "dashboard.html").read_text()
        cls.alerts = json.loads((ROOT / "sec_filing_alerts.json").read_text())
        cls.details = json.loads((ROOT / "sec_filing_details.json").read_text())
        cls.quarterly = json.loads((ROOT / "quarterly_financials.json").read_text())

    def test_tab_defaults_to_14_days_and_allows_7_days(self):
        self.assertIn("🚨 4_SEC 每日重點", self.html)
        self.assertIn('id="tab-sec"', self.html)
        self.assertIn('data-days="7"', self.html)
        self.assertIn('class="sec-range-btn active" data-days="14"', self.html)
        self.assertIn("let secRangeDays = 14", self.html)

    def test_tab_loads_same_origin_radar_data(self):
        self.assertIn("fetch('sec_filing_alerts.json'", self.html)
        self.assertIn("fetch('sec_filing_details.json'", self.html)
        self.assertIn("fetch('quarterly_financials.json'", self.html)
        self.assertIn("function renderSecDaily()", self.html)
        self.assertIn('id="secQuarterlyBody"', self.html)
        self.assertIn('id="secKpiQuarterly"', self.html)
        self.assertIn("details.quarterly", self.html)
        self.assertIn('id="secQuarterlyTicker"', self.html)
        self.assertIn('id="secQuarterlyTrendBody"', self.html)
        self.assertIn('id="secFilingsTicker"', self.html)
        self.assertIn('id="secTradesTicker"', self.html)
        self.assertIn('id="secDilutionTicker"', self.html)
        self.assertIn("function setSecTableTicker(section, ticker)", self.html)

    def test_numeric_meanings_are_explained(self):
        required_copy = [
            "每一列等於一份 SEC 文件",
            "單位是「份 SEC 文件／accession」",
            "交易金額＝股數 × 單價",
            "不是申報人的剩餘持股價值",
            "10b5-1",
            "不估算稀釋百分比",
            "申報日是文件送交 SEC 的日期",
            "不受上方最近 7／14 日篩選影響",
            "QoQ 是相較上一季、YoY 是相較去年同期",
            "自由現金流（FCF）＝OCF－資本支出",
            "EPS 與加權平均股數不能用相減法",
        ]
        for phrase in required_copy:
            self.assertIn(phrase, self.html)

    def test_form4_and_offering_details_join_to_alert_accessions(self):
        form4_events = [event for event in self.alerts["events"] if event["form"] in {"4", "4/A"}]
        offering_events = [event for event in self.alerts["events"] if event["group"] == "募資／稀釋"]
        self.assertTrue(form4_events)
        self.assertTrue(offering_events)
        self.assertTrue(any(
            self.details["form4"].get(event["accession"], {}).get("transactions")
            for event in form4_events
        ))
        self.assertTrue(all(
            event["accession"] in self.details["offerings"] for event in offering_events
        ))

    def test_quarterly_snapshot_covers_all_tracked_companies(self):
        quarterly = self.details.get("quarterly", {})
        self.assertEqual(len(quarterly), 14)
        self.assertEqual(quarterly["ONDS"]["event"]["form"], "10-Q")
        self.assertEqual(quarterly["TSM"]["status"], "foreign")

    def test_four_quarter_financials_are_comparable_without_foreign_estimates(self):
        companies = self.quarterly["companies"]
        self.assertEqual(len(companies), 14)
        self.assertGreaterEqual(len(companies["ONDS"]["periods"]), 8)
        self.assertEqual(companies["ARM"]["status"], "available")
        self.assertGreaterEqual(len(companies["ARM"]["periods"]), 8)
        self.assertEqual(companies["TSM"]["status"], "foreign_unavailable")
        self.assertEqual(companies["TSM"]["periods"], [])
        self.assertTrue(companies["TSM"]["official_results_url"].startswith("https://investor.tsmc.com/"))
        q4 = next(period for period in companies["ONDS"]["periods"] if period["q4_derived"])
        self.assertIsNone(q4["values"]["diluted_eps"])
        self.assertIsNone(q4["values"]["diluted_shares"])

    def test_foreign_quarterly_sources_and_compact_warning_are_explained(self):
        self.assertIn("ARM 的 6-K 有季度 XBRL，已納入", self.html)
        self.assertIn("開啟官方季度財報", self.html)
        self.assertIn('class="sec-warning-icon"', self.html)
        self.assertIn('title="${escapeSec(period.quality_notes.join(\' \'))}"', self.html)

    def test_current_personal_holdings_are_embedded(self):
        expected = [
            '{ ticker: "ARM", shares: 15, cost: 231.038 }',
            '{ ticker: "COHR", shares: 10, cost: 336.066 }',
            '{ ticker: "NOK", shares: 600, cost: 11.68895 }',
        ]
        for holding in expected:
            self.assertIn(holding, self.html)


if __name__ == "__main__":
    unittest.main()
