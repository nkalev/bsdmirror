"""The admin console follows the site's theme (spec 6.2, "Light theme").

admin/index.html used to hardcode data-theme="dark" and admin.js had no theme
code at all: zero setAttribute calls, no matchMedia, no 'theme' storage key.
The console now loads js/theme-init.js exactly like the public page, and
admin.js's AdminTheme object adopts whatever that already set, keeps every
rendered toggle in step, and saves only an explicit choice -- the same
contract as main.js's ThemeManager (tests/test_theme.py), applied to a page
whose toggle is a data-action button inside a re-rendered layout rather than
a single static element.

tests/js/admin_theme_harness.mjs runs the real admin.js in a Node vm, in two
shapes: one with document.documentElement and window.matchMedia, and one with
neither -- the shape tests/js/escaping_harness.mjs and tests/js/
contrast_harness.mjs already load this file into, so every top-level theme
access must be guarded.
"""

import json
import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ADMIN_JS = REPO_ROOT / "frontend" / "public" / "admin" / "js" / "admin.js"
ADMIN_INDEX = REPO_ROOT / "frontend" / "public" / "admin" / "index.html"
HARNESS = REPO_ROOT / "tests" / "js" / "admin_theme_harness.mjs"
NODE = shutil.which("node")

requires_node = pytest.mark.skipif(
    NODE is None, reason="node is not installed; the admin theme behaviour checks cannot run"
)

CHECKS = [
    "a fresh load adopts html[data-theme]",
    "current falls back to light when no attribute is set",
    "current falls back to light with no documentElement",
    "renderThemeToggle returns the markup for the current theme",
    "toggleTheme flips the attribute, saves the choice, and updates every toggle in place",
    "a failing storage write still flips the theme and updates the toggle",
    "a failing storage read is treated as nothing saved",
    "the system listener applies the OS theme while nothing is saved",
    "the system listener is ignored once a choice is saved",
    "a sandbox with no documentElement and no matchMedia still loads and renders the layout",
    "renderLayout renders exactly one theme toggle whose icon matches the attribute",
    "renderLoginPage renders exactly one theme toggle whose icon matches the attribute",
]


@pytest.fixture(scope="module")
def harness_results():
    proc = subprocess.run(
        [NODE, str(HARNESS), str(ADMIN_JS)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@requires_node
@pytest.mark.parametrize("name", CHECKS)
def test_admin_theme_behaviour(harness_results, name):
    assert name in harness_results, f"harness did not run {name!r}"
    ok, detail = harness_results[name]
    assert ok, detail


@requires_node
def test_the_harness_runs_exactly_these_checks(harness_results):
    assert set(harness_results) == set(CHECKS)


def _html_tag(text):
    """The literal `<html ...>` opening tag, not `<!DOCTYPE html>` before it."""
    start = text.index("<html")
    end = text.index(">", start)
    return text[start : end + 1]


def test_admin_index_has_no_static_data_theme():
    tag = _html_tag(ADMIN_INDEX.read_text(encoding="utf-8"))
    assert "data-theme" not in tag, (
        "admin/index.html must not hardcode a theme; js/theme-init.js sets data-theme "
        "before the first paint, the same as the public page"
    )


def test_admin_index_keeps_data_surface_admin():
    tag = _html_tag(ADMIN_INDEX.read_text(encoding="utf-8"))
    assert 'data-surface="admin"' in tag, 'data-surface="admin" selects the admin token layer'


def test_admin_theme_init_runs_in_head_before_the_stylesheets():
    head = ADMIN_INDEX.read_text(encoding="utf-8").split("</head>", 1)[0]
    script = head.find('<script src="/js/theme-init.js"></script>')
    first_stylesheet = head.find('<link rel="stylesheet"')
    assert script != -1, "admin/index.html does not load /js/theme-init.js in <head>"
    assert first_stylesheet != -1, "admin/index.html <head> has no stylesheet"
    assert script < first_stylesheet, "theme-init.js must run before the stylesheets apply"
