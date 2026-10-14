"""Follow-up classification and dashboard ordering. Pure: fixed clock, no database."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.clock import get_now
from app.followups import (
    ALL_LEADS,
    OVERDUE_EARLIER,
    TODAY,
    FollowUpState,
    classify,
    dashboard_sort_key,
    today_bounds,
)

IST = ZoneInfo("Asia/Kolkata")
# The specification's reference clock: 13 Oct 2026, 20:30 IST = 15:00 UTC.
NOW = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)


def ist(day: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, second, tzinfo=IST)


def utc(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC)


# --- classify: the specification's boundary table -----------------------------


@pytest.mark.parametrize(
    ("follow_up_at", "due_today", "overdue"),
    [
        pytest.param(None, False, False, id="no follow-up"),
        pytest.param(ist(13, 21), True, False, id="later today"),
        pytest.param(ist(13, 14), True, True, id="earlier today: due and overdue"),
        pytest.param(ist(13, 23, 59), True, False, id="last minute of today"),
        pytest.param(ist(13, 23, 59, 59), True, False, id="last second of today"),
        pytest.param(ist(14, 0), False, False, id="start of tomorrow (half-open)"),
        pytest.param(utc(13, 19), False, False, id="13 Oct UTC is 14 Oct IST: upcoming"),
        pytest.param(utc(12, 20), True, True, id="12 Oct UTC is 13 Oct IST: today"),
        pytest.param(ist(12, 16), False, True, id="yesterday"),
        pytest.param(ist(13, 0), True, True, id="local midnight starting today"),
        pytest.param(ist(12, 23, 59, 59), False, True, id="one second before local midnight"),
        pytest.param(ist(20, 10), False, False, id="future day"),
        pytest.param(NOW, True, False, id="exactly now: not overdue"),
    ],
)
def test_classify_matches_specification(
    follow_up_at: datetime | None, due_today: bool, overdue: bool
) -> None:
    assert classify(follow_up_at, NOW, IST) == FollowUpState(due_today, overdue)


def test_exactly_now_becomes_overdue_one_second_later() -> None:
    assert classify(NOW, NOW, IST).overdue is False
    assert classify(NOW, NOW + timedelta(seconds=1), IST).overdue is True


def test_now_given_in_any_offset_gives_the_same_result() -> None:
    # The injected clock may be UTC or local: only the instant matters.
    for now in (NOW, NOW.astimezone(IST), NOW.astimezone(ZoneInfo("America/New_York"))):
        assert classify(ist(13, 14), now, IST) == FollowUpState(True, True)


def test_today_uses_app_timezone_not_utc_date() -> None:
    # 23:00 UTC on 12 Oct is already 13 Oct (04:30) in IST.
    now = utc(12, 23)
    assert classify(utc(12, 18, 29), now, IST).due_today is False  # 12 Oct 23:59 IST
    assert classify(utc(12, 18, 30), now, IST).due_today is True  # 13 Oct 00:00 IST
    # The same instants in a UTC-based app fall on 12 Oct, today there.
    assert classify(utc(12, 18, 29), now, UTC).due_today is True


def test_today_bounds_are_local_midnights() -> None:
    start, end = today_bounds(NOW, IST)
    assert (start, end) == (ist(13, 0), ist(14, 0))
    assert start.astimezone(UTC) == utc(12, 18, 30)


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValueError, match="now must be timezone-aware"):
        classify(ist(13, 14), datetime(2026, 10, 13, 20, 30), IST)
    with pytest.raises(ValueError, match="follow_up_at must be timezone-aware"):
        classify(datetime(2026, 10, 13, 14, 0), NOW, IST)


def test_get_now_is_utc_aware() -> None:
    now = get_now()
    assert now.tzinfo is UTC


# --- dashboard ordering ------------------------------------------------------------

DEFAULT_CREATED = utc(1, 0)


def key(
    lead_id: int,
    follow_up_at: datetime | None = None,
    last_discussion_at: datetime | None = None,
    created_at: datetime = DEFAULT_CREATED,
) -> tuple[int, ...]:
    return dashboard_sort_key(
        follow_up_at=follow_up_at,
        last_discussion_at=last_discussion_at,
        created_at=created_at,
        lead_id=lead_id,
        now=NOW,
        tz=IST,
    )


def ordered(*keys: tuple[int, ...]) -> list[int]:
    """Lead ids in sorted order (the id is the last element of every key)."""
    return [-k[-1] for k in sorted(keys)]


def test_each_follow_up_state_lands_in_its_group() -> None:
    assert key(1, ist(12, 16))[0] == OVERDUE_EARLIER
    assert key(1, ist(13, 0))[0] == TODAY
    assert key(1, ist(13, 14))[0] == TODAY  # overdue today stays in Today
    assert key(1, ist(13, 23, 59, 59))[0] == TODAY
    assert key(1, ist(14, 0))[0] == ALL_LEADS  # upcoming
    assert key(1, None)[0] == ALL_LEADS


def test_groups_are_ordered_overdue_earlier_then_today_then_all() -> None:
    assert ordered(
        key(1, None, last_discussion_at=utc(13, 14)),  # all leads, recent note
        key(2, ist(13, 22)),  # today
        key(3, ist(11, 9)),  # earlier day
        key(4, ist(15, 9)),  # upcoming -> all leads, no discussions
    ) == [3, 2, 1, 4]


def test_overdue_earlier_group_is_oldest_first() -> None:
    assert ordered(key(1, ist(12, 16)), key(2, ist(10, 9)), key(3, ist(12, 9))) == [2, 3, 1]


def test_today_group_is_earliest_time_first() -> None:
    assert ordered(key(1, ist(13, 22)), key(2, ist(13, 9)), key(3, ist(13, 14))) == [2, 3, 1]


def test_all_leads_latest_discussion_first_then_none_by_newest_created() -> None:
    assert ordered(
        key(1, last_discussion_at=utc(10, 9)),
        key(2, created_at=utc(5, 0)),  # no discussions, older
        key(3, last_discussion_at=utc(12, 9)),
        key(4, created_at=utc(8, 0)),  # no discussions, newer
    ) == [3, 1, 4, 2]


def test_ties_break_on_newest_created_then_highest_id() -> None:
    same = {"follow_up_at": ist(13, 22)}
    assert ordered(
        key(1, **same, created_at=utc(2, 0)),
        key(2, **same, created_at=utc(3, 0)),
        key(3, **same, created_at=utc(3, 0)),
    ) == [3, 2, 1]
    tied_note = {"last_discussion_at": utc(12, 9), "created_at": utc(1, 0)}
    assert ordered(key(5, **tied_note), key(9, **tied_note), key(7, **tied_note)) == [9, 7, 5]


def test_microsecond_differences_are_ordered_exactly() -> None:
    a = utc(12, 9)
    b = a + timedelta(microseconds=1)
    assert ordered(key(1, last_discussion_at=a), key(2, last_discussion_at=b)) == [2, 1]
