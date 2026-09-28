import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class TechnologyResearchPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "etf_research.html").read_text()
        cls.script = (ROOT / "assets/tech_stock_map.js").read_text()
        cls.archive = (ROOT / "etf_research_archive.html").read_text()
        cls.archive_script = (ROOT / "assets/etf_research.js").read_text()

    def test_new_page_loads_dated_stock_map_and_shares_existing_styles(self):
        self.assertRegex(self.html, r'src="assets/tech_stock_map\.js\?v=\w+"')
        self.assertRegex(self.html, r'href="assets/tech_stock_map\.css\?v=\w+"')
        self.assertIn("'tech_stock_map.json'", self.script)
        for element in ("techMap", "techBreadth", "techDetail", "techEtfs", "techFocus", "techAsOf"):
            self.assertIn(f'id="{element}"', self.html)

    def test_map_supports_nested_industry_zoom_search_and_equal_area(self):
        for piece in ("function squarify(", "data-focus", "data-ticker", "techSearch",
                      "techAdjacent", "techEqual", "function renderBreadth("):
            self.assertIn(piece, self.script)
        for period in ("1d", "1w", "1m", "3m", "6m"):
            self.assertIn(f'data-period="{period}"', self.html)
        self.assertIn("科技 ETF 參考指標", self.html)
        self.assertNotIn('id="etfHealthBody"', self.html)

    def test_header_only_keeps_the_market_date(self):
        self.assertNotIn('href="dashboard.html"', self.html)
        self.assertNotIn('href="market_rotation.html"', self.html)
        self.assertIn('id="techAsOf"', self.html)

    def test_old_etf_research_and_backtests_remain_available(self):
        self.assertIn('href="etf_research_archive.html"', self.html)
        for element in ("etfOverview", "etfHealthBody", "themeSignalSummary", "etfMomentumSummary"):
            self.assertIn(f'id="{element}"', self.archive)
        for path in ("etf_health.json", "etf_constituents.json",
                     "market_rotation_history/backtest/theme_etf_signals.json"):
            self.assertIn(f"'{path}'", self.archive_script)
        self.assertIn('href="etf_research.html"', (ROOT / "dashboard.html").read_text())
        self.assertIn('href="etf_research.html"', (ROOT / "market_rotation.html").read_text())

    def test_page_explains_method_and_missing_file(self):
        for piece in ("100 億美元", "GOOG／GOOGL", "未調整股息或拆股", "未驗證預測能力"):
            self.assertIn(piece, self.html)
        self.assertIn('科技股資料尚未產出', self.script)


if __name__ == "__main__":
    unittest.main()
