"""The orphaned-sync reaper.

The defect: if the sync container dies mid-rsync -- OOM kill, host reboot,
SIGKILL -- the completion block in sync_mirror_job never runs. The SyncJob row
stays RUNNING and the Mirror row stays SYNCING forever, and trigger_sync
(backend/app/api/admin.py) then refuses every manual retry with "Mirror is
already syncing". Recovery was a hand-written UPDATE against production.

The hard part was never detecting staleness. It was not killing a live sync.
Production job 615 ran for 15 hours 43 minutes and was healthy the whole time:
a 2.58 TB OpenBSD transfer of 567,277 files. Job 624 was the same mirror,
incremental, and finished in 13 minutes. Any elapsed-time threshold either
reaps job 615 at hour fifteen or is so generous it never fires. So the reaper
uses no threshold at all -- it asks whether the single process that runs jobs
is running *this* job, and a RUNNING row it does not own is a row nothing will
advance.

This file is organised as:

  1. the decision, as a table -- every combination, including job 615's
  2. the decision under mutation -- break it on purpose, require a red test
  3. the reaper against a real database
  4. job 615 end to end: a reaper pass fired *during* a live 15h43m transfer
  5. the structural invariants the decision rests on
  6. the API side: what being stuck actually costs, and that clearing it helps
"""
import ast
import asyncio
import inspect
import logging
import pathlib
import textwrap
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from shared.models import Mirror, MirrorStatus, SyncJob, SyncStatus
from sync import sync_service
from sync.sync_service import (
    LONG_RUNNING_REAP_WARN_SECONDS,
    _as_utc,
    _orphan_verdict,
)

# The engine / factory / service / mirror fixtures come from tests/conftest.py
# and are auto-discovered. Only the non-fixture helpers are imported.
from tests.conftest import PREVIOUS_SYNC, FakeProcess, auth_header, reload, run_job

# Job 615's real rsync output, transcribed from the production run.
from tests.test_sync_job import JOB_615_EXIT_24

SYNC_SERVICE_PATH = pathlib.Path(sync_service.__file__)

# Job 615's real elapsed time. Used as an argument, never as a threshold.
JOB_615_ELAPSED = timedelta(hours=15, minutes=43)

