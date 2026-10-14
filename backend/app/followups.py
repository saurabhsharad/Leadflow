"""Follow-up classification and dashboard ordering (see the specification, section 6).

Pure functions of (follow-up, now, timezone): no database, no system clock.
Every argument is a timezone-aware instant; "today" is the calendar day of
`now` in the application timezone, never the server's local timezone.
"""

from datetime import UTC, datetime, time, timedelta, tzinfo
from typing import NamedTuple

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# Dashboard groups, in display order.
OVERDUE_EARLIER = 0  # follow-up before today: oldest first
TODAY = 1  # follow-up today (possibly already overdue): earliest time first
ALL_LEADS = 2  # everything else: latest discussion first, none last


class FollowUpState(NamedTuple):
    due_today: bool
    overdue: bool


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def today_bounds(now: datetime, tz: tzinfo) -> tuple[datetime, datetime]:
    """[start of today, start of tomorrow) in `tz`, as aware datetimes."""
    _require_aware(now, "now")
    local_date = now.astimezone(tz).date()
    today_start = datetime.combine(local_date, time.min, tzinfo=tz)
    tomorrow_start = datetime.combine(local_date + timedelta(days=1), time.min, tzinfo=tz)
    return today_start, tomorrow_start


def classify(follow_up_at: datetime | None, now: datetime, tz: tzinfo) -> FollowUpState:
    """Due today: today_start <= f < tomorrow_start (half-open). Overdue: f < now (strict).

    Both can be true: a 3 PM follow-up viewed at 5 PM is due today and overdue.
    """
    if follow_up_at is None:
        return FollowUpState(due_today=False, overdue=False)
    _require_aware(follow_up_at, "follow_up_at")
    today_start, tomorrow_start = today_bounds(now, tz)
    return FollowUpState(
        due_today=today_start <= follow_up_at < tomorrow_start,
        overdue=follow_up_at < now,
    )


def _micros(value: datetime) -> int:
    """Exact integer microseconds since the epoch (floats could tie or misorder)."""
    _require_aware(value, "timestamp")
    return (value - _EPOCH) // timedelta(microseconds=1)


def dashboard_sort_key(
    *,
    follow_up_at: datetime | None,
    last_discussion_at: datetime | None,
    created_at: datetime,
    lead_id: int,
    now: datetime,
    tz: tzinfo,
) -> tuple[int, ...]:
    """Sort key placing each lead in exactly one dashboard group, in group order.

    1. Overdue from earlier days (f < today_start): oldest follow-up first.
    2. Today's follow-ups: earliest follow-up first.
    3. All other leads: latest discussion first, leads without discussions
       last, then newest created first.
    Remaining ties: newest created first, then highest id (deterministic).
    """
    tie_breaker = (-_micros(created_at), -lead_id)
    if follow_up_at is not None:
        today_start, tomorrow_start = today_bounds(now, tz)
        if follow_up_at < today_start:
            return (OVERDUE_EARLIER, _micros(follow_up_at), *tie_breaker)
        if follow_up_at < tomorrow_start:
            return (TODAY, _micros(follow_up_at), *tie_breaker)
    if last_discussion_at is None:
        return (ALL_LEADS, 1, 0, *tie_breaker)
    return (ALL_LEADS, 0, -_micros(last_discussion_at), *tie_breaker)
