"""
run_rsync exit-code handling and sync_mirror_job persistence.

Everything here is driven by production job 615: a 2.58 TB OpenBSD sync that
transferred 567,277 files over 15.7 hours, then exited 24 because five upstream
rsync temp files were deleted by the upstream mirror mid-copy. That run was
recorded FAILED, which in turn wiped Mirror.last_sync_completed and discarded
the size and file-count stats -- leaving the public site advertising 43 GB of a
2.5 TB mirror.

Two seams, both synthetic, both narrow:

  * asyncio.create_subprocess_exec is replaced so no rsync runs and no network
    is touched. The argv SyncService builds is captured and asserted on, so the
    fake cannot drift away from the real invocation unnoticed.
  * SyncService.session_maker is replaced with a synchronous SQLite session
    behind an async facade. aiosqlite is not in either requirements file (see
    the note in conftest.py) and adding a dependency is not this change's call.
    Every statement, mapping and constraint is real; only the await points are
    synthetic.

The schema comes from shared/models/ -- there is now only one copy, imported by
both services. This module used to build its tables from a second `Base` that
sync_service declared at the bottom of its own file, and that copy typed
mirrors.mirror_type as VARCHAR(20) where production has the Postgres enum
`mirror_type`. So this file was exercising a table shape that has never existed
in the database it is meant to describe, and could not have noticed: the test
and the code under test were the same wrong copy, agreeing with each other.

What that specifically changed for the fixture below: under VARCHAR(20) the
literal "openbsd" was stored verbatim, lowercase. Under the real column it is
coerced to the label 'OPENBSD' -- the enum members subclass str, so SQLAlchemy
resolves the lowercase value to its member and then persists the member NAME.
Same Python input, two different rows. The fixture now passes MirrorType.OPENBSD
so the intent is explicit rather than resting on that coercion.
"""
import logging
from datetime import datetime

import pytest

from shared.models import MirrorStatus, SyncStatus
from sync import sync_service
from sync.sync_service import (
    _classify_partial_transfer,
    _is_rsync_temp_path,
    _VANISHED_RE,
)

# ---------------------------------------------------------------------------
# rsync output fixtures
# ---------------------------------------------------------------------------

# Job 615, reconstructed in the rsync 3.2.7 --stats format. The five
# "file has vanished" lines are the temp files the upstream mirror deleted
# while it was itself syncing; each is an rsync temp file (leading dot, random
# six-character suffix), not a file the mirror was ever meant to hold.
#
# The trailing " (in OpenBSD)" on those lines is not decoration: it is what
# rsync 3.x emits, and every fixture in this file used to omit it because the
# sample they were transcribed from had been filtered through a grep that cut
# at the closing quote. See the job 619 section at the bottom -- that omission
# is what made the classifier reject a run it should have tolerated.
JOB_615_EXIT_24 = """\
receiving incremental file list
file has vanished: "/pub/OpenBSD/snapshots/packages/amd64/.base80.tgz.lLPdyl" (in OpenBSD)
file has vanished: "/pub/OpenBSD/snapshots/packages/amd64/.debug-spidermonkey140-140.14.0v1.tgz.2ML90i" (in OpenBSD)
file has vanished: "/pub/OpenBSD/snapshots/packages/amd64/.gcc-11.2.0p14.tgz.KjR1mQ" (in OpenBSD)
file has vanished: "/pub/OpenBSD/snapshots/packages/i386/.llvm-16.0.6p9.tgz.9wKzTb" (in OpenBSD)
file has vanished: "/pub/OpenBSD/snapshots/packages/arm64/.rust-1.78.0.tgz.Xq4mVn" (in OpenBSD)

Number of files: 571,398 (reg: 567,277, dir: 4,110, link: 11)
Number of created files: 567,277 (reg: 567,277)
Number of deleted files: 112 (reg: 111, dir: 1)
Number of regular files transferred: 567,277
Total file size: 2,594,831,248,502 bytes
Total transferred file size: 2,584,831,248,502 bytes
Literal data: 2,584,831,248,502 bytes
Matched data: 0 bytes
File list size: 14,286,848
File list generation time: 3.221 seconds
File list transfer time: 0.000 seconds
Total bytes sent: 11,405,312
Total bytes received: 2,585,442,119,680

sent 11,405,312 bytes  received 2,585,442,119,680 bytes  45,732,118.44 bytes/sec
total size is 2,594,831,248,502  speedup is 1.00
rsync warning: some files vanished before they could be transferred (code 24) at main.c(1338) [receiver=3.2.7]
"""

# A clean run of the same mirror.
CLEAN_EXIT_0 = """\
receiving incremental file list

Number of files: 571,398 (reg: 567,277, dir: 4,110, link: 11)
Number of created files: 0
Number of deleted files: 0
Number of regular files transferred: 0
Total file size: 2,594,831,248,502 bytes
Total transferred file size: 0 bytes
Total bytes sent: 155,478
Total bytes received: 1,203,456
"""

