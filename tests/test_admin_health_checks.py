"""
Last-run view over scripts/health_check.sh's status file: GET
/api/admin/health-checks (backend/app/core/health_status.py).

scripts/health_check.sh (systemd timer, devops-sre) is the process that
actually watches this deployment and alerts Discord on a transition. Until
this endpoint existed, nothing showed whether that script was still running
at all -- a quiet channel was the only "all clear", indistinguishable from
"the timer died". Every branch below exists because the file this endpoint
reads is written by a process outside this container, on a schedule this
container does not control, so it can be missing, stale, oversized or simply
wrong in ways a normal API input never is -- and the view must fail CLOSED
(toward "unknown"/"stale"/"incomplete") rather than ever reporting "ok" on a
technicality.

Organised the same way app.core.disk and its tests are:

  1. _validate_document       pure schema-1 shape check, no IO.
  2. read_health_status_document   blocking IO, proved against real files in
                                   tmp_path.
  3. build_health_status_view / _evaluate_state   pure state machine, proved
                                   with hand-built documents and a fixed
                                   clock, including a mutation of the
                                   ordered rules table that breaks the
                                   fail-closed order on purpose.
  4. get_health_status_view        the async wrapper, against real files.
  5. GET /api/admin/health-checks  end to end, including auth.
"""
import copy
import json
import time
from datetime import datetime, timezone

import pytest

from app.api import admin as admin_module
from app.core import health_status
from tests.conftest import auth_header

# ---------------------------------------------------------------------------
# Shared fixture-document builder
# ---------------------------------------------------------------------------


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _doc(
    *,
    finished_epoch=1_789_284_589,
    ok=("api responding (HTTP 200, status=healthy)",),
    bad=(),
    skipped=(),
    warnings=(),
    counts=None,
    alerting=None,
    state_persisted=True,
):
    """A fully valid schema-1 document. The default finished_epoch is the
    task contract's own example timestamp; every other field defaults to
    "fresh and clean" so a test only has to override what it is testing."""
    return {
        "schema": 1,
        "finished_at": _iso(finished_epoch),
        "finished_epoch": finished_epoch,
        "counts": counts if counts is not None else {"ok": len(ok), "bad": len(bad)},
        "ok": list(ok),
        "bad": list(bad),
        "skipped": list(skipped),
        "warnings": list(warnings),
        "alerting": (
            alerting if alerting is not None else {"channels": ["discord"], "notification": "none"}
        ),
        "state_persisted": state_persisted,
    }


# A fixed clock for every build_health_status_view test below, so "fresh",
# "stale" and "future" are exact, reproducible offsets rather than a race
# against the real clock.
NOW = datetime(2026, 9, 13, 8, 0, 0, tzinfo=timezone.utc)
NOW_EPOCH = int(NOW.timestamp())


# ---------------------------------------------------------------------------
# 1. _validate_document -- pure schema-1 shape check
# ---------------------------------------------------------------------------


def test_validate_document_accepts_a_fully_valid_schema_1_document():
    assert health_status._validate_document(_doc()) is None


def test_validate_document_accepts_the_literal_contract_example():
    """The exact JSON block from the task's own contract, not a paraphrase."""
    example = {
        "schema": 1,
        "finished_at": "2026-09-13T07:29:49Z",
        "finished_epoch": 1789284589,
        "counts": {"ok": 6, "bad": 0},
        "ok": ["api responding (HTTP 200, status=healthy)"],
        "bad": [
            {"key": "disk", "label": "disk", "detail": "/data/mirrors is 96% full, threshold 95%"}
        ],
        "skipped": [{"check": "containers", "reason": "docker not found on this host"}],
        "warnings": ["disk usage 86% on /data/mirrors (warn at 85%, alert at 95%)"],
        "alerting": {"channels": ["discord"], "notification": "none"},
        "state_persisted": True,
    }
    assert health_status._validate_document(example) is None


@pytest.mark.parametrize("bad_doc", [None, [], "not an object", 42, True, 3.14, ["a", "b"]])
def test_validate_document_rejects_anything_that_is_not_a_json_object(bad_doc):
    assert health_status._validate_document(bad_doc) is not None


_DELETE = object()  # sentinel: remove this key rather than set it to a value


