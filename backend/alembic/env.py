from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection

from app.config import get_settings
from app.db import get_engine
from app.models import Base

config = context.config

# Configure logging for CLI runs only; tests (which pass a connection) keep pytest's.
if config.config_file_name is not None and "connection" not in config.attributes:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Importing app.models registers both tables, their constraints and the index.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout (`alembic upgrade head --sql`) without connecting."""
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Tests pass their own connection (to the test database) via config.attributes;
    # the CLI uses the application's engine, i.e. DATABASE_URL.
    connection = config.attributes.get("connection")
    if connection is not None:
        run_migrations(connection)
        return
    with get_engine().connect() as connection:
        run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
