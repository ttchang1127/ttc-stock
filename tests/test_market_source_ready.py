import importlib.util
import pathlib
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

import pandas as pd


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "check_market_source_ready", SCRIPTS / "check_market_source_ready.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MarketSourceReadinessTests(unittest.TestCase):
    def test_extracts_single_symbol_adjusted_close_from_multiindex(self):
        dates = pd.to_datetime(["2026-09-11", "2026-09-14"])
        columns = pd.MultiIndex.from_tuples([
            ("Adj Close", "SPY"),
            ("Close", "SPY"),
        ])
        frame = pd.DataFrame([[700.0, 701.0], [710.0, 711.0]], index=dates, columns=columns)
        values = MODULE.adjusted_close(frame, "SPY")
        self.assertEqual(values.index[-1].date(), date(2026, 9, 14))
        self.assertEqual(values.iloc[-1], 710.0)

    def test_fetch_latest_session_uses_last_non_null_adjusted_close(self):
        dates = pd.to_datetime(["2026-09-11", "2026-09-14"])
        columns = pd.MultiIndex.from_tuples([("Adj Close", "SPY")])
        frame = pd.DataFrame([[700.0], [float("nan")]], index=dates, columns=columns)
        with mock.patch.object(MODULE.yf, "download", return_value=frame):
            latest = MODULE.fetch_latest_session("SPY", date(2026, 9, 14))
        self.assertEqual(latest, date(2026, 9, 11))

    def test_github_output_records_last_probe_state(self):
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory) / "github-output"
            MODULE.append_github_output(output, {
                "expected_session": "2026-09-14",
                "latest_session": "2026-09-11",
                "fresh": "false",
            })
            self.assertEqual(
                output.read_text().splitlines(),
                [
                    "expected_session=2026-09-14",
                    "latest_session=2026-09-11",
                    "fresh=false",
                ],
            )


if __name__ == "__main__":
    unittest.main()