def _apply_mutation(keypath: tuple, value) -> dict:
    doc = copy.deepcopy(_doc())
    target = doc
    for key in keypath[:-1]:
        target = target[key]
    if value is _DELETE:
        del target[keypath[-1]]
    else:
        target[keypath[-1]] = value
    return doc


# (description, keypath into a fresh _doc(), replacement value or _DELETE).
# Each case breaks exactly one field of an otherwise-valid document.
FIELD_MUTATIONS = [
    ("schema missing", ("schema",), _DELETE),
    ("schema wrong version", ("schema",), 2),
    ("schema wrong type", ("schema",), "1"),
    ("finished_at missing", ("finished_at",), _DELETE),
    ("finished_at wrong type", ("finished_at",), 12345),
    ("finished_epoch missing", ("finished_epoch",), _DELETE),
    ("finished_epoch wrong type", ("finished_epoch",), "12345"),
    ("finished_epoch is a bool, not an int", ("finished_epoch",), True),
    ("counts missing", ("counts",), _DELETE),
    ("counts is not an object", ("counts",), [6, 0]),
    ("counts.ok missing", ("counts", "ok"), _DELETE),
    ("counts.ok wrong type", ("counts", "ok"), "6"),
    ("counts.bad missing", ("counts", "bad"), _DELETE),
    ("counts.bad wrong type", ("counts", "bad"), "0"),
    ("ok missing", ("ok",), _DELETE),
    ("ok is not a list", ("ok",), "api ok"),
    ("ok contains a non-string item", ("ok",), [1]),
    ("bad missing", ("bad",), _DELETE),
    ("bad is not a list", ("bad",), {}),
    ("bad item missing key", ("bad",), [{"label": "disk", "detail": "full"}]),
    ("bad item missing label", ("bad",), [{"key": "disk", "detail": "full"}]),
    ("bad item missing detail", ("bad",), [{"key": "disk", "label": "disk"}]),
    ("bad item has a non-string detail", ("bad",), [{"key": "disk", "label": "disk", "detail": 1}]),
    ("skipped missing", ("skipped",), _DELETE),
    ("skipped is not a list", ("skipped",), {}),
    ("skipped item missing check", ("skipped",), [{"reason": "no docker"}]),
    ("skipped item missing reason", ("skipped",), [{"check": "containers"}]),
    ("warnings missing", ("warnings",), _DELETE),
    ("warnings is not a list", ("warnings",), "disk high"),
    ("warnings contains a non-string item", ("warnings",), [1]),
    ("alerting missing", ("alerting",), _DELETE),
    ("alerting is not an object", ("alerting",), ["discord"]),
    ("alerting.channels missing", ("alerting", "channels"), _DELETE),
    ("alerting.channels contains a non-string item", ("alerting", "channels"), [1]),
    ("alerting.notification missing", ("alerting", "notification"), _DELETE),
    ("alerting.notification wrong type", ("alerting", "notification"), 1),
    ("state_persisted missing", ("state_persisted",), _DELETE),
    ("state_persisted wrong type", ("state_persisted",), "true"),
]


@pytest.mark.parametrize(
    "description,keypath,value", FIELD_MUTATIONS, ids=[c[0] for c in FIELD_MUTATIONS]
)
def test_validate_document_rejects_every_broken_field(description, keypath, value):
    reason = health_status._validate_document(_apply_mutation(keypath, value))
    assert reason is not None, f"{description}: validator accepted a broken document"


def test_field_mutation_table_actually_covers_every_top_level_field():
    """Guards the guard: every key _doc() writes must be exercised by at
    least one row above, or a future field could go unchecked silently."""
    covered = {keypath[0] for _, keypath, _ in FIELD_MUTATIONS}
    assert covered == set(_doc().keys())


# ---------------------------------------------------------------------------
# 2. read_health_status_document -- blocking IO, against real files
# ---------------------------------------------------------------------------


def test_read_health_status_document_missing_file(tmp_path):
    doc, reason = health_status.read_health_status_document(str(tmp_path / "absent.json"))
    assert doc is None
    assert reason.startswith("no health-check report found yet")


def test_read_health_status_document_a_directory_is_unreadable_not_an_exception(tmp_path):
    path = tmp_path / "status.json"
    path.mkdir()
    doc, reason = health_status.read_health_status_document(str(path))
    assert doc is None
    assert reason == "health-status file could not be read"


