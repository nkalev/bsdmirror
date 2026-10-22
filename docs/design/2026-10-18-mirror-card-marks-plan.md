# Mirror card marks: implementation plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the three mirror-card logo images with the original marks of `2026-10-17-mirror-card-marks.md`, masked onto the tiles in the text colour.

**Architecture:** Three new SVG files under `frontend/public/img/` become CSS masks on a decorative `<span>` in each card's tile; the three old `*-logo.svg` files go away. Tests pin the markup, the files' grid and paint, and the class-to-file mapping. No change to the CSP, nginx, the API or the admin console.

**Tech Stack:** static HTML and CSS, SVG, pytest run through `docker compose run --rm -T test` (the repo is mounted read-only in that container, so nothing in it writes to the checkout), ruff from the same container.

**Spec:** `docs/design/2026-10-17-mirror-card-marks.md`. Where this plan and the spec differ, the spec wins; say so in the report.

**Branch:** `feat/mirror-card-marks`, already created from `main` at 5f276fe. Nothing is committed on it yet; the spec and this plan are untracked there.

---

## File structure

| File | Task | Responsibility |
|---|---|---|
| `tests/test_public_page_structure.py` | 1 | One new test at the end: each tile holds exactly one decorative mark span and the card holds no `<img>` |
| `tests/test_images.py` | 1 | Constants `PROJECT_MARKS`, `PROJECT_MARK_PAINT`, `STYLE_CSS`; two new parametrised tests after the icon-consumer tests; one word in the module docstring |
| `tests/test_nginx_cache_policy.py` | 1 | One path in `LONG_CACHED` |
| `frontend/public/img/freebsd-trident.svg`, `netbsd-flag.svg`, `openbsd-blowfish.svg` | 2 | New, byte for byte from this plan |
| `frontend/public/img/freebsd-logo.svg`, `netbsd-logo.svg`, `openbsd-logo.svg` | 2 | Deleted |
| `frontend/public/index.html` | 2 | Three tile lines |
| `frontend/public/css/style.css` | 2 | The `.mirror-logo` block and three mark rules |
| `frontend/public/img/README.md` | 2 | The "Project logos" section becomes "Project marks" |
| `docs/design/2026-09-25-reflection-redesign.md` | 3 | Three superseded pointers |
| `docs/design/2026-10-17-mirror-card-marks.md`, this plan | 3 | Committed |

## How the tasks run

