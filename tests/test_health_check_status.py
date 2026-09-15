"""scripts/health_check.sh must publish a redacted status.json every real run.

Contract (shared with the backend/admin-view side of this feature):

  * $HEALTH_STATUS_DIR/status.json, written right after state_save, only on
    MODE=run with DRY_RUN=0 -- never by --dry-run, --test-alert, --check-deps
    or --show-state, and not at all if the script exits before reaching that
    point.
  * status.json.tmp.$$ in the same directory, chmod 0644, then `mv -f`; the
    directory is created if missing and chmod 0755 on every run. Both modes
    are explicit because the script runs under `umask 077`.
  * Every string in it goes through redact() first.
  * Failing to write it warns and changes nothing else.

These tests drive write_status() and the small set of functions that feed it
(pass_condition, add_condition, skip_check, warn, redact_register) directly,
the same way tests/test_health_check_env.py drives load_env: the script is
run with its own trailing `main "$@"` stripped, which defines every function
and runs none of them. A handful of tests instead call main() itself, with
check_api/check_mirrors/check_disk/check_containers/require_deps/
channel_send_discord redefined as stubs afterwards -- bash resolves a
function call by name at the time it runs, so a later definition of the same
name simply wins, and main() never touches a real network, docker socket or
webhook.

No test here makes a real HTTP request or shells out to a real `docker`;
docker-comes-from-somewhere is handled by curating PATH, not by mocking.

The final section is a contract test with the backend half of this feature:
script and backend were built in parallel from the same written contract,
and field NAMES were cross-checked by hand, but types and enum values never
ran against each other until a test actually feeds write_status's real
output through backend.app.core.health_status's real, unmodified reader and
state machine. That module's own tests (tests/test_admin_health_checks.py)
prove it against hand-built documents; this proves the document write_status
actually produces is one of them.
"""

import json
import pathlib
import shlex
import shutil
import subprocess
from datetime import datetime, timezone

import pytest

# pyproject.toml's pythonpath = ["backend", "."] puts backend/app on
# sys.path for the whole suite -- the same import test_admin_health_checks.py
# uses for the module this file's contract tests read output back through.
from app.core import health_status

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "health_check.sh"

# Tools health_check.sh's definitions (require_deps, the checks, write_status)
# can reach for. Built as an allowlist symlink directory rather than pruning
# PATH by directory, because a directory-based prune to hide `docker` would
# also hide anything installed alongside it -- jq and coreutils commonly are.
_SHIM_TOOLS = (
    "bash",
    "jq",
    "awk",
    "sed",
    "date",
    "grep",
    "tr",
    "cut",
    "mkdir",
    "chmod",
    "mv",
    "rm",
    "dirname",
    "basename",
    "cat",
    "mktemp",
    "df",
    "curl",
    "hostname",
    "sh",
)


def _definitions_only():
    text = SCRIPT.read_text()
    body, entry, rest = text.rpartition('\nmain "$@"\n')
    assert entry and not rest, 'health_check.sh must end with its `main "$@"` call'
    return body + "\n"


def _shim_path(tmp_path, without=()):
    """A PATH built only from _SHIM_TOOLS, minus the names in `without`."""
    shim = tmp_path / "shim-bin"
    shim.mkdir(exist_ok=True)
    for tool in _SHIM_TOOLS:
        if tool in without:
            continue
        found = shutil.which(tool)
        link = shim / tool
        if found and not link.exists():
            link.symlink_to(found)
    return str(shim)


