"""Append-only daily snapshots of the market-rotation research layer.

Plan sections 15.4-15.6, 19.5 and 20.9-20.10: one aggregate line per market
session in ``market_rotation_history/YYYY/YYYY-MM.jsonl``, listed in
``index.json``.  A snapshot records what the daily run knew on that
session (history quality A: frozen forward, never recomputed later), so it
keeps only aggregates, states and audit fields, never raw quotes.

Rules:
* the key is ``as_of + calculation_version + research_rules + universe_snapshot_id``;
* re-running the same key with the same content changes nothing;
* the same session with different content is refused: the first snapshot
  stays, and the caller reports a conflict instead of rewriting history;
* sessions only move forward; an older ``as_of`` is never back-filled.

Standard library only; the builder writes the returned texts in the same
atomic batch as the published rotation files.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from market_rotation_contracts import dump_json

ROOT = Path(__file__).resolve().parent.parent
HISTORY_DIR = ROOT / "market_rotation_history"
SCHEMA_VERSION = 1
GROUP_FIELDS = ("R20", "RS5", "RS20", "RS60", "RS120", "A5", "BPOS20", "BMA20", "P10",
                "LWGAP", "volume_expansion", "DVS5", "issuers")


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(dump_json(value).encode("utf-8")).hexdigest()


def universe_snapshot_id(universe: dict) -> str:
    """Members, classification and index membership that produced a snapshot."""
    members = sorted(
        (row["ticker"], row["sector"], row["industry"], tuple(row["indexes"]), row["classification"])
        for row in universe["members"]
    )
    return digest(members)[:23]


def snapshot_record(research: dict, groups: dict, summary: dict, universe: dict) -> dict:
    """One session's aggregate snapshot from the same validated batch."""
    data = research["data"]
    ranked = {row["group_id"]: row for key in ("sectors", "industries") for row in groups["data"][key]}
    coverage = summary["data"]["coverage"]
    market = data["market"]
    rows = {}
    for row in data["groups"]:
        score = ranked.get(row["group_id"])
        state = row["state"]
        conc = row["concentration"]
        rows[row["group_id"]] = {
            "rank": score["rank"] if score else None,
            "rotation_score": score["rotation_score"] if score else None,
            "quadrant": score["quadrant"] if score else None,
            **{field: row["evidence"].get(field) for field in GROUP_FIELDS},
            "raw_state": state["raw"],
            "confirmed_state": state["confirmed"],
            "pending_state": state["pending"],
            "days_in_state": state["days_in_state"],
            "risk_tags": row["risk_tags"],
            "median_relative_20d": conc["median_relative_20d"],
            "top1_removal_impact_pp": conc["top1_removal_impact_pp"],
            "top3_positive_share": conc["top3_positive_share"],
        }
    return {
        "as_of": research["as_of"],
        "schema_version": SCHEMA_VERSION,
        "history_quality": "A",
        "snapshot_kind": "forward_frozen",
        "calculation_version": research["versions"]["calculation"],
        "research_rules": research["versions"]["research_rules"],
        "universe_snapshot_id": universe_snapshot_id(universe),
        "dataset_id": research["dataset_id"],
        "price_source": data.get("price_source", "Yahoo Finance Adj Close via yfinance"),
        "coverage": {
            "universe_securities": coverage["universe_securities"],
            "priced_securities": coverage["priced_securities"],
            "coverage_pct": coverage["coverage_pct"],
            "unavailable_tickers": coverage["unavailable_tickers"],
        },
        "market": {
            "evidence": market["evidence"],
            "indexes": market["indexes"],
            "raw_state": market["state"]["raw"],
            "confirmed_state": market["state"]["confirmed"],
            "pending_state": market["state"]["pending"],
            "days_in_state": market["state"]["days_in_state"],
            "leadership": market["leadership"]["type"],
            "confidence": market["confidence"],
        },
        "groups": rows,
    }


