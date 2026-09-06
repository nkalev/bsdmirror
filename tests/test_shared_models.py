"""The unified schema must be byte-for-byte what production already contains.

WHY THIS FILE IS STRICTER THAN THE REST OF THE SUITE

This repo has no migrations. `Base.metadata.create_all` creates missing TABLES
only: on a database where `mirrors` already exists it will not add a column, will
not widen a type, will not touch an enum, and will not complain. So a model that
disagrees with the live schema does not fail a deploy. It produces wrong data, or
an error weeks later, against a database holding 3.8 TB of mirror state.

That is why the assertions below compare against a transcription of the *actual
production schema* rather than against the models' own previous output. Comparing
the models to themselves is what the old duplicated definitions did to each
other, and they still drifted seventeen ways.

WHAT SQLITE CANNOT TELL US, AND WHAT IS DONE INSTEAD

The rest of this suite runs on in-memory SQLite, which has no enum types at all
-- SQLAlchemy emits VARCHAR + a CHECK constraint there. A passing SQLite test
therefore says nothing about the thing that actually broke in 798ae79. Three
compensations, none of which need a server:

  1. Every DDL assertion compiles against `postgresql.dialect()`, the real
     Postgres compiler, not against SQLite.
  2. The enum round trip goes through `Enum.bind_processor(postgresql.dialect())`
     and `Enum.result_processor(postgresql.dialect(), None)` -- the exact
     functions that would encode and decode the value on a live connection.
     Everything between those two functions is the DBAPI and the wire; the
     translation logic is fully exercised here.
  3. The structural guards (one create_all, one declarative base, one class per
     table) are AST and object-identity checks, which do not involve a database
     at all.

What remains unverified without a Postgres server is listed at the bottom of this
docstring rather than left implicit:

  * That production's enum labels really are what was pasted into GROUND_TRUTH.
    That transcription is the input to this file, not an output of it.
  * That `CREATE TYPE` ordering, collation and search_path behave on the server
    as the compiler renders them.
  * Anything about existing row contents.
"""
import ast
import os
import pathlib

import pytest
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects import postgresql

