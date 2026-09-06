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


# ---------------------------------------------------------------------------
# The dark mapping in error.css must not drift from tokens.css
# ---------------------------------------------------------------------------

TOKENS_CSS = REPO_ROOT / "frontend" / "public" / "css" / "tokens.css"
ERROR_CSS = REPO_ROOT / "frontend" / "public" / "css" / "error.css"


def _dark_block_of_tokens_css() -> dict:
    """The `[data-theme="dark"]` semantic mapping, as {token: value}.

    Matched on the rule itself, not on the first textual occurrence of the
    string: tokens.css mentions `[data-theme="dark"]` several times in its
    header comment, and anchoring on those lands in the raw palette block and
    silently returns the wrong 24 entries. Ask me how I know.
    """
    css = TOKENS_CSS.read_text()
    m = re.search(r'^\[data-theme="dark"\]\s*\{', css, re.M)
    assert m, 'tokens.css has no [data-theme="dark"] rule'
    body = css[m.end():css.index("}", m.end())]
    return dict(re.findall(r"(--[\w-]+)\s*:\s*(var\(--c-[\w-]+\))\s*;", body))


def _error_css_dark_overrides() -> dict:
    css = ERROR_CSS.read_text()
    m = re.search(r"@media\s*\(prefers-color-scheme:\s*dark\)\s*\{", css)
    assert m, "error.css has no prefers-color-scheme block"
    return dict(re.findall(r"(--[\w-]+)\s*:\s*(var\(--c-[\w-]+\))\s*;", css[m.end():]))


def test_error_page_dark_mapping_matches_tokens_css():
    """error.css restates part of the dark theme because these pages have no JS
    to set data-theme. Restating is a drift risk, so pin it: every token it
    overrides must resolve to the same palette entry tokens.css uses for dark.

    If this fails, the error pages are showing a colour the rest of the site
    stopped using -- which is invisible until someone hits a 404 on a dark
    desktop, i.e. exactly when nobody is looking.
    """
    dark = _dark_block_of_tokens_css()
    overrides = _error_css_dark_overrides()
    assert overrides, "the prefers-color-scheme block defines no tokens"

    mismatched = {
        tok: (val, dark.get(tok))
        for tok, val in overrides.items()
        if dark.get(tok) != val
    }
    assert not mismatched, (
        "error.css disagrees with tokens.css's dark theme: "
        + "; ".join(
            "%s is %s here but %s there" % (t, a, b) for t, (a, b) in mismatched.items()
        )
    )


def test_every_token_the_error_pages_use_is_overridden_for_dark():
    """A token consumed by error.css but absent from its dark block keeps its
    light value on a dark background -- the half-themed page that looks like a
    rendering bug. Covers only the theme-dependent colour tokens; --font-* and
    --transition-* are intentionally theme-independent.
    """
    css = ERROR_CSS.read_text()
    body = css[: re.search(r"@media\s*\(prefers-color-scheme", css).start()]
    used = set(re.findall(r"var\((--(?:bg|text|accent|border)-[\w-]+)\)", body))
    missing = sorted(used - set(_error_css_dark_overrides()))
    assert not missing, "used by the error pages but not remapped for dark: %s" % missing
