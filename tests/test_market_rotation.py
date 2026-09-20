import importlib.util
import json
import pathlib
import tempfile
import unittest
from datetime import date, datetime, timezone

import pandas as pd


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_market_rotation", ROOT / "scripts/build_market_rotation.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def synthetic_universe():
    members = []
    for sector, prefix in (("Information Technology", "TEC"), ("Financials", "FIN")):
        for number in range(6):
            members.append({
                "ticker": f"{prefix}{number}",
                "yahoo_ticker": f"{prefix}{number}",
                "name": f"{sector} {number}",
                "sector": sector,
                "industry": f"{sector} Group {number // 3}",
                "indexes": ["S&P 500"],
                "classification": "GICS",
            })
    return {
        "schema_version": 1,
        "generated_at": "2026-01-01T00:00:00+00:00",
        "counts": {"sp500_securities": 12, "nasdaq100_securities": 0, "combined_securities": 12},
        "members": members,
    }


class MarketRotationBuilderTests(unittest.TestCase):
    def setUp(self):
        self.universe = synthetic_universe()
        dates = pd.bdate_range("2025-01-02", periods=110)
        closes = {}
        volumes = {}
        for row in self.universe["members"]:
            ticker = row["ticker"]
            daily_growth = 1.003 if ticker.startswith("TEC") else 0.999
            closes[ticker] = [100 * daily_growth ** index for index in range(len(dates))]
            base_volume = 1_000_000
            volumes[ticker] = [base_volume * (1.8 if ticker.startswith("TEC") and index >= 105 else 1)
                               for index in range(len(dates))]
        self.closes = pd.DataFrame(closes, index=dates)
        self.volumes = pd.DataFrame(volumes, index=dates)

    def test_build_payload_detects_broad_relative_leadership(self):
        payload = MODULE.build_payload(self.universe, self.closes, self.volumes)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["coverage"]["coverage_pct"], 100.0)
        self.assertEqual(len(payload["sectors"]), 2)
        self.assertEqual(len(payload["industries"]), 4)
        tech = next(row for row in payload["sectors"] if row["key"] == "Information Technology")
        finance = next(row for row in payload["sectors"] if row["key"] == "Financials")
        self.assertGreater(tech["relative_strength_20d"], 0)
        self.assertLess(finance["relative_strength_20d"], 0)
        self.assertGreater(tech["rotation_score"], finance["rotation_score"])
        self.assertEqual(len(tech["trajectory"]), 10)
        self.assertEqual(len(tech["leaders"]), 5)
        self.assertIn(tech["quadrant"], {"leading", "weakening"})

    def test_refuses_materially_partial_market_data(self):
        with self.assertRaisesRegex(ValueError, "refusing to publish partial"):
            MODULE.build_payload(self.universe, self.closes.iloc[:, :10], self.volumes.iloc[:, :10])

    def test_write_if_changed_ignores_only_generation_timestamp(self):
        payload = {"schema_version": 1, "generated_at": "first", "value": 7}
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "output.json"
            self.assertTrue(MODULE.write_if_changed(path, payload))
            updated = dict(payload, generated_at="second")
            self.assertFalse(MODULE.write_if_changed(path, updated))
            self.assertEqual(json.loads(path.read_text())["generated_at"], "first")

    def test_expected_session_detects_missing_monday_after_market_close(self):
        run_time = datetime(2026, 9, 15, 1, 11, tzinfo=timezone.utc)
        self.assertEqual(
            MODULE.expected_latest_market_session(run_time),
            date(2026, 9, 14),
        )
        with self.assertRaisesRegex(ValueError, "1 market session behind"):
            MODULE.require_fresh_market_data(date(2026, 9, 11), date(2026, 9, 14))

    def test_expected_session_respects_exchange_holidays_and_source_grace(self):
        before_cutoff = datetime(2026, 9, 8, 19, 0, tzinfo=timezone.utc)
        self.assertEqual(
            MODULE.expected_latest_market_session(before_cutoff),
            date(2026, 9, 4),
        )
        self.assertFalse(MODULE.is_market_session(date(2026, 9, 7)))
        self.assertFalse(MODULE.is_market_session(date(2026, 4, 3)))
        self.assertTrue(MODULE.is_market_session(date(2026, 9, 14)))

    def test_current_or_newer_market_session_passes_freshness_gate(self):
        MODULE.require_fresh_market_data(date(2026, 9, 14), date(2026, 9, 14))
        MODULE.require_fresh_market_data(date(2026, 9, 15), date(2026, 9, 14))

    def test_latest_session_requires_ninety_percent_cross_sectional_coverage(self):
        expected = self.closes.index[-1].date()
        one_missing = self.closes.copy()
        one_missing.iloc[-1, 0] = float("nan")
        MODULE.require_latest_session_coverage(one_missing, expected, 12)

        two_missing = one_missing.copy()
        two_missing.iloc[-1, 1] = float("nan")
        with self.assertRaisesRegex(ValueError, "10/12 securities"):
            MODULE.require_latest_session_coverage(two_missing, expected, 12)


class MarketRotationPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / "market_rotation.html").read_text()
        cls.dashboard = (ROOT / "dashboard.html").read_text()
        cls.workflow = (ROOT / ".github/workflows/update-prices.yml").read_text()

    def test_standalone_page_explains_proxy_and_periods(self):
        for marker in (
            "市場板塊族群輪動雷達", "market_rotation.json", "四象限輪動路徑",
            "20 日相對強弱", "5 日相對動能加速度", "最近 10 個交易日",
            "不是申購贖回或資金淨流入", "板塊內部領漲與落後個股",
            "S&amp;P 500 ＋ Nasdaq-100", "返回投資儀表板", "勾選顯示",
            "chartSelections", "data-chart-preset=\"top3\"", "全部清除",
            "trajectoryDirection", "箭頭尖端是最新交易日", "圖表分析期限",
            "路徑＝最近 10 個交易日", "60 日指標只參與下方綜合輪動分數",
            "renderTrajectoryPeriod", "sample[0].date", "Math.atan2(dy, dx)",
            "四個象限代表什麼？", "右上｜相對強、動能加速",
            "左上｜仍落後、動能回升", "右下｜仍領先、動能降溫",
            "左下｜相對弱、動能惡化", "改善 → 領先 → 轉弱 → 落後",
            "象限只描述價格相對位置與方向",
            "market_rotation_universe.json", "renderIndustryMembers",
            "次產業實際納入股票", "點選查看納入的",
            "不是整個市場所有同業",
        ):
            self.assertIn(marker, self.page)

    def test_dashboard_links_to_standalone_page(self):
        self.assertIn('href="market_rotation.html"', self.dashboard)
        self.assertIn("🧭 市場族群輪動", self.dashboard)

    def test_daily_workflow_builds_and_allows_rotation_outputs(self):
        self.assertIn("python3 scripts/build_market_rotation.py", self.workflow)
        self.assertIn("python3 scripts/check_market_source_ready.py", self.workflow)
        self.assertIn("steps.market_source.outputs.fresh == 'true'", self.workflow)
        self.assertIn("17 12 * * 2-6", self.workflow)
        self.assertIn('if [ "$status" -eq 75 ]', self.workflow)
        self.assertIn('if [ "$status" -ne 75 ]', self.workflow)
        self.assertIn("steps.rotation_build.outputs.fresh == 'false'", self.workflow)
        self.assertIn("preserving the prior rotation file", self.workflow)
        self.assertIn("'lxml>=5,<7'", self.workflow)
        self.assertIn("market_rotation_universe", self.workflow)
        self.assertIn("market_rotation|", self.workflow)


if __name__ == "__main__":
    unittest.main()
