"""Check that published data is as fresh as its schedule promises.

Most derived files are only rewritten when their content changes, so their
timestamps say nothing about pipeline health.  This monitor therefore looks
only at signals that must advance on every successful run:

* the latest SPY session in prices.json, market_rotation.json ``as_of``, and
  tech_stock_map.json ``as_of``,
  measured in NYSE sessions behind the session that should be available;
* the SEC watcher heartbeat in .github/sec-filing-state.json, which is
  written on every successful run, including days without new filings.

Standard library only.  It never fails the workflow for stale data: it
reports through --github-output / --markdown so a separate step can open or
close one tracking issue.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from market_calendar import expected_latest_market_session, market_session_lag  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# One session of slack covers Yahoo publishing late and the evening catch-up
# run; two sessions behind means both daily attempts missed.
MAX_MARKET_SESSIONS_BEHIND = 1
# SEC alerts run Tuesday-Saturday; Saturday to Tuesday is the longest normal gap.
MAX_SEC_HEARTBEAT_AGE = timedelta(days=4)


def load(root: Path, name: str):
    path = root / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def market_result(key: str, label: str, latest: date | None, now: datetime, source: str) -> dict:
    expected = expected_latest_market_session(now)
    if latest is None:
        return {"key": key, "label": label, "status": "missing", "latest": None,
                "expected": expected.isoformat(), "detail": f"無法讀取 {source}"}
    lag = market_session_lag(latest, expected)
    status = "stale" if lag > MAX_MARKET_SESSIONS_BEHIND else "fresh"
    return {"key": key, "label": label, "status": status, "latest": latest.isoformat(),
            "expected": expected.isoformat(), "detail": f"落後 {lag} 個 NYSE 交易日（{source}）"}


def prices_latest(root: Path) -> date | None:
    data = load(root, "prices.json")
    try:
        return date.fromisoformat(data["series"]["SPY"]["dates"][-1])
    except (TypeError, KeyError, IndexError, ValueError):
        return None


def rotation_latest(root: Path) -> date | None:
    data = load(root, "market_rotation.json")
    try:
        return date.fromisoformat(data["as_of"])
    except (TypeError, KeyError, ValueError):
        return None


def tech_map_latest(root: Path) -> date | None:
    data = load(root, "tech_stock_map.json")
    try:
        return date.fromisoformat(data["as_of"])
    except (TypeError, KeyError, ValueError):
        return None


def sec_result(root: Path, now: datetime) -> dict:
    source = ".github/sec-filing-state.json updated_at"
    data = load(root, ".github/sec-filing-state.json")
    try:
        heartbeat = datetime.fromisoformat(data["updated_at"])
    except (TypeError, KeyError, ValueError):
        return {"key": "sec_watcher", "label": "SEC 申報監看", "status": "missing",
                "latest": None, "expected": None, "detail": f"無法讀取 {source}"}
    if heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=timezone.utc)
    age = now - heartbeat
    status = "stale" if age > MAX_SEC_HEARTBEAT_AGE else "fresh"
    hours = int(age.total_seconds() // 3600)
    return {"key": "sec_watcher", "label": "SEC 申報監看", "status": status,
            "latest": heartbeat.astimezone(timezone.utc).isoformat(timespec="minutes"),
            "expected": f"{MAX_SEC_HEARTBEAT_AGE.days} 天內",
            "detail": f"最後成功檢查距今 {hours // 24} 天 {hours % 24} 小時"}


def evaluate(root: Path, now: datetime) -> list[dict]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return [
        market_result("prices", "每日股價（prices.json）", prices_latest(root), now,
                      "prices.json 的 SPY 最新交易日"),
        market_result("market_rotation", "市場板塊輪動（market_rotation.json）", rotation_latest(root), now,
                      "market_rotation.json 的 as_of"),
        market_result("tech_stock_map", "科技股產業鏈地圖（tech_stock_map.json）", tech_map_latest(root), now,
                      "tech_stock_map.json 的 as_of"),
        sec_result(root, now),
    ]


def render_markdown(results: list[dict], now: datetime) -> str:
    icon = {"fresh": "✅", "stale": "🟠", "missing": "🔴"}
    lines = [
        f"資料新鮮度檢查時間：{now.astimezone(timezone.utc).isoformat(timespec='minutes')}",
        "",
        "| 資料 | 狀態 | 最新 | 應有 | 說明 |",
        "|---|---|---|---|---|",
    ]
    for row in results:
        lines.append(f"| {row['label']} | {icon[row['status']]} {row['status']} | {row['latest'] or '—'} "
                     f"| {row['expected'] or '—'} | {row['detail']} |")
    lines += [
        "",
        "此檢查只看每次成功執行都必須前進的訊號；過期代表對應排程連續沒有成功更新。",
        "請到 Actions 查看該排程最近的執行紀錄，不要手動修改資料檔。",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--now", type=datetime.fromisoformat, help="Timezone-aware ISO time for replay/tests.")
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    now = args.now or datetime.now(timezone.utc)
    results = evaluate(args.root, now)
    problems = [row for row in results if row["status"] != "fresh"]
    report = render_markdown(results, now)
    print(report)
    if args.markdown:
        args.markdown.write_text(report)
    if args.github_output:
        with args.github_output.open("a") as handle:
            handle.write(f"stale={'true' if problems else 'false'}\n")
            handle.write(f"stale_keys={','.join(row['key'] for row in problems)}\n")


if __name__ == "__main__":
    main()
