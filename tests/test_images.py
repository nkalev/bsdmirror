"""Static checks on the images frontend/public serves: the b|d mark, the
icons, the logos and the favicon set.

docs/design/2026-09-25-reflection-redesign.md, sections 4.5 to 4.7. The CSP
loads images from this origin only (img-src 'self', no data:), an SVG opened
directly renders as a document, and nginx serves images with a week-long
`immutable` cache, so an image is never changed in place.
"""

import pathlib
import re
import struct
import xml.etree.ElementTree as ET
import zlib
from html.parser import HTMLParser

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PUBLIC = REPO_ROOT / "frontend" / "public"
IMG = PUBLIC / "img"
ICONS = IMG / "icons"
SVG_NS = "{http://www.w3.org/2000/svg}"
URL_REFERENCE = re.compile(r"""url\(\s*['"]?([^'")\s]*)""", re.I)
# Any <?...?> but the XML declaration. ElementTree drops these while parsing,
# so they are looked for in the raw text; <?xml-stylesheet?> loads a sheet.
PROCESSING_INSTRUCTION = re.compile(r"<\?(?!xml\s)", re.I)
# Elements that run code, pull in other content, or rewrite attributes
# after load, such as an href retargeted by <set>.
FORBIDDEN = (
    "script",
    "foreignObject",
    "image",
    "set",
    "animate",
    "animateMotion",
    "animateTransform",
)
ICON_NAMES = {
    "dashboard",
    "mirrors",
    "sync-failures",
    "protected-paths",
    "users",
    "audit-logs",
    "settings",
    "sun",
    "moon",
    "copy",
    "sync",
    "arrow-right",
    "check",
    "close",
    "info",
}
ICON_STROKE = {
    "viewBox": "0 0 24 24",
    "fill": "none",
    # Without a stroke the mask is empty.
    "stroke": "#000",
    "stroke-width": "1.6",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
}
# The b's bowl is a ring: the outer circle, then the hole (section 4.5).
MARK_BOWL = "M5 46a12 12 0 1 0 24 0a12 12 0 1 0-24 0ZM11 46a6 6 0 1 0 12 0a6 6 0 1 0-12 0Z"
FAVICON_BOWL = (
    "M5 46a11 11 0 1 0 22 0a11 11 0 1 0-22 0ZM11.8 46a4.2 4.2 0 1 0 8.4 0a4.2 4.2 0 1 0-8.4 0Z"
)
# The b, then the d: the same group, mirrored across the 64-unit grid.
MIRROR = "translate(64 0) scale(-1 1)"
FAVICON_SVG = IMG / "favicon.svg"
FAVICON_LIGHT = {
    "tile-from": "#FFFFFF",
    "tile-to": "#CDD2DA",
    "edge": "#C4C9D1",
    "glyph": "#0C0E12",
    "axis": "#C8232C",
}
# (class, property, colour): the whole of the dark rule, in order.
FAVICON_DARK = [
    ("tile-from", "stop-color", "#1C1F26"),
    ("tile-to", "stop-color", "#07080B"),
    ("edge", "stroke", "#2C313A"),
    ("glyph", "fill", "#EDEFF3"),
    ("axis", "fill", "#FF5A60"),
]


def rel(path):
    return str(path.relative_to(PUBLIC))


def svg_root(path):
    root = ET.parse(path).getroot()
    assert root.tag == SVG_NS + "svg", f"{path.name} is not an SVG document"
    return root


def attributes(element, *names):
    return {name: element.get(name) for name in names}


def by_class(root):
    found = {}
    for element in root.iter():
        for name in (element.get("class") or "").split():
            found.setdefault(name, []).append(element)
    return found


def group_ids(root):
    return [g.get("id") for g in root.iter(SVG_NS + "g") if g.get("id")]


def tags(root):
    return [element.tag.removeprefix(SVG_NS) for element in root.iter()]


