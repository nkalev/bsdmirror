"""
Cross-mirror sync failures: GET /api/admin/sync-failures.

Sync history has always been readable one mirror at a time (GET
/api/mirrors/{id}/sync-history), and that shape hid a real incident: 101
FAILED rows sat in the database, split three ways by mirror, and the pattern
only became visible once someone ran a GROUP BY across all of them --

    2026-04..06     2 failures/month     baseline noise
    2026-07        33 failures           30 of them OpenBSD
    2026-08        33 failures           32 of them OpenBSD
    2026-09         0 failures

`SyncJob.error_message` was populated the whole time; nothing read it across
mirrors. This is that GROUP BY, standing.

This file is organised as:

  1. group_failure_incidents -- the grouping, as a table of named properties
  2. that table under mutation -- break the function, require it to notice
  3. mirror_failure_summary -- same shape, for the per-mirror totals
  4. that table under mutation
  5. the endpoint against a real (SQLite) database

Escaping of `error_message` in the rendered admin panel -- it is rsync's own
stderr, untrusted text capable of carrying paths, quotes and newlines -- is
proved separately in tests/test_admin_js_escaping.py via
tests/js/escaping_harness.mjs's renderSyncFailures checks; it is not repeated
here. This file only proves the backend never mangles or half-escapes the
string before it gets there (see test_error_message_round_trips_byte_for_byte
below): escaping is the frontend's job, done exactly once, at the point
admin.js builds markup.
"""
import inspect
import textwrap
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Sequence

import pytest

from app.core import sync_failures
from app.core.sync_failures import group_failure_incidents, mirror_failure_summary
from shared.models import Mirror, MirrorStatus, MirrorType, SyncJob, SyncStatus
from tests.conftest import auth_header

