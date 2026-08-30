"""
BSD Mirrors Sync Service

Handles scheduled rsync synchronization of BSD mirrors.
Polls for pending sync jobs created by the admin panel.
"""
import asyncio
import logging
import os
import re
import signal
from datetime import datetime, timezone
from typing import NamedTuple, Optional

from aiohttp import web
from croniter import croniter
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
import structlog

# Configure stdlib logging before structlog: structlog's filter_by_level checks
# the *stdlib* logger's effective level, and the root logger defaults to WARNING,
# which silently discards every logger.info() call. An unrecognised LOG_LEVEL
# falls back to INFO instead of raising at import time. SyncConfig is defined
# below this point, so the env var is read directly here and mirrored there.
_log_level = logging.getLevelName(os.getenv("LOG_LEVEL", "INFO").strip().upper())
if not isinstance(_log_level, int):
    _log_level = logging.INFO

# format="%(message)s" keeps the line exactly as structlog's JSONRenderer emits it.
# The level is set on this module's own logger so third-party loggers (aiohttp's
# access log for the health endpoint, for one) keep the levels they have today.
logging.basicConfig(format="%(message)s")
logging.getLogger(__name__).setLevel(_log_level)

# Configure logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# How often to poll for pending jobs (seconds)
POLL_INTERVAL = 10

# rsync exit codes that mean "the mirror on disk is good".
#
#   0   success.
#   24  "some files vanished before they could be transferred". This is a
#       warning, not an error, and it is routine when pulling from a public
#       mirror that is itself syncing: upstream deletes its own rsync temp
#       files (.base80.tgz.lLPdyl and friends) between the file list being
#       built and the transfer reaching them. Job 615 moved 567,277 files /
#       2,584,831,248,502 bytes over 15.7 hours and was recorded FAILED because
#       exactly five such temp files disappeared.
#
# 23 is NOT in this set. It is handled separately, by inspecting the error
# lines -- see _classify_partial_transfer below.
#
# There is no "completed with warnings" SyncStatus and there must not be: this
# repo has no migrations (schema comes from Base.metadata.create_all), so a new
# enum value would never reach an existing database. A tolerated run is
# COMPLETED and the warning text survives in SyncJob.rsync_output.
RSYNC_EXIT_SUCCESS = 0
RSYNC_EXIT_VANISHED_SOURCE_FILES = 24
RSYNC_SUCCESS_EXIT_CODES = frozenset({RSYNC_EXIT_SUCCESS, RSYNC_EXIT_VANISHED_SOURCE_FILES})

# 24 is tolerated unconditionally because the code IS the condition: rsync
# returns 24 only when the sole thing that went wrong was source files
# disappearing. 23 -- "some files/attrs were not transferred" -- is a bucket,
# and has to be opened before it can be judged.
#
# Both codes come from the same race against an upstream that is itself
# syncing. The upstream writes each file to an rsync temp name, mode 0600, then
# renames it into place. Losing that race one way gives us a file that is gone
# by the time we ask for it (24); losing it the other way gives us a file that
# is there but unreadable (23). Job 615 hit the first, job 617 the second:
# 3,190 files transferred, the full 2,628,302,118,514-byte tree seen,
# speedup 424.29 -- a clean incremental -- recorded FAILED over six 0600 temp
# files and two vanished ones.
#
# So 23 is tolerated only when EVERY error line in the output is positively
# recognised as one of those two shapes. Anything else -- a permission error on
# real mirror content, an I/O error, a full disk -- and the run fails. The
# asymmetry that argued against blanket-tolerating 23 still holds and is what
# shapes the classifier: a spurious FAILED is loud and retryable, a spurious
# ACTIVE on a truncated mirror is invisible. Unrecognised means fail.
RSYNC_EXIT_PARTIAL_TRANSFER = 23

# An rsync temp name is "." + the original basename + "." + six characters from
# mkstemp's [A-Za-z0-9] alphabet. Matching that structure, rather than a loose
# "starts with a dot" or a substring of the message, is what keeps ordinary
# dotfiles out: ".cshrc" has no second component, ".vimrc.swp" has a 3-character
# one, "base80.tgz" has no leading dot.
_RSYNC_TEMP_BASENAME_RE = re.compile(r"^\.(?P<stem>[^/]+)\.(?P<suffix>[A-Za-z0-9]{6})$")

