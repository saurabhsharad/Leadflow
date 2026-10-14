"""Demo data for LeadFlow: eight fictional leads with times relative to now.

Run from backend/:

    python -m scripts.seed           # insert, but only into an empty database
    python -m scripts.seed --auto    # the same, only when SEED_DEMO_DATA=true (container start)
    DATABASE_URL=... python -m scripts.seed --reset --yes --confirm-database NAME

Normal and --auto runs never change existing rows: they insert only when both
tables are empty. --reset replaces every lead and discussion, so it needs
--yes, the target database's name, and DATABASE_URL set explicitly in the
environment (a value in .env is not enough). Rerun it on a later day to make
"today" in the demo data current again.

Follow-up states are not decided here: the API classifies them on every read
(app.followups). This only picks instants that land in each state.
"""

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from pydantic import ValidationError
from sqlalchemy import Connection, Engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.clock import get_now
from app.config import Settings
from app.db import build_engine
from app.followups import today_bounds
from app.models import Discussion, Lead, LeadStatus

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Within this long of midnight a "later today" or "earlier today" instant would
# be minutes away from the day boundary, so the specification moves it to a
# fixed time on the neighbouring day instead (section 13).
MIDNIGHT_MARGIN = timedelta(minutes=10)

EXIT_OK = 0
EXIT_DATABASE_ERROR = 1
EXIT_REFUSED = 2


class SeedError(Exception):
    """A refusal or precondition failure, reported without a traceback."""


# --- The plan: pure data, no database ----------------------------------------------


@dataclass(frozen=True)
class DiscussionSeed:
    note: str
    created_at: datetime
    # The follow-up this note scheduled (history), not necessarily the lead's current one.
    follow_up_at: datetime | None = None


@dataclass(frozen=True)
class LeadSeed:
    name: str
    company: str | None
    phone: str | None
    status: LeadStatus
    created_at: datetime
    # The lead's current follow-up: the newest one its notes scheduled, or None if cleared.
    next_follow_up_at: datetime | None
    discussions: tuple[DiscussionSeed, ...] = ()  # oldest first

    @property
    def updated_at(self) -> datetime:
        return max([self.created_at, *(d.created_at for d in self.discussions)])


@dataclass(frozen=True)
class FollowUpTimes:
    later_today: datetime  # due today, not yet overdue
    earlier_today: datetime  # due today and already overdue
    previous_day: datetime  # overdue from an earlier day
    tomorrow: datetime  # upcoming
    in_three_days: datetime  # upcoming, further out


def _floor_minute(value: datetime) -> datetime:
    return value.replace(second=0, microsecond=0)


def _wall_clock(day: date, hour: int, tz: tzinfo) -> datetime:
    """`hour`:00 on `day` in `tz`, as a UTC instant."""
    return datetime.combine(day, time(hour), tzinfo=tz).astimezone(UTC)