def test_read_health_status_document_empty_file(tmp_path):
    path = tmp_path / "status.json"
    path.write_text("")
    doc, reason = health_status.read_health_status_document(str(path))
    assert doc is None
    assert reason == "health-status file is not valid JSON"


def test_read_health_status_document_invalid_json_syntax(tmp_path):
    path = tmp_path / "status.json"
    path.write_text("{not json")
    doc, reason = health_status.read_health_status_document(str(path))
    assert doc is None
    assert reason == "health-status file is not valid JSON"


def test_read_health_status_document_not_utf8(tmp_path):
    path = tmp_path / "status.json"
    path.write_bytes(b"\xff\xfe\x00\x01")
    doc, reason = health_status.read_health_status_document(str(path))
    assert doc is None
    assert reason == "health-status file is not valid JSON"


@pytest.mark.parametrize("payload", ["[]", "42", "true", "null", '"just a string"'])
def test_read_health_status_document_valid_json_but_not_an_object(tmp_path, payload):
    path = tmp_path / "status.json"
    path.write_text(payload)
    doc, reason = health_status.read_health_status_document(str(path))
    assert doc is None
    assert reason == "health-status file does not contain a JSON object"


def test_read_health_status_document_schema_2_is_unusable(tmp_path):
    path = tmp_path / "status.json"
    broken = _doc()
    broken["schema"] = 2
    path.write_text(json.dumps(broken))
    doc, reason = health_status.read_health_status_document(str(path))
    assert doc is None
    assert reason == "health-status file has an unsupported schema version"


def test_read_health_status_document_oversized_file_is_rejected(tmp_path):
    path = tmp_path / "status.json"
    # Content need not be valid JSON: the size check happens before anything
    # is parsed, so an oversized file is rejected without ever reading it.
    path.write_bytes(b"x" * (health_status.MAX_FILE_BYTES + 1))
    doc, reason = health_status.read_health_status_document(str(path))
    assert doc is None
    assert reason == "health-status file is larger than 1 MiB"


def test_read_health_status_document_exactly_at_the_size_limit_is_read(tmp_path):
    """Larger than 1 MiB is unusable; AT 1 MiB is not."""
    body = json.dumps(_doc())
    padding = " " * (health_status.MAX_FILE_BYTES - len(body))  # trailing JSON whitespace
    path = tmp_path / "status.json"
    path.write_text(body + padding)
    assert path.stat().st_size == health_status.MAX_FILE_BYTES

    doc, reason = health_status.read_health_status_document(str(path))
    assert reason is None
    assert doc == _doc()


def test_read_health_status_document_returns_the_parsed_document_on_success(tmp_path):
    path = tmp_path / "status.json"
    path.write_text(json.dumps(_doc()))
    doc, reason = health_status.read_health_status_document(str(path))
    assert reason is None
    assert doc == _doc()


def test_read_health_status_document_bounded_read_catches_a_file_that_outgrew_getsize(
    tmp_path, monkeypatch
):
    """The os.path.getsize gate is a fast-path optimisation, not the only
    defence against an oversized file: appsec review finding. A real file
    larger than the cap must still be rejected even when getsize -- a
    separate stat call, taken slightly earlier -- reports a small size (a
    concurrent writer growing the file between the two calls, or simply a
    getsize implementation that lied), because the actual read is bounded to
    MAX_FILE_BYTES + 1 regardless of what getsize said.
    """
    path = tmp_path / "status.json"
    path.write_bytes(b"x" * (health_status.MAX_FILE_BYTES + 100))
    monkeypatch.setattr(health_status.os.path, "getsize", lambda p: 10)

    doc, reason = health_status.read_health_status_document(str(path))
    assert doc is None
    assert reason == "health-status file is larger than 1 MiB"


def test_read_health_status_document_deeply_nested_json_is_unusable_not_a_crash(tmp_path):
    """appsec review finding: json.loads raises RecursionError, not
    JSONDecodeError, on pathologically deep nesting -- well under
    MAX_FILE_BYTES, so the size gate does not catch it. This used to escape
    read_health_status_document entirely; see _JSON_PARSE_ERRORS."""
    path = tmp_path / "status.json"
    path.write_text("[" * 100_000 + "]" * 100_000)
    doc, reason = health_status.read_health_status_document(str(path))
    assert doc is None
    assert reason == "health-status file is not valid JSON"


