"""Output-contract cases (MR-CON-*) for the market-rotation data files."""

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


def golden_v1():
    payload = json.loads(fixture.GOLDEN_V1.read_text())
    payload["generated_at"] = "2026-01-01T00:00:00+00:00"
    return payload


class V1ContractTests(unittest.TestCase):
    def assert_violation(self, payload, fragment):
        with self.assertRaises(contracts.ContractError) as caught:
            contracts.validate_v1(payload)
        self.assertTrue(any(fragment in error for error in caught.exception.errors),
                        f"expected a violation mentioning {fragment!r}, got:\n{caught.exception}")

    def test_mr_con_001_golden_output_satisfies_contract(self):
        contracts.validate_v1(golden_v1())

    def test_mr_con_001_rejects_nan_and_names_its_path(self):
        payload = golden_v1()
        payload["sectors"][0]["breadth"] = float("nan")
        self.assert_violation(payload, "$.sectors[0].breadth: non-finite")
        with self.assertRaises(ValueError):
            contracts.dump_json(payload)

    def test_mr_con_001_rejects_infinity_in_trajectory(self):
        payload = golden_v1()
        payload["industries"][2]["trajectory"][4]["x"] = float("inf")
        self.assert_violation(payload, "$.industries[2].trajectory[4].x: non-finite")

    def test_mr_con_001_rejects_missing_required_field(self):
        payload = golden_v1()
        del payload["sectors"][1]["rotation_score"]
        self.assert_violation(payload, "$.sectors[1:Health Care].rotation_score: missing field")

    def test_mr_con_001_rejects_unknown_quadrant(self):
        payload = golden_v1()
        payload["sectors"][0]["quadrant"] = "bullish"
        self.assert_violation(payload, "unknown quadrant 'bullish'")

    def test_mr_con_001_rejects_quadrant_that_contradicts_axes(self):
        payload = golden_v1()
        payload["sectors"][0]["quadrant"] = "lagging"
        payload["sectors"][0]["quadrant_zh"] = "落後"
        self.assert_violation(payload, "lagging contradicts")

    def test_mr_con_001_rejects_out_of_range_score_and_share(self):
        payload = golden_v1()
        payload["sectors"][0]["rotation_score"] = 101
        payload["sectors"][0]["breadth"] = -1
        self.assert_violation(payload, "rotation_score: 101 outside [0, 100]")
        self.assert_violation(payload, "breadth: -1 outside [0, 100]")

    def test_mr_con_001_rejects_boolean_numbers_and_wrong_types(self):
        payload = golden_v1()
        payload["coverage"]["priced_securities"] = "24"
        payload["sectors"][0]["persistence"] = True
        self.assert_violation(payload, "$.coverage.priced_securities: expected int")
        self.assert_violation(payload, "persistence: must be a number, not a boolean")

    def test_mr_con_001_rejects_coverage_below_publish_threshold(self):
        payload = golden_v1()
        payload["coverage"]["coverage_pct"] = 89.9
        self.assert_violation(payload, "coverage_pct: 89.9 outside [90.0, 100]")

    def test_mr_con_001_rejects_unsorted_or_duplicate_groups(self):
        payload = golden_v1()
        payload["sectors"].reverse()
        self.assert_violation(payload, "$.sectors: must be ordered by rotation_score")
        payload = golden_v1()
        payload["industries"].append(copy.deepcopy(payload["industries"][-1]))
        self.assert_violation(payload, "duplicate group key")

    def test_mr_con_001_rejects_trajectory_order_and_future_dates(self):
        payload = golden_v1()
        payload["sectors"][0]["trajectory"].reverse()
        self.assert_violation(payload, "dates must be unique and oldest first")
        payload = golden_v1()
        payload["sectors"][0]["trajectory"][-1]["date"] = "2099-01-01"
        self.assert_violation(payload, "is after as_of")

    def test_mr_con_001_rejects_undersized_groups_and_long_stock_lists(self):
        payload = golden_v1()
        payload["industries"][0]["member_count"] = 2
        payload["sectors"][0]["leaders"].append(copy.deepcopy(payload["sectors"][0]["leaders"][0]))
        self.assert_violation(payload, "member_count: 2 below minimum 3")
        self.assert_violation(payload, "leaders: 6 entries, maximum 5")

    def test_mr_con_001_rejects_invalid_unranked_group(self):
        payload = golden_v1()
        payload["coverage"]["unranked_groups"] = [
            {"type": "country", "key": "X", "missing_components": ["volume"]}]
        self.assert_violation(payload, "type: must be sector or industry")
        self.assert_violation(payload, "invalid components ['volume']")

    def test_mr_con_001_rejects_wrong_schema_version(self):
        payload = golden_v1()
        payload["schema_version"] = 2
        self.assert_violation(payload, "$.schema_version: expected 1")

    def test_dump_json_is_compact_and_newline_terminated(self):
        text = contracts.dump_json({"b": 1, "a": "資訊科技"})
        self.assertEqual(text, '{"b":1,"a":"資訊科技"}\n')


