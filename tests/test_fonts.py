"""The self-hosted fonts: what fonts.css loads, what fonts/ holds, and what
fonts/README.md records about them.

docs/design/2026-09-25-reflection-redesign.md, sections 3 and 4.2. The CSP
loads fonts from this origin only (font-src 'self'), and nginx serves fonts
with a week-long `immutable` cache, so a changed font has to ship under a new
name. fonts/README.md is the record of where each file came from, under which
license, and which bytes it holds. These tests keep the stylesheet, the
directory and that record in step.
"""

import hashlib
import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PUBLIC = REPO_ROOT / "frontend" / "public"
FONTS = PUBLIC / "fonts"
FONTS_CSS = PUBLIC / "css" / "fonts.css"
FONTS_README = FONTS / "README.md"

CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
MARKUP_COMMENT = re.compile(r"<!--.*?-->", re.S)
CSS_URL = re.compile(r"""url\(\s*(['"]?)(.*?)\1\s*\)""")
FONT_URL = re.compile(r"""url\(\s*['"]?/fonts/([^'")]+\.woff2)['"]?\s*\)""")
FONT_FACE = re.compile(r"@font-face\s*\{(.*?)\}", re.S)
FAMILY = re.compile(r"""font-family:\s*(['"])([^'"]+)\1""")
WEIGHT = re.compile(r"font-weight:\s*([^;]+);")
CHECKSUM = re.compile(r"^([0-9a-f]{64})  (\S+\.woff2)$", re.M)
WOFF2_FILES = sorted(path.name for path in FONTS.glob("*.woff2"))


def public_files(*suffixes):
    return sorted(path for path in PUBLIC.rglob("*") if path.suffix in suffixes)


def rel(path):
    return str(path.relative_to(PUBLIC))


def without_comments(path):
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".css", ".js"):
        return CSS_COMMENT.sub("", text)
    if path.suffix in (".html", ".svg"):
        return MARKUP_COMMENT.sub("", text)
    return text


def font_face_blocks():
    return FONT_FACE.findall(CSS_COMMENT.sub("", FONTS_CSS.read_text(encoding="utf-8")))


def parse_face(body):
    """(family, weight, file) of one @font-face body, with None for a field
    that does not parse."""
    family, weight, url = FAMILY.search(body), WEIGHT.search(body), FONT_URL.search(body)
    return (
        family.group(2) if family else None,
        weight.group(1).strip() if weight else None,
        url.group(1) if url else None,
    )


def font_faces():
    """(family, weight, file) for every @font-face in fonts.css that parses.
    The parametrized tests below are built from this at collection time, so it
    must not raise on an odd block: test_every_font_face_parses names those."""
    return [face for face in map(parse_face, font_face_blocks()) if None not in face]


def readme_checksums():
    text = FONTS_README.read_text(encoding="utf-8")
    return {name: digest for digest, name in CHECKSUM.findall(text)}


@pytest.mark.parametrize("path", public_files(".css", ".html", ".js", ".svg"), ids=rel)
def test_nothing_loads_fonts_from_google(path):
    text = without_comments(path)
    for host in ("fonts.googleapis.com", "fonts.gstatic.com"):
        assert host not in text, f"{rel(path)} references {host}; font-src allows this origin only"


def test_every_css_url_is_a_file_on_this_origin():
    """Every url() in every stylesheet, not only fonts.css: image masks are
    held to the same rule."""
    found, problems = 0, []
    for css in public_files(".css"):
        for _, url in CSS_URL.findall(CSS_COMMENT.sub("", css.read_text(encoding="utf-8"))):
            found += 1
            if url.startswith("#"):
                continue  # a reference within the same document
            target = PUBLIC / url.split("?")[0].split("#")[0].lstrip("/")
            if not url.startswith("/") or url.startswith("//"):
                problems.append(f"{rel(css)}: url({url}) is not a path on this origin")
            elif not target.is_file():
                problems.append(f"{rel(css)}: url({url}) names no file under frontend/public")
    assert found, "no url() in any stylesheet; the pattern is broken"
    assert not problems, "\n".join(problems)


def test_every_font_face_parses():
    blocks = font_face_blocks()
    assert blocks, "no @font-face in fonts.css; the pattern is broken"
    bad = [body.strip() for body in blocks if None in parse_face(body)]
    assert not bad, "@font-face with no family, weight or /fonts/ url():\n" + "\n---\n".join(bad)


def test_the_fonts_directory_holds_only_fonts_licences_and_the_readme():
    others = sorted(
        path.name
        for path in FONTS.iterdir()
        if not path.name.startswith(".")
        and path.suffix != ".woff2"
        and not (path.name.startswith("LICENSE-") and path.suffix == ".txt")
        and path.name != "README.md"
    )
    assert others == [], f"fonts/ holds files that are none of those: {others}"


def test_fonts_css_the_readme_and_the_directory_list_the_same_files():
    assert {file for _, _, file in font_faces()} == set(WOFF2_FILES)
    assert set(readme_checksums()) == set(WOFF2_FILES)


@pytest.mark.parametrize("name", WOFF2_FILES)
def test_each_font_is_woff2(name):
    # A file that is not a font at all, such as a saved error page, would
    # otherwise pass every other check here until a page first used it.
    assert (FONTS / name).read_bytes()[:4] == b"wOF2", f"{name} is not a WOFF2 file"


@pytest.mark.parametrize("name", WOFF2_FILES)
def test_each_font_matches_the_checksum_in_the_readme(name):
    digest = hashlib.sha256((FONTS / name).read_bytes()).hexdigest()
    assert readme_checksums().get(name) == digest, (
        f"{name} does not match its checksum in fonts/README.md. nginx caches fonts for a "
        "week as immutable: a changed font ships under a new name, with its checksum listed"
    )


@pytest.mark.parametrize("family", sorted({family for family, _, _ in font_faces()}))
def test_every_family_ships_with_its_open_font_license(family):
    license_file = f"LICENSE-{family.replace(' ', '')}.txt"
    text = (FONTS / license_file).read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE" in text.upper()
    assert license_file in FONTS_README.read_text(encoding="utf-8")
    # The copyright lines come before this sentence. A Reserved Font Name
    # declared there would forbid serving Google's subset builds under the
    # family's name. Every OFL text defines the term further down; that is fine.
    head, found, _ = text.partition("This Font Software is licensed")
    assert found, f"{license_file} does not read like an OFL text"
    assert "Reserved Font Name" not in head, f"{license_file} declares a Reserved Font Name"


def test_no_license_is_left_for_a_family_that_is_gone():
    families = {family.replace(" ", "") for family, _, _ in font_faces()}
    licensed = {path.name[len("LICENSE-") : -len(".txt")] for path in FONTS.glob("LICENSE-*.txt")}
    assert licensed == families


@pytest.mark.parametrize(
    "family, weights, stem",
    [
        ("Unbounded", {"600", "700"}, "unbounded"),
        ("Instrument Sans", {"400", "500", "600"}, "instrument-sans"),
    ],
)
def test_the_new_families_ship_latin_and_latin_ext_only(family, weights, stem):
    faces = [(weight, file) for name, weight, file in font_faces() if name == family]
    assert faces, f"fonts.css has no @font-face for {family}"
    # Every weight in both subsets: checked apart, the weights and the files
    # would miss a weight that has only one of them.
    subsets = ("latin", "latin-ext")
    assert set(faces) == {(w, f"{stem}-{s}.woff2") for w in weights for s in subsets}
