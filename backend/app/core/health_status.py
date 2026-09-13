"""
Last-run view over the hourly health-check script's status file.

scripts/health_check.sh (systemd timer: scripts/systemd/bsdmirror-health.timer;
both owned by devops-sre) is the process that actually looks at this
deployment -- API reachability, mirror staleness, disk headroom, container
health -- and alerts Discord on a transition. Nothing before this endpoint
showed whether that script was still running at all: a quiet Discord channel
is the only "all clear" today, and silence is exactly the failure mode the
script exists to catch (see 2026-07-02 / 58 silent nights in that script's own
header). GET /api/admin/health-checks is that visibility, built from the JSON
file the script writes on every run and this backend reads through a
read-only bind mount at settings.HEALTH_STATUS_FILE.

This is not app.api.health (this process's own liveness) and not
app.core.disk (free space on the mirror volume) -- it is a report ABOUT a
process that runs outside this container, on a schedule this container does
not control, so the file can be missing, stale, or simply wrong in ways a
normal API input never is. Three layers, each pure except the one that has to
touch a filesystem:

  read_health_status_document   Blocking: stat, read, UTF-8 decode, JSON
                                 decode, and the full schema-1 shape check.
                                 Never raises -- every failure comes back as
                                 (None, reason). Run through asyncio.to_thread
                                 by get_health_status_view, never awaited
                                 directly from a coroutine (see
                                 tests/test_async_hygiene.py, which knows this
                                 function's name the same way it already knows
                                 app.core.disk.read_disk_usage's).
  _validate_document             Pure. Checks every field schema 1 promises,
                                 by name and by type, and fails CLOSED: one
                                 wrong type anywhere is "the file is
                                 unusable", never a best-effort partial read.
  build_health_status_view      Pure. unknown (missing, unusable, or
                                 clock-skewed) is decided here directly, from
                                 `now` and `finished_epoch`; stale/failing/
                                 incomplete/ok is delegated to _STATE_RULES,
                                 an explicit, ordered table -- first match
                                 wins -- rather than an if/elif chain, so a
                                 test can mutate the table itself (remove or
                                 reorder a named entry) to prove the order is
                                 load-bearing, without needing to re-parse or
                                 re-execute this module's own source to do it.
                                 The view must never say "ok" on a
                                 technicality when an earlier rule already
                                 disqualifies it.

Every string that ends up in the response was written by a script running on
a production host, not typed by an operator through this API -- but it is
still untrusted from this process's point of view (a bug in the script, or a
compromised host, could put anything in that file), so every list is capped
at MAX_LIST_ITEMS and every string at MAX_STRING_LENGTH on the way out. The
endpoint itself never raises: an unreadable, oversized or malformed file is
state "unknown", not a 500, because the one thing worse than "I do not know
whether the health check ran" is a broken dashboard.
"""
import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

# 1 MiB. A schema-1 report today (six checks, no skips) is under 1 KB; a file
# anywhere near this limit was not written by health_check.sh, and reading an
# unbounded file into memory on every dashboard poll is its own hazard.
MAX_FILE_BYTES = 1024 * 1024

# scripts/systemd/bsdmirror-health.timer: OnCalendar=hourly with
# RandomizedDelaySec=5m. A run that is simply late is at most ~65 minutes
# after the previous one; ONE MISSED run followed by a normally-delayed next
# one is at most 60 + 60 + 5 = 125 minutes between two successful finishes.
# 7800s (130 min) is that plus a small margin, not a guess -- see the timer
# unit's own comment for the schedule this derives from.
STALE_AFTER_SECONDS = 130 * 60

# How far into the future finished_epoch may claim to be before this is a
# clock problem between hosts rather than a real result.
MAX_CLOCK_SKEW_SECONDS = 300

MAX_LIST_ITEMS = 50
MAX_STRING_LENGTH = 500

SUPPORTED_SCHEMA = 1


# ---------------------------------------------------------------------------
# Schema 1 validation -- pure, no IO.
# ---------------------------------------------------------------------------