from shared.models import (
    AuditLog,
    Base,
    Mirror,
    MirrorStatus,
    MirrorType,
    Setting,
    SyncJob,
    SyncStatus,
    User,
    UserRole,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PG = postgresql.dialect()


# ---------------------------------------------------------------------------
# Production ground truth
# ---------------------------------------------------------------------------
#
# Transcribed from a dump of the live database. Notation is the dump's own:
# Postgres internal type names (int4/int8/varchar/bool/timestamptz/text/json),
# USER-DEFINED(x) for an enum column, and the column default where one exists.
#
# `None` means THE DUMP DID NOT SAY. Those fields are not compared, because
# inventing a value for them would turn a gap in the evidence into an assertion
# that looks like it was checked. Which fields those are is reported by
# test_ground_truth_coverage below, so the gap stays visible.
#
# (name, pg_type, nullable, default)
GROUND_TRUTH = {
    "mirrors": [
        ("id",                  "int4",                       False, "nextval"),
        ("name",                "varchar",                    False, None),
        ("mirror_type",         "USER-DEFINED(mirror_type)",  False, None),
        ("upstream_url",        "varchar",                    False, None),
        ("local_path",          "varchar",                    False, None),
        ("enabled",             "bool",                       False, None),
        ("status",              "USER-DEFINED(mirror_status)", False, None),
        ("last_sync_started",   "timestamptz",                True,  None),
        ("last_sync_completed", "timestamptz",                True,  None),
        ("last_sync_error",     "text",                       True,  None),
        ("total_size_bytes",    "int8",                       True,  None),
        ("file_count",          "int8",                       True,  None),
        ("created_at",          "timestamptz",                False, "now()"),
        ("updated_at",          "timestamptz",                False, "now()"),
    ],
    "sync_jobs": [
        ("id",                "int4",                        False, None),
        ("mirror_id",         "int4",                        False, None),
        ("status",            "USER-DEFINED(sync_status)",   False, None),
        ("started_at",        "timestamptz",                 True,  None),
        ("completed_at",      "timestamptz",                 True,  None),
        ("files_transferred", "int8",                        True,  None),
        ("bytes_transferred", "int8",                        True,  None),
        ("files_deleted",     "int8",                        True,  None),
        ("rsync_output",      "text",                        True,  None),
        ("error_message",     "text",                        True,  None),
        ("triggered_by",      "varchar",                     True,  None),
        ("created_at",        "timestamptz",                 False, "now()"),
    ],
    "settings": [
        ("id",          "int4",        False, None),
        ("key",         "varchar",     False, None),
        ("value",       "text",        True,  None),
        ("description", "text",        True,  None),
        ("updated_at",  "timestamptz", False, "now()"),
    ],
    "users": [
        ("id",            "int4",                      None,  None),
        ("username",      "varchar",                   False, None),
        ("email",         "varchar",                   True,  None),
        ("password_hash", "varchar",                   False, None),
        ("role",          "USER-DEFINED(user_role)",   False, None),
        ("is_active",     "bool",                      False, None),
        ("created_at",    "timestamptz",               False, None),
        ("updated_at",    "timestamptz",               False, None),
        ("last_login",    "timestamptz",               True,  None),
    ],
    "audit_logs": [
        ("id",            "int4",    None,  None),
        ("user_id",       "int4",    True,  None),
        ("action",        "varchar", False, None),
        ("resource_type", "varchar", False, None),
        ("resource_id",   "varchar", True,  None),
        ("details",       "json",    True,  None),
        ("ip_address",    "varchar", True,  None),
        ("user_agent",    "text",    True,  None),
        ("created_at",    "timestamptz", False, None),
    ],
}

# Labels AND their order. Order is part of the type in Postgres: it defines the
# sort order of the enum and cannot be changed by ALTER TYPE without recreating
# it. SQLAlchemy takes both from the Python class's declaration order.
GROUND_TRUTH_ENUMS = {
    "mirror_status": ["ACTIVE", "SYNCING", "ERROR", "DISABLED"],
    "mirror_type":   ["FREEBSD", "NETBSD", "OPENBSD"],
    "sync_status":   ["PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"],
    "user_role":     ["ADMIN", "OPERATOR", "READONLY"],
}


# ---------------------------------------------------------------------------
# Rendering the models in the dump's notation
# ---------------------------------------------------------------------------

# SQLAlchemy renders the Postgres DDL spelling; the dump reports the internal
# type name. Same type, two names for it.
_DDL_TO_PG_INTERNAL = {
    "SERIAL": "int4",
    "INTEGER": "int4",
    "BIGINT": "int8",
    "BOOLEAN": "bool",
    "TEXT": "text",
    "JSON": "json",
    "TIMESTAMP WITH TIME ZONE": "timestamptz",
}


def pg_type_name(column) -> str:
    """The column's type as the production dump spells it."""
    if isinstance(column.type, SAEnum) and column.type.native_enum:
        return "USER-DEFINED(%s)" % column.type.name
    ddl = column.type.compile(dialect=PG)
    if ddl.startswith("VARCHAR"):
        return "varchar"
    # SERIAL is not a type, it is INTEGER + a nextval default. The compiler only
    # spells it that way inside CREATE TABLE, so reconstruct the same condition.
    if column.primary_key and column.autoincrement and ddl == "INTEGER":
        ddl = "SERIAL"
    return _DDL_TO_PG_INTERNAL.get(ddl, ddl)


def pg_default(column):
    """The column default in the dump's notation, or None if there is none."""
    if column.primary_key and column.autoincrement and not column.foreign_keys:
        if column.type.compile(dialect=PG) == "INTEGER":
            return "nextval"
    if column.server_default is not None:
        return str(column.server_default.arg).strip()
    # A Python-side default (`default=True`) is applied by SQLAlchemy on INSERT
    # and never reaches the DDL, so it is not a column default in the dump.
    return None


def rendered(table_name):
    table = Base.metadata.tables[table_name]
    return [
        (c.name, pg_type_name(c), c.nullable, pg_default(c))
        for c in table.columns
    ]


# ---------------------------------------------------------------------------
# 1. The models produce exactly the production schema
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("table_name", sorted(GROUND_TRUTH))
def test_columns_match_production_exactly(table_name):
    """Column by column, type by type, in order, against the live schema.

    Order matters as well as content: Postgres assigns attnum by position, and
    create_all on a fresh database would lay the table out in this order. A
    diff of zero is the only acceptable result.
    """
    expected = GROUND_TRUTH[table_name]
    actual = rendered(table_name)

    assert [c[0] for c in actual] == [c[0] for c in expected], (
        "%s: column set or order differs from production" % table_name
    )

    # Indexed rather than zip(): the name/order assertion above has already
    # established the two lists are the same length, and zip(strict=) is 3.10+
    # while some developer machines here are still on 3.9.
    diffs = []
    for i, exp in enumerate(expected):
        name, exp_type, exp_nullable, exp_default = exp
        _, act_type, act_nullable, act_default = actual[i]
        if exp_type != act_type:
            diffs.append("%s.%s type: production=%s models=%s"
                         % (table_name, name, exp_type, act_type))
        if exp_nullable is not None and exp_nullable != act_nullable:
            diffs.append("%s.%s nullable: production=%s models=%s"
                         % (table_name, name, exp_nullable, act_nullable))
        if exp_default is not None and exp_default != act_default:
            diffs.append("%s.%s default: production=%s models=%s"
                         % (table_name, name, exp_default, act_default))
    assert diffs == [], "\n".join(diffs)


def test_no_table_exists_that_production_does_not_have():
    """create_all would CREATE a table the models invent, silently and for real.

    Unlike a column difference this one is not inert: a table missing from the
    database is exactly the case create_all does act on.
    """
    assert sorted(Base.metadata.tables) == sorted(GROUND_TRUTH)


def test_ground_truth_coverage():
    """Report, rather than hide, which fields the production dump did not pin.

    This test cannot fail on a schema change -- it exists so the unasserted
    fields are named in the output of a normal run instead of being invisible
    inside a `None`.
    """
    unspecified = [
        "%s.%s %s" % (t, c[0], kind)
        for t, cols in sorted(GROUND_TRUTH.items())
        for c in cols
        for kind, val in (("nullable", c[2]), ("default", c[3]))
        if val is None
    ]
    # Defaults are legitimately absent on most columns; only flag the shape of
    # the gap, and assert the one class of elision that matters is small.
    missing_nullable = [u for u in unspecified if u.endswith("nullable")]
    assert missing_nullable == ["audit_logs.id nullable", "users.id nullable"], (
        "the dump elided nullability on: %s" % missing_nullable
    )


def test_primary_keys_elided_by_the_dump_are_all_serial_not_null():
    """users.id and audit_logs.id are written without NOT NULL in the dump.

    A Postgres primary key is NOT NULL by definition, so the dump is
    abbreviating rather than describing a nullable column. Asserted here
    separately so the elision above is closed rather than merely noted.
    """
    for table_name in sorted(GROUND_TRUTH):
        col = Base.metadata.tables[table_name].c.id
        assert col.primary_key is True, table_name
        assert col.nullable is False, table_name
        assert pg_type_name(col) == "int4", table_name
        assert pg_default(col) == "nextval", table_name


# ---------------------------------------------------------------------------
# 2. Enums: labels, order, and the round trip through the Postgres dialect
# ---------------------------------------------------------------------------

def enum_types():
    found = {}
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, SAEnum):
                found[col.type.name] = col.type
    return found


