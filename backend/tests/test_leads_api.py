"""Lead endpoints end to end: HTTP -> router -> services -> PostgreSQL test database."""

from collections.abc import Iterator
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.exc import DataError
from sqlalchemy.orm import Session

from app.clock import get_now
from app.db import build_engine, get_engine
from app.main import app
from app.models import Discussion, Lead, LeadStatus
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


def seed_lead(session: Session, name: str, **fields: object) -> Lead:
    lead = Lead(name=name, **fields)
    session.add(lead)
    session.commit()
    return lead


def seed_discussion(
    session: Session, lead: Lead, note: str, created_at: datetime, **fields: object
) -> Discussion:
    discussion = Discussion(lead_id=lead.id, note=note, created_at=created_at, **fields)
    session.add(discussion)
    session.commit()
    return discussion


def error_fields(response) -> list[str | None]:  # noqa: ANN001
    body = response.json()
    assert set(body) == {"detail", "code", "errors"}
    assert body["code"] == "validation_error"
    return [e["field"] for e in body["errors"]]


# --- GET /api/leads -----------------------------------------------------------


def test_list_empty(client: TestClient) -> None:
    response = client.get("/api/leads")
    assert response.status_code == 200
    assert response.json() == []


def test_list_summary_fields_flags_and_latest_discussion(
    client: TestClient, db_session: Session
) -> None:
    lead = seed_lead(
        db_session,
        "Sarah Connor",
        company="Acme Corp",
        phone="555-0199",
        status=LeadStatus.PROPOSAL_SENT,
        next_follow_up_at=ist(13, 14),
        created_at=ist(8, 16),
        updated_at=ist(11, 10, 30),
    )
    seed_discussion(db_session, lead, "older", ist(10, 9))
    seed_discussion(db_session, lead, "Sent pricing tier PDF.", ist(11, 10, 30))

    assert client.get("/api/leads").json() == [
        {
            "id": lead.id,
            "name": "Sarah Connor",
            "company": "Acme Corp",
            "phone": "555-0199",
            "status": "proposal_sent",
            "next_follow_up_at": "2026-10-13T08:30:00Z",
            "follow_up_due_today": True,
            "follow_up_overdue": True,
            "last_discussion": {
                "note": "Sent pricing tier PDF.",
                "created_at": "2026-10-11T05:00:00Z",
            },
            "created_at": "2026-10-08T10:30:00Z",
            "updated_at": "2026-10-11T05:00:00Z",
        }
    ]


def test_list_order_is_deterministic(client: TestClient, db_session: Session) -> None:
    created = ist(1, 9)
    seed_lead(db_session, "no notes", created_at=created)
    noted = seed_lead(db_session, "noted", created_at=created)
    seed_discussion(db_session, noted, "a", ist(12, 9))
    seed_lead(db_session, "today", created_at=created, next_follow_up_at=ist(13, 22))
    seed_lead(db_session, "yesterday", created_at=created, next_follow_up_at=ist(12, 9))
    tied = seed_lead(db_session, "tied newer id", created_at=created)
    seed_discussion(db_session, tied, "b", ist(12, 9))

    names = [lead["name"] for lead in client.get("/api/leads").json()]
    assert names == ["yesterday", "today", "tied newer id", "noted", "no notes"]
    assert names == [lead["name"] for lead in client.get("/api/leads").json()]


def test_list_filters_by_status(client: TestClient, db_session: Session) -> None:
    seed_lead(db_session, "A", status=LeadStatus.WON)
    seed_lead(db_session, "B", status=LeadStatus.LOST)
    response = client.get("/api/leads", params={"status": "won"})
    assert [lead["name"] for lead in response.json()] == ["A"]


@pytest.mark.parametrize("value", ["Won", "pending", ""])
def test_list_rejects_invalid_status(client: TestClient, value: str) -> None:
    response = client.get("/api/leads", params={"status": value})
    assert response.status_code == 422
    assert error_fields(response) == ["status"]


def test_list_search_is_case_insensitive_trimmed_and_combinable(
    client: TestClient, db_session: Session
) -> None:
    seed_lead(db_session, "Sarah Connor", status=LeadStatus.QUALIFIED)
    seed_lead(db_session, "Farah Khan", status=LeadStatus.NEW)
    seed_lead(db_session, "John Smith", status=LeadStatus.QUALIFIED)

    def names(**params: str) -> list[str]:
        return sorted(lead["name"] for lead in client.get("/api/leads", params=params).json())

    assert names(q="RAH") == ["Farah Khan", "Sarah Connor"]
    assert names(q="  rah  ") == ["Farah Khan", "Sarah Connor"]
    assert names(q="rah", status="qualified") == ["Sarah Connor"]
    assert names(q="   ") == ["Farah Khan", "John Smith", "Sarah Connor"]  # blank = no filter


def test_list_search_treats_wildcards_literally(client: TestClient, db_session: Session) -> None:
    seed_lead(db_session, "100% Leads")
    seed_lead(db_session, "Plain_Name")
    seed_lead(db_session, "PlainXName")
    assert [r["name"] for r in client.get("/api/leads", params={"q": "%"}).json()] == ["100% Leads"]
    assert [r["name"] for r in client.get("/api/leads", params={"q": "n_n"}).json()] == [
        "Plain_Name"
    ]


