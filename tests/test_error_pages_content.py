"""Content and structure pins for the static error pages (404.html, 50x.html).

Spec: docs/design/2026-09-25-reflection-redesign.md, section 5.3. These pages
carry no <script> (nothing can ever set data-theme on them; see
test_error_pages_inline_styles.py), so what a visitor sees is exactly this
markup: one headline, one explanatory sentence, the b|d mark, and a link back
to "/". tests/test_error_pages_inline_styles.py already pins their minimal
stylesheet contract (tokens.css and error.css only, no data-theme, no inline
style, every class defined); this file pins what the pages say, how the mark
reaches them, and that error.css keeps to the system font stack.

Parses each page with html.parser.HTMLParser into a small DOM-ish tree --
the same approach tests/test_public_page_structure.py uses for index.html --
rather than a handful of independent regexes, so "the one <h1> on the page"
is the same question a browser would answer.

The pages from before section 5.3's redesign fail it: their headlines read
"404 - Not Found" and "Server Error", their link "Return to homepage", and
neither carried a mark.
"""
import pathlib
import re
from html.parser import HTMLParser

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PUBLIC = REPO_ROOT / "frontend" / "public"
INDEX_HTML = PUBLIC / "index.html"
ERROR_CSS = PUBLIC / "css" / "error.css"

HEADLINES = {
    "404.html": "Page not found",
    "50x.html": "Something went wrong on our side",
}
PAGES = list(HEADLINES)

SCRIPT_TAG_RE = re.compile(r"<script\b", re.IGNORECASE)
TITLE_RE = re.compile(r"<title>([^<]*)</title>", re.IGNORECASE)
FONT_TOKEN_RE = re.compile(r"var\(\s*--font-")


class Node:
    """A minimal DOM-ish node: a tag, its attributes (last-wins, like a real
    DOM), and children that are either more Nodes or raw text strings."""

    def __init__(self, tag, attrs):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []

    def classes(self):
        return set((self.attrs.get("class") or "").split())

    def text(self):
        return "".join(c if isinstance(c, str) else c.text() for c in self.children)

    def walk(self):
        yield self
        for c in self.children:
            if isinstance(c, Node):
                yield from c.walk()

    def __repr__(self):
        return f"<{self.tag} {self.attrs}>"