def assert_inert(path, root):
    """An SVG under /img/ opened directly renders as a document: no script, no
    event handler, no style attribute, nothing loaded from outside the file."""
    raw = path.read_text(encoding="utf-8")
    assert not PROCESSING_INSTRUCTION.search(raw), f"{path.name}: a processing instruction"
    assert "<!DOCTYPE" not in raw.upper(), f"{path.name}: a DOCTYPE"
    for element in root.iter():
        # An element in another namespace, such as <html:script>, still runs.
        assert element.tag.startswith(SVG_NS), f"{path.name}: <{element.tag}> is not SVG"
        tag = element.tag.removeprefix(SVG_NS)
        assert tag not in FORBIDDEN, f"{path.name}: <{tag}>"
        texts = [element.text or ""] if tag == "style" else []
        for text in texts:
            assert "@import" not in text.lower(), f"{path.name}: @import in <style>"
        for attribute, value in element.attrib.items():
            name = attribute.rsplit("}", 1)[-1]
            assert not name.startswith("on"), f"{path.name}: {name}= event handler"
            assert name != "style", f"{path.name}: style= attribute; style-src 'self' drops it"
            if name == "href":
                assert value.startswith("#"), f"{path.name}: href={value!r} leaves the file"
            texts.append(value)
        for text in texts:
            for target in URL_REFERENCE.findall(text):
                assert target.startswith("#"), f"{path.name}: url({target}) leaves the file"


@pytest.mark.parametrize("path", sorted(IMG.rglob("*.svg")), ids=rel)
def test_every_svg_here_is_inert(path):
    assert_inert(path, svg_root(path))


def test_the_icon_set_is_the_fifteen_the_design_names():
    assert {path.stem for path in ICONS.glob("*.svg")} == ICON_NAMES
    others = [p.name for p in ICONS.iterdir() if p.suffix != ".svg" and not p.name.startswith(".")]
    assert others == []


@pytest.mark.parametrize("name", sorted(ICON_NAMES))
def test_each_icon_is_drawn_with_the_shared_round_stroke(name):
    path = ICONS / f"{name}.svg"
    root = svg_root(path)
    assert attributes(root, *ICON_STROKE) == ICON_STROKE
    assert len(root), "no shapes"
    for element in root.iter():
        if element is not root:
            overridden = {"fill", "stroke", *ICON_STROKE} & set(element.attrib)
            assert not overridden, f"{name}.svg: <{element.tag}> sets {sorted(overridden)}"


def test_mark_glyph_is_the_regular_b_and_its_mirror_image():
    root = svg_root(IMG / "mark-glyph.svg")
    assert root.get("viewBox") == "0 0 64 64"
    assert tags(root) == ["svg", "defs", "g", "rect", "path", "use", "use"]
    assert group_ids(root) == ["b"]
    stems = [attributes(r, "x", "y", "width", "height") for r in root.iter(SVG_NS + "rect")]
    assert stems == [{"x": "5", "y": "6", "width": "7", "height": "52"}]
    bowls = [attributes(b, "d", "fill-rule") for b in root.iter(SVG_NS + "path")]
    assert bowls == [{"d": MARK_BOWL, "fill-rule": "evenodd"}]
    uses = [dict(u.attrib) for u in root.iter(SVG_NS + "use")]
    assert uses == [{"href": "#b"}, {"href": "#b", "transform": MIRROR}]


def test_mark_axis_is_the_regular_axis():
    root = svg_root(IMG / "mark-axis.svg")
    assert root.get("viewBox") == "0 0 64 64"
    assert tags(root) == ["svg", "rect"]
    axes = [attributes(r, "x", "y", "width", "height", "rx") for r in root.iter(SVG_NS + "rect")]
    assert axes == [{"x": "30.7", "y": "3", "width": "2.6", "height": "58", "rx": "1.3"}]