def test_enum_labels_and_order_match_production():
    types = enum_types()
    assert sorted(types) == sorted(GROUND_TRUTH_ENUMS)
    for name, expected in sorted(GROUND_TRUTH_ENUMS.items()):
        assert list(types[name].enums) == expected, (
            "enum %s: production=%s models=%s" % (name, expected, list(types[name].enums))
        )


def test_enums_are_native_postgres_types_not_varchar():
    """The regression from 798ae79, and its unfixed sibling.

    mirrors.mirror_type is `USER-DEFINED(mirror_type)` in production and was
    `Column(String(20))` in the sync service's copy of this table until these
    models were unified. It never corrupted anything only because the sync
    service happens never to write that column -- which is luck, not a design.
    """
    for table_name, column_name, type_name in [
        ("mirrors", "mirror_type", "mirror_type"),
        ("mirrors", "status", "mirror_status"),
        ("sync_jobs", "status", "sync_status"),
        ("users", "role", "user_role"),
    ]:
        col = Base.metadata.tables[table_name].c[column_name]
        assert isinstance(col.type, SAEnum), "%s.%s is not an Enum" % (table_name, column_name)
        assert col.type.native_enum is True, "%s.%s is not a native Postgres enum" % (
            table_name, column_name)
        assert col.type.name == type_name
        assert col.type.compile(dialect=PG) == type_name


