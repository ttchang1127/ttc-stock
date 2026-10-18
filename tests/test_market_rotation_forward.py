import copy
import json
from pathlib import Path
import sys
import unittest

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import market_rotation_forward as forward  # noqa: E402


class ForwardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.protocol = json.loads((ROOT / "market_rotation_forward_protocol.json").read_text())
        cls.index, history_rows = forward.read_snapshots(ROOT / "market_rotation_history")
        # These cases exercise the frozen baseline and a synthetic next session.
        # Later real snapshots must not change their expected event counts.
        cls.rows = [row for row in history_rows if row["as_of"] <= cls.protocol["baseline_as_of"]]

    def test_preprotocol_snapshots_are_not_events(self):
        result = forward.build(self.protocol, self.index, self.rows, {}, "2026-10-11T12:00:00Z")
        self.assertEqual((result["event_count"], result["matured_20d"], result["matured_60d"]), (0, 0, 0))

    def test_transition_freezes_first_seen_and_only_confirmed_state(self):
        rows = copy.deepcopy(self.rows)
        sector = "sector:utilities"
        next_row = copy.deepcopy(rows[-1])
        next_row["as_of"] = "2026-10-12"
        next_row["dataset_id"] = "sha256:test-next-session"
        next_row["groups"][sector]["raw_state"] = "cooling"
        rows.append(next_row)
        first = forward.build(self.protocol, self.index, rows, {}, "2026-10-13T11:00:00Z")
        self.assertEqual(first["event_count"], 0)
        rows[-1]["groups"][sector]["confirmed_state"] = "cooling"
        first = forward.build(self.protocol, self.index, rows, {}, "2026-10-13T11:00:00Z")
        self.assertEqual(first["event_count"], 1)
        first_seen = first["events"][0]["first_seen_at_utc"]
        second = forward.build(self.protocol, self.index, rows, first, "2026-10-14T11:00:00Z")
        self.assertEqual(second["events"][0]["first_seen_at_utc"], first_seen)
        self.assertEqual(second["events"][0]["eligibility_confirmed_at_utc"], "2026-10-14T11:00:00Z")

    def test_entry_waits_for_first_seen_and_missing_does_not_slide(self):
        event = {"signal_as_of": "2026-10-12", "first_seen_at_utc": "2026-10-13T23:00:00Z",
                 "eligibility_confirmed_at_utc": "2026-10-13T23:00:00Z",
                 "etf": "XLU", "entry": {"status": "pending"},
                 "outcomes": {"20d": {"status": "pending"}, "60d": {"status": "pending"}}}
        dates = pd.bdate_range("2026-10-12", periods=25)
        prices = pd.DataFrame({"SPY": [100.0] * 25, "XLU": [100.0] * 25}, index=dates)
        prices.loc["2026-10-14", "XLU"] = float("nan")
        forward.price_outcomes(event, prices)
        self.assertEqual(event["entry"]["date"], "2026-10-14")
        self.assertEqual(event["entry"]["status"], "missing")
        self.assertEqual(event["outcomes"]["20d"]["status"], "pending")

    def test_exact_horizon_and_max_adverse_excess(self):
        event = {"signal_as_of": "2026-10-12", "first_seen_at_utc": "2026-10-13T23:00:00Z",
                 "eligibility_confirmed_at_utc": "2026-10-13T23:00:00Z",
                 "etf": "XLU", "entry": {"status": "pending"},
                 "outcomes": {"20d": {"status": "pending"}, "60d": {"status": "pending"}}}
        dates = pd.bdate_range("2026-10-12", periods=23)
        prices = pd.DataFrame({"SPY": [100.0] * 23, "XLU": [100.0] * 23}, index=dates)
        prices.loc["2026-10-19", "XLU"] = 95.0
        prices.loc[dates[-1], "XLU"] = 105.0
        forward.price_outcomes(event, prices)
        self.assertEqual(event["entry"]["date"], "2026-10-14")
        self.assertEqual(event["outcomes"]["20d"]["status"], "mature")
        self.assertEqual(event["outcomes"]["20d"]["excess_pp"], 5.0)
        self.assertEqual(event["outcomes"]["20d"]["max_adverse_excess_pp"], -5.0)
        self.assertEqual(event["outcomes"]["60d"]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
