import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
REQUIRED_PACKAGES = ("pandas", "yfinance", "pypdf", "lxml", "curl_cffi")


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

    def test_every_python_workflow_installs_the_requirements_file(self):
        checked = 0
        for path in sorted(WORKFLOWS.glob("*.yml")):
            text = path.read_text()
            if "python3 " not in text:
                continue
            checked += 1
            installs = re.findall(r"pip install[^\n]*", text)
            self.assertTrue(installs, f"{path.name} runs Python without installing dependencies")
            for line in installs:
                self.assertIn("-r requirements.txt", line,
                              f"{path.name} installs packages outside requirements.txt: {line}")
        self.assertGreaterEqual(checked, 4)

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
