"""Output contracts for the market-rotation data files.

Standard library only, so the Pages quality gate and check_integrity.py can
validate committed artifacts without pandas or yfinance.  Every failure names
the JSON path, group or field that broke the contract.
"""

from __future__ import annotations

import hashlib
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


def check_ranked_order(checker: Checker, path: str, rows: list[dict]) -> None:
    # v1 rows carry no stable id (an alias may keep an old id after a rename),
    # so only score order is checked here; v2 also checks the id tie-break.
    scores = [row.get("rotation_score") or 0 for row in rows if isinstance(row, dict)]
    if scores != sorted(scores, reverse=True):
        checker.fail(path, "must be ordered by rotation_score descending")


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
        check_ranked_order(c, f"$.{collection}", rows)
    c.raise_if_failed()


# ---------------------------------------------------------------------------
# v2: summary / groups / stocks sharing one dataset_id
# ---------------------------------------------------------------------------

SCHEMA_VERSION_V2 = 2
V2_FILES = ("summary", "groups", "stocks")
GROUP_ID = re.compile(r"^(sector|industry):[a-z0-9]+(?:-[a-z0-9]+)*$")
STOCK_ID = re.compile(r"^security:[a-z0-9]+(?:-[a-z0-9]+)*$")
DATASET_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
ROLES = ("leader", "improver", "weakening", "broadest")
STOCK_FLAGS = {"missing_return_20d", "missing_volume"}
SUMMARY_MAX_BYTES = 50_000
CARD_EVIDENCE_LIMIT = 3


