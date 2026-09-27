"""NYSE session calendar shared by the market-data builders and monitors.

Standard library only, so freshness monitoring runs without pandas/yfinance.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


NEW_YORK = ZoneInfo("America/New_York")
# Give Yahoo two hours after the regular 16:00 ET close before declaring the
# current session missing.  The scheduled job normally runs later than this.
MARKET_DATA_CUTOFF = time(18, 0)


def observed_fixed_holiday(value: date) -> date:
    if value.weekday() == 5:
        return value - timedelta(days=1)
    if value.weekday() == 6:
        return value + timedelta(days=1)
    return value


def nth_weekday(year: int, month: int, weekday: int, number: int) -> date:
    value = date(year, month, 1)
    value += timedelta(days=(weekday - value.weekday()) % 7)
    return value + timedelta(weeks=number - 1)


def last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        value = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        value = date(year, month + 1, 1) - timedelta(days=1)
    return value - timedelta(days=(value.weekday() - weekday) % 7)


def easter_sunday(year: int) -> date:
    """Return Gregorian Easter using the anonymous computus algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    length = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * length) // 451
    month = (h + length - 7 * m + 114) // 31
    day = (h + length - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def nyse_holidays(year: int) -> set[date]:
    """Regular full-day NYSE holidays; exceptional closures stay explicit."""
    holidays = {
        observed_fixed_holiday(date(year, 1, 1)),
        nth_weekday(year, 1, 0, 3),   # Martin Luther King Jr. Day
        nth_weekday(year, 2, 0, 3),   # Washington's Birthday
        easter_sunday(year) - timedelta(days=2),
        last_weekday(year, 5, 0),     # Memorial Day
        observed_fixed_holiday(date(year, 7, 4)),
        nth_weekday(year, 9, 0, 1),   # Labor Day
        nth_weekday(year, 11, 3, 4),  # Thanksgiving
        observed_fixed_holiday(date(year, 12, 25)),
    }
    if year >= 2022:
        holidays.add(observed_fixed_holiday(date(year, 6, 19)))
    return holidays


# Add one-off national days of mourning or emergency closures here after an
# official exchange announcement.  Keeping the override visible is safer than
# silently treating every federal holiday as an equity-market closure.
EXTRA_MARKET_CLOSURES: set[date] = set()


def is_market_session(value: date) -> bool:
    holidays = set().union(*(
        nyse_holidays(year) for year in range(value.year - 1, value.year + 2)
    ))
    return value.weekday() < 5 and value not in holidays and value not in EXTRA_MARKET_CLOSURES


def previous_market_session(value: date) -> date:
    candidate = value
    while not is_market_session(candidate):
        candidate -= timedelta(days=1)
    return candidate


def expected_latest_market_session(now: datetime | None = None) -> date:
    """Latest NYSE session whose regular close should be available from Yahoo."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    market_now = current.astimezone(NEW_YORK)
    candidate = market_now.date()
    if market_now.timetz().replace(tzinfo=None) < MARKET_DATA_CUTOFF:
        candidate -= timedelta(days=1)
    return previous_market_session(candidate)


def market_session_lag(actual: date, expected: date) -> int:
    if actual >= expected:
        return 0
    lag = 0
    candidate = actual + timedelta(days=1)
    while candidate <= expected:
        if is_market_session(candidate):
            lag += 1
        candidate += timedelta(days=1)
    return lag