# ---------------------------------------------------------------------------
# 2b. _parse_json's exception tuple, and a mutation of it
#
# _JSON_PARSE_ERRORS/_parse_json exist specifically so this is provable
# without re-parsing or re-executing this module's own source (the exec()/
# eval() technique used elsewhere in this repo's test suite): `recoverable`
# is a real parameter of the real function, and a test can narrow a COPY of
# the tuple and pass it there directly.
# ---------------------------------------------------------------------------

_DEEPLY_NESTED_JSON = "[" * 100_000 + "]" * 100_000


def test_the_unmutated_parser_turns_a_recursion_error_into_a_reason():
    """Guards the guard: the default `recoverable` tuple has to actually
    catch this before narrowing it means anything."""
    doc, reason = health_status._parse_json(_DEEPLY_NESTED_JSON)
    assert doc is None
    assert reason == "health-status file is not valid JSON"


def test_mutation_narrowing_to_just_jsondecodeerror_lets_recursionerror_escape():
    """The exact pre-fix shape: catching only json.JSONDecodeError, the way
    read_health_status_document used to, lets RecursionError escape
    uncaught."""
    narrowed = (json.JSONDecodeError,)
    with pytest.raises(RecursionError):
        health_status._parse_json(_DEEPLY_NESTED_JSON, recoverable=narrowed)


# ---------------------------------------------------------------------------
# 3. build_health_status_view / _evaluate_state -- pure state machine
# ---------------------------------------------------------------------------


def test_reason_set_short_circuits_to_unknown_without_touching_doc():
    """`doc=None` alongside a reason must never be dereferenced -- this is
    what lets read_health_status_document's failure modes and this function
    compose without a None-check duplicated on both sides."""
    result = health_status.build_health_status_view(None, "the file could not be read", NOW)
    assert result["state"] == "unknown"
    assert result["reason"] == "the file could not be read"
    assert result["finished_at"] is None
    assert result["age_seconds"] is None
    assert result["counts"] is None
    assert result["alerting"] is None
    assert result["state_persisted"] is None
    assert result["ok"] == result["bad"] == result["skipped"] == result["warnings"] == []
    # NOT null: a fixed configuration value, meaningful even with no file.
    assert result["stale_after_seconds"] == health_status.STALE_AFTER_SECONDS


def test_clock_skew_future_timestamp_is_unknown():
    doc = _doc(finished_epoch=NOW_EPOCH + health_status.MAX_CLOCK_SKEW_SECONDS + 1)
    result = health_status.build_health_status_view(doc, None, NOW)
    assert result["state"] == "unknown"
    assert "future" in result["reason"] or "skew" in result["reason"]


def test_clock_skew_boundary_exactly_300s_ahead_is_not_skewed():
    doc = _doc(finished_epoch=NOW_EPOCH + health_status.MAX_CLOCK_SKEW_SECONDS)
    result = health_status.build_health_status_view(doc, None, NOW)
    assert result["state"] != "unknown"
    assert result["age_seconds"] == 0  # negative raw age clamped to zero


def test_stale_when_age_exceeds_the_threshold_but_lists_are_still_returned():
    doc = _doc(
        finished_epoch=NOW_EPOCH - health_status.STALE_AFTER_SECONDS - 1,
        warnings=["disk usage 86%"],
    )
    result = health_status.build_health_status_view(doc, None, NOW)
    assert result["state"] == "stale"
    assert result["counts"] is not None
    assert result["alerting"] is not None
    assert result["state_persisted"] is True
    assert result["warnings"] == ["disk usage 86%"]


def test_stale_boundary_exactly_at_the_threshold_is_not_stale():
    doc = _doc(finished_epoch=NOW_EPOCH - health_status.STALE_AFTER_SECONDS)
    result = health_status.build_health_status_view(doc, None, NOW)
    assert result["state"] != "stale"
    assert result["age_seconds"] == health_status.STALE_AFTER_SECONDS