T0 = datetime(2026, 7, 1, 4, 0, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


def _job(job_id, mirror_id, error_message, created_at, status=SyncStatus.FAILED):
    return SyncJob(
        id=job_id,
        mirror_id=mirror_id,
        status=status,
        error_message=error_message,
        created_at=created_at,
    )


def _mirror(mirror_id, name, mirror_type):
    return Mirror(
        id=mirror_id,
        name=name,
        mirror_type=mirror_type,
        upstream_url="rsync://example.test/",
        local_path="/data/mirrors/x",
        enabled=True,
        status=MirrorStatus.ACTIVE,
    )


def _run_checks(checks, fn):
    """Every named property in `checks`, as {name: passed}. Any exception --
    not just AssertionError -- counts as a failure, the same way a mutation
    that raises (a dropped zero-guard, say) should read as "broken", not
    "crashed, so it doesn't count"."""
    results = {}
    for name, check in checks.items():
        try:
            check(fn)
            results[name] = True
        except Exception:
            results[name] = False
    return results


# ---------------------------------------------------------------------------
# 1. group_failure_incidents
# ---------------------------------------------------------------------------


def _repeated_identical_errors_collapse_to_one_incident(fn):
    jobs = [
        _job(1, 1, "boom", T0),
        _job(2, 1, "boom", T0 + HOUR),
        _job(3, 1, "boom", T0 + 2 * HOUR),
    ]
    out = fn(jobs)
    assert len(out) == 1, out
    assert out[0]["occurrences"] == 3, out
    assert out[0]["mirror_id"] == 1


def _different_mirrors_with_the_same_error_stay_separate(fn):
    jobs = [_job(1, 1, "boom", T0), _job(2, 2, "boom", T0)]
    out = fn(jobs)
    assert len(out) == 2, out


def _different_errors_on_the_same_mirror_stay_separate(fn):
    jobs = [_job(1, 1, "boom", T0), _job(2, 1, "bang", T0)]
    out = fn(jobs)
    assert len(out) == 2, out


def _latest_job_id_breaks_ties_by_processing_order(fn):
    # Same timestamp on both -- callers are expected to sort (created_at, id)
    # ascending before calling this, so the job seen last (id 2) is "latest".
    jobs = [_job(1, 1, "boom", T0), _job(2, 1, "boom", T0)]
    out = fn(jobs)
    assert len(out) == 1
    assert out[0]["latest_job_id"] == 2, out


def _first_seen_is_the_true_minimum_even_out_of_order(fn):
    jobs = [_job(2, 1, "boom", T0 + HOUR), _job(1, 1, "boom", T0)]
    out = fn(jobs)
    assert out[0]["first_seen"] == T0, out


def _incidents_are_ordered_by_last_seen_descending(fn):
    jobs = [_job(1, 1, "old", T0), _job(2, 2, "new", T0 + 2 * HOUR)]
    out = fn(jobs)
    assert [g["error_message"] for g in out] == ["new", "old"], out


def _a_missing_error_message_is_its_own_group(fn):
    jobs = [_job(1, 1, None, T0), _job(2, 1, "boom", T0)]
    out = fn(jobs)
    assert len(out) == 2, out
    assert any(g["error_message"] is None for g in out), out


def _an_empty_job_list_produces_no_incidents(fn):
    assert fn([]) == []


INCIDENT_CHECKS = {
    "repeated identical errors collapse to one incident": _repeated_identical_errors_collapse_to_one_incident,
    "different mirrors with the same error stay separate": _different_mirrors_with_the_same_error_stay_separate,
    "different errors on the same mirror stay separate": _different_errors_on_the_same_mirror_stay_separate,
    "latest_job_id breaks ties by processing order": _latest_job_id_breaks_ties_by_processing_order,
    "first_seen is the true minimum even out of order": _first_seen_is_the_true_minimum_even_out_of_order,
    "incidents are ordered by last_seen descending": _incidents_are_ordered_by_last_seen_descending,
    "a missing error_message is its own group": _a_missing_error_message_is_its_own_group,
    "an empty job list produces no incidents": _an_empty_job_list_produces_no_incidents,
}


@pytest.mark.parametrize("name", sorted(INCIDENT_CHECKS), ids=lambda n: n.replace(" ", "_"))
def test_group_failure_incidents_property(name):
    INCIDENT_CHECKS[name](group_failure_incidents)


# ---------------------------------------------------------------------------
# 2. group_failure_incidents under mutation
#
# Same approach as the orphan reaper's decision table and the admin.js
# escaper: break the function on purpose and require the table above to
# notice. A property list that passes against a deliberately broken function
# is not testing it.
# ---------------------------------------------------------------------------

_EXEC_NAMESPACE = {
    "Iterable": Iterable,
    "List": List,
    "Sequence": Sequence,
    "Mirror": Mirror,
    "SyncJob": SyncJob,
    "SyncStatus": SyncStatus,
    "Counter": Counter,
}


def _load(source, name):
    namespace = dict(_EXEC_NAMESPACE)
    exec(compile(source, f"<mutated {name}>", "exec"), namespace)
    return namespace[name]


def _incidents_source():
    return textwrap.dedent(inspect.getsource(sync_failures.group_failure_incidents))


def test_the_unmutated_grouping_passes_every_check():
    """The harness has to agree with the real function before it can be
    trusted to judge a broken one."""
    fn = _load(_incidents_source(), "group_failure_incidents")
    results = _run_checks(INCIDENT_CHECKS, fn)
    assert all(results.values()), [n for n, ok in results.items() if not ok]


INCIDENT_MUTATIONS = [
    (
        "merge_across_mirrors",
        "key = (job.mirror_id, job.error_message)",
        "key = job.error_message",
        "different mirrors with the same error stay separate",
    ),
    (
        "merge_different_errors_on_one_mirror",
        "key = (job.mirror_id, job.error_message)",
        "key = job.mirror_id",
        "different errors on the same mirror stay separate",
    ),
    (
        # Off-by-comparison: a tie now keeps the FIRST job seen as "latest"
        # instead of the last, silently pointing "View Logs" at a stale job.
        "tie_break_uses_strict_greater_than",
        'if job.created_at >= bucket["last_seen"]:',
        'if job.created_at > bucket["last_seen"]:',
        "latest_job_id breaks ties by processing order",
    ),
    (
        "stop_tracking_the_true_first_seen",
        '        if job.created_at < bucket["first_seen"]:\n'
        '            bucket["first_seen"] = job.created_at\n',
        "",
        "first_seen is the true minimum even out of order",
    ),
    (
        "sort_ascending_instead_of_descending",
        'return sorted(groups.values(), key=lambda g: g["last_seen"], reverse=True)',
        'return sorted(groups.values(), key=lambda g: g["last_seen"])',
        "incidents are ordered by last_seen descending",
    ),
    (
        # occurrences stops accumulating -- every incident reads as "1",
        # which is exactly the "62 unreadable rows" problem this exists to
        # fix, just relabelled as one row that undercounts by 61.
        "occurrences_stops_incrementing",
        'bucket["occurrences"] += 1',
        'bucket["occurrences"] = 1',
        "repeated identical errors collapse to one incident",
    ),
]


@pytest.mark.parametrize(
    "name,old,new,must_fail", INCIDENT_MUTATIONS, ids=[m[0] for m in INCIDENT_MUTATIONS]
)
def test_incident_mutation_is_caught(name, old, new, must_fail):
    source = _incidents_source()
    assert source.count(old) == 1, (
        f"mutation {name!r} no longer matches group_failure_incidents exactly "
        f"once (found {source.count(old)}). Update the mutation, do not delete it."
    )

    mutated = _load(source.replace(old, new), "group_failure_incidents")
    results = _run_checks(INCIDENT_CHECKS, mutated)
    failed = sorted(n for n, ok in results.items() if not ok)

    assert failed, (
        f"mutation {name!r} broke the grouping and every check still passed. "
        f"The table does not test what it claims to."
    )
    assert must_fail in failed, (
        f"mutation {name!r} was expected to fail {must_fail!r}, but the " f"failures were {failed}"
    )


# ---------------------------------------------------------------------------
# 3. mirror_failure_summary
# ---------------------------------------------------------------------------


def _a_mirror_with_no_jobs_still_appears_with_zero_counts(fn):
    m1 = _mirror(1, "FreeBSD", MirrorType.FREEBSD)
    m2 = _mirror(2, "NetBSD", MirrorType.NETBSD)
    jobs = [_job(1, 1, None, T0, status=SyncStatus.COMPLETED)]

    out = fn(jobs, [m1, m2])

    assert len(out) == 2, out
    row2 = next(r for r in out if r["mirror_id"] == 2)
    assert row2["failed"] == 0 and row2["completed"] == 0, row2
    assert row2["failure_rate_percent"] is None, row2


def _failed_and_completed_are_counted_independently(fn):
    m = _mirror(1, "OpenBSD", MirrorType.OPENBSD)
    jobs = [_job(i, 1, "boom", T0, status=SyncStatus.FAILED) for i in range(1, 3)] + [
        _job(i, 1, None, T0, status=SyncStatus.COMPLETED) for i in range(10, 15)
    ]

    out = fn(jobs, [m])

    assert out[0]["failed"] == 2, out
    assert out[0]["completed"] == 5, out


def _pending_and_cancelled_jobs_are_excluded_from_both_counters(fn):
    m = _mirror(1, "OpenBSD", MirrorType.OPENBSD)
    jobs = [
        _job(1, 1, None, T0, status=SyncStatus.PENDING),
        _job(2, 1, None, T0, status=SyncStatus.RUNNING),
        _job(3, 1, None, T0, status=SyncStatus.CANCELLED),
    ]

    out = fn(jobs, [m])

    assert out[0]["failed"] == 0 and out[0]["completed"] == 0, out


def _failure_rate_percent_reflects_the_true_ratio(fn):
    m = _mirror(1, "OpenBSD", MirrorType.OPENBSD)
    jobs = [_job(1, 1, "boom", T0, status=SyncStatus.FAILED)] + [
        _job(i, 1, None, T0, status=SyncStatus.COMPLETED) for i in range(10, 13)
    ]

    out = fn(jobs, [m])

    assert out[0]["failure_rate_percent"] == 25.0, out


def _mirrors_are_ordered_by_failed_count_descending(fn):
    m_low = _mirror(1, "Low", MirrorType.FREEBSD)
    m_high = _mirror(2, "High", MirrorType.NETBSD)
    m_mid = _mirror(3, "Mid", MirrorType.OPENBSD)
    jobs = [_job(i, 2, "x", T0, status=SyncStatus.FAILED) for i in range(1, 6)] + [
        _job(i, 3, "x", T0, status=SyncStatus.FAILED) for i in range(10, 12)
    ]

    out = fn(jobs, [m_low, m_high, m_mid])

    assert [r["mirror_id"] for r in out] == [2, 3, 1], out


SUMMARY_CHECKS = {
    "a mirror with no jobs at all still appears with zero counts": _a_mirror_with_no_jobs_still_appears_with_zero_counts,
    "failed and completed are counted independently": _failed_and_completed_are_counted_independently,
    "pending and cancelled jobs are excluded from both counters": _pending_and_cancelled_jobs_are_excluded_from_both_counters,
    "failure_rate_percent reflects the true ratio": _failure_rate_percent_reflects_the_true_ratio,
    "mirrors are ordered by failed count descending": _mirrors_are_ordered_by_failed_count_descending,
}


@pytest.mark.parametrize("name", sorted(SUMMARY_CHECKS), ids=lambda n: n.replace(" ", "_"))
def test_mirror_failure_summary_property(name):
    SUMMARY_CHECKS[name](mirror_failure_summary)


# ---------------------------------------------------------------------------
# 4. mirror_failure_summary under mutation
# ---------------------------------------------------------------------------


def _summary_source():
    return textwrap.dedent(inspect.getsource(sync_failures.mirror_failure_summary))


def test_the_unmutated_summary_passes_every_check():
    fn = _load(_summary_source(), "mirror_failure_summary")
    results = _run_checks(SUMMARY_CHECKS, fn)
    assert all(results.values()), [n for n, ok in results.items() if not ok]


SUMMARY_MUTATIONS = [
    (
        "swap_failed_and_completed_counters",
        "        if job.status == SyncStatus.FAILED:\n"
        "            failed[job.mirror_id] += 1\n"
        "        elif job.status == SyncStatus.COMPLETED:\n"
        "            completed[job.mirror_id] += 1",
        "        if job.status == SyncStatus.FAILED:\n"
        "            completed[job.mirror_id] += 1\n"
        "        elif job.status == SyncStatus.COMPLETED:\n"
        "            failed[job.mirror_id] += 1",
        "failed and completed are counted independently",
    ),
    (
        # Removes the zero-jobs guard. A mirror with nothing in the window
        # now raises ZeroDivisionError instead of reading "0 failed".
        "failure_rate_drops_the_zero_guard",
        '"failure_rate_percent": round(f / total * 100, 1) if total else None,',
        '"failure_rate_percent": round(f / total * 100, 1),',
        "a mirror with no jobs at all still appears with zero counts",
    ),
    (
        "sort_ascending_instead_of_descending",
        'return sorted(summary, key=lambda s: s["failed"], reverse=True)',
        'return sorted(summary, key=lambda s: s["failed"])',
        "mirrors are ordered by failed count descending",
    ),
    (
        # "Why list a mirror with nothing to show" -- exactly the
        # optimisation that makes a healthy mirror indistinguishable from
        # one no data has loaded for yet.
        "skip_mirrors_with_no_jobs_at_all",
        "for mirror in mirrors:",
        "for mirror in mirrors:\n"
        "        if mirror.id not in failed and mirror.id not in completed:\n"
        "            continue",
        "a mirror with no jobs at all still appears with zero counts",
    ),
]


@pytest.mark.parametrize(
    "name,old,new,must_fail", SUMMARY_MUTATIONS, ids=[m[0] for m in SUMMARY_MUTATIONS]
)
def test_summary_mutation_is_caught(name, old, new, must_fail):
    source = _summary_source()
    assert source.count(old) == 1, (
        f"mutation {name!r} no longer matches mirror_failure_summary exactly "
        f"once (found {source.count(old)}). Update the mutation, do not delete it."
    )

    mutated = _load(source.replace(old, new), "mirror_failure_summary")
    results = _run_checks(SUMMARY_CHECKS, mutated)
    failed = sorted(n for n, ok in results.items() if not ok)

    assert failed, f"mutation {name!r} broke the summary and every check still passed."
    assert must_fail in failed, (
        f"mutation {name!r} was expected to fail {must_fail!r}, but the " f"failures were {failed}"
    )


# ---------------------------------------------------------------------------
# 5. The endpoint, against a real (SQLite) database
# ---------------------------------------------------------------------------


def _failed_job(db_session, mirror_id, error_message, created_at):
    job = SyncJob(
        mirror_id=mirror_id,
        status=SyncStatus.FAILED,
        error_message=error_message,
        created_at=created_at,
        triggered_by="scheduled",
    )
    db_session.add(job)
    db_session.commit()
    return job


def _completed_job(db_session, mirror_id, created_at):
    job = SyncJob(
        mirror_id=mirror_id,
        status=SyncStatus.COMPLETED,
        created_at=created_at,
        triggered_by="scheduled",
    )
    db_session.add(job)
    db_session.commit()
    return job


async def test_sync_failures_groups_repeated_identical_errors_end_to_end(client, seed, db_session):
    now = datetime.now(timezone.utc)
    for i in range(3):
        _failed_job(
            db_session, seed["mirror_id"], "rsync: connection timed out", now - timedelta(hours=i)
        )

    resp = await client.get(
        "/api/admin/sync-failures", headers=auth_header(seed["users"]["readonly"])
    )
    assert resp.status_code == 200

    incidents = resp.json()["incidents"]
    matching = [i for i in incidents if i["error_message"] == "rsync: connection timed out"]
    assert len(matching) == 1, incidents
    assert matching[0]["occurrences"] == 3
    assert matching[0]["mirror_id"] == seed["mirror_id"]
    assert matching[0]["mirror_name"] == seed["mirror"].name


async def test_sync_failures_reports_the_success_count_alongside_failures(client, seed, db_session):
    now = datetime.now(timezone.utc)
    _failed_job(db_session, seed["mirror_id"], "boom", now)
    _completed_job(db_session, seed["mirror_id"], now)
    _completed_job(db_session, seed["mirror_id"], now)

    resp = await client.get("/api/admin/sync-failures", headers=auth_header(seed["users"]["admin"]))
    assert resp.status_code == 200
    body = resp.json()

    # conftest's `seed` fixture also creates one COMPLETED job for this
    # mirror, so the totals include it.
    assert body["totals"]["failed"] == 1
    assert body["totals"]["completed"] == 3

    row = next(m for m in body["by_mirror"] if m["mirror_id"] == seed["mirror_id"])
    assert row["failed"] == 1
    assert row["completed"] == 3
    assert row["failure_rate_percent"] == 25.0


async def test_sync_failures_respects_the_days_window(client, seed, db_session):
    now = datetime.now(timezone.utc)
    _failed_job(db_session, seed["mirror_id"], "recent failure", now - timedelta(days=1))
    _failed_job(db_session, seed["mirror_id"], "ancient failure", now - timedelta(days=90))

    resp = await client.get(
        "/api/admin/sync-failures?days=7", headers=auth_header(seed["users"]["operator"])
    )
    assert resp.status_code == 200
    messages = {i["error_message"] for i in resp.json()["incidents"]}
    assert "recent failure" in messages
    assert "ancient failure" not in messages


async def test_sync_failures_defaults_to_a_30_day_window(client, seed):
    resp = await client.get(
        "/api/admin/sync-failures", headers=auth_header(seed["users"]["readonly"])
    )
    assert resp.status_code == 200
    assert resp.json()["period_days"] == 30


async def test_sync_failures_error_message_round_trips_byte_for_byte(client, seed, db_session):
    """The backend must not escape, truncate or otherwise transform
    error_message -- that is admin.js's job, at the point it builds markup,
    proved in tests/test_admin_js_escaping.py. If this endpoint pre-escaped
    the string, the frontend's html`` would escape it a second time and an
    operator would read literal &amp;lt; in the panel."""
    hostile = '<script>alert(1)</script>\nrsync: "/pub/OpenBSD/7.9" failed & retried'
    now = datetime.now(timezone.utc)
    _failed_job(db_session, seed["mirror_id"], hostile, now)

    resp = await client.get(
        "/api/admin/sync-failures", headers=auth_header(seed["users"]["readonly"])
    )
    assert resp.status_code == 200
    incident = next(
        i
        for i in resp.json()["incidents"]
        if i["mirror_id"] == seed["mirror_id"] and i["occurrences"] == 1
    )
    assert incident["error_message"] == hostile


async def test_sync_failures_limit_caps_the_number_of_incidents(client, seed, db_session):
    now = datetime.now(timezone.utc)
    for i in range(5):
        _failed_job(
            db_session, seed["mirror_id"], f"distinct error {i}", now - timedelta(minutes=i)
        )

    resp = await client.get(
        "/api/admin/sync-failures?limit=2", headers=auth_header(seed["users"]["admin"])
    )
    assert resp.status_code == 200
    assert len(resp.json()["incidents"]) == 2


async def test_sync_failures_with_no_failures_returns_an_empty_incident_list(client, seed):
    resp = await client.get(
        "/api/admin/sync-failures", headers=auth_header(seed["users"]["readonly"])
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["incidents"] == []
    assert body["totals"]["failed"] == 0