# Job 617: the incremental pass over the tree job 615 seeded. A textbook
# successful incremental -- 3,190 files moved, the whole 2.63 TB tree seen,
# speedup 424.29 -- that exited 23 and was recorded FAILED.
#
# Every error line is the same upstream race as job 615, caught on the other
# side of the rename. ftp.hostserver.de writes each file to an rsync temp name
# mode 0600 and then renames it into place; if we reach it before the rename we
# get Permission denied, if after the unlink we get "file has vanished".
JOB_617_EXIT_23 = """\
receiving incremental file list
rsync: [sender] send_files failed to open "/patches/.2.2.tar.gz.Yf874d" (in OpenBSD): Permission denied (13)
rsync: [sender] send_files failed to open "/snapshots/amd64/.install80.img.cG99qU" (in OpenBSD): Permission denied (13)
rsync: [sender] send_files failed to open "/snapshots/arm64/.base80.tgz.XVIpnS" (in OpenBSD): Permission denied (13)
rsync: [sender] send_files failed to open "/snapshots/i386/.install80.iso.rdGCa3" (in OpenBSD): Permission denied (13)
rsync: [sender] send_files failed to open "/snapshots/packages/aarch64/.chromium-151.0.7922.169.tgz.l4HNjI" (in OpenBSD): Permission denied (13)
rsync: [sender] send_files failed to open "/snapshots/powerpc64/.install80.iso.XfGnWV" (in OpenBSD): Permission denied (13)
file has vanished: "/snapshots/packages/amd64/.base80.tgz.lLPdyl" (in OpenBSD)
file has vanished: "/snapshots/i386/.install80.iso.9wKzTb" (in OpenBSD)

Number of files: 571,398 (reg: 567,277, dir: 4,110, link: 11)
Number of created files: 0
Number of deleted files: 4 (reg: 4)
Number of regular files transferred: 3,190
Total file size: 2,628,302,118,514 bytes
Total transferred file size: 6,194,382,336 bytes

sent 11,405,312 bytes  received 6,205,787,648 bytes  45,732,118.44 bytes/sec
total size is 2,628,302,118,514  speedup is 424.29
rsync error: some files/attrs were not transferred (code 23) at main.c(1338) [sender=3.2.7]
"""

# The dangerous shape: exit 23 where the unreadable file is real mirror
# content, not a temp file. Must stay a failure.
REAL_PERMISSION_ERROR_EXIT_23 = """\
receiving incremental file list
rsync: [sender] send_files failed to open "/snapshots/amd64/base80.tgz" (in OpenBSD): Permission denied (13)
file has vanished: "/snapshots/arm64/.base80.tgz.XVIpnS" (in OpenBSD)

Number of files: 571,398 (reg: 567,277, dir: 4,110, link: 11)
Total file size: 2,628,302,118,514 bytes
rsync error: some files/attrs were not transferred (code 23) at main.c(1338) [sender=3.2.7]
"""


# A genuine failure. rsync dies partway through, so the stats block describes
# only the fraction it managed before the connection dropped.
PARTIAL_THEN_EXIT_30 = """\
receiving incremental file list

Number of files: 12,004 (reg: 11,900, dir: 104)
Number of deleted files: 0
Number of regular files transferred: 11,900
Total file size: 43,112,974,336 bytes
Total transferred file size: 43,112,974,336 bytes

rsync error: timeout in data send/receive (code 30) at io.c(197) [receiver=3.2.7]
"""

# openrsync / rsync 2.6.9 compatible: the older spelling of the transferred
# count, and no parenthesised breakdown anywhere.
OLD_RSYNC_EXIT_0 = """\
Number of files: 5
Number of files transferred: 2
Total file size: 17 B
Total transferred file size: 12 B
"""


# ---------------------------------------------------------------------------
# Test doubles and fixtures
#
# FakeProcess, _SessionContext, the engine/factory/service/rsync/mirror
# fixtures and the reload/run_job helpers all live in tests/conftest.py now.
# They were defined here until a second module -- tests/test_orphan_reaper.py,
# which drives the same SyncService against the same OpenBSD mirror -- needed
# them. Importing fixtures across test modules works but makes ruff report
# every use as F811 (a parameter shadowing an imported name), and pytest's own
# answer to "two modules need the same fixture" is conftest.
#
# The non-fixture helpers still have to be imported; only fixtures are
# auto-discovered.
# ---------------------------------------------------------------------------
from tests.conftest import (  # noqa: E402
    PREVIOUS_SYNC,
    FakeProcess,
    reload,
    run_job,
)


# ---------------------------------------------------------------------------
# Defect 1: exit 24 is a warning, not a failure
# ---------------------------------------------------------------------------

async def test_exit_24_is_success_at_the_run_rsync_boundary(service, rsync, tmp_path):
    """`some files vanished before they could be transferred` is rsync telling
    you the source moved under it, not that the copy is broken."""
    rsync(24, JOB_615_EXIT_24)

    success, output, stats = await service.run_rsync(
        "rsync://ftp2.eu.openbsd.org/OpenBSD/", str(tmp_path / "openbsd"), "OpenBSD"
    )

    assert success is True
    assert "code 24" in output
    assert stats["regular_files"] == 567_277
    assert stats["total_size"] == 2_594_831_248_502


