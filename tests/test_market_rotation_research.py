import copy
import json
import pathlib
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import market_rotation_contracts as contracts  # noqa: E402
import market_rotation_fixture as fixture  # noqa: E402
import market_rotation_research as research  # noqa: E402

SECTORS = list(research.SECTOR_STYLE)
PREFIX = {"Information Technology": "INF", "Communication Services": "COM", "Consumer Discretionary": "CND",
          "Industrials": "IND", "Materials": "MAT", "Energy": "ENE", "Consumer Staples": "CNS",
          "Health Care": "HEA", "Utilities": "UTI", "Financials": "FIN", "Real Estate": "REA"}


def synthetic_market(drifts: dict[str, float], sessions: int = 200, per_sector: int = 6,
                     special: dict[str, np.ndarray] | None = None, seed: int = 7):
    """Deterministic closes/volumes/metadata: 11 sectors x ``per_sector`` issuers.

    ``drifts`` sets each sector's daily drift for the last 70 sessions;
    ``special`` replaces one ticker's whole close path.  Alphabet-style dual
    classes (TEC0 and TEC0B) share an issuer name.
    """
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2025-01-02", periods=sessions)
    closes, rows = {}, []
    for number, sector in enumerate(SECTORS):
        for member in range(per_sector):
            ticker = f"{PREFIX[sector]}{member}"
            noise = rng.normal(0, 0.004, sessions)
            drift = np.zeros(sessions)
            drift[-70:] = drifts.get(sector, 0.0)
            closes[ticker] = 100 * np.cumprod(1 + drift + noise)
            rows.append({"ticker": ticker, "name": f"{sector} issuer {member}", "sector": sector,
                         "industry": f"{sector} industry {member % 2}",
                         "indexes": ["S&P 500"] + (["Nasdaq-100"] if number < 3 else [])})
    closes["INF0B"] = closes["INF0"] * 1.001
    rows.append({"ticker": "INF0B", "name": "Information Technology issuer 0",
                 "sector": "Information Technology", "industry": "Information Technology industry 0",
                 "indexes": ["S&P 500", "Nasdaq-100"]})
    for ticker, path in (special or {}).items():
        closes[ticker] = path
    closes = pd.DataFrame(closes, index=index)
    volumes = pd.DataFrame(1_000_000.0, index=index, columns=closes.columns)
    metadata = pd.DataFrame(rows).set_index("ticker")
    return closes, volumes, metadata


def run(closes, volumes, metadata):
    parents = {f"{s} industry {k}": s for s in SECTORS for k in (0, 1)}
    return research.compute_research(closes, volumes, metadata, 99.0, parents)


def sector(result, name):
    return next(g for g in result["groups"] if g["group_type"] == "sector" and g["name_en"] == name)


class MarketEnvironmentTests(unittest.TestCase):
    def test_broad_rally_is_broad_expansion(self):
        result = run(*synthetic_market({s: 0.004 for s in SECTORS}))
        self.assertEqual(result["market"]["state"]["confirmed"], "broad_expansion")
        self.assertGreaterEqual(result["market"]["evidence"]["B20"], 60)

    def test_broad_selloff_is_retreat_and_the_least_bad_sector_is_flagged(self):
        drifts = {s: -0.006 for s in SECTORS}
        drifts["Energy"] = -0.002  # falls, but less than everything else
        result = run(*synthetic_market(drifts))
        market = result["market"]
        self.assertEqual(market["state"]["confirmed"], "broad_retreat")
        energy = sector(result, "Energy")
        self.assertGreater(energy["evidence"]["RS20"], 0)
        self.assertGreater(energy["evidence"]["RS60"], 0)
        self.assertLess(energy["evidence"]["R20"], 0)
        # Relatively strongest, but none of its companies is rising: never "confirmed leading".
        self.assertNotEqual(energy["state"]["confirmed"], "confirmed_leading")
        self.assertIn("relative_only", energy["risk_tags"])

    def test_leadership_type_needs_two_of_the_top_three_sectors(self):
        rs = pd.Series({"Information Technology": 0.05, "Communication Services": 0.04, "Energy": 0.03,
                        "Utilities": -0.01})
        self.assertEqual(research.leadership(rs)["type"], "growth_tech")
        rs = pd.Series({"Information Technology": 0.05, "Energy": 0.04, "Utilities": 0.03})
        self.assertEqual(research.leadership(rs)["type"], "none")

    def test_index_baskets_are_reported_separately(self):
        result = run(*synthetic_market({s: 0.002 for s in SECTORS}))
        indexes = result["market"]["indexes"]
        self.assertEqual(indexes["Nasdaq-100"]["securities"], 19)
        self.assertEqual(indexes["S&P 500"]["securities"], 67)
        self.assertIsNotNone(result["market"]["nasdaq_minus_sp500"]["return_20d"])


