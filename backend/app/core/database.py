"""
Database connection and session management.
"""
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
import structlog

from app.core.config import settings

# Re-exported, not defined here. `Base` lives in shared/models/base.py so the
# sync service can import the same MetaData without importing FastAPI; this
# module owns the engine and the session, not the schema. Existing callers
# (app.core.__init__, tests/conftest.py) keep importing it from here.
from shared.models import Base

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


async def init_db() -> None:
    """Initialize database connection and create tables.

    THIS IS THE ONLY create_all IN THE REPOSITORY, ON PURPOSE.

    The sync service imports the same `Base` and could therefore create the
    schema too. It must not. create_all creates missing *tables* only -- it
    never adds a column or alters a type on a table that already exists, and
    this repo has no migrations -- so whichever process runs first fixes the
    schema permanently. Both containers start together, so a second caller is
    also a race: two concurrent `CREATE TYPE mirror_status ...` and the loser
    raises DuplicateObject.

    Enforced, not just documented: tests/test_shared_models.py
    ::test_create_all_has_exactly_one_caller walks every .py file in the repo
    and fails if a second call appears anywhere.

    Importing shared.models (at module scope, above) is what registers all five
    mapped classes on Base.metadata; without it create_all would find an empty
    MetaData and silently create nothing.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized")


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