async def test_exit_24_records_a_completed_job_with_full_stats(service, rsync, factory, mirror):
    """The whole of job 615, end to end: COMPLETED, mirror ACTIVE, 2.58 TB and
    567,277 files stored, and the warning text kept for an operator to read.

    Note what is NOT here: no new SyncStatus member. This repo has no
    migrations -- schema comes from Base.metadata.create_all -- so a
    "completed with warnings" enum value would never exist in the production
    database. The signal lives in rsync_output instead.
    """
    rsync(24, JOB_615_EXIT_24)

    await run_job(service, mirror)

    m, j = reload(factory, mirror["mirror_id"], mirror["job_id"])

    assert j.status is SyncStatus.COMPLETED
    assert j.error_message is None
    assert j.files_transferred == 567_277
    assert j.bytes_transferred == 2_584_831_248_502

    assert m.status is MirrorStatus.ACTIVE
    assert m.last_sync_error is None
    assert m.total_size_bytes == 2_594_831_248_502
    assert m.file_count == 567_277

    # The only surviving record that this run was not perfectly clean.
    assert "some files vanished" in j.rsync_output
    assert "code 24" in j.rsync_output
    assert ".base80.tgz.lLPdyl" in j.rsync_output


# ---------------------------------------------------------------------------
# Exit 23: tolerated only when every error line is the upstream temp-file race
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path",
    [
        # The six from job 617, verbatim.
        "/patches/.2.2.tar.gz.Yf874d",
        "/snapshots/amd64/.install80.img.cG99qU",
        "/snapshots/arm64/.base80.tgz.XVIpnS",
        "/snapshots/i386/.install80.iso.rdGCa3",
        "/snapshots/packages/aarch64/.chromium-151.0.7922.169.tgz.l4HNjI",
        "/snapshots/powerpc64/.install80.iso.XfGnWV",
        # The five from job 615.
        "/snapshots/packages/amd64/.base80.tgz.lLPdyl",
        "/snapshots/packages/amd64/.debug-spidermonkey140-140.14.0v1.tgz.2ML90i",
    ],
)
def test_real_rsync_temp_paths_are_recognised(path):
    assert _is_rsync_temp_path(path) is True


@pytest.mark.parametrize(
    "path,why",
    [
        ("/snapshots/amd64/base80.tgz", "no leading dot: ordinary mirror content"),
        ("/pub/OpenBSD/7.5/README", "no leading dot"),
        ("/etc/.cshrc", "leading dot but no second component"),
        ("/x/.profile", "leading dot but no second component"),
        ("/x/.htaccess", "leading dot but no second component"),
        ("/x/.vimrc.swp", "suffix is 3 characters, not 6"),
        ("/x/.tar.gz", "suffix is 2 characters"),
        ("/x/.a.toolongsuffix", "suffix is longer than 6"),
        # These two carry a digit, so the lowercase-backup guard cannot reject
        # them: only the exact length of mkstemp's template can. Without them a
        # relaxation of {6} to + goes unnoticed.
        ("/x/.dataset.v20240115", "suffix longer than 6, digits so only length rejects it"),
        ("/x/.file.a1b", "suffix shorter than 6, digits so only length rejects it"),
        # The exact boundary. mkstemp's template is six X's, not "about six",
        # and these two are the only cases that would notice {6} being widened
        # to {5,7}. Both carry digits so nothing but the length rule can reject
        # them.
        ("/x/.file.a1b2c", "suffix is 5 characters: one short of mkstemp's template"),
        ("/x/.file.a1b2c3d", "suffix is 7 characters: one over"),
        ("/x/.a.abc-de", "suffix is not from mkstemp's alphabet"),
        ("/x/..Yf874d", "empty stem"),
    ],
)
def test_paths_that_are_not_rsync_temp_files(path, why):
    """The pattern has to be tight enough that a real file cannot slip through.
    Each of these would, if accepted, let a genuine permission error be waved
    through as benign."""
    assert _is_rsync_temp_path(path) is False, why


@pytest.mark.parametrize("path", ["/x/.config.backup", "/x/.index.master"])
def test_backup_style_dotfiles_are_accepted_and_that_is_deliberate(path):
    """CHANGED: these two were rejected, by a guard that additionally required
    the six-character suffix not to be entirely lowercase letters.

    They fit rsync's temp-file structure exactly -- leading dot, stem, six
    characters from mkstemp's alphabet -- and are now accepted. That is a real
    loosening, made on purpose:

      * The guard misfired at a rate that mattered. 0.54% of genuine mkstemp
        suffixes are all lowercase; across the ~8 error lines a run like job 617
        produces, 4.2% of syncs would have tripped it. Nightly, that is a
        spurious FAILED every three to four weeks.
      * What it bought was close to unreachable here. It would take a real file
        named like this that ALSO throws Permission denied (13) on the sender,
        and dot-prefixed files are not mirror content on these trees --
        rsync/rsyncd.conf excludes them from what we serve with `exclude = .* ~*`.
      * The cost lands on a channel that is about to be watched.
        scripts/health_check.sh is being wired to Slack precisely because a real
        failure went unnoticed for 58 nights; an alert that cries wolf monthly
        gets muted, and then the next real one is missed too.

    What still protects this path: the suffix must be exactly six characters
    from [A-Za-z0-9], and the error line must carry errno 13. A file called
    ".config.backup" is only ever tolerated if rsync also reports Permission
    denied on it, which for excluded non-content is not a thing that happens.
    """
    assert _is_rsync_temp_path(path) is True