def follow_up_times(now: datetime, tz: tzinfo) -> FollowUpTimes:
    """One instant per follow-up state, relative to `now` in `tz`.

    Arithmetic happens in UTC: subtracting two datetimes that share a ZoneInfo
    compares wall-clock times and would be off by an hour across a DST change.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(UTC)
    today_start, tomorrow_start = (bound.astimezone(UTC) for bound in today_bounds(now, tz))
    today = now.astimezone(tz).date()

    until_midnight = tomorrow_start - now
    if until_midnight >= MIDNIGHT_MARGIN:
        later_today = _floor_minute(now + until_midnight / 2)
    else:
        later_today = _wall_clock(today + timedelta(days=1), 10, tz)

    since_midnight = now - today_start
    if since_midnight >= MIDNIGHT_MARGIN:
        earlier_today = _floor_minute(today_start + since_midnight / 2)
    else:
        earlier_today = _wall_clock(today - timedelta(days=1), 16, tz)

    return FollowUpTimes(
        later_today=later_today,
        earlier_today=earlier_today,
        previous_day=_wall_clock(today - timedelta(days=1), 11, tz),
        tomorrow=_wall_clock(today + timedelta(days=1), 11, tz),
        in_three_days=_wall_clock(today + timedelta(days=3), 15, tz),
    )


def build_demo_plan(now: datetime, tz: tzinfo) -> list[LeadSeed]:
    """The demo leads, in insertion order. Names, companies and numbers are fictional."""
    at = follow_up_times(now, tz)
    now = now.astimezone(UTC)

    def ago(days: int = 0, hours: int = 0) -> datetime:
        return _floor_minute(now - timedelta(days=days, hours=hours))

    return [
        LeadSeed(
            name="Sarah Whitfield",
            company="Brightwater Analytics",
            phone="555-0101",
            status=LeadStatus.QUALIFIED,
            created_at=ago(9, 3),
            next_follow_up_at=at.later_today,
            discussions=(
                DiscussionSeed(
                    "Intro call. Their 12-person analytics team has outgrown spreadsheets "
                    "for pipeline reporting.",
                    ago(8, 2),
                ),
                DiscussionSeed(
                    "Ran the product demo for Sarah and their ops lead. Main concern: "
                    "importing three years of history.",
                    ago(4, 5),
                    follow_up_at=ago(2),
                ),
                DiscussionSeed(
                    "Budget approved in principle. Agreed to call tonight, after her board "
                    "meeting, to confirm the seat count.",
                    ago(0, 2),
                    follow_up_at=at.later_today,
                ),
            ),
        ),
        LeadSeed(
            name="Marcus Oyelaran",
            company="Bluefin Logistics",
            phone="555-0102",
            status=LeadStatus.PROPOSAL_SENT,
            created_at=ago(14),
            next_follow_up_at=at.earlier_today,
            discussions=(
                DiscussionSeed(
                    "Discovery call: 40 drivers, dispatch currently coordinated over group chats.",
                    ago(12, 4),
                ),
                DiscussionSeed(
                    "Sent the annual-plan proposal with volume pricing. Marcus will review it "
                    "with finance and wants a call to go through it.",
                    ago(3, 3),
                    follow_up_at=at.earlier_today,
                ),
            ),
        ),
        LeadSeed(
            name="Rahul Menon",
            company="Cedar & Pine Interiors",
            phone="555-0103",
            status=LeadStatus.CONTACTED,
            created_at=ago(20),
            next_follow_up_at=at.previous_day,
            discussions=(
                DiscussionSeed(
                    "Inbound from the website form. Wants to track showroom walk-ins.",
                    ago(18, 6),
                ),
                DiscussionSeed(
                    "Left a voicemail; Rahul replied by email asking for a callback next week.",
                    ago(10, 2),
                    follow_up_at=ago(7),
                ),
                DiscussionSeed(
                    "Spoke briefly while he was travelling. Asked for a callback once he is "
                    "back in the office.",
                    ago(4, 1),
                    follow_up_at=at.previous_day,
                ),
            ),
        ),
        LeadSeed(
            name="Daniel Ferreira",
            company="Harbor Health Clinics",
            phone="555-0104",
            status=LeadStatus.NEW,
            created_at=ago(3, 6),
            next_follow_up_at=at.tomorrow,
            discussions=(
                DiscussionSeed(
                    "Referred by an existing customer. Runs four outpatient clinics.",
                    ago(3, 5),
                ),
                DiscussionSeed(
                    "Emailed an introduction; Daniel asked for a short call in the morning.",
                    ago(0, 5),
                    follow_up_at=at.tomorrow,
                ),
            ),
        ),
        LeadSeed(
            name="Aisha Karim",
            company=None,
            phone=None,
            status=LeadStatus.NEW,
            created_at=ago(0, 1),
            next_follow_up_at=None,
        ),
        LeadSeed(
            name="Tomás Lindqvist",
            company="Summit Outdoor Gear",
            phone="555-0106",
            status=LeadStatus.WON,
            created_at=ago(30),
            # Cleared after the contract was signed; the notes keep their follow-ups.
            next_follow_up_at=None,
            discussions=(
                DiscussionSeed(
                    "First call. Replacing a legacy CRM before the peak season.",
                    ago(28),
                ),
                DiscussionSeed(
                    "Sent a proposal for 15 seats.",
                    ago(21, 3),
                    follow_up_at=ago(18),
                ),
                DiscussionSeed(
                    "Agreed a 10% multi-year discount; contract out for signature.",
                    ago(18, 1),
                    follow_up_at=ago(15),
                ),
                DiscussionSeed(
                    "Contract signed. Onboarding starts next Monday.",
                    ago(14, 2),
                ),
            ),
        ),
        LeadSeed(
            name="Elena Vasquez",
            company="Lumen Studio",
            phone="555-0107",
            status=LeadStatus.LOST,
            created_at=ago(26),
            next_follow_up_at=None,
            discussions=(
                DiscussionSeed("Demo for their five-person design team.", ago(25, 4)),
                DiscussionSeed(
                    "Elena chose a tool bundled with their project-management suite. "
                    "Worth revisiting next year.",
                    ago(16, 2),
                ),
            ),
        ),
        LeadSeed(
            name="Priya Nair",
            company="Kestrel Software",
            phone="555-0108",
            status=LeadStatus.CONTACTED,
            created_at=ago(6),
            next_follow_up_at=at.in_three_days,
            discussions=(
                DiscussionSeed("Met at a SaaS meetup; asked for a pricing sheet.", ago(5, 2)),
                DiscussionSeed(
                    "Sent pricing. Priya is on leave this week; follow up when she is back.",
                    ago(1, 4),
                    follow_up_at=at.in_three_days,
                ),
            ),
        ),
    ]


# --- Writing ---------------------------------------------------------------------------


def _check_schema(connection: Connection) -> None:
    """Refuse to write unless the database is migrated to the latest revision."""
    head = ScriptDirectory.from_config(Config(str(BACKEND_DIR / "alembic.ini"))).get_current_head()
    current = MigrationContext.configure(connection).get_current_revision()
    if current != head:
        raise SeedError(
            f"the database schema is at revision {current or 'none'}, not {head}; "
            "run `alembic upgrade head` first"
        )


def _insert(session: Session, plan: Sequence[LeadSeed]) -> None:
    for seed in plan:
        session.add(
            Lead(
                name=seed.name,
                company=seed.company,
                phone=seed.phone,
                status=seed.status,
                next_follow_up_at=seed.next_follow_up_at,
                created_at=seed.created_at,
                updated_at=seed.updated_at,
                discussions=[
                    Discussion(note=d.note, follow_up_at=d.follow_up_at, created_at=d.created_at)
                    for d in seed.discussions
                ],
            )
        )
    session.flush()


def seed_if_empty(engine: Engine, now: datetime, tz: tzinfo) -> bool:
    """Insert the demo data only if both tables are empty. Returns whether it did."""
    with Session(engine) as session, session.begin():
        _check_schema(session.connection())
        # Block concurrent writers (e.g. two containers starting) between the
        # emptiness check and the inserts; released at commit or rollback.
        session.execute(text("LOCK TABLE leads, discussions IN EXCLUSIVE MODE"))
        leads = session.scalar(select(func.count()).select_from(Lead))
        discussions = session.scalar(select(func.count()).select_from(Discussion))
        if leads or discussions:
            return False
        _insert(session, build_demo_plan(now, tz))
    return True


def reset_and_seed(engine: Engine, now: datetime, tz: tzinfo) -> None:
    """Replace every lead and discussion with the demo data, in one transaction."""
    with Session(engine) as session, session.begin():
        _check_schema(session.connection())
        # Only the two application tables; no CASCADE, so an unexpected
        # dependent table makes this fail instead of being emptied too.
        session.execute(text("TRUNCATE leads, discussions RESTART IDENTITY"))
        _insert(session, build_demo_plan(now, tz))


# --- Command line ----------------------------------------------------------------------


def describe_target(database_url: str) -> str:
    """host:port/database, never the user name or password."""
    url = make_url(database_url)
    return f"{url.host or 'localhost'}:{url.port or 5432}/{url.database}"


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.seed",
        description="Insert LeadFlow demo data (only into an empty database unless --reset).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--auto",
        action="store_true",
        help="do nothing unless SEED_DEMO_DATA is true (for container start-up)",
    )
    mode.add_argument(
        "--reset",
        action="store_true",
        help="DELETE every lead and discussion, then insert the demo data",
    )
    parser.add_argument("--yes", action="store_true", help="confirm --reset")
    parser.add_argument(
        "--confirm-database",
        metavar="NAME",
        help="with --reset: the name of the database to reset, which must match DATABASE_URL",
    )
    return parser.parse_args(argv)


def _load_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        # hide_input_in_errors keeps the values (e.g. DATABASE_URL) out of these messages.
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise SeedError(f"invalid configuration: {problems}") from None


def _check_reset_request(args: argparse.Namespace) -> None:
    if not args.yes:
        raise SeedError("--reset deletes every lead and discussion; add --yes to confirm")
    if not args.confirm_database:
        raise SeedError("--reset also needs --confirm-database NAME (the target database's name)")
    if not os.environ.get("DATABASE_URL"):
        raise SeedError(
            "--reset needs DATABASE_URL set explicitly in the environment; "
            "a value read from .env is not accepted for a reset"
        )
    try:
        database = make_url(os.environ["DATABASE_URL"]).database
    except (ArgumentError, ValueError):
        raise SeedError("DATABASE_URL is not a valid SQLAlchemy URL") from None
    if args.confirm_database != database:
        raise SeedError(
            f"--confirm-database {args.confirm_database!r} does not match the target "
            f"database {database!r}"
        )


def main(
    argv: Sequence[str] | None = None,
    *,
    engine_factory: Callable[[str], Engine] = build_engine,
    now: datetime | None = None,
) -> int:
    args = _parse_args(argv)
    if (args.yes or args.confirm_database) and not args.reset:
        print("seed: --yes and --confirm-database only apply to --reset", file=sys.stderr)
        return EXIT_REFUSED
    try:
        if args.reset:
            _check_reset_request(args)
        settings = _load_settings()
        if args.reset and settings.database_url != os.environ["DATABASE_URL"]:
            # Settings match variable names case-insensitively, so another spelling
            # (e.g. database_url) could win; reset only the URL that was confirmed.
            raise SeedError(
                "the configured database URL differs from the exported DATABASE_URL "
                "whose database name was confirmed"
            )
        if args.auto and not settings.seed_demo_data:
            print("seed: SEED_DEMO_DATA is not enabled; no demo data inserted.")
            return EXIT_OK

        target = describe_target(settings.database_url)
        print(f"seed: target database {target}")
        current = now if now is not None else get_now()
        engine = engine_factory(settings.database_url)
        try:
            if args.reset:
                reset_and_seed(engine, current, settings.timezone)
                print(f"seed: replaced all leads and discussions in {target} with demo data.")
            elif seed_if_empty(engine, current, settings.timezone):
                print(f"seed: inserted demo data into {target}.")
            else:
                print(f"seed: {target} already has leads or discussions; nothing changed.")
        finally:
            engine.dispose()
    except SeedError as exc:
        print(f"seed: {exc}; nothing was changed.", file=sys.stderr)
        return EXIT_REFUSED
    except SQLAlchemyError as exc:
        # Only the type: driver messages can include the host and user name.
        print(f"seed: database error ({type(exc).__name__}); nothing was changed.", file=sys.stderr)
        return EXIT_DATABASE_ERROR
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
