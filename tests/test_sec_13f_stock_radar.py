import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sec_13f_stock_radar.py"
SPEC = importlib.util.spec_from_file_location("sec_13f_stock_radar", SCRIPT)
radar = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(radar)


class ThirteenFTests(unittest.TestCase):
    def test_matches_current_and_old_ondas_names(self):
        self.assertEqual(radar.ticker_for({"NAMEOFISSUER": "ONDAS INC", "TITLEOFCLASS": "COM NEW"}), "ONDS")
        self.assertEqual(radar.ticker_for({"NAMEOFISSUER": "ONDAS HLDGS INC", "TITLEOFCLASS": "COM"}), "ONDS")

    def test_period_sort_is_chronological_not_alphabetical(self):
        datasets = [{"rows": [
            {"ticker": "AAPL", "period": "31-DEC-2025", "put_call": "", "manager_cik": "1", "manager": "A", "shares": 10, "value_usd": 100},
            {"ticker": "AAPL", "period": "31-MAR-2026", "put_call": "", "manager_cik": "1", "manager": "A", "shares": 12, "value_usd": 130},
        ]}]
        result = radar.aggregate(datasets)
        self.assertEqual(result["periods"], ["31-MAR-2026", "31-DEC-2025"])
        self.assertEqual(result["stocks"]["AAPL"]["snapshots"][0]["value_usd"], 130)


if __name__ == "__main__":
    unittest.main()
