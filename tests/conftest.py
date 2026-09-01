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

from datetime import datetime, timedelta, timezone  # noqa: E402
from functools import lru_cache  # noqa: E402
from typing import Optional  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

# The E402 suppressions above are deliberate: the os.environ block has to run
# before app.core.config is imported, and imports execute top to bottom.

from app.core.database import Base, get_db  # noqa: E402
from app.core.redis import get_redis  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.main import app  # noqa: E402
from shared.models import (  # noqa: E402
    Mirror,
    MirrorStatus,
    MirrorType,
    Setting,
    SyncJob,
    SyncStatus,
    User,
    UserRole,
)
from sync import sync_service  # noqa: E402
from sync.sync_service import SyncService  # noqa: E402

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


# ===========================================================================
# The sync service
#
# A second seam, for the half of the codebase that is not FastAPI. These are
# in conftest rather than in a test module because two modules need them --
# tests/test_sync_job.py (rsync exit codes and job persistence) and
# tests/test_orphan_reaper.py (abandoned jobs) -- and importing a fixture from
# one test module into another makes every use look like a redefinition.
#
# Same constraints as above: no aiosqlite, no Postgres, no network, no rsync.
# ===========================================================================

class FakeProcess:
    """The slice of asyncio.subprocess.Process that run_rsync touches."""

    def __init__(self, returncode: int, output: str) -> None:
        self.returncode = returncode
        self._output = output
        self.terminated = False

    async def communicate(self):
        return self._output.encode("utf-8"), None

    def terminate(self) -> None:
        self.terminated = True


class _SessionContext:
    """`async with self.session_maker() as session:` -- one fresh Session per
    context, matching async_sessionmaker's contract closely enough that
    sync_mirror_job cannot tell the difference."""

    def __init__(self, factory):
        self._factory = factory
        self._session = None

    async def __aenter__(self):
        self._session = self._factory()
        return _AsyncSessionShim(self._session)

    async def __aexit__(self, exc_type, exc, tb):
        self._session.close()
        return False


# The last time the OpenBSD mirror below was known good. Every assertion about
# last_sync_completed is "still this" or "later than this".
PREVIOUS_SYNC = datetime(2026, 8, 27, 4, 0, tzinfo=timezone.utc)


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        Base.metadata.drop_all(eng)
        eng.dispose()


@pytest.fixture
def factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@pytest.fixture
def service(factory):
    """A SyncService with no async engine and no network.

    __init__ builds a real asyncpg engine against a host that does not exist in
    this environment, so it is bypassed and only the attributes the methods
    under test read are set. Keep this list matching SyncService.__init__.
    """
    svc = object.__new__(SyncService)
    svc.running = True
    svc.current_sync = None
    # The reaper's ownership set: the ids of the jobs this process is executing
    # right now. Everything in tests/test_orphan_reaper.py turns on it.
    svc.active_job_ids = set()
    svc.sync_schedule = "0 4 * * *"
    svc.sync_bandwidth_limit = 0
    svc.sync_timeout = 600
    svc.session_maker = lambda: _SessionContext(factory)
    return svc


@pytest.fixture
def rsync(monkeypatch):
    """Replace asyncio.create_subprocess_exec. Returns a setter; the argv of
    each call is recorded in `calls`."""
    calls = []

    def configure(returncode: int, output: str):
        async def fake_exec(*cmd, **kwargs):
            calls.append(list(cmd))
            return FakeProcess(returncode, output)

        monkeypatch.setattr(sync_service.asyncio, "create_subprocess_exec", fake_exec)
        return calls

    configure.calls = calls
    return configure


@pytest.fixture
def mirror(factory, tmp_path):
    """An OpenBSD mirror that has already synced successfully once.

    last_sync_completed, total_size_bytes and file_count are pre-populated so
    every test can tell "left alone" apart from "overwritten" and from
    "cleared". The numbers are job 615's.
    """
    session = factory()
    row = Mirror(
        name="OpenBSD",
        # The column is the Postgres enum `mirror_type`; SQLAlchemy persists
        # the member NAME, so this stores the label 'OPENBSD'. It read
        # mirror_type="openbsd" while sync_service had its own VARCHAR(20)
        # copy of this table, which stored that string as-is.
        mirror_type=MirrorType.OPENBSD,
        upstream_url="rsync://ftp2.eu.openbsd.org/OpenBSD/",
        local_path=str(tmp_path / "openbsd"),
        enabled=True,
        status=MirrorStatus.ACTIVE,
        last_sync_started=PREVIOUS_SYNC,
        last_sync_completed=PREVIOUS_SYNC,
        last_sync_error=None,
        total_size_bytes=2_594_831_248_502,
        file_count=567_277,
    )
    session.add(row)
    session.commit()
    job = SyncJob(mirror_id=row.id, status=SyncStatus.PENDING, triggered_by="manual")
    session.add(job)
    session.commit()
    result = {"mirror_id": row.id, "job_id": job.id, "local_path": row.local_path,
              "upstream": row.upstream_url}
    session.close()
    return result


def reload(factory, mirror_id, job_id):
    """Re-read a mirror and a job through a fresh session."""
    session = factory()
    try:
        m = session.execute(select(Mirror).where(Mirror.id == mirror_id)).scalar_one()
        j = session.execute(select(SyncJob).where(SyncJob.id == job_id)).scalar_one()
        return m, j
    finally:
        session.close()


async def run_job(service, mirror):
    await service.sync_mirror_job(
        job_id=mirror["job_id"],
        mirror_id=mirror["mirror_id"],
        name="OpenBSD",
        upstream=mirror["upstream"],
        local_path=mirror["local_path"],
    )
