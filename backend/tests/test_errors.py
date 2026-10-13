"""The shared error envelope, exercised through the real app. No database needed."""

from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.db import build_engine, get_engine
from app.errors import LeadNotFound, is_connectivity_error
from app.main import app
from app.models import LeadStatus
from app.schemas import LeadCreate, LeadUpdate

ALLOWED_ORIGIN = "http://localhost:3000"
SECRET = "s3cret-internal-detail"
UNREACHABLE_DB_URL = f"postgresql+psycopg://leak_user:{SECRET}@127.0.0.1:1/leak_db"
SENSITIVE_NAME = "Sarah Connor-Leak"
SENSITIVE_PHONE = "555-0199-77"


def assert_envelope(body: dict, code: str) -> None:
    assert set(body) == {"detail", "code", "errors"}
    assert body["code"] == code
    assert isinstance(body["detail"], str) and body["detail"]
    assert isinstance(body["errors"], list)


@pytest.fixture
def client() -> Iterator[TestClient]:
    """The real app plus temporary routes that raise each kind of error."""

    def raise_not_found() -> None:
        raise LeadNotFound(7)

    def raise_runtime_error() -> None:
        raise RuntimeError(SECRET)

    def connect_to_unreachable_db() -> None:
        with build_engine(UNREACHABLE_DB_URL).connect() as connection:
            connection.execute(text("SELECT 1"))

    def raise_integrity_error() -> None:
        raise IntegrityError(
            f"INSERT INTO leads (name) VALUES ('{SECRET}')", {"name": SECRET}, Exception(SECRET)
        )

    def raise_pool_timeout() -> None:
        raise PoolTimeoutError(f"QueuePool limit reached {SECRET}")

    def fail_to_establish_connection() -> None:
        # What SQLAlchemy raises when psycopg cannot connect, for any reason
        # (refused, bad password, unknown database...): no statement, no SQLSTATE.
        raise OperationalError(None, None, psycopg.OperationalError("connection failed"))

    def fail_auth_after_connecting() -> None:
        # A server error with SQLSTATE 28P01 raised on an already-open connection.
        raise OperationalError("SELECT 1", {}, psycopg.errors.lookup("28P01")("auth failed"))

    def raise_error_with_bound_parameters() -> None:
        # Built exactly as SQLAlchemy's Connection builds statement errors, using
        # the application's engine configuration (hide_parameters) - no DB needed.
        raise DBAPIError.instance(
            "INSERT INTO leads (name, phone) VALUES (%(name)s, %(phone)s)",
            {"name": SENSITIVE_NAME, "phone": SENSITIVE_PHONE},
            psycopg.errors.lookup("23505")("duplicate key value"),
            psycopg.Error,
            hide_parameters=build_engine(UNREACHABLE_DB_URL).hide_parameters,
        )

    def create(body: LeadCreate) -> None: ...

    def update(body: LeadUpdate) -> None: ...

    def list_by_status(status: LeadStatus) -> None: ...

    routes_before = len(app.router.routes)
    app.get("/_test/not-found")(raise_not_found)
    app.get("/_test/runtime-error")(raise_runtime_error)
    app.get("/_test/db-unreachable")(connect_to_unreachable_db)
    app.get("/_test/db-integrity")(raise_integrity_error)
    app.get("/_test/pool-timeout")(raise_pool_timeout)
    app.get("/_test/db-connect-failed")(fail_to_establish_connection)
    app.get("/_test/db-auth-after-connect")(fail_auth_after_connecting)
    app.get("/_test/db-error-with-parameters")(raise_error_with_bound_parameters)
    app.post("/_test/leads")(create)
    app.patch("/_test/leads")(update)
    app.get("/_test/leads")(list_by_status)
    try:
        yield TestClient(app)
    finally:
        del app.router.routes[routes_before:]


# --- Validation (422) ---------------------------------------------------------


def test_validation_error_envelope_with_field_paths(client: TestClient) -> None:
    response = client.post("/_test/leads", json={"name": "  ", "phone": "abc", "status": "won"})
    assert response.status_code == 422
    body = response.json()
    assert_envelope(body, "validation_error")
    assert body["detail"] == "Validation failed"
    assert body["errors"] == [
        {"field": "name", "message": "Name is required"},
        {"field": "phone", "message": "String should match pattern '^[0-9+()\\-\\s]*$'"},
        {"field": "status", "message": "Extra inputs are not permitted"},
    ]


def test_missing_required_field_message(client: TestClient) -> None:
    body = client.post("/_test/leads", json={}).json()
    assert body["errors"] == [{"field": "name", "message": "Name is required"}]


def test_validation_messages_do_not_echo_input(client: TestClient) -> None:
    response = client.post("/_test/leads", json={"name": "a" * 121, "phone": SECRET})
    assert response.status_code == 422
    assert SECRET not in response.text
    assert "a" * 121 not in response.text


def test_value_error_message_has_no_pydantic_prefix(client: TestClient) -> None:
    body = client.patch("/_test/leads", json={"status": None}).json()
    assert body["errors"] == [{"field": "status", "message": "Status cannot be null"}]


def test_body_level_error_has_null_field(client: TestClient) -> None:
    response = client.patch("/_test/leads", json={})
    assert response.status_code == 422
    assert response.json()["errors"] == [
        {"field": None, "message": "Provide at least one of: status, next_follow_up_at"}
    ]


