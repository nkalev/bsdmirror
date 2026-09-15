"""deploy.sh's sync gate must not let --yes stand in for --force-sync-restart.

Gate 3 (require_no_sync_in_progress) exists because recreating the sync
container SIGTERMs a running rsync: the transfer is lost, and a mirror can be
left at SYNCING with no way to clear it from the admin UI. When the gate finds
a RUNNING job, only --force-sync-restart gets past it. When it could not read
the sync state at all, it used to accept --yes as well -- and every production
deploy runs `scripts/deploy.sh --yes main`, so not knowing whether an rsync was
running was the weakest case instead of the most careful one.

deploy.sh only runs main() when executed, so these tests source it and call the
gate directly, with `docker` and `env_get` replaced by shell functions.
"""

import os
import pathlib
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEPLOY_SH = REPO_ROOT / "scripts" / "deploy.sh"

PROBE = """
source "$DEPLOY_SH"
env_get() { printf '%s' "$2"; }
docker() { printf '%s' "$FAKE_PSQL_OUTPUT"; return "$FAKE_PSQL_RC"; }
if [ "$FAKE_CONFIRM" = "yes" ]; then confirm() { return 0; }; fi
ASSUME_YES=$FAKE_ASSUME_YES
FORCE_SYNC_RESTART=$FAKE_FORCE_SYNC_RESTART
require_no_sync_in_progress
echo "GATE PASSED"
"""

# Every way the gate can fail to learn the number of RUNNING sync jobs.
UNREADABLE = [
    pytest.param({"psql_output": "", "psql_rc": 1}, id="psql-fails"),
    pytest.param({"psql_output": "", "psql_rc": 0}, id="empty-output"),
    pytest.param(
        {"psql_output": "psql: error: connection refused", "psql_rc": 0}, id="non-numeric"
    ),
]


def run_gate(tmp_path, *, psql_output, psql_rc=0, assume_yes=False, force=False, confirm=False):
    probe = tmp_path / "probe.sh"
    probe.write_text(PROBE)
    result = subprocess.run(
        ["bash", str(probe)],
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "NO_COLOR": "1",
            "DEPLOY_SH": str(DEPLOY_SH),
            "FAKE_PSQL_OUTPUT": psql_output,
            "FAKE_PSQL_RC": str(psql_rc),
            "FAKE_ASSUME_YES": "1" if assume_yes else "0",
            "FAKE_FORCE_SYNC_RESTART": "1" if force else "0",
            "FAKE_CONFIRM": "yes" if confirm else "no",
        },
        # Not a terminal, so confirm() cannot prompt, and nothing can read stdin.
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    result.output = result.stdout + result.stderr
    return result


@pytest.mark.parametrize("state", UNREADABLE)
def test_yes_alone_refuses_when_the_sync_state_is_unreadable(tmp_path, state):
    # Before the fix this returned 0 and the deploy went on to recreate sync.
    result = run_gate(tmp_path, assume_yes=True, **state)
    assert result.returncode == 2, result.output
    assert "GATE PASSED" not in result.output
    assert "--force-sync-restart" in result.stderr


@pytest.mark.parametrize("state", UNREADABLE)
@pytest.mark.parametrize("assume_yes", [False, True], ids=["force", "force-and-yes"])
def test_force_sync_restart_passes_an_unreadable_state_loudly(tmp_path, state, assume_yes):
    result = run_gate(tmp_path, force=True, assume_yes=assume_yes, **state)
    assert result.returncode == 0, result.output
    assert "GATE PASSED" in result.output
    assert "BYPASSING THE SYNC GATE" in result.output


def test_unreadable_state_without_a_terminal_or_flags_refuses(tmp_path):
    result = run_gate(tmp_path, psql_output="", psql_rc=1)
    assert result.returncode == 2, result.output
    assert "GATE PASSED" not in result.output


def test_unreadable_state_can_still_be_confirmed_interactively(tmp_path):
    result = run_gate(tmp_path, psql_output="", psql_rc=1, confirm=True)
    assert result.returncode == 0, result.output
    assert "GATE PASSED" in result.output


def test_no_running_sync_passes_with_yes(tmp_path):
    result = run_gate(tmp_path, psql_output="0", assume_yes=True)
    assert result.returncode == 0, result.output
    assert "no sync_jobs in RUNNING state" in result.output


def test_a_running_sync_refuses_yes_and_yields_only_to_force(tmp_path):
    refused = run_gate(tmp_path, psql_output="2", assume_yes=True)
    assert refused.returncode == 2, refused.output
    assert "GATE PASSED" not in refused.output

    forced = run_gate(tmp_path, psql_output="2", force=True)
    assert forced.returncode == 0, forced.output
    assert "BYPASSING THE SYNC GATE" in forced.output
