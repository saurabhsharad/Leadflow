"""Demo seed data: the plan (pure, fixed clocks) and the writes (test database only).

Tests named test_db_* use the PostgreSQL test database through the db_engine
fixture; the rest need no database (`pytest tests/test_seed.py -k "not db"`).
"""

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import build_engine
from app.followups import FollowUpState, classify, today_bounds
from app.models import Discussion, Lead, LeadStatus
from app.schemas import DiscussionCreate, LeadCreate
from app.services import leads as services
from scripts import seed
from scripts.seed import (
    EXIT_DATABASE_ERROR,
    EXIT_OK,
    EXIT_REFUSED,
    LeadSeed,
    SeedError,
    build_demo_plan,
    describe_target,
    follow_up_times,
    reset_and_seed,
    seed_if_empty,
)

IST = ZoneInfo("Asia/Kolkata")
NEW_YORK = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)  # 20:30 IST, the specification's clock

# A URL that must never appear in output: its credentials are the point of the check.
SECRET_URL = "postgresql+psycopg://alice:s3cr3t-pw@db.example:6543/crm_demo"


def ist(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=IST)


def by_name(plan: list[LeadSeed]) -> dict[str, LeadSeed]:
    return {lead.name: lead for lead in plan}


def assert_valid_plan(plan: list[LeadSeed], now: datetime) -> None:
    """Invariants that must hold whatever the clock says."""
    assert len(plan) >= 6
    assert {lead.status for lead in plan} == set(LeadStatus)
    assert any(not lead.discussions for lead in plan)
    for lead in plan:
        # Exactly what the API would accept (lengths, phone pattern, follow-up years).
        accepted = LeadCreate(name=lead.name, company=lead.company, phone=lead.phone)
        assert (accepted.name, accepted.company, accepted.phone) == (
            lead.name,
            lead.company,
            lead.phone,
        )
        assert lead.phone is None or re.fullmatch(r"555-01\d\d", lead.phone)
        assert lead.created_at.utcoffset() == timedelta(0)
        assert lead.created_at <= now
        assert lead.updated_at >= lead.created_at
        if lead.discussions:
            assert 2 <= len(lead.discussions) <= 4

        previous = lead.created_at
        for discussion in lead.discussions:
            DiscussionCreate(note=discussion.note, follow_up_at=discussion.follow_up_at)
            assert previous < discussion.created_at <= now  # oldest first, after the lead
            previous = discussion.created_at
            if discussion.follow_up_at is not None:
                assert discussion.follow_up_at > discussion.created_at

        # Current vs history: the lead's follow-up is the newest one its notes
        # scheduled (as POST /discussions would leave it) or was cleared since.
        scheduled = [d.follow_up_at for d in lead.discussions if d.follow_up_at is not None]
        if lead.next_follow_up_at is not None:
            assert scheduled and lead.next_follow_up_at == scheduled[-1]


# --- The plan ----------------------------------------------------------------------------


def test_follow_up_times_at_the_specification_clock() -> None:
    times = follow_up_times(NOW, IST)

    assert times.later_today == ist(13, 22, 15)  # midway between 20:30 and midnight
    assert times.earlier_today == ist(13, 10, 15)  # midway between midnight and 20:30
    assert times.previous_day == ist(12, 11)
    assert times.tomorrow == ist(14, 11)
    assert times.in_three_days == ist(16, 15)
    assert all(t.utcoffset() == timedelta(0) for t in vars(times).values())