def test_bad_non_empty_is_failing():
    doc = _doc(bad=[{"key": "disk", "label": "disk", "detail": "96% full"}])
    result = health_status.build_health_status_view(doc, None, NOW)
    assert result["state"] == "failing"
    assert "disk" in result["reason"]


def test_skipped_non_empty_is_incomplete():
    doc = _doc(skipped=[{"check": "containers", "reason": "docker not found"}])
    result = health_status.build_health_status_view(doc, None, NOW)
    assert result["state"] == "incomplete"


def test_no_alerting_channels_is_incomplete():
    doc = _doc(alerting={"channels": [], "notification": "none"})
    result = health_status.build_health_status_view(doc, None, NOW)
    assert result["state"] == "incomplete"


def test_failed_notification_is_incomplete():
    doc = _doc(alerting={"channels": ["discord"], "notification": "failed"})
    result = health_status.build_health_status_view(doc, None, NOW)
    assert result["state"] == "incomplete"


def test_ok_count_below_one_is_incomplete_even_if_the_ok_list_is_not_empty():
    """incomplete is driven by counts.ok, not by len(doc['ok']) -- the two
    can disagree if the script's own counting ever drifts from its lists,
    and counts is the field the task's contract names."""
    doc = _doc(ok=["stale entry"], counts={"ok": 0, "bad": 0})
    result = health_status.build_health_status_view(doc, None, NOW)
    assert result["state"] == "incomplete"


def test_fresh_and_clean_is_ok():
    doc = _doc(finished_epoch=NOW_EPOCH - 60)
    result = health_status.build_health_status_view(doc, None, NOW)
    assert result["state"] == "ok"
    assert result["age_seconds"] == 60


def test_the_literal_contract_example_is_failing_not_incomplete():
    """The task's own example document has a non-empty `bad`, a non-empty
    `skipped` AND a warning all at once -- proving that `failing` (bad
    non-empty) outranks `incomplete` (skipped non-empty) in practice, not
    just in two separate single-condition tests."""
    doc = {
        "schema": 1,
        "finished_at": "2026-09-13T07:29:49Z",
        "finished_epoch": NOW_EPOCH - 60,
        "counts": {"ok": 6, "bad": 0},
        "ok": ["api responding (HTTP 200, status=healthy)"],
        "bad": [
            {"key": "disk", "label": "disk", "detail": "/data/mirrors is 96% full, threshold 95%"}
        ],
        "skipped": [{"check": "containers", "reason": "docker not found on this host"}],
        "warnings": ["disk usage 86% on /data/mirrors (warn at 85%, alert at 95%)"],
        "alerting": {"channels": ["discord"], "notification": "none"},
        "state_persisted": True,
    }
    result = health_status.build_health_status_view(doc, None, NOW)
    assert result["state"] == "failing"


# --- precedence: first match wins, proved across pairs of conditions -------


def test_stale_outranks_failing():
    doc = _doc(
        finished_epoch=NOW_EPOCH - health_status.STALE_AFTER_SECONDS - 1,
        bad=[{"key": "disk", "label": "disk", "detail": "full"}],
    )
    assert health_status.build_health_status_view(doc, None, NOW)["state"] == "stale"


def test_failing_outranks_incomplete():
    doc = _doc(
        bad=[{"key": "disk", "label": "disk", "detail": "full"}],
        skipped=[{"check": "containers", "reason": "docker not found"}],
        alerting={"channels": [], "notification": "failed"},
        counts={"ok": 0, "bad": 1},
    )
    assert health_status.build_health_status_view(doc, None, NOW)["state"] == "failing"


def test_skipped_outranks_the_other_incomplete_reasons():
    doc = _doc(
        skipped=[{"check": "containers", "reason": "docker not found"}],
        alerting={"channels": [], "notification": "failed"},
        counts={"ok": 0, "bad": 0},
    )
    result = health_status.build_health_status_view(doc, None, NOW)
    assert result["state"] == "incomplete"
    assert "skipped" in result["reason"]


# --- caps --------------------------------------------------------------


def test_list_length_is_capped_at_50():
    doc = _doc(ok=[f"check {i}" for i in range(60)], counts={"ok": 60, "bad": 0})
    result = health_status.build_health_status_view(doc, None, NOW)
    assert len(result["ok"]) == health_status.MAX_LIST_ITEMS