# `file has vanished: "/path" (in OpenBSD)`
#
# The trailing " (in MODULE)" clause is what rsync 3.x actually emits and older
# rsync omits, so both shapes have to parse. An earlier revision anchored $
# straight after the closing quote, having been written against log lines that
# had been through `grep -oE '...[^"]*'` -- which stops at the quote and hid the
# clause. Job 619 then failed on two lines that begin "file has vanished:",
# because the pattern rejected the only shape production ever produces.
#
# The clause is modelled exactly as _SEND_FAILED_OPEN_RE below already models
# it, deliberately: one convention for one piece of rsync syntax.
#
# The path is [^"]* rather than .* so the capture stops at the closing quote. A
# greedy .* on a line carrying two quoted spans runs across both and yields a
# "path" that is not one.
#
# $ stays. The anchor is the safety property: a diagnostic with unexplained
# trailing text is not one we understand, and it has to fall through to
# `unrecognised` rather than be waved past on a prefix match.
_VANISHED_RE = re.compile(r'^file has vanished: "(?P<path>[^"]*)"(?: \(in [^)]*\))?$')

# `rsync: [sender] send_files failed to open "/p" (in OpenBSD): Permission denied (13)`
# The [sender] tag and the (in MODULE) clause are both absent on older rsync.
# The errno is pinned to 13: this branch exists for the 0600-temp-file race and
# nothing else, so a different errno on the same path shape still fails.
_SEND_FAILED_OPEN_RE = re.compile(
    r'^rsync: (?:\[[a-z]+\] )?send_files failed to open "(?P<path>[^"]*)"'
    r'(?: \(in [^)]*\))?: Permission denied \(13\)$'
)

# The terminal "rsync error: ... (code N)" line. Only ignored when N is the
# code the process actually exited with -- a (code 11) line inside a run that
# exits 23 is a real second failure and must not be waved through.
_EXIT_SUMMARY_RE = re.compile(r"^rsync (?:error|warning): .*\(code (?P<code>\d+)\)")

# Line prefixes that mean "rsync is reporting a problem". Deliberately broad,
# and safe to over-include: a line caught here must then be positively
# classified as benign or the whole run fails, so a false positive costs a
# spurious failure, never a spurious success. rsync does not prefix all of
# these with "rsync:" -- "file has vanished:" and "IO error encountered" are
# both bare -- which is why this is a list and not a single prefix test.
_DIAGNOSTIC_PREFIXES = (
    "rsync:",
    "rsync error:",
    "rsync warning:",
    "ERROR:",
    "ERROR ",
    "WARNING:",
    "file has vanished:",
    "IO error encountered",
    "skipping ",
    "symlink has no referent",
    "cannot delete non-empty directory",
    "could not make way for",
    "delete_file:",
    "recv_files:",
    "send_files:",
    "readlink_stat(",
    "opendir ",
    "rename failed",
    "mkstemp ",
)


class RsyncErrorVerdict(NamedTuple):
    """The result of reading an exit-23 run's error lines.

    tolerable is True only when nothing was left unrecognised AND at least one
    line was positively explained. An exit 23 with no error lines we can read
    is unattributable, and unattributable means failure.
    """

    tolerable: bool
    vanished: tuple
    upstream_temp_files: tuple
    unrecognised: tuple