def compute_dataset_id(canonical: dict) -> str:
    """SHA-256 of the canonical model; generated_at and paths are never inside it."""
    text = json.dumps(canonical, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve_field(group: dict, field: str) -> tuple[bool, Any]:
    value: Any = group
    for part in field.split("."):
        if not isinstance(value, dict) or part not in value:
            return False, None
        value = value[part]
    return True, value


def check_group_records(c: Checker, path: str, groups: Any, as_of: Any,
                        stock_sectors: dict | None) -> dict:
    """Validate normalised group records; returns {group_id: record}."""
    by_id: dict = {}
    if not isinstance(groups, list):
        c.fail(path, "must be a list")
        return by_id
    ranks: dict[str, list] = {"sector": [], "industry": []}
    for index, group in enumerate(groups):
        gid = group.get("group_id") if isinstance(group, dict) else None
        where = f"{path}[{index}:{gid}]"
        gid = c.require(group, where, "group_id", str)
        if gid is None:
            continue
        if not GROUP_ID.match(gid):
            c.fail(f"{where}.group_id", "invalid group id format")
        if gid in by_id:
            c.fail(f"{where}.group_id", "duplicate group id")
        by_id[gid] = group
        group_type = c.require(group, where, "group_type", str)
        if group_type not in MIN_MEMBERS or not gid.startswith(f"{group_type}:"):
            c.fail(f"{where}.group_type", f"{group_type!r} does not match id {gid}")
            continue
        parent = group.get("parent_group_id")
        if group_type == "sector" and parent is not None:
            c.fail(f"{where}.parent_group_id", "must be null for a sector")
        if group_type == "industry" and not (isinstance(parent, str) and parent.startswith("sector:")):
            c.fail(f"{where}.parent_group_id", "industry needs a sector parent")
        c.require(group, where, "name_en", str)
        c.require(group, where, "name_zh", str)
        members = c.require(group, where, "member_count", int)
        if isinstance(members, int) and members < MIN_MEMBERS[group_type]:
            c.fail(f"{where}.member_count", f"{members} below minimum {MIN_MEMBERS[group_type]}")
        ranks[group_type].append(c.require(group, where, "rank", int))
        metrics = c.require(group, where, "metrics", dict) or {}
        extra = set(metrics) - set(GROUP_METRIC_UNITS)
        if extra:
            c.fail(f"{where}.metrics", f"unexpected metrics {sorted(extra)}")
        c.metrics(metrics, f"{where}.metrics", GROUP_METRIC_UNITS, required=SCORE_COMPONENTS)
        percentiles = c.require(group, where, "ranks", dict) or {}
        if set(percentiles) != set(SCORE_COMPONENTS):
            c.fail(f"{where}.ranks", "must hold exactly the six score components")
        for component in SCORE_COMPONENTS:
            c.number(percentiles, f"{where}.ranks", component, nullable=False, low=0, high=100)
        c.number(group, where, "rotation_score", nullable=False, low=0, high=100)
        c.number(group, where, "score_change_5d", low=-100, high=100)
        check_quadrant(c, where, group.get("quadrant"), metrics.get("relative_strength_20d"),
                       metrics.get("acceleration_5d"))
        check_trajectory(c, f"{where}.trajectory", group.get("trajectory"), as_of)
        for side in ("leader_stock_ids", "laggard_stock_ids"):
            refs = group.get(side, "missing")
            if group_type == "industry":
                if refs is not None:
                    c.fail(f"{where}.{side}", "industries carry no stock selection (null)")
                continue
            if not isinstance(refs, list) or len(refs) > 5 or len(set(refs)) != len(refs):
                c.fail(f"{where}.{side}", "must be up to 5 unique stock ids")
                continue
            for ref in refs:
                if stock_sectors is None:
                    continue
                if ref not in stock_sectors:
                    c.fail(f"{where}.{side}", f"unknown stock {ref}")
                elif stock_sectors[ref] != gid:
                    c.fail(f"{where}.{side}", f"{ref} belongs to {stock_sectors[ref]}")
    for group_type, values in ranks.items():
        if values and values != list(range(1, len(values) + 1)):
            c.fail(path, f"{group_type} ranks must run 1..{len(values)} in list order")
    for group_type in MIN_MEMBERS:
        rows = [g for g in groups if isinstance(g, dict) and g.get("group_type") == group_type]
        keys = [(-(g.get("rotation_score") or 0), g.get("group_id", "")) for g in rows]
        if keys != sorted(keys):
            c.fail(path, f"{group_type} groups must be ordered by rotation_score, then group id")
    return by_id


def check_stock_records(c: Checker, path: str, stocks: Any) -> dict:
    """Validate security records; returns {stock_id: sector_id}."""
    sectors: dict = {}
    if not isinstance(stocks, list):
        c.fail(path, "must be a list")
        return sectors
    tickers = set()
    for index, stock in enumerate(stocks):
        sid = stock.get("stock_id") if isinstance(stock, dict) else None
        where = f"{path}[{index}:{sid}]"
        sid = c.require(stock, where, "stock_id", str)
        if sid is None:
            continue
        if not STOCK_ID.match(sid):
            c.fail(f"{where}.stock_id", "invalid stock id format")
        if sid in sectors:
            c.fail(f"{where}.stock_id", "duplicate stock id")
        ticker = c.require(stock, where, "ticker", str)
        if ticker in tickers:
            c.fail(f"{where}.ticker", "duplicate ticker")
        tickers.add(ticker)
        for key in ("yahoo_ticker", "name", "classification", "sector_name_en", "industry_name_en"):
            c.require(stock, where, key, str)
        sector = c.require(stock, where, "sector_id", str)
        if isinstance(sector, str) and not sector.startswith("sector:"):
            c.fail(f"{where}.sector_id", "must be a sector id")
        industry = c.require(stock, where, "industry_id", str)
        if isinstance(industry, str) and not industry.startswith("industry:"):
            c.fail(f"{where}.industry_id", "must be an industry id")
        sectors[sid] = sector
        indexes = c.require(stock, where, "indexes", list) or []
        if not indexes or any(not isinstance(value, str) for value in indexes):
            c.fail(f"{where}.indexes", "must list at least one index name")
        c.metrics(c.require(stock, where, "metrics", dict) or {}, f"{where}.metrics", STOCK_METRIC_UNITS)
        flags = c.require(stock, where, "quality_flags", list) or []
        if not set(flags) <= STOCK_FLAGS:
            c.fail(f"{where}.quality_flags", f"unknown flags {sorted(set(flags) - STOCK_FLAGS)}")
    ids = [s.get("stock_id") for s in stocks if isinstance(s, dict)]
    if ids != sorted(ids):
        c.fail(path, "stocks must be ordered by stock_id")
    return sectors


def check_unranked(c: Checker, path: str, rows: Any, group_ids: dict) -> None:
    for index, row in enumerate(rows if isinstance(rows, list) else []):
        where = f"{path}[{index}]"
        gid = c.require(row, where, "group_id", str)
        if isinstance(gid, str) and not GROUP_ID.match(gid):
            c.fail(f"{where}.group_id", "invalid group id format")
        if gid in group_ids:
            c.fail(f"{where}.group_id", "an unranked group cannot also be ranked")
        if c.require(row, where, "group_type", str) not in MIN_MEMBERS:
            c.fail(f"{where}.group_type", "must be sector or industry")
        c.require(row, where, "name_en", str)
        missing = c.require(row, where, "missing_components", list) or []
        if not missing or not set(missing) <= set(SCORE_COMPONENTS):
            c.fail(f"{where}.missing_components", f"invalid components {missing!r}")


def check_roles(c: Checker, path: str, roles: Any, groups: dict) -> None:
    if not isinstance(roles, dict) or set(roles) != set(ROLES):
        c.fail(path, f"must define exactly {list(ROLES)}")
        return
    expected_quadrant = {"leader": "leading", "improver": "improving", "weakening": "weakening"}
    for role, gid in roles.items():
        if gid is None:
            continue
        group = groups.get(gid)
        if group is None or group.get("group_type") != "sector":
            c.fail(f"{path}.{role}", f"{gid!r} is not a ranked sector")
        elif role in expected_quadrant and group.get("quadrant") != expected_quadrant[role]:
            c.fail(f"{path}.{role}", f"{gid} is {group.get('quadrant')}, not {expected_quadrant[role]}")


def validate_canonical(canonical: Any) -> None:
    c = Checker()
    c.finite_everywhere(canonical)
    if not isinstance(canonical, dict):
        raise ContractError(["$: must be an object"])
    for forbidden in ("generated_at", "dataset_id"):
        if forbidden in canonical:
            c.fail(f"$.{forbidden}", "must not be part of the canonical model")
    as_of = c.date(canonical, "$", "as_of")
    stocks = check_stock_records(c, "$.stocks", canonical.get("stocks"))
    groups = check_group_records(c, "$.groups", canonical.get("groups"), as_of, stocks)
    check_unranked(c, "$.coverage.unranked_groups",
                   (canonical.get("coverage") or {}).get("unranked_groups"), groups)
    check_roles(c, "$.roles", canonical.get("roles"), groups)
    c.raise_if_failed()


def check_envelope(c: Checker, name: str, payload: Any) -> dict:
    path = f"{name}"
    if not isinstance(payload, dict):
        c.fail(path, "must be an object")
        return {}
    if payload.get("schema_name") != f"market-rotation-{name}":
        c.fail(f"{path}.schema_name", f"expected market-rotation-{name}, got {payload.get('schema_name')!r}")
    version = payload.get("schema_version")
    if version != SCHEMA_VERSION_V2:
        c.fail(f"{path}.schema_version", f"expected {SCHEMA_VERSION_V2}, got {version!r}")
    dataset = c.require(payload, path, "dataset_id", str)
    if isinstance(dataset, str) and not DATASET_ID.match(dataset):
        c.fail(f"{path}.dataset_id", "must be sha256:<64 hex>")
    c.date(payload, path, "as_of")
    c.require(payload, path, "generated_at", str)
    versions = c.require(payload, path, "versions", dict) or {}
    for key in ("calculation", "universe"):
        c.require(versions, f"{path}.versions", key, str)
    return c.require(payload, path, "data", dict) or {}


def validate_v2(summary: Any, groups: Any, stocks: Any) -> None:
    """Validate the three v2 files as one batch, including cross-file references."""
    c = Checker()
    payloads = {"summary": summary, "groups": groups, "stocks": stocks}
    data = {}
    for name, payload in payloads.items():
        c.finite_everywhere(payload, name)
        data[name] = check_envelope(c, name, payload)
    for key in ("dataset_id", "as_of", "versions", "schema_version"):
        values = {name: payload.get(key) for name, payload in payloads.items() if isinstance(payload, dict)}
        if len({json.dumps(value, sort_keys=True) for value in values.values()}) > 1:
            c.fail(f"*.{key}", f"files come from different batches: {values}")
    as_of = summary.get("as_of") if isinstance(summary, dict) else None

    stock_sectors = check_stock_records(c, "stocks.data.stocks", data["stocks"].get("stocks"))
    group_rows = (data["groups"].get("sectors") or []) + (data["groups"].get("industries") or [])
    for collection, group_type in (("sectors", "sector"), ("industries", "industry")):
        rows = data["groups"].get(collection)
        if not isinstance(rows, list) or any(
                isinstance(row, dict) and row.get("group_type") != group_type for row in rows):
            c.fail(f"groups.data.{collection}", f"must be a list of {group_type} records")
    group_ids = check_group_records(c, "groups.data", group_rows, as_of, stock_sectors)

    body = data["summary"]
    if body.get("status") != "ready":
        c.fail("summary.data.status", "a published summary must be ready")
    coverage = c.require(body, "summary.data", "coverage", dict) or {}
    c.number(coverage, "summary.data.coverage", "coverage_pct", nullable=False,
             low=MIN_COVERAGE_PCT, high=100)
    check_unranked(c, "summary.data.coverage.unranked_groups", coverage.get("unranked_groups"), group_ids)
    c.require(body, "summary.data", "benchmark", dict)
    c.require(body, "summary.data", "methodology", dict)
    defaults = c.require(body, "summary.data", "defaults", dict) or {}
    for key, group_type in (("chart_group_ids", "sector"), ("top_industry_ids", "industry")):
        for ref in c.require(defaults, "summary.data.defaults", key, list) or []:
            if ref not in group_ids or group_ids[ref].get("group_type") != group_type:
                c.fail(f"summary.data.defaults.{key}", f"{ref!r} is not a ranked {group_type}")
    check_roles(c, "summary.data.roles", body.get("roles"), group_ids)
    for index, card in enumerate(c.require(body, "summary.data", "cards", list) or []):
        where = f"summary.data.cards[{index}]"
        gid = c.require(card, where, "group_id", str)
        if gid not in group_ids:
            c.fail(f"{where}.group_id", f"{gid!r} not in groups")
        card_roles = c.require(card, where, "roles", list) or []
        if not card_roles or not set(card_roles) <= set(ROLES):
            c.fail(f"{where}.roles", f"invalid roles {card_roles!r}")
        evidence = c.require(card, where, "evidence", list) or []
        if len(evidence) > CARD_EVIDENCE_LIMIT:
            c.fail(f"{where}.evidence", f"{len(evidence)} items, maximum {CARD_EVIDENCE_LIMIT}")
        for position, item in enumerate(evidence):
            ref = item.get("group_id") if isinstance(item, dict) else None
            field = item.get("field") if isinstance(item, dict) else None
            if ref not in group_ids or not isinstance(field, str) \
                    or not resolve_field(group_ids[ref], field)[0]:
                c.fail(f"{where}.evidence[{position}]", f"{ref}/{field} does not resolve")
    size = len(dump_json(summary).encode("utf-8")) if not c.errors else 0
    if size > SUMMARY_MAX_BYTES:
        c.fail("summary", f"{size} bytes exceeds {SUMMARY_MAX_BYTES}")
    c.raise_if_failed()


def v1_comparison(v1: dict) -> dict:
    """Project v1 onto the shared comparison structure used by parity checks."""
    result = {}
    for collection, group_type in (("sectors", "sector"), ("industries", "industry")):
        for position, row in enumerate(v1.get(collection) or []):
            entry = {
                "position": position, "member_count": row.get("member_count"),
                "metrics": {key: row.get(key) for key in GROUP_METRIC_UNITS},
                "ranks": {key: row.get(f"rank_{key}") for key in SCORE_COMPONENTS},
                "rotation_score": row.get("rotation_score"),
                "score_change_5d": row.get("score_change_5d"),
                "quadrant": row.get("quadrant"), "trajectory": row.get("trajectory"),
            }
            if group_type == "sector":
                for side in ("leaders", "laggards"):
                    entry[side] = [{"ticker": s.get("ticker"), "name": s.get("name"),
                                    **{k: s.get(k) for k in STOCK_METRIC_UNITS}}
                                   for s in row.get(side) or []]
            result[(group_type, row.get("key"))] = entry
    return result


def v2_comparison(groups: dict, stocks: dict) -> dict:
    by_id = {s["stock_id"]: s for s in stocks["data"]["stocks"]}
    result = {}
    for collection, group_type in (("sectors", "sector"), ("industries", "industry")):
        for position, group in enumerate(groups["data"][collection]):
            entry = {
                "position": position, "member_count": group["member_count"],
                "metrics": {key: group["metrics"].get(key) for key in GROUP_METRIC_UNITS},
                "ranks": dict(group["ranks"]), "rotation_score": group["rotation_score"],
                "score_change_5d": group["score_change_5d"],
                "quadrant": group["quadrant"], "trajectory": group["trajectory"],
            }
            if group_type == "sector":
                for side, key in (("leaders", "leader_stock_ids"), ("laggards", "laggard_stock_ids")):
                    entry[side] = [{"ticker": by_id[ref]["ticker"], "name": by_id[ref]["name"],
                                    **{k: by_id[ref]["metrics"].get(k) for k in STOCK_METRIC_UNITS}}
                                   for ref in group[key]]
            result[(group_type, group["name_en"])] = entry
    return result


def exact_differences(left: Any, right: Any, path: str, found: list) -> None:
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right), key=str):
            exact_differences(left.get(key, "<missing>"), right.get(key, "<missing>"),
                              f"{path}.{key}", found)
    elif isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        for index, (a, b) in enumerate(zip(left, right)):
            exact_differences(a, b, f"{path}[{index}]", found)
    elif left != right or type(left) is not type(right):
        found.append(f"{path}: v1={left!r} v2={right!r}")


