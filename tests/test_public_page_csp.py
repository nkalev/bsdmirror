"""
The public page must work under the Content-Security-Policy nginx actually sends.

This exists because of a bug that three rounds of code reading did not catch.
`frontend/public/index.html` wired its three "Copy rsync URL" buttons with
`onclick="copyRsync('FreeBSD')"`. The production policy has always carried
`script-src 'self'`, which blocks inline event handlers, so all three buttons
were dead for every visitor -- silently, with the failure visible only in the
browser console. `copyRsync` itself was fine. Only the wiring was blocked.

Reading cannot find that class of bug: an `onclick` attribute looks like
working code, and the policy that kills it lives in a different file, in a
different language, owned by a different role. So this file does not read. It
serves `frontend/public` over HTTP with the real policy string, drives real
headless Chrome, dispatches a genuine trusted mouse click on each button, and
asserts something happened.

What that proves: the buttons work in a browser that enforces the production
CSP, and no CSP violation is raised while doing it. What it does not prove:
that nginx sends this policy -- the string is asserted equal to the one in
nginx/nginx.conf (test_harness_csp_matches_nginx), but whether nginx actually
emits it on a given route is a devops-sre concern and `add_header` inheritance
makes it a real one. It also does not cover browsers other than the installed
Chrome.

Skips, loudly, if node or Chrome is missing. A local run without them reports
fewer tests than CI.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PUBLIC = REPO_ROOT / "frontend" / "public"
INDEX_HTML = PUBLIC / "index.html"
ADMIN_INDEX_HTML = PUBLIC / "admin" / "index.html"
MAIN_JS = PUBLIC / "js" / "main.js"
HARNESS = REPO_ROOT / "tests" / "js" / "csp_click_harness.mjs"
NGINX_CONF = REPO_ROOT / "nginx" / "nginx.conf"

NODE = shutil.which("node")

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
]


def find_chrome():
    for candidate in CHROME_CANDIDATES:
        if "/" in candidate:
            if pathlib.Path(candidate).exists():
                return candidate
        else:
            found = shutil.which(candidate)
            if found:
                return found
    return None


CHROME = find_chrome()

requires_browser = pytest.mark.skipif(
    NODE is None or CHROME is None,
    reason=f"needs node and Chrome (node={bool(NODE)}, chrome={bool(CHROME)})",
)


def run_click_harness(docroot):
    proc = subprocess.run(
        [NODE, str(HARNESS), str(docroot), CHROME],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, (
        f"click harness failed (rc={proc.returncode})\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def clicked():
    return run_click_harness(PUBLIC)


# ---------------------------------------------------------------------------
# The policy under test must be the policy in production
# ---------------------------------------------------------------------------
def nginx_csp():
    """The single `map $host $csp_policy` default value from nginx/nginx.conf."""
    conf = NGINX_CONF.read_text(encoding="utf-8")
    block = re.search(r"map\s+\$host\s+\$csp_policy\s*\{(.*?)\}", conf, re.S)
    assert block, "no `map $host $csp_policy` block in nginx/nginx.conf"
    value = re.search(r'default\s+"([^"]+)"', block.group(1))
    assert value, "no default value in the $csp_policy map"
    return value.group(1)


def harness_csp():
    source = HARNESS.read_text(encoding="utf-8")
    block = re.search(r"const CSP = (.*?);\n", source, re.S)
    assert block, "no CSP constant in the click harness"
    return "".join(re.findall(r'"([^"]*)"', block.group(1)))


@pytest.mark.skipif(not NGINX_CONF.exists(), reason="nginx/nginx.conf not present")
def test_harness_csp_matches_nginx():
    """Otherwise this file cheerfully tests a policy nobody serves."""
    assert harness_csp() == nginx_csp(), (
        "the CSP in tests/js/csp_click_harness.mjs has drifted from "
        "nginx/nginx.conf. Copy the nginx value across; do not relax the test."
    )


# ---------------------------------------------------------------------------
# Static: no inline handlers anywhere. Cheap, always runs.
# ---------------------------------------------------------------------------
INLINE_HANDLER = re.compile(r"""\son([a-z]{3,})\s*=\s*["']""")


@pytest.mark.parametrize(
    "html_path", [INDEX_HTML, ADMIN_INDEX_HTML], ids=["index.html", "admin/index.html"]
)
def test_no_inline_event_handlers(html_path):
    """script-src 'self' blocks these, so they are dead code that looks alive."""
    found = sorted(
        {f"on{m.group(1)}" for m in INLINE_HANDLER.finditer(html_path.read_text(encoding="utf-8"))}
    )
    assert not found, (
        f"{html_path.name} has inline event handler(s) {found}. The production "
        f"CSP blocks them; bind with addEventListener in the page's JS instead."
    )


def test_copy_buttons_carry_a_data_attribute():
    html = INDEX_HTML.read_text(encoding="utf-8")
    names = re.findall(r'data-copy-rsync="([^"]+)"', html)
    assert names == ["FreeBSD", "NetBSD", "OpenBSD"], (
        f"expected the three mirror buttons to be tagged for binding, got {names}"
    )


