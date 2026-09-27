"""
The page-wide [data-copy] buttons: bound, and safe with no Clipboard API.

docs/design/2026-09-25-reflection-redesign.md, section 5.1. The hero's "Copy
rsync URL" button and the two access-row icon buttons carry a data-copy
attribute (rsync-root or https-root), separately from the per-mirror buttons'
data-copy-rsync wiring test_public_page_csp.py already covers.
tests/js/csp_click_harness.mjs proves, in a real browser under the production
CSP, that clicking each one shows the right toast -- but a real browser
always has navigator.clipboard, so it cannot exercise the guard copyUrl()
adds: outside a secure context, and in older browsers, navigator.clipboard is
undefined rather than a promise that rejects, so a missing guard turns a
click into a thrown TypeError instead of the "Failed to copy URL" toast a
rejected write gets. The per-mirror copyRsync has no such guard: spec section
5.2 keeps those buttons unchanged.

tests/js/copy_buttons_harness.mjs runs the real main.js in a Node vm (there is
no JS test runner in this repo -- see test_admin_js_escaping.py for the same
approach against admin.js), binds its real bindDataCopyButtons() against a
fake button, fires a genuine click through the same addEventListener path the
page uses, and reports what the toast said.
"""

import json
import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MAIN_JS = REPO_ROOT / "frontend" / "public" / "js" / "main.js"
HARNESS = REPO_ROOT / "tests" / "js" / "copy_buttons_harness.mjs"

NODE = shutil.which("node")
requires_node = pytest.mark.skipif(
    NODE is None, reason="node is not installed; the copy-button behaviour checks cannot run"
)


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
    payload = json.loads(proc.stdout)
    assert not payload.get("loadError"), f"harness failed to load main.js: {payload['loadError']}"
    return {c["name"]: (c["ok"], c["detail"]) for c in payload["checks"]}


CHECKS = [
    "a bound data-copy button copies its built URL and shows the toast",
    "a data-copy click with no navigator.clipboard toasts Failed to copy URL instead of throwing",
    "an unrecognised data-copy value is left unbound rather than throwing",
    "an inherited object key as the data-copy value is left unbound",
]


@requires_node
@pytest.mark.parametrize("name", CHECKS)
def test_copy_button_behaviour(harness_results, name):
    assert (
        name in harness_results
    ), f"harness did not run {name!r}; it reported {sorted(harness_results)}"
    ok, detail = harness_results[name]
    assert ok, detail


@requires_node
def test_the_harness_runs_exactly_these_checks(harness_results):
    """The parametrised list must not drift behind the harness."""
    assert sorted(harness_results) == sorted(CHECKS)
