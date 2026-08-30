"""
_parse_rsync_stats (sync/sync_service.py) against real rsync --stats output.

Pure function, no infrastructure. These tests pin down exactly which number
ends up in Mirror.file_count and SyncJob.bytes_transferred, because the
production figures (FreeBSD 5,582 files / 836 GB vs NetBSD 32,140 files /
616 GB) were inconsistent with each other while the byte totals matched `du`.

The contract these tests now encode:

    regular_files      the `reg:` sub-count. What "files" means on the public
                       site and in the admin panel.
    total_entries      the leading number: every file-list entry, of which
                       directories and symlinks are not files.
    files_transferred  matched on both the rsync 3.x spelling and the
                       2.6.9/openrsync one.
    files_deleted      new; SyncJob.files_deleted had no parser at all.
    total_size, bytes_transferred

An earlier revision of this file asserted the opposite of the first, second and
fourth of those, because it was written to document the parser as it stood.
Those tests were rewritten, not deleted: each one below states what changed.

Fixture provenance, stated because it matters:

  * RSYNC_3_FREEBSD / RSYNC_3_NETBSD / RSYNC_3_HUMAN_READABLE are written in the
    rsync 3.x --stats format. That is what the sync container runs:
    sync/Dockerfile is python:3.12-slim (Debian bookworm) + `apt-get install
    rsync`, i.e. rsync 3.2.7. GNU rsync 3.x could not be executed on the machine
    these tests were written on -- macOS ships openrsync -- so this block is
    transcribed from the documented 3.x format rather than captured.

  * RSYNC_2_6_9 is a verbatim capture, produced by running the exact argv from
    SyncService.run_rsync against a local directory:
        rsync -rlptHz --delete --delete-delay --delay-updates --stats \
              --no-owner --no-group --timeout=600 src/ dst/
    on `openrsync: protocol version 29 / rsync version 2.6.9 compatible`.

"""
import pytest

from sync.sync_service import SyncService

# __init__ opens a SQLAlchemy async engine we have no use for. _parse_rsync_stats
# never touches self, so bypass __init__ rather than build a connection pool.
_parser = object.__new__(SyncService)


def parse(output: str) -> dict:
    return _parser._parse_rsync_stats(output)


# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

# rsync 3.2.7. Note the parenthesised breakdown on "Number of files:" -- the
# leading number is the total of every entry type that follows it.
RSYNC_3_FREEBSD = """\
receiving incremental file list

Number of files: 5,582 (reg: 4,321, dir: 1,261)
Number of created files: 0
Number of deleted files: 0
Number of regular files transferred: 12
Total file size: 897,648,164,864 bytes
Total transferred file size: 4,294,967,296 bytes
Literal data: 4,294,967,296 bytes
Matched data: 0 bytes
File list size: 131,072
File list generation time: 0.014 seconds
File list transfer time: 0.000 seconds
Total bytes sent: 1,048,576
Total bytes received: 4,295,024,640

sent 1,048,576 bytes  received 4,295,024,640 bytes  12,345,678.00 bytes/sec
total size is 897,648,164,864  speedup is 208.93
"""

# rsync 3.2.7, tree containing symlinks, with non-zero created/deleted counts.
RSYNC_3_NETBSD = """\
receiving incremental file list

Number of files: 32,140 (reg: 30,879, dir: 1,255, link: 6)
Number of created files: 41 (reg: 39, dir: 2)
Number of deleted files: 17 (reg: 17)
Number of regular files transferred: 39
Total file size: 661,424,963,584 bytes
Total transferred file size: 8,589,934,592 bytes
Literal data: 8,589,934,592 bytes
Matched data: 0 bytes
File list size: 786,432
File list generation time: 0.211 seconds
File list transfer time: 0.000 seconds
Total bytes sent: 2,097,152
Total bytes received: 8,592,031,744

sent 2,097,152 bytes  received 8,592,031,744 bytes  9,876,543.00 bytes/sec
total size is 661,424,963,584  speedup is 76.97
"""

