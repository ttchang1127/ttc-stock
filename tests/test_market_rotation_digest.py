import copy
import json
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import market_rotation_digest as digest  # noqa: E402
import portfolio_rotation as portfolio  # noqa: E402

TRADE_WORDS = re.compile(r"買進|賣出|加碼|減碼|停損|目標權重")


def group_record(group_id, state="neutral_mixed", pending=None, tags=(), rs20=1.0, r20=1.0, top=None,
                 dominance=False):
    return {
        "group_id": group_id, "group_type": group_id.split(":")[0],
        "state": {"raw": pending or state, "confirmed": state, "pending": pending, "pending_days": 1 if pending else 0,
                  "days_in_state": 4, "since": "2026-09-20", "confirm_sessions": 2, "since_is_lower_bound": False},
        "risk_tags": list(tags), "evidence": {"RS20": rs20, "R20": r20, "RS60": 1.0, "BPOS20": 60.0, "DVS5": 0.1},
        "concentration": {"top_contributor": {"ticker": top} if top else None, "single_issuer_dominance": dominance},
    }


class ExposureTests(unittest.TestCase):
    def setUp(self):
        self.universe = {"members": [
            {"ticker": "NVDA", "sector": "Information Technology", "industry": "Semiconductors",
             "classification": "GICS", "indexes": ["S&P 500"]},
            {"ticker": "ARM", "sector": "Information Technology", "industry": "Semiconductors",
             "classification": "ICB", "indexes": ["Nasdaq-100"]},
            {"ticker": "GOOG", "sector": "Communication Services", "industry": "Interactive Media & Services",
             "classification": "GICS", "indexes": ["S&P 500"]},
        ]}
        self.overrides = {"funds_excluded": {"VOO": "ETF"}, "classification": {"NOK": {
            "sector": "Information Technology", "industry": "Communications Equipment",
            "source": "20-F", "reason": "not in universe", "reviewed_at": "2026-09-27"}}}
        self.registry = {"groups": [
            {"group_id": "sector:information-technology", "group_type": "sector",
             "name_en": "Information Technology", "aliases": []},
            {"group_id": "sector:communication-services", "group_type": "sector",
             "name_en": "Communication Services", "aliases": []},
            {"group_id": "industry:semiconductors", "group_type": "industry", "name_en": "Semiconductors",
             "aliases": []},
            {"group_id": "industry:communications-equipment", "group_type": "industry",
             "name_en": "Communications Equipment", "aliases": []},
        ]}
        dates = ["2026-09-24", "2026-09-25"]
        self.prices = {"series": {t: {"dates": dates, "closes": [1.0, close]} for t, close in
                                  (("NVDA", 100.0), ("ARM", 100.0), ("GOOG", 200.0), ("NOK", 10.0), ("VOO", 500.0))}}
        self.holdings = {"updated_at": "2026-09-27", "currency": "USD", "holdings": [
            {"ticker": "NVDA", "shares": 10, "cost": 50}, {"ticker": "ARM", "shares": 10, "cost": 80},
            {"ticker": "GOOG", "shares": 5, "cost": 150}, {"ticker": "NOK", "shares": 100, "cost": 5},
            {"ticker": "VOO", "shares": 100, "cost": 400}]}
        self.research = {"as_of": "2026-09-25", "data": {"groups": [
            group_record("sector:information-technology", "cooling", top="NVDA", dominance=True),
            group_record("sector:communication-services", "confirmed_leading"),
            group_record("industry:semiconductors", "neutral_mixed", pending="clear_lagging"),
        ]}}

    def build(self, **changes):
        args = dict(holdings=self.holdings, prices=self.prices, universe=self.universe, overrides=self.overrides,
                    registry=self.registry, research=self.research, previous=None)
        args.update(changes)
        return portfolio.build_exposure(**args)

    def test_funds_are_excluded_and_weights_use_market_value(self):
        exposure = self.build()
        self.assertEqual(exposure["excluded_funds"], ["VOO"])
        self.assertEqual({p["ticker"] for p in exposure["positions"]}, {"NVDA", "ARM", "GOOG", "NOK"})
        self.assertAlmostEqual(sum(p["weight"] for p in exposure["positions"]), 100.0, places=1)
        sectors = {row["name"]: row["weight"] for row in exposure["sector_concentration"]["sectors"]}
        self.assertEqual(sectors, {"Information Technology": 75.0, "Communication Services": 25.0})
        self.assertEqual(exposure["sector_concentration"]["effective_sectors"], round(1 / (0.75**2 + 0.25**2), 2))
        self.assertTrue(exposure["needs_review"], "a majority sector needs review")

    def test_manual_classification_and_unclassified_holdings(self):
        exposure = self.build()
        nok = next(p for p in exposure["positions"] if p["ticker"] == "NOK")
        self.assertEqual(nok["industry_id"], "industry:communications-equipment")
        self.assertIn("人工分類", nok["classification_source"])
        holdings = copy.deepcopy(self.holdings)
        holdings["holdings"].append({"ticker": "ZZZ", "shares": 1, "cost": 1})
        self.assertFalse(self.build(holdings=holdings)["coverage"]["complete"])

    def test_cost_does_not_change_weights(self):
        cheaper = copy.deepcopy(self.holdings)
        for row in cheaper["holdings"]:
            row["cost"] = 1
        self.assertEqual(self.build()["sector_concentration"], self.build(holdings=cheaper)["sector_concentration"])

    def test_research_priorities_follow_rotation_state(self):
        positions = {p["ticker"]: p for p in self.build()["positions"]}
        self.assertEqual(positions["NVDA"]["research_priority"], "review_now")
        self.assertEqual(positions["GOOG"]["research_priority"], "monitor")
        self.assertTrue(any("追價" in reason for reason in positions["GOOG"]["reasons"]))
        for position in positions.values():
            self.assertTrue(position["not_an_action"])
            self.assertIsNone(TRADE_WORDS.search("".join(position["reasons"])), position["reasons"])

    def test_stale_or_missing_price_blocks_the_conclusion(self):
        prices = copy.deepcopy(self.prices)
        prices["series"]["ARM"]["dates"] = ["2026-09-10", "2026-09-11"]
        del prices["series"]["GOOG"]
        positions = {p["ticker"]: p for p in self.build(prices=prices)["positions"]}
        self.assertEqual(positions["ARM"]["research_priority"], "data_blocked")
        self.assertEqual(positions["GOOG"]["research_priority"], "data_blocked")

    def test_weight_changes_attribute_trades_and_drift(self):
        before = self.build()
        prices = copy.deepcopy(self.prices)
        prices["series"]["GOOG"]["closes"][-1] = 400.0
        drift = self.build(prices=prices, previous=before)["changes"]
        self.assertTrue(drift and all(change["cause"] == "market_drift" for change in drift))
        holdings = copy.deepcopy(self.holdings)
        holdings["holdings"][2]["shares"] = 10
        trade = self.build(holdings=holdings, previous=before)["changes"]
        self.assertTrue(trade and all(change["cause"] == "holding_change" for change in trade))


