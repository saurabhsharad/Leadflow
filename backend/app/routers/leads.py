"""Lead endpoints (see the specification, section 8).

Handlers only wire dependencies to the service layer: validation happens in the
schemas and parameter types, business rules in app.services.leads, and errors
(LeadNotFound, validation, database) in the central handlers of app.errors.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from pydantic import StringConstraints
from sqlalchemy.orm import Session

from app.clock import get_now
from app.config import Settings, get_settings
from app.db import get_db
from app.errors import ErrorResponse
from app.models import LeadStatus
from app.schemas import (
    DiscussionCreate,
    DiscussionCreated,
    LeadCreate,
    LeadDetail,
    LeadSummary,
    LeadUpdate,
)
from app.services import leads as services

# leads.id is a PostgreSQL INTEGER; larger values would fail in the database
# ("integer out of range") instead of being a clean validation error.
MAX_LEAD_ID = 2_147_483_647

DbSession = Annotated[Session, Depends(get_db)]
Now = Annotated[datetime, Depends(get_now)]
AppSettings = Annotated[Settings, Depends(get_settings)]
LeadId = Annotated[int, Path(ge=1, le=MAX_LEAD_ID)]
# Trimmed first, then limited to 100 characters; blank after trimming means no filter.
SearchText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]

VALIDATION_ERROR = {422: {"model": ErrorResponse, "description": "Validation failed"}}
NOT_FOUND = {404: {"model": ErrorResponse, "description": "Lead not found"}}

router = APIRouter(prefix="/api/leads", tags=["leads"])


@router.get("", response_model=list[LeadSummary], responses=VALIDATION_ERROR)
def list_leads(
    session: DbSession,
    now: Now,
    settings: AppSettings,
    status_filter: Annotated[LeadStatus | None, Query(alias="status")] = None,
    q: Annotated[SearchText | None, Query()] = None,
) -> list[LeadSummary]:
    """Leads in dashboard order, optionally filtered by status and name search."""
    return services.list_leads(session, now, settings.timezone, status=status_filter, q=q)


@router.post(
    "",
    response_model=LeadSummary,
    status_code=status.HTTP_201_CREATED,
    responses=VALIDATION_ERROR,
)
def create_lead(
    data: LeadCreate, session: DbSession, now: Now, settings: AppSettings
) -> LeadSummary:
    return services.create_lead(session, data, now, settings.timezone)


@router.get("/{lead_id}", response_model=LeadDetail, responses=NOT_FOUND | VALIDATION_ERROR)
def get_lead(lead_id: LeadId, session: DbSession, now: Now, settings: AppSettings) -> LeadDetail:
    """One lead with its discussion history, newest first."""
    return services.get_lead(session, lead_id, now, settings.timezone)


@router.patch("/{lead_id}", response_model=LeadSummary, responses=NOT_FOUND | VALIDATION_ERROR)
def update_lead(
    lead_id: LeadId, data: LeadUpdate, session: DbSession, now: Now, settings: AppSettings
) -> LeadSummary:
    """Change status and/or the follow-up; omitted fields stay as they are."""
    return services.update_lead(session, lead_id, data, now, settings.timezone)


@router.post(
    "/{lead_id}/discussions",
    response_model=DiscussionCreated,
    status_code=status.HTTP_201_CREATED,
    responses=NOT_FOUND | VALIDATION_ERROR,
)
def add_discussion(
    lead_id: LeadId, data: DiscussionCreate, session: DbSession, now: Now, settings: AppSettings
) -> DiscussionCreated:
    """Log a note; a given follow_up_at also becomes the lead's current follow-up."""
    return services.add_discussion(session, lead_id, data, now, settings.timezone)
