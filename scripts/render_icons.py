#!/usr/bin/env python3
"""Render favicon.ico and apple-touch-icon.png from img/favicon.svg.

docs/design/2026-09-25-reflection-redesign.md, section 4.6. Run it with the
test image, which has Chromium, as a one-off container that may write to the
checkout. The compose `test` service mounts the checkout read-only.

    docker build -f Dockerfile.test -t bsdmirror-test .
    docker run --rm --network none -u "$(id -u):$(id -g)" \\
        --security-opt seccomp=unconfined -e HOME=/tmp -v "$PWD:/repo" -w /repo \\
        bsdmirror-test python scripts/render_icons.py

--network none keeps the render offline: it needs nothing but the checkout.
Both outputs use favicon.svg's light colours; its dark-theme <style> is left
out, because neither file can follow the browser's theme. favicon.ico holds
16, 32 and 48px PNGs with transparent corners. apple-touch-icon.png is 180px
and opaque, with the tile full-bleed: iOS rounds the corners itself and paints
transparent pixels black.
"""

import pathlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

REPO = pathlib.Path(__file__).resolve().parent.parent
PUBLIC = REPO / "frontend" / "public"
SOURCE = PUBLIC / "img" / "favicon.svg"
ICO = PUBLIC / "favicon.ico"
TOUCH_ICON = PUBLIC / "img" / "apple-touch-icon.png"
ICO_SIZES = (16, 32, 48)
TOUCH_SIZE = 180
SVG_URI = "http://www.w3.org/2000/svg"

PAGE = """<!DOCTYPE html>
<html><head><style>
html, body {{ margin: 0; background: transparent; }}
img {{ display: block; width: {size}px; height: {size}px; }}
</style></head><body><img src="icon.svg" alt=""></body></html>
"""


def light_only(svg: str) -> str:
    """favicon.svg without its dark-theme <style>."""
    stripped, count = re.subn(r"\s*<style\b[^>]*>.*?</style>", "", svg, flags=re.S)
    if count > 1:
        sys.exit("favicon.svg has more than one <style>; expected at most the dark-theme rule")
    return stripped


def full_bleed(svg: str) -> str:
    """The light tile stretched over the whole square, without corners or edge."""
    ET.register_namespace("", SVG_URI)
    root = ET.fromstring(light_only(svg))
    tiles = [el for el in root.iter() if "edge" in (el.get("class") or "").split()]
    if len(tiles) != 1:
        sys.exit('expected exactly one class="edge" element, the tile, in favicon.svg')
    tile = tiles[0]
    tile.attrib.update({"x": "0", "y": "0", "width": "64", "height": "64", "rx": "0"})
    for attribute in ("stroke", "stroke-width"):
        tile.attrib.pop(attribute, None)
    return ET.tostring(root, encoding="unicode")


def find_chromium() -> str:
    for name in ("chromium", "chromium-browser", "google-chrome"):
        found = shutil.which(name)
        if found:
            return found
    sys.exit("no Chromium on PATH; run this in the test image (see the docstring)")


def render(chromium: str, svg: str, size: int, workdir: pathlib.Path) -> bytes:
    """svg as a size-by-size PNG on a transparent background."""
    (workdir / "icon.svg").write_text(svg, encoding="utf-8")
    page = workdir / "page.html"
    page.write_text(PAGE.format(size=size), encoding="utf-8")
    out = workdir / f"icon-{size}.png"
    command = [
        chromium,
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--default-background-color=00000000",
        f"--window-size={size},{size}",
        f"--screenshot={out}",
        page.as_uri(),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=120)
    except subprocess.CalledProcessError as failure:
        tail = failure.stderr.decode(errors="replace")[-2000:]
        sys.exit(f"Chromium failed rendering {size}px (exit {failure.returncode}):\n{tail}")
    except subprocess.TimeoutExpired as late:
        sys.exit(f"Chromium did not finish rendering {size}px within {late.timeout:g} s")
    png = out.read_bytes() if out.exists() else b""
    header_ok = len(png) >= 24 and png[:8] == b"\x89PNG\r\n\x1a\n"
    if not header_ok or struct.unpack(">II", png[16:24]) != (size, size):
        sys.exit(f"Chromium did not produce a {size}x{size} PNG")
    return png


def ico(pngs: dict[int, bytes]) -> bytes:
    """An ICO whose images are PNGs, which every current browser and Windows read."""
    header = struct.pack("<HHH", 0, 1, len(pngs))
    entries, images = b"", b""
    offset = len(header) + 16 * len(pngs)
    for size, png in sorted(pngs.items()):
        side = 0 if size == 256 else size  # one byte each way; 0 means 256
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(png), offset)
        images += png
        offset += len(png)
    return header + entries + images


def main() -> None:
    svg = SOURCE.read_text(encoding="utf-8")
    chromium = find_chromium()
    with tempfile.TemporaryDirectory() as tmp:
        workdir = pathlib.Path(tmp)
        light = light_only(svg)
        icon = ico({size: render(chromium, light, size, workdir) for size in ICO_SIZES})
        touch_icon = render(chromium, full_bleed(svg), TOUCH_SIZE, workdir)
    # Nothing is written until both have rendered, so a failed run changes neither file.
    ICO.write_bytes(icon)
    TOUCH_ICON.write_bytes(touch_icon)
    for path in (ICO, TOUCH_ICON):
        print(f"wrote {path.relative_to(REPO)} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
