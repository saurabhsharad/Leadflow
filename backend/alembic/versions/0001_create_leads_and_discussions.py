"""Create leads and discussions tables.

Revision ID: 0001
Revises:
Create Date: 2026-10-13

Written by hand to match app/models.py and the schema in the project
specification; tests check that it stays in sync with the models. The "not
blank" CHECKs use a regex instead of the specification's btrim(), because the
one-argument btrim() strips only spaces and would accept tab- or newline-only text.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEAD_STATUSES = ("new", "contacted", "qualified", "proposal_sent", "won", "lost")


def upgrade() -> None:
    op.create_table(
        "leads",
        sa.Column("id", sa.Integer(), sa.Identity(always=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("company", sa.String(length=120), nullable=True),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="new", nullable=False),
        sa.Column("next_follow_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_leads")),
        sa.CheckConstraint("name ~ '[^[:space:]]'", name=op.f("ck_leads_name_not_blank")),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in LEAD_STATUSES) + ")",
            name=op.f("ck_leads_status"),
        ),
    )

    op.create_table(
        "discussions",
        sa.Column("id", sa.Integer(), sa.Identity(always=True), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("follow_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discussions")),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
            name=op.f("fk_discussions_lead_id_leads"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("note ~ '[^[:space:]]'", name=op.f("ck_discussions_note_not_blank")),
    )

    op.create_index(
        "ix_discussions_lead_created",
        "discussions",
        ["lead_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )


def downgrade() -> None:
    # Reverse dependency order: the index and discussions (which reference leads) first.
    op.drop_index("ix_discussions_lead_created", table_name="discussions")
    op.drop_table("discussions")
    op.drop_table("leads")
