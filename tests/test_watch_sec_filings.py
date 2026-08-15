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
    def test_filters_unwatched_forms(self):
        rows = watcher.extract_filings("TEST", "0000000001", payload(["10-Q", "UPLOAD"]))
        self.assertEqual([row["form"] for row in rows], ["10-Q"])

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


if __name__ == "__main__":
    unittest.main()