def check_parity(v1: dict, summary: dict, groups: dict, stocks: dict) -> None:
    """v1 and v2 must carry identical numbers; serialisers never recalculate."""
    found: list[str] = []
    left, right = v1_comparison(v1), v2_comparison(groups, stocks)
    for key in sorted(set(left) | set(right)):
        label = f"{key[0]}[{key[1]}]"
        if key not in left or key not in right:
            found.append(f"{label}: only in {'v2' if key not in left else 'v1'}")
            continue
        exact_differences(left[key], right[key], label, found)
    body = summary["data"]
    if v1.get("as_of") != summary.get("as_of"):
        found.append(f"as_of: v1={v1.get('as_of')} v2={summary.get('as_of')}")
    exact_differences(v1.get("benchmark"), body.get("benchmark"), "benchmark", found)
    exact_differences(v1.get("methodology"), body.get("methodology"), "methodology", found)
    coverage_v1 = dict(v1.get("coverage") or {})
    coverage_v2 = dict(body.get("coverage") or {})
    unranked_v1 = [(r.get("type"), r.get("key"), r.get("missing_components"))
                   for r in coverage_v1.pop("unranked_groups", [])]
    unranked_v2 = [(r.get("group_type"), r.get("name_en"), r.get("missing_components"))
                   for r in coverage_v2.pop("unranked_groups", [])]
    exact_differences(coverage_v1, coverage_v2, "coverage", found)
    if unranked_v1 != unranked_v2:
        found.append(f"coverage.unranked_groups: v1={unranked_v1} v2={unranked_v2}")
    if found:
        raise ContractError(["parity " + item for item in found])


