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
