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
from typing import AbstractSet, ClassVar, Dict, NamedTuple, Optional

from aiohttp import web
from croniter import croniter
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
import structlog

# The schema, defined once, in shared/models/. This file used to redeclare
# mirrors, sync_jobs and settings by hand at the bottom of the module, in a
# second declarative_base(), under a comment asking that they be kept matching
# the backend's -- which nothing checked and which had drifted seventeen ways,
# one of them into production (798ae79).
#
# These imports are at the top of the file now, with everything else. They sat
# below the code that used them only because they were definitions, not
# imports; that reason is gone, and with it their three E402 suppressions.
#
# NOT IMPORTED, deliberately: Base. This service must never create the schema.
# create_all belongs to the backend alone -- see shared/models/base.py.
from shared.models import Mirror, MirrorStatus, MirrorType, Setting, SyncJob, SyncStatus
from shared.settings_spec import (
    DEFAULT_SYNC_SCHEDULE,
    SettingError,
    UnknownSettingKey,
    parse_setting,
)

# Per-mirror rsync protect-filter rules -- see the module docstring there for
# what these do to --delete and why the list lives outside settings_spec.
#
# Import shape matches __main__.py's `from sync_service import SyncService`,
# not shared.models'. sync/Dockerfile COPYs sync/'s *contents* into /app (see
# "EVERY COPY SOURCE ... RELATIVE TO THE REPO ROOT" there), so in the
# container sync_service.py and protected_paths.py are siblings at /app/ with
# no enclosing `sync` package -- the bare import is what production actually
# runs. Under pytest, sync/ has no __init__.py and is never added to sys.path
# on its own (pyproject.toml's pythonpath is `backend` and `.`), so the same
# module is reached as sync.protected_paths instead. Both branches load the
# same file; tests/test_protected_paths.py imports it the second way, matching
# every other test's `from sync import sync_service`.
try:
    from protected_paths import protect_filter_args
except ImportError:
    from sync.protected_paths import protect_filter_args

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

# How many poll cycles between settings reloads and reaper passes. At
# POLL_INTERVAL=10 that is one of each every five minutes.
SETTINGS_RELOAD_INTERVAL_CYCLES = 30
REAP_INTERVAL_CYCLES = 30

# A reaped job that had been running longer than this is logged at WARNING
# rather than INFO. It does not change the decision -- nothing about elapsed
# time does -- it just makes an unexpected reap of a long transfer loud instead
# of a line in the noise. Job 615 ran 15h43m legitimately; if this service ever
# reaps something that shape, the operator should not have to go looking.
LONG_RUNNING_REAP_WARN_SECONDS = 3600

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


# ---------------------------------------------------------------------------
# Orphaned sync jobs
#
# If this container dies mid-rsync -- OOM kill, host reboot, SIGKILL -- the
# completion block in sync_mirror_job never runs. The SyncJob row stays RUNNING
# and the Mirror row stays SYNCING forever, and admin.py's trigger_sync then
# refuses every manual retry with "Mirror is already syncing". Recovery was a
# hand-written UPDATE.
#
# WHAT THIS DELIBERATELY DOES NOT USE: elapsed time.
#
# Duration cannot separate a dead sync from a slow one, and the production
# record says so outright. Job 615 ran for 15 hours 43 minutes: a healthy,
# actively progressing 2.58 TB transfer of 567,277 files. Job 624 was the same
# mirror, incremental, and finished in 13 minutes. Any elapsed-time threshold
# is either short enough to kill job 615 at hour fifteen or long enough to be
# useless. There is no value in between, so no value is used.
#
# WHAT IT USES INSTEAD: ownership.
#
# The sync service is a single process that runs its jobs strictly one at a
# time -- poll_pending_jobs awaits each sync_mirror_job in a for loop, and
# scheduler_loop awaits poll_pending_jobs. So the process knows the id of every
# job it is working on, and a RUNNING row whose id is not in that set is a row
# nothing is going to advance. That is not a heuristic about a job; it is the
# absence of the only thing that could ever move it.
#
# The claim is ordered so the window cannot open the wrong way:
#
#   sync_mirror_job()    add(job_id)          <- synchronous, before any await
#                        UPDATE ... RUNNING   <- row becomes RUNNING after
#                        run_rsync(...)
#                        UPDATE ... COMPLETED <- row stops being RUNNING first
#                        discard(job_id)      <- claim released after
#
# Both mutations are plain set operations with no await between them and the
# statement they guard, and the reaper is a coroutine on the same event loop,
# so it can only observe the pair in a consistent state. "RUNNING and claimed"
# and "not RUNNING and unclaimed" are the only two things it can see for a job
# this process is handling. A false positive against a live local sync is not
# unlikely here, it is unrepresentable.
#
# The one case that does read as an orphan without being a crash is a job that
# raised between the two commits -- a database blip, a cancellation. The finally
# releases the claim while the row still says RUNNING, so the next reaper pass
# clears it. That is correct: nothing is going to finish that job either.
#
# ASSUMPTION, stated because it is load-bearing: exactly one sync-service
# process talks to this database. docker-compose.yml pins the container name
# (bsdmirrors-sync), so Docker refuses a second copy and Compose replaces
# rather than duplicates. If that ever stops being true, ownership has to move
# out of this process's memory and into a claim both processes can see -- which
# means a column, which means migrations, which this repo does not have. Adding
# replicas without doing that would let one process reap another's live job.
# ---------------------------------------------------------------------------

