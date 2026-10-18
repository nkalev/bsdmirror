# Mirror card marks

- **Status:** proposed, 2026-10-17
- **Scope:** the three project logos on the public site's mirror cards
- **Supersedes:** the "Kept, restyled to fit" decision for those logos in `2026-09-25-reflection-redesign.md`, section 2, and the "logo" wording in its sections 4.1 and 5.1

## 1. Summary

The mirror cards get three original marks -- a trident, a flag and a blowfish -- in place of the February drawings of each project's emblem. They are rendered the way the site's icons are (section 4.7 of the Reflection spec): CSS masks painted in `--text-primary`, so they follow the light and dark theme with everything else. Unlike the icons, which are 1.6-unit strokes, the marks are filled silhouettes, which carry logo weight next to the 18px names and stay crisp at the card's 26px.

**What does not change:** the card markup around the tile, the 40px tile, the CSP, nginx, the API, the admin console.

## 2. Why original marks, not the official logos

Decided with the user on 2026-10-17 from a side-by-side of the current drawings and the drafts, in both themes.

**The current files** (`freebsd-logo.svg`, `netbsd-logo.svg`, `openbsd-logo.svg`, from the February redesign) are crude at 26px, carry the only saturated colours left on the page, and sit in the one legal position both foundations rule out: a FreeBSD-coloured disc with horns and a daemon face, a redrawn NetBSD flag, a Puffy derivative.

**What the projects say**, read on 2026-10-17:

| Project | Terms | Source |
|---|---|---|
| FreeBSD | The official logo may be used, without permission, on a site that promotes FreeBSD. It must link to freebsd.org or the Foundation, must not be altered "in any way", and its first use carries the ® and a trademark notice. The daemon is Kirk McKusick's copyright: personal use with his credit line. | freebsd.org/logo/; freebsdfoundation.org trademark usage terms and FAQ; mckusick.com/beastie/mainpage/copyright.html |
| NetBSD | The flag is licensed for non-commercial sites "to identify NetBSD-related web pages"; it must not be cut up or materially altered; the licence is revocable. | netbsd.org/gallery/logos.html; netbsd.org/about/disclaimer.html |
| OpenBSD | The artwork and policy pages state no terms for Puffy. Unverified either way. | openbsd.org/artwork.html; openbsd.org/policy.html |

So a *redrawn* official logo is the one thing not allowed. Two directions were viable: the official files unaltered, with the links and notices, or original marks. The user chose original marks: they fit the Reflection system (chrome greys, one accent, theme-aware masks), they need no notices, and they read as the three projects to anyone who knows BSD. The marks are generic symbols, not renditions of the trademarks: a trident is not the horned FreeBSD mark, a plain flag on a pole is not the NetBSD flag image, and a line-art blowfish is not Puffy. **Nobody may later "improve" them toward the official marks**; that is the altered-logo case the terms forbid. The README under `img/` says so.

Rejected variants: a 1.6-stroke outline style (too thin next to 18px Unbounded names), and tinting each tile with its project's colour (the Reflection spec removed the per-OS colours on purpose).

## 3. The marks

Conventions:

- `viewBox="0 0 24 24"`, the icon grid, and no `width`/`height` on the root, so the mask scales to its box. No `<style>` element. Filled shapes in `#000`; the trident's U is the one stroke (2.2 units). Colour is irrelevant to a mask, which reads alpha, and black keeps the files legible when opened directly. The test in section 5 checks each of these.
- Inert, like every SVG under `/img/` (`tests/test_images.py::test_every_svg_here_is_inert` already covers new files).
- Each fits inside a 1.3-unit margin of the grid: about 1.4px of air inside the 26px mask box, which itself sits 7px inside the 40px tile.
- Where two shapes meet, one runs into the other by at least a unit. Two anti-aliased edges that only touch leave a faint seam when zoomed; the flag therefore starts under the pole, and the trident's outer prongs reach into the U's stroke.

### 3.1 FreeBSD: `freebsd-trident.svg`

Beastie's trident, not Beastie. A 5.5-unit U whose arms rise straight to the outer prongs' shoulders, so the stroke and the prong coincide instead of meeting at a joint; three tips (shoulders at y=4.8, tips at y=1.3); a shaft to y=22.6.

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
  <!-- Trident, drawn for a CSS mask: a U whose arms rise under the outer prongs, three tips, a shaft. -->
  <path d="M6.5 4.8V9.3a5.5 5.5 0 0 0 11 0V4.8" fill="none" stroke="#000" stroke-width="2.2"/>
  <path d="M5.4 9.3V4.8L6.5 1.3l1.1 3.5v4.5Z"/>
  <path d="M16.4 9.3V4.8l1.1-3.5 1.1 3.5v4.5Z"/>
  <path d="M10.9 13V4.8L12 1.3l1.1 3.5V13Z"/>
  <rect x="10.9" y="11" width="2.2" height="11.6" rx="1.1"/>
