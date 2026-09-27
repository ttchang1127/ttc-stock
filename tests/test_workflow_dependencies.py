import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
REQUIRED_PACKAGES = ("pandas", "yfinance", "pypdf", "lxml", "curl_cffi", "PyYAML")
# Run by data-freshness.yml without installing anything.
STDLIB_ONLY_SCRIPTS = {"check_data_freshness.py"}


class WorkflowDependencyTests(unittest.TestCase):
    """Dependencies come from one file so no workflow can drift behind the suite.

    sec-filing-alerts.yml once listed its own subset without pandas and failed
    at test import on every run from 2026-09-13, silently freezing SEC radars.
    """

    def test_requirements_file_lists_what_the_code_imports(self):
        names = {re.split(r"[<>=!~\[ ]", line.strip(), maxsplit=1)[0].lower()
                 for line in (ROOT / "requirements.txt").read_text().splitlines()
                 if line.strip() and not line.startswith("#")}
        for package in REQUIRED_PACKAGES:
            self.assertIn(package.lower(), names, f"requirements.txt is missing {package}")

    def test_every_third_party_import_is_covered_by_requirements(self):
        """A module imported by code or tests but missing here breaks CI at import time."""
        import ast
        import sys
        # Import name -> requirements entry (numpy arrives with pandas).
        provided_by = {"yaml": "pyyaml", "numpy": "pandas"}
        names = {re.split(r"[<>=!~\[ ]", line.strip(), maxsplit=1)[0].lower()
                 for line in (ROOT / "requirements.txt").read_text().splitlines()
                 if line.strip() and not line.startswith("#")}
        local = {path.stem for folder in ("scripts", "tests") for path in (ROOT / folder).glob("*.py")}
        missing = set()
        for folder in ("scripts", "tests"):
            for path in (ROOT / folder).rglob("*.py"):
                for node in ast.walk(ast.parse(path.read_text())):
                    modules = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                               else [node.module] if isinstance(node, ast.ImportFrom)
                               and node.module and not node.level else [])
                    for module in modules:
                        top = module.split(".")[0]
                        if top in sys.stdlib_module_names or top in local or top == "__future__":
                            continue
                        if provided_by.get(top, top).lower() not in names:
                            missing.add(f"{path.relative_to(ROOT)}: {top}")
        self.assertEqual(sorted(missing), [], "add these packages to requirements.txt")

    def test_every_python_workflow_installs_the_requirements_file(self):
        checked = 0
        for path in sorted(WORKFLOWS.glob("*.yml")):
            text = path.read_text()
            installs = re.findall(r"pip install[^\n]*", text)
            for line in installs:
                self.assertIn("-r requirements.txt", line,
                              f"{path.name} installs packages outside requirements.txt: {line}")
            scripts = set(re.findall(r"python3 scripts/([a-z0-9_]+\.py)", text))
            needs_packages = "unittest" in text or bool(scripts - STDLIB_ONLY_SCRIPTS)
            if needs_packages:
                checked += 1
                self.assertTrue(installs, f"{path.name} runs package-dependent Python without installing")
        self.assertGreaterEqual(checked, 5)

    def test_stdlib_only_scripts_import_no_third_party_packages(self):
        import ast
        import sys
        local = {path.stem for path in (ROOT / "scripts").glob("*.py")}
        for name in STDLIB_ONLY_SCRIPTS | {"market_calendar.py"}:
            tree = ast.parse((ROOT / "scripts" / name).read_text())
            for node in ast.walk(tree):
                modules = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                           else [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
                for module in modules:
                    top = module.split(".")[0]
                    self.assertTrue(top in sys.stdlib_module_names or top in local or top == "__future__",
                                    f"{name} imports third-party {module}")

    def test_session_start_hook_installs_the_requirements_file(self):
        hook = (ROOT / ".claude/hooks/session-start.sh").read_text()
        self.assertIn("requirements.txt", hook)
        self.assertNotRegex(hook, r"pip install[^\n]*'?pandas")


class PullRequestTestWorkflowTests(unittest.TestCase):
    def test_pull_requests_run_full_suite_and_integrity_offline(self):
        workflow = (WORKFLOWS / "tests.yml").read_text()
        self.assertIn("pull_request:", workflow)
        self.assertIn("python3 -m unittest discover -s tests -v", workflow)
        self.assertIn("python3 scripts/check_integrity.py --quiet", workflow)
        self.assertIn("contents: read", workflow, "PR checks must not be able to push")
        for fetcher in ("fetch_", "build_market_rotation.py", "watch_sec_filings.py"):
            self.assertNotIn(fetcher, workflow, "PR checks must not fetch live data")


if __name__ == "__main__":
    unittest.main()
