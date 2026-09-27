import copy
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import etf_holdings  # noqa: E402
import portfolio_rotation  # noqa: E402
import refresh_etf_holdings  # noqa: E402

UNIVERSE = {"members": [
    {"ticker": "NVDA", "name": "Nvidia", "sector": "Information Technology", "industry": "Semiconductors",
     "classification": "GICS", "indexes": ["S&P 500"]},
    {"ticker": "AAPL", "name": "Apple Inc.", "sector": "Information Technology",
     "industry": "Technology Hardware", "classification": "GICS", "indexes": ["S&P 500"]},
    {"ticker": "MSFT", "name": "Microsoft", "sector": "Information Technology", "industry": "Software",
     "classification": "GICS", "indexes": ["S&P 500"]},
    {"ticker": "JPM", "name": "JPMorgan Chase", "sector": "Financials", "industry": "Banks",
     "classification": "GICS", "indexes": ["S&P 500"]},
]}


def holding(name, weight, ticker=None, isin=None):
    ids = ""
    if ticker or isin:
        ids = "<identifiers>" + (f'<isin value="{isin}"/>' if isin else "") + \
              (f'<ticker value="{ticker}"/>' if ticker else "") + "</identifiers>"
    return (f"<invstOrSec><name>{name}</name><title>{name} COM</title><cusip>000000000</cusip>{ids}"
            f"<balance>10</balance><units>NS</units><valUSD>{weight * 1000}</valUSD><pctVal>{weight}</pctVal>"
            "<assetCat>EC</assetCat></invstOrSec>")


def nport(series="S000001", rows=None, filler=60, report="2026-06-30"):
    rows = rows if rows is not None else [
        holding("NVIDIA CORP", 20.0, ticker="NVDA US"), holding("Apple Inc", 15.0),
        holding("MICROSOFT CORP", 10.0, ticker="MSFT"), holding("Tiny Software Co", 4.0)]
    listed = sum(float(r.split("<pctVal>")[1].split("<")[0]) for r in rows)
    each = (99.5 - listed) / filler if filler else 0
    rows = rows + [holding(f"Small Cap {n}", round(each, 6)) for n in range(filler)]
    return ('<?xml version="1.0"?><edgarSubmission xmlns="http://www.sec.gov/edgar/nport">'
            "<headerData><seriesClassInfo><seriesId>" + series + "</seriesId></seriesClassInfo></headerData>"
            "<formData><genInfo><regName>Test Trust</regName><seriesName>Test IT Fund</seriesName>"
            f"<seriesId>{series}</seriesId><repPdEnd>2026-09-30</repPdEnd><repPdDate>{report}</repPdDate>"
            "</genInfo><fundInfo><totAssets>1000</totAssets><netAssets>990</netAssets></fundInfo>"
            "<invstOrSecs>" + "".join(rows) + "</invstOrSecs></formData></edgarSubmission>")


FUND_INDEX = {"fields": ["cik", "seriesId", "classId", "symbol"],
              "data": [[52848, "S000001", "C000009", "VGT"], [36405, "S000002", "C000010", "VOO"]]}


class ParseTests(unittest.TestCase):
    def test_holdings_map_by_ticker_then_exact_name(self):
        parsed = etf_holdings.parse_nport(nport(), UNIVERSE)
        rows = {row["name"]: row for row in parsed["holdings"]}
        self.assertEqual((rows["NVIDIA CORP"]["ticker"], rows["NVIDIA CORP"]["mapping"]), ("NVDA", "nport_ticker"))
        self.assertEqual((rows["Apple Inc"]["ticker"], rows["Apple Inc"]["mapping"]), ("AAPL", "name_match"))
        self.assertIsNone(rows["Tiny Software Co"]["ticker"], "no guessing for unknown names")
        self.assertEqual(parsed["series_id"], "S000001")
        self.assertEqual(parsed["report_date"], "2026-06-30")
        self.assertEqual(parsed["holdings"][0]["ticker"], "NVDA", "largest weight first")

    def test_identifier_formats(self):
        self.assertEqual(etf_holdings.ticker_from_identifier("BRK/B US"), "BRK.B")
        self.assertEqual(etf_holdings.ticker_from_identifier("aapl"), "AAPL")
        self.assertIsNone(etf_holdings.ticker_from_identifier("N/A"))
        self.assertIsNone(etf_holdings.ticker_from_identifier(""))

    def test_validation_rejects_wrong_series_thin_or_unbalanced_files(self):
        good = etf_holdings.parse_nport(nport(), UNIVERSE)
        self.assertEqual(etf_holdings.validate(good, "S000001"), [])
        self.assertTrue(etf_holdings.validate(good, "S999999"))
        thin = etf_holdings.parse_nport(nport(filler=3), UNIVERSE)
        self.assertTrue(any("holdings" in p for p in etf_holdings.validate(thin, "S000001")))
        half = etf_holdings.parse_nport(nport(rows=[holding("NVIDIA CORP", 20.0, ticker="NVDA")], filler=0),
                                        UNIVERSE)
        self.assertTrue(etf_holdings.validate(half, "S000001"))

    def test_summary(self):
        summary = etf_holdings.summarise(etf_holdings.parse_nport(nport(), UNIVERSE))
        self.assertAlmostEqual(summary["weight_total_pct"], 99.5, places=1)
        self.assertEqual(summary["mapped_weight_pct"], 45.0)
        self.assertEqual(summary["top10_weight_pct"] >= 49, True)