@pytest.mark.parametrize(
    "member",
    list(MirrorStatus) + list(MirrorType) + list(SyncStatus) + list(UserRole),
    ids=lambda m: "%s.%s" % (type(m).__name__, m.name),
)
def test_enum_round_trip_through_the_postgres_dialect(member):
    """Write it, read it back, get the same member -- and the stored form is the
    uppercase NAME, not the lowercase value.

    This is the assertion the whole change hangs on. Every enum here is
    `class X(str, Enum)` with lowercase values (ACTIVE = "active"), but
    SQLAlchemy's Enum persists `.name`, so the database holds 'ACTIVE'. Every
    existing row in production is encoded that way.

    It is one keyword argument from silently inverting: adding
    `values_callable=lambda e: [m.value for m in e]` to any of these columns
    would start writing 'active' and reading nothing back, with no error at
    import time and no failing test anywhere else in this suite.

    bind_processor/result_processor are the functions a live asyncpg connection
    calls. Running them directly is what makes this meaningful despite the rest
    of the suite being on SQLite.
    """
    column = {
        MirrorStatus: ("mirrors", "status"),
        MirrorType: ("mirrors", "mirror_type"),
        SyncStatus: ("sync_jobs", "status"),
        UserRole: ("users", "role"),
    }[type(member)]
    enum_type = Base.metadata.tables[column[0]].c[column[1]].type

    to_db = enum_type.bind_processor(PG)
    from_db = enum_type.result_processor(PG, None)

    stored = to_db(member)
    assert stored == member.name, "stored form must be the NAME"
    assert stored == stored.upper(), "production labels are uppercase"
    assert stored != member.value, (
        "storing the value would make every existing row unreadable"
    )

    assert from_db(stored) is member, "round trip did not return the same member"


def test_lowercase_value_is_coerced_to_the_name_on_write():
    """A bare "openbsd" still reaches the database as 'OPENBSD'.

    Pinned because it is load-bearing and accidental: the members subclass str,
    so SQLAlchemy's lookup finds MirrorType.OPENBSD from the string "openbsd"
    and then persists its name. Dropping the `str` mixin from these classes
    would keep every existing call site compiling and start writing 'openbsd'
    into a type whose labels are all uppercase.
    """
    to_db = Base.metadata.tables["mirrors"].c.mirror_type.type.bind_processor(PG)
    assert to_db("openbsd") == "OPENBSD"
    assert to_db(MirrorType.OPENBSD) == "OPENBSD"


def test_unknown_enum_string_is_not_validated_before_it_reaches_postgres():
    """Documented, not endorsed.

    SQLAlchemy passes an unrecognised string straight through; Postgres is what
    rejects it, with `invalid input value for enum`. Anything building a Mirror
    from user input must validate against MirrorType itself -- the column will
    not do it. Asserted so that if a future SQLAlchemy version starts raising
    here, this file says so rather than some unrelated test failing obscurely.
    """
    to_db = Base.metadata.tables["mirrors"].c.mirror_type.type.bind_processor(PG)
    assert to_db("not-a-bsd") == "not-a-bsd"