def test_list_search_length_is_checked_after_trimming(client: TestClient) -> None:
    assert client.get("/api/leads", params={"q": "x" * 100}).status_code == 200
    assert client.get("/api/leads", params={"q": f"  {'x' * 100}  "}).status_code == 200
    response = client.get("/api/leads", params={"q": "x" * 101})
    assert response.status_code == 422
    assert error_fields(response) == ["q"]


# --- POST /api/leads ----------------------------------------------------------


def test_create_lead(client: TestClient) -> None:
    response = client.post(
        "/api/leads", json={"name": "  Kyle Reese ", "company": "", "phone": "555-0100"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["id"] == 1
    assert {k: body[k] for k in ("name", "company", "phone", "status")} == {
        "name": "Kyle Reese",
        "company": None,
        "phone": "555-0100",
        "status": "new",
    }
    assert body["next_follow_up_at"] is None
    assert (body["follow_up_due_today"], body["follow_up_overdue"]) == (False, False)
    assert body["last_discussion"] is None
    assert body["created_at"].endswith("Z")
    assert body["created_at"] == body["updated_at"]
    assert client.get("/api/leads/1").status_code == 200


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({}, "name"),
        ({"name": ""}, "name"),
        ({"name": "   "}, "name"),
        ({"name": "A", "phone": "555-CALL"}, "phone"),
        ({"name": "A", "status": "won"}, "status"),
        ({"name": "A", "email": "a@example.com"}, "email"),
        ({"name": "A", "id": 5}, "id"),
    ],
)
def test_create_lead_rejects_invalid_input(client: TestClient, payload: dict, field: str) -> None:
    response = client.post("/api/leads", json=payload)
    assert response.status_code == 422
    assert error_fields(response) == [field]
    assert client.get("/api/leads").json() == []


def test_create_lead_blank_name_message(client: TestClient) -> None:
    response = client.post("/api/leads", json={"name": "  "})
    assert response.json() == {
        "detail": "Validation failed",
        "code": "validation_error",
        "errors": [{"field": "name", "message": "Name is required"}],
    }


# --- GET /api/leads/{lead_id} -------------------------------------------------


def test_get_lead_without_discussions(client: TestClient, db_session: Session) -> None:
    lead = seed_lead(db_session, "A")
    body = client.get(f"/api/leads/{lead.id}").json()
    assert body["id"] == lead.id
    assert body["discussions"] == []
    assert body["last_discussion"] is None


def test_get_lead_with_history_newest_first(client: TestClient, db_session: Session) -> None:
    lead = seed_lead(db_session, "A")
    seed_discussion(db_session, lead, "oldest", ist(10, 9))
    first = seed_discussion(db_session, lead, "tie, lower id", ist(11, 9))
    second = seed_discussion(
        db_session, lead, "tie, higher id", ist(11, 9), follow_up_at=ist(14, 11)
    )

    response = client.get(f"/api/leads/{lead.id}")
    assert response.status_code == 200
    body = response.json()
    assert [d["note"] for d in body["discussions"]] == ["tie, higher id", "tie, lower id", "oldest"]
    assert body["discussions"][0] == {
        "id": second.id,
        "note": "tie, higher id",
        "follow_up_at": iso_utc(ist(14, 11)),
        "created_at": iso_utc(ist(11, 9)),
    }
    assert body["discussions"][1]["id"] == first.id
    assert body["last_discussion"] == {"note": "tie, higher id", "created_at": iso_utc(ist(11, 9))}


def test_get_missing_lead_is_404_envelope(client: TestClient) -> None:
    response = client.get("/api/leads/999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Lead not found", "code": "lead_not_found", "errors": []}


@pytest.mark.parametrize("lead_id", ["abc", "0", "-1", "1.5", str(MAX_LEAD_ID + 1)])
def test_get_lead_rejects_invalid_id(client: TestClient, lead_id: str) -> None:
    response = client.get(f"/api/leads/{lead_id}")
    assert response.status_code == 422
    assert error_fields(response) == ["lead_id"]


def test_largest_valid_id_is_a_clean_404(client: TestClient) -> None:
    assert client.get(f"/api/leads/{MAX_LEAD_ID}").json()["code"] == "lead_not_found"


def test_ids_beyond_postgres_integer_would_fail_in_the_database(db_session: Session) -> None:
    # Why the path parameter has an upper bound: PostgreSQL rejects the value.
    with pytest.raises(DataError):
        services.get_lead(db_session, MAX_LEAD_ID + 1, NOW, IST)


# --- PATCH /api/leads/{lead_id} -----------------------------------------------


