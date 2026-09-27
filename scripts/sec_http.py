"""Shared SEC EDGAR access: one User-Agent, one request pace, one retry policy.

Standard library only.  SEC's fair-access policy asks every client to
declare a contact in its User-Agent and to stay under 10 requests per
second across the whole process; SEC blocks clients that do not.  Every
scheduled script that talks to sec.gov goes through ``get`` so those rules
live in one place instead of being re-implemented (slightly differently)
in each fetcher.
"""

from __future__ import annotations

import http.client
import json
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable

DEFAULT_USER_AGENT = "Sec_kb Research gibon1127@gmail.com"
MIN_INTERVAL = 0.11  # seconds between request starts: < 10 requests/second
RETRY_HTTP_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_RETRY_AFTER = 60.0

_pace_lock = threading.Lock()
_last_request = 0.0


def user_agent() -> str:
    """``SEC_USER_AGENT`` when set (workflows pass the repository variable)."""
    return os.environ.get("SEC_USER_AGENT") or DEFAULT_USER_AGENT


def _wait_for_turn() -> None:
    global _last_request
    with _pace_lock:
        delay = _last_request + MIN_INTERVAL - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        _last_request = time.monotonic()


def _retry_delay(error: Exception, attempt: int, backoff: float) -> float | None:
    """Seconds to wait before retrying, or None when retrying cannot help."""
    if isinstance(error, urllib.error.HTTPError):
        if error.code not in RETRY_HTTP_STATUS:
            return None  # 403/404 and friends will not change on a retry
        retry_after = (error.headers or {}).get("Retry-After", "")
        if retry_after.strip().isdigit():
            return min(float(retry_after), MAX_RETRY_AFTER)
    return backoff * (attempt + 1)


def request(url: str, read: Callable[[Any], Any], *, accept: str | None = None,
            headers: dict[str, str] | None = None, timeout: float = 45,
            attempts: int = 3, backoff: float = 1.5) -> Any:
    """Paced, retried GET; ``read(response)`` parses the body inside the retry.

    Transient failures (network errors, timeouts, truncated or unparsable
    bodies, HTTP 429/5xx) are retried; the last error is re-raised so callers
    keep their existing fail-closed handling.
    """
    all_headers = {"User-Agent": user_agent()}
    if accept:
        all_headers["Accept"] = accept
    all_headers.update(headers or {})
    req = urllib.request.Request(url, headers=all_headers)
    for attempt in range(attempts):
        _wait_for_turn()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return read(response)
        except (urllib.error.URLError, TimeoutError, ConnectionError,
                http.client.IncompleteRead, json.JSONDecodeError) as error:
            delay = _retry_delay(error, attempt, backoff)
            if delay is None or attempt + 1 == attempts:
                raise
            time.sleep(delay)
    raise ValueError("attempts must be at least 1")


def get(url: str, *, max_bytes: int | None = None, **options: Any) -> bytes:
    """Response body; with ``max_bytes`` only that prefix is requested and read."""
    if max_bytes:
        options["headers"] = {**options.get("headers", {}), "Range": f"bytes=0-{max_bytes - 1}"}
        return request(url, lambda response: response.read(max_bytes), **options)
    return request(url, lambda response: response.read(), **options)


def get_text(url: str, errors: str = "ignore", **options: Any) -> str:
    return get(url, **options).decode("utf-8", errors=errors)


def get_json(url: str, **options: Any) -> Any:
    options.setdefault("accept", "application/json")
    return request(url, lambda response: json.loads(response.read().decode("utf-8")), **options)
