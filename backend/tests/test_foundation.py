import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.db import build_engine, get_engine
from app.main import app

UNREACHABLE_DB_URL = "postgresql+psycopg://leak_user:leak_password@127.0.0.1:1/leak_db"


def test_health_returns_503_without_leaking_details_when_database_is_down() -> None:
    app.dependency_overrides[get_engine] = lambda: build_engine(UNREACHABLE_DB_URL)
    try:
        response = TestClient(app).get("/api/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Database unavailable",
        "code": "database_unavailable",
        "errors": [],
    }
    for secret in ("leak_user", "leak_password", "leak_db", "127.0.0.1"):
        assert secret not in response.text


@pytest.mark.parametrize(
    "database_url",
    [
        "MARKER_USER:MARKER_PASSWORD not a url",
        "postgresql+psycopg://MARKER_USER:MARKER_PASSWORD@localhost:notaport/db",
        "postgresx://MARKER_USER:MARKER_PASSWORD@localhost:5432/db",
    ],
)
def test_malformed_database_url_is_rejected_without_leaking_it(database_url: str) -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL") as exc_info:
        Settings(database_url=database_url)

    error_text = str(exc_info.value)
    for secret in ("MARKER_USER", "MARKER_PASSWORD", "localhost"):
        assert secret not in error_text


def test_valid_database_url_is_accepted() -> None:
    url = "postgresql+psycopg://leadflow:pw@localhost:5433/leadflow"
    assert Settings(database_url=url).database_url == url


VALID_DB_URL = "postgresql+psycopg://x@y/z"


def test_timezone_defaults_to_asia_kolkata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_TIMEZONE", raising=False)
    assert Settings(_env_file=None, database_url=VALID_DB_URL).app_timezone == "Asia/Kolkata"


@pytest.mark.parametrize("timezone", ["Asia/Kolkata", "UTC"])
def test_canonical_timezone_is_accepted(timezone: str) -> None:
    assert Settings(database_url=VALID_DB_URL, app_timezone=timezone).app_timezone == timezone


@pytest.mark.parametrize("timezone", ["asia/kolkata", "ASIA/KOLKATA", "utc"])
def test_noncanonical_timezone_casing_is_rejected_with_suggestion(timezone: str) -> None:
    with pytest.raises(ValidationError, match="did you mean") as exc_info:
        Settings(database_url=VALID_DB_URL, app_timezone=timezone)
    assert "Unknown IANA timezone" in str(exc_info.value)


@pytest.mark.parametrize("timezone", ["Mars/Olympus", "", "../etc/passwd"])
def test_unknown_timezone_is_rejected(timezone: str) -> None:
    with pytest.raises(ValidationError, match="Unknown IANA timezone"):
        Settings(database_url=VALID_DB_URL, app_timezone=timezone)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://localhost:3000", ["http://localhost:3000"]),
        (
            " http://localhost:3000 , http://127.0.0.1:3000 ",
            ["http://localhost:3000", "http://127.0.0.1:3000"],
        ),
    ],
)
def test_cors_origins_are_parsed(raw: str, expected: list[str]) -> None:
    assert Settings(database_url=VALID_DB_URL, cors_origins=raw).cors_origins == expected


@pytest.mark.parametrize("raw", ["", "   ", " , ,"])
def test_empty_cors_origins_are_rejected(raw: str) -> None:
    with pytest.raises(ValidationError, match="at least one origin"):
        Settings(database_url=VALID_DB_URL, cors_origins=raw)


@pytest.mark.parametrize("raw", ["*", "http://localhost:3000, *"])
def test_wildcard_cors_origin_is_rejected(raw: str) -> None:
    with pytest.raises(ValidationError, match="Wildcard"):
        Settings(database_url=VALID_DB_URL, cors_origins=raw)
