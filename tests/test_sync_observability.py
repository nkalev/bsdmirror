"""files_deleted: recorded on every sync job, shown nowhere -- until now.

SyncJob.files_deleted is a real column (shared/models/sync_job.py) and the
sync service has parsed "Number of deleted files:" into it since
tests/test_rsync_stats.py's test_deleted_file_count_is_captured landed --
see sync/sync_service.py's _parse_rsync_stats docstring for that history.
Nothing downstream of the column ever read it:
`grep -c files_deleted frontend/public/admin/js/admin.js` was 0. A sync that
quietly deleted 400 GB of an EOL release looked, in this panel, identical to a
routine one that deleted nothing -- precisely the failure the new EOL-
retention filters (sync/protected_paths.py) are meant to guard against, with
the one number that would reveal a bad filter sitting unread in the database.

This file tests the three JSON endpoints admin.js reads a sync job through,
each of which needed exactly one field added:

  GET /api/admin/sync-jobs/{id}/logs      SyncJobLogResponse (admin.py)
  GET /api/mirrors/{id}/sync-history      a plain dict (mirrors.py)
  GET /api/admin/dashboard                recent_syncs[] (admin.py)

The rendering side -- admin.js marking a large count distinctly rather than
merely printing it -- is exercised by tests/js/escaping_harness.mjs via
tests/test_admin_js_escaping.py's filesDeletedBadge and renderDashboard
checks; it is not repeated here.
"""
from shared.models import SyncJob, SyncStatus
from tests.conftest import auth_header


def _job_with_files_deleted(db_session, mirror_id, files_deleted):
    """A completed SyncJob with only files_deleted set explicitly; every
    other column keeps its model default (in particular, files_transferred
    and bytes_transferred stay NULL, matching a job whose only interesting
    outcome was a deletion)."""
    job = SyncJob(
        mirror_id=mirror_id,
        status=SyncStatus.COMPLETED,
        triggered_by="scheduled",
        files_deleted=files_deleted,
    )
    db_session.add(job)
    db_session.commit()
    return job


# A representative small figure (ordinary --delete churn), one at the exact
# boundary admin.js treats as "large" (LARGE_DELETION_THRESHOLD in admin.js),
# one comfortably past it in the shape of the actual incident this feature
# exists for (an EOL release's file count), and the zero case -- which must
# round-trip as 0, not be confused with the "parser never ran" NULL case
# covered separately below.
FILES_DELETED_VALUES = [0, 3, 1000, 500_000]


# ---------------------------------------------------------------------------
# GET /api/admin/sync-jobs/{id}/logs
# ---------------------------------------------------------------------------


async def test_sync_job_logs_reports_files_deleted_when_present(client, seed, db_session):
    for value in FILES_DELETED_VALUES:
        job = _job_with_files_deleted(db_session, seed["mirror_id"], value)
        resp = await client.get(
            f"/api/admin/sync-jobs/{job.id}/logs",
            headers=auth_header(seed["users"]["readonly"]),
        )
        assert resp.status_code == 200
        assert resp.json()["files_deleted"] == value, f"round-trip failed for {value}"


async def test_sync_job_logs_reports_null_when_the_parser_never_set_it(client, seed):
    """conftest's `seed` fixture creates a job with every optional numeric
    column left at its default (NULL) -- the shape of a job whose rsync
    output never matched the "Number of deleted files:" branch at all, not
    one where zero were deleted. The two must stay distinguishable."""
    resp = await client.get(
        f"/api/admin/sync-jobs/{seed['job_id']}/logs",
        headers=auth_header(seed["users"]["admin"]),
    )
    assert resp.status_code == 200
    assert resp.json()["files_deleted"] is None


# ---------------------------------------------------------------------------
# GET /api/mirrors/{id}/sync-history
# ---------------------------------------------------------------------------


async def test_sync_history_reports_files_deleted_when_present(client, seed, db_session):
    for value in FILES_DELETED_VALUES:
        job = _job_with_files_deleted(db_session, seed["mirror_id"], value)
        resp = await client.get(f"/api/mirrors/{seed['mirror_id']}/sync-history?limit=50")
        assert resp.status_code == 200
        by_id = {row["id"]: row for row in resp.json()}
        assert by_id[job.id]["files_deleted"] == value, f"round-trip failed for {value}"


async def test_sync_history_reports_null_when_the_parser_never_set_it(client, seed):
    resp = await client.get(f"/api/mirrors/{seed['mirror_id']}/sync-history")
    assert resp.status_code == 200
    by_id = {row["id"]: row for row in resp.json()}
    assert by_id[seed["job_id"]]["files_deleted"] is None


# ---------------------------------------------------------------------------
# GET /api/admin/dashboard -- recent_syncs[]
# ---------------------------------------------------------------------------


async def test_dashboard_recent_syncs_reports_files_deleted(client, seed, db_session):
    """Only one representative value here, not the full table: recent_syncs
    is `.limit(5)`, so creating FILES_DELETED_VALUES worth of extra jobs on
    top of conftest's seeded one would start pushing earlier rows -- this
    test's own fixture data -- out of the window it is trying to read."""
    job = _job_with_files_deleted(db_session, seed["mirror_id"], 12_345)
    resp = await client.get("/api/admin/dashboard", headers=auth_header(seed["users"]["readonly"]))
    assert resp.status_code == 200
    by_id = {row["id"]: row for row in resp.json()["recent_syncs"]}
    assert by_id[job.id]["files_deleted"] == 12_345


async def test_dashboard_recent_syncs_reports_null_when_the_parser_never_set_it(client, seed):
    resp = await client.get("/api/admin/dashboard", headers=auth_header(seed["users"]["readonly"]))
    assert resp.status_code == 200
    by_id = {row["id"]: row for row in resp.json()["recent_syncs"]}
    assert by_id[seed["job_id"]]["files_deleted"] is None
