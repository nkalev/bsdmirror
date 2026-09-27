"""Structural pins for frontend/public/index.html (spec section 5.1).

main.js and tests/js/states_harness.mjs already pin *behaviour*: given a
particular API response, MirrorStatus writes a particular data-state and
text. Neither proves the markup those functions look up actually exists, in
the right shape, with the right hooks, or that the page ships in the correct
*pre-JavaScript* state a visitor's first paint shows before any fetch
resolves. This file is the other half: it parses the real index.html with
html.parser.HTMLParser (a real DOM-ish tree, not a handful of independent
regexes, so a query like "the .pill inside #freebsd-stream" is asking the
same question a browser would) and pins every id, class and data-attribute
`main.js`/style.css rely on, the copy spec section 5.1 introduces, and the
accessibility shape (one h1, decorative content marked aria-hidden, every
.icon span naming a real file) spec section 9 requires.

Byte-identical opening tags (the three per-mirror copy buttons) are checked
against the raw text instead of through the parsed tree: "byte-identical" is
a property of the source bytes, and tests/test_public_page_csp.py's own
negative control already depends on that literal string existing exactly
once per mirror.
"""
import pathlib
from html.parser import HTMLParser

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PUBLIC = REPO_ROOT / "frontend" / "public"
INDEX_HTML = PUBLIC / "index.html"
ICONS_DIR = PUBLIC / "img" / "icons"

MIRRORS = ["freebsd", "netbsd", "openbsd"]
MIRROR_NAMES = {"freebsd": "FreeBSD", "netbsd": "NetBSD", "openbsd": "OpenBSD"}

VOID_ELEMENTS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


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

    def direct_text(self):
        """Just this node's own text children, not a descendant's -- for a
        node like #overallStatus that wraps both a heading and a paragraph,
        where "the text" only makes sense per-child."""
        return "".join(c for c in self.children if isinstance(c, str))

    def walk(self):
        yield self
        for c in self.children:
            if isinstance(c, Node):
                yield from c.walk()

    def element_children(self):
        return [c for c in self.children if isinstance(c, Node)]

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
        node = self._open(tag, attrs)
        if tag not in VOID_ELEMENTS:
            self.stack.append(node)

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


def find_all(root, tag=None, id=None, class_=None, attrs=None):
    for n in root.walk():
        if tag is not None and n.tag != tag:
            continue
        if id is not None and n.attrs.get("id") != id:
            continue
        if class_ is not None and class_ not in n.classes():
            continue
        if attrs is not None and any(n.attrs.get(k) != v for k, v in attrs.items()):
            continue
        yield n


def find_one(root, **kw):
    matches = list(find_all(root, **kw))
    assert (
        len(matches) == 1
    ), f"expected exactly one match for {kw}, found {len(matches)}: {matches}"
    return matches[0]


HTML_TEXT = INDEX_HTML.read_text(encoding="utf-8")
ROOT = parse(HTML_TEXT)


# ===========================================================================
# Headings: one h1, section h2s (spec section 9, "Headings").
# ===========================================================================
def test_exactly_one_h1():
    h1s = list(find_all(ROOT, tag="h1"))
    assert len(h1s) == 1, f"expected exactly one <h1>, found {len(h1s)}"
    assert h1s[0].classes() == {"hero-title"}
    assert h1s[0].text() == "Every BSD, mirrored."


def test_every_section_has_an_h2_section_title():
    for section_id in ("mirrors", "status", "access", "about"):
        section = find_one(ROOT, tag="section", id=section_id)
        h2s = [n for n in section.walk() if n.tag == "h2"]
        assert len(h2s) == 1, f"#{section_id} has {len(h2s)} <h2>, expected 1"
        assert "section-title" in h2s[0].classes()


# ===========================================================================
# Header hooks: #themeToggle, .theme-icon, .nav-admin (spec section 5.2).
# ===========================================================================
def test_theme_toggle_hook_and_icon_span():
    toggle = find_one(ROOT, id="themeToggle")
    assert toggle.tag == "button"
    assert toggle.attrs.get("aria-label") == "Toggle theme"
    icons = [n for n in toggle.walk() if "theme-icon" in n.classes()]
    assert len(icons) == 1, "themeToggle must contain exactly one .theme-icon span"
    icon = icons[0]
    assert icon.tag == "span"
    assert icon.classes() == {"icon", "theme-icon"}
    assert icon.attrs.get("data-icon") == "moon"
    assert icon.attrs.get("aria-hidden") == "true"
    assert icon.text() == "", "ThemeManager.apply never writes the icon's textContent"


