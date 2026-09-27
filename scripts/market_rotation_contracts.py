"""Output contracts for the market-rotation data files.

Standard library only, so the Pages quality gate and check_integrity.py can
validate committed artifacts without pandas or yfinance.  Every failure names
the JSON path, group or field that broke the contract.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
QUADRANTS = {"leading": "領先", "improving": "改善", "weakening": "轉弱", "lagging": "落後"}
SCORE_COMPONENTS = (
    "relative_strength_20d", "relative_strength_60d", "acceleration_5d",
    "breadth", "dollar_volume_expansion", "persistence",
)
# Units: "pp"/"pct" are percentage points / percent (may be negative);
# "share" is 0..100 percent of members or sessions; "score" is 0..100.
GROUP_METRIC_UNITS = {
    "return_5d": "pct", "return_20d": "pct", "return_60d": "pct",
    "relative_strength_5d": "pp", "relative_strength_20d": "pp",
    "relative_strength_60d": "pp", "acceleration_5d": "pp",
    "breadth_positive_20d": "share", "breadth_above_ma20": "share", "breadth": "share",
    "dollar_volume_expansion": "pct", "persistence": "share",
    "liquidity_weighted_return_20d": "pct", "leadership_gap": "pp",
}
STOCK_METRIC_UNITS = {
    "return_5d": "pct", "return_20d": "pct", "return_60d": "pct",
    "relative_strength_20d": "pp", "dollar_volume_expansion": "pct",
}
MIN_MEMBERS = {"sector": 5, "industry": 3}
TRAJECTORY_POINTS = 10
MIN_COVERAGE_PCT = 90.0


class ContractError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        shown = "\n  ".join(errors[:25])
        more = f"\n  ... {len(errors) - 25} more" if len(errors) > 25 else ""
        super().__init__(f"{len(errors)} contract violation(s):\n  {shown}{more}")


def group_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def dump_json(payload: Any) -> str:
    """The one serialisation used for every published rotation file."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"


