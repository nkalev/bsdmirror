"""The public site's theme is applied before the first paint and follows the system until chosen.

main.js used to set data-theme only on DOMContentLoaded, defaulting to light,
so a dark-mode visitor saw the page painted light and then faded to dark by the
body's colour transition on every load. It also ignored prefers-color-scheme,
wrote "light" into storage on a first visit (so the system preference could
never win afterwards), and threw -- stopping all of main.js -- wherever
localStorage is blocked.

js/theme-init.js now runs from <head>, ahead of the stylesheets, and applies an
explicit saved choice, else the system preference, else light. main.js's
ThemeManager adopts that, keeps the toggle's icon and label in step, saves only
explicit choices, and follows system changes until one is made.
tests/js/theme_harness.mjs runs both real scripts in a Node vm with only the
browser APIs they touch stubbed.
"""

import json
import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PUBLIC = REPO_ROOT / "frontend" / "public"
THEME_INIT = PUBLIC / "js" / "theme-init.js"
MAIN_JS = PUBLIC / "js" / "main.js"
INDEX_HTML = PUBLIC / "index.html"
HARNESS = REPO_ROOT / "tests" / "js" / "theme_harness.mjs"
NODE = shutil.which("node")

requires_node = pytest.mark.skipif(
    NODE is None, reason="node is not installed; the theme behaviour checks cannot run"
)

CHECKS = [
    "no saved choice and a light system preference gives light",
    "no saved choice and a dark system preference gives dark",
    "a saved dark choice wins over a light system preference",
    "a saved light choice wins over a dark system preference",
    "an unrecognised saved value falls back to the system preference",
    "storage that throws still applies the system preference",
    "without matchMedia and with nothing saved the theme is light",
    "theme-init writes nothing to storage",
    "ThemeManager.init adopts the theme theme-init applied and syncs the toggle",
    "ThemeManager.init alone falls back to the saved or system theme",
    "clicking the toggle flips the theme and saves the choice",
    "a failing storage write still flips the theme",
    "a system change is followed until the visitor chooses",
    "a system change is ignored once a choice is saved",
]


@pytest.fixture(scope="module")
def harness_results():
    proc = subprocess.run(
        [NODE, str(HARNESS), str(THEME_INIT), str(MAIN_JS)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@requires_node
@pytest.mark.parametrize("name", CHECKS)
def test_theme_behaviour(harness_results, name):
    assert name in harness_results, f"harness did not run {name!r}"
    ok, detail = harness_results[name]
    assert ok, detail


@requires_node
def test_the_harness_runs_exactly_these_checks(harness_results):
    assert set(harness_results) == set(CHECKS)


def test_theme_init_runs_in_head_before_the_stylesheets():
    head = INDEX_HTML.read_text(encoding="utf-8").split("</head>", 1)[0]
    script = head.find('<script src="/js/theme-init.js"></script>')
    first_stylesheet = head.find('<link rel="stylesheet"')
    assert script != -1, "index.html does not load /js/theme-init.js in <head>"
    assert first_stylesheet != -1, "index.html <head> has no stylesheet"
    assert script < first_stylesheet, "theme-init.js must run before the stylesheets apply"