def _is_int(value: Any) -> bool:
    """True for a JSON integer. bool is a subclass of int in Python, and
    schema 1 has no boolean-shaped integer field, so True/False are always
    wrong here."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_str(value: Any) -> bool:
    return isinstance(value, str)


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(_is_str(item) for item in value)


def _validate_document(doc: Any) -> Optional[str]:
    """None if `doc` matches schema 1 exactly -- every field present and of
    the right type; otherwise a reason naming what was wrong.

    Fails on the FIRST problem found rather than collecting every one (the
    caller only ever shows one reason), checked in the order the fields
    appear in the schema so the reason for a given bad input is stable.
    json.loads already proves the bytes were valid JSON; this is the shape
    check beyond that.
    """
    if not isinstance(doc, dict):
        return "health-status file does not contain a JSON object"

    if doc.get("schema") != SUPPORTED_SCHEMA:
        return "health-status file has an unsupported schema version"

    if not _is_str(doc.get("finished_at")):
        return "health-status file is missing a valid 'finished_at' timestamp"

    if not _is_int(doc.get("finished_epoch")):
        return "health-status file is missing a valid 'finished_epoch' timestamp"

    counts = doc.get("counts")
    if (
        not isinstance(counts, dict)
        or not _is_int(counts.get("ok"))
        or not _is_int(counts.get("bad"))
    ):
        return "health-status file has an invalid 'counts' section"

    if not _is_str_list(doc.get("ok")):
        return "health-status file has an invalid 'ok' list"

    bad = doc.get("bad")
    if not isinstance(bad, list) or not all(
        isinstance(item, dict)
        and _is_str(item.get("key"))
        and _is_str(item.get("label"))
        and _is_str(item.get("detail"))
        for item in bad
    ):
        return "health-status file has an invalid 'bad' list"

    skipped = doc.get("skipped")
    if not isinstance(skipped, list) or not all(
        isinstance(item, dict) and _is_str(item.get("check")) and _is_str(item.get("reason"))
        for item in skipped
    ):
        return "health-status file has an invalid 'skipped' list"

    if not _is_str_list(doc.get("warnings")):
        return "health-status file has an invalid 'warnings' list"

    alerting = doc.get("alerting")
    if (
        not isinstance(alerting, dict)
        or not _is_str_list(alerting.get("channels"))
        or not _is_str(alerting.get("notification"))
    ):
        return "health-status file has an invalid 'alerting' section"

    if not isinstance(doc.get("state_persisted"), bool):
        return "health-status file is missing a valid 'state_persisted' flag"

    return None


# ---------------------------------------------------------------------------
# Blocking file IO -- run through asyncio.to_thread, never awaited directly.
# ---------------------------------------------------------------------------


# Exceptions json.loads can raise on adversarial input that still just mean
# "this file is not valid JSON", not a bug in this module: JSONDecodeError
# for ordinary syntax errors, RecursionError for pathologically deep nesting
# (e.g. "[" * 100_000 + "]" * 100_000 -- a couple hundred KB, comfortably
# under MAX_FILE_BYTES, but enough nesting that CPython's recursive-descent
# JSON parser blows the interpreter's recursion limit), and ValueError for
# anything else json.loads documents itself as raising. A prior version of
# this module caught only JSONDecodeError, so the RecursionError case above
# escaped read_health_status_document entirely and turned into a 500 -- see
# tests/test_admin_health_checks.py for the case and its mutation-check.
_JSON_PARSE_ERRORS: tuple = (json.JSONDecodeError, RecursionError, ValueError)


def _parse_json(
    text: str, recoverable: tuple = _JSON_PARSE_ERRORS
) -> tuple[Optional[Any], Optional[str]]:
    """json.loads(text), turning every exception in `recoverable` into
    (None, reason) rather than letting it propagate.

    `recoverable` is a seam for tests only: production code always calls
    this with the default tuple, and passing a narrower one exercises this
    exact function, unmodified -- see _evaluate_state's `rules` parameter
    for the same technique.
    """
    try:
        return json.loads(text), None
    except recoverable:
        return None, "health-status file is not valid JSON"


def read_health_status_document(path: str) -> tuple[Optional[dict], Optional[str]]:
    """Blocking: stats, reads and JSON-decodes `path`. Never raises -- every
    failure this function can hit (missing file, unreadable, too large, not
    UTF-8, not valid JSON, not a JSON object, wrong schema, any field missing
    or the wrong type) comes back as (None, reason) instead, because the
    caller's job is to render an "unknown" card, not a 500.

    Run this through asyncio.to_thread (see get_health_status_view), never
    awaited directly from a coroutine -- see the module docstring and
    tests/test_async_hygiene.py, which knows this function's name.
    """
    try:
        size = os.path.getsize(path)
    except FileNotFoundError:
        return None, (
            "no health-check report found yet -- the systemd timer may not be "
            "installed, may not have run yet, or the health-status directory "
            "is not mounted"
        )
    except OSError as exc:
        logger.warning("Health status file could not be statted", path=path, error=str(exc))
        return None, "health-status file could not be read"

    if size > MAX_FILE_BYTES:
        return None, "health-status file is larger than 1 MiB"

    # Capped at MAX_FILE_BYTES + 1, not read() unbounded: the getsize() gate
    # above is a fast-path optimisation against the common case, not the only
    # defence -- a file that grows between the stat and this read (a
    # concurrent writer, or a getsize() that lied) must still be caught here
    # rather than read into memory without a limit.
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_FILE_BYTES + 1)
    except OSError as exc:
        logger.warning("Health status file could not be read", path=path, error=str(exc))
        return None, "health-status file could not be read"

    if len(raw) > MAX_FILE_BYTES:
        return None, "health-status file is larger than 1 MiB"

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, "health-status file is not valid JSON"

    doc, reason = _parse_json(text)
    if reason is not None:
        return None, reason

    reason = _validate_document(doc)
    if reason is not None:
        return None, reason

    return doc, None


# ---------------------------------------------------------------------------
# The state machine -- pure, no IO. Takes exactly what
# read_health_status_document (or a test) hands back.
# ---------------------------------------------------------------------------


def _cap_string(value: str) -> str:
    return value[:MAX_STRING_LENGTH]


def _cap_str_list(items: list) -> list:
    return [_cap_string(item) for item in items[:MAX_LIST_ITEMS]]


def _cap_bad_list(items: list) -> list:
    return [
        {
            "key": _cap_string(item["key"]),
            "label": _cap_string(item["label"]),
            "detail": _cap_string(item["detail"]),
        }
        for item in items[:MAX_LIST_ITEMS]
    ]


def _cap_skipped_list(items: list) -> list:
    return [
        {"check": _cap_string(item["check"]), "reason": _cap_string(item["reason"])}
        for item in items[:MAX_LIST_ITEMS]
    ]


def _unknown(reason: str) -> dict:
    """The shape for states 1-3: lists empty, everything else null EXCEPT
    stale_after_seconds, which is a fixed configuration value rather than
    anything read from the file, and stays meaningful even when the file
    could not be used at all."""
    return {
        "state": "unknown",
        "reason": reason,
        "finished_at": None,
        "age_seconds": None,
        "stale_after_seconds": STALE_AFTER_SECONDS,
        "counts": None,
        "ok": [],
        "bad": [],
        "skipped": [],
        "warnings": [],
        "alerting": None,
        "state_persisted": None,
    }


def _reason_stale(doc: dict, age_seconds: int) -> str:
    return (
        f"last health check finished {age_seconds // 60} minutes ago, over "
        f"the {STALE_AFTER_SECONDS // 60}-minute threshold -- the hourly "
        "timer may have stopped running"
    )


def _reason_failing(doc: dict, age_seconds: int) -> str:
    bad = doc["bad"]
    labels = ", ".join(item["label"] for item in bad[:5])
    return f"{len(bad)} check{'s' if len(bad) != 1 else ''} failing: {labels}"


def _reason_skipped(doc: dict, age_seconds: int) -> str:
    skipped = doc["skipped"]
    checks = ", ".join(item["check"] for item in skipped[:5])
    return f"{len(skipped)} check{'s' if len(skipped) != 1 else ''} skipped: {checks}"


def _reason_no_channels(doc: dict, age_seconds: int) -> str:
    return "no alerting channels are configured"


def _reason_notification_failed(doc: dict, age_seconds: int) -> str:
    return "the last alert notification failed to send"


def _reason_no_oks(doc: dict, age_seconds: int) -> str:
    return "no checks reported ok"


# The state machine's own "first match wins" order, as an explicit, ordered
# table rather than an if/elif chain: a table is something a test can mutate
# directly (remove or reorder a named entry, see this module's tests) without
# needing to re-parse or re-execute this file's own source to prove the order
# is load-bearing.
#
#   1-2. unknown    (file missing / file unusable)    -- via `reason`, above
#                    _evaluate_state is ever called.
#   3.   unknown    (finished_epoch clock-skewed into the future) -- also
#                    handled above _evaluate_state, since it can only be
#                    decided from `now` and `finished_epoch`, not from a rule
#                    keyed only on `doc` and `age_seconds`.
#   4-6. this table, first match wins: stale, then failing, then each
#        incomplete reason in the order listed here.
#   7.   ok         (falls through _evaluate_state entirely)
_STATE_RULES: list[dict] = [
    {
        "name": "stale",
        "state": "stale",
        "predicate": lambda doc, age: age > STALE_AFTER_SECONDS,
        "reason": _reason_stale,
    },
    {
        "name": "failing",
        "state": "failing",
        "predicate": lambda doc, age: bool(doc["bad"]),
        "reason": _reason_failing,
    },
    {
        "name": "skipped",
        "state": "incomplete",
        "predicate": lambda doc, age: bool(doc["skipped"]),
        "reason": _reason_skipped,
    },
    {
        "name": "no_channels",
        "state": "incomplete",
        "predicate": lambda doc, age: not doc["alerting"]["channels"],
        "reason": _reason_no_channels,
    },
    {
        "name": "notification_failed",
        "state": "incomplete",
        "predicate": lambda doc, age: doc["alerting"]["notification"] == "failed",
        "reason": _reason_notification_failed,
    },
    {
        "name": "no_oks",
        "state": "incomplete",
        "predicate": lambda doc, age: doc["counts"]["ok"] < 1,
        "reason": _reason_no_oks,
    },
]


def _evaluate_state(doc: dict, age_seconds: int, rules: Optional[list] = None) -> tuple[str, str]:
    """The first rule in `rules` (default _STATE_RULES) whose predicate
    matches wins; falls through to "ok" if none do.

    `rules` is a seam for tests only: production code always calls this with
    the default, real table. A test that removes or reorders a named entry
    from a COPY of _STATE_RULES and passes it here is exercising this exact
    function, unmodified -- not a reimplementation of it that could drift
    from what ships.
    """
    for rule in _STATE_RULES if rules is None else rules:
        if rule["predicate"](doc, age_seconds):
            return rule["state"], rule["reason"](doc, age_seconds)
    return "ok", f"all {doc['counts']['ok']} checks passed"


def build_health_status_view(doc: Optional[dict], reason: Optional[str], now: datetime) -> dict:
    """The state machine GET /api/admin/health-checks reports.

    `doc` and `reason` are exactly what read_health_status_document (or a
    test) hands back: `reason` set means `doc` is None and every check below
    is skipped, so a file that could not be read or did not validate is
    unknown BEFORE anything about its content is inspected. See _STATE_RULES
    for the ordered stale/failing/incomplete decision and this module's
    tests for a mutation that breaks it on purpose.
    """
    if reason is not None:
        return _unknown(reason)

    now_epoch = now.timestamp()
    finished_epoch = doc["finished_epoch"]

    if finished_epoch > now_epoch + MAX_CLOCK_SKEW_SECONDS:
        return _unknown(
            "health-status file's timestamp is more than 5 minutes in the "
            "future; this looks like clock skew between hosts, not a real result"
        )

    age_seconds = max(0, round(now_epoch - finished_epoch))
    state, reason_text = _evaluate_state(doc, age_seconds)

    alerting = doc["alerting"]
    counts = doc["counts"]

    return {
        "state": state,
        "reason": reason_text,
        "finished_at": _cap_string(doc["finished_at"]),
        "age_seconds": age_seconds,
        "stale_after_seconds": STALE_AFTER_SECONDS,
        "counts": {"ok": counts["ok"], "bad": counts["bad"]},
        "ok": _cap_str_list(doc["ok"]),
        "bad": _cap_bad_list(doc["bad"]),
        "skipped": _cap_skipped_list(doc["skipped"]),
        "warnings": _cap_str_list(doc["warnings"]),
        "alerting": {
            "channels": _cap_str_list(alerting["channels"]),
            "notification": _cap_string(alerting["notification"]),
        },
        "state_persisted": doc["state_persisted"],
    }


async def get_health_status_view(path: str) -> dict:
    """Entry point admin.py calls. Offloads the blocking read to a worker
    thread (see read_health_status_document's docstring) and always returns
    a 200-shaped dict -- there is no exception path left for a caller to
    catch.

    The broad except below is a backstop, not the primary defence:
    read_health_status_document and build_health_status_view are each
    already supposed to turn every failure they know about into
    (None, reason) or a state, never a raise. This exists for whatever
    neither of them anticipated, so a bug in either one degrades this
    endpoint to "unknown" instead of a 500 -- and still shows up in the
    logs, with a traceback, for whoever has to fix it.
    """
    try:
        doc, reason = await asyncio.to_thread(read_health_status_document, path)
        return build_health_status_view(doc, reason, datetime.now(timezone.utc))
    except Exception:
        logger.error("Health status view failed unexpectedly", path=path, exc_info=True)
        return _unknown("an unexpected error occurred while checking the health-status file")