def snapshot(as_of, market="neutral_mixed", leadership="none", pending=None, groups=None,
             versions=("1.0.0", "research-1.0")):
    return {
        "as_of": as_of, "calculation_version": versions[0], "research_rules": versions[1],
        "market": {"confirmed_state": market, "pending_state": pending, "leadership": leadership,
                   "evidence": {"R20": 1.0, "B20": 55.0}},
        "groups": groups or {},
    }


def srow(state="neutral_mixed", pending=None, tags=(), issuers=11):
    return {"confirmed_state": state, "pending_state": pending, "risk_tags": list(tags), "issuers": issuers,
            "RS20": 1.0, "RS60": 1.0, "A5": 0.1, "BPOS20": 60.0, "BMA20": 60.0, "R20": 1.0}


NAMES = {"sector:energy": {"name_zh": "能源"}, "sector:information-technology": {"name_zh": "資訊科技"},
         "industry:semiconductors": {"name_zh": "Semiconductors"}, "industry:tiny": {"name_zh": "Tiny"}}
HOLDINGS = {"sector:information-technology": ["NVDA"], "industry:semiconductors": ["NVDA"]}


class DigestTests(unittest.TestCase):
    def build(self, current, previous, previous_digest=None):
        return digest.build_digest(current, previous, NAMES, HOLDINGS, None, None, previous_digest)

    def test_first_snapshot_and_rule_change_are_silent_baselines(self):
        self.assertEqual(self.build(snapshot("2026-09-28"), [])["status"], "baseline")
        changed = self.build(snapshot("2026-09-29", market="broad_expansion"),
                             [snapshot("2026-09-28", versions=("1.0.0", "research-0.9"))])
        self.assertEqual((changed["status"], changed["notify_count"]), ("baseline_after_rule_change", 0))
        self.assertEqual(self.build(None, [])["status"], "awaiting_history")

    def test_confirmed_changes_notify_and_pending_does_not(self):
        previous = snapshot("2026-09-28", groups={"sector:energy": srow("confirmed_leading"),
                                                  "sector:information-technology": srow("confirmed_leading")})
        current = snapshot("2026-09-29", market="broad_retreat", pending=None, groups={
            "sector:energy": srow("cooling"),
            "sector:information-technology": srow("confirmed_leading", pending="cooling")})
        result = self.build(current, [previous])
        kinds = [(e["priority"], e["scope"], e["entity_id"], e["change_type"]) for e in result["events"]]
        self.assertEqual(kinds, [("P1", "market", "market", "conclusion_changed"),
                                 ("P2", "sector", "sector:energy", "conclusion_changed"),
                                 ("P3", "sector", "sector:information-technology", "pending_change")])
        self.assertEqual(result["notify_count"], 2)
        self.assertEqual(result["events"][2]["related_holdings"], ["NVDA"])
        self.assertTrue(result["batch_id"].startswith("rotation-2026-09-29-"))

    def test_rerun_with_the_same_batch_does_not_notify_again(self):
        previous = snapshot("2026-09-28", market="neutral_mixed")
        current = snapshot("2026-09-29", market="broad_expansion")
        first = self.build(current, [previous])
        second = self.build(current, [previous], previous_digest=first)
        self.assertEqual((first["notify_count"], second["notify_count"]), (1, 0))
        self.assertEqual(first["events"], second["events"])

    def test_holdings_sort_first_within_a_priority(self):
        previous = snapshot("2026-09-28", groups={"sector:energy": srow("neutral_mixed"),
                                                  "sector:information-technology": srow("neutral_mixed")})
        current = snapshot("2026-09-29", groups={"sector:energy": srow("clear_lagging"),
                                                 "sector:information-technology": srow("cooling")})
        entities = [e["entity_id"] for e in self.build(current, [previous])["events"]]
        self.assertEqual(entities, ["sector:information-technology", "sector:energy"])

    def test_risk_needs_two_sessions_to_appear_or_clear(self):
        def run(tag_days):
            snaps = [snapshot(f"2026-09-2{i}", groups={"sector:energy": srow(tags=tags)})
                     for i, tags in enumerate(tag_days, start=5)]
            return [(e["change_type"]) for e in self.build(snaps[-1], snaps[:-1])["events"]]
        tag = ("single_issuer_dominance",)
        self.assertEqual(run([(), (), tag]), [], "one session is not enough")
        self.assertEqual(run([(), tag, tag]), ["new_risk"])
        self.assertEqual(run([tag, (), ()]), ["risk_resolved"])
        self.assertEqual(run([tag, tag, tag]), [], "a lasting risk is not news")

    def test_small_industries_and_score_only_moves_are_not_events(self):
        previous = snapshot("2026-09-28", groups={"industry:tiny": srow("neutral_mixed", issuers=4)})
        current = snapshot("2026-09-29", groups={"industry:tiny": srow("confirmed_leading", issuers=4)})
        self.assertEqual(self.build(current, [previous])["status"], "no_change")

    def test_alert_text_never_gives_trade_instructions(self):
        previous = snapshot("2026-09-28", groups={"sector:information-technology": srow("confirmed_leading")})
        current = snapshot("2026-09-29", groups={"sector:information-technology": srow("clear_lagging")})
        text = digest.alert_markdown(self.build(current, [previous]), None, "https://example.invalid/page")
        self.assertIn("不是買賣訊號", text)
        self.assertIn("NVDA", text)
        self.assertIsNone(TRADE_WORDS.search(text.replace("不是買賣訊號", "")))


