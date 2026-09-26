"""Every Chrome harness gives Chrome time to start, and stops it when a run fails.

tests/js/contrast_harness.mjs, csp_click_harness.mjs and favicon_harness.mjs
each start headless Chrome and wait for it to write DevToolsActivePort before
driving it.
On 2026-09-25 a pull-request CI run failed every real-browser contrast test at
setup with "Chrome did not expose a DevTools endpoint within 10s". The first
Chrome start on that GitHub-hosted runner outlasted the fixed 10 s while the
rest of the suite ran at normal speed, and the re-run passed. In the passing
run of the same commit, the first contrast run (a cold Chrome start plus the
measurements) took 8.8 s and a second, warm one 3.5 s: 10 s was never much
headroom.

The harness also exited without stopping the Chrome it had started, so the
half-started browser kept running into the next test.

These tests swap Chrome for a stand-in that records its pid and never writes
DevToolsActivePort, so they need node but not Chrome, and they shorten the
start limit through CHROME_START_TIMEOUT_MS so the failure path takes seconds.
"""

import os
import pathlib
import pwd
import re
import shutil
import signal
import subprocess
import tempfile
import time

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PUBLIC = REPO_ROOT / "frontend" / "public"
ADMIN_JS = PUBLIC / "admin" / "js" / "admin.js"
JS_DIR = REPO_ROOT / "tests" / "js"
NODE = shutil.which("node")

requires_node = pytest.mark.skipif(
    NODE is None, reason="node is not installed; the harnesses cannot run"
)

# Each harness, and the arguments it takes before the Chrome binary.
HARNESSES = {
    "contrast": (JS_DIR / "contrast_harness.mjs", [PUBLIC, ADMIN_JS]),
    "csp": (JS_DIR / "csp_click_harness.mjs", [PUBLIC]),
    "favicon": (
        JS_DIR / "favicon_harness.mjs",
        [PUBLIC / "img" / "favicon.svg", "default-src 'self'"],
    ),
}


def is_running(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # An exited process that nobody has reaped still answers kill(pid, 0), and
    # nothing reaps orphans in the test container, where pytest is pid 1.
    try:
        stat = pathlib.Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return True
    return stat.rsplit(")", 1)[1].split()[0] != "Z"


def gone_within(pid, seconds):
    deadline = time.monotonic() + seconds
    while is_running(pid):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True


@pytest.fixture
def stand_in_chrome(tmp_path):
    """A "Chrome" that records its pid and never exposes DevTools."""
    script_dir, own_dir = tmp_path, None
    if os.statvfs(tmp_path).f_flag & getattr(os, "ST_NOEXEC", 0):
        # The test container mounts /tmp noexec, so a script there cannot be
        # started ("spawn ... EACCES"). The account's own home directory is on
        # the container's filesystem, which can run programs.
        home = pwd.getpwuid(os.getuid()).pw_dir
        script_dir = own_dir = pathlib.Path(tempfile.mkdtemp(prefix="stand-in-chrome-", dir=home))
    pidfile = tmp_path / "chrome.pid"
    script = script_dir / "chrome"
    script.write_text(f'#!/bin/sh\necho $$ > "{pidfile}"\nexec sleep 300\n')
    script.chmod(0o755)
    yield script, pidfile
    # Never leave one behind, whatever the harness did.
    if pidfile.exists():
        pid = int(pidfile.read_text())
        if is_running(pid):
            os.kill(pid, signal.SIGKILL)
    if own_dir is not None:
        shutil.rmtree(own_dir, ignore_errors=True)


def run_harness(name, chrome, start_timeout_ms):
    harness, args = HARNESSES[name]
    return subprocess.run(
        [NODE, str(harness), *map(str, args), str(chrome)],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(REPO_ROOT),
        env=dict(os.environ, CHROME_START_TIMEOUT_MS=str(start_timeout_ms)),
        check=False,
    )


@requires_node
@pytest.mark.parametrize("name", sorted(HARNESSES))
def test_a_chrome_that_never_starts_is_stopped_when_the_harness_gives_up(name, stand_in_chrome):
    chrome, pidfile = stand_in_chrome
    proc = run_harness(name, chrome, start_timeout_ms=1000)
    assert proc.returncode != 0, proc.stdout
    assert "did not expose a DevTools endpoint" in proc.stderr, proc.stderr
    assert pidfile.exists(), f"the {name} harness never started Chrome:\n{proc.stderr}"
    pid = int(pidfile.read_text())
    assert gone_within(pid, 5), f"the {name} harness exited but left Chrome (pid {pid}) running"


@requires_node
@pytest.mark.parametrize("name", sorted(HARNESSES))
def test_the_start_limit_can_be_shortened_and_the_error_names_it(name, stand_in_chrome):
    chrome, _ = stand_in_chrome
    started = time.monotonic()
    proc = run_harness(name, chrome, start_timeout_ms=1500)
    elapsed = time.monotonic() - started
    assert "did not expose a DevTools endpoint within 1.5s" in proc.stderr, proc.stderr
    assert elapsed < 8, f"the {name} harness took {elapsed:.1f}s to give up on a 1.5 s limit"


@pytest.mark.parametrize("name", sorted(HARNESSES))
def test_the_default_start_limit_is_at_least_30_seconds(name):
    source = HARNESSES[name][0].read_text(encoding="utf-8")
    match = re.search(r"^const DEFAULT_CHROME_START_TIMEOUT_MS = ([0-9_]+);$", source, re.MULTILINE)
    assert match, f"the {name} harness no longer declares DEFAULT_CHROME_START_TIMEOUT_MS"
    assert int(match.group(1).replace("_", "")) >= 30_000
