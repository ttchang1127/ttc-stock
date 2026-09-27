import copy
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock
from xml.sax.saxutils import escape

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
    name = escape(name)
    return (f"<invstOrSec><name>{name}</name><title>{name} COM</title><cusip>000000000</cusip>{ids}"
            f"<balance>10</balance><units>NS</units><valUSD>{weight * 1000}</valUSD><pctVal>{weight}</pctVal>"
            "<assetCat>EC</assetCat></invstOrSec>")


def nport(series="S000001", rows=None, filler=60, report="2026-06-30", flows=""):
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
            "</genInfo><fundInfo><totAssets>1000</totAssets><netAssets>990</netAssets>" + flows + "</fundInfo>"
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
        self.assertEqual(etf_holdings.ticker_from_identifier("AAPL UW"), "AAPL")
        self.assertIsNone(etf_holdings.ticker_from_identifier("CCO CN"), "Cameco's Toronto code is not US 'CCO'")
        self.assertEqual(etf_holdings.ticker_from_identifier("aapl"), "AAPL")
        self.assertIsNone(etf_holdings.ticker_from_identifier("N/A"))
        self.assertIsNone(etf_holdings.ticker_from_identifier(""))

    def test_sec_company_names_map_what_the_universe_short_names_miss(self):
        # Real VOO/VGT 2026 names that the universe's short names ("Amazon", "Lilly (Eli)") did not match.
        sec = etf_holdings.sec_name_index({
            "0": {"cik_str": 1, "ticker": "AMZN", "title": "AMAZON COM INC"},
            "1": {"cik_str": 2, "ticker": "LLY", "title": "ELI LILLY & Co"},
            "2": {"cik_str": 3, "ticker": "SNDK", "title": "Sandisk Corp"},
            "3": {"cik_str": 4, "ticker": "TJX", "title": "TJX COMPANIES INC /DE/"},
            "4": {"cik_str": 5, "ticker": "GOOGL", "title": "Alphabet Inc."},
            "5": {"cik_str": 5, "ticker": "GOOG", "title": "Alphabet Inc."},
            "6": {"cik_str": 6, "ticker": "BRK-B", "title": "BERKSHIRE HATHAWAY INC"}})
        self.assertEqual(sec["alphabet"], "GOOGL", "the first listing of an issuer wins")
        self.assertEqual(sec["berkshire hathaway"], "BRK.B")
        rows = [holding("Amazon.com Inc", 5.0), holding("Eli Lilly & Co", 4.0), holding("Sandisk Corp/DE", 3.0),
                holding("TJX Cos Inc/The", 2.0), holding("Apple Inc", 6.0), holding("Unknown Plc", 1.0)]
        parsed = etf_holdings.parse_nport(nport(rows=rows), UNIVERSE, sec)
        got = {row["name"]: (row["ticker"], row["mapping"]) for row in parsed["holdings"]}
        self.assertEqual(got["Amazon.com Inc"], ("AMZN", "sec_name"))
        self.assertEqual(got["Eli Lilly & Co"], ("LLY", "sec_name"))
        self.assertEqual(got["Sandisk Corp/DE"], ("SNDK", "sec_name"))
        self.assertEqual(got["TJX Cos Inc/The"], ("TJX", "sec_name"))
        self.assertEqual(got["Apple Inc"], ("AAPL", "name_match"), "the universe is still tried first")
        self.assertEqual(got["Unknown Plc"], (None, None))
        summary = etf_holdings.summarise(parsed)
        self.assertEqual(summary["mapped_by"]["sec_name"], 14.0)

    def test_monthly_flows_from_item_b6(self):
        flows = ('<mon1Flow sales="500" reinvestment="0" redemption="200"/>'
                 '<mon2Flow><sales>100</sales><reinvestment>5</reinvestment><redemption>300</redemption></mon2Flow>'
                 '<mon3Flow sales="N/A" reinvestment="0" redemption="10"/>')
        parsed = etf_holdings.parse_nport(nport(flows=flows, report="2026-02-28"), UNIVERSE)
        self.assertEqual([row["month"] for row in parsed["monthly_flows"]], ["2025-12", "2026-01", "2026-02"],
                         "month 3 ends on the report date, across the year boundary")
        self.assertEqual(parsed["monthly_flows"][0]["net_usd"], 300.0)
        self.assertEqual(parsed["monthly_flows"][1]["net_usd"], -195.0, "attributes or child elements")
        self.assertIsNone(parsed["monthly_flows"][2]["net_usd"], "a missing figure is not read as zero")
        self.assertEqual(etf_holdings.parse_nport(nport(), UNIVERSE)["monthly_flows"], [])

    def test_securities_lending_collateral_does_not_fail_validation(self):
        # TAN 2024-25: reinvested collateral took all positions to 134% of net assets.
        collateral = holding("State Street Navigator Securities Lending", 34.0).replace("<assetCat>EC",
                                                                                         "<assetCat>STIV")
        document = nport(rows=[holding("NVIDIA CORP", 20.0, ticker="NVDA US")], filler=20)
        document = document.replace("</invstOrSecs>", collateral + "</invstOrSecs>")
        parsed = etf_holdings.parse_nport(document, UNIVERSE)
        self.assertAlmostEqual(sum(row["weight_pct"] for row in parsed["holdings"]), 133.5, places=1)
        self.assertEqual(etf_holdings.validate(parsed, "S000001"), [])
        stock_light = etf_holdings.parse_nport(nport(rows=[
            holding("Cash Sweep", 60.0).replace("<assetCat>EC", "<assetCat>STIV")], filler=20), UNIVERSE)
        self.assertTrue(any("common stock" in p for p in etf_holdings.validate(stock_light, "S000001")))

    def test_validation_rejects_wrong_series_thin_or_unbalanced_files(self):
        good = etf_holdings.parse_nport(nport(), UNIVERSE)
        self.assertEqual(etf_holdings.validate(good, "S000001"), [])
        self.assertTrue(etf_holdings.validate(good, "S999999"))
        thin = etf_holdings.parse_nport(nport(filler=3, rows=[holding("NVIDIA CORP", 20.0)]), UNIVERSE)
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
        get_json, get_text = self.fake_http({"000026000003": nport(series="S000777"),
                                             "000026000002": nport(series="S000001")})
        with mock.patch.object(etf_holdings.sec_http, "get_json", get_json), \
                mock.patch.object(etf_holdings.sec_http, "get_text", get_text):
            self.assertIsNone(etf_holdings.fetch_latest("VGT", UNIVERSE, FUND_INDEX, "0000-26-000002"))

    def test_series_feed_is_used_before_scanning_the_trust(self):
        feed = ('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
                '<entry><category term="NPORT-P"/><content type="text/xml"><accession-number>0000-26-000009'
                '</accession-number><filing-date>2026-08-29</filing-date><filing-type>NPORT-P</filing-type>'
                '</content></entry>'
                '<entry><content><accession-number>0000-26-000008</accession-number><filing-date>2026-08-30'
                '</filing-date><filing-type>NPORT-P/A</filing-type></content></entry></feed>')
        self.assertEqual([row["accession"] for row in etf_holdings.series_feed(feed)], ["0000-26-000009"],
                         "amendments are not read as the regular filing")
        urls = []

        def get_text(url, **kwargs):
            urls.append(url)
            return feed if "browse-edgar" in url else nport(series="S000001")

        def get_json(url, **kwargs):
            raise AssertionError("the trust list is not needed when the series feed answers")
        with mock.patch.object(etf_holdings.sec_http, "get_json", get_json), \
                mock.patch.object(etf_holdings.sec_http, "get_text", get_text):
            result = etf_holdings.fetch_latest("VGT", UNIVERSE, FUND_INDEX, sec_names={})
        self.assertEqual((result["accession"], result["lookup"]), ("0000-26-000009", "series_feed"))
        self.assertEqual(result["mapping_version"], etf_holdings.MAPPING_VERSION)
        self.assertIn("CIK=S000001", urls[0])

    def test_bad_filing_raises_instead_of_returning_partial_data(self):
        docs = {"000026000003": nport(series="S000001", filler=2)}
        get_json, get_text = self.fake_http(docs)
        with mock.patch.object(etf_holdings.sec_http, "get_json", get_json), \
                mock.patch.object(etf_holdings.sec_http, "get_text", get_text), \
                self.assertRaises(ValueError):
            etf_holdings.fetch_latest("VGT", UNIVERSE, FUND_INDEX)