def test_plan_covers_every_follow_up_state() -> None:
    plan = build_demo_plan(NOW, IST)
    leads = by_name(plan)
    today_start, tomorrow_start = today_bounds(NOW, IST)

    def state(name: str) -> FollowUpState:
        return classify(leads[name].next_follow_up_at, NOW, IST)

    assert state("Sarah Whitfield") == FollowUpState(due_today=True, overdue=False)
    assert state("Marcus Oyelaran") == FollowUpState(due_today=True, overdue=True)
    assert state("Rahul Menon") == FollowUpState(due_today=False, overdue=True)
    assert leads["Rahul Menon"].next_follow_up_at < today_start  # an earlier day
    assert state("Daniel Ferreira") == FollowUpState(due_today=False, overdue=False)
    daniel = leads["Daniel Ferreira"].next_follow_up_at
    assert daniel is not None and daniel.astimezone(IST).date() == tomorrow_start.date()
    assert state("Priya Nair") == FollowUpState(due_today=False, overdue=False)
    for name in ("Aisha Karim", "Tomás Lindqvist", "Elena Vasquez"):
        assert leads[name].next_follow_up_at is None


def test_plan_shape_and_invariants() -> None:
    plan = build_demo_plan(NOW, IST)
    assert_valid_plan(plan, NOW)

    assert len(plan) == 8
    assert [len(lead.discussions) for lead in plan] == [3, 2, 3, 2, 0, 4, 2, 2]
    assert not by_name(plan)["Aisha Karim"].discussions
    # A cleared lead keeps the follow-ups its notes scheduled, as history.
    tomas = by_name(plan)["Tomás Lindqvist"]
    assert tomas.next_follow_up_at is None
    assert any(d.follow_up_at is not None for d in tomas.discussions)


def test_plan_supports_the_filter_and_search_demo() -> None:
    # Playwright spec 4 filters Qualified and searches "rah": one match, and
    # another "rah" lead that only the status filter removes.
    plan = build_demo_plan(NOW, IST)
    rah = [lead for lead in plan if "rah" in lead.name.lower()]
    assert [lead.name for lead in rah if lead.status is LeadStatus.QUALIFIED] == ["Sarah Whitfield"]
    assert any(lead.status is not LeadStatus.QUALIFIED for lead in rah)


def test_plan_is_deterministic_for_a_given_clock() -> None:
    assert build_demo_plan(NOW, IST) == build_demo_plan(NOW, IST)


def test_now_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        follow_up_times(datetime(2026, 10, 13, 20, 30), IST)


# --- Around midnight ----------------------------------------------------------------------


def test_just_before_midnight_later_today_moves_to_tomorrow_morning() -> None:
    now = ist(13, 23, 55)
    times = follow_up_times(now, IST)

    assert times.later_today == ist(14, 10)
    assert classify(times.later_today, now, IST) == FollowUpState(due_today=False, overdue=False)
    assert classify(times.earlier_today, now, IST) == FollowUpState(due_today=True, overdue=True)


def test_ten_minutes_before_midnight_still_uses_today() -> None:
    now = ist(13, 23, 50)  # exactly the margin
    assert follow_up_times(now, IST).later_today == ist(13, 23, 55)


def test_just_after_midnight_earlier_today_moves_to_yesterday_afternoon() -> None:
    now = ist(14, 0, 5)
    times = follow_up_times(now, IST)

    assert times.earlier_today == ist(13, 16)
    assert classify(times.earlier_today, now, IST) == FollowUpState(due_today=False, overdue=True)
    assert classify(times.later_today, now, IST) == FollowUpState(due_today=True, overdue=False)


def test_exactly_midnight() -> None:
    now = ist(14, 0)
    times = follow_up_times(now, IST)

    assert times.earlier_today == ist(13, 16)
    assert times.later_today == ist(14, 12)


@pytest.mark.parametrize(
    "minute",
    sorted({*range(0, 24 * 60, 15), 1, 9, 10, 11, 1429, 1430, 1431, 1439}),
)
def test_every_time_of_day_gives_a_valid_plan(minute: int) -> None:
    now = (ist(13, 0) + timedelta(minutes=minute)).astimezone(UTC)
    plan = build_demo_plan(now, IST)
    assert_valid_plan(plan, now)

    leads = by_name(plan)
    later = classify(leads["Sarah Whitfield"].next_follow_up_at, now, IST)
    earlier = classify(leads["Marcus Oyelaran"].next_follow_up_at, now, IST)
    # Due later today, or (near midnight) tomorrow morning; never overdue.
    assert not later.overdue
    # Overdue earlier today, or (just after midnight) overdue from yesterday.
    assert earlier.overdue
    assert classify(leads["Rahul Menon"].next_follow_up_at, now, IST) == FollowUpState(
        due_today=False, overdue=True
    )


