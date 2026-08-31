"""The single declarative base for every table in the bsdmirror database.

WHY THIS IS THE ONLY ONE
------------------------
Until this module existed there were two. `backend/app/core/database.py`
declared a `DeclarativeBase`, and `sync/sync_service.py` called
`declarative_base()` for a second, unrelated MetaData holding hand-written
copies of `mirrors`, `sync_jobs` and `settings`.

Two MetaData objects over one physical database cannot be checked against each
other by anything -- not by SQLAlchemy, not by a type checker, not by a test --
because neither knows the other exists. They drifted in seventeen distinct ways
before this file was written; commit 798ae79 ("Fix sync service enum type
mismatch with PostgreSQL") is the one that reached production.

WHO CREATES TABLES
------------------
`Base.metadata.create_all` is called from exactly one place in this repository:
`init_db()` in backend/app/core/database.py, at backend startup.

Deliberately, this module offers no create/init helper of its own. The sync
service now imports this Base and therefore *could* create the schema; it must
not, because:

  * create_all creates missing TABLES only. It never adds a column or alters a
    type on a table that already exists (there are no migrations in this repo),
    so whichever process gets there first defines the schema permanently.
  * The backend and sync containers start together. Two concurrent
    `CREATE TYPE mirror_status ...` statements race, and the loser raises
    DuplicateObject.
  * The sync service holds the same database role as the backend, so no
    privilege stops it.

tests/test_shared_models.py::test_create_all_has_exactly_one_caller enforces
this by walking the AST of every Python file in the repository. Adding a second
caller is a failing test, not a production incident.
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""
    pass
