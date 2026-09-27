"""Read data_manifest.json: who produces each data file and who may commit it.

Standard library only.  Workflows call

    python3 scripts/data_manifest.py check-changed --workflow update-prices

before committing, instead of maintaining a hand-written regex allowlist.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "data_manifest.json"


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    return json.loads(path.read_text())


def entry_for(path: str, manifest: dict) -> dict | None:
    for row in manifest["files"]:
        if row["path"] == path:
            return row
    for row in manifest["patterns"]:
        if re.search(row["pattern"], path):
            return row
    return None


def may_commit(path: str, workflow: str, manifest: dict) -> bool:
    row = entry_for(path, manifest)
    return bool(row) and workflow in row["committed_by"]


def allowlist_regex(workflow: str, manifest: dict) -> str:
    """The equivalent single regex, for documentation and marker checks."""
    json_stems = [row["path"][:-5] for row in manifest["files"]
                  if workflow in row["committed_by"] and "/" not in row["path"] and row["path"].endswith(".json")]
    other = [re.escape(row["path"]) for row in manifest["files"]
             if workflow in row["committed_by"] and not (row["path"].endswith(".json") and "/" not in row["path"])]
    patterns = [row["pattern"] for row in manifest["patterns"] if workflow in row["committed_by"]]
    parts = [f"^({'|'.join(json_stems)})\\.json$"] if json_stems else []
    parts += [f"^{path}$" for path in other] + patterns
    return "|".join(parts)


def changed_paths() -> list[str]:
    out = subprocess.run(["git", "status", "--porcelain", "-z", "--untracked-files=all"],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    paths, records = [], out.split("\0")
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        status, path = record[:2], record[3:]
        paths.append(path)
        if "R" in status or "C" in status:
            index += 1  # skip the rename source
    return sorted(set(paths))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check-changed", help="fail if a changed path is not committable by the workflow")
    check.add_argument("--workflow", required=True)
    check.add_argument("paths", nargs="*", help="paths to check instead of git status")
    explain = sub.add_parser("explain", help="show the manifest entry for a path")
    explain.add_argument("path")
    args = parser.parse_args()
    manifest = load_manifest()

    if args.command == "explain":
        print(json.dumps(entry_for(args.path, manifest), ensure_ascii=False, indent=2))
        return
    paths = args.paths or changed_paths()
    unexpected = [path for path in paths if not may_commit(path, args.workflow, manifest)]
    if unexpected:
        print(f"Unexpected files changed for {args.workflow}; refusing to commit:")
        for path in unexpected:
            row = entry_for(path, manifest)
            reason = "not in data_manifest.json" if row is None else f"committed_by {row['committed_by']}"
            print(f"  {path} ({reason})")
        sys.exit(1)
    print(f"{len(paths)} changed path(s) are committable by {args.workflow}.")


if __name__ == "__main__":
    main()