class _DomBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", [])
        self.stack = [self.root]

    def _open(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        return node

    def handle_starttag(self, tag, attrs):
        self.stack.append(self._open(tag, attrs))

    def handle_startendtag(self, tag, attrs):
        self._open(tag, attrs)  # explicitly self-closed: never pushed

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def parse(html_text):
    builder = _DomBuilder()
    builder.feed(html_text)
    return builder.root


def find_all(root, tag=None):
    for n in root.walk():
        if tag is None or n.tag == tag:
            yield n


def find_one(root, **kw):
    matches = list(find_all(root, **kw))
    assert (
        len(matches) == 1
    ), f"expected exactly one match for {kw}, found {len(matches)}: {matches}"
    return matches[0]


def _read(page):
    return (PUBLIC / page).read_text(encoding="utf-8")


def _root(page):
    return parse(_read(page))


# ===========================================================================
# No script anywhere (spec section 5.3: these pages must render when
# everything else, including the backend, is failing).
# ===========================================================================
@pytest.mark.parametrize("page", PAGES)
def test_no_script_tag_anywhere(page):
    html_text = _read(page)
    assert not SCRIPT_TAG_RE.search(html_text), f"{page} carries a <script>"
    assert not list(find_all(_root(page), tag="script")), f"{page} carries a <script> element"


# ===========================================================================
# One h1, the exact new headline (spec section 5.3 gives the copy verbatim).
# ===========================================================================
@pytest.mark.parametrize("page", PAGES, ids=PAGES)
def test_exactly_one_h1_with_the_new_headline(page):
    root = _root(page)
    h1 = find_one(root, tag="h1")
    assert h1.text() == HEADLINES[page]


# ===========================================================================
# One explanatory sentence. The spec gives the headlines verbatim but not
# this wording, so only the shape is pinned: exactly one <p>, non-trivial,
# reading like a sentence, and distinct between the two pages -- not the
# literal words, which are web-designer's to choose.
# ===========================================================================
def test_each_page_has_exactly_one_explanatory_sentence():
    sentences = {}
    for page in PAGES:
        p = find_one(_root(page), tag="p")
        text = p.text().strip()
        assert len(text) >= 20, f"{page}'s <p> ({text!r}) is too short to be an explanation"
        assert text.endswith("."), f"{page}'s <p> ({text!r}) doesn't read as a full sentence"
        sentences[page] = text
    assert (
        sentences["404.html"] != sentences["50x.html"]
    ), "the two pages describe different problems and must not share a sentence"


# ===========================================================================
# The "Back to the mirror" link, to "/" (spec section 5.3, exact wording).
# ===========================================================================
@pytest.mark.parametrize("page", PAGES, ids=PAGES)
def test_back_to_the_mirror_link(page):
    root = _root(page)
    link = find_one(root, tag="a")
    assert link.attrs.get("href") == "/"
    assert link.text() == "Back to the mirror"


# ===========================================================================
# The mark (spec section 4.5): "index.html and the error pages use an inline
# <symbol> of the same geometry, styled with CSS classes". One hidden sprite
# holds <symbol id="mark">; one visible <svg class="mark"> draws it with a
# single <use>. No element carries a presentation colour, so the classes
# alone colour it, in both themes.
# ===========================================================================
def _svgs(root):
    return list(find_all(root, tag="svg"))


def _sprite(root):
    sprites = [svg for svg in _svgs(root) if list(find_all(svg, tag="symbol"))]
    assert len(sprites) == 1, f"expected one <svg> holding the <symbol>, found {len(sprites)}"
    return sprites[0]


def _visible_mark(root):
    marks = [svg for svg in _svgs(root) if "mark" in svg.classes()]
    assert len(marks) == 1, f'expected one <svg class="mark">, found {len(marks)}'
    return marks[0]


def _mark_symbol(root):
    symbols = [n for n in find_all(root, tag="symbol") if n.attrs.get("id") == "mark"]
    assert len(symbols) == 1, f'expected one <symbol id="mark">, found {len(symbols)}'
    return symbols[0]


def _shape(node):
    """A node's tag, attributes and child elements, recursively, without the
    whitespace between them: what two copies of one <symbol> must share."""
    return (
        node.tag,
        sorted(node.attrs.items()),
        [_shape(c) for c in node.children if isinstance(c, Node)],
    )


@pytest.mark.parametrize("page", PAGES, ids=PAGES)
def test_the_mark_is_an_inline_symbol_drawn_by_one_use(page):
    root = _root(page)
    assert _svgs(root), f"{page} has no <svg> -- no mark"

    sprite = _sprite(root)
    assert "visually-hidden" in sprite.classes(), f"{page}: the sprite <svg> isn't visually-hidden"
    assert sprite.attrs.get("aria-hidden") == "true", f"{page}: the sprite <svg> isn't aria-hidden"
    _mark_symbol(sprite)

    mark = _visible_mark(root)
    assert mark.attrs.get("aria-hidden") == "true", f"{page}: the visible mark isn't aria-hidden"
    hrefs = [use.attrs.get("href") for use in find_all(mark, tag="use")]
    assert hrefs == ["#mark"], f'{page}: the mark must be one <use href="#mark">, not {hrefs}'

    for svg in _svgs(root):
        for node in svg.walk():
            set_directly = {"fill", "stroke", "style"} & set(node.attrs)
            assert not set_directly, f"{page}: <{node.tag}> sets {sorted(set_directly)} directly"


@pytest.mark.parametrize("page", PAGES, ids=PAGES)
def test_the_mark_symbol_is_index_htmls_geometry_and_classes(page):
    symbol = _mark_symbol(_root(page))
    glyph = [n.tag for n in symbol.walk() if "mark-glyph" in n.classes()]
    axis = [n.tag for n in symbol.walk() if "mark-axis" in n.classes()]
    assert glyph == ["g"], f"{page}: the b and the d must share one .mark-glyph group"
    assert axis == ["rect"], f"{page}: the axis must be one .mark-axis rect"
    index_symbol = _mark_symbol(parse(INDEX_HTML.read_text(encoding="utf-8")))
    assert _shape(symbol) == _shape(index_symbol), f"{page}'s mark differs from index.html's"


# ===========================================================================
# Sized without CSS. An <svg> with no width or height lays out at 300x150
# when nothing styles it, and the 503 page can arrive with its stylesheets
# rate-limited (spec section 8 accepts that). The attributes keep that page
# readable: the mark at 64px, the sprite at nothing. error.css overrides both
# whenever it loads.
# ===========================================================================
@pytest.mark.parametrize("page", PAGES, ids=PAGES)
def test_both_svgs_carry_their_own_size(page):
    root = _root(page)
    mark = _visible_mark(root)
    sprite = _sprite(root)
    assert (mark.attrs.get("width"), mark.attrs.get("height")) == ("64", "64")
    assert (sprite.attrs.get("width"), sprite.attrs.get("height")) == ("0", "0")


# ===========================================================================
# The system font stack (spec section 4.2: "Error pages: they use the system
# font stack only"). The pages never load fonts.css, so a var(--font-*) here
# would name a webfont that cannot arrive.
# ===========================================================================
def test_error_css_uses_no_font_token():
    css = re.sub(r"/\*.*?\*/", "", ERROR_CSS.read_text(encoding="utf-8"), flags=re.S)
    assert not FONT_TOKEN_RE.search(css), "error.css reads a --font-* token"


# ===========================================================================
# Titles: not pinned verbatim (spec doesn't give exact copy), but must name
# the site and distinguish the two failures.
# ===========================================================================
def test_titles_are_sensible():
    titles = {}
    for page in PAGES:
        m = TITLE_RE.search(_read(page))
        assert m, f"{page} has no <title>"
        titles[page] = m.group(1).strip()
    for page, title in titles.items():
        assert title, f"{page}'s <title> is empty"
        assert "BSD Mirror" in title, f"{page}'s <title> ({title!r}) doesn't name the site"
    assert titles["404.html"] != titles["50x.html"], "the two pages must not share a title"
    assert re.search(r"not found", titles["404.html"], re.IGNORECASE)
    assert re.search(r"error", titles["50x.html"], re.IGNORECASE)
