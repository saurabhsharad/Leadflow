import logging
from typing import Annotated, Literal

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.db import get_engine
from app.errors import ErrorResponse, database_unavailable_response, register_error_handlers
from app.routers import leads

logger = logging.getLogger(__name__)

settings = get_settings()  # Fails at startup on invalid config, e.g. a bad APP_TIMEZONE.

app = FastAPI(title="LeadFlow API", version="0.1.0")

# Error handling first: middleware added later wraps earlier middleware, so CORS
# stays outermost and even 500 responses carry CORS headers.
register_error_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)

app.include_router(leads.router)


class HealthResponse(BaseModel):
    status: Literal["ok"]
    database: Literal["ok"]


@app.get(
    "/api/health",
    response_model=HealthResponse,
    responses={503: {"model": ErrorResponse, "description": "Database unavailable"}},
)
def health(engine: Annotated[Engine, Depends(get_engine)]) -> HealthResponse | JSONResponse:
    """Report whether the API is running and PostgreSQL answers `SELECT 1`."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        # Log only the exception type; the message can contain connection details.
        logger.warning("Health check database query failed: %s", type(exc).__name__)
        return database_unavailable_response()
    return HealthResponse(status="ok", database="ok")