def test_main_js_binds_the_copy_buttons():
    js = MAIN_JS.read_text(encoding="utf-8")
    assert "data-copy-rsync" in js, "main.js does not look for the buttons"
    assert "addEventListener" in js
    assert "bindCopyRsyncButtons()" in js, (
        "the binding function is defined but never called from DOMContentLoaded"
    )


# ---------------------------------------------------------------------------
# Behavioural: a real click, in a real browser, under the real policy
# ---------------------------------------------------------------------------
@requires_browser
def test_no_csp_violations_on_load(clicked):
    assert clicked["cspViolations"] == [], (
        "the page raised CSP violations:\n  " + "\n  ".join(clicked["cspViolations"])
    )


@requires_browser
def test_all_three_copy_buttons_are_found(clicked):
    assert [b["dataAttr"] for b in clicked["buttons"]] == ["FreeBSD", "NetBSD", "OpenBSD"]


@requires_browser
@pytest.mark.parametrize("index,mirror", list(enumerate(["FreeBSD", "NetBSD", "OpenBSD"])))
def test_copy_button_responds_to_a_real_click(clicked, index, mirror):
    button = clicked["buttons"][index]
    assert button["onclickAttr"] is None, (
        f"{mirror} button still has an inline onclick, which the CSP blocks"
    )
    assert button["toast"]["shown"], (
        f"clicking the {mirror} button produced no toast; the handler did not run"
    )
    assert f"/{mirror}/" in button["toast"]["text"], (
        f"{mirror} button copied the wrong URL: {button['toast']['text']!r}"
    )


# ---------------------------------------------------------------------------
# Negative control
#
# The behavioural tests above pass if the buttons work. They would also pass if
# the harness silently stopped clicking. Put the bug back and require the
# harness to see it.
# ---------------------------------------------------------------------------
@requires_browser
def test_harness_detects_a_reintroduced_inline_handler(tmp_path):
    docroot = tmp_path / "public"
    shutil.copytree(PUBLIC, docroot)

    html = (docroot / "index.html").read_text(encoding="utf-8")
    reverted = html.replace(
        '<button class="btn btn-secondary" data-copy-rsync="FreeBSD">',
        '<button class="btn btn-secondary" onclick="copyRsync(\'FreeBSD\')">',
        1,
    )
    assert reverted != html, "could not plant the inline handler"
    (docroot / "index.html").write_text(reverted, encoding="utf-8")

    result = run_click_harness(docroot)

    inline = [v for v in result["cspViolations"] if "inline event handler" in v]
    assert inline, (
        "planting an inline onclick raised no CSP violation. Either the harness "
        "is not enforcing the policy or it is not clicking."
    )
    assert not result["buttons"][0]["toast"]["shown"], (
        "the reverted button still worked, so the harness cannot tell a dead "
        "button from a live one"
    )
    # The other two, still bound properly, must keep working -- otherwise the
    # control would also pass if the harness broke outright.
    assert result["buttons"][1]["toast"]["shown"]
    assert result["buttons"][2]["toast"]["shown"]


# ---------------------------------------------------------------------------
# The directive itself, not just harness/nginx agreement
# ---------------------------------------------------------------------------



def _directives(csp: str) -> dict:
    """Split a CSP into {directive: source-list}.

    A directive with no sources (`upgrade-insecure-requests`) maps to "", so
    callers can `.get(name, "")` and test for a source without a length check.
    """
    out = {}
    for part in csp.split(";"):
        part = part.strip()
        if not part:
            continue
        name, _, sources = part.partition(" ")
        out[name] = sources.strip()
    return out

@pytest.mark.skipif(not NGINX_CONF.exists(), reason="nginx/nginx.conf not present")
def test_style_src_does_not_allow_unsafe_inline():
    """'unsafe-inline' in style-src was the price of 24 inline style attributes
    in admin.js and an inline <style> in each error page. Those are gone and
    two other modules keep them gone, so the directive went too.

    test_harness_csp_matches_nginx above only pins the harness to nginx; both
    could drift back together and it would still pass. This asserts the thing
    we actually care about.

    Putting it back re-enables style-context injection: any interpolation that
    reaches a style attribute becomes live CSS again. If some future feature
    genuinely needs inline styles, prefer a hash or nonce over reopening this.
    """
    style_src = _directives(nginx_csp()).get("style-src", "")
    assert "'unsafe-inline'" not in style_src, (
        "style-src has regained 'unsafe-inline': %r. Check what reintroduced an "
        "inline style; the two inline-style guards should have caught it first."
        % style_src
    )
    assert "'self'" in style_src, "style-src must still permit the site's own stylesheets"


@pytest.mark.skipif(not NGINX_CONF.exists(), reason="nginx/nginx.conf not present")
def test_script_src_does_not_allow_unsafe_inline():
    """The same guarantee for scripts, which never had it. Asserted so that
    'just add unsafe-inline' is never the quiet fix for a broken handler."""
    assert "'unsafe-inline'" not in _directives(nginx_csp()).get("script-src", "")
