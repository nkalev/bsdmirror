"""The public site's mirror status model: a data-state attribute and a word, not classes.

docs/design/2026-09-25-reflection-redesign.md, section 5.2. main.js used to
rewrite `.status-dot`'s className, `.status-indicator`'s className and
`.pulse`'s inline background every 60 seconds, and returned early -- doing
nothing at all -- when the status API failed, so an outage left whatever "All
Systems Operational" the HTML had shipped with looking current. `every()` over
an empty mirror list also read as true, so a response with no mirrors in it
showed that same false all-clear.

MirrorStatus now writes only a `data-state` attribute and a `.status-text`
word, on a mirror's card pill (#<id>-status), its stream row (#<id>-stream)
and the row's own .pill child alike, plus the overall card (#overallStatus),
whose title and sentence are chosen from every mirror's computed state at
once -- including the API-failure and no-mirror-online cases the old
className-only version could not represent. The three old writes are gone,
and so is the .stat-card "loading" removal: style.css and
tests/js/contrast_harness.mjs key off data-state alone.

tests/js/states_harness.mjs runs the real main.js in a Node vm with a small
fake DOM (in tests/js/theme_harness.mjs's style) and stubbed fetch responses,
one per row of section 5.2's two tables plus these edge cases: an absent
mirror, an empty mirrors object, an API failure on the first load and after a
success, sentences naming two or three mirrors, the new #statFiles stat, the
[data-hostname] fill, a run against sparser markup with no stream rows to
prove every lookup is null-safe, and a run with the retired .status-dot,
.status-indicator, .pulse and .stat-card elements present to prove none of
them is ever written.
"""

import json
import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MAIN_JS = REPO_ROOT / "frontend" / "public" / "js" / "main.js"
HARNESS = REPO_ROOT / "tests" / "js" / "states_harness.mjs"
NODE = shutil.which("node")

requires_node = pytest.mark.skipif(
    NODE is None, reason="node is not installed; the mirror status behaviour checks cannot run"
)

CHECKS = [
    # Section 5.2, table 1: API status -> data-state and text.
    "an active mirror maps to online/Online on its card pill, stream row and row pill, and writes size and sync",
    "a syncing mirror maps to syncing/Syncing on its card pill, stream row and row pill",
    "an error mirror maps to error/Error on its card pill, stream row and row pill",
    "an explicitly disabled mirror maps to disabled/Offline",
    "a mirror absent from a successful response maps to disabled/Offline",
    "an unrecognised API status maps to unknown/Unknown",
    "a lower-cased API key still resolves to its mirror's elements",
    # Table 1's last row: the API request itself fails.
    "a first-load API failure leaves the shipped pills unchanged and marks the overall card unavailable",
    "an API failure after a success keeps each pill's last state and marks the overall card unavailable",
    # Section 5.2, table 2: the overall card after a successful load.
    "all three mirrors online gives All systems operational",
    "at least one but not all mirrors online gives Systems operational",
    "no mirrors online gives No mirrors online",
    "a single syncing mirror gives Sync in progress",
    "a single error mirror gives Degraded service",
    "an error mirror overrides a syncing one for the overall state",
    "two mirrors in error are joined as A and B in the sentence",
    "three mirrors syncing are joined as A, B and C in the sentence",
    # Stats and hostname.
    "statSize and statFiles are written from totals when present",
    "statSize and statFiles are left untouched when totals is empty",
    "statLastSync reflects the most recently updated mirror",
    "hostname fill sets #hostname, #rsynchost and every stream row's data-hostname element",
    # Null-safety against sparser markup, and the retired legacy writes.
    "load does not throw against markup with no stream rows",
    "the legacy status-dot, status-indicator, pulse and stat-card elements are present but never written",
]


@pytest.fixture(scope="module")
def harness_results():
    proc = subprocess.run(
        [NODE, str(HARNESS), str(MAIN_JS)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@requires_node
@pytest.mark.parametrize("name", CHECKS)
def test_mirror_status_behaviour(harness_results, name):
    assert name in harness_results, f"harness did not run {name!r}"
    ok, detail = harness_results[name]
    assert ok, detail


@requires_node
def test_the_harness_runs_exactly_these_checks(harness_results):
    """The parametrised list must not drift behind the harness."""
    assert set(harness_results) == set(CHECKS)