# ---------------------------------------------------------------------------
# 3. Constraints and indexes the dump does not show but the code depends on
# ---------------------------------------------------------------------------

def test_sync_jobs_foreign_key_cascades_on_mirror_delete():
    """ON DELETE CASCADE, which the sync service's copy of this table omitted.

    backend/app/api/admin.py deletes mirrors and relies on the database to
    remove their sync_jobs. Had the sync service's definition ever been the one
    to create this table -- it never called create_all, so it was not -- every
    mirror deletion would have failed on a foreign key violation instead.
    """
    fks = list(Base.metadata.tables["sync_jobs"].c.mirror_id.foreign_keys)
    assert len(fks) == 1
    assert fks[0].target_fullname == "mirrors.id"
    assert fks[0].ondelete == "CASCADE"


def test_audit_logs_foreign_key_nulls_the_user_on_delete():
    """SET NULL, not CASCADE: deleting a user must not delete the audit trail
    of what that user did."""
    fks = list(Base.metadata.tables["audit_logs"].c.user_id.foreign_keys)
    assert len(fks) == 1
    assert fks[0].target_fullname == "users.id"
    assert fks[0].ondelete == "SET NULL"


def test_uniqueness_constraints():
    for table_name, column_name in [
        ("mirrors", "name"),
        ("settings", "key"),
        ("users", "username"),
        ("users", "email"),
    ]:
        col = Base.metadata.tables[table_name].c[column_name]
        assert col.unique is True, "%s.%s lost its uniqueness" % (table_name, column_name)


# ---------------------------------------------------------------------------
# 4. Structural guards: the duplication must not be able to come back
# ---------------------------------------------------------------------------

def python_files():
    """Every .py file in the repo, excluding caches and virtualenvs."""
    skip = {".git", "__pycache__", ".venv", "venv", ".pytest_cache", ".ruff_cache",
            "node_modules", "data"}
    for path in sorted(REPO_ROOT.rglob("*.py")):
        if not skip.isdisjoint(path.parts):
            continue
        yield path


def test_create_all_has_exactly_one_caller():
    """`Base.metadata.create_all` must be called from NOWHERE in the shipped code.

    This assertion used to name one permitted caller,
    `backend/app/core/database.py::init_db`. It now permits none, because
    Alembic owns the schema: backend/alembic/versions/ builds it, and
    scripts/migrate.sh applies it.

    Not style -- consequence, and the same consequence as before. create_all
    creates missing TABLES and nothing else, so on an existing database the
    first caller to run fixes the schema permanently and every later
    disagreement is silent. What changes with migrations in the repo is that a
    surviving create_all is now actively harmful rather than merely limited: on
    a fresh install it would build the schema before `alembic upgrade head`
    ran, and the baseline migration would then fail trying to CREATE TABLE over
    tables that already exist. Two mechanisms, one database, and the winner
    decided by startup order.

    The name of this test is kept deliberately. It is the string someone greps
    for after `create_all` reappears in a diff.

    Test code is excluded: tests/conftest.py and tests/test_sync_job.py build a
    throwaway in-memory SQLite schema per test, which is the intended use --
    those never touch Postgres and never touch alembic_version.
    """
    callers = []
    for path in python_files():
        if path.parts[len(REPO_ROOT.parts)] == "tests":
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        # Map each node to the function that encloses it, so the assertion can
        # name the owner rather than a line number that any edit above would
        # invalidate.
        enclosing = {}
        for parent in ast.walk(tree):
            if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(parent):
                    enclosing.setdefault(child, parent.name)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            # run_sync(Base.metadata.create_all) passes it as a value rather
            # than calling it, so the arguments are inspected too.
            passed_as_value = any(
                isinstance(arg, ast.Attribute) and arg.attr in ("create_all", "drop_all")
                for arg in node.args
            )
            if name in ("create_all", "drop_all") or passed_as_value:
                callers.append("%s::%s" % (path.relative_to(REPO_ROOT),
                                           enclosing.get(node, "<module>")))

    assert callers == [], (
        "create_all/drop_all must not be called outside the test suite -- Alembic "
        "owns the schema (backend/alembic/, scripts/migrate.sh). A second "
        "mechanism that creates tables makes the schema depend on which process "
        "starts first. Found: %s" % callers
    )


