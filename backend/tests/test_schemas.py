"""Request and response schema rules. Pure validation: no database or clock needed."""

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

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

IST = timezone(timedelta(hours=5, minutes=30))
FOLLOW_UP_IST = datetime(2026, 10, 15, 11, 0, tzinfo=IST)
FOLLOW_UP_UTC = datetime(2026, 10, 15, 5, 30, tzinfo=UTC)


def error_types(model: type[BaseModel], data: dict[str, Any]) -> list[tuple[tuple, str]]:
    with pytest.raises(ValidationError) as exc_info:
        model.model_validate(data)
    return [(e["loc"], e["type"]) for e in exc_info.value.errors()]


# --- LeadCreate ---------------------------------------------------------------


def test_lead_create_valid_and_trimmed() -> None:
    lead = LeadCreate.model_validate(
        {"name": "  Sarah Connor ", "company": " Acme Corp ", "phone": " +91 (555) 0199-1 "}
    )
    assert lead.model_dump() == {
        "name": "Sarah Connor",
        "company": "Acme Corp",
        "phone": "+91 (555) 0199-1",
    }


def test_lead_create_optional_fields_default_to_none() -> None:
    assert LeadCreate.model_validate({"name": "A"}).model_dump() == {
        "name": "A",
        "company": None,
        "phone": None,
    }


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_lead_create_blank_optional_strings_become_none(value: str) -> None:
    lead = LeadCreate.model_validate({"name": "A", "company": value, "phone": value})
    assert (lead.company, lead.phone) == (None, None)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({}, [(("name",), "missing")]),
        ({"name": None}, [(("name",), "string_type")]),
        ({"name": ""}, [(("name",), "string_too_short")]),
        ({"name": "   \t "}, [(("name",), "string_too_short")]),
        ({"name": "\u00a0"}, [(("name",), "string_too_short")]),  # non-breaking space
    ],
)
def test_lead_create_rejects_missing_or_blank_name(data: dict, expected: list) -> None:
    assert error_types(LeadCreate, data) == expected


def test_lead_create_name_length_is_counted_after_trimming() -> None:
    assert len(LeadCreate.model_validate({"name": "a" * 120}).name) == 120
    assert len(LeadCreate.model_validate({"name": f"  {'a' * 120}  "}).name) == 120
    assert error_types(LeadCreate, {"name": "a" * 121}) == [(("name",), "string_too_long")]


def test_lead_create_company_length_boundary() -> None:
    assert LeadCreate.model_validate({"name": "A", "company": "c" * 120}).company == "c" * 120
    assert error_types(LeadCreate, {"name": "A", "company": "c" * 121}) == [
        (("company",), "string_too_long")
    ]


def test_lead_create_phone_length_boundary() -> None:
    assert LeadCreate.model_validate({"name": "A", "phone": "1" * 30}).phone == "1" * 30
    assert error_types(LeadCreate, {"name": "A", "phone": "1" * 31}) == [
        (("phone",), "string_too_long")
    ]


@pytest.mark.parametrize("phone", ["555-0123", "+1 (555) 0123", "0123456789", "+44 20 7946 0958"])
def test_lead_create_accepts_phone_characters_from_spec(phone: str) -> None:
    assert LeadCreate.model_validate({"name": "A", "phone": phone}).phone == phone


@pytest.mark.parametrize("phone", ["555-CALL", "555.0123", "ext 12", "#123", "555/0123"])
def test_lead_create_rejects_other_phone_characters(phone: str) -> None:
    assert error_types(LeadCreate, {"name": "A", "phone": phone}) == [
        (("phone",), "string_pattern_mismatch")
    ]


@pytest.mark.parametrize(
    "field",
    ["status", "id", "created_at", "updated_at", "next_follow_up_at", "email"],
)
def test_lead_create_rejects_unexpected_and_server_managed_fields(field: str) -> None:
    assert error_types(LeadCreate, {"name": "A", field: "x"}) == [((field,), "extra_forbidden")]


# --- LeadUpdate ---------------------------------------------------------------


@pytest.mark.parametrize("status", [s.value for s in LeadStatus])
def test_lead_update_accepts_each_status(status: str) -> None:
    update = LeadUpdate.model_validate({"status": status})
    assert update.status is LeadStatus(status)
    assert update.model_dump(exclude_unset=True) == {"status": LeadStatus(status)}


@pytest.mark.parametrize("status", ["New", "WON", "proposal sent", "pending", ""])
def test_lead_update_rejects_invalid_status(status: str) -> None:
    assert error_types(LeadUpdate, {"status": status}) == [(("status",), "enum")]


def test_lead_update_rejects_null_status() -> None:
    assert error_types(LeadUpdate, {"status": None}) == [(("status",), "value_error")]