def run_probe(tmp_path, script_body, *, env=None, args=(), path_without=()):
    """Run `script_body` appended after the script's own definitions.

    A fresh `probe.sh` per call, matching test_health_check_env.py's
    load_config: a file rather than `bash -c` or stdin, so a scenario is free
    to be as long as it needs to be.
    """
    probe = tmp_path / "probe.sh"
    probe.write_text(_definitions_only() + script_body)
    full_env = {"PATH": _shim_path(tmp_path, without=path_without)}
    full_env.update(env or {})
    return subprocess.run(
        ["bash", str(probe), *args],
        env=full_env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def write_direct(tmp_path, status_dir, setup):
    """Run `setup`, then call write_status(), and assert it did not fail.

    `setup` populates whichever of OK_MESSAGES/BAD_RECORDS/SKIPPED_RECORDS/
    WARN_MESSAGES/SELECTED_CHANNELS/NOTIFICATION_RESULT/STATE_DEGRADED the
    test cares about via the real functions (pass_condition, add_condition,
    skip_check, warn) or, for the last three, a plain assignment.
    """
    script = f"umask 077\nHEALTH_STATUS_DIR={shlex.quote(str(status_dir))}\n{setup}\nwrite_status\n"
    result = run_probe(tmp_path, script)
    assert result.returncode == 0, f"write_status failed: {result.stderr}"
    return result


def load_status(status_dir):
    return json.loads((status_dir / "status.json").read_text())


# ---------------------------------------------------------------------------
# HEALTH_STATUS_DIR's default
#
# Must NOT derive from STATE_DIRECTORY (unlike HEALTH_STATE_FILE): nesting it
# under the systemd unit's private StateDirectory=bsdmirror let Docker
# auto-create that directory itself, at Docker's own permissive default mode,
# on a fresh host where `docker compose up` (which needs this bind mount's
# source to exist) runs before install-health-timer.sh ever does -- and
# systemd does not tighten the mode of a directory that already exists. See
# the comment on this assignment in the script.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "extra_env",
    [{}, {"STATE_DIRECTORY": "/some/other/state/dir"}],
    ids=["state_directory_unset", "state_directory_set_to_something_else"],
)
def test_health_status_dir_default_ignores_state_directory(tmp_path, extra_env):
    result = run_probe(tmp_path, 'printf "%s" "$HEALTH_STATUS_DIR"\n', env=extra_env)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "/var/lib/bsdmirror-status"


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


def test_schema_and_types(tmp_path):
    status_dir = tmp_path / "status"
    write_direct(
        tmp_path,
        status_dir,
        """
pass_condition "api responding (HTTP 200, status=healthy)"
add_condition "disk" "disk" "/data/mirrors is 96% full, threshold 95%"
skip_check "containers" "docker not found on this host"
warn "disk usage 86% on /data/mirrors (warn at 85%, alert at 95%)"
SELECTED_CHANNELS=" discord"
NOTIFICATION_RESULT="delivered"
""",
    )
    data = load_status(status_dir)

    assert data["schema"] == 1
    assert isinstance(data["finished_epoch"], int)
    assert isinstance(data["finished_at"], str)
    assert data["finished_at"].endswith("Z")
    assert len(data["finished_at"]) == len("2026-09-13T07:29:49Z")

    assert data["counts"] == {"ok": 1, "bad": 1}
    assert isinstance(data["ok"], list)
    assert isinstance(data["bad"], list)
    assert isinstance(data["skipped"], list)
    assert isinstance(data["warnings"], list)

    assert data["ok"] == ["api responding (HTTP 200, status=healthy)"]
    assert data["bad"] == [
        {"key": "disk", "label": "disk", "detail": "/data/mirrors is 96% full, threshold 95%"}
    ]
    assert data["skipped"] == [{"check": "containers", "reason": "docker not found on this host"}]
    assert data["warnings"] == ["disk usage 86% on /data/mirrors (warn at 85%, alert at 95%)"]

    assert data["alerting"] == {"channels": ["discord"], "notification": "delivered"}
    assert data["state_persisted"] is True


def test_empty_run_has_empty_lists_and_zero_counts(tmp_path):
    status_dir = tmp_path / "status"
    write_direct(tmp_path, status_dir, 'SELECTED_CHANNELS=""\n')
    data = load_status(status_dir)
    assert data["counts"] == {"ok": 0, "bad": 0}
    assert data["ok"] == []
    assert data["bad"] == []
    assert data["skipped"] == []
    assert data["warnings"] == []
    assert data["alerting"] == {"channels": [], "notification": "none"}


