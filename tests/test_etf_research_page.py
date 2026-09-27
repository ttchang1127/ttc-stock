import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class EtfResearchPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "etf_research.html").read_text()
        cls.script = (ROOT / "assets/etf_research.js").read_text()
        cls.rotation_html = (ROOT / "market_rotation.html").read_text()
        cls.rotation_script = (ROOT / "assets/market_rotation_research.js").read_text()

    def test_page_loads_its_own_script_and_the_shared_styles(self):
        self.assertIn('src="assets/etf_research.js"', self.html)
        self.assertIn('href="assets/market_rotation.css"', self.html)
        self.assertNotIn("market_rotation_legacy.js", self.html, "the ETF page does not need the rotation charts")

    def test_every_etf_section_lives_here(self):
        for element in ("etfOverview", "etfHealthBody", "etfHealthNote", "themeSignalSummary", "etfMomentumSummary",
                        "etfAsOf"):
            self.assertIn(f'id="{element}"', self.html)
        for path in ("etf_health.json", "market_rotation_history/backtest/theme_etf_signals.json",
                     "market_rotation_history/backtest/sector_etf_momentum.json"):
            self.assertIn(f"'{path}'", self.script)
        for renderer in ("renderOverview", "renderEtfHealth", "renderThemeSignals", "renderEtfMomentum"):
            self.assertIn(f"function {renderer}(", self.script)

    def test_the_rotation_page_no_longer_carries_etf_sections(self):
        for element in ("etfHealthBody", "themeSignalSummary", "etfMomentumSummary"):
            self.assertNotIn(element, self.rotation_html)
            self.assertNotIn(element, self.rotation_script)
        self.assertIn('href="etf_research.html"', self.rotation_html, "the rotation page links to the ETF page")

    def test_pages_link_both_ways(self):
        self.assertIn('href="market_rotation.html"', self.html)
        self.assertIn('href="dashboard.html"', self.html)
        self.assertIn('href="etf_research.html"', (ROOT / "dashboard.html").read_text())

    def test_every_missing_file_has_a_plain_message(self):
        for message in ("尚未產出 etf_health.json", "主題 ETF 訊號回測尚未執行", "板塊 ETF 中期動能回測尚未執行"):
            self.assertIn(message, self.script)

    def test_the_page_says_it_does_not_predict(self):
        self.assertIn("不是買賣訊號", self.html)
        self.assertIn("不預測下個月", self.script)


if __name__ == "__main__":
    unittest.main()
