import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Connection, Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

# app.main loads settings at import time; give tests a harmless default so they
# do not depend on a developer's .env. Nothing listens on port 1.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1:1/test")

from app.config import ROOT_ENV_FILE  # noqa: E402
from app.db import build_engine  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]


class TestDatabaseSettings(BaseSettings):
    """TEST_DATABASE_URL from the environment or the repository-root .env."""

    __test__ = False  # not a pytest test class
    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE, extra="ignore", hide_input_in_errors=True
    )

    test_database_url: str | None = None


def alembic_config(connection: Connection) -> Config:
    """Alembic config that migrates over the given connection (the test database)."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    """Engine for the dedicated test database, migrated to the latest revision.

    Fails (never skips) when TEST_DATABASE_URL is missing or unreachable, so a
    run without PostgreSQL cannot be mistaken for a passing one.
    """
    url = TestDatabaseSettings().test_database_url
    if not url:
        pytest.fail(
            "TEST_DATABASE_URL is not set. PostgreSQL tests need the dedicated "
            "leadflow_test database; see README.md > Checks.",
            pytrace=False,
        )
    database = make_url(url).database or ""
    if not database.endswith("_test"):
        # These tests drop and recreate tables: refuse anything but a test database.
        pytest.fail(
            f"Refusing to run: TEST_DATABASE_URL database {database!r} must end in '_test'.",
            pytrace=False,
        )

    engine = build_engine(url)
    connect_error: str | None = None
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        # Keep only the type: the driver's message includes connection details.
        connect_error = type(exc).__name__
    if connect_error:
        engine.dispose()
        pytest.fail(
            f"Cannot connect to the test database {database!r} ({connect_error}). "
            "Start PostgreSQL with `docker compose up -d db`.",
            pytrace=False,
        )

    # Start from a known state: remove anything left over, then apply all migrations.
    with engine.begin() as connection:
        config = alembic_config(connection)
        command.downgrade(config, "base")
        command.upgrade(config, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def make_alembic_config() -> Callable[[Connection], Config]:
    return alembic_config


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """A session on an emptied test database; each test starts with no rows."""
    with db_engine.begin() as connection:
        connection.execute(text("TRUNCATE leads, discussions RESTART IDENTITY CASCADE"))
    with Session(db_engine) as session:
        yield session
