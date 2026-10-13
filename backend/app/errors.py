"""One error envelope for every non-2xx response (see the specification, section 8).

    {"detail": "Validation failed", "code": "validation_error",
     "errors": [{"field": "name", "message": "Name is required"}]}

`errors` lists field problems for 422 responses and is empty otherwise. Bodies
never contain exception messages, SQL, stack traces or connection details;
unexpected errors are logged server-side only.
"""

import logging
from collections.abc import Awaitable, Callable
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.exc import DBAPIError, OperationalError, SQLAlchemyError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.exceptions import HTTPException

logger = logging.getLogger(__name__)

# Request locations FastAPI prefixes to validation error paths.
_LOCATION_PREFIXES = {"body", "query", "path", "header", "cookie"}
# PostgreSQL SQLSTATEs that mean the server is unreachable or going away:
# class 08 (connection exception) and 57P01-57P03 (shutdown, cannot connect now).
_CONNECTION_SQLSTATE_CLASS = "08"
_SHUTDOWN_SQLSTATES = {"57P01", "57P02", "57P03"}
_HTTP_ERROR_CODES = {404: "not_found", 405: "method_not_allowed"}


class ErrorItem(BaseModel):
    field: str | None
    message: str


class ErrorResponse(BaseModel):
    detail: str
    code: str
    errors: list[ErrorItem] = []


class LeadNotFound(Exception):
    """Raised by services when a lead id does not exist; becomes a 404."""

    def __init__(self, lead_id: int) -> None:
        super().__init__(f"Lead {lead_id} not found")
        self.lead_id = lead_id


def error_response(
    status_code: int,
    code: str,
    detail: str,
    errors: list[ErrorItem] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(detail=detail, code=code, errors=errors or [])
    return JSONResponse(body.model_dump(), status_code=status_code, headers=headers)


def database_unavailable_response() -> JSONResponse:
    return error_response(503, "database_unavailable", "Database unavailable")


def internal_error_response() -> JSONResponse:
    return error_response(500, "internal_error", "Internal server error")


def is_connectivity_error(exc: SQLAlchemyError) -> bool:
    """True when no usable database connection could be obtained or it dropped.

    This includes every failure while *establishing* a connection, whatever the
    cause (see below), so a misconfiguration can also surface as a 503.
    """
    if isinstance(exc, PoolTimeoutError):
        return True
    if not isinstance(exc, DBAPIError):
        return False
    if exc.connection_invalidated:
        return True
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if sqlstate is None:
        # psycopg raises a bare OperationalError without a SQLSTATE when a
        # connection cannot be established: refused, timed out, closed
        # unexpectedly, but also wrong credentials, an unknown database or a
        # TLS failure, since libpq reports these before any SQL runs. We treat
        # them all as "database unavailable" rather than parse message text.
        return isinstance(exc, OperationalError)
    return sqlstate.startswith(_CONNECTION_SQLSTATE_CLASS) or sqlstate in _SHUTDOWN_SQLSTATES


def _field_path(loc: tuple[int | str, ...], error_type: str) -> str | None:
    """("body", "items", 0, "note") -> "items.0.note"; body-level errors -> None."""
    if error_type == "json_invalid":
        return None  # the location is a character offset, not a field
    parts = list(loc)
    if parts and parts[0] in _LOCATION_PREFIXES:
        parts = parts[1:]
    return ".".join(str(part) for part in parts) or None


def _validation_message(error: dict[str, Any], field: str | None) -> str:
    error_type = error["type"]
    ctx = error.get("ctx", {})
    if field and (
        error_type == "missing" or (error_type == "string_too_short" and ctx.get("min_length") == 1)
    ):
        label = field.rsplit(".", 1)[-1].replace("_", " ").capitalize()
        return f"{label} is required"
    if error_type == "value_error" and "error" in ctx:
        return str(ctx["error"])  # our own ValueError message, without "Value error, "
    return error["msg"]


async def handle_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = []
    for error in exc.errors():
        field = _field_path(tuple(error["loc"]), error["type"])
        errors.append(ErrorItem(field=field, message=_validation_message(error, field)))
    return error_response(422, "validation_error", "Validation failed", errors)


async def handle_http_exception(_request: Request, exc: HTTPException) -> JSONResponse:
    # Framework errors such as unknown routes (404) and wrong methods (405);
    # the status code and headers (e.g. Allow) are preserved.
    try:
        detail = HTTPStatus(exc.status_code).phrase.capitalize()
    except ValueError:  # non-standard status code
        detail = "Request failed"
    code = _HTTP_ERROR_CODES.get(exc.status_code, "http_error")
    return error_response(exc.status_code, code, detail, headers=getattr(exc, "headers", None))


async def handle_lead_not_found(_request: Request, _exc: LeadNotFound) -> JSONResponse:
    return error_response(404, "lead_not_found", "Lead not found")


async def handle_database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    if is_connectivity_error(exc):
        # Log only the type: driver messages contain hosts and ports.
        logger.warning(
            "Database unavailable during %s %s: %s",
            request.method,
            request.url.path,
            type(exc).__name__,
        )
        return database_unavailable_response()
    logger.exception("Database error during %s %s", request.method, request.url.path)
    return internal_error_response()


async def catch_unhandled_errors(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Turn any other exception into the 500 envelope.

    Implemented as middleware rather than an `Exception` handler because
    FastAPI runs `Exception` handlers outside CORSMiddleware, so the browser
    could not read the response. This middleware is added inside CORS.
    """
    try:
        return await call_next(request)
    except Exception:
        logger.exception("Unhandled error during %s %s", request.method, request.url.path)
        return internal_error_response()


def register_error_handlers(app: FastAPI) -> None:
    """Install the handlers; call before adding CORSMiddleware (see above)."""
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(HTTPException, handle_http_exception)
    app.add_exception_handler(LeadNotFound, handle_lead_not_found)
    app.add_exception_handler(SQLAlchemyError, handle_database_error)
    app.middleware("http")(catch_unhandled_errors)