def test_ok_bad_skipped_warnings_preserve_order(tmp_path):
    status_dir = tmp_path / "status"
    write_direct(
        tmp_path,
        status_dir,
        """
pass_condition "first ok"
pass_condition "second ok"
pass_condition "third ok"
add_condition "disk" "disk" "first bad"
add_condition "containers" "containers" "second bad"
skip_check "mirrors" "first skip"
skip_check "containers" "second skip"
warn "first warning"
warn "second warning"
""",
    )
    data = load_status(status_dir)
    assert data["ok"] == ["first ok", "second ok", "third ok"]
    assert [b["detail"] for b in data["bad"]] == ["first bad", "second bad"]
    assert [s["reason"] for s in data["skipped"]] == ["first skip", "second skip"]
    assert data["warnings"] == ["first warning", "second warning"]
    assert data["counts"] == {"ok": 3, "bad": 2}


@pytest.mark.parametrize(
    ("channels", "notification", "expected"),
    [
        (" discord", "delivered", ["discord"]),
        (" discord slack", "failed", ["discord", "slack"]),
        ("", "none", []),
    ],
)
def test_channels_and_notification_values(tmp_path, channels, notification, expected):
    status_dir = tmp_path / "status"
    write_direct(
        tmp_path,
        status_dir,
        f"""
pass_condition "ok"
SELECTED_CHANNELS={shlex.quote(channels)}
NOTIFICATION_RESULT={shlex.quote(notification)}
""",
    )
    data = load_status(status_dir)
    assert data["alerting"] == {"channels": expected, "notification": notification}


def test_state_persisted_false_when_state_degraded(tmp_path):
    status_dir = tmp_path / "status"
    write_direct(tmp_path, status_dir, 'pass_condition "ok"\nSTATE_DEGRADED=1\n')
    assert load_status(status_dir)["state_persisted"] is False


def test_state_persisted_true_by_default(tmp_path):
    status_dir = tmp_path / "status"
    write_direct(tmp_path, status_dir, 'pass_condition "ok"\n')
    assert load_status(status_dir)["state_persisted"] is True


# ---------------------------------------------------------------------------
# On-disk shape: modes, atomic replace
# ---------------------------------------------------------------------------


def test_modes_0755_dir_0644_file_under_restrictive_umask(tmp_path):
    status_dir = tmp_path / "status"
    write_direct(tmp_path, status_dir, 'pass_condition "ok"\n')
    assert oct(status_dir.stat().st_mode)[-3:] == "755"
    assert oct((status_dir / "status.json").stat().st_mode)[-3:] == "644"


def test_tmp_file_is_gone_after_the_replace(tmp_path):
    status_dir = tmp_path / "status"
    write_direct(tmp_path, status_dir, 'pass_condition "ok"\n')
    assert sorted(p.name for p in status_dir.iterdir()) == ["status.json"]


def test_directory_is_created_if_missing(tmp_path):
    status_dir = tmp_path / "nested" / "status"
    assert not status_dir.parent.exists()
    write_direct(tmp_path, status_dir, 'pass_condition "ok"\n')
    assert status_dir.is_dir()
    assert (status_dir / "status.json").is_file()


def test_write_failure_warns_and_changes_nothing_else(tmp_path):
    # mkdir -p under a plain file must fail: this is not a directory, it can
    # never become one.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    status_dir = blocker / "status"
    script = f"""
umask 077
HEALTH_STATUS_DIR={shlex.quote(str(status_dir))}
pass_condition "ok"
add_condition "disk" "disk" "bad"
if write_status; then rc=0; else rc=$?; fi
echo "RC=$rc CHECKS_BAD=$CHECKS_BAD CHECKS_OK=$CHECKS_OK"
"""
    result = run_probe(tmp_path, script)
    assert result.returncode == 0, result.stderr
    assert "RC=1 CHECKS_BAD=1 CHECKS_OK=1" in result.stdout
    assert "cannot create" in result.stderr
    assert not status_dir.exists()


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