def snapshot_key(record: dict) -> tuple:
    return (record["as_of"], record["calculation_version"], record["research_rules"],
            record["universe_snapshot_id"])


def read_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def empty_index() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "description": "Daily market-rotation research snapshots, one line per session; past months are immutable.",
        "history_quality": "A",
        "a_history_effective_from": None,
        "last_as_of": None,
        "snapshot_count": 0,
        "months": [],
    }


def plan_append(record: dict, history_dir: Path = HISTORY_DIR) -> tuple[dict[Path, str], str, str]:
    """Texts to write (possibly none), a status and a human message.

    Status is ``appended``, ``unchanged`` (identical rerun), ``conflict``
    (same session, different content: history kept as is) or
    ``out_of_order`` (older than the latest snapshot).
    """
    history_dir = Path(history_dir)
    index_path = history_dir / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else empty_index()
    as_of = record["as_of"]
    month = as_of[:7]
    month_path = history_dir / as_of[:4] / f"{month}.jsonl"
    lines = read_lines(month_path)

    record_hash = digest(record)
    for existing in lines:
        if existing["as_of"] != as_of:
            continue
        if snapshot_key(existing) == snapshot_key(record) and digest(existing) == record_hash:
            return {}, "unchanged", f"{as_of} snapshot already recorded"
        return {}, "conflict", (f"{as_of} already has a different snapshot "
                                f"({existing['calculation_version']}/{existing['research_rules']}); "
                                "history is append-only, the original is kept")
    if index["last_as_of"] and as_of < index["last_as_of"]:
        return {}, "out_of_order", f"{as_of} is older than the latest snapshot {index['last_as_of']}"

    month_text = "".join(dump_json(row) for row in lines + [record])
    relative = month_path.relative_to(history_dir).as_posix()
    months = [row for row in index["months"] if row["month"] != month]
    months.append({
        "month": month,
        "path": relative,
        "first_as_of": (lines[0]["as_of"] if lines else as_of),
        "last_as_of": as_of,
        "count": len(lines) + 1,
        "sha256": "sha256:" + hashlib.sha256(month_text.encode("utf-8")).hexdigest(),
    })
    index = {
        **index,
        "a_history_effective_from": index["a_history_effective_from"] or as_of,
        "last_as_of": as_of,
        "snapshot_count": index["snapshot_count"] + 1,
        "months": sorted(months, key=lambda row: row["month"]),
    }
    texts = {month_path: month_text, index_path: json.dumps(index, ensure_ascii=False, indent=1) + "\n"}
    return texts, "appended", f"{as_of} snapshot appended ({len(lines) + 1} in {month})"


def validate_history(history_dir: Path = HISTORY_DIR) -> list[str]:
    """Problems with the committed history (empty list when consistent)."""
    history_dir = Path(history_dir)
    index_path = history_dir / "index.json"
    if not index_path.exists():
        return []
    index = json.loads(index_path.read_text())
    problems, seen, total = [], [], 0
    for month in index["months"]:
        path = history_dir / month["path"]
        if not path.exists():
            problems.append(f"{month['path']} listed but missing")
            continue
        text = path.read_text()
        if "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest() != month["sha256"]:
            problems.append(f"{month['path']} changed after it was recorded")
        rows = read_lines(path)
        dates = [row["as_of"] for row in rows]
        if dates != sorted(set(dates)):
            problems.append(f"{month['path']} has duplicate or unordered sessions")
        if len(rows) != month["count"] or any(not d.startswith(month["month"]) for d in dates):
            problems.append(f"{month['path']} count or month mismatch")
        if any(row.get("history_quality") != "A" for row in rows):
            problems.append(f"{month['path']} contains a non-A snapshot")
        seen += dates
        total += len(rows)
    if seen != sorted(seen):
        problems.append("sessions are not in order across months")
    if total != index["snapshot_count"] or (seen and seen[-1] != index["last_as_of"]):
        problems.append("index totals do not match the month files")
    return problems