def test_job_617_is_fully_attributable():
    """All eight error lines resolve; nothing is left over."""
    verdict = _classify_partial_transfer(JOB_617_EXIT_23, 23)

    assert verdict.tolerable is True
    assert len(verdict.upstream_temp_files) == 6
    assert len(verdict.vanished) == 2
    assert verdict.unrecognised == ()


def test_a_permission_error_on_real_content_is_not_tolerated():
    """The case the classifier exists to catch. Five of the six lines could be
    benign and it would still have to fail on the sixth."""
    verdict = _classify_partial_transfer(REAL_PERMISSION_ERROR_EXIT_23, 23)

    assert verdict.tolerable is False
    assert len(verdict.unrecognised) == 1
    assert "base80.tgz" in verdict.unrecognised[0]
    # It still recognised the benign line -- the failure is not from blindness.
    assert len(verdict.vanished) == 1


@pytest.mark.parametrize(
    "line,why",
    [
        (
            'rsync: [sender] send_files failed to open "/x/.base80.tgz.XVIpnS"'
            " (in OpenBSD): Input/output error (5)",
            "temp path but the errno is not the 0600 race",
        ),
        (
            'rsync: [receiver] write failed on "/data/mirrors/openbsd/x":'
            " No space left on device (28)",
            "full disk",
        ),
        (
            "IO error encountered -- skipping file deletion",
            "deletions were skipped: the mirror is not converged",
        ),
        (
            'rsync: [sender] send_files failed to open "/x/base80.tgz"'
            " (in OpenBSD): Permission denied (13)",
            "permission denied on real content",
        ),
        (
            'symlink has no referent: "/x/broken"',
            "unprefixed diagnostic rsync writes without an rsync: tag",
        ),
        (
            "rsync error: error in file IO (code 11) at receiver.c(200)",
            "a summary line for a different code than the one we exited with",
        ),
        (
            'skipping non-regular file "/x/weird"',
            "unprefixed diagnostic",
        ),
    ],
)
def test_a_single_unrecognised_line_defeats_the_whole_run(line, why):
    """Six perfectly benign lines plus one unreadable one must fail. The
    classifier is an AND across every line, not a majority vote."""
    output = JOB_617_EXIT_23.replace(
        "file has vanished:", line + "\nfile has vanished:", 1
    )

    verdict = _classify_partial_transfer(output, 23)

    assert verdict.tolerable is False, why
    assert line in verdict.unrecognised


def test_exit_23_with_no_readable_error_lines_is_not_tolerated():
    """Unattributable is not the same as benign. If we cannot say why rsync
    returned 23, we do not get to call it a success."""
    verdict = _classify_partial_transfer(
        "Number of files: 5 (reg: 5)\n"
        "rsync error: some files/attrs were not transferred (code 23)\n",
        23,
    )

    assert verdict.tolerable is False
    assert verdict.unrecognised == ()
    assert verdict.vanished == ()
    assert verdict.upstream_temp_files == ()


def test_the_exit_summary_line_is_not_itself_an_unrecognised_error():
    """`rsync error: ... (code 23)` is the exit status restated, not a ninth
    problem. Counting it would make every exit 23 untolerable and quietly
    disable the whole feature."""
    verdict = _classify_partial_transfer(JOB_617_EXIT_23, 23)
    assert not any("code 23" in line for line in verdict.unrecognised)


def test_normal_output_lines_are_not_mistaken_for_diagnostics():
    """The stats block, the transfer summary and the file-list header all
    survive an exit 23 without being read as errors."""
    verdict = _classify_partial_transfer(JOB_617_EXIT_23, 23)
    for noise in ("receiving incremental", "Number of files", "sent ", "total size is"):
        assert not any(noise in line for line in verdict.unrecognised)


async def test_job_617_end_to_end_is_recorded_completed_with_full_stats(
    service, rsync, factory, mirror
):
    """The whole point: job 617 becomes a successful sync with the 2.63 TB tree
    recorded, instead of FAILED with the mirror stuck at 43 GB."""
    rsync(23, JOB_617_EXIT_23)

    await run_job(service, mirror)

    m, j = reload(factory, mirror["mirror_id"], mirror["job_id"])

    assert j.status is SyncStatus.COMPLETED
    assert j.error_message is None
    assert j.files_transferred == 3_190
    assert j.files_deleted == 4

    assert m.status is MirrorStatus.ACTIVE
    assert m.last_sync_error is None
    assert m.total_size_bytes == 2_628_302_118_514
    assert m.file_count == 567_277
    assert _naive(m.last_sync_completed) > _naive(PREVIOUS_SYNC)

    # The evidence an operator needs to tell this from a clean run.
    assert "code 23" in j.rsync_output
    assert "Permission denied (13)" in j.rsync_output


