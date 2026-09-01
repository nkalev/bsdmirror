"""
Database connection and session management.
"""
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
import structlog

from app.core.config import settings

# Re-exported, not defined here. `Base` lives in shared/models/base.py so the
# sync service can import the same MetaData without importing FastAPI; this
# module owns the engine and the session, not the schema. Existing callers
# (app.core.__init__, tests/conftest.py) keep importing it from here.
#
# It is no longer used *in* this module: the schema is built by Alembic
# (backend/alembic/, scripts/migrate.sh), not by create_all. The re-export
# stays because conftest.py builds a throwaway SQLite schema from it per test.
from shared.models import Base  # noqa: F401  (re-export; see above)

logger = structlog.get_logger(__name__)

# Create async engine
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,
)

# Session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


SCHEMA_NOT_MIGRATED = (
    "The database has no alembic_version table, so no migration has ever been "
    "applied to it and the schema this process needs may not exist.\n"
    "\n"
    "  Fresh install:      scripts/migrate.sh upgrade\n"
    "  Existing database:  scripts/migrate.sh adopt   (stamps it, runs no DDL)\n"
    "\n"
    "This container will keep restarting until one of those has been run. That "
    "is deliberate: it used to create the tables itself, which silently ignored "
    "every column, type and constraint change on a table that already existed."
)


async def init_db() -> None:
    """Verify the database is under Alembic's control. Creates nothing.

    THIS FUNCTION USED TO CALL Base.metadata.create_all. IT NO LONGER DOES, AND
    NOTHING IN THIS REPOSITORY DOES.

    create_all creates missing TABLES and nothing else. On a database where
    `mirrors` already exists it will not add a column, will not widen a type,
    will not touch an enum, and will not complain -- so with no migrations, no
    schema change was ever deployable and nothing said so. Alembic now owns the
    schema (backend/alembic/, scripts/migrate.sh). Keeping create_all as well
    would mean two mechanisms defining one database, with whichever ran first
    winning: on a fresh install create_all would build the schema and the
    baseline migration would then fail trying to CREATE TABLE over it.

    Enforced, not just documented: tests/test_shared_models.py
    ::test_create_all_has_exactly_one_caller now asserts there are NO callers
    outside the test suite.

    WHAT THIS CHECKS, AND WHAT IT DELIBERATELY DOES NOT
    ---------------------------------------------------
    It checks one thing: that `alembic_version` exists and holds a revision. If
    it does not, the schema is either absent (fresh install, migrations not run)
    or was built by the create_all this function used to call and has never been
    adopted -- and in both cases the right answer is a message naming the
    command to run, not an `UndefinedTable` traceback from the seeding query
    twenty lines later in main.py's lifespan.

    It does NOT require the revision to equal this image's head. That check
    belongs to scripts/deploy.sh, which migrates before it recreates containers.
    Enforcing it here would make `deploy.sh --rollback` impossible: the older
    image would refuse to start against a database the newer migration had
    already moved forward, which is exactly the moment a rollback is needed.
    """
    async with engine.connect() as conn:
        # Two statements rather than one, because `SELECT ... FROM
        # alembic_version` against a database that does not have that table is
        # a PARSE error -- it cannot be guarded by a WHERE clause, and catching
        # ProgrammingError here would also swallow a genuinely broken
        # connection. to_regclass returns NULL instead of raising.
        #
        # Postgres-specific, and that is fine: this function only ever runs
        # against the compose postgres service. The test suite never reaches it
        # (tests/conftest.py drives the app through ASGITransport, which does
        # not run lifespan).
        present = await conn.scalar(text("SELECT to_regclass('public.alembic_version')"))
        revision = None
        if present is not None:
            revision = await conn.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))

    if revision is None:
        raise RuntimeError(SCHEMA_NOT_MIGRATED)

    logger.info("Database schema verified", alembic_revision=revision)


async def close_db() -> None:
    """Close database connection."""
    await engine.dispose()
    logger.info("Database connection closed")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting database session."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