def test_favicon_svg_is_the_small_mark_on_the_light_tile():
    root = svg_root(FAVICON_SVG)
    assert root.get("viewBox") == "0 0 64 64"
    # The <style> holding the dark rule is pinned by the next test; the
    # fallback drops it.
    shapes = [tag for tag in tags(root) if tag != "style"]
    assert shapes == [
        "svg",
        "defs",
        "linearGradient",
        "stop",
        "stop",
        "g",
        "rect",
        "path",
        "rect",
        "g",
        "use",
        "use",
        "rect",
    ]
    parts = by_class(root)

    def colours(name, attribute):
        return [(e.get(attribute) or "").upper() for e in parts[name]]

    # The light colours are presentation attributes, which style-src never blocks.
    assert colours("tile-from", "stop-color") == [FAVICON_LIGHT["tile-from"]]
    assert colours("tile-to", "stop-color") == [FAVICON_LIGHT["tile-to"]]
    assert colours("edge", "stroke") == [FAVICON_LIGHT["edge"]]
    assert colours("glyph", "fill") == [FAVICON_LIGHT["glyph"]] * 2
    assert colours("axis", "fill") == [FAVICON_LIGHT["axis"]]
    # The tile is painted by the gradient the dark rule recolours: a flat fill
    # would leave the favicon light in a dark theme.
    tile = attributes(parts["edge"][0], "x", "y", "width", "height", "rx", "stroke-width", "fill")
    assert tile == {
        "x": "1",
        "y": "1",
        "width": "62",
        "height": "62",
        "rx": "14",
        "stroke-width": "2",
        "fill": "url(#tile)",
    }
    # The small mark (section 4.5), scaled to 50 of the tile's 64 units and
    # inset 7 on each side.
    assert root.find(SVG_NS + "g").get("transform") == "translate(7 7) scale(.78125)"
    assert group_ids(root) == ["b"]
    stems = [
        attributes(r, "x", "y", "width", "height")
        for r in root.iter(SVG_NS + "rect")
        if not r.get("class")
    ]
    assert stems == [{"x": "4", "y": "8", "width": "8", "height": "49"}]
    bowls = [attributes(b, "d", "fill-rule") for b in root.iter(SVG_NS + "path")]
    assert bowls == [{"d": FAVICON_BOWL, "fill-rule": "evenodd"}]
    uses = [{k: v for k, v in e.attrib.items() if k != "fill"} for e in parts["glyph"]]
    assert uses == [
        {"class": "glyph", "href": "#b"},
        {"class": "glyph", "href": "#b", "transform": MIRROR},
    ]
    axis = attributes(parts["axis"][0], "x", "y", "width", "height", "rx")
    assert axis == {"x": "30", "y": "5", "width": "4", "height": "54", "rx": "2"}


def test_favicon_svg_turns_dark_with_one_media_rule_and_nothing_else():
    styles = [element.text or "" for element in svg_root(FAVICON_SVG).iter(SVG_NS + "style")]
    if not styles:
        pytest.skip("favicon.svg ships as the light tile only (the design's fallback)")
    assert len(styles) == 1
    css = re.sub(r"\s+", " ", styles[0]).strip()
    rule = re.fullmatch(r"@media \(prefers-color-scheme: dark\) \{ (.*) \}", css)
    assert rule, f"the <style> must hold one dark-scheme rule and nothing else: {css}"
    body = rule.group(1)
    declaration = r"\.([a-z-]+) \{ ([a-z-]+): (#[0-9A-Fa-f]{6});? \}"
    assert re.fullmatch(rf"(?:{declaration} ?)+", body), f"the rule may only set colours: {body}"
    found = [(name, prop, colour.upper()) for name, prop, colour in re.findall(declaration, body)]
    assert found == FAVICON_DARK


FAVICON_ICO = PUBLIC / "favicon.ico"
TOUCH_ICON = IMG / "apple-touch-icon.png"


def png_size(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    return struct.unpack(">II", data[16:24])


def png_chunks(data):
    """(type, body) for each chunk of a PNG, in file order."""
    pos = 8
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos : pos + 8])
        yield kind, data[pos + 8 : pos + 8 + length]
        pos += 12 + length