async def test_exit_23_on_real_content_still_fails_end_to_end(
    service, rsync, factory, mirror
):
    """And the mirror keeps its previous good numbers rather than being
    republished with whatever the partial run measured."""
    rsync(23, REAL_PERMISSION_ERROR_EXIT_23)

    await run_job(service, mirror)

    m, j = reload(factory, mirror["mirror_id"], mirror["job_id"])

    assert j.status is SyncStatus.FAILED
    assert m.status is MirrorStatus.ERROR
    assert _naive(m.last_sync_completed) == _naive(PREVIOUS_SYNC)
    assert m.total_size_bytes == 2_594_831_248_502


async def test_tolerated_exit_23_is_logged_at_warning_with_counts(
    service, rsync, factory, mirror, caplog
):
    """A tolerated 23 must not be silent: the operator has to be able to see
    how many lines were waved through and which ones."""
    rsync(23, JOB_617_EXIT_23)

    with caplog.at_level(logging.WARNING, logger="sync.sync_service"):
        await run_job(service, mirror)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "a tolerated exit 23 produced no warning record"

    rendered = " ".join(r.getMessage() for r in warnings)
    assert "exit 23 tolerated" in rendered
    assert '"upstream_temp_file_count": 6' in rendered
    assert '"vanished_count": 2' in rendered
    # At least one concrete path, so the reason is auditable and not just a tally.
    assert ".install80.img.cG99qU" in rendered


async def test_untolerated_exit_23_is_logged_at_error_with_the_offending_line(
    service, rsync, factory, mirror, caplog
):
    rsync(23, REAL_PERMISSION_ERROR_EXIT_23)

    with caplog.at_level(logging.ERROR, logger="sync.sync_service"):
        await run_job(service, mirror)

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors

    rendered = " ".join(r.getMessage() for r in errors)
    assert '"unrecognised_count": 1' in rendered
    assert "/snapshots/amd64/base80.tgz" in rendered


def test_exit_24_is_not_routed_through_the_classifier():
    """24 stays unconditional. Its definition IS the benign condition -- rsync
    returns it only when nothing worse happened -- so it does not need, and
    must not acquire, a way to fail. This is the boundary between the two
    codes' handling, stated once."""
    verdict = _classify_partial_transfer(JOB_615_EXIT_24, 24)
    # The 24 summary line is recognised, and the vanished files are counted;
    # but run_rsync never consults this for a 24 run.
    assert verdict.tolerable is True
    assert len(verdict.vanished) == 5


@pytest.mark.parametrize("code", [1, 5, 10, 12, 25, 30, 35, 255])
async def test_every_other_nonzero_exit_code_still_fails(service, rsync, code, tmp_path):
    """0 and 24 are unconditional successes and 23 is conditional; every other
    code fails outright. 25 in particular sits next to 24 and must not be swept
    in by an off-by-one or a `>=` comparison."""
    rsync(code, PARTIAL_THEN_EXIT_30)

    success, _, _ = await service.run_rsync(
        "rsync://upstream/x/", str(tmp_path / "x"), "X"
    )

    assert success is False


async def test_exit_0_remains_success(service, rsync, factory, mirror):
    rsync(0, CLEAN_EXIT_0)

    await run_job(service, mirror)

    _, j = reload(factory, mirror["mirror_id"], mirror["job_id"])
    assert j.status is SyncStatus.COMPLETED


async def test_delete_is_passed_so_a_deleted_count_is_always_meaningful(service, rsync, tmp_path):
    """Pins the argv the fake stands in for, and the flag that makes
    SyncJob.files_deleted worth parsing at all."""
    calls = rsync(0, CLEAN_EXIT_0)

    await service.run_rsync("rsync://upstream/x/", str(tmp_path / "x"), "X")

    argv = calls[0]
    assert argv[0] == "rsync"
    assert "--delete" in argv
    assert "--stats" in argv
    assert argv[-2:] == ["rsync://upstream/x/", str(tmp_path / "x")]


# ---------------------------------------------------------------------------
# Defect 2: a failure must not erase last_sync_completed
# ---------------------------------------------------------------------------

async def test_failure_leaves_last_sync_completed_untouched(service, rsync, factory, mirror):
    """"When was this mirror last good?" is the question a failed sync makes
    urgent, and the old code answered it by writing NULL.

    Observed live: OpenBSD showed last_sync_completed = NULL with 43 GB of
    successfully-synced data sitting on disk.
    """
    rsync(30, PARTIAL_THEN_EXIT_30)

    await run_job(service, mirror)

    m, j = reload(factory, mirror["mirror_id"], mirror["job_id"])

    assert j.status is SyncStatus.FAILED
    assert m.status is MirrorStatus.ERROR
    assert m.last_sync_completed is not None
    assert _naive(m.last_sync_completed) == _naive(PREVIOUS_SYNC)


async def test_failure_records_the_error_without_losing_history(service, rsync, factory, mirror):
    """The failure still has to be visible -- preserving last_sync_completed is
    not the same as hiding the problem."""
    rsync(30, PARTIAL_THEN_EXIT_30)

    await run_job(service, mirror)

    m, j = reload(factory, mirror["mirror_id"], mirror["job_id"])
    assert "code 30" in m.last_sync_error
    assert "code 30" in j.error_message
    assert j.completed_at is not None


