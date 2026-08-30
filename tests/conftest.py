"""
Shared test fixtures.

Design constraint: this suite must run from a bare checkout with nothing but
`pip install -r backend/requirements.txt`. No Docker, no Postgres, no Redis, no
network. Everything below exists to honour that.

Two seams are used, both of them ones FastAPI provides on purpose:

  get_db     -> a real SQLAlchemy ORM session against in-memory SQLite, wrapped
                in a thin async facade (see _AsyncSessionShim).
  get_redis  -> an in-process dict standing in for the token blacklist.

Why a shim instead of aiosqlite: aiosqlite is not in backend/requirements.txt,
and adding a dependency is not this change's call to make. The shim keeps the
suite installable from the existing requirements file, which is the whole point
of CI being able to run it on day one. Every SQL statement, every ORM mapping
and every constraint is still real -- only the await points are synthetic.
"""
import os

# Settings are a module-level singleton built at import time from the
# environment (backend/app/core/config.py), and four fields are required with no
# default. These must be set before anything under app.* is imported.
# setdefault, not assignment, so a developer can override any of them locally.
os.environ.setdefault("POSTGRES_PASSWORD", "pytest-not-a-real-password")
os.environ.setdefault("REDIS_PASSWORD", "pytest-not-a-real-password")
os.environ.setdefault("SECRET_KEY", "pytest-signing-key-do-not-use-anywhere-else")
os.environ.setdefault("ADMIN_PASSWORD", "pytest-not-a-real-password")
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("LOG_LEVEL", "WARNING")

from datetime import timedelta  # noqa: E402
from functools import lru_cache  # noqa: E402
from typing import Optional  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

# The E402 suppressions above are deliberate: the os.environ block has to run
# before app.core.config is imported, and imports execute top to bottom.

from app.core.database import Base, get_db  # noqa: E402
from app.core.redis import get_redis  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models.mirror import Mirror, MirrorStatus, MirrorType  # noqa: E402
from app.models.setting import Setting  # noqa: E402
from app.models.sync_job import SyncJob, SyncStatus  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402

# Passwords used by the seeded fixtures. >= 12 chars so they also satisfy
# UserCreateRequest's min_length when reused in create-user tests.
ADMIN_PASSWORD = "admin-password-1234"
OPERATOR_PASSWORD = "operator-password-1234"
READONLY_PASSWORD = "readonly-password-1234"


@lru_cache(maxsize=None)
def cached_hash(password: str) -> str:
    """bcrypt at cost 12 is ~0.17s a call. Each distinct password is hashed once
    per session instead of once per test."""
    return hash_password(password)


class _AsyncSessionShim:
    """Async facade over a synchronous SQLAlchemy Session.

    Only the surface the routes actually touch is overridden; everything else
    (add, add_all, expire, get, ...) forwards unchanged via __getattr__.
    """

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    async def execute(self, *args, **kwargs):
        return self._session.execute(*args, **kwargs)

    async def commit(self) -> None:
        self._session.commit()

    async def rollback(self) -> None:
        self._session.rollback()

    async def flush(self, *args, **kwargs) -> None:
        self._session.flush(*args, **kwargs)

    async def refresh(self, instance, *args, **kwargs) -> None:
        self._session.refresh(instance, *args, **kwargs)

    async def delete(self, instance) -> None:
        self._session.delete(instance)

    async def close(self) -> None:
        self._session.close()


class FakeRedis:
    """Stand-in for redis.asyncio.Redis covering the calls the app makes:
    setex (blacklist_token), exists (is_token_blacklisted) and ping (health)."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def setex(self, key: str, ttl: int, value: str) -> bool:
        self.store[key] = value
        self.ttls[key] = ttl
        return True

    async def exists(self, *keys: str) -> int:
        return sum(1 for key in keys if key in self.store)

    async def get(self, key: str) -> Optional[str]:
        return self.store.get(key)

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if self.store.pop(key, None) is not None:
                self.ttls.pop(key, None)
                removed += 1
        return removed

    async def ping(self) -> bool:
        return True


@pytest.fixture
def db_session():
    """A fresh in-memory SQLite database per test.

    StaticPool holds a single connection open for the engine's lifetime; without
    it every checkout would get a brand-new (empty) :memory: database.
    """
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def seed(db_session):
    """One user per role, one enabled mirror, one sync job, one setting.

    Returned as a dict so tests can reference ids without re-querying.
    """
    users = {
        "admin": User(
            username="alice-admin",
            email="alice@example.test",
            password_hash=cached_hash(ADMIN_PASSWORD),
            role=UserRole.ADMIN,
            is_active=True,
        ),
        "operator": User(
            username="olly-operator",
            email="olly@example.test",
            password_hash=cached_hash(OPERATOR_PASSWORD),
            role=UserRole.OPERATOR,
            is_active=True,
        ),
        "readonly": User(
            username="rita-readonly",
            email="rita@example.test",
            password_hash=cached_hash(READONLY_PASSWORD),
            role=UserRole.READONLY,
            is_active=True,
        ),
    }
    # A second admin, so admin-only destructive endpoints have a target that is
    # not the caller (delete_user/update_user refuse to act on self).
    users["victim"] = User(
        username="vic-target",
        email="vic@example.test",
        password_hash=cached_hash(READONLY_PASSWORD),
        role=UserRole.READONLY,
        is_active=True,
    )

    mirror = Mirror(
        name="FreeBSD",
        mirror_type=MirrorType.FREEBSD,
        upstream_url="rsync://ftp.freebsd.org/FreeBSD/",
        local_path="/data/mirrors/freebsd/pub/FreeBSD",
        enabled=True,
        status=MirrorStatus.ACTIVE,
    )

    db_session.add_all(list(users.values()))
    db_session.add(mirror)
    db_session.commit()

    job = SyncJob(mirror_id=mirror.id, status=SyncStatus.COMPLETED, triggered_by="scheduled")
    setting = Setting(key="sync_schedule", value="0 4 * * *", description="cron schedule")
    db_session.add_all([job, setting])
    db_session.commit()

    return {
        "users": users,
        "mirror": mirror,
        "mirror_id": mirror.id,
        "job": job,
        "job_id": job.id,
        "setting": setting,
    }


@pytest.fixture
async def client(db_session, fake_redis):
    """httpx.AsyncClient bound straight to the ASGI app.

    ASGITransport does not run lifespan, which is what we want: no init_db, no
    init_redis, no admin-user seeding.
    """
    shim = _AsyncSessionShim(db_session)

    async def _get_db():
        # Mirrors the real get_db (backend/app/core/database.py): commit on a
        # clean exit, roll back on any exception. It deliberately does not close
        # -- one session is shared for the duration of a single test.
        try:
            yield shim
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise

    async def _get_redis():
        return fake_redis

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_redis] = _get_redis
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()


def token_for(user: User, expires_delta: Optional[timedelta] = None) -> str:
    """Mint a token the way /api/auth/token does, without paying for bcrypt.

    Authorization tests care about the claims, not about the login handshake;
    the login handshake has its own tests in test_auth.py.
    """
    return create_access_token(
        data={"sub": user.username, "user_id": user.id, "role": user.role.value},
        expires_delta=expires_delta,
    )


def auth_header(user: User, expires_delta: Optional[timedelta] = None) -> dict:
    return {"Authorization": f"Bearer {token_for(user, expires_delta)}"}