class Checker:
    def __init__(self):
        self.errors: list[str] = []

    def fail(self, path: str, message: str) -> None:
        self.errors.append(f"{path}: {message}")

    def raise_if_failed(self) -> None:
        if self.errors:
            raise ContractError(self.errors)

    def finite_everywhere(self, value: Any, path: str = "$") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                self.finite_everywhere(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                self.finite_everywhere(item, f"{path}[{index}]")
        elif isinstance(value, float) and not math.isfinite(value):
            self.fail(path, f"non-finite number {value!r}")

    def require(self, row: Any, path: str, key: str, kind: type | tuple, nullable=False) -> Any:
        if not isinstance(row, dict):
            self.fail(path, "must be an object")
            return None
        if key not in row:
            self.fail(f"{path}.{key}", "missing field")
            return None
        value = row[key]
        if value is None and nullable:
            return None
        if kind in (int, float, (int, float)) and isinstance(value, bool):
            self.fail(f"{path}.{key}", "must be a number, not a boolean")
            return None
        if not isinstance(value, kind):
            self.fail(f"{path}.{key}", f"expected {getattr(kind, '__name__', kind)}, got {type(value).__name__}")
            return None
        return value

    def number(self, row: Any, path: str, key: str, nullable=True, low=None, high=None):
        value = self.require(row, path, key, (int, float), nullable=nullable)
        if isinstance(value, (int, float)) and math.isfinite(value):
            if low is not None and value < low or high is not None and value > high:
                self.fail(f"{path}.{key}", f"{value} outside [{low}, {high}]")
        return value

    def date(self, row: Any, path: str, key: str, nullable=False):
        value = self.require(row, path, key, str, nullable=nullable)
        if isinstance(value, str) and not DATE.match(value):
            self.fail(f"{path}.{key}", f"expected YYYY-MM-DD, got {value!r}")
        return value

    def metrics(self, row: dict, path: str, units: dict, required: tuple = ()):
        for key, unit in units.items():
            bounds = (0, 100) if unit in ("share", "score") else (None, None)
            self.number(row, path, key, nullable=key not in required, low=bounds[0], high=bounds[1])


def check_quadrant(checker: Checker, path: str, quadrant: Any, x: Any, y: Any) -> None:
    if quadrant not in QUADRANTS:
        checker.fail(f"{path}.quadrant", f"unknown quadrant {quadrant!r}")
        return
    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
        expected = ("leading" if x >= 0 and y >= 0 else "improving" if x < 0 <= y
                    else "weakening" if x >= 0 > y else "lagging")
        if quadrant != expected:
            checker.fail(f"{path}.quadrant", f"{quadrant} contradicts x={x}, y={y} ({expected})")


def check_trajectory(checker: Checker, path: str, trail: Any, as_of: Any) -> None:
    if not isinstance(trail, list):
        checker.fail(path, "must be a list")
        return
    if len(trail) > TRAJECTORY_POINTS:
        checker.fail(path, f"{len(trail)} points, maximum {TRAJECTORY_POINTS}")
    dates = []
    for index, point in enumerate(trail):
        where = f"{path}[{index}]"
        dates.append(checker.date(point, where, "date"))
        checker.number(point, where, "x", nullable=False)
        checker.number(point, where, "y", nullable=False)
        checker.number(point, where, "score", nullable=False, low=0, high=100)
    valid = [value for value in dates if isinstance(value, str)]
    if valid != sorted(set(valid)):
        checker.fail(path, "dates must be unique and oldest first")
    if valid and isinstance(as_of, str) and valid[-1] > as_of:
        checker.fail(path, f"last point {valid[-1]} is after as_of {as_of}")


def check_ranked_order(checker: Checker, path: str, rows: list[dict], key_field: str) -> None:
    keys = [(-(row.get("rotation_score") or 0), group_slug(str(row.get(key_field, ""))))
            for row in rows if isinstance(row, dict)]
    if keys != sorted(keys):
        checker.fail(path, "must be ordered by rotation_score descending, then stable group id")


def validate_v1(payload: Any) -> None:
    """Validate the legacy ``market_rotation.json`` shape consumed by the live page."""
    c = Checker()
    c.finite_everywhere(payload)
    if not isinstance(payload, dict):
        raise ContractError(["$: must be an object"])
    if payload.get("schema_version") != 1:
        c.fail("$.schema_version", f"expected 1, got {payload.get('schema_version')!r}")
    c.require(payload, "$", "generated_at", str)
    as_of = c.date(payload, "$", "as_of")

    methodology = c.require(payload, "$", "methodology", dict) or {}
    c.require(methodology, "$.methodology", "label", str)
    weights = c.require(methodology, "$.methodology", "score_weights", dict) or {}
    if weights and (set(weights) != set(SCORE_COMPONENTS) or sum(weights.values()) != 100):
        c.fail("$.methodology.score_weights", "must cover the six components and sum to 100")
    c.require(payload, "$", "sources", dict)

    coverage = c.require(payload, "$", "coverage", dict) or {}
    universe = c.require(coverage, "$.coverage", "universe_securities", int)
    priced = c.require(coverage, "$.coverage", "priced_securities", int)
    if isinstance(universe, int) and isinstance(priced, int) and not 0 < priced <= universe:
        c.fail("$.coverage.priced_securities", f"{priced} not within 1..{universe}")
    c.number(coverage, "$.coverage", "coverage_pct", nullable=False, low=MIN_COVERAGE_PCT, high=100)
    tickers = c.require(coverage, "$.coverage", "unavailable_tickers", list) or []
    if any(not isinstance(value, str) for value in tickers):
        c.fail("$.coverage.unavailable_tickers", "must contain ticker strings")
    for index, row in enumerate(c.require(coverage, "$.coverage", "unranked_groups", list) or []):
        where = f"$.coverage.unranked_groups[{index}]"
        if c.require(row, where, "type", str) not in MIN_MEMBERS:
            c.fail(f"{where}.type", "must be sector or industry")
        c.require(row, where, "key", str)
        missing = c.require(row, where, "missing_components", list) or []
        if not missing or not set(missing) <= set(SCORE_COMPONENTS):
            c.fail(f"{where}.missing_components", f"invalid components {missing!r}")
    c.date(coverage, "$.coverage", "start")
    if c.date(coverage, "$.coverage", "end") != as_of:
        c.fail("$.coverage.end", "must equal as_of")

    benchmark = c.require(payload, "$", "benchmark", dict) or {}
    c.require(benchmark, "$.benchmark", "name", str)
    for key in ("return_5d", "return_20d", "return_60d", "dollar_volume_expansion"):
        c.number(benchmark, "$.benchmark", key)

    for collection, group_type in (("sectors", "sector"), ("industries", "industry")):
        rows = c.require(payload, "$", collection, list) or []
        if collection == "sectors" and not rows:
            c.fail("$.sectors", "must not be empty")
        seen = set()
        for index, row in enumerate(rows):
            key = row.get("key") if isinstance(row, dict) else None
            where = f"$.{collection}[{index}:{key}]"
            if c.require(row, where, "key", str) in seen:
                c.fail(f"{where}.key", "duplicate group key")
            seen.add(key)
            c.require(row, where, "name", str)
            c.require(row, where, "name_zh", str)
            members = c.require(row, where, "member_count", int)
            if isinstance(members, int) and members < MIN_MEMBERS[group_type]:
                c.fail(f"{where}.member_count", f"{members} below minimum {MIN_MEMBERS[group_type]}")
            c.metrics(row, where, GROUP_METRIC_UNITS, required=SCORE_COMPONENTS)
            for component in SCORE_COMPONENTS:
                c.number(row, where, f"rank_{component}", nullable=False, low=0, high=100)
            c.number(row, where, "rotation_score", nullable=False, low=0, high=100)
            c.number(row, where, "score_change_5d", low=-100, high=100)
            check_quadrant(c, where, row.get("quadrant"), row.get("relative_strength_20d"),
                           row.get("acceleration_5d"))
            if row.get("quadrant") in QUADRANTS and row.get("quadrant_zh") != QUADRANTS[row["quadrant"]]:
                c.fail(f"{where}.quadrant_zh", f"does not match {row['quadrant']}")
            check_trajectory(c, f"{where}.trajectory", row.get("trajectory"), as_of)
            if group_type == "sector":
                for side in ("leaders", "laggards"):
                    stocks = c.require(row, where, side, list) or []
                    if len(stocks) > 5:
                        c.fail(f"{where}.{side}", f"{len(stocks)} entries, maximum 5")
                    for position, stock in enumerate(stocks):
                        spot = f"{where}.{side}[{position}]"
                        c.require(stock, spot, "ticker", str)
                        c.require(stock, spot, "name", str)
                        c.metrics(stock, spot, STOCK_METRIC_UNITS, required=("relative_strength_20d",))
        check_ranked_order(c, f"$.{collection}", rows, "key")
    c.raise_if_failed()
