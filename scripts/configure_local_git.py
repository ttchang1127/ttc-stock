#!/usr/bin/env python3
"""Keep macOS Finder icon metadata from breaking Git reference discovery.

On some external macOS volumes, folders given a custom icon receive an empty
``Icon\r`` resource-fork carrier.  When that happens below ``.git/refs``, Git
interprets the file as a loose ref and fetch/pull fails before negotiation.

This tool removes only zero-byte files with that exact Finder filename under
``.git/refs`` and configures Git to hide Codex's local checkpoint namespace
from fetch connectivity checks.  Other refs and non-empty files are untouched.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

FINDER_ICON_NAME = "Icon\r"
CODEX_FETCH_HIDE_REF = "refs/codex"


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, text=True, capture_output=True, check=True,
    )


def resolve_git_dir(repo: Path) -> Path:
    result = run_git(repo, "rev-parse", "--path-format=absolute", "--git-dir")
    return Path(result.stdout.strip()).resolve()


def invalid_finder_ref_files(git_dir: Path) -> list[Path]:
    refs = git_dir / "refs"
    if not refs.is_dir():
        return []
    return sorted(
        path for path in refs.rglob("*")
        if path.is_file() and path.name == FINDER_ICON_NAME and path.stat().st_size == 0
    )


def remove_invalid_finder_refs(git_dir: Path) -> list[Path]:
    removed = invalid_finder_ref_files(git_dir)
    for path in removed:
        path.unlink()
    return removed


def fetch_hidden_refs(repo: Path) -> list[str]:
    result = subprocess.run(
        ["git", "config", "--local", "--get-all", "fetch.hideRefs"],
        cwd=repo, text=True, capture_output=True, check=False,
    )
    if result.returncode not in {0, 1}:
        raise subprocess.CalledProcessError(
            result.returncode, result.args, result.stdout, result.stderr,
        )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def configure_fetch_hide_ref(repo: Path) -> bool:
    values = fetch_hidden_refs(repo)
    if CODEX_FETCH_HIDE_REF in values:
        return False
    run_git(repo, "config", "--local", "--add", "fetch.hideRefs", CODEX_FETCH_HIDE_REF)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--check", action="store_true",
        help="只檢查，不刪除檔案或修改本機 Git config",
    )
    args = parser.parse_args()
    repo = args.repo.resolve()
    git_dir = resolve_git_dir(repo)
    invalid = invalid_finder_ref_files(git_dir)
    hide_configured = CODEX_FETCH_HIDE_REF in fetch_hidden_refs(repo)

    if args.check:
        print(f"Finder 非法 ref：{len(invalid)}；fetch.hideRefs：{'已設定' if hide_configured else '未設定'}")
        for path in invalid:
            print(f"  {path}")
        return 1 if invalid or not hide_configured else 0

    removed = remove_invalid_finder_refs(git_dir)
    added = configure_fetch_hide_ref(repo)
    print(f"已移除 {len(removed)} 個空白 Finder Icon ref")
    print(f"fetch.hideRefs={CODEX_FETCH_HIDE_REF}：{'本次新增' if added else '原已設定'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