</svg>
```

### 3.2 NetBSD: `netbsd-flag.svg`

A flag on a pole with a base. The visible flag is 14 wide (from the pole's right edge at x=6.6 to x=20.6) by 9 tall, with one wave: two cubic segments, hump then dip, amplitude 1.4; the bottom edge is the top edge moved down 9 units. The path begins with a straight stub from x=5.5, inside the pole, so the curve the user approved is unchanged.

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
  <!-- Flag, drawn for a CSS mask: pole, base, a flag with one wave. -->
  <rect x="4.4" y="1.4" width="2.2" height="21.2" rx="1.1"/>
  <rect x="1.6" y="20.8" width="7.8" height="1.8" rx="0.9"/>
  <path d="M5.5 4H6.6C8.9 2.1 11.3 2.1 13.6 4S18.3 5.9 20.6 4V13C18.3 14.9 15.9 14.9 13.6 13S8.9 11.1 6.6 13H5.5Z"/>
</svg>
```

### 3.3 OpenBSD: `openbsd-blowfish.svg`

A blowfish facing right: a 14 by 12.4 oval body with an eye (a hole, with a pupil), ten short bristles kept off the face and rooted a unit inside the body, a pout, and a forked tail whose tip reaches 1.1 units into the body.

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
  <!-- Blowfish, drawn for a CSS mask: body with an eye, ten bristles, a pout, a forked tail. -->
  <path fill-rule="evenodd" d="M5.8 12.6a7.0 6.2 0 1 0 14.0 0a7.0 6.2 0 1 0-14.0 0ZM14.3 10.7a1.7 1.7 0 1 0 3.4 0a1.7 1.7 0 1 0-3.4 0Z"/>
  <circle cx="16.4" cy="10.7" r="0.8"/>
  <circle cx="19.8" cy="13.7" r="1.15"/>
  <path d="M16.81 8.74 17.85 6.05 15.62 8.01ZM14.55 7.63 14.33 4.72 13.11 7.41ZM11.96 7.45 10.52 4.87 10.55 7.78ZM9.53 8.24 7.14 6.47 8.41 9.05ZM7.71 9.84 4.82 9.22 7.09 10.99ZM7.09 14.21 4.82 15.98 7.71 15.36ZM8.41 16.15 7.14 18.73 9.53 16.96ZM10.55 17.42 10.52 20.33 11.96 17.75ZM13.11 17.79 14.33 20.48 14.55 17.57ZM15.62 17.19 17.85 19.15 16.81 16.46Z"/>
  <path d="M6.9 12.6L1.6 8.6L2.9 12.6L1.6 16.6Z"/>
</svg>
```

The bristle coordinates come from a generator (angles 55, 80, 105, 130, 155, 205, 230, 255, 280 and 305 degrees; base corners 7 degrees either side, on an ellipse one unit inside the body; tips 1.8 units outside it). The file is the artefact; the generator is not kept.

### 3.4 Names

New names, because `/img/` is served with `expires 7d` and `Cache-Control: public, immutable` (`img/README.md`): a browser that has `freebsd-logo.svg` would keep it for a week. The names say what is drawn, not "logo", which matches section 2. The three `*-logo.svg` files are deleted in the same change. Outside `docs/`, which keeps its history as written, the old names appear in `index.html`, `img/README.md` and one path in `tests/test_nginx_cache_policy.py` (`grep -rn 'bsd-logo' --exclude-dir=docs`), all updated here.

## 4. Rendering

### 4.1 Markup, `frontend/public/index.html`

Each card's tile holds a decorative span instead of an `<img>`:

```html
<span class="mirror-logo-tile"><span class="mirror-logo mirror-logo-freebsd" aria-hidden="true"></span></span>
```

and `mirror-logo-netbsd`, `mirror-logo-openbsd` on the other two. The mark is decorative: the `<h3 class="mirror-name">` beside it already names the card, so today's `alt="FreeBSD"` had a screen reader say each name twice. Nothing else in the card changes; the copy button's opening tag stays byte-identical (`tests/test_public_page_csp.py`'s negative control).

### 4.2 Styles, `frontend/public/css/style.css`

`.mirror-logo` becomes a mask in the manner of `.icon` (the same longhand mask properties, in the same order), painted in `--text-primary`, which is the text colour on the `--bg-secondary` tile and so already meets the contrast bar; and one rule per mark names its file:

```css
.mirror-logo {
    display: block;
    width: 26px;
    height: 26px;
    background-color: var(--text-primary);
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
}

