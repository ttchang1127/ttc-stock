"""Build the daily rotation digest and the direct-equity exposure together.

Reads the committed research layer, A-quality history, holdings and prices;
writes ``market_rotation_daily_digest.json`` and
``portfolio_equity_exposure.json`` in one atomic batch.  Run by the daily
workflow after the rotation build, and by hand after editing
``portfolio_holdings.json``:

    python3 scripts/build_market_rotation_digest.py

``--github-output`` publishes notify_count and batch_id; ``--alert-markdown``
receives the issue body when there is something to notify.  Standard
library only.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from jsonio import dumps, load_json, replace_texts
from market_rotation_digest import alert_markdown, build_digest
from market_rotation_history import HISTORY_DIR, read_lines
from portfolio_rotation import build_exposure, holdings_by_group

ROOT = Path(__file__).resolve().parent.parent
PAGE_URL = "https://ttchang1127.github.io/ttc-stock/market_rotation.html"


def recent_snapshots(history_dir: Path, count: int = 3) -> list[dict]:
    """The latest ``count`` snapshots, oldest first."""
    index = load_json(history_dir / "index.json", None)
    if not index:
        return []
    rows: list[dict] = []
    for month in reversed(index["months"]):
        rows = read_lines(history_dir / month["path"]) + rows
        if len(rows) >= count:
            break
    return rows[-count:]


def display_names(groups: dict | None, registry: dict) -> dict[str, dict]:
    names = {row["group_id"]: {"name_zh": row["name_en"], "name_en": row["name_en"]} for row in registry["groups"]}
    for key in ("sectors", "industries"):
        for row in (groups or {}).get("data", {}).get(key, []):
            names[row["group_id"]] = {"name_zh": row["name_zh"], "name_en": row["name_en"]}
    return names


def build(root: Path = ROOT, history_dir: Path = HISTORY_DIR) -> tuple[dict, dict]:
    research = load_json(root / "market_rotation_research.json", None)
    groups = load_json(root / "market_rotation_groups.json", None)
    registry = load_json(root / "market_rotation_registry.json")
    names = display_names(groups, registry)
    overrides = load_json(root / "portfolio_classification.json")
    fund_holdings = {ticker: data for ticker in overrides.get("funds_excluded", {})
                     if (data := load_json(root / "etf_holdings" / f"{ticker}.json", None))}
    exposure = build_exposure(
        load_json(root / "portfolio_holdings.json"), load_json(root / "prices.json"),
        load_json(root / "market_rotation_universe.json"), overrides,
        registry, research, load_json(root / "portfolio_equity_exposure.json", None),
        {group_id: row["name_zh"] for group_id, row in names.items()}, fund_holdings,
    )
    snapshots = recent_snapshots(history_dir)
    digest = build_digest(snapshots[-1] if snapshots else None, snapshots[:-1], names,
                          holdings_by_group(exposure), research, groups,
                          load_json(root / "market_rotation_daily_digest.json", None))
    return digest, exposure


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--history-dir", type=Path, default=HISTORY_DIR)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--alert-markdown", type=Path)
    args = parser.parse_args()
    digest, exposure = build(args.root, args.history_dir)
    replace_texts({
        args.root / "market_rotation_daily_digest.json": dumps(digest, indent=1),
        args.root / "portfolio_equity_exposure.json": dumps(exposure, indent=1),
    })
    if args.alert_markdown and digest["notify_count"]:
        args.alert_markdown.write_text(alert_markdown(digest, exposure, PAGE_URL))
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as handle:
            handle.write(f"notify_count={digest['notify_count']}\nbatch_id={digest['batch_id'] or 'none'}\n")
    review = sum(p["research_priority"] == "review_now" for p in exposure["positions"])
    print(f"Rotation digest {digest['as_of']}: {digest['status']}, {digest['event_count']} events, "
          f"notify {digest['notify_count']}; exposure {exposure['coverage']['priced_positions']}/"
          f"{exposure['coverage']['total_positions']} priced, {review} to review")


if __name__ == "__main__":
    main()
