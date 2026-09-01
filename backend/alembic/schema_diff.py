"""Compare shared/models/ against a live schema and report every difference.

    python /app/alembic/schema_diff.py

Exit 0 when the model definitions and the database agree, 1 when they do not,
2 when it could not tell (connection refused, no such database).

WHY THIS EXISTS WHEN `alembic check` ALREADY DOES THIS
-----------------------------------------------------
`alembic check` refuses to run at all unless the database is already at head:
autogenerate raises "Target database is not up to date." when the revision in
`alembic_version` is not the newest one, and on a database that has never been
stamped there is no `alembic_version` table and no revision at all.

That is exactly the state production is in before adoption, and it is precisely
the moment the comparison matters most: `scripts/migrate.sh adopt` must not
stamp a database as being at 0001_baseline unless the schema really is what
0001_baseline describes. Stamping the wrong thing writes a claim that no later
command re-checks.

So this goes one level below the command line to `compare_metadata()`, the same
function `--autogenerate` and `check` are built on, with the same comparison
options (runtime.COMPARE_OPTS) -- and no revision preconditions.

After adoption, `alembic check` is the right tool and is what CI and
`migrate.sh check` use. This one is for before, and for reporting *what*
differs when it does.
"""
import asyncio
import sys

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

from runtime import COMPARE_OPTS, add_models_root_to_sys_path, database_url

add_models_root_to_sys_path()

from shared.models import Base  # noqa: E402  (needs the path set above)


def _diff(connection):
    ctx = MigrationContext.configure(connection, opts=dict(COMPARE_OPTS))
    return compare_metadata(ctx, Base.metadata)


async def main() -> int:
    url = database_url()
    engine = create_async_engine(url, poolclass=None)
    try:
        async with engine.connect() as connection:
            diff = await connection.run_sync(_diff)
    except SQLAlchemyError as exc:
        # Redacted: the URL carries POSTGRES_PASSWORD and this runs in CI logs
        # and in deploy output.
        print("could not compare: %s" % type(exc).__name__, file=sys.stderr)
        print(str(exc).splitlines()[0] if str(exc) else "", file=sys.stderr)
        return 2
    finally:
        await engine.dispose()

    if not diff:
        print("schema matches shared/models/: 0 differences")
        return 0

    print("schema DIFFERS from shared/models/: %d difference(s)" % len(diff))
    for entry in diff:
        print("  %r" % (entry,))
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
