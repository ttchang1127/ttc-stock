"""Append-only daily records: one JSON line per session in ``YYYY-MM.jsonl`` files.

Shared by the ETF flow record and the ETF health snapshots.  A record is a
dict with ``as_of`` (YYYY-MM-DD) and ``etfs``; a session is written once.
A rerun with identical ``etfs`` is a no-op, a rerun with different values
keeps the first line (a conflict to report, never an overwrite), and a
session older than the last recorded one is refused.
"""

from __future__ import annotations

import json
from pathlib import Path

from jsonio import dumps


def read_history(directory: Path) -> list[dict]:
    rows = []
    for path in sorted(Path(directory).glob("*.jsonl")):
        rows.extend(json.loads(line) for line in path.read_text().splitlines() if line.strip())
    return rows


def plan_append(record: dict, directory: Path) -> tuple[dict[Path, str], str, str]:
    """(texts, status, message); status is appended / unchanged / conflict / out_of_order."""
    directory = Path(directory)
    history = read_history(directory)
    same = next((row for row in history if row["as_of"] == record["as_of"]), None)
    if same is not None:
        if same["etfs"] == record["etfs"]:
            return {}, "unchanged", f"{directory.name}: {record['as_of']} already recorded"
        return {}, "conflict", f"{directory.name}: {record['as_of']} already recorded with other values; kept the first"
    if history and history[-1]["as_of"] > record["as_of"]:
        return {}, "out_of_order", f"{directory.name}: {record['as_of']} is older than {history[-1]['as_of']}"
    path = directory / f"{record['as_of'][:7]}.jsonl"
    existing = path.read_text() if path.exists() else ""
    return {path: existing + dumps(record)}, "appended", f"{directory.name}: recorded {record['as_of']}"


def validate_history(directory: Path) -> list[str]:
    directory = Path(directory)
    problems, dates = [], []
    for path in sorted(directory.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if not row["as_of"].startswith(path.stem):
                problems.append(f"{directory.name}/{path.name}: {row['as_of']} is in the wrong month file")
            dates.append(row["as_of"])
    if dates != sorted(set(dates)):
        problems.append(f"{directory.name}: dates are duplicated or out of order")
    return problems
