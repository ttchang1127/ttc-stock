"""data_manifest.json must describe every data file and match what workflows do."""

import pathlib
import re
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import data_manifest  # noqa: E402

WORKFLOWS = ROOT / ".github/workflows"


def git_add_list(workflow: str) -> set[str]:
    text = (WORKFLOWS / f"{workflow}.yml").read_text()
    paths = set()
    for match in re.finditer(r"git add ((?:[^\n]*\\\n)*[^\n]*)", text):
        paths |= {token for token in match.group(1).replace("\\\n", " ").split() if token != "-A"}
    return paths


class ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = data_manifest.load_manifest()
        cls.files = {row["path"]: row for row in cls.manifest["files"]}

    def test_every_root_json_file_is_described(self):
        root_json = {path.name for path in ROOT.glob("*.json")} - {"data_manifest.json"}
        missing = sorted(root_json - set(self.files))
        self.assertEqual(missing, [], "add these files to data_manifest.json")

    def test_every_described_file_exists(self):
        missing = sorted(path for path, row in self.files.items()
                         if not (ROOT / path).exists() and not row.get("awaiting_first_run"))
        self.assertEqual(missing, [])

    def test_awaiting_first_run_flag_is_removed_once_the_file_exists(self):
        stale = sorted(path for path, row in self.files.items()
                       if row.get("awaiting_first_run") and (ROOT / path).exists())
        self.assertEqual(stale, [], "the producer has run: drop awaiting_first_run from these entries")

    def test_entries_use_known_values(self):
        policies = set(self.manifest["edit_policies"])
        cadences = set(self.manifest["cadence_values"])
        workflows = {path.stem for path in WORKFLOWS.glob("*.yml")}
        for row in self.manifest["files"] + self.manifest["patterns"]:
            label = row.get("path") or row.get("pattern")
            self.assertIn(row["edit"], policies, label)
            self.assertIn(row["kind"], {"generated", "human", "mixed"}, label)
            self.assertTrue(set(row["committed_by"]) <= workflows, label)
            if "cadence" in row:
                self.assertIn(row["cadence"], cadences, label)
            if row["kind"] == "generated":
                self.assertEqual(row["edit"], "never", label)
                self.assertTrue(row["producer"], label)
            if row["kind"] == "human":
                self.assertIsNone(row["producer"], label)

    def test_producers_exist_and_name_their_output(self):
        for row in self.manifest["files"] + self.manifest["patterns"]:
            producer = row.get("producer")
            if not producer:
                continue
            source = (ROOT / producer)
            self.assertTrue(source.is_file(), f"missing producer {producer}")
            name = pathlib.Path(row.get("path", "")).name
            if not name:
                continue
            # v2 rotation files are named market_rotation_{name}.json by the builder.
            templated = f"{name.rsplit('_', 1)[0]}_{{"
            text = source.read_text()
            self.assertTrue(name in text or templated in text, f"{producer} never names {name}")

    def test_sec_workflows_commit_exactly_what_the_manifest_says(self):
        for workflow in ("sec-filing-alerts", "sec-13f-radar"):
            added = git_add_list(workflow)
            for path in sorted(added):
                if path.endswith("/"):
                    self.assertTrue(any(row["pattern"] == f"^{path}" and workflow in row["committed_by"]
                                        for row in self.manifest["patterns"]), f"{workflow}: {path}")
                else:
                    self.assertIn(workflow, self.files[path]["committed_by"], f"{workflow} adds {path}")
            declared = {path for path, row in self.files.items() if workflow in row["committed_by"]}
            self.assertEqual(sorted(declared - added), [], f"{workflow} never adds these declared files")

    def test_daily_workflow_uses_the_manifest_not_an_inline_regex(self):
        workflow = (WORKFLOWS / "update-prices.yml").read_text()
        self.assertIn("python3 scripts/data_manifest.py check-changed --workflow update-prices", workflow)
        self.assertNotIn("grep -Ev", workflow)

    def test_human_maintained_files_are_never_committed_by_the_daily_refresh(self):
        for path, row in self.files.items():
            if row["kind"] == "human":
                self.assertNotIn("update-prices", row["committed_by"], path)

    def test_generated_rotation_and_report_outputs_are_committable(self):
        for path in ("market_rotation_summary.json", "market_rotation_registry.json", "prices.json",
                     "nvda_report.html", "30_Analysis/NVDA_Master_Investment_Thesis_2026.md",
                     "60_SEC_Filing_Radar/Research_Synthesis.md"):
            self.assertTrue(data_manifest.may_commit(path, "update-prices", self.manifest), path)
        for path in ("portfolio_holdings.json", "dcf_assumptions.json", "dashboard.html",
                     "scripts/build_market_rotation.py", "sec_filing_alerts.json"):
            self.assertFalse(data_manifest.may_commit(path, "update-prices", self.manifest), path)

    def test_rendered_regex_agrees_with_entry_lookup(self):
        regex = data_manifest.allowlist_regex("update-prices", self.manifest)
        tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
        for path in tracked + ["new_report.html", "unknown.json", "prices.json.bak"]:
            self.assertEqual(bool(re.search(regex, path)),
                             data_manifest.may_commit(path, "update-prices", self.manifest), path)


class CheckChangedCliTests(unittest.TestCase):
    def run_cli(self, *paths):
        return subprocess.run([sys.executable, str(ROOT / "scripts/data_manifest.py"), "check-changed",
                               "--workflow", "update-prices", *paths], capture_output=True, text=True)

    def test_allowed_paths_pass(self):
        result = self.run_cli("prices.json", "market_rotation_stocks.json", "tsla_report.html")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unexpected_paths_fail_with_reasons(self):
        result = self.run_cli("prices.json", "portfolio_holdings.json", "stray.txt")
        self.assertEqual(result.returncode, 1)
        self.assertIn("portfolio_holdings.json (committed_by ['sec-filing-alerts'])", result.stdout)
        self.assertIn("stray.txt (not in data_manifest.json)", result.stdout)


if __name__ == "__main__":
    unittest.main()
