from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Deterministic constraint names, so migrations can refer to them reliably.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class LeadStatus(StrEnum):
    NEW = "new"
    CONTACTED = "contacted"
    QUALIFIED = "qualified"
    PROPOSAL_SENT = "proposal_sent"
    WON = "won"
    LOST = "lost"


# "Not blank" CHECKs require at least one non-whitespace character. PostgreSQL's
# one-argument btrim() strips only spaces, so `btrim(x) <> ''` would accept "\t".
NOT_BLANK = "{column} ~ '[^[:space:]]'"


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (CheckConstraint(NOT_BLANK.format(column="name"), name="name_not_blank"),)

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    company: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(30))
    # Stored as VARCHAR + CHECK (not a native PostgreSQL enum), using the lowercase
    # values rather than the Python member names.
    status: Mapped[LeadStatus] = mapped_column(
        Enum(
            LeadStatus,
            name="status",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda statuses: [s.value for s in statuses],
        ),
        server_default=LeadStatus.NEW.value,
    )
    next_follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # The database deletes a lead's discussions (ON DELETE CASCADE). passive_deletes
    # lets it do so instead of the ORM loading every discussion to delete it first.
    discussions: Mapped[list["Discussion"]] = relationship(
        back_populates="lead",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="(Discussion.created_at.desc(), Discussion.id.desc())",
    )


class Discussion(Base):
    __tablename__ = "discussions"
    __table_args__ = (CheckConstraint(NOT_BLANK.format(column="note"), name="note_not_blank"),)

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"))
    note: Mapped[str] = mapped_column(Text)
    # The follow-up this discussion scheduled; kept as history when the lead's
    # current follow-up (Lead.next_follow_up_at) changes later.
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lead: Mapped[Lead] = relationship(back_populates="discussions")


# Newest-first discussion history per lead; id breaks ties between equal timestamps.
Index(
    "ix_discussions_lead_created",
    Discussion.lead_id,
    Discussion.created_at.desc(),
    Discussion.id.desc(),
)
