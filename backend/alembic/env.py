"""Alembic environment for bsdmirror.

WHAT THIS CONNECTS TO AND WHY IT LOOKS LIKE THIS
------------------------------------------------
The metadata is `shared.models.Base.metadata` -- the same object
`backend/app/core/database.py` and `sync/sync_service.py` import. That is the
whole reason Alembic could be adopted at all: autogenerating against the two
model definitions that existed before commit c62891a would have baked
seventeen drifts into the first migration.

The engine is async (asyncpg), matching the application. asyncpg is already in
backend/requirements.txt; a sync driver would have meant adding psycopg2 for
migrations only. So `run_migrations_online` opens an AsyncEngine and hands the
sync-facing connection to Alembic through `connection.run_sync`.

Offline mode (`alembic upgrade --sql`) needs no driver and no server. That is
what `scripts/migrate.sh sql` uses to print the statements for review before
anything is applied.
"""
import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# Alembic executes this file by path (importlib.spec_from_file_location), which
# does NOT put its directory on sys.path the way running a script does. So the
# sibling module has to be reachable before it can be imported.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime import COMPARE_OPTS, add_models_root_to_sys_path, database_url

add_models_root_to_sys_path()

from shared.models import Base  # noqa: E402  (needs the path set above)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Importing shared.models is what registers all five mapped classes on this
# MetaData. Without it autogenerate sees an empty model schema and proposes
# dropping every table in the database.
target_metadata = Base.metadata

CONTEXT_OPTS = dict(COMPARE_OPTS, target_metadata=target_metadata)


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of executing it.

    No DBAPI, no connection, no server. `literal_binds` inlines parameters so
    the output is runnable SQL a human can read, which is the point.
    """
    context.configure(
        url=database_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **CONTEXT_OPTS,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, **CONTEXT_OPTS)
    # One transaction for the whole run. Postgres has transactional DDL, so a
    # migration that fails half way leaves the schema exactly as it was rather
    # than half applied -- which is the difference between "the deploy stopped"
    # and "the deploy stopped and now nobody knows what the schema is".
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        {"sqlalchemy.url": database_url()},
        prefix="sqlalchemy.",
        # NullPool: this process runs one migration and exits. A pool would
        # hold connections open past the end of the run.
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