def test_malformed_json_has_null_field(client: TestClient) -> None:
    response = client.patch(
        "/_test/leads", content=b'{"status": ', headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    errors = response.json()["errors"]
    assert len(errors) == 1
    assert errors[0]["field"] is None


def test_query_parameter_error_uses_parameter_name(client: TestClient) -> None:
    response = client.get("/_test/leads", params={"status": "pending"})
    assert response.status_code == 422
    [error] = response.json()["errors"]
    assert error["field"] == "status"


# --- HTTP errors (404, 405) ---------------------------------------------------


def test_unknown_route_is_404_not_found(client: TestClient) -> None:
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not found", "code": "not_found", "errors": []}


def test_unsupported_method_is_405_and_keeps_allow_header(client: TestClient) -> None:
    response = client.delete("/api/health")
    assert response.status_code == 405
    assert response.json() == {
        "detail": "Method not allowed",
        "code": "method_not_allowed",
        "errors": [],
    }
    assert response.headers["allow"] == "GET"


def test_lead_not_found_is_404_lead_not_found(client: TestClient) -> None:
    response = client.get("/_test/not-found")
    assert response.status_code == 404
    assert response.json() == {"detail": "Lead not found", "code": "lead_not_found", "errors": []}


# --- Unexpected errors (500) --------------------------------------------------


def test_unexpected_error_is_generic_500_and_logged(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    response = client.get("/_test/runtime-error")
    assert response.status_code == 500
    assert response.json() == {
        "detail": "Internal server error",
        "code": "internal_error",
        "errors": [],
    }
    assert SECRET not in response.text
    assert "Traceback" not in response.text
    # The details go to the server log instead.
    assert any(r.exc_info and SECRET in str(r.exc_info[1]) for r in caplog.records)


def test_500_response_keeps_cors_headers(client: TestClient) -> None:
    response = client.get("/_test/runtime-error", headers={"Origin": ALLOWED_ORIGIN})
    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


def test_non_connectivity_database_error_is_500_without_sql(client: TestClient) -> None:
    response = client.get("/_test/db-integrity")
    assert response.status_code == 500
    assert_envelope(response.json(), "internal_error")
    assert SECRET not in response.text
    assert "INSERT" not in response.text


# --- Database unavailable (503) -----------------------------------------------


def test_unreachable_database_is_503_without_details(client: TestClient) -> None:
    response = client.get("/_test/db-unreachable", headers={"Origin": ALLOWED_ORIGIN})
    assert response.status_code == 503
    assert response.json() == {
        "detail": "Database unavailable",
        "code": "database_unavailable",
        "errors": [],
    }
    for leaked in (SECRET, "leak_user", "leak_db", "127.0.0.1"):
        assert leaked not in response.text
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


def test_pool_timeout_is_503(client: TestClient) -> None:
    response = client.get("/_test/pool-timeout")
    assert response.status_code == 503
    assert response.json()["code"] == "database_unavailable"
    assert SECRET not in response.text


def _wrapped(orig: Exception, *, invalidated: bool = False) -> OperationalError:
    return OperationalError("SELECT 1", {}, orig, connection_invalidated=invalidated)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (PoolTimeoutError("pool exhausted"), True),
        # Connection establishment: psycopg gives no SQLSTATE whatever the cause
        # (refused, bad password, unknown database), so all count as unavailable.
        (_wrapped(psycopg.OperationalError("connection failed")), True),
        (_wrapped(psycopg.OperationalError("closed"), invalidated=True), True),
        (_wrapped(psycopg.errors.lookup("08006")("connection failure")), True),
        (_wrapped(psycopg.errors.lookup("57P01")("admin shutdown")), True),
        (_wrapped(psycopg.errors.lookup("57P02")("crash shutdown")), True),
        (_wrapped(psycopg.errors.lookup("57P03")("cannot connect now")), True),
        # Server errors on an already-open connection, 28P01 included, are not outages.
        (_wrapped(psycopg.errors.lookup("28P01")("auth failed after connecting")), False),
        (_wrapped(psycopg.errors.lookup("57014")("query canceled")), False),
        (IntegrityError("INSERT", {}, psycopg.errors.lookup("23505")("duplicate")), False),
        (SQLAlchemyError("something else"), False),
    ],
)
def test_only_genuine_connectivity_failures_count_as_unavailable(
    exc: SQLAlchemyError, expected: bool
) -> None:
    assert is_connectivity_error(exc) is expected


def test_connection_establishment_failure_is_503(client: TestClient) -> None:
    # Covers configuration causes too (e.g. a wrong password): psycopg reports
    # them before any SQL runs, without a SQLSTATE, like a refused connection.
    response = client.get("/_test/db-connect-failed")
    assert response.status_code == 503
    assert response.json() == {
        "detail": "Database unavailable",
        "code": "database_unavailable",
        "errors": [],
    }


def test_auth_error_after_connecting_is_500(client: TestClient) -> None:
    response = client.get("/_test/db-auth-after-connect")
    assert response.status_code == 500
    assert response.json() == {
        "detail": "Internal server error",
        "code": "internal_error",
        "errors": [],
    }


# --- Logging of database errors -----------------------------------------------


def test_engines_hide_bound_parameters() -> None:
    assert build_engine(UNREACHABLE_DB_URL).hide_parameters is True
    assert get_engine().hide_parameters is True


def test_database_error_log_keeps_traceback_but_hides_parameters(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    response = client.get("/_test/db-error-with-parameters")
    assert response.status_code == 500
    assert SENSITIVE_NAME not in response.text

    logged = caplog.text  # includes the formatted traceback
    assert "Traceback" in logged
    assert "IntegrityError" in logged
    assert "INSERT INTO leads" in logged  # the SQL stays available for debugging
    assert "SQL parameters hidden" in logged
    assert SENSITIVE_NAME not in logged
    assert SENSITIVE_PHONE not in logged
