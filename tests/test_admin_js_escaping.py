"""
Escaping in frontend/public/admin/js/admin.js.

There is no JS test runner in this repo and adding one is not this change's
call to make, so the JavaScript is exercised two ways from here:

  1. Behaviourally, by shelling out to `node tests/js/escaping_harness.mjs`,
     which loads the real admin.js into a vm context and drives the helpers and
     the page renderers with attack strings. See that file for the checks.
  2. Structurally, by parsing admin.js as text in this file, to enforce the
     invariants the tagged template cannot enforce on its own -- chiefly that
     nothing writes to innerHTML except setHtml(), and that no interpolation
     lands in a context the escaper does not cover.

What that does and does not prove is worth being explicit about. It proves the
escaping logic is correct as a string transformation, and that every render
path in admin.js routes attacker-controlled fields through it. It does not
prove browser behaviour: there is no DOM here, so parser quirks (mXSS, foreign
content in svg/math, namespace confusion) are out of scope, as is anything
about how a real engine reparses the result. The mitigation for that class is a
CSP on /admin/, which is devops-sre's and is not in place today.

--- Why a tagged template rather than a render helper -----------------------

The previous design made escaping opt-in: escapeHtml() existed and was called
in the settings and mirror views but not in renderUsers, renderAuditLogs or
Toast.show. Three paths drifted because nothing made drifting fail.

A render helper -- row(cells), table(rows) -- would escape by default too, but
it would mean rewriting 456 lines of markup into function calls. That markup's
appearance belongs to web-designer, so a redesign of it is not the developer's
change to make. It would also be a much larger diff to review for the exact
property being fixed.

html`...` inverts the default without touching the markup: the literal keeps
its shape, gains a five-character prefix, and every ${...} inside it is escaped
unless it is already a SafeHtml. Adding a table row cannot silently reintroduce
the bug, because the raw path no longer exists -- setHtml() takes SafeHtml and
nothing else, so a forgotten tag is a TypeError at the sink instead of an
injection.

--- Why one escaper for both contexts ---------------------------------------

escapeHtml() escapes & < > " ' and backtick, not just the three that matter in
element text. admin.js interpolates into value="..." and class="..." in a dozen
places, and in those a payload needs only a quote:

    " onfocus="alert(1)" autofocus x="

The escaper it replaced was `div.textContent = str; return div.innerHTML`,
which serialises a text node. Per the HTML fragment serialisation algorithm
that escapes &, <, > and U+00A0 only -- quotes are escaped in attribute mode,
not text mode -- so it was a text-context escaper being used in attribute
context at every one of those sites. test_mutation_is_caught's
drop_double_quote_from_escape_set re-creates exactly that hole and asserts the
suite catches it.

Escaping both quote styles is enough for element text and for quoted attribute
values. It is not enough for unquoted attribute values, for URL-bearing
attributes (a javascript: URL survives HTML escaping intact), for on* handlers,
or inside script/style elements. admin.js has none of those; the static tests
below fail if one appears.
"""
import json
import pathlib
import re
import shutil
import subprocess
from html.parser import HTMLParser

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PUBLIC = REPO_ROOT / "frontend" / "public"
ADMIN_JS = REPO_ROOT / "frontend" / "public" / "admin" / "js" / "admin.js"
ADMIN_INDEX = PUBLIC / "admin" / "index.html"
ADMIN_JS_SRC = "/admin/js/admin.js"
MAIN_JS = REPO_ROOT / "frontend" / "public" / "js" / "main.js"
HARNESS = REPO_ROOT / "tests" / "js" / "escaping_harness.mjs"
TOKENS_CSS = REPO_ROOT / "frontend" / "public" / "css" / "tokens.css"

NODE = shutil.which("node")
requires_node = pytest.mark.skipif(
    NODE is None,
    reason="node is not installed; the behavioural escaping checks cannot run",
)