class HeadlineTests(unittest.TestCase):
    def research(self, evidence, confidence="high"):
        return {"as_of": "2026-09-25", "data": {
            "market": {"state": {"confirmed": "narrow_leadership", "raw": "narrow_leadership"},
                       "leadership": {"label": "成長／科技主導"}, "evidence": {"R20": 2.1},
                       "confidence": confidence},
            "groups": [{"group_id": "sector:information-technology", "evidence": evidence}]}}

    groups = {"data": {"sectors": [
        {"group_id": "sector:information-technology", "name_zh": "資訊科技",
         "metrics": {"relative_strength_20d": 1.2, "acceleration_5d": 0.3}},
        {"group_id": "sector:industrials", "name_zh": "工業",
         "metrics": {"relative_strength_20d": -0.8, "acceleration_5d": 1.1}}]}}

    def test_sentence_follows_the_evidence_order(self):
        text = digest.headline(self.research({"R20": 3.0, "RS60": 1.0, "BPOS20": 43.0, "DVS5": 0.2}), self.groups)
        self.assertTrue(text.startswith("截至 2026-09-25，市場狀態「狹幅領漲」（成長／科技主導），合併股票池近 20 日上漲 2.10%。"))
        self.assertIn("資訊科技為相對領先代表（+1.20pp）", text)
        self.assertIn("工業的 5 日相對動能改善最快", text)
        self.assertTrue(text.endswith("資訊科技廣度僅 43%，領先仍偏集中。"))

    def test_one_limitation_chosen_by_priority_and_zero_is_a_value(self):
        text = digest.headline(self.research({"R20": -1.0, "RS60": -1.0, "BPOS20": 0.0}), self.groups)
        self.assertTrue(text.endswith("領先只代表跌得較少。"))
        text = digest.headline(self.research({"R20": 3.0, "RS60": 1.0, "BPOS20": 0.0}), self.groups)
        self.assertTrue(text.endswith("廣度僅 0%，領先仍偏集中。"))
        text = digest.headline(self.research({"R20": 3.0, "RS60": 1.0, "BPOS20": 70.0, "DVS5": 0.1}), self.groups)
        self.assertTrue(text.endswith("不是買賣訊號。"))
        text = digest.headline(self.research({"R20": 3.0}, confidence="low"), self.groups)
        self.assertTrue(text.endswith("結論信心較低。"))


class RepositoryExposureTests(unittest.TestCase):
    def test_every_direct_holding_is_classified(self):
        holdings = json.loads((ROOT / "portfolio_holdings.json").read_text())
        universe = json.loads((ROOT / "market_rotation_universe.json").read_text())
        overrides = json.loads((ROOT / "portfolio_classification.json").read_text())
        classes = portfolio.classify(universe, overrides)
        for row in holdings["holdings"]:
            if row["ticker"] not in overrides["funds_excluded"]:
                self.assertIn(row["ticker"], classes, "add a reviewed entry to portfolio_classification.json")
        for ticker, row in overrides["classification"].items():
            for key in ("sector", "industry", "source", "reason", "reviewed_at"):
                self.assertTrue(row.get(key), f"{ticker}.{key}")


if __name__ == "__main__":
    unittest.main()
