"""Cross-endpoint integration and contract checks (specification sections 6, 8, 9, 11).

Everything here goes through HTTP only: data is created by the API itself, the
clock is fixed, and the database is the PostgreSQL test database.
"""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.clock import get_now
from app.db import build_engine, get_engine
from app.main import app
from app.services import leads as services

NOW = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)  # 20:30 IST, the specification's clock
ORIGIN = "http://localhost:3000"
ERROR_KEYS = {"detail", "code", "errors"}


@pytest.fixture
def client(db_session: Session, db_engine: Engine) -> Iterator[TestClient]:
    """The real app on the test database with a fixed clock; tables start empty."""
    app.dependency_overrides[get_engine] = lambda: db_engine
    app.dependency_overrides[get_now] = lambda: NOW
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def create(client: TestClient, name: str, **fields: object) -> int:
    response = client.post("/api/leads", json={"name": name, **fields})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def log(client: TestClient, lead_id: int, note: str, follow_up_at: str | None = None) -> dict:
    payload = (
        {"note": note} if follow_up_at is None else {"note": note, "follow_up_at": follow_up_at}
    )
    response = client.post(f"/api/leads/{lead_id}/discussions", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def patch(client: TestClient, lead_id: int, **fields: object) -> dict:
    response = client.patch(f"/api/leads/{lead_id}", json=fields)
    assert response.status_code == 200, response.text
    return response.json()


def dashboard(client: TestClient, **params: str) -> list[tuple[str, bool, bool]]:
    """(name, due_today, overdue) in list order."""
    response = client.get("/api/leads", params=params)
    assert response.status_code == 200
    return [(r["name"], r["follow_up_due_today"], r["follow_up_overdue"]) for r in response.json()]


# --- Health -----------------------------------------------------------------------


def test_health_is_200_when_postgres_answers(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


# --- Dashboard driven entirely by API writes (spec section 6) ------------------------


def test_api_writes_move_leads_between_dashboard_groups(client: TestClient) -> None:
    acme = create(client, "Acme")
    beta = create(client, "Beta")
    core = create(client, "Core")
    # No discussions, no follow-ups: newest created first.
    assert dashboard(client) == [
        ("Core", False, False),
        ("Beta", False, False),
        ("Acme", False, False),
    ]

    # A note with a follow-up later today pins the lead into Today's group.
    log(client, acme, "Call booked", "2026-10-13T21:00:00+05:30")
    # A note without a follow-up moves Beta ahead of leads without discussions.
    log(client, beta, "Sent brochure")
    assert dashboard(client) == [
        ("Acme", True, False),  # today
        ("Beta", False, False),  # has a discussion
        ("Core", False, False),  # no discussions
    ]

    # A follow-up on an earlier day goes to the top, overdue.
    patch(client, core, next_follow_up_at="2026-10-12T16:00:00+05:30")
    assert dashboard(client)[0] == ("Core", False, True)

    # Rescheduling Acme to tomorrow takes it out of Today; its history keeps both dates.
    log(client, acme, "Moved to tomorrow", "2026-10-14T11:00:00+05:30")
    # Clearing Core's follow-up returns it to All Leads (still no discussions: last).
    cleared = patch(client, core, next_follow_up_at=None)
    assert cleared["next_follow_up_at"] is None
    assert dashboard(client) == [
        ("Acme", False, False),  # newest discussion
        ("Beta", False, False),
        ("Core", False, False),
    ]

    detail = client.get(f"/api/leads/{acme}").json()
    assert detail["next_follow_up_at"] == "2026-10-14T05:30:00Z"
    assert [(d["note"], d["follow_up_at"]) for d in detail["discussions"]] == [
        ("Moved to tomorrow", "2026-10-14T05:30:00Z"),
        ("Call booked", "2026-10-13T15:30:00Z"),
    ]


def test_follow_up_in_any_offset_is_stored_as_the_same_instant(client: TestClient) -> None:
    lead = create(client, "Offsets")
    # 10:00 in New York (-05:00) on 13 Oct is 15:00 UTC = 20:30 IST: exactly "now".
    body = patch(client, lead, next_follow_up_at="2026-10-13T10:00:00-05:00")
    assert body["next_follow_up_at"] == "2026-10-13T15:00:00Z"
    assert (body["follow_up_due_today"], body["follow_up_overdue"]) == (True, False)


def test_status_and_search_filters_keep_group_order(client: TestClient) -> None:
    rows = [
        ("Sarah Old", "qualified", "2026-10-11T09:00:00+05:30"),  # earlier day
        ("Farah Today", "qualified", "2026-10-13T22:00:00+05:30"),  # today
        ("Sarah Plain", "qualified", None),
        ("Sarah Lost", "lost", "2026-10-13T09:00:00+05:30"),  # today, other status
        ("John Old", "qualified", "2026-10-10T09:00:00+05:30"),  # earlier day
    ]
    for name, status, follow_up in rows:
        lead = create(client, name)
        fields: dict[str, object] = {"status": status}
        if follow_up:
            fields["next_follow_up_at"] = follow_up
        patch(client, lead, **fields)

    everything = [name for name, *_ in dashboard(client)]

    def filtered(**params: str) -> list[str]:
        return [name for name, *_ in dashboard(client, **params)]

    def expected(keep) -> list[str]:  # noqa: ANN001
        return [name for name in everything if keep(name)]

    by_status = {name: status for name, status, _ in rows}
    assert filtered(status="qualified") == expected(lambda n: by_status[n] == "qualified")
    assert filtered(q="sarah") == expected(lambda n: "sarah" in n.lower())
    assert filtered(status="qualified", q="rah") == expected(
        lambda n: by_status[n] == "qualified" and "rah" in n.lower()
    )
    assert filtered(status="qualified", q="rah") == ["Sarah Old", "Farah Today", "Sarah Plain"]


# --- Error envelope on every endpoint -------------------------------------------------

ENDPOINTS = [
    ("GET", "/api/leads", None),
    ("POST", "/api/leads", {"name": "A"}),
    ("GET", "/api/leads/1", None),
    ("PATCH", "/api/leads/1", {"status": "won"}),
    ("POST", "/api/leads/1/discussions", {"note": "x"}),
]


@pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS)
def test_every_endpoint_returns_503_envelope_when_database_is_down(
    client: TestClient, method: str, path: str, body: dict | None
) -> None:
    unreachable = build_engine("postgresql+psycopg://u:leak_pw@127.0.0.1:1/leak_db")
    app.dependency_overrides[get_engine] = lambda: unreachable
    response = client.request(method, path, json=body, headers={"Origin": ORIGIN})
    assert response.status_code == 503
    assert response.json() == {
        "detail": "Database unavailable",
        "code": "database_unavailable",
        "errors": [],
    }
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert "leak_pw" not in response.text


@pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS[2:])
def test_every_lead_endpoint_returns_the_same_404_envelope(
    client: TestClient, method: str, path: str, body: dict | None
) -> None:
    response = client.request(method, path, json=body)
    assert response.status_code == 404
    assert response.json() == {"detail": "Lead not found", "code": "lead_not_found", "errors": []}