def png_rows(data):
    """(channels, rows) for an 8-bit, non-interlaced RGB or RGBA PNG."""
    width, height = png_size(data)
    bit_depth, colour_type, _, _, interlace = data[24:29]
    assert bit_depth == 8 and colour_type in (2, 6) and interlace == 0, "unexpected PNG format"
    channels = 4 if colour_type == 6 else 3
    idat = b"".join(body for kind, body in png_chunks(data) if kind == b"IDAT")
    raw, stride = zlib.decompress(idat), width * channels
    rows, previous = [], bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        kind, row = raw[start], bytearray(raw[start + 1 : start + 1 + stride])
        assert kind <= 4, f"row {y}: unknown PNG filter type {kind}"
        for x in range(stride):
            left = row[x - channels] if x >= channels else 0
            up = previous[x]
            up_left = previous[x - channels] if x >= channels else 0
            if kind == 1:
                row[x] = (row[x] + left) & 0xFF
            elif kind == 2:
                row[x] = (row[x] + up) & 0xFF
            elif kind == 3:
                row[x] = (row[x] + (left + up) // 2) & 0xFF
            elif kind == 4:
                estimate = left + up - up_left
                distances = (abs(estimate - left), abs(estimate - up), abs(estimate - up_left))
                row[x] = (row[x] + (left, up, up_left)[distances.index(min(distances))]) & 0xFF
        rows.append(bytes(row))
        previous = row
    return channels, rows


def test_favicon_ico_holds_16_32_and_48_pixel_pngs():
    data = FAVICON_ICO.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1), "not an ICO file"
    sizes = []
    for i in range(count):
        entry = data[6 + 16 * i : 22 + 16 * i]
        width, height, _, _, _, _, length, offset = struct.unpack("<BBBBHHII", entry)
        png = data[offset : offset + length]
        size = png_size(png)
        assert size == (width or 256, height or 256), "directory size differs from the image"
        # The tile has rounded corners: transparent outside them, opaque inside.
        channels, rows = png_rows(png)
        assert channels == 4, f"{size[0]}px: no alpha channel, so no transparent corners"
        middle = size[0] // 2
        assert rows[0][3] == 0, f"{size[0]}px: the corner pixel is not transparent"
        assert rows[middle][middle * 4 + 3] == 255, f"{size[0]}px: the middle is not opaque"
        sizes.append(size)
    assert sorted(sizes) == [(16, 16), (32, 32), (48, 48)]


def test_the_touch_icon_is_an_opaque_180_pixel_square():
    data = TOUCH_ICON.read_bytes()
    assert png_size(data) == (180, 180)
    kinds = [kind for kind, _ in png_chunks(data)]
    assert b"tRNS" not in kinds, "a tRNS chunk makes a colour transparent; iOS paints it black"
    channels, rows = png_rows(data)
    if channels == 4:
        alpha = min(row[i] for row in rows for i in range(3, len(row), 4))
        assert alpha == 255, "iOS paints transparent pixels black"


PAGES = [
    PUBLIC / "index.html",
    PUBLIC / "admin" / "index.html",
    PUBLIC / "404.html",
    PUBLIC / "50x.html",
]
FAVICON_LINKS = [
    # sizes="32x32", not "any" or absent: with either, Chrome shows the ICO, not the SVG.
    {"rel": "icon", "href": "/favicon.ico", "sizes": "32x32"},
    {"rel": "icon", "type": "image/svg+xml", "href": "/img/favicon.svg"},
    {"rel": "apple-touch-icon", "href": "/img/apple-touch-icon.png"},
]
# rel is a case-insensitive list of tokens, so "shortcut icon" and "ICON" are icon links too.
ICON_RELS = {"icon", "apple-touch-icon", "apple-touch-icon-precomposed"}


class LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "link":
            self.links.append(dict(attrs))


def test_pages_lists_every_html_page():
    assert sorted(PUBLIC.rglob("*.html")) == sorted(PAGES), "PAGES must list every HTML page"


@pytest.mark.parametrize("page", PAGES, ids=rel)
def test_every_page_links_the_favicon_set(page):
    collector = LinkCollector()
    collector.feed(page.read_text(encoding="utf-8"))
    icons = [
        link for link in collector.links if ICON_RELS & set((link.get("rel") or "").lower().split())
    ]
    assert icons == FAVICON_LINKS
    for link in icons:
        assert (PUBLIC / link["href"].lstrip("/")).is_file(), f"{link['href']} does not exist"