def test_lead_update_omitted_follow_up_is_not_in_partial_dump() -> None:
    update = LeadUpdate.model_validate({"status": "won"})
    assert "next_follow_up_at" not in update.model_dump(exclude_unset=True)


def test_lead_update_explicit_null_clears_follow_up() -> None:
    update = LeadUpdate.model_validate({"next_follow_up_at": None})
    assert update.model_dump(exclude_unset=True) == {"next_follow_up_at": None}


def test_lead_update_accepts_aware_follow_up_alongside_status() -> None:
    update = LeadUpdate.model_validate_json(
        '{"status": "qualified", "next_follow_up_at": "2026-10-15T11:00:00+05:30"}'
    )
    assert update.model_dump(exclude_unset=True) == {
        "status": LeadStatus.QUALIFIED,
        "next_follow_up_at": FOLLOW_UP_IST,
    }
    assert update.next_follow_up_at == FOLLOW_UP_UTC  # same instant


@pytest.mark.parametrize("value", ["2026-10-15T11:00:00", datetime(2026, 10, 15, 11, 0)])
def test_lead_update_rejects_naive_datetime(value: object) -> None:
    assert error_types(LeadUpdate, {"next_follow_up_at": value}) == [
        (("next_follow_up_at",), "timezone_aware")
    ]


# The year range is checked on the UTC instant, so 05:30 IST on 1 Jan 2000 is the
# first accepted IST minute and 05:29 IST is still 1999 in UTC.
@pytest.mark.parametrize(
    "value",
    ["2000-01-01T00:00:00Z", "2100-12-31T23:59:59Z", "2000-01-01T05:30:00+05:30"],
)
def test_follow_up_year_range_bounds_are_inclusive(value: str) -> None:
    assert LeadUpdate.model_validate({"next_follow_up_at": value}).next_follow_up_at is not None


# The last four are valid ISO datetimes whose UTC conversion overflows (Python's
# datetime range is years 1-9999); they must be validation errors, not OverflowError.
OUT_OF_RANGE_FOLLOW_UPS = [
    "1999-12-31T23:59:59Z",
    "2101-01-01T00:00:00Z",
    "2000-01-01T05:29:00+05:30",
    "9999-12-31T23:59:59-05:00",
    "0001-01-01T00:00:00+05:00",
    "9999-12-31T23:59:59.999999-23:59",
    "0001-01-01T00:00:00+23:59",
]


@pytest.mark.parametrize("value", OUT_OF_RANGE_FOLLOW_UPS)
def test_follow_up_year_outside_range_is_rejected(value: str) -> None:
    assert error_types(LeadUpdate, {"next_follow_up_at": value}) == [
        (("next_follow_up_at",), "value_error")
    ]


@pytest.mark.parametrize("value", OUT_OF_RANGE_FOLLOW_UPS)
def test_discussion_follow_up_outside_range_is_rejected(value: str) -> None:
    assert error_types(DiscussionCreate, {"note": "x", "follow_up_at": value}) == [
        (("follow_up_at",), "value_error")
    ]


def test_lead_update_rejects_empty_body() -> None:
    assert error_types(LeadUpdate, {}) == [((), "value_error")]


@pytest.mark.parametrize("field", ["name", "company", "phone", "id", "created_at", "updated_at"])
def test_lead_update_rejects_non_editable_fields(field: str) -> None:
    assert error_types(LeadUpdate, {"status": "won", field: "x"}) == [((field,), "extra_forbidden")]


# --- DiscussionCreate ---------------------------------------------------------


def test_discussion_create_valid_and_trimmed() -> None:
    discussion = DiscussionCreate.model_validate(
        {"note": "  Wants a revised quote.\n", "follow_up_at": FOLLOW_UP_IST}
    )
    assert discussion.note == "Wants a revised quote."
    assert discussion.follow_up_at == FOLLOW_UP_UTC


@pytest.mark.parametrize(
    "data", [{"note": "Call back"}, {"note": "Call back", "follow_up_at": None}]
)
def test_discussion_create_omitted_or_null_follow_up_means_none(data: dict) -> None:
    assert DiscussionCreate.model_validate(data).follow_up_at is None


def test_discussion_create_keeps_inner_newlines() -> None:
    assert DiscussionCreate.model_validate({"note": "line 1\nline 2"}).note == "line 1\nline 2"


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({}, [(("note",), "missing")]),
        ({"note": ""}, [(("note",), "string_too_short")]),
        ({"note": " \n\t "}, [(("note",), "string_too_short")]),
    ],
)
def test_discussion_create_rejects_missing_or_blank_note(data: dict, expected: list) -> None:
    assert error_types(DiscussionCreate, data) == expected


def test_discussion_create_note_length_boundary() -> None:
    assert len(DiscussionCreate.model_validate({"note": "n" * 5000}).note) == 5000
    assert len(DiscussionCreate.model_validate({"note": f" {'n' * 5000} "}).note) == 5000
    assert error_types(DiscussionCreate, {"note": "n" * 5001}) == [(("note",), "string_too_long")]