- **Task 1** goes to the `developer` agent and **Task 2** to the `web-designer` agent (CLAUDE.md's owner table), each dispatched with its task text below pasted in full, the spec path, and these standing rules: run tests and ruff only through `docker compose run --rm -T test ...`, never on the host; change only the files the task names; do not commit; report the commands run and their output verbatim, with the exit code. Pass `model: "sonnet"` in the Agent call: this session loaded the agent files before they moved to Sonnet 5.5, and the alias resolves to `claude-sonnet-5-5`.
- Task 1 runs first and ends red by design: its tests describe files and markup Task 2 creates. Task 2 then ends green. Neither commits; the controller commits in Task 3 in an order that keeps every commit green: documentation, then Task 2's files, then Task 1's.
- **Task 3** is the controller's: verification against the spec, the whole suite, the look in both themes, the commits.

---

## Task 1 (developer): the tests, red

**Files:**
- Modify: `tests/test_public_page_structure.py` (append at the end of the file)
- Modify: `tests/test_images.py` (docstring line 2; constants after `ICON_STROKE`; two tests after `test_every_icon_class_named_in_admin_js_or_index_html_is_a_real_icon`)
- Modify: `tests/test_nginx_cache_policy.py:213`

- [ ] **Step 1: the markup test.** Append to the end of `tests/test_public_page_structure.py`, after `test_at_least_the_expected_icon_variants_are_present`:

```python


# ===========================================================================
# Mirror card marks: one decorative mask span per tile
# (docs/design/2026-10-17-mirror-card-marks.md, section 4.1).
# ===========================================================================
def test_each_mirror_card_tile_holds_one_decorative_mark():
    """The mark is a <span> masked by style.css, not an <img>: an <img> SVG
    cannot see the page's colour tokens, so it could not follow the theme.
    It is decorative because the <h3> beside it already names the card."""
    for os_id in MIRRORS:
        card = find_one(ROOT, class_="mirror-card", attrs={"data-mirror": os_id})
        tile = find_one(card, class_="mirror-logo-tile")
        children = tile.element_children()
        assert len(children) == 1, f"{os_id}: the tile must hold exactly one element"
        mark = children[0]
        assert mark.tag == "span", f"{os_id}: the mark is a masked <span>, not <{mark.tag}>"
        expected = {"mirror-logo", f"mirror-logo-{os_id}"}
        assert mark.classes() == expected, f"{os_id}: {sorted(mark.classes())}"
        assert mark.attrs.get("aria-hidden") == "true", f"{os_id}: the mark must be aria-hidden"
        assert list(find_all(card, tag="img")) == [], f"{os_id}: an <img> in a mirror card"
```

- [ ] **Step 2: the asset tests.** In `tests/test_images.py`:

  1. Line 2 of the module docstring: `icons, the logos and the favicon set.` becomes `icons, the project marks and the favicon set.`
  2. After the `ICON_STROKE = {...}` dict (before `# The b's bowl is a ring`), insert:

```python
# The project marks on the mirror cards
# (docs/design/2026-10-17-mirror-card-marks.md): original silhouettes that
# style.css masks onto each card's tile in --text-primary. "Mark" alone means
# the b|d mark in this file, so these carry the PROJECT_ prefix.
PROJECT_MARKS = {
    "freebsd": "freebsd-trident.svg",
    "netbsd": "netbsd-flag.svg",
    "openbsd": "openbsd-blowfish.svg",
}
# A mask reads alpha, so paint never shows; black keeps a file legible when
# opened directly, and `none` is how a shape says it has no stroke or fill.
PROJECT_MARK_PAINT = {"#000", "none"}
STYLE_CSS = PUBLIC / "css" / "style.css"
```

  3. After `test_every_icon_class_named_in_admin_js_or_index_html_is_a_real_icon` (before `test_mark_glyph_is_the_regular_b_and_its_mirror_image`), insert:

```python
@pytest.mark.parametrize("os_id", sorted(PROJECT_MARKS))
def test_each_project_mark_is_a_black_mask_on_the_icon_grid(os_id):
    """The icon grid, no width/height so the mask scales to its box, no
    <style>, and nothing painted in a colour. Inertness is checked for every
    SVG here by test_every_svg_here_is_inert."""
    path = IMG / PROJECT_MARKS[os_id]
    assert path.is_file(), f"{path.relative_to(PUBLIC)} is missing"
    root = svg_root(path)
    assert root.get("viewBox") == "0 0 24 24", f"{path.name}: viewBox={root.get('viewBox')!r}"
    assert root.get("width") is None and root.get("height") is None, f"{path.name}: sized root"
    assert "style" not in tags(root), f"{path.name}: <style>"
    for element in root.iter():
        for name in ("fill", "stroke"):
            value = element.get(name)
            assert value is None or value in PROJECT_MARK_PAINT, f"{path.name}: {name}={value!r}"


@pytest.mark.parametrize("os_id", sorted(PROJECT_MARKS))
def test_each_project_mark_is_masked_onto_its_card(os_id):
    """style.css names each file from its own card's class, in both mask-image
    longhands. Pinning the mapping is what catches two rules with their files
    swapped; test_fonts.py already checks that every url() names a file."""
    css = STYLE_CSS.read_text(encoding="utf-8")
    rule = re.search(rf"^\.mirror-logo-{os_id}\s*\{{([^}}]*)\}}", css, re.M)
    assert rule, f".mirror-logo-{os_id} has no rule in style.css"
    for prop in ("-webkit-mask-image", "mask-image"):
        declared = re.findall(rf"(?<![\w-]){prop}\s*:\s*([^;]+);", rule.group(1))
        want = [f"url(/img/{PROJECT_MARKS[os_id]})"]
        assert declared == want, f".mirror-logo-{os_id} {prop}: {declared}"
```

- [ ] **Step 3: the cache-policy path.** In `tests/test_nginx_cache_policy.py`, `LONG_CACHED`: the line `    "/img/freebsd-logo.svg",` becomes `    "/img/freebsd-trident.svg",`. (The test resolves the path against the parsed nginx config; it does not need the file. The old name just goes stale.)

- [ ] **Step 4: run the three files and watch them fail for the right reasons.**

```bash
docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_public_page_structure.py tests/test_images.py tests/test_nginx_cache_policy.py; echo "rc=$?"
```

Expected: `rc=1`, with exactly these seven failures and nothing else failing:

- `test_public_page_structure.py::test_each_mirror_card_tile_holds_one_decorative_mark` -- `freebsd: the mark is a masked <span>, not <img>`
- `test_images.py::test_each_project_mark_is_a_black_mask_on_the_icon_grid[freebsd|netbsd|openbsd]` -- `img/<file> is missing`
- `test_images.py::test_each_project_mark_is_masked_onto_its_card[freebsd|netbsd|openbsd]` -- `.mirror-logo-<os> has no rule in style.css`

Any other failure, or a different message, means the test or this plan is wrong: stop and report it.

- [ ] **Step 5: lint.**

```bash
docker compose run --rm -T test ruff check tests/test_public_page_structure.py tests/test_images.py tests/test_nginx_cache_policy.py; echo "rc=$?"
docker compose run --rm -T test ruff format --check tests/test_public_page_structure.py tests/test_images.py tests/test_nginx_cache_policy.py; echo "rc=$?"
```

Expected: `rc=0` for both. The container cannot write to the checkout, so a formatting difference is fixed by hand and re-checked.

- [ ] **Step 6: report.** `git status --short` and `git diff --stat`, the pytest summary line and the seven failure messages, both ruff lines. Do not commit.

---

## Task 2 (web-designer): the marks, green

**Files:**
- Create: `frontend/public/img/freebsd-trident.svg`, `frontend/public/img/netbsd-flag.svg`, `frontend/public/img/openbsd-blowfish.svg`
- Delete: `frontend/public/img/freebsd-logo.svg`, `frontend/public/img/netbsd-logo.svg`, `frontend/public/img/openbsd-logo.svg`
- Modify: `frontend/public/index.html:148,175,202`
- Modify: `frontend/public/css/style.css:640-644`
- Modify: `frontend/public/img/README.md:50-54`

Task 1 has already run and left its tests red in the working tree; this task makes them green without touching any test file.

- [ ] **Step 1: the three files, byte for byte.** Each file is exactly the block below, including the comment line, two-space indentation and a trailing newline after `</svg>`. Write them with a heredoc or the Write tool; do not retype them.

`frontend/public/img/freebsd-trident.svg`:

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

`frontend/public/img/netbsd-flag.svg`:

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
  <!-- Flag, drawn for a CSS mask: pole, base, a flag with one wave. -->
  <rect x="4.4" y="1.4" width="2.2" height="21.2" rx="1.1"/>
  <rect x="1.6" y="20.8" width="7.8" height="1.8" rx="0.9"/>
  <path d="M5.5 4H6.6C8.9 2.1 11.3 2.1 13.6 4S18.3 5.9 20.6 4V13C18.3 14.9 15.9 14.9 13.6 13S8.9 11.1 6.6 13H5.5Z"/>
</svg>
```

`frontend/public/img/openbsd-blowfish.svg`:

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

Check: `sha256sum frontend/public/img/{freebsd-trident,netbsd-flag,openbsd-blowfish}.svg` must print

```
76125ee96a889f289dc32e1de668557c471c71fe644819fdf435c5693bc385cf  frontend/public/img/freebsd-trident.svg
5b4871bf054000caa6fde5611e9f8f4663411927841b5613c83b69b88ae8c63d  frontend/public/img/netbsd-flag.svg
476b26621e2a81fcb0ecae30bb3546c4562ae69f779ba0b22d0328e45eafe463  frontend/public/img/openbsd-blowfish.svg
```

- [ ] **Step 2: delete the old files.** `rm frontend/public/img/freebsd-logo.svg frontend/public/img/netbsd-logo.svg frontend/public/img/openbsd-logo.svg` -- plain `rm`, not `git rm`: nothing is staged until Task 3 builds each commit from an explicit path list.

- [ ] **Step 3: the markup.** In `frontend/public/index.html`, the three tile lines (148, 175 and 202) become, each keeping its 28-space indentation:

```html
                            <span class="mirror-logo-tile"><span class="mirror-logo mirror-logo-freebsd" aria-hidden="true"></span></span>
```
```html
                            <span class="mirror-logo-tile"><span class="mirror-logo mirror-logo-netbsd" aria-hidden="true"></span></span>
```
```html
                            <span class="mirror-logo-tile"><span class="mirror-logo mirror-logo-openbsd" aria-hidden="true"></span></span>
```

Nothing else in the file changes; `grep -c '<img' frontend/public/index.html` must drop by exactly three.

- [ ] **Step 4: the styles.** In `frontend/public/css/style.css`, replace the block

```css
.mirror-logo {
    display: block;
    width: 26px;
    height: 26px;
}
```

with

```css
/* The project marks (docs/design/2026-10-17-mirror-card-marks.md): original
   silhouettes drawn for CSS masks, painted in the text colour so they follow
   the theme the way the icons do. Each card's class names its file. */
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

.mirror-logo-netbsd {
    -webkit-mask-image: url(/img/netbsd-flag.svg);
    mask-image: url(/img/netbsd-flag.svg);
}

.mirror-logo-openbsd {
    -webkit-mask-image: url(/img/openbsd-blowfish.svg);
    mask-image: url(/img/openbsd-blowfish.svg);
}
```

`.mirror-logo-tile` above it and `.mirror-name` below it are unchanged.

- [ ] **Step 5: the README.** In `frontend/public/img/README.md`, replace the section

```markdown
## Project logos

`freebsd-logo.svg`, `netbsd-logo.svg` and `openbsd-logo.svg` are simple
drawings of each project's emblem, used on the mirror cards.
```

with

```markdown
## Project marks

`freebsd-trident.svg`, `netbsd-flag.svg` and `openbsd-blowfish.svg` are the
marks on the mirror cards (`docs/design/2026-10-17-mirror-card-marks.md`).
They are original drawings -- a trident, a flag on a pole, a blowfish -- and
deliberately not the projects' logos. FreeBSD permits its official logo on
a site like this one only unaltered, linked to the project and carrying a
trademark notice; NetBSD licenses its flag to non-commercial sites, not cut up
or materially altered; OpenBSD's pages state no terms for Puffy. A generic
symbol needs none of that, so **never redraw these toward the official
emblems**: that re-creates the altered-logo case the terms rule out.

They are drawn on the icon grid -- `viewBox="0 0 24 24"`, no `width`/`height`,
no `<style>`, every `fill`/`stroke` `#000` or `none`, nothing outside a
1.3-unit margin -- but as filled silhouettes rather than 1.6-unit strokes, and
`style.css` masks each onto its card's tile in `--text-primary`:

    <span class="mirror-logo mirror-logo-freebsd" aria-hidden="true"></span>

`tests/test_images.py` pins the grid, the paint and the class-to-file mapping;
`tests/test_public_page_structure.py` pins the markup. A changed mark ships
under a new name, like every image here.
```

- [ ] **Step 6: run the tests Task 1 left red, plus the two that watch stylesheet URLs and the public page under the CSP.**

```bash
docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_public_page_structure.py tests/test_images.py tests/test_nginx_cache_policy.py tests/test_fonts.py tests/test_public_page_csp.py; echo "rc=$?"
```

Expected: every test passes, `rc=0`. (`test_public_page_csp.py` drives headless Chrome; if it reports a skip for a missing browser, say so -- the controller runs the whole suite in Task 3.)

- [ ] **Step 7: report.** `git status --short`: fourteen lines -- three ` D` (the old logos), six ` M` (Task 1's three test files, `index.html`, `style.css`, the README) and five `??` (the three new SVGs and the two design documents). Then the sha256 lines from Step 1 and the pytest summary line. Do not commit.

---

## Task 3 (controller): verify, look, commit

- [ ] **Step 1: the files are the spec's.** Compare each new SVG with the block embedded in the spec's section 3; they must be byte-identical. Diff `index.html`, `style.css` and `README.md` against Task 2's text. Confirm no file outside the two tasks' lists changed: `git status --short` shows exactly the twelve paths of Tasks 1 and 2 (three deleted, six modified, three new) plus the two untracked design documents, and nothing is staged.

- [ ] **Step 2: the whole suite.**

```bash
docker compose run --rm -T test; echo "rc=$?"
```

Expected: `rc=0`. Record the summary line (the count is seven higher than on `main`).

- [ ] **Step 3: the look.** Serve the checkout's `frontend/public` from a plain nginx container (no API, so the pills stay at "Checking…"; the cards, masks and theme toggle do not need it):

```bash
docker run --rm -d --name marks-look -p 127.0.0.1:8089:80 -v "$PWD/frontend/public:/usr/share/nginx/html:ro" nginx:1.25-bookworm
```

Open `http://127.0.0.1:8089/#mirrors` in the browser pane; look at the three tiles in both themes (the header's theme toggle), then zoom on the blowfish's eye: the top-right bristle sits half a pixel from the hole at 26px and must not visibly notch it. Screenshot the cards in both themes. Then `docker rm -f marks-look`.

The "before" half of the spec's comparison is the live site, `https://mirror.kalev.systems/#mirrors`, which serves `main` (its footer shows the SHA, 5f276fe): screenshot its cards in both themes the same way, switching the theme back afterwards. The four screenshots go in the PR body.

- [ ] **Step 4: the superseded pointers.** In `docs/design/2026-09-25-reflection-redesign.md`:
  - line 28, the table row ending `| Kept, restyled to fit |` ends `| Kept, restyled to fit. Superseded 2026-10-17: original marks instead, see `2026-10-17-mirror-card-marks.md` |`
  - line 115, the cell `Removed in PR 2. The cards carry each project's logo instead.` gains ` Superseded 2026-10-17: the cards carry original marks, see `2026-10-17-mirror-card-marks.md`.`
  - line 272, `   - The project's logo in a 40px raised tile.` becomes `   - The project's logo in a 40px raised tile. Superseded 2026-10-17: an original mark, see `2026-10-17-mirror-card-marks.md`.`

- [ ] **Step 5: three commits, each green, under the user's identity, subject lines only.** Each is built from an explicit path list, so nothing from another set rides along (`git add` of a deleted path stages the deletion):

```bash
git add docs/design/2026-10-17-mirror-card-marks.md docs/design/2026-10-18-mirror-card-marks-plan.md docs/design/2026-09-25-reflection-redesign.md
git commit -q -m "Design original marks for the mirror cards" && git status --short
```

```bash
git add frontend/public/img/freebsd-trident.svg frontend/public/img/netbsd-flag.svg frontend/public/img/openbsd-blowfish.svg frontend/public/img/freebsd-logo.svg frontend/public/img/netbsd-logo.svg frontend/public/img/openbsd-logo.svg frontend/public/index.html frontend/public/css/style.css frontend/public/img/README.md
git commit -q -m "Replace the mirror card logos with original marks" && C2=$(git rev-parse HEAD) && echo "$C2" && git status --short
```

```bash
git add tests/test_public_page_structure.py tests/test_images.py tests/test_nginx_cache_policy.py
git commit -q -m "Test the mirror card marks" && git status --short
```

After each commit `git status --short` must show only what the later commits will take; after the third it is empty. `git show --stat` of each must list 3, 9 and 3 files.

Commit 2 is green by reasoning (the old cache-policy path still resolves against the nginx config, and every other check already covers the new files), and the whole suite at the tip proves commit 3. For evidence on commit 2 itself, run the suite from a worktree checked out at the SHA printed above (`C2`, not `HEAD~1`, which only means commit 2 once commit 3 exists), reusing the project name so the test image is not rebuilt. A fresh shell has no `SCRATCH`, so set it in the same command, to this session's scratchpad directory:

```bash
SCRATCH=/private/tmp/claude-501/-Users-nkalev-git-repos-personal-bsdmirror/ebdd0c5f-23c0-4b2a-97f8-32f77546194c/scratchpad; C2=<the SHA printed after commit 2>; git worktree add -q "$SCRATCH/marks/wt-2" "$C2" && docker compose -p bsdmirror --project-directory "$SCRATCH/marks/wt-2" run --rm -T test; echo "rc=$?"; git worktree remove --force "$SCRATCH/marks/wt-2"
```

Expected: `rc=0`. The summary line differs from Step 2's: in a worktree `/repo/.git` is a file, so the git-backed checks in `tests/test_gitignore_covers_secrets.py` skip, as that file documents.

- [ ] **Step 6: hand back.** Report the three SHAs, both suite runs' summary lines and exit codes, and the four screenshots. Pushing and opening the PR wait for the user's word; after that, what remains is the spec's section 6 items 4 and 5: CI green on the merge commit, the deploy with the user's approval, and the live check in both themes.