def _is_rsync_temp_path(path: str) -> bool:
    """True if `path` names a file rsync itself created as a transfer temp.

    The structural match is the whole test: a leading dot, a non-empty stem, and
    a six-character suffix from mkstemp's alphabet.

    An earlier revision also rejected an all-lowercase-alphabetic suffix, on the
    grounds that ".config.backup" fits the structure exactly. That refinement is
    deliberately gone. It should not come back without new evidence, because:

      * It misfires often. mkstemp draws 6 characters from a 62-character
        alphabet, so (26/62)^6 = 0.54% of genuine temp names are all lowercase.
        Jobs 615 and 617 carried 5 and 8 attributable error lines; at 8 per run
        the chance a sync trips the guard is 1-(1-0.0054)^8 = 4.2%, which on a
        nightly schedule is a spurious FAILED every three to four weeks.
      * It protects against almost nothing on these trees. The scenario it
        prevents needs a real file named ".<stem>.<six lowercase letters>" that
        ALSO raises Permission denied (13) on the sender. Dot-prefixed files are
        not mirror content by convention here -- rsync/rsyncd.conf:22,28,34,40
        excludes them from what we serve, with `exclude = .* ~*`.
      * A false alarm stops being free the moment something is listening.
        scripts/health_check.sh is being put behind a Slack webhook because a
        real upstream failure ran unnoticed for 58 consecutive nights. An alert
        that cries wolf monthly teaches people to mute it, which is the exact
        failure mode the webhook exists to end.

    The safety in this function is carried by the exact six-character length and,
    at the call site, by the errno being pinned to Permission denied (13). Both
    stay. Neither is negotiable the way this refinement was.
    """
    basename = path.rsplit("/", 1)[-1]
    return _RSYNC_TEMP_BASENAME_RE.match(basename) is not None


def _classify_partial_transfer(output: str, returncode: int) -> RsyncErrorVerdict:
    """Decide whether an rsync exit 23 is the upstream temp-file race.

    Every line that looks like a diagnostic must resolve to one of:
      * `file has vanished: "..."` -- the source went away mid-run. Tolerated
        for any path, because that is already how exit 24 is treated and the
        two codes describe the same event.
      * a Permission-denied open failure on a path whose basename has rsync's
        temp-file structure.
      * the terminal exit-summary line for this very exit code.

    Anything else lands in `unrecognised` and the run fails.
    """
    vanished = []
    temp_files = []
    unrecognised = []

    for raw_line in output.split("\n"):
        line = raw_line.strip()
        if not line or not line.startswith(_DIAGNOSTIC_PREFIXES):
            continue

        summary = _EXIT_SUMMARY_RE.match(line)
        if summary and int(summary.group("code")) == returncode:
            continue

        gone = _VANISHED_RE.match(line)
        if gone:
            vanished.append(gone.group("path"))
            continue

        denied = _SEND_FAILED_OPEN_RE.match(line)
        if denied and _is_rsync_temp_path(denied.group("path")):
            temp_files.append(denied.group("path"))
            continue

        unrecognised.append(line)

    tolerable = not unrecognised and bool(vanished or temp_files)
    return RsyncErrorVerdict(
        tolerable=tolerable,
        vanished=tuple(vanished),
        upstream_temp_files=tuple(temp_files),
        unrecognised=tuple(unrecognised),
    )

# rsync 3.x breaks its counts down by entry type:
#     Number of files: 5,582 (reg: 4,321, dir: 1,261)
# _BREAKDOWN_RE grabs the parenthesised part. rsync 2.6.9 and openrsync print
# no parenthesis at all.
_BREAKDOWN_RE = re.compile(r"\(([^)]*)\)")

# Items inside that parenthesis are separated by ", " while the thousands
# separator inside a number is a bare ",". Splitting on comma-then-whitespace
# is what keeps "reg: 4,321, dir: 1,261" from being read as reg=4: an item
# separator always has a space after it, a thousands separator never does.
_BREAKDOWN_ITEM_SEPARATOR_RE = re.compile(r",\s+")


def _to_int(token: str) -> Optional[int]:
    """First whitespace-delimited word of `token` as an int, or None.

    Handles the thousands separators rsync always writes and the unit suffix it
    appends to sizes ("17 B" on 2.6.9, "17 bytes" on 3.x). Returns None rather
    than guessing for -h/--human-readable output ("897.65G"), so a scaled
    number is never mistaken for an exact one.
    """
    try:
        return int(token.strip().split()[0].replace(",", ""))
    except (IndexError, ValueError):
        return None


def _parse_count_field(value: str) -> tuple[Optional[int], dict]:
    """Split an rsync count field into its leading total and its breakdown.

        "5,582 (reg: 4,321, dir: 1,261)" -> (5582, {"reg": 4321, "dir": 1261})
        "5"                              -> (5, {})

    Sub-counts that do not parse are omitted, so an empty breakdown dict means
    "no usable breakdown" and the caller can fall back to the leading total.
    """
    breakdown = {}
    match = _BREAKDOWN_RE.search(value)
    if match:
        head = value[:match.start()]
        for item in _BREAKDOWN_ITEM_SEPARATOR_RE.split(match.group(1)):
            key, separator, raw = item.partition(":")
            if not separator:
                continue
            parsed = _to_int(raw)
            if parsed is not None:
                breakdown[key.strip().lower()] = parsed
    else:
        head = value

    return _to_int(head), breakdown


