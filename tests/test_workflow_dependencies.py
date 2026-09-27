import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"


class WorkflowTestDependencyTests(unittest.TestCase):
    def test_workflows_running_full_suite_install_its_imports(self):
        """A workflow that runs every test module must install what they import.

        sec-filing-alerts.yml ran `unittest discover` without pandas and failed
        at import on every run from 2026-09-13, silently freezing SEC radars.
        """
        full_suite = re.compile(r"unittest discover -s tests(?! -p)")
        checked = 0
        for path in sorted(WORKFLOWS.glob("*.yml")):
            text = path.read_text()
            if not full_suite.search(text):
                continue
            checked += 1
            installs = " ".join(re.findall(r"pip install[^\n]*", text))
            for package in ("pandas", "yfinance", "pypdf"):
                self.assertIn(package, installs, f"{path.name} runs the full suite without {package}")
        self.assertGreater(checked, 0)


if __name__ == "__main__":
    unittest.main()