class V2ContractTests(unittest.TestCase):
    """MR-CON-002/003 and MR-PAR-001 on the fixture's v2 batch."""

    @classmethod
    def setUpClass(cls):
        cls.outputs = fixture.build_fixture_outputs()

    def batch(self):
        return {name: copy.deepcopy(self.outputs[name]) for name in ("v1", "summary", "groups", "stocks")}

    def assert_v2_violation(self, batch, fragment):
        with self.assertRaises(contracts.ContractError) as caught:
            contracts.validate_v2(batch["summary"], batch["groups"], batch["stocks"])
        self.assertTrue(any(fragment in error for error in caught.exception.errors),
                        f"expected {fragment!r} in:\n{caught.exception}")

    def assert_parity_violation(self, batch, fragment):
        with self.assertRaises(contracts.ContractError) as caught:
            contracts.check_parity(batch["v1"], batch["summary"], batch["groups"], batch["stocks"])
        self.assertTrue(any(fragment in error for error in caught.exception.errors),
                        f"expected {fragment!r} in:\n{caught.exception}")

    def test_golden_v2_files_are_unchanged(self):
        for name in ("summary", "groups", "stocks"):
            expected = json.loads(fixture.GOLDEN[name].read_text())
            changed = fixture.differences(fixture.stable(expected), fixture.stable(self.outputs[name]))
            self.assertEqual(changed, [], f"{name} golden drift:\n" + "\n".join(changed))

    def test_v2_batch_satisfies_contract_and_parity(self):
        batch = self.batch()
        contracts.validate_v2(batch["summary"], batch["groups"], batch["stocks"])
        contracts.check_parity(batch["v1"], batch["summary"], batch["groups"], batch["stocks"])

    def test_mr_con_002_mixed_dataset_ids_are_rejected(self):
        batch = self.batch()
        batch["stocks"]["dataset_id"] = "sha256:" + "0" * 64
        self.assert_v2_violation(batch, "*.dataset_id: files come from different batches")

    def test_mr_con_002_mixed_as_of_and_schema_are_rejected(self):
        batch = self.batch()
        batch["groups"]["as_of"] = "2026-06-17"
        self.assert_v2_violation(batch, "*.as_of: files come from different batches")
        batch = self.batch()
        batch["summary"]["schema_version"] = 3
        self.assert_v2_violation(batch, "summary.schema_version: expected 2, got 3")

    def test_mr_con_002_schema_name_must_match_file_role(self):
        batch = self.batch()
        batch["groups"]["schema_name"] = "market-rotation-stocks"
        self.assert_v2_violation(batch, "groups.schema_name: expected market-rotation-groups")

    def test_mr_con_003_summary_references_must_resolve(self):
        batch = self.batch()
        batch["summary"]["data"]["roles"]["leader"] = "sector:unknown"
        batch["summary"]["data"]["defaults"]["top_industry_ids"].append("sector:energy")
        batch["summary"]["data"]["cards"][0]["evidence"][0]["field"] = "metrics.not_a_metric"
        self.assert_v2_violation(batch, "summary.data.roles.leader: 'sector:unknown' is not a ranked sector")
        self.assert_v2_violation(batch, "'sector:energy' is not a ranked industry")
        self.assert_v2_violation(batch, "metrics.not_a_metric does not resolve")

    def test_mr_con_003_role_must_sit_in_its_quadrant(self):
        batch = self.batch()
        batch["summary"]["data"]["roles"]["leader"] = "sector:energy"
        self.assert_v2_violation(batch, "sector:energy is lagging, not leading")

    def test_mr_con_003_group_stock_references_must_resolve_to_that_sector(self):
        batch = self.batch()
        tech = batch["groups"]["data"]["sectors"][0]
        tech["leader_stock_ids"][0] = "security:ene0"
        tech["laggard_stock_ids"][0] = "security:ghost"
        self.assert_v2_violation(batch, "security:ene0 belongs to sector:energy")
        self.assert_v2_violation(batch, "unknown stock security:ghost")

    def test_mr_con_003_duplicate_ids_are_rejected(self):
        batch = self.batch()
        stocks = batch["stocks"]["data"]["stocks"]
        stocks.insert(1, copy.deepcopy(stocks[0]))
        self.assert_v2_violation(batch, "duplicate stock id")
        batch = self.batch()
        industries = batch["groups"]["data"]["industries"]
        industries.append(copy.deepcopy(industries[-1]))
        self.assert_v2_violation(batch, "duplicate group id")

    def test_mr_con_003_unranked_group_cannot_also_be_ranked(self):
        batch = self.batch()
        batch["summary"]["data"]["coverage"]["unranked_groups"] = [{
            "group_id": "sector:energy", "group_type": "sector", "name_en": "Energy",
            "missing_components": ["dollar_volume_expansion"]}]
        self.assert_v2_violation(batch, "an unranked group cannot also be ranked")

    def test_summary_size_limit(self):
        batch = self.batch()
        batch["summary"]["data"]["methodology"]["padding"] = "x" * contracts.SUMMARY_MAX_BYTES
        self.assert_v2_violation(batch, f"exceeds {contracts.SUMMARY_MAX_BYTES}")

    def test_mr_par_001_changed_number_names_group_and_field(self):
        batch = self.batch()
        batch["groups"]["data"]["industries"][3]["metrics"]["breadth"] += 0.01
        name = batch["groups"]["data"]["industries"][3]["name_en"]
        self.assert_parity_violation(batch, f"parity industry[{name}].metrics.breadth")

    def test_mr_par_001_changed_leader_or_order_is_caught(self):
        batch = self.batch()
        batch["groups"]["data"]["sectors"][0]["leader_stock_ids"].reverse()
        self.assert_parity_violation(batch, "parity sector[Information Technology].leaders[0].ticker")
        batch = self.batch()
        batch["v1"]["industries"][0], batch["v1"]["industries"][1] = (
            batch["v1"]["industries"][1], batch["v1"]["industries"][0])
        self.assert_parity_violation(batch, ".position")

    def test_mr_par_001_summary_context_must_match_v1(self):
        batch = self.batch()
        batch["summary"]["data"]["benchmark"]["return_20d"] = 9.99
        batch["summary"]["data"]["coverage"]["priced_securities"] = 23
        self.assert_parity_violation(batch, "parity benchmark.return_20d")
        self.assert_parity_violation(batch, "parity coverage.priced_securities")

    def test_dataset_id_ignores_generated_at_but_tracks_content(self):
        later = fixture.build_fixture_outputs("2027-01-01T00:00:00+00:00")
        self.assertEqual(later["summary"]["dataset_id"], self.outputs["summary"]["dataset_id"])
        universe, closes, volumes = fixture.load_fixture()
        closes.iloc[-1, 0] *= 1.01
        builder = fixture.load_builder()
        canonical, _ = builder.calculate_canonical(universe, closes, volumes)
        self.assertNotEqual(contracts.compute_dataset_id(canonical), self.outputs["summary"]["dataset_id"])

    def test_dataset_id_tracks_registry_ids(self):
        universe, closes, volumes = fixture.load_fixture()
        builder = fixture.load_builder()
        registry = {"schema_version": 1, "securities": [], "groups": [{
            "group_id": "sector:tech", "group_type": "sector",
            "name_en": "Information Technology", "aliases": []}]}
        canonical, _ = builder.calculate_canonical(universe, closes, volumes, registry)
        self.assertNotEqual(contracts.compute_dataset_id(canonical), self.outputs["summary"]["dataset_id"])

    def test_registry_contract(self):
        contracts.validate_registry(self.outputs["registry"])
        broken = copy.deepcopy(self.outputs["registry"])
        broken["groups"][1]["aliases"] = [broken["groups"][0]["name_en"]]
        broken["groups"][1]["group_type"] = broken["groups"][0]["group_type"]
        with self.assertRaisesRegex(contracts.ContractError, "maps to more than one id"):
            contracts.validate_registry(broken)