def test_string_length_is_capped_at_500():
    doc = _doc(bad=[{"key": "disk", "label": "disk", "detail": "x" * 600}])
    result = health_status.build_health_status_view(doc, None, NOW)
    assert len(result["bad"][0]["detail"]) == health_status.MAX_STRING_LENGTH


def test_alerting_channels_and_notification_are_capped_too():
    doc = _doc(alerting={"channels": [f"chan{i}" for i in range(60)], "notification": "n" * 600})
    result = health_status.build_health_status_view(doc, None, NOW)
    assert len(result["alerting"]["channels"]) == health_status.MAX_LIST_ITEMS
    assert len(result["alerting"]["notification"]) == health_status.MAX_STRING_LENGTH


def test_finished_at_is_capped_too():
    doc = _doc()
    doc["finished_at"] = "2026" + "9" * 600
    result = health_status.build_health_status_view(doc, None, NOW)
    assert len(result["finished_at"]) == health_status.MAX_STRING_LENGTH


# --- mutation-check: the fail-closed order itself -----------------------
#
# _STATE_RULES is an explicit, ordered table specifically so this does not
# need to re-parse or re-execute this module's own source (as
# app.core.disk's arithmetic table and app.core.protected_paths_view's
# mutation tests do) to prove the order matters: a plain Python list
# comprehension over a COPY of the real table is the mutation, and
# _evaluate_state -- the real, unmodified production function -- is what
# runs it. A suite that still passes against a table missing an entry is not
# testing the table.


def test_the_unmutated_rules_mark_a_skipped_check_as_incomplete():
    """Guards the guard: the default table has to agree with the property
    being tested before removing an entry from a copy of it means anything."""
    doc = _doc(skipped=[{"check": "containers", "reason": "docker not found"}])
    state, _ = health_status._evaluate_state(doc, age_seconds=0)
    assert state == "incomplete"


def test_every_rule_name_in_the_table_is_unique():
    """The mutation below selects a rule by name; a duplicate name would let
    it silently remove the wrong one (or not the only one intended)."""
    names = [rule["name"] for rule in health_status._STATE_RULES]
    assert len(names) == len(set(names)), names


def test_mutation_removing_the_skipped_rule_lets_it_fall_through_to_ok():
    """The mistake this guards against: dropping (or reordering past) the
    skipped-non-empty rule lets a report where a check never ran read as a
    clean "ok" -- the exact "ok on a technicality" this state machine exists
    to prevent.
    """
    assert any(rule["name"] == "skipped" for rule in health_status._STATE_RULES), (
        "mutation targets a rule named 'skipped' that no longer exists; "
        "update the mutation, do not delete it"
    )
    mutated_rules = [rule for rule in health_status._STATE_RULES if rule["name"] != "skipped"]

    doc = _doc(skipped=[{"check": "containers", "reason": "docker not found"}])
    state, _ = health_status._evaluate_state(doc, age_seconds=0, rules=mutated_rules)

    assert state != "incomplete", "mutation was supposed to hide the skipped condition"
    assert state == "ok", (
        f"expected the mutation to fail OPEN to ok, got {state!r} instead -- this "
        "mutation no longer exercises the fail-closed order"
    )


# ---------------------------------------------------------------------------
# 4. get_health_status_view -- the async wrapper, against real files and the
#    real clock (unlike section 3, which pins `now`).
# ---------------------------------------------------------------------------


def _fresh_doc(**overrides):
    epoch = int(time.time()) - 60
    return _doc(finished_epoch=epoch, **overrides)


async def test_get_health_status_view_missing_file_is_unknown(tmp_path):
    result = await health_status.get_health_status_view(str(tmp_path / "absent.json"))
    assert result["state"] == "unknown"
    assert result["stale_after_seconds"] == health_status.STALE_AFTER_SECONDS
    assert result["counts"] is None


async def test_get_health_status_view_fresh_and_clean_file_is_ok(tmp_path):
    path = tmp_path / "status.json"
    path.write_text(json.dumps(_fresh_doc()))
    result = await health_status.get_health_status_view(str(path))
    assert result["state"] == "ok"