class FetchTests(unittest.TestCase):
    def submissions(self):
        return {"filings": {"recent": {
            "form": ["NPORT-P", "10-K", "NPORT-P", "NPORT-P"],
            "accessionNumber": ["0000-26-000003", "x", "0000-26-000002", "0000-25-000001"],
            "filingDate": ["2026-08-28", "2026-08-01", "2026-08-27", "2026-05-29"],
            "reportDate": ["2026-06-30", "", "2026-06-30", "2026-03-31"]}}}

    def fake_http(self, documents):
        def get_json(url, **kwargs):
            return self.submissions()

        def get_text(url, **kwargs):
            return documents[url.split("/")[-2]]
        return get_json, get_text

    def test_scans_the_trust_for_the_right_series(self):
        docs = {"000026000003": nport(series="S000777"), "000026000002": nport(series="S000001")}
        get_json, get_text = self.fake_http(docs)
        with mock.patch.object(etf_holdings.sec_http, "get_json", get_json), \
                mock.patch.object(etf_holdings.sec_http, "get_text", get_text):
            result = etf_holdings.fetch_latest("VGT", UNIVERSE, FUND_INDEX)
        self.assertEqual((result["accession"], result["series_id"]), ("0000-26-000002", "S000001"))
        self.assertEqual(result["source"], "SEC Form N-PORT (NPORT-P)")

    def test_known_accession_means_nothing_new(self):
        get_json, get_text = self.fake_http({"000026000003": nport(series="S000777")})
        with mock.patch.object(etf_holdings.sec_http, "get_json", get_json), \
                mock.patch.object(etf_holdings.sec_http, "get_text", get_text):
            self.assertIsNone(etf_holdings.fetch_latest("VGT", UNIVERSE, FUND_INDEX, "0000-26-000002"))

    def test_bad_filing_raises_instead_of_returning_partial_data(self):
        docs = {"000026000003": nport(series="S000001", filler=2)}
        get_json, get_text = self.fake_http(docs)
        with mock.patch.object(etf_holdings.sec_http, "get_json", get_json), \
                mock.patch.object(etf_holdings.sec_http, "get_text", get_text), \
                self.assertRaises(ValueError):
            etf_holdings.fetch_latest("VGT", UNIVERSE, FUND_INDEX)


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.directory.name)
        (self.root / "portfolio_classification.json").write_text(json.dumps(
            {"funds_excluded": {"VGT": "ETF", "VOO": "ETF"}, "classification": {}}))
        (self.root / "market_rotation_universe.json").write_text(json.dumps(UNIVERSE))
        self.folder = self.root / "etf_holdings"

    def tearDown(self):
        self.directory.cleanup()

    def record(self, ticker, accession="A1"):
        parsed = etf_holdings.parse_nport(nport(), UNIVERSE)
        return {"etf": ticker, "accession": accession, "report_date": parsed["report_date"], "filed": "2026-08-27",
                "summary": etf_holdings.summarise(parsed), "holdings": parsed["holdings"]}

    def test_new_filings_are_written_and_failures_keep_the_old_file(self):
        def fetch(ticker, universe, index, known):
            if ticker == "VOO":
                raise LookupError("no filing")
            return self.record(ticker)
        texts, messages = refresh_etf_holdings.refresh(self.root, self.folder, fetch, FUND_INDEX)
        self.assertIn(self.folder / "VGT.json", texts)
        self.assertNotIn(self.folder / "VOO.json", texts)
        index = json.loads(texts[self.folder / "index.json"])
        self.assertIn("error", index["funds"]["VOO"])
        self.assertTrue(any(m.startswith("::warning::VOO") for m in messages))

    def test_unchanged_filings_write_nothing(self):
        self.folder.mkdir()
        (self.folder / "VGT.json").write_text(json.dumps(self.record("VGT")))
        (self.folder / "VOO.json").write_text(json.dumps(self.record("VOO")))
        entry = {"accession": "A1", "report_date": "2026-06-30", "filed": "2026-08-27",
                 **self.record("VGT")["summary"]}
        (self.folder / "index.json").write_text(json.dumps({"schema_version": 1,
                                                            "funds": {"VGT": entry, "VOO": entry}}))
        texts, _ = refresh_etf_holdings.refresh(self.root, self.folder, lambda *a: None, FUND_INDEX)
        self.assertEqual(texts, {})