# rsync 3.2.7 with nothing to do.
RSYNC_3_NO_CHANGES = """\
Number of files: 5,582 (reg: 4,321, dir: 1,261)
Number of created files: 0
Number of deleted files: 0
Number of regular files transferred: 0
Total file size: 897,648,164,864 bytes
Total transferred file size: 0 bytes
Literal data: 0 bytes
Matched data: 0 bytes
File list size: 131,072
File list generation time: 0.011 seconds
File list transfer time: 0.000 seconds
Total bytes sent: 155,478
Total bytes received: 1,203,456
"""

# rsync 3.2.7 invoked with -h/--human-readable. Not in SyncService.run_rsync's
# argv today, but reachable through a popt alias or RSYNC_* env in the image.
RSYNC_3_HUMAN_READABLE = """\
Number of files: 5.58K (reg: 4.32K, dir: 1.26K)
Number of created files: 0
Number of deleted files: 0
Number of regular files transferred: 12
Total file size: 897.65G bytes
Total transferred file size: 4.29G bytes
Literal data: 4.29G bytes
Matched data: 0 bytes
File list size: 131.07K
Total bytes sent: 1.05M
Total bytes received: 4.30G
"""

# Verbatim capture. openrsync / rsync 2.6.9 compatible.
RSYNC_2_6_9 = """\
Number of files: 5
Number of files transferred: 2
Total file size: 17 B
Total transferred file size: 12 B
Unmatched data: 12 B
Matched data: 0 B
File list size: 125 B
Total sent: 255 B
Total received: 76 B

sent 255 bytes  received 76 bytes  157619 bytes/sec
total size is 17  speedup is 0.05
"""


# ---------------------------------------------------------------------------
# The core question: which number lands in Mirror.file_count?
# ---------------------------------------------------------------------------

def test_regular_files_is_the_reg_subcount_not_the_file_list_total():
    """`Number of files: 5,582 (reg: 4,321, dir: 1,261)`.

    CHANGED. This test previously asserted that Mirror.file_count received
    5,582 -- the size of the whole file list, i.e. regular files PLUS
    directories, symlinks and devices -- and that the `reg:` sub-count was
    discarded. The admin panel and /api/stats/overview both label that number
    "files", so 1,261 of the 5,582 were not files: a 29% over-report.

    The contract is now the `reg:` count, with the file-list total kept
    separately under total_entries rather than thrown away.
    """
    stats = parse(RSYNC_3_FREEBSD)
    assert stats["regular_files"] == 4321
    assert stats["total_entries"] == 5582
    assert stats["total_entries"] - stats["regular_files"] == 1261, "directories"


def test_symlinks_are_excluded_from_the_regular_file_count_too():
    """CHANGED, was test_total_files_also_absorbs_symlinks. `link: 6` is six
    symlinks, not six files."""
    stats = parse(RSYNC_3_NETBSD)
    assert stats["regular_files"] == 30879
    assert stats["total_entries"] == 32140
    assert stats["total_entries"] == 30879 + 1255 + 6


def test_thousands_separators_inside_the_breakdown_survive():
    """Regression test with teeth: inside the parenthesis the item separator is
    ", " and the thousands separator is ",". Splitting the breakdown on a bare
    comma reads `reg: 567,277` as 567, and every count silently collapses to
    its first three digits -- a far worse error than the one being fixed, and
    one that still leaves a plausible-looking number in the column.

    These are job 615's real counts.
    """
    stats = parse("Number of files: 571,398 (reg: 567,277, dir: 4,110, link: 11)\n")
    assert stats["regular_files"] == 567277
    assert stats["total_entries"] == 571398


def test_the_parenthesised_breakdown_is_no_longer_discarded():
    """CHANGED. The old parser returned four keys and no way to recover the
    reg/dir split downstream; both halves are now present."""
    stats = parse(RSYNC_3_FREEBSD)
    assert set(stats) == {
        "regular_files",
        "total_entries",
        "files_transferred",
        "files_deleted",
        "total_size",
        "bytes_transferred",
    }


def test_created_and_deleted_lines_are_not_mistaken_for_the_total():
    """`Number of created files:` and `Number of deleted files:` do not contain
    the substring `Number of files:`, so the `in` test does not collide. This is
    load-bearing and worth pinning: the branch is substring matching, not a
    prefix or regex match.

    CHANGED only in that the deleted line now has a branch of its own, so the
    assertion covers both directions: the totals are not polluted by it, and it
    is no longer ignored.
    """
    assert "Number of files:" not in "Number of created files: 41 (reg: 39, dir: 2)"
    assert "Number of files:" not in "Number of deleted files: 17 (reg: 17)"
    stats = parse(RSYNC_3_NETBSD)
    assert stats["total_entries"] == 32140  # not 41, not 17
    assert stats["regular_files"] == 30879
    assert stats["files_deleted"] == 17