class IntegrityCheckTests(unittest.TestCase):
    """C-45 on a temporary repo root holding fixture artifacts."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location("check_integrity", ROOT / "scripts/check_integrity.py")
        cls.integrity = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.integrity)
        cls.outputs = fixture.build_fixture_outputs()

    def setUp(self):
        import tempfile
        self.directory = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.directory.name)
        self.original_root = self.integrity.REPO_ROOT
        self.integrity.REPO_ROOT = self.root
        for name, filename in (("v1", "market_rotation.json"), ("registry", "market_rotation_registry.json"),
                               ("summary", "market_rotation_summary.json"),
                               ("groups", "market_rotation_groups.json"),
                               ("stocks", "market_rotation_stocks.json")):
            (self.root / filename).write_text(contracts.dump_json(self.outputs[name]))

    def tearDown(self):
        self.integrity.REPO_ROOT = self.original_root
        self.directory.cleanup()

    def test_consistent_batch_passes(self):
        passed, detail = self.integrity.c45()
        self.assertTrue(passed, detail)
        self.assertIn("逐欄一致", detail)

    def test_missing_v2_file_fails(self):
        (self.root / "market_rotation_stocks.json").unlink()
        passed, detail = self.integrity.c45()
        self.assertFalse(passed)
        self.assertIn("v2 檔案不完整", detail)

    def test_pending_state_before_first_dual_write(self):
        for name in ("summary", "groups", "stocks"):
            (self.root / f"market_rotation_{name}.json").unlink()
        passed, detail = self.integrity.c45()
        self.assertTrue(passed, detail)
        self.assertIn("尚未產出", detail)

    def test_mixed_batch_fails(self):
        stocks = copy.deepcopy(self.outputs["stocks"])
        stocks["dataset_id"] = "sha256:" + "f" * 64
        (self.root / "market_rotation_stocks.json").write_text(contracts.dump_json(stocks))
        passed, detail = self.integrity.c45()
        self.assertFalse(passed)
        self.assertIn("different batches", detail)

    def test_ids_missing_from_registry_fail(self):
        registry = copy.deepcopy(self.outputs["registry"])
        registry["securities"] = [row for row in registry["securities"] if row["ticker"] != "TEC0"]
        (self.root / "market_rotation_registry.json").write_text(contracts.dump_json(registry))
        passed, detail = self.integrity.c45()
        self.assertFalse(passed)
        self.assertIn("security:tec0", detail)


class WritePathTests(unittest.TestCase):
    """MR-IO-*: nothing on disk changes unless every new payload is valid."""

    @classmethod
    def setUpClass(cls):
        cls.builder = fixture.load_builder()

    def setUp(self):
        import tempfile
        self.directory = tempfile.TemporaryDirectory()
        self.folder = pathlib.Path(self.directory.name)
        self.path = self.folder / "market_rotation.json"

    def tearDown(self):
        self.directory.cleanup()

    def leftovers(self):
        return sorted(item.name for item in self.folder.iterdir() if item.name.endswith(".tmp"))

    def test_mr_io_002_substantive_change_rewrites_compact_file(self):
        first = golden_v1()
        self.assertTrue(self.builder.write_if_changed(self.path, first, contracts.validate_v1))
        changed = golden_v1()
        changed["sectors"][0]["breadth"] = 50.0
        self.assertTrue(self.builder.write_if_changed(self.path, changed, contracts.validate_v1))
        text = self.path.read_text()
        self.assertEqual(text, contracts.dump_json(changed))
        self.assertTrue(text.endswith("}\n") and "\n" not in text[:-1])

    def test_mr_io_002_reformats_pretty_file_without_touching_generated_at(self):
        stored = dict(golden_v1(), generated_at="first")
        self.path.write_text(json.dumps(stored, ensure_ascii=False, indent=2))
        rerun = dict(golden_v1(), generated_at="second")
        self.assertTrue(self.builder.write_if_changed(self.path, rerun, contracts.validate_v1))
        self.assertEqual(json.loads(self.path.read_text())["generated_at"], "first")
        self.assertFalse(self.builder.write_if_changed(self.path, rerun, contracts.validate_v1))

    def test_mr_io_003_corrupt_file_is_repaired_by_valid_payload(self):
        self.path.write_text('{"schema_version": 1, "sectors": [')
        self.assertTrue(self.builder.write_if_changed(self.path, golden_v1(), contracts.validate_v1))
        contracts.validate_v1(json.loads(self.path.read_text()))

    def test_mr_io_003_corrupt_file_untouched_when_new_payload_is_invalid(self):
        broken = '{"schema_version": 1, "sectors": ['
        self.path.write_text(broken)
        invalid = golden_v1()
        invalid["sectors"][0]["quadrant"] = "bullish"
        with self.assertRaises(contracts.ContractError):
            self.builder.write_if_changed(self.path, invalid, contracts.validate_v1)
        self.assertEqual(self.path.read_text(), broken)

    def test_contract_failure_keeps_published_file(self):
        self.builder.write_if_changed(self.path, golden_v1(), contracts.validate_v1)
        before = self.path.read_bytes()
        invalid = golden_v1()
        del invalid["coverage"]
        with self.assertRaises(contracts.ContractError):
            self.builder.write_if_changed(self.path, invalid, contracts.validate_v1)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.leftovers(), [])

    def test_non_finite_payload_is_refused_even_without_validator(self):
        self.builder.write_if_changed(self.path, {"value": 1})
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.builder.write_if_changed(self.path, {"value": float("nan")})
        self.assertEqual(self.path.read_bytes(), before)

    def test_publish_outputs_writes_v1_v2_and_registry_together(self):
        registry_path = self.folder / "market_rotation_registry.json"
        first = fixture.build_fixture_outputs("first")
        changed = self.builder.publish_outputs(first, self.path, registry_path)
        self.assertEqual(changed, {name: True for name in ("v1", "summary", "groups", "stocks", "registry")})
        written = {name: json.loads((self.folder / f"market_rotation_{name}.json").read_text())
                   for name in ("summary", "groups", "stocks")}
        self.assertEqual({payload["dataset_id"] for payload in written.values()},
                         {first["summary"]["dataset_id"]})
        rerun = fixture.build_fixture_outputs("second")
        self.assertEqual(self.builder.publish_outputs(rerun, self.path, registry_path),
                         {name: False for name in changed}, "MR-IO-001 across the batch")
        self.assertEqual(json.loads(self.path.read_text())["generated_at"], "first")
        self.assertEqual(self.leftovers(), [])

    def test_batch_publish_replaces_nothing_when_any_file_fails(self):
        other = self.folder / "other.json"
        self.builder.write_if_changed(self.path, golden_v1(), contracts.validate_v1)
        other.write_text('{"old":true}\n')
        before = (self.path.read_bytes(), other.read_bytes())
        changed = golden_v1()
        changed["sectors"][0]["breadth"] = 50.0

        def reject(_payload):
            raise contracts.ContractError(["$.other: rejected for test"])

        with self.assertRaises(contracts.ContractError):
            self.builder.publish_artifacts([
                (self.path, changed, contracts.validate_v1),
                (other, {"new": True}, reject),
            ])
        self.assertEqual((self.path.read_bytes(), other.read_bytes()), before)
        self.assertEqual(self.leftovers(), [])


if __name__ == "__main__":
    unittest.main()
