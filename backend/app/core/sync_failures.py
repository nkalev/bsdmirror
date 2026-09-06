"""
Cross-mirror sync failure aggregation for the admin panel.

Sync history has always been readable one mirror at a time (GET
/api/mirrors/{id}/sync-history), and that shape hid a real incident: 101
FAILED rows sat in the database, split three ways by mirror, and the pattern
only became visible once someone ran a GROUP BY across all of them --

    2026-04..06     2 failures/month     baseline noise
    2026-07        33 failures           30 of them OpenBSD
    2026-08        33 failures           32 of them OpenBSD
    2026-09         0 failures

`SyncJob.error_message` was populated the whole time; nothing read it across
mirrors. `GET /api/admin/sync-failures` (admin.py) is that read, and the two
functions below are what it is built on.

Both are pure functions over already-fetched SyncJob/Mirror rows -- no
session, no await -- specifically so they can be unit- and mutation-tested
without a database. See tests/test_admin_sync_failures.py.
"""
from collections import Counter
from typing import Iterable, List, Sequence

from shared.models import Mirror, SyncJob, SyncStatus


def group_failure_incidents(jobs: Iterable[SyncJob]) -> List[dict]:
    """Collapse repeated identical failures into incidents.

    One entry per distinct (mirror_id, error_message) pair among `jobs`: the
    July/August spike above was ~62 rows carrying what was effectively one
    fact ("OpenBSD's upstream is unreachable"), and a raw list of 62 identical
    rows is its own kind of unreadable. Grouping the same error on the same
    mirror into one incident with a count is what makes that fact visible
    instead of merely present.

    `jobs` is not filtered or sorted by this function -- callers pass
    whatever SyncStatus.FAILED rows are in the reporting window, in whatever
    order they were fetched. Ties in `created_at` (two jobs sharing a
    timestamp, which a test fixture can produce even though real rsync runs
    cannot) are broken by *iteration order*: whichever job is seen last is
    "latest". Callers that care about a deterministic tie-break should sort
    jobs by (created_at, id) ascending before calling this, which also makes
    "last seen" and "id of the most recent occurrence" agree.

    Returned sorted by last_seen, most recent first: the incident still
    happening belongs at the top of the admin view, not wherever its first
    occurrence would otherwise sort it.
    """
    groups: dict = {}
    for job in jobs:
        key = (job.mirror_id, job.error_message)
        bucket = groups.get(key)
        if bucket is None:
            bucket = {
                "mirror_id": job.mirror_id,
                "error_message": job.error_message,
                "occurrences": 0,
                "first_seen": job.created_at,
                "last_seen": job.created_at,
                "latest_job_id": job.id,
            }
            groups[key] = bucket

        bucket["occurrences"] += 1
        if job.created_at < bucket["first_seen"]:
            bucket["first_seen"] = job.created_at
        if job.created_at >= bucket["last_seen"]:
            bucket["last_seen"] = job.created_at
            bucket["latest_job_id"] = job.id

    return sorted(groups.values(), key=lambda g: g["last_seen"], reverse=True)


def mirror_failure_summary(jobs: Iterable[SyncJob], mirrors: Sequence[Mirror]) -> List[dict]:
    """Failed and completed counts, side by side, for every mirror.

    A failure count means little on its own: 62 failures out of 62 attempts
    is a dead upstream, 62 out of 1,000 is an ordinary Tuesday, and neither
    is distinguishable from the other without the completed count next to it.

    Every mirror in `mirrors` is represented, including one with zero of
    either -- a healthy mirror should read as "0 failed", not be absent from
    the table, which would look identical to "no data yet" or a rendering
    bug. `jobs` should be every job in the reporting window regardless of
    status; passing only failed jobs makes every `completed` figure read as
    zero.
    """
    failed: Counter = Counter()
    completed: Counter = Counter()
    for job in jobs:
        if job.status == SyncStatus.FAILED:
            failed[job.mirror_id] += 1
        elif job.status == SyncStatus.COMPLETED:
            completed[job.mirror_id] += 1

    summary = []
    for mirror in mirrors:
        f = failed[mirror.id]
        c = completed[mirror.id]
        total = f + c
        summary.append(
            {
                "mirror_id": mirror.id,
                "mirror_name": mirror.name,
                "mirror_type": mirror.mirror_type.value,
                "failed": f,
                "completed": c,
                "failure_rate_percent": round(f / total * 100, 1) if total else None,
            }
        )

    return sorted(summary, key=lambda s: s["failed"], reverse=True)