def _regular_file_count(value: str) -> Optional[int]:
    """The number of *regular files* in an rsync count field.

    `Number of files: 5,582 (reg: 4,321, dir: 1,261)` describes 4,321 files and
    1,261 directories. The leading 5,582 is the size of the file list, not a
    file count, and reporting it under a column labelled "files" over-reports
    by the directory, symlink and device count -- 29% in that sample.

    A breakdown with no `reg:` key means zero regular files (a tree of nothing
    but directories), which is why the fallback is only used when the breakdown
    is absent entirely. That fallback -- rsync 2.6.9 and openrsync, which print
    no breakdown -- still over-reports; there is no finer number in that output.
    """
    total, breakdown = _parse_count_field(value)
    if breakdown:
        return breakdown.get("reg", 0)
    return total


class SyncConfig:
    """Configuration from environment variables."""

    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
    POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
    POSTGRES_DB = os.getenv("POSTGRES_DB", "bsdmirrors")
    POSTGRES_USER = os.getenv("POSTGRES_USER", "bsdmirrors")
    POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")

    REDIS_HOST = os.getenv("REDIS_HOST", "redis")
    REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

    SYNC_SCHEDULE = os.getenv("SYNC_SCHEDULE", "0 4 * * *")
    SYNC_BANDWIDTH_LIMIT = int(os.getenv("SYNC_BANDWIDTH_LIMIT", "0"))
    SYNC_TIMEOUT = int(os.getenv("SYNC_TIMEOUT", "600"))

    FREEBSD_ENABLED = os.getenv("FREEBSD_ENABLED", "true").lower() == "true"
    FREEBSD_UPSTREAM = os.getenv("FREEBSD_UPSTREAM", "rsync://ftp.freebsd.org/FreeBSD/")

    NETBSD_ENABLED = os.getenv("NETBSD_ENABLED", "true").lower() == "true"
    NETBSD_UPSTREAM = os.getenv("NETBSD_UPSTREAM", "rsync://rsync.NetBSD.org/NetBSD/")

    OPENBSD_ENABLED = os.getenv("OPENBSD_ENABLED", "true").lower() == "true"
    OPENBSD_UPSTREAM = os.getenv("OPENBSD_UPSTREAM", "rsync://ftp2.eu.openbsd.org/OpenBSD/")

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"


config = SyncConfig()


