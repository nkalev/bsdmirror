"""Validation for the rows in the `settings` table.

Four keys are seeded by the backend's lifespan (backend/app/main.py) and read
back by the sync service (sync/sync_service.py). Until now nothing checked what
went into them: PATCH /api/admin/settings accepted `dict[str, str]` and wrote
any string to any existing key.

That was not a cosmetic gap. `sync_schedule` is fed to `croniter()` inside
`scheduler_loop`'s try block; a malformed value raises, the generic handler
catches it, and the loop retries every POLL_INTERVAL seconds forever -- never
syncing, and logging an error each time. `sync_timeout` and
`sync_bandwidth_limit` were parsed with `int()` under a bare `except ValueError:
pass`, so garbage silently kept the previous value with no record that it had
been ignored.

This module lives in shared/ rather than in backend/app/ because the service
that *validates* a value is not the service that *uses* it. The API is one way
a row gets written; a psql session is another, a restore from an older dump is
a third. So the same spec is imported by both sides:

    backend/app/api/admin.py   rejects a bad value at the write boundary (422)
    sync/sync_service.py       refuses to adopt a bad value it reads back

Nothing here imports from `app.*` or from `sync_service`, per shared/__init__.py.
croniter is pinned at 2.0.1 in *both* backend/requirements.txt and
sync/requirements.txt, so it is available to both importers.

------------------------------------------------------------------------------
Why these bounds, and not just "whatever parses"

A value can be perfectly parseable and still break every sync. `sync_timeout=1`
is a valid integer and a guaranteed failure. The bounds below are derived from
the shape of a real run -- production job 615, a 2.58 TB OpenBSD sync of
567,277 files over 15h43m -- not from what `int()` happens to accept.
"""
from datetime import datetime
from typing import Any, Callable, Dict, NamedTuple

from croniter import croniter

# --------------------------------------------------------------------------
# Defaults. These are the values backend/app/main.py seeds, restated here so
# the sync service has something known-good to fall back to without importing
# the backend.
# --------------------------------------------------------------------------
DEFAULT_SYNC_SCHEDULE = "0 4 * * *"
DEFAULT_SYNC_BANDWIDTH_LIMIT = 0
DEFAULT_SYNC_TIMEOUT = 600
DEFAULT_SYNC_ON_STARTUP = False

# --------------------------------------------------------------------------
# Bounds
# --------------------------------------------------------------------------

# rsync --timeout, in seconds. It is an *I/O inactivity* timeout, not a wall
# clock on the run, so the floor has to clear the quiet phases of a healthy
# transfer rather than the transfer itself.
#
# Job 615 reports "File list generation time: 3.221 seconds" -- 3.2 s during
# which not one byte moves -- and it runs with --delay-updates and
# --delete-delay, whose rename and unlink passes over 567,277 files at the end
# of the run are quieter and longer still. 60 s is the smallest value that
# leaves room for those, and it is still a tenth of the 600 s default, which
# remains the recommendation.
MIN_SYNC_TIMEOUT = 60

# 24 hours. Past this the timeout can no longer fire inside a daily schedule
# window, so it has stopped being a timeout. It also catches the obvious typo
# of entering milliseconds (600000).
MAX_SYNC_TIMEOUT = 86_400

# rsync --bwlimit, in KB/s. 0 is rsync's documented "unlimited" and is the
# seeded default, so it is allowed explicitly rather than as a boundary case.
BANDWIDTH_UNLIMITED = 0

# Job 615's file list is 14,286,848 bytes ("File list size"). At 128 KB/s that
# list alone takes ~112 s to cross the wire before a single file is
# transferred; at 8 KB/s it takes ~29 minutes, which is longer than the default
# --timeout, so the sync would abort on its own file list. 128 KB/s is roughly
# where a limit throttles a transfer instead of killing it.
MIN_SYNC_BANDWIDTH_LIMIT = 128

