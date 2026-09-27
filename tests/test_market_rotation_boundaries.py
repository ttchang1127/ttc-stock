"""Boundary, data-quality and symbol cases for the market-rotation builder.

Each case copies the deterministic ``quadrants`` fixture and changes exactly
one condition, so the scenario is visible in the test body.  Case ids
(MR-EDGE-001 ...) match 00_Meta/市場板塊族群輪動_初步計畫.md section 32.3.
"""

import json
import math
import pathlib
import sys
import unittest

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import market_rotation_fixture as fixture  # noqa: E402

MODULE = fixture.load_builder()


def all_numbers(value, path="$"):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from all_numbers(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from all_numbers(item, f"{path}[{index}]")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        yield path, value


class BoundaryCase(unittest.TestCase):
    def setUp(self):
        self.universe, self.closes, self.volumes = fixture.load_fixture()

    def build(self):
        return MODULE.build_payload(self.universe, self.closes, self.volumes)

    def drop(self, *tickers):
        self.closes = self.closes.drop(columns=list(tickers))
        self.volumes = self.volumes.drop(columns=list(tickers))

    def listed_tickers(self, payload):
        return {item["ticker"] for row in payload["sectors"]
                for item in row["leaders"] + row["laggards"]}

    def assert_json_finite(self, payload):
        json.dumps(payload, allow_nan=False)
        for path, number in all_numbers(payload):
            self.assertTrue(math.isfinite(number), f"{path} is not finite: {number}")


class SessionAndCoverageThresholdTests(BoundaryCase):
    def test_mr_edge_001_seventy_four_sessions_excluded(self):
        self.closes.iloc[:46, self.closes.columns.get_loc("TEC0")] = float("nan")
        self.assertEqual(int(self.closes["TEC0"].notna().sum()), 74)
        payload = self.build()
        self.assertEqual(payload["coverage"]["priced_securities"], 23, "MR-EDGE-001")
        self.assertEqual(payload["coverage"]["unavailable_tickers"], ["TEC0"], "MR-EDGE-001")
        self.assertNotIn("TEC0", self.listed_tickers(payload), "MR-EDGE-001")

    def test_mr_edge_001_seventy_five_sessions_included(self):
        self.closes.iloc[:45, self.closes.columns.get_loc("TEC0")] = float("nan")
        self.assertEqual(int(self.closes["TEC0"].notna().sum()), 75)
        payload = self.build()
        self.assertEqual(payload["coverage"]["priced_securities"], 24, "MR-EDGE-001")
        self.assertIn("TEC0", self.listed_tickers(payload), "MR-EDGE-001")

    def test_mr_edge_002_twenty_two_of_twenty_four_passes(self):
        self.drop("TEC0", "ENE5")
        payload = self.build()
        self.assertEqual(payload["coverage"]["priced_securities"], 22)
        self.assertEqual(payload["coverage"]["coverage_pct"], 91.7)

    def test_mr_edge_002_twenty_one_of_twenty_four_refuses_whole_batch(self):
        self.drop("TEC0", "ENE5", "HLT3")
        with self.assertRaisesRegex(ValueError, r"Only 21/24 securities have 75 sessions"):
            self.build()

    def test_mr_edge_003_minimum_members_kept_at_threshold(self):
        self.drop("TEC0")
        payload = self.build()
        sectors = {row["key"]: row for row in payload["sectors"]}
        industries = {row["key"] for row in payload["industries"]}
        self.assertEqual(sectors["Information Technology"]["member_count"], 5, "MR-EDGE-003 sector=5")
        self.assertIn("Application Software", industries, "MR-EDGE-003 industry=3")
        self.assertNotIn("Semiconductors", industries, "MR-EDGE-003 industry=2 excluded")

    def test_mr_edge_003_sector_below_threshold_excluded(self):
        self.drop("TEC0", "TEC1")
        payload = self.build()
        self.assertNotIn("Information Technology", {row["key"] for row in payload["sectors"]},
                         "MR-EDGE-003 sector=4 excluded")


def raw_row(key, x=1.0, y=1.0, value=1.0):
    return {
        "key": key, "name": key, "name_zh": key, "member_count": 5,
        "relative_strength_20d": x, "acceleration_5d": y,
        "relative_strength_60d": value, "breadth": value,
        "dollar_volume_expansion": value, "persistence": value,
    }


class QuadrantAndOrderingTests(unittest.TestCase):
    def test_mr_edge_004_zero_axis_counts_as_non_negative(self):
        rows = {row["key"]: row for row in MODULE.score_rows([
            raw_row("both-zero", 0.0, 0.0), raw_row("x-negative", -0.01, 0.0),
            raw_row("y-negative", 0.0, -0.01), raw_row("both-negative", -0.01, -0.01),
        ])}
        self.assertEqual(rows["both-zero"]["quadrant"], "leading", "MR-EDGE-004 x=0,y=0")
        self.assertEqual(rows["x-negative"]["quadrant"], "improving", "MR-EDGE-004 y=0")
        self.assertEqual(rows["y-negative"]["quadrant"], "weakening", "MR-EDGE-004 x=0")
        self.assertEqual(rows["both-negative"]["quadrant"], "lagging")

    def test_mr_edge_004_quadrant_uses_published_rounded_axes(self):
        rows = {row["key"]: row for row in MODULE.score_rows([
            raw_row("noise-below-zero", -1e-9, -1e-9), raw_row("clearly-negative", -0.01, -0.01),
        ])}
        noise = rows["noise-below-zero"]
        self.assertEqual((noise["relative_strength_20d"], noise["acceleration_5d"]), (0.0, 0.0))
        self.assertEqual(math.copysign(1, noise["acceleration_5d"]), 1.0, "no -0.0 in output")
        self.assertEqual(noise["quadrant"], "leading",
                         "MR-EDGE-004 a value published as 0.00 must use the non-negative quadrant")
        self.assertEqual(rows["clearly-negative"]["quadrant"], "lagging")

    def test_mr_edge_005_ties_use_stable_group_id(self):
        rows = MODULE.score_rows([raw_row("Utilities"), raw_row("Energy"), raw_row("Materials")])
        self.assertEqual(len({row["rotation_score"] for row in rows}), 1, "fixture must tie")
        self.assertEqual([row["key"] for row in rows], ["Energy", "Materials", "Utilities"],
                         "MR-EDGE-005 tie order must follow stable group id, not input order")

    def test_mr_calc_008_zero_relative_strength_is_not_missing(self):
        rows = MODULE.rank_stock_rows([
            {"ticker": "LOW", "relative_strength_20d": -1.0},
            {"ticker": "ZERO", "relative_strength_20d": 0.0},
            {"ticker": "NONE", "relative_strength_20d": None},
            {"ticker": "HIGH", "relative_strength_20d": 1.0},
            {"ticker": "ALSO", "relative_strength_20d": 1.0},
        ])
        self.assertEqual([row["ticker"] for row in rows], ["ALSO", "HIGH", "ZERO", "LOW", "NONE"])


class DataQualityTests(BoundaryCase):
    def test_mr_data_001_zero_prior_volume_is_missing_not_infinite(self):
        prior = self.volumes.index[-25:-5]
        semis = ["TEC0", "TEC1", "TEC2"]
        self.volumes.loc[prior, semis] = 0.0
        payload = self.build()
        self.assert_json_finite(payload)
        industries = {row["key"]: row for row in payload["industries"]}
        self.assertNotIn("Semiconductors", industries,
                         "a group without a volume component must not receive a ranked score")
        unranked = {row["key"]: row for row in payload["coverage"]["unranked_groups"]}
        self.assertEqual(unranked["Semiconductors"]["missing_components"],
                         ["dollar_volume_expansion"], "MR-DATA-001")
        for sector in payload["sectors"]:
            for item in sector["leaders"] + sector["laggards"]:
                if item["ticker"] in semis:
                    self.assertIsNone(item["dollar_volume_expansion"], item["ticker"])

    def test_mr_data_002_non_positive_and_non_finite_prices_never_reach_json(self):
        latest = self.closes.index[-1]
        self.closes.loc[latest, "TEC0"] = 0.0
        self.closes.loc[latest, "IND0"] = -5.0
        self.closes.loc[latest, "HLT0"] = float("inf")
        payload = self.build()
        self.assert_json_finite(payload)
        for collection in ("sectors", "industries"):
            for row in payload[collection]:
                for field in ("relative_strength_20d", "acceleration_5d", "breadth", "return_20d"):
                    self.assertIsNotNone(row[field], f"MR-DATA-002 {row['key']}.{field}")
        listed = self.listed_tickers(payload)
        for ticker in ("TEC0", "IND0", "HLT0"):
            self.assertNotIn(ticker, listed, f"MR-DATA-002 {ticker} has no valid latest price")

    def test_mr_data_003_missing_latest_price_is_excluded_from_breadth(self):
        # TEC0 is below its moving average in the fixture only if counted as
        # a failure; without a latest price it must leave the denominator.
        self.closes.loc[self.closes.index[-1], "TEC0"] = float("nan")
        payload = self.build()
        tech = next(row for row in payload["sectors"] if row["key"] == "Information Technology")
        self.assertEqual(tech["breadth_positive_20d"], 100.0, "MR-DATA-003 denominator is 5, not 6")
        self.assertEqual(tech["breadth_above_ma20"], 100.0, "MR-DATA-003 denominator is 5, not 6")
        self.assertEqual(payload["coverage"]["priced_securities"], 24,
                         "a missing latest close does not remove 119 valid sessions")


class SymbolTests(BoundaryCase):
    def test_mr_sym_001_dotted_ticker_keeps_display_symbol(self):
        self.assertEqual(MODULE.yahoo_symbol("BRK.B"), "BRK-B")
        member = next(row for row in self.universe["members"] if row["ticker"] == "TEC0")
        member.update(ticker="TEC.A", yahoo_ticker="TEC-A")
        self.closes = self.closes.rename(columns={"TEC0": "TEC-A"})
        self.volumes = self.volumes.rename(columns={"TEC0": "TEC-A"})
        payload = self.build()
        tech = next(row for row in payload["sectors"] if row["key"] == "Information Technology")
        self.assertEqual(tech["laggards"][0]["ticker"], "TEC.A", "MR-SYM-001")
        self.assertEqual(payload["coverage"]["unavailable_tickers"], [], "MR-SYM-001")

    def test_mr_sym_002_overlapping_constituents_counted_once(self):
        sp = pd.DataFrame({
            "Symbol": [f"S{n:03d}" for n in range(489)] + ["BRK.B"],
            "Security": [f"S&P {n}" for n in range(490)],
            "GICS Sector": ["Financials"] * 490,
            "GICS Sub-Industry": ["Multi-Sector Holdings"] * 490,
        })
        ndx = pd.DataFrame({
            "Ticker": [f"S{n:03d}" for n in range(10)] + [f"N{n:03d}" for n in range(90)],
            "Company": [f"Nasdaq {n}" for n in range(100)],
            "ICB Industry[1]": ["Technology"] * 100,
            "ICB Subsector[1]": ["Software"] * 100,
        })
        tables = {MODULE.SP500_URL: sp, MODULE.NASDAQ100_URL: ndx}
        original_fetch, original_find = MODULE.fetch_html, MODULE.find_table
        MODULE.fetch_html = lambda url: url
        MODULE.find_table = lambda html, required: tables[html]
        try:
            universe = MODULE.build_universe()
        finally:
            MODULE.fetch_html, MODULE.find_table = original_fetch, original_find
        members = {row["ticker"]: row for row in universe["members"]}
        self.assertEqual(universe["counts"]["combined_securities"], 580, "MR-SYM-002")
        self.assertEqual(len(universe["members"]), 580, "MR-SYM-002 duplicate member rows")
        self.assertEqual(members["S000"]["indexes"], ["S&P 500", "Nasdaq-100"], "MR-SYM-002")
        self.assertEqual(members["S000"]["classification"], "GICS", "S&P GICS wins on overlap")
        self.assertEqual(members["N000"]["sector"], "Information Technology", "ICB mapped")
        self.assertEqual(members["BRK.B"]["yahoo_ticker"], "BRK-B", "MR-SYM-001")


if __name__ == "__main__":
    unittest.main()
