"""Lead and discussion business rules (see the specification, sections 6-9).

Conventions:
- Every function takes an open Session owned by the caller (one per request).
  Writes call commit() exactly once; on any exception before that, nothing is
  committed and the caller's session rollback discards the partial work.
- `now` and `tz` are passed in (the injected clock and APP_TIMEZONE), so the
  follow-up flags are deterministic in tests.
- Missing leads raise LeadNotFound; database errors propagate unchanged to the
  central error handlers. Nothing here builds HTTP responses or logs row data.
"""

from datetime import datetime, tzinfo

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.errors import LeadNotFound
from app.followups import classify, dashboard_sort_key
from app.models import Discussion, Lead, LeadStatus
from app.schemas import (
    DiscussionCreate,
    DiscussionCreated,
    DiscussionRead,
    LastDiscussion,
    LeadCreate,
    LeadDetail,
    LeadSummary,
    LeadUpdate,
)

# --- Queries ------------------------------------------------------------------


def _summary_query() -> Select[tuple[Lead, str | None, datetime | None]]:
    """Leads with their newest discussion, in one query (no N+1).

    DISTINCT ON (lead_id) keeps the first row per lead in the subquery's order:
    newest created_at, and the highest id when timestamps tie.
    """
    latest = (
        select(Discussion.lead_id, Discussion.note, Discussion.created_at)
        .distinct(Discussion.lead_id)
        .order_by(Discussion.lead_id, Discussion.created_at.desc(), Discussion.id.desc())
        .subquery("latest_discussion")
    )
    return select(Lead, latest.c.note, latest.c.created_at).outerjoin(
        latest, latest.c.lead_id == Lead.id
    )


def _to_summary(
    lead: Lead,
    last_note: str | None,
    last_discussion_at: datetime | None,
    now: datetime,
    tz: tzinfo,
) -> LeadSummary:
    state = classify(lead.next_follow_up_at, now, tz)
    last_discussion = (
        LastDiscussion(note=last_note, created_at=last_discussion_at)
        if last_note is not None and last_discussion_at is not None
        else None
    )
    return LeadSummary(
        id=lead.id,
        name=lead.name,
        company=lead.company,
        phone=lead.phone,
        status=lead.status,
        next_follow_up_at=lead.next_follow_up_at,
        follow_up_due_today=state.due_today,
        follow_up_overdue=state.overdue,
        last_discussion=last_discussion,
        created_at=lead.created_at,
        updated_at=lead.updated_at,
    )


def _get_lead(session: Session, lead_id: int) -> Lead:
    lead = session.get(Lead, lead_id)
    if lead is None:
        raise LeadNotFound(lead_id)
    return lead


def _lead_summary(session: Session, lead_id: int, now: datetime, tz: tzinfo) -> LeadSummary:
    row = session.execute(_summary_query().where(Lead.id == lead_id)).one_or_none()
    if row is None:
        raise LeadNotFound(lead_id)
    return _to_summary(*row, now, tz)


# --- Leads --------------------------------------------------------------------


def create_lead(session: Session, data: LeadCreate, now: datetime, tz: tzinfo) -> LeadSummary:
    """Insert a lead; id, status ("new") and timestamps come from the database."""
    lead = Lead(**data.model_dump())
    session.add(lead)
    session.commit()
    session.refresh(lead)
    return _to_summary(lead, None, None, now, tz)


def get_lead(session: Session, lead_id: int, now: datetime, tz: tzinfo) -> LeadDetail:
    """One lead with its full discussion history, newest first (created_at, then id)."""
    lead = _get_lead(session, lead_id)
    discussions = lead.discussions  # ordered by the relationship's order_by
    latest = discussions[0] if discussions else None
    summary = _to_summary(
        lead,
        latest.note if latest else None,
        latest.created_at if latest else None,
        now,
        tz,
    )
    return LeadDetail(
        **dict(summary), discussions=[DiscussionRead.model_validate(d) for d in discussions]
    )


def list_leads(
    session: Session,
    now: datetime,
    tz: tzinfo,
    status: LeadStatus | None = None,
    q: str | None = None,
) -> list[LeadSummary]:
    """All leads in dashboard order: overdue from earlier days, today, then the rest.

    `status` filters by exact status; `q` is a case-insensitive name search in
    which % and _ are literal. Both are optional and combinable.
    """
    query = _summary_query()
    if status is not None:
        query = query.where(Lead.status == status)
    if q:
        query = query.where(Lead.name.icontains(q, autoescape=True))
    summaries = [_to_summary(*row, now, tz) for row in session.execute(query)]
    return sorted(
        summaries,
        key=lambda s: dashboard_sort_key(
            follow_up_at=s.next_follow_up_at,
            last_discussion_at=s.last_discussion.created_at if s.last_discussion else None,
            created_at=s.created_at,
            lead_id=s.id,
            now=now,
            tz=tz,
        ),
    )


def update_lead(
    session: Session, lead_id: int, data: LeadUpdate, now: datetime, tz: tzinfo
) -> LeadSummary:
    """Apply only the fields the client sent.

    An omitted field is untouched; an explicit `next_follow_up_at: null` clears
    the follow-up. LeadUpdate itself rejects empty bodies and a null status.
    """
    lead = _get_lead(session, lead_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(lead, field, value)
    # Set explicitly so the write is recorded even if the values are unchanged.
    lead.updated_at = func.now()
    session.commit()
    return _lead_summary(session, lead_id, now, tz)


# --- Discussions --------------------------------------------------------------


def add_discussion(
    session: Session, lead_id: int, data: DiscussionCreate, now: datetime, tz: tzinfo
) -> DiscussionCreated:
    """Append a note to a lead's history, optionally scheduling its next follow-up.

    With follow_up_at, the lead's current follow-up is replaced and the
    discussion keeps the value it scheduled (history survives later changes).
    Without it (omitted or null), the lead row is not touched at all: its
    follow-up is never cleared as a side effect. One commit covers both rows.
    """
    lead = _get_lead(session, lead_id)
    discussion = Discussion(lead_id=lead.id, note=data.note, follow_up_at=data.follow_up_at)
    session.add(discussion)
    if data.follow_up_at is not None:
        lead.next_follow_up_at = data.follow_up_at
        lead.updated_at = func.now()
    session.commit()
    session.refresh(discussion)
    return DiscussionCreated(
        discussion=DiscussionRead.model_validate(discussion),
        lead=_lead_summary(session, lead_id, now, tz),
    )