def test_deleted_file_count_is_captured():
    """CHANGED, was test_deleted_file_count_is_never_captured.

    SyncJob.files_deleted is a real column and `--delete` is always passed, but
    no branch read `Number of deleted files:`, so it was NULL on every job ever
    run.

    The value taken is the `reg:` sub-count, for the same reason and by the same
    helper as regular_files: `Number of deleted files: 112 (reg: 111, dir: 1)`
    is 111 files and one directory, and a column labelled "files deleted"
    should not count the directory.
    """
    stats = parse(RSYNC_3_NETBSD)
    assert stats["files_deleted"] == 17

    job_615 = parse("Number of deleted files: 112 (reg: 111, dir: 1)\n")
    assert job_615["files_deleted"] == 111


def test_a_breakdown_without_a_reg_key_means_zero_regular_files():
    """A tree of nothing but directories. The leading total must NOT be used as
    a fallback here -- the breakdown parsed fine and it says there are no
    files."""
    stats = parse("Number of files: 3 (dir: 3)\n")
    assert stats["regular_files"] == 0
    assert stats["total_entries"] == 3


def test_device_and_special_entries_are_excluded():
    stats = parse("Number of files: 9 (reg: 5, dir: 2, link: 1, dev: 1)\n")
    assert stats["regular_files"] == 5
    assert stats["total_entries"] == 9


# ---------------------------------------------------------------------------
# The other three fields
# ---------------------------------------------------------------------------

def test_parses_every_field_from_rsync_3_output():
    """CHANGED: was four keys, now six. total_entries and files_deleted are
    new."""
    assert parse(RSYNC_3_FREEBSD) == {
        "regular_files": 4321,
        "total_entries": 5582,
        "files_transferred": 12,
        "files_deleted": 0,
        "total_size": 897648164864,
        "bytes_transferred": 4294967296,
    }


def test_total_file_size_is_not_shadowed_by_total_transferred_file_size():
    """Both lines end in `file size:`. The branches are ordered
    `Total file size:` then `Total transferred file size:`, and neither string
    is a substring of the other, so they stay distinct."""
    stats = parse(RSYNC_3_FREEBSD)
    assert stats["total_size"] == 897648164864
    assert stats["bytes_transferred"] == 4294967296
    assert stats["total_size"] != stats["bytes_transferred"]


def test_zero_transfer_run_still_reports_totals():
    stats = parse(RSYNC_3_NO_CHANGES)
    assert stats["files_transferred"] == 0
    assert stats["bytes_transferred"] == 0
    assert stats["files_deleted"] == 0
    assert stats["total_size"] == 897648164864

    # A zero here is a real measurement and is falsy, which is why
    # sync_mirror_job now tests `stats.get(...) is not None` rather than
    # truthiness: the old guard could not tell "nothing transferred" from
    # "nothing parsed". Presence of the key is the signal.
    assert not stats["bytes_transferred"]
    assert "bytes_transferred" in stats


def test_trailing_summary_lines_are_ignored():
    """`total size is 897,648,164,864  speedup is 208.93` is lower-case and has
    no colon, so it cannot overwrite total_size."""
    stats = parse(RSYNC_3_FREEBSD)
    assert stats["total_size"] == 897648164864


# ---------------------------------------------------------------------------
# Version fragility
# ---------------------------------------------------------------------------

def test_rsync_2_6_9_transferred_count_is_matched():
    """CHANGED, was test_rsync_2_6_9_output_silently_loses_files_transferred.

    Captured from a real run. rsync < 3.0 and openrsync emit `Number of files
    transferred:`; the parser matched only `Number of regular files
    transferred:`, so the key was absent and sync_mirror_job wrote NULL with no
    error, no warning and a successful exit status. Both spellings now match.

    2.6.9 prints no parenthesised breakdown, so regular_files falls back to the
    leading number -- which does include directories. That fallback still
    over-reports; there is simply no finer number in this output. It is the
    reason total_entries and regular_files are equal here.
    """
    stats = parse(RSYNC_2_6_9)
    assert stats["files_transferred"] == 2
    assert stats["regular_files"] == 5
    assert stats["total_entries"] == 5


