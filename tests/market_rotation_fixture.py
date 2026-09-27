"""Shared loaders and assertions for the market-rotation tests.

This module only reads committed fixtures and compares outputs.  It must not
contain rotation formulas, otherwise a wrong formula could be copied here and
pass alongside the production code.

Updating the golden file is a deliberate act:

    python3 tests/market_rotation_fixture.py --update-golden

prints every changed path before writing, so the commit can explain which
formula or contract change caused it.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import pathlib
import sys

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/market_rotation"
QUADRANTS = FIXTURES / "quadrants"
GOLDEN_V1 = QUADRANTS / "expected_v1.json"
GOLDEN = {
    "v1": GOLDEN_V1,
    "summary": QUADRANTS / "expected_v2_summary.json",
    "groups": QUADRANTS / "expected_v2_groups.json",
    "stocks": QUADRANTS / "expected_v2_stocks.json",
}
VOLATILE_KEYS = ("generated_at",)


def load_builder():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "build_market_rotation", ROOT / "scripts/build_market_rotation.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_fixture(name: str = "quadrants") -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    folder = FIXTURES / name
    universe = json.loads((folder / "universe.json").read_text())
    closes = pd.read_csv(folder / "closes.csv", index_col="date", parse_dates=True)
    volumes = pd.read_csv(folder / "volumes.csv", index_col="date", parse_dates=True)
    return universe, closes.astype(float), volumes.astype(float)


def stable(payload: dict) -> dict:
    value = dict(payload)
    for key in VOLATILE_KEYS:
        value.pop(key, None)
    return value


def canonical_json(payload: dict) -> str:
    return json.dumps(stable(payload), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False) + "\n"


def differences(expected, actual, path: str = "$", limit: int = 20) -> list[str]:
    """Return readable paths such as ``$.sectors[Energy].rotation_score``."""
    found: list[str] = []

    def label(items, index):
        item = items[index]
        if isinstance(item, dict):
            for key in ("key", "group_id", "stock_id", "ticker", "date"):
                if key in item:
                    return f"{index}:{item[key]}"
        return str(index)

    def walk(left, right, where):
        if len(found) >= limit:
            return
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(set(left) | set(right)):
                if key not in left:
                    found.append(f"{where}.{key}: unexpected field")
                elif key not in right:
                    found.append(f"{where}.{key}: missing field")
                else:
                    walk(left[key], right[key], f"{where}.{key}")
        elif isinstance(left, list) and isinstance(right, list):
            if len(left) != len(right):
                found.append(f"{where}: length {len(left)} != {len(right)}")
            for index in range(min(len(left), len(right))):
                walk(left[index], right[index], f"{where}[{label(left, index)}]")
        elif left != right or type(left) is not type(right):
            found.append(f"{where}: expected {left!r}, got {right!r}")

    walk(expected, actual, path)
    return found


def build_fixture_v1() -> dict:
    universe, closes, volumes = load_fixture()
    return load_builder().build_payload(universe, closes, volumes)


_CANONICAL_CACHE: dict = {}


def fixture_canonical() -> tuple[dict, dict]:
    """The unmodified quadrants fixture is built once per test process."""
    if "quadrants" not in _CANONICAL_CACHE:
        universe, closes, volumes = load_fixture()
        _CANONICAL_CACHE["quadrants"] = load_builder().calculate_canonical(universe, closes, volumes)
    canonical, registry = _CANONICAL_CACHE["quadrants"]
    return copy.deepcopy(canonical), copy.deepcopy(registry)


def build_fixture_outputs(generated_at: str = "2026-01-01T00:00:00+00:00") -> dict:
    """v1, the three v2 files and the registry, after every batch gate passed."""
    canonical, registry = fixture_canonical()
    return load_builder().build_outputs(canonical, registry, generated_at)


def main() -> None:
    parser = argparse.ArgumentParser(description="Market-rotation golden maintenance")
    parser.add_argument("--update-golden", action="store_true")
    args = parser.parse_args()
    outputs = build_fixture_outputs()
    outputs["v1"] = build_fixture_v1()
    any_change = False
    for name, path in GOLDEN.items():
        if path.exists():
            changed = differences(stable(json.loads(path.read_text())), stable(outputs[name]), limit=200)
        else:
            changed = ["(new golden file)"]
        print(f"[{name}] " + ("\n".join(changed) or "unchanged"))
        if changed:
            any_change = True
            if args.update_golden:
                path.write_text(canonical_json(outputs[name]))
                print(f"Wrote {path.relative_to(ROOT)}")
    if any_change and not args.update_golden:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
