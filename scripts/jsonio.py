"""Shared JSON reading and safe publishing for the data pipeline scripts.

Standard library only.  Two guarantees every generator should have:

* never write NaN/Infinity, which browsers reject as invalid JSON;
* never leave a half-written or unvalidated file: every payload of a batch
  is validated and serialised first, then staged beside its target and
  swapped in with ``os.replace``.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

Validator = Callable[[Any], None]


def load_json(path: Path, default: Any = None) -> Any:
    """Parsed JSON, or ``default`` when the file does not exist."""
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text())


def dumps(payload: Any, indent: int | None = None) -> str:
    """Serialise with a trailing newline; compact when ``indent`` is None."""
    options = {"indent": indent} if indent is not None else {"separators": (",", ":")}
    return json.dumps(payload, ensure_ascii=False, allow_nan=False, **options) + "\n"


def replace_texts(texts: dict[Path, str]) -> None:
    """Stage every text beside its target, then swap them all in."""
    staged: list[tuple[str, Path]] = []
    try:
        for path, text in texts.items():
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                "w", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
                delete=False, encoding="utf-8",
            )
            with handle:
                handle.write(text)
            staged.append((handle.name, path))
        for temporary, path in staged:
            os.replace(temporary, path)
    finally:
        for temporary, _ in staged:
            if os.path.exists(temporary):
                os.unlink(temporary)


def write_json(path: Path, payload: Any, indent: int | None = 1,
               validate: Validator | None = None) -> None:
    """Validate, serialise and atomically replace one JSON file."""
    if validate is not None:
        validate(payload)
    replace_texts({Path(path): dumps(payload, indent)})


def require_companies(minimum: int = 1) -> Validator:
    """Validator for the per-company outputs (fundamentals, health, valuation)."""
    def validate(payload: Any) -> None:
        if not isinstance(payload, dict) or not payload.get("generated_at"):
            raise ValueError("payload must be an object with generated_at")
        companies = payload.get("companies")
        if not isinstance(companies, dict) or len(companies) < minimum:
            count = len(companies) if isinstance(companies, dict) else 0
            raise ValueError(f"expected at least {minimum} companies, got {count}; refusing to publish")
        bad = sorted(ticker for ticker, row in companies.items() if not isinstance(row, dict))
        if bad:
            raise ValueError(f"company rows must be objects: {bad}")
    return validate