def test_the_two_transferred_spellings_do_not_collide():
    """`Number of files transferred:` is not a substring of `Number of regular
    files transferred:`, so adding the older spelling could not shadow the
    newer one."""
    assert "Number of files transferred:" not in "Number of regular files transferred: 39"
    assert parse("Number of regular files transferred: 39\n")["files_transferred"] == 39
    assert parse("Number of files transferred: 39\n")["files_transferred"] == 39


def test_rsync_2_6_9_byte_unit_suffix_survives_by_luck():
    """2.6.9 writes `Total file size: 17 B`, 3.x writes `... 17 bytes`. Both
    parse, because the branch does `.split()[0]` before int(). The
    files_transferred branch has no such guard -- see the next test."""
    stats = parse(RSYNC_2_6_9)
    assert stats["total_size"] == 17
    assert stats["bytes_transferred"] == 12


def test_every_numeric_branch_shares_the_same_split_guard():
    """CHANGED, was test_files_transferred_branch_lacks_the_split_guard_the_others_have.

    The files_transferred branch used to do `.strip().replace(",", "")` with no
    `.split()[0]`, so any trailing token on that line broke it where the other
    three coped. Every branch now goes through the same _to_int helper, so the
    behaviour is uniform.

    This is a side effect of consolidating the branches, not one of the five
    defects being fixed; it is called out here so it is not mistaken for one.
    """
    assert parse("Number of regular files transferred: 12 files\n")["files_transferred"] == 12
    assert parse("Number of regular files transferred: 12\n")["files_transferred"] == 12
    assert parse("Total file size: 17 bytes\n")["total_size"] == 17
    assert parse("Total file size: 17 B\n")["total_size"] == 17


def test_human_readable_output_silently_drops_every_size():
    """`Total file size: 897.65G bytes` raises ValueError inside int(); the
    handler logs at debug and moves on. LOG_LEVEL is INFO in production, so this
    is invisible, and sync_mirror_job's `if success and stats.get("total_size")`
    then leaves Mirror.total_size_bytes at its previous value."""
    stats = parse(RSYNC_3_HUMAN_READABLE)
    assert "total_size" not in stats
    assert "bytes_transferred" not in stats
    assert "regular_files" not in stats
    assert "total_entries" not in stats

    # CHANGED: files_deleted now appears, because `Number of deleted files: 0`
    # is not scaled and so parses. Only the un-scaled integers survive.
    assert stats == {"files_transferred": 12, "files_deleted": 0}


def test_a_scaled_count_is_rejected_rather_than_truncated():
    """`reg: 4.32K` must yield no key at all. Reading it as 4 would be worse
    than reading nothing: sync_mirror_job would store 4 as the file count of a
    4,321-file mirror, and `is not None` would accept it."""
    stats = parse("Number of files: 5.58K (reg: 4.32K, dir: 1.26K)\n")
    assert "regular_files" not in stats
    assert "total_entries" not in stats


# ---------------------------------------------------------------------------
# Degenerate input
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "output",
    ["", "\n", "rsync: connection unexpectedly closed", "rsync error: timeout (code 30)"],
    ids=["empty", "newline", "connection-error", "timeout-error"],
)
def test_output_without_a_stats_block_yields_an_empty_dict(output):
    """A failed rsync produces no stats block. The parser returns {} rather than
    raising, which is why run_rsync can return (False, output, {})."""
    assert parse(output) == {}


def test_malformed_numbers_are_skipped_not_raised():
    assert parse("Number of files: not-a-number\n") == {}
    assert parse("Total file size:\n") == {}


def test_a_later_stats_block_overwrites_an_earlier_one():
    """The parser walks every line and reassigns, so if output ever contains two
    stats blocks (a retry, or --info=stats2 verbosity) the last one wins."""
    stats = parse(RSYNC_3_FREEBSD + RSYNC_3_NETBSD)
    assert stats["regular_files"] == 30879
    assert stats["total_entries"] == 32140
    assert stats["total_size"] == 661424963584