async def test_success_does_advance_last_sync_completed(service, rsync, factory, mirror):
    """The counterpart: preserving the old value on failure must not freeze it
    on success."""
    rsync(0, CLEAN_EXIT_0)

    await run_job(service, mirror)

    m, _ = reload(factory, mirror["mirror_id"], mirror["job_id"])
    assert _naive(m.last_sync_completed) > _naive(PREVIOUS_SYNC)


def _naive(value: datetime) -> datetime:
    """SQLite round-trips DateTime(timezone=True) as naive. Compare on a single
    footing rather than asserting a tz that the driver never stored."""
    return value.replace(tzinfo=None) if value.tzinfo else value


# ---------------------------------------------------------------------------
# Defect 3: which runs may write mirror stats
# ---------------------------------------------------------------------------

async def test_failed_run_does_not_overwrite_stats_with_partial_numbers(
    service, rsync, factory, mirror
):
    """A failed rsync still prints a --stats block, but it describes only the
    fraction transferred before it died -- here 43 GB of a 2.5 TB mirror.

    Writing that would replace a correct total with a smaller wrong one: the
    same understatement the public site was already showing, arrived at from
    the other direction. So the success gate stays.
    """
    rsync(30, PARTIAL_THEN_EXIT_30)

    await run_job(service, mirror)

    m, _ = reload(factory, mirror["mirror_id"], mirror["job_id"])
    assert m.total_size_bytes == 2_594_831_248_502
    assert m.file_count == 567_277


async def test_a_legitimate_zero_is_stored_rather_than_treated_as_a_parse_failure(
    service, rsync, factory, mirror
):
    """The guard was `if success and stats.get("total_size")`, which cannot
    tell 0 from a missing key, so an emptied upstream left the old totals
    standing forever. `is not None` distinguishes them."""
    rsync(0, "Number of files: 0 (reg: 0, dir: 0)\nTotal file size: 0 bytes\n")

    await run_job(service, mirror)

    m, _ = reload(factory, mirror["mirror_id"], mirror["job_id"])
    assert m.total_size_bytes == 0
    assert m.file_count == 0


async def test_unparseable_stats_leave_the_previous_totals_alone(
    service, rsync, factory, mirror
):
    """A successful run whose stats block did not parse (-h output, say) must
    not blank the columns -- absent key, not zero."""
    rsync(0, "Number of files: 5.58K (reg: 4.32K, dir: 1.26K)\nTotal file size: 897.65G bytes\n")

    await run_job(service, mirror)

    m, _ = reload(factory, mirror["mirror_id"], mirror["job_id"])
    assert m.total_size_bytes == 2_594_831_248_502
    assert m.file_count == 567_277


async def test_mirror_file_count_stores_regular_files_not_file_list_entries(
    service, rsync, factory, mirror
):
    """Defect 4 at the column that the public site reads. 571,398 is the file
    list; 567,277 of those are files and 4,121 are directories and symlinks."""
    rsync(24, JOB_615_EXIT_24)

    await run_job(service, mirror)

    m, _ = reload(factory, mirror["mirror_id"], mirror["job_id"])
    assert m.file_count == 567_277
    assert m.file_count != 571_398


# ---------------------------------------------------------------------------
# Defect 5: files_deleted, and the older transferred-count spelling
# ---------------------------------------------------------------------------

async def test_files_deleted_reaches_the_column(service, rsync, factory, mirror):
    """SyncJob.files_deleted has always been a real column and --delete has
    always been passed, but nothing parsed the line, so it was NULL on every
    job ever run. Job 615 deleted 112 entries: 111 files and one directory."""
    rsync(24, JOB_615_EXIT_24)

    await run_job(service, mirror)

    _, j = reload(factory, mirror["mirror_id"], mirror["job_id"])
    assert j.files_deleted == 111


async def test_old_rsync_transferred_count_reaches_the_column(service, rsync, factory, mirror):
    """rsync < 3.0 and openrsync write "Number of files transferred:". The
    parser only knew the 3.x spelling, so files_transferred was silently NULL
    on those hosts -- a successful job with no numbers on it."""
    rsync(0, OLD_RSYNC_EXIT_0)

    await run_job(service, mirror)

    _, j = reload(factory, mirror["mirror_id"], mirror["job_id"])
    assert j.files_transferred == 2
    assert j.bytes_transferred == 12


# ---------------------------------------------------------------------------
# Job bookkeeping that the fixes must not have disturbed
# ---------------------------------------------------------------------------

async def test_job_is_marked_running_before_rsync_starts(service, monkeypatch, factory, mirror):
    """sync_mirror_job's first commit sets RUNNING/SYNCING. Read it from inside
    the subprocess call, which is the only point at which that state is live."""
    seen = {}

    async def fake_exec(*cmd, **kwargs):
        m, j = reload(factory, mirror["mirror_id"], mirror["job_id"])
        seen["mirror_status"] = m.status
        seen["job_status"] = j.status
        seen["started_at"] = j.started_at
        return FakeProcess(0, CLEAN_EXIT_0)

    monkeypatch.setattr(sync_service.asyncio, "create_subprocess_exec", fake_exec)

    await run_job(service, mirror)

    assert seen["job_status"] is SyncStatus.RUNNING
    assert seen["mirror_status"] is MirrorStatus.SYNCING
    assert seen["started_at"] is not None


