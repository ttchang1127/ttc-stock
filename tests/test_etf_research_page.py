import json
import pathlib
import unittest
from datetime import date

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

    def test_manual_evidence_cards_have_traceable_sources_and_no_false_d_grade(self):
        evidence = json.loads((ROOT / 'tech_stock_evidence.json').read_text())
        tickers = {stock['ticker'] for stock in json.loads((ROOT / 'tech_stock_map.json').read_text())['stocks']}
        self.assertIn("'tech_stock_evidence.json'", self.script)
        self.assertIn('不代表證據為 D 級', self.script)
        self.assertEqual(evidence['schema_version'], 1)
        self.assertTrue((ROOT / '30_Analysis/Tech_Stock_Map_Evidence_Source_Index.md').is_file())
        self.assertIn('Tech_Stock_Map_Evidence_Source_Index.md', evidence['kb_index_url'])
        reviewed = date.fromisoformat(evidence['reviewed_at'])
        for ticker, card in evidence['cards'].items():
            with self.subTest(ticker=ticker):
                self.assertIn(ticker, tickers)
                self.assertIn(card['grade'], {'A', 'B', 'C', 'D'})
                for stage in ('demand', 'order', 'revenue', 'profit'):
                    self.assertTrue(card['pathway'][stage])
                for field in ('evidence_scope', 'research_inference', 'counterevidence', 'next_check'):
                    self.assertTrue(card[field])
                self.assertTrue(card['sources'])
                for source in card['sources']:
                    self.assertTrue(source['url'].startswith('https://'))
                    self.assertLessEqual(date.fromisoformat(source['published_at']), reviewed)
                    self.assertTrue(source['period'])

    def test_sec_review_status_separates_claims_from_whole_filing_review(self):
        review = json.loads((ROOT / 'tech_stock_sec_review.json').read_text())
        stocks = {stock['ticker'] for stock in json.loads((ROOT / 'tech_stock_map.json').read_text())['stocks']}
        self.assertIn('id="techSecSummary"', self.html)
        self.assertIn("'tech_stock_sec_review.json'", self.script)
        self.assertTrue(stocks <= review['companies'].keys())
        self.assertEqual(review['scope'], {
            'companies_cached': 182, 'filings_cached': 885,
            'representative_companies': 113, 'representative_claims': 224,
            'whole_filings_reviewed': 0,
        })
        self.assertEqual(sum(row['cached_filings'] for row in review['companies'].values()), 885)
        self.assertEqual(sum(row['representative_review'] is not None for row in review['companies'].values()), 113)
        for ticker, row in review['companies'].items():
            with self.subTest(ticker=ticker):
                self.assertEqual(row['document_review'], 'not_reviewed')
                claim = row['representative_review']
                if not claim:
                    continue
                for key in ('revenue', 'annual_business'):
                    source = claim[key]['source']
                    if source:
                        self.assertTrue(source['url'].startswith('https://www.sec.gov/Archives/'))
                        self.assertLessEqual(date.fromisoformat(source['filing_date']),
                                             date.fromisoformat(review['reviewed_at']))
                self.assertEqual(claim['annual_business']['status'], 'checked')
        for ticker in ('CYBR', 'SAP'):
            self.assertEqual(review['companies'][ticker]['representative_review']['revenue']['status'], 'source_gap')
        self.assertIsNone(review['companies']['AVGO']['representative_review'])
        self.assertIn('coverage_exception', review['companies']['CBRS'])

    def test_research_observations_match_the_frozen_price_snapshot(self):
        notes = json.loads((ROOT / 'tech_stock_research_notes.json').read_text())
        snapshot = json.loads((ROOT / notes['price_source']).read_text())
        self.assertEqual(snapshot['as_of'], notes['price_as_of'])
        self.assertIn("'tech_stock_research_notes.json'", self.script)
        benchmark = notes['group_context']['vgt_one_month_pct']
        for category in ('leader', 'follow_on'):
            for row in notes['lists'][category]:
                with self.subTest(category=category, ticker=row['ticker']):
                    actual = snapshot['candidates'][row['ticker']]['returns_raw_pct']['1m']
                    self.assertAlmostEqual(actual, row['one_month_return_pct'], places=2)
                    self.assertAlmostEqual(actual - benchmark, row['one_month_vs_vgt_pp'], places=2)
        context = notes['group_context']
        group_id = snapshot['candidates']['MRVL']['group_id']
        members = [row for row in snapshot['candidates'].values()
                   if row['included'] and row['group_id'] == group_id and row['returns_raw_pct']['1m'] is not None]
        self.assertEqual(len(members), context['ticker_count'])
        self.assertEqual(sum(row['returns_raw_pct']['1m'] > 0 for row in members), context['one_month_up_count'])
        self.assertAlmostEqual(sum(row['returns_raw_pct']['1m'] for row in members) / len(members),
                               context['one_month_equal_pct'], places=2)
        cap = sum(row['market_cap_usd'] for row in members)
        weighted = sum(row['returns_raw_pct']['1m'] * row['market_cap_usd'] for row in members) / cap
        self.assertAlmostEqual(weighted, context['one_month_cap_weighted_pct'], places=2)
        self.assertEqual(notes['lists']['laggard'], [])


if __name__ == "__main__":
    unittest.main()
