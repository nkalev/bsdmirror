"""
Disk capacity for the mirror data volume.

Nothing else in this codebase measures free space: shared/models has no
column for it, no endpoint returns it, and the sync service does not track
it. The only size figure anywhere is Mirror.total_size_bytes, summed -- what
the mirrors *contain*, never what the disk has *left*.

That distinction used to not matter much: rsync's `--delete` (sync_service.py)
kept the tree roughly the size of upstream. `sync/protected_paths.py` removes
that bound on purpose, so EOL releases survive upstream pruning -- which means
the tree now grows monotonically and nothing here would notice it approaching
the disk's actual limit.

docker-compose.yml bind-mounts the mirror tree read-only at the fixed
container path `/data/mirrors`. settings.MIRROR_DATA_PATH
(backend/app/core/config.py) defaults to that same string -- and is what this
module actually reads -- so `os.statvfs` on it is a real, local syscall
against that mount: no `df` subprocess, no network. Note the coupling: the
container's `environment:` list does not currently pass a MIRROR_DATA_PATH
value through, so the setting stays at its default regardless of what the
compose file's own MIRROR_DATA_PATH (the unrelated HOST-side source path for
that bind mount) is set to. The two happening to share a name is a trap for
a future edit, not a guarantee.

os.statvfs is still a blocking syscall, not network I/O, and the
async-discipline rule in CLAUDE.md draws no exception for "usually fast":
callers must go through `get_disk_usage`, which offloads it to a worker
thread, rather than calling `read_disk_usage` directly from a coroutine.
tests/test_async_hygiene.py enforces this for the primitives it already
knows about; `os.statvfs` is added to that list alongside this module so a
future direct call is caught the same way.
"""
import asyncio
import os
from dataclasses import dataclass
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class DiskUsage:
    """Byte counts for one filesystem, plus the df-style used% derived from
    them.

    total_bytes    f_frsize * f_blocks -- the filesystem's raw size.
    free_bytes     f_frsize * f_bavail -- space available to an UNPRIVILEGED
                   process, not f_bfree. ext4/xfs both reserve a slice of the
                   free blocks for root (5% by default); this backend runs as
                   an ordinary user and could not write into that reserve, so
                   counting it as "free" would overstate headroom.
    used_bytes     total_bytes - (f_frsize * f_bfree). Deliberately NOT
                   total_bytes - free_bytes: that would fold the root reserve
                   into "used" and make used + free < total look like a bug
                   when it is really just the reserve neither term counts.
    percent_used   used / (used + free) * 100 -- `df`'s own formula (GNU
                   coreutils: 100 * used / (used + avail)), not used / total.
                   The two diverge by exactly the reserved-block fraction, and
                   `df` is what the number in the task's own audit (46%) and
                   everything an operator already knows about this host was
                   read from.
    """

    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent_used: float


def _usage_from_statvfs(vfs: os.statvfs_result) -> DiskUsage:
    """Pure arithmetic over an already-taken statvfs result. Split out from
    read_disk_usage so the derivation can be unit-tested with a fabricated
    struct and without a real filesystem."""
    total = vfs.f_frsize * vfs.f_blocks
    free = vfs.f_frsize * vfs.f_bavail
    used = total - (vfs.f_frsize * vfs.f_bfree)
    denominator = used + free
    percent_used = round((used / denominator) * 100, 1) if denominator else 0.0
    return DiskUsage(
        total_bytes=total,
        used_bytes=used,
        free_bytes=free,
        percent_used=percent_used,
    )


def read_disk_usage(path: str) -> DiskUsage:
    """Blocking. `os.statvfs` is a syscall, not a thread-safety issue, but it
    still blocks the calling thread for the duration of the call -- run this
    through `asyncio.to_thread` (see `get_disk_usage`), never awaited directly
    from a coroutine.

    Raises OSError (FileNotFoundError, PermissionError, ...) exactly as
    os.statvfs does; callers that need "unavailable" rather than an exception
    should use get_disk_usage.
    """
    return _usage_from_statvfs(os.statvfs(path))


async def get_disk_usage(path: str) -> Optional[DiskUsage]:
    """Disk capacity for `path`, or None if it cannot be read.

    None rather than a raised exception: this backs one field of the admin
    dashboard, not a startup check, so an unreadable path -- wrong mount, a
    permission error, whatever -- should degrade that one field rather than
    the whole /api/admin/dashboard response with a 500.
    """
    try:
        return await asyncio.to_thread(read_disk_usage, path)
    except OSError as exc:
        logger.warning("Disk usage check failed", path=path, error=str(exc))
        return None