async def test_rsync_output_is_tail_truncated_to_ten_thousand_characters(
    service, rsync, factory, mirror
):
    """The truncation keeps the TAIL, which is where rsync writes its exit
    warning -- `rsync warning: some files vanished ... (code 24)` is the last
    line of a 15-hour run. Truncating the head would have thrown away the one
    thing defect 1 leaves behind as evidence."""
    noise = "transferring: some/very/long/path/name/deep/in/the/tree\n" * 400
    rsync(24, noise + JOB_615_EXIT_24)

    await run_job(service, mirror)

    _, j = reload(factory, mirror["mirror_id"], mirror["job_id"])
    assert len(j.rsync_output) == 10_000
    assert "some files vanished" in j.rsync_output
    assert j.rsync_output.endswith("[receiver=3.2.7]\n")


async def test_subprocess_failure_is_caught_and_reported_as_a_failed_job(
    service, monkeypatch, factory, mirror
):
    """run_rsync's except branch returns (False, str(e), {}). Check it does not
    then trip over the empty stats dict."""

    async def boom(*cmd, **kwargs):
        raise OSError("rsync: command not found")

    monkeypatch.setattr(sync_service.asyncio, "create_subprocess_exec", boom)

    await run_job(service, mirror)

    m, j = reload(factory, mirror["mirror_id"], mirror["job_id"])
    assert j.status is SyncStatus.FAILED
    assert j.files_transferred is None
    assert j.files_deleted is None
    assert m.status is MirrorStatus.ERROR
    # Still not erased, even on the path where there is no rsync at all.
    assert _naive(m.last_sync_completed) == _naive(PREVIOUS_SYNC)


# ---------------------------------------------------------------------------
# Job 619: the trailing "(in MODULE)" clause on vanished lines
# ---------------------------------------------------------------------------
#
# These two lines are verbatim and unsanitised, copied out of the structured log
# of job 619. Every earlier fixture in this file carried a shortened form of this
# shape -- the trailing " (in OpenBSD)" was lost to a `grep -oE '...[^"]*'` that
# stopped at the closing quote -- so the pattern was written against output that
# rsync never actually produces. Nothing in the suite could catch that, because
# the fixtures and the regex shared the same wrong assumption.
#
# Keep these two strings verbatim. They are the only test data in this file
# taken directly from a production log rather than transcribed or reconstructed.
JOB_619_VANISHED_VERBATIM = (
    'file has vanished: "/snapshots/packages/amd64/'
    '.geckodriver-0.31.0p1.tgz.S5EDPJ" (in OpenBSD)',
    'file has vanished: "/snapshots/packages/riscv64/'
    '.dgen-sdl-1.33p2-debugger.tgz.Bk5dNR" (in OpenBSD)',
)


@pytest.mark.parametrize("line", JOB_619_VANISHED_VERBATIM)
def test_vanished_line_with_module_clause_is_recognised(line):
    """rsync appends " (in MODULE)" after the closing quote. The pattern
    anchored $ immediately after the quote, so these landed in `unrecognised`
    and failed job 619 -- a run whose every error line was benign."""
    match = _VANISHED_RE.match(line)
    assert match is not None, "verbatim rsync output must parse"
    assert match.group("path").endswith(".tgz.S5EDPJ") or match.group(
        "path"
    ).endswith(".tgz.Bk5dNR")
    assert '"' not in match.group("path"), "the capture must not run past the quote"
    assert "(in OpenBSD)" not in match.group("path"), "module clause is not part of the path"


def test_vanished_line_without_module_clause_still_parses():
    """Older rsync omits the clause entirely. Both shapes must work; the fix
    must not simply move the anchor to require the module."""
    line = 'file has vanished: "/snapshots/packages/amd64/.base80.tgz.lLPdyl"'
    match = _VANISHED_RE.match(line)
    assert match is not None
    assert match.group("path") == "/snapshots/packages/amd64/.base80.tgz.lLPdyl"


def test_vanished_path_capture_stops_at_the_first_quote():
    """A greedy .* would swallow the closing quote and everything up to a later
    one, silently producing a path that is not a path."""
    line = 'file has vanished: "/a/.x.AAAAAA" and "/b/.y.BBBBBB"'
    match = _VANISHED_RE.match(line)
    if match is not None:
        assert match.group("path") == "/a/.x.AAAAAA"


def test_vanished_line_with_trailing_junk_is_still_rejected():
    """The anchor has to stay in some form. A diagnostic carrying unexplained
    trailing text is not something we understand, and unrecognised must keep
    meaning unrecognised."""
    assert _VANISHED_RE.match(
        'file has vanished: "/a/.x.AAAAAA" (in OpenBSD) and then the disk caught fire'
    ) is None
    assert _VANISHED_RE.match('file has vanished: "/a/.x.AAAAAA" unexpected trailer') is None