def test_sync_service_does_not_import_base():
    """The sync service must not be able to create the schema by accident.

    It imports the models it uses and deliberately not `Base`, so
    `Base.metadata.create_all` is not reachable from that module without
    someone adding an import -- a visible line in a diff, next to the comment
    saying why not to.
    """
    source = (REPO_ROOT / "sync" / "sync_service.py").read_text()
    tree = ast.parse(source)

    from_shared = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("shared"):
            from_shared.setdefault(node.module, set()).update(
                alias.name for alias in node.names
            )

    every_name = set().union(*from_shared.values()) if from_shared else set()
    assert "Base" not in every_name, "sync_service imported Base; it must not create tables"

    # Pinned per module, not as one flat set across all of shared/.
    #
    # The flat version failed the moment sync_service started importing
    # shared.settings_spec -- which is a module it SHOULD import; validating a
    # settings value against the same spec the API writes it through is the
    # whole point of that package. What must stay pinned is the model surface:
    # the schema names this service touches, and specifically that Base is not
    # among them.
    assert from_shared.get("shared.models") == {
        "Mirror", "MirrorStatus", "MirrorType", "Setting", "SyncJob", "SyncStatus"
    }


def test_exactly_one_declarative_base_in_the_repo():
    """Two MetaData objects over one database cannot be checked against each
    other by anything. That is how seventeen drifts accumulated unnoticed."""
    definitions = []
    for path in python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                fname = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
                if fname == "declarative_base":
                    definitions.append("%s:%d" % (path.relative_to(REPO_ROOT), node.lineno))
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    bname = base.attr if isinstance(base, ast.Attribute) else getattr(
                        base, "id", None)
                    if bname == "DeclarativeBase":
                        definitions.append("%s:%d" % (path.relative_to(REPO_ROOT), node.lineno))
    assert len(definitions) == 1, "expected one declarative base, found: %s" % definitions
    assert definitions[0].startswith("shared/models/base.py"), definitions


def test_one_mapped_class_per_table():
    """Belt and braces on the above: no two classes may claim the same table.

    SQLAlchemy would raise on a duplicate within one MetaData, but not across
    two -- which was exactly the old arrangement.
    """
    by_table = {}
    for mapper in Base.registry.mappers:
        by_table.setdefault(mapper.local_table.name, []).append(mapper.class_.__name__)
    assert {t: sorted(v) for t, v in by_table.items() if len(v) > 1} == {}
    assert sorted(by_table) == sorted(GROUND_TRUTH)


def test_both_services_see_the_identical_class_objects():
    """Not "equivalent definitions" -- the same objects in memory.

    The strongest form of the property this change exists to create: it is not
    that the two copies now agree, it is that there is no second copy to
    disagree.
    """
    from sync import sync_service

    assert sync_service.Mirror is Mirror
    assert sync_service.SyncJob is SyncJob
    assert sync_service.Setting is Setting
    assert sync_service.MirrorStatus is MirrorStatus
    assert sync_service.MirrorType is MirrorType
    assert sync_service.SyncStatus is SyncStatus

    from app.core.database import Base as backend_base

    assert backend_base is Base
    assert backend_base.metadata is Base.metadata


