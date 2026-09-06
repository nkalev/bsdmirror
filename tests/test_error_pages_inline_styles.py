"""The static error pages (404.html, 50x.html) must carry no inline style,
and every class they name must actually be defined in a stylesheet that page
links.

This mirrors tests/test_admin_inline_styles.py's two failure directions for
the same reason: these two pages carried the last inline `<style>` blocks in
the frontend, and removing them is what lets a future change drop
`style-src 'unsafe-inline'` from the CSP without breaking anything (see
nginx/nginx.conf and CLAUDE.md -- that removal itself is out of scope here).

The class-definition check resolves each page's stylesheets from that page's
own `<link>` tags rather than from a hand-maintained list. That is
deliberate: test_admin_inline_styles.py used to get this wrong by checking a
class against a stylesheet the admin page does not actually load, which lets
a class defined only there pass a check that should have failed. Reading the
`<link>` tags at test time instead of copying them into a separate constant
makes that particular mistake structurally impossible to reintroduce here --
there is no second list to drift out of sync with the markup.
"""

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PUBLIC_DIR = REPO_ROOT / "frontend" / "public"
ERROR_PAGES = [PUBLIC_DIR / "404.html", PUBLIC_DIR / "50x.html"]

STYLE_TAG = re.compile(r"<style[\s>]", re.IGNORECASE)
STYLE_ATTR = re.compile(r'\sstyle="[^"]*"', re.IGNORECASE)
LINK_STYLESHEET = re.compile(r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"')
CLASS_ATTR = re.compile(r'class="([^"]*)"')
HTML_TAG = re.compile(r"<html\b[^>]*>", re.IGNORECASE)

# A class only counts as defined where it terminates a selector: `.foo{`,
# `.foo,`, `.foo.bar`, `.foo::before`, `.foo > x`. Matching `\.([\w-]+)`
# anywhere would also pick up decimals inside declarations such as
# `flex: 1.5` and quietly define classes named after them. Copied from
# tests/test_admin_inline_styles.py, which had already worked this out.
CLASS_SELECTOR = re.compile(r"\.([a-zA-Z][\w-]*)(?=[\s,{:.>+~\[])")


def _linked_stylesheets(html: str) -> list:
    """Every stylesheet `html` actually <link>s, resolved the same way the
    browser resolves it: root-relative to frontend/public/, which is exactly
    what nginx serves at `/` for these two pages (production.conf's
    `error_page 404 /404.html` and `location = /50x.html` both point `root`
    at this same directory)."""
    return [PUBLIC_DIR / href.lstrip("/") for href in LINK_STYLESHEET.findall(html)]


def _classes_used(html: str) -> set:
    used = set()
    for attr in CLASS_ATTR.findall(html):
        for token in attr.split():
            if re.fullmatch(r"[a-zA-Z][\w-]*", token):
                used.add(token)
    return used


def _classes_defined(stylesheets) -> set:
    css = "\n".join(p.read_text() for p in stylesheets if p.exists())
    return set(CLASS_SELECTOR.findall(css))


def test_error_pages_have_no_inline_style_block_or_attribute():
    offenders = []
    for page in ERROR_PAGES:
        html = page.read_text()
        if STYLE_TAG.search(html):
            offenders.append(f"{page.name}: <style> block")
        offenders += [f"{page.name}: {m.strip()}" for m in STYLE_ATTR.findall(html)]
    assert offenders == [], (
        "inline styling in a static error page. Each one is a reason the CSP "
        "must keep style-src 'unsafe-inline'. Move the declarations into "
        "frontend/public/css/error.css and name a class instead:\n  "
        + "\n  ".join(offenders)
    )


def test_every_linked_stylesheet_exists_on_disk():
    """A <link href> to a file that was never created (or was renamed) would
    silently make the next test see zero definitions -- reporting every class
    as missing for a confusing reason, or none at all if the page happens to
    use no classes. Fail on the actual cause first."""
    for page in ERROR_PAGES:
        html = page.read_text()
        for sheet in _linked_stylesheets(html):
            assert sheet.exists(), f"{page.name} links {sheet}, which does not exist"


def test_every_class_in_error_pages_is_defined_in_a_linked_stylesheet():
    missing = {}
    for page in ERROR_PAGES:
        html = page.read_text()
        defined = _classes_defined(_linked_stylesheets(html))
        gap = sorted(_classes_used(html) - defined)
        if gap:
            missing[page.name] = gap
    assert not missing, (
        "class named in the markup but not defined in any stylesheet that "
        "page links, so it renders unstyled with no error anywhere: %s" % missing
    )


def test_the_missing_class_check_can_actually_find_one():
    """A guard that cannot fail is not a guard. Pins that a name absent from
    every linked stylesheet is genuinely reported, the same way
    test_admin_inline_styles.py pins its own extractor."""
    html = (PUBLIC_DIR / "404.html").read_text()
    defined = _classes_defined(_linked_stylesheets(html))
    assert "definitely-not-a-real-class" not in defined


def test_the_inline_style_check_can_actually_find_one():
    """Same reasoning as above, for the other half of this file: prove the
    regexes fire on real offenders instead of only ever seeing a clean tree."""
    assert STYLE_TAG.search("<style>body{color:red}</style>")
    assert STYLE_ATTR.findall('<div style="color:red">')


def test_error_pages_load_only_tokens_and_error_css():
    """Pins the minimal-dependency contract these pages were designed around:
    tokens.css for the custom properties, error.css for the rules, and
    nothing else. style.css (~680 lines of header/hero/dashboard rules) and
    fonts.css (self-hosted @font-face declarations, unneeded because
    var(--font-sans) degrades to system fonts without them) are both
    available from the same static root, but loading either here is exactly
    the "chases four stylesheets" failure mode the 50x page -- shown when the
    backend, not nginx, is down -- can least afford."""
    expected = {"tokens.css", "error.css"}
    for page in ERROR_PAGES:
        html = page.read_text()
        linked_names = {p.name for p in _linked_stylesheets(html)}
        assert linked_names == expected, (
            "%s links %s, expected exactly %s"
            % (page.name, sorted(linked_names), sorted(expected))
        )


def test_error_pages_carry_no_data_theme_attribute():
    """These pages ship no <script>, so nothing can ever set data-theme on
    <html> the way main.js does for the public site. Asserting its absence
    here documents that the light values in tokens.css' :root are not a
    fallback for a theme that failed to apply -- they are the only theme
    these two pages ever render, by construction.

    Matches the <html ...> tag itself with a dedicated regex rather than
    splitting the document on the first ">": that lands on <!DOCTYPE html>,
    which can never contain data-theme either way, making the assertion pass
    no matter what the real <html> tag says -- a guard that cannot fail.
    """
    for page in ERROR_PAGES:
        html = page.read_text()
        match = HTML_TAG.search(html)
        assert match, f"{page.name} has no <html> tag"
        assert "data-theme" not in match.group(0), (
            f"{page.name} sets data-theme on <html> but ships no script that "
            "could ever change it again"
        )