def test_redacted_secret_never_appears_in_the_file(tmp_path):
    status_dir = tmp_path / "status"
    secret = "https://discord.com/api/webhooks/123456789012345/AAAABBBBCCCCDDDDEEEEFFFF"
    write_direct(
        tmp_path,
        status_dir,
        f"""
redact_register {shlex.quote(secret)}
add_condition "disk" "disk" "leaked in a detail: {secret}"
pass_condition "leaked in an ok message: {secret}"
warn "leaked in a warning: {secret}"
""",
    )
    raw = (status_dir / "status.json").read_text()
    assert secret not in raw
    assert raw.count("<redacted>") == 3

    data = json.loads(raw)
    assert "<redacted>" in data["bad"][0]["detail"]
    assert "<redacted>" in data["ok"][0]
    assert "<redacted>" in data["warnings"][0]


def test_short_string_is_not_redacted(tmp_path):
    # redact_register itself drops anything under 12 characters -- confirms
    # this test is exercising redact(), not merely echoing input verbatim.
    status_dir = tmp_path / "status"
    write_direct(
        tmp_path,
        status_dir,
        """
redact_register "short"
add_condition "disk" "disk" "short appears here"
""",
    )
    data = load_status(status_dir)
    assert data["bad"][0]["detail"] == "short appears here"


# ---------------------------------------------------------------------------
# check_containers' one real skip path: no docker on PATH.
# ---------------------------------------------------------------------------


def test_docker_missing_records_a_skip(tmp_path):
    status_dir = tmp_path / "status"
    script = f"""
umask 077
HEALTH_STATUS_DIR={shlex.quote(str(status_dir))}
check_containers
write_status
"""
    result = run_probe(tmp_path, script, path_without=("docker",))
    assert result.returncode == 0, result.stderr
    data = load_status(status_dir)
    assert data["skipped"] == [{"check": "containers", "reason": "docker not found on this host"}]
    assert data["counts"] == {"ok": 0, "bad": 0}


# ---------------------------------------------------------------------------
# main(): when write_status is (and is not) reached.
# ---------------------------------------------------------------------------

# require_deps is stubbed in every main()-level test below: Dockerfile.test
# has jq but not curl (this suite never makes a real HTTP request), and the
# bare CI runner that also collects this file has both -- stubbing keeps the
# two environments from testing different code paths.
_NO_NETWORK_STUBS = """
require_deps() { return 0; }
check_api() { pass_condition "api responding (HTTP 200, status=healthy)"; return 0; }
check_mirrors() { return 0; }
check_disk() { add_condition "disk" "disk" "/data/mirrors is 96% full, threshold 95%"; return 1; }
check_containers() { skip_check "containers" "docker not found on this host"; return 0; }
channel_configured_discord() { return 0; }
channel_send_discord() { return 0; }
"""


def test_dry_run_writes_no_file(tmp_path):
    status_dir = tmp_path / "status"
    state_file = tmp_path / "state.json"
    scenario = _NO_NETWORK_STUBS + '\nmain "$@"\n'
    result = run_probe(
        tmp_path,
        scenario,
        env={"HEALTH_STATUS_DIR": str(status_dir)},
        args=["--dry-run", "--state-file", str(state_file), "--quiet"],
    )
    assert result.returncode == 1, result.stderr  # a condition (disk) is bad
    assert not status_dir.exists()


@pytest.mark.parametrize("flag", ["--check-deps", "--show-state", "--test-alert"])
def test_other_modes_never_write_status(tmp_path, flag):
    status_dir = tmp_path / "status"
    state_file = tmp_path / "state.json"
    scenario = _NO_NETWORK_STUBS + '\nmain "$@"\n'
    result = run_probe(
        tmp_path,
        scenario,
        env={"HEALTH_STATUS_DIR": str(status_dir)},
        args=[flag, "--state-file", str(state_file), "--quiet"],
    )
    assert (
        not status_dir.exists()
    ), f"{flag} must never write status.json (exit {result.returncode}): {result.stderr}"