def test_models_do_not_import_from_either_service():
    """shared/ must not depend on app.* or sync_service.

    The dependency runs one way. If it ever ran both, importing the models
    would drag FastAPI into the sync image and the package would stop being
    shareable -- which is how one of these packages becomes two again.
    """
    offenders = []
    for path in sorted((REPO_ROOT / "shared").rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            for n in names:
                if n.split(".")[0] in ("app", "sync", "sync_service"):
                    offenders.append("%s:%d imports %s"
                                     % (path.relative_to(REPO_ROOT), node.lineno, n))
    assert offenders == []


# ---------------------------------------------------------------------------
# 5. The columns the sync service gained by unifying
# ---------------------------------------------------------------------------

def test_columns_the_sync_service_gained_all_have_defaults():
    """mirrors.created_at, mirrors.updated_at, sync_jobs.created_at and
    settings.updated_at were absent from the sync service's copy.

    Unifying gives that service four NOT NULL columns it did not know about. It
    INSERTs SyncJob rows (sync_mirror_job), so this matters: without a
    server-side default those inserts would start failing with a NOT NULL
    violation the first time the unified models shipped. Each has
    `server_default=now()`, so Postgres fills them and the sync path is
    unchanged. tests/test_sync_job.py exercises the same inserts end to end.
    """
    for table_name, column_name in [
        ("mirrors", "created_at"),
        ("mirrors", "updated_at"),
        ("sync_jobs", "created_at"),
        ("settings", "updated_at"),
    ]:
        col = Base.metadata.tables[table_name].c[column_name]
        assert col.nullable is False, "%s.%s" % (table_name, column_name)
        assert col.server_default is not None, (
            "%s.%s is NOT NULL with no server default; an INSERT from the sync "
            "service that omits it would fail" % (table_name, column_name)
        )
        assert str(col.server_default.arg).strip() == "now()"


def test_sync_jobs_insert_needs_only_the_columns_the_sync_service_supplies():
    """sync_service.sync_mirror() constructs SyncJob(mirror_id, status,
    triggered_by) and nothing else. Every other NOT NULL column on that table
    must therefore be filled by the database or by SQLAlchemy."""
    supplied = {"mirror_id", "status", "triggered_by"}
    unfilled = [
        c.name for c in Base.metadata.tables["sync_jobs"].columns
        if c.name not in supplied
        and not c.nullable
        and c.server_default is None
        and c.default is None
        and not (c.primary_key and c.autoincrement)
    ]
    assert unfilled == [], (
        "sync_service would fail to insert a SyncJob: %s have no value" % unfilled
    )


# ---------------------------------------------------------------------------
# 6. The full DDL, as one comparable artefact
# ---------------------------------------------------------------------------

def test_create_table_ddl_snapshot():
    """The whole CREATE TABLE output, pinned.

    The per-column tests above are the readable ones; this is the one that
    catches a change nobody thought to parametrise -- a dropped index, a
    changed VARCHAR length, a constraint that quietly became an index.
    """
    from sqlalchemy.schema import CreateTable

    ddl = "\n".join(
        " ".join(str(CreateTable(Base.metadata.tables[t]).compile(dialect=PG)).split())
        for t in sorted(Base.metadata.tables)
    )
    expected = "\n".join([
        "CREATE TABLE audit_logs ( id SERIAL NOT NULL, user_id INTEGER, "
        "action VARCHAR(100) NOT NULL, resource_type VARCHAR(50) NOT NULL, "
        "resource_id VARCHAR(100), details JSON, ip_address VARCHAR(45), "
        "user_agent TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, "
        "PRIMARY KEY (id), FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL )",

        "CREATE TABLE mirrors ( id SERIAL NOT NULL, name VARCHAR(50) NOT NULL, "
        "mirror_type mirror_type NOT NULL, upstream_url VARCHAR(500) NOT NULL, "
        "local_path VARCHAR(500) NOT NULL, enabled BOOLEAN NOT NULL, "
        "status mirror_status NOT NULL, last_sync_started TIMESTAMP WITH TIME ZONE, "
        "last_sync_completed TIMESTAMP WITH TIME ZONE, last_sync_error TEXT, "
        "total_size_bytes BIGINT, file_count BIGINT, "
        "created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, "
        "updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, "
        "PRIMARY KEY (id), UNIQUE (name) )",

        "CREATE TABLE settings ( id SERIAL NOT NULL, key VARCHAR(100) NOT NULL, "
        "value TEXT, description TEXT, "
        "updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, PRIMARY KEY (id) )",

        "CREATE TABLE sync_jobs ( id SERIAL NOT NULL, mirror_id INTEGER NOT NULL, "
        "status sync_status NOT NULL, started_at TIMESTAMP WITH TIME ZONE, "
        "completed_at TIMESTAMP WITH TIME ZONE, files_transferred BIGINT, "
        "bytes_transferred BIGINT, files_deleted BIGINT, rsync_output TEXT, "
        "error_message TEXT, triggered_by VARCHAR(50), "
        "created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, PRIMARY KEY (id), "
        "FOREIGN KEY(mirror_id) REFERENCES mirrors (id) ON DELETE CASCADE )",

        "CREATE TABLE users ( id SERIAL NOT NULL, username VARCHAR(50) NOT NULL, "
        "email VARCHAR(255), password_hash VARCHAR(255) NOT NULL, "
        "role user_role NOT NULL, is_active BOOLEAN NOT NULL, "
        "created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, "
        "updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, "
        "last_login TIMESTAMP WITH TIME ZONE, PRIMARY KEY (id), UNIQUE (email) )",
    ])
    assert ddl == expected


def test_index_ddl_snapshot():
    """Indexes are emitted separately from CREATE TABLE and are just as easy to
    lose. ix_settings_key is UNIQUE; that is the settings.key uniqueness."""
    from sqlalchemy.schema import CreateIndex

    indexes = sorted(
        " ".join(str(CreateIndex(ix).compile(dialect=PG)).split())
        for t in Base.metadata.tables.values()
        for ix in t.indexes
    )
    assert indexes == [
        "CREATE INDEX ix_audit_logs_action ON audit_logs (action)",
        "CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at)",
        "CREATE INDEX ix_audit_logs_user_id ON audit_logs (user_id)",
        "CREATE INDEX ix_sync_jobs_mirror_id ON sync_jobs (mirror_id)",
        "CREATE UNIQUE INDEX ix_settings_key ON settings (key)",
        "CREATE UNIQUE INDEX ix_users_username ON users (username)",
    ]


def test_models_are_importable_without_the_backend_on_the_path():
    """The sync image has no `app` package in it at all.

    `import shared.models` must therefore not reach `app.*` transitively.
    Checked by importing into a fresh interpreter with only the repo root on
    sys.path -- the same shape as /app in the sync container.
    """
    import subprocess
    import sys

    # cwd=REPO_ROOT and no PYTHONPATH: sys.path is the repo root plus
    # site-packages, with backend/ nowhere on it -- the same shape as /app in
    # the sync container, where the `app` package does not exist.
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys;"
         "assert not [p for p in sys.path if p.endswith('backend')], sys.path;"
         "import shared.models as m;"
         "assert 'app' not in sys.modules, sorted(k for k in sys.modules if k.startswith('app'));"
         "print(sorted(m.Base.metadata.tables))"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "audit_logs" in result.stdout


def test_the_model_classes_are_unchanged_from_the_definitions_that_built_production():
    """A spot check in plain Python, independent of every helper above.

    If the rendering functions in this file are themselves wrong, the tests
    that use them can pass while the schema is broken. These assertions touch
    the SQLAlchemy objects directly.
    """
    assert Mirror.__tablename__ == "mirrors"
    assert SyncJob.__tablename__ == "sync_jobs"
    assert Setting.__tablename__ == "settings"
    assert User.__tablename__ == "users"
    assert AuditLog.__tablename__ == "audit_logs"

    assert MirrorStatus.ACTIVE.value == "active"
    assert MirrorStatus.ACTIVE.name == "ACTIVE"
    assert [m.name for m in MirrorType] == ["FREEBSD", "NETBSD", "OPENBSD"]
    assert [m.name for m in SyncStatus] == [
        "PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
    assert [m.name for m in UserRole] == ["ADMIN", "OPERATOR", "READONLY"]

    # str mixin: load-bearing, see test_lowercase_value_is_coerced_to_the_name
    for enum_cls in (MirrorStatus, MirrorType, SyncStatus, UserRole):
        assert issubclass(enum_cls, str), enum_cls
