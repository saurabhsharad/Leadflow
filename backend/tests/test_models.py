"""Model and schema behaviour against the real PostgreSQL test database."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Discussion, Lead, LeadStatus

FOLLOW_UP = datetime(2026, 10, 15, 5, 30, tzinfo=UTC)


def add_lead(session: Session, **fields: object) -> Lead:
    lead = Lead(name="Sarah Connor", **fields)
    session.add(lead)
    session.commit()
    return lead


def insert_raw(session: Session, sql: str, **params: object) -> None:
    """Insert with plain SQL, so PostgreSQL (not the ORM) is what validates it."""
    session.execute(text(sql), params)
    session.flush()


# --- Schema -----------------------------------------------------------------


def test_both_tables_exist(db_engine: Engine) -> None:
    assert {"leads", "discussions"} <= set(inspect(db_engine).get_table_names())


def test_timestamp_columns_are_timezone_aware(db_engine: Engine) -> None:
    with db_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT table_name, column_name, data_type FROM information_schema.columns "
                "WHERE table_name IN ('leads', 'discussions') AND data_type LIKE 'timestamp%'"
            )
        ).all()
    assert {(t, c): d for t, c, d in rows} == {
        ("leads", "next_follow_up_at"): "timestamp with time zone",
        ("leads", "created_at"): "timestamp with time zone",
        ("leads", "updated_at"): "timestamp with time zone",
        ("discussions", "follow_up_at"): "timestamp with time zone",
        ("discussions", "created_at"): "timestamp with time zone",
    }


def test_discussion_index_has_expected_columns_and_order(db_engine: Engine) -> None:
    with db_engine.connect() as connection:
        definition = connection.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_discussions_lead_created'")
        ).scalar_one()
    assert definition.endswith(
        "ON public.discussions USING btree (lead_id, created_at DESC, id DESC)"
    )


def test_required_columns_are_not_nullable(db_engine: Engine) -> None:
    with db_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT table_name, column_name, is_nullable FROM information_schema.columns "
                "WHERE table_name IN ('leads', 'discussions')"
            )
        ).all()
    nullable = {(t, c) for t, c, n in rows if n == "YES"}
    assert nullable == {
        ("leads", "company"),
        ("leads", "phone"),
        ("leads", "next_follow_up_at"),
        ("discussions", "follow_up_at"),
    }


# --- Leads ------------------------------------------------------------------


def test_lead_defaults_and_optional_fields(db_session: Session) -> None:
    lead = add_lead(db_session)

    assert lead.id is not None
    assert lead.status == LeadStatus.NEW
    assert lead.company is None
    assert lead.phone is None
    assert lead.next_follow_up_at is None
    assert lead.created_at.tzinfo is not None
    assert lead.updated_at.tzinfo is not None


def test_status_is_stored_as_lowercase_value(db_session: Session) -> None:
    add_lead(db_session, status=LeadStatus.PROPOSAL_SENT)
    stored = db_session.execute(text("SELECT status FROM leads")).scalar_one()
    assert stored == "proposal_sent"


def test_lead_with_all_fields_round_trips(db_session: Session) -> None:
    lead = add_lead(
        db_session,
        company="Acme Corp",
        phone="555-0199",
        status=LeadStatus.QUALIFIED,
        next_follow_up_at=FOLLOW_UP,
    )
    db_session.expire_all()
    reloaded = db_session.get(Lead, lead.id)
    assert reloaded is not None
    assert (reloaded.company, reloaded.phone, reloaded.status) == (
        "Acme Corp",
        "555-0199",
        LeadStatus.QUALIFIED,
    )
    assert reloaded.next_follow_up_at == FOLLOW_UP


def test_updated_at_advances_on_update(db_session: Session) -> None:
    lead = add_lead(db_session)
    created_at, first_updated_at = lead.created_at, lead.updated_at

    lead.status = LeadStatus.CONTACTED
    db_session.commit()

    assert lead.created_at == created_at
    assert lead.updated_at > first_updated_at


def test_all_six_statuses_are_accepted_by_postgres(db_session: Session) -> None:
    for status in ("new", "contacted", "qualified", "proposal_sent", "won", "lost"):
        insert_raw(db_session, "INSERT INTO leads (name, status) VALUES ('A', :s)", s=status)
    assert [s.value for s in LeadStatus] == [
        "new",
        "contacted",
        "qualified",
        "proposal_sent",
        "won",
        "lost",
    ]


@pytest.mark.parametrize("status", ["New", "pending", "proposal sent", ""])
def test_invalid_status_is_rejected_by_postgres(db_session: Session, status: str) -> None:
    with pytest.raises(IntegrityError, match="ck_leads_status"):
        insert_raw(db_session, "INSERT INTO leads (name, status) VALUES ('A', :s)", s=status)


@pytest.mark.parametrize("name", ["", " ", "  \t ", "\r\n\f\v"])
def test_blank_lead_name_is_rejected_by_postgres(db_session: Session, name: str) -> None:
    with pytest.raises(IntegrityError, match="ck_leads_name_not_blank"):
        insert_raw(db_session, "INSERT INTO leads (name) VALUES (:n)", n=name)


def test_text_with_surrounding_whitespace_is_accepted(db_session: Session) -> None:
    # The database only rejects all-whitespace values; trimming is the API's job.
    insert_raw(db_session, "INSERT INTO leads (name) VALUES (:n)", n=" Sarah\t")
    assert db_session.execute(text("SELECT name FROM leads")).scalar_one() == " Sarah\t"


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO leads (name) VALUES (NULL)",
        "INSERT INTO leads (name, status) VALUES ('A', NULL)",
        "INSERT INTO leads (name, created_at) VALUES ('A', NULL)",
        "INSERT INTO leads (name, updated_at) VALUES ('A', NULL)",
    ],
)
def test_lead_required_columns_reject_null(db_session: Session, sql: str) -> None:
    with pytest.raises(IntegrityError, match="not-null"):
        insert_raw(db_session, sql)


# --- Discussions ------------------------------------------------------------


def test_lead_can_have_multiple_discussions_newest_first(db_session: Session) -> None:
    lead = add_lead(db_session)
    # Same transaction, so PostgreSQL's now() gives both the same created_at;
    # the id tie-breaker must still put the later row first.
    lead.discussions.append(Discussion(note="First call"))
    lead.discussions.append(Discussion(note="Sent pricing", follow_up_at=FOLLOW_UP))
    db_session.commit()

    db_session.expire_all()
    reloaded = db_session.get(Lead, lead.id)
    assert reloaded is not None
    notes = [(d.note, d.follow_up_at) for d in reloaded.discussions]
    assert notes == [("Sent pricing", FOLLOW_UP), ("First call", None)]
    assert reloaded.discussions[0].created_at == reloaded.discussions[1].created_at
    assert all(d.lead_id == lead.id for d in reloaded.discussions)


def test_discussion_follow_up_is_independent_of_lead_follow_up(db_session: Session) -> None:
    lead = add_lead(db_session, next_follow_up_at=FOLLOW_UP)
    discussion = Discussion(lead=lead, note="Rescheduled", follow_up_at=FOLLOW_UP)
    db_session.add(discussion)
    db_session.commit()

    lead.next_follow_up_at = None
    db_session.commit()

    db_session.expire_all()
    assert db_session.get(Discussion, discussion.id).follow_up_at == FOLLOW_UP


@pytest.mark.parametrize("note", ["", " ", "\n\t ", "\r\n\f\v"])
def test_blank_discussion_note_is_rejected_by_postgres(db_session: Session, note: str) -> None:
    lead = add_lead(db_session)
    with pytest.raises(IntegrityError, match="ck_discussions_note_not_blank"):
        insert_raw(
            db_session,
            "INSERT INTO discussions (lead_id, note) VALUES (:lead_id, :note)",
            lead_id=lead.id,
            note=note,
        )


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO discussions (lead_id, note) VALUES (NULL, 'x')",
        "INSERT INTO discussions (lead_id, note) VALUES (:lead_id, NULL)",
        "INSERT INTO discussions (lead_id, note, created_at) VALUES (:lead_id, 'x', NULL)",
    ],
)
def test_discussion_required_columns_reject_null(db_session: Session, sql: str) -> None:
    lead = add_lead(db_session)
    with pytest.raises(IntegrityError, match="not-null"):
        insert_raw(db_session, sql, lead_id=lead.id)


def test_discussion_for_missing_lead_is_rejected(db_session: Session) -> None:
    with pytest.raises(IntegrityError, match="fk_discussions_lead_id_leads"):
        insert_raw(db_session, "INSERT INTO discussions (lead_id, note) VALUES (999, 'x')")


# --- Cascade ----------------------------------------------------------------


def count_discussions(session: Session) -> int:
    return session.execute(select(func.count()).select_from(Discussion)).scalar_one()


def add_lead_with_discussions(session: Session) -> Lead:
    lead = Lead(name="Cascade", discussions=[Discussion(note="a"), Discussion(note="b")])
    session.add(lead)
    session.commit()
    session.expire_all()  # discussions not loaded, as after a fresh query
    return lead


def test_deleting_lead_in_database_cascades_to_discussions(db_session: Session) -> None:
    lead = add_lead_with_discussions(db_session)
    db_session.execute(text("DELETE FROM leads WHERE id = :id"), {"id": lead.id})
    db_session.commit()
    assert count_discussions(db_session) == 0


def test_deleting_lead_through_orm_cascades_to_discussions(db_session: Session) -> None:
    lead = add_lead_with_discussions(db_session)
    db_session.delete(lead)
    db_session.commit()
    assert count_discussions(db_session) == 0