def test_discussion_create_rejects_naive_follow_up() -> None:
    assert error_types(DiscussionCreate, {"note": "x", "follow_up_at": "2026-10-15T11:00"}) == [
        (("follow_up_at",), "timezone_aware")
    ]


@pytest.mark.parametrize("field", ["id", "lead_id", "created_at", "next_follow_up_at", "author"])
def test_discussion_create_rejects_unexpected_fields(field: str) -> None:
    assert error_types(DiscussionCreate, {"note": "x", field: 1}) == [((field,), "extra_forbidden")]


# --- Responses ----------------------------------------------------------------


def make_discussion(
    id: int, created_at: datetime, follow_up_at: datetime | None = None
) -> Discussion:
    # Transient ORM object: never added to a session, so no database is involved.
    return Discussion(
        id=id, lead_id=3, note=f"note {id}", follow_up_at=follow_up_at, created_at=created_at
    )


def lead_summary_data(lead: Lead) -> dict[str, Any]:
    """The lead's columns plus the values the service layer will compute."""
    return {
        **{f: getattr(lead, f) for f in LeadSummary.model_fields if hasattr(Lead, f)},
        "follow_up_due_today": True,
        "follow_up_overdue": False,
        "last_discussion": lead.discussions[0] if lead.discussions else None,
    }


@pytest.fixture
def lead() -> Lead:
    created = datetime(2026, 10, 8, 16, 0, tzinfo=IST)
    return Lead(
        id=3,
        name="Sarah Connor",
        company="Acme Corp",
        phone=None,
        status=LeadStatus.PROPOSAL_SENT,
        next_follow_up_at=FOLLOW_UP_IST,
        created_at=created,
        updated_at=created,
        discussions=[
            make_discussion(2, datetime(2026, 10, 11, 10, 30, tzinfo=IST), FOLLOW_UP_IST),
            make_discussion(1, datetime(2026, 10, 9, 10, 30, tzinfo=IST)),
        ],
    )


def test_discussion_read_from_orm_object_hides_lead_id_and_uses_utc() -> None:
    discussion = make_discussion(13, datetime(2026, 10, 13, 20, 35, tzinfo=IST), FOLLOW_UP_IST)
    assert DiscussionRead.model_validate(discussion).model_dump(mode="json") == {
        "id": 13,
        "note": "note 13",
        "follow_up_at": "2026-10-15T05:30:00Z",
        "created_at": "2026-10-13T15:05:00Z",
    }


def test_last_discussion_from_orm_object() -> None:
    discussion = make_discussion(1, datetime(2026, 10, 11, 5, 0, tzinfo=UTC))
    assert LastDiscussion.model_validate(discussion).model_dump(mode="json") == {
        "note": "note 1",
        "created_at": "2026-10-11T05:00:00Z",
    }


def test_lead_summary_matches_api_contract_shape(lead: Lead) -> None:
    body = LeadSummary.model_validate(lead_summary_data(lead)).model_dump(mode="json")
    assert body == {
        "id": 3,
        "name": "Sarah Connor",
        "company": "Acme Corp",
        "phone": None,
        "status": "proposal_sent",
        "next_follow_up_at": "2026-10-15T05:30:00Z",
        "follow_up_due_today": True,
        "follow_up_overdue": False,
        "last_discussion": {"note": "note 2", "created_at": "2026-10-11T05:00:00Z"},
        "created_at": "2026-10-08T10:30:00Z",
        "updated_at": "2026-10-08T10:30:00Z",
    }


def test_lead_summary_without_discussions_or_follow_up(lead: Lead) -> None:
    lead.discussions = []
    lead.next_follow_up_at = None
    body = LeadSummary.model_validate(lead_summary_data(lead)).model_dump(mode="json")
    assert body["last_discussion"] is None
    assert body["next_follow_up_at"] is None


def test_lead_detail_includes_discussions_in_given_order(lead: Lead) -> None:
    detail = LeadDetail.model_validate({**lead_summary_data(lead), "discussions": lead.discussions})
    assert [d.id for d in detail.discussions] == [2, 1]
    assert set(detail.model_dump()) == set(LeadSummary.model_fields) | {"discussions"}


def test_response_rejects_naive_timestamps(lead: Lead) -> None:
    lead.created_at = datetime(2026, 10, 8, 10, 30)
    with pytest.raises(ValidationError, match="timezone"):
        LeadSummary.model_validate(lead_summary_data(lead))


def test_discussion_created_wraps_discussion_and_lead(lead: Lead) -> None:
    created = DiscussionCreated.model_validate(
        {"discussion": lead.discussions[0], "lead": lead_summary_data(lead)}
    )
    assert set(created.model_dump()) == {"discussion", "lead"}
    assert created.discussion.id == 2
