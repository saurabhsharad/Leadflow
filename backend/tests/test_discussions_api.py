"""POST /api/leads/{lead_id}/discussions end to end, against the PostgreSQL test database."""

from collections.abc import Iterator
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.clock import get_now
from app.db import build_engine, get_engine
from app.main import app
from app.models import Discussion, Lead
from app.routers.leads import MAX_LEAD_ID
from app.services import leads as services

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)  # 20:30 IST, the specification's clock
ORIGIN = "http://localhost:3000"


def ist(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=IST)


def iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture
def client(db_session: Session, db_engine: Engine) -> Iterator[TestClient]:
    """The real app on the test database with a fixed clock; tables start empty."""
    app.dependency_overrides[get_engine] = lambda: db_engine
    app.dependency_overrides[get_now] = lambda: NOW
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def lead(db_session: Session) -> Lead:
    """A lead with an existing follow-up (tomorrow 11:00 IST) and no discussions."""
    lead = Lead(name="Sarah Connor", phone="555-0199", next_follow_up_at=ist(14, 11))
    db_session.add(lead)
    db_session.commit()
    return lead


def url(lead_id: int | str) -> str:
    return f"/api/leads/{lead_id}/discussions"


def discussion_count(session: Session) -> int:
    session.expire_all()
    return session.execute(select(func.count()).select_from(Discussion)).scalar_one()


def error_fields(response) -> list[str | None]:  # noqa: ANN001
    body = response.json()
    assert set(body) == {"detail", "code", "errors"}
    assert body["code"] == "validation_error"
    return [e["field"] for e in body["errors"]]


# --- Success --------------------------------------------------------------------


