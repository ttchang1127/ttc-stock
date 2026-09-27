import hashlib
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone

import pandas as pd


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))
import market_rotation_fixture as fixture  # noqa: E402
import market_calendar  # noqa: E402

SPEC = importlib.util.spec_from_file_location(
    "build_market_rotation", ROOT / "scripts/build_market_rotation.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

# Locked specification values: changing either is a formula change that needs
# a golden update and an explanation in the commit message.
SPEC_WEIGHTS = {
    "relative_strength_20d": 20, "relative_strength_60d": 15, "acceleration_5d": 15,
    "breadth": 25, "dollar_volume_expansion": 15, "persistence": 10,
}
FIXTURE_QUADRANTS = {
    "Information Technology": "leading", "Industrials": "improving",
    "Health Care": "weakening", "Energy": "lagging",
}


def percentile_ranks(values: dict) -> dict:
    """Average-rank percentile, written independently of pandas.rank."""
    ordered = sorted(values.values())
    result = {}
    for key, value in values.items():
        below = sum(1 for item in ordered if item < value)
        equal = sum(1 for item in ordered if item == value)
        result[key] = (below + (equal + 1) / 2) / len(ordered) * 100
    return result


class MarketRotationFixtureTests(unittest.TestCase):
    """Current-behaviour locks on the deterministic ``quadrants`` fixture."""

    @classmethod
    def setUpClass(cls):
        cls.universe, cls.closes, cls.volumes = fixture.load_fixture()
        cls.payload = MODULE.build_payload(cls.universe, cls.closes, cls.volumes)
        cls.sectors = {row["key"]: row for row in cls.payload["sectors"]}
        cls.sector_of = {row["ticker"]: row["sector"] for row in cls.universe["members"]}

    def sector_tickers(self, sector):
        return [ticker for ticker, value in self.sector_of.items() if value == sector]

    def test_golden_v1_output_is_unchanged(self):
        """MR-CALC golden: only generated_at may differ from expected_v1.json."""
        expected = json.loads(fixture.GOLDEN_V1.read_text())
        changed = fixture.differences(fixture.stable(expected), fixture.stable(self.payload))
        self.assertEqual(changed, [], "Golden v1 drift (run tests/market_rotation_fixture.py "
                         "to review):\n" + "\n".join(changed))

    def test_repeated_builds_are_byte_identical(self):
        first = fixture.canonical_json(fixture.build_fixture_v1())
        second = fixture.canonical_json(fixture.build_fixture_v1())
        self.assertEqual(hashlib.sha256(first.encode()).hexdigest(),
                         hashlib.sha256(second.encode()).hexdigest())
        self.assertEqual(first, fixture.GOLDEN_V1.read_text())

    def test_mr_calc_001_quadrant_signs_and_labels(self):
        benchmark_r20 = (self.closes.iloc[-1] / self.closes.iloc[-21] - 1).mean()
        for name, expected_quadrant in FIXTURE_QUADRANTS.items():
            row = self.sectors[name]
            tickers = self.sector_tickers(name)
            r20 = (self.closes[tickers].iloc[-1] / self.closes[tickers].iloc[-21] - 1).mean()
            self.assertAlmostEqual(row["relative_strength_20d"],
                                   round((r20 - benchmark_r20) * 100, 2), places=2, msg=name)
            x, y = row["relative_strength_20d"], row["acceleration_5d"]
            expected_signs = {
                "leading": (True, True), "improving": (False, True),
                "weakening": (True, False), "lagging": (False, False),
            }[expected_quadrant]
            self.assertEqual((x >= 0, y >= 0), expected_signs, f"MR-CALC-001 {name} x={x} y={y}")
            self.assertEqual(row["quadrant"], expected_quadrant, f"MR-CALC-001 {name}")

    def test_mr_calc_002_weighted_percentile_score_and_order(self):
        for collection in ("sectors", "industries"):
            rows = self.payload[collection]
            for metric, weight in SPEC_WEIGHTS.items():
                expected = percentile_ranks({row["key"]: row[metric] for row in rows})
                for row in rows:
                    self.assertEqual(row[f"rank_{metric}"], round(expected[row["key"]], 1),
                                     f"MR-CALC-002 {collection}/{row['key']}/{metric}")
            for row in rows:
                score = sum(percentile_ranks({r["key"]: r[m] for r in rows})[row["key"]] * w / 100
                            for m, w in SPEC_WEIGHTS.items())
                self.assertEqual(row["rotation_score"], round(score, 1),
                                 f"MR-CALC-002 {collection}/{row['key']}")
            scores = [row["rotation_score"] for row in rows]
            self.assertEqual(scores, sorted(scores, reverse=True), f"MR-CALC-002 {collection} order")

    def test_mr_calc_003_breadth(self):
        for name in FIXTURE_QUADRANTS:
            tickers = self.sector_tickers(name)
            window = self.closes[tickers]
            positive = ((window.iloc[-1] / window.iloc[-21] - 1) > 0).mean()
            above = (window.iloc[-1] > window.iloc[-20:].mean()).mean()
            row = self.sectors[name]
            self.assertEqual(row["breadth_positive_20d"], round(positive * 100, 2), name)
            self.assertEqual(row["breadth_above_ma20"], round(above * 100, 2), name)
            self.assertEqual(row["breadth"], round((positive + above) / 2 * 100, 2), name)

    def test_mr_calc_004_dollar_volume_expansion(self):
        for name in FIXTURE_QUADRANTS:
            tickers = self.sector_tickers(name)
            daily = (self.closes[tickers] * self.volumes[tickers]).sum(axis=1)
            expected = daily.iloc[-5:].mean() / daily.iloc[-25:-5].mean() - 1
            self.assertEqual(self.sectors[name]["dollar_volume_expansion"],
                             round(expected * 100, 2), f"MR-CALC-004 {name}")
        self.assertGreater(self.sectors["Information Technology"]["dollar_volume_expansion"], 0)
        self.assertLess(self.sectors["Energy"]["dollar_volume_expansion"], 0)

    def test_mr_calc_005_persistence(self):
        returns = self.closes.pct_change()
        universe_daily = returns.mean(axis=1).iloc[-10:]
        for name in FIXTURE_QUADRANTS:
            group_daily = returns[self.sector_tickers(name)].mean(axis=1).iloc[-10:]
            share = sum(1 for g, u in zip(group_daily, universe_daily) if g > u) / 10
            self.assertEqual(self.sectors[name]["persistence"], round(share * 100, 2), name)

    def test_mr_calc_006_trajectory_is_latest_ten_sessions_oldest_first(self):
        expected_dates = [value.strftime("%Y-%m-%d") for value in self.closes.index[-10:]]
        for collection in ("sectors", "industries"):
            for row in self.payload[collection]:
                trail = row["trajectory"]
                self.assertEqual([point["date"] for point in trail], expected_dates,
                                 f"MR-CALC-006 {row['key']}")
                self.assertEqual((trail[-1]["x"], trail[-1]["y"], trail[-1]["score"]),
                                 (row["relative_strength_20d"], row["acceleration_5d"],
                                  row["rotation_score"]), f"MR-CALC-006 {row['key']} latest point")

    def test_mr_calc_007_score_change_is_five_sessions(self):
        for collection in ("sectors", "industries"):
            for row in self.payload[collection]:
                five_back = row["trajectory"][-6]["score"]
                self.assertEqual(row["score_change_5d"],
                                 round(row["rotation_score"] - five_back, 1),
                                 f"MR-CALC-007 {row['key']}")

    def test_mr_calc_008_sector_leaders_and_laggards(self):
        r20 = self.closes.iloc[-1] / self.closes.iloc[-21] - 1
        benchmark = r20.mean()
        for name in FIXTURE_QUADRANTS:
            ranked = sorted(self.sector_tickers(name), key=lambda t: r20[t], reverse=True)
            row = self.sectors[name]
            self.assertEqual([item["ticker"] for item in row["leaders"]], ranked[:5], name)
            self.assertEqual([item["ticker"] for item in row["laggards"]], ranked[::-1][:5], name)
            for item in row["leaders"]:
                self.assertAlmostEqual(item["relative_strength_20d"],
                                       round((r20[item["ticker"]] - benchmark) * 100, 2),
                                       places=2, msg=f"MR-CALC-008 {item['ticker']}")


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
        self.assertFalse(market_calendar.is_market_session(date(2026, 9, 7)))
        self.assertFalse(market_calendar.is_market_session(date(2026, 4, 3)))
        self.assertTrue(market_calendar.is_market_session(date(2026, 9, 14)))

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
        cls.html = (ROOT / "market_rotation.html").read_text()
        cls.page = cls.html + (ROOT / "assets/market_rotation_legacy.js").read_text()
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
            "market_rotation_universe.json", "industryMembersHtml",
            "實際納入股票", "點選查看納入的",
            "不是整個市場所有同業", "industry-members-row", "scrollIntoView",
        ):
            self.assertIn(marker, self.page)

    def test_static_assets_use_relative_pages_paths(self):
        """G6: assets load from /ttc-stock/ on Pages and from a local HTTP server."""
        import re
        refs = re.findall(r'(?:href|src)="(assets/[^"]+)"', self.html)
        self.assertIn("assets/market_rotation.css", refs)
        self.assertIn('<script src="assets/market_rotation_legacy.js" defer></script>', self.html)
        for ref in refs:
            self.assertTrue((ROOT / ref).is_file(), f"missing static asset {ref}")
        for forbidden in ('href="/assets', 'src="/assets', "file://", "/Volumes/"):
            self.assertNotIn(forbidden, self.page)
        self.assertNotIn("<style", self.html, "styles live in assets/market_rotation.css")
        self.assertNotIn("<script>", self.html, "legacy code lives in assets/market_rotation_legacy.js")

    def test_chart_dependency_is_pinned_and_optional(self):
        self.assertIn("https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.min.js", self.html)
        self.assertNotIn('src="https://cdn.jsdelivr.net/npm/chart.js"', self.html, "unpinned CDN version")
        self.assertIn("typeof Chart === 'undefined'", self.page)
        self.assertIn("圖表元件載入失敗", self.page)

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
        self.assertIn("pip install --quiet -r requirements.txt", self.workflow)
        self.assertIn("lxml>=5,<7", (ROOT / "requirements.txt").read_text())
        import data_manifest
        manifest = data_manifest.load_manifest()
        for name in ("market_rotation", "market_rotation_universe", "market_rotation_summary",
                     "market_rotation_groups", "market_rotation_stocks", "market_rotation_registry"):
            self.assertTrue(data_manifest.may_commit(f"{name}.json", "update-prices", manifest),
                            f"daily commit allowlist must accept {name}.json")