# ---------------------------------------------------------------------------
# Harness driver
# ---------------------------------------------------------------------------
def run_harness(source_path):
    """Run the node harness against `source_path`, return {name: (ok, detail)}."""
    proc = subprocess.run(
        [NODE, str(HARNESS), str(source_path)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, (
        f"harness crashed (rc={proc.returncode})\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    payload = json.loads(proc.stdout)
    return {c["name"]: (c["ok"], c["detail"]) for c in payload["checks"]}


@pytest.fixture(scope="module")
def harness_results():
    return run_harness(ADMIN_JS)


# ---------------------------------------------------------------------------
# Behaviour: the real admin.js
# ---------------------------------------------------------------------------
# Named individually so a failure names the property that broke, rather than
# "the JS tests failed".
HARNESS_CHECKS = [
    "escapeHtml escapes all six metacharacters",
    "escapeHtml escapes every occurrence, not just the first",
    "escapeHtml renders 0 and false, blanks only null/undefined",
    "html`` escapes payloads in element-text context",
    "html`` escapes payloads in double-quoted attribute context",
    "html`` escapes payloads in single-quoted attribute context",
    "html`` escapes payloads in class= alongside a static prefix",
    "html`` escapes a payload in the final interpolation slot",
    "html`` escapes a payload in the first interpolation slot",
    "html`` preserves the static markup around interpolations",
    "html`` composes without double-escaping nested SafeHtml",
    "html`` interpolates arrays of SafeHtml",
    "html`` renders an empty array as nothing",
    "html`` escapes a plain string that contains markup",
    "setHtml rejects a plain string",
    "setHtml accepts SafeHtml and writes the escaped value",
    "trustedHtml is the only bypass and returns SafeHtml",
    "renderUsers escapes username and email end-to-end",
    "renderAuditLogs escapes username, resource and ip end-to-end",
    "renderAuditLogs escapes an unmapped action string",
    "renderMirrors escapes name, url_path and status end-to-end",
    "renderSettings escapes setting values in attribute context",
    "renderLayout escapes the logged-in username in the sidebar",
    "renderLayout renders exactly one theme toggle button",
    "renderLoginPage renders exactly one theme toggle button",
    "DISK_USAGE_CRITICAL_PERCENT is defined and equals 95",
    "renderLayout gives every nav-item a literal href of # plus its data-nav",
    "renderLayout sets aria-current=page on the current nav-item and false on the rest",
    "renderLayout toast container carries role=status and aria-live=polite",
    "renderLoginPage renders one toastContainer with role=status and aria-live=polite",
    "renderLayout gives #modal role=dialog aria-modal=true and aria-labelledby=modalTitle",
    "Toast.show escapes a hostile server error string",
    "Modal.show escapes a hostile title and trusts SafeHtml body",
    "Modal.show gives its title id=modalTitle for aria-labelledby",
    "Toast.show adds is-leaving instead of writing a style",
    "showAddUser gives every label a for= matching an input id in the form",
    "editUser gives every label a for= matching an input id in the form",
    "filesDeletedBadge marks a count at the large-deletion threshold",
    "filesDeletedBadge leaves a count below the threshold unmarked",
    "renderDashboard escapes recent activity action and sync status end-to-end",
    "renderDashboard shows free disk space and flags high usage as a warning",
    "renderSyncFailures escapes error_message and mirror name end-to-end",
    "renderSyncFailures shows a placeholder when there are no incidents",
    "renderProtectedPaths escapes pattern text and mirror names end-to-end",
    "renderProtectedPaths shows every mirror type even when none are configured",
    "renderProtectedPaths escapes a hostile architecture directory name in an "
    "archive-inventory location end-to-end",
    "renderProtectedPaths shows an inventory error but still renders the pattern list "
    "when the archive-inventory fetch fails",
    "renderProtectedPaths shows a per-mirror unavailable state without a 500",
    "renderProtectedPaths escapes hostile names in current/unclassified/errors end-to-end",
    "renderHealthChecksCard escapes bad, skipped, warning and ok entries end-to-end",
    "renderHealthChecksCard renders unknown when given no data",
    "renderDashboard renders the health-checks card end-to-end via its own fetch",
    "renderDashboard shows the health-checks card as unknown, not a false all-clear, when that fetch fails",
    "renderLayout renders the sidebar mark and wordmark",
    "renderLoginPage renders the mark",
    "renderLayout gives every nav-item an icon span naming the right icon",
    "renderLayout gives the logout button an icon-log-out span",
    "renderDashboard tile icons name mirrors, check, sync, users and disk",
    "renderSyncFailures tile icons name close and check",
    "renderHealthChecksCard gives every row an icon wrapper with the right modifier and icon",
    "renderDashboard activity rows carry the mapped icon for every action, including the default",
    "Toast.show renders an icon span for success, error and info",
    "Modal.show renders a close button with an icon-close span and aria-label",
    "renderUsers Add User button carries an icon-plus span",
    "every icon span rendered anywhere names a file under img/icons/",
    "renderMirrors renders the status pill with no inner span",
    "renderDashboard renders a Recent Sync Jobs pill with no inner span",
    "viewSyncLogs shows the status as a pill and drops the title emoji prefix",
    "viewMirror renders each history row status as a pill instead of an emoji",
    "renderDashboard shows the disk meter at is-warn, at is-crit and never for an unknown percentage",
    "renderMirrors, renderSyncFailures, renderProtectedPaths, renderUsers, renderAuditLogs and "
    "renderSettings mark numeric and time cells with class=num",
    "releaseTagBadges renders At risk with no emoji",
    "admin.js no longer names status-dot anywhere",
    "no rendered view contains an emoji or symbol glyph beyond the allowed dashes and ellipsis",
    "renderDashboard gives Recent Sync Jobs pills a class from the job-status allowlist only",
    "viewSyncLogs gives the status pill a class from the job-status allowlist only",
    "viewMirror gives each history row pill a class from the job-status allowlist only",
    "renderMirrors gives the status pill a class from the mirror-status allowlist only",
    "renderDashboard draws the disk meter only for a finite percentage and clamps its fill to 0-100",
    "renderDashboard picks the disk meter band from the raw percentage and rounds only the fill width",
    "router.navigate sends an inherited key to the dashboard and render() does not throw",
    "renderDashboard gives an inherited activity action the default icon and plain text",
    "renderHealthChecksCard shows an inherited state as the neutral badge with its own text",
    "renderProtectedPaths shows an inherited protection value as the neutral pill",
    "renderAuditLogs shows an inherited action name as plain text",
    "Modal.show moves focus to the close button and Modal.close hands it back to the opener",
    "Modal.show retries the focus once a frame until the dialog is visible, and a close cancels the retry",
    "Modal.show keeps the first opener when it is shown again while open, and never refocuses a detached one",
    "router.render brings the active nav-item into view when it can, and runs without it",
    "every <table> a rendered view emits sits inside a .table-container",
]


@requires_node
@pytest.mark.parametrize("check_name", HARNESS_CHECKS)
def test_escaping_behaviour(harness_results, check_name):
    assert (
        check_name in harness_results
    ), f"harness did not run {check_name!r}; it reported {sorted(harness_results)}"
    ok, detail = harness_results[check_name]
    assert ok, detail


@requires_node
def test_harness_check_list_is_complete(harness_results):
    """The parametrised list must not drift behind the harness."""
    assert sorted(harness_results) == sorted(HARNESS_CHECKS)


# ---------------------------------------------------------------------------
# Mutation testing
#
# Same approach as the rsync classifier tests: break the helper on purpose and
# require the suite to notice. A test that passes against a deliberately broken
# escaper is not testing the escaper.
#
# (name, old, new, must_fail) -- must_fail names one check that has to go red,
# so a mutation cannot be "caught" by some unrelated assertion.
# ---------------------------------------------------------------------------
# fmt: off
MUTATIONS = [
    (
        "drop_double_quote_from_escape_set",
        """return String(value).replace(/[&<>"'`]/g, (ch) => HTML_ESCAPES[ch]);""",
        """return String(value).replace(/[&<>'`]/g, (ch) => HTML_ESCAPES[ch]);""",
        "html`` escapes payloads in double-quoted attribute context",
    ),
    (
        "drop_single_quote_from_escape_set",
        """return String(value).replace(/[&<>"'`]/g, (ch) => HTML_ESCAPES[ch]);""",
        """return String(value).replace(/[&<>"`]/g, (ch) => HTML_ESCAPES[ch]);""",
        "html`` escapes payloads in single-quoted attribute context",
    ),
    (
        "drop_ampersand_from_escape_set",
        """return String(value).replace(/[&<>"'`]/g, (ch) => HTML_ESCAPES[ch]);""",
        """return String(value).replace(/[<>"'`]/g, (ch) => HTML_ESCAPES[ch]);""",
        "escapeHtml escapes all six metacharacters",
    ),
    (
        # The bug class this mutation guards against: an escape that stops in
        # the wrong place. Without /g only the first metacharacter is replaced.
        "drop_global_regex_flag",
        """return String(value).replace(/[&<>"'`]/g, (ch) => HTML_ESCAPES[ch]);""",
        """return String(value).replace(/[&<>"'`]/, (ch) => HTML_ESCAPES[ch]);""",
        "escapeHtml escapes every occurrence, not just the first",
    ),
    (
        "reintroduce_falsy_guard",
        "    if (value === null || value === undefined) return '';",
        "    if (!value) return '';",
        "escapeHtml renders 0 and false, blanks only null/undefined",
    ),
    (
        # Interpolation trusts plain strings -- i.e. the tag does nothing.
        "interpolate_trusts_plain_strings",
        "    return escapeHtml(value);\n}",
        "    return String(value);\n}",
        "html`` escapes payloads in element-text context",
    ),
    (
        # Off-by-one: stop one value early. Every literal whose last ${} is
        # trusted still looks correct.
        "html_loop_stops_one_value_early",
        "    for (let i = 0; i < values.length; i++) {",
        "    for (let i = 0; i < values.length - 1; i++) {",
        "html`` escapes a payload in the final interpolation slot",
    ),
    (
        # Off-by-one the other way: skip the first value.
        "html_loop_skips_first_value",
        "    for (let i = 0; i < values.length; i++) {",
        "    for (let i = 1; i < values.length; i++) {",
        "html`` escapes a payload in the first interpolation slot",
    ),
    (
        "html_drops_leading_static_chunk",
        "    let out = strings[0];",
        "    let out = '';",
        "html`` preserves the static markup around interpolations",
    ),
    (
        "interpolate_stops_handling_arrays",
        "    if (Array.isArray(value)) return value.map(interpolateHtml).join('');\n",
        "",
        "html`` interpolates arrays of SafeHtml",
    ),
    (
        "interpolate_stops_passing_through_safehtml",
        "    if (value instanceof SafeHtml) return value.value;\n",
        "",
        "html`` composes without double-escaping nested SafeHtml",
    ),
    (
        # The structural guard: if setHtml takes anything, a forgotten html``
        # tag silently injects again.
        "setHtml_accepts_plain_strings",
        "    if (!(content instanceof SafeHtml)) {\n"
        "        throw new TypeError('setHtml() requires html`...`, got ' + typeof content);\n"
        "    }\n"
        "    el.innerHTML = content.value;",
        "    el.innerHTML = String(content);",
        "setHtml rejects a plain string",
    ),
]
# fmt: on


@requires_node
@pytest.mark.parametrize("name,old,new,must_fail", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_mutation_is_caught(tmp_path, name, old, new, must_fail):
    source = ADMIN_JS.read_text(encoding="utf-8")
    assert source.count(old) == 1, (
        f"mutation {name!r} no longer matches admin.js exactly once "
        f"(found {source.count(old)}). Update the mutation, do not delete it."
    )

    mutated = tmp_path / "admin.js"
    mutated.write_text(source.replace(old, new), encoding="utf-8")

    results = run_harness(mutated)
    failed = sorted(n for n, (ok, _) in results.items() if not ok)
    assert failed, (
        f"mutation {name!r} broke the escaper and every check still passed. "
        f"The suite does not test what it claims to."
    )
    assert must_fail in failed, (
        f"mutation {name!r} was expected to fail {must_fail!r}, " f"but the failures were {failed}"
    )


# ---------------------------------------------------------------------------
# Structural invariants (no node required)
# ---------------------------------------------------------------------------
TAG_OPEN = re.compile(r"<[a-zA-Z/]")
ATTR_ASSIGN = re.compile(r"""([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*["']""")

# Attributes where HTML-escaping is not sufficient protection. A javascript:
# URL contains no HTML metacharacter, so href="${x}" is exploitable however
# well x is escaped; style="" is a CSS context; on* is a script context.
UNSAFE_ATTRS = {
    "href",
    "src",
    "action",
    "formaction",
    "srcdoc",
    "data",
    "xlink:href",
    "style",
    "background",
    "poster",
}

# Assembled rather than written literally so this file does not itself trip a
# "code calls a dangerous HTML sink" scanner. These are names to match.
OTHER_SINKS = [
    "insertAdjacentHTML",
    "outerHTML",
    ".".join(("document", "write")),
    "createContextualFragment",
]


# ---------------------------------------------------------------------------
# Comment stripping
#
# Every scanner below reads admin.js as text, so comments have to go first --
# this file's own documentation mentions `<script>` and ` onfocus=` as examples
# of what must not appear, and a scanner that cannot tell code from prose would
# flag them.
#
# Stripping comments from JavaScript needs a real lexer, not a regex. admin.js
# contains all three constructs that defeat the naive version:
#
#   admin.js:745   //  inside a template literal (rsync://mirror.example.com/)
#   admin.js:800   //  inside a regex literal    (/^(rsync|https?):\/\//)
#   admin.js:801   //  inside a string           ('...http://, or https://')
#
# Comment bodies are replaced with spaces rather than removed, so every byte
# offset and line number in the stripped copy still matches the real file.
# ---------------------------------------------------------------------------

# A '/' starts a regex literal, rather than division, when the previous
# significant character cannot end an expression.
_REGEX_MAY_FOLLOW = set("(,=:[!&|?{};+-*%~^<>") | {""}


def strip_js_comments(source):
    """Blank out // and /* */ comments, preserving length and line numbering."""
    out = list(source)
    i, n = 0, len(source)
    state = "code"
    stack = []  # nesting of template literals and their ${} holes
    prev = ""  # last significant code character

    while i < n:
        c = source[i]
        nxt = source[i + 1] if i + 1 < n else ""

        if state == "code":
            if c == "/" and nxt == "/":
                out[i] = out[i + 1] = " "
                i += 2
                state = "line"
            elif c == "/" and nxt == "*":
                out[i] = out[i + 1] = " "
                i += 2
                state = "block"
            elif c == "/" and prev in _REGEX_MAY_FOLLOW:
                i += 1
                state = "regex"
            elif c == "'":
                i += 1
                state = "sq"
            elif c == '"':
                i += 1
                state = "dq"
            elif c == "`":
                stack.append("tpl")
                i += 1
                state = "tpl"
            elif c == "}" and stack and stack[-1] == "hole":
                stack.pop()
                i += 1
                state = "tpl"
            else:
                if not c.isspace():
                    prev = c
                i += 1

        elif state == "line":
            if c == "\n":
                state = "code"
                i += 1
            else:
                out[i] = " "
                i += 1

        elif state == "block":
            if c == "*" and nxt == "/":
                out[i] = out[i + 1] = " "
                i += 2
                state = "code"
            else:
                if c != "\n":
                    out[i] = " "
                i += 1

        elif state in ("sq", "dq", "regex"):
            closer = {"sq": "'", "dq": '"', "regex": "/"}[state]
            if c == "\\":
                i += 2
            elif c == closer:
                prev = closer
                i += 1
                state = "code"
            elif c == "\n" and state != "regex":
                # Unterminated string; bail back to code rather than run away.
                state = "code"
                i += 1
            else:
                i += 1

        elif state == "tpl":
            if c == "\\":
                i += 2
            elif c == "$" and nxt == "{":
                stack.append("hole")
                i += 2
                state = "code"
            elif c == "`":
                stack.pop()
                prev = "`"
                i += 1
                state = "tpl" if stack and stack[-1] == "tpl" else "code"
            else:
                i += 1

    return "".join(out)


def admin_js_source():
    """admin.js with comments blanked out."""
    return strip_js_comments(ADMIN_JS.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Every script the console loads
#
# admin/index.html loads /js/theme-init.js ahead of its stylesheets as well as
# admin.js (spec 6.2), and both run in the authenticated console. The sink,
# style and inline-handler guards below used to read admin.js alone, so a
# write in theme-init.js was nobody's business. The set they scan is the
# page's own <script src> list, read with an HTML parser, so a script added to
# the page is scanned without anyone remembering to add it here.
# ---------------------------------------------------------------------------
class _ScriptTags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.srcs = []  # one entry per <script>: its src, or None when it has none

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.srcs.append(dict(attrs).get("src"))


def script_srcs(page_html):
    """The src of every <script> in a page, in document order.

    A script the guards cannot read from this checkout -- an inline one,
    another origin's, a path relative to the page -- fails here, so none is
    quietly left out of the scan.
    """
    tags = _ScriptTags()
    tags.feed(page_html)
    for src in tags.srcs:
        assert (
            src is not None
        ), "an inline <script>: script-src 'self' blocks it, and no guard here reads it"
        assert src.startswith("/") and not src.startswith(
            "//"
        ), f"<script src={src!r}> is not a path on this origin; the guards read this checkout"
    return tags.srcs


def console_script_path(src):
    """Where a <script src> from admin/index.html lives in this checkout.

    admin.js resolves through ADMIN_JS, which the planted-defect controls patch.
    """
    return ADMIN_JS if src == ADMIN_JS_SRC else PUBLIC / src.lstrip("/")


def console_script_sources():
    """{src: source with comments blanked} for every script the console loads."""
    return {
        src: strip_js_comments(console_script_path(src).read_text(encoding="utf-8"))
        for src in script_srcs(ADMIN_INDEX.read_text(encoding="utf-8"))
    }


def line_of(source, index):
    return source.count("\n", 0, index) + 1


def interpolations(source):
    """Yield (line, expression, context) for every ${...} in the file.

    context is 'text' (element content or a plain JS string), 'attr:<name>'
    (inside a quoted attribute value) or 'bare-tag' (inside a tag but not
    inside a quoted value).
    """
    for m in re.finditer(r"\$\{", source):
        i = m.start()

        depth, j = 0, i + 1
        while j < len(source):
            if source[j] == "{":
                depth += 1
            elif source[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        expr = source[i + 2 : j]

        # Nearest real tag opener before us, vs the nearest tag close. A bare
        # '<' in JS (`diffMins < 60`) is not a tag opener, hence [a-zA-Z/].
        opens = [t.start() for t in TAG_OPEN.finditer(source, 0, i)]
        last_open = opens[-1] if opens else -1
        last_close = source.rfind(">", 0, i)

        if last_open <= last_close:
            yield line_of(source, i), expr, "text"
            continue

        segment = source[last_open:i]
        in_quoted = segment.count('"') % 2 == 1 or segment.count("'") % 2 == 1
        if not in_quoted:
            yield line_of(source, i), expr, "bare-tag"
            continue

        assigns = ATTR_ASSIGN.findall(segment)
        yield line_of(source, i), expr, "attr:" + (assigns[-1].lower() if assigns else "?")


def test_only_set_html_writes_innerhtml():
    """innerHTML must have exactly one writer, and it must be setHtml()."""
    source = admin_js_source()
    writes = [line_of(source, m.start()) for m in re.finditer(r"\.innerHTML\s*=", source)]
    assert len(writes) == 1, f"expected 1 innerHTML write, found them on lines {writes}"

    # ...and it must live inside setHtml, not somewhere that merely mentions it.
    body_start = source.index("function setHtml(")
    body_end = source.index("\n}", body_start)
    assert (
        body_start < source.index(".innerHTML =") < body_end
    ), "the innerHTML write is outside setHtml()"


# Assembled rather than written literally, like OTHER_SINKS above: this file
# names the property only to match it.
HTML_PROPERTY = "inner" + "HTML"


def test_no_other_console_script_touches_the_html_property():
    """The sink test above pins admin.js to exactly one writer, setHtml().
    Every other script the console loads gets none: the property is not named
    in it at all, as a read, a write or a computed key."""
    for src, source in console_script_sources().items():
        if src == ADMIN_JS_SRC:
            continue
        assert HTML_PROPERTY not in source, f"{src} names {HTML_PROPERTY}, which bypasses setHtml()"


def test_no_other_html_sinks():
    for src, source in console_script_sources().items():
        for sink in OTHER_SINKS:
            assert sink not in source, f"{sink} in {src} bypasses setHtml()"


# Every way JavaScript can set an element's style. The CSP is style-src 'self'
# with no 'unsafe-inline', which blocks the style attribute however a script
# sets it, and the console's rule is that it needs none: a state is a class.
STYLE_WRITES = [
    # el.style.x = ..., el.style = ..., el.style[...] = ..., el.style.cssText,
    # el.style.setProperty(...), Object.assign(el.style, ...), el?.style: every
    # one of them names the member `.style`. `.styleSheets` does not match.
    ("a .style member", re.compile(r"\.style\b")),
    ("a ['style'] member", re.compile(r"""\[\s*['"`]style['"`]\s*\]""")),
    ("attributeStyleMap", re.compile(r"attributeStyleMap")),
    ("setAttribute('style', ...)", re.compile(r"""setAttribute\(\s*['"`]style['"`]""")),
    (
        "setAttributeNS(ns, 'style', ...)",
        re.compile(r"""setAttributeNS\(\s*[^,()]*,\s*['"`]style['"`]"""),
    ),
]


def style_writes(source):
    """[(line, form)] for every way `source` can set an element's style."""
    hits = []
    for form, pattern in STYLE_WRITES:
        hits += [(line_of(source, m.start()), form) for m in pattern.finditer(source)]
    return sorted(hits)


def test_no_style_property_writes():
    """No script the console loads writes an element's style anywhere. The
    toast's animation is a class, is-leaving, applied through classList -- not
    a CSSOM assignment -- so a style-src 'self' policy with no 'unsafe-inline'
    has nothing to block here. Reads of .style count too: nothing needs one."""
    found = {
        src: hits
        for src, source in console_script_sources().items()
        if (hits := style_writes(source))
    }
    assert not found, f"element style written at {found}; use a class instead"


def test_no_template_literal_join_remains():
    """`).join('') was how arrays were flattened before; it must not come back.

    Joining SafeHtml objects produces a plain string, which html`` then escapes
    -- so a stray .join('') is a rendering bug, and it is exactly the shape
    someone reaches for when an array does not render.
    """
    assert "`).join('')" not in admin_js_source(), "a template-literal .map().join('') survived"


def test_no_double_escaping_call_sites():
    """escapeHtml() inside an html`` literal would escape twice."""
    assert (
        "${escapeHtml(" not in admin_js_source()
    ), "explicit escapeHtml() inside an interpolation double-escapes; html`` already escapes"


def test_every_interpolation_lands_in_a_context_the_escaper_covers():
    offenders = []
    for line, expr, context in interpolations(admin_js_source()):
        if not context.startswith("attr:"):
            continue
        name = context.split(":", 1)[1]
        if name in UNSAFE_ATTRS or name.startswith("on"):
            offenders.append((line, name, expr.strip()))
    assert not offenders, (
        "interpolation into an attribute HTML-escaping does not protect:\n"
        + "\n".join(f'  admin.js:{ln}  {n}="${{{e}}}"' for ln, n, e in offenders)
    )


def test_bare_in_tag_interpolations_are_static_literals():
    """Unquoted positions inside a tag must not carry server data.

    escapeHtml() does not escape space, tab, newline, '=' or '/', so an
    unquoted attribute value is not made safe by it. The only interpolations
    allowed in that position are ternaries between string literals -- the
    `? 'selected' : ''` pattern on the settings and edit-user <option>s.
    """
    literal_ternary = re.compile(r"^.*\?\s*'([^']*)'\s*:\s*'([^']*)'$", re.S)
    offenders = []
    for line, expr, context in interpolations(admin_js_source()):
        if context != "bare-tag":
            continue
        m = literal_ternary.match(expr.strip())
        if not m or any(c in m.group(1) + m.group(2) for c in "<>\"'&= \t\n/"):
            offenders.append((line, expr.strip()))
    assert not offenders, (
        "unquoted in-tag interpolation that is not a static literal ternary:\n"
        + "\n".join(f"  admin.js:{ln}  ${{{e}}}" for ln, e in offenders)
    )


def test_bare_in_tag_scan_actually_finds_the_known_sites():
    """Guard the scanner itself: if it silently matched nothing, it proves nothing."""
    bare = [c for _, _, c in interpolations(admin_js_source()) if c == "bare-tag"]
    assert len(bare) == 7, (
        f"expected the 7 `? 'selected' : ''` option ternaries, found {len(bare)}. "
        f"If markup changed legitimately, update this count."
    )


def test_interpolation_scan_covers_the_attribute_sites():
    """Guard the scanner: the known attribute interpolations must be classified."""
    contexts = [c for _, _, c in interpolations(admin_js_source())]
    attrs = sorted({c.split(":", 1)[1] for c in contexts if c.startswith("attr:")})
    assert (
        "value" in attrs and "class" in attrs and "data-id" in attrs
    ), f"scanner failed to classify the known attribute sites; saw {attrs}"


def test_no_inline_event_handlers_in_markup():
    """admin.js dispatches via delegation on [data-action]; on* must stay absent
    from it and from every other script the console loads."""
    found = {}
    for src, source in console_script_sources().items():
        # \s prefix so data-action= and similar attribute names do not match.
        names = sorted({m.group(1) for m in re.finditer(r"\son([a-z]{3,})\s*=", source)})
        if names:
            found[src] = names
    assert not found, f"inline event handler attribute(s) in markup: {found}"


def test_no_interpolation_into_script_or_style_elements():
    for src, source in console_script_sources().items():
        for tag in ("script", "style"):
            assert (
                f"<{tag}" not in source
            ), f"a <{tag}> element in {src} is a context escapeHtml() does not cover"


def test_the_scan_covers_theme_init_and_admin_js():
    """The guards above are only as wide as the set they loop over: if the page
    parser quietly returned nothing, every one of them would pass over no file."""
    sources = console_script_sources()
    assert "/js/theme-init.js" in sources, "the scan no longer reaches theme-init.js"
    assert ADMIN_JS_SRC in sources, "the scan no longer reaches admin.js"
    assert all(source.strip() for source in sources.values()), "a scanned script read as empty"


def test_script_srcs_lists_a_pages_scripts_in_order():
    page = '<script src="/a.js"></script><p>x</p><script src="/b/c.js" defer></script>'
    assert script_srcs(page) == ["/a.js", "/b/c.js"]


@pytest.mark.parametrize(
    "script",
    [
        "<script>var x = 1;</script>",
        "<script src></script>",
        '<script src="https://cdn.example/x.js"></script>',
        '<script src="//cdn.example/x.js"></script>',
        '<script src="js/x.js"></script>',
    ],
    ids=["inline", "no_value", "another_origin", "protocol_relative", "relative_to_the_page"],
)
def test_script_srcs_refuses_a_script_it_cannot_scan(script):
    with pytest.raises(AssertionError):
        script_srcs(f"<html><body>{script}</body></html>")


# One snippet per way of setting a style that the scan must see.
STYLE_WRITE_FORMS = [
    "el.style.color = 'red';",
    "el.style = 'color: red';",
    "el.style['color'] = 'red';",
    "Object.assign(el.style, { color: 'red' });",
    "el.attributeStyleMap.set('color', 'red');",
    "el.setAttribute('style', 'color: red');",
    'el.setAttribute("style", "color: red");',
    "el.setAttributeNS(null, 'style', 'color: red');",
    "el?.style.setProperty('color', 'red');",
    "el['style'].cssText = 'color: red';",
]


@pytest.mark.parametrize("snippet", STYLE_WRITE_FORMS)
def test_the_style_scan_sees_every_form_of_write(snippet):
    assert style_writes(snippet), f"{snippet!r} sets a style and the scan does not see it"


def test_the_style_scan_leaves_alone_what_is_not_a_write():
    clean = (
        "getComputedStyle(el); document.styleSheets; el.classList.add('is-leaving'); "
        "el.setAttribute('class', 'style'); el.setAttribute('data-style', 'x');"
    )
    assert style_writes(clean) == []


# ---------------------------------------------------------------------------
# CSS custom properties read from JavaScript
#
# Neither file reads a var(--token) any more: admin.js's inline styles moved
# into classes, and main.js's last reads went with its .pulse writes (spec
# section 5.2). The check stays for any read either file adds: a token
# defined nowhere silently falls back to the inherited value, or to the
# literal fallback -- which pins one theme's colour in both themes.
# ---------------------------------------------------------------------------
CSS_VAR_READ = re.compile(r"var\(\s*(--[a-zA-Z0-9-]+)")


def defined_tokens():
    css = TOKENS_CSS.read_text(encoding="utf-8")
    return set(re.findall(r"^\s*(--[a-zA-Z0-9-]+)\s*:", css, re.M))


@pytest.mark.parametrize("js_path", [ADMIN_JS, MAIN_JS], ids=["admin.js", "main.js"])
def test_css_custom_properties_read_from_js_are_defined(js_path):
    defined = defined_tokens()
    source = js_path.read_text(encoding="utf-8")
    undefined = sorted({name for name in CSS_VAR_READ.findall(source) if name not in defined})
    assert not undefined, (
        f"{js_path.name} reads CSS custom propert(ies) that tokens.css does not "
        f"define: {undefined}. An undefined var() resolves to the inherited "
        f"value, or pins the literal fallback across both themes."
    )


# ---------------------------------------------------------------------------
# The comment stripper is itself a helper the scanners depend on, so it gets
# the same treatment: if it silently ate a template literal or kept a comment,
# every scanner above would quietly stop proving anything.
# ---------------------------------------------------------------------------
# Comment bodies become spaces rather than vanishing, so expectations spell the
# width out rather than hand-counting it.
LEXER_CASES = [
    (
        "line comment goes",
        "a; // <script> onfocus=x\nb;",
        "a; " + " " * len("// <script> onfocus=x") + "\nb;",
    ),
    ("block comment goes", "a;/* <script> */b;", "a;" + " " * len("/* <script> */") + "b;"),
    (
        "block comment keeps newlines",
        "a;/* x\ny */b;",
        "a;" + " " * len("/* x") + "\n" + " " * len("y */") + "b;",
    ),
    ("double slash in a string survives", "x('http://a');", "x('http://a');"),
    ("double slash in a template literal survives", "x(`u rsync://a/b`);", "x(`u rsync://a/b`);"),
    ("double slash in a regex survives", r"m(/^a:\/\//);", r"m(/^a:\/\//);"),
    ("star slash in a string survives", "x('/* not a comment');", "x('/* not a comment');"),
    ("division is not a regex", "a = b / c; // z\n", "a = b / c; " + " " * len("// z") + "\n"),
    ("nested template hole survives", "x(`a${b(`c//d`)}e`);", "x(`a${b(`c//d`)}e`);"),
    ("comment inside a template hole goes", "x(`a${/* z */b}c`);", "x(`a${       b}c`);"),
    ("escaped backtick does not end the literal", "x(`a\\`//b`);", "x(`a\\`//b`);"),
]


@pytest.mark.parametrize(
    "name,src,expected", LEXER_CASES, ids=[c[0].replace(" ", "_") for c in LEXER_CASES]
)
def test_strip_js_comments(name, src, expected):
    got = strip_js_comments(src)
    assert got == expected, f"{name}: {got!r} != {expected!r}"
    assert len(got) == len(src), "offsets must be preserved"


def test_strip_js_comments_preserves_offsets_on_the_real_file():
    raw = ADMIN_JS.read_text(encoding="utf-8")
    stripped = strip_js_comments(raw)
    assert len(stripped) == len(raw)
    assert stripped.count("\n") == raw.count("\n")
    # Code survived...
    assert "function escapeHtml(value) {" in stripped
    assert "rsync://mirror.example.com/FreeBSD/" in stripped
    assert r"/^(rsync|https?):\/\//" in stripped
    # ...and prose did not.
    assert "Single Page Application" not in stripped


# ---------------------------------------------------------------------------
# Negative controls for the structural scanners.
#
# A scanner that finds nothing passes whether or not it works. Each case below
# plants the exact defect a scanner exists to catch into a copy of admin.js and
# requires that scanner to fail on it.
# ---------------------------------------------------------------------------
NEGATIVE_CONTROLS = [
    (
        "second_innerhtml_writer",
        "function setHtml(el, content) {",
        "function unsafeRender(el, s) {\n    el.innerHTML = s;\n}\n\n"
        "function setHtml(el, content) {",
        "test_only_set_html_writes_innerhtml",
    ),
    (
        "insertadjacenthtml_sink",
        "function setHtml(el, content) {",
        "function unsafeRender(el, s) {\n    el.insertAdjacentHTML('beforeend', s);\n}\n\n"
        "function setHtml(el, content) {",
        "test_no_other_html_sinks",
    ),
    (
        "interpolation_into_href",
        '<a href="/" class="btn btn-secondary btn-sm" target="_blank">',
        '<a href="${mirror.url_path}" class="btn btn-secondary btn-sm" target="_blank">',
        "test_every_interpolation_lands_in_a_context_the_escaper_covers",
    ),
    (
        "unquoted_attribute_value",
        "<td><code>${log.ip_address || '--'}</code></td>",
        "<td><code data-ip=${log.ip_address}>x</code></td>",
        "test_bare_in_tag_interpolations_are_static_literals",
    ),
    (
        "inline_event_handler",
        '<button class="modal-close" data-action="closeModal" aria-label="Close">',
        '<button class="modal-close" onclick="Modal.close()" data-action="closeModal" aria-label="Close">',
        "test_no_inline_event_handlers_in_markup",
    ),
    (
        "reintroduced_template_join",
        "                        `)}\n                    </tbody>",
        "                        `).join('')}\n                    </tbody>",
        "test_no_template_literal_join_remains",
    ),
    (
        "reintroduced_explicit_escape_call",
        "<td><strong>${user.username}</strong></td>",
        "<td><strong>${escapeHtml(user.username)}</strong></td>",
        "test_no_double_escaping_call_sites",
    ),
    (
        "style_assignment",
        "function setHtml(el, content) {",
        "function paint(el) {\n    el.style = 'display: none';\n}\n\n"
        "function setHtml(el, content) {",
        "test_no_style_property_writes",
    ),
    (
        "style_attribute_set_from_script",
        "function setHtml(el, content) {",
        "function paint(el) {\n    el.setAttribute('style', 'display: none');\n}\n\n"
        "function setHtml(el, content) {",
        "test_no_style_property_writes",
    ),
]


@pytest.mark.parametrize(
    "name,old,new,scanner",
    NEGATIVE_CONTROLS,
    ids=[c[0] for c in NEGATIVE_CONTROLS],
)
def test_scanner_catches_planted_defect(tmp_path, monkeypatch, name, old, new, scanner):
    source = ADMIN_JS.read_text(encoding="utf-8")
    assert source.count(old) >= 1, (
        f"negative control {name!r} no longer matches admin.js. "
        f"Update the control, do not delete it."
    )

    planted = tmp_path / "admin.js"
    planted.write_text(source.replace(old, new, 1), encoding="utf-8")
    monkeypatch.setattr("tests.test_admin_js_escaping.ADMIN_JS", planted)

    with pytest.raises(AssertionError):
        globals()[scanner]()


# ---------------------------------------------------------------------------
# The same controls for the other script the console loads.
#
# The guards loop over every <script src> in admin/index.html, so a defect in
# theme-init.js has to fail them too. Each defect below is appended to a copy of
# that file, which the scanners then read in place of the real one, and the
# failure has to name the file: it is that copy tripping the guard, not
# something else about the page.
# ---------------------------------------------------------------------------
THEME_INIT_SRC = "/js/theme-init.js"
THEME_INIT_CONTROLS = [
    (
        "html_property_write",
        f"document.body.{HTML_PROPERTY} = window.location.hash;",
        "test_no_other_console_script_touches_the_html_property",
    ),
    (
        "insert_adjacent_html",
        "document.body.insertAdjacentHTML('beforeend', window.location.hash);",
        "test_no_other_html_sinks",
    ),
    (
        "style_assignment",
        "document.documentElement.style = 'display: none';",
        "test_no_style_property_writes",
    ),
    (
        "style_attribute_set_from_script",
        "document.documentElement.setAttribute('style', 'display: none');",
        "test_no_style_property_writes",
    ),
    (
        "inline_handler_in_markup",
        "var markup = '<img src=x onerror=alert(1)>';",
        "test_no_inline_event_handlers_in_markup",
    ),
    (
        "script_element_in_markup",
        "var markup = '<script src=//evil.example/x.js></script>';",
        "test_no_interpolation_into_script_or_style_elements",
    ),
]


@pytest.mark.parametrize(
    "name,defect,scanner",
    THEME_INIT_CONTROLS,
    ids=[c[0] for c in THEME_INIT_CONTROLS],
)
def test_scanner_catches_a_defect_planted_in_theme_init(
    tmp_path, monkeypatch, name, defect, scanner
):
    original = console_script_path
    planted = tmp_path / "theme-init.js"
    planted.write_text(
        original(THEME_INIT_SRC).read_text(encoding="utf-8") + "\n" + defect + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "tests.test_admin_js_escaping.console_script_path",
        lambda src: planted if src == THEME_INIT_SRC else original(src),
    )

    with pytest.raises(AssertionError, match="theme-init"):
        globals()[scanner]()