def test_nav_admin_is_not_a_nav_link():
    admin_links = list(find_all(ROOT, class_="nav-admin"))
    assert len(admin_links) == 1
    admin = admin_links[0]
    assert admin.tag == "a"
    assert admin.attrs.get("href") == "/admin"
    assert admin.text() == "Admin"
    assert "nav-link" not in admin.classes()


def test_nav_anchors_and_their_sections_agree():
    nav = find_one(ROOT, tag="nav")
    links = [n for n in nav.walk() if n.tag == "a"]
    hrefs = [link.attrs.get("href") for link in links]
    assert hrefs == ["#mirrors", "#status", "#access", "#about"]
    labels = [link.text() for link in links]
    assert labels == ["Mirrors", "Status", "Access", "About"]
    for anchor in ("mirrors", "status", "access", "about"):
        find_one(ROOT, tag="section", id=anchor)  # raises if missing/duplicated


# ===========================================================================
# Hero copy and stats (spec section 5.1): stats start at an em dash.
# ===========================================================================
def test_hero_copy():
    hero = find_one(ROOT, class_="hero")
    eyebrow = find_one(hero, class_="hero-eyebrow")
    assert eyebrow.text() == "FreeBSD · NetBSD · OpenBSD"
    lede = find_one(hero, class_="hero-lede")
    assert lede.text() == (
        "High-speed access to releases, packages and documentation, "
        "synced from the official upstream mirrors."
    )


def test_hero_stats_start_at_an_em_dash():
    labels = {"statSize": "mirrored", "statFiles": "files", "statLastSync": "last sync"}
    for stat_id in labels:
        value = find_one(ROOT, id=stat_id)
        assert value.classes() == {"stat-value"}
        assert value.text() == "—"
    # Labels are checked positionally: three .stat blocks, each holding one
    # .stat-value and one .stat-label, in the same order as `labels` above.
    stats = list(find_all(ROOT, class_="stat"))
    assert len(stats) == 3
    for stat, (stat_id, label) in zip(stats, labels.items(), strict=True):
        value = find_one(stat, class_="stat-value")
        assert value.attrs.get("id") == stat_id
        assert find_one(stat, class_="stat-label").text() == label


def test_hero_ctas():
    hero = find_one(ROOT, class_="hero")
    browse = find_one(hero, class_="hero-ctas")
    ctas = browse.element_children()
    assert len(ctas) == 2
    browse_link, copy_button = ctas
    assert browse_link.tag == "a" and browse_link.attrs.get("href") == "#mirrors"
    assert browse_link.text() == "Browse mirrors"
    assert copy_button.tag == "button"
    assert copy_button.attrs.get("data-copy") == "rsync-root"
    assert copy_button.text() == "Copy rsync URL"


# ===========================================================================
# Sync streams: one row per mirror, each with a pill and a hostname hook
# (spec section 5.2's new markup).
# ===========================================================================
def test_stream_rows_start_unknown_and_reading_checking():
    for os_id in MIRRORS:
        row = find_one(ROOT, id=f"{os_id}-stream")
        assert row.attrs.get("data-state") == "unknown"
        pills = [n for n in row.walk() if "pill" in n.classes() and n is not row]
        assert len(pills) == 1, f"#{os_id}-stream must contain exactly one .pill"
        pill = pills[0]
        assert pill.attrs.get("data-state") == "unknown"
        assert find_one(pill, class_="status-text").text() == "Checking…"
        hosts = [n for n in row.walk() if "data-hostname" in n.attrs]
        assert len(hosts) == 1, f"#{os_id}-stream must contain exactly one [data-hostname]"
        assert hosts[0].attrs.get("data-hostname") == ""
        line = find_one(row, class_="stream-line")
        assert line.attrs.get("aria-hidden") == "true"