def test_patch_status_keeps_omitted_follow_up(client: TestClient, db_session: Session) -> None:
    lead = seed_lead(db_session, "A", next_follow_up_at=ist(14, 11))
    response = client.patch(f"/api/leads/{lead.id}", json={"status": "contacted"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "contacted"
    assert body["next_follow_up_at"] == iso_utc(ist(14, 11))
    assert client.get(f"/api/leads/{lead.id}").json()["status"] == "contacted"


def test_patch_sets_follow_up_and_flags(client: TestClient, db_session: Session) -> None:
    lead = seed_lead(db_session, "A", status=LeadStatus.QUALIFIED)
    response = client.patch(
        f"/api/leads/{lead.id}", json={"next_follow_up_at": "2026-10-13T14:00:00+05:30"}
    )
    body = response.json()
    assert body["next_follow_up_at"] == "2026-10-13T08:30:00Z"
    assert (body["follow_up_due_today"], body["follow_up_overdue"]) == (True, True)
    assert body["status"] == "qualified"


def test_patch_explicit_null_clears_follow_up(client: TestClient, db_session: Session) -> None:
    lead = seed_lead(db_session, "A", status=LeadStatus.WON, next_follow_up_at=ist(12, 9))
    body = client.patch(f"/api/leads/{lead.id}", json={"next_follow_up_at": None}).json()
    assert body["next_follow_up_at"] is None
    assert (body["follow_up_due_today"], body["follow_up_overdue"]) == (False, False)
    assert body["status"] == "won"


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({}, None),  # empty body
        ({"status": None}, "status"),
        ({"status": "pending"}, "status"),
        ({"next_follow_up_at": "2026-10-13T14:00:00"}, "next_follow_up_at"),  # naive
        ({"next_follow_up_at": "not a date"}, "next_follow_up_at"),
        ({"name": "Renamed"}, "name"),
        ({"status": "won", "updated_at": "2026-10-13T14:00:00Z"}, "updated_at"),
    ],
)
def test_patch_rejects_invalid_input(
    client: TestClient, db_session: Session, payload: dict, field: str | None
) -> None:
    lead = seed_lead(db_session, "A", next_follow_up_at=ist(14, 11))
    response = client.patch(f"/api/leads/{lead.id}", json=payload)
    assert response.status_code == 422
    assert error_fields(response) == [field]
    unchanged = client.get(f"/api/leads/{lead.id}").json()
    assert (unchanged["name"], unchanged["status"]) == ("A", "new")
    assert unchanged["next_follow_up_at"] == iso_utc(ist(14, 11))


def test_patch_unknown_lead_is_404(client: TestClient) -> None:
    response = client.patch("/api/leads/999", json={"status": "won"})
    assert response.status_code == 404
    assert response.json()["code"] == "lead_not_found"


# --- Error contract -----------------------------------------------------------


def test_unknown_route_and_method(client: TestClient) -> None:
    response = client.get("/api/leads/1/unknown")
    assert (response.status_code, response.json()["code"]) == (404, "not_found")

    response = client.delete("/api/leads/1")
    assert response.status_code == 405
    assert response.json() == {
        "detail": "Method not allowed",
        "code": "method_not_allowed",
        "errors": [],
    }
    # Starlette fills Allow from the first route matching the path only, so it
    # lists GET but not PATCH (a known framework limitation, not our handler).
    assert "GET" in response.headers["allow"].split(", ")


def test_unexpected_error_is_generic_500_with_cors(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("SELECT secret FROM leads -- Sarah Connor 555-0199")

    monkeypatch.setattr(services, "list_leads", explode)
    response = client.get("/api/leads", headers={"Origin": ORIGIN})
    assert response.status_code == 500
    assert response.json() == {
        "detail": "Internal server error",
        "code": "internal_error",
        "errors": [],
    }
    assert response.headers["access-control-allow-origin"] == ORIGIN
    for leaked in ("SELECT", "Sarah", "555-0199", "Traceback"):
        assert leaked not in response.text


def test_failed_request_commits_nothing(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The request session is closed without committing when a request fails."""
    lead = seed_lead(db_session, "A", next_follow_up_at=ist(14, 11))

    def change_then_fail(session: Session, lead_id: int, *_args: object) -> None:
        row = session.get(Lead, lead_id)
        row.status = LeadStatus.LOST
        row.next_follow_up_at = None
        session.flush()  # sent to PostgreSQL inside the request's transaction...
        raise RuntimeError("failure before commit")  # ...but never committed

    monkeypatch.setattr(services, "update_lead", change_then_fail)
    response = client.patch(f"/api/leads/{lead.id}", json={"status": "lost"})
    assert response.status_code == 500

    monkeypatch.undo()
    body = client.get(f"/api/leads/{lead.id}").json()
    assert body["status"] == "new"
    assert body["next_follow_up_at"] == iso_utc(ist(14, 11))


def test_unreachable_database_is_503(client: TestClient) -> None:
    unreachable = build_engine("postgresql+psycopg://u:leak_pw@127.0.0.1:1/leak_db")
    app.dependency_overrides[get_engine] = lambda: unreachable
    response = client.get("/api/leads", headers={"Origin": ORIGIN})
    assert response.status_code == 503
    assert response.json() == {
        "detail": "Database unavailable",
        "code": "database_unavailable",
        "errors": [],
    }
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert "leak_pw" not in response.text
