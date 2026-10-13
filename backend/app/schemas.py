"""Request and response schemas for the LeadFlow API (see the specification, section 8).

Requests use extra="forbid", so an unknown or misspelt field is a validation
error instead of being silently ignored. Responses read from ORM objects.
"""

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.models import LeadStatus

# Plausible range for follow-up instants (UTC years 2000-2100 inclusive); anything
# else is almost certainly a typo. The upper bound is exclusive.
FOLLOW_UP_START = datetime(2000, 1, 1, tzinfo=UTC)
FOLLOW_UP_END = datetime(2101, 1, 1, tzinfo=UTC)


def _blank_to_none(value: Any) -> Any:
    """Trim optional strings; a blank or whitespace-only string means "not given"."""
    if isinstance(value, str):
        return value.strip() or None
    return value


def _check_follow_up_year(value: datetime) -> datetime:
    # Compare with aware bounds instead of converting: astimezone(UTC) raises
    # OverflowError near datetime.min/max (e.g. 9999-12-31T23:59-05:00), while
    # comparing aware datetimes only subtracts offsets and cannot overflow.
    if not FOLLOW_UP_START <= value < FOLLOW_UP_END:
        raise ValueError("Year must be between 2000 and 2100 (UTC)")
    return value


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


RequiredName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
OptionalCompany = Annotated[
    Annotated[str, StringConstraints(max_length=120)] | None, BeforeValidator(_blank_to_none)
]
OptionalPhone = Annotated[
    Annotated[str, StringConstraints(max_length=30, pattern=r"^[0-9+()\-\s]*$")] | None,
    BeforeValidator(_blank_to_none),
]
RequiredNote = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)
]
# Requests must carry an offset (naive datetimes are rejected) and a plausible year.
FollowUpDatetime = Annotated[AwareDatetime, AfterValidator(_check_follow_up_year)]
# Responses always serialise instants in UTC ("...Z"), whatever the DB session timezone.
UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResponseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Requests ---------------------------------------------------------------


class LeadCreate(RequestModel):
    """POST /api/leads. Status is not accepted: new leads always start as "new"."""

    name: RequiredName
    company: OptionalCompany = None
    phone: OptionalPhone = None


class LeadUpdate(RequestModel):
    """PATCH /api/leads/{id}.

    Apply with model_dump(exclude_unset=True): an omitted field is left unchanged,
    while an explicit `"next_follow_up_at": null` clears the follow-up.
    """

    status: LeadStatus | None = None
    next_follow_up_at: FollowUpDatetime | None = None

    @field_validator("status")
    @classmethod
    def status_not_null(cls, value: LeadStatus | None) -> LeadStatus:
        # Runs only when status is supplied; a lead always has a status.
        if value is None:
            raise ValueError("Status cannot be null")
        return value

    @model_validator(mode="after")
    def require_a_field(self) -> "LeadUpdate":
        if not self.model_fields_set:
            raise ValueError("Provide at least one of: status, next_follow_up_at")
        return self


class DiscussionCreate(RequestModel):
    """POST /api/leads/{id}/discussions.

    An omitted or null follow_up_at both mean "leave the lead's follow-up
    unchanged"; this endpoint never clears it.
    """

    note: RequiredNote
    follow_up_at: FollowUpDatetime | None = None


# --- Responses --------------------------------------------------------------


class DiscussionRead(ResponseModel):
    id: int
    note: str
    follow_up_at: UtcDatetime | None
    created_at: UtcDatetime


class LastDiscussion(ResponseModel):
    """The newest discussion of a lead, as shown on its dashboard card."""

    note: str
    created_at: UtcDatetime


class LeadSummary(ResponseModel):
    """A lead as returned by list, create and update.

    follow_up_due_today, follow_up_overdue and last_discussion are not columns:
    the service layer computes them and supplies them alongside the lead.
    """

    id: int
    name: str
    company: str | None
    phone: str | None
    status: LeadStatus
    next_follow_up_at: UtcDatetime | None
    follow_up_due_today: bool
    follow_up_overdue: bool
    last_discussion: LastDiscussion | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class LeadDetail(LeadSummary):
    """GET /api/leads/{id}: the summary plus full history, newest first."""

    discussions: list[DiscussionRead]


class DiscussionCreated(BaseModel):
    """Response of POST /api/leads/{id}/discussions."""

    discussion: DiscussionRead
    lead: LeadSummary
