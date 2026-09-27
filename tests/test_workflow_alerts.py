"""Scheduled workflows report their own failures and recover their issues."""

import os
import pathlib
import subprocess
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
SCRIPTS = ROOT / ".github/scripts"
FAKE_GH = """#!/bin/bash
echo "$*" >> "$FAKE_GH_LOG"
case "$1 $2" in
  "issue list") echo "${FAKE_EXISTING:-}" ;;
  "run view") printf '%s\\n' "${FAKE_STEPS:-}" ;;
esac
"""


class AlertWiringTests(unittest.TestCase):
    def workflows(self):
        return {path.name: yaml.safe_load(path.read_text()) for path in sorted(WORKFLOWS.glob("*.yml"))}

    def test_every_non_pr_workflow_has_an_independent_alert_job(self):
        for name, workflow in self.workflows().items():
            if name == "tests.yml":
                self.assertNotIn("alert", workflow["jobs"], "PR checks report on the PR itself")
                continue
            jobs = workflow["jobs"]
            self.assertIn("alert", jobs, f"{name} has no failure alert job")
            alert = jobs["alert"]
            self.assertEqual(sorted(alert["needs"]), sorted(job for job in jobs if job != "alert"),
                             f"{name} alert must wait on every other job")
            self.assertEqual(alert["if"], "always()")
            self.assertEqual(alert["permissions"], {"actions": "read", "contents": "read", "issues": "write"})
            steps = alert["steps"]
            self.assertEqual(steps[0]["uses"], "actions/checkout@v4", "alert must not depend on the main job")
            self.assertIn("workflow-alert.sh", steps[-1]["run"])
            self.assertEqual(steps[-1]["env"]["RESULTS"], "${{ join(needs.*.result, ' ') }}")

    def test_freshness_watchdog_runs_daily_and_tracks_one_issue(self):
        workflow = self.workflows()["data-freshness.yml"]
        crons = [row["cron"] for row in workflow[True]["schedule"]]
        self.assertEqual(crons, ["37 5 * * *"])
        steps = workflow["jobs"]["check"]["steps"]
        runs = " ".join(step.get("run", "") for step in steps)
        self.assertIn("check_data_freshness.py", runs)
        self.assertIn('issue-alert.sh open "🟠 資料新鮮度警示"', runs)
        self.assertIn('issue-alert.sh close "🟠 資料新鮮度警示"', runs)


class AlertScriptTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        folder = pathlib.Path(self.directory.name)
        (folder / "gh").write_text(FAKE_GH)
        (folder / "gh").chmod(0o755)
        self.log = folder / "gh.log"
        self.log.touch()
        self.env = dict(os.environ, PATH=f"{folder}:{os.environ['PATH']}", FAKE_GH_LOG=str(self.log),
                        GITHUB_WORKFLOW="SEC filing alerts", GITHUB_REPOSITORY="owner/repo",
                        GITHUB_REPOSITORY_OWNER="owner", GITHUB_SERVER_URL="https://github.com",
                        GITHUB_RUN_ID="42", GITHUB_EVENT_NAME="schedule", GITHUB_SHA="abcdef1234",
                        GH_TOKEN="test")

    def tearDown(self):
        self.directory.cleanup()

    def run_alert(self, results, **env):
        result = subprocess.run(["bash", str(SCRIPTS / "workflow-alert.sh"), results],
                                env={**self.env, **env}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return [line for line in self.log.read_text().splitlines() if line]

    def test_failure_without_open_issue_creates_one_naming_the_failed_step(self):
        calls = self.run_alert("failure", FAKE_STEPS="- watch / Verify filing watcher")
        create = [call for call in calls if call.startswith("issue create")]
        self.assertEqual(len(create), 1, calls)
        self.assertIn("--title 🔴 排程失敗：SEC filing alerts", create[0])
        self.assertIn("--assignee owner", create[0])
        self.assertTrue(any("run view 42" in call for call in calls))
        self.assertNotIn("issue close", " ".join(calls))

    def test_failure_body_lists_run_link_and_failed_steps(self):
        capture = pathlib.Path(self.directory.name) / "body.md"
        gh = pathlib.Path(self.directory.name) / "gh"
        gh.write_text(FAKE_GH.replace('case "$1 $2" in',
                                      'if [ "$1 $2" = "issue create" ]; then cp "${@: -3:1}" '
                                      f'"{capture}"; fi\ncase "$1 $2" in'))
        self.run_alert("failure", FAKE_STEPS="- watch / Verify filing watcher")
        body = capture.read_text()
        self.assertIn("https://github.com/owner/repo/actions/runs/42", body)
        self.assertIn("- watch / Verify filing watcher", body)
        self.assertIn("下一次成功執行時，這個 issue 會自動關閉", body)

    def test_repeated_failure_comments_on_the_open_issue(self):
        calls = self.run_alert("failure", FAKE_EXISTING="17")
        self.assertTrue(any(call.startswith("issue comment 17") for call in calls), calls)
        self.assertFalse(any(call.startswith("issue create") for call in calls))

    def test_any_failed_job_counts_as_failure(self):
        calls = self.run_alert("success failure")
        self.assertTrue(any(call.startswith("issue create") for call in calls), calls)

    def test_success_closes_the_open_issue(self):
        calls = self.run_alert("success success", FAKE_EXISTING="17")
        close = [call for call in calls if call.startswith("issue close")]
        self.assertEqual(len(close), 1, calls)
        self.assertIn("issue close 17", close[0])
        self.assertIn("已恢復", close[0])

    def test_success_without_open_issue_does_nothing_else(self):
        calls = self.run_alert("success")
        self.assertEqual([call.split(" ")[:2] for call in calls], [["issue", "list"]])

    def test_skipped_or_cancelled_runs_change_nothing(self):
        for results in ("skipped skipped", "success cancelled", ""):
            self.log.write_text("")
            self.assertEqual(self.run_alert(results, FAKE_EXISTING="17"), [], results)

    def test_issue_alert_rejects_unknown_actions(self):
        result = subprocess.run(["bash", str(SCRIPTS / "issue-alert.sh"), "reopen", "t", "x"],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