JOB_619_EXIT_23 = """\
receiving incremental file list
rsync: [sender] send_files failed to open "/patches/.2.2.tar.gz.Yf874d" (in OpenBSD): Permission denied (13)
rsync: [sender] send_files failed to open "/snapshots/amd64/.install80.img.cG99qU" (in OpenBSD): Permission denied (13)
rsync: [sender] send_files failed to open "/snapshots/arm64/.base80.tgz.XVIpnS" (in OpenBSD): Permission denied (13)
rsync: [sender] send_files failed to open "/snapshots/i386/.install80.iso.rdGCa3" (in OpenBSD): Permission denied (13)
rsync: [sender] send_files failed to open "/snapshots/packages/aarch64/.chromium-151.0.7922.169.tgz.l4HNjI" (in OpenBSD): Permission denied (13)
rsync: [sender] send_files failed to open "/snapshots/powerpc64/.install80.iso.XfGnWV" (in OpenBSD): Permission denied (13)
%s
%s

Number of files: 571,398 (reg: 567,277, dir: 4,110, link: 11)
Number of created files: 0
Number of deleted files: 2 (reg: 2)
Number of regular files transferred: 41
Total file size: 2,628,302,118,514 bytes
Total transferred file size: 78,381,056 bytes

sent 402,112 bytes  received 78,772,224 bytes  1,204,112.44 bytes/sec
total size is 2,628,302,118,514  speedup is 33,201.14
rsync error: some files/attrs were not transferred (code 23) at main.c(1338) [sender=3.2.7]
""" % JOB_619_VANISHED_VERBATIM


def test_job_619_is_fully_attributable():
    """The post-deploy verification run. Six temp files and two vanished files,
    all benign; it was recorded FAILED and left OpenBSD at 43 GB."""
    verdict = _classify_partial_transfer(JOB_619_EXIT_23, 23)

    assert verdict.unrecognised == ()
    assert len(verdict.upstream_temp_files) == 6
    assert len(verdict.vanished) == 2
    assert verdict.tolerable is True


async def test_job_619_end_to_end_is_recorded_completed(service, rsync, factory, mirror):
    rsync(23, JOB_619_EXIT_23)

    await run_job(service, mirror)

    m, j = reload(factory, mirror["mirror_id"], mirror["job_id"])
    assert j.status is SyncStatus.COMPLETED
    assert m.status is MirrorStatus.ACTIVE
    assert m.total_size_bytes == 2_628_302_118_514
    assert m.file_count == 567_277


# Same run, as an rsync old enough to omit the module clause would report it.
# Both shapes have to reach `tolerable`, so the fix cannot be "require (in X)".
OLD_RSYNC_EXIT_23_NO_MODULE_CLAUSE = """\
rsync: send_files failed to open "/patches/.2.2.tar.gz.Yf874d": Permission denied (13)
file has vanished: "/snapshots/packages/amd64/.geckodriver-0.31.0p1.tgz.S5EDPJ"
rsync error: some files/attrs were not transferred (code 23) at main.c(1338)
"""


def test_both_module_clause_shapes_are_tolerated_end_to_end():
    """The clause is optional on both benign branches, and its presence or
    absence must not change the verdict."""
    with_clause = _classify_partial_transfer(JOB_619_EXIT_23, 23)
    without_clause = _classify_partial_transfer(OLD_RSYNC_EXIT_23_NO_MODULE_CLAUSE, 23)

    assert with_clause.tolerable is True
    assert without_clause.tolerable is True
    assert without_clause.unrecognised == ()
    assert len(without_clause.upstream_temp_files) == 1
    assert len(without_clause.vanished) == 1


def test_the_module_clause_is_not_absorbed_into_the_path():
    """If " (in OpenBSD)" were captured as part of the path, the temp-file
    structural check downstream would be reading a basename that ends in
    ")" and would reject every one of them."""
    verdict = _classify_partial_transfer(JOB_619_EXIT_23, 23)

    for path in verdict.vanished + verdict.upstream_temp_files:
        assert "(in " not in path
        assert not path.endswith(")")
        assert _is_rsync_temp_path(path), path


def test_send_files_path_capture_cannot_run_across_two_quoted_spans():
    """A filename may legally contain a double quote, so a diagnostic can carry
    two quoted spans. With a `.*?` capture the regex backtracks past the first
    closing quote and returns "/snapshots/amd64/base80.tgz" and "/x/.decoy.AAAAAA"
    as one path; rsplit("/") then yields the temp-shaped basename `.decoy.AAAAAA`
    and a permission error on REAL mirror content is waved through as benign.

    `[^"]*` cannot cross a quote, so the line matches nothing, falls to
    unrecognised, and the run fails. This is the same defect class as the
    vanished-line anchor: the capture has to end where the quoted span ends.
    """
    line = (
        'rsync: [sender] send_files failed to open '
        '"/snapshots/amd64/base80.tgz" and "/x/.decoy.AAAAAA": Permission denied (13)'
    )
    output = (
        line
        + '\nfile has vanished: "/x/.real.S5EDPJ" (in OpenBSD)'
        + "\nrsync error: some files/attrs were not transferred (code 23) at main.c(1338)\n"
    )

    verdict = _classify_partial_transfer(output, 23)

    assert verdict.tolerable is False
    assert line in verdict.unrecognised
    assert verdict.upstream_temp_files == ()
