"""Alembic migration tests against the dedicated PostgreSQL test database."""

from collections.abc import Callable

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Connection, Engine, inspect, text

from app.models import Base

SCHEMA_TABLES = {"leads", "discussions"}


def schema_objects(connection: Connection) -> dict[str, set[str]]:
    """Tables, constraints and indexes currently in the public schema."""
    tables = set(inspect(connection).get_table_names()) - {"alembic_version"}
    constraints = set(
        connection.execute(
            text(
                "SELECT conname FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace "
                "WHERE n.nspname = 'public' AND conname <> 'alembic_version_pkc'"
            )
        ).scalars()
    )
    indexes = set(
        connection.execute(
            text(
                "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' "
                "AND indexname <> 'alembic_version_pkc'"
            )
        ).scalars()
    )
    return {"tables": tables, "constraints": constraints, "indexes": indexes}


EXPECTED_AT_HEAD = {
    "tables": SCHEMA_TABLES,
    "constraints": {
        "pk_leads",
        "ck_leads_name_not_blank",
        "ck_leads_status",
        "pk_discussions",
        "fk_discussions_lead_id_leads",
        "ck_discussions_note_not_blank",
    },
    "indexes": {"pk_leads", "pk_discussions", "ix_discussions_lead_created"},
}
EMPTY = {"tables": set(), "constraints": set(), "indexes": set()}


def current_revision(connection: Connection) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


def test_upgrade_downgrade_upgrade_cycle(
    db_engine: Engine, make_alembic_config: Callable[[Connection], Config]
) -> None:
    # db_engine has already migrated the dedicated test database to head.
    with db_engine.begin() as connection:
        config = make_alembic_config(connection)

        # Downgrade removes everything the initial migration created.
        command.downgrade(config, "base")
        assert schema_objects(connection) == EMPTY
        assert current_revision(connection) is None

        # A completely clean database (no alembic_version table) upgrades to head.
        connection.execute(text("DROP TABLE alembic_version"))
        command.upgrade(config, "head")
        assert schema_objects(connection) == EXPECTED_AT_HEAD
        assert current_revision(connection) == "0001"

        # And the cycle repeats: downgrade, then upgrade again.
        command.downgrade(config, "base")
        assert schema_objects(connection) == EMPTY
        command.upgrade(config, "head")
        assert schema_objects(connection) == EXPECTED_AT_HEAD


def test_foreign_key_cascades_on_delete(db_engine: Engine) -> None:
    with db_engine.connect() as connection:
        delete_rule = connection.execute(
            text(
                "SELECT confdeltype FROM pg_constraint "
                "WHERE conname = 'fk_discussions_lead_id_leads'"
            )
        ).scalar_one()
    assert delete_rule == "c"  # c = CASCADE


def test_migration_matches_models(db_engine: Engine) -> None:
    """Autogenerate finds nothing to change: the migration and models agree."""
    with db_engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        diff = compare_metadata(context, Base.metadata)
    assert diff == []