# 10 GB/s. Above any link this will ever run on; it exists to catch a value
# entered in bytes or bits rather than KB.
MAX_SYNC_BANDWIDTH_LIMIT = 10_000_000

# Accepted spellings for sync_on_startup. The admin UI's <select> only ever
# sends "true"/"false", but the row is also editable by hand. Anything outside
# this table is rejected rather than silently read as false, which is what
# `.lower() == "true"` did with every typo.
_TRUE_WORDS = frozenset({"true", "1", "yes", "on", "enabled"})
_FALSE_WORDS = frozenset({"false", "0", "no", "off", "disabled"})


# Any fixed, unambiguous instant works. Chosen away from a month boundary, a
# DST transition and a leap day so no expression is judged against an edge case.
_CRON_VALIDATION_BASE = datetime(2026, 6, 15, 12, 0, 0)


class SettingError(ValueError):
    """A setting value that is syntactically parseable but not usable.

    Subclasses ValueError so a pydantic field_validator can raise it directly
    and FastAPI turns it into a 422.
    """


class UnknownSettingKey(KeyError):
    """A key that is not one of the four seeded settings."""


def _parse_sync_schedule(raw: str) -> str:
    """Validate by doing exactly what the scheduler does.

    Not `croniter.is_valid()`: is_valid is a try/except around construction, and
    the operation that actually wedges scheduler_loop is
    `croniter(schedule, base).get_next(datetime)`. Validating the real call
    means a value that constructs but cannot advance -- were croniter ever to
    grow one -- is rejected here rather than discovered at 04:00.

    A fixed base date keeps this a pure function: the same string always gets
    the same verdict, so a value cannot be accepted on Tuesday and rejected on
    Wednesday.
    """
    value = raw.strip()
    if not value:
        raise SettingError("sync_schedule: must not be empty")
    try:
        croniter(value, _CRON_VALIDATION_BASE).get_next(datetime)
    except Exception as exc:
        raise SettingError(
            f"sync_schedule: {value!r} is not a usable cron expression "
            f"({exc}). Expected five fields -- minute hour day month weekday -- "
            f"for example {DEFAULT_SYNC_SCHEDULE!r} for daily at 04:00."
        ) from exc
    return value



def _parse_int(key: str, raw: str) -> int:
    value = raw.strip()
    try:
        return int(value)
    except ValueError as exc:
        raise SettingError(f"{key}: {raw!r} is not a whole number") from exc


def _parse_sync_timeout(raw: str) -> int:
    seconds = _parse_int("sync_timeout", raw)
    if seconds < MIN_SYNC_TIMEOUT or seconds > MAX_SYNC_TIMEOUT:
        raise SettingError(
            f"sync_timeout: {seconds} is out of range. rsync --timeout is an "
            f"I/O inactivity timeout in seconds and must be between "
            f"{MIN_SYNC_TIMEOUT} and {MAX_SYNC_TIMEOUT} "
            f"(default {DEFAULT_SYNC_TIMEOUT}). 0 would disable the timeout "
            f"entirely, which is what leaves a hung transfer running forever."
        )
    return seconds


def _parse_sync_bandwidth_limit(raw: str) -> int:
    kbps = _parse_int("sync_bandwidth_limit", raw)
    if kbps == BANDWIDTH_UNLIMITED:
        return BANDWIDTH_UNLIMITED
    if kbps < MIN_SYNC_BANDWIDTH_LIMIT or kbps > MAX_SYNC_BANDWIDTH_LIMIT:
        raise SettingError(
            f"sync_bandwidth_limit: {kbps} is out of range. rsync --bwlimit is "
            f"in KB/s; use 0 for unlimited, otherwise "
            f"{MIN_SYNC_BANDWIDTH_LIMIT}-{MAX_SYNC_BANDWIDTH_LIMIT}. Below "
            f"{MIN_SYNC_BANDWIDTH_LIMIT} KB/s a full mirror cannot even "
            f"transfer its own file list before --timeout fires."
        )
    return kbps


