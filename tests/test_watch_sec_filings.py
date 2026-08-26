import importlib.util
import pathlib
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "watch_sec_filings.py"
SPEC = importlib.util.spec_from_file_location("watch_sec_filings", SCRIPT)
watcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watcher)


def payload(forms, items=None):
    count = len(forms)
    return {
        "filings": {"recent": {
            "form": forms,
            "filingDate": ["2026-08-15"] * count,
            "accessionNumber": [f"0000000001-26-{i:06d}" for i in range(count)],
            "primaryDocument": [f"doc{i}.htm" for i in range(count)],
            "items": items or [""] * count,
            "acceptanceDateTime": ["20260815120000"] * count,
            "reportDate": ["2026-06-30"] * count,
        }}
    }


class FilingWatcherTests(unittest.TestCase):
    def test_includes_accounting_review_forms(self):
        rows = watcher.extract_filings("TEST", "0000000001", payload(["10-Q", "UPLOAD"]))
        self.assertEqual([row["form"] for row in rows], ["10-Q", "UPLOAD"])
        self.assertEqual(rows[1]["group"], "會計審閱")
        self.assertEqual(rows[1]["severity"], "high")

    def test_schema_migration_baselines_new_form_without_alert(self):
        rows = watcher.extract_filings("TEST", "0000000001", payload(["10-Q", "UPLOAD"]))
        state = {"schema_version": 1, "companies": {"TEST": {"seen_accessions": []}}}
        new = watcher.update_state(
            {"TEST": "0000000001"}, {"TEST": rows}, state, suppress_new_forms=True
        )
        self.assertEqual([event["form"] for event in new], ["10-Q"])
        self.assertEqual(len(state["companies"]["TEST"]["seen_accessions"]), 2)

    def test_critical_8k_item(self):
        row = watcher.extract_filings(
            "TEST", "0000000001", payload(["8-K"], ["4.02,9.01"]))[0]
        self.assertEqual(row["severity"], "critical")
        self.assertIn("財報不得再依賴", row["items_summary"])

    def test_form4_is_medium(self):
        row = watcher.extract_filings("TEST", "0000000001", payload(["4"]))[0]
        self.assertEqual(row["group"], "內部人持股")
        self.assertEqual(row["severity"], "medium")

    def test_alert_contains_accessible_sec_link(self):
        row = watcher.extract_filings("TEST", "0000000001", payload(["10-K"]))[0]
        alert = watcher.render_alert([row], [], "2026-08-15T00:00:00+00:00")
        self.assertIn("SEC 新申報通知", alert)
        self.assertIn("https://www.sec.gov/Archives/edgar/data/1/", alert)

    def test_only_unseen_accession_triggers(self):
        rows = watcher.extract_filings("TEST", "0000000001", payload(["10-Q", "8-K"]))
        state = {"companies": {"TEST": {"seen_accessions": [rows[0]["accession"]]}}}
        new = watcher.update_state({"TEST": "0000000001"}, {"TEST": rows}, state)
        self.assertEqual([event["accession"] for event in new], [rows[1]["accession"]])
        self.assertEqual(len(state["companies"]["TEST"]["seen_accessions"]), 2)

    def test_update_batch_records_priority_financial_and_external_deltas(self):
        prior = watcher.extract_filings("TEST", "0000000001", payload(["4"]))[0]
        latest = watcher.extract_filings("TEST", "0000000001", payload(["10-Q"]))[0]
        ownership = {
            "ticker": "TEST", "accession": "owner-1", "filing_date": "2026-08-15",
            "importance": "high",
        }
        batch = watcher.build_update_batch(
            [latest], [prior], "2026-08-16T04:00:00+00:00",
            previous_checked_at="2026-08-15T04:00:00+00:00",
            prior_advanced={"ownership_timeline": [], "enforcement": []},
            current_advanced={"ownership_timeline": [ownership], "enforcement": []},
        )
        self.assertEqual(batch["new_count"], 1)
        self.assertEqual(batch["financial_accessions"], [latest["accession"]])
        self.assertEqual(batch["ownership_accessions"], ["owner-1"])
        self.assertEqual(batch["company_changes"][0]["before_priority"], "updated")
        self.assertEqual(batch["company_changes"][0]["after_priority"], "urgent")
        self.assertTrue(batch["company_changes"][0]["priority_changed"])

    def test_zero_change_batch_is_still_explicit(self):
        batch = watcher.build_update_batch(
            [], [], "2026-08-16T04:00:00+00:00",
            previous_checked_at="2026-08-15T04:00:00+00:00",
            prior_advanced={}, current_advanced={},
        )
        self.assertEqual(batch["new_count"], 0)
        self.assertEqual(batch["company_changes"], [])
        self.assertEqual(batch["previous_checked_at"], "2026-08-15T04:00:00+00:00")

    def test_initial_batch_does_not_alert_on_existing_external_history(self):
        ownership = {
            "ticker": "TEST", "accession": "owner-1", "filing_date": "2026-08-15",
            "importance": "high",
        }
        batch = watcher.build_update_batch(
            [], [], "2026-08-16T04:00:00+00:00", initializing=True,
            prior_advanced={}, current_advanced={"ownership_timeline": [ownership]},
        )
        self.assertTrue(batch["baseline"])
        self.assertEqual(batch["ownership_accessions"], [])
        self.assertEqual(batch["company_changes"], [])


if __name__ == "__main__":
    unittest.main()