def test_the_sync_streams_section_is_a_named_region():
    """The name belongs on the <section>, where it makes the streams a
    region landmark. On the generic <div> inside it an aria-label names
    nothing: ARIA does not let a generic element carry a name."""
    section = find_one(ROOT, tag="section", class_="streams")
    assert section.attrs.get("aria-label") == "Sync streams"
    inner = find_one(section, class_="streams-inner")
    assert "aria-label" not in inner.attrs


# ===========================================================================
# Mirror cards: hooks main.js writes to, and the byte-identical copy button.
# ===========================================================================
def test_mirror_cards_have_the_hooks_main_js_writes_to():
    cards = list(find_all(ROOT, class_="mirror-card"))
    assert len(cards) == 3
    seen_mirrors = {c.attrs.get("data-mirror") for c in cards}
    assert seen_mirrors == set(MIRRORS)
    for os_id in MIRRORS:
        card = find_one(ROOT, class_="mirror-card", attrs={"data-mirror": os_id})
        status = find_one(card, id=f"{os_id}-status")
        assert "pill" in status.classes()
        assert status.attrs.get("data-state") == "unknown"
        assert find_one(status, class_="status-text").text() == "Checking…"
        assert find_one(card, id=f"{os_id}-size").text() == "--"
        assert find_one(card, id=f"{os_id}-sync").text() == "--"


def test_mirror_actions_hold_exactly_a_browse_link_then_a_copy_button():
    for os_id in MIRRORS:
        card = find_one(ROOT, class_="mirror-card", attrs={"data-mirror": os_id})
        actions = find_one(card, class_="mirror-actions")
        controls = actions.element_children()
        assert len(controls) == 2, f"{os_id}: .mirror-actions must hold exactly two controls"
        browse, copy = controls
        assert browse.tag == "a" and browse.attrs.get("href") == f"/{MIRROR_NAMES[os_id]}/"
        assert copy.tag == "button"
        assert copy.attrs.get("data-copy-rsync") == MIRROR_NAMES[os_id]
        assert copy.text() == "rsync URL"


def test_mirror_actions_copy_buttons_are_byte_identical_opening_tags():
    """tests/test_public_page_csp.py's negative control depends on this
    exact string existing once per mirror; a parsed-attribute comparison
    would not catch an attribute-order change the way a byte comparison
    does."""
    for name in MIRROR_NAMES.values():
        literal = f'<button class="btn btn-secondary" data-copy-rsync="{name}">'
        assert HTML_TEXT.count(literal) == 1, f"{literal!r} must appear exactly once"


# ===========================================================================
# Overall status card (spec section 5.2's overall-card table).
# ===========================================================================
def test_overall_status_card_starts_unknown_and_checking():
    card = find_one(ROOT, id="overallStatus")
    assert "status-card" in card.classes()
    assert card.attrs.get("data-state") == "unknown"
    dot = find_one(card, class_="status-dot")
    assert dot.attrs.get("aria-hidden") == "true"
    h3 = find_one(card, tag="h3")
    assert h3.text() == "Checking mirror status…"
    p = find_one(card, tag="p")
    assert p.direct_text() == ""


# ===========================================================================
# Access section: the new #access hooks (spec section 5.1).
# ===========================================================================
def test_access_rows_have_labelled_copy_buttons():
    access = find_one(ROOT, tag="section", id="access")
    hostname = find_one(access, id="hostname")
    assert hostname.text() == "mirror.example.com"
    rsynchost = find_one(access, id="rsynchost")
    assert rsynchost.text() == "mirror.example.com"

    https_button = find_one(access, attrs={"data-copy": "https-root"})
    assert https_button.tag == "button"
    assert "icon-btn" in https_button.classes()
    assert https_button.attrs.get("aria-label") == "Copy HTTPS URL"

    rsync_button = find_one(access, attrs={"data-copy": "rsync-root"})
    assert rsync_button.tag == "button"
    assert "icon-btn" in rsync_button.classes()
    assert rsync_button.attrs.get("aria-label") == "Copy rsync URL"

    labels = [n.text() for n in find_all(access, class_="access-label")]
    assert labels == ["HTTP/HTTPS", "rsync"]


# ===========================================================================
# Footer and toast.
# ===========================================================================
def test_footer_version_literal_class_and_toast_hook():
    # tests/test_footer_version.py depends on this exact literal string.
    assert 'class="footer-version"' in HTML_TEXT
    toast = find_one(ROOT, id="toast")
    assert toast.text() == ""