def _parse_sync_on_startup(raw: str) -> bool:
    value = raw.strip().lower()
    if value in _TRUE_WORDS:
        return True
    if value in _FALSE_WORDS:
        return False
    raise SettingError(
        f"sync_on_startup: {raw!r} is not a boolean. Use 'true' or 'false'. "
        f"It used to be compared with `.lower() == \"true\"`, so a typo like "
        f"'ture' was silently read as false."
    )


def _render_bool(value: bool) -> str:
    return "true" if value else "false"


class SettingSpec(NamedTuple):
    """How one settings row is validated and stored.

    parse   str -> typed value, raising SettingError on anything unusable.
    render  typed value -> the canonical string written to the column.

    Round-tripping through render is what makes storage canonical: '  0 4 * * * '
    and 'TRUE' and '0600' become '0 4 * * *', 'true' and '600'. The sync service
    compares the schedule string it read last time against the one it just read
    to decide whether to recompute the next run; without canonicalisation a
    stray space reads as a change.
    """

    parse: Callable[[str], Any]
    render: Callable[[Any], str]
    default: Any
    description: str


SETTING_SPECS: Dict[str, SettingSpec] = {
    "sync_schedule": SettingSpec(
        parse=_parse_sync_schedule,
        render=str,
        default=DEFAULT_SYNC_SCHEDULE,
        description="Cron schedule for automatic mirror synchronization",
    ),
    "sync_bandwidth_limit": SettingSpec(
        parse=_parse_sync_bandwidth_limit,
        render=str,
        default=DEFAULT_SYNC_BANDWIDTH_LIMIT,
        description="Rsync bandwidth limit in KB/s (0 = unlimited)",
    ),
    "sync_timeout": SettingSpec(
        parse=_parse_sync_timeout,
        render=str,
        default=DEFAULT_SYNC_TIMEOUT,
        description="Rsync timeout in seconds",
    ),
    "sync_on_startup": SettingSpec(
        parse=_parse_sync_on_startup,
        render=_render_bool,
        default=DEFAULT_SYNC_ON_STARTUP,
        description="Run full sync when sync service starts",
    ),
}

SETTING_KEYS = frozenset(SETTING_SPECS)


def parse_setting(key: str, raw: str) -> Any:
    """Typed value for `key`, or SettingError. Unknown key -> UnknownSettingKey."""
    try:
        spec = SETTING_SPECS[key]
    except KeyError as exc:
        raise UnknownSettingKey(key) from exc
    if raw is None:
        raise SettingError(f"{key}: must not be null")
    return spec.parse(raw)


def canonical_setting(key: str, raw: str) -> str:
    """The exact string to store for `key`, or SettingError.

    Callers that write the row should write *this*, not the string they were
    given, so what comes back out of the database is what the parser produced.
    """
    try:
        spec = SETTING_SPECS[key]
    except KeyError as exc:
        raise UnknownSettingKey(key) from exc
    return spec.render(spec.parse(raw))


def validate_settings(values: Dict[str, str]) -> Dict[str, str]:
    """Validate a whole batch, reporting *every* bad value rather than the first.

    Returns {key: canonical string} for the whole batch, or raises SettingError
    with one message per rejected key. All-or-nothing on purpose: the caller
    applies the returned dict, so there is no path on which half a batch lands.

    Unknown keys are passed through untouched -- their existence is a database
    question (they get a 404 from the route), not a value question.
    """
    canonical: Dict[str, str] = {}
    problems = []
    for key, raw in values.items():
        if key not in SETTING_SPECS:
            continue
        try:
            canonical[key] = canonical_setting(key, raw)
        except SettingError as exc:
            problems.append(str(exc))
    if problems:
        raise SettingError("; ".join(problems))
    return canonical