# --- Daylight-saving changes (Asia/Kolkata has none) ----------------------------------------


@pytest.mark.parametrize(
    "local_now",
    [
        datetime(2026, 3, 8, 12, 0, tzinfo=NEW_YORK),  # 23-hour day
        datetime(2026, 3, 8, 4, 0, tzinfo=NEW_YORK),  # just after the skipped hour
        datetime(2026, 11, 1, 12, 0, tzinfo=NEW_YORK),  # 25-hour day
        datetime(2026, 11, 1, 1, 30, fold=1, tzinfo=NEW_YORK),  # the repeated hour
    ],
)
def test_dst_days_keep_order_and_real_elapsed_midpoints(local_now: datetime) -> None:
    now = local_now.astimezone(UTC)
    today_start, tomorrow_start = (b.astimezone(UTC) for b in today_bounds(now, NEW_YORK))
    times = follow_up_times(now, NEW_YORK)

    assert today_start <= times.earlier_today < now < times.later_today < tomorrow_start
    # Midpoints of real elapsed time, not of wall-clock hours.
    assert abs((times.later_today - now) - (tomorrow_start - now) / 2) < timedelta(minutes=1)
    assert abs((times.earlier_today - today_start) - (now - today_start) / 2) < timedelta(minutes=1)
    # Fixed times keep their wall-clock hour on the neighbouring days.
    assert times.previous_day.astimezone(NEW_YORK).hour == 11
    assert times.tomorrow.astimezone(NEW_YORK).hour == 11
    assert times.in_three_days.astimezone(NEW_YORK).hour == 15
    assert_valid_plan(build_demo_plan(now, NEW_YORK), now)


# --- Command line, without a database ----------------------------------------------------------


def no_engine(url: str) -> Engine:
    raise AssertionError("the command must not create an engine")


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Explicit settings, so a developer's shell or .env cannot change the outcome."""
    monkeypatch.setenv("DATABASE_URL", SECRET_URL)
    monkeypatch.setenv("APP_TIMEZONE", "Asia/Kolkata")
    monkeypatch.setenv("SEED_DEMO_DATA", "false")
    return monkeypatch


def test_describe_target_never_shows_credentials() -> None:
    assert describe_target(SECRET_URL) == "db.example:6543/crm_demo"


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--reset"], "--yes"),
        (["--reset", "--yes"], "--confirm-database"),
        (["--reset", "--confirm-database", "crm_demo"], "--yes"),
        (["--reset", "--yes", "--confirm-database", "leadflow"], "does not match"),
        (["--yes"], "only apply to --reset"),
        (["--confirm-database", "crm_demo"], "only apply to --reset"),
    ],
)
def test_reset_needs_every_confirmation(
    cli_env: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    message: str,
) -> None:
    assert seed.main(argv, engine_factory=no_engine, now=NOW) == EXIT_REFUSED
    out, err = capsys.readouterr()
    assert message in err
    assert "s3cr3t" not in out + err and "alice" not in out + err


