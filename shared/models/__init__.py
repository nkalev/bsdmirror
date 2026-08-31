"""The bsdmirror schema: one definition, imported by both services.

STYLE: SQLAlchemy 2.0 `Mapped[...]` / `mapped_column(...)`
---------------------------------------------------------
The two former copies were written in different styles -- this one, and
`Column(...)` with `declarative_base()` in the sync service. This one survives
for two reasons, in this order:

1. IT IS WHAT PRODUCTION ACTUALLY CONTAINS. The live schema was created by
   `Base.metadata.create_all` from these exact class bodies. The sync service's
   copies describe a database that has never existed. With no migrations, the
   models are not a proposal -- they are a claim about 3.8 TB of existing rows,
   and only one of the two copies was ever true.

2. THE ANNOTATION CARRIES NULLABILITY. `Mapped[str]` is NOT NULL and
   `Mapped[Optional[str]]` is nullable, checkable by a type checker and visible
   at the point of use. `Column(String(50))` defaults to nullable and says
   nothing. Six of the seventeen drifts found when these files were merged were
   exactly that: a column the backend declared NOT NULL that the sync service
   believed was optional.

WHAT HAD DRIFTED, for the record -- backend (correct) vs sync (wrong):

    mirrors.mirror_type       ENUM mirror_type      vs VARCHAR(20)   <- 798ae79's sibling
    mirrors.name              NOT NULL              vs nullable
    mirrors.upstream_url      NOT NULL              vs nullable
    mirrors.local_path        NOT NULL              vs nullable
    mirrors.enabled           NOT NULL              vs nullable
    mirrors.status            NOT NULL              vs nullable
    mirrors.created_at        present               vs ABSENT
    mirrors.updated_at        present               vs ABSENT
    settings.key              UNIQUE INDEX          vs UNIQUE CONSTRAINT
    settings.updated_at       present               vs ABSENT
    sync_jobs.mirror_id       NOT NULL              vs nullable
    sync_jobs.mirror_id FK    ON DELETE CASCADE     vs no action
    sync_jobs.mirror_id       INDEX                 vs no index
    sync_jobs.status          NOT NULL              vs nullable
    sync_jobs.triggered_by    has column comment    vs no comment
    sync_jobs.created_at      present               vs ABSENT
    users, audit_logs         5 tables in metadata  vs 3

ENUMS ARE STORED BY NAME, NOT BY VALUE
--------------------------------------
Every enum here is `class X(str, Enum)` with lowercase values -- ACTIVE =
"active" -- but SQLAlchemy's `Enum(SomePyEnum)` uses the member *names* as the
Postgres labels and persists `.name`. So the database holds 'ACTIVE', and
mirror_status is ENUM('ACTIVE','SYNCING','ERROR','DISABLED') in that order.

That is an implicit SQLAlchemy default, it is what every existing row is
encoded with, and it is one keyword argument away from silently changing:
adding `values_callable=lambda e: [m.value for m in e]` would flip every column
to lowercase and make every stored row unreadable, with no error at import
time. tests/test_shared_models.py pins the labels, their order, and the
round trip through the *Postgres* dialect's own bind/result processors.
"""
from shared.models.base import Base
from shared.models.user import User, UserRole
from shared.models.mirror import Mirror, MirrorType, MirrorStatus
from shared.models.sync_job import SyncJob, SyncStatus
from shared.models.audit_log import AuditLog
from shared.models.setting import Setting

__all__ = [
    "Base",
    "User",
    "UserRole",
    "Mirror",
    "MirrorType",
    "MirrorStatus",
    "SyncJob",
    "SyncStatus",
    "AuditLog",
    "Setting",
]