def test_note_with_follow_up_returns_201_and_updates_lead(client: TestClient, lead: Lead) -> None:
    # The specification's example request, with the follow-up given in IST.
    response = client.post(
        url(lead.id),
        json={
            "note": "  Wants a revised enterprise quote. ",
            "follow_up_at": "2026-10-15T11:00:00+05:30",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"discussion", "lead"}

    discussion = body["discussion"]
    assert set(discussion) == {"id", "note", "follow_up_at", "created_at"}
    assert discussion["id"] == 1
    assert discussion["note"] == "Wants a revised enterprise quote."
    assert discussion["follow_up_at"] == "2026-10-15T05:30:00Z"
    assert discussion["created_at"].endswith("Z")

    summary = body["lead"]
    assert summary["id"] == lead.id
    assert summary["next_follow_up_at"] == "2026-10-15T05:30:00Z"  # replaced
    assert (summary["follow_up_due_today"], summary["follow_up_overdue"]) == (False, False)
    assert summary["last_discussion"] == {
        "note": "Wants a revised enterprise quote.",
        "created_at": discussion["created_at"],
    }
    assert summary["updated_at"] == discussion["created_at"]  # same transaction

    detail = client.get(f"/api/leads/{lead.id}").json()
    assert detail["next_follow_up_at"] == "2026-10-15T05:30:00Z"
    assert detail["discussions"] == [discussion]


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"note": "Called, no answer"}, id="follow_up_at omitted"),
        pytest.param({"note": "Called, no answer", "follow_up_at": None}, id="follow_up_at null"),
    ],
)
def test_note_without_follow_up_keeps_lead_follow_up(
    client: TestClient, lead: Lead, payload: dict
) -> None:
    before = client.get(f"/api/leads/{lead.id}").json()

    response = client.post(url(lead.id), json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["discussion"]["follow_up_at"] is None
    assert body["lead"]["next_follow_up_at"] == iso_utc(ist(14, 11))  # never cleared
    assert body["lead"]["updated_at"] == before["updated_at"]
    assert body["lead"]["last_discussion"]["note"] == "Called, no answer"

    after = client.get(f"/api/leads/{lead.id}").json()
    assert after["next_follow_up_at"] == iso_utc(ist(14, 11))
    assert [d["note"] for d in after["discussions"]] == ["Called, no answer"]


def test_history_keeps_earlier_follow_ups(client: TestClient, lead: Lead) -> None:
    for payload in (
        {"note": "first", "follow_up_at": "2026-10-14T10:00:00+05:30"},
        {"note": "second", "follow_up_at": "2026-10-16T10:00:00+05:30"},
        {"note": "third"},
    ):
        assert client.post(url(lead.id), json=payload).status_code == 201

    detail = client.get(f"/api/leads/{lead.id}").json()
    assert detail["next_follow_up_at"] == iso_utc(ist(16, 10))
    assert [(d["id"], d["note"], d["follow_up_at"]) for d in detail["discussions"]] == [
        (3, "third", None),
        (2, "second", iso_utc(ist(16, 10))),
        (1, "first", iso_utc(ist(14, 10))),
    ]


def test_past_follow_up_is_accepted_and_overdue(client: TestClient, lead: Lead) -> None:
    response = client.post(
        url(lead.id),
        json={"note": "Should have called", "follow_up_at": "2026-10-13T14:00:00+05:30"},
    )
    assert response.status_code == 201
    summary = response.json()["lead"]
    assert (summary["follow_up_due_today"], summary["follow_up_overdue"]) == (True, True)


def test_note_length_is_counted_after_trimming(client: TestClient, lead: Lead) -> None:
    response = client.post(url(lead.id), json={"note": f"  {'n' * 5000}\n"})
    assert response.status_code == 201
    assert len(response.json()["discussion"]["note"]) == 5000


# --- Not found and validation ---------------------------------------------------------


def test_missing_lead_is_404_and_creates_nothing(client: TestClient, db_session: Session) -> None:
    response = client.post(url(999), json={"note": "x", "follow_up_at": "2026-10-15T11:00:00Z"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Lead not found", "code": "lead_not_found", "errors": []}
    assert discussion_count(db_session) == 0


@pytest.mark.parametrize("lead_id", ["abc", "0", "-1", "1.5", str(MAX_LEAD_ID + 1)])
def test_invalid_lead_id_is_422(client: TestClient, lead_id: str) -> None:
    response = client.post(url(lead_id), json={"note": "x"})
    assert response.status_code == 422
    assert error_fields(response) == ["lead_id"]


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({}, "note"),
        ({"note": ""}, "note"),
        ({"note": " \n\t "}, "note"),
        ({"note": "n" * 5001}, "note"),
        ({"note": 42}, "note"),
        ({"note": "x", "follow_up_at": "2026-10-15T11:00:00"}, "follow_up_at"),  # naive
        ({"note": "x", "follow_up_at": "next Tuesday"}, "follow_up_at"),
        ({"note": "x", "follow_up_at": "1999-12-31T23:59:59Z"}, "follow_up_at"),
        ({"note": "x", "follow_up_at": "9999-12-31T23:59:59-05:00"}, "follow_up_at"),
        ({"note": "x", "lead_id": 2}, "lead_id"),
        ({"note": "x", "created_at": "2026-10-13T15:00:00Z"}, "created_at"),
        ({"note": "x", "next_follow_up_at": None}, "next_follow_up_at"),
    ],
)
def test_invalid_body_is_422_and_changes_nothing(
    client: TestClient, db_session: Session, lead: Lead, payload: dict, field: str
) -> None:
    response = client.post(url(lead.id), json=payload)
    assert response.status_code == 422
    assert error_fields(response) == [field]
    assert discussion_count(db_session) == 0
    assert client.get(f"/api/leads/{lead.id}").json()["next_follow_up_at"] == iso_utc(ist(14, 11))


def test_blank_note_message(client: TestClient, lead: Lead) -> None:
    response = client.post(url(lead.id), json={"note": "   "})
    assert response.json()["errors"] == [{"field": "note", "message": "Note is required"}]


def test_malformed_json_is_422_without_field(client: TestClient, lead: Lead) -> None:
    response = client.post(
        url(lead.id), content=b'{"note": ', headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert error_fields(response) == [None]


def test_other_methods_are_405(client: TestClient, lead: Lead) -> None:
    response = client.get(url(lead.id))
    assert response.status_code == 405
    assert response.json()["code"] == "method_not_allowed"
    assert response.headers["allow"] == "POST"


# --- Failures ---------------------------------------------------------------------------


def test_failure_before_commit_persists_nothing(
    client: TestClient, db_session: Session, lead: Lead, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure after the insert rolls back both the note and the follow-up change."""

    def insert_update_then_fail(session: Session, lead_id: int, data, *_args: object) -> None:  # noqa: ANN001
        session.add(Discussion(lead_id=lead_id, note=data.note, follow_up_at=data.follow_up_at))
        session.get(Lead, lead_id).next_follow_up_at = data.follow_up_at
        session.flush()  # both statements reach PostgreSQL inside the request transaction
        raise RuntimeError("failure before commit")

    monkeypatch.setattr(services, "add_discussion", insert_update_then_fail)
    response = client.post(
        url(lead.id), json={"note": "lost", "follow_up_at": "2026-10-20T10:00:00+05:30"}
    )
    assert response.status_code == 500

    monkeypatch.undo()
    assert discussion_count(db_session) == 0
    assert client.get(f"/api/leads/{lead.id}").json()["next_follow_up_at"] == iso_utc(ist(14, 11))


def test_unexpected_error_is_generic_500_with_cors(
    client: TestClient, lead: Lead, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("INSERT INTO discussions VALUES ('Sarah Connor', '555-0199')")

    monkeypatch.setattr(services, "add_discussion", explode)
    response = client.post(url(lead.id), json={"note": "x"}, headers={"Origin": ORIGIN})
    assert response.status_code == 500
    assert response.json() == {
        "detail": "Internal server error",
        "code": "internal_error",
        "errors": [],
    }
    assert response.headers["access-control-allow-origin"] == ORIGIN
    for leaked in ("INSERT", "Sarah", "555-0199", "Traceback"):
        assert leaked not in response.text


def test_unreachable_database_is_503_with_cors(client: TestClient) -> None:
    unreachable = build_engine("postgresql+psycopg://u:leak_pw@127.0.0.1:1/leak_db")
    app.dependency_overrides[get_engine] = lambda: unreachable
    response = client.post(url(1), json={"note": "x"}, headers={"Origin": ORIGIN})
    assert response.status_code == 503
    assert response.json() == {
        "detail": "Database unavailable",
        "code": "database_unavailable",
        "errors": [],
    }
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert "leak_pw" not in response.text


# --- API documentation ---------------------------------------------------------------


def test_endpoint_is_documented() -> None:
    operation = app.openapi()["paths"]["/api/leads/{lead_id}/discussions"]["post"]
    assert set(operation["responses"]) == {"201", "404", "422"}
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/DiscussionCreate"
    }
    assert operation["responses"]["201"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/DiscussionCreated"
    }