# ===========================================================================
# Accessibility: the mark, the hero art and every icon span are aria-hidden,
# and every .icon span names a real file under /img/icons/ (spec section 9).
# ===========================================================================
def test_mark_definition_and_header_mark_are_aria_hidden():
    hidden_svg = find_one(ROOT, tag="svg", class_="visually-hidden")
    assert hidden_svg.attrs.get("aria-hidden") == "true"
    assert find_one(hidden_svg, tag="symbol").attrs.get("id") == "mark"

    header = find_one(ROOT, tag="header")
    header_mark = find_one(header, tag="svg", class_="mark")
    assert header_mark.attrs.get("aria-hidden") == "true"


def test_hero_art_is_aria_hidden():
    art = find_one(ROOT, class_="hero-art")
    assert art.attrs.get("aria-hidden") == "true"
    marks = list(find_all(art, tag="svg", class_="mark"))
    assert len(marks) == 2, "the hero art holds the standing mark and its reflection"


def test_new_tab_links_carry_noopener():
    """A target="_blank" link without rel="noopener" hands the opened page a
    handle on this one (window.opener). Current browsers imply it, but the
    markup should not rely on that."""
    new_tab = [n for n in ROOT.walk() if n.tag == "a" and n.attrs.get("target") == "_blank"]
    assert new_tab, "expected the About and footer links to open in a new tab"
    for link in new_tab:
        rel = set((link.attrs.get("rel") or "").split())
        assert "noopener" in rel, f"{link} opens a new tab without rel=noopener"


def test_the_hero_gradient_spans_the_whole_glyph():
    """Spec section 4.5: the hero glyph is filled with one vertical gradient.
    In the default objectBoundingBox units each shape gets its own gradient, so
    the bowls (y 34-58) and the stems (y 6-58) shade differently where they
    overlap, and a seam shows. User-space units from the glyph's top to its
    bottom give every shape the same continuous gradient."""
    gradient = find_one(ROOT, tag="lineargradient", id="hero-mark-gradient")
    attrs = gradient.attrs  # HTMLParser lowercases attribute names
    assert attrs.get("gradientunits") == "userSpaceOnUse"
    assert (attrs.get("x1"), attrs.get("x2")) == ("0", "0"), "the gradient must be vertical"
    assert (attrs.get("y1"), attrs.get("y2")) == ("6", "58"), "from the glyph's top to its bottom"


ICON_CLASS_PREFIX = "icon-"


def _icon_file_name(node):
    others = node.classes() - {"icon"}
    assert len(others) == 1, f"<span class={node.attrs.get('class')!r}> has an unexpected class set"
    variant = next(iter(others))
    if variant == "theme-icon":
        name = node.attrs.get("data-icon")
        assert name, "theme-icon span has no data-icon"
        return name
    assert variant.startswith(ICON_CLASS_PREFIX), f"unexpected icon class {variant!r}"
    return variant[len(ICON_CLASS_PREFIX) :]


def test_every_icon_span_is_aria_hidden_and_names_an_existing_svg():
    icons = list(find_all(ROOT, class_="icon"))
    assert icons, "no .icon spans found -- did index.html's markup change shape?"
    for node in icons:
        assert node.tag == "span"
        assert (
            node.attrs.get("aria-hidden") == "true"
        ), f"<span class={node.attrs.get('class')!r}> is decorative and must be aria-hidden"
        name = _icon_file_name(node)
        path = ICONS_DIR / f"{name}.svg"
        assert (
            path.is_file()
        ), f"<span class={node.attrs.get('class')!r}> names {path}, which does not exist"


def test_at_least_the_expected_icon_variants_are_present():
    """A floor, not a ceiling: pins that the icon spans spec section 4.7
    calls for are actually there, without pinning every place one is used
    (the copy icon alone appears on six buttons) or ruling out a new one --
    test_every_icon_span_is_aria_hidden_and_names_an_existing_svg above
    already holds any icon span to a real file."""
    variants = set()
    for node in find_all(ROOT, class_="icon"):
        variants |= node.classes() - {"icon"}
    missing = {"icon-copy", "icon-arrow-right", "theme-icon"} - variants
    assert not missing, f"no .icon span uses {sorted(missing)}"
