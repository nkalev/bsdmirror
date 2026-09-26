# Images

The images here are served from `/img/` with `expires 7d` and
`Cache-Control: public, immutable` (`nginx/sites/production/production.conf`).
A browser that has one keeps it for a week without asking again, so
**never change an image in place**. Ship a changed image under a new name, and
update what references it in the same commit.

The Content-Security-Policy allows images from this origin only
(`img-src 'self'`, no `data:`), and an SVG opened directly renders as a
document. So no SVG here has a script, an event handler, a `style=` attribute,
or a reference to anything outside its own file. `tests/test_images.py` checks
every SVG here for all four.

## The b|d mark

In "bsd", the b and the d are mirror images of each other. The mark keeps
them and turns the s into a mirror line. The geometry is on a 64-unit grid
(`docs/design/2026-09-25-reflection-redesign.md`, section 4.5):

| Size | Stem (x, width, y) | Bowl centre | Outer / inner radius | Axis (x, width, y, corner radius) |
|---|---|---|---|---|
| Regular, 25px and larger | 5, 7, 6-58 | (17, 46) | 12 / 6 | 30.7, 2.6, 3-61, 1.3 |
| Small, 24px and smaller | 4, 8, 8-57 | (16, 46) | 11 / 4.2 | 30, 4, 5-59, 2 |

The d is the b mirrored: `translate(64 0) scale(-1 1)`.

`mark-glyph.svg` (b and d) and `mark-axis.svg` (the mirror line) use the
regular geometry in one colour. They are drawn for CSS masks, the way the
redesigned admin console is to use them (design sections 4.5 and 6.1): the
glyph painted in `--text-primary`, the axis in `--accent-primary`.

## Icons

`icons/NAME.svg` holds 15 icons on a 24-unit grid. Each is drawn with 1.6-unit
round strokes, set once on the root `<svg>`. They are drawn for CSS masks, the
way the redesigned pages are to use them (design section 4.7), so each takes
the text colour of the element it sits in:

    <span class="icon icon-copy" aria-hidden="true"></span>

To add an icon, draw it on the same grid with the same root attributes, and add
its name to `ICON_NAMES` in `tests/test_images.py`.

## Project logos

`freebsd-logo.svg`, `netbsd-logo.svg` and `openbsd-logo.svg` are simple
drawings of each project's emblem, used on the mirror cards.

## Favicons

The favicon set is the exception to never changing a file in place: browsers
ask for `/favicon.ico` by that name, the pages link `favicon.svg` and
`apple-touch-icon.png` by theirs, and the deploy's own probe requests
`favicon.svg`. A new version of any of them reaches returning visitors within
the week.

- **`favicon.svg`:** the small mark on a rounded tile. It is light by default,
  and one `@media (prefers-color-scheme: dark)` rule in its `<style>` turns it
  into the dark tile. The light colours are presentation attributes, which the
  CSP's `style-src 'self'` never blocks.