# --- Browser access (spec section 11) -----------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", "/api/leads"), ("PATCH", "/api/leads/1"), ("POST", "/api/leads/1/discussions")],
)
def test_cors_preflight_allows_json_writes_from_the_frontend(
    client: TestClient, method: str, path: str
) -> None:
    response = client.options(
        path,
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert method in response.headers["access-control-allow-methods"]
    assert "content-type" in response.headers["access-control-allow-headers"].lower()


def test_cors_rejects_other_origins(client: TestClient) -> None:
    preflight = client.options(
        "/api/leads",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in preflight.headers
    simple = client.get("/api/leads", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in simple.headers


# --- Request-scoped sessions (spec section 9) -----------------------------------------


def test_request_sessions_are_released_after_success_and_errors(
    client: TestClient, db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    lead = create(client, "Pool")
    log(client, lead, "note")
    client.get("/api/leads")
    client.get(f"/api/leads/{lead}")
    client.get("/api/leads/999")  # 404 from the service
    client.patch(f"/api/leads/{lead}", json={})  # 422 before the service

    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(services, "list_leads", explode)
    assert client.get("/api/leads").status_code == 500

    assert db_engine.pool.checkedout() == 0


# --- API documentation (spec section 8) ------------------------------------------------


def test_openapi_documents_exactly_the_specified_endpoints() -> None:
    spec = app.openapi()
    operations = {
        (method.upper(), path): sorted(op["responses"])
        for path, methods in spec["paths"].items()
        for method, op in methods.items()
    }
    assert operations == {
        ("GET", "/api/health"): ["200", "503"],
        ("GET", "/api/leads"): ["200", "422"],
        ("POST", "/api/leads"): ["201", "422"],
        ("GET", "/api/leads/{lead_id}"): ["200", "404", "422"],
        ("PATCH", "/api/leads/{lead_id}"): ["200", "404", "422"],
        ("POST", "/api/leads/{lead_id}/discussions"): ["201", "404", "422"],
    }

    schemas = spec["components"]["schemas"]
    assert schemas["LeadStatus"]["enum"] == [
        "new",
        "contacted",
        "qualified",
        "proposal_sent",
        "won",
        "lost",
    ]
    assert set(schemas["ErrorResponse"]["properties"]) == ERROR_KEYS
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            for code, response in op["responses"].items():
                if code.startswith(("4", "5")):
                    schema = response["content"]["application/json"]["schema"]
                    assert schema == {"$ref": "#/components/schemas/ErrorResponse"}, (
                        method,
                        path,
                        code,
                    )
    assert set(schemas["LeadSummary"]["required"]) == {
        "id",
        "name",
        "company",
        "phone",
        "status",
        "next_follow_up_at",
        "follow_up_due_today",
        "follow_up_overdue",
        "last_discussion",
        "created_at",
        "updated_at",
    }
    assert schemas["LeadCreate"]["additionalProperties"] is False
    assert schemas["LeadUpdate"]["additionalProperties"] is False
    assert schemas["DiscussionCreate"]["additionalProperties"] is False


def test_docs_are_served(client: TestClient) -> None:
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200