def validate_registry(registry: Any) -> None:
    c = Checker()
    if not isinstance(registry, dict) or registry.get("schema_version") != 1:
        raise ContractError(["registry: expected schema_version 1"])
    for collection, id_key, pattern in (("groups", "group_id", GROUP_ID),
                                        ("securities", "stock_id", STOCK_ID)):
        seen_ids, seen_names = set(), set()
        rows = c.require(registry, "registry", collection, list) or []
        for index, row in enumerate(rows):
            where = f"registry.{collection}[{index}]"
            identifier = c.require(row, where, id_key, str)
            if isinstance(identifier, str) and not pattern.match(identifier):
                c.fail(f"{where}.{id_key}", "invalid id format")
            if identifier in seen_ids:
                c.fail(f"{where}.{id_key}", "duplicate id")
            seen_ids.add(identifier)
            names = [c.require(row, where, "name_en" if collection == "groups" else "ticker", str)]
            names += c.require(row, where, "aliases", list) or []
            scope = row.get("group_type") if collection == "groups" else "security"
            for name in names:
                if (scope, name) in seen_names:
                    c.fail(where, f"name {name!r} maps to more than one id")
                seen_names.add((scope, name))
        ids = [row.get(id_key) for row in rows if isinstance(row, dict)]
        if ids != sorted(ids):
            c.fail(f"registry.{collection}", f"must be ordered by {id_key}")
    c.raise_if_failed()
