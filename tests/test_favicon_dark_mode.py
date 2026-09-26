"""favicon.svg's dark tile must survive the production CSP header.

docs/design/2026-09-25-reflection-redesign.md, section 4.6. favicon.svg keeps
its light colours in presentation attributes and switches to its dark tile with
one `@media (prefers-color-scheme: dark)` rule in a <style> element. nginx
serves it with `style-src 'self'`, which would block that <style> if Chromium
applied an image's own CSP header to it.

tests/js/favicon_harness.mjs draws the file in a dark colour scheme three ways,
on a mid-grey page, and reads back one pixel of each tile: with the production
CSP header, without it, and without its <style>. The last two are controls. The
copy without the header must read dark and the copy without the <style> must
read light, or the harness is not measuring the rule. A copy that did not draw
reads the grey page, which is neither. In both cases the real test fails as
broken instead of answering.

This proves Chromium's behaviour only; another browser at worst shows the
light tile. If favicon.svg drops its dark rule, the design's fallback (a light
tile whose edge reads on either tab colour), there is nothing to check and
these tests skip.
"""

import json
import subprocess
import xml.etree.ElementTree as ET

import pytest

from tests.test_public_page_csp import CHROME, NODE, REPO_ROOT, nginx_csp

FAVICON = REPO_ROOT / "frontend" / "public" / "img" / "favicon.svg"
HARNESS = REPO_ROOT / "tests" / "js" / "favicon_harness.mjs"

# Relative luminance, from 0 (black) to 1 (white). At the sampled point the
# dark tile reads about 0.01 and the light tile about 0.9. The grey page behind
# the copies, #808080, reads about 0.22: neither.
DARK_BELOW = 0.1
LIGHT_ABOVE = 0.6

pytestmark = [
    pytest.mark.skipif(
        NODE is None or CHROME is None,
        reason=f"needs node and Chrome (node={bool(NODE)}, chrome={bool(CHROME)})",
    ),
    pytest.mark.skipif(
        ET.parse(FAVICON).getroot().find("{http://www.w3.org/2000/svg}style") is None,
        reason="favicon.svg ships as the light tile only (the design's fallback)",
    ),
]


def luminance(rgba):
    def linear(channel):
        c = channel / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b, _ = rgba
    return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)


def reads_dark(rgba):
    return luminance(rgba) < DARK_BELOW


def reads_light(rgba):
    return luminance(rgba) > LIGHT_ABOVE


@pytest.fixture(scope="module")
def pixels():
    proc = subprocess.run(
        [NODE, str(HARNESS), str(FAVICON), nginx_csp(), CHROME],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert proc.returncode == 0, (
        f"favicon harness failed (rc={proc.returncode})\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    return json.loads(proc.stdout)


def test_the_copy_without_csp_renders_dark(pixels):
    assert reads_dark(pixels["withoutCsp"]), (
        f"with no CSP at all the tile read {pixels['withoutCsp']}, not dark. favicon.svg's "
        "dark rule no longer darkens the tile, the harness is not putting the image in a "
        "dark colour scheme, or the copy did not draw."
    )


def test_the_copy_without_its_style_renders_light(pixels):
    assert reads_light(pixels["withoutStyle"]), (
        f"without its <style> the tile read {pixels['withoutStyle']}, not light. The "
        "sampled pixel is not on the tile, the copy did not draw, or something other than "
        "the rule darkens it."
    )


def test_the_dark_rule_applies_under_the_production_csp(pixels):
    if not (reads_dark(pixels["withoutCsp"]) and reads_light(pixels["withoutStyle"])):
        pytest.fail("a control failed (see the other two tests); this reading means nothing")
    reading = pixels["withCsp"]
    assert reads_dark(reading) or reads_light(reading), (
        f"with the production CSP header the tile read {reading}, which is neither tile: "
        "the copy did not draw. The harness is broken, and this is no answer."
    )
    assert reads_dark(reading), (
        f"with the production CSP header the tile read {reading}, the light tile: Chromium "
        "blocks favicon.svg's <style>. Take the design's fallback, a light-only favicon "
        "(docs/design/2026-09-25-reflection-redesign.md, section 4.6)."
    )