async def test_get_health_status_view_backstop_catches_any_unexpected_exception(monkeypatch):
    """appsec review finding: the "never raises" promise is not just about
    the failure modes this module already knows how to name. If
    read_health_status_document (or build_health_status_view) ever raises
    something neither of them anticipated, get_health_status_view's own
    backstop must still turn it into "unknown", not let it reach the
    endpoint as a 500.
    """

    def boom(path):
        raise RuntimeError("boom")

    monkeypatch.setattr(health_status, "read_health_status_document", boom)

    result = await health_status.get_health_status_view("/irrelevant/path")
    assert result["state"] == "unknown"


async def test_get_health_status_view_backstop_also_catches_a_broken_view_builder(monkeypatch):
    def boom(doc, reason, now):
        raise RuntimeError("boom")

    monkeypatch.setattr(health_status, "build_health_status_view", boom)

    result = await health_status.get_health_status_view("/irrelevant/path")
    assert result["state"] == "unknown"


# ---------------------------------------------------------------------------
# 5. GET /api/admin/health-checks -- end to end
# ---------------------------------------------------------------------------


async def test_health_checks_endpoint_never_500s_regardless_of_the_configured_path(client, seed):
    """No assumption about whether devops-sre's compose wiring mounts
    anything at the default HEALTH_STATUS_FILE path in THIS container --
    only that the endpoint is always a 200 with one of the defined states."""
    resp = await client.get(
        "/api/admin/health-checks", headers=auth_header(seed["users"]["readonly"])
    )
    assert resp.status_code == 200
    assert resp.json()["state"] in {"ok", "failing", "incomplete", "stale", "unknown"}


async def test_health_checks_endpoint_reports_unknown_for_a_missing_file(
    client, seed, tmp_path, monkeypatch
):
    monkeypatch.setattr(admin_module.settings, "HEALTH_STATUS_FILE", str(tmp_path / "absent.json"))
    resp = await client.get(
        "/api/admin/health-checks", headers=auth_header(seed["users"]["readonly"])
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "unknown"
    assert body["counts"] is None
    assert body["ok"] == body["bad"] == body["skipped"] == body["warnings"] == []


async def test_health_checks_endpoint_reads_the_configured_file(
    client, seed, tmp_path, monkeypatch
):
    path = tmp_path / "status.json"
    path.write_text(json.dumps(_fresh_doc(ok=["all good"])))
    monkeypatch.setattr(admin_module.settings, "HEALTH_STATUS_FILE", str(path))

    resp = await client.get("/api/admin/health-checks", headers=auth_header(seed["users"]["admin"]))
    assert resp.status_code == 200
    assert resp.json()["state"] == "ok"


async def test_health_checks_endpoint_rejects_anonymous_exactly_like_dashboard(client, seed):
    """Not merely "returns 401 too" -- the same status and body as the
    sibling endpoint that shares its auth dependency."""
    dashboard_resp = await client.get("/api/admin/dashboard")
    health_resp = await client.get("/api/admin/health-checks")

    assert dashboard_resp.status_code == 401
    assert health_resp.status_code == 401
    assert health_resp.json() == dashboard_resp.json()


async def test_health_checks_endpoint_returns_200_unknown_for_pathologically_nested_json(
    client, seed, tmp_path, monkeypatch
):
    """appsec review finding, proved at the HTTP layer: a status.json with
    deeply nested JSON (well under the 1 MiB cap) used to raise
    RecursionError out of json.loads and turn this endpoint into a 500."""
    path = tmp_path / "status.json"
    path.write_text("[" * 100_000 + "]" * 100_000)
    monkeypatch.setattr(admin_module.settings, "HEALTH_STATUS_FILE", str(path))

    resp = await client.get(
        "/api/admin/health-checks", headers=auth_header(seed["users"]["readonly"])
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "unknown"


async def test_health_checks_endpoint_returns_200_unknown_when_the_reader_raises_unexpectedly(
    client, seed, monkeypatch
):
    """appsec review finding: the endpoint's "always 200" promise must hold
    even for a failure mode this module's own authors did not anticipate,
    not only the ones it has a named reason string for."""

    def boom(path):
        raise RuntimeError("boom")

    monkeypatch.setattr(health_status, "read_health_status_document", boom)

    resp = await client.get(
        "/api/admin/health-checks", headers=auth_header(seed["users"]["readonly"])
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "unknown"