class OrphanVerdict(NamedTuple):
    """Whether one sync job is abandoned, and why.

    elapsed_seconds is reported, never consulted. It exists for the log line so
    an operator can see what was reaped; see the note above on why it is not
    allowed anywhere near the decision.
    """

    reap: bool
    reason: str
    elapsed_seconds: Optional[float]


def _as_utc(value: datetime) -> datetime:
    """Postgres hands back an aware datetime; SQLite hands back a naive one.

    The columns are DateTime(timezone=True) and every writer uses
    datetime.now(timezone.utc), so a naive value read back is UTC that lost its
    tzinfo in transit, not local time.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _orphan_verdict(
    job_id: int,
    job_status: SyncStatus,
    started_at: Optional[datetime],
    active_job_ids: AbstractSet[int],
    now: datetime,
) -> OrphanVerdict:
    """Decide whether a sync job has been abandoned.

    Pure, and pure on purpose: everything it needs is an argument, so the
    decision can be tested exhaustively -- including against job 615's real
    shape -- without a database, a subprocess or a clock.

    A job with no started_at cannot be one of ours: this process writes
    started_at in the same statement that sets RUNNING. If the row says RUNNING
    with started_at NULL it was written by something else and is not being
    advanced by anything.
    """
    elapsed = None
    if started_at is not None:
        elapsed = (now - _as_utc(started_at)).total_seconds()

    if job_status != SyncStatus.RUNNING:
        return OrphanVerdict(False, f"status is {job_status.value}, not running", elapsed)

    if job_id in active_job_ids:
        return OrphanVerdict(False, "this process is running it", elapsed)

    return OrphanVerdict(True, "no process in this service is running it", elapsed)


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
    SYNC_ON_STARTUP = os.getenv("SYNC_ON_STARTUP", "false")

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
        # Job ids this process is executing right now. The reaper's entire
        # decision rests on this set -- see the block above OrphanVerdict.
        # sync_mirror_job is the only writer.
        self.active_job_ids: set = set()
        # Runtime settings (reloaded from DB)
        self.sync_schedule = config.SYNC_SCHEDULE
        self.sync_bandwidth_limit = config.SYNC_BANDWIDTH_LIMIT
        self.sync_timeout = config.SYNC_TIMEOUT

        # SYNC_ON_STARTUP is the DEFAULT; the `sync_on_startup` settings row
        # overrides it in reload_settings, exactly like the three above. Until
        # now this attribute did not exist and run() read the environment
        # variable directly, so the admin panel's dropdown wrote a row that
        # nothing consulted.
        #
        # Parsed rather than assigned raw. The old test was
        # `.lower() == "true"`, which silently read SYNC_ON_STARTUP=yes and
        # SYNC_ON_STARTUP=1 as FALSE -- an operator who enabled it that way got
        # no startup sync and no warning -- and read the typo "ture" the same
        # way. parse_setting accepts the spellings a person actually types and
        # rejects the rest loudly.
        try:
            self.sync_on_startup = parse_setting("sync_on_startup", config.SYNC_ON_STARTUP)
        except SettingError as exc:
            logger.warning(
                "Ignoring unusable SYNC_ON_STARTUP, defaulting to false",
                rejected=config.SYNC_ON_STARTUP,
                reason=str(exc),
            )
            self.sync_on_startup = False

    # Which settings row feeds which attribute. Everything about a key -- how
    # it parses, what range it may hold -- lives in shared/settings_spec.py,
    # which the backend's PATCH /api/admin/settings validates against too.
    _SETTING_ATTRS: ClassVar[Dict[str, str]] = {
        "sync_schedule": "sync_schedule",
        "sync_bandwidth_limit": "sync_bandwidth_limit",
        "sync_timeout": "sync_timeout",
        "sync_on_startup": "sync_on_startup",
    }

    async def reload_settings(self) -> None:
        """Reload settings from the database settings table (if it exists).

        Every value is validated before it is adopted, and one that fails is
        refused with a WARNING rather than taken or dropped in silence.

        The API validates on write, but the API is not the only way a row gets
        written: a psql session, a restore from an older dump, or a deployment
        that predates the validation all reach this table without passing
        through it. A value that wedges the scheduler is not less wedging for
        having arrived by another route, so the reader checks too.

        This used to be `int(...)` under a bare `except ValueError: pass`, which
        kept the previous value and said nothing -- an operator who typed "60O"
        into the timeout box saw it saved, saw it listed, and had no way to find
        out it was being ignored. sync_schedule had no guard at all: it went
        straight to croniter() in scheduler_loop, raised inside the generic
        handler, and left the loop retrying every ten seconds forever.
        """
        try:
            async with self.session_maker() as session:
                result = await session.execute(select(Setting))
                settings_rows = result.scalars().all()
        except Exception as e:
            # Settings table may not exist yet -- use env defaults
            logger.debug("Could not reload settings from DB", error=str(e))
            return

        for row in settings_rows:
            attr = self._SETTING_ATTRS.get(row.key)
            if attr is None or row.value is None:
                continue
            try:
                value = parse_setting(row.key, row.value)
            except UnknownSettingKey:
                # _SETTING_ATTRS is a subset of SETTING_SPECS, so this cannot
                # happen -- and tests/test_settings_validation.py pins that.
                # Caught rather than allowed to propagate because an exception
                # escaping here lands in scheduler_loop's generic handler,
                # which retries every ten seconds forever: the exact wedge this
                # whole change exists to close. Loud, not fatal.
                logger.error(
                    "Settings key has no spec; not adopting it",
                    key=row.key,
                )
                continue
            except SettingError as exc:
                logger.warning(
                    "Ignoring unusable setting, keeping current value",
                    key=row.key,
                    rejected=row.value,
                    current=getattr(self, attr),
                    reason=str(exc),
                )
                continue
            setattr(self, attr, value)

    async def run_rsync(
        self,
        source: str,
        destination: str,
        mirror_name: str,
        mirror_type: Optional[MirrorType] = None,
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

        # -f "P <pattern>" rules for this mirror's protected (EOL) trees, if
        # any -- see sync/protected_paths.py. [] for a mirror with nothing
        # configured, so --delete keeps behaving exactly as it did before this
        # existed.
        cmd.extend(protect_filter_args(mirror_type))

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

    async def sync_mirror_job(
        self,
        job_id: int,
        mirror_id: int,
        name: str,
        upstream: str,
        local_path: str,
        mirror_type: Optional[MirrorType] = None,
    ) -> None:
        """Execute a sync for a pre-existing SyncJob record."""
        # Claim the job before anything writes RUNNING to its row, and hold the
        # claim until after something writes a terminal status. This ordering is
        # what makes the reaper safe; the long comment above OrphanVerdict lays
        # out why. Both statements are plain set operations with no await
        # between them and the database write they bracket, so the reaper --
        # another coroutine on this same loop -- cannot catch them half-applied.
        self.active_job_ids.add(job_id)
        try:
            await self._sync_mirror_job(job_id, mirror_id, name, upstream, local_path, mirror_type)
        finally:
            # finally, not "after the happy path": if the body raised between
            # the two commits the row still says RUNNING and nothing is going
            # to finish it. Releasing the claim here is what lets the next
            # reaper pass clear it without waiting for a restart.
            self.active_job_ids.discard(job_id)

    async def _sync_mirror_job(
        self,
        job_id: int,
        mirror_id: int,
        name: str,
        upstream: str,
        local_path: str,
        mirror_type: Optional[MirrorType] = None,
    ) -> None:
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
        success, output, stats = await self.run_rsync(upstream, local_path, name, mirror_type)

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

    async def sync_mirror(
        self,
        mirror_id: int,
        name: str,
        upstream: str,
        local_path: str,
        mirror_type: Optional[MirrorType] = None,
    ) -> None:
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

        await self.sync_mirror_job(job_id, mirror_id, name, upstream, local_path, mirror_type)

    REAPED_JOB_MESSAGE = (
        "Sync job abandoned: no sync-service process was running it. The most "
        "likely cause is the sync container stopping mid-rsync. The mirror on "
        "disk is whatever rsync had written when it stopped -- incomplete, but "
        "not corrupt -- and the next sync will resume from there."
    )

    async def reap_orphaned_jobs(self, trigger: str) -> int:
        """Close out sync jobs that no process is running. Returns the count.

        Two things get fixed, in this order:

          1. SyncJob rows stuck at RUNNING -> FAILED, with completed_at and an
             error_message saying what happened. The mirror they belong to
             comes out of SYNCING at the same time.
          2. Mirror rows stuck at SYNCING with no RUNNING job anywhere. Step 1
             cannot produce this state, but a deleted job row or a hand-edited
             table can, and it blocks trigger_sync just as effectively.

        Deliberately NOT touched: last_sync_completed, total_size_bytes and
        file_count. They answer "when was this mirror last known good and how
        big was it then", and a sync that died has no better answer to offer --
        the same reasoning that keeps sync_mirror_job from clearing them on an
        ordinary failure.

        The mirror goes to ERROR rather than ACTIVE because the tree on disk is
        a partial transfer. ERROR is also what the admin panel surfaces as
        needing attention, which is true here.

        The job goes to FAILED rather than CANCELLED: CANCELLED reads as "a
        person stopped this", and nobody did.
        """
        now = datetime.now(timezone.utc)
        reaped = 0

        async with self.session_maker() as session:
            result = await session.execute(
                select(SyncJob).where(SyncJob.status == SyncStatus.RUNNING)
            )
            running_jobs = result.scalars().all()

            orphans = []
            for job in running_jobs:
                verdict = _orphan_verdict(
                    job_id=job.id,
                    job_status=job.status,
                    started_at=job.started_at,
                    active_job_ids=self.active_job_ids,
                    now=now,
                )
                if verdict.reap:
                    orphans.append((job, verdict))

            for job, verdict in orphans:
                await session.execute(
                    update(SyncJob)
                    .where(SyncJob.id == job.id)
                    .values(
                        status=SyncStatus.FAILED,
                        completed_at=now,
                        error_message=self.REAPED_JOB_MESSAGE,
                    )
                )
                await session.execute(
                    update(Mirror)
                    .where(Mirror.id == job.mirror_id)
                    .where(Mirror.status == MirrorStatus.SYNCING)
                    .values(
                        status=MirrorStatus.ERROR,
                        last_sync_error=self.REAPED_JOB_MESSAGE,
                    )
                )
                reaped += 1

                # Elapsed time does not decide anything, but a reap of
                # something that had been running for hours is worth being
                # loud about: if this service ever gets a job 615 wrong, the
                # operator should find it in the log rather than in the size
                # of the mirror.
                elapsed = verdict.elapsed_seconds
                log = logger.info
                if elapsed is not None and elapsed >= LONG_RUNNING_REAP_WARN_SECONDS:
                    log = logger.warning
                log(
                    "Reaped orphaned sync job",
                    job_id=job.id,
                    mirror_id=job.mirror_id,
                    trigger=trigger,
                    reason=verdict.reason,
                    elapsed_seconds=elapsed,
                )

            # Step 2. A mirror still claiming to sync with nothing running it.
            # Recomputed from the database after the updates above, so a mirror
            # this process is genuinely syncing is excluded by the same fact
            # that protects its job: its job row still says RUNNING.
            still_running = await session.execute(
                select(SyncJob.mirror_id).where(SyncJob.status == SyncStatus.RUNNING)
            )
            busy_mirror_ids = set(still_running.scalars().all())

            stuck = await session.execute(
                select(Mirror).where(Mirror.status == MirrorStatus.SYNCING)
            )
            for mirror in stuck.scalars().all():
                if mirror.id in busy_mirror_ids:
                    continue
                await session.execute(
                    update(Mirror)
                    .where(Mirror.id == mirror.id)
                    .values(
                        status=MirrorStatus.ERROR,
                        last_sync_error=self.REAPED_JOB_MESSAGE,
                    )
                )
                logger.warning(
                    "Cleared mirror stuck in SYNCING with no running job",
                    mirror_id=mirror.id,
                    mirror=mirror.name,
                    trigger=trigger,
                )

            await session.commit()

        return reaped

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
                local_path=mirror.local_path,
                mirror_type=mirror.mirror_type,
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
                local_path=mirror.local_path,
                mirror_type=mirror.mirror_type,
            )

    def _next_scheduled_run(self, base: datetime) -> datetime:
        """The next fire time for self.sync_schedule, falling back if it cannot.

        This is the last line of defence on the wedge. croniter() used to be
        called inline in the loop below, inside the try block, so an unusable
        schedule raised, hit the generic handler, and put the whole loop into a
        ten-second retry that never polled a job or ran a sync -- with the
        scheduler broken by a string an operator typed into a text box.

        Both earlier layers can be bypassed. The API validates on write, but a
        row can be written by psql; reload_settings validates on read, but
        self.sync_schedule also comes from the SYNC_SCHEDULE environment
        variable, which nothing validates at all. So the value is checked once
        more at the point of use, and an unusable one is replaced by the seeded
        default instead of taking the service down. A mirror syncing at 04:00
        when someone meant 03:00 is a wrong schedule; a mirror that never syncs
        again is an outage.
        """
        try:
            return croniter(self.sync_schedule, base).get_next(datetime)
        except Exception as exc:
            logger.error(
                "Unusable sync schedule, falling back to the default",
                rejected=self.sync_schedule,
                fallback=DEFAULT_SYNC_SCHEDULE,
                error=str(exc),
            )
            self.sync_schedule = DEFAULT_SYNC_SCHEDULE
            return croniter(DEFAULT_SYNC_SCHEDULE, base).get_next(datetime)

    async def scheduler_loop(self) -> None:
        """Main scheduler loop — polls for pending jobs every POLL_INTERVAL seconds
        and runs scheduled syncs at the configured cron schedule."""
        next_run = self._next_scheduled_run(datetime.now())
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
                if poll_count % SETTINGS_RELOAD_INTERVAL_CYCLES == 0:
                    old_schedule = self.sync_schedule
                    await self.reload_settings()
                    # If schedule changed, recalculate next run
                    if self.sync_schedule != old_schedule:
                        logger.info("Sync schedule changed", old=old_schedule, new=self.sync_schedule)
                        next_run = self._next_scheduled_run(datetime.now())
                        logger.info("Next scheduled sync recalculated", next_run=next_run.isoformat())

                # Reap jobs abandoned by a process that is no longer running
                # them. Also done once at startup, which is where a crash's
                # orphans get cleared; this pass exists for the case the
                # startup one cannot reach -- a job stranded while this process
                # kept running, e.g. an exception between marking it RUNNING
                # and marking it finished. Without it that job would need a
                # container restart to clear.
                if poll_count % REAP_INTERVAL_CYCLES == 0:
                    await self.reap_orphaned_jobs(trigger="scheduler")

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
                    next_run = self._next_scheduled_run(datetime.now())
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

        # Wait for the database to be ready -- CONNECTION *AND* SCHEMA.
        #
        # This used to check only `select(1)`. Postgres accepts connections as
        # soon as it is up, which is well before Alembic has created anything,
        # so on a fresh install the loop broke out immediately and the next two
        # calls ran against an empty database: reload_settings swallowed
        # `relation "settings" does not exist` at debug level and
        # poll_pending_jobs logged it as a warning. A genuine error, once per
        # boot, that everyone learned to scroll past.
        #
        # to_regclass returns NULL rather than raising for a missing relation,
        # so this is a question and not an exception handler. It is the same
        # check backend/app/core/database.py:init_db() makes, deliberately.
        schema_ready = False
        for i in range(30):
            try:
                async with self.engine.connect() as conn:
                    await conn.execute(select(1))
                    present = await conn.scalar(
                        text("SELECT to_regclass('public.alembic_version')")
                    )
                if present is not None:
                    schema_ready = True
                    break
                logger.info("Database is up; waiting for migrations", attempt=i + 1)
            except Exception:
                logger.info("Waiting for database...", attempt=i + 1)
            await asyncio.sleep(2)

        if not schema_ready:
            # Deliberately NOT fatal here, unlike the backend, which refuses to
            # start. This service serves no HTTP contract, its health server is
            # already listening, and the scheduler loop retries on its own. The
            # thing that was missing is the actionable message, not an exit.
            logger.error(
                "No alembic_version table after 60s; the schema this service "
                "needs may not exist. Fresh install: scripts/migrate.sh upgrade. "
                "Existing database: scripts/migrate.sh adopt."
            )

        # Load settings from database
        await self.reload_settings()

        # Clear jobs abandoned by the previous incarnation of this process.
        #
        # This is the moment the reaper is most obviously right: a process that
        # has just started owns no jobs, so every RUNNING row in the table
        # belongs to a process that is gone. Nothing here is a judgement call.
        #
        # It must run BEFORE poll_pending_jobs, or a mirror stuck in SYNCING
        # from the crash stays stuck for the whole first cycle.
        #
        # What this does not cover: a container that dies and never comes back.
        # Nothing inside the sync service can fix that -- compose's
        # `restart: unless-stopped` is what brings it back after a crash, and
        # if the host is down or the image will not start, no code in this file
        # runs at all. That case needs an external watchdog, not a reaper.
        try:
            reaped = await self.reap_orphaned_jobs(trigger="startup")
            if reaped:
                logger.warning("Reaped orphaned sync jobs on startup", count=reaped)
        except Exception as e:
            logger.warning("Could not reap orphaned jobs on startup", error=str(e))

        # Process any pending jobs on startup
        try:
            pending = await self.poll_pending_jobs()
            if pending > 0:
                logger.info("Processed pending jobs on startup", count=pending)
        except Exception as e:
            logger.warning("Could not poll pending jobs on startup (tables may not exist yet)", error=str(e))

        # Run initial sync on startup (optional).
        #
        # Reads self.sync_on_startup, which reload_settings has just populated
        # from the `sync_on_startup` settings row, falling back to the
        # SYNC_ON_STARTUP environment variable. This used to read the
        # environment variable directly, so the admin panel's dropdown wrote a
        # validated row that nothing ever consulted.
        #
        # Order matters and is already correct: reload_settings() runs above,
        # so a row set through the UI wins over the env default on this boot,
        # not the next one.
        if self.sync_on_startup:
            logger.info("Running initial sync on startup", source="settings")
            await self.run_scheduled_sync()

        # Start scheduler
        await self.scheduler_loop()

        await self.engine.dispose()
        logger.info("Sync service stopped")


if __name__ == "__main__":
    service = SyncService()
    asyncio.run(service.run())
