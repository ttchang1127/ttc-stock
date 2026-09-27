import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class DashboardDataHealthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / "dashboard.html").read_text()

    def test_strip_sits_under_the_header_with_three_sources(self):
        header_end = self.page.index("</header>")
        strip = self.page.index('id="dataHealthStrip"')
        tabs = self.page.index("<!-- Navigation Tabs -->")
        self.assertLess(header_end, strip)
        self.assertLess(strip, tabs, "the strip must be visible before any tab content")
        self.assertEqual(re.findall(r'data-health="([a-z]+)"', self.page), ["prices", "rotation", "sec"])

    def test_sources_are_heartbeats_not_content_timestamps(self):
        self.assertIn("latestCoveredSession()", self.page)
        self.assertIn("fetchJSON('market_rotation_summary.json')", self.page)
        self.assertIn("fetchJSON('sec_filing_alerts.json')", self.page)
        self.assertIn("renderDataHealth();\n  </script>", self.page)

    def test_states_are_labelled_with_text_not_only_colour(self):
        for label in ("✅ 正常", "🟠 可能過期", "❔ 無法讀取"):
            self.assertIn(label, self.page)
        self.assertIn("const DATA_HEALTH_MAX_AGE_DAYS = 4;", self.page)
        self.assertIn("每日巡檢會依 NYSE 交易日精確判斷", self.page)

    def test_rotation_briefing_sits_before_the_tabs_and_links_the_page(self):
        briefing = self.page.index('id="rotationBriefing"')
        self.assertLess(self.page.index('id="dataHealthStrip"'), briefing)
        self.assertLess(briefing, self.page.index("<!-- Navigation Tabs -->"))
        self.assertIn('<a id="rotationBriefing" class="rotation-brief" href="market_rotation.html"', self.page)
        self.assertIn("fetchJSON('market_rotation_daily_digest.json')", self.page)
        self.assertIn("fetchJSON('portfolio_equity_exposure.json')", self.page)
        self.assertIn("市場環境研究層尚未產出", self.page)
        self.assertIn("研究中", self.page)

    def test_no_fake_data_generators(self):
        self.assertEqual(len(re.findall(r"Math\.sin|Math\.random|seedMap", self.page)), 0)


if __name__ == "__main__":
    unittest.main()
