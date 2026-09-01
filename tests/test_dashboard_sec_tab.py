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
        cls.thesis_tracking = json.loads((ROOT / "investment_thesis_tracking.json").read_text())
        cls.thesis_status = json.loads((ROOT / "investment_thesis_status.json").read_text())
        cls.exhibit_991 = json.loads((ROOT / "exhibit_991_analysis.json").read_text())
        cls.earnings_calls = json.loads((ROOT / "earnings_call_analysis.json").read_text())
        cls.editorial = json.loads((ROOT / "sec_daily_editorial.json").read_text())
        cls.change_candidates = json.loads((ROOT / "sec_daily_change_candidates.json").read_text())

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
        self.assertIn("fetch('investment_thesis_tracking.json'", self.html)
        self.assertIn("fetch('investment_thesis_status.json'", self.html)
        self.assertIn("fetch('exhibit_991_analysis.json'", self.html)
        self.assertIn("fetch('earnings_call_analysis.json'", self.html)
        self.assertIn("fetch('sec_daily_editorial.json'", self.html)
        self.assertIn("fetch('sec_daily_change_candidates.json'", self.html)
        self.assertIn("fetch('valuation.json'", self.html)
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
        self.assertIn("點選一次，同步切換①八季數字、②重要申報、③ Form 4、④募資稀釋、⑤進階 SEC 雷達、⑥文字差異、⑦投資論點、⑧ Exhibit 99.1 與⑨ Earnings Call", self.html)
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

    def test_exhibit_991_cards_show_verbatim_evidence_and_missing_state(self):
        self.assertEqual(self.exhibit_991["schema_version"], 1)
        self.assertEqual(len(self.exhibit_991["categories"]), 7)
        analyzed = [row for row in self.exhibit_991["filings"] if row["status"] == "analyzed"]
        self.assertTrue({"COHR", "ONDS", "NVDA", "MRVL"}.issubset(
            {row["ticker"] for row in analyzed}
        ))
        self.assertTrue(all(row["exhibit_url"].startswith("https://www.sec.gov/") for row in analyzed))
        self.assertTrue(all(any(row["categories"].values()) for row in analyzed))
        self.assertIn("安全港文字是警語", self.exhibit_991["categories"]["risks"]["meaning"])
        required_copy = [
            'id="secExhibit991"', "function renderSecExhibit991()",
            "⑧ Exhibit 99.1", "Item 2.02", "證據覆蓋",
            "本附件未可靠辨識此項；保留缺值",
            "不代表公司未公布財報；外國私人發行人也可能使用 6-K",
            "舊卡已移除，不顯示可能過期的內容",
            "本卡是官方附件的原文閱讀索引，不是投資評分",
        ]
        for phrase in required_copy:
            self.assertIn(phrase, self.html)

    def test_earnings_call_cards_distinguish_text_and_replay_sources(self):
        self.assertEqual(self.earnings_calls["schema_version"], 3)
        self.assertEqual(self.earnings_calls["history_quarters"], 4)
        self.assertEqual(len(self.earnings_calls["companies"]), 14)
        self.assertEqual(len(self.earnings_calls["categories"]), 7)
        self.assertTrue(any(row["status"] == "analyzed" for row in self.earnings_calls["companies"].values()))
        self.assertTrue(any(row["status"] == "replay_only" for row in self.earnings_calls["companies"].values()))
        available = [
            row for row in self.earnings_calls["companies"].values()
            if row["status"] in {"analyzed", "replay_only", "analyzed_cached"}
        ]
        self.assertTrue(all(row.get("provenance", {}).get("status") for row in available))
        text_rows = [
            row for row in self.earnings_calls["companies"].values()
            if row["status"] in {"analyzed", "analyzed_cached"}
        ]
        self.assertEqual(len(text_rows), 7)
        self.assertTrue(all(row["history_coverage"]["status"] == "complete" for row in text_rows))
        self.assertTrue(all(len(row["history"]) == 4 for row in text_rows))
        self.assertTrue(all(len(row["quarter_comparisons"]) == 3 for row in text_rows))
        replay_rows = [row for row in self.earnings_calls["companies"].values() if row["status"] == "replay_only"]
        self.assertTrue(all(row["history_coverage"]["status"] == "not_applicable" for row in replay_rows))
        required_copy = [
            'id="secEarningsCall"', "function renderSecEarningsCall()",
            "⑨ Earnings Call", "完整官方逐字稿", "官方 Prepared Remarks",
            "僅官方影音／回放", "第三方逐字稿", "Q&A",
            "與 Exhibit 99.1", "不把語氣關鍵字轉成評分或買賣建議",
            "本次下載失敗", "來源鏈：",
            "較新官方候選", "safeEarningsCallUrl", "row.allowed_hosts",
            "最近四季法說趨勢比較", "本季新增命中", "連續兩季命中",
            "本季未再命中", "資料不足", "不等於風險消失",
        ]
        for phrase in required_copy:
            self.assertIn(phrase, self.html)

    def test_periodic_filing_text_diff_has_actual_excerpts_and_caveats(self):
        self.assertEqual(set(self.text_changes["companies"]), set(self.quarterly["companies"]))
        compared = [row for row in self.text_changes["companies"].values() if row["status"] == "compared"]
        self.assertGreaterEqual(len(compared), 12)
        unavailable = [row for row in self.text_changes["companies"].values() if row["status"] == "unavailable"]
        self.assertTrue(all(
            row.get("sections") and all(section.get("reason") for section in row["sections"].values())
            for row in unavailable
        ))
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
            "目前建議動作",
            "SEC 證據分數／100",
            "判讀信心",
            "支持證據",
            "風險證據",
            "什麼會改變結論",
            "實際稀釋股數 YoY",
            "證據偏正向",
            "中性觀察",
            "風險偏高",
            "高風險",
            "不是買進／賣出指令",
            "重要文件本身只提高閱讀優先度，不預設多空",
        ]
        for phrase in required_copy:
            self.assertIn(phrase, self.html)
        for category in ("'atm_equity'", "'equity'", "'convertible'", "'shelf'", "'merger_stock_consideration'"):
            self.assertIn(category, self.html)
        self.assertIn("const yearAgo = periods[4]", self.html)
        self.assertIn("ownershipAge <= 90", self.html)
        self.assertIn("['P', 'S'].includes(tx.code)", self.html)
        self.assertIn("row.tx.rule_10b5_1 === true", self.html)
        self.assertIn("const evidenceScore = Math.max(0, Math.min(100", self.html)
        self.assertIn("dimensions.reduce((sum, item) => sum + item.score", self.html)
        self.assertIn("financialScore", self.html)
        self.assertIn("dilutionScore", self.html)
        self.assertIn("actualDilutionScore", self.html)
        self.assertIn("dilutedSharesYoy", self.html)
        self.assertIn("ownershipScore", self.html)
        self.assertIn("reviewScore", self.html)

    def test_daily_change_brief_distinguishes_new_zero_and_legacy_batches(self):
        required_copy = [
            'id="secUpdateBrief"',
            "🆕 今天有什麼變化",
            "function renderSecUpdateBrief()",
            "function secLegacyUpdateBatch(alerts)",
            "本次檢查沒有新申報、外部重大訊號或論點狀態改變",
            "不是資料停更",
            "閱讀優先度改變",
            "新定期財報文件",
            "大股東／執法新增訊號",
            "論點狀態改變",
            "投資論點狀態變更",
            "單純數值更新但分類不變不重複通知",
            "不把所有 6-K 當財報",
            "優先度只決定閱讀順序",
        ]
        for phrase in required_copy:
            self.assertIn(phrase, self.html)

    def test_daily_change_candidates_are_drafts_with_sources_and_caveats(self):
        self.assertEqual(self.change_candidates["schema_version"], 1)
        self.assertEqual(
            self.change_candidates["candidate_count"],
            len(self.change_candidates["candidates"]),
        )
        self.assertTrue(all(row["status"] == "pending_ai_review"
                            for row in self.change_candidates["candidates"]))
        self.assertTrue(all(row["type"] in {"risk", "improvement", "conclusion"}
                            for row in self.change_candidates["candidates"]))
        self.assertTrue(all(row["source_keys"] and row["sources"]
                            for row in self.change_candidates["candidates"]))
        required_copy = [
            'id="secChangeCandidates"', "function renderSecChangeCandidates()",
            "每日變更候選稿", "新增風險候選", "改善候選", "結論變化候選",
            "規則自動產生、等待 AI 閱讀官方原文的候選稿",
            "不是最終綜合判讀", "Form 144 只代表擬售意向",
            "10b5-1 賣出訊號會降低證據強度", "renderSecChangeCandidates();",
        ]
        for phrase in required_copy:
            self.assertIn(phrase, self.html)

    def test_core_holdings_have_objective_daily_reading_order(self):
        required_copy = [
            'id="secReadingRank"',
            "function secReadingRankRows()",
            "function renderSecReadingRank()",
            "data-sec-rank-ticker",
            "核心持股每日閱讀排序",
            "本區只列出閱讀先後，不建立待辦或人工列管",
            "潛在稀釋、重大／重要申報、90 日內重大 13D／13G",
            "排序只決定每日閱讀先後，不是利多／利空、投資評等或報酬預測",
            "renderSecReadingRank();",
        ]
        for phrase in required_copy:
            self.assertIn(phrase, self.html)
        self.assertIn("return SEC_CORE_TICKERS.map(displayTicker =>", self.html)
        self.assertIn("onclick=\"setSecCoreTicker('${escapeSec(row.displayTicker)}')\"", self.html)
        self.assertIn("secDaysSince(row.filing_date) <= 90", self.html)

    def test_daily_editorial_contains_digested_evidence_and_next_checks(self):
        core = {"NVDA", "TSM", "MSFT", "META", "AAPL", "AMZN", "ARM",
                "ONDS", "TSLA", "GOOG", "COHR", "MRVL", "INTC", "NOK"}
        companies = self.editorial["companies"]
        self.assertEqual(self.editorial["schema_version"], 3)
        self.assertEqual({row["ticker"] for row in companies}, core)
        self.assertEqual(sorted(row["rank"] for row in companies), list(range(1, 15)))
        self.assertEqual(
            self.editorial["portfolio_order"],
            ["MRVL", "NOK", "COHR", "NVDA", "INTC", "TSLA", "GOOG", "ARM"],
        )
        self.assertIsNone(self.editorial["comparison"]["previous_reviewed_at"])
        self.assertEqual(self.editorial["comparison"]["changes"], [])
        for row in companies:
            self.assertTrue(row["summary"], row["ticker"])
            self.assertGreaterEqual(len(row["evidence"]), 3, row["ticker"])
            self.assertTrue(row["watch"], row["ticker"])
            self.assertTrue(row["source_url"].startswith(("https://www.sec.gov/", "https://www.nokia.com/")))
            coverage = row["coverage"]
            self.assertIn("ownership_accession", coverage, row["ticker"])
            self.assertTrue(coverage["quarterly_key"], row["ticker"])
            self.assertTrue(coverage["thesis_fingerprint"], row["ticker"])
            self.assertIsInstance(coverage["enforcement_keys"], list, row["ticker"])
        required_copy = [
            'id="secEditorial"', "function renderSecEditorial()",
            "人工消化後的每日綜合重點", "目前實際持股閱讀順序",
            "今日已人工消化", "非今日覆核稿", "人工稿不會假裝即時自動判讀",
            "renderSecEditorial();", "merger_stock_consideration",
        ]
        for phrase in required_copy:
            self.assertIn(phrase, self.html)
        amzn = next(row for row in companies if row["ticker"] == "AMZN")
        self.assertIn("Globalstar", amzn["summary"])
        self.assertIn("條件式", " ".join(amzn["evidence"]))

    def test_editorial_changes_holdings_groups_and_cross_company_rankings(self):
        required_copy = [
            "function renderSecEditorialChanges(editorial)",
            "相較前次判讀有什麼改變",
            "只會列出新增風險、改善與結論變化",
            "未變項目不重複列出",
            "new Set(['risk', 'improvement', 'conclusion'])",
            "const SEC_OWNED_TICKERS = new Set(userHoldings.map",
            "💼 實際持股｜優先看部位風險",
            "👀 觀察名單",
            "function secHoldingPosition(ticker, companyTone)",
            "持有 ${formatSecNumber(position.holding.shares",
            'id="secCrossCompany"',
            "function secCrossCompanyRows()",
            "function renderSecCrossCompany()",
            "營收 YoY<br>#1＝成長最高",
            "毛利率<br>#1＝最高",
            "FCF 率<br>#1＝最高",
            "稀釋股數 YoY<br>#1＝風險最高",
            "估值警戒<br>#1＝不確定性最高",
            "跨幣別只比較比率、不直接比較金額",
            "renderSecCrossCompany();",
        ]
        for phrase in required_copy:
            self.assertIn(phrase, self.html)
        actual = {"ARM", "COHR", "GOOG", "INTC", "MRVL", "NOK", "NVDA", "TSLA"}
        self.assertEqual(set(self.editorial["portfolio_order"]), actual)
        self.assertNotIn("ONDS", self.editorial["portfolio_order"])

    def test_daily_reading_order_uses_ai_editorial_status_without_local_tracking(self):
        required_copy = [
            "本區只列出閱讀先後，不建立待辦或人工列管",
            "✅ AI 已讀，已記錄重點",
            "最新重點涵蓋 ${aiReadCount}／${rows.length} 家",
            "const editorialByTicker = new Map",
            "function secAiEditorialStatus(displayTicker, editorialByTicker, data = secDailyData)",
            "🟠 有新資料，待 AI 重讀",
            "event.detected_at", "event.accepted_at",
            "quarterlyKey !== coverage.quarterly_key",
            "thesis.fingerprint !== coverage.thesis_fingerprint",
            "latestOwnership.accession !== coverage.ownership_accession",
            "coveredEnforcement.has(key)",
            "若覆核後偵測到新增或覆蓋指紋改變",
        ]
        for phrase in required_copy:
            self.assertIn(phrase, self.html)
        forbidden_copy = [
            "SEC_READING_STORAGE_KEY", "secDailyReadingProgress.v1",
            "function toggleSecCompanyReading", "goToNextUnreadSecCompany",
            "completeCurrentAndNextSecCompany", "data-sec-read-toggle",
        ]
        for phrase in forbidden_copy:
            self.assertNotIn(phrase, self.html)

    def test_eight_quarter_objective_diagnosis_uses_actual_thresholds_and_queue(self):
        required_copy = [
            'id="secQuarterlyDiagnosis"',
            "function secQuarterlyTrendAnalysis(company)",
            "function secTrendStreak(periods, metric, mode = 'percent', threshold = 0)",
            "function renderSecQuarterlyDiagnosis(company)",
            "八季財務趨勢自動判讀",
            "營收連續下降",
            "毛利率連續惡化",
            "營業利益率連續為負",
            "FCF 由正轉負",
            "FCF 連續為負",
            "稀釋股數年增至少 10%",
            "營收連降至少 3 季或 YoY ≤ -10%",
            "此判讀只描述已公布數字，不預測股價或未來業績",
            "八季財務警報 ${financialTrend.alerts.length} 項",
            "已提高每日閱讀排序",
        ]
        for phrase in required_copy:
            self.assertIn(phrase, self.html)
        self.assertIn("financialTrend.queueAlert", self.html)
        self.assertIn("renderSecQuarterlyDiagnosis(company);", self.html)

    def test_investment_thesis_tracker_has_company_rules_history_and_queue(self):
        self.assertEqual(set(self.thesis_tracking["companies"]), set(self.quarterly["companies"]))
        self.assertEqual(set(self.thesis_status["companies"]), set(self.quarterly["companies"]))
        self.assertEqual(self.thesis_tracking["schema_version"], 1)
        allowed_metrics = {"revenue_growth", "gross_margin", "operating_margin", "cash_dilution"}
        for ticker, company in self.thesis_tracking["companies"].items():
            self.assertEqual(len(company["theses"]), 3, ticker)
            self.assertTrue((ROOT / company["master_report"]).exists(), ticker)
            self.assertEqual(len({thesis["id"] for thesis in company["theses"]}), 3, ticker)
            for thesis in company["theses"]:
                self.assertIn(thesis["metric"], allowed_metrics)
                self.assertTrue(thesis["title"])
                self.assertTrue(thesis["rationale"])
                self.assertTrue(thesis["invalidation"])
        required_copy = [
            'id="secThesisTracker"',
            "function secInvestmentThesisSnapshot(company, config, offset = 0)",
            "function secInvestmentThesisAnalysis(company, config)",
            "function secInvestmentThesisForTicker(ticker)",
            "function renderSecThesisTracker()",
            "投資論點與失效條件追蹤卡",
            "最近四季論點狀態歷史",
            "狀態變更日誌",
            "🟢 論點維持", "🔵 需要驗證", "🟡 部分失效", "🔴 重大失效",
            "0 項失效且至少 2 項支持＝論點維持",
            "狀態變化或任何失效項目會提高每日閱讀排序",
            "renderSecThesisTracker();",
            "GitHub Issue 只在分類真的改變時建立",
        ]
        for phrase in required_copy:
            self.assertIn(phrase, self.html)
        self.assertIn("Array.from({ length: 4 }", self.html)
        self.assertIn("investmentThesis.queueAlert", self.html)

    def test_eight_quarter_financial_chart_has_metric_switching_and_units(self):
        self.assertTrue(all(len(company.get("periods", [])) >= 8 for company in self.quarterly["companies"].values()))
        required_copy = [
            'id="chartSecQuarterly"',
            'id="secQuarterlyChartSummary"',
            "function setSecQuarterlyMetric(metric)",
            "function renderSecQuarterlyChart(company)",
            "function secQuarterlyMetricConfig(metric, currency)",
            "data-sec-quarterly-metric=\"revenue\"",
            "data-sec-quarterly-metric=\"gross_margin\"",
            "data-sec-quarterly-metric=\"operating_margin\"",
            "data-sec-quarterly-metric=\"free_cash_flow\"",
            "data-sec-quarterly-metric=\"diluted_shares\"",
            "const periods = [...newestFirst].reverse()",
            "橫軸每一格是一個財報季度",
            "缺值會留白，不以 0 補值",
            "const amount = secAmountDisplay(currency)",
            "free_cash_flow: { label: '自由現金流', divisor: amount.divisor, unit: `${currency} ${amount.unit}`, deltaMode: 'absolute'",
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

    def test_mobile_sec_filters_and_portfolio_chart_do_not_force_page_overflow(self):
        required_copy = [
            'class="portfolio-allocation-layout"',
            'class="portfolio-allocation-table-wrap"',
            'class="portfolio-allocation-chart-card"',
            'class="portfolio-allocation-chart-wrap"',
            '.portfolio-allocation-layout { grid-template-columns: minmax(0, 1fr); }',
            '.macd-result-display { grid-template-columns: minmax(0, 1fr); }',
            '.sec-section-filter { width: 100%; flex-wrap: wrap; }',
            '.sec-section-filter .sec-quarterly-select { flex: 1 1 130px; min-width: 0; max-width: 100%; }',
            '#liveMACDChart { max-width: 100%; }',
            '#chartPortfolioPie { max-width: 100%; }',
        ]
        for marker in required_copy:
            self.assertIn(marker, self.html)
        self.assertNotIn(
            'style="display: grid; grid-template-columns: 2fr 1fr; gap: 24px; align-items: start;"',
            self.html,
        )


if __name__ == "__main__":
    unittest.main()