def test_real_run_writes_status_with_delivered_notification(tmp_path):
    status_dir = tmp_path / "status"
    state_file = tmp_path / "state.json"
    scenario = _NO_NETWORK_STUBS + '\nmain "$@"\n'
    result = run_probe(
        tmp_path,
        scenario,
        env={"HEALTH_STATUS_DIR": str(status_dir)},
        args=["--state-file", str(state_file), "--quiet"],
    )
    # A fresh state file: the disk condition is a NEW transition, so main()
    # exits 1 (a condition is bad) having attempted delivery.
    assert result.returncode == 1, result.stderr
    data = load_status(status_dir)
    assert data["counts"] == {"ok": 1, "bad": 1}
    assert data["bad"] == [
        {"key": "disk", "label": "disk", "detail": "/data/mirrors is 96% full, threshold 95%"}
    ]
    assert data["skipped"] == [{"check": "containers", "reason": "docker not found on this host"}]
    assert data["alerting"] == {"channels": ["discord"], "notification": "delivered"}
    assert data["state_persisted"] is True


def test_real_run_with_no_transition_has_notification_none(tmp_path):
    status_dir = tmp_path / "status"
    state_file = tmp_path / "state.json"
    scenario = _NO_NETWORK_STUBS + '\nmain "$@"\n'
    common_args = ["--state-file", str(state_file), "--quiet"]
    common_env = {"HEALTH_STATUS_DIR": str(status_dir)}

    first = run_probe(tmp_path, scenario, env=common_env, args=common_args)
    assert first.returncode == 1, first.stderr

    # Second run: same bad condition, no state change, so reconcile() finds
    # no transition and main() never calls dispatch at all.
    second = run_probe(tmp_path, scenario, env=common_env, args=common_args)
    assert second.returncode == 1, second.stderr
    data = load_status(status_dir)
    assert data["alerting"]["notification"] == "none"
    assert data["alerting"]["channels"] == ["discord"]


# ---------------------------------------------------------------------------
# Contract test: the backend's real reader/state-machine against write_status's
# real output.
#
# Everything above proves what write_status puts in the file, in isolation.
# This proves the OTHER half of the contract: that backend.app.core.
# health_status -- built independently against the same written contract --
# accepts that file and classifies it the way the feature's own table says it
# should. A passing schema is not enough: a string where the backend expects
# an int, or a channel list joined the wrong way, would validate as JSON but
# fail _validate_document or silently misclassify, and production would show
# "unknown" forever while every check stayed green -- discovered post-deploy,
# which is the exact failure mode this repo's history is full of.
# ---------------------------------------------------------------------------


def _read_and_classify(status_dir, *, now_offset=0):
    """Run status.json at `status_dir` through the backend's real, unmodified
    read_health_status_document + build_health_status_view.

    `now` is pinned to the document's own finished_epoch (+ now_offset)
    rather than the wall clock, the same reason test_admin_health_checks.py
    pins a fixed NOW for its build_health_status_view tests: age_seconds must
    be an exact, reproducible number, not a race against how long the bash
    subprocess above took.
    """
    path = status_dir / "status.json"
    doc, reason = health_status.read_health_status_document(str(path))
    now = (
        datetime.fromtimestamp(doc["finished_epoch"] + now_offset, tz=timezone.utc)
        if doc is not None
        else datetime.now(timezone.utc)
    )
    view = health_status.build_health_status_view(doc, reason, now)
    return reason, view


def test_contract_all_ok_one_channel_no_notification_is_state_ok(tmp_path):
    status_dir = tmp_path / "status"
    write_direct(
        tmp_path,
        status_dir,
        """
pass_condition "api responding (HTTP 200, status=healthy)"
SELECTED_CHANNELS=" discord"
NOTIFICATION_RESULT="none"
""",
    )
    reason, view = _read_and_classify(status_dir)
    assert reason is None, f"backend validator rejected write_status's own output: {reason}"
    assert view["state"] != "unknown"
    assert view["state"] == "ok"