.mirror-logo-freebsd {
    -webkit-mask-image: url(/img/freebsd-trident.svg);
    mask-image: url(/img/freebsd-trident.svg);
}
```

`.mirror-logo-tile` is unchanged. The CSP needs nothing: `img-src 'self'` already admits mask images, as the icons on the same page prove.

What the existing checks cover, stated exactly:

- `tests/test_fonts.py::test_every_css_url_is_a_file_on_this_origin`: every `url()` in every stylesheet names a file that exists, the new mask URLs included.
- `tests/test_public_page_csp.py` (`tests/js/csp_click_harness.mjs`): loads the public page under the production CSP, in the light theme only, and fails on any console message naming the Content Security Policy.
- `tests/test_contrast.py` (`tests/js/contrast_harness.mjs`): loads the public page in both themes, with no CSP header on the public pages, and measures contrast on named elements; the tile is not one of them.

So appearance in both themes is proved by the look in section 6, item 3, not by a harness.

### 4.3 Theme

Nothing to do: the mask takes `--text-primary`, which the theme toggle swaps. This is the point of masks over `<img>` -- an `<img>` SVG cannot see the page's tokens.

## 5. Changes by file and owner

| Owner | File | Change |
|---|---|---|
| web-designer | `frontend/public/img/freebsd-trident.svg`, `netbsd-flag.svg`, `openbsd-blowfish.svg` | New, byte for byte as in section 3 |
| web-designer | `frontend/public/img/freebsd-logo.svg`, `netbsd-logo.svg`, `openbsd-logo.svg` | Deleted |
| web-designer | `frontend/public/index.html` | Three tile lines, section 4.1 |
| web-designer | `frontend/public/css/style.css` | `.mirror-logo` block and three mark rules, section 4.2 |
| web-designer | `frontend/public/img/README.md` | "Project logos" becomes "Project marks": what they are, the terms table from section 2 in brief, the rule against redrawing toward the official marks, the conventions from section 3 |
| developer | `tests/test_public_page_structure.py` | New test, below |
| developer | `tests/test_images.py` | Two new tests, below; the module docstring's "the logos" becomes "the project marks" |
| developer | `tests/test_nginx_cache_policy.py` | `LONG_CACHED`: `/img/freebsd-logo.svg` becomes `/img/freebsd-trident.svg` |
| -- | `docs/design/2026-09-25-reflection-redesign.md` | A "superseded 2026-10-17, see `2026-10-17-mirror-card-marks.md`" pointer on the logos row of the section 2 table, the token row in section 4.1 that says "The cards carry each project's logo instead", and the section 5.1 card bullet "The project's logo in a 40px raised tile" |

**The tests**, each keyed on the fixed list `freebsd`, `netbsd`, `openbsd` so none can pass by matching nothing:

- `test_public_page_structure.py::test_each_mirror_card_tile_holds_one_decorative_mark`: for each card, its `.mirror-logo-tile` has exactly one element child; it is a `<span>` whose classes are exactly `mirror-logo` and `mirror-logo-<os>`, with `aria-hidden="true"`; and the card contains no `<img>`. Fails today because the tile's only child is an `<img>`.
- `test_images.py::test_each_project_mark_is_a_black_mask_on_the_icon_grid[<os>]`: the mark file from the fixed mapping (`freebsd` to `freebsd-trident.svg`, `netbsd` to `netbsd-flag.svg`, `openbsd` to `openbsd-blowfish.svg`) exists; its root has `viewBox="0 0 24 24"` and neither `width` nor `height`; it holds no `<style>`; every `fill` and `stroke` attribute in it is `#000` or `none`. Fails today because the file does not exist.
- `test_images.py::test_each_project_mark_is_masked_onto_its_card[<os>]`: `style.css` has a rule whose selector is exactly `.mirror-logo-<os>` and whose `-webkit-mask-image` and `mask-image` are both `url(/img/<file>)` for that OS's file from the same mapping. Pinning the mapping is what catches two rules with their files swapped. Fails today because no such rule exists.

**Routing.** The work crosses the web-designer/developer boundary, so it is routed as the table says (CLAUDE.md, "When to delegate"), in two steps on branch `feat/mirror-card-marks`: `developer` writes the three tests and the cache-policy path change and shows them red; `web-designer` then makes the asset, markup, style and README changes and shows them green. This session verifies each step's output against this spec, commits this document and the three superseded pointers in the parent spec itself, and keeps one commit per step.

## 6. Definition of done

1. Tests first: the three new tests fail on the current tree for the reasons given in section 5, then pass once the web-designer step lands.
2. `docker compose run --rm test` exits 0, read from the exit code, not the last line.
3. A look at the cards in both themes on a local serve of the branch, at 26px and zoomed, before the PR is opened; the before/after comparison goes in the PR body.
4. CI green on the merge commit, then `scripts/deploy.sh --yes main` on the server, with the user's approval. `verify_frontend_assets` byte-checks the three new files and confirms the three deleted ones no longer serve their old bytes. No migration, no nginx change.
5. The live cards checked in both themes after the deploy.

## 7. Out of scope

- The admin console shows no project logos; nothing to do there.
- The favicon, the b|d mark and the per-OS colours are untouched.
- Larger or recoloured tiles: the 40px tile and 26px mark from the Reflection spec stay.
