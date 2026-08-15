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

    def test_tab_defaults_to_14_days_and_allows_7_days(self):
        self.assertIn("🚨 4_SEC 每日重點", self.html)
        self.assertIn('id="tab-sec"', self.html)
        self.assertIn('data-days="7"', self.html)
        self.assertIn('class="sec-range-btn active" data-days="14"', self.html)
        self.assertIn("let secRangeDays = 14", self.html)

    def test_tab_loads_same_origin_radar_data(self):
        self.assertIn("fetch('sec_filing_alerts.json'", self.html)
        self.assertIn("fetch('sec_filing_details.json'", self.html)
        self.assertIn("function renderSecDaily()", self.html)

    def test_numeric_meanings_are_explained(self):
        required_copy = [
            "每一列等於一份 SEC 文件",
            "單位是「份 SEC 文件／accession」",
            "交易金額＝股數 × 單價",
            "不是申報人的剩餘持股價值",
            "10b5-1",
            "不估算稀釋百分比",
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


if __name__ == "__main__":
    unittest.main()