class ConcentrationTests(unittest.TestCase):
    def one_stock_sector(self):
        base_drifts = {s: 0.0 for s in SECTORS}
        base_drifts["Information Technology"] = -0.001
        closes, _, _ = synthetic_market(base_drifts)
        surge = closes["INF1"].to_numpy().copy()
        surge[-30:] = surge[-31] * np.cumprod(np.full(30, 1.02))
        return synthetic_market(base_drifts, special={"INF1": surge})

    def test_single_company_carrying_a_sector_is_flagged(self):
        result = run(*self.one_stock_sector())
        tech = sector(result, "Information Technology")
        conc = tech["concentration"]
        self.assertGreater(conc["mean_relative_20d"], 0)
        self.assertEqual(conc["top_contributor"]["ticker"], "INF1")
        self.assertTrue(conc["single_issuer_dominance"])
        self.assertIn("negative_without_top1", conc["reasons"])
        self.assertIn("single_issuer_dominance", tech["risk_tags"])

    def test_broad_strength_is_not_flagged(self):
        drifts = {s: 0.0 for s in SECTORS}
        drifts["Energy"] = 0.004
        result = run(*synthetic_market(drifts))
        energy = sector(result, "Energy")
        self.assertFalse(energy["concentration"]["single_issuer_dominance"], energy["concentration"])
        self.assertNotIn("single_issuer_dominance", energy["risk_tags"])

    def test_dual_share_classes_count_as_one_issuer(self):
        result = run(*synthetic_market({s: 0.001 for s in SECTORS}))
        tech = sector(result, "Information Technology")
        self.assertEqual(tech["evidence"]["issuers"], 6)
        self.assertEqual(tech["concentration"]["issuers"], 6)

    def test_top3_share_only_for_groups_of_six_or_more(self):
        result = run(*synthetic_market({s: 0.001 for s in SECTORS}))
        industry = next(g for g in result["groups"] if g["group_type"] == "industry")
        self.assertIsNone(industry["concentration"]["top3_positive_share"])
        self.assertIn("small_sample", industry["risk_tags"])
        self.assertEqual(industry["state"]["confirmed"], "small_sample_clue")


class ConfirmationTests(unittest.TestCase):
    def walk(self, states):
        index = pd.bdate_range("2026-01-01", periods=len(states))
        return research.confirm(pd.Series(states, index=index))

    def test_new_state_needs_two_sessions(self):
        walk = self.walk(["a", "a", "b", "a", "b", "b", "b"])
        self.assertEqual(list(walk["confirmed"]), ["a", "a", "a", "a", "a", "b", "b"])
        self.assertEqual(list(walk["pending"])[:5], [None, None, "b", None, "b"])
        last = walk.iloc[-1]
        self.assertEqual(last["days_in_state"], 2)
        self.assertFalse(last["since_is_lower_bound"])

    def test_insufficient_data_freezes_state_and_pending_count(self):
        walk = self.walk(["a", "b", "insufficient_data", "b", "c"])
        self.assertEqual(list(walk["confirmed"]), ["a", "a", "a", "b", "b"])
        self.assertEqual(walk.iloc[2]["pending_days"], 1)
        self.assertEqual(walk.iloc[-1]["pending"], "c")

    def test_first_state_is_a_lower_bound(self):
        walk = self.walk(["insufficient_data", "a", "a"])
        self.assertIsNone(walk.iloc[0]["confirmed"])
        self.assertTrue(walk.iloc[-1]["since_is_lower_bound"])
        self.assertEqual(walk.iloc[-1]["days_in_state"], 2)

    def test_states_never_read_future_sessions(self):
        closes, volumes, metadata = synthetic_market({s: (0.003 if i % 2 else -0.003)
                                                      for i, s in enumerate(SECTORS)})
        full = research.state_history(closes, volumes, metadata)
        cut = 150
        partial = research.state_history(closes.iloc[:cut], volumes.iloc[:cut], metadata)
        pd.testing.assert_frame_equal(full["market_walk"].iloc[:cut], partial["market_walk"])
        for name, walk in partial["sector_walks"].items():
            pd.testing.assert_frame_equal(full["sector_walks"][name].iloc[:cut], walk)


class DirectionalVolumeTests(unittest.TestCase):
    def test_zero_volume_rules(self):
        up = pd.DataFrame({"a": [10.0, 5.0, 0.0, 0.0]})
        down = pd.DataFrame({"a": [5.0, 0.0, 4.0, 0.0]})
        ratio, share = research.directional_volume(up, down)
        self.assertEqual(ratio["a"].iloc[0], 2.0)
        self.assertTrue(np.isnan(ratio["a"].iloc[1]))
        self.assertEqual(share["a"].iloc[1], 1.0)
        self.assertEqual((ratio["a"].iloc[2], share["a"].iloc[2]), (0.0, -1.0))
        self.assertTrue(np.isnan(ratio["a"].iloc[3]) and np.isnan(share["a"].iloc[3]))


class PublishedResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builder = fixture.load_builder()
        universe, closes, volumes = fixture.load_fixture()
        canonical, registry = fixture.fixture_canonical()
        cls.research = cls.builder.calculate_research(universe, closes, volumes, canonical, registry)
        cls.outputs = cls.builder.build_outputs(canonical, registry, "t", cls.research)

    def test_research_shares_the_batch_dataset_and_stable_ids(self):
        payload = self.outputs["research"]
        self.assertEqual(payload["dataset_id"], self.outputs["groups"]["dataset_id"])
        self.assertEqual(payload["data"]["rule_status"], "research")
        v2_ids = {g["group_id"] for key in ("sectors", "industries") for g in self.outputs["groups"]["data"][key]}
        for row in payload["data"]["groups"]:
            self.assertEqual(row["ranked"], row["group_id"] in v2_ids)

    def test_validator_rejects_foreign_batches_and_unknown_codes(self):
        groups = self.outputs["groups"]
        for mutate, message in (
                (lambda p: p.update(dataset_id="sha256:" + "0" * 64), "dataset_id"),
                (lambda p: p["data"]["groups"][0]["risk_tags"].append("buy_signal"), "unknown tag"),
                (lambda p: p["data"]["market"]["state"].update(raw="bull_market"), "unknown state"),
                (lambda p: p["data"].update(rule_status="validated"), "rule_status"),
                (lambda p: p["data"]["groups"][0]["evidence"].update(BPOS20=120), "outside")):
            payload = copy.deepcopy(self.outputs["research"])
            mutate(payload)
            with self.assertRaisesRegex(contracts.ContractError, message):
                contracts.validate_research(payload, groups)

    def test_publish_writes_research_in_the_same_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = pathlib.Path(directory)
            changed = self.builder.publish_outputs(self.outputs, folder / "market_rotation.json",
                                                   folder / "market_rotation_registry.json")
            self.assertTrue(changed["research"])
            written = json.loads((folder / "market_rotation_research.json").read_text())
            self.assertEqual(written["dataset_id"], self.outputs["summary"]["dataset_id"])


class ResearchPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "market_rotation.html").read_text()
        cls.script = (ROOT / "assets/market_rotation_research.js").read_text()

    def test_page_loads_the_research_script_and_sections(self):
        self.assertIn('<script src="assets/market_rotation_research.js" defer></script>', self.html)
        for element in ('id="marketEnvironment"', 'id="sectorStateBody"', 'id="backtestSummary"', "研究中",
                        'id="rotationDigest"', 'id="portfolioExposure"', "不是買賣或調整部位的指令"):
            self.assertIn(element, self.html)
        for path in ("market_rotation_research.json", "market_rotation_history/backtest/sector_results.json",
                     "market_rotation_daily_digest.json", "portfolio_equity_exposure.json"):
            self.assertIn(f"'{path}'", self.script)

    def test_every_missing_file_has_a_plain_message(self):
        for message in ("市場環境研究層尚未產出", "板塊絕對狀態尚未產出", "回測尚未執行",
                        "每日變化摘要尚未產出", "持股曝險尚未產出", "每日快照尚未開始累積"):
            self.assertIn(message, self.script)
        self.assertIn("C 級歷史", self.script)
        self.assertIn("存活者偏誤", self.script)

    def test_every_code_has_a_page_mapping(self):
        for tag in contracts.RISK_TAGS:
            self.assertIn(f"{tag}:", self.script, f"TAG_TONE lacks {tag}")
        for state in list(contracts.MARKET_STATES) + list(contracts.GROUP_STATES):
            if state != "insufficient_data":
                self.assertIn(f"{state}:", self.script, f"STATE_TONE lacks {state}")
        row = pd.Series({"R5": 0.01, "R20": 0.01, "R60": 0.02, "B20": 0.5, "B60": 0.5, "UDVR5": 1.0,
                         "dB20_5": 0.0, "down_share5": 0.5, "new_lows": 3, "LWGAP": 0.0})
        checks = research.market_checks(row, pd.Series([0.01, -0.01]), pd.Series([0.01, -0.01]), None)
        codes = {item["code"] for spec in checks.values()
                 for item in spec["checks"] + ([spec["gate"]] if "gate" in spec else [])}
        for code in codes:
            self.assertIn(f"'{code}':", self.script, f"CHECK_LABELS lacks {code}")


if __name__ == "__main__":
    unittest.main()
