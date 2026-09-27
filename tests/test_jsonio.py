import json
import pathlib
import re
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import jsonio  # noqa: E402


class JsonIoTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.folder = pathlib.Path(self.directory.name)
        self.path = self.folder / "out.json"

    def tearDown(self):
        self.directory.cleanup()

    def leftovers(self):
        return [item.name for item in self.folder.iterdir() if item.name.endswith(".tmp")]

    def test_dumps_formats_match_existing_files(self):
        self.assertEqual(jsonio.dumps({"a": "資訊", "b": [1]}), '{"a":"資訊","b":[1]}\n')
        self.assertEqual(jsonio.dumps({"a": 1}, indent=1), '{\n "a": 1\n}\n')

    def test_dumps_refuses_nan_and_infinity(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValueError):
                jsonio.dumps({"value": value})

    def test_load_json_default_for_missing_file(self):
        self.assertEqual(jsonio.load_json(self.path, {"empty": True}), {"empty": True})
        self.assertIsNone(jsonio.load_json(self.path, None))
        self.path.write_text('{"x": 1}')
        self.assertEqual(jsonio.load_json(self.path), {"x": 1})

    def test_load_json_without_default_requires_the_file(self):
        with self.assertRaises(FileNotFoundError):
            jsonio.load_json(self.path)

    def test_write_json_replaces_file_without_leftovers(self):
        jsonio.write_json(self.path, {"generated_at": "t", "companies": {"A": {}}})
        self.assertEqual(json.loads(self.path.read_text())["companies"], {"A": {}})
        self.assertEqual(self.leftovers(), [])

    def test_failed_validation_or_nan_leaves_published_file_untouched(self):
        self.path.write_text('{"old": true}\n')
        with self.assertRaises(ValueError):
            jsonio.write_json(self.path, {"companies": {}}, validate=jsonio.require_companies(1))
        with self.assertRaises(ValueError):
            jsonio.write_json(self.path, {"value": float("nan")})
        self.assertEqual(self.path.read_text(), '{"old": true}\n')
        self.assertEqual(self.leftovers(), [])

    def test_replace_texts_writes_every_file(self):
        other = self.folder / "nested" / "b.json"
        jsonio.replace_texts({self.path: "a\n", other: "b\n"})
        self.assertEqual((self.path.read_text(), other.read_text()), ("a\n", "b\n"))

    def test_require_companies_messages(self):
        validate = jsonio.require_companies(14)
        with self.assertRaisesRegex(ValueError, "generated_at"):
            validate({"companies": {}})
        with self.assertRaisesRegex(ValueError, "at least 14 companies, got 13"):
            validate({"generated_at": "t", "companies": {str(n): {} for n in range(13)}})
        with self.assertRaisesRegex(ValueError, r"company rows must be objects: \['X'\]"):
            validate({"generated_at": "t", "companies": {**{str(n): {} for n in range(13)}, "X": 1}})
        validate({"generated_at": "t", "companies": {str(n): {} for n in range(14)}})


class GeneratorAdoptionTests(unittest.TestCase):
    def test_core_generators_publish_through_jsonio(self):
        for name, source in (("compute_fundamentals", "fin"), ("compute_financial_health", "fin"),
                             ("compute_valuation", "fundamentals")):
            text = (ROOT / f"scripts/{name}.py").read_text()
            self.assertIn(f"write_json(OUTPUT_PATH, payload, indent=1, validate=require_companies(len({source})))",
                          text, name)
            self.assertNotIn("OUTPUT_PATH.write_text", text, f"{name} must not write unvalidated output")


def scheduled_scripts():
    """Every scripts/*.py a GitHub Actions workflow runs."""
    names = set()
    for workflow in (ROOT / ".github/workflows").glob("*.yml"):
        names.update(re.findall(r"python3? scripts/(\w+)\.py", workflow.read_text()))
    return sorted(names)


class ScheduledWriterTests(unittest.TestCase):
    # Its reader deliberately falls back on unreadable JSON, not only missing files.
    OWN_LOADER = {"build_company_event_calendar"}
    # Read-only checker; its JSON writes go to scratch copies it builds itself.
    CHECKERS = {"check_integrity"}

    def test_scheduled_scripts_publish_through_jsonio(self):
        scripts = scheduled_scripts()
        self.assertIn("watch_sec_filings", scripts)
        for name in sorted(set(scripts) - self.CHECKERS):
            text = (ROOT / f"scripts/{name}.py").read_text()
            with self.subTest(script=name):
                self.assertIsNone(re.search(r"write_text\(\s*json\.dumps", text),
                                  "write JSON with jsonio.write_json/replace_texts")
                self.assertNotIn("def atomic_write", text)
                if name not in self.OWN_LOADER:
                    self.assertNotIn("def load_json", text, "import load_json from jsonio")

    def test_sec_watcher_advances_state_and_events_together(self):
        text = (ROOT / "scripts/watch_sec_filings.py").read_text()
        batch = re.search(r"replace_texts\(\{(.*?)\}\)", text, re.S)
        self.assertIsNotNone(batch)
        for target in ("args.state", "args.events", "args.note"):
            self.assertIn(target, batch.group(1))


if __name__ == "__main__":
    unittest.main()
