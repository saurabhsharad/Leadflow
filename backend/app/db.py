from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.config import get_settings

# Seconds to wait for a PostgreSQL connection before giving up, so requests
# such as the health check fail fast instead of hanging when the DB is down.
CONNECT_TIMEOUT_SECONDS = 3


def build_engine(database_url: str) -> Engine:
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_timeout=CONNECT_TIMEOUT_SECONDS,
        connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS},
        # Keep bound values (lead names, phone numbers, notes) out of exception
        # text and therefore out of logged tracebacks; the SQL itself remains.
        hide_parameters=True,
    )


@lru_cache
def get_engine() -> Engine:
    return build_engine(get_settings().database_url)


def get_db(engine: Annotated[Engine, Depends(get_engine)]) -> Iterator[Session]:
    """One session per request, closed afterwards.

    It never commits: services commit once per write. Closing the session
    rolls back anything uncommitted, e.g. after an exception mid-request.
    """
    with Session(engine) as session:
        yield session