class SyncService:
    """Main sync service class."""

    def __init__(self):
        self.running = True
        self.engine = create_async_engine(config.database_url, pool_size=5)
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)
        self.current_sync: Optional[asyncio.subprocess.Process] = None
        # Runtime settings (reloaded from DB)
        self.sync_schedule = config.SYNC_SCHEDULE
        self.sync_bandwidth_limit = config.SYNC_BANDWIDTH_LIMIT
        self.sync_timeout = config.SYNC_TIMEOUT

    async def reload_settings(self) -> None:
        """Reload settings from the database settings table (if it exists)."""
        try:
            async with self.session_maker() as session:
                result = await session.execute(select(Setting))
                settings_rows = result.scalars().all()

                for s in settings_rows:
                    if s.key == "sync_schedule" and s.value:
                        self.sync_schedule = s.value
                    elif s.key == "sync_bandwidth_limit" and s.value:
                        try:
                            self.sync_bandwidth_limit = int(s.value)
                        except ValueError:
                            pass
                    elif s.key == "sync_timeout" and s.value:
                        try:
                            self.sync_timeout = int(s.value)
                        except ValueError:
                            pass
        except Exception as e:
            # Settings table may not exist yet — use env defaults
            logger.debug("Could not reload settings from DB", error=str(e))

    async def run_rsync(
        self,
        source: str,
        destination: str,
        mirror_name: str
    ) -> tuple[bool, str, dict]:
        """Run rsync command and capture output."""

        # Build rsync command
        cmd = [
            "rsync",
            "-rlptHz",
            "--delete",
            "--delete-delay",
            "--delay-updates",
            "--stats",
            "--no-owner",
            "--no-group",
            f"--timeout={self.sync_timeout}",
        ]

        if self.sync_bandwidth_limit > 0:
            cmd.append(f"--bwlimit={self.sync_bandwidth_limit}")

        cmd.extend([source, destination])

        logger.info("Starting rsync", mirror=mirror_name, source=source, destination=destination)

        try:
            # Ensure destination exists
            os.makedirs(destination, exist_ok=True)

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            self.current_sync = process

            stdout, _ = await process.communicate()
            output = stdout.decode("utf-8", errors="replace")

            self.current_sync = None

            # Parse statistics from output
            stats = self._parse_rsync_stats(output)

            if process.returncode in RSYNC_SUCCESS_EXIT_CODES:
                if process.returncode == RSYNC_EXIT_VANISHED_SOURCE_FILES:
                    # Warning, not an error. The mirror on disk is complete
                    # apart from files upstream deleted mid-run, which the next
                    # sync will not look for either. Logged at warning so it is
                    # visible, returned as success so the job is not FAILED.
                    logger.warning(
                        "Rsync completed with vanished source files",
                        mirror=mirror_name,
                        returncode=process.returncode,
                        stats=stats,
                    )
                else:
                    logger.info("Rsync completed successfully", mirror=mirror_name, stats=stats)
                return True, output, stats

            if process.returncode == RSYNC_EXIT_PARTIAL_TRANSFER:
                verdict = _classify_partial_transfer(output, process.returncode)
                if verdict.tolerable:
                    logger.warning(
                        "Rsync exit 23 tolerated: every error line was an upstream "
                        "temp file or a vanished source",
                        mirror=mirror_name,
                        returncode=process.returncode,
                        upstream_temp_file_count=len(verdict.upstream_temp_files),
                        vanished_count=len(verdict.vanished),
                        upstream_temp_files=list(verdict.upstream_temp_files[:10]),
                        vanished=list(verdict.vanished[:10]),
                        stats=stats,
                    )
                    return True, output, stats

                logger.error(
                    "Rsync failed: exit 23 with error lines that are not the "
                    "upstream temp-file race",
                    mirror=mirror_name,
                    returncode=process.returncode,
                    unrecognised_count=len(verdict.unrecognised),
                    unrecognised=list(verdict.unrecognised[:10]),
                    upstream_temp_file_count=len(verdict.upstream_temp_files),
                    vanished_count=len(verdict.vanished),
                )
                return False, output, stats

            logger.error("Rsync failed", mirror=mirror_name, returncode=process.returncode)
            return False, output, stats

        except Exception as e:
            logger.error("Rsync error", mirror=mirror_name, error=str(e))
            return False, str(e), {}

    def _parse_rsync_stats(self, output: str) -> dict:
        """Parse the --stats block of an rsync run.

        Every key is optional. A key is absent when rsync did not print the
        line, or printed a value int() will not take -- which is how
        -h/--human-readable output is rejected rather than guessed at. Callers
        must therefore use stats.get(), and must distinguish a missing key from
        a legitimate zero.

        Keys:
          regular_files      regular files in the file list, from the `reg:`
                             sub-count. This is what Mirror.file_count means by
                             "files"; see _regular_file_count.
          total_entries      the leading number on `Number of files:`, i.e.
                             every file-list entry of every type. Nothing
                             writes it to a column today; it is returned so the
                             reg/total split stays recoverable downstream
                             instead of being silently dropped.
          files_transferred  regular files actually sent. Both the rsync 3.x
                             spelling ("Number of regular files transferred:")
                             and the 2.6.9/openrsync one ("Number of files
                             transferred:") are matched -- the latter used to
                             fall through and leave the column NULL.
          files_deleted      regular files removed by --delete, which is always
                             passed. SyncJob.files_deleted had no parser at all
                             and was NULL on every job ever run.
          total_size         bytes in the whole tree.
          bytes_transferred  bytes actually sent.

        Branch matching stays substring-based (`in`), not prefix-based: no two
        of these labels is a substring of another, and "Number of created
        files:" / "Number of deleted files:" do not contain "Number of files:".
        """
        stats = {}

        for line in output.split("\n"):
            # split(":", 1) -- not split(":") -- because the value half of a
            # 3.x count line contains its own colons inside the parenthesis.
            parts = line.split(":", 1)
            if len(parts) != 2:
                continue
            value = parts[1]

            if "Number of files:" in line:
                total, breakdown = _parse_count_field(value)
                regular = breakdown.get("reg", 0) if breakdown else total
                if total is not None:
                    stats["total_entries"] = total
                if regular is not None:
                    stats["regular_files"] = regular
                if total is None and regular is None:
                    logger.debug("Failed to parse rsync file counts", line=line.strip())
            elif "Number of deleted files:" in line:
                deleted = _regular_file_count(value)
                if deleted is not None:
                    stats["files_deleted"] = deleted
                else:
                    logger.debug("Failed to parse rsync files_deleted", line=line.strip())
            elif ("Number of regular files transferred:" in line
                    or "Number of files transferred:" in line):
                transferred = _to_int(value)
                if transferred is not None:
                    stats["files_transferred"] = transferred
                else:
                    logger.debug("Failed to parse rsync files_transferred", line=line.strip())
            elif "Total file size:" in line:
                total_size = _to_int(value)
                if total_size is not None:
                    stats["total_size"] = total_size
                else:
                    logger.debug("Failed to parse rsync total_size", line=line.strip())
            elif "Total transferred file size:" in line:
                sent = _to_int(value)
                if sent is not None:
                    stats["bytes_transferred"] = sent
                else:
                    logger.debug("Failed to parse rsync bytes_transferred", line=line.strip())

        return stats

    async def sync_mirror_job(self, job_id: int, mirror_id: int, name: str, upstream: str, local_path: str) -> None:
        """Execute a sync for a pre-existing SyncJob record."""
        async with self.session_maker() as session:
            # Mark job as running
            await session.execute(
                update(SyncJob)
                .where(SyncJob.id == job_id)
                .values(status=SyncStatus.RUNNING, started_at=datetime.now(timezone.utc))
            )
            # Update mirror status to syncing
            await session.execute(
                update(Mirror)
                .where(Mirror.id == mirror_id)
                .values(status=MirrorStatus.SYNCING, last_sync_started=datetime.now(timezone.utc))
            )
            await session.commit()

        logger.info("Executing sync job", job_id=job_id, mirror=name)

        # Run rsync
        success, output, stats = await self.run_rsync(upstream, local_path, name)

        # Update job and mirror status
        async with self.session_maker() as session:
            now = datetime.now(timezone.utc)

            # Update sync job
            await session.execute(
                update(SyncJob)
                .where(SyncJob.id == job_id)
                .values(
                    status=SyncStatus.COMPLETED if success else SyncStatus.FAILED,
                    completed_at=now,
                    files_transferred=stats.get("files_transferred"),
                    bytes_transferred=stats.get("bytes_transferred"),
                    files_deleted=stats.get("files_deleted"),
                    rsync_output=output[-10000:] if len(output) > 10000 else output,
                    error_message=None if success else output[-1000:]
                )
            )

            # Update mirror status.
            #
            # last_sync_completed is NOT cleared on failure. It answers "when
            # was this mirror last known good", which is the one question a
            # failed sync makes urgent; overwriting it with NULL destroyed the
            # answer at exactly the wrong moment. The failure is recorded in
            # status, last_sync_error and the SyncJob row instead.
            mirror_update = {
                "status": MirrorStatus.ACTIVE if success else MirrorStatus.ERROR,
                "last_sync_error": None if success else output[-500:]
            }
            if success:
                mirror_update["last_sync_completed"] = now

            # Size and file count are still only written on success. A failed
            # run's --stats block describes the partial transfer it managed
            # before dying, so recording it would replace a correct total with
            # a smaller wrong one -- the same understatement this guard exists
            # to prevent, just from the other direction. `is not None` rather
            # than truthiness so a genuine zero (an empty upstream) is stored
            # instead of being mistaken for a parse failure.
            if success and stats.get("total_size") is not None:
                mirror_update["total_size_bytes"] = stats["total_size"]
            if success and stats.get("regular_files") is not None:
                mirror_update["file_count"] = stats["regular_files"]

            await session.execute(
                update(Mirror)
                .where(Mirror.id == mirror_id)
                .values(**mirror_update)
            )
            await session.commit()

        logger.info("Mirror sync finished", mirror=name, job_id=job_id, success=success)

    async def sync_mirror(self, mirror_id: int, name: str, upstream: str, local_path: str) -> None:
        """Create a new sync job and execute it (for scheduled syncs)."""
        async with self.session_maker() as session:
            sync_job = SyncJob(
                mirror_id=mirror_id,
                status=SyncStatus.PENDING,
                triggered_by="scheduled"
            )
            session.add(sync_job)
            await session.commit()
            await session.refresh(sync_job)
            job_id = sync_job.id

        await self.sync_mirror_job(job_id, mirror_id, name, upstream, local_path)

    async def poll_pending_jobs(self) -> int:
        """Check for pending sync jobs and execute them. Returns count of jobs processed."""
        processed = 0

        async with self.session_maker() as session:
            result = await session.execute(
                select(SyncJob, Mirror)
                .join(Mirror, SyncJob.mirror_id == Mirror.id)
                .where(SyncJob.status == SyncStatus.PENDING)
                .order_by(SyncJob.id.asc())
            )
            pending_jobs = result.all()

        for sync_job, mirror in pending_jobs:
            if not self.running:
                break

            logger.info("Found pending sync job", job_id=sync_job.id, mirror=mirror.name)

            await self.sync_mirror_job(
                job_id=sync_job.id,
                mirror_id=mirror.id,
                name=mirror.name,
                upstream=mirror.upstream_url,
                local_path=mirror.local_path
            )
            processed += 1

        return processed

    async def run_scheduled_sync(self) -> None:
        """Run sync for all enabled mirrors."""
        logger.info("Starting scheduled sync for all mirrors")

        async with self.session_maker() as session:
            result = await session.execute(
                select(Mirror).where(Mirror.enabled.is_(True))
            )
            mirrors = result.scalars().all()

        for mirror in mirrors:
            if not self.running:
                break

            await self.sync_mirror(
                mirror_id=mirror.id,
                name=mirror.name,
                upstream=mirror.upstream_url,
                local_path=mirror.local_path
            )

    async def scheduler_loop(self) -> None:
        """Main scheduler loop — polls for pending jobs every POLL_INTERVAL seconds
        and runs scheduled syncs at the configured cron schedule."""
        cron = croniter(self.sync_schedule, datetime.now())
        next_run = cron.get_next(datetime)
        settings_reload_interval = 30  # Reload settings every 30 cycles (~5 min)
        poll_count = 0

        logger.info("Next scheduled sync", next_run=next_run.isoformat())

        while self.running:
            try:
                # Sleep in short intervals to poll for pending jobs
                await asyncio.sleep(POLL_INTERVAL)

                if not self.running:
                    break

                poll_count += 1

                # Reload settings periodically to pick up admin panel changes
                if poll_count % settings_reload_interval == 0:
                    old_schedule = self.sync_schedule
                    await self.reload_settings()
                    # If schedule changed, recalculate next run
                    if self.sync_schedule != old_schedule:
                        logger.info("Sync schedule changed", old=old_schedule, new=self.sync_schedule)
                        cron = croniter(self.sync_schedule, datetime.now())
                        next_run = cron.get_next(datetime)
                        logger.info("Next scheduled sync recalculated", next_run=next_run.isoformat())

                # Poll for manually triggered pending jobs
                processed = await self.poll_pending_jobs()
                if processed > 0:
                    logger.info("Processed pending jobs", count=processed)

                # Check if cron schedule is due
                now = datetime.now()
                if now >= next_run:
                    logger.info("Cron schedule triggered", schedule=self.sync_schedule)

                    # Reload settings before scheduled sync
                    await self.reload_settings()

                    await self.run_scheduled_sync()

                    # Advance to next cron time
                    cron = croniter(self.sync_schedule, datetime.now())
                    next_run = cron.get_next(datetime)
                    logger.info("Next scheduled sync", next_run=next_run.isoformat())

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Scheduler loop error", error=str(e))
                await asyncio.sleep(POLL_INTERVAL)

    async def health_handler(self, request: web.Request) -> web.Response:
        """Health check endpoint handler."""
        return web.json_response({
            "status": "healthy",
            "running": self.running,
            "syncing": self.current_sync is not None
        })

    async def start_health_server(self) -> None:
        """Start the health check HTTP server."""
        app = web.Application()
        app.router.add_get("/health", self.health_handler)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", 8001)
        await site.start()
        logger.info("Health server started on port 8001")

    def handle_signal(self, signum: int, frame) -> None:
        """Handle shutdown signals."""
        logger.info("Received signal, shutting down", signal=signum)
        self.running = False

        if self.current_sync:
            self.current_sync.terminate()

    async def run(self) -> None:
        """Main entry point."""
        logger.info("Starting BSD Mirrors Sync Service")

        # Set up signal handlers
        signal.signal(signal.SIGTERM, self.handle_signal)
        signal.signal(signal.SIGINT, self.handle_signal)

        # Start health server
        await self.start_health_server()

        # Wait for database to be ready
        for i in range(30):
            try:
                async with self.engine.connect() as conn:
                    await conn.execute(select(1))
                    break
            except Exception:
                logger.info("Waiting for database...", attempt=i+1)
                await asyncio.sleep(2)

        # Load settings from database
        await self.reload_settings()

        # Process any pending jobs on startup
        try:
            pending = await self.poll_pending_jobs()
            if pending > 0:
                logger.info("Processed pending jobs on startup", count=pending)
        except Exception as e:
            logger.warning("Could not poll pending jobs on startup (tables may not exist yet)", error=str(e))

        # Run initial sync on startup (optional)
        if os.getenv("SYNC_ON_STARTUP", "false").lower() == "true":
            await self.run_scheduled_sync()

        # Start scheduler
        await self.scheduler_loop()

        await self.engine.dispose()
        logger.info("Sync service stopped")