def test_contract_a_bad_condition_is_state_failing(tmp_path):
    status_dir = tmp_path / "status"
    write_direct(
        tmp_path,
        status_dir,
        """
pass_condition "api responding (HTTP 200, status=healthy)"
add_condition "disk" "disk" "/data/mirrors is 96% full, threshold 95%"
SELECTED_CHANNELS=" discord"
NOTIFICATION_RESULT="none"
""",
    )
    reason, view = _read_and_classify(status_dir)
    assert reason is None, f"backend validator rejected write_status's own output: {reason}"
    assert view["state"] != "unknown"
    assert view["state"] == "failing"


def test_contract_a_skipped_check_is_state_incomplete(tmp_path):
    # The real check_containers, with docker genuinely absent from PATH --
    # not a hand-set SKIPPED_RECORDS -- so this is the actual skip path, the
    # same as test_docker_missing_records_a_skip above.
    status_dir = tmp_path / "status"
    script = f"""
umask 077
HEALTH_STATUS_DIR={shlex.quote(str(status_dir))}
pass_condition "api responding (HTTP 200, status=healthy)"
check_containers
SELECTED_CHANNELS=" discord"
NOTIFICATION_RESULT="none"
write_status
"""
    result = run_probe(tmp_path, script, path_without=("docker",))
    assert result.returncode == 0, result.stderr
    reason, view = _read_and_classify(status_dir)
    assert reason is None, f"backend validator rejected write_status's own output: {reason}"
    assert view["state"] != "unknown"
    assert view["state"] == "incomplete"


def test_contract_no_channel_configured_is_state_incomplete(tmp_path):
    status_dir = tmp_path / "status"
    write_direct(
        tmp_path,
        status_dir,
        """
pass_condition "api responding (HTTP 200, status=healthy)"
SELECTED_CHANNELS=""
NOTIFICATION_RESULT="none"
""",
    )
    reason, view = _read_and_classify(status_dir)
    assert reason is None, f"backend validator rejected write_status's own output: {reason}"
    assert view["state"] != "unknown"
    assert view["state"] == "incomplete"


def test_contract_notification_failed_is_state_incomplete(tmp_path):
    status_dir = tmp_path / "status"
    write_direct(
        tmp_path,
        status_dir,
        """
pass_condition "api responding (HTTP 200, status=healthy)"
SELECTED_CHANNELS=" discord"
NOTIFICATION_RESULT="failed"
""",
    )
    reason, view = _read_and_classify(status_dir)
    assert reason is None, f"backend validator rejected write_status's own output: {reason}"
    assert view["state"] != "unknown"
    assert view["state"] == "incomplete"


def test_contract_two_alert_channels_round_trip_as_exactly_those_two_names(tmp_path):
    # Exercises the REAL select_channels(), not a hand-set SELECTED_CHANNELS:
    # this is what actually proves write_status's `split(" ")` agrees with
    # how select_channels joins the list, rather than assuming it from
    # reading the source. ALERT_CHANNELS is comma-separated here on purpose
    # (select_channels' own documented syntax) precisely because the join it
    # produces internally is a separate question from the syntax accepted.
    status_dir = tmp_path / "status"
    script = f"""
umask 077
HEALTH_STATUS_DIR={shlex.quote(str(status_dir))}
ALERT_CHANNELS="discord,slack"
DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/123456789012345/AAAABBBBCCCCDDDDEEEEFFFF"
SLACK_WEBHOOK="https://hooks.slack.com/services/T000/B000/XXXXXXXXXXXXXXXXXXXXXXXX"
select_channels
pass_condition "api responding (HTTP 200, status=healthy)"
NOTIFICATION_RESULT="none"
write_status
"""
    result = run_probe(tmp_path, script)
    assert result.returncode == 0, result.stderr

    data = load_status(status_dir)
    assert data["alerting"]["channels"] == ["discord", "slack"]

    reason, view = _read_and_classify(status_dir)
    assert reason is None, f"backend validator rejected write_status's own output: {reason}"
    assert view["state"] != "unknown"
    assert view["alerting"]["channels"] == ["discord", "slack"]
