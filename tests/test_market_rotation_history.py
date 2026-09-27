import copy
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import market_rotation_fixture as fixture  # noqa: E402
import market_rotation_history as history  # noqa: E402
from jsonio import replace_texts  # noqa: E402


class HistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        builder = fixture.load_builder()
        cls.universe, closes, volumes = fixture.load_fixture()
        canonical, registry = fixture.fixture_canonical()
        research = builder.calculate_research(cls.universe, closes, volumes, canonical, registry)
        cls.outputs = builder.build_outputs(canonical, registry, "t", research)
        cls.record = history.snapshot_record(cls.outputs["research"], cls.outputs["groups"],
                                             cls.outputs["summary"], cls.universe)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.folder = pathlib.Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def record_on(self, as_of, **changes):
        record = copy.deepcopy(self.record)
        record["as_of"] = as_of
        record.update(changes)
        return record

    def append(self, record):
        texts, status, message = history.plan_append(record, self.folder)
        replace_texts(texts)
        return status, texts

    def snapshot_files(self):
        return {path.relative_to(self.folder).as_posix(): path.read_text()
                for path in sorted(self.folder.rglob("*")) if path.is_file()}

    def test_snapshot_keeps_aggregates_and_audit_fields_only(self):
        record = self.record
        self.assertEqual((record["history_quality"], record["snapshot_kind"]), ("A", "forward_frozen"))
        self.assertTrue(record["universe_snapshot_id"].startswith("sha256:"))
        self.assertEqual(record["dataset_id"], self.outputs["summary"]["dataset_id"])
        self.assertNotIn("stocks", record)
        for row in record["groups"].values():
            self.assertIn("confirmed_state", row)
            self.assertIn("top1_removal_impact_pp", row)

    def test_append_then_identical_rerun_changes_nothing(self):
        self.assertEqual(self.append(self.record_on("2026-09-25"))[0], "appended")
        before = self.snapshot_files()
        status, texts = self.append(self.record_on("2026-09-25"))
        self.assertEqual((status, texts), ("unchanged", {}))
        self.assertEqual(self.snapshot_files(), before)
        index = json.loads((self.folder / "index.json").read_text())
        self.assertEqual((index["snapshot_count"], index["a_history_effective_from"]), (1, "2026-09-25"))

    def test_same_session_with_different_content_keeps_the_original(self):
        self.append(self.record_on("2026-09-25"))
        before = self.snapshot_files()
        revised = self.record_on("2026-09-25", dataset_id="sha256:" + "1" * 64)
        self.assertEqual(self.append(revised)[0], "conflict")
        self.assertEqual(self.snapshot_files(), before)

    def test_sessions_only_move_forward(self):
        self.append(self.record_on("2026-09-25"))
        self.assertEqual(self.append(self.record_on("2026-09-24"))[0], "out_of_order")

    def test_months_are_split_and_listed(self):
        for as_of in ("2026-09-29", "2026-09-30", "2026-10-01"):
            self.assertEqual(self.append(self.record_on(as_of))[0], "appended")
        index = json.loads((self.folder / "index.json").read_text())
        self.assertEqual([(m["month"], m["count"]) for m in index["months"]], [("2026-09", 2), ("2026-10", 1)])
        self.assertEqual(index["last_as_of"], "2026-10-01")
        september = (self.folder / "2026/2026-09.jsonl").read_text().splitlines()
        self.assertEqual([json.loads(line)["as_of"] for line in september], ["2026-09-29", "2026-09-30"])
        self.assertEqual(history.validate_history(self.folder), [])

    def test_validation_catches_edits_to_recorded_history(self):
        self.append(self.record_on("2026-09-29"))
        self.append(self.record_on("2026-09-30"))
        path = self.folder / "2026/2026-09.jsonl"
        lines = path.read_text().splitlines()
        edited = json.loads(lines[0])
        edited["market"]["confirmed_state"] = "broad_expansion"
        path.write_text("\n".join([json.dumps(edited), lines[1]]) + "\n")
        self.assertTrue(any("changed after it was recorded" in p for p in history.validate_history(self.folder)))


class BuilderHistoryTests(unittest.TestCase):
    def run_main(self, folder, extra):
        builder = fixture.load_builder()
        universe, closes, volumes = fixture.load_fixture()
        (folder / "universe.json").write_text(json.dumps(universe))
        argv = ["build_market_rotation.py", "--skip-universe-refresh",
                "--universe", str(folder / "universe.json"),
                "--output", str(folder / "market_rotation.json"),
                "--registry", str(folder / "market_rotation_registry.json"),
                "--history-dir", str(folder / "history"),
                "--expected-session", closes.index[-1].date().isoformat(), *extra]
        original_fetch, original_argv = builder.fetch_market_data, sys.argv
        builder.fetch_market_data = lambda *args, **kwargs: (closes.copy(), volumes.copy())
        sys.argv = argv
        try:
            builder.main()
        finally:
            builder.fetch_market_data, sys.argv = original_fetch, original_argv

    def test_daily_run_writes_one_snapshot_and_reruns_are_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = pathlib.Path(directory)
            self.run_main(folder, ["--write-history"])
            month_files = list((folder / "history").rglob("*.jsonl"))
            self.assertEqual(len(month_files), 1)
            first = month_files[0].read_text()
            research = json.loads((folder / "market_rotation_research.json").read_text())
            self.assertEqual(json.loads(first)["dataset_id"], research["dataset_id"])
            self.run_main(folder, ["--write-history"])
            self.assertEqual(month_files[0].read_text(), first)
            self.assertEqual(history.validate_history(folder / "history"), [])

    def test_history_is_opt_in_and_never_from_stale_replays(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = pathlib.Path(directory)
            self.run_main(folder, [])
            self.assertFalse((folder / "history").exists())
            with self.assertRaises(SystemExit):
                self.run_main(folder, ["--write-history", "--allow-stale"])


if __name__ == "__main__":
    unittest.main()
