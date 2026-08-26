import json
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class DashboardSecTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "dashboard.html").read_text()
        cls.alerts = json.loads((ROOT / "sec_filing_alerts.json").read_text())
        cls.details = json.loads((ROOT / "sec_filing_details.json").read_text())
        cls.quarterly = json.loads((ROOT / "quarterly_financials.json").read_text())
        cls.advanced = json.loads((ROOT / "sec_advanced_radars.json").read_text())
        cls.thirteen_f = json.loads((ROOT / "sec_13f_stock_radar.json").read_text())
        cls.text_changes = json.loads((ROOT / "filing_text_changes.json").read_text())

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
        self.assertIn("fetch('sec_advanced_radars.json'", self.html)
        self.assertIn("fetch('sec_13f_stock_radar.json'", self.html)
        self.assertIn("fetch('filing_text_changes.json'", self.html)
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
        self.assertIn('id="secAdvancedCategory"', self.html)
        self.assertIn('id="secAdvancedTicker"', self.html)
        self.assertIn('id="secAdvancedInterpretation"', self.html)
        self.assertIn('id="secAdvancedActual"', self.html)
        self.assertIn("function renderSecAdvanced()", self.html)

    def test_core_holding_shortcuts_sync_all_sec_sections(self):
        core = ["NVDA", "TSM", "MSFT", "META", "AAPL", "AMZN", "ARM",
                "ONDS", "TSLA", "GOOG", "COHR", "MRVL", "INTC", "NOK"]
        self.assertIn('id="secCoreShortcuts"', self.html)
        self.assertIn("function setSecCoreTicker(ticker)", self.html)
        self.assertIn("function renderSecCoreShortcuts()", self.html)
        self.assertIn("點選一次，同步切換①八季數字、②重要申報、③ Form 4、④募資稀釋、⑤進階 SEC 雷達與⑥文字差異", self.html)
        for ticker in core:
            self.assertIn(f'data-sec-core-ticker="{ticker}"', self.html)
            self.assertIn(f"setSecCoreTicker('{ticker}')", self.html)
        tab_one = re.findall(r"selectQuickTicker\('([A-Z]+)'\)", self.html)
        sec_tab = re.findall(r'data-sec-core-ticker="([A-Z]+)"', self.html)
        self.assertEqual(tab_one, core)
        self.assertEqual(sec_tab, tab_one)
        for assignment in ("secQuarterlyTicker = dataTicker", "secFilingsTicker = dataTicker",
                           "secTradesTicker = dataTicker", "secDilutionTicker = dataTicker",
                           "secAdvancedTicker = dataTicker"):
            self.assertIn(assignment, self.html)
        self.assertIn("const SEC_TICKER_ALIASES = { GOOG: 'GOOGL' }", self.html)
        self.assertIn("button.setAttribute('aria-pressed', active ? 'true' : 'false')", self.html)

    def test_periodic_filing_text_diff_has_actual_excerpts_and_caveats(self):
        self.assertEqual(set(self.text_changes["companies"]), set(self.quarterly["companies"]))
        compared = [row for row in self.text_changes["companies"].values() if row["status"] == "compared"]
        self.assertGreaterEqual(len(compared), 13)
        self.assertTrue(all(row["previous"]["form"] == row["latest"]["form"] for row in compared))
        self.assertTrue(any(
            section.get("added") or section.get("modified") or section.get("removed")
            for row in compared for section in row["sections"].values()
            if section["status"] == "compared"
        ))
        signals = {
            item["language_signal"]["label"]
            for row in compared for section in row["sections"].values()
            if section["status"] == "compared"
            for group in ("added", "modified") for item in section.get(group, [])
        }
        self.assertTrue({"可能升高措辭", "可能緩和措辭", "大幅改寫"}.issubset(signals))
        required_copy = [
            'id="secTextDiff"', "function renderSecTextDiff()",
            "10-K／10-Q 文字差異雷達", "前一期原文", "本期原文",
            "大幅改寫",
            "不再列出」不等於風險已消失", "原文段落比對",
        ]
        for phrase in required_copy:
            self.assertIn(phrase, self.html)

    def test_single_company_sec_brief_is_traceable_and_objective(self):
        required_copy = [
            'id="secCompanyBrief"',
            "function renderSecCompanyBrief()",
            "單公司 SEC 綜合判讀",
            "財務連續性",
            "最新重要申報",
            "Form 4 主動買／賣",
            "募資與稀釋",
            "大股東最新狀態",
            "會計審閱／執法",
            "這是閱讀優先度，不是投資評等",
            "財務升降與 Form 4 買賣僅陳述事實",
        ]
        for phrase in required_copy:
            self.assertIn(phrase, self.html)
        for category in ("'atm_equity'", "'equity'", "'convertible'", "'shelf'"):
            self.assertIn(category, self.html)
        self.assertIn("const yearAgo = periods[4]", self.html)
        self.assertIn("ownershipAge <= 90", self.html)
        self.assertIn("['P', 'S'].includes(tx.code)", self.html)

    def test_daily_change_brief_distinguishes_new_zero_and_legacy_batches(self):
        required_copy = [
            'id="secUpdateBrief"',
            "🆕 今天有什麼變化",
            "function renderSecUpdateBrief()",
            "function secLegacyUpdateBatch(alerts)",
            "本次檢查沒有新申報或外部重大訊號",
            "不是資料停更",
            "閱讀優先度改變",
            "新定期財報文件",
            "大股東／執法新增訊號",
            "不把所有 6-K 當財報",
            "優先度只決定閱讀順序",
        ]
        for phrase in required_copy:
            self.assertIn(phrase, self.html)

    def test_advanced_radars_cover_all_requested_categories(self):
        for key in ("footnotes", "accounting_review", "ownership_13dg", "governance",
                    "insiders", "mergers", "enforcement"):
            self.assertIn(key, self.advanced)
        self.assertEqual(set(self.thirteen_f["stocks"]), set(self.quarterly["companies"]))
        self.assertEqual(len(self.thirteen_f["periods"]), 2)
        self.assertIn("13D／13G 持股數／比例", self.html)
        self.assertIn("Form 144 是擬售通知", self.html)
        self.assertIn("45 天時滯", self.html)

    def test_each_advanced_radar_has_dynamic_interpretation(self):
        self.assertIn("SEC_ADVANCED_INTERPRETATIONS", self.html)
        required_copy = [
            "不是附件份數，也不是風險數量",
            "不是審閱輪數或違規件數",
            "不是獨立大股東人數",
            "不是薪酬事件數",
            "不是成交筆數或申報人數",
            "括號數字是合併後的交易宗數",
            "顯示 0 不代表沒有法律風險",
            "14 代表 14 檔追蹤股票，不是 14 家機構",
            "Form 144 是出售意向，不等於交易已完成",
        ]
        for phrase in required_copy:
            self.assertIn(phrase, self.html)

    def test_advanced_radar_shows_concrete_filing_content(self):
        required_copy = [
            "目前實際申報內容",
            "不是範例；內容隨雷達與公司篩選同步更新",
            "交易原文摘錄",
            "實際受益持股",
            "change_from_prior",
            "13D Item 4 投資目的摘錄",
            "secAdvancedForm4Facts",
            "交易後",
            "申報備註",
        ]
        for phrase in required_copy:
            self.assertIn(phrase, self.html)

    def test_ownership_latest_status_overview(self):
        snapshot = self.advanced.get("ownership_snapshot", [])
        self.assertTrue(snapshot)
        self.assertLess(len(snapshot), len(self.advanced["ownership_13dg"]))
        self.assertTrue(all(item["history_count"] == len(item["history"]) for item in snapshot))
        self.assertTrue({"above_5", "exit", "realignment"}.issubset({item["status"] for item in snapshot}))
        for marker in ("secOwnershipOverview", "大股東最新狀態總覽", "secOwnershipStatus",
                       "renderSecOwnershipOverview", "同公司、同申報 CIK、同 CUSIP",
                       "申報主體重整顯示 0 股時"):
            self.assertIn(marker, self.html)

    def test_ownership_change_timeline_and_alert_levels(self):
        timeline = self.advanced.get("ownership_timeline", [])
        self.assertTrue(timeline)
        self.assertEqual(len(timeline), len(self.advanced["ownership_13dg"]))
        self.assertTrue({"high", "watch", "routine"}.issubset({event["importance"] for event in timeline}))
        self.assertTrue(all(event["event_label"] and event["interpretation"] for event in timeline))
        for marker in ("secOwnershipTimeline", "大股東異動時間軸與警報", "secOwnershipEventLevel",
                       "renderSecOwnershipTimeline", "secOwnershipTimelineChange", "顏色表示閱讀優先度",
                       "13G→13D", "持股比例變動至少 2pp"):
            self.assertIn(marker, self.html)
        merger_rows = self.advanced["mergers"]
        merger_deals = self.advanced["merger_deals"]
        window = self.advanced["merger_window"]
        self.assertEqual(window["years"], 3)
        self.assertEqual(window["document_count"], len(merger_rows))
        self.assertEqual(window["deal_count"], len(merger_deals))
        self.assertEqual(sum(deal["document_count"] for deal in merger_deals), len(merger_rows))
        self.assertTrue(all(row["event"]["filing_date"] >= window["cutoff"] for row in merger_rows))
        self.assertEqual({deal["deal_name"] for deal in merger_deals}, {
            "Amazon 收購 Globalstar", "Nokia 收購 Infinera",
        })
        self.assertNotIn("MSFT", {row["event"]["ticker"] for row in merger_rows})
        self.assertIn("advanced.merger_deals", self.html)
        self.assertIn("最後可見程序", self.html)

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

    def test_four_quarter_financials_include_official_foreign_ir_results(self):
        companies = self.quarterly["companies"]
        self.assertEqual(len(companies), 14)
        self.assertGreaterEqual(len(companies["ONDS"]["periods"]), 8)
        self.assertEqual(companies["ARM"]["status"], "available")
        self.assertGreaterEqual(len(companies["ARM"]["periods"]), 8)
        self.assertEqual(companies["TSM"]["status"], "available")
        self.assertEqual(companies["TSM"]["currency"], "TWD")
        self.assertGreaterEqual(len(companies["TSM"]["periods"]), 8)
        self.assertEqual(companies["NOK"]["status"], "available")
        self.assertEqual(companies["NOK"]["currency"], "EUR")
        self.assertGreaterEqual(len(companies["NOK"]["periods"]), 8)
        self.assertTrue(companies["TSM"]["official_results_url"].startswith("https://investor.tsmc.com/"))
        q4 = next(period for period in companies["ONDS"]["periods"] if period["q4_derived"])
        self.assertIsNone(q4["values"]["diluted_eps"])
        self.assertIsNone(q4["values"]["diluted_shares"])

    def test_foreign_quarterly_sources_and_compact_warning_are_explained(self):
        self.assertIn("ARM 採 SEC 6-K XBRL", self.html)
        self.assertIn("NOK 採官方 IFRS reported 歐元數字", self.html)
        self.assertIn("TSM 採官方 TIFRS consolidated 新台幣數字", self.html)
        self.assertIn("開啟官方季度財報", self.html)
        self.assertIn('class="sec-warning-icon"', self.html)
        self.assertIn('data-tooltip="${escapeSec(period.quality_notes.join(\' \'))}"', self.html)
        self.assertIn('id="secWarningTooltip"', self.html)
        self.assertIn("function showSecWarningTooltip(button, pin = false)", self.html)
        self.assertIn("function toggleSecWarningTooltip(event, button)", self.html)

    def test_native_currency_quarterly_rendering_is_explicit(self):
        self.assertIn('id="secRevenueHeading"', self.html)
        self.assertIn("function formatSecAmount(value, currency = 'USD')", self.html)
        self.assertIn("USD／EUR 以 M（百萬）、TWD 以 B（十億）", self.html)
        self.assertIn("safeQuarterlySourceUrl(period.url)", self.html)

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
