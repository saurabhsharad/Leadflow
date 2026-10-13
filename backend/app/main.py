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

logger = logging.getLogger(__name__)

settings = get_settings()  # Fails at startup on invalid config, e.g. a bad APP_TIMEZONE.

app = FastAPI(title="LeadFlow API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)


class HealthResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    database: Literal["ok", "unavailable"]


@app.get(
    "/api/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "Database unavailable"}},
)
def health(engine: Annotated[Engine, Depends(get_engine)]) -> HealthResponse | JSONResponse:
    """Report whether the API is running and PostgreSQL answers `SELECT 1`."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        # Log only the exception type; the message can contain connection details.
        logger.warning("Health check database query failed: %s", type(exc).__name__)
        body = HealthResponse(status="unavailable", database="unavailable")
        return JSONResponse(status_code=503, content=body.model_dump())
    return HealthResponse(status="ok", database="ok")
