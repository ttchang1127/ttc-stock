"""Canonical model, stable-id registry and role selection (WP-2)."""

import copy
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import market_rotation_contracts as contracts  # noqa: E402
import market_rotation_fixture as fixture  # noqa: E402

MODULE = fixture.load_builder()


class CanonicalModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.universe, cls.closes, cls.volumes = fixture.load_fixture()
        cls.canonical, cls.registry = MODULE.calculate_canonical(cls.universe, cls.closes, cls.volumes)

    def test_canonical_is_valid_and_excludes_run_metadata(self):
        contracts.validate_canonical(self.canonical)
        self.assertNotIn("generated_at", self.canonical)
        self.assertNotIn("dataset_id", self.canonical)
        self.assertEqual(self.canonical["versions"]["calculation"], "rotation-score-v1")

    def test_v1_serializer_reproduces_golden(self):
        payload = MODULE.serialize_v1(self.canonical, "2026-01-01T00:00:00+00:00")
        expected = json.loads(fixture.GOLDEN_V1.read_text())
        self.assertEqual(fixture.differences(fixture.stable(expected), fixture.stable(payload)), [])

    def test_groups_are_normalised_with_stable_ids_and_parents(self):
        groups = {g["group_id"]: g for g in self.canonical["groups"]}
        semis = groups["industry:semiconductors"]
        self.assertEqual(semis["parent_group_id"], "sector:information-technology")
        self.assertIsNone(semis["leader_stock_ids"], "industries carry no stock selection")
        tech = groups["sector:information-technology"]
        self.assertIsNone(tech["parent_group_id"])
        self.assertEqual(tech["rank"], 1)
        self.assertEqual(tech["leader_stock_ids"][0], "security:tec5")
        self.assertEqual(set(tech["metrics"]), set(contracts.GROUP_METRIC_UNITS))
        self.assertEqual(set(tech["ranks"]), set(contracts.SCORE_COMPONENTS))

    def test_every_stock_appears_once_with_group_ids(self):
        stocks = self.canonical["stocks"]
        self.assertEqual(len(stocks), 24)
        self.assertEqual(len({s["stock_id"] for s in stocks}), 24)
        tec0 = next(s for s in stocks if s["ticker"] == "TEC0")
        self.assertEqual((tec0["sector_id"], tec0["industry_id"]),
                         ("sector:information-technology", "industry:semiconductors"))
        self.assertEqual(tec0["quality_flags"], [])

    def test_roles_follow_fixed_rules(self):
        self.assertEqual(self.canonical["roles"], {
            "leader": "sector:information-technology",
            "improver": "sector:industrials",
            "weakening": "sector:health-care",
            # IT and Health Care both have 100% breadth; the higher score wins.
            "broadest": "sector:information-technology",
        })


def group(group_id, quadrant, score, acceleration=1.0, breadth=50.0):
    return {"group_id": group_id, "quadrant": quadrant, "rotation_score": score,
            "metrics": {"acceleration_5d": acceleration, "breadth": breadth}}


class RoleSelectionTests(unittest.TestCase):
    def test_mr_read_001_002_empty_quadrants_yield_none_not_stand_ins(self):
        roles = MODULE.select_roles([group("sector:a", "lagging", 90), group("sector:b", "weakening", 80)])
        self.assertIsNone(roles["leader"], "MR-READ-001 no leading group")
        self.assertIsNone(roles["improver"], "MR-READ-002 no improving group")
        self.assertEqual(roles["weakening"], "sector:b")

    def test_improver_ranks_by_acceleration_then_score_then_id(self):
        roles = MODULE.select_roles([
            group("sector:c", "improving", 10, acceleration=3.0),
            group("sector:b", "improving", 90, acceleration=2.0),
            group("sector:a", "improving", 10, acceleration=3.0),
        ])
        self.assertEqual(roles["improver"], "sector:a")

    def test_mr_read_008_ties_break_on_stable_id(self):
        roles = MODULE.select_roles([group("sector:z", "leading", 70), group("sector:m", "leading", 70)])
        self.assertEqual(roles["leader"], "sector:m")

    def test_mr_read_003_same_group_in_two_roles_is_one_card(self):
        cards = MODULE.role_cards({"leader": "sector:a", "improver": None,
                                   "weakening": "sector:b", "broadest": "sector:a"})
        self.assertEqual([c["group_id"] for c in cards], ["sector:a", "sector:b"])
        self.assertEqual(cards[0]["roles"], ["leader", "broadest"])
        self.assertEqual([item["field"] for item in cards[0]["evidence"]],
                         ["metrics.relative_strength_20d", "metrics.breadth", "metrics.acceleration_5d"],
                         "each merged role keeps its primary evidence")


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.universe, self.closes, self.volumes = fixture.load_fixture()

    def test_new_names_get_readable_slug_ids(self):
        registry = MODULE.Registry()
        self.assertEqual(registry.group_id("industry", "Aerospace & Defense"), "industry:aerospace-defense")
        self.assertEqual(registry.stock_id("BRK.B"), "security:brk-b")

    def test_recorded_ids_and_aliases_win_over_current_names(self):
        seeded = {"schema_version": 1, "securities": [], "groups": [{
            "group_id": "sector:information-technology", "group_type": "sector",
            "name_en": "Technology", "aliases": ["Information Technology"]}]}
        registry = MODULE.Registry(seeded)
        self.assertEqual(registry.group_id("sector", "Information Technology"),
                         "sector:information-technology")
        self.assertEqual(registry.group_id("sector", "Technology"), "sector:information-technology")

    def test_slug_collision_gets_hash_suffix_not_a_merge(self):
        registry = MODULE.Registry()
        first = registry.group_id("industry", "Health Care")
        second = registry.group_id("industry", "Health-Care")
        self.assertEqual(first, "industry:health-care")
        self.assertRegex(second, r"^industry:health-care-[0-9a-f]{6}$")
        contracts.validate_registry(registry.payload())

    def test_registration_is_independent_of_member_order(self):
        forward, backward = MODULE.Registry(), MODULE.Registry()
        forward.register_universe(self.universe["members"])
        backward.register_universe(list(reversed(self.universe["members"])))
        self.assertEqual(forward.payload(), backward.payload())

    def test_existing_registry_entries_are_never_rewritten(self):
        _, first = MODULE.calculate_canonical(self.universe, self.closes, self.volumes)
        extended = copy.deepcopy(self.universe)
        extended["members"][0] = dict(extended["members"][0], industry="Semiconductor Materials")
        _, second = MODULE.calculate_canonical(extended, self.closes, self.volumes, first)
        self.assertTrue(all(row in second["groups"] for row in first["groups"]))
        self.assertIn("industry:semiconductor-materials", {g["group_id"] for g in second["groups"]})

    def test_chinese_name_changes_do_not_affect_ids(self):
        original = MODULE.SECTOR_ZH["Energy"]
        try:
            MODULE.SECTOR_ZH["Energy"] = "能源類股"
            canonical, _ = MODULE.calculate_canonical(self.universe, self.closes, self.volumes)
        finally:
            MODULE.SECTOR_ZH["Energy"] = original
        energy = next(g for g in canonical["groups"] if g["name_en"] == "Energy")
        self.assertEqual((energy["group_id"], energy["name_zh"]), ("sector:energy", "能源類股"))


if __name__ == "__main__":
    unittest.main()
