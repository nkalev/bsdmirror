"""
_parse_rsync_stats (sync/sync_service.py) against real rsync --stats output.

Pure function, no infrastructure. These tests exist to pin down exactly which
number ends up in Mirror.file_count and SyncJob.bytes_transferred, because the
production figures (FreeBSD 5,582 files / 836 GB vs NetBSD 32,140 files /
616 GB) are inconsistent with each other while the byte totals match `du`.

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

The tests assert current behaviour. Nothing here fixes the parser.
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

def test_total_files_is_the_file_list_total_not_the_regular_file_count():
    """`Number of files: 5,582 (reg: 4,321, dir: 1,261)`.

    The parser takes `line.split(":")[1].strip().split()[0]`, i.e. the number
    before the parenthesis. In rsync 3.x that is the size of the whole file
    list -- regular files plus directories plus symlinks plus devices -- and
    the regular-file count sits inside the parenthesis, which is discarded.

    So Mirror.file_count is over-reported by the directory and symlink count
    (here 1,261 of 5,582, i.e. 29% of the stored value is not a file), and the
    admin panel and /api/stats/overview both label it "files".
    """
    stats = parse(RSYNC_3_FREEBSD)
    assert stats["total_files"] == 5582
    assert stats["total_files"] != 4321, "the `reg:` sub-count is what a user means by 'files'"
    assert stats["total_files"] == 4321 + 1261


def test_total_files_also_absorbs_symlinks():
    stats = parse(RSYNC_3_NETBSD)
    assert stats["total_files"] == 32140
    assert stats["total_files"] == 30879 + 1255 + 6


def test_the_parenthesised_breakdown_is_discarded_entirely():
    """Nothing in the returned dict carries reg/dir/link, so the true file count
    cannot be recovered downstream."""
    stats = parse(RSYNC_3_FREEBSD)
    assert set(stats) == {"total_files", "files_transferred", "total_size", "bytes_transferred"}


def test_created_and_deleted_lines_are_not_mistaken_for_the_total():
    """`Number of created files:` and `Number of deleted files:` do not contain
    the substring `Number of files:`, so the `in` test does not collide. This is
    load-bearing and worth pinning: the branch is substring matching, not a
    prefix or regex match."""
    assert "Number of files:" not in "Number of created files: 41 (reg: 39, dir: 2)"
    assert "Number of files:" not in "Number of deleted files: 17 (reg: 17)"
    stats = parse(RSYNC_3_NETBSD)
    assert stats["total_files"] == 32140  # not 41, not 17


def test_deleted_file_count_is_never_captured():
    """SyncJob.files_deleted is a real column (backend/app/models/sync_job.py)
    but no branch reads `Number of deleted files:`, so it is always NULL even
    though rsync reports it and `--delete` is always passed."""
    stats = parse(RSYNC_3_NETBSD)
    assert "files_deleted" not in stats


# ---------------------------------------------------------------------------
# The other three fields
# ---------------------------------------------------------------------------

def test_parses_all_four_fields_from_rsync_3_output():
    assert parse(RSYNC_3_FREEBSD) == {
        "total_files": 5582,
        "files_transferred": 12,
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
    assert stats["total_size"] == 897648164864
    # sync_mirror_job guards its writes with `if success and stats.get(...)`,
    # so a legitimate 0 is indistinguishable from a parse failure there.
    assert not stats["bytes_transferred"]


def test_trailing_summary_lines_are_ignored():
    """`total size is 897,648,164,864  speedup is 208.93` is lower-case and has
    no colon, so it cannot overwrite total_size."""
    stats = parse(RSYNC_3_FREEBSD)
    assert stats["total_size"] == 897648164864


# ---------------------------------------------------------------------------
# Version fragility
# ---------------------------------------------------------------------------

def test_rsync_2_6_9_output_silently_loses_files_transferred():
    """Captured from a real run. rsync < 3.0 (and openrsync) emit
    `Number of files transferred:`; the parser only matches
    `Number of regular files transferred:`.

    The key is simply absent from the dict. sync_mirror_job then writes
    files_transferred=None onto the SyncJob with no error, no warning, and a
    successful exit status.
    """
    stats = parse(RSYNC_2_6_9)
    assert "files_transferred" not in stats
    assert stats["total_files"] == 5


def test_rsync_2_6_9_byte_unit_suffix_survives_by_luck():
    """2.6.9 writes `Total file size: 17 B`, 3.x writes `... 17 bytes`. Both
    parse, because the branch does `.split()[0]` before int(). The
    files_transferred branch has no such guard -- see the next test."""
    stats = parse(RSYNC_2_6_9)
    assert stats["total_size"] == 17
    assert stats["bytes_transferred"] == 12


def test_files_transferred_branch_lacks_the_split_guard_the_others_have():
    """total_files/total_size/bytes_transferred all do
    `.strip().split()[0].replace(",", "")`. files_transferred does
    `.strip().replace(",", "")` with no split, so any suffix or parenthetical on
    that line breaks it where the other three would cope."""
    with_suffix = "Number of regular files transferred: 12 files\n"
    assert "files_transferred" not in parse(with_suffix)

    without_suffix = "Number of regular files transferred: 12\n"
    assert parse(without_suffix)["files_transferred"] == 12


def test_human_readable_output_silently_drops_every_size():
    """`Total file size: 897.65G bytes` raises ValueError inside int(); the
    handler logs at debug and moves on. LOG_LEVEL is INFO in production, so this
    is invisible, and sync_mirror_job's `if success and stats.get("total_size")`
    then leaves Mirror.total_size_bytes at its previous value."""
    stats = parse(RSYNC_3_HUMAN_READABLE)
    assert "total_size" not in stats
    assert "bytes_transferred" not in stats
    assert "total_files" not in stats
    # Only the un-suffixed integer survives.
    assert stats == {"files_transferred": 12}


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
    assert stats["total_files"] == 32140
    assert stats["total_size"] == 661424963584