# Import models (for SQLAlchemy metadata)
# NOTE: These must match the backend's model definitions exactly,
# including using the same PostgreSQL enum types.
#
# E402 (import not at top of file) is suppressed on the next three lines only.
# These imports sit below the code that uses them because this file duplicates
# backend/app/models/ by hand. Moving them is not a formatting fix -- it is
# Phase 4, which extracts a shared models package and deletes this whole block.
# Delete these three noqa comments then; RUF100 will fail the build if they
# outlive their reason.
import enum as python_enum  # noqa: E402
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, BigInteger, Enum, ForeignKey  # noqa: E402
from sqlalchemy.orm import declarative_base  # noqa: E402

Base = declarative_base()


class MirrorStatus(str, python_enum.Enum):
    ACTIVE = "active"
    SYNCING = "syncing"
    ERROR = "error"
    DISABLED = "disabled"


class SyncStatus(str, python_enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Mirror(Base):
    __tablename__ = "mirrors"
    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True)
    mirror_type = Column(String(20))
    upstream_url = Column(String(500))
    local_path = Column(String(500))
    enabled = Column(Boolean, default=True)
    status = Column(Enum(MirrorStatus, name="mirror_status"), default=MirrorStatus.ACTIVE)
    last_sync_started = Column(DateTime(timezone=True))
    last_sync_completed = Column(DateTime(timezone=True))
    last_sync_error = Column(Text)
    total_size_bytes = Column(BigInteger)
    file_count = Column(BigInteger)

class SyncJob(Base):
    __tablename__ = "sync_jobs"
    id = Column(Integer, primary_key=True)
    mirror_id = Column(Integer, ForeignKey("mirrors.id"))
    status = Column(Enum(SyncStatus, name="sync_status"), default=SyncStatus.PENDING)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    files_transferred = Column(BigInteger)
    bytes_transferred = Column(BigInteger)
    files_deleted = Column(BigInteger)
    rsync_output = Column(Text)
    error_message = Column(Text)
    triggered_by = Column(String(50))

class Setting(Base):
    """Settings table — mirrors backend Setting model."""
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text)
    description = Column(Text)


if __name__ == "__main__":
    service = SyncService()
    asyncio.run(service.run())