class HistoryTests(unittest.TestCase):
    def feed(self, accessions):
        entries = "".join(f"<entry><content><accession-number>{acc}</accession-number><filing-date>{filed}"
                          "</filing-date><filing-type>NPORT-P</filing-type></content></entry>"
                          for acc, filed in accessions)
        return f'<feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'

    def test_history_reads_only_unknown_filings_and_records_bad_ones(self):
        feed = self.feed([("0000-26-000003", "2026-08-28"), ("0000-26-000002", "2026-05-28"),
                          ("0000-25-000001", "2025-11-26")])
        docs = {"000026000003": nport(report="2026-06-30"), "000026000002": nport(filler=2, report="2026-03-31")}
        fetched = []

        def get_text(url, **kwargs):
            if "browse-edgar" in url:
                return feed
            fetched.append(url.split("/")[-2])
            return docs[url.split("/")[-2]]
        with mock.patch.object(etf_holdings.sec_http, "get_text", get_text):
            entries, skipped = etf_holdings.fetch_history("VGT", UNIVERSE, FUND_INDEX, {}, {"0000-25-000001"})
        self.assertEqual(fetched, ["000026000003", "000026000002"], "a known accession is not downloaded")
        self.assertEqual([row["report_date"] for row in entries], ["2026-06-30"])
        self.assertEqual(entries[0]["weights"]["NVDA"], 20.0)
        self.assertNotIn(None, entries[0]["weights"])
        self.assertEqual([row["accession"] for row in skipped], ["0000-26-000002"])

    def test_merge_only_appends(self):
        history = {"etf": "SMH", "filings": [{"accession": "A2", "report_date": "2026-06-30", "filed": "2026-08-28",
                                              "weights": {"NVDA": 20.0}}], "skipped": []}
        merged = etf_holdings.merge_history(history, [
            {"accession": "A2", "report_date": "2026-06-30", "filed": "2026-08-28", "weights": {"NVDA": 99.0}},
            {"accession": "A1", "report_date": "2026-03-31", "filed": "2026-05-28", "weights": {"NVDA": 18.0}}],
            [{"accession": "X", "filed": "2026-01-01", "reason": "bad"}])
        self.assertEqual([row["accession"] for row in merged["filings"]], ["A1", "A2"])
        self.assertEqual(merged["filings"][1]["weights"]["NVDA"], 20.0, "a recorded filing is never replaced")
        self.assertEqual(etf_holdings.validate_history(merged), [])
        self.assertEqual(merged["skipped"], [{"accession": "X", "filed": "2026-01-01", "reason": "bad"}])
        self.assertEqual(etf_holdings.retry_skipped(merged), {"X"}, "skipped under older rules is retried")
        retried = etf_holdings.merge_history(merged, [
            {"accession": "X", "report_date": "2025-12-31", "filed": "2026-01-01", "weights": {}}], [])
        self.assertEqual([row["accession"] for row in retried["filings"]], ["X", "A1", "A2"])
        self.assertEqual(retried["skipped"], [], "a retried filing that passes leaves the skipped list")
        again = etf_holdings.merge_history(merged, [], [
            {"accession": "X", "filed": "2026-01-01", "reason": "still bad",
             "validation_version": etf_holdings.VALIDATION_VERSION}])
        self.assertEqual(again["skipped"][0]["reason"], "still bad")
        self.assertEqual(etf_holdings.retry_skipped(again), set())
        broken = {**merged, "filings": merged["filings"][::-1]}
        self.assertTrue(etf_holdings.validate_history(broken))


class RefreshTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(etf_holdings, "THEME_ETFS", {})
        patcher.start()
        self.addCleanup(patcher.stop)
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
        def fetch(ticker, universe, index, known, sec_names):
            if ticker == "VOO":
                raise LookupError("no filing")
            return self.record(ticker)
        texts, messages = refresh_etf_holdings.refresh(self.root, self.folder, fetch, FUND_INDEX, {})
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
        texts, _ = refresh_etf_holdings.refresh(self.root, self.folder, lambda *a: None, FUND_INDEX, {})
        self.assertEqual(texts, {})

    def test_without_the_sec_company_list_nothing_is_rewritten(self):
        def fail(url, **kwargs):
            raise OSError("down")
        with mock.patch.object(refresh_etf_holdings.sec_http, "get_json", fail):
            texts, messages = refresh_etf_holdings.refresh(self.root, self.folder, lambda *a: self.fail("fetched"),
                                                           FUND_INDEX)
        self.assertEqual(texts, {})
        self.assertIn("SEC company list unavailable", messages[0])

    def test_research_etfs_are_refreshed_and_old_mappings_are_redone(self):
        self.folder.mkdir()
        (self.folder / "VGT.json").write_text(json.dumps(self.record("VGT")))  # no mapping_version: v1
        current = {**self.record("VOO"), "mapping_version": etf_holdings.MAPPING_VERSION}
        (self.folder / "VOO.json").write_text(json.dumps(current))
        seen = {}

        def fetch(ticker, universe, index, known, sec_names):
            seen[ticker] = known
            return None if known else self.record(ticker, "A2")
        history_calls = []

        def history_fetch(ticker, universe, index, sec_names, known):
            history_calls.append((ticker, set(known)))
            return [{"accession": "OLD", "report_date": "2026-03-31", "filed": "2026-05-28", "weights": {}}], []
        with mock.patch.object(etf_holdings, "THEME_ETFS", {"SMH": "半導體"}):
            self.assertEqual(refresh_etf_holdings.fund_list(self.root), ["SMH", "VGT", "VOO"])
            texts, _ = refresh_etf_holdings.refresh(self.root, self.folder, fetch, FUND_INDEX, {}, history_fetch)
        self.assertEqual(history_calls, [("SMH", {"A2"})], "history only for research ETFs; the new filing is known")
        history = json.loads(texts[self.folder / "history" / "SMH.json"])
        self.assertEqual([row["accession"] for row in history["filings"]], ["OLD", "A2"])
        self.assertEqual(seen, {"SMH": None, "VGT": None, "VOO": "A1"})
        self.assertIn(self.folder / "SMH.json", texts)
        self.assertIn(self.folder / "VGT.json", texts, "re-mapped under the current rules")
        self.assertNotIn(self.folder / "VOO.json", texts)


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