def test_reset_refuses_a_database_url_that_is_not_in_the_environment(
    cli_env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Even if .env provides one, a reset needs DATABASE_URL in the process environment.
    cli_env.delenv("DATABASE_URL")
    argv = ["--reset", "--yes", "--confirm-database", "crm_demo"]

    assert seed.main(argv, engine_factory=no_engine, now=NOW) == EXIT_REFUSED
    assert "set explicitly in the environment" in capsys.readouterr().err


def test_reset_refuses_when_the_configured_url_is_not_the_confirmed_one(
    cli_env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The exported DATABASE_URL names crm_demo, but settings resolve another URL
    # (as a differently spelled variable could make them do).
    other = "postgresql+psycopg://bob:other-pw@db.example:6543/crm_demo"
    cli_env.setattr(
        seed, "_load_settings", lambda: Settings(database_url=other, app_timezone="Asia/Kolkata")
    )
    argv = ["--reset", "--yes", "--confirm-database", "crm_demo"]

    assert seed.main(argv, engine_factory=no_engine, now=NOW) == EXIT_REFUSED
    out, err = capsys.readouterr()
    assert "differs from the exported DATABASE_URL" in err
    for secret in ("s3cr3t", "alice", "other-pw", "bob"):
        assert secret not in out + err


def test_auto_does_nothing_unless_enabled(
    cli_env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert seed.main(["--auto"], engine_factory=no_engine, now=NOW) == EXIT_OK
    assert "not enabled" in capsys.readouterr().out


def test_auto_and_reset_are_mutually_exclusive(cli_env: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit):
        seed.main(["--auto", "--reset", "--yes"], engine_factory=no_engine, now=NOW)


def test_database_errors_do_not_leak_connection_details(
    cli_env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Nothing listens on port 1, so connecting fails immediately; no data is touched.
    cli_env.setenv("DATABASE_URL", "postgresql+psycopg://alice:s3cr3t-pw@127.0.0.1:1/crm_demo")

    assert seed.main([], engine_factory=build_engine, now=NOW) == EXIT_DATABASE_ERROR
    out, err = capsys.readouterr()
    assert "target database 127.0.0.1:1/crm_demo" in out
    assert "database error (OperationalError)" in err
    assert "s3cr3t" not in out + err and "alice" not in out + err


# --- Writes: the PostgreSQL test database only (db_engine refuses anything else) ----------------


def count(session: Session, model: type[Lead] | type[Discussion]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def snapshot(session: Session) -> list[tuple[object, ...]]:
    """Every row's key values, read in a transaction that is ended before returning.

    An open read transaction keeps ACCESS SHARE locks, which would make the
    TRUNCATE in reset_and_seed (another connection) wait forever.
    """
    session.expire_all()
    leads = session.execute(
        select(Lead.id, Lead.name, Lead.status, Lead.next_follow_up_at, Lead.updated_at).order_by(
            Lead.id
        )
    ).all()
    discussions = session.execute(
        select(Discussion.id, Discussion.lead_id, Discussion.note, Discussion.created_at).order_by(
            Discussion.id
        )
    ).all()
    session.rollback()  # read-only: ends the transaction and releases its locks
    return [*leads, *discussions]


def add_existing_lead(session: Session) -> int:
    lead = Lead(name="Existing Customer", status=LeadStatus.WON)
    session.add(lead)
    session.flush()
    # Read the id before committing: afterwards the object is expired, and
    # loading it again would open a new transaction that holds locks.
    lead_id = lead.id
    session.commit()
    return lead_id


def test_db_seed_inserts_the_plan_into_an_empty_database(
    db_session: Session, db_engine: Engine
) -> None:
    assert seed_if_empty(db_engine, NOW, IST) is True

    plan = build_demo_plan(NOW, IST)
    summaries = {s.name: s for s in services.list_leads(db_session, NOW, IST)}
    assert summaries.keys() == by_name(plan).keys()
    assert count(db_session, Discussion) == sum(len(lead.discussions) for lead in plan)
    for lead in plan:
        summary = summaries[lead.name]
        assert summary.status == lead.status
        assert summary.next_follow_up_at == lead.next_follow_up_at
        state = classify(lead.next_follow_up_at, NOW, IST)
        assert (summary.follow_up_due_today, summary.follow_up_overdue) == state
        assert summary.created_at == lead.created_at

    # History survives next to the current follow-up, newest first.
    tomas = services.get_lead(db_session, summaries["Tomás Lindqvist"].id, NOW, IST)
    assert tomas.next_follow_up_at is None
    assert [d.note for d in tomas.discussions] == [
        d.note for d in reversed(by_name(plan)["Tomás Lindqvist"].discussions)
    ]
    assert any(d.follow_up_at is not None for d in tomas.discussions)


def test_db_a_second_run_changes_nothing(db_session: Session, db_engine: Engine) -> None:
    assert seed_if_empty(db_engine, NOW, IST) is True
    before = snapshot(db_session)

    assert seed_if_empty(db_engine, NOW + timedelta(days=1), IST) is False
    assert snapshot(db_session) == before


def test_db_existing_data_is_never_touched(db_session: Session, db_engine: Engine) -> None:
    lead_id = add_existing_lead(db_session)
    before = snapshot(db_session)

    assert seed_if_empty(db_engine, NOW, IST) is False
    assert snapshot(db_session) == before
    assert [lead_id] == list(db_session.scalars(select(Lead.id)))


def test_db_reset_replaces_existing_rows(db_session: Session, db_engine: Engine) -> None:
    add_existing_lead(db_session)

    reset_and_seed(db_engine, NOW, IST)

    db_session.expire_all()
    names = list(db_session.scalars(select(Lead.name).order_by(Lead.id)))
    assert names == [lead.name for lead in build_demo_plan(NOW, IST)]
    assert min(db_session.scalars(select(Lead.id))) == 1  # identities restarted


def test_db_a_failed_reset_rolls_back(
    db_session: Session, db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_existing_lead(db_session)
    before = snapshot(db_session)
    real_insert = seed._insert

    def insert_then_fail(session: Session, plan: list[LeadSeed]) -> None:
        real_insert(session, plan)  # truncated and inserted, not yet committed
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(seed, "_insert", insert_then_fail)
    with pytest.raises(RuntimeError):
        reset_and_seed(db_engine, NOW, IST)

    assert snapshot(db_session) == before


def test_db_auto_inserts_only_when_enabled_and_empty(
    db_session: Session, db_engine: Engine, cli_env: pytest.MonkeyPatch
) -> None:
    def factory(url: str) -> Engine:
        return db_engine  # whatever the configured URL, write only to the test database

    assert seed.main(["--auto"], engine_factory=factory, now=NOW) == EXIT_OK
    assert count(db_session, Lead) == 0

    cli_env.setenv("SEED_DEMO_DATA", "true")
    assert seed.main(["--auto"], engine_factory=factory, now=NOW) == EXIT_OK
    assert count(db_session, Lead) == 8
    before = snapshot(db_session)

    assert seed.main(["--auto"], engine_factory=factory, now=NOW) == EXIT_OK
    assert snapshot(db_session) == before


def test_db_confirmed_reset_through_the_command(
    db_session: Session, db_engine: Engine, cli_env: pytest.MonkeyPatch
) -> None:
    add_existing_lead(db_session)
    url = db_engine.url
    assert url.database and url.database.endswith("_test")
    cli_env.setenv("DATABASE_URL", url.render_as_string(hide_password=True))

    argv = ["--reset", "--yes", "--confirm-database", url.database]
    assert seed.main(argv, engine_factory=lambda _: db_engine, now=NOW) == EXIT_OK
    assert count(db_session, Lead) == 8


def test_db_an_unmigrated_database_is_refused(
    db_engine: Engine, make_alembic_config: Callable[[Connection], Config]
) -> None:
    with db_engine.begin() as connection:
        command.downgrade(make_alembic_config(connection), "base")
    try:
        with pytest.raises(SeedError, match="alembic upgrade head"):
            seed_if_empty(db_engine, NOW, IST)
        with pytest.raises(SeedError, match="alembic upgrade head"):
            reset_and_seed(db_engine, NOW, IST)
    finally:
        with db_engine.begin() as connection:
            command.upgrade(make_alembic_config(connection), "head")
