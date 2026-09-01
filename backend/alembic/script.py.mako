"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

REVIEW CHECKLIST -- delete the lines that do not apply, answer the ones that do.
  [ ] Does this run against a table with rows in it? (mirrors, sync_jobs,
      settings, users and audit_logs all have rows in production.)
  [ ] Does it take a lock that blocks reads or writes for longer than a moment?
      ALTER TABLE ... ADD COLUMN with no default is instant; with a volatile
      default, or a type change, it rewrites the table.
  [ ] Is it safe for the CURRENTLY RUNNING code? scripts/deploy.sh applies
      migrations BEFORE it recreates backend and sync, so the old containers
      serve traffic against the new schema for the length of a rebuild.
  [ ] Does downgrade() lose data? Say so here if it does.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