class MainDualWriteTests(unittest.TestCase):
    def test_main_writes_v1_v2_and_registry_offline(self):
        universe, closes, volumes = fixture.load_fixture()
        as_of = closes.index[-1].date().isoformat()
        with tempfile.TemporaryDirectory() as directory:
            folder = pathlib.Path(directory)
            (folder / "universe.json").write_text(json.dumps(universe))
            argv = ["build_market_rotation.py", "--skip-universe-refresh",
                    "--universe", str(folder / "universe.json"),
                    "--output", str(folder / "market_rotation.json"),
                    "--registry", str(folder / "market_rotation_registry.json"),
                    "--expected-session", as_of]
            original_fetch, original_argv = MODULE.fetch_market_data, sys.argv
            MODULE.fetch_market_data = lambda *args, **kwargs: (closes.copy(), volumes.copy())
            sys.argv = argv
            try:
                MODULE.main()
            finally:
                MODULE.fetch_market_data, sys.argv = original_fetch, original_argv
            names = ["market_rotation.json", "market_rotation_registry.json"] + [
                f"market_rotation_{name}.json" for name in ("summary", "groups", "stocks")]
            self.assertEqual(sorted(path.name for path in folder.glob("market_rotation*.json")), sorted(names))
            v1 = json.loads((folder / "market_rotation.json").read_text())
            summary = json.loads((folder / "market_rotation_summary.json").read_text())
            self.assertEqual(fixture.differences(
                fixture.stable(json.loads(fixture.GOLDEN_V1.read_text())), fixture.stable(v1)), [])
            self.assertEqual(summary["as_of"], as_of)
            self.assertEqual(summary["generated_at"], v1["generated_at"])


class PagesDeployGateTests(unittest.TestCase):
    def test_mr_dep_001_pages_artifact_waits_for_quality_gate(self):
        workflow = (ROOT / ".github/workflows/deploy-pages.yml").read_text()
        quality = workflow[workflow.index("  quality:"):workflow.index("  deploy:")]
        deploy = workflow[workflow.index("  deploy:"):]
        self.assertIn("python3 -m unittest discover -s tests -p 'test_market_rotation*.py'", quality)
        self.assertIn("python3 scripts/check_integrity.py --quiet", quality)
        self.assertLess(quality.index("unittest discover"), quality.index("check_integrity.py"))
        self.assertIn("needs: quality", deploy)
        self.assertIn("ref: ${{ needs.quality.outputs.sha }}", deploy)
        self.assertNotIn("upload-pages-artifact", quality)
        self.assertIn("upload-pages-artifact", deploy)
        self.assertNotIn("build_market_rotation.py", workflow, "Pages must not refetch market data")
        self.assertNotIn("continue-on-error", workflow)


if __name__ == "__main__":
    unittest.main()
