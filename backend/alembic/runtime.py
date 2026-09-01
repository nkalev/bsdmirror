"""Bootstrapping shared by env.py and the standalone helpers in this directory.

Two things have to happen before either can do anything, and both are easy to
get subtly wrong in one place and not the other, so they live here once:

  1. `shared.models` must be importable. That is the whole point of adopting
     Alembic now -- the metadata comes from the one model package both services
     import (shared/models/), not from a copy.
  2. A database URL must be built without importing `app.core.config`.

This module is imported, never run. It is not a migration; Alembic only scans
`versions/`.
"""
import os
import sys
from pathlib import Path


def add_models_root_to_sys_path() -> Path:
    """Put the directory that CONTAINS `shared/` on sys.path, and return it.

    Two layouts have to work and no single relative path is correct in both:

        image      /app/alembic/env.py          with shared/ at /app/shared
        checkout   backend/alembic/env.py       with shared/ at <repo>/shared

    So this walks up from this file looking for the package rather than
    guessing, and raises naming every directory it tried if it does not find
    it -- because the alternative failure is an ImportError from inside Alembic
    that reads like a broken installation rather than a wrong layout.
    """
    tried = []
    for candidate in Path(__file__).resolve().parents:
        tried.append(candidate)
        if (candidate / "shared" / "models" / "__init__.py").is_file():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            return candidate
    raise RuntimeError(
        "cannot find the shared/models package from %s; looked in: %s"
        % (__file__, ", ".join(str(p) for p in tried))
    )


def database_url() -> str:
    """The URL migrations run against.

    Deliberately built from POSTGRES_* rather than by importing
    `app.core.config`. Two reasons, in this order:

      1. `app.core.config.Settings` requires SECRET_KEY, ADMIN_PASSWORD and
         REDIS_PASSWORD, none of which a migration needs. Importing it would
         make `alembic upgrade` fail on a host that has a database password and
         nothing else -- including inside `docker compose run --rm backend`,
         where those are present only because compose passes them.
      2. `backend/` is not on sys.path in a bare checkout, and putting it there
         would pull FastAPI and pydantic-settings into the migration path.

    The f-string below is therefore the third copy of this URL in the repo
    (backend/app/core/config.py:38, sync/sync_service.py:379). The CI job
    `migrations` asserts this function and `Settings.DATABASE_URL` produce the
    identical string for the same environment, so the copies cannot drift in
    silence the way the model definitions did.

    ALEMBIC_DATABASE_URL overrides everything. It exists for the one case the
    POSTGRES_* variables cannot express: pointing a verification run at a
    throwaway database on a server whose real one must not be touched.
    """
    override = os.getenv("ALEMBIC_DATABASE_URL")
    if override:
        return override

    user = os.getenv("POSTGRES_USER", "bsdmirrors")
    password = os.getenv("POSTGRES_PASSWORD", "")
    host = os.getenv("POSTGRES_HOST", "postgres")
    port = os.getenv("POSTGRES_PORT", "5432")
    name = os.getenv("POSTGRES_DB", "bsdmirrors")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{name}"


# Comparison options, defined once and used by every path that compares
# shared/models/ against a live schema: env.py's offline render, env.py's online
# run, and schema_diff.py.
#
# They must be identical everywhere. `migrate.sh sql` renders offline and
# `migrate.sh upgrade` applies online; a reviewer who reads SQL produced under
# different comparison rules than the ones that will run has reviewed something
# else.
#
#   compare_type            without it, varchar(50) -> varchar(100) and every
#                           enum change is invisible to autogenerate. The one
#                           schema incident this repo has already had (798ae79)
#                           was an enum/varchar mismatch.
#   compare_server_default  catches a server_default added to or removed from an
#                           existing column. Verified against the live schema
#                           shape: func.now() reflects back as now() and does
#                           not produce a spurious diff.
#   include_schemas=False   one schema, `public`. True would make autogenerate
#                           propose dropping anything Postgres keeps elsewhere.
COMPARE_OPTS = {
    "compare_type": True,
    "compare_server_default": True,
    "include_schemas": False,
}