class LookThroughTests(unittest.TestCase):
    def test_funds_are_unpacked_into_tickers_and_sectors(self):
        universe = copy.deepcopy(UNIVERSE)
        overrides = {"funds_excluded": {"VGT": "ETF"}, "fund_sectors": {"VGT": "Information Technology"},
                     "classification": {}}
        registry = {"groups": [
            {"group_id": "sector:information-technology", "group_type": "sector",
             "name_en": "Information Technology", "aliases": []},
            {"group_id": "sector:financials", "group_type": "sector", "name_en": "Financials", "aliases": []}]}
        prices = {"series": {"NVDA": {"dates": ["2026-09-25"], "closes": [100.0]},
                             "JPM": {"dates": ["2026-09-25"], "closes": [100.0]},
                             "VGT": {"dates": ["2026-09-25"], "closes": [100.0]}}}
        holdings = {"holdings": [{"ticker": "NVDA", "shares": 10, "cost": 1}, {"ticker": "JPM", "shares": 10,
                                                                                "cost": 1},
                                 {"ticker": "VGT", "shares": 20, "cost": 1}]}
        parsed = etf_holdings.parse_nport(nport(), universe)
        fund = {"VGT": {"report_date": "2026-06-30", "accession": "A1", "summary": etf_holdings.summarise(parsed),
                        "holdings": parsed["holdings"]}}
        exposure = portfolio_rotation.build_exposure(holdings, prices, universe, overrides, registry, None,
                                                     fund_holdings=fund)
        view = exposure["look_through"]
        self.assertTrue(view["available"])
        self.assertEqual(view["total_value"], 4000.0)
        self.assertEqual(view["direct_share_pct"], 50.0)
        nvda = next(row for row in view["top_positions"] if row["ticker"] == "NVDA")
        self.assertEqual(nvda["direct_weight"], 25.0)
        self.assertEqual(nvda["via_weight"]["VGT"], 10.0)
        self.assertTrue(nvda["overlap"])
        sectors = {row["name"]: row["weight"] for row in view["sectors"]}
        self.assertAlmostEqual(sum(sectors.values()), 100.0, places=1)
        self.assertEqual(sectors["Financials"], 25.0)
        self.assertAlmostEqual(sectors["Information Technology"], 74.75, places=2, msg="unmapped VGT names count as IT")
        self.assertAlmostEqual(sectors["Cash & other"], 0.25, places=2)
        self.assertEqual(exposure["sector_concentration"]["sectors"][0]["weight"], 50.0,
                         "the direct-only view is unchanged")

    def test_share_classes_of_one_issuer_are_one_company(self):
        keys = portfolio_rotation.issuer_keys({"members": [
            {"ticker": "GOOG", "name": "Alphabet Inc."}, {"ticker": "GOOGL", "name": "Alphabet Inc."},
            {"ticker": "NVDA", "name": "Nvidia"}]})
        self.assertEqual((keys["GOOG"], keys["GOOGL"], keys["NVDA"]), ("GOOG/GOOGL", "GOOG/GOOGL", "NVDA"))
        view = portfolio_rotation.look_through_view(
            {"holdings": [{"ticker": "GOOG", "shares": 1}, {"ticker": "VOO", "shares": 1}]},
            {"VOO": {"closes": [100.0]}}, {"funds_excluded": {"VOO": "ETF"}},
            {"GOOG": {"sector": "Communication Services"}}, {}, {},
            {"VOO": {"report_date": "2026-06-30", "accession": "A", "summary": {"mapped_weight_pct": 100,
                                                                                "top10_weight_pct": 100},
                     "holdings": [{"ticker": "GOOGL", "weight_pct": 60.0}, {"ticker": "GOOG", "weight_pct": 40.0}]}},
            {"GOOG": 100.0}, keys)
        self.assertEqual([row["ticker"] for row in view["top_positions"]], ["GOOG/GOOGL"])
        self.assertEqual(view["top_positions"][0]["weight"], 100.0)
        self.assertEqual(view["sectors"][0]["name"], "Communication Services")

    def test_without_fund_files_the_view_says_so(self):
        exposure_view = portfolio_rotation.look_through_view(
            {"holdings": [{"ticker": "VGT", "shares": 1}]}, {"VGT": {"closes": [1.0]}},
            {"funds_excluded": {"VGT": "ETF"}}, {}, {}, {}, {}, {})
        self.assertFalse(exposure_view["available"])
        self.assertEqual(exposure_view["missing_funds"], ["VGT"])


if __name__ == "__main__":
    unittest.main()
