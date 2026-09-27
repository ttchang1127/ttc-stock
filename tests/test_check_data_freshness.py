import importlib.util
import json
import pathlib
import tempfile
import unittest
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("check_data_freshness", ROOT / "scripts/check_data_freshness.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

# Tuesday 2026-09-15 05:37 UTC = Tuesday 01:37 in New York, before the 18:00
# cutoff, so Monday 09-14 is the latest session whose close should be published.
NOW = datetime(2026, 9, 15, 5, 37, tzinfo=timezone.utc)


class FreshnessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.directory.name)
        (self.root / ".github").mkdir()
        self.write(prices="2026-09-14", rotation="2026-09-14", sec="2026-09-12T04:10:00+00:00")

    def tearDown(self):
        self.directory.cleanup()

    def write(self, prices=None, rotation=None, sec=None):
        if prices:
            (self.root / "prices.json").write_text(json.dumps(
                {"series": {"SPY": {"dates": ["2026-09-01", prices], "closes": [1, 2]}}}))
        if rotation:
            (self.root / "market_rotation.json").write_text(json.dumps({"as_of": rotation}))
        if sec:
            (self.root / ".github/sec-filing-state.json").write_text(json.dumps({"updated_at": sec}))

    def status(self, now=NOW):
        return {row["key"]: row for row in MODULE.evaluate(self.root, now)}

    def test_everything_current_is_fresh(self):
        self.assertEqual({key: row["status"] for key, row in self.status().items()},
                         {"prices": "fresh", "market_rotation": "fresh", "sec_watcher": "fresh"})

    def test_one_session_behind_is_tolerated(self):
        self.write(prices="2026-09-11")
        self.assertEqual(self.status()["prices"]["status"], "fresh")

    def test_two_sessions_behind_is_stale(self):
        self.write(rotation="2026-09-10")
        row = self.status()["market_rotation"]
        self.assertEqual(row["status"], "stale")
        self.assertIn("落後 2 個 NYSE 交易日", row["detail"])

    def test_exchange_holidays_do_not_count_as_lag(self):
        # Tuesday after Labor Day: Friday 09-04 is only one session behind.
        self.write(prices="2026-09-04", rotation="2026-09-04")
        after_labor_day = datetime(2026, 9, 8, 23, 30, tzinfo=timezone.utc)
        rows = self.status(after_labor_day)
        self.assertEqual(rows["prices"]["expected"], "2026-09-08")
        self.assertEqual(rows["prices"]["status"], "fresh")

    def test_saturday_to_tuesday_sec_gap_is_normal(self):
        tuesday_morning = datetime(2026, 9, 15, 3, 59, tzinfo=timezone.utc)
        self.assertEqual(self.status(tuesday_morning)["sec_watcher"]["status"], "fresh")

    def test_sec_heartbeat_older_than_four_days_is_stale(self):
        # The real outage: last success 2026-09-12, checked on 2026-09-27.
        late = datetime(2026, 9, 27, 3, 58, tzinfo=timezone.utc)
        row = self.status(late)["sec_watcher"]
        self.assertEqual(row["status"], "stale")
        self.assertIn("14 天", row["detail"])

    def test_missing_or_corrupt_sources_are_reported(self):
        (self.root / "prices.json").unlink()
        (self.root / ".github/sec-filing-state.json").write_text("{broken")
        rows = self.status()
        self.assertEqual(rows["prices"]["status"], "missing")
        self.assertEqual(rows["sec_watcher"]["status"], "missing")

    def test_cli_reports_through_github_output_without_failing(self):
        import subprocess
        import sys
        self.write(prices="2026-09-01")
        output = self.root / "out.txt"
        report = self.root / "report.md"
        result = subprocess.run([
            sys.executable, str(ROOT / "scripts/check_data_freshness.py"), "--root", str(self.root),
            "--now", NOW.isoformat(), "--github-output", str(output), "--markdown", str(report),
        ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("stale=true", output.read_text())
        self.assertIn("stale_keys=prices", output.read_text())
        self.assertIn("每日股價", report.read_text())

    def test_naive_time_is_rejected(self):
        with self.assertRaises(ValueError):
            MODULE.evaluate(self.root, datetime(2026, 9, 15, 5, 37))


if __name__ == "__main__":
    unittest.main()
