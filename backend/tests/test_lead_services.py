"""Service layer against the PostgreSQL test database, with a fixed clock."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.errors import LeadNotFound
from app.models import Discussion, Lead, LeadStatus
from app.schemas import DiscussionCreate, LeadCreate, LeadUpdate
from app.services import leads as services

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)  # 20:30 IST, the specification's clock


def ist(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=IST)


def add_lead(session: Session, name: str, **fields: object) -> Lead:
    """Insert directly (bypassing services) to control timestamps in tests."""
    lead = Lead(name=name, **fields)
    session.add(lead)
    session.commit()
    return lead


def add_discussion(session: Session, lead: Lead, note: str, created_at: datetime) -> Discussion:
    discussion = Discussion(lead_id=lead.id, note=note, created_at=created_at)
    session.add(discussion)
    session.commit()
    return discussion


@contextmanager
def count_statements(session: Session) -> Iterator[list[str]]:
    statements: list[str] = []
    engine = session.get_bind()

    def record(_conn, _cursor, statement, *_args) -> None:  # noqa: ANN001
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


# --- create_lead --------------------------------------------------------------


def test_create_lead_uses_database_defaults(db_session: Session) -> None:
    summary = services.create_lead(
        db_session, LeadCreate(name="  Sarah Connor ", company="Acme"), NOW, IST
    )
    assert summary.id == 1
    assert summary.name == "Sarah Connor"
    assert (summary.company, summary.phone) == ("Acme", None)
    assert summary.status is LeadStatus.NEW
    assert summary.next_follow_up_at is None
    assert (summary.follow_up_due_today, summary.follow_up_overdue) == (False, False)
    assert summary.last_discussion is None
    assert summary.created_at.tzinfo is not None
    assert summary.created_at == summary.updated_at

    stored = db_session.execute(select(Lead)).scalar_one()
    assert (stored.id, stored.name, stored.status) == (1, "Sarah Connor", LeadStatus.NEW)


def test_create_lead_ids_are_generated_in_sequence(db_session: Session) -> None:
    ids = [services.create_lead(db_session, LeadCreate(name=n), NOW, IST).id for n in "ABC"]
    assert ids == [1, 2, 3]


# --- get_lead -----------------------------------------------------------------


def test_get_lead_returns_detail(db_session: Session) -> None:
    lead = add_lead(db_session, "Kyle", phone="555-0100", next_follow_up_at=ist(13, 14))
    detail = services.get_lead(db_session, lead.id, NOW, IST)
    assert (detail.id, detail.name, detail.phone) == (lead.id, "Kyle", "555-0100")
    assert (detail.follow_up_due_today, detail.follow_up_overdue) == (True, True)
    assert detail.discussions == []
    assert detail.last_discussion is None


def test_get_missing_lead_raises_lead_not_found(db_session: Session) -> None:
    with pytest.raises(LeadNotFound) as exc_info:
        services.get_lead(db_session, 999, NOW, IST)
    assert exc_info.value.lead_id == 999


# --- update_lead --------------------------------------------------------------


def test_update_status_leaves_omitted_follow_up_unchanged(db_session: Session) -> None:
    lead = add_lead(db_session, "A", next_follow_up_at=ist(14, 11))
    created_at = lead.created_at

    summary = services.update_lead(
        db_session, lead.id, LeadUpdate.model_validate({"status": "qualified"}), NOW, IST
    )

    assert summary.status is LeadStatus.QUALIFIED
    assert summary.next_follow_up_at == ist(14, 11)
    assert summary.updated_at > created_at
    db_session.expire_all()
    assert db_session.get(Lead, lead.id).status is LeadStatus.QUALIFIED


def test_update_explicit_null_clears_follow_up_and_keeps_status(db_session: Session) -> None:
    lead = add_lead(db_session, "A", status=LeadStatus.WON, next_follow_up_at=ist(12, 9))
    summary = services.update_lead(
        db_session, lead.id, LeadUpdate.model_validate({"next_follow_up_at": None}), NOW, IST
    )
    assert summary.next_follow_up_at is None
    assert (summary.follow_up_due_today, summary.follow_up_overdue) == (False, False)
    assert summary.status is LeadStatus.WON


def test_update_follow_up_recomputes_flags(db_session: Session) -> None:
    lead = add_lead(db_session, "A")
    summary = services.update_lead(
        db_session,
        lead.id,
        LeadUpdate.model_validate({"next_follow_up_at": "2026-10-13T21:00:00+05:30"}),
        NOW,
        IST,
    )
    assert summary.next_follow_up_at == ist(13, 21)
    assert (summary.follow_up_due_today, summary.follow_up_overdue) == (True, False)


def test_update_records_write_even_when_values_are_unchanged(db_session: Session) -> None:
    lead = add_lead(db_session, "A")
    before = lead.updated_at
    summary = services.update_lead(
        db_session, lead.id, LeadUpdate.model_validate({"status": "new"}), NOW, IST
    )
    assert summary.updated_at > before


def test_empty_update_is_rejected_before_reaching_the_service() -> None:
    with pytest.raises(ValidationError):
        LeadUpdate.model_validate({})


def test_update_missing_lead_raises_lead_not_found(db_session: Session) -> None:
    with pytest.raises(LeadNotFound):
        services.update_lead(
            db_session, 404, LeadUpdate.model_validate({"status": "won"}), NOW, IST
        )


# --- list_leads ---------------------------------------------------------------


def test_list_shows_newest_discussion_and_ties_break_on_id(db_session: Session) -> None:
    lead = add_lead(db_session, "A")
    add_discussion(db_session, lead, "older", ist(10, 9))
    add_discussion(db_session, lead, "tied first", ist(11, 9))
    add_discussion(db_session, lead, "tied second", ist(11, 9))  # same time, higher id

    [summary] = services.list_leads(db_session, NOW, IST)
    assert summary.last_discussion is not None
    assert summary.last_discussion.note == "tied second"
    assert summary.last_discussion.created_at == ist(11, 9)


def test_list_orders_groups_and_puts_leads_without_discussions_last(db_session: Session) -> None:
    created = ist(1, 9)
    quiet_old = add_lead(db_session, "no notes, older", created_at=ist(1, 8))
    quiet_new = add_lead(db_session, "no notes, newer", created_at=ist(2, 8))
    talked = add_lead(db_session, "recent note", created_at=created)
    add_discussion(db_session, talked, "hi", ist(12, 9))
    talked_earlier = add_lead(db_session, "older note", created_at=created)
    add_discussion(db_session, talked_earlier, "hi", ist(11, 9))
    today = add_lead(db_session, "today", created_at=created, next_follow_up_at=ist(13, 22))
    earlier = add_lead(db_session, "yesterday", created_at=created, next_follow_up_at=ist(12, 9))
    upcoming = add_lead(db_session, "tomorrow", created_at=ist(3, 8), next_follow_up_at=ist(14, 9))

    names = [s.name for s in services.list_leads(db_session, NOW, IST)]
    assert names == [
        earlier.name,  # overdue from an earlier day
        today.name,  # today's follow-ups
        talked.name,  # all leads: newest discussion first
        talked_earlier.name,
        upcoming.name,  # no discussions: newest created first
        quiet_new.name,
        quiet_old.name,
    ]


def test_list_computes_follow_up_flags(db_session: Session) -> None:
    add_lead(db_session, "earlier today", next_follow_up_at=ist(13, 14))
    [summary] = services.list_leads(db_session, NOW, IST)
    assert (summary.follow_up_due_today, summary.follow_up_overdue) == (True, True)


def test_list_is_a_single_query_regardless_of_lead_count(db_session: Session) -> None:
    for i in range(5):
        lead = add_lead(db_session, f"Lead {i}")
        for day in (8, 9, 10):
            add_discussion(db_session, lead, f"note {day}", ist(day, 9))
    db_session.expire_all()

    with count_statements(db_session) as statements:
        summaries = services.list_leads(db_session, NOW, IST)

    assert len(summaries) == 5
    assert all(s.last_discussion and s.last_discussion.note == "note 10" for s in summaries)
    assert len(statements) == 1
    assert "DISTINCT ON" in statements[0]


def test_list_filters_by_status_and_case_insensitive_name(db_session: Session) -> None:
    add_lead(db_session, "Sarah Connor", status=LeadStatus.QUALIFIED)
    add_lead(db_session, "Farah Khan", status=LeadStatus.NEW)
    add_lead(db_session, "John Smith", status=LeadStatus.QUALIFIED)

    def names(**filters: object) -> list[str]:
        return sorted(s.name for s in services.list_leads(db_session, NOW, IST, **filters))

    assert names(status=LeadStatus.QUALIFIED) == ["John Smith", "Sarah Connor"]
    assert names(q="RAH") == ["Farah Khan", "Sarah Connor"]
    assert names(status=LeadStatus.QUALIFIED, q="rah") == ["Sarah Connor"]
    assert names(q="") == ["Farah Khan", "John Smith", "Sarah Connor"]


def test_list_search_treats_wildcards_literally(db_session: Session) -> None:
    add_lead(db_session, "100% Leads")
    add_lead(db_session, "Plain_Name")
    add_lead(db_session, "PlainXName")
    assert [s.name for s in services.list_leads(db_session, NOW, IST, q="%")] == ["100% Leads"]
    assert [s.name for s in services.list_leads(db_session, NOW, IST, q="n_n")] == ["Plain_Name"]


# --- add_discussion -----------------------------------------------------------


def note(text: str, follow_up_at: str | None = None) -> DiscussionCreate:
    """A validated request; follow_up_at=None means the field is omitted."""
    data: dict[str, object] = {"note": text}
    if follow_up_at is not None:
        data["follow_up_at"] = follow_up_at
    return DiscussionCreate.model_validate(data)


def test_add_discussion_with_follow_up_updates_lead_in_one_write(db_session: Session) -> None:
    lead = add_lead(db_session, "A", next_follow_up_at=ist(12, 9))
    before = lead.updated_at

    created = services.add_discussion(
        db_session, lead.id, note("  Wants a quote ", "2026-10-13T21:00:00+05:30"), NOW, IST
    )

    discussion = created.discussion
    assert (discussion.id, discussion.note) == (1, "Wants a quote")
    assert discussion.follow_up_at == ist(13, 21)
    assert discussion.created_at.tzinfo is not None
    summary = created.lead
    assert summary.next_follow_up_at == ist(13, 21)  # replaced
    assert (summary.follow_up_due_today, summary.follow_up_overdue) == (True, False)
    assert summary.last_discussion is not None
    assert summary.last_discussion.note == "Wants a quote"
    assert summary.updated_at > before
    assert summary.updated_at == discussion.created_at  # same transaction, same now()


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"note": "Called, no answer"}, id="follow_up_at omitted"),
        pytest.param({"note": "Called", "follow_up_at": None}, id="follow_up_at null"),
    ],
)
def test_add_discussion_without_follow_up_leaves_lead_untouched(
    db_session: Session, payload: dict[str, object]
) -> None:
    lead = add_lead(db_session, "A", next_follow_up_at=ist(14, 11))
    updated_at = lead.updated_at

    created = services.add_discussion(
        db_session, lead.id, DiscussionCreate.model_validate(payload), NOW, IST
    )

    assert created.discussion.follow_up_at is None
    assert created.lead.next_follow_up_at == ist(14, 11)  # never cleared
    assert created.lead.updated_at == updated_at  # lead row not written
    assert created.lead.last_discussion is not None
    assert created.lead.last_discussion.note == payload["note"]


def test_add_discussion_to_missing_lead_raises_and_inserts_nothing(db_session: Session) -> None:
    with pytest.raises(LeadNotFound) as exc_info:
        services.add_discussion(db_session, 404, note("x"), NOW, IST)
    assert exc_info.value.lead_id == 404
    db_session.rollback()
    assert db_session.execute(select(Discussion)).first() is None


def test_rescheduling_keeps_earlier_follow_up_in_history(db_session: Session) -> None:
    lead = add_lead(db_session, "A")
    for payload in (
        note("first", "2026-10-14T10:00:00+05:30"),
        note("second", "2026-10-16T10:00:00+05:30"),
        note("third, no date"),
    ):
        services.add_discussion(db_session, lead.id, payload, NOW, IST)

    detail = services.get_lead(db_session, lead.id, NOW, IST)
    assert detail.next_follow_up_at == ist(16, 10)
    assert [(d.note, d.follow_up_at) for d in detail.discussions] == [
        ("third, no date", None),
        ("second", ist(16, 10)),
        ("first", ist(14, 10)),
    ]


def test_discussion_history_order_is_deterministic_for_equal_timestamps(
    db_session: Session,
) -> None:
    lead = add_lead(db_session, "A")
    for text in ("a", "b", "c"):
        add_discussion(db_session, lead, text, ist(12, 9))
    add_discussion(db_session, lead, "older", ist(11, 9))
    db_session.expire_all()

    detail = services.get_lead(db_session, lead.id, NOW, IST)
    assert [d.note for d in detail.discussions] == ["c", "b", "a", "older"]
    assert detail.last_discussion is not None
    assert detail.last_discussion.note == "c"


def test_failure_before_commit_persists_neither_note_nor_follow_up(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    lead = add_lead(db_session, "A", next_follow_up_at=ist(14, 11))

    def flush_then_fail() -> None:
        db_session.flush()  # the INSERT and UPDATE reach the database...
        raise RuntimeError("simulated failure before commit")  # ...but are never committed

    monkeypatch.setattr(db_session, "commit", flush_then_fail)
    with pytest.raises(RuntimeError, match="simulated"):
        services.add_discussion(
            db_session, lead.id, note("lost", "2026-10-20T10:00:00+05:30"), NOW, IST
        )
    monkeypatch.undo()
    db_session.rollback()  # what closing the request's session does

    assert db_session.execute(select(Discussion)).first() is None
    assert db_session.get(Lead, lead.id).next_follow_up_at == ist(14, 11)


def test_new_discussion_becomes_last_discussion_in_list(db_session: Session) -> None:
    lead = add_lead(db_session, "A")
    add_discussion(db_session, lead, "old", ist(1, 9))
    services.add_discussion(db_session, lead.id, note("fresh"), NOW, IST)
    [summary] = services.list_leads(db_session, NOW, IST)
    assert summary.last_discussion is not None
    assert summary.last_discussion.note == "fresh"