NOW = datetime(2026, 8, 29, 20, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 1. The decision
#
# (name, job_id, status, started_at, active_job_ids, expect_reap, why)
# ---------------------------------------------------------------------------
DECISIONS = [
    (
        "job_615_at_hour_fifteen_is_not_reaped",
        615, SyncStatus.RUNNING, NOW - JOB_615_ELAPSED, {615}, False,
        "the real one. 15h43m into a healthy 2.58 TB transfer, owned by this "
        "process. Duration is not consulted, so hour fifteen is no different "
        "from minute one.",
    ),
    (
        "job_615_at_hour_fifteen_unowned_is_reaped",
        615, SyncStatus.RUNNING, NOW - JOB_615_ELAPSED, set(), True,
        "the same row, same age, with the difference that decides it: nothing "
        "is running it.",
    ),
    (
        "a_thirteen_minute_incremental_is_not_reaped_either",
        624, SyncStatus.RUNNING, NOW - timedelta(minutes=13), {624}, False,
        "job 624, the same mirror. Short and owned.",
    ),
    (
        "a_thirteen_minute_orphan_is_reaped_immediately",
        624, SyncStatus.RUNNING, NOW - timedelta(minutes=13), set(), True,
        "no grace period. A crash thirteen minutes ago is as dead as one from "
        "last week, and waiting only extends the outage.",
    ),
    (
        "an_orphan_from_one_second_ago_is_reaped",
        700, SyncStatus.RUNNING, NOW - timedelta(seconds=1), set(), True,
        "the claim is taken before the row says RUNNING, so an unclaimed "
        "RUNNING row is never merely young.",
    ),
    (
        "another_jobs_claim_does_not_protect_this_one",
        700, SyncStatus.RUNNING, NOW - timedelta(hours=2), {615, 624}, True,
        "membership is per job id, not 'is this process busy'.",
    ),
    (
        "a_running_job_with_no_started_at_is_an_orphan",
        701, SyncStatus.RUNNING, None, set(), True,
        "this process writes started_at in the same statement that sets "
        "RUNNING, so a RUNNING row without one was written by something else.",
    ),
    (
        "a_running_job_with_no_started_at_that_we_own_is_still_ours",
        702, SyncStatus.RUNNING, None, {702}, False,
        "ownership outranks every other signal, including a missing timestamp.",
    ),
    (
        "a_pending_job_is_not_touched",
        703, SyncStatus.PENDING, None, set(), False,
        "PENDING is the queue the reaper's own output feeds back into. "
        "Reaping it would fail the retry that is meant to fix things.",
    ),
    (
        "a_completed_job_is_not_touched",
        704, SyncStatus.COMPLETED, NOW - timedelta(days=90), set(), False,
        "finished ninety days ago and unowned. Only RUNNING is reapable.",
    ),
    (
        "a_failed_job_is_not_touched",
        705, SyncStatus.FAILED, NOW - timedelta(days=90), set(), False,
        "already terminal.",
    ),
    (
        "a_cancelled_job_is_not_touched",
        706, SyncStatus.CANCELLED, NOW - timedelta(days=90), set(), False,
        "already terminal.",
    ),
    (
        "a_naive_started_at_is_read_as_utc",
        707, SyncStatus.RUNNING, (NOW - JOB_615_ELAPSED).replace(tzinfo=None), {707}, False,
        "SQLite drops tzinfo where Postgres keeps it. Both must reach the same "
        "verdict, and a mis-read timezone must not become an eight-hour error "
        "in the reported elapsed time.",
    ),
]


@pytest.mark.parametrize(
    "name,job_id,status,started_at,active,expect_reap,why",
    DECISIONS, ids=[case[0] for case in DECISIONS],
)
def test_the_decision(name, job_id, status, started_at, active, expect_reap, why):
    verdict = _orphan_verdict(
        job_id=job_id,
        job_status=status,
        started_at=started_at,
        active_job_ids=active,
        now=NOW,
    )
    assert verdict.reap is expect_reap, why


def test_elapsed_is_reported_for_the_log_line():
    """Reported, never consulted. It is what an operator reads to decide whether
    a reap was a surprise."""
    verdict = _orphan_verdict(
        job_id=615,
        job_status=SyncStatus.RUNNING,
        started_at=NOW - JOB_615_ELAPSED,
        active_job_ids=set(),
        now=NOW,
    )
    assert verdict.elapsed_seconds == pytest.approx(JOB_615_ELAPSED.total_seconds())


def test_a_naive_timestamp_gives_the_same_elapsed_as_an_aware_one():
    aware = _orphan_verdict(615, SyncStatus.RUNNING, NOW - JOB_615_ELAPSED, set(), NOW)
    naive = _orphan_verdict(
        615, SyncStatus.RUNNING, (NOW - JOB_615_ELAPSED).replace(tzinfo=None), set(), NOW
    )
    assert aware.elapsed_seconds == naive.elapsed_seconds


def test_as_utc_does_not_shift_an_already_aware_value():
    aware = datetime(2026, 8, 29, 4, 0, tzinfo=timezone.utc)
    assert _as_utc(aware) is aware


def test_the_verdict_carries_a_reason():
    """It goes into the log line next to the job id. 'reap=True' on its own is
    not something an operator can act on."""
    owned = _orphan_verdict(615, SyncStatus.RUNNING, NOW, {615}, NOW)
    orphan = _orphan_verdict(615, SyncStatus.RUNNING, NOW, set(), NOW)
    assert owned.reason != orphan.reason
    assert owned.reason and orphan.reason


# ---------------------------------------------------------------------------
# 2. The decision under mutation
#
# Same approach as the rsync classifier and the admin.js escaper: break the
# function on purpose and require the table above to notice. A decision table
# that passes against a deliberately broken decision is not testing it.
#
# The function is pure and self-contained, so it can be re-exec'd in isolation
# with only the names it closes over injected.
#
# (name, old, new, must_fail) -- must_fail names one case that has to flip, so
# a mutation cannot be "caught" by some unrelated assertion.
# ---------------------------------------------------------------------------

def _decision_source() -> str:
    """The real text of the decision, straight out of sync_service.py."""
    return "\n\n".join(
        textwrap.dedent(inspect.getsource(obj))
        for obj in (sync_service.OrphanVerdict, sync_service._as_utc, sync_service._orphan_verdict)
    )


def _load_decision(source: str):
    namespace = {
        "datetime": datetime,
        "timezone": timezone,
        "Optional": __import__("typing").Optional,
        "AbstractSet": __import__("typing").AbstractSet,
        "NamedTuple": __import__("typing").NamedTuple,
        "SyncStatus": SyncStatus,
    }
    exec(compile(source, "<mutated _orphan_verdict>", "exec"), namespace)
    return namespace["_orphan_verdict"]


def _run_decision_table(fn):
    """Every case from DECISIONS, as {name: passed}."""
    results = {}
    for name, job_id, status, started_at, active, expect_reap, _why in DECISIONS:
        try:
            verdict = fn(
                job_id=job_id,
                job_status=status,
                started_at=started_at,
                active_job_ids=active,
                now=NOW,
            )
            results[name] = verdict.reap is expect_reap
        except Exception:
            results[name] = False
    return results


def test_the_unmutated_decision_passes_its_own_table():
    """The harness has to agree with the real function before it can be trusted
    to judge a broken one."""
    results = _run_decision_table(_load_decision(_decision_source()))
    assert all(results.values()), [n for n, ok in results.items() if not ok]


OWNERSHIP_BRANCH = """    if job_id in active_job_ids:
        return OrphanVerdict(False, "this process is running it", elapsed)"""

STATUS_BRANCH = """    if job_status != SyncStatus.RUNNING:
        return OrphanVerdict(False, f"status is {job_status.value}, not running", elapsed)"""

MUTATIONS = [
    (
        # The design the brief warned about, written out in full. Reap anything
        # that has been running longer than an hour. It passes every easy case
        # and loses a 2.5 TB transfer at hour fifteen.
        "replace_ownership_with_a_naive_elapsed_threshold",
        OWNERSHIP_BRANCH,
        """    if elapsed is not None and elapsed < 3600:
        return OrphanVerdict(False, "started recently", elapsed)""",
        "job_615_at_hour_fifteen_is_not_reaped",
    ),
    (
        # The generous version of the same mistake: six hours instead of one.
        # Still kills job 615, just later in its run.
        "add_a_six_hour_ceiling_on_top_of_ownership",
        OWNERSHIP_BRANCH,
        """    if job_id in active_job_ids and not (elapsed is not None and elapsed > 21600):
        return OrphanVerdict(False, "this process is running it", elapsed)""",
        "job_615_at_hour_fifteen_is_not_reaped",
    ),
    (
        # The other half of the same trade: a threshold long enough never to
        # touch job 615 is long enough to leave an outage running for a day.
        "require_a_job_to_be_stale_before_reaping_it",
        """    return OrphanVerdict(True, "no process in this service is running it", elapsed)""",
        """    if elapsed is not None and elapsed < 86400:
        return OrphanVerdict(False, "not stale yet", elapsed)
    return OrphanVerdict(True, "no process in this service is running it", elapsed)""",
        "a_thirteen_minute_orphan_is_reaped_immediately",
    ),
    (
        "invert_the_ownership_test",
        "    if job_id in active_job_ids:",
        "    if job_id not in active_job_ids:",
        "job_615_at_hour_fifteen_is_not_reaped",
    ),
    (
        "drop_the_ownership_test_entirely",
        OWNERSHIP_BRANCH + "\n",
        "",
        "job_615_at_hour_fifteen_is_not_reaped",
    ),
    (
        # "Is this process busy?" instead of "is it busy with THIS job?".
        # Looks equivalent while only one job runs at a time; it is not, and it
        # would make every orphan unreapable for as long as any sync is running.
        "ask_whether_the_process_is_busy_rather_than_which_job",
        "    if job_id in active_job_ids:",
        "    if active_job_ids:",
        "another_jobs_claim_does_not_protect_this_one",
    ),
    (
        "drop_the_status_test_entirely",
        STATUS_BRANCH + "\n",
        "",
        "a_pending_job_is_not_touched",
    ),
    (
        "widen_the_status_test_to_include_pending",
        "    if job_status != SyncStatus.RUNNING:",
        "    if job_status not in (SyncStatus.RUNNING, SyncStatus.PENDING):",
        "a_pending_job_is_not_touched",
    ),
    (
        "treat_a_completed_job_as_reapable",
        "    if job_status != SyncStatus.RUNNING:",
        "    if job_status == SyncStatus.FAILED:",
        "a_completed_job_is_not_touched",
    ),
    (
        # A RUNNING row with no started_at is exactly the row this process could
        # not have written. Excusing it means it is never cleared.
        "treat_a_missing_started_at_as_a_live_job",
        "    if job_status != SyncStatus.RUNNING:",
        "    if started_at is None or job_status != SyncStatus.RUNNING:",
        "a_running_job_with_no_started_at_is_an_orphan",
    ),
    (
        # Postgres returns aware datetimes, SQLite naive ones. Dropping the
        # normalisation raises on the naive path rather than returning a wrong
        # answer -- which is better, but still a failure to catch.
        "stop_normalising_naive_timestamps",
        "        elapsed = (now - _as_utc(started_at)).total_seconds()",
        "        elapsed = (now - started_at).total_seconds()",
        "a_naive_started_at_is_read_as_utc",
    ),
]


@pytest.mark.parametrize(
    "name,old,new,must_fail", MUTATIONS, ids=[m[0] for m in MUTATIONS]
)
def test_mutation_is_caught(name, old, new, must_fail):
    source = _decision_source()
    assert source.count(old) == 1, (
        f"mutation {name!r} no longer matches the decision exactly once "
        f"(found {source.count(old)}). Update the mutation, do not delete it."
    )

    mutated = _load_decision(source.replace(old, new))
    results = _run_decision_table(mutated)
    failed = sorted(n for n, ok in results.items() if not ok)

    assert failed, (
        f"mutation {name!r} broke the decision and every case still passed. "
        f"The table does not test what it claims to."
    )
    assert must_fail in failed, (
        f"mutation {name!r} was expected to fail {must_fail!r}, "
        f"but the failures were {failed}"
    )


def test_the_decision_never_reads_the_clock():
    """`now` is a parameter, and there is no other source of time in there.

    A decision that reads the clock cannot be replayed, and one that reads
    elapsed time cannot tell job 615 from a corpse. Both are ruled out
    structurally rather than by convention."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(sync_service._orphan_verdict)))
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "now" not in calls and "utcnow" not in calls and "time" not in calls


# ---------------------------------------------------------------------------
# 3. The reaper against a real database
# ---------------------------------------------------------------------------

def set_state(factory, mirror_id, job_id, *, job_status, mirror_status, started_at=None):
    session = factory()
    try:
        session.execute(
            update(SyncJob).where(SyncJob.id == job_id).values(
                status=job_status,
                started_at=started_at or (datetime.now(timezone.utc) - JOB_615_ELAPSED),
            )
        )
        session.execute(
            update(Mirror).where(Mirror.id == mirror_id).values(status=mirror_status)
        )
        session.commit()
    finally:
        session.close()


async def test_a_crashed_sync_is_cleared_on_startup(service, factory, mirror):
    """The whole defect, in one test. A process that has just started owns no
    jobs, so every RUNNING row belongs to a process that is gone."""
    set_state(factory, mirror["mirror_id"], mirror["job_id"],
              job_status=SyncStatus.RUNNING, mirror_status=MirrorStatus.SYNCING)
    service.active_job_ids = set()

    reaped = await service.reap_orphaned_jobs(trigger="startup")

    assert reaped == 1
    m, j = reload(factory, mirror["mirror_id"], mirror["job_id"])
    assert j.status == SyncStatus.FAILED
    assert j.completed_at is not None
    assert "abandoned" in j.error_message
    assert m.status == MirrorStatus.ERROR
    assert m.last_sync_error


async def test_reaping_does_not_destroy_the_last_known_good_record(service, factory, mirror):
    """last_sync_completed answers "when was this mirror last known good", and
    a sync that died has no better answer. Same reasoning that keeps
    sync_mirror_job from clearing it on an ordinary failure."""
    set_state(factory, mirror["mirror_id"], mirror["job_id"],
              job_status=SyncStatus.RUNNING, mirror_status=MirrorStatus.SYNCING)

    await service.reap_orphaned_jobs(trigger="startup")

    m, _ = reload(factory, mirror["mirror_id"], mirror["job_id"])
    assert m.last_sync_completed.replace(tzinfo=timezone.utc) == PREVIOUS_SYNC
    assert m.total_size_bytes == 2_594_831_248_502
    assert m.file_count == 567_277


async def test_a_job_this_process_is_running_is_left_alone(service, factory, mirror):
    set_state(factory, mirror["mirror_id"], mirror["job_id"],
              job_status=SyncStatus.RUNNING, mirror_status=MirrorStatus.SYNCING)
    service.active_job_ids = {mirror["job_id"]}

    reaped = await service.reap_orphaned_jobs(trigger="scheduler")

    assert reaped == 0
    m, j = reload(factory, mirror["mirror_id"], mirror["job_id"])
    assert j.status == SyncStatus.RUNNING
    assert j.completed_at is None
    assert m.status == MirrorStatus.SYNCING, (
        "the second pass, which clears mirrors stuck in SYNCING, must not "
        "clear one whose job is still running"
    )


async def test_a_pending_job_is_not_reaped(service, factory, mirror):
    """PENDING is the queue. The mirror's retry lands there, and reaping it
    would break the recovery the reaper exists to enable."""
    set_state(factory, mirror["mirror_id"], mirror["job_id"],
              job_status=SyncStatus.PENDING, mirror_status=MirrorStatus.ACTIVE)

    assert await service.reap_orphaned_jobs(trigger="startup") == 0

    _, j = reload(factory, mirror["mirror_id"], mirror["job_id"])
    assert j.status == SyncStatus.PENDING


async def test_reaping_is_idempotent(service, factory, mirror):
    set_state(factory, mirror["mirror_id"], mirror["job_id"],
              job_status=SyncStatus.RUNNING, mirror_status=MirrorStatus.SYNCING)

    assert await service.reap_orphaned_jobs(trigger="startup") == 1
    assert await service.reap_orphaned_jobs(trigger="startup") == 0
    assert await service.reap_orphaned_jobs(trigger="scheduler") == 0


async def test_a_mirror_stuck_in_syncing_with_no_running_job_is_cleared(
    service, factory, mirror, caplog
):
    """Reaping the job cannot produce this state, but a deleted job row or a
    hand-edited table can -- and it blocks trigger_sync just as effectively."""
    set_state(factory, mirror["mirror_id"], mirror["job_id"],
              job_status=SyncStatus.COMPLETED, mirror_status=MirrorStatus.SYNCING)

    with caplog.at_level(logging.WARNING, logger="sync.sync_service"):
        await service.reap_orphaned_jobs(trigger="startup")

    m, _ = reload(factory, mirror["mirror_id"], mirror["job_id"])
    assert m.status == MirrorStatus.ERROR
    assert "stuck in SYNCING" in caplog.text


async def test_reaping_a_stale_job_does_not_disturb_a_mirror_that_moved_on(
    service, factory, mirror
):
    """A RUNNING row can outlive its relevance.

    Sequence: the container is SIGKILLed mid-sync, leaving job N RUNNING. It
    restarts, the operator retries, job N+1 succeeds, and the mirror is ACTIVE
    and current. Job N is still RUNNING in the table -- if the reaper's mirror
    update is not conditioned on the mirror actually being SYNCING, clearing
    that stale row drags a healthy, freshly-synced mirror into ERROR and posts
    a sync failure that did not happen.

    The job is still closed out. Only the mirror is left alone.
    """
    set_state(factory, mirror["mirror_id"], mirror["job_id"],
              job_status=SyncStatus.RUNNING, mirror_status=MirrorStatus.ACTIVE)

    assert await service.reap_orphaned_jobs(trigger="startup") == 1

    m, j = reload(factory, mirror["mirror_id"], mirror["job_id"])
    assert j.status == SyncStatus.FAILED, "the stale row must still be closed"
    assert m.status == MirrorStatus.ACTIVE, (
        "the mirror had moved on; reaping an old job must not report a failure "
        "against a mirror that is currently fine"
    )
    assert m.last_sync_error is None, "no error to show: nothing is wrong with it"


@pytest.mark.parametrize(
    "status", [MirrorStatus.ACTIVE, MirrorStatus.ERROR, MirrorStatus.DISABLED]
)
async def test_a_mirror_not_claiming_to_sync_is_never_touched(
    service, factory, mirror, status
):
    set_state(factory, mirror["mirror_id"], mirror["job_id"],
              job_status=SyncStatus.COMPLETED, mirror_status=status)

    await service.reap_orphaned_jobs(trigger="startup")

    m, _ = reload(factory, mirror["mirror_id"], mirror["job_id"])
    assert m.status == status


async def test_reaping_a_long_run_is_logged_at_warning(service, factory, mirror, caplog):
    """Elapsed time decides nothing, but a reap of something job-615-shaped is
    worth being loud about. If this service ever gets one wrong, the operator
    should find it in the log rather than in the size of the mirror."""
    set_state(factory, mirror["mirror_id"], mirror["job_id"],
              job_status=SyncStatus.RUNNING, mirror_status=MirrorStatus.SYNCING)

    with caplog.at_level(logging.INFO, logger="sync.sync_service"):
        await service.reap_orphaned_jobs(trigger="startup")

    reaped = [r for r in caplog.records if "Reaped orphaned sync job" in r.getMessage()]
    assert reaped and reaped[0].levelno == logging.WARNING
    assert JOB_615_ELAPSED.total_seconds() > LONG_RUNNING_REAP_WARN_SECONDS


async def test_reaping_a_short_run_is_logged_at_info(service, factory, mirror, caplog):
    set_state(
        factory, mirror["mirror_id"], mirror["job_id"],
        job_status=SyncStatus.RUNNING, mirror_status=MirrorStatus.SYNCING,
        started_at=datetime.now(timezone.utc) - timedelta(minutes=13),
    )

    with caplog.at_level(logging.INFO, logger="sync.sync_service"):
        await service.reap_orphaned_jobs(trigger="startup")

    reaped = [r for r in caplog.records if "Reaped orphaned sync job" in r.getMessage()]
    assert reaped and reaped[0].levelno == logging.INFO


# ---------------------------------------------------------------------------
# 4. Job 615, end to end: a reaper pass fired during a live transfer
#
# The tests above hand the decision a row. These two run a real sync_mirror_job
# through the real claim/release path, hold it open in the middle of rsync,
# back-date the row to job 615's actual elapsed time, and then fire the reaper
# at it. That is the failure this design exists to prevent, reproduced as
# closely as a test can.
# ---------------------------------------------------------------------------

class BlockingProcess(FakeProcess):
    """A transfer that has started and has not finished. communicate() reports
    that it is under way and then waits to be released."""

    def __init__(self, returncode, output, started, release):
        super().__init__(returncode, output)
        self._started = started
        self._release = release

    async def communicate(self):
        self._started.set()
        await self._release.wait()
        return await super().communicate()


@pytest.fixture
def in_flight_rsync(monkeypatch):
    """Replace create_subprocess_exec with one that stalls mid-transfer.

    The Events are built inside configure(), which the tests call from within
    the running loop. Building them in the fixture body binds them to whatever
    loop is current when fixtures are set up, and awaiting them from the test's
    loop then raises "attached to a different loop".
    """

    def configure(returncode, output):
        started = asyncio.Event()
        release = asyncio.Event()

        async def fake_exec(*cmd, **kwargs):
            return BlockingProcess(returncode, output, started, release)

        monkeypatch.setattr(sync_service.asyncio, "create_subprocess_exec", fake_exec)
        return started, release

    return configure


def backdate(factory, job_id, elapsed):
    """Make the row as old as the run it stands in for, without waiting."""
    session = factory()
    try:
        session.execute(
            update(SyncJob).where(SyncJob.id == job_id).values(
                started_at=datetime.now(timezone.utc) - elapsed
            )
        )
        session.commit()
    finally:
        session.close()


async def test_a_live_job_615_survives_a_reaper_pass_at_hour_fifteen(
    service, in_flight_rsync, factory, mirror, caplog
):
    """The test the whole design is for.

    A real sync_mirror_job, in the middle of a real (faked) rsync, whose row
    has been aged to job 615's actual 15h43m. The reaper runs against the live
    database while the transfer is still going, and must not touch it. Then the
    transfer finishes and is recorded exactly as it would have been.

    A reaper that passes only the easy cases is how you lose a 2.5 TB transfer
    at hour fifteen; this is the case that is not easy.
    """
    started, release = in_flight_rsync(24, JOB_615_EXIT_24)

    transfer = asyncio.create_task(run_job(service, mirror))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)

        # Mid-transfer, and now fifteen hours and forty-three minutes in.
        backdate(factory, mirror["job_id"], JOB_615_ELAPSED)

        m, j = reload(factory, mirror["mirror_id"], mirror["job_id"])
        assert j.status == SyncStatus.RUNNING
        assert m.status == MirrorStatus.SYNCING
        assert mirror["job_id"] in service.active_job_ids, (
            "the claim must be held for the whole run, not just taken at the end"
        )

        with caplog.at_level(logging.INFO, logger="sync.sync_service"):
            reaped = await service.reap_orphaned_jobs(trigger="scheduler")

        assert reaped == 0, "a live 15h43m transfer was reaped"
        assert "Reaped orphaned sync job" not in caplog.text

        m, j = reload(factory, mirror["mirror_id"], mirror["job_id"])
        assert j.status == SyncStatus.RUNNING, "the reaper altered a live job"
        assert j.completed_at is None
        assert m.status == MirrorStatus.SYNCING, "the reaper altered a live mirror"
    finally:
        release.set()
        await asyncio.wait_for(transfer, timeout=5)

    # And the transfer completes as it always would have: exit 24, tolerated,
    # 2.58 TB and 567,277 files recorded.
    m, j = reload(factory, mirror["mirror_id"], mirror["job_id"])
    assert j.status == SyncStatus.COMPLETED
    assert j.bytes_transferred == 2_584_831_248_502
    assert j.files_transferred == 567_277
    assert m.status == MirrorStatus.ACTIVE
    assert m.total_size_bytes == 2_594_831_248_502
    assert mirror["job_id"] not in service.active_job_ids


async def test_repeated_reaper_passes_across_a_long_transfer_never_touch_it(
    service, in_flight_rsync, factory, mirror
):
    """Not one pass -- every pass. At REAP_INTERVAL_CYCLES a 15h43m run sees
    roughly 188 of them, and it only takes one to lose the transfer."""
    started, release = in_flight_rsync(24, JOB_615_EXIT_24)

    transfer = asyncio.create_task(run_job(service, mirror))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)

        for hour in range(1, 17):
            backdate(factory, mirror["job_id"], timedelta(hours=hour))
            assert await service.reap_orphaned_jobs(trigger="scheduler") == 0, (
                f"reaped at hour {hour}"
            )
    finally:
        release.set()
        await asyncio.wait_for(transfer, timeout=5)

    _, j = reload(factory, mirror["mirror_id"], mirror["job_id"])
    assert j.status == SyncStatus.COMPLETED


async def test_a_job_stranded_by_an_exception_is_reaped_without_a_restart(
    service, factory, mirror, monkeypatch
):
    """The case startup reaping cannot reach.

    If sync_mirror_job raises between marking the job RUNNING and marking it
    finished, scheduler_loop catches it and carries on -- the process lives, so
    no restart happens, and the row stays RUNNING forever. Releasing the claim
    in a `finally` is what makes the next scheduled pass clear it.
    """
    boom = RuntimeError("connection reset while committing")

    async def explode(job_id, mirror_id, name, upstream, local_path):
        # Reproduce the state the real body would have left: RUNNING row,
        # SYNCING mirror, then a failure before the completion block.
        set_state(factory, mirror_id, job_id,
                  job_status=SyncStatus.RUNNING, mirror_status=MirrorStatus.SYNCING)
        raise boom

    monkeypatch.setattr(service, "_sync_mirror_job", explode)

    with pytest.raises(RuntimeError):
        await run_job(service, mirror)

    assert service.active_job_ids == set(), (
        "the claim must be released even when the body raises, or the stranded "
        "job is protected from the reaper forever"
    )

    assert await service.reap_orphaned_jobs(trigger="scheduler") == 1
    m, j = reload(factory, mirror["mirror_id"], mirror["job_id"])
    assert j.status == SyncStatus.FAILED
    assert m.status == MirrorStatus.ERROR


# ---------------------------------------------------------------------------
# 5. The structural invariants the decision rests on
#
# The safety argument is about ordering: the claim is taken before the row says
# RUNNING and released after it stops saying so, with no await in between. That
# is a property of the source, so it is checked against the source.
# ---------------------------------------------------------------------------

def _function_def(name):
    tree = ast.parse(SYNC_SERVICE_PATH.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {SYNC_SERVICE_PATH}")


def test_the_claim_is_taken_before_anything_can_await():
    """`self.active_job_ids.add(job_id)` must be the first statement in
    sync_mirror_job, ahead of every await.

    This is what makes a false positive against a live local sync
    unrepresentable rather than merely unlikely: the reaper is a coroutine on
    the same event loop, so it can only run at an await point, and there is no
    await point between the claim and the UPDATE that sets RUNNING.
    """
    body = _function_def("sync_mirror_job").body
    statements = [s for s in body if not isinstance(s, ast.Expr) or
                  not isinstance(s.value, ast.Constant)]

    first = statements[0]
    assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Call)
    assert ast.unparse(first.value).startswith("self.active_job_ids.add")

    rest = statements[1:]
    assert len(rest) == 1 and isinstance(rest[0], ast.Try), (
        "everything after the claim must sit in a try, so the release is "
        "unconditional"
    )
    assert not any(isinstance(n, (ast.Await, ast.AsyncWith, ast.AsyncFor))
                   for n in ast.walk(first))


def test_the_claim_is_released_in_a_finally():
    """Not "after the happy path". A body that raised leaves a RUNNING row that
    nothing will finish, and the release is what makes it reapable."""
    try_node = _function_def("sync_mirror_job").body[-1]
    assert isinstance(try_node, ast.Try)
    released = [ast.unparse(s) for s in try_node.finalbody]
    assert any("self.active_job_ids.discard(job_id)" in s for s in released)


def test_active_job_ids_has_exactly_one_writer():
    """The reaper's entire decision reads this set. Anything else mutating it
    is a way to protect a dead job or expose a live one."""
    tree = ast.parse(SYNC_SERVICE_PATH.read_text())
    enclosing = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                enclosing.setdefault(child, node.name)

    writers = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"add", "discard", "remove", "clear", "pop", "update"}
                and "active_job_ids" in ast.unparse(node.func.value)):
            writers.add(enclosing.get(node, "<module>"))

    assert writers == {"sync_mirror_job"}, writers


def test_the_reaper_runs_at_startup_before_any_pending_job_is_picked_up():
    """Order matters: a mirror stuck in SYNCING from the crash would otherwise
    stay stuck for the whole first cycle."""
    calls = [
        ast.unparse(node)
        for node in ast.walk(_function_def("run"))
        if isinstance(node, ast.Call)
    ]
    reap = next(i for i, c in enumerate(calls) if "reap_orphaned_jobs" in c)
    poll = next(i for i, c in enumerate(calls) if "poll_pending_jobs" in c)
    assert reap < poll


def test_the_reaper_also_runs_periodically():
    """Startup reaping only helps if the service restarts. The scheduler pass
    is what covers a job stranded while this process kept running."""
    source = ast.unparse(_function_def("scheduler_loop"))
    assert "reap_orphaned_jobs" in source
    assert "REAP_INTERVAL_CYCLES" in source


def test_the_reaper_never_consults_elapsed_time_to_decide():
    """_orphan_verdict is the only thing allowed an opinion. The reaper reads
    verdict.elapsed_seconds for the log level and nothing else."""
    node = _function_def("reap_orphaned_jobs")
    source = ast.unparse(node)
    assert "verdict.reap" in source
    comparisons = [
        ast.unparse(n) for n in ast.walk(node)
        if isinstance(n, ast.Compare) and "elapsed" in ast.unparse(n)
    ]
    assert all("LONG_RUNNING_REAP_WARN_SECONDS" in c or "None" in c for c in comparisons), (
        f"elapsed time is compared against something other than the log "
        f"threshold: {comparisons}"
    )


# ---------------------------------------------------------------------------
# 6. The API side
# ---------------------------------------------------------------------------

async def test_a_mirror_stuck_in_syncing_refuses_every_retry(client, seed, db_session):
    """What the operator actually hit: admin.py's trigger_sync guard, with no
    way past it but an UPDATE against production."""
    db_session.execute(
        update(Mirror).where(Mirror.id == seed["mirror_id"]).values(
            status=MirrorStatus.SYNCING
        )
    )
    db_session.commit()

    response = await client.post(
        f"/api/admin/mirrors/{seed['mirror_id']}/sync",
        headers=auth_header(seed["users"]["admin"]),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Mirror is already syncing"


async def test_the_state_the_reaper_leaves_behind_accepts_a_retry(
    client, seed, db_session
):
    """ERROR is the point of moving the mirror out of SYNCING: it is honest
    about the tree on disk being a partial transfer, and it lets the operator
    retry from the panel instead of from psql."""
    db_session.execute(
        update(Mirror).where(Mirror.id == seed["mirror_id"]).values(
            status=MirrorStatus.ERROR,
            last_sync_error="Sync job abandoned: ...",
        )
    )
    db_session.commit()

    response = await client.post(
        f"/api/admin/mirrors/{seed['mirror_id']}/sync",
        headers=auth_header(seed["users"]["admin"]),
    )
    assert response.status_code == 200, response.text

    job_id = response.json()["job_id"]
    queued = db_session.execute(
        select(SyncJob).where(SyncJob.id == job_id)
    ).scalar_one()
    assert queued.status == SyncStatus.PENDING, (
        "the retry lands in the queue the reaper is careful not to touch"
    )
