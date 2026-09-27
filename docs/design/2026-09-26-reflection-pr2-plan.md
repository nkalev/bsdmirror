# Reflection PR 2 (public site and error pages) Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the public site and both error pages in the Reflection style:
- the new palette and type;
- the b|d mark on its reflective floor;
- a sync stream per mirror;
- status pills;
- a `main.js` status model that writes only `data-state` and text.

The admin console must look exactly as it does today until PR 3.

**Architecture:**
- **Groundwork: three tasks with no styling change.**
  - A legacy block pins the admin console's own token values.
  - `main.js` learns the `data-state` model while still writing the old classes.
  - The theme toggle's icon becomes a `data-icon` attribute.
- **The switch.** One commit replaces the palette in `tokens.css`, `style.css`, `index.html`, and the contrast tests that pin all three. They can't land apart: the contrast tests read the stylesheet's selectors and the tokens' values, and the harness reads the page.
- **Three smaller tasks** remove the old class and style writes, bind the page-wide copy buttons and click them under the production CSP, and redesign the error pages.

**Tech stack:**
- static HTML and CSS with no build step;
- vanilla JavaScript;
- pytest in the compose `test` service;
- Node 22 harnesses in a `vm` sandbox or headless Chromium over the DevTools protocol (`tests/js/`);
- one nginx comment.

**Spec:** [2026-09-25-reflection-redesign.md](2026-09-25-reflection-redesign.md), sections 3, 4.1-4.4, 4.7, 4.8, 5, 7, 9, 10 and 11.

**Earliest deploy: 2026-10-03, 10:05 UTC.** That is 7 days after PR 1a's deploy (spec section 8, "Soak period"). PR 1b deployed on 2026-09-26 too, so both conditions in the spec's delivery table hold from then.

**Dry run.** Every code block in Tasks 1 to 7 was built in a throwaway export of this branch and run in the test image. Each chunk was then reviewed independently. Finally the whole plan was applied again from its own text, step by step, in a fresh export: it reproduced every commit byte for byte, and every red, green and whole-suite count in the steps is the one observed there.

| After | Whole suite |
|---|---|
| the base (`ec1c741`) | 1397 passed |
| Task 1 | 1400 |
| Task 2 | 1425 |
| Task 3 | 1425 |
| Task 4 | 1530 |
| Task 5 | 1529 |
| Task 6 | 1537 |
| Task 7 | 1553 |

Tasks 8 and 9 touch the visual check, GitHub and production. Their scripts ran against the export; their GitHub and production steps did not.

**Before Task 1** (*controller*): commit this plan on the branch as its first commit:

```bash
git add docs/design/2026-09-26-reflection-pr2-plan.md
git commit -m "Add the Reflection PR 2 plan"
```

**Decisions the user approved on 2026-09-27, together with this plan:**
- **The error pages' `<title>`s** become "Page not found · BSD Mirror" and "Server error · BSD Mirror". Spec section 1 limits copy changes to those sections 5.1-5.3 list, and the titles are not listed. Approved.
- **Choices the spec leaves open:**
  - the hero stats' labels ("mirrored", "files", "last sync");
  - the access rows keep their "HTTP/HTTPS" and "rsync" labels but drop today's one-line descriptions, which the new row has no room for;
  - the stream's syncing dots are amber (`--status-syncing`), matching the syncing pill, where the mockup used the red accent.

---

## Working rules for every task

**Docker only.** Nothing builds, tests or lints on the host.

| What | Command |
|---|---|
| One test file | `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/FILE.py; echo "rc=$?"` |
| The whole suite | `docker compose run --rm -T test; echo "rc=$?"` |
| Lint | `docker compose run --rm -T test ruff check FILES; echo "rc=$?"` then `docker compose run --rm -T test ruff format --check FILES; echo "rc=$?"` (FILES may be `.`) |
| Format files (writes them) | `docker run --rm -u "$(id -u):$(id -g)" -v "$PWD:/repo" -w /repo -e RUFF_CACHE_DIR=/tmp/ruff-cache bsdmirror-test ruff format FILES` |
| shellcheck, as CI runs it | `docker run --rm -v "$PWD:/mnt:ro" -w /mnt koalaman/shellcheck:v0.11.0 --format=gcc scripts/*.sh; echo "rc=$?"` |
| The compose file | `docker compose config -q; echo "rc=$?"` |

Read the exit code, never the last line. Piping a run through `tail` reports `tail`'s status and turns a red suite green. The `bsdmirror-test` image already exists; no task changes `Dockerfile.test` or a requirements file, so nothing needs rebuilding. Each run prints 4 Pydantic deprecation warnings from `backend/app`, and a whole-suite run 3 more from PyJWT in `tests/test_auth.py`; all 7 predate this work.

**Owners** follow CLAUDE.md, and each step names its owner. A task whose steps have more than one owner is dispatched to them in order, in the same checkout.

**TDD.** Every test step is run, and seen to fail for the reason given, before the step that makes it pass. Paste the output into the task report. Where a test passes from the start, the step says so and says what it guards.

**Commits:**
- Subject only, imperative, under 72 characters, no trailers.
- Each task ends in one commit.
- A task with several owners ends with a commit step owned by the last owner, which commits every file the task names.
- Every commit leaves the suite green: run the whole suite before committing, and commit only on `rc=0`. A test written in one step is committed together with the change that makes it pass.

**`$SCRATCH`** is a directory outside the checkout: the controller's session scratchpad. Throwaway scripts and downloads go there, never into the repo. Every script this plan puts there is written out in full below, so a later session can recreate it. A dispatched subagent does not know `$SCRATCH`: the controller creates the directory a step needs and passes its absolute path.

**Shells and long waits.**
- The controller's shell may be zsh, and every block here works in zsh and bash alike. A glob that must expand inside a container is quoted into `sh -c '...'`, because zsh aborts on a glob that matches nothing on the host.
- Anything that can outlast a few minutes runs with the Bash tool's `run_in_background: true`, and the controller waits for its exit notification. That covers the deploy. CI is never waited on or polled: after a pull request opens, the app's `ccd_pr` tools report it (Task 9 Steps 4 to 6), and a one-off `gh run list` or `gh run view` is fine. The tool stops a foreground command after at most 10 minutes, and killing the ssh session mid-deploy can interrupt the deploy itself.

**Controller steps** are marked *controller*. The session that dispatches the tasks does them itself, because they ask the user something, touch GitHub or production, or edit the working agreement in `CLAUDE.md`.

**Counts.** Every count in this plan was observed in the dry run. The base, `main` at `ec1c741`, gives `1397 passed`, rc=0.

## Files

| File | Change | Owner | Tasks |
|---|---|---|---|
| `frontend/public/css/tokens.css` | The legacy admin block; then the Reflection palette, the new tokens, and the retired ones removed | web-designer | 1, 4 |
| `frontend/public/css/style.css` | Rewritten for the new page | web-designer | 4 |
| `frontend/public/index.html` | The theme icon's `data-icon`; then rewritten to spec section 5.1 | web-designer | 3, 4 |
| `frontend/public/css/error.css` | New dark mapping and reduced motion; then the error-page layout | web-designer | 4, 7 |
| `frontend/public/404.html`, `50x.html` | The mark, the new headline and sentence, "Back to the mirror" | web-designer | 7 |
| `frontend/public/js/main.js` | The `data-state` status model; the theme icon's `data-icon`; the old class and style writes removed; the page-wide copy binding | developer | 2, 3, 5, 6 |
| `nginx/nginx.conf` | The `.pulse` part of the CSP comment removed | devops-sre | 5 |
| `tests/test_legacy_admin_tokens.py` | New. Pins every token `admin.css` uses | developer | 1 |
| `tests/test_contrast.py` | Two admin mutations re-pointed; then the public half rewritten, and two parser bugs fixed | developer | 1, 4 |
| `tests/js/states_harness.mjs`, `tests/test_public_states.py` | New. Spec section 5.2's state tables, driven through `MirrorStatus` in a vm | developer | 2, 5 |
| `tests/js/theme_harness.mjs`, `tests/test_theme.py` | The `data-icon` contract replaces the glyph checks | developer | 3 |
| `tests/js/contrast_harness.mjs` | The public probes rewritten; fails on page JS errors | developer | 4 |
| `tests/test_public_page_structure.py` | New. Every hook, anchor, copy string and initial state in `index.html` | developer | 4 |
| `tests/test_reduced_motion.py` | New. Reduced motion turns every animation and transition off; no `transition: all`; colour transitions settle inside the harness windows | developer | 4 |
| `tests/test_focus_ring.py` | New. The 2px accent focus ring, in `style.css` and then `error.css` | developer | 4, 7 |
| `tests/test_admin_js_escaping.py` | One stale comment | developer | 5 |
| `tests/js/csp_click_harness.mjs`, `tests/test_public_page_csp.py` | The page-wide copy buttons clicked under the production CSP | developer | 6 |
| `tests/js/copy_buttons_harness.mjs`, `tests/test_copy_buttons.py` | New. The copy binding in a vm, including a missing Clipboard API | developer | 6 |
| `tests/test_error_pages_content.py` | New. The error pages' copy, the mark and its size attributes | developer | 7 |
| `docs/design/2026-09-26-reflection-pr2-plan.md` | This plan | controller | before Task 1 |

---

## Chunk 1: Groundwork, with no styling change

Three tasks that change no styling: the admin console gets its own token values, `main.js` learns the `data-state` model while still writing the old classes, and the theme toggle's icon becomes an attribute. Task 2 does change the status wording the page shows (sentence case, "Syncing", and a truthful "Status unavailable" when the API is down).

### Task 1: The legacy admin block

Task 4, later in this PR, rewrites `tokens.css`'s primitives and its light/dark
semantic layers for the Reflection palette. The admin panel reads through that
same cascade -- `data-theme="dark" data-surface="admin"` is static on
`admin/index.html`, never toggled -- and must keep looking exactly as it does
today until PR 3 gives it its own redesign. This task adds a LEGACY ADMIN
section to the existing `[data-surface="admin"]` block that pins every token
`admin.css` actually uses at a literal value, so none of them can fall through
to a shared layer Task 4 is about to change. It touches no markup and no
component stylesheet: only `tokens.css` and its tests.

The block already declared three of the 28 tokens (`--header-height`,
`--radius-md`, `--radius-lg`) for an unrelated reason (admin's chrome is
denser than the public site's). This task replaces them, and adds the other
25, as two commented groups -- the admin surface's 9 non-colour tokens, then
LEGACY ADMIN's 19 colours as raw hex -- rather than one flat list, so the
block already carries the shape Task 4's own admin layer keeps afterwards
(spec section 7). `--accent-secondary`'s override stays too, appended after
the colours with its existing comment: Task 4 retires it, and until then it
is the one admin override this task leaves resolving through the shared
primitives rather than pinning as a literal.

**Files:**
- Create: `tests/test_legacy_admin_tokens.py`
- Modify: `tests/test_contrast.py` (`TOKEN_MUTATIONS`'s two admin-targeted
  entries, and their two dedicated tests)
- Modify: `frontend/public/css/tokens.css` (the `[data-surface="admin"]` block)

- [ ] **Step 1 (developer): create `tests/test_legacy_admin_tokens.py`.**

```python
"""Pins the admin panel's tokens across PR 2's palette switch.

docs/design/2026-09-25-reflection-redesign.md's palette change (section 4.1)
rewrites the same primitive and semantic layers of tokens.css the admin panel
has always read through the cascade -- LIGHT THEME, DARK THEME, and the small
ADMIN SURFACE block on top. PR 2 rewrites the first two; the admin panel must
not move at all until PR 3 gives it its own redesign.

The fix lives in tokens.css itself, not here: a LEGACY ADMIN section inside
the [data-surface="admin"] block declares every token admin.css actually
reads at today's value, as a literal, so nothing there can resolve through a
shared layer PR 2 repoints. This file pins that fix two ways --

  1. every token admin.css uses must be declared directly in the admin
     block, not merely reachable through it, so a shared-layer change can
     never quietly reach admin again; and
  2. those declarations must equal a fixed snapshot, so the block itself can
     only change on purpose --

plus a self-check that the snapshot's key set still matches what admin.css
actually uses, so the first two claims cannot both stay green while quietly
checking the wrong set. PR 3 deletes the whole section once the admin panel
gets its own redesign.
"""

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TOKENS_CSS = REPO_ROOT / "frontend" / "public" / "css" / "tokens.css"
ADMIN_CSS = REPO_ROOT / "frontend" / "public" / "admin" / "css" / "admin.css"

# The 28 tokens admin.css uses (19 colours, then 9 non-colour), each at the
# value it resolves to today -- re-verified by hand against tokens.css's
# INVARIANTS, LIGHT THEME, DARK THEME and ADMIN SURFACE blocks, since the
# admin panel is permanently data-theme="dark" data-surface="admin". Colours
# are the flat, uppercase hex a browser paints, not a var() reference: that is
# what makes the pin independent of whatever changes above it in the cascade.
LEGACY_ADMIN_TOKENS = {
    "--accent-primary": "#F48C06",
    "--bg-card": "#1A1A2E",
    "--bg-primary": "#0D0D1A",
    "--bg-secondary": "#1A1A2E",
    "--bg-tertiary": "#2A2A40",
    "--border-color": "#2A2A40",
    "--status-error": "#EF4444",
    "--status-error-bg": "#462B3B",
    "--status-error-text": "#F87171",
    "--status-healthy": "#22C55E",
    "--status-healthy-bg": "#1C3C38",
    "--status-info-bg": "#203B56",
    "--status-info-text": "#38BDF8",
    "--status-syncing": "#F59E0B",
    "--status-syncing-bg": "#463427",
    "--text-muted": "#9696AC",
    "--text-on-accent": "#0D0D1A",
    "--text-primary": "#E8E8F0",
    "--text-secondary": "#A0A0B8",
    "--font-sans": "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    "--font-mono": "'JetBrains Mono', 'Fira Code', monospace",
    "--header-height": "64px",
    "--radius-lg": "14px",
    "--radius-md": "10px",
    "--radius-sm": "6px",
    "--sidebar-width": "260px",
    "--transition-base": "300ms ease",
    "--transition-fast": "150ms ease",
}

# Same tiny reader test_contrast.py uses: no nested rules ever appear inside
# tokens.css's flat custom-property blocks, so a non-greedy match between the
# outermost braces is enough -- see that file's docstring for the fuller
# parser this deliberately does not reimplement.
_RULE_RE = re.compile(r"([^{}]+)\{([^}]*)\}")


def _strip_css_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _admin_block() -> str:
    css = _strip_css_comments(TOKENS_CSS.read_text(encoding="utf-8"))
    bodies = [
        body for sel, body in _RULE_RE.findall(css) if sel.strip() == '[data-surface="admin"]'
    ]
    assert (
        len(bodies) == 1
    ), f'expected exactly one [data-surface="admin"] rule, found {len(bodies)}'
    return bodies[0]


def _admin_block_declarations() -> dict:
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", _admin_block()))


def _vars_used_by_admin_css() -> set:
    return set(re.findall(r"var\((--[\w-]+)\)", ADMIN_CSS.read_text(encoding="utf-8")))


def test_every_admin_css_token_is_pinned_in_the_admin_block():
    """Every var(--x) admin.css consumes must be declared directly in
    tokens.css's [data-surface="admin"] block -- not merely resolvable
    through the shared cascade above it -- so admin never falls through to
    whatever the light/dark layers become."""
    declared = _admin_block_declarations()
    used = _vars_used_by_admin_css()
    missing = sorted(used - set(declared))
    assert not missing, (
        'admin.css uses tokens the [data-surface="admin"] block does not declare, so they '
        f"would fall through to the shared palette once it changes: {missing}"
    )


def test_admin_css_uses_exactly_the_tokens_this_file_pins():
    """Keeps LEGACY_ADMIN_TOKENS itself honest: if admin.css starts or stops
    using a token, this fails before the snapshot check below can silently
    keep passing against the wrong set."""
    used = _vars_used_by_admin_css()
    assert used == set(LEGACY_ADMIN_TOKENS), (
        f"admin.css's own var() usage no longer matches this file's pinned set -- "
        f"used but not pinned: {sorted(used - set(LEGACY_ADMIN_TOKENS))}, "
        f"pinned but unused: {sorted(set(LEGACY_ADMIN_TOKENS) - used)}"
    )


def test_admin_block_values_match_the_pinned_snapshot():
    """The admin block can only change deliberately: PR 3 deletes this whole
    section at once, so a value drifting one hex digit at a time here would
    otherwise go unnoticed until then."""
    declared = _admin_block_declarations()
    mismatched = {
        name: {"tokens.css": declared.get(name), "pinned": expected}
        for name, expected in LEGACY_ADMIN_TOKENS.items()
        if declared.get(name) != expected
    }
    assert not mismatched, f"admin block drifted from its pinned snapshot: {mismatched}"
```

- [ ] **Step 2 (developer): re-point the two admin-targeted mutations in `tests/test_contrast.py`.** Both currently mutate an INVARIANTS `var()` reference that the new admin block is about to shadow for ADMIN; once it does, mutating the invariant reaches nothing ADMIN reads, and each check would fail with "changed a live token and nothing failed" instead of catching a real regression. Re-point both at the literal LEGACY ADMIN line instead.

In `TOKEN_MUTATIONS`, replace:

```python
    (
        "text_on_accent_reverts_to_white",
        "--text-on-accent: var(--c-navy-900);",
        "--text-on-accent: var(--c-white);",
        None,  # asserted separately: this breaks an ADMIN_CHECKS id, checked below
    ),
    (
        "status_error_text_reverts_to_status_error",
        "--status-error-text: var(--c-red-400);",
        "--status-error-text: var(--c-red-500);",
        None,  # breaks an ADMIN_CHECKS id, checked below
    ),
```

with:

```python
    (
        # Targets the LEGACY ADMIN line, not the INVARIANTS var() reference:
        # since the admin block now pins its own --text-on-accent, mutating
        # the invariant no longer reaches ADMIN at all.
        "text_on_accent_reverts_to_white",
        "--text-on-accent: #0D0D1A;",
        "--text-on-accent: #FFFFFF;",
        None,  # asserted separately: this breaks an ADMIN_CHECKS id, checked below
    ),
    (
        # Same shape as the mutation above: the admin block pins its own
        # --status-error-text now, so this targets that line instead of the
        # INVARIANTS var() reference, which no longer reaches ADMIN.
        "status_error_text_reverts_to_status_error",
        "--status-error-text: #F87171;",
        "--status-error-text: #EF4444;",
        None,  # breaks an ADMIN_CHECKS id, checked below
    ),
```

`test_text_on_accent_mutation_breaks_an_admin_fill` and
`test_status_error_text_mutation_breaks_the_error_badge` hard-code the same
two strings a second time, independently of `TOKEN_MUTATIONS`. Replace:

```python
    mutated_text = TOKENS_TEXT.replace(
        "--text-on-accent: var(--c-navy-900);", "--text-on-accent: var(--c-white);"
    )
```

with:

```python
    mutated_text = TOKENS_TEXT.replace("--text-on-accent: #0D0D1A;", "--text-on-accent: #FFFFFF;")
```

and replace:

```python
    mutated_text = TOKENS_TEXT.replace(
        "--status-error-text: var(--c-red-400);", "--status-error-text: var(--c-red-500);"
    )
```

with:

```python
    mutated_text = TOKENS_TEXT.replace(
        "--status-error-text: #F87171;", "--status-error-text: #EF4444;"
    )
```

No other mutation needs to move: `text_muted_dark_reverts_to_the_old_failing_shade`'s
`must_fail`, `.detail-label [dark]`, is a `PUBLIC_PAIRS` id, unaffected by
anything the admin block shadows.

- [ ] **Step 3 (developer): run the tests, and watch them fail.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_legacy_admin_tokens.py tests/test_contrast.py; echo "rc=$?"`

Expected: `rc=1`, `6 failed, 139 passed, 4 warnings`:
- `test_every_admin_css_token_is_pinned_in_the_admin_block` and
  `test_admin_block_values_match_the_pinned_snapshot` (new file) fail because
  the admin block does not declare any of the 25 tokens yet -- each lists all
  25 missing/mismatched names.
- `test_tokens_css_mutation_is_caught[text_on_accent_reverts_to_white]` and
  `[status_error_text_reverts_to_status_error]` fail with "no longer matches
  tokens.css exactly once (found 0)": the literal LEGACY ADMIN lines do not
  exist yet.
- `test_text_on_accent_mutation_breaks_an_admin_fill` and
  `test_status_error_text_mutation_breaks_the_error_badge` fail for a more
  interesting reason: with the literal line absent, `.replace()` is a silent
  no-op, so each compares *today's real, unmutated* ratio against `< 4.5` and
  loses -- `7.89` and `4.548` respectively (the latter close enough to the
  4.5:1 bar to be worth noting: `--status-error-text` was never far above it).
  `test_admin_css_uses_exactly_the_tokens_this_file_pins` passes already: it
  only checks admin.css's own usage against the pinned set, not the block.

- [ ] **Step 4 (web-designer): update the header, and add the two-group LEGACY ADMIN section, in `tokens.css`.** The new block below leaves the header's layer list, its "second copy" paragraph and its whole "Deliberate divergence" section describing something that no longer exists (a four-token divergence), so those move first.

In the file header, replace:

```css
   5. ADMIN SURFACE        The five tokens where the admin panel genuinely
                           disagrees with the public site. See notes below.

   ---------------------------------------------------------------------------
   How a surface picks its values
   ---------------------------------------------------------------------------
   Theme and surface are independent axes, both expressed on <html>:

     <html>                                    public site, light
     <html data-theme="dark">                  public site, dark  (main.js)
     <html data-theme="dark" data-surface="admin">   admin panel

   The admin panel has no theme toggle; it is dark-only and always has been.
   It carries data-theme="dark" statically so it consumes the same dark theme
   the public site does, instead of maintaining a second copy of those values.

   Layers 3-5 all have specificity (0,1,0), so ordering in this file decides:
   dark overrides light, admin overrides dark. Keep them in this order.

   ---------------------------------------------------------------------------
   Deliberate divergence (layer 5)
   ---------------------------------------------------------------------------
   These are design decisions, not merge accidents. The admin panel is a denser,
   more utilitarian surface than the marketing-oriented public site:

     --header-height   72px -> 64px   admin chrome is tighter
     --radius-md       12px -> 10px   smaller corners suit dense controls
     --radius-lg       16px -> 14px   ditto
     --accent-secondary  red -> orange  admin's gradient stays inside the orange
                                        family; the public site's runs orange->red

   --accent-gradient is derived from --accent-primary and --accent-secondary, so
   overriding the latter is enough to retune the gradient for the admin surface.
*/
```

with:

```css
   5. ADMIN SURFACE        Frozen ahead of the admin console's own redesign
                           (spec section 6). See the note at that block.

   ---------------------------------------------------------------------------
   How a surface picks its values
   ---------------------------------------------------------------------------
   Theme and surface are independent axes, both expressed on <html>:

     <html>                                    public site, light
     <html data-theme="dark">                  public site, dark  (main.js)
     <html data-theme="dark" data-surface="admin">   admin panel

   The admin panel has no theme toggle yet (spec section 6.2 adds one); it is
   dark-only and carries data-theme="dark" statically so it consumes the same
   dark theme the public site does, instead of maintaining a second copy.

   Layers 3-5 all have specificity (0,1,0), so ordering in this file decides:
   dark overrides light, admin overrides dark. Keep them in this order.

   ---------------------------------------------------------------------------
   Layer 5, frozen ahead of the admin redesign
   ---------------------------------------------------------------------------
   The admin console must keep looking exactly as it does today until its own
   redesign (spec section 6), even though this file's primitives and light/dark
   semantics are about to change under it. [data-surface="admin"] pins the
   values admin.css reads directly, as literals, so none of them can resolve
   through the shared layers above once they do. That admin redesign deletes
   the LEGACY ADMIN group and folds admin's colours back into the shared
   light/dark layers, checked in both themes; see spec section 7.

   --accent-secondary is the one admin override the freeze leaves alone: it
   still resolves through PRIMITIVES rather than a raw hex value, and
   --accent-gradient is derived from --accent-primary and --accent-secondary,
   so overriding the latter here is enough to retune the gradient for the
   admin surface. PR 2 retires both --accent-secondary and --accent-gradient.
*/
```

Then the block's own banner and body. Replace:

```css
/* ===========================================================================
   5. ADMIN SURFACE
   Only the tokens the admin panel deliberately disagrees on. Everything else
   it inherits from layers 1-4. Must stay after layer 4 to win the cascade.
   =========================================================================== */

[data-surface="admin"] {
    --header-height: 64px;

    --radius-md: 10px;
    --radius-lg: 14px;

    /* Gradient stays within the orange family instead of running orange->red. */
    --accent-secondary: var(--c-orange-600);
}
```

with:

```css
/* ===========================================================================
   5. ADMIN SURFACE
   Frozen ahead of the admin console's own redesign (spec section 6), which
   deletes the LEGACY ADMIN group below and folds admin's colours back into
   the shared light/dark layers above (spec section 7).
   =========================================================================== */

[data-surface="admin"] {
    /* ===== ADMIN SURFACE: NON-COLOUR TOKENS =====
       admin.css's own values for the non-colour tokens, declared here so a
       change to the INVARIANTS layer above never reaches the admin console.
       The admin console's own redesign revisits these; until then they keep
       today's numbers (spec section 7: "the admin layer then holds only
       non-colour tokens"). */
    --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    --font-mono: 'JetBrains Mono', 'Fira Code', monospace;
    --header-height: 64px;
    --radius-sm: 6px;
    --radius-md: 10px;
    --radius-lg: 14px;
    --sidebar-width: 260px;
    --transition-fast: 150ms ease;
    --transition-base: 300ms ease;

    /* ===== LEGACY ADMIN =====
       Pins every colour token admin.css consumes at its value today, as a
       literal rather than a var() reference, so none of them can resolve
       through a shared layer when this file's primitives and light/dark
       semantics change under it. Raw hex, so these do not follow the shared
       primitives, which the Reflection palette replaces. The admin console's
       own redesign deletes this whole group.
       Verified against admin.css by tests/test_legacy_admin_tokens.py. */
    --accent-primary: #F48C06;
    --bg-card: #1A1A2E;
    --bg-primary: #0D0D1A;
    --bg-secondary: #1A1A2E;
    --bg-tertiary: #2A2A40;
    --border-color: #2A2A40;
    --status-error: #EF4444;
    --status-error-bg: #462B3B;
    --status-error-text: #F87171;
    --status-healthy: #22C55E;
    --status-healthy-bg: #1C3C38;
    --status-info-bg: #203B56;
    --status-info-text: #38BDF8;
    --status-syncing: #F59E0B;
    --status-syncing-bg: #463427;
    --text-muted: #9696AC;
    --text-on-accent: #0D0D1A;
    --text-primary: #E8E8F0;
    --text-secondary: #A0A0B8;

    /* Gradient stays within the orange family instead of running orange->red. */
    --accent-secondary: var(--c-orange-600);
}
```

Every value above was re-derived from `tokens.css` itself, not copied from a
spec: the 9 non-colour tokens carry their pre-existing values forward (three
were already declared for admin's denser chrome; the other six match the
shared INVARIANTS layer verbatim), and the 19 colours were resolved by
walking `--name` through DARK THEME then INVARIANTS (admin is permanently
`data-theme="dark" data-surface="admin"`), upper-casing hex on the way in (the
source primitive for `--status-healthy`, `--c-green-500`, is written
lower-case; the pinned value is `#22C55E`, the same colour). The two groups
and their comments match Task 4's admin block word for word (spec section 7),
and every comment in the block reads true both before Task 4's palette switch
and after it; only the trailing `--accent-secondary` override, which Task 4
retires, is unique to this task.

- [ ] **Step 5 (developer): run green, lint, and the whole suite.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_legacy_admin_tokens.py tests/test_contrast.py; echo "rc=$?"`
Expected: `145 passed, 4 warnings`, `rc=0` (the 139 that already passed, plus the 6 fixed above).

Lint both Python files. Both are clean on the first run:
`docker compose run --rm -T test ruff check tests/test_legacy_admin_tokens.py tests/test_contrast.py; echo "rc=$?"` -> no output, `rc=0`.
`docker compose run --rm -T test ruff format --check tests/test_legacy_admin_tokens.py tests/test_contrast.py; echo "rc=$?"` -> `2 files already formatted`, `rc=0`.

Run: `docker compose run --rm -T test; echo "rc=$?"`
Expected: `1400 passed, 7 warnings`, `rc=0`: the base suite's 1397, plus the 3 tests `test_legacy_admin_tokens.py` adds.

- [ ] **Step 6 (developer): confirm nothing changed for admin.** Two checks, neither of them new standing tests -- both re-verify that this task itself did what it claims, on top of the pinned-snapshot regression test Step 1 already leaves behind.

First, that ADMIN resolves every token `admin.css` uses to the same value before this task's edit and after it, run as a one-off script (not committed):

```bash
docker compose run --rm -T test python - <<'PY'
import pathlib, re, subprocess

ROOT = pathlib.Path(".")
TOKENS_CSS = ROOT / "frontend/public/css/tokens.css"
ADMIN_CSS = ROOT / "frontend/public/admin/css/admin.css"
RULE_RE = re.compile(r"([^{}]+)\{([^}]*)\}")

def strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)

def parse_props(body):
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body))

def build_admin_theme(text):
    css = strip_comments(text)
    roots, dark_body, admin_body = [], None, None
    for sel, body in RULE_RE.findall(css):
        sel = sel.strip()
        if sel == ":root":
            roots.append(body)
        elif sel == '[data-theme="dark"]':
            dark_body = body
        elif sel == '[data-surface="admin"]':
            admin_body = body
    light = {}
    for body in roots:
        light.update(parse_props(body))
    dark = dict(light); dark.update(parse_props(dark_body))
    admin = dict(dark); admin.update(parse_props(admin_body))
    return admin

def resolve(theme, name, seen=frozenset()):
    value = theme[name].strip()
    m = re.fullmatch(r"var\((--[\w-]+)\)", value)
    return resolve(theme, m.group(1), seen | {name}) if m else value

def normalized(v):
    return v.upper() if re.fullmatch(r"#[0-9A-Fa-f]{6}", v) else v

before = build_admin_theme(subprocess.run(
    ["git", "show", "HEAD:frontend/public/css/tokens.css"],
    capture_output=True, text=True, check=True).stdout)
after = build_admin_theme(TOKENS_CSS.read_text())
used = sorted(set(re.findall(r"var\((--[\w-]+)\)", ADMIN_CSS.read_text())))

bad = [n for n in used if normalized(resolve(before, n)) != normalized(resolve(after, n))]
print(f"tokens admin.css uses, checked: {len(used)}")
print("MISMATCHES:", bad) if bad else print("identical before and after")
raise SystemExit(1 if bad else 0)
PY
echo "rc=$?"
```

Run this after Step 4's edit and before Step 7's commit, while `HEAD` still
points at the commit before this task's own -- a plain checkout, not a git
worktree: `git show HEAD:...` resolves through `.git` directly, and a linked
worktree's `.git` file points at an absolute path on the host that the
container cannot see, which would fail this check for a reason that has
nothing to do with the tokens themselves. Expected: `tokens admin.css uses,
checked: 28`, `identical before and after`, `rc=0`. (Before `normalized()`
was added, the same script printed `MISMATCHES: ['--status-healthy']` --
`resolve()` alone found the two sides differing only in case, `#22c55e`
versus `#22C55E`, the same colour; `normalized()` above accounts for that and
is why it belongs in the check.)

Second, that the dynamic (real-Chrome) admin probes are unchanged -- they are
not expected to move, since neither `admin.css` nor `admin.js` did:

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_contrast.py -k "admin_panel_contrast_in_a_real_browser or dynamic_probe_list_matches_the_harness or harness_detects_a_reintroduced_low_contrast_fill"; echo "rc=$?"`
Expected: `15 passed, 127 deselected, 4 warnings`, `rc=0`: the 13 `DYNAMIC_ADMIN_CHECKS` probes, the
probe-list pin against `contrast_harness.mjs`, and the negative control that
plants a real low-contrast fill and confirms the harness catches it.

- [ ] **Step 7 (developer): commit.**

```bash
git add tests/test_legacy_admin_tokens.py tests/test_contrast.py frontend/public/css/tokens.css
git commit -m "Pin the admin console's tokens ahead of the palette switch"
```

### Task 2: The status state model in `main.js`

Spec section 5.2 is the contract. **Behaviour only:** the old markup and
stylesheet stay until Task 4 -- this task adds a `data-state` attribute and a
worded `.status-text` alongside the existing `.status-dot` className,
`.status-indicator` className and `.pulse` inline-style writes, not instead of
them yet. The old writes are kept, each marked with a "removed in Task 5"
comment, because today's stylesheet and `tests/js/contrast_harness.mjs` still
key off them.

Three behavioural gaps close at the same time, because the old code could not
represent them with classNames alone:
- an outage used to leave the hardcoded "All Systems Operational" HTML
  showing, because `load()` returned early -- doing nothing at all -- when the
  API failed. The overall card now explicitly says "Status unavailable".
- `[].every(s => s === 'active')` on an empty mirror list reads as `true`, so
  a response with no mirrors in it showed the same false all-clear. The
  overall state is now computed by counting three fixed mirrors, never by
  `.every()` over whatever the response happened to contain.
- a mirror missing entirely from the response (the backend omits disabled
  mirrors outright) used to leave that mirror's dot exactly as shipped,
  because the old code only ever looped over `Object.entries(mirrors)`. The
  new model loops over the fixed `MIRRORS` list instead, so an absent mirror
  reads as `disabled`/"Offline" like an explicit one.

`setHostname()` is untouched in one respect that is easy to get wrong: it
stays a one-time page setup called once from `DOMContentLoaded`, exactly as
today, not from `load()`. Filling in the hostname has nothing to do with the
status poll -- moving it into `load()` would re-run it every 60 seconds for
no reason, tie a page-setup concern to the poll's success/failure path, and
mean a future stricter early return in `load()` could silently start skipping
it. Its selector gains `, [data-hostname]`; nothing about when it runs
changes.

**Files:**
- Create: `tests/js/states_harness.mjs`, `tests/test_public_states.py`
- Modify: `frontend/public/js/main.js`

- [ ] **Step 1 (developer): create `tests/js/states_harness.mjs`.**

```js
/**
 * Mirror status harness for the MirrorStatus in frontend/public/js/main.js.
 *
 * docs/design/2026-09-25-reflection-redesign.md, section 5.2. Runs the real
 * main.js in a Node vm context with a small fake DOM -- in theme_harness.mjs's
 * style -- and a stubbed fetch, then drives MirrorStatus.load() through every
 * row of section 5.2's two tables (the per-mirror state model, and the
 * overall card computed from it), plus these edge cases: an absent mirror, an
 * empty mirrors object, a first-load API failure, a failure after a success,
 * and sentences naming two or three mirrors. Prints one JSON object,
 * {checkName: [ok, detail]}, for tests/test_public_states.py to assert on --
 * the same shape theme_harness.mjs uses. Unlike that harness,
 * MirrorStatus.load() is async (it awaits API.get()), so check() here awaits
 * its scenario before recording the result, the way footer_version_harness.mjs
 * awaits FooterVersion.load().
 *
 * setHostname() is a one-time page setup with nothing to do with the status
 * poll -- it is called once from DOMContentLoaded, not from load() -- so the
 * epilogue exposes it alongside MirrorStatus and the hostname check below
 * calls it directly on its own fake page, rather than going through load().
 *
 * The fake DOM matches the *future* markup section 5.1 describes (a stream
 * row and pill per mirror, #statFiles, [data-hostname] elements), since that
 * is the contract main.js implements ahead of the stylesheet and markup
 * switch later in this PR. One check (see "does not throw against today's
 * markup" below) instead builds today's sparser real markup, to prove every
 * lookup is null-safe against it.
 *
 * Usage:  node states_harness.mjs <path-to-main.js>
 */
import fs from 'node:fs';
import vm from 'node:vm';

const [mainPath] = process.argv.slice(2);
const MAIN_SOURCE = fs.readFileSync(mainPath, 'utf8');

/** One fake element: setAttribute/getAttribute (data-state), textContent,
 * className and a plain style object (legacy .pulse writes), plus a flat,
 * non-recursive querySelector into a caller-supplied child map -- the same
 * trade-off theme_harness.mjs's icon/toggle stubs make. `state`, given,
 * seeds data-state the way the shipped HTML does (section 5.2: "As shipped
 * in the HTML, before any data" is data-state="unknown"). */
function makeEl({ text = '', state = null, children = {} } = {}) {
    const attrs = new Map();
    if (state !== null) attrs.set('data-state', state);
    let textContent = text;
    let className = '';
    return {
        get textContent() { return textContent; },
        set textContent(v) { textContent = v; },
        get className() { return className; },
        set className(v) { className = v; },
        style: {},
        // .stat-card's ancestor and its "loading" class: the legacy
        // .stat-card loading removal does not need a real DOM tree to land
        // on, just something with a working classList so the call does not
        // throw.
        classList: { remove: () => {} },
        closest: () => ({ classList: { remove: () => {} } }),
        setAttribute: (name, value) => attrs.set(name, String(value)),
        getAttribute: (name) => (attrs.has(name) ? attrs.get(name) : null),
        querySelector: (sel) => children[sel] ?? null
    };
}

/** A fresh page. `minimal` builds today's real markup -- no stream rows, no
 * [data-hostname], no #statFiles -- everything else builds the future markup
 * section 5.1 describes, which is what most checks below drive. */
function makePage({ minimal = false, hostname = 'mirror.test' } = {}) {
    const mirrors = {};
    for (const id of ['freebsd', 'netbsd', 'openbsd']) {
        const statusText = makeEl({ text: 'Checking…' });
        const dot = makeEl({});
        const statusEl = makeEl({ state: 'unknown', children: { '.status-dot': dot, '.status-text': statusText } });

        const pillStatusText = makeEl({ text: 'Checking…' });
        const pill = makeEl({ state: 'unknown', children: { '.status-text': pillStatusText } });
        const stream = makeEl({ state: 'unknown', children: { '.pill': pill } });

        mirrors[id] = {
            statusEl, dot, statusText, stream, pill, pillStatusText,
            size: makeEl({ text: '--' }),
            sync: makeEl({ text: '--' }),
            dataHostname: makeEl({ text: '' })
        };
    }

    const overallTitle = makeEl({ text: 'Checking mirror status…' });
    const overallDesc = makeEl({ text: '' });
    const indicator = makeEl({});
    const pulse = makeEl({});
    const overall = makeEl({
        state: 'unknown',
        children: { h3: overallTitle, p: overallDesc, '.status-indicator': indicator, '.pulse': pulse }
    });
    overall.h3 = overallTitle;
    overall.p = overallDesc;
    overall.indicator = indicator;
    overall.pulse = pulse;

    const statSize = makeEl({ text: '—' });
    const statFiles = makeEl({ text: '—' });
    const statLastSync = makeEl({ text: '—' });
    const hostnameEl = makeEl({ text: '' });
    const rsynchostEl = makeEl({ text: '' });

    const byId = { overallStatus: overall, statSize, statLastSync, hostname: hostnameEl, rsynchost: rsynchostEl };
    if (!minimal) byId.statFiles = statFiles;
    for (const [id, els] of Object.entries(mirrors)) {
        byId[`${id}-status`] = els.statusEl;
        byId[`${id}-size`] = els.size;
        byId[`${id}-sync`] = els.sync;
        if (!minimal) byId[`${id}-stream`] = els.stream;
    }

    const dataHostnameEls = minimal ? [] : Object.values(mirrors).map((m) => m.dataHostname);

    let fetchImpl = async () => { throw new Error('no fetch stubbed for this scenario'); };

    const sandbox = {
        console,
        document: {
            addEventListener: () => {},
            getElementById: (id) => (Object.prototype.hasOwnProperty.call(byId, id) ? byId[id] : null),
            querySelector: () => null,
            // Only the one compound selector setHostname() actually uses,
            // split generically so word order or spacing there cannot make
            // this pass by accident.
            querySelectorAll: (sel) => {
                const found = [];
                for (const part of sel.split(',').map((s) => s.trim())) {
                    if (part === '[data-hostname]') found.push(...dataHostnameEls);
                    else if (part.startsWith('#') && byId[part.slice(1)]) found.push(byId[part.slice(1)]);
                }
                return found;
            },
            documentElement: { getAttribute: () => null, setAttribute: () => {} }
        },
        navigator: {},
        localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
        setTimeout: () => 0,
        setInterval: () => 0,
        clearTimeout: () => {},
        clearInterval: () => {},
        fetch: (...args) => fetchImpl(...args),
        location: { hostname }
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);

    // Run once per page: MirrorStatus itself holds no state between calls,
    // everything "remembered" across load()s lives in the DOM stubs above.
    // setHostname is exposed alongside it because it is not part of load()'s
    // call graph at all -- see the file header.
    const { MirrorStatus, setHostname } = vm.runInContext(
        `${MAIN_SOURCE}\n;({ MirrorStatus, setHostname })`,
        sandbox,
        { filename: mainPath }
    );

    return {
        load: () => MirrorStatus.load(),
        setHostname: () => setHostname(),
        setFetch: (impl) => { fetchImpl = impl; },
        mirrors,
        overall,
        statSize,
        statFiles,
        statLastSync,
        hostnameEl,
        rsynchostEl,
        dataHostnameEls
    };
}

const ok = (body) => ({ ok: true, status: 200, json: async () => body });
const networkFailure = async () => { throw new Error('network disabled in harness'); };

const results = {};

async function check(name, fn) {
    try {
        const outcome = await fn();
        results[name] = outcome === true ? [true, ''] : [false, String(outcome)];
    } catch (err) {
        results[name] = [false, `threw: ${(err && err.stack) || err}`];
    }
}

const expect = (actual, expected, what) =>
    actual === expected ? true : `${what}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`;

const all = (...outcomes) => outcomes.find((outcome) => outcome !== true) ?? true;

// ---------------------------------------------------------------------------
// Section 5.2, table 1: API status -> data-state and text, on the card pill,
// the stream row and the row's own .pill child.
// ---------------------------------------------------------------------------
await check(
    'an active mirror maps to online/Online on its card pill, stream row and row pill, and writes size and sync',
    async () => {
        const page = makePage();
        const now = new Date().toISOString();
        page.setFetch(async () => ok({
            mirrors: {
                FreeBSD: { status: 'active', size: '799.9 GB', last_updated: now },
                NetBSD: { status: 'active' },
                OpenBSD: { status: 'active' }
            },
            totals: {}
        }));
        await page.load();
        const m = page.mirrors.freebsd;
        return all(
            expect(m.statusEl.getAttribute('data-state'), 'online', 'card pill data-state'),
            expect(m.statusText.textContent, 'Online', 'card pill text'),
            expect(m.stream.getAttribute('data-state'), 'online', 'stream row data-state'),
            expect(m.pill.getAttribute('data-state'), 'online', 'row pill data-state'),
            expect(m.pillStatusText.textContent, 'Online', 'row pill text'),
            expect(m.size.textContent, '799.9 GB', 'size'),
            expect(m.sync.textContent, 'Just now', 'sync')
        );
    }
);

await check('a syncing mirror maps to syncing/Syncing on its card pill, stream row and row pill', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'active' }, NetBSD: { status: 'syncing' }, OpenBSD: { status: 'active' } },
        totals: {}
    }));
    await page.load();
    const m = page.mirrors.netbsd;
    return all(
        expect(m.statusEl.getAttribute('data-state'), 'syncing', 'card pill data-state'),
        expect(m.statusText.textContent, 'Syncing', 'card pill text'),
        expect(m.stream.getAttribute('data-state'), 'syncing', 'stream row data-state'),
        expect(m.pill.getAttribute('data-state'), 'syncing', 'row pill data-state'),
        expect(m.pillStatusText.textContent, 'Syncing', 'row pill text')
    );
});

await check('an error mirror maps to error/Error on its card pill, stream row and row pill', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'active' }, NetBSD: { status: 'active' }, OpenBSD: { status: 'error' } },
        totals: {}
    }));
    await page.load();
    const m = page.mirrors.openbsd;
    return all(
        expect(m.statusEl.getAttribute('data-state'), 'error', 'card pill data-state'),
        expect(m.statusText.textContent, 'Error', 'card pill text'),
        expect(m.stream.getAttribute('data-state'), 'error', 'stream row data-state'),
        expect(m.pill.getAttribute('data-state'), 'error', 'row pill data-state'),
        expect(m.pillStatusText.textContent, 'Error', 'row pill text')
    );
});

await check('an explicitly disabled mirror maps to disabled/Offline', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'disabled' }, NetBSD: { status: 'active' }, OpenBSD: { status: 'active' } },
        totals: {}
    }));
    await page.load();
    const m = page.mirrors.freebsd;
    return all(
        expect(m.statusEl.getAttribute('data-state'), 'disabled', 'data-state'),
        expect(m.statusText.textContent, 'Offline', 'text')
    );
});

await check('a mirror absent from a successful response maps to disabled/Offline', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'active' }, NetBSD: { status: 'active' } }, // OpenBSD omitted entirely
        totals: {}
    }));
    await page.load();
    const m = page.mirrors.openbsd;
    return all(
        expect(m.statusEl.getAttribute('data-state'), 'disabled', 'data-state'),
        expect(m.statusText.textContent, 'Offline', 'text')
    );
});

await check('an unrecognised API status maps to unknown/Unknown', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'bogus' }, NetBSD: { status: 'active' }, OpenBSD: { status: 'active' } },
        totals: {}
    }));
    await page.load();
    const m = page.mirrors.freebsd;
    return all(
        expect(m.statusEl.getAttribute('data-state'), 'unknown', 'data-state'),
        expect(m.statusText.textContent, 'Unknown', 'text')
    );
});

await check("a lower-cased API key still resolves to its mirror's elements", async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { freebsd: { status: 'active' }, netbsd: { status: 'syncing' }, openbsd: { status: 'error' } },
        totals: {}
    }));
    await page.load();
    return all(
        expect(page.mirrors.freebsd.statusEl.getAttribute('data-state'), 'online', 'freebsd'),
        expect(page.mirrors.netbsd.statusEl.getAttribute('data-state'), 'syncing', 'netbsd'),
        expect(page.mirrors.openbsd.statusEl.getAttribute('data-state'), 'error', 'openbsd')
    );
});

// ---------------------------------------------------------------------------
// Section 5.2's last table-1 row: the API request itself fails.
// ---------------------------------------------------------------------------
await check(
    'a first-load API failure leaves the shipped pills unchanged and marks the overall card unavailable',
    async () => {
        const page = makePage();
        page.setFetch(networkFailure);
        await page.load();
        const m = page.mirrors.freebsd;
        return all(
            expect(m.statusEl.getAttribute('data-state'), 'unknown', 'card pill data-state'),
            expect(m.statusText.textContent, 'Checking…', 'card pill text'),
            expect(page.overall.getAttribute('data-state'), 'unknown', 'overall data-state'),
            expect(page.overall.h3.textContent, 'Status unavailable', 'overall title'),
            expect(
                page.overall.p.textContent,
                "The status service didn't answer. The mirrors themselves may still be reachable.",
                'overall sentence'
            )
        );
    }
);

await check(
    "an API failure after a success keeps each pill's last state and marks the overall card unavailable",
    async () => {
        const page = makePage();
        page.setFetch(async () => ok({
            mirrors: { FreeBSD: { status: 'active' }, NetBSD: { status: 'active' }, OpenBSD: { status: 'active' } },
            totals: {}
        }));
        await page.load();
        page.setFetch(networkFailure);
        await page.load();
        const m = page.mirrors.freebsd;
        return all(
            expect(m.statusEl.getAttribute('data-state'), 'online', 'card pill data-state kept'),
            expect(m.statusText.textContent, 'Online', 'card pill text kept'),
            expect(page.overall.getAttribute('data-state'), 'unknown', 'overall data-state'),
            expect(page.overall.h3.textContent, 'Status unavailable', 'overall title')
        );
    }
);

// ---------------------------------------------------------------------------
// Section 5.2, table 2: the overall card after a successful load.
// ---------------------------------------------------------------------------
await check('all three mirrors online gives All systems operational', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'active' }, NetBSD: { status: 'active' }, OpenBSD: { status: 'active' } },
        totals: {}
    }));
    await page.load();
    return all(
        expect(page.overall.getAttribute('data-state'), 'online', 'data-state'),
        expect(page.overall.h3.textContent, 'All systems operational', 'title'),
        expect(page.overall.p.textContent, 'All mirrors are synchronized and available.', 'sentence')
    );
});

await check('at least one but not all mirrors online gives Systems operational', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'active' }, NetBSD: { status: 'disabled' } }, // OpenBSD absent
        totals: {}
    }));
    await page.load();
    return all(
        expect(page.overall.getAttribute('data-state'), 'online', 'data-state'),
        expect(page.overall.h3.textContent, 'Systems operational', 'title'),
        expect(page.overall.p.textContent, 'Some mirrors are offline; the rest are available.', 'sentence')
    );
});

await check('no mirrors online gives No mirrors online', async () => {
    const page = makePage();
    page.setFetch(async () => ok({ mirrors: {}, totals: {} }));
    await page.load();
    return all(
        expect(page.overall.getAttribute('data-state'), 'disabled', 'data-state'),
        expect(page.overall.h3.textContent, 'No mirrors online', 'title'),
        expect(page.overall.p.textContent, 'No mirror is reporting as online right now.', 'sentence')
    );
});

await check('a single syncing mirror gives Sync in progress', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'active' }, NetBSD: { status: 'syncing' }, OpenBSD: { status: 'active' } },
        totals: {}
    }));
    await page.load();
    return all(
        expect(page.overall.getAttribute('data-state'), 'syncing', 'data-state'),
        expect(page.overall.h3.textContent, 'Sync in progress', 'title'),
        expect(page.overall.p.textContent, 'NetBSD is syncing now.', 'sentence')
    );
});

await check('a single error mirror gives Degraded service', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'active' }, NetBSD: { status: 'active' }, OpenBSD: { status: 'error' } },
        totals: {}
    }));
    await page.load();
    return all(
        expect(page.overall.getAttribute('data-state'), 'error', 'data-state'),
        expect(page.overall.h3.textContent, 'Degraded service', 'title'),
        expect(page.overall.p.textContent, 'OpenBSD is experiencing issues.', 'sentence')
    );
});

await check('an error mirror overrides a syncing one for the overall state', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'error' }, NetBSD: { status: 'syncing' }, OpenBSD: { status: 'active' } },
        totals: {}
    }));
    await page.load();
    return all(
        expect(page.overall.getAttribute('data-state'), 'error', 'data-state'),
        expect(page.overall.h3.textContent, 'Degraded service', 'title'),
        expect(page.overall.p.textContent, 'FreeBSD is experiencing issues.', 'sentence')
    );
});

await check('two mirrors in error are joined as A and B in the sentence', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { NetBSD: { status: 'error' }, FreeBSD: { status: 'error' }, OpenBSD: { status: 'active' } },
        totals: {}
    }));
    await page.load();
    return expect(page.overall.p.textContent, 'FreeBSD and NetBSD are experiencing issues.', 'sentence');
});

await check('three mirrors syncing are joined as A, B and C in the sentence', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { OpenBSD: { status: 'syncing' }, FreeBSD: { status: 'syncing' }, NetBSD: { status: 'syncing' } },
        totals: {}
    }));
    await page.load();
    return expect(page.overall.p.textContent, 'FreeBSD, NetBSD and OpenBSD are syncing now.', 'sentence');
});

// ---------------------------------------------------------------------------
// Stats and hostname fill.
// ---------------------------------------------------------------------------
await check('statSize and statFiles are written from totals when present', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'active' }, NetBSD: { status: 'active' }, OpenBSD: { status: 'active' } },
        totals: { size: '2.1 TB', files: '604,618' }
    }));
    await page.load();
    return all(
        expect(page.statSize.textContent, '2.1 TB', 'statSize'),
        expect(page.statFiles.textContent, '604,618', 'statFiles')
    );
});

await check('statSize and statFiles are left untouched when totals is empty', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'active' }, NetBSD: { status: 'active' }, OpenBSD: { status: 'active' } },
        totals: {}
    }));
    await page.load();
    return all(
        expect(page.statSize.textContent, '—', 'statSize'),
        expect(page.statFiles.textContent, '—', 'statFiles')
    );
});

await check('statLastSync reflects the most recently updated mirror', async () => {
    const page = makePage();
    const now = new Date().toISOString();
    const earlier = new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString();
    page.setFetch(async () => ok({
        mirrors: {
            FreeBSD: { status: 'active', last_updated: earlier },
            NetBSD: { status: 'active', last_updated: now },
            OpenBSD: { status: 'active' }
        },
        totals: {}
    }));
    await page.load();
    return expect(page.statLastSync.textContent, 'Just now', 'statLastSync');
});

await check("hostname fill sets #hostname, #rsynchost and every stream row's data-hostname element", async () => {
    // setHostname() is page setup, not part of the status poll: called
    // directly here, never through load() (see the file header).
    const page = makePage({ hostname: 'mirror.test' });
    page.setHostname();
    return all(
        expect(page.hostnameEl.textContent, 'mirror.test', '#hostname'),
        expect(page.rsynchostEl.textContent, 'mirror.test', '#rsynchost'),
        expect(page.dataHostnameEls.length, 3, 'number of [data-hostname] elements'),
        expect(page.dataHostnameEls.every((el) => el.textContent === 'mirror.test'), true, 'every [data-hostname] text')
    );
});

// ---------------------------------------------------------------------------
// Null-safety against today's real markup, and the legacy writes kept for now.
// ---------------------------------------------------------------------------
await check("load does not throw against today's markup, which has no stream rows", async () => {
    // setHostname() is no longer part of load()'s call graph (see the file
    // header), so this is purely about load() itself against sparse markup.
    const page = makePage({ minimal: true });
    const now = new Date().toISOString();
    page.setFetch(async () => ok({
        mirrors: {
            FreeBSD: { status: 'active', size: '1.0 TB', last_updated: now },
            NetBSD: { status: 'active' },
            OpenBSD: { status: 'active' }
        },
        totals: { size: '3.0 TB' }
    }));
    await page.load();
    const m = page.mirrors.freebsd;
    return all(
        expect(m.statusEl.getAttribute('data-state'), 'online', 'card pill data-state'),
        expect(page.statSize.textContent, '3.0 TB', 'statSize')
    );
});

await check('an active mirror still gets the legacy status-dot healthy class', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'active' }, NetBSD: { status: 'active' }, OpenBSD: { status: 'active' } },
        totals: {}
    }));
    await page.load();
    return expect(page.mirrors.freebsd.dot.className, 'status-dot healthy', 'dot className');
});

await check('a syncing mirror still drives the legacy status-indicator and pulse colour', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'active' }, NetBSD: { status: 'syncing' }, OpenBSD: { status: 'active' } },
        totals: {}
    }));
    await page.load();
    return all(
        expect(page.mirrors.netbsd.dot.className, 'status-dot syncing', 'dot className'),
        expect(page.overall.indicator.className, 'status-indicator syncing', 'indicator className'),
        expect(page.overall.pulse.style.background, 'var(--accent-primary)', 'pulse background')
    );
});

process.stdout.write(JSON.stringify(results));
```

- [ ] **Step 2 (developer): create `tests/test_public_states.py`.**

```python
"""The public site's mirror status model: a data-state attribute and a word, not classes.

docs/design/2026-09-25-reflection-redesign.md, section 5.2. main.js used to
rewrite `.status-dot`'s className, `.status-indicator`'s className and
`.pulse`'s inline background every 60 seconds, and returned early -- doing
nothing at all -- when the status API failed, so an outage left whatever "All
Systems Operational" the HTML had shipped with looking current. `every()` over
an empty mirror list also read as true, so a response with no mirrors in it
showed that same false all-clear.

MirrorStatus now writes only a `data-state` attribute and a `.status-text`
word, on a mirror's card pill (#<id>-status), its stream row (#<id>-stream,
markup this PR ships later -- the lookup is null against today's page) and
the row's own .pill child alike, plus the overall card (#overallStatus),
whose title and sentence are chosen from every mirror's computed state at
once -- including the API-failure and no-mirror-online cases the old
className-only version could not represent. The three old writes stay for
now, because today's stylesheet and tests/js/contrast_harness.mjs still key
off them.

tests/js/states_harness.mjs runs the real main.js in a Node vm with a small
fake DOM (in tests/js/theme_harness.mjs's style) and stubbed fetch responses,
one per row of section 5.2's two tables plus these edge cases: an absent
mirror, an empty mirrors object, an API failure on the first load and after a
success, sentences naming two or three mirrors, the new #statFiles stat, the
[data-hostname] fill, and a run against today's sparser real markup to prove
every lookup is null-safe.
"""

import json
import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MAIN_JS = REPO_ROOT / "frontend" / "public" / "js" / "main.js"
HARNESS = REPO_ROOT / "tests" / "js" / "states_harness.mjs"
NODE = shutil.which("node")

requires_node = pytest.mark.skipif(
    NODE is None, reason="node is not installed; the mirror status behaviour checks cannot run"
)

CHECKS = [
    # Section 5.2, table 1: API status -> data-state and text.
    "an active mirror maps to online/Online on its card pill, stream row and row pill, and writes size and sync",
    "a syncing mirror maps to syncing/Syncing on its card pill, stream row and row pill",
    "an error mirror maps to error/Error on its card pill, stream row and row pill",
    "an explicitly disabled mirror maps to disabled/Offline",
    "a mirror absent from a successful response maps to disabled/Offline",
    "an unrecognised API status maps to unknown/Unknown",
    "a lower-cased API key still resolves to its mirror's elements",
    # Table 1's last row: the API request itself fails.
    "a first-load API failure leaves the shipped pills unchanged and marks the overall card unavailable",
    "an API failure after a success keeps each pill's last state and marks the overall card unavailable",
    # Section 5.2, table 2: the overall card after a successful load.
    "all three mirrors online gives All systems operational",
    "at least one but not all mirrors online gives Systems operational",
    "no mirrors online gives No mirrors online",
    "a single syncing mirror gives Sync in progress",
    "a single error mirror gives Degraded service",
    "an error mirror overrides a syncing one for the overall state",
    "two mirrors in error are joined as A and B in the sentence",
    "three mirrors syncing are joined as A, B and C in the sentence",
    # Stats and hostname.
    "statSize and statFiles are written from totals when present",
    "statSize and statFiles are left untouched when totals is empty",
    "statLastSync reflects the most recently updated mirror",
    "hostname fill sets #hostname, #rsynchost and every stream row's data-hostname element",
    # Null-safety against today's markup, and the legacy writes kept for now.
    "load does not throw against today's markup, which has no stream rows",
    "an active mirror still gets the legacy status-dot healthy class",
    "a syncing mirror still drives the legacy status-indicator and pulse colour",
]


@pytest.fixture(scope="module")
def harness_results():
    proc = subprocess.run(
        [NODE, str(HARNESS), str(MAIN_JS)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@requires_node
@pytest.mark.parametrize("name", CHECKS)
def test_mirror_status_behaviour(harness_results, name):
    assert name in harness_results, f"harness did not run {name!r}"
    ok, detail = harness_results[name]
    assert ok, detail


@requires_node
def test_the_harness_runs_exactly_these_checks(harness_results):
    """The parametrised list must not drift behind the harness."""
    assert set(harness_results) == set(CHECKS)
```

- [ ] **Step 3 (developer): run the tests, and watch them fail.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_public_states.py; echo "rc=$?"`

Expected: `rc=1`, `21 failed, 4 passed, 4 warnings`. Only 4 pass:
`test_the_harness_runs_exactly_these_checks` (it only compares the check-name
sets, unaffected by whether the checks themselves pass), and 3 of the 24
behavioural checks -- all three cover code this task keeps rather than
changes, so they already hold against today's `main.js`:
`statLastSync reflects the most recently updated mirror`, `an active mirror
still gets the legacy status-dot healthy class` and `a syncing mirror still
drives the legacy status-indicator and pulse colour`. The other 21 fail for
six distinct reasons, confirming the harness exercises real gaps rather than
a typo:

- **13 checks** fail on a bare `data-state: expected "X", got "unknown"` (or
  `"online"`/`"disabled"` etc. depending on the check) -- today's `main.js`
  never calls `setAttribute('data-state', ...)` anywhere, so every pill, row,
  row pill and the overall card stay at the fake DOM's shipped `"unknown"`.
  This is every row of section 5.2's two tables except the ones below.
- **`an unrecognised API status maps to unknown/Unknown`** fails differently:
  `text: expected "Unknown", got "bogus"` -- today's `formatStatus()` falls
  back to returning the raw status string itself for anything unmapped,
  never the word "Unknown".
- **The two- and three-name sentence checks** fail on wording and order, not
  just presence: `sentence: expected "FreeBSD and NetBSD are experiencing
  issues.", got "NetBSD, FreeBSD are experiencing issues."` -- today's code
  joins with a bare comma (no "and"), in API-response order rather than
  `MIRRORS` order, and says "currently syncing" rather than "syncing now".
- **The stats checks** fail two different ways: `statFiles: expected
  "604,618", got "—"` (the element and the read of `totals.files` do not
  exist yet), and, more interestingly, `statSize: expected "—", got
  undefined` -- today's `updateHeroStats` guards on `data.totals` being
  truthy, not on `data.totals.size` itself, so an empty `totals: {}` (exactly
  what `tests/js/contrast_harness.mjs`'s stub sends) assigns the bare JS value
  `undefined` to `#statSize`'s `textContent`. The harness's fake DOM stores
  whatever is assigned without coercing it, which is why the failure reads
  `got undefined` rather than a string; a real browser's `textContent` setter
  treats an assigned `undefined` the same as `null` and empties the element
  instead (checked directly against headless Chromium: assigning `undefined`
  there produces `""`), so today's live bug is an emptied stat, not literally
  the word "undefined" on screen. Either way this is a real bug the new model
  fixes as a side effect of "only write a value that is present".
- **The hostname check** fails narrowly, not outright: `every [data-hostname]
  text: expected true, got false`. The harness calls `setHostname()` directly
  (it is page setup, not part of `load()`'s call graph -- see the file
  header), so against today's `main.js` it *does* still fill `#hostname` and
  `#rsynchost` correctly; only the new `[data-hostname]` elements stay empty,
  because today's selector, `'#hostname, #rsynchost'`, does not include them
  yet.
- **The two failure-behaviour checks** are the exception: `a first-load API
  failure ...` fails only on `overall title: expected "Status unavailable",
  got "Checking mirror status…"` -- today's `load()` returns before touching
  the overall card at all on a failed fetch, so an outage leaves whatever the
  HTML shipped with looking current (this is the "false all-clear" constraint
  3.6 names). `an API failure after a success ...` fails on `card pill
  data-state kept: expected "online", got "unknown"`, for the same root cause
  as the 13 above.

None of the 21 throw (the `TypeError: statSize.closest is not a function`
seen while drafting the harness itself, before it stubbed `.closest()`, is
gone -- that was the harness's own gap, not `main.js`'s, and is fixed in the
committed harness above).

- [ ] **Step 4 (developer): change `frontend/public/js/main.js`.** `ThemeManager`,
  `API`, `FooterVersion`, `Toast`, `copyRsync` and `bindCopyRsyncButtons` stay
  byte-identical -- verified with `diff` against `HEAD` after this step, not
  just by eye. Two regions change: the whole `MirrorStatus` object, and the
  tail of the file from just after `bindCopyRsyncButtons()` to the end.

  Replace:

```js
// Mirror status manager
const MirrorStatus = {
    async load() {
        const data = await API.get('/stats/overview');
        if (!data) return;

        // Update hero stats
        this.updateHeroStats(data);

        // Update mirror cards
        this.updateMirrorCards(data.mirrors);

        // Update overall status
        this.updateOverallStatus(data.mirrors);
    },

    updateOverallStatus(mirrors) {
        if (!mirrors) return;

        const statusCard = document.getElementById('overallStatus');
        if (!statusCard) return;

        const statuses = Object.values(mirrors).map(m => m.status);
        const anyError = statuses.includes('error');
        const anySyncing = statuses.includes('syncing');
        const allActive = statuses.every(s => s === 'active');

        const indicator = statusCard.querySelector('.status-indicator');
        const title = statusCard.querySelector('h3');
        const desc = statusCard.querySelector('p');
        const pulse = statusCard.querySelector('.pulse');

        if (anyError) {
            indicator.className = 'status-indicator degraded';
            if (pulse) pulse.style.background = 'var(--status-error, #ef4444)';
            title.textContent = 'Degraded Service';
            const errorMirrors = Object.entries(mirrors)
                .filter(([, m]) => m.status === 'error')
                .map(([name]) => name);
            desc.textContent = `${errorMirrors.join(', ')} ${errorMirrors.length === 1 ? 'is' : 'are'} experiencing issues.`;
        } else if (anySyncing) {
            indicator.className = 'status-indicator syncing';
            if (pulse) pulse.style.background = 'var(--accent-primary)';
            title.textContent = 'Sync In Progress';
            const syncingMirrors = Object.entries(mirrors)
                .filter(([, m]) => m.status === 'syncing')
                .map(([name]) => name);
            desc.textContent = `${syncingMirrors.join(', ')} ${syncingMirrors.length === 1 ? 'is' : 'are'} currently syncing.`;
        } else if (allActive) {
            indicator.className = 'status-indicator healthy';
            if (pulse) pulse.style.background = 'var(--status-healthy)';
            title.textContent = 'All Systems Operational';
            desc.textContent = 'All mirrors are synchronized and available.';
        } else {
            indicator.className = 'status-indicator healthy';
            if (pulse) pulse.style.background = 'var(--status-healthy)';
            title.textContent = 'Systems Operational';
            desc.textContent = 'Mirrors are available.';
        }
    },

    updateHeroStats(data) {
        const statSize = document.getElementById('statSize');
        const statLastSync = document.getElementById('statLastSync');

        if (statSize && data.totals) {
            statSize.textContent = data.totals.size;
            statSize.closest('.stat-card')?.classList.remove('loading');
        }

        // Find most recent sync
        if (data.mirrors) {
            const syncs = Object.values(data.mirrors)
                .map(m => m.last_updated)
                .filter(Boolean)
                .sort()
                .reverse();

            if (syncs.length > 0 && statLastSync) {
                const lastSync = new Date(syncs[0]);
                statLastSync.textContent = this.formatRelativeTime(lastSync);
                statLastSync.closest('.stat-card')?.classList.remove('loading');
            }
        }
    },

    updateMirrorCards(mirrors) {
        if (!mirrors) return;

        for (const [name, mirror] of Object.entries(mirrors)) {
            const lowerName = name.toLowerCase();

            // Update status
            const statusEl = document.getElementById(`${lowerName}-status`);
            if (statusEl) {
                const dot = statusEl.querySelector('.status-dot');
                const text = statusEl.querySelector('.status-text');

                if (dot) {
                    const statusClassMap = {
                        'active': 'healthy',
                        'syncing': 'syncing',
                        'error': 'error',
                        'disabled': ''
                    };
                    const statusClass = statusClassMap[mirror.status] || '';
                    dot.className = 'status-dot' + (statusClass ? ' ' + statusClass : '');
                }
                if (text) {
                    text.textContent = this.formatStatus(mirror.status);
                }
            }

            // Update size
            const sizeEl = document.getElementById(`${lowerName}-size`);
            if (sizeEl && mirror.size) {
                sizeEl.textContent = mirror.size;
            }

            // Update last sync
            const syncEl = document.getElementById(`${lowerName}-sync`);
            if (syncEl && mirror.last_updated) {
                const date = new Date(mirror.last_updated);
                syncEl.textContent = this.formatRelativeTime(date);
            }
        }
    },

    formatStatus(status) {
        const statusMap = {
            'active': 'Online',
            'syncing': 'Syncing...',
            'error': 'Error',
            'disabled': 'Offline'
        };
        return statusMap[status] || status;
    },

    formatRelativeTime(date) {
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMins / 60);
        const diffDays = Math.floor(diffHours / 24);

        if (diffMins < 1) return 'Just now';
        if (diffMins < 60) return `${diffMins}m ago`;
        if (diffHours < 24) return `${diffHours}h ago`;
        if (diffDays < 7) return `${diffDays}d ago`;

        return date.toLocaleDateString();
    }
};
```

  with:

```js
// Mirror status manager
//
// docs/design/2026-09-25-reflection-redesign.md, section 5.2. Each mirror's
// card pill (#<id>-status), its stream row (#<id>-stream -- markup PR 2 adds
// later; on today's page the lookup is simply null) and the row's own .pill
// child all carry a data-state the stylesheet keys off, plus a worded
// .status-text. The overall card gets the same treatment, with its own
// data-state and a title/sentence chosen from every mirror's state at once --
// including the "API failed" and "no mirror online" cases the old
// className-only version could not represent (every() over an empty mirror
// list used to read as "all active").
//
// MIRRORS fixes the three cards the page ships. The API's own keys
// (Mirror.name, e.g. "FreeBSD") are matched to them case-insensitively: the
// real API sends that casing, the contrast harness's stub sends lower-case,
// and both must resolve to the same element ids.
const MIRRORS = ['freebsd', 'netbsd', 'openbsd'];

// API status -> this page's data-state and the word shown next to it.
// "disabled" covers both an explicit disabled status and a mirror missing
// entirely from a successful response: the backend omits disabled mirrors
// outright, so "absent" and "disabled" are the same fact here.
const STATE_TEXT = {
    online: 'Online',
    syncing: 'Syncing',
    error: 'Error',
    disabled: 'Offline',
    unknown: 'Unknown'
};

function mirrorState(apiStatus) {
    if (apiStatus === 'active') return 'online';
    if (apiStatus === 'syncing') return 'syncing';
    if (apiStatus === 'error') return 'error';
    if (apiStatus === 'disabled' || apiStatus === undefined) return 'disabled';
    return 'unknown';
}

// "A", "A and B", "A, B and C" -- for the overall card's sentence, in the
// API's own key casing and in MIRRORS order (not response order).
function joinNames(names) {
    if (names.length < 2) return names[0] || '';
    if (names.length === 2) return `${names[0]} and ${names[1]}`;
    return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}

const isAre = (count) => (count === 1 ? 'is' : 'are');

// Writes data-state and, where the element has one, its .status-text. Used
// for a mirror's card pill, its stream row, and the row's own .pill child
// alike -- every argument may be null or undefined, since the stream row and
// its pill do not exist until PR 2's new markup ships.
function paintState(el, state, text) {
    if (!el) return;
    el.setAttribute('data-state', state);
    const label = el.querySelector('.status-text');
    if (label) label.textContent = text;
}

const MirrorStatus = {
    async load() {
        const data = await API.get('/stats/overview');
        if (!data || !data.mirrors) {
            this.showUnavailable();
            return;
        }

        this.updateMirrorStates(data.mirrors);
        this.updateStats(data);

        // --- Legacy, removed in Task 5: keeps today's .status-dot,
        // .status-indicator and .pulse writes going, alongside the
        // data-state model above, until the stylesheet that reads them is
        // replaced later in this PR. ---
        this.updateMirrorCards(data.mirrors);
        this.updateOverallStatus(data.mirrors);
    },

    // The data-state model, section 5.2's first table.
    updateMirrorStates(mirrors) {
        const byLowerKey = {};
        for (const [key, mirror] of Object.entries(mirrors)) {
            byLowerKey[key.toLowerCase()] = { key, mirror };
        }

        const named = { online: [], syncing: [], error: [] };

        for (const id of MIRRORS) {
            const found = byLowerKey[id];
            const mirror = found?.mirror;
            const state = mirrorState(mirror?.status);
            const text = STATE_TEXT[state];

            paintState(document.getElementById(`${id}-status`), state, text);
            const row = document.getElementById(`${id}-stream`);
            paintState(row, state, text);
            paintState(row?.querySelector('.pill'), state, text);

            if (found && state in named) {
                named[state].push(found.key);
            }

            const sizeEl = document.getElementById(`${id}-size`);
            if (sizeEl && mirror?.size) {
                sizeEl.textContent = mirror.size;
            }

            const syncEl = document.getElementById(`${id}-sync`);
            if (syncEl && mirror?.last_updated) {
                syncEl.textContent = this.formatRelativeTime(new Date(mirror.last_updated));
            }
        }

        this.updateOverallState(named);
    },

    // The overall card, after a successful load (section 5.2's second table).
    updateOverallState(named) {
        const card = document.getElementById('overallStatus');
        if (!card) return;

        const title = card.querySelector('h3');
        const desc = card.querySelector('p');
        const onlineCount = named.online.length;

        let state;
        let titleText;
        let sentence;
        if (named.error.length > 0) {
            state = 'error';
            titleText = 'Degraded service';
            sentence = `${joinNames(named.error)} ${isAre(named.error.length)} experiencing issues.`;
        } else if (named.syncing.length > 0) {
            state = 'syncing';
            titleText = 'Sync in progress';
            sentence = `${joinNames(named.syncing)} ${isAre(named.syncing.length)} syncing now.`;
        } else if (onlineCount === MIRRORS.length) {
            state = 'online';
            titleText = 'All systems operational';
            sentence = 'All mirrors are synchronized and available.';
        } else if (onlineCount > 0) {
            state = 'online';
            titleText = 'Systems operational';
            sentence = 'Some mirrors are offline; the rest are available.';
        } else {
            state = 'disabled';
            titleText = 'No mirrors online';
            sentence = 'No mirror is reporting as online right now.';
        }

        card.setAttribute('data-state', state);
        if (title) title.textContent = titleText;
        if (desc) desc.textContent = sentence;
    },

    // The API request itself failed, or answered without a mirrors object:
    // the overall card says so; every mirror pill is left exactly as it was.
    showUnavailable() {
        const card = document.getElementById('overallStatus');
        if (!card) return;
        card.setAttribute('data-state', 'unknown');
        const title = card.querySelector('h3');
        const desc = card.querySelector('p');
        if (title) title.textContent = 'Status unavailable';
        if (desc) {
            desc.textContent =
                "The status service didn't answer. The mirrors themselves may still be reachable.";
        }
    },

    updateStats(data) {
        const statSize = document.getElementById('statSize');
        if (statSize && data.totals?.size) {
            statSize.textContent = data.totals.size;
            // --- Legacy, removed in Task 5: today's markup starts this
            // stat-card "loading"; the new markup this PR ships later
            // will not. ---
            statSize.closest('.stat-card')?.classList.remove('loading');
        }

        const statFiles = document.getElementById('statFiles');
        if (statFiles && data.totals?.files) {
            statFiles.textContent = data.totals.files;
        }

        const statLastSync = document.getElementById('statLastSync');
        if (statLastSync && data.mirrors) {
            const syncs = Object.values(data.mirrors)
                .map(m => m.last_updated)
                .filter(Boolean)
                .sort()
                .reverse();
            if (syncs.length > 0) {
                statLastSync.textContent = this.formatRelativeTime(new Date(syncs[0]));
                // --- Legacy, removed in Task 5: see above. ---
                statLastSync.closest('.stat-card')?.classList.remove('loading');
            }
        }
    },

    // --- Legacy: rewrites .status-dot's className, exactly as today.
    // Removed in Task 5 (docs/design/2026-09-25-reflection-redesign.md,
    // section 5.2 "Changes": "Data attributes, not class rewrites"). The
    // data-state model above already recomputes every mirror's state and its
    // .status-text; #<id>-size and #<id>-sync moved there too, so this keeps
    // only the one write nothing else needs. ---
    updateMirrorCards(mirrors) {
        for (const [name, mirror] of Object.entries(mirrors)) {
            const lowerName = name.toLowerCase();
            const statusEl = document.getElementById(`${lowerName}-status`);
            const dot = statusEl?.querySelector('.status-dot');
            if (!dot) continue;

            const statusClassMap = {
                'active': 'healthy',
                'syncing': 'syncing',
                'error': 'error',
                'disabled': ''
            };
            const statusClass = statusClassMap[mirror.status] || '';
            dot.className = 'status-dot' + (statusClass ? ' ' + statusClass : '');
        }
    },

    // --- Legacy: rewrites .status-indicator's className and .pulse's inline
    // background, exactly as today -- including today's own "all mirrors
    // online" logic, not the fixed table updateOverallState uses above.
    // Removed in Task 5. ---
    updateOverallStatus(mirrors) {
        const statusCard = document.getElementById('overallStatus');
        if (!statusCard) return;

        const statuses = Object.values(mirrors).map(m => m.status);
        const anyError = statuses.includes('error');
        const anySyncing = statuses.includes('syncing');
        const allActive = statuses.every(s => s === 'active');

        const indicator = statusCard.querySelector('.status-indicator');
        const pulse = statusCard.querySelector('.pulse');
        if (!indicator) return;

        if (anyError) {
            indicator.className = 'status-indicator degraded';
            if (pulse) pulse.style.background = 'var(--status-error, #ef4444)';
        } else if (anySyncing) {
            indicator.className = 'status-indicator syncing';
            if (pulse) pulse.style.background = 'var(--accent-primary)';
        } else if (allActive) {
            indicator.className = 'status-indicator healthy';
            if (pulse) pulse.style.background = 'var(--status-healthy)';
        } else {
            indicator.className = 'status-indicator healthy';
            if (pulse) pulse.style.background = 'var(--status-healthy)';
        }
    },

    formatRelativeTime(date) {
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMins / 60);
        const diffDays = Math.floor(diffHours / 24);

        if (diffMins < 1) return 'Just now';
        if (diffMins < 60) return `${diffMins}m ago`;
        if (diffHours < 24) return `${diffHours}h ago`;
        if (diffDays < 7) return `${diffDays}d ago`;

        return date.toLocaleDateString();
    }
};
```

`MIRRORS`, `STATE_TEXT`, `mirrorState`, `joinNames`, `isAre` and `paintState`
are new top-level names alongside `ThemeManager`/`API`; `formatStatus` is gone
(nothing calls it once `.status-text` is written from `STATE_TEXT` instead).
`updateMirrorCards` and `updateOverallStatus` keep their names and only their
class/style-writing halves -- the text they used to write (`.status-text`,
`h3`, `p`) moved to `updateMirrorStates`/`updateOverallState`, which is why
`updateOverallStatus` can drop its `title`/`desc` lookups entirely.
`updateMirrorCards` drops its own `if (!mirrors) return;` guard outright, not
just its body -- `load()` never calls it once `data.mirrors` has failed the
guard above, so the check would be dead code. Neither `load()` nor anything
else in this block touches `setHostname()`: that stays entirely outside
`MirrorStatus`, unchanged in when it runs (see the second replacement below).

  Second, replace:

```js
// Set hostname in UI
function setHostname() {
    const hostname = window.location.hostname;
    document.querySelectorAll('#hostname, #rsynchost').forEach(el => {
        el.textContent = hostname;
    });
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    ThemeManager.init();
    setHostname();
    bindCopyRsyncButtons();
    MirrorStatus.load();
    FooterVersion.load();

    // Refresh status every 60 seconds
    setInterval(() => MirrorStatus.load(), 60000);
});
```

  with:

```js
// Set hostname in UI
function setHostname() {
    const hostname = window.location.hostname;
    document.querySelectorAll('#hostname, #rsynchost, [data-hostname]').forEach(el => {
        el.textContent = hostname;
    });
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    ThemeManager.init();
    setHostname();
    bindCopyRsyncButtons();
    MirrorStatus.load();
    FooterVersion.load();

    // Refresh status every 60 seconds
    setInterval(() => MirrorStatus.load(), 60000);
});
```

  The page-wide `[data-copy]` buttons that section 5.1 and Task 4's markup add
  are not wired up here: `COPY_URL_BUILDERS`, `copyUrl()` and
  `bindDataCopyButtons()` all move to Task 6, which binds them and adds the
  CSP-driven click proof in the same commit. Until then those buttons exist
  (from Task 4 on) but do nothing, same as any other unbound markup.

Byte-identity of the six kept pieces was checked directly, not just asserted.
Run:

```
git diff -- frontend/public/js/main.js
```

against the working tree just before this step's commit: it reports exactly
two hunks, `@@ -87,141 +87,259 @@ const API = {` (the `MirrorStatus` region,
matching the first replacement above) and `@@ -318,7 +436,7 @@ function
bindCopyRsyncButtons() {` (this second replacement's one real line change).
Neither hunk's context or changed lines touch `ThemeManager`, `API`,
`FooterVersion`, `Toast`, `copyRsync` or `bindCopyRsyncButtons` -- a hunk-based
diff cannot miss a change to any of them, since it necessarily shows every
line that differs. The only change in this second replacement block, and the
only change anywhere in the file outside the first replacement, is
`setHostname()`'s selector gaining `, [data-hostname]`. `setHostname()`'s own
call site is untouched -- it is called once from `DOMContentLoaded`, exactly
as it was, never from `load()`: filling in the hostname is one-time page setup
with nothing to do with the status poll.

- [ ] **Step 5 (developer): run green, lint, the four named regression files, and the whole suite.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_public_states.py; echo "rc=$?"`
Expected: `25 passed, 4 warnings`, `rc=0` (the 24 behavioural checks
plus the completeness check).

Run the lint pair on `tests/test_public_states.py`:
`docker compose run --rm -T test ruff check tests/test_public_states.py; echo "rc=$?"` -> `rc=0`.
`docker compose run --rm -T test ruff format --check tests/test_public_states.py; echo "rc=$?"` ->
`1 file already formatted`, `rc=0`. (`states_harness.mjs` is JavaScript; ruff
does not lint it.)

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_theme.py tests/test_footer_version.py tests/test_public_page_csp.py tests/test_admin_js_escaping.py; echo "rc=$?"`
Expected: `134 passed, 4 warnings`, `rc=0`. This is the load-bearing
run for this task: `test_theme.py` and `test_footer_version.py` prove
`ThemeManager`/`FooterVersion` still behave correctly (on top of the `diff`
above proving they are untouched); `test_public_page_csp.py` drives real
headless Chrome through the three existing `data-copy-rsync` buttons under the
production CSP and confirms they still work (its own `[data-copy]` clicks are
Task 6's addition, not this one's); `test_admin_js_escaping.py` includes
`test_css_custom_properties_read_from_js_are_defined[main.js]`, which scans
`main.js` for every `var(--x)` and fails if `tokens.css` does not define it --
this task adds no new `var()` read, so the four pre-existing ones (all inside
the legacy `updateOverallStatus`, e.g. `var(--status-error, #ef4444)`) are the
only ones checked, and all four already resolve.

Run: `docker compose run --rm -T test; echo "rc=$?"`
Expected: `1425 passed, 7 warnings`, `rc=0` -- the base `1400`
(Task 1's own expected count) plus the `25` this task adds. Read the exit
code directly, not from a pipe to `tail`.

- [ ] **Step 6 (developer): commit.**

```bash
git add tests/js/states_harness.mjs tests/test_public_states.py frontend/public/js/main.js
git commit -m "Drive the mirror status from a data-state model"
```

### Task 3: The theme icon contract

Spec section 5.2's last bullet, "Theme icon": `ThemeManager` stops writing
glyphs. It sets `data-icon="sun|moon"` on `.theme-icon`, and the icon becomes
a CSS mask. Its `aria-label`s, storage key, system-preference fallback and
`theme-init.js` are unchanged. This task carries that contract end to end --
the harness stub, the pinned checks, `ThemeManager.apply` itself, and the one
line of `index.html` markup the attribute lands on -- while leaving every
other part of `ThemeManager` byte-identical. Task 4's stylesheet is what
actually draws the icon; until then the toggle renders as an empty button,
which is expected and is called out in Step 7 below.

Only `frontend/public/index.html` crosses into `web-designer`'s territory,
and only for the one line the spec already dictates verbatim; everything
else -- both test files and `main.js` -- is `developer`.

**Files:**
- Modify: `tests/js/theme_harness.mjs` (the `.theme-icon` stub, its two
  accessors, and the four checks that read them)
- Modify: `tests/test_theme.py` (the module docstring's description of what
  `ThemeManager.apply` keeps in step; none of the pinned `CHECKS` names
  mention a glyph, so that list itself does not move)
- Modify: `frontend/public/js/main.js` (`ThemeManager.apply`)
- Modify: `frontend/public/index.html` (the toggle's icon `<span>`)

- [ ] **Step 1 (developer): give the `.theme-icon` stub attributes, in `tests/js/theme_harness.mjs`.** The stub currently holds only a `textContent` glyph. Give it the same `setAttribute`/`getAttribute` shape the toggle stub two lines below it already has, backed by its own attribute map seeded with the shipped default (`data-icon="moon"`, empty text), and expose both readings to the checks.

  First, the two glyph constants become the attribute strings `ThemeManager` now writes. Replace:

```js
const MOON = '☾';
const SUN = '☀';
```

  with:

```js
const MOON = 'moon';
const SUN = 'sun';
```

  Then the stub itself. Replace:

```js
    const icon = { textContent: MOON };
```

  with:

```js
    const iconAttrs = new Map([['data-icon', MOON]]);
    const icon = {
        textContent: '',
        setAttribute: (name, value) => iconAttrs.set(name, String(value)),
        getAttribute: (name) => (iconAttrs.has(name) ? iconAttrs.get(name) : null),
    };
```

  Then the page object's own accessor, which the checks already call `icon()`. Replace:

```js
        theme: () => (htmlAttrs.has('data-theme') ? htmlAttrs.get('data-theme') : null),
        icon: () => icon.textContent,
        label: () => toggleAttrs.get('aria-label'),
```

  with:

```js
        theme: () => (htmlAttrs.has('data-theme') ? htmlAttrs.get('data-theme') : null),
        icon: () => icon.getAttribute('data-icon'),
        iconText: () => icon.textContent,
        label: () => toggleAttrs.get('aria-label'),
```

  `MOON` and `SUN` keep their names and only change value, so every existing `expect(page.icon(), SUN, ...)` / `expect(page.icon(), MOON, ...)` call keeps comparing against the right constant once `icon()` reads the attribute instead of the text -- only the four bodies in Step 2 need a second assertion added, not a different first one.

- [ ] **Step 2 (developer): the four checks that read the icon.** Ten of the fourteen checks never call `page.icon()` and are untouched. The other four asserted the glyph; each now asserts `data-icon` under the same constant, plus that `iconText()` is still the empty string the stub started with -- the "never written" half of the contract. Their names are unchanged; none ever named a glyph.

  In `'ThemeManager.init adopts the theme theme-init applied and syncs the toggle'`, replace:

```js
    return all(
        expect(page.theme(), 'dark', 'data-theme'),
        expect(page.icon(), SUN, 'icon'),
        expect(page.label(), 'Switch to light theme', 'aria-label'),
        expect(page.writes.length, 0, 'storage writes'),
    );
});
```

  with:

```js
    return all(
        expect(page.theme(), 'dark', 'data-theme'),
        expect(page.icon(), SUN, 'data-icon'),
        expect(page.iconText(), '', 'icon textContent'),
        expect(page.label(), 'Switch to light theme', 'aria-label'),
        expect(page.writes.length, 0, 'storage writes'),
    );
});
```

  In `'ThemeManager.init alone falls back to the saved or system theme'`, replace:

```js
    page.loadThemeManager().init();
    return all(expect(page.theme(), 'dark', 'data-theme'), expect(page.icon(), SUN, 'icon'));
});
```

  with:

```js
    page.loadThemeManager().init();
    return all(
        expect(page.theme(), 'dark', 'data-theme'),
        expect(page.icon(), SUN, 'data-icon'),
        expect(page.iconText(), '', 'icon textContent'),
    );
});
```

  In `'clicking the toggle flips the theme and saves the choice'`, replace:

```js
    return all(
        expect(page.theme(), 'light', 'data-theme'),
        expect(page.icon(), MOON, 'icon'),
        expect(page.label(), 'Switch to dark theme', 'aria-label'),
        expect(JSON.stringify(page.writes), JSON.stringify([['theme', 'light']]), 'storage writes'),
    );
});
```

  with:

```js
    return all(
        expect(page.theme(), 'light', 'data-theme'),
        expect(page.icon(), MOON, 'data-icon'),
        expect(page.iconText(), '', 'icon textContent'),
        expect(page.label(), 'Switch to dark theme', 'aria-label'),
        expect(JSON.stringify(page.writes), JSON.stringify([['theme', 'light']]), 'storage writes'),
    );
});
```

  In `'a system change is followed until the visitor chooses'`, replace:

```js
    page.systemChanges(true);
    return all(expect(page.theme(), 'dark', 'data-theme'), expect(page.icon(), SUN, 'icon'));
});
```

  with:

```js
    page.systemChanges(true);
    return all(
        expect(page.theme(), 'dark', 'data-theme'),
        expect(page.icon(), SUN, 'data-icon'),
        expect(page.iconText(), '', 'icon textContent'),
    );
});
```

- [ ] **Step 3 (developer): `tests/test_theme.py`'s docstring.** Scanned against the 14 `CHECKS` entries, none names a glyph, so the pinned list itself does not move; only the paragraph describing the contract needs correcting, since it now reads the attribute rather than writing a symbol. Replace:

```text
js/theme-init.js now runs from <head>, ahead of the stylesheets, and applies an
explicit saved choice, else the system preference, else light. main.js's
ThemeManager adopts that, keeps the toggle's icon and label in step, saves only
explicit choices, and follows system changes until one is made.
tests/js/theme_harness.mjs runs both real scripts in a Node vm with only the
browser APIs they touch stubbed.
"""
```

  with:

```text
js/theme-init.js now runs from <head>, ahead of the stylesheets, and applies an
explicit saved choice, else the system preference, else light. main.js's
ThemeManager adopts that, keeps the toggle's label and its icon's data-icon
attribute in step (docs/design/2026-09-25-reflection-redesign.md, section
5.2's "Theme icon": no glyph is ever written), saves only explicit choices,
and follows system changes until one is made.
tests/js/theme_harness.mjs runs both real scripts in a Node vm with only the
browser APIs they touch stubbed.
"""
```

- [ ] **Step 4 (developer): run the tests, and watch them fail.**

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_theme.py; echo "rc=$?"`

  Expected: `rc=1`, `4 failed, 12 passed, 4 warnings`. Exactly the four checks Step 2 touched fail, against today's `main.js`, which still writes the glyph:
  - `ThemeManager.init adopts the theme theme-init applied and syncs the toggle` -- `AssertionError: data-icon: expected "sun", got "moon"` (the stub's shipped default; `main.js` never calls `setAttribute('data-icon', ...)`, so it never moves off it).
  - `ThemeManager.init alone falls back to the saved or system theme` -- the same `data-icon` mismatch.
  - `a system change is followed until the visitor chooses` -- the same `data-icon` mismatch.
  - `clicking the toggle flips the theme and saves the choice` -- a different reason: `AssertionError: icon textContent: expected "", got "☾"`. `data-icon` itself does not fail here: today's `main.js` never calls `setAttribute('data-icon', ...)` at all, so the attribute never leaves the stub's shipped default, `moon` -- and the theme this check ends on is light, whose expected icon is also `MOON` ('moon'), so the two coincide and that assertion passes for the wrong reason. It is the second assertion, `iconText()`, that actually catches the bug: `apply()` still writes the glyph into `textContent`.

  The other ten checks pass unchanged: they never call `page.icon()` or `page.iconText()`.

- [ ] **Step 5 (developer): change `ThemeManager.apply`, in `frontend/public/js/main.js`.** Replace:

```js
    apply(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        document.getElementById('themeToggle')?.setAttribute(
            'aria-label', theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'
        );
        const icon = document.querySelector('.theme-icon');
        if (icon) {
            icon.textContent = theme === 'dark' ? '☀' : '☾';
        }
    }
```

  with:

```js
    apply(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        document.getElementById('themeToggle')?.setAttribute(
            'aria-label', theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'
        );
        document.querySelector('.theme-icon')?.setAttribute('data-icon', theme === 'dark' ? 'sun' : 'moon');
    }
```

  This is the only change to `ThemeManager`. `init`, `saved`, `preferred`, `save`, the `aria-label` strings, the `STORAGE_KEY` and `SYSTEM_DARK` fallback are untouched -- confirm with `git diff frontend/public/js/main.js`, which shows exactly this one hunk.

- [ ] **Step 6 (developer): run green.**

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_theme.py; echo "rc=$?"`
  Expected: `16 passed, 4 warnings`, `rc=0` -- the 14 behavioural checks, `test_the_harness_runs_exactly_these_checks`, and `test_theme_init_runs_in_head_before_the_stylesheets`.

- [ ] **Step 7 (web-designer): `index.html`'s icon span.** Replace:

```html
                    <span class="theme-icon">&#9790;</span>
```

  with:

```html
                    <span class="icon theme-icon" data-icon="moon" aria-hidden="true"></span>
```

  `.icon` and `.theme-icon[data-icon="..."]` have no rule yet -- `style.css` still has no selector naming either -- so the toggle button renders empty (no glyph, no mask) between this commit and Task 4's stylesheet. The button itself keeps its size from `.theme-toggle`'s padding, so it stays clickable; Step 8 confirms that with the real dynamic contrast harness rather than by assertion. No other test pins the old span: `tests/test_images.py` pins only the three favicon `<link>`s (`FAVICON_LINKS`), unaffected by this line, and no stylesheet under `frontend/public/css` has a `.theme-icon` rule to remove or collide with (`grep -rn '\.theme-icon' frontend/public/css` returns nothing, before or after). Nothing in this task's own suite pins the new span's shape either -- `tests/js/theme_harness.mjs`'s stub reads `data-icon`/`textContent` off a fake element, never this markup, so a typo in the class list or attribute name here would not be caught until Task 4's `tests/test_public_page_structure.py` parses the real HTML.

- [ ] **Step 8 (developer): run green, lint, the four named regression files, and the whole suite.**

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_theme.py; echo "rc=$?"`
  Expected: `16 passed, 4 warnings`, `rc=0` (unchanged by Step 7; index.html plays no part in the Node-vm harness).

  Run the lint pair on `tests/test_theme.py`, the only Python file this task touches:
  `docker compose run --rm -T test ruff check tests/test_theme.py; echo "rc=$?"` -> `rc=0`.
  `docker compose run --rm -T test ruff format --check tests/test_theme.py; echo "rc=$?"` -> `1 file already formatted`, `rc=0`.

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_contrast.py; echo "rc=$?"`
  Expected: `142 passed, 4 warnings`, `rc=0`. This is the load-bearing check for Step 7: `-k "real_browser or dynamic"` selects 48 of the 142, 47 of them parametrized cases of `test_public_site_contrast_in_a_real_browser` (34, one per pinned selector per theme) and `test_admin_panel_contrast_in_a_real_browser` (13), driven in real headless Chrome, plus one static pin (`test_dynamic_probe_list_matches_the_harness`). The public 34 share one fixture that only reaches its dark-theme readings by dispatching a genuine mouse click at `#themeToggle`'s bounding-box centre and then asserting `data-theme` flipped -- a click that fails raises inside fixture setup, and every one of the 34 would report as an error, not a pass. All 47 browser-driven cases passed, so the now-empty button is still hit at its layout position under the 1400x4200 viewport `contrast_harness.mjs` uses.

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_footer_version.py; echo "rc=$?"`
  Expected: `20 passed, 4 warnings`, `rc=0` -- unaffected; `FooterVersion` is a separate top-level `const` this task never touches.

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_public_states.py; echo "rc=$?"`
  Expected: `25 passed, 4 warnings`, `rc=0` -- `states_harness.mjs` loads `main.js` for `MirrorStatus` alone and never touches `ThemeManager` or `.theme-icon`.

  Run: `docker compose run --rm -T test; echo "rc=$?"`
  Expected: `1425 passed, 7 warnings`, `rc=0` -- the same count PR 2 entered this task with: this task edits four checks' bodies and one docstring paragraph without adding or removing a single test. Read the exit code directly, not through a `tail`.

- [ ] **Step 9 (developer): commit.**

```bash
git add tests/js/theme_harness.mjs tests/test_theme.py frontend/public/js/main.js frontend/public/index.html
git commit -m "Set the theme icon by data-icon instead of a glyph"
```

---

## Chunk 2: The switch

One task: the palette, the stylesheet and the page change together with the contrast tests that pin them.

### Task 4: The palette, the stylesheet and the page, switched together

Spec sections 4.1-4.5, 4.7, 4.8, 5.1 and 9 are the contract. `tokens.css` gets the Reflection palette, `style.css` and `index.html` are rewritten for section 5.1's structure, and `error.css` follows the palette's dark values. The four files switch in one commit with their tests, because neither side can land first and leave the suite green:
- `tests/test_contrast.py` builds every check at import from `style.css`'s selectors and `tokens.css`'s values, so one missing selector stops the whole module from collecting. The new file fails that way against Task 3's stylesheet (`no exact '.wordmark' rule found`, Step 6), and Task 3's file fails the same way against the new one (`no exact '.stat-card' rule found`).
- `tests/js/contrast_harness.mjs` drives the real page in Chrome, and the three new test files pin the new markup, the new stylesheet's motion and its focus ring.
- `error.css`'s dark block must mirror `tokens.css`'s dark values (`tests/test_error_pages_inline_styles.py`), and its link used `--accent-secondary`, which this palette retires.

The admin console does not move. The admin halves of both contrast files carry over, apart from the colour two mutations plant (see Notes), and admin renders through the LEGACY ADMIN block Task 1 pinned, which this task keeps as it is apart from dropping `--accent-secondary`. `main.js` does not change: its legacy class writes go in Task 5, and the page-wide `data-copy` buttons this markup adds stay unbound until Task 6.

The five test files are `developer`'s (Steps 1 to 6, 12 and 13). `tokens.css`, `style.css`, `index.html` and `error.css` are `web-designer`'s (Steps 7 to 11).

**Files:**
- Replace: `tests/test_contrast.py`
- Replace: `tests/js/contrast_harness.mjs`
- Create: `tests/test_public_page_structure.py`
- Create: `tests/test_reduced_motion.py`
- Create: `tests/test_focus_ring.py`
- Replace: `frontend/public/css/tokens.css`
- Replace: `frontend/public/css/style.css`
- Replace: `frontend/public/index.html`
- Replace: `frontend/public/css/error.css`

- [ ] **Step 1 (developer): replace `tests/test_contrast.py` in full.** The admin half keeps its content: `ADMIN_PAIRS`, `compute_admin_checks`, the two admin-targeted `TOKEN_MUTATIONS` Task 1 re-pointed, the four `admin.css` mutations (two of them with a new planted colour, see Notes) and the dynamic admin checks. The public half is rewritten:
- **`PUBLIC_PAIRS`:** 25 entries for the new selectors, each checked in both themes (50 checks): `.wordmark`, `.pill` and its three `[data-state]` variants, `.status-dot` and its three `.status-card[data-state]` variants, the online stream line, and the carried-over text pairs. A new `bg_source` kind, `("body",)`, covers `.stat-label`, `.about-text a` and `.section-subtitle`, whose ancestors declare no background of their own.
- **`TOKEN_PAIRS`:** 22 pairs from spec section 9, resolved from `tokens.css` in both themes (44 checks) whether or not a rule consumes them today: `--border-strong` and `--stream-line` on `--bg-card`, `--status-info` and `--status-incomplete` on their tints (admin-only today), the disk meter's three fills (`--text-secondary`, `--status-syncing` and `--status-error`) on its track, `--border-color`, at 3:1, and the text, accent and status pairs. The meter's tick, `--text-primary` on `--bg-card` at 3:1, gets no row of its own: the 4.5:1 text pair already checks the same two tokens at a stricter threshold, and a second row would repeat its check id (see Notes). `test_tokens_css_mutation_is_caught` scores every mutation against these too; `--border-strong` and the meter fills have no selector-level consumer, so nothing else could catch a regression in them.
- **Two parser fixes, each pinned by its own test.** `header_ambient_background` picks the dark `.header` rule by the theme's label, not `theme is DARK`, which was false for the fresh theme dicts every mutation test builds (`test_header_ambient_background_uses_the_dark_selector_for_a_copied_dict`). `strip_at_rule_bodies()` removes top-level `@media` and `@keyframes` blocks, counting braces, before `_RULE_RE` runs, so a selector that `style.css` repeats inside a media query, such as `.access-grid`, is no longer found twice (`test_strip_at_rule_bodies_removes_nested_media_and_keyframes`, `test_find_block_is_not_fooled_by_a_selector_reused_inside_at_rules`). The second test's repro puts a `.nav` rule ahead of the `.access-grid` override inside its `@media` block, as `style.css` does: `_RULE_RE` swallows only the first nested rule into the at-rule's "selector", so an override that came first would never be seen twice, and the test could not fail.
- **Removed:** `test_gradient_is_not_a_resolvable_solid_colour`, `compute_gradient_text_checks`, `GRADIENT_CHECKS` and `test_gradient_text_large_text_contrast`, since `--accent-gradient` is retired and no text is painted with a gradient. `--text-muted` is now an alias of `--text-secondary` with no consumer in `style.css`, so `test_text_muted_is_no_longer_the_old_failing_value` becomes `test_text_secondary_resolves_to_each_themes_own_shade`.
- **Re-grounded self-tests:** `test_the_contrast_arithmetic_can_actually_fail` proves the formula on dark's `--status-healthy` (`#5AD69A`) against light's tint (`#E3F4EA`), 1.60:1. `test_light_dark_admin_actually_differ` compares `--bg-card` between dark and admin, a colour the legacy block still sets, instead of the retired `--accent-secondary`.
- **`TOKEN_MUTATIONS` (10, up from 7):** the two admin ones, unchanged; `text_secondary_light_reverts_to_the_other_themes_shade` and `text_secondary_dark_reverts_to_the_other_themes_shade` in place of the `text_muted_*` pair; `status_healthy_light_reverts_to_the_dark_shade`, `status_syncing_light_reverts_to_the_dark_shade` and `status_error_light_reverts_to_the_dark_shade`; `status_syncing_bg_light_reverts_to_the_dark_tint`, the one mutation on the background side of a pair, which gives the light syncing tint the dark theme's step, `--c-amber-925` (2.68:1 under `--status-syncing`); and `border_strong_light_reverts_to_a_lighter_step` and `stream_line_dark_reverts_to_a_lighter_step`, on the palette's two tightest margins, 3.17:1 and 3.10:1 against 3:1. Three dedicated tests check that the healthy mutation breaks the pill, the dot and both token pairs at once, that the stream-line one breaks the selector pair and the token pair, and that the syncing-tint one breaks the pill and its token pair. `status_syncing_tint_light_reverts_to_the_old_failing_alpha` has no successor: the tint token is retired.
- **`CSS_MUTATIONS` (still 6):** `stream_line_online_reverts_to_the_plain_border_colour` replaces `nav_link_hover_reverts_to_accent_primary_text` (see Notes), with `test_stream_line_online_css_mutation_also_fails_in_dark` for the second theme. `btn_primary_public_reverts_to_white_text` is retargeted at the new `.btn-primary` block.
- **Two more negative controls,** beside the admin one. `test_harness_reports_an_uncaught_js_error_on_the_public_page` plants a throw at the top of `main.js`'s `DOMContentLoaded` handler in a copy of the docroot, and requires the harness to fail with that error's own message. `test_harness_detects_a_low_contrast_pill_on_the_public_page` mirrors the admin control on the public page: it plants `color: #5E8A6E` on `.pill[data-state="online"]` in a copy of `style.css`, and requires a real browser to measure that probe under 4.5:1 in both themes (3.45:1 light, 3.90:1 dark).
- **`_measured_ratio()` rejects a translucent foreground,** with its own message. Every probed colour is an opaque token, so an alpha below 1 means the probe read an element its rule never painted: an unmatched `::before` reads `rgba(0, 0, 0, 0)`, which dropping the alpha scored as black, a false 21:1 on the light card.

```python
"""WCAG 2.1 AA contrast for the public site and the admin panel.

The public site runs the "Reflection" palette (docs/design/2026-09-25-
reflection-redesign.md, sections 4.1-4.4, 4.7-4.8 and 9); the admin panel is
frozen at its pre-Reflection colours by tokens.css's LEGACY ADMIN block
(tests/test_legacy_admin_tokens.py) until its own redesign. This file checks
both, but the two halves are largely independent: a change to the public
palette should never need to touch ADMIN_PAIRS, and vice versa.

This file has two halves.

STATIC (always runs, no external tooling): reads style.css, admin.css and
tokens.css as text, resolves the same var() chains a browser's cascade would,
and does the WCAG relative-luminance arithmetic. Mirrors the house style in
test_error_pages_inline_styles.py (which parses tokens.css's dark block
directly rather than hand-copying its values) and test_admin_inline_styles.py
(whose stylesheet list is deliberately not a second, driftable copy of what a
page actually links). The pairs checked here are the ones a real element on
the page actually renders -- an element's own declared background where it has
one, its nearest styled ancestor's where it does not (documented per check) --
plus a token-level table for every pair spec section 9 names regardless of
whether a component rule happens to consume it today.

DYNAMIC (skips without node/Chrome): shells out to
tests/js/contrast_harness.mjs, which drives real headless Chrome and reads
getComputedStyle for the same elements, including two genuine :hover states
dispatched as real mouse input, and every mirror-status pill/dot/stream-line
variant, driven from a stubbed /api/ response and, where the stub cannot
naturally reach a variant (the neutral pill, three of the four status-dot
states), by setting data-state on the element directly -- CSS keys off the
attribute alone, so that is a faithful probe of the same rule the static half
parses. What the static half cannot see on its own: whether the browser's
actual cascade -- specificity, inheritance, a CSS transition sampled
mid-fade -- agrees with what a text-only parser assumed. See that file's
docstring for the rest of the trade-offs (most notably: it reaches admin.js's
markup by calling its page-renderer functions directly, the same way
tests/js/escaping_harness.mjs does, rather than driving the SPA through a
live backend).

Both halves are mutation-tested: tests/test_admin_js_escaping.py's reasoning
applies here word for word -- a guard only ever seen passing is
indistinguishable from one that cannot fail.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TOKENS_CSS = REPO_ROOT / "frontend" / "public" / "css" / "tokens.css"
STYLE_CSS = REPO_ROOT / "frontend" / "public" / "css" / "style.css"
ADMIN_CSS = REPO_ROOT / "frontend" / "public" / "admin" / "css" / "admin.css"
ADMIN_JS = REPO_ROOT / "frontend" / "public" / "admin" / "js" / "admin.js"
HARNESS = REPO_ROOT / "tests" / "js" / "contrast_harness.mjs"


# ===========================================================================
# WCAG 2.1 relative luminance / contrast ratio
#
# https://www.w3.org/TR/WCAG21/#dfn-relative-luminance and #dfn-contrast-ratio.
# The one implementation dynamic measurements are also checked against
# (test_contrast_ratio_matches_the_wcag_worked_examples pins it to the
# spec's own numbers).
# ===========================================================================
def _hex_to_rgb(value):
    value = value.lstrip("#")
    assert len(value) == 6, f"expected a 6-digit hex colour, got {value!r}"
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def _srgb_channel_to_linear(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color):
    r, g, b = _hex_to_rgb(hex_color)
    R, G, B = (_srgb_channel_to_linear(c) for c in (r, g, b))
    return 0.2126 * R + 0.7152 * G + 0.0722 * B


def contrast_ratio(hex_a, hex_b):
    la, lb = relative_luminance(hex_a), relative_luminance(hex_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def composite(fg_hex, alpha, bg_hex):
    """Alpha-blend fg over bg, both given as opaque hex, in sRGB-encoded
    space -- how a browser paints a translucent rgba() box over a solid one."""
    fr, fg_, fb = _hex_to_rgb(fg_hex)
    br, bg_, bb = _hex_to_rgb(bg_hex)
    return "#%02X%02X%02X" % (
        round(fr * alpha + br * (1 - alpha)),
        round(fg_ * alpha + bg_ * (1 - alpha)),
        round(fb * alpha + bb * (1 - alpha)),
    )


def test_contrast_ratio_matches_the_wcag_worked_examples():
    """Pins the formula itself, independent of this app's tokens, against
    values anyone can check by hand: pure black on white is exactly 21:1,
    and swapping the two arguments must not change the answer."""
    assert contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio("#FFFFFF", "#000000") == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio("#777777", "#777777") == pytest.approx(1.0, abs=0.001)


def test_composite_matches_simple_alpha_blend_arithmetic():
    assert composite("#FF0000", 0.0, "#00FF00") == "#00FF00"
    assert composite("#FF0000", 1.0, "#00FF00") == "#FF0000"
    assert composite("#FFFFFF", 0.5, "#000000") == "#808080"


# ===========================================================================
# A tiny CSS reader: comment stripping, at-rule stripping, exact-selector
# block lookup, declaration lookup, and var() resolution against tokens.css's
# cascade.
#
# Deliberately not a general CSS parser -- just enough to answer "what does
# this exact selector declare for this exact property", the same scope
# test_error_pages_inline_styles.py's regexes keep to.
# ===========================================================================
_RULE_RE = re.compile(r"([^{}]+)\{([^}]*)\}")
_AT_RULE_OPEN = re.compile(r"@(?:media|keyframes)\b[^{]*\{")


def strip_css_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def strip_at_rule_bodies(css):
    """Removes every top-level @media/@keyframes block, brace-depth-counted
    by hand rather than left to _RULE_RE (which has no concept of nesting):
    _RULE_RE's `[^}]*` body stops at the FIRST `}` it meets, so the first
    rule nested inside one of these blocks merges into the at-rule's own
    "selector" (swallowing that rule's opening brace), and every rule AFTER
    the first then looks exactly like an ordinary, unconditional top-level
    rule to _RULE_RE -- selector text and all. A selector reused inside a
    responsive override or a @keyframes step then makes find_block() see its
    real, unconditional rule "twice" (style.css has this shape today: a
    top-level `.access-grid` under Mirrors/Access, and another one -- a
    responsive override, one column instead of auto-fit -- inside `@media
    (max-width: 639.98px)`). Removing the whole block first means _RULE_RE
    only ever sees the rules a pinned selector is actually meant to name: an
    unconditional, always-applied one. See
    test_find_block_is_not_fooled_by_a_selector_reused_inside_at_rules for
    the regression this fixes.
    """
    out, pos = [], 0
    for m in _AT_RULE_OPEN.finditer(css):
        if m.start() < pos:
            continue  # already inside a block this loop is removing
        out.append(css[pos : m.start()])
        depth, i = 1, m.end()
        while depth > 0 and i < len(css):
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
            i += 1
        pos = i
    out.append(css[pos:])
    return "".join(out)


def _prepared_css(css_text):
    """Comments, then @media/@keyframes bodies, stripped in that order: a
    comment could itself contain a brace, which would desync
    strip_at_rule_bodies()'s hand-rolled depth counter if it ran first."""
    return strip_at_rule_bodies(strip_css_comments(css_text))


def test_strip_at_rule_bodies_removes_nested_media_and_keyframes():
    css = (
        ".access-grid { grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }\n"
        "@media (max-width: 639.98px) {\n"
        "    .access-grid { grid-template-columns: 1fr; }\n"
        "    .nav { display: none; }\n"
        "}\n"
        "@keyframes spin {\n"
        "    0% { transform: rotate(0deg); }\n"
        "    100% { transform: rotate(360deg); }\n"
        "}\n"
    )
    prepared = strip_at_rule_bodies(css)
    assert "@media" not in prepared
    assert "@keyframes" not in prepared
    assert "639.98px" not in prepared
    assert "rotate" not in prepared
    # The real, unconditional rule survives untouched.
    assert (
        ".access-grid { grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }" in prepared
    )


def test_find_block_is_not_fooled_by_a_selector_reused_inside_at_rules():
    """Pins the _RULE_RE nested-at-rule bug directly, with a minimal repro
    of style.css's real shape: a responsive override of ".access-grid" that
    is not the first rule in its @media block. The first nested rule is the
    one _RULE_RE merges into the at-rule's own "selector", so the repro needs
    a rule ahead of the override, as style.css has (".nav" there). Without
    strip_at_rule_bodies(), find_block() sees ".access-grid" twice (its real
    top-level rule, plus the override, which _RULE_RE's brace-per-rule
    matching cannot tell apart from a second top-level one) and raises
    "found 2 times, expected 1" -- a false failure on a perfectly ordinary
    responsive override, for a selector nobody had touched."""
    css = (
        ".access-grid { grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }\n"
        "@media (max-width: 639.98px) {\n"
        "    .nav { display: none; }\n"
        "    .access-grid { grid-template-columns: 1fr; }\n"
        "}\n"
    )
    block = find_block(css, ".access-grid")
    assert block.strip() == "grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));"


def find_block(css_text, selector):
    """The declaration body of the one rule whose selector, once stripped of
    surrounding whitespace, is exactly `selector` -- not a substring match,
    so `.nav-link` cannot accidentally match `.nav-link:hover` and a combined
    selector like `th,\\ntd` cannot accidentally match `th`. Only ever looks
    at top-level rules: see strip_at_rule_bodies() above for why a selector
    inside a @media/@keyframes block must not count."""
    css = _prepared_css(css_text)
    matches = [body for sel, body in _RULE_RE.findall(css) if sel.strip() == selector]
    assert matches, f"no exact {selector!r} rule found"
    assert len(matches) == 1, f"{selector!r} rule found {len(matches)} times, expected 1"
    return matches[0]


_PROP_TEMPLATE = r"(?<![\w-]){prop}(?![\w-])\s*:\s*([^;]+);"


def declared(block, prop):
    """The value of an exact property name in a declaration block. The
    negative look-around stops `background` from matching inside
    `background-color`."""
    m = re.search(_PROP_TEMPLATE.format(prop=re.escape(prop)), block)
    assert m, f"no {prop!r} declaration in block {block!r}"
    return m.group(1).strip()


def declared_background(block):
    """`background-color` if present, else the shorthand `background` --
    every component rule this file reads uses one or the other for a single
    solid colour, never both."""
    for prop in ("background-color", "background"):
        m = re.search(_PROP_TEMPLATE.format(prop=prop), block)
        if m:
            return m.group(1).strip()
    raise AssertionError(f"no background/background-color in block {block!r}")


def var_ref(value):
    m = re.fullmatch(r"var\((--[\w-]+)\)", value)
    assert m, f"expected a bare var(--x) reference, got {value!r}"
    return m.group(1)


# A handful of CSS keyword colours, needed only so the mutation tests below
# can plant a literal like `color: white` and have the checker compute a
# real (failing) ratio for it, instead of tripping var_ref()'s assertion on a
# value that was never a token reference to begin with. No real, un-mutated
# rule in style.css/admin.css uses one of these any more.
_NAMED_COLORS = {"white": "#FFFFFF", "black": "#000000"}


def color_hex(theme, raw_value):
    """Resolve a declared colour value -- var(--x), a bare hex, or a CSS
    keyword -- to a plain #RRGGBB against `theme`."""
    raw_value = raw_value.strip()
    m = re.fullmatch(r"var\((--[\w-]+)\)", raw_value)
    if m:
        return resolved_hex(theme, m.group(1))
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", raw_value):
        return raw_value.upper()
    if raw_value.lower() in _NAMED_COLORS:
        return _NAMED_COLORS[raw_value.lower()]
    raise AssertionError(f"unrecognised colour value: {raw_value!r}")


# ===========================================================================
# tokens.css: build one resolved dict of custom properties per theme
# ===========================================================================
def parse_custom_properties(block):
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", block))


def build_themes(tokens_css_text):
    """Returns (light, dark, admin), each {token_name: raw value string}.

    Raw, not yet resolved through var() -- resolve()/resolved_hex() below walk
    the chain at lookup time using whichever of these three dicts is asked,
    so a token that is only overridden for one theme still resolves correctly
    through the layers under it (tokens.css's own layering rule: dark
    overrides light, admin overrides dark).
    """
    css = _prepared_css(tokens_css_text)
    root_bodies, dark_body, admin_body = [], None, None
    for sel, body in _RULE_RE.findall(css):
        sel = sel.strip()
        if sel == ":root":
            root_bodies.append(body)
        elif sel == '[data-theme="dark"]':
            assert dark_body is None, 'more than one [data-theme="dark"] block'
            dark_body = body
        elif sel == '[data-surface="admin"]':
            assert admin_body is None, 'more than one [data-surface="admin"] block'
            admin_body = body

    assert (
        len(root_bodies) == 3
    ), f"expected 3 :root blocks (primitives, invariants, light theme), found {len(root_bodies)}"
    assert dark_body is not None, 'no [data-theme="dark"] block found'
    assert admin_body is not None, 'no [data-surface="admin"] block found'

    light = {}
    for body in root_bodies:
        light.update(parse_custom_properties(body))

    dark = dict(light)
    dark.update(parse_custom_properties(dark_body))

    admin = dict(dark)
    admin.update(parse_custom_properties(admin_body))

    return light, dark, admin


def resolve(theme, name, _seen=frozenset()):
    assert name not in _seen, f"cycle resolving {name}: {_seen}"
    assert name in theme, f"{name} is not defined in this theme"
    value = theme[name].strip()
    m = re.fullmatch(r"var\((--[\w-]+)\)", value)
    if m:
        return resolve(theme, m.group(1), _seen | {name})
    return value


def resolved_hex(theme, name):
    value = resolve(theme, name)
    assert re.fullmatch(r"#[0-9A-Fa-f]{6}", value), (
        f"{name} does not resolve to a plain hex colour (got {value!r}); "
        f"a gradient or non-colour token was asked for a solid colour"
    )
    return value.upper()


TOKENS_TEXT = TOKENS_CSS.read_text(encoding="utf-8")
LIGHT, DARK, ADMIN = build_themes(TOKENS_TEXT)


def test_light_dark_admin_actually_differ():
    """A guard against build_themes() silently returning the same dict three
    times, which would make every "checked in both themes" claim below
    meaningless. --bg-card is a colour the LEGACY ADMIN block still sets as
    a literal (tests/test_legacy_admin_tokens.py), so it also proves admin
    is not just quietly inheriting dark's resolved value."""
    assert resolved_hex(LIGHT, "--bg-primary") != resolved_hex(DARK, "--bg-primary")
    assert resolved_hex(DARK, "--bg-card") != resolved_hex(ADMIN, "--bg-card")


# ===========================================================================
# .header's own background is a literal translucent rgba(), not a
# var(--bg-*) token -- it needs the alpha for the sticky/blurred header
# effect. .nav-link, .nav-admin and .wordmark have no background of their
# own, so the backdrop they actually render against is that rgba() composited
# over whatever is behind the header: --bg-primary, the page background.
#
# Keyed on the theme LABEL, not on `theme is DARK`: the real (non-mutated)
# checks below always pass this module's own LIGHT/DARK singletons, so
# `is DARK` happened to work for them, but every mutation test rebuilds a
# fresh pair of dicts via build_themes() -- equal by value, never `is DARK`
# -- and a fresh "dark" dict was silently scored against the LIGHT .header
# rule instead. See test_header_ambient_background_uses_the_dark_selector_
# for_a_copied_dict for the regression this fixes.
# ===========================================================================
def header_ambient_background(style_css_text, theme, theme_label):
    selector = '[data-theme="dark"] .header' if theme_label == "dark" else ".header"
    block = find_block(style_css_text, selector)
    value = declared_background(block)
    m = re.fullmatch(
        r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)", value
    )
    assert m, f"{selector} background is not a plain rgb()/rgba(): {value!r}"
    r, g, b = (float(m.group(i)) for i in (1, 2, 3))
    alpha = float(m.group(4)) if m.group(4) is not None else 1.0
    literal_hex = "#%02X%02X%02X" % (round(r), round(g), round(b))
    return composite(literal_hex, alpha, resolved_hex(theme, "--bg-primary"))


def test_header_ambient_background_uses_the_dark_selector_for_a_copied_dict():
    """header_ambient_background used to decide light vs dark with
    `theme is DARK`, true only for this module's own singleton. A dict that
    is merely equal to DARK -- exactly what every mutation test hands it,
    via a fresh build_themes() call -- used to fall through to the LIGHT
    `.header` rule instead, silently scoring a dark-theme header pairing
    against the wrong backdrop. text_secondary_dark_reverts_to_the_other_
    themes_shade below is the mutation that actually found this: under the
    old identity check it measured 4.62:1 against the light header (a false
    pass) where the real, dark header gives 2.67:1 (a real failure)."""
    copied_dark = dict(DARK)
    assert copied_dark is not DARK
    assert header_ambient_background(
        STYLE_CSS_TEXT, copied_dark, "dark"
    ) == header_ambient_background(STYLE_CSS_TEXT, DARK, "dark")


# ===========================================================================
# The pairs the public site actually renders (style.css)
#
# Each entry: (id, fg_selector, fg_prop, bg_source, min_ratio). bg_source is
# ("own", ) for the same block's own background, ("parent", selector) for a
# named ancestor rule's background (however many DOM levels up -- neither
# side of this file tracks real nesting depth, only which rule to read),
# ("body", ) for the page's own background where the element's whole ancestor
# chain declares none of its own, or ("header", ) for the header's special
# translucent composite. Checked in both light and dark, since main.js can
# set either on the public site.
# ===========================================================================
PUBLIC_PAIRS = [
    ("body", "body", "color", ("own",), 4.5),
    (".nav-link", ".nav-link", "color", ("header",), 4.5),
    (".nav-link:hover", ".nav-link:hover", "color", ("own",), 4.5),
    (".nav-admin", ".nav-admin", "color", ("header",), 4.5),
    (".wordmark", ".wordmark", "color", ("header",), 4.5),
    # .hero/.hero-copy/.stat declare no background of their own; what
    # actually renders behind .stat-label is body's own --bg-primary.
    (".stat-label", ".stat-label", "color", ("body",), 4.5),
    (".mirror-description", ".mirror-description", "color", ("parent", ".mirror-card"), 4.5),
    # .mirror-details itself has no background; two levels up to the card.
    (".mirror-details dt", ".mirror-details dt", "color", ("parent", ".mirror-card"), 4.5),
    (".btn-primary", ".btn-primary", "color", ("own",), 4.5),
    (".btn-secondary:hover", ".btn-secondary:hover", "color", ("own",), 4.5),
    (".access-label", ".access-label", "color", ("parent", ".access-row"), 4.5),
    (".footer-content p", ".footer-content p", "color", ("parent", ".footer"), 4.5),
    (".footer-content a", ".footer-content a", "color", ("parent", ".footer"), 4.5),
    (".about-text a", ".about-text a", "color", ("body",), 4.5),
    (".section-subtitle", ".section-subtitle", "color", ("body",), 4.5),
    (".toast", ".toast", "color", ("own",), 4.5),
    # Pills (spec section 4.8): keyed only by data-state, never a class
    # rewrite. Neutral (the base rule, used for "disabled"/"unknown") plus
    # the three named states.
    (".pill", ".pill", "color", ("own",), 4.5),
    ('.pill[data-state="online"]', '.pill[data-state="online"]', "color", ("own",), 4.5),
    ('.pill[data-state="syncing"]', '.pill[data-state="syncing"]', "color", ("own",), 4.5),
    ('.pill[data-state="error"]', '.pill[data-state="error"]', "color", ("own",), 4.5),
    # The overall status card's dot: a UI indicator (WCAG 2.1 SC 1.4.11,
    # 3:1), not text -- fg_prop is `background` (the dot's own fill), and
    # the surface it sits on is .status-card's own --bg-card, regardless of
    # which data-state rule (if any) currently overrides the dot's colour.
    (".status-dot", ".status-dot", "background", ("parent", ".status-card"), 3.0),
    (
        '.status-card[data-state="online"] .status-dot',
        '.status-card[data-state="online"] .status-dot',
        "background",
        ("parent", ".status-card"),
        3.0,
    ),
    (
        '.status-card[data-state="syncing"] .status-dot',
        '.status-card[data-state="syncing"] .status-dot',
        "background",
        ("parent", ".status-card"),
        3.0,
    ),
    (
        '.status-card[data-state="error"] .status-dot',
        '.status-card[data-state="error"] .status-dot',
        "background",
        ("parent", ".status-card"),
        3.0,
    ),
    # The one sync-stream state with a bare var() background; syncing/error
    # paint with a gradient (see the note below PUBLIC_CHECKS).
    (
        '.stream[data-state="online"] .stream-line::before',
        '.stream[data-state="online"] .stream-line::before',
        "background",
        ("parent", ".streams-inner"),
        3.0,
    ),
]


def compute_public_checks(style_css_text, themes):
    """themes: {label: theme_dict}. Returns [(check_id, ratio, min_ratio, fg_hex, bg_hex)]."""
    results = []
    for label, theme in themes.items():
        for check_id, fg_selector, fg_prop, bg_source, min_ratio in PUBLIC_PAIRS:
            fg_block = find_block(style_css_text, fg_selector)
            fg_hex = color_hex(theme, declared(fg_block, fg_prop))

            kind = bg_source[0]
            if kind == "own":
                bg_hex = color_hex(theme, declared_background(fg_block))
            elif kind == "parent":
                bg_block = find_block(style_css_text, bg_source[1])
                bg_hex = color_hex(theme, declared_background(bg_block))
            elif kind == "body":
                body_block = find_block(style_css_text, "body")
                bg_hex = color_hex(theme, declared_background(body_block))
            elif kind == "header":
                bg_hex = header_ambient_background(style_css_text, theme, label)
            else:  # pragma: no cover - guards a typo in PUBLIC_PAIRS itself
                raise AssertionError(f"unknown bg_source kind {kind!r}")

            ratio = contrast_ratio(fg_hex, bg_hex)
            results.append((f"{check_id} [{label}]", ratio, min_ratio, fg_hex, bg_hex))
    return results


# Not selector-pinnable, and not worth making so: the syncing stream's dots
# and the error stream's dashed line are radial-gradient()/repeating-linear-
# gradient() values wrapping the token, not a bare var(), so color_hex()
# would reject them by design -- that guard is doing its job. Both are
# covered instead by the token-level table below, which needs no CSS
# parsing at all.
STYLE_CSS_TEXT = STYLE_CSS.read_text(encoding="utf-8")
PUBLIC_CHECKS = compute_public_checks(STYLE_CSS_TEXT, {"light": LIGHT, "dark": DARK})


@pytest.mark.parametrize(
    "check_id,ratio,min_ratio,fg_hex,bg_hex",
    PUBLIC_CHECKS,
    ids=[c[0] for c in PUBLIC_CHECKS],
)
def test_public_site_contrast(check_id, ratio, min_ratio, fg_hex, bg_hex):
    assert (
        ratio >= min_ratio
    ), f"{check_id}: {fg_hex} on {bg_hex} is {ratio:.2f}:1, needs >= {min_ratio}:1"


def test_footer_version_declares_no_opacity():
    """opacity multiplies straight through whatever colour is behind it and
    is invisible to a colour-token contrast check (getComputedStyle().color
    is unaffected by opacity; it is a paint-time effect) -- an opacity here
    could take an already-compliant --text-secondary back down below 4.5:1
    without any of the ratio checks above ever seeing it, since
    .footer-version declares no colour of its own (it inherits
    .footer-content p's, covered above)."""
    block = find_block(STYLE_CSS_TEXT, ".footer-version")
    m = re.search(_PROP_TEMPLATE.format(prop="opacity"), block)
    assert m is None or m.group(1).strip() in ("1", "1.0"), (
        f".footer-version declares opacity: {m.group(1) if m else None!r}, which "
        f"fades --text-secondary below 4.5:1 against --bg-secondary in both themes"
    )


# ===========================================================================
# The token-level pairs spec section 9 names, resolved directly from
# tokens.css in both themes -- independent of whether a component rule in
# style.css happens to consume a given pair today. Two of these
# (--status-info, --status-incomplete) are admin-only today (spec section
# 4.8's table); --border-strong has no public consumer yet either (no form
# field on the public site), and neither do the disk meter's fills (spec
# section 4.8, "Disk meter") -- all of them are pinned here so whichever
# rule consumes them first (the admin console's own redesign, spec section
# 6.1) inherits an already-checked pair instead of introducing one.
# ===========================================================================
TOKEN_PAIRS = [
    ("--text-primary", "--bg-primary", 4.5),
    ("--text-primary", "--bg-card", 4.5),
    ("--text-primary", "--bg-secondary", 4.5),
    ("--text-secondary", "--bg-primary", 4.5),
    ("--text-secondary", "--bg-card", 4.5),
    ("--text-secondary", "--bg-secondary", 4.5),
    ("--accent-primary", "--bg-primary", 4.5),
    ("--accent-primary", "--bg-card", 4.5),
    ("--text-on-accent", "--accent-primary", 4.5),
    ("--status-healthy", "--status-healthy-bg", 4.5),
    ("--status-syncing", "--status-syncing-bg", 4.5),
    ("--status-error", "--status-error-bg", 4.5),
    ("--status-info", "--status-info-bg", 4.5),
    ("--status-incomplete", "--status-incomplete-bg", 4.5),
    ("--border-strong", "--bg-card", 3.0),
    ("--stream-line", "--bg-card", 3.0),
    ("--status-healthy", "--bg-card", 3.0),
    ("--status-syncing", "--bg-card", 3.0),
    ("--status-error", "--bg-card", 3.0),
    # The disk meter: each fill against the track (--border-color), 3:1. The
    # tick at 85% (--text-primary on --bg-card, 3:1) has no row of its own:
    # the 4.5:1 text pair at the top of this list is the same two tokens at
    # a stricter threshold, and a second row would repeat its check id.
    ("--text-secondary", "--border-color", 3.0),
    ("--status-syncing", "--border-color", 3.0),
    ("--status-error", "--border-color", 3.0),
]


def compute_token_checks(themes):
    """themes: {label: theme_dict}. Same return shape as compute_public_checks."""
    results = []
    for label, theme in themes.items():
        for fg, bg, min_ratio in TOKEN_PAIRS:
            fg_hex, bg_hex = resolved_hex(theme, fg), resolved_hex(theme, bg)
            ratio = contrast_ratio(fg_hex, bg_hex)
            results.append((f"{fg} on {bg} [{label}]", ratio, min_ratio, fg_hex, bg_hex))
    return results


TOKEN_CHECKS = compute_token_checks({"light": LIGHT, "dark": DARK})


@pytest.mark.parametrize(
    "check_id,ratio,min_ratio,fg_hex,bg_hex", TOKEN_CHECKS, ids=[c[0] for c in TOKEN_CHECKS]
)
def test_token_level_contrast(check_id, ratio, min_ratio, fg_hex, bg_hex):
    assert (
        ratio >= min_ratio
    ), f"{check_id}: {fg_hex} on {bg_hex} is {ratio:.2f}:1, needs >= {min_ratio}:1"


# ===========================================================================
# The pairs the admin panel actually renders (admin.css). Admin is dark-only
# (data-theme="dark" data-surface="admin" is static, never toggled), so
# these are checked once, against ADMIN. Untouched by the public palette
# switch: every one of these still passes because of the LEGACY ADMIN block.
# ===========================================================================
# fmt: off
ADMIN_PAIRS = [
    (".nav-item.active", ".nav-item.active", "color", ("own",), 4.5),
    (".user-avatar", ".user-avatar", "color", ("own",), 4.5),
    (".user-role", ".user-role", "color", ("parent", ".user-info"), 4.5),
    (".nav-section-title", ".nav-section-title", "color", ("parent", ".sidebar"), 4.5),
    (".stat-card-label", ".stat-card-label", "color", ("parent", ".stat-card"), 4.5),
    ("th", "th", "color", ("own",), 4.5),
    (".status-badge.disabled", ".status-badge.disabled", "color", ("own",), 4.5),
    (".status-badge.active", ".status-badge.active", "color", ("own",), 4.5),
    (".status-badge.syncing", ".status-badge.syncing", "color", ("own",), 4.5),
    (".status-badge.error", ".status-badge.error", "color", ("own",), 4.5),
    (".stat-card-trend.up", ".stat-card-trend.up", "color", ("own",), 4.5),
    (".stat-card-trend.down", ".stat-card-trend.down", "color", ("own",), 4.5),
    (".form-input::placeholder", ".form-input::placeholder", "color", ("parent", ".form-input"), 4.5),
    (".btn-primary", ".btn-primary", "color", ("own",), 4.5),
    (".btn-danger", ".btn-danger", "color", ("own",), 4.5),
    (".modal-close", ".modal-close", "color", ("parent", ".modal"), 4.5),
    (".activity-time", ".activity-time", "color", ("parent", ".card"), 4.5),
    (".login-subtitle", ".login-subtitle", "color", ("parent", ".login-card"), 4.5),
    (".login-error", ".login-error", "color", ("own",), 4.5),
    (".u-text-muted", ".u-text-muted", "color", ("parent", ".card"), 4.5),
    (".log-pre-error", ".log-pre-error", "color", ("parent", ".log-pre"), 4.5),
    # Health-checks card (dashboard): the "incomplete" state's own badge
    # variant, and the .card-title-adjacent subheading the card's four
    # checklists use instead of it. Same shape as the pairs above, just two
    # selectors that did not exist before that card did.
    (".status-badge.health-incomplete", ".status-badge.health-incomplete", "color", ("own",), 4.5),
    (".card-subtitle", ".card-subtitle", "color", ("parent", ".card"), 4.5),
    # Archive inventory (Protected Paths page): the informational tag variant
    # (Newest / Latest-in-major / Pre-release) and the "At risk" warning pill
    # -- see releaseTagBadges in admin.js. Both are their own solid fill, the
    # same "own" shape as the other .status-badge variants above.
    (".status-badge.info", ".status-badge.info", "color", ("own",), 4.5),
    (".status-badge.at-risk", ".status-badge.at-risk", "color", ("own",), 4.5),
    # The location-name chips joinCodeList's <code> elements render as, once
    # scoped by the .code-chip-list wrapper (renderMirrorInventoryCard,
    # releaseRows). Its own solid background, not the ambient card/table one.
    (".code-chip-list code", ".code-chip-list code", "color", ("own",), 4.5),
]
# fmt: on


def compute_admin_checks(admin_css_text, admin_theme):
    results = []
    for check_id, fg_selector, fg_prop, bg_source, min_ratio in ADMIN_PAIRS:
        fg_block = find_block(admin_css_text, fg_selector)
        fg_hex = color_hex(admin_theme, declared(fg_block, fg_prop))

        kind = bg_source[0]
        if kind == "own":
            bg_hex = color_hex(admin_theme, declared_background(fg_block))
        elif kind == "parent":
            bg_block = find_block(admin_css_text, bg_source[1])
            bg_hex = color_hex(admin_theme, declared_background(bg_block))
        else:  # pragma: no cover
            raise AssertionError(f"unknown bg_source kind {kind!r}")

        ratio = contrast_ratio(fg_hex, bg_hex)
        results.append((check_id, ratio, min_ratio, fg_hex, bg_hex))
    return results


ADMIN_CSS_TEXT = ADMIN_CSS.read_text(encoding="utf-8")
ADMIN_CHECKS = compute_admin_checks(ADMIN_CSS_TEXT, ADMIN)


@pytest.mark.parametrize(
    "check_id,ratio,min_ratio,fg_hex,bg_hex", ADMIN_CHECKS, ids=[c[0] for c in ADMIN_CHECKS]
)
def test_admin_panel_contrast(check_id, ratio, min_ratio, fg_hex, bg_hex):
    assert (
        ratio >= min_ratio
    ), f"{check_id}: {fg_hex} on {bg_hex} is {ratio:.2f}:1, needs >= {min_ratio}:1"


# ---------------------------------------------------------------------------
# The .form-input::placeholder case needs its ancestor's *pseudo-element*
# declaration read directly rather than through find_block()/declared() on
# the input itself -- ::placeholder is its own rule in admin.css.
# ---------------------------------------------------------------------------
def test_the_placeholder_check_reads_the_pseudo_element_rule():
    """Guards the ADMIN_PAIRS entry above against silently resolving the
    *input's* text colour instead of the placeholder's -- they are different
    rules (.form-input sets --text-primary; .form-input::placeholder sets
    --text-muted) and a selector typo would make this check pass for the
    wrong reason."""
    block = find_block(ADMIN_CSS_TEXT, ".form-input::placeholder")
    assert var_ref(declared(block, "color")) == "--text-muted"


# ===========================================================================
# Guards that can actually fail
#
# Same reasoning as test_error_pages_inline_styles.py's
# test_the_missing_class_check_can_actually_find_one and
# test_admin_inline_styles.py's test_the_check_can_actually_find_a_missing_
# class: a check that has only ever been seen passing is indistinguishable
# from one whose extractor is silently broken.
# ===========================================================================
def test_the_contrast_arithmetic_can_actually_fail():
    """Proves the formula finds a real failure when handed one, not just a
    passing one: dark's --status-healthy (#5AD69A, chosen for a dark
    surface) on light's --status-healthy-bg tint (#E3F4EA) is the exact
    wrong-theme pairing status_healthy_light_reverts_to_the_dark_shade
    plants below -- see tokens.css for why each theme needs its own step of
    the green ramp."""
    assert contrast_ratio("#5AD69A", "#E3F4EA") < 4.5


def test_text_secondary_resolves_to_each_themes_own_shade():
    """--text-muted has no consumer of its own (grep style.css -- nothing
    reads it): it is a plain alias of --text-secondary in both themes (see
    tokens.css's LIGHT/DARK blocks). The meaningful fact for this palette is
    that --text-secondary -- consumed everywhere from .nav-link to
    .footer-content -- resolves to each theme's OWN step of the grey ramp,
    never the other theme's, which is exactly what
    text_secondary_light/dark_reverts_to_the_other_themes_shade below
    mutate away."""
    assert resolved_hex(LIGHT, "--text-secondary") != resolved_hex(DARK, "--text-secondary")
    assert resolved_hex(LIGHT, "--text-muted") == resolved_hex(LIGHT, "--text-secondary")
    assert resolved_hex(DARK, "--text-muted") == resolved_hex(DARK, "--text-secondary")


def test_white_on_accent_primary_would_fail_in_dark_and_admin():
    """White text is not used on a solid --accent-primary fill anywhere any
    more (see --text-on-accent's consumers), but the number itself -- proving
    why -- must still hold, in the new public dark theme as much as in the
    (unchanged) admin one."""
    assert contrast_ratio("#FFFFFF", resolved_hex(DARK, "--accent-primary")) < 4.5
    assert contrast_ratio("#FFFFFF", resolved_hex(ADMIN, "--accent-primary")) < 4.5


# ===========================================================================
# Mutation testing (static half)
#
# Same shape as test_admin_js_escaping.py's MUTATIONS table: (name, old, new,
# must_fail). Each mutation is applied to a copy of the real file text, run
# back through the same builder/checker functions the real suite uses, and
# must turn at least the named check red. failed_ids is drawn from all three
# check tables -- public, token-level and admin -- since a token-only pair
# (--border-strong's, or the disk meter's) never appears in a selector-level
# PUBLIC_CHECKS id at all.
# ===========================================================================
TOKEN_MUTATIONS = [
    (
        # --text-muted has no consumer of its own (see
        # test_text_secondary_resolves_to_each_themes_own_shade), so the grey
        # text this guards is --text-secondary's.
        "text_secondary_light_reverts_to_the_other_themes_shade",
        "--text-secondary: var(--c-graphite-700);",
        "--text-secondary: var(--c-graphite-400);",
        ".mirror-description [light]",
    ),
    (
        # Also covers header_ambient_background()'s keying on the theme
        # label: this mutation's .nav-link [dark] must be scored against the
        # dark header, where it is 2.67:1 and fails; scored against the light
        # one it would read 4.62:1 and pass -- see
        # test_header_ambient_background_uses_the_dark_selector_for_a_
        # copied_dict above.
        "text_secondary_dark_reverts_to_the_other_themes_shade",
        "--text-secondary: var(--c-graphite-400);",
        "--text-secondary: var(--c-graphite-700);",
        ".nav-link [dark]",
    ),
    (
        # Targets the LEGACY ADMIN line, not the INVARIANTS var() reference:
        # the admin block pins its own --text-on-accent, so a mutation of the
        # shared layers never reaches ADMIN.
        "text_on_accent_reverts_to_white",
        "--text-on-accent: #0D0D1A;",
        "--text-on-accent: #FFFFFF;",
        None,  # asserted separately: this breaks an ADMIN_CHECKS id, checked below
    ),
    (
        # Same shape as the mutation above: --status-error-text exists only
        # in the admin block, so this targets that line.
        "status_error_text_reverts_to_status_error",
        "--status-error-text: #F87171;",
        "--status-error-text: #EF4444;",
        None,  # breaks an ADMIN_CHECKS id, checked below
    ),
    (
        "status_healthy_light_reverts_to_the_dark_shade",
        "--status-healthy: var(--c-green-700);",
        "--status-healthy: var(--c-green-400);",
        None,  # breaks the pill, the dot and both token pairs at once, checked below
    ),
    (
        "status_syncing_light_reverts_to_the_dark_shade",
        "--status-syncing: var(--c-amber-800);",
        "--status-syncing: var(--c-amber-400);",
        '.pill[data-state="syncing"] [light]',
    ),
    (
        "status_error_light_reverts_to_the_dark_shade",
        "--status-error: var(--c-red-650);",
        "--status-error: var(--c-red-300);",
        '.pill[data-state="error"] [light]',
    ),
    (
        # The background side of a pill pair; every other entry here moves a
        # foreground. The light tint taking the dark theme's step must fail
        # the pill that sits on it, so a pill pair that read some other
        # surface instead of its own tint cannot pass unnoticed.
        "status_syncing_bg_light_reverts_to_the_dark_tint",
        "--status-syncing-bg: var(--c-amber-50);",
        "--status-syncing-bg: var(--c-amber-925);",
        '.pill[data-state="syncing"] [light]',
    ),
    (
        # --border-strong has no colour/background consumer in style.css
        # (only a border-color:, which declared()/declared_background()
        # never scan) -- this can only ever be caught at the token level.
        "border_strong_light_reverts_to_a_lighter_step",
        "--border-strong: var(--c-graphite-500);",
        "--border-strong: var(--c-graphite-400);",
        "--border-strong on --bg-card [light]",
    ),
    (
        "stream_line_dark_reverts_to_a_lighter_step",
        "--stream-line: var(--c-graphite-650);",
        "--stream-line: var(--c-graphite-700);",
        None,  # breaks the selector-level stream-line pair and its token pair, checked below
    ),
]


@pytest.mark.parametrize(
    "name,old,new,must_fail", TOKEN_MUTATIONS, ids=[m[0] for m in TOKEN_MUTATIONS]
)
def test_tokens_css_mutation_is_caught(name, old, new, must_fail):
    assert TOKENS_TEXT.count(old) == 1, (
        f"mutation {name!r} no longer matches tokens.css exactly once "
        f"(found {TOKENS_TEXT.count(old)}). Update the mutation, do not delete it."
    )
    mutated_text = TOKENS_TEXT.replace(old, new)
    light, dark, admin = build_themes(mutated_text)

    public_results = compute_public_checks(STYLE_CSS_TEXT, {"light": light, "dark": dark})
    token_results = compute_token_checks({"light": light, "dark": dark})
    admin_results = compute_admin_checks(ADMIN_CSS_TEXT, admin)
    failed_ids = {
        cid
        for cid, ratio, min_ratio, *_ in public_results + token_results + admin_results
        if ratio < min_ratio
    }

    assert failed_ids, f"mutation {name!r} changed a live token and nothing failed"
    if must_fail is not None:
        assert must_fail in failed_ids, (
            f"mutation {name!r} was expected to fail {must_fail!r}, but the "
            f"failures were {sorted(failed_ids)}"
        )


def test_text_on_accent_mutation_breaks_an_admin_fill():
    """The two token mutations above that pass must_fail=None still have to
    break *something* concrete -- named here instead of folded into the
    parametrised case so a failure points at a specific, checkable claim
    rather than "some id or other went red"."""
    mutated_text = TOKENS_TEXT.replace("--text-on-accent: #0D0D1A;", "--text-on-accent: #FFFFFF;")
    _, _, admin = build_themes(mutated_text)
    results = {cid: ratio for cid, ratio, *_ in compute_admin_checks(ADMIN_CSS_TEXT, admin)}
    assert results[".nav-item.active"] < 4.5
    assert results[".btn-primary"] < 4.5
    assert results[".user-avatar"] < 4.5
    assert results[".btn-danger"] < 4.5


def test_status_error_text_mutation_breaks_the_error_badge():
    mutated_text = TOKENS_TEXT.replace(
        "--status-error-text: #F87171;", "--status-error-text: #EF4444;"
    )
    _, _, admin = build_themes(mutated_text)
    results = {cid: ratio for cid, ratio, *_ in compute_admin_checks(ADMIN_CSS_TEXT, admin)}
    assert results[".status-badge.error"] < 4.5
    assert results[".log-pre-error"] < 4.5


def test_status_healthy_mutation_breaks_the_pill_the_dot_and_both_tokens():
    """--status-healthy backs .pill[data-state="online"] (text on the tint),
    .status-card[data-state="online"] .status-dot (a fill on --bg-card) and
    two TOKEN_PAIRS rows at once -- darkening it for one and not the others
    was never on the table, so one mutation must break all four."""
    mutated_text = TOKENS_TEXT.replace(
        "--status-healthy: var(--c-green-700);", "--status-healthy: var(--c-green-400);"
    )
    light, dark, _ = build_themes(mutated_text)
    themes = {"light": light, "dark": dark}
    results = {cid: ratio for cid, ratio, *_ in compute_public_checks(STYLE_CSS_TEXT, themes)}
    tokens = {cid: ratio for cid, ratio, *_ in compute_token_checks(themes)}
    assert results['.pill[data-state="online"] [light]'] < 4.5
    assert results['.status-card[data-state="online"] .status-dot [light]'] < 3.0
    assert tokens["--status-healthy on --status-healthy-bg [light]"] < 4.5
    assert tokens["--status-healthy on --bg-card [light]"] < 3.0


def test_stream_line_mutation_breaks_the_selector_and_the_token_pair():
    """--stream-line is read both as a component rule (the online stream's
    solid line) and, independently, at the token level (section 9's list) --
    a fix at either layer could otherwise mask a regression at the other, so
    one mutation must break both."""
    mutated_text = TOKENS_TEXT.replace(
        "--stream-line: var(--c-graphite-650);", "--stream-line: var(--c-graphite-700);"
    )
    light, dark, _ = build_themes(mutated_text)
    themes = {"light": light, "dark": dark}
    results = {cid: ratio for cid, ratio, *_ in compute_public_checks(STYLE_CSS_TEXT, themes)}
    tokens = {cid: ratio for cid, ratio, *_ in compute_token_checks(themes)}
    assert results['.stream[data-state="online"] .stream-line::before [dark]'] < 3.0
    assert tokens["--stream-line on --bg-card [dark]"] < 3.0


def test_status_syncing_bg_mutation_breaks_the_pill_and_its_token_pair():
    """--status-syncing-bg is read by .pill[data-state="syncing"] (the
    must_fail the parametrised case above names) and, independently, by the
    --status-syncing on --status-syncing-bg token pair: one mutation of the
    tint must break both, so a fix at either layer cannot mask the other."""
    mutated_text = TOKENS_TEXT.replace(
        "--status-syncing-bg: var(--c-amber-50);", "--status-syncing-bg: var(--c-amber-925);"
    )
    light, dark, _ = build_themes(mutated_text)
    themes = {"light": light, "dark": dark}
    results = {cid: ratio for cid, ratio, *_ in compute_public_checks(STYLE_CSS_TEXT, themes)}
    tokens = {cid: ratio for cid, ratio, *_ in compute_token_checks(themes)}
    assert results['.pill[data-state="syncing"] [light]'] < 4.5
    assert tokens["--status-syncing on --status-syncing-bg [light]"] < 4.5


CSS_MUTATIONS = [
    (
        # A slip this palette does not make harmless: painting the online
        # sync-stream's line with the plain hairline --border-color instead
        # of the purpose-built --stream-line token (a very plausible "they're
        # both just greys" swap) fails the 3:1 indicator floor in both
        # themes. (--accent-primary, by contrast, clears the header and every
        # card and tinted surface on its own -- style.css's .nav-admin comment
        # -- so no swap to it is worth a mutation here.)
        "stream_line_online_reverts_to_the_plain_border_colour",
        STYLE_CSS,
        "STYLE",
        "height: 1.5px;\n    background: var(--stream-line);",
        "height: 1.5px;\n    background: var(--border-color);",
        '.stream[data-state="online"] .stream-line::before [light]',
    ),
    (
        "btn_primary_public_reverts_to_white_text",
        STYLE_CSS,
        "STYLE",
        "background: var(--accent-primary);\n    border-color: transparent;\n    color: var(--text-on-accent);",
        "background: var(--accent-primary);\n    border-color: transparent;\n    color: white;",
        ".btn-primary [dark]",
    ),
    (
        # A component-file edit, not a token edit: reverts just this one
        # rule's `color` back to --status-error, independent of
        # test_status_error_text_mutation_breaks_the_error_badge above (which
        # mutates the token instead). Both must be caught; a fix at either
        # layer could otherwise mask a regression at the other.
        "status_badge_error_reverts_color_to_status_error",
        ADMIN_CSS,
        "ADMIN",
        ".status-badge.error {\n    background: var(--status-error-bg);\n"
        "    /* status-error-text, not status-error: see tokens.css -- status-error\n"
        "       itself is 3.65-3.71:1 here (needs 4.5:1 as text). */\n"
        "    color: var(--status-error-text);",
        ".status-badge.error {\n    background: var(--status-error-bg);\n"
        "    /* status-error-text, not status-error: see tokens.css -- status-error\n"
        "       itself is 3.65-3.71:1 here (needs 4.5:1 as text). */\n"
        "    color: var(--status-error);",
        ".status-badge.error",
    ),
    (
        # Same shape as the mutation above, for the health-checks card's
        # "incomplete" badge -- with one difference from the other three
        # ADMIN_CSS mutations here: the "wrong" colour is a literal hex, not
        # var(--status-info). --status-info is not one of the 28 tokens
        # admin.css actually uses (tests/test_legacy_admin_tokens.py), so the
        # legacy block deliberately does not pin it, and it resolves through
        # the SHARED (public, Reflection-palette) dark theme instead, to
        # #7CB7F2 -- 5.44:1 here, so planting var(--status-info) would pass
        # for a reason unrelated to admin.css. #2D5A82 -- a plausible,
        # unremarkable medium blue -- is 1.59:1 against --status-info-bg
        # whatever the shared palette does, which is the point: this guard is
        # about admin.css choosing the right token, not about which colour
        # any particular token resolves to.
        "status_badge_health_incomplete_reverts_color_to_a_plausible_low_contrast_blue",
        ADMIN_CSS,
        "ADMIN",
        ".status-badge.health-incomplete {\n    background: var(--status-info-bg);\n"
        "    color: var(--status-info-text);",
        ".status-badge.health-incomplete {\n    background: var(--status-info-bg);\n"
        "    color: #2D5A82;",
        ".status-badge.health-incomplete",
    ),
    (
        # Same shape and same reason as the mutation above, for the
        # archive-inventory table's informational tag variant (Newest /
        # Latest-in-major / Pre-release).
        "status_badge_info_reverts_color_to_a_plausible_low_contrast_blue",
        ADMIN_CSS,
        "ADMIN",
        ".status-badge.info {\n    background: var(--status-info-bg);\n"
        "    color: var(--status-info-text);",
        ".status-badge.info {\n    background: var(--status-info-bg);\n" "    color: #2D5A82;",
        ".status-badge.info",
    ),
    (
        # Same shape as status_badge_error_reverts_color_to_status_error, for
        # the "At risk" pill: reverts its `color` back to --status-error,
        # which is 3.34:1 against this pill's own background (needs 4.5:1).
        "status_badge_at_risk_reverts_color_to_status_error",
        ADMIN_CSS,
        "ADMIN",
        ".status-badge.at-risk {\n    background: var(--status-error-bg);\n"
        "    color: var(--status-error-text);",
        ".status-badge.at-risk {\n    background: var(--status-error-bg);\n"
        "    color: var(--status-error);",
        ".status-badge.at-risk",
    ),
]


@pytest.mark.parametrize(
    "name,path,which,old,new,must_fail", CSS_MUTATIONS, ids=[m[0] for m in CSS_MUTATIONS]
)
def test_component_css_mutation_is_caught(name, path, which, old, new, must_fail):
    source = path.read_text(encoding="utf-8")
    assert source.count(old) == 1, (
        f"mutation {name!r} no longer matches {path.name} exactly once "
        f"(found {source.count(old)}). Update the mutation, do not delete it."
    )
    mutated = source.replace(old, new)

    if which == "STYLE":
        results = compute_public_checks(mutated, {"light": LIGHT, "dark": DARK})
    else:
        results = compute_admin_checks(mutated, ADMIN)

    failed_ids = {cid for cid, ratio, min_ratio, *_ in results if ratio < min_ratio}
    assert failed_ids, f"mutation {name!r} changed a live rule and nothing failed"
    assert must_fail in failed_ids, (
        f"mutation {name!r} was expected to fail {must_fail!r}, but the "
        f"failures were {sorted(failed_ids)}"
    )


def test_stream_line_online_css_mutation_also_fails_in_dark():
    """The CSS_MUTATIONS entry above only names the [light] id (must_fail
    takes one); --border-color is a near-invisible hairline in both themes,
    so this checks the other one explicitly rather than leaving it
    unproven."""
    source = STYLE_CSS.read_text(encoding="utf-8")
    old = "height: 1.5px;\n    background: var(--stream-line);"
    new = "height: 1.5px;\n    background: var(--border-color);"
    mutated = source.replace(old, new)
    results = {
        cid: ratio
        for cid, ratio, *_ in compute_public_checks(mutated, {"light": LIGHT, "dark": DARK})
    }
    assert results['.stream[data-state="online"] .stream-line::before [dark]'] < 3.0


# ===========================================================================
# DYNAMIC: real headless Chrome, real getComputedStyle, real :hover
# ===========================================================================
NODE = shutil.which("node")

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
]


def find_chrome():
    for candidate in CHROME_CANDIDATES:
        if "/" in candidate:
            if pathlib.Path(candidate).exists():
                return candidate
        else:
            found = shutil.which(candidate)
            if found:
                return found
    return None


CHROME = find_chrome()
requires_browser = pytest.mark.skipif(
    NODE is None or CHROME is None,
    reason=f"needs node and Chrome (node={bool(NODE)}, chrome={bool(CHROME)})",
)


def run_contrast_harness(docroot, admin_js_path):
    proc = subprocess.run(
        [NODE, str(HARNESS), str(docroot), str(admin_js_path), CHROME],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, (
        f"contrast harness failed (rc={proc.returncode})\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def measured():
    return run_contrast_harness(REPO_ROOT / "frontend" / "public", ADMIN_JS)


_RGB_RE = re.compile(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)")


def _rgb_string_to_hex(value):
    m = _RGB_RE.fullmatch(value.strip())
    assert m, f"not an rgb()/rgba() string: {value!r}"
    r, g, b = (round(float(m.group(i))) for i in (1, 2, 3))
    return "#%02X%02X%02X" % (r, g, b)


def _measured_ratio(measurement, page_bg_hex):
    """A harness measurement is {color, backgroundColor}, both rgb()/rgba()
    strings from getComputedStyle. backgroundColor keeps its alpha as
    declared (getComputedStyle never composites); this composites it over
    the resolved page background exactly the way header_ambient_background()
    does for the static half, so a translucent .header reads correctly.

    The foreground gets no such treatment: every probed text colour, dot and
    line is an opaque token, so a translucent one means the probe read an
    element the expected rule never painted -- an unmatched ::before reads
    rgba(0, 0, 0, 0), which dropping the alpha would score as black, a
    false 21:1 against a white card."""
    assert "error" not in measurement, f"harness could not measure this element: {measurement}"
    fg = _RGB_RE.fullmatch(measurement["color"].strip())
    assert fg, f"not an rgb()/rgba() string: {measurement['color']!r}"
    fg_alpha = float(fg.group(4)) if fg.group(4) is not None else 1.0
    assert fg_alpha >= 1.0, (
        f"the measured foreground {measurement['color']!r} is translucent (alpha "
        f"{fg_alpha:g}), so no contrast ratio can be read from it: the rule this "
        f"probe expects did not paint the element"
    )
    fg_hex = _rgb_string_to_hex(measurement["color"])
    m = _RGB_RE.fullmatch(measurement["backgroundColor"].strip())
    r, g, b = (round(float(m.group(i))) for i in (1, 2, 3))
    alpha = float(m.group(4)) if m.group(4) is not None else 1.0
    bg_hex = "#%02X%02X%02X" % (r, g, b)
    if alpha < 1.0:
        bg_hex = composite(bg_hex, alpha, page_bg_hex)
    return contrast_ratio(fg_hex, bg_hex)


# (probe_id, theme_label, min_ratio) -- a hand-maintained copy of
# PUBLIC_PROBES in contrast_harness.mjs, pinned in step by
# test_dynamic_probe_list_matches_the_harness below. Every id is measured in
# both themes; the four ids the /api/ stub cannot reach on its own (the
# neutral pill, and the online, syncing and neutral status-dot) are reached
# by the harness setting data-state itself, not by relying on which state the
# stub happens to produce -- see contrast_harness.mjs's docstring.
# fmt: off
DYNAMIC_PUBLIC_CHECKS = [
    ("body", "light", 4.5), ("body", "dark", 4.5),
    (".nav-link", "light", 4.5), (".nav-link", "dark", 4.5),
    (".nav-link:hover", "light", 4.5), (".nav-link:hover", "dark", 4.5),
    (".nav-admin", "light", 4.5), (".nav-admin", "dark", 4.5),
    (".stat-label", "light", 4.5), (".stat-label", "dark", 4.5),
    (".mirror-description", "light", 4.5), (".mirror-description", "dark", 4.5),
    (".access-label", "light", 4.5), (".access-label", "dark", 4.5),
    (".btn-primary", "light", 4.5), (".btn-primary", "dark", 4.5),
    (".btn-secondary:hover", "light", 4.5), (".btn-secondary:hover", "dark", 4.5),
    (".footer-content p", "light", 4.5), (".footer-content p", "dark", 4.5),
    (".footer-content a", "light", 4.5), (".footer-content a", "dark", 4.5),
    (".about-text a", "light", 4.5), (".about-text a", "dark", 4.5),
    (".footer-version", "light", 4.5), (".footer-version", "dark", 4.5),
    (".section-subtitle", "light", 4.5), (".section-subtitle", "dark", 4.5),
    (".toast", "light", 4.5), (".toast", "dark", 4.5),
    (".pill", "light", 4.5), (".pill", "dark", 4.5),
    ('.pill[data-state="online"]', "light", 4.5), ('.pill[data-state="online"]', "dark", 4.5),
    ('.pill[data-state="syncing"]', "light", 4.5), ('.pill[data-state="syncing"]', "dark", 4.5),
    ('.pill[data-state="error"]', "light", 4.5), ('.pill[data-state="error"]', "dark", 4.5),
    # UI indicators (WCAG 2.1 SC 1.4.11): 3:1, not 4.5:1.
    (".status-dot", "light", 3.0), (".status-dot", "dark", 3.0),
    ('.status-card[data-state="online"] .status-dot', "light", 3.0),
    ('.status-card[data-state="online"] .status-dot', "dark", 3.0),
    ('.status-card[data-state="syncing"] .status-dot', "light", 3.0),
    ('.status-card[data-state="syncing"] .status-dot', "dark", 3.0),
    ('.status-card[data-state="error"] .status-dot', "light", 3.0),
    ('.status-card[data-state="error"] .status-dot', "dark", 3.0),
    ('.stream[data-state="online"] .stream-line::before', "light", 3.0),
    ('.stream[data-state="online"] .stream-line::before', "dark", 3.0),
]
# fmt: on


@requires_browser
@pytest.mark.parametrize(
    "probe_id,theme_label,min_ratio",
    DYNAMIC_PUBLIC_CHECKS,
    ids=[f"{p} [{t}]" for p, t, _ in DYNAMIC_PUBLIC_CHECKS],
)
def test_public_site_contrast_in_a_real_browser(measured, probe_id, theme_label, min_ratio):
    page_bg = resolved_hex(LIGHT if theme_label == "light" else DARK, "--bg-primary")
    measurement = measured["public"][theme_label][probe_id]
    ratio = _measured_ratio(measurement, page_bg)
    assert ratio >= min_ratio, (
        f"{probe_id} [{theme_label}]: real browser measured {measurement}, "
        f"contrast {ratio:.2f}:1, needs >= {min_ratio}:1"
    )


# fmt: off
DYNAMIC_ADMIN_CHECKS = [
    ".login-subtitle", ".btn-primary", ".nav-item.active", ".user-avatar",
    ".user-role", ".nav-section-title", ".status-badge.disabled",
    ".status-badge.active", "th", ".u-text-muted", ".status-badge.error",
    ".status-badge.syncing", ".form-input::placeholder",
]
# fmt: on


@requires_browser
@pytest.mark.parametrize("probe_id", DYNAMIC_ADMIN_CHECKS)
def test_admin_panel_contrast_in_a_real_browser(measured, probe_id):
    page_bg = resolved_hex(ADMIN, "--bg-primary")
    measurement = measured["admin"][probe_id]
    ratio = _measured_ratio(measurement, page_bg)
    assert (
        ratio >= 4.5
    ), f"{probe_id}: real browser measured {measurement}, contrast {ratio:.2f}:1, needs >= 4.5:1"


@requires_browser
def test_dynamic_probe_list_matches_the_harness():
    """The two probe id lists above are a hand-maintained copy of
    PUBLIC_PROBES/ADMIN_PROBES in contrast_harness.mjs. Pins them together the
    same way test_admin_inline_styles.py pins its STYLEHEETS list against
    admin/index.html's actual <link> tags -- so a probe added to one and not
    the other fails loudly here instead of silently measuring nothing."""
    harness_source = HARNESS.read_text(encoding="utf-8")
    public_block = re.search(r"const PUBLIC_PROBES = \[(.*?)\n\];", harness_source, re.S)
    admin_block = re.search(r"const ADMIN_PROBES = \[(.*?)\n\];", harness_source, re.S)
    assert public_block and admin_block

    harness_public_ids = set(re.findall(r"id:\s*'([^']+)'", public_block.group(1)))
    harness_admin_ids = set(re.findall(r"id:\s*'([^']+)'", admin_block.group(1)))

    test_public_ids = {p for p, _, _ in DYNAMIC_PUBLIC_CHECKS}
    test_admin_ids = set(DYNAMIC_ADMIN_CHECKS) | {".form-input::placeholder"}

    assert test_public_ids == harness_public_ids, (
        f"public probe ids differ: test has {test_public_ids - harness_public_ids} extra, "
        f"harness has {harness_public_ids - test_public_ids} extra"
    )
    # The harness measures placeholder separately from ADMIN_PROBES (it needs
    # the two-argument getComputedStyle form); admin_block therefore will not
    # contain it, which is expected rather than a drift.
    assert test_admin_ids - {".form-input::placeholder"} == harness_admin_ids, (
        f"admin probe ids differ: test has "
        f"{(test_admin_ids - {'.form-input::placeholder'}) - harness_admin_ids} extra, "
        f"harness has {harness_admin_ids - test_admin_ids} extra"
    )


@requires_browser
def test_harness_detects_a_reintroduced_low_contrast_fill(tmp_path):
    """Negative control for the dynamic half, same shape as
    test_public_page_csp.py's test_harness_detects_a_reintroduced_inline_
    handler: plant the original bug in a copy of the real docroot, rerun the
    real harness, and require it to see a real browser render white on
    accent-primary rather than merely trusting the source diff.

    The bug lives in admin.css (.btn-primary's `color`), not admin.js -- the
    harness links the real admin.css into its fixture page, so the docroot
    served to it, not the admin.js path, is what needs mutating."""
    docroot = tmp_path / "public"
    shutil.copytree(REPO_ROOT / "frontend" / "public", docroot)
    admin_css_copy = docroot / "admin" / "css" / "admin.css"

    source = admin_css_copy.read_text(encoding="utf-8")
    old = "background: var(--accent-primary);\n    color: var(--text-on-accent);\n}"
    new = "background: var(--accent-primary);\n    color: white;\n}"
    assert (
        source.count(old) == 1
    ), "admin.css .btn-primary rule no longer matches; update the control"
    admin_css_copy.write_text(source.replace(old, new), encoding="utf-8")

    result = run_contrast_harness(docroot, ADMIN_JS)
    ratio = _measured_ratio(result["admin"][".btn-primary"], resolved_hex(ADMIN, "--bg-primary"))
    assert ratio < 4.5, (
        f"planting color: white back into admin.css's .btn-primary did not make a "
        f"real browser render a failing ratio (measured {ratio:.2f}:1) -- the "
        f"harness is not actually measuring what admin.css renders"
    )


@requires_browser
def test_harness_detects_a_low_contrast_pill_on_the_public_page(tmp_path):
    """The public half's negative control, the same shape as the admin one
    above: plant a low-contrast text colour on the online pill in a copy of
    the docroot's style.css, rerun the real harness, and require a real
    browser to render a failing ratio for that probe in both themes.
    #5E8A6E, a plausible muted green, is 3.45:1 on the light online tint and
    3.90:1 on the dark one."""
    docroot = tmp_path / "public"
    shutil.copytree(REPO_ROOT / "frontend" / "public", docroot)
    style_css_copy = docroot / "css" / "style.css"

    source = style_css_copy.read_text(encoding="utf-8")
    old = '.pill[data-state="online"] {\n    color: var(--status-healthy);'
    new = '.pill[data-state="online"] {\n    color: #5E8A6E;'
    assert (
        source.count(old) == 1
    ), "style.css's online pill rule no longer matches; update the control"
    style_css_copy.write_text(source.replace(old, new), encoding="utf-8")

    result = run_contrast_harness(docroot, ADMIN_JS)
    for theme_label, theme in (("light", LIGHT), ("dark", DARK)):
        measurement = result["public"][theme_label]['.pill[data-state="online"]']
        ratio = _measured_ratio(measurement, resolved_hex(theme, "--bg-primary"))
        assert ratio < 4.5, (
            f"planting color: #5E8A6E on style.css's online pill did not make a real "
            f"browser render a failing ratio in {theme_label} (measured {ratio:.2f}:1) "
            f"-- the harness is not actually measuring what style.css renders"
        )


@requires_browser
def test_harness_reports_an_uncaught_js_error_on_the_public_page(tmp_path):
    """Negative control for the DevTools exception guard added to
    contrast_harness.mjs: plant a synchronous throw where main.js's
    DOMContentLoaded handler runs, rerun the real harness against a copy of
    the docroot, and require it to fail loudly (not hang, not silently
    return a partial measurement) instead of merely trusting that
    Runtime.exceptionThrown is wired up correctly."""
    docroot = tmp_path / "public"
    shutil.copytree(REPO_ROOT / "frontend" / "public", docroot)
    main_js_copy = docroot / "js" / "main.js"

    source = main_js_copy.read_text(encoding="utf-8")
    old = "document.addEventListener('DOMContentLoaded', () => {\n    ThemeManager.init();"
    new = (
        "document.addEventListener('DOMContentLoaded', () => {\n"
        "    throw new Error('planted for test_harness_reports_an_uncaught_js_error_on_the_public_page');"
        "\n    ThemeManager.init();"
    )
    assert (
        source.count(old) == 1
    ), "main.js's DOMContentLoaded handler no longer matches; update the control"
    main_js_copy.write_text(source.replace(old, new), encoding="utf-8")

    proc = subprocess.run(
        [NODE, str(HARNESS), str(docroot), str(ADMIN_JS), CHROME],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode != 0, (
        "planting a synchronous throw in main.js's DOMContentLoaded handler "
        "did not make the harness fail -- it is not actually watching for "
        f"uncaught JS errors on the public page\nstdout:\n{proc.stdout}"
    )
    assert (
        "planted for test_harness_reports_an_uncaught_js_error_on_the_public_page" in proc.stderr
    ), f"the harness failed, but not with the planted error's message:\n{proc.stderr}"
```

- [ ] **Step 2 (developer): replace `tests/js/contrast_harness.mjs` in full.** The admin half is unchanged (`loadAdminRenderers`, `buildAdminFixtureHtml`, `renderWith`, `ADMIN_PROBES`, `measurePlaceholder` and the admin fixture page), and so are the command line, `<docroot> <admin-js-path> [chrome-binary]`, and the Chrome start and stop handling `tests/test_chrome_harness_start.py` checks. The public half:
- **`PUBLIC_PROBES`:** 24 probes, each read in both themes. Fifteen are measured as shipped: `body`, `.nav-link` and a real `:hover` on it, `.nav-admin`, `.stat-label`, `.mirror-description`, `.access-label`, `.btn-primary`, a real `.btn-secondary:hover`, the two footer pairs, `.footer-version`, `.about-text a`, `.section-subtitle` and `.toast`. Nine depend on `data-state`: four pill states, four status-dot states and the online stream line.
- **The stub and the states.** The `/api/` stub puts one mirror in each live state (FreeBSD active, NetBSD syncing, OpenBSD error) and fills `totals`, where it used to answer with two active mirrors, one syncing and empty totals. `measurePublicProbes()` waits until `main.js` has painted those states (`NATURAL_STATE_READY`), then measures. The wait includes `#freebsd-stream`'s own `data-state`, which the online line's `::before` keys off: the row's pill is painted by a separate call, so an online pill proves nothing about the row. The neutral pill and three of the four status-dot states, which no single response reaches, are set by `setDataState()` immediately before their own measurement, after that element's stub-driven reading.
- **The dark pass.** After the genuine click on `#themeToggle`, the harness reloads `/index.html`. `theme-init.js` reopens it dark from the saved choice, so the dark pass measures a fresh paint, never an override the light pass left behind.
- **Settled colours.** `launchChrome()` emulates `prefers-reduced-motion: reduce` alongside `prefers-color-scheme: light`, so `style.css`'s reduced-motion block turns every transition off and each reading is the final colour (see Notes).
- **Page errors fail the run.** The `CDP` class collects `Runtime.exceptionThrown` events and `console.error()` calls, and `checkForPageErrors()` fails on either, at the end of `main()` and on every poll inside `waitFor()`.
- **`measurePseudoBackground()` takes a `bgSelector`:** `.stream-line` declares no background, so the online line is measured against `.streams-inner`, two levels up.

```js
/**
 * Dynamic half of the WCAG contrast guard (tests/test_contrast.py).
 *
 * test_contrast.py's parametrized checks read style.css/admin.css/tokens.css
 * as text and do the WCAG relative-luminance arithmetic themselves. That
 * proves the declared values are compliant; it does not prove a real engine's
 * cascade resolves each element to the colour the text-only parser assumed --
 * the same gap test_public_page_csp.py's harness exists to close for the CSP
 * (reading finds an onclick attribute that looks like working code; it took a
 * real browser to show the policy killed it).
 *
 * This harness serves frontend/public over plain HTTP (no CSP -- that is a
 * different test's job), drives real headless Chrome over the DevTools
 * Protocol, and reads `getComputedStyle(...).color` /
 * `...backgroundColor` for the same elements test_contrast.py reasons about
 * statically. Two pages are covered:
 *
 *   - the public site, both themes, toggled with a genuine click on
 *     #themeToggle (not by setting the attribute from here) so the real
 *     ThemeManager code path is exercised;
 *   - a synthetic admin fixture: admin.js's own page-renderer functions
 *     (renderLoginPage, renderLayout, renderUsers, renderMirrors), loaded
 *     into a vm context exactly the way tests/js/escaping_harness.mjs does,
 *     called for their real HTML output, and dropped into a page that links
 *     the real admin.css/tokens.css/fonts.css. The admin SPA needs a live
 *     backend to reach these views by clicking through the app; calling the
 *     renderers directly gets the real markup without one, the same
 *     trade-off escaping_harness.mjs already makes. Unchanged by the public
 *     palette switch.
 *
 * :hover states (.nav-link:hover, .btn-secondary:hover) are reached with a
 * genuine Input.dispatchMouseEvent mousemove, not a CSS class toggle, so the
 * browser's own hit-testing decides whether the pseudo-class applies.
 *
 * The public site's mirror status is data-state-keyed (main.js writes one
 * attribute per element; nothing here reads a class -- spec section 5.2).
 * The /api/ stub below seeds one mirror of each live state (FreeBSD online,
 * NetBSD syncing, OpenBSD error), which the harness waits for by polling the
 * real, stub-driven attribute values -- proving the real end-to-end paint,
 * not just that some element exists. The neutral pill and three of the four
 * status-dot states are not reachable through any single stub response (the
 * overall card's data-state is one value at a time), so for those the
 * harness sets data-state on the element itself immediately before
 * measuring it, always AFTER that same element's naturally-stubbed
 * measurement has already been taken -- CSS keys purely off the attribute,
 * so this is exactly the cascade test_contrast.py's static half assumes,
 * just reached a different way. Every element visited this way is
 * re-measured fresh in each theme pass (see measurePublicProbes()), so a
 * light-pass override is never still sitting there when the dark pass reads
 * the same element "naturally".
 *
 * Colour/background-color changes on data-state (or class, or :hover) run
 * through a CSS transition (--transition-fast, 150ms) -- a probe taken
 * mid-fade once measured a pill's neutral colours moments after main.js had
 * already set it to "online". Rather than guess a settle delay per probe,
 * launchChrome() emulates `prefers-reduced-motion: reduce` for the whole
 * session: style.css's own reduced-motion block (`transition: none
 * !important` on `*, *::before, *::after`) then makes every one of these
 * changes apply instantly, so getComputedStyle -- which forces a synchronous
 * style recalculation regardless -- always reads the settled value with no
 * wait at all. The 250ms hover settle and 450ms theme-switch wait stay as
 * extra margin for the real event/click plumbing, not because a colour
 * fade needs time to finish any more.
 *
 * Also fails loudly, instead of silently reporting whatever partial
 * measurements it collected, if the public page raises an uncaught JS error
 * or an unhandled promise rejection at any point: a main.js write that
 * throws may break nothing a probe measures, so nothing else here would
 * notice it. Runtime.exceptionThrown reports both categories once
 * Runtime.enable is on; console.error() calls are also treated as failures.
 * waitFor() checks on every poll, and main() once more at the end; see
 * checkForPageErrors().
 *
 * No npm packages: node's built-in http/vm/WebSocket only, and whatever
 * Chrome is already installed. getComputedStyle always resolves to
 * rgb()/rgba() regardless of how the source declared the colour; the
 * WCAG maths (and any alpha compositing) is left to the Python side so there
 * is exactly one implementation of it across both the static and dynamic
 * checks.
 *
 * Usage:  node contrast_harness.mjs <docroot> <admin-js-path> [chrome-binary]
 * Output: JSON {"public": {...}, "admin": {...}} on stdout.
 */
import { createServer } from 'node:http';
import { readFile, mkdtemp, readFile as rf } from 'node:fs/promises';
import { existsSync, readFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { tmpdir } from 'node:os';
import path from 'node:path';
import vm from 'node:vm';

const DOCROOT = path.resolve(process.argv[2]);
const ADMIN_JS_PATH = path.resolve(process.argv[3]);
const CHROME = process.argv[4]
    || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

// How long Chrome gets to write DevToolsActivePort. It was a fixed 10 s until a
// cold start on a GitHub-hosted runner outlasted it and failed every
// real-browser test at setup (2026-09-25). CHROME_START_TIMEOUT_MS overrides
// it; tests/test_chrome_harness_start.py uses that to reach the failure fast.
const DEFAULT_CHROME_START_TIMEOUT_MS = 30_000;
const CHROME_START_TIMEOUT_MS = Number(process.env.CHROME_START_TIMEOUT_MS) > 0
    ? Number(process.env.CHROME_START_TIMEOUT_MS)
    : DEFAULT_CHROME_START_TIMEOUT_MS;

// The Chrome this run started, so a run that fails can stop it rather than
// leave it running into whatever runs next.
let chromeProcess = null;

const MIME = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.woff2': 'font/woff2',
    '.json': 'application/json'
};

// ---------------------------------------------------------------------------
// admin.js's real page renderers, loaded the way escaping_harness.mjs does.
// Unchanged by the public palette switch.
// ---------------------------------------------------------------------------
function loadAdminRenderers(sourcePath) {
    const source = readFileSync(sourcePath, 'utf8');
    const sandbox = {
        console,
        setTimeout: () => 0,
        setInterval: () => 0,
        clearTimeout: () => {},
        document: {
            addEventListener: () => {},
            getElementById: () => null,
            createElement: () => ({ style: {}, remove() {} })
        },
        window: { addEventListener() {}, history: { pushState() {} }, location: { hash: '' } },
        localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
        fetch: async () => { throw new Error('network disabled in harness'); }
    };
    sandbox.globalThis = sandbox;
    const epilogue = `
;({ html, renderLoginPage, renderLayout, renderUsers, renderMirrors, state, api });
`;
    return vm.runInNewContext(source + epilogue, sandbox, { filename: sourcePath });
}

/** Mocks api.get for the duration of one async renderer call, as
 * escaping_harness.mjs's renderWith does, then returns the rendered string. */
async function renderWith(mod, fn, payload) {
    mod.api.get = async () => payload;
    return String(await fn());
}

function buildAdminFixtureHtml(mod) {
    const login = String(mod.renderLoginPage());

    mod.state.user = { id: 1, username: 'alice-admin', role: 'admin' };
    mod.state.currentPage = 'dashboard';
    const layout = String(mod.renderLayout(mod.html`<p>fixture</p>`, 'Dashboard'));

    // Deferred: renderWith is async and buildAdminFixtureHtml is not, so the
    // two table renders are produced by the caller and passed in instead.
    return { login, layout };
}

// ---------------------------------------------------------------------------
// Static + synthetic-fixture server
// ---------------------------------------------------------------------------
function serve(fixtureHtml) {
    return new Promise((resolve) => {
        const server = createServer(async (req, res) => {
            const url = req.url.split('?')[0];
            if (url === '/__admin_fixture__.html') {
                res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
                return res.end(fixtureHtml);
            }
            let rel = decodeURIComponent(url);
            if (rel.endsWith('/')) rel += 'index.html';
            const file = path.join(DOCROOT, path.normalize(rel));
            if (!file.startsWith(DOCROOT) || !existsSync(file)) {
                if (rel.startsWith('/api/')) {
                    res.writeHead(200, { 'Content-Type': 'application/json' });
                    // One mirror in each live state -- online, syncing,
                    // error -- so MirrorStatus.load() (main.js) paints every
                    // pill/stream/status-dot variant the /api/ response can
                    // reach on its own; the neutral pill and the other three
                    // status-dot states are reached by the harness setting
                    // data-state directly, see measurePublicProbes(). Any
                    // /api/ path (including /health, for FooterVersion)
                    // gets this same body: it has no "version" field, so
                    // FooterVersion.load() leaves .footer-version empty,
                    // which this harness never asserts text content on.
                    return res.end(JSON.stringify({
                        mirrors: {
                            freebsd: {
                                status: 'active', size: '1.4 TB',
                                last_updated: new Date(Date.now() - 3 * 60_000).toISOString()
                            },
                            netbsd: {
                                status: 'syncing', size: '900 GB',
                                last_updated: new Date(Date.now() - 3 * 60_000).toISOString()
                            },
                            openbsd: { status: 'error' }
                        },
                        totals: { size: '4.2 TB', files: '604,618' }
                    }));
                }
                res.writeHead(404);
                return res.end('not found');
            }
            res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream' });
            res.end(await readFile(file));
        });
        server.listen(0, '127.0.0.1', () => resolve({ server, port: server.address().port }));
    });
}

// ---------------------------------------------------------------------------
// Minimal CDP client (identical shape to csp_click_harness.mjs's), plus a
// standing collector for two kinds of page misbehaviour that no probe
// otherwise notices: an uncaught JS error (or unhandled promise rejection --
// Chrome reports both through the same event once Runtime.enable is on) and
// a console.error() call. Both are queried on every waitFor() poll and once
// more at the end of main(), so a bug anywhere in the run -- not just during
// a specific probe -- is caught.
// ---------------------------------------------------------------------------
class CDP {
    constructor(ws) {
        this.ws = ws;
        this.id = 0;
        this.pending = new Map();
        this.jsErrors = [];
        this.consoleErrors = [];
        ws.addEventListener('message', (ev) => {
            const msg = JSON.parse(ev.data);
            if (msg.method === 'Runtime.exceptionThrown') {
                const d = msg.params.exceptionDetails;
                const detail = d.exception?.description || d.exception?.value || d.text || JSON.stringify(d);
                this.jsErrors.push(String(detail));
                return;
            }
            if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') {
                const parts = (msg.params.args || []).map((a) => a.value ?? a.description ?? String(a));
                this.consoleErrors.push(parts.join(' '));
                return;
            }
            if (msg.id && this.pending.has(msg.id)) {
                const { resolve, reject } = this.pending.get(msg.id);
                this.pending.delete(msg.id);
                msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
            }
        });
    }

    static connect(url) {
        return new Promise((resolve, reject) => {
            const ws = new WebSocket(url);
            ws.addEventListener('open', () => resolve(new CDP(ws)));
            ws.addEventListener('error', reject);
        });
    }

    send(method, params = {}, sessionId) {
        const id = ++this.id;
        this.ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
        return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
    }
}

/** Throws, naming every collected error, if the public page misbehaved at
 * any point in the run so far. Called on every waitFor() poll, so an error
 * that stops the page from ever reaching the awaited state is reported as
 * itself rather than as a timeout, and once more at the end of main(), for
 * anything raised after the last wait -- a whole-session check, not a
 * per-probe one. "Report it, don't hide it": the message carries the full
 * detail rather than just a count, since this is the only place any of it is
 * ever surfaced. */
function checkForPageErrors(cdp) {
    if (cdp.jsErrors.length === 0 && cdp.consoleErrors.length === 0) return;
    const lines = [
        ...cdp.jsErrors.map((e) => `uncaught JS error/rejection: ${e}`),
        ...cdp.consoleErrors.map((e) => `console.error(): ${e}`)
    ];
    throw new Error(
        `the public page misbehaved during this run (${cdp.jsErrors.length} JS error(s)/` +
        `rejection(s), ${cdp.consoleErrors.length} console.error() call(s)):\n` + lines.join('\n')
    );
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function launchChrome() {
    const userDataDir = await mkdtemp(path.join(tmpdir(), 'contrast-chrome-'));
    const chrome = spawn(CHROME, [
        '--headless=new',
        '--remote-debugging-port=0',
        `--user-data-dir=${userDataDir}`,
        '--no-first-run', '--no-default-browser-check',
        '--disable-gpu', '--disable-extensions', '--mute-audio'
    ], { stdio: ['ignore', 'ignore', 'pipe'] });
    chromeProcess = chrome;

// Chrome's stderr is piped, so SOMETHING has to read it.
//
// An unread pipe fills at roughly 64KB on Linux, and a process that fills it
// blocks on write() until someone drains it. A chatty headless Chrome -- which
// is what a loaded CI runner produces, between GPU, sandbox and font warnings
// -- can therefore block BEFORE it writes DevToolsActivePort, and the loop
// below then times out with "Chrome did not expose a DevTools endpoint" while
// Chrome sits alive and stuck. That is not a flake; it is this function
// holding the pipe shut.
//
// Draining also gives the failure something to say. The old error threw away
// everything Chrome had written, so a real crash and a slow start were
// indistinguishable in CI logs. Both harnesses had this; this one was simply
// the first to lose the race.
    let chromeStderr = '';
    chrome.stderr.setEncoding('utf8');
    chrome.stderr.on('data', (chunk) => {
        // Bounded: keep the tail. An unbounded buffer would just move the
        // memory problem here from the kernel's pipe.
        chromeStderr = (chromeStderr + chunk).slice(-8192);
    });

    let wsUrl = null;
    const deadline = Date.now() + CHROME_START_TIMEOUT_MS;
    while (!wsUrl && Date.now() < deadline) {
        await sleep(100);
        try {
            const portFile = path.join(userDataDir, 'DevToolsActivePort');
            const [p] = (await rf(portFile, 'utf8')).split('\n');
            const version = await (await fetch(`http://127.0.0.1:${p}/json/version`)).json();
            wsUrl = version.webSocketDebuggerUrl;
        } catch { /* not up yet */ }
    }
    if (!wsUrl) {
        throw new Error(
            `Chrome did not expose a DevTools endpoint within ${CHROME_START_TIMEOUT_MS / 1000}s.\n` +
            '--- chrome stderr (tail) ---\n' + (chromeStderr || '(nothing on stderr)')
        );
    }
    const cdp = await CDP.connect(wsUrl);
    const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
    await cdp.send('Emulation.setDeviceMetricsOverride', {
        width: 1400, height: 4200, deviceScaleFactor: 1, mobile: false
    }, sessionId);
    // The public site follows prefers-color-scheme until a visitor picks a
    // theme (js/theme-init.js), so main()'s first pass is only the light theme
    // if this Chrome says light. Pin it rather than inherit the host's default.
    // prefers-reduced-motion: reduce turns every colour/background transition
    // and every @keyframes animation off (style.css's own reduced-motion
    // block) for the rest of the session -- see the module docstring for why
    // that, not a per-probe sleep, is how this harness gets a settled colour
    // after a data-state change.
    await cdp.send('Emulation.setEmulatedMedia', {
        features: [
            { name: 'prefers-color-scheme', value: 'light' },
            { name: 'prefers-reduced-motion', value: 'reduce' }
        ]
    }, sessionId);
    await cdp.send('Page.enable', {}, sessionId);
    await cdp.send('Runtime.enable', {}, sessionId);
    return { chrome, cdp, sessionId };
}

/** Polls `expression` in the page until it is truthy. For state a page only
 * reaches after its load event: navigate() waits for load, not for the
 * fetches a DOMContentLoaded handler starts.
 *
 * Checks for a page error on every poll, not just once at the end of
 * main(): a synchronous throw early in main.js's DOMContentLoaded handler
 * stops the rest of that handler from ever running, so MirrorStatus.load()
 * is never called and the condition this function is waiting for is never
 * going to become true no matter how long it waits. Left unchecked here,
 * that surfaces as a generic "timed out" message five seconds later instead
 * of the real cause, which checkForPageErrors() already has on hand. */
async function waitFor(cdp, evaluate, expression, what, timeoutMs = 5000) {
    const deadline = Date.now() + timeoutMs;
    while (!(await evaluate(expression))) {
        checkForPageErrors(cdp);
        if (Date.now() > deadline) throw new Error(`timed out after ${timeoutMs}ms waiting for ${what}`);
        await sleep(50);
    }
}

async function navigate(cdp, sessionId, url) {
    const loaded = new Promise((resolve) => {
        const handler = (raw) => {
            const msg = JSON.parse(raw.data ?? '{}');
            if (msg.method === 'Page.loadEventFired') resolve();
        };
        cdp.ws.addEventListener('message', handler, { once: false });
    });
    await cdp.send('Page.navigate', { url }, sessionId);
    // Page.navigate resolves on commit, not load; a short poll is simpler and
    // more robust here than wiring up a one-shot event listener per call.
    for (let i = 0; i < 50; i++) {
        const { result } = await cdp.send('Runtime.evaluate', {
            expression: 'document.readyState', returnByValue: true
        }, sessionId);
        if (result.value === 'complete') break;
        await sleep(50);
    }
    await sleep(150);
}

function makeEvaluate(cdp, sessionId) {
    return async (expression) => {
        const r = await cdp.send('Runtime.evaluate', {
            expression, returnByValue: true, awaitPromise: true
        }, sessionId);
        if (r.exceptionDetails) throw new Error(r.exceptionDetails.text);
        return r.result.value;
    };
}

/** getComputedStyle(color) for `selector`, and (backgroundColor) for
 * `bgSelector` (a different element when the probed element's own background
 * is transparent and the ambient colour comes from an ancestor). If `hover`,
 * a real mouse is moved onto `selector` first. */
async function measure(cdp, sessionId, evaluate, { selector, bgSelector, hover }) {
    // Park the pointer off-page first so no previous probe's hover lingers.
    await cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 0, y: 0 }, sessionId);

    if (hover) {
        const box = await evaluate(`(() => {
            const el = document.querySelector(${JSON.stringify(selector)});
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
        })()`);
        if (!box) return { error: `no element for ${selector}` };
        await cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: box.x, y: box.y }, sessionId);
        // Under prefers-reduced-motion the hover colour/background applies
        // instantly (no transition to settle); this margin is for the real
        // input dispatch and hit-testing to land, not for a fade to finish.
        await sleep(250);
    }

    return evaluate(`(() => {
        const fg = document.querySelector(${JSON.stringify(selector)});
        const bg = document.querySelector(${JSON.stringify(bgSelector)});
        if (!fg || !bg) return { error: 'element(s) not found: ' +
            (!fg ? ${JSON.stringify(selector)} : ${JSON.stringify(bgSelector)}) };
        return {
            color: getComputedStyle(fg).color,
            backgroundColor: getComputedStyle(bg).backgroundColor
        };
    })()`);
}

/** Like measure(), but for an element whose own identity is a fill colour,
 * not text -- .status-dot has no content, so the pairing that matters is
 * backgroundColor-vs-backgroundColor, not colour-vs-backgroundColor. Reads
 * backgroundColor on both sides and still returns it under the `color` key,
 * so the {color, backgroundColor} shape test_contrast.py's _measured_ratio()
 * already expects needs no change to handle it. No hover: none of these
 * probes are hover states. */
async function measureDot(evaluate, { selector, bgSelector }) {
    return evaluate(`(() => {
        const fg = document.querySelector(${JSON.stringify(selector)});
        const bg = document.querySelector(${JSON.stringify(bgSelector)});
        if (!fg || !bg) return { error: 'element(s) not found: ' +
            (!fg ? ${JSON.stringify(selector)} : ${JSON.stringify(bgSelector)}) };
        return {
            color: getComputedStyle(fg).backgroundColor,
            backgroundColor: getComputedStyle(bg).backgroundColor
        };
    })()`);
}

/** For a ::before pseudo-element painted by a background token (the online
 * sync-stream's line) rather than a placeholder's text colour:
 * getComputedStyle(el, pseudo) is the only way to reach a pseudo-element's
 * computed style at all (it has no node querySelector can return). Unlike
 * the admin-only ::placeholder case below, the comparison background here is
 * a separate ancestor (.streams-inner), not the pseudo's own host element
 * (.stream-line itself declares no background), so bgSelector is always
 * required. */
async function measurePseudoBackground(evaluate, selector, pseudo, bgSelector) {
    return evaluate(`(() => {
        const el = document.querySelector(${JSON.stringify(selector)});
        const bg = document.querySelector(${JSON.stringify(bgSelector)});
        if (!el || !bg) return { error: 'element(s) not found: ' +
            (!el ? ${JSON.stringify(selector)} : ${JSON.stringify(bgSelector)}) };
        const style = getComputedStyle(el, ${JSON.stringify(pseudo)});
        const color = style && style.backgroundColor;
        if (!color) return { error: 'getComputedStyle(el, ' + ${JSON.stringify(pseudo)} +
            ') returned no backgroundColor in this Chrome build' };
        return { color, backgroundColor: getComputedStyle(bg).backgroundColor };
    })()`);
}

/** Sets data-state on `selector` directly, because CSS keys every pill,
 * status-dot and stream-line purely off that attribute (spec section 5.2) --
 * a probe does not need main.js to have painted a particular value, only for
 * the value to be there when getComputedStyle reads it. Always applied
 * immediately before the measurement it exists for; see PUBLIC_PROBES'
 * ordering comment for why that order matters. */
async function setDataState(evaluate, selector, value) {
    const ok = await evaluate(`(() => {
        const el = document.querySelector(${JSON.stringify(selector)});
        if (!el) return false;
        el.setAttribute('data-state', ${JSON.stringify(value)});
        return true;
    })()`);
    if (!ok) throw new Error(`setDataState: no element for ${selector}`);
}

/** Dispatches a PUBLIC_PROBES entry to whichever of measure()/measureDot()/
 * measurePseudoBackground() its shape calls for, applying setState first if
 * the probe has one, so main()'s probe loop can stay a plain `for` over one
 * list. */
async function measureProbe(cdp, sessionId, evaluate, probe) {
    if (probe.setState) await setDataState(evaluate, probe.setState.selector, probe.setState.value);
    if (probe.pseudo) return measurePseudoBackground(evaluate, probe.selector, probe.pseudo, probe.bgSelector);
    if (probe.dot) return measureDot(evaluate, probe);
    return measure(cdp, sessionId, evaluate, probe);
}

// ---------------------------------------------------------------------------
// Probe lists -- mirrors the selectors test_contrast.py reasons about
// statically. Keep the two in step; a mismatch is not caught automatically
// (test_dynamic_probe_list_matches_the_harness only compares the id sets,
// not this ordering comment).
//
// Order matters for four entries: '#freebsd-status' and '#overallStatus'
// are each probed twice, first at whatever /api/ naturally left them (the
// online pill and the error dot, both real end-to-end paints) and then
// again with data-state forced to a value the stub cannot reach on this
// element (the neutral pill, the online/syncing/neutral dot). The forced
// entries are listed after their element's natural one so the natural
// measurement is never accidentally taken from an already-overridden
// element -- see measurePublicProbes() in main(), which reruns this whole
// list once per theme after a fresh natural paint.
// ---------------------------------------------------------------------------
const PUBLIC_PROBES = [
    { id: 'body', selector: 'body', bgSelector: 'body' },
    { id: '.nav-link', selector: '.nav-link', bgSelector: '.header' },
    { id: '.nav-link:hover', selector: '.nav-link', bgSelector: '.nav-link', hover: true },
    { id: '.nav-admin', selector: '.nav-admin', bgSelector: '.header' },
    { id: '.stat-label', selector: '.stat-label', bgSelector: 'body' },
    { id: '.mirror-description', selector: '.mirror-description', bgSelector: '.mirror-card' },
    { id: '.access-label', selector: '.access-label', bgSelector: '.access-row' },
    { id: '.btn-primary', selector: '.mirror-actions .btn-primary', bgSelector: '.mirror-actions .btn-primary' },
    { id: '.btn-secondary:hover', selector: '.mirror-actions .btn-secondary', bgSelector: '.mirror-actions .btn-secondary', hover: true },
    { id: '.footer-content p', selector: '.footer-content p:not(.footer-version)', bgSelector: '.footer' },
    { id: '.footer-content a', selector: '.footer-content p a', bgSelector: '.footer' },
    { id: '.about-text a', selector: '.about-text a', bgSelector: 'body' },
    { id: '.footer-version', selector: '.footer-version', bgSelector: '.footer' },
    { id: '.section-subtitle', selector: '.section-subtitle', bgSelector: 'body' },
    { id: '.toast', selector: '#toast', bgSelector: '#toast' },
    // Pills, natural first (the stub's own online/syncing/error), then the
    // neutral base rule forced onto the same element the online pill just
    // used.
    { id: '.pill[data-state="online"]', selector: '#freebsd-status', bgSelector: '#freebsd-status' },
    { id: '.pill[data-state="syncing"]', selector: '#netbsd-status', bgSelector: '#netbsd-status' },
    { id: '.pill[data-state="error"]', selector: '#openbsd-status', bgSelector: '#openbsd-status' },
    { id: '.pill', selector: '#freebsd-status', bgSelector: '#freebsd-status', setState: { selector: '#freebsd-status', value: 'disabled' } },
    // The one sync-stream state with a bare var() background (see
    // test_contrast.py's PUBLIC_PAIRS comment on the syncing/error lines'
    // gradients); natural, from the same stub entry as the pill above.
    { id: '.stream[data-state="online"] .stream-line::before', selector: '#freebsd-stream .stream-line', pseudo: '::before', bgSelector: '.streams-inner' },
    // The overall card's dot: natural (error, since any mirror erroring
    // wins main.js's priority order), then the other three states forced
    // onto the same element in turn.
    { id: '.status-card[data-state="error"] .status-dot', selector: '#overallStatus .status-dot', bgSelector: '#overallStatus', dot: true },
    { id: '.status-card[data-state="online"] .status-dot', selector: '#overallStatus .status-dot', bgSelector: '#overallStatus', dot: true, setState: { selector: '#overallStatus', value: 'online' } },
    { id: '.status-card[data-state="syncing"] .status-dot', selector: '#overallStatus .status-dot', bgSelector: '#overallStatus', dot: true, setState: { selector: '#overallStatus', value: 'syncing' } },
    { id: '.status-dot', selector: '#overallStatus .status-dot', bgSelector: '#overallStatus', dot: true, setState: { selector: '#overallStatus', value: 'disabled' } }
];

const ADMIN_PROBES = [
    { id: '.login-subtitle', selector: '#login-fixture .login-subtitle', bgSelector: '#login-fixture .login-card' },
    { id: '.btn-primary', selector: '#login-fixture .btn-primary', bgSelector: '#login-fixture .btn-primary' },
    { id: '.nav-item.active', selector: '#layout-fixture .nav-item.active', bgSelector: '#layout-fixture .nav-item.active' },
    { id: '.user-avatar', selector: '#layout-fixture .user-avatar', bgSelector: '#layout-fixture .user-avatar' },
    { id: '.user-role', selector: '#layout-fixture .user-role', bgSelector: '#layout-fixture .user-info' },
    { id: '.nav-section-title', selector: '#layout-fixture .nav-section-title', bgSelector: '#layout-fixture .sidebar' },
    { id: '.status-badge.disabled', selector: '#users-fixture .status-badge.disabled', bgSelector: '#users-fixture .status-badge.disabled' },
    { id: '.status-badge.active', selector: '#users-fixture .status-badge.active', bgSelector: '#users-fixture .status-badge.active' },
    { id: 'th', selector: '#users-fixture th', bgSelector: '#users-fixture th' },
    { id: '.u-text-muted', selector: '#mirrors-fixture .u-text-muted', bgSelector: '#mirrors-fixture .card' },
    { id: '.status-badge.error', selector: '#mirrors-fixture .status-badge.error', bgSelector: '#mirrors-fixture .status-badge.error' },
    { id: '.status-badge.syncing', selector: '#mirrors-fixture .status-badge.syncing', bgSelector: '#mirrors-fixture .status-badge.syncing' }
];

/** ::placeholder is a pseudo-element, not reachable through the plain
 * (element, property) probe shape above. Chrome supports the two-argument
 * form of getComputedStyle for it; measured separately for that reason, with
 * a clearly-labelled error (rather than a silent skip) if a given Chrome
 * build does not support it -- test_contrast.py treats a missing/errored
 * measurement as "not dynamically confirmed" and falls back to its static
 * coverage of the same pairing, but it needs to see why. Unchanged by the
 * public palette switch. */
async function measurePlaceholder(evaluate, selector, bgSelector) {
    return evaluate(`(() => {
        const input = document.querySelector(${JSON.stringify(selector)});
        const bg = document.querySelector(${JSON.stringify(bgSelector)});
        if (!input || !bg) return { error: 'element(s) not found' };
        const style = getComputedStyle(input, '::placeholder');
        const color = style && style.color;
        if (!color) return { error: 'getComputedStyle(el, "::placeholder") returned no colour in this Chrome build' };
        return { color, backgroundColor: getComputedStyle(bg).backgroundColor };
    })()`);
}

// The condition the /api/ stub's own response satisfies once main.js has
// painted it for real: every element PUBLIC_PROBES measures "naturally"
// (not via setState) at its expected, stub-driven value. Waited for once per
// theme pass, before that pass's probe loop runs -- see measurePublicProbes().
// That includes #freebsd-stream, whose own data-state is what the online
// stream line's ::before keys off: the row's pill is painted separately, so
// a pill reading "online" says nothing about the row.
const NATURAL_STATE_READY = `(
    document.getElementById('freebsd-status')?.getAttribute('data-state') === 'online' &&
    document.getElementById('netbsd-status')?.getAttribute('data-state') === 'syncing' &&
    document.getElementById('openbsd-status')?.getAttribute('data-state') === 'error' &&
    document.getElementById('freebsd-stream')?.getAttribute('data-state') === 'online' &&
    document.getElementById('overallStatus')?.getAttribute('data-state') === 'error'
)`;

/** Waits for a fresh, real, stub-driven paint (proving main.js's own wiring,
 * not just that an element exists), then measures every PUBLIC_PROBES entry
 * in order. Called once per theme; main() ensures each call sees a page
 * that has just (re)run its DOMContentLoaded handler against the stub, so a
 * setState override from a previous call is never still sitting on an
 * element this one reads "naturally". */
async function measurePublicProbes(cdp, sessionId, evaluate) {
    await waitFor(cdp, evaluate, NATURAL_STATE_READY, 'the stubbed mirror statuses to paint');
    const out = {};
    for (const probe of PUBLIC_PROBES) {
        out[probe.id] = await measureProbe(cdp, sessionId, evaluate, probe);
    }
    return out;
}

async function main() {
    const mod = loadAdminRenderers(ADMIN_JS_PATH);
    const { login, layout } = buildAdminFixtureHtml(mod);
    const usersHtml = await renderWith(mod, mod.renderUsers, [
        { id: 1, username: 'rita', email: 'rita@example.test', role: 'readonly', is_active: false, last_login: null },
        { id: 2, username: 'alice', email: 'alice@example.test', role: 'admin', is_active: true, last_login: null }
    ]);
    const mirrorsHtml = await renderWith(mod, mod.renderMirrors, [
        {
            id: 1, name: 'OpenBSD', url_path: '/OpenBSD/', status: 'error',
            total_size_human: '1 GB', last_sync_completed: null
        },
        {
            id: 2, name: 'NetBSD', url_path: '/NetBSD/', status: 'syncing',
            total_size_human: '2 GB', last_sync_completed: null
        }
    ]);

    const fixtureHtml = `<!DOCTYPE html>
<html data-theme="dark" data-surface="admin">
<head>
<meta charset="UTF-8">
<link rel="stylesheet" href="/css/fonts.css">
<link rel="stylesheet" href="/css/tokens.css">
<link rel="stylesheet" href="/admin/css/admin.css">
</head>
<body>
<div id="login-fixture">${login}</div>
<div id="layout-fixture">${layout}</div>
<div id="users-fixture">${usersHtml}</div>
<div id="mirrors-fixture">${mirrorsHtml}</div>
</body>
</html>`;

    const { server, port } = await serve(fixtureHtml);
    const origin = `http://127.0.0.1:${port}`;
    const { chrome, cdp, sessionId } = await launchChrome();
    const evaluate = makeEvaluate(cdp, sessionId);

    const out = { public: { light: {}, dark: {} }, admin: {} };

    await navigate(cdp, sessionId, `${origin}/index.html`);
    const initialTheme = await evaluate('document.documentElement.getAttribute("data-theme")');
    if (initialTheme !== 'light') {
        throw new Error(`index.html did not open in the light theme (got ${initialTheme})`);
    }
    out.public.light = await measurePublicProbes(cdp, sessionId, evaluate);

    // A genuine click on the real toggle button, not setAttribute from here,
    // so ThemeManager's own click handler and its localStorage write are
    // what actually flips the theme.
    const toggleBox = await evaluate(`(() => {
        const b = document.getElementById('themeToggle');
        const r = b.getBoundingClientRect();
        return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
    })()`);
    for (const type of ['mousePressed', 'mouseReleased']) {
        await cdp.send('Input.dispatchMouseEvent', {
            type, x: toggleBox.x, y: toggleBox.y, button: 'left', clickCount: 1
        }, sessionId);
    }
    // Extra margin for the click/attribute plumbing to land; the colour
    // fade itself needs none of this under prefers-reduced-motion (see the
    // module docstring).
    await sleep(450);
    let theme = await evaluate('document.documentElement.getAttribute("data-theme")');
    if (theme !== 'dark') throw new Error(`clicking #themeToggle did not set data-theme=dark (got ${theme})`);

    // Reload so the dynamic probes read a second, fresh, real paint rather
    // than reusing whatever the light pass's setState calls left behind on
    // shared elements (#freebsd-status, #overallStatus). ThemeManager just
    // saved "dark" to localStorage; theme-init.js reads that choice and
    // applies dark before first paint, so this reopens dark without
    // clicking the toggle again -- the click above already proved that path.
    await navigate(cdp, sessionId, `${origin}/index.html`);
    theme = await evaluate('document.documentElement.getAttribute("data-theme")');
    if (theme !== 'dark') {
        throw new Error(`reloading did not keep data-theme=dark (got ${theme}); did the toggle's localStorage write fail?`);
    }
    out.public.dark = await measurePublicProbes(cdp, sessionId, evaluate);

    await navigate(cdp, sessionId, `${origin}/__admin_fixture__.html`);
    for (const probe of ADMIN_PROBES) {
        out.admin[probe.id] = await measure(cdp, sessionId, evaluate, probe);
    }
    out.admin['.form-input::placeholder'] = await measurePlaceholder(
        evaluate, '#login-fixture .form-input', '#login-fixture .form-input'
    );

    checkForPageErrors(cdp);

    process.stdout.write(JSON.stringify(out, null, 2) + '\n');
    chrome.kill();
    server.close();
    process.exit(0);
}

main().catch((err) => {
    process.stderr.write(String(err && err.stack ? err.stack : err) + '\n');
    chromeProcess?.kill();
    process.exit(1);
});
```

- [ ] **Step 3 (developer): create `tests/test_public_page_structure.py`.** It parses `index.html` with `html.parser.HTMLParser` into a small tree queried by `find_all`/`find_one`, so a query like "the `.pill` inside `#freebsd-stream`" asks what a browser would. It pins:
- one `h1`, and one `h2` per section;
- the header hooks: `#themeToggle`'s `.theme-icon`, starting at `data-icon="moon"` with no text, and `.nav-admin` without `.nav-link`;
- the four nav anchors and the sections they point at;
- the hero's copy, its three stats starting at an em dash, and its two actions;
- each stream row's starting `data-state="unknown"`, its one `.pill` and its `[data-hostname]`, and the streams `<section>` named "Sync streams" by its own `aria-label`, which makes it a region landmark, with no name on the generic `.streams-inner` inside it;
- each mirror card's status, size and sync hooks, and exactly two `.mirror-actions` controls, including a raw-text check that the three copy buttons' opening tags are byte-identical (`tests/test_public_page_csp.py`'s negative control depends on that literal);
- `#overallStatus`'s starting state and copy;
- the `#access` rows, their hosts and their buttons' `aria-label`s;
- the literal `class="footer-version"`, and `#toast`;
- for spec section 9: the mark definition, the header mark and the hero art are `aria-hidden`, and every `.icon` span is `aria-hidden` and names a file that exists under `frontend/public/img/icons/`, through its `icon-*` class or, for the theme toggle, its `data-icon`;
- the copy, arrow and theme icons are all in use: a floor, so a new icon elsewhere on the page does not fail it.

```python
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
```

- [ ] **Step 4 (developer): create `tests/test_reduced_motion.py`.** It covers `style.css` and `error.css`; `admin.css` waits for the admin console's own redesign (spec section 10). Three checks:
- no sheet uses the `all` catch-all in a transition or animation;
- a sheet with any motion, meaning a `@keyframes` rule or any `transition` or `animation` other than `none`, carries a `@media (prefers-reduced-motion: reduce)` block that sets `animation: none !important` and `transition: none !important` on `*, *::before, *::after` (`test_a_sheet_with_any_motion_turns_it_off_under_reduced_motion`). Spec section 4.4 turns "every animation and transition" off, so a colour fade counts: `error.css`'s theme fade needs the block as much as `style.css`'s sheen does. The block is found by counting braces, so the sheet's indentation never matters;
- colour transitions settle inside the contrast harness's windows (spec section 4.4): a `color`, `background`, `background-color`, `border-color`, `fill`, `stroke` or `outline-color` transition runs on `var(--transition-fast)` or `var(--transition-base)`, never longer (`test_colour_transitions_settle_within_the_harness_windows`). Transforms and shadows may take `--transition-lift`; the harness never measures them.

Five self-tests check the helpers, including the duration check's handling of commas inside `cubic-bezier()`, and pin the list of sheets to the two files (`test_the_checks_cover_style_css_and_error_css`).

```python
"""Reduced motion and motion timing (spec sections 4.4 and 9's "Motion").

Every animation and transition the public site declares must be switched off
under `prefers-reduced-motion: reduce`, and no stylesheet may use the `all`
catch-all in a transition/animation shorthand -- naming every property a rule
actually animates is what lets one `*, *::before, *::after { transition: none
!important }` turn all of them off at once, and lets a reviewer see, from the
rule itself, exactly what moves.

Scope: style.css (spec sections 4.2-4.4) and error.css. A sheet needs its own
`@media (prefers-reduced-motion: reduce)` block as soon as it declares any
motion at all: a `@keyframes` rule, or any `transition` or `animation` other
than `none`. A colour fade counts -- spec section 4.4 turns "every animation
and transition" off -- so error.css's theme fade needs the block as much as
style.css's sheen does.

Colour changes must also settle inside the contrast harness's sampling
windows (spec section 4.4): a `color`, `background`, `background-color`,
`border-color`, `fill`, `stroke` or `outline-color` transition runs on
`--transition-fast` or `--transition-base`, never longer. Transforms and
shadows may take longer; the harness never measures them.

admin.css still has two real animations (`spin`, `slideIn`) and is
deliberately out of scope until the admin console's own redesign (spec
section 10: "PR 3 extends it to admin.css, whose spin and slideIn animations
stay until then").
"""
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
STYLE_CSS = REPO_ROOT / "frontend" / "public" / "css" / "style.css"
ERROR_CSS = REPO_ROOT / "frontend" / "public" / "css" / "error.css"
STYLESHEETS = [STYLE_CSS, ERROR_CSS]

# `all` as a whole word inside a transition/animation shorthand's value list
# -- catches `transition: all 150ms ease` and `transition: color .2s, all
# .2s` alike, not a property that merely contains "all" as a substring.
TRANSITION_ALL_RE = re.compile(r"(?:transition|animation)\s*:\s*(?:[^;]*,\s*)?all\b")
KEYFRAMES_RE = re.compile(r"@keyframes\b")
# A transition or animation shorthand and its value; the negative look-behind
# keeps `-webkit-transition` and `animation-name` out.
MOTION_RE = re.compile(r"(?<![\w-])(?:transition|animation)\s*:\s*([^;]+);")
TRANSITION_RE = re.compile(r"(?<![\w-])transition\s*:\s*([^;]+);")
REDUCED_MOTION_OPEN_RE = re.compile(r"@media\s*\(\s*prefers-reduced-motion\s*:\s*reduce\s*\)\s*\{")
# Scoped to the block find_reduced_motion_block() already extracted, so this
# never needs to worry about a brace nested inside some other rule.
ALL_SELECTOR_RE = re.compile(r"\*\s*,\s*\*::before\s*,\s*\*::after\s*\{([^}]*)\}")

# Spec section 4.4, "Settle within the harness windows": the contrast harness
# samples 250ms after a hover and 450ms after a theme switch.
COLOUR_PROPERTIES = {
    "color",
    "background",
    "background-color",
    "border-color",
    "fill",
    "stroke",
    "outline-color",
}
SETTLING_DURATIONS = {"var(--transition-fast)", "var(--transition-base)"}


def _strip_comments(css_text):
    return re.sub(r"/\*.*?\*/", "", css_text, flags=re.S)


def _at_rule_body(css_text, open_brace_end):
    """The body of an at-rule whose opening `{` ends at `open_brace_end`,
    found by counting nested braces rather than assuming any indentation
    convention (contrast this with the column-0 trick
    test_error_pages_inline_styles.py uses for a similarly-shaped tokens.css
    lookup -- that sheet's formatting makes the shortcut safe; writing the
    general case once here means style.css's own nested rules can never
    trip it up)."""
    depth, i = 1, open_brace_end
    while depth > 0 and i < len(css_text):
        if css_text[i] == "{":
            depth += 1
        elif css_text[i] == "}":
            depth -= 1
        i += 1
    return css_text[open_brace_end : i - 1]


def find_reduced_motion_block(css_text):
    m = REDUCED_MOTION_OPEN_RE.search(css_text)
    if not m:
        return None
    return _at_rule_body(css_text, m.end())


def needs_a_reduced_motion_override(css_text):
    """True if this sheet declares any @keyframes, or any transition or
    animation other than `none` -- the reduced-motion block's own
    `transition: none !important` never counts as motion."""
    css = _strip_comments(css_text)
    if KEYFRAMES_RE.search(css):
        return True
    return any(not m.group(1).strip().startswith("none") for m in MOTION_RE.finditer(css))


def _split_top_level_commas(value):
    """A transition list's items: split on the commas between them, not on
    the ones inside a function such as cubic-bezier(.2, .8, .2, 1)."""
    items, depth, start = [], 0, 0
    for i, ch in enumerate(value):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            items.append(value[start:i])
            start = i + 1
    items.append(value[start:])
    return [" ".join(item.split()) for item in items]


def slow_colour_transitions(css_text):
    """Every transition item that animates one of COLOUR_PROPERTIES on
    anything but --transition-fast or --transition-base, as written."""
    slow = []
    for m in TRANSITION_RE.finditer(_strip_comments(css_text)):
        for item in _split_top_level_commas(m.group(1)):
            prop, _, timing = item.partition(" ")
            if prop in COLOUR_PROPERTIES and timing not in SETTLING_DURATIONS:
                slow.append(item)
    return slow


def test_no_stylesheet_uses_the_all_catch_all():
    offenders = []
    for sheet in STYLESHEETS:
        text = sheet.read_text(encoding="utf-8")
        offenders += [f"{sheet.name}: {m.group(0)!r}" for m in TRANSITION_ALL_RE.finditer(text)]
    assert offenders == [], (
        "transition/animation: all found; name every property explicitly so the "
        "reduced-motion block below can turn each one off individually:\n  "
        + "\n  ".join(offenders)
    )


def test_a_sheet_with_any_motion_turns_it_off_under_reduced_motion():
    for sheet in STYLESHEETS:
        text = sheet.read_text(encoding="utf-8")
        if not needs_a_reduced_motion_override(text):
            continue
        body = find_reduced_motion_block(text)
        assert body is not None, (
            f"{sheet.name} declares a transition, an animation or @keyframes "
            f"but has no @media (prefers-reduced-motion: reduce) block"
        )
        rule = ALL_SELECTOR_RE.search(body)
        assert rule, f"{sheet.name}'s reduced-motion block has no `*, *::before, *::after` rule"
        declarations = rule.group(1)
        assert re.search(
            r"animation\s*:\s*none\s*!important", declarations
        ), f"{sheet.name}'s reduced-motion rule does not set animation: none !important"
        assert re.search(
            r"transition\s*:\s*none\s*!important", declarations
        ), f"{sheet.name}'s reduced-motion rule does not set transition: none !important"


def test_colour_transitions_settle_within_the_harness_windows():
    slow = []
    for sheet in STYLESHEETS:
        text = sheet.read_text(encoding="utf-8")
        slow += [f"{sheet.name}: {item}" for item in slow_colour_transitions(text)]
    assert slow == [], (
        "a colour, background or border transition runs on something other than "
        "--transition-fast or --transition-base, so the contrast harness could "
        "sample it mid-fade:\n  " + "\n  ".join(slow)
    )


def test_the_predicate_can_actually_require_the_block():
    """A guard that has only ever been seen skipping is indistinguishable
    from one that can never fire."""
    assert needs_a_reduced_motion_override("@keyframes spin { to { transform: rotate(1turn); } }")
    assert needs_a_reduced_motion_override(".x { transition: all 150ms ease; }")
    assert needs_a_reduced_motion_override(".x { transition: color 150ms ease; }")
    assert needs_a_reduced_motion_override(".x { animation: spin 1s linear infinite; }")
    assert not needs_a_reduced_motion_override(".x { transition: none; }")
    assert not needs_a_reduced_motion_override(".x { color: red; }")


def test_the_all_catch_all_regex_does_not_fire_on_a_property_merely_containing_all():
    """`all` must be a whole word: a property list like `transition: background-
    color .2s` must never be mistaken for the banned catch-all merely because
    "all" appears inside "background-color"."""
    assert not TRANSITION_ALL_RE.search(".x { transition: background-color .2s ease; }")


def test_the_reduced_motion_block_extractor_can_actually_find_one():
    sample = (
        "@media (prefers-reduced-motion: reduce) {\n"
        "    html { scroll-behavior: auto; }\n\n"
        "    *, *::before, *::after {\n"
        "        animation: none !important;\n"
        "        transition: none !important;\n"
        "    }\n"
        "}\n"
        ".after-the-block { color: red; }\n"
    )
    body = find_reduced_motion_block(sample)
    assert body is not None
    assert "after-the-block" not in body, "the extractor read past the block's own closing brace"
    rule = ALL_SELECTOR_RE.search(body)
    assert rule and "animation: none !important" in rule.group(1)


def test_the_duration_check_can_actually_find_a_slow_colour_transition():
    """Same reasoning as the predicate's self-test above, for
    slow_colour_transitions(): a transform may take --transition-lift, a
    colour may not, and a comma inside cubic-bezier() does not split an
    item."""
    assert slow_colour_transitions(
        ".x { transition: color var(--transition-lift), transform var(--transition-lift); }"
    ) == ["color var(--transition-lift)"]
    assert slow_colour_transitions(
        ".x { transition: background-color 400ms cubic-bezier(.2, .8, .2, 1); }"
    ) == ["background-color 400ms cubic-bezier(.2, .8, .2, 1)"]
    assert not slow_colour_transitions(
        ".x { transition: transform var(--transition-lift), color var(--transition-fast); }"
    )
    assert not slow_colour_transitions("* { transition: none !important; }")


def test_the_checks_cover_style_css_and_error_css():
    """The checks above loop over STYLESHEETS; this pins that list to both
    files, so a typo in it cannot silently shrink every check to one."""
    assert {p.name for p in STYLESHEETS} == {"style.css", "error.css"}
```

- [ ] **Step 5 (developer): create `tests/test_focus_ring.py`.** Spec section 9's focus ring: `style.css` has one unconditional `:focus-visible` rule, with `outline: 2px solid var(--accent-primary)` and `outline-offset: 2px`. Top-level rules are found by counting braces, so a rule inside a `@media` block, which applies only some of the time, does not count. The ring's colour needs no pair of its own: `--accent-primary` on the surface and the ground are already `TOKEN_PAIRS` rows. `STYLESHEETS` holds only `style.css` for now; Task 7 adds `error.css` with the error pages' own focus rule.

```python
"""The keyboard focus ring (spec section 9, "Focus"): every interactive
element shows a 2px accent outline at a 2px offset.

One unconditional `:focus-visible` rule per stylesheet draws the ring for
every element at once, so this pins that rule rather than each control. Its
colour is --accent-primary, whose contrast against the surface and the ground
tests/test_contrast.py's token pairs pin in both themes.

Covers style.css. error.css joins STYLESHEETS once the error pages carry a
focus rule of their own (spec section 5.3).
"""
import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
STYLE_CSS = REPO_ROOT / "frontend" / "public" / "css" / "style.css"
STYLESHEETS = [STYLE_CSS]


def top_level_rules(css_text):
    """(selector, declarations) for every rule outside an at-rule, found by
    counting braces: a rule inside a @media block applies only some of the
    time, so it never counts as the page-wide ring."""
    css = re.sub(r"/\*.*?\*/", "", css_text, flags=re.S)
    rules, depth, start, selector, body_start = [], 0, 0, "", 0
    for i, ch in enumerate(css):
        if ch == "{":
            if depth == 0:
                selector, body_start = css[start:i].strip(), i + 1
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                if not selector.startswith("@"):
                    rules.append((selector, css[body_start:i]))
                start = i + 1
    return rules


def declared(body, prop):
    m = re.search(rf"(?<![\w-]){re.escape(prop)}\s*:\s*([^;]+);", body)
    return " ".join(m.group(1).split()) if m else None


@pytest.mark.parametrize("sheet", STYLESHEETS, ids=[p.name for p in STYLESHEETS])
def test_focus_visible_draws_a_2px_accent_outline_at_a_2px_offset(sheet):
    rules = [
        body
        for selector, body in top_level_rules(sheet.read_text(encoding="utf-8"))
        if selector == ":focus-visible"
    ]
    assert (
        len(rules) == 1
    ), f"{sheet.name} has {len(rules)} top-level :focus-visible rules, expected 1"
    assert declared(rules[0], "outline") == "2px solid var(--accent-primary)"
    assert declared(rules[0], "outline-offset") == "2px"
```

- [ ] **Step 6 (developer): run the tests, and watch them fail.** The four design files are still Task 3's; the five test files are Steps 1 to 5's.

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_reduced_motion.py tests/test_public_page_structure.py tests/test_focus_ring.py; echo "rc=$?"`

Expected: `rc=1`, `19 failed, 10 passed, 4 warnings`. Each failure is the one its test describes:
- `test_no_stylesheet_uses_the_all_catch_all`: five `style.css: 'transition: all'` matches, one each in Task 3's `.theme-toggle`, `.stat-card`, `.mirror-card`, `.btn` and `.toast`.
- `test_a_sheet_with_any_motion_turns_it_off_under_reduced_motion`: `style.css declares a transition, an animation or @keyframes but has no @media (prefers-reduced-motion: reduce) block`. Task 3's file has `@keyframes pulse` and `pulse-ring`, and no such block. Task 3's `error.css` would fail next: its colour fade counts as motion, and it has no block either.
- `test_exactly_one_h1`: the page's one `<h1>`, the hero title, reads `BSD Mirror`; `Every BSD, mirrored.` does not exist yet.
- `test_every_section_has_an_h2_section_title`: `expected exactly one match for {'tag': 'section', 'id': 'access'}, found 0`. There is no `#access` yet.
- `test_nav_admin_is_not_a_nav_link`: the admin link is `class="nav-link nav-admin"`.
- `test_nav_anchors_and_their_sections_agree`: the nav links are `#mirrors`, `#status`, `#about` and `/admin`, where the test expects `#mirrors`, `#status`, `#access` and `#about`.
- `test_hero_copy` and `test_hero_ctas`: there is no `.hero-eyebrow` and no `.hero-ctas`.
- `test_hero_stats_start_at_an_em_dash`: `#statSize` reads `Loading...`, not an em dash.
- `test_stream_rows_start_unknown_and_reading_checking`: there is no `#freebsd-stream`, nor any stream row.
- `test_the_sync_streams_section_is_a_named_region`: `expected exactly one match for {'tag': 'section', 'class_': 'streams'}, found 0`. There is no streams section yet.
- `test_mirror_cards_have_the_hooks_main_js_writes_to`: `#freebsd-status` is `class="mirror-status"`, not a `.pill`.
- `test_mirror_actions_hold_exactly_a_browse_link_then_a_copy_button`: the copy button reads `Copy rsync URL`, not `rsync URL`.
- `test_overall_status_card_starts_unknown_and_checking`: `#overallStatus` has no `data-state` at all.
- `test_access_rows_have_labelled_copy_buttons`: there is no `#access`.
- `test_mark_definition_and_header_mark_are_aria_hidden` and `test_hero_art_is_aria_hidden`: there is no `svg.visually-hidden` and no `.hero-art`, because there is no inline `<symbol id="mark">` or hero art yet.
- `test_at_least_the_expected_icon_variants_are_present`: `no .icon span uses ['icon-arrow-right', 'icon-copy']`. Only `theme-icon` (Task 3's span) exists.
- `test_focus_visible_draws_a_2px_accent_outline_at_a_2px_offset[style.css]`: `style.css has 0 top-level :focus-visible rules, expected 1`. Task 3's file has no focus rule at all.

The other 10 pass already: the four structure tests Task 3's markup satisfies (the theme toggle's span, the copy buttons' byte-identical opening tags, the footer and toast hooks, and the icon-span check, whose one span names `moon.svg`), `test_colour_transitions_settle_within_the_harness_windows`, since Task 3's colour transitions already run on `--transition-fast` or `--transition-base`, and the five self-tests.

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_contrast.py; echo "rc=$?"`

Expected: `rc=2`, and a single collection error, `ERROR tests/test_contrast.py - AssertionError: no exact '.wordmark' rule found`. `compute_public_checks` builds `PUBLIC_CHECKS` at import, and `.wordmark` is the first selector in `PUBLIC_PAIRS` that Task 3's `style.css` lacks, so pytest stops at `Interrupted: 1 error during collection` and none of the module's tests runs.

- [ ] **Step 7 (web-designer): replace `frontend/public/css/tokens.css` in full.** Five blocks, in order:
- the primitives, named by hue family and step (`--c-graphite-*`, `--c-red-*`, `--c-green-*`, `--c-amber-*`, `--c-blue-*`, `--c-purple-*`, and `--c-white`), each a 6-digit uppercase hex from spec section 4.1, plus the hero gradient's two ends per theme;
- the invariants: fonts, radii, transitions and layout;
- the light `:root` block;
- `[data-theme="dark"]`;
- `[data-surface="admin"]`: Task 1's two groups, the admin surface's non-colour tokens and LEGACY ADMIN's 19 colours as raw hex, unchanged apart from dropping `--accent-secondary`.

`--accent-secondary`, `--accent-gradient` and the other retired tokens are gone from every layer; `--bg-tertiary`, `--status-error-text` and `--status-info-text` survive only in the legacy admin group. The header names the one custom property declared outside this file, `style.css`'s `--mark-glyph-fill` on `.hero-mark`, which carries the hero gradient across the `<use>` boundary (see Notes). The two group comments are Task 1's, word for word, and read true before the palette switch and after it: the non-colour group keeps a change to the invariants from reaching admin, and the LEGACY ADMIN group's raw hex keeps admin off the shared primitives.

```css
/* BSD Mirror - Design Tokens */
/* "Reflection" palette: chrome greys, one accent ("daemon red"), a light and
   a dark theme. Single source of truth for colour, type, spacing, radius and
   motion. Consumed by both surfaces via <link>, ahead of the page stylesheet:

     public site   frontend/public/index.html        -> tokens.css, then css/style.css
     admin panel   frontend/public/admin/index.html  -> tokens.css, then admin/css/admin.css

   Do not declare custom properties in style.css or admin.css. Add them here.
   The one exception is a property that carries a value across a <use>
   boundary, where no selector reaches: style.css sets --mark-glyph-fill on
   .hero-mark for the inline mark's glyph, per element, not as a token.
   See docs/design/2026-09-25-reflection-redesign.md, sections 4.1 and 7.

   ---------------------------------------------------------------------------
   Layers
   ---------------------------------------------------------------------------
   1. PRIMITIVES (--c-*)   Raw palette, named by hue family and step. No
                           meaning attached, never used directly by a
                           component rule -- semantic tokens reference these.
   2. INVARIANTS           Semantics that do not change with theme or surface.
   3. LIGHT THEME          Semantics for :root, i.e. the public site's default.
   4. DARK THEME           Semantics for [data-theme="dark"], set by main.js.
   5. ADMIN SURFACE        Frozen ahead of the admin console's own redesign
                           (spec section 6). See the note at that block.

   ---------------------------------------------------------------------------
   How a surface picks its values
   ---------------------------------------------------------------------------
   Theme and surface are independent axes, both expressed on <html>:

     <html>                                    public site, light
     <html data-theme="dark">                  public site, dark  (main.js)
     <html data-theme="dark" data-surface="admin">   admin panel

   The admin panel has no theme toggle yet (spec section 6.2 adds one); it is
   dark-only and carries data-theme="dark" statically so it consumes the same
   dark theme the public site does, instead of maintaining a second copy.

   Layers 3-5 all have specificity (0,1,0), so ordering in this file decides:
   dark overrides light, admin overrides dark. Keep them in this order.

   ---------------------------------------------------------------------------
   Layer 5, frozen ahead of the admin redesign
   ---------------------------------------------------------------------------
   The admin console must keep looking exactly as it does today until its own
   redesign (spec section 6), even though this file's primitives and light/dark
   semantics changed under it. [data-surface="admin"] pins the values admin.css
   reads directly, as literals, so none of them can resolve through the shared
   layers above. That admin redesign deletes the LEGACY ADMIN group and folds
   admin's colours back into the shared light/dark layers, checked in both
   themes; see spec section 7.
*/

/* ===========================================================================
   1. PRIMITIVES
   Raw palette values. Reference these from the semantic layers only.
   =========================================================================== */

:root {
    /* Neutrals ("chrome grey"): one ramp, lightest to darkest, spanning both
       themes' surfaces, text and hairlines. */
    --c-white: #FFFFFF;
    --c-graphite-50: #F4F5F7;
    --c-graphite-75: #EDEFF3;
    --c-graphite-100: #ECEEF1;
    --c-graphite-200: #D9DDE3;
    --c-graphite-400: #A2A9B6;
    --c-graphite-450: #8D95A3;
    --c-graphite-500: #8A919D;
    --c-graphite-550: #7F8794;
    --c-graphite-600: #5F6673;
    --c-graphite-650: #5C6370;
    --c-graphite-700: #4E5563;
    --c-graphite-750: #4A515E;
    --c-graphite-850: #252932;
    --c-graphite-900: #161920;
    --c-graphite-925: #101217;
    --c-graphite-950: #0C0E12;
    --c-graphite-975: #07080B;

    /* Accent ("daemon red") and its ink. */
    --c-red-50: #FBE4E2;
    --c-red-300: #FF7B72;
    --c-red-400: #FF5A60;
    --c-red-600: #C8232C;
    --c-red-650: #B42318;
    --c-red-900: #2D1415;
    --c-red-975: #16060A;

    /* Status hues: online (green), syncing (amber), info (blue), incomplete
       (purple). Each carries a light-theme text step, a dark-theme text
       step, and a tint for each theme's pill/card background. */
    --c-green-50: #E3F4EA;
    --c-green-400: #5AD69A;
    --c-green-700: #1B7A48;
    --c-green-925: #0F2A1D;

    --c-amber-50: #FBF0DA;
    --c-amber-400: #F2C14E;
    --c-amber-800: #8C5A00;
    --c-amber-925: #2A2210;

    --c-blue-50: #E3EEFA;
    --c-blue-400: #7CB7F2;
    --c-blue-700: #1F5FA8;
    --c-blue-925: #10233A;

    --c-purple-50: #EFE7F8;
    --c-purple-400: #C4A3F0;
    --c-purple-700: #6B3FA0;
    --c-purple-925: #241A33;
}

/* ===========================================================================
   2. INVARIANTS
   Same on every theme and every surface.
   =========================================================================== */

:root {
    /* Typography. Unbounded, Instrument Sans and JetBrains Mono are
       self-hosted and declared in css/fonts.css, which every page links
       ahead of this file. The fallback chains cover the swap period before
       the webfont arrives, and any glyph outside the shipped unicode-ranges. */
    --font-display: 'Unbounded', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    --font-sans: 'Instrument Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    --font-mono: 'JetBrains Mono', 'Fira Code', monospace;

    /* Motion. --transition-lift is new, for the card/button/icon lifts in
       spec section 4.4; --transition-fast and --transition-base cover colour,
       background and border transitions as before. */
    --transition-fast: 150ms ease;
    --transition-base: 250ms ease;
    --transition-lift: 400ms cubic-bezier(.2, .8, .2, 1);

    /* Radius. */
    --radius-sm: 8px;
    --radius-md: 10px;
    --radius-lg: 12px;
    --radius-xl: 14px;
    --radius-full: 999px;

    /* Layout. --sidebar-width is unchanged until the admin console's own
       redesign (spec section 6), which retunes it to 188px. */
    --container-max: 1180px;
    --header-height: 64px;
    --sidebar-width: 260px;
}

/* ===========================================================================
   3. LIGHT THEME  (public site default)
   =========================================================================== */

:root {
    --bg-primary: var(--c-graphite-100);
    --bg-secondary: var(--c-graphite-50);
    --bg-card: var(--c-white);

    --text-primary: var(--c-graphite-950);
    --text-secondary: var(--c-graphite-700);
    --text-muted: var(--c-graphite-700);

    --border-color: var(--c-graphite-200);
    /* Control border, at least 3:1 against --bg-card (WCAG 2.1 SC 1.4.11).
       --border-color above is a hairline only (1.36:1 here) -- fine for a
       card edge or divider, not for a boundary that is the only way to see a
       control. Not yet consumed on the public site (no form fields); the
       admin console's own redesign (spec section 6.1) is its first user. */
    --border-strong: var(--c-graphite-500);

    --accent-primary: var(--c-red-600);
    --text-on-accent: var(--c-white);

    --status-healthy: var(--c-green-700);
    --status-syncing: var(--c-amber-800);
    --status-error: var(--c-red-650);
    --status-info: var(--c-blue-700);
    --status-incomplete: var(--c-purple-700);

    --status-healthy-bg: var(--c-green-50);
    --status-syncing-bg: var(--c-amber-50);
    --status-error-bg: var(--c-red-50);
    --status-info-bg: var(--c-blue-50);
    --status-incomplete-bg: var(--c-purple-50);

    /* Idle sync-stream line, at least 3:1 against --bg-card. */
    --stream-line: var(--c-graphite-550);

    /* Tinted with the ink rather than pure black, so shadows stay cool
       rather than muddy. Alpha variants are written literally: there is no
       build step to derive them, and color-mix() would change the resolved
       value. */
    --shadow-card: 0 1px 2px rgba(12, 14, 18, .06), 0 14px 30px -18px rgba(12, 14, 18, .35);
    --shadow-card-hover: 0 1px 2px rgba(12, 14, 18, .06), 0 14px 38px -18px rgba(12, 14, 18, .35);

    /* The hero mark's sheen sweep (spec section 4.4) and the modal scrim. */
    --sheen: rgba(255, 255, 255, .85);
    --sheen-blend: soft-light;
    --scrim: rgba(12, 14, 18, .45);

    /* The hero mark's vertical gradient fill (spec section 4.5). */
    --mark-gradient-from: var(--c-graphite-950);
    --mark-gradient-to: var(--c-graphite-750);
}

/* ===========================================================================
   4. DARK THEME
   Applied by main.js on the public site; static on the admin panel.
   =========================================================================== */

[data-theme="dark"] {
    --bg-primary: var(--c-graphite-975);
    --bg-secondary: var(--c-graphite-900);
    --bg-card: var(--c-graphite-925);

    --text-primary: var(--c-graphite-75);
    --text-secondary: var(--c-graphite-400);
    --text-muted: var(--c-graphite-400);

    --border-color: var(--c-graphite-850);
    --border-strong: var(--c-graphite-600);

    --accent-primary: var(--c-red-400);
    --text-on-accent: var(--c-red-975);

    --status-healthy: var(--c-green-400);
    --status-syncing: var(--c-amber-400);
    --status-error: var(--c-red-300);
    --status-info: var(--c-blue-400);
    --status-incomplete: var(--c-purple-400);

    --status-healthy-bg: var(--c-green-925);
    --status-syncing-bg: var(--c-amber-925);
    --status-error-bg: var(--c-red-900);
    --status-info-bg: var(--c-blue-925);
    --status-incomplete-bg: var(--c-purple-925);

    --stream-line: var(--c-graphite-650);

    --shadow-card: 0 1px 2px rgba(0, 0, 0, .45), 0 16px 34px -18px rgba(0, 0, 0, .85);
    --shadow-card-hover: 0 1px 2px rgba(0, 0, 0, .45), 0 16px 38px -18px rgba(0, 0, 0, .85);

    --sheen: rgba(255, 255, 255, .16);
    --sheen-blend: screen;
    --scrim: rgba(0, 0, 0, .6);

    --mark-gradient-from: var(--c-graphite-75);
    --mark-gradient-to: var(--c-graphite-450);
}

/* ===========================================================================
   5. ADMIN SURFACE
   Frozen ahead of the admin console's own redesign (spec section 6), which
   deletes the LEGACY ADMIN group below and folds admin's colours back into
   the shared light/dark layers above (spec section 7).
   =========================================================================== */

[data-surface="admin"] {
    /* ===== ADMIN SURFACE: NON-COLOUR TOKENS =====
       admin.css's own values for the non-colour tokens, declared here so a
       change to the INVARIANTS layer above never reaches the admin console.
       The admin console's own redesign revisits these; until then they keep
       today's numbers (spec section 7: "the admin layer then holds only
       non-colour tokens"). */
    --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    --font-mono: 'JetBrains Mono', 'Fira Code', monospace;
    --header-height: 64px;
    --radius-sm: 6px;
    --radius-md: 10px;
    --radius-lg: 14px;
    --sidebar-width: 260px;
    --transition-fast: 150ms ease;
    --transition-base: 300ms ease;

    /* ===== LEGACY ADMIN =====
       Pins every colour token admin.css consumes at its value today, as a
       literal rather than a var() reference, so none of them can resolve
       through a shared layer when this file's primitives and light/dark
       semantics change under it. Raw hex, so these do not follow the shared
       primitives, which the Reflection palette replaces. The admin console's
       own redesign deletes this whole group.
       Verified against admin.css by tests/test_legacy_admin_tokens.py. */
    --accent-primary: #F48C06;
    --bg-card: #1A1A2E;
    --bg-primary: #0D0D1A;
    --bg-secondary: #1A1A2E;
    --bg-tertiary: #2A2A40;
    --border-color: #2A2A40;
    --status-error: #EF4444;
    --status-error-bg: #462B3B;
    --status-error-text: #F87171;
    --status-healthy: #22C55E;
    --status-healthy-bg: #1C3C38;
    --status-info-bg: #203B56;
    --status-info-text: #38BDF8;
    --status-syncing: #F59E0B;
    --status-syncing-bg: #463427;
    --text-muted: #9696AC;
    --text-on-accent: #0D0D1A;
    --text-primary: #E8E8F0;
    --text-secondary: #A0A0B8;
}
```

- [ ] **Step 8 (web-designer): replace `frontend/public/css/style.css` in full.** In sections: reset and base, icons (masks), the mark, header, buttons, section rhythm, hero, sync streams, pills, mirror cards, status and access, about, section headings, footer, toast, focus, reduced motion, and responsive. No `transition: all` anywhere, and every colour transition runs on `--transition-fast`. Every colour a contrast check reads is a bare `var(--token)` in `color:` or `background:`, on a top-level rule whose selector appears once. The exceptions are the header's two `rgba()` backgrounds, which the header check composites, and the syncing and error stream lines, whose gradients the token-level pairs cover instead. Also:
- **Layout (spec section 4.3):** each of the six sections carries a 72px gap below itself, 48px under 640px, so a heading starts right at its section's top edge. `html { scroll-padding-top: calc(var(--header-height) + 16px); }` then lands every anchor's heading 16px below the sticky header, instead of under it. Nothing inside a section adds to its gap: the About text's last child drops its bottom margin, so About ends the same 72px above the footer. Access's title, the one with no subtitle, keeps the 36px a subtitle leaves above a section's content (`.access .section-title`), instead of its own 10px.
- **Type (spec section 4.2):** the overall status card's title is set in the display face, Unbounded 600 at 18px, like `.mirror-name`; `.mono` is JetBrains Mono 500.
- **The sheen:** `.hero-sheen` rests at `130% 0`, `sheen-sweep`'s first keyframe, off the art's left edge, so a frame without the animation never shows a slice of it. The reduced-motion block also sets `.hero-sheen { display: none; }`.
- **Pills** keep their content width in a stream row's fixed grid column (`justify-self: start`).

```css
/* BSD Mirror - Public Site Stylesheet ("Reflection") */
/* Design tokens live in css/tokens.css, linked ahead of this file in index.html.
   Do not declare custom properties here, with one exception: a property that
   carries a value across a <use> boundary into the inline mark, where no
   selector reaches (.hero-mark's --mark-glyph-fill, below).
   Web fonts are self-hosted in css/fonts.css, also linked ahead of this file.
   See docs/design/2026-09-25-reflection-redesign.md, sections 4.2-4.4, 4.7,
   4.8 and 5.1 for the system this file implements. */

/* ===========================================================================
   Reset & base
   =========================================================================== */
*, *::before, *::after {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

/* A nav anchor scrolls its section's heading to 16px below the sticky
   header, instead of under it. */
html {
    scroll-behavior: smooth;
    scroll-padding-top: calc(var(--header-height) + 16px);
}

body {
    font-family: var(--font-sans);
    background-color: var(--bg-primary);
    color: var(--text-primary);
    font-size: 15px;
    line-height: 1.5;
    min-height: 100vh;
    transition: background-color var(--transition-fast), color var(--transition-fast);
}

h1, h2, h3, h4 {
    line-height: 1.15;
}

/* Visually hidden but still reachable by <use href="#mark">: an SVG holding
   only <symbol>/<defs> content must stay in the render tree (unlike
   display:none, which some engines exclude referenced content from), so this
   is the standard clip-based hidden pattern rather than display:none. */
.visually-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    margin: -1px;
    padding: 0;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
}

.container {
    max-width: var(--container-max);
    margin: 0 auto;
    padding: 0 20px;
}

.mono {
    font-family: var(--font-mono);
    font-weight: 500;
    font-variant-numeric: tabular-nums;
}

/* ===========================================================================
   Icons -- CSS masks on spans (spec section 4.7), so no <img>/<svg> is
   needed for a glyph that must take the surrounding text colour.
   =========================================================================== */
.icon {
    display: inline-block;
    flex-shrink: 0;
    width: 16px;
    height: 16px;
    background-color: currentColor;
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
}

.icon-copy {
    -webkit-mask-image: url(/img/icons/copy.svg);
    mask-image: url(/img/icons/copy.svg);
}

.icon-arrow-right {
    -webkit-mask-image: url(/img/icons/arrow-right.svg);
    mask-image: url(/img/icons/arrow-right.svg);
}

/* The theme toggle's icon swaps mask image by data-icon (set by main.js's
   ThemeManager.apply), never a glyph or a class rewrite. */
.theme-icon[data-icon="moon"] {
    -webkit-mask-image: url(/img/icons/moon.svg);
    mask-image: url(/img/icons/moon.svg);
}

.theme-icon[data-icon="sun"] {
    -webkit-mask-image: url(/img/icons/sun.svg);
    mask-image: url(/img/icons/sun.svg);
}

/* ===========================================================================
   The b|d mark (spec section 4.5). One inline <symbol id="mark"> in
   index.html holds the regular geometry; every <svg class="mark"><use
   href="#mark"></use></svg> instance renders it. Colours are classes, not
   presentation attributes, so they follow the theme.
   =========================================================================== */
.mark {
    display: block;
    width: 28px;
    height: 28px;
}

/* --mark-glyph-fill is unset by default, so .mark-glyph falls back to the
   flat --text-primary. A <use> instance's shadow content does not match a
   compound selector rooted outside it (a .hero-mark .mark-glyph rule matches
   nothing), but a custom property set on the <use>'s own ancestor DOES
   inherit across that boundary -- the same mechanism that lets currentColor
   reach into a referenced <symbol>. .hero-mark below sets the one property;
   every plain <svg class="mark"> (the header/nav instance) never does, so it
   keeps the flat fill. */
.mark-glyph {
    fill: var(--mark-glyph-fill, var(--text-primary));
}

.mark-axis {
    fill: var(--accent-primary);
}

/* The hero's two mark instances (the standing glyph and its reflection) use
   the vertical gradient instead of the flat --text-primary. The axis keeps
   --accent-primary either way -- only .mark-glyph reads this property. */
.hero-mark {
    --mark-glyph-fill: url(#hero-mark-gradient);
}

.mark-gradient-from {
    stop-color: var(--mark-gradient-from);
}

.mark-gradient-to {
    stop-color: var(--mark-gradient-to);
}

/* ===========================================================================
   Header
   =========================================================================== */
.header {
    position: sticky;
    top: 0;
    z-index: 100;
    background: rgba(236, 238, 241, 0.85);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--border-color);
    height: var(--header-height);
    display: flex;
    align-items: center;
}

[data-theme="dark"] .header {
    background: rgba(7, 8, 11, 0.85);
}

.header-inner {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    width: 100%;
}

.brand {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-shrink: 0;
}

.wordmark {
    font-family: var(--font-display);
    font-size: 17px;
    font-weight: 600;
    letter-spacing: -0.02em;
    color: var(--text-primary);
}

.nav {
    display: flex;
    align-items: center;
    gap: 2px;
    margin: 0 auto;
}

.nav-link {
    color: var(--text-secondary);
    text-decoration: none;
    font-weight: 500;
    font-size: 14px;
    white-space: nowrap;
    padding: 8px 14px;
    border-radius: var(--radius-sm);
    transition: color var(--transition-fast), background-color var(--transition-fast);
}

.nav-link:hover {
    color: var(--text-primary);
    background-color: var(--bg-secondary);
}

.nav-actions {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-shrink: 0;
}

.nav-admin {
    /* accent-primary reaches AA as normal-size text on the header's ambient
       backdrop in both themes (4.84:1 light, 6.56:1 dark) -- see
       docs/design/2026-09-25-reflection-redesign.md section 4.1: this
       palette's accent was chosen to clear every pair in section 9 without
       the secondary-accent workaround the previous palette needed here. */
    color: var(--accent-primary);
    text-decoration: none;
    font-weight: 600;
    font-size: 14px;
    padding: 8px 10px;
}

.icon-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 34px;
    height: 34px;
    border-radius: var(--radius-md);
    border: 1px solid var(--border-color);
    background: var(--bg-card);
    color: var(--text-primary);
    cursor: pointer;
    transition: background-color var(--transition-fast), border-color var(--transition-fast);
}

.icon-btn:hover {
    background: var(--bg-secondary);
    border-color: var(--border-strong);
}

.theme-toggle .theme-icon {
    transition: transform var(--transition-lift);
}

.theme-toggle:hover .theme-icon {
    transform: rotate(-18deg);
}

/* ===========================================================================
   Buttons
   =========================================================================== */
.btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 11px 18px;
    border-radius: var(--radius-md);
    border: 1px solid var(--border-color);
    background: var(--bg-card);
    color: var(--text-primary);
    font-weight: 600;
    font-size: 14px;
    font-family: var(--font-sans);
    white-space: nowrap;
    text-decoration: none;
    cursor: pointer;
    transition: transform var(--transition-base), box-shadow var(--transition-base);
}

.btn:hover {
    transform: translateY(-1px);
    box-shadow: var(--shadow-card);
}

.btn-primary {
    background: var(--accent-primary);
    border-color: transparent;
    color: var(--text-on-accent);
}

.btn-secondary {
    background: var(--bg-card);
    color: var(--text-primary);
    border-color: var(--border-color);
}

.btn-secondary:hover {
    background: var(--bg-secondary);
    border-color: var(--border-strong);
    color: var(--text-primary);
}

/* Compact sizing for buttons inside a mirror card, applied by context so the
   copy button's own opening tag can stay exactly
   `<button class="btn btn-secondary" data-copy-rsync="...">`
   (tests/test_public_page_csp.py's negative control matches that literal
   string). */
.mirror-actions .btn {
    padding: 8px 13px;
    font-size: 13px;
    border-radius: var(--radius-sm);
}

/* ===========================================================================
   Section rhythm (spec section 4.3): 72px between sections, 48px under
   640px (see Responsive). Each section carries the gap below itself, so a
   nav anchor lands on the section's heading, not on padding above it.
   =========================================================================== */
.hero,
.streams,
.mirrors,
.status,
.access,
.about {
    padding-bottom: 72px;
}

/* ===========================================================================
   Hero
   =========================================================================== */
.hero {
    padding-top: 56px;
}

.hero-inner {
    display: grid;
    grid-template-columns: 1fr;
    gap: 32px;
    align-items: center;
}

@media (min-width: 980px) {
    .hero-inner {
        grid-template-columns: minmax(0, 1.2fr) minmax(0, .8fr);
        gap: 40px;
    }
}

.hero-eyebrow {
    font-family: var(--font-mono);
    font-size: 13px;
    font-weight: 500;
    letter-spacing: 0.03em;
    color: var(--text-secondary);
    margin-bottom: 14px;
}

.hero-title {
    font-family: var(--font-display);
    font-weight: 700;
    font-size: clamp(32px, 7.4vw, 70px);
    line-height: 0.98;
    letter-spacing: -0.04em;
    margin-bottom: 18px;
}

.hero-lede {
    max-width: 46ch;
    color: var(--text-secondary);
    font-size: 15.5px;
    margin-bottom: 28px;
}

.hero-stats {
    display: flex;
    flex-wrap: wrap;
    gap: 16px 30px;
    margin-bottom: 28px;
}

.stat {
    display: flex;
    flex-direction: column;
    gap: 2px;
}

.stat-value {
    font-family: var(--font-sans);
    font-weight: 600;
    font-size: 22px;
    letter-spacing: -0.01em;
    color: var(--text-primary);
}

.stat-label {
    font-size: 12.5px;
    color: var(--text-secondary);
}

.hero-ctas {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
}

.hero-art {
    position: relative;
    display: grid;
    justify-items: center;
    isolation: isolate;
}

.hero-art .mark {
    width: min(230px, 42vw);
    height: min(230px, 42vw);
}

.hero-floor {
    width: 84%;
    height: 1px;
    margin: 6px 0 2px;
    background: linear-gradient(90deg, transparent, var(--border-color) 18%, var(--border-color) 82%, transparent);
}

.hero-reflect {
    height: calc(min(230px, 42vw) * .5);
    overflow: hidden;
    display: grid;
    justify-items: center;
}

.hero-reflect .mark {
    transform: scaleY(-1);
    opacity: .3;
    -webkit-mask-image: linear-gradient(to top, #000 0%, transparent 55%);
    mask-image: linear-gradient(to top, #000 0%, transparent 55%);
}

/* At rest, the sheen sits off the art's left edge, where sheen-sweep starts,
   so a still frame never shows part of it. */
.hero-sheen {
    position: absolute;
    inset: 0;
    pointer-events: none;
    mix-blend-mode: var(--sheen-blend);
    background: linear-gradient(105deg, transparent 38%, var(--sheen) 50%, transparent 62%) 130% 0 / 260% 100% no-repeat;
    animation: sheen-sweep 7.5s cubic-bezier(.2, .8, .2, 1) infinite;
}

@keyframes sheen-sweep {
    0% { background-position: 130% 0; }
    55%, 100% { background-position: -30% 0; }
}

/* ===========================================================================
   Sync streams -- one row per mirror, between the hero and the mirror cards.
   =========================================================================== */
.streams-inner {
    display: grid;
    gap: 2px;
    padding: 8px 16px;
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
}

.stream {
    display: grid;
    grid-template-columns: 84px auto minmax(40px, 1fr) auto 104px;
    align-items: center;
    gap: 14px;
    min-height: 40px;
    font-size: 13px;
}

.stream-name {
    font-weight: 600;
}

.stream-label,
.stream-host {
    color: var(--text-secondary);
    font-size: 12px;
    white-space: nowrap;
}

.stream-line {
    position: relative;
    height: 8px;
}

/* Online: a solid line, at least 3:1 against the surface -- see
   docs/design/2026-09-25-reflection-redesign.md section 4.1, --stream-line. */
.stream[data-state="online"] .stream-line::before {
    content: '';
    position: absolute;
    inset: 50% 0 auto;
    height: 1.5px;
    background: var(--stream-line);
}

/* Syncing: dots flowing from upstream to mirror, in the same amber as the
   row's syncing pill. */
.stream[data-state="syncing"] .stream-line {
    background: radial-gradient(circle, var(--status-syncing) 0 2px, transparent 2.6px) 0 50% / 16px 8px repeat-x;
    animation: stream-flow .9s linear infinite;
}

@keyframes stream-flow {
    to { background-position: 16px 50%; }
}

/* Error: a broken dashed line with a × where the sync stopped. */
.stream[data-state="error"] .stream-line {
    background:
        repeating-linear-gradient(90deg, var(--status-error) 0 6px, transparent 6px 11px) 0 50% / 42% 1.5px no-repeat,
        repeating-linear-gradient(90deg, var(--status-error) 0 6px, transparent 6px 11px) 100% 50% / 42% 1.5px no-repeat;
}

.stream[data-state="error"] .stream-line::after {
    content: '\00d7';
    position: absolute;
    left: 50%;
    top: 50%;
    transform: translate(-50%, -54%);
    color: var(--status-error);
    font-size: 16px;
    font-weight: 700;
    line-height: 1;
}

/* ===========================================================================
   Pills -- shared by every mirror state (spec section 4.8). Keyed only by
   data-state, never a class rewrite, so main.js only ever needs to set one
   attribute.
   =========================================================================== */
.pill {
    display: inline-flex;
    align-items: center;
    /* Content width, even in a stream row's fixed grid column. */
    justify-self: start;
    gap: 6px;
    padding: 4px 10px 4px 8px;
    border-radius: var(--radius-full);
    font-size: 12px;
    font-weight: 600;
    white-space: nowrap;
    color: var(--text-secondary);
    background: var(--bg-secondary);
    transition: color var(--transition-fast), background-color var(--transition-fast);
}

.pill-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: currentColor;
    flex-shrink: 0;
}

.pill[data-state="online"] {
    color: var(--status-healthy);
    background: var(--status-healthy-bg);
}

.pill[data-state="syncing"] {
    color: var(--status-syncing);
    background: var(--status-syncing-bg);
}

.pill[data-state="syncing"] .pill-dot {
    animation: pill-ring 1.5s cubic-bezier(.2, .8, .2, 1) infinite;
}

@keyframes pill-ring {
    0% { box-shadow: 0 0 0 0 color-mix(in srgb, currentColor 55%, transparent); }
    100% { box-shadow: 0 0 0 7px transparent; }
}

.pill[data-state="error"] {
    color: var(--status-error);
    background: var(--status-error-bg);
}

/* ===========================================================================
   Mirror cards
   =========================================================================== */
.mirror-cards {
    display: grid;
    gap: 20px;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
}

@media (min-width: 980px) {
    .mirror-cards {
        grid-template-columns: repeat(3, 1fr);
    }
}

.mirror-card {
    display: flex;
    flex-direction: column;
    gap: 14px;
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-xl);
    padding: 22px;
    box-shadow: var(--shadow-card);
    transition: transform var(--transition-lift), box-shadow var(--transition-lift);
}

.mirror-card:hover {
    transform: translateY(-3px);
    box-shadow: var(--shadow-card-hover);
}

.mirror-card-header {
    display: flex;
    align-items: center;
    gap: 12px;
}

.mirror-logo-tile {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 40px;
    height: 40px;
    border-radius: var(--radius-md);
    background: var(--bg-secondary);
}

.mirror-logo {
    display: block;
    width: 26px;
    height: 26px;
}

.mirror-name {
    font-family: var(--font-display);
    font-weight: 600;
    font-size: 18px;
    letter-spacing: -0.02em;
    flex: 1;
}

.mirror-description {
    color: var(--text-secondary);
    font-size: 13.5px;
}

.mirror-details {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
}

.mirror-details dt {
    font-size: 12px;
    color: var(--text-secondary);
}

.mirror-details dd {
    margin-top: 2px;
    font-size: 13.5px;
    color: var(--text-primary);
}

.mirror-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: auto;
    padding-top: 4px;
}

/* ===========================================================================
   Status & access
   =========================================================================== */
.status-card {
    display: flex;
    align-items: center;
    gap: 16px;
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-xl);
    padding: 22px;
}

.status-dot {
    flex-shrink: 0;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: var(--text-secondary);
}

.status-card[data-state="online"] .status-dot {
    background: var(--status-healthy);
}

.status-card[data-state="syncing"] .status-dot {
    background: var(--status-syncing);
}

.status-card[data-state="error"] .status-dot {
    background: var(--status-error);
}

/* A card title, so the display face (spec section 4.2), sized like
   .mirror-name. */
.status-card h3 {
    font-family: var(--font-display);
    font-size: 18px;
    font-weight: 600;
    letter-spacing: -0.02em;
    margin-bottom: 4px;
}

.status-card p {
    color: var(--text-secondary);
    font-size: 13.5px;
}

/* Access has no subtitle, so its title keeps the 36px a subtitle leaves
   above a section's content, instead of its own 10px. */
.access .section-title {
    margin-bottom: 36px;
}

.access-grid {
    display: grid;
    gap: 14px;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
}

.access-row {
    display: flex;
    align-items: center;
    gap: 12px;
    min-width: 0;
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    padding: 10px 10px 10px 16px;
}

.access-label {
    flex-shrink: 0;
    width: 76px;
    font-size: 12px;
    font-weight: 600;
    color: var(--text-secondary);
}

.access-url {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 13px;
}

/* ===========================================================================
   About
   =========================================================================== */
.about-content {
    max-width: 700px;
    margin: 0 auto;
}

.about-content > .section-title,
.about-content > .section-subtitle {
    text-align: left;
}

.about-text p {
    color: var(--text-secondary);
    margin-bottom: 20px;
}

.about-text a {
    color: var(--text-secondary);
    text-decoration: underline;
    text-underline-offset: 2px;
}

.about-text h4 {
    font-size: 15px;
    font-weight: 600;
    margin-bottom: 8px;
    color: var(--text-primary);
}

/* The last paragraph's margin would add to the section's own 72px gap
   below it. */
.about-text > :last-child {
    margin-bottom: 0;
}

/* ===========================================================================
   Section headings shared by Mirrors, Status, Access and About
   =========================================================================== */
.section-title {
    font-family: var(--font-display);
    font-weight: 600;
    font-size: 30px;
    letter-spacing: -0.03em;
    margin-bottom: 10px;
    text-align: center;
}

.section-subtitle {
    text-align: center;
    color: var(--text-secondary);
    margin-bottom: 36px;
    font-size: 14.5px;
}

/* ===========================================================================
   Footer
   =========================================================================== */
.footer {
    padding: 28px 0;
    border-top: 1px solid var(--border-color);
    background: var(--bg-secondary);
}

.footer-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    text-align: center;
}

.footer-content p {
    color: var(--text-secondary);
    font-size: 13.5px;
}

.footer-content a {
    color: var(--text-secondary);
    text-decoration: underline;
    text-underline-offset: 2px;
}

.footer-version {
    font-family: var(--font-mono);
    font-size: 12px !important;
}

/* ===========================================================================
   Toast
   =========================================================================== */
.toast {
    position: fixed;
    bottom: 24px;
    left: 50%;
    transform: translateX(-50%) translateY(100px);
    background: var(--bg-card);
    color: var(--text-primary);
    border: 1px solid var(--border-color);
    padding: 12px 20px;
    border-radius: var(--radius-md);
    font-size: 13.5px;
    font-weight: 500;
    font-family: var(--font-mono);
    box-shadow: var(--shadow-card-hover);
    opacity: 0;
    transition: transform var(--transition-base), opacity var(--transition-base);
    z-index: 1000;
}

.toast.show {
    transform: translateX(-50%) translateY(0);
    opacity: 1;
}

/* ===========================================================================
   Focus
   =========================================================================== */
:focus-visible {
    outline: 2px solid var(--accent-primary);
    outline-offset: 2px;
}

/* ===========================================================================
   Reduced motion -- every animation and transition off. No animation is ever
   set as an inline style, so this rule always wins.
   =========================================================================== */
@media (prefers-reduced-motion: reduce) {
    html {
        scroll-behavior: auto;
    }

    *, *::before, *::after {
        animation: none !important;
        transition: none !important;
    }

    /* A sheen that never moves is only a smudge on the art. */
    .hero-sheen {
        display: none;
    }
}

/* ===========================================================================
   Responsive
   =========================================================================== */
@media (max-width: 639.98px) {
    .nav {
        display: none;
    }

    .hero,
    .streams,
    .mirrors,
    .status,
    .access,
    .about {
        padding-bottom: 48px;
    }

    .hero-art {
        order: -1;
    }

    .stream {
        grid-template-columns: 70px minmax(30px, 1fr) 88px;
    }

    .stream-label,
    .stream-host {
        display: none;
    }

    .access-grid {
        grid-template-columns: 1fr;
    }
}
```

- [ ] **Step 9 (web-designer): replace `frontend/public/index.html` in full.** The structure in spec section 5.1:
- the header: the mark and wordmark, the four nav anchors, the theme toggle and `.nav-admin`;
- the hero: the eyebrow, the `h1`, the lede, three stats, two actions and the art;
- an unanchored sync-streams strip, one row per mirror, in a `<section>` named "Sync streams" by its `aria-label`;
- `#mirrors` with the three cards, `#status` with the overall card, and a new `#access` section with the two copy rows;
- `#about` and the footer, with today's copy.

Every pill, stream row and the overall card start at `data-state="unknown"`, reading "Checking…", and the hero stats start at an em dash. The `<symbol id="mark">` and its gradient sit in a clipped `<svg class="visually-hidden">` near the top of `<body>`, not `display:none`, so every `<use href="#mark">` on the page can resolve it. The hero's and the access rows' `data-copy` buttons do nothing until Task 6 binds them.

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="Mirror for FreeBSD, NetBSD and OpenBSD releases, packages and documentation">
    <title>BSD Mirror</title>
    <!-- Sets data-theme before the first paint; see js/theme-init.js. -->
    <script src="/js/theme-init.js"></script>
    <link rel="stylesheet" href="/css/fonts.css">
    <link rel="stylesheet" href="/css/tokens.css">
    <link rel="stylesheet" href="/css/style.css">
    <link rel="icon" href="/favicon.ico" sizes="32x32">
    <link rel="icon" type="image/svg+xml" href="/img/favicon.svg">
    <link rel="apple-touch-icon" href="/img/apple-touch-icon.png">
</head>
<body>
    <!-- The b|d mark (docs/design/2026-09-25-reflection-redesign.md, section
         4.5): one definition, reused by every <svg class="mark"><use
         href="#mark"></use></svg> below. Kept in the render tree (clipped,
         not display:none) so <use> can still resolve it. -->
    <svg class="visually-hidden" aria-hidden="true" focusable="false">
        <defs>
            <symbol id="mark" viewBox="0 0 64 64">
                <g class="mark-glyph">
                    <rect x="5" y="6" width="7" height="52"/>
                    <path fill-rule="evenodd" d="M5 46a12 12 0 1 0 24 0a12 12 0 1 0-24 0ZM11 46a6 6 0 1 0 12 0a6 6 0 1 0-12 0Z"/>
                    <g transform="translate(64 0) scale(-1 1)">
                        <rect x="5" y="6" width="7" height="52"/>
                        <path fill-rule="evenodd" d="M5 46a12 12 0 1 0 24 0a12 12 0 1 0-24 0ZM11 46a6 6 0 1 0 12 0a6 6 0 1 0-12 0Z"/>
                    </g>
                </g>
                <rect class="mark-axis" x="30.7" y="3" width="2.6" height="58" rx="1.3"/>
            </symbol>
            <linearGradient id="hero-mark-gradient" x1="0" y1="0" x2="0" y2="1">
                <stop class="mark-gradient-from" offset="0"/>
                <stop class="mark-gradient-to" offset="1"/>
            </linearGradient>
        </defs>
    </svg>

    <header class="header">
        <div class="container header-inner">
            <div class="brand">
                <svg class="mark" viewBox="0 0 64 64" aria-hidden="true" focusable="false"><use href="#mark"></use></svg>
                <span class="wordmark">BSD Mirror</span>
            </div>
            <nav class="nav" aria-label="Site">
                <a href="#mirrors" class="nav-link">Mirrors</a>
                <a href="#status" class="nav-link">Status</a>
                <a href="#access" class="nav-link">Access</a>
                <a href="#about" class="nav-link">About</a>
            </nav>
            <div class="nav-actions">
                <button class="icon-btn theme-toggle" id="themeToggle" type="button" aria-label="Toggle theme">
                    <span class="icon theme-icon" data-icon="moon" aria-hidden="true"></span>
                </button>
                <a href="/admin" class="nav-admin">Admin</a>
            </div>
        </div>
    </header>

    <main>
        <!-- Hero -->
        <section class="hero">
            <div class="container hero-inner">
                <div class="hero-copy">
                    <p class="hero-eyebrow">FreeBSD &middot; NetBSD &middot; OpenBSD</p>
                    <h1 class="hero-title">Every BSD, mirrored.</h1>
                    <p class="hero-lede">High-speed access to releases, packages and documentation, synced from the official upstream mirrors.</p>
                    <div class="hero-stats">
                        <div class="stat">
                            <span class="stat-value" id="statSize">&mdash;</span>
                            <span class="stat-label">mirrored</span>
                        </div>
                        <div class="stat">
                            <span class="stat-value" id="statFiles">&mdash;</span>
                            <span class="stat-label">files</span>
                        </div>
                        <div class="stat">
                            <span class="stat-value" id="statLastSync">&mdash;</span>
                            <span class="stat-label">last sync</span>
                        </div>
                    </div>
                    <div class="hero-ctas">
                        <a href="#mirrors" class="btn btn-primary">Browse mirrors<span class="icon icon-arrow-right" aria-hidden="true"></span></a>
                        <button class="btn btn-secondary" type="button" data-copy="rsync-root"><span class="icon icon-copy" aria-hidden="true"></span>Copy rsync URL</button>
                    </div>
                </div>
                <div class="hero-art" aria-hidden="true">
                    <svg class="mark hero-mark" viewBox="0 0 64 64" focusable="false"><use href="#mark"></use></svg>
                    <div class="hero-floor"></div>
                    <div class="hero-reflect">
                        <svg class="mark hero-mark" viewBox="0 0 64 64" focusable="false"><use href="#mark"></use></svg>
                    </div>
                    <div class="hero-sheen"></div>
                </div>
            </div>
        </section>

        <!-- Sync streams: one row per mirror, upstream to us. -->
        <section class="streams" aria-label="Sync streams">
            <div class="container">
                <div class="streams-inner">
                    <div class="stream" id="freebsd-stream" data-state="unknown">
                        <span class="stream-name">FreeBSD</span>
                        <span class="stream-label">Upstream</span>
                        <span class="stream-line" aria-hidden="true"></span>
                        <span class="stream-host mono" data-hostname=""></span>
                        <span class="pill" data-state="unknown">
                            <span class="pill-dot" aria-hidden="true"></span>
                            <span class="status-text">Checking&hellip;</span>
                        </span>
                    </div>
                    <div class="stream" id="netbsd-stream" data-state="unknown">
                        <span class="stream-name">NetBSD</span>
                        <span class="stream-label">Upstream</span>
                        <span class="stream-line" aria-hidden="true"></span>
                        <span class="stream-host mono" data-hostname=""></span>
                        <span class="pill" data-state="unknown">
                            <span class="pill-dot" aria-hidden="true"></span>
                            <span class="status-text">Checking&hellip;</span>
                        </span>
                    </div>
                    <div class="stream" id="openbsd-stream" data-state="unknown">
                        <span class="stream-name">OpenBSD</span>
                        <span class="stream-label">Upstream</span>
                        <span class="stream-line" aria-hidden="true"></span>
                        <span class="stream-host mono" data-hostname=""></span>
                        <span class="pill" data-state="unknown">
                            <span class="pill-dot" aria-hidden="true"></span>
                            <span class="status-text">Checking&hellip;</span>
                        </span>
                    </div>
                </div>
            </div>
        </section>

        <!-- Mirrors -->
        <section class="mirrors" id="mirrors">
            <div class="container">
                <h2 class="section-title">Available Mirrors</h2>
                <p class="section-subtitle">Browse and sync from our high-speed BSD distribution mirrors</p>
                <div class="mirror-cards">
                    <!-- FreeBSD -->
                    <article class="mirror-card" data-mirror="freebsd">
                        <div class="mirror-card-header">
                            <span class="mirror-logo-tile"><img src="/img/freebsd-logo.svg" alt="FreeBSD" class="mirror-logo"></span>
                            <h3 class="mirror-name">FreeBSD</h3>
                            <span class="pill" id="freebsd-status" data-state="unknown">
                                <span class="pill-dot" aria-hidden="true"></span>
                                <span class="status-text">Checking&hellip;</span>
                            </span>
                        </div>
                        <p class="mirror-description">The FreeBSD operating system - a powerful, flexible Unix-like OS for servers, desktops, and embedded platforms.</p>
                        <dl class="mirror-details">
                            <div>
                                <dt>Size:</dt>
                                <dd class="mono" id="freebsd-size">--</dd>
                            </div>
                            <div>
                                <dt>Last Sync:</dt>
                                <dd class="mono" id="freebsd-sync">--</dd>
                            </div>
                        </dl>
                        <div class="mirror-actions">
                            <a href="/FreeBSD/" class="btn btn-primary">Browse files<span class="icon icon-arrow-right" aria-hidden="true"></span></a>
                            <button class="btn btn-secondary" data-copy-rsync="FreeBSD"><span class="icon icon-copy" aria-hidden="true"></span>rsync URL</button>
                        </div>
                    </article>

                    <!-- NetBSD -->
                    <article class="mirror-card" data-mirror="netbsd">
                        <div class="mirror-card-header">
                            <span class="mirror-logo-tile"><img src="/img/netbsd-logo.svg" alt="NetBSD" class="mirror-logo"></span>
                            <h3 class="mirror-name">NetBSD</h3>
                            <span class="pill" id="netbsd-status" data-state="unknown">
                                <span class="pill-dot" aria-hidden="true"></span>
                                <span class="status-text">Checking&hellip;</span>
                            </span>
                        </div>
                        <p class="mirror-description">NetBSD - "Of course it runs NetBSD". A highly portable, clean, and well-documented operating system.</p>
                        <dl class="mirror-details">
                            <div>
                                <dt>Size:</dt>
                                <dd class="mono" id="netbsd-size">--</dd>
                            </div>
                            <div>
                                <dt>Last Sync:</dt>
                                <dd class="mono" id="netbsd-sync">--</dd>
                            </div>
                        </dl>
                        <div class="mirror-actions">
                            <a href="/NetBSD/" class="btn btn-primary">Browse files<span class="icon icon-arrow-right" aria-hidden="true"></span></a>
                            <button class="btn btn-secondary" data-copy-rsync="NetBSD"><span class="icon icon-copy" aria-hidden="true"></span>rsync URL</button>
                        </div>
                    </article>

                    <!-- OpenBSD -->
                    <article class="mirror-card" data-mirror="openbsd">
                        <div class="mirror-card-header">
                            <span class="mirror-logo-tile"><img src="/img/openbsd-logo.svg" alt="OpenBSD" class="mirror-logo"></span>
                            <h3 class="mirror-name">OpenBSD</h3>
                            <span class="pill" id="openbsd-status" data-state="unknown">
                                <span class="pill-dot" aria-hidden="true"></span>
                                <span class="status-text">Checking&hellip;</span>
                            </span>
                        </div>
                        <p class="mirror-description">OpenBSD - Proactively secure. Free. Functional. The most security-focused BSD distribution.</p>
                        <dl class="mirror-details">
                            <div>
                                <dt>Size:</dt>
                                <dd class="mono" id="openbsd-size">--</dd>
                            </div>
                            <div>
                                <dt>Last Sync:</dt>
                                <dd class="mono" id="openbsd-sync">--</dd>
                            </div>
                        </dl>
                        <div class="mirror-actions">
                            <a href="/OpenBSD/" class="btn btn-primary">Browse files<span class="icon icon-arrow-right" aria-hidden="true"></span></a>
                            <button class="btn btn-secondary" data-copy-rsync="OpenBSD"><span class="icon icon-copy" aria-hidden="true"></span>rsync URL</button>
                        </div>
                    </article>
                </div>
            </div>
        </section>

        <!-- Status -->
        <section class="status" id="status">
            <div class="container">
                <h2 class="section-title">Mirror Status</h2>
                <p class="section-subtitle">Real-time synchronization and availability overview</p>
                <div class="status-card" id="overallStatus" data-state="unknown">
                    <span class="status-dot" aria-hidden="true"></span>
                    <div>
                        <h3>Checking mirror status&hellip;</h3>
                        <p></p>
                    </div>
                </div>
            </div>
        </section>

        <!-- Access -->
        <section class="access" id="access">
            <div class="container">
                <h2 class="section-title">Access Methods</h2>
                <div class="access-grid">
                    <div class="access-row">
                        <span class="access-label">HTTP/HTTPS</span>
                        <code class="access-url mono">https://<span id="hostname">mirror.example.com</span>/</code>
                        <button class="icon-btn" type="button" data-copy="https-root" aria-label="Copy HTTPS URL">
                            <span class="icon icon-copy" aria-hidden="true"></span>
                        </button>
                    </div>
                    <div class="access-row">
                        <span class="access-label">rsync</span>
                        <code class="access-url mono">rsync://<span id="rsynchost">mirror.example.com</span>/</code>
                        <button class="icon-btn" type="button" data-copy="rsync-root" aria-label="Copy rsync URL">
                            <span class="icon icon-copy" aria-hidden="true"></span>
                        </button>
                    </div>
                </div>
            </div>
        </section>

        <!-- About -->
        <section class="about" id="about">
            <div class="container">
                <div class="about-content">
                    <h2 class="section-title">About This Mirror</h2>
                    <p class="section-subtitle">Built on open source mirror software</p>
                    <div class="about-text">
                        <p>
                            This mirror provides fast and reliable access to BSD operating system distributions.
                            It synchronizes regularly with the official upstream mirrors, so you always have the
                            latest releases, packages, and security updates.
                        </p>

                        <p>
                            The software that runs it is
                            <a href="https://github.com/nkalev/bsdmirror" target="_blank" rel="noopener">open source</a>,
                            released under the BSD 3-Clause license. Anyone may use it to run their own mirror
                            &mdash; community-run or otherwise &mdash; under that license's terms.
                        </p>

                        <h4>Contact</h4>
                        <p>For issues or questions, please open an issue on our <a href="https://github.com/nkalev/bsdmirror" target="_blank" rel="noopener">GitHub repository</a>.</p>
                    </div>
                </div>
            </div>
        </section>
    </main>

    <footer class="footer">
        <div class="container">
            <div class="footer-content">
                <p>&copy; 2026 BSD Mirror &middot; Runs on <a href="https://github.com/nkalev/bsdmirror" target="_blank" rel="noopener">open source software</a></p>
                <!-- Populated at runtime by main.js (FooterVersion) from GET /api/health's
                     "version" field -- GIT_SHA-BUILD_DATE, baked into the backend image at
                     build time. Left empty here rather than templated: this file is static
                     and bind-mounted with no build step (see docker-compose.yml), so there is
                     nowhere to render a value into it before nginx serves it. Left empty, not
                     filled with a placeholder, if the API is unreachable -- see FooterVersion.load(). -->
                <p class="footer-version"></p>
            </div>
        </div>
    </footer>

    <!-- Toast notification -->
    <div class="toast" id="toast"></div>

    <script src="/js/main.js"></script>
</body>
</html>
```

- [ ] **Step 10 (web-designer): replace `frontend/public/css/error.css` in full.** The error pages' own redesign is Task 7; this step only brings `error.css` in line with the new tokens. The dark `@media` block mirrors the new `tokens.css` dark values as `var(--c-*)`, four tokens now. The link shares `--accent-primary` with the heading, which clears 4.5:1 in both themes, since `--accent-secondary` is retired. The body's colour fade moves to `--transition-fast`, as in `style.css` and spec section 4.4, and a `@media (prefers-reduced-motion: reduce)` block turns it off: `tests/test_reduced_motion.py` counts any transition as motion. The comments' contrast figures, font name and token count are brought up to date.

```css
/* BSD Mirror - Static Error Pages (404, 50x) */
/* Shared by frontend/public/404.html and frontend/public/50x.html.
   Design tokens live in css/tokens.css, linked ahead of this file.
   Do not declare custom properties here.

   Deliberately NOT linking css/style.css or css/fonts.css:

   - style.css is the full site stylesheet (header, hero, sync streams,
     mirror cards, status and access). These two pages render one heading,
     one paragraph and one link; loading it would be the "chases four
     stylesheets" failure mode the 50x page specifically cannot afford when
     the backend is down.
   - fonts.css declares the self-hosted @font-face rules for 'Instrument
     Sans'. Without it, var(--font-sans) simply falls through to its system-
     font fallbacks below -- no failed request, no unstyled flash, just a
     plain sans-serif.

   Both files are still served solely as static files by nginx off the same
   document root as this stylesheet (nginx/sites/production/production.conf),
   so neither depends on the backend being up.

   No [data-theme="dark"] rules appear below on purpose: these pages carry no
   script, nothing ever sets data-theme on <html>, and every color here is a
   custom property that tokens.css already resolves per theme. Light is what
   renders, and light is the deliberate no-JS default (tokens.css :root, and
   the same default main.js falls back to when localStorage is empty). */

body {
    font-family: var(--font-sans);
    background-color: var(--bg-primary);
    color: var(--text-primary);
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 100vh;
    margin: 0;
    transition: background-color var(--transition-fast), color var(--transition-fast);
}

.error-content {
    text-align: center;
    padding: 2rem;
}

.error-content h1 {
    /* Large text (3rem, well over the 24px/18.66px-bold WCAG threshold), so
       the 3:1 large-text ratio applies rather than 4.5:1 -- though this
       palette's accent clears both here: 4.84:1 in light, 6.56:1 in dark. */
    color: var(--accent-primary);
    font-size: 3rem;
    margin-bottom: 0.5rem;
}

.error-content p {
    /* Normal-size text (1.1rem): needs 4.5:1. --text-secondary reaches
       6.44:1 in light and 8.48:1 in dark against --bg-primary. */
    color: var(--text-secondary);
    font-size: 1.1rem;
}

.error-content a {
    /* Also normal-size text needing 4.5:1. This palette's accent clears it
       directly (4.84:1 light, 6.56:1 dark against --bg-primary) -- unlike
       the previous palette, there is no second accent needed here. */
    color: var(--accent-primary);
    text-decoration: none;
}

.error-content a:hover {
    text-decoration: underline;
}

@media (max-width: 768px) {
    .error-content h1 {
        font-size: 2.25rem;
    }
}

/* Reduced motion (spec section 4.4): the body's colour fade above is this
   file's only motion, and it goes too. */
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        animation: none !important;
        transition: none !important;
    }
}

/* ---------------------------------------------------------------------------
   OS dark preference
   ---------------------------------------------------------------------------
   These pages ship no <script>, and this codebase picks its theme purely in
   JavaScript -- main.js sets data-theme on <html>, and there is no
   prefers-color-scheme rule anywhere else in frontend/. So without this block
   an error page renders tokens.css's :root (light) on every machine, including
   one whose entire desktop is dark. That is not "theme-aware"; it is "always
   light, in tokens", which is a different and less useful thing.

   The four tokens below are exactly the ones these pages consume, mirroring
   tokens.css's [data-theme="dark"] block. They reference the same --c-* palette
   entries rather than restating hex, so a palette change still flows from one
   definition. test_error_page_dark_mapping_matches_tokens_css asserts the two
   agree -- add a token to an error page and you must add it in both places or
   that test fails.

   :not([data-theme="light"]) so that an explicitly chosen light theme still
   wins if these pages ever gain scripting. Specificity (0,2,0) also puts this
   above tokens.css's bare :root (0,1,0), which is what makes it apply at all.

   Contrast in this mode, against --bg-primary #07080B:
     --text-primary    #EDEFF3  17.40:1
     --text-secondary  #A2A9B6   8.48:1
     --accent-primary  #FF5A60   6.56:1  (3rem heading, needs 3.0; link, needs 4.5)
   --------------------------------------------------------------------------- */
@media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
        --bg-primary: var(--c-graphite-975);
        --text-primary: var(--c-graphite-75);
        --text-secondary: var(--c-graphite-400);
        --accent-primary: var(--c-red-400);
    }
}
```

- [ ] **Step 11 (web-designer): look at it.** Render the page with the visual-check script Task 8 Step 1 gives in full. The controller writes Task 8 Step 1's two scripts to `$SCRATCH/pr2/screens.sh` and `$SCRATCH/pr2/tiles.py` before dispatching this step, and passes `$SCRATCH`'s absolute path. The script serves `frontend/public` with a stubbed status API (FreeBSD online, NetBSD syncing, OpenBSD in error), screenshots the public page and both error pages at 1440, 768 and 400px, light and dark, renders the 503 page once more without its stylesheets, and compares the admin login page with `main`'s files byte for byte:

```bash
rm -rf "$SCRATCH/pr2/main-public" && mkdir -p "$SCRATCH/pr2/main-public"
git archive main frontend/public | tar -x -C "$SCRATCH/pr2/main-public"
bash "$SCRATCH/pr2/screens.sh" "$PWD" "$SCRATCH/pr2/main-public/frontend/public"; echo "rc=$?"
```

Expected: `admin login page: byte-identical to the base checkout`, nineteen `pr2-*.png` files listed, and `rc=0`. Chromium may print harmless `dbus` errors. The files land in `.screenshots/`, which git ignores. If the admin page differs, the script keeps both images as `pr2-admin-*.png` and exits 3: the admin block is letting a shared token through, and that is fixed in `tokens.css` before going on. `pr2-50x-unstyled-1440.png` is Task 7's to check; this task does not touch the error pages' markup.

Tile the six tall home-page PNGs with Task 8 Step 3's command, so the Read tool shows them at full size. Then open every home tile and every other `pr2-404-*` and `pr2-50x-*` PNG with the Read tool, and check each of these in both themes:
- **Header:** sticky, with its translucent background over the page; the mark and wordmark; four nav links; the toggle showing the moon in light and the sun in dark; Admin in the accent colour.
- **Hero:** the eyebrow, the headline on two lines at 1440px and at 400px (spec section 12 flags Unbounded's width), the lede, three stats and both actions. The art shows the mark, the floor and the reflection, and no sheen: the stills force reduced motion, which hides it, so a light wedge or streak along the art's right edge means `.hero-sheen` is showing at rest. The glyph is a vertical gradient, not a flat fill; the pixel check below confirms it.
- **Streams:** FreeBSD a solid line, NetBSD dots in the syncing amber, OpenBSD a dashed line with a centred ×, each ending in its pill, and each pill only as wide as its word, not stretched across its column.
- **Cards, status and access:** each card's logo, name, pill, description, size, last sync and both actions; the overall card's error dot, "Degraded service" in the display face like the card names, and "OpenBSD is experiencing issues."; the two access rows' copy buttons, and the stubbed host in the HTTPS and rsync URLs.
- **Spacing:** the same gap between every two sections, from the hero down to the footer, larger at 1440 and 768px (72px) than at 400px (48px), and every section heading, Access's included, the same distance above its content. The spacing check below measures both.
- **Responsive:** at 1440px, the hero in two columns and the cards three across. At 768px, the hero in one column with the art after the copy, the cards two to a row, and the nav still showing, since it collapses only below 640px. At 400px, the nav reduced to the toggle and Admin, the art first, the stream rows without "Upstream" and the host, and the access rows stacked.
- **Error pages:** 404 and 50x, where dark comes from `prefers-color-scheme` alone (these pages have no `data-theme` and no script): a dark background, with the heading and link in the accent.

Check the gradient in pixels, with `tests/test_images.py`'s PNG reader:

```bash
docker compose run --rm -T test python -c '
import pathlib
from tests.test_images import png_rows

for scheme in ("light", "dark"):
    channels, rows = png_rows(pathlib.Path(f".screenshots/pr2-home-{scheme}-1440.png").read_bytes())
    for end, y in (("top", 163), ("bottom", 342)):
        r, g, b = rows[y][985 * channels : 985 * channels + 3]
        print(scheme, end, "#%02X%02X%02X" % (r, g, b))
'
```

Expected: `light top #0D0F13`, `light bottom #49505D`, `dark top #EBEDF1` and `dark bottom #9097A5`. At 1440px the hero mark's `<svg>` sits at (955, 138), 230px square, so x = 985 is the middle of the "b" stem, and y = 163 and y = 342 are one grid unit inside its two ends, where the gradient has moved about 2% of its way. Each sample is therefore within three steps per channel of its gradient end: `#0C0E12` to `#4A515E` in light, `#EDEFF3` to `#8D95A3` in dark. A flat fill would print one colour twice.

Then follow each nav anchor, and the hero's "Browse mirrors". This frames the page at 1440×900, clicks each link in it and prints where the target section's heading lands:

```bash
docker compose run --rm -T test bash -c '
mkdir -p /tmp/www && cp -R frontend/public/. /tmp/www/
cat >/tmp/www/anchor-check.html <<EOF
<iframe id="f" src="/index.html" width="1440" height="900"></iframe>
<pre id="out"></pre>
<script>
f.onload = async () => {
    const d = f.contentDocument, lines = [];
    for (const link of [...d.querySelectorAll(".nav a"), d.querySelector(".hero-ctas a")]) {
        f.contentWindow.scrollTo(0, 0);
        link.click();
        await new Promise((r) => setTimeout(r, 300));
        const heading = d.querySelector(link.getAttribute("href") + " h2").getBoundingClientRect();
        const header = d.querySelector(".header").getBoundingClientRect();
        lines.push(link.textContent.trim() + ": heading top " + Math.round(heading.top) +
            "px, header bottom " + header.bottom + "px");
    }
    out.textContent = lines.join("\n");
};
</script>
EOF
cd /tmp/www && python3 -m http.server 8765 --bind 127.0.0.1 >/dev/null 2>&1 &
sleep 1
chromium --headless=new --disable-gpu --force-prefers-reduced-motion --virtual-time-budget=8000 \
    --dump-dom http://127.0.0.1:8765/anchor-check.html 2>/dev/null | sed -n "/<pre/,/<\/pre>/p"'
```

Expected, each heading fully visible below the header:
- `Mirrors: heading top 80px, header bottom 64px`
- `Status: heading top 80px, header bottom 64px`
- `Access: heading top 242px, header bottom 64px`
- `About: heading top 440px, header bottom 64px`
- `Browse mirrors: heading top 80px, header bottom 64px`

Mirrors, Status and "Browse mirrors" land 16px below the header, as `scroll-padding-top` asks; Access and About sit lower because a 900px window cannot scroll the page any further. The headless screenshot flag cannot do this job: it mis-draws a page scrolled to a fragment. With the `scroll-padding-top` line taken out, Mirrors, Status and "Browse mirrors" read 0px, under the header.

Then measure the spacing. This frames the page at the three widths and prints, for each, the gap below each of the six sections (the last one's to the footer), and the gap between each section's heading, or its subtitle where it has one, and the content under it:

```bash
docker compose run --rm -T test bash -c '
mkdir -p /tmp/www && cp -R frontend/public/. /tmp/www/
cat >/tmp/www/gap-check.js <<EOF
const measure = (frame) => {
    const d = frame.contentDocument;
    const kids = (s) => [...s.querySelectorAll(":scope > .container > *")].map((e) => e.getBoundingClientRect());
    const sections = [...d.querySelectorAll("main > section")];
    const gaps = sections.map((s, i) => {
        const next = sections[i + 1] ? Math.min(...kids(sections[i + 1]).map((r) => r.top))
            : d.querySelector(".footer").getBoundingClientRect().top;
        return Math.round(next - Math.max(...kids(s).map((r) => r.bottom)));
    });
    const headings = [...d.querySelectorAll(".section-title")].map((t) => {
        const last = t.nextElementSibling.matches(".section-subtitle") ? t.nextElementSibling : t;
        return Math.round(last.nextElementSibling.getBoundingClientRect().top - last.getBoundingClientRect().bottom);
    });
    return frame.width + "px: sections " + gaps.join(" ") + ", headings " + headings.join(" ");
};
window.onload = () => {
    out.textContent = [...document.querySelectorAll("iframe")].map(measure).join("\n");
};
EOF
cat >/tmp/www/gap-check.html <<EOF
<iframe src="/index.html" width="1440" height="900"></iframe>
<iframe src="/index.html" width="768" height="900"></iframe>
<iframe src="/index.html" width="400" height="900"></iframe>
<pre id="out"></pre>
<script src="gap-check.js"></script>
EOF
cd /tmp/www && python3 -m http.server 8765 --bind 127.0.0.1 >/dev/null 2>&1 &
sleep 1
chromium --headless=new --disable-gpu --force-prefers-reduced-motion --virtual-time-budget=8000 \
    --dump-dom http://127.0.0.1:8765/gap-check.html 2>/dev/null | sed -n "/<pre/,/<\/pre>/p"'
```

Expected, the gaps in page order (hero, streams, mirrors, status, access, about) and the headings in the same order (Mirrors, Status, Access, About):
- `1440px: sections 72 72 72 72 72 72, headings 36 36 36 36`
- `768px: sections 72 72 72 72 72 72, headings 36 36 36 36`
- `400px: sections 48 48 48 48 48 48, headings 36 36 36 36`

Against the same stylesheet without `.access .section-title` and `.about-text > :last-child`, the headings read `36 36 10 36` at every width, and the last section gap `92` (`68` at 400px).

Motion does not show in a still, and the script forces reduced motion besides. Check the sheen, the stream dots and the syncing pill's ring against spec section 4.4's timings in `style.css` instead.

- [ ] **Step 12 (developer): run green, lint, and the whole suite.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_contrast.py tests/test_public_page_structure.py tests/test_reduced_motion.py tests/test_focus_ring.py tests/test_chrome_harness_start.py; echo "rc=$?"`

Expected: `256 passed, 4 warnings`, `rc=0`:
- 218 in `test_contrast.py`: 153 static checks (the selector, token and admin pairs, the mutations and the self-tests), and 65 that need node and Chrome (the 48 public and 13 admin real-browser probes, the probe-list pin and the three negative controls);
- 29 in the three new files: 20 structure checks, 8 motion checks and the focus ring;
- 9 in `test_chrome_harness_start.py`, unaffected: the harness's command line and its Chrome start and stop handling did not change.

Read the count as well as the code: without node or Chrome the 65 skip, and a run with skips still exits 0.

Mutation check, for the at-rule repro: in `tests/test_contrast.py`, change `_prepared_css()`'s `return strip_at_rule_bodies(strip_css_comments(css_text))` to `return strip_css_comments(css_text)`, and run `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_contrast.py -k find_block_is_not_fooled; echo "rc=$?"`.
- Expected: `1 failed, 217 deselected, 4 warnings`, with `AssertionError: '.access-grid' rule found 2 times, expected 1`, and `rc=1`.
- Restore the line and re-run: `1 passed, 217 deselected, 4 warnings`, `rc=0`.

Mutation check, for the stream-row wait: run the harness on a copy of the docroot whose `main.js` never paints the rows.

```bash
docker compose run --rm -T test bash -c 'cp -R frontend/public /tmp/public && sed -i "/paintState(row, state, text);/d" /tmp/public/js/main.js && node tests/js/contrast_harness.mjs /tmp/public frontend/public/admin/js/admin.js chromium >/dev/null; echo "rc=$?"'
```

Expected: `Error: timed out after 5000ms waiting for the stubbed mirror statuses to paint`, then `rc=1`: the run stops before either theme is measured. The copy lives in the container's `/tmp`, so nothing needs restoring.

Run the lint pair on the four Python files. Both are clean on the first run, since the code above is already formatted; ruff does not lint `contrast_harness.mjs`.
`docker compose run --rm -T test ruff check tests/test_contrast.py tests/test_public_page_structure.py tests/test_reduced_motion.py tests/test_focus_ring.py; echo "rc=$?"` -> `rc=0`.
`docker compose run --rm -T test ruff format --check tests/test_contrast.py tests/test_public_page_structure.py tests/test_reduced_motion.py tests/test_focus_ring.py; echo "rc=$?"` -> `4 files already formatted`, `rc=0`.

Run: `docker compose run --rm -T test; echo "rc=$?"`

Expected: `1530 passed, 7 warnings`, `rc=0`: Task 3's 1425, plus 76 more in `test_contrast.py` (142 before, 218 now) and the 29 in the three new files. Read the exit code directly, not through a `tail`.

- [ ] **Step 13 (developer): commit.**

```bash
git add frontend/public/css/tokens.css frontend/public/css/style.css frontend/public/index.html frontend/public/css/error.css tests/test_contrast.py tests/js/contrast_harness.mjs tests/test_public_page_structure.py tests/test_reduced_motion.py tests/test_focus_ring.py
git commit -m "Switch the public site to the Reflection palette and layout"
```

#### Notes

**Design decisions.**
- **The hero mark's gradient crosses `<use>` through an inherited custom property.** `.mark-glyph { fill: var(--mark-glyph-fill, var(--text-primary)); }` falls back to the flat fill, and `.hero-mark { --mark-glyph-fill: url(#hero-mark-gradient); }` sets the property on the `<use>`'s own ancestor. A compound selector such as `.hero-mark .mark-glyph` does not match a `<use>`'s shadow content: the first attempt used one, and a pixel-sampled screenshot showed the stem flat `--text-primary` from top to bottom. A custom property inherits across that boundary, the same way `currentColor` does. After the change, the stem sampled `#0C0E12` at the top and `#4A515E` at the bottom, the light theme's two gradient ends. It is the one custom property declared outside `tokens.css`, and both files' headers name it as the exception to that rule.
- **The syncing dots are amber.** The syncing stream's dots use `--status-syncing`, the same amber as the row's own syncing pill; the mockup drew them in the accent red. Spec section 5.1 names no colour for them, and amber keeps one meaning per colour on the page: red is the accent and errors, amber is syncing.
- **Pills keep their content width.** `.pill` sets `justify-self: start`, as the mockup's pill does, so a pill in a stream row's fixed column (104px, 88px under 640px) hugs its word instead of stretching across it. In the card headers, which are flex rows, the property does nothing.
- **Sections carry their gap below them.** Each of the six sections has a 72px bottom padding, 48px under 640px. None of the four anchored sections has padding above its heading, so `scroll-padding-top` alone decides where an anchor lands. The hero keeps its own 56px under the header, a space spec section 4.3 does not set. Nothing inside a section adds to its gap, so `.about-text > :last-child` has no bottom margin. Every section's content starts 36px below its heading block: the subtitle's margin where there is one, and for Access, which has none, its title's own (`.access .section-title`).
- **The status card's title is a card title** in spec section 4.2's sense, so it takes Unbounded 600, at `.mirror-name`'s 18px.
- **Hero stat labels.** Spec section 5.1 names the three stats but not their labels. They read "mirrored", "files" and "last sync", without the mockup's ", UTC": `#statLastSync` shows a relative time such as "2h ago", not a clock time.
- **Access rows.** They keep today's labels, "HTTP/HTTPS" and "rsync", rather than the mockup's shorter "HTTPS": section 5.1 marks each copy change "new", and these labels are not among them. Today's two descriptive sentences and per-method `<h4>`s are dropped: each row is one compact line (label, URL and copy button) with no room for a sentence, and nothing pins them. `#access`'s `<h2>` reuses today's "Access Methods", the heading this content already had.
- **Card titles stay `<h3>`**, under `#mirrors`'s `<h2>`. Section 4.2 lists "card titles" as a font assignment for Unbounded, not a heading level.
- **Card buttons are sized by context,** with `.mirror-actions .btn`, not a `.btn-sm` class, so the copy button's opening tag stays byte-identical.
- **Breakpoints follow the spec,** not the mockup's 640px hero breakpoint: the hero is two columns from 980px, one column in DOM order (copy, then art) from 640px to 980px, and art-first below 640px.

**Test decisions.**
- **The pill and status-dot probes use the stub, then forced states.** `measurePublicProbes()` first waits for the stub's own paint, a real end-to-end check that `main.js`'s wiring works against the new markup in a browser, not only in the Node `vm` harness `tests/test_public_states.py` runs. Only then does it force the states one response cannot reach, always after the element's natural reading. The neutral pill is forced too, rather than read before the stub resolves: on a loopback server the fetch can land before `navigate()` notices the load, which would make that probe flaky.
- **`test_light_dark_admin_actually_differ` compares `--bg-card`** (dark `#101217`, admin's pinned `#1A1A2E`): it is already the vehicle for the file's other assertion and needs no new resolution path.
- **`strip_at_rule_bodies()` counts braces,** instead of the column-0 shortcut `tests/test_error_pages_inline_styles.py` uses for `tokens.css`. Both work on this `style.css`, but a formatter change could silently break the shortcut.
- **The meter's tick has no `TOKEN_PAIRS` row.** Spec section 9 names it, `--text-primary` against `--bg-card` at 3:1, but the 4.5:1 text pair already checks those two tokens, and any ratio that clears 4.5:1 clears 3:1. A second row would also give two checks one id, `--text-primary on --bg-card [light]`, which pytest would have to rename and the mutation tests' `failed_ids` could not tell apart. The comment at the meter rows says so.
- **The focus ring has a file of its own.** In `test_contrast.py`, its red would hide behind that module's collection error in Step 6; in `tests/test_focus_ring.py` it fails on its own against Task 3's stylesheet, which has no `:focus-visible` rule. Task 7 extends it by adding `error.css` to `STYLESHEETS`.
- **Any transition counts as motion.** Spec section 4.4 turns every animation and transition off under reduced motion, so `needs_a_reduced_motion_override()` fires on any `transition` or `animation` that is not `none`, where it first fired only on `@keyframes` or `all`. `error.css`'s colour fade therefore needs a reduced-motion block, which Step 10 adds, and `test_error_css_has_no_motion_to_disable_yet`, which pinned the opposite, is gone. Task 7's `error.css` must keep the block while it has a transition.
- **The streams region is pinned.** `test_the_sync_streams_section_is_a_named_region` is not one of the hooks `main.js` needs; it holds the fix for an `aria-label` that sat on the generic `.streams-inner`, where ARIA lets it name nothing.
- **The public page has its own contrast control.** `test_harness_detects_a_low_contrast_pill_on_the_public_page` plants a mid-tone green that fails on both themes' online tints, so it proves both theme passes measure the real stylesheet, not only the light one.

**Findings from the dry run.**
- **Two `admin.css` mutations now plant a literal colour.** `status_badge_health_incomplete_reverts_color_to_status_info` and `status_badge_info_reverts_color_to_status_info` planted `var(--status-info)`. That token is not among the 28 tokens `admin.css` reads, so the legacy block does not pin it, and it falls through to the shared dark theme. The new palette moved it from a shade that failed to `#7CB7F2`, 5.44:1 on `--status-info-bg`, and both mutations stopped failing ("changed a live rule and nothing failed") for a reason unrelated to `admin.css`. They now plant `#2D5A82`, 1.59:1 whatever the shared palette does, and are named `status_badge_health_incomplete_reverts_color_to_a_plausible_low_contrast_blue` and `status_badge_info_reverts_color_to_a_plausible_low_contrast_blue`. The comment at the mutation says why.
- **The nav-hover mutation has no successor.** `nav_link_hover_reverts_to_accent_primary_text` guarded a swap that failed in the old palette. This palette's `--accent-primary` was chosen to clear the header and every tinted surface on its own (`.nav-admin`'s comment in `style.css`), so the swap no longer fails anywhere. Rather than drop the slot, `stream_line_online_reverts_to_the_plain_border_colour` guards a plausible slip this palette does not prevent: the online stream line painted with the `--border-color` hairline instead of `--stream-line`, 1.36:1 in light and 1.29:1 in dark.
- **The harness emulates reduced motion.** Screenshots sampled during the dry run showed that a pill's colours transition over `--transition-fast` (150ms), so a probe taken right after a `data-state` change could read the neutral colours. Instead of a settle delay per probe, the harness emulates `prefers-reduced-motion: reduce` for the whole session; `style.css`'s own block turns every transition off, and `getComputedStyle` reads the settled colour at once. That removes the whole class of timing bugs, not only the probes anyone thought to check. The 250ms hover and 450ms theme-switch waits stay, as margin for the input plumbing. `screens.sh` forces reduced motion for the same reason.
- **An unpainted stream line passed in light.** With `main.js`'s row paint deleted from a copy of the docroot, the harness first ran to completion: the online line's `::before` matched no rule and read `rgba(0, 0, 0, 0)`, which `_measured_ratio()` scored as black, 21:1 on the light card, while dark failed at 1.12:1. `NATURAL_STATE_READY` now waits for `#freebsd-stream` itself, so that copy stops the run (Step 12's mutation check), and `_measured_ratio()` rejects a translucent foreground, so such a reading fails in both themes whatever else paints the row.
- **The at-rule repro could not fail.** `test_find_block_is_not_fooled_by_a_selector_reused_inside_at_rules` first had the `.access-grid` override as the only rule in its `@media` block, the one `_RULE_RE` swallows, so it passed with `strip_at_rule_bodies()` disabled. With `.nav` ahead of the override, as in `style.css`, disabling the strip fails it (Step 12's mutation check).
- **Anchors landed under the header, and the sheen showed at rest.** Measured in Chrome at 1440×900 before the fixes: `#mirrors`, `#status` and "Browse mirrors" put their headings at 0px to 8px, behind the 64px sticky header. With its animation off, `.hero-sheen`'s shorthand position `0 0` left part of the gradient over the art's right edge, a wedge in the reduced-motion stills of both themes. Section gaps were 48px, 48px and then 64px, and the stream pills stretched across their column.
- **Two spacing slips outlived those fixes.** Step 11's spacing check found About 92px above the footer, its 72px plus the last paragraph's 20px margin, and the Access heading 10px above its rows, since Access has no subtitle and its title's own margin is 10px; the other headings sit 36px above their content.
- **`waitFor()` checks for page errors on every poll.** The first version checked once, at the end of `main()`. The JS-error negative control then failed with `timed out after 5000ms waiting for the stubbed mirror statuses to paint` instead of the planted message: the throw stops `MirrorStatus.load()` from ever running, so the wait could never succeed, while the real exception sat unread in `cdp.jsErrors`.
- **`main.js` does not throw against the new markup.** `checkForPageErrors()` ran clean through both theme passes and the admin fixture, and the negative control shows the guard is not inert. The legacy paths Task 5 removes are silent no-ops here:
  - `statSize.closest('.stat-card')`, and the same call on `#statLastSync`: the new markup has no `.stat-card` (the stats are `.stat`, with no loading state), so the optional chain does nothing.
  - `updateMirrorCards`: `#<id>-status` is now a `.pill` whose dot is `.pill-dot`, so the `.status-dot` lookup returns `null` and the loop continues before writing anything.
  - `updateOverallStatus`: there is no `.status-indicator`, so the function returns before writing anything.
  - One naming coincidence, not a bug: the overall card's own dot is also `.status-dot` (`#overallStatus > .status-dot`), but `updateMirrorCards` only looks inside the card pills, never inside `#overallStatus`.

**Ids and classes `main.js` touches in this markup.** This task supplies the markup `main.js` already expects:
- `#themeToggle`, and `.theme-icon`'s `data-icon`;
- `#freebsd-status`, `#netbsd-status` and `#openbsd-status`, each a `.pill` carrying `data-state` and a nested `.status-text`;
- `#freebsd-stream`, `#netbsd-stream` and `#openbsd-stream`, each carrying `data-state` itself, and holding one `.pill` (also given `data-state` and a `.status-text`) and one `[data-hostname]`;
- `#freebsd-size` and `#freebsd-sync`, and likewise for NetBSD and OpenBSD;
- `#overallStatus`, carrying `data-state`, with a nested `h3` and `p`;
- `#statSize`, `#statFiles` and `#statLastSync`;
- `#hostname`, `#rsynchost`, and the three stream rows' `[data-hostname]` spans;
- the three `[data-copy-rsync]` buttons on the mirror cards;
- `#toast` and `.footer-version`.

The three `[data-copy]` buttons (the hero's `rsync-root`, and the access rows' `https-root` and `rsync-root`) are in the markup from this task, but `main.js` binds nothing to them until Task 6.

---

## Chunk 3: The new page, finished

Three tasks on top of the switch: the old status class and style writes come out of `main.js`, the page-wide copy buttons get their binding and a click test under the production CSP, and the error pages are redesigned.

### Task 5: Legacy writes out, and the nginx comment

Task 2 kept three legacy write paths in `main.js` beside the `data-state` model, each marked "removed in Task 5": `updateMirrorCards` rewrites each mirror's `.status-dot` className, `updateOverallStatus` rewrites `.status-indicator`'s className and `.pulse`'s inline background, and `updateStats` removes a `.stat-card`'s "loading" class. All three have been dead on the real page since Task 4:
- each mirror's card pill now holds a `.pill-dot`, not a `.status-dot`, so `updateMirrorCards` finds no dot and skips every mirror;
- the overall card keeps a `.status-dot`, which `style.css` colours through `.status-card[data-state]`, but it has no `.status-indicator`, so `updateOverallStatus` returns before it writes anything;
- no `.stat-card` is left, so `closest('.stat-card')` is null and the optional chaining skips the removal.

So nothing a visitor sees changes. This task deletes the dead code and proves the deletion with the fake DOM in `tests/js/states_harness.mjs`, where the legacy elements do exist and any write to them would show. `tests/js/contrast_harness.mjs` and `tests/test_contrast.py` need no change: they stopped keying off the old classes in Task 4. The same edits retire the comments that still describe the stream rows as markup to come.

**Files:**
- Modify: `tests/js/states_harness.mjs`
- Modify: `tests/test_public_states.py`
- Modify: `frontend/public/js/main.js`
- Modify: `tests/test_admin_js_escaping.py` (one comment)
- Modify: `nginx/nginx.conf`

- [ ] **Step 1 (developer): make the fake DOM record className, classList and style writes, in `tests/js/states_harness.mjs`.** First the file header, which still calls section 5.1's markup the future. Replace:

```js
 * The fake DOM matches the *future* markup section 5.1 describes (a stream
 * row and pill per mirror, #statFiles, [data-hostname] elements), since that
 * is the contract main.js implements ahead of the stylesheet and markup
 * switch later in this PR. One check (see "does not throw against today's
 * markup" below) instead builds today's sparser real markup, to prove every
 * lookup is null-safe against it.
```

with:

```js
 * The fake DOM matches the markup section 5.1 describes and index.html ships
 * (a stream row and pill per mirror, #statFiles, [data-hostname] elements).
 * One check (see "does not throw against markup with no stream rows" below)
 * instead builds a sparser page without them, to prove every lookup is
 * null-safe against it.
```

A check that only compares the final value against its starting value would miss a write that happens to repeat the starting value, so `makeEl` gains a `writes` array, shared by every element one `makePage()` call builds. The `className` setter pushes onto it; so does `classList.remove`, on the element and on the ancestor `closest()` returns, which is where the `.stat-card` removal lands; and `style` becomes a `Proxy` that does the same for every property set. Replace `makeEl`'s doc comment and body:

```js
/** One fake element: setAttribute/getAttribute (data-state), textContent,
 * className and a plain style object (legacy .pulse writes), plus a flat,
 * non-recursive querySelector into a caller-supplied child map -- the same
 * trade-off theme_harness.mjs's icon/toggle stubs make. `state`, given,
 * seeds data-state the way the shipped HTML does (section 5.2: "As shipped
 * in the HTML, before any data" is data-state="unknown"). */
function makeEl({ text = '', state = null, children = {} } = {}) {
    const attrs = new Map();
    if (state !== null) attrs.set('data-state', state);
    let textContent = text;
    let className = '';
    return {
        get textContent() { return textContent; },
        set textContent(v) { textContent = v; },
        get className() { return className; },
        set className(v) { className = v; },
        style: {},
        // .stat-card's ancestor and its "loading" class: the legacy
        // .stat-card loading removal does not need a real DOM tree to land
        // on, just something with a working classList so the call does not
        // throw.
        classList: { remove: () => {} },
        closest: () => ({ classList: { remove: () => {} } }),
        setAttribute: (name, value) => attrs.set(name, String(value)),
        getAttribute: (name) => (attrs.has(name) ? attrs.get(name) : null),
        querySelector: (sel) => children[sel] ?? null
    };
}
```

with:

```js
/** One fake element: setAttribute/getAttribute (data-state), textContent,
 * className, classList and style (all write-tracking, see `writes` below),
 * plus a flat, non-recursive querySelector into a caller-supplied child map
 * -- the same trade-off theme_harness.mjs's icon/toggle stubs make. `state`,
 * given, seeds data-state the way the shipped HTML does (section 5.2: "As
 * shipped in the HTML, before any data" is data-state="unknown").
 *
 * `writes`, when given, is one array shared by every element `makePage`
 * builds for a page. The className setter, classList.remove (the element's
 * own, and the one on the ancestor closest() finds) and a Proxy around style
 * each push a description onto it, so a check can assert that a whole
 * page's worth of elements were never written to -- not just that the final
 * value still looks untouched, which a write of the same value would hide. */
function makeEl({ text = '', state = null, children = {}, writes = null } = {}) {
    const attrs = new Map();
    if (state !== null) attrs.set('data-state', state);
    let textContent = text;
    let className = '';
    const style = new Proxy({}, {
        set(target, prop, value) {
            writes?.push(`style.${String(prop)} = ${JSON.stringify(value)}`);
            target[prop] = value;
            return true;
        }
    });
    // Records each call instead of tracking classes: no check reads a class
    // back, they only need to know whether one was ever touched.
    const recordingClassList = (owner) => ({
        remove: (name) => { writes?.push(`${owner}classList.remove(${JSON.stringify(name)})`); }
    });
    return {
        get textContent() { return textContent; },
        set textContent(v) { textContent = v; },
        get className() { return className; },
        set className(v) {
            writes?.push(`className = ${JSON.stringify(v)}`);
            className = v;
        },
        style,
        classList: recordingClassList(''),
        // The ancestor a closest() lookup lands on, such as the .stat-card
        // whose "loading" class main.js used to remove: a stand-in with a
        // recording classList of its own.
        closest: (sel) => ({ classList: recordingClassList(`closest(${JSON.stringify(sel)}).`) }),
        setAttribute: (name, value) => attrs.set(name, String(value)),
        getAttribute: (name) => (attrs.has(name) ? attrs.get(name) : null),
        querySelector: (sel) => children[sel] ?? null
    };
}
```

- [ ] **Step 2 (developer): thread `writes` through every element `makePage` builds.** Its doc comment also stops calling the sparse page "today's real markup". Replace:

```js
/** A fresh page. `minimal` builds today's real markup -- no stream rows, no
 * [data-hostname], no #statFiles -- everything else builds the future markup
 * section 5.1 describes, which is what most checks below drive. */
function makePage({ minimal = false, hostname = 'mirror.test' } = {}) {
    const mirrors = {};
    for (const id of ['freebsd', 'netbsd', 'openbsd']) {
        const statusText = makeEl({ text: 'Checking…' });
        const dot = makeEl({});
        const statusEl = makeEl({ state: 'unknown', children: { '.status-dot': dot, '.status-text': statusText } });

        const pillStatusText = makeEl({ text: 'Checking…' });
        const pill = makeEl({ state: 'unknown', children: { '.status-text': pillStatusText } });
        const stream = makeEl({ state: 'unknown', children: { '.pill': pill } });

        mirrors[id] = {
            statusEl, dot, statusText, stream, pill, pillStatusText,
            size: makeEl({ text: '--' }),
            sync: makeEl({ text: '--' }),
            dataHostname: makeEl({ text: '' })
        };
    }

    const overallTitle = makeEl({ text: 'Checking mirror status…' });
    const overallDesc = makeEl({ text: '' });
    const indicator = makeEl({});
    const pulse = makeEl({});
    const overall = makeEl({
        state: 'unknown',
        children: { h3: overallTitle, p: overallDesc, '.status-indicator': indicator, '.pulse': pulse }
    });
    overall.h3 = overallTitle;
    overall.p = overallDesc;
    overall.indicator = indicator;
    overall.pulse = pulse;

    const statSize = makeEl({ text: '—' });
    const statFiles = makeEl({ text: '—' });
    const statLastSync = makeEl({ text: '—' });
    const hostnameEl = makeEl({ text: '' });
    const rsynchostEl = makeEl({ text: '' });
```

with:

```js
/** A fresh page. `minimal` builds a sparser page -- no stream rows, no
 * [data-hostname], no #statFiles, as index.html was before section 5.1's
 * redesign -- everything else builds the markup section 5.1 describes, which
 * is what most checks below drive. */
function makePage({ minimal = false, hostname = 'mirror.test' } = {}) {
    // Shared by every element this page builds, so one check can assert that
    // no className, classList or style write happened anywhere on the page.
    const writes = [];
    const mirrors = {};
    for (const id of ['freebsd', 'netbsd', 'openbsd']) {
        const statusText = makeEl({ text: 'Checking…', writes });
        const dot = makeEl({ writes });
        const statusEl = makeEl({
            state: 'unknown', writes,
            children: { '.status-dot': dot, '.status-text': statusText }
        });

        const pillStatusText = makeEl({ text: 'Checking…', writes });
        const pill = makeEl({ state: 'unknown', writes, children: { '.status-text': pillStatusText } });
        const stream = makeEl({ state: 'unknown', writes, children: { '.pill': pill } });

        mirrors[id] = {
            statusEl, dot, statusText, stream, pill, pillStatusText,
            size: makeEl({ text: '--', writes }),
            sync: makeEl({ text: '--', writes }),
            dataHostname: makeEl({ text: '', writes })
        };
    }

    const overallTitle = makeEl({ text: 'Checking mirror status…', writes });
    const overallDesc = makeEl({ text: '', writes });
    const indicator = makeEl({ writes });
    const pulse = makeEl({ writes });
    const overall = makeEl({
        state: 'unknown', writes,
        children: { h3: overallTitle, p: overallDesc, '.status-indicator': indicator, '.pulse': pulse }
    });
    overall.h3 = overallTitle;
    overall.p = overallDesc;
    overall.indicator = indicator;
    overall.pulse = pulse;

    const statSize = makeEl({ text: '—', writes });
    const statFiles = makeEl({ text: '—', writes });
    const statLastSync = makeEl({ text: '—', writes });
    const hostnameEl = makeEl({ text: '', writes });
    const rsynchostEl = makeEl({ text: '', writes });
```

Then expose it on the page object. Replace:

```js
    return {
        load: () => MirrorStatus.load(),
        setHostname: () => setHostname(),
        setFetch: (impl) => { fetchImpl = impl; },
        mirrors,
        overall,
        statSize,
        statFiles,
        statLastSync,
        hostnameEl,
        rsynchostEl,
        dataHostnameEls
    };
}
```

with:

```js
    return {
        load: () => MirrorStatus.load(),
        setHostname: () => setHostname(),
        setFetch: (impl) => { fetchImpl = impl; },
        mirrors,
        overall,
        statSize,
        statFiles,
        statLastSync,
        hostnameEl,
        rsynchostEl,
        dataHostnameEls,
        writes
    };
}
```

- [ ] **Step 3 (developer): replace the two checks that expected the old writes with one that expects none.** Both drove one scenario each (an active mirror, a syncing mirror) and asserted the legacy elements *did* get written. The new check drives one scenario that would reach every legacy path at once: an active, a syncing and an error mirror, non-empty totals, and a `last_updated` so `#statLastSync` is written too. It asserts `writes` stays empty. The section comment above them and the null-safety check's name stop calling the sparse page "today's markup": since Task 4 the real page has stream rows. Replace:

```js
// ---------------------------------------------------------------------------
// Null-safety against today's real markup, and the legacy writes kept for now.
// ---------------------------------------------------------------------------
await check("load does not throw against today's markup, which has no stream rows", async () => {
```

with:

```js
// ---------------------------------------------------------------------------
// Null-safety against sparser markup, and the retired legacy writes.
// ---------------------------------------------------------------------------
await check('load does not throw against markup with no stream rows', async () => {
```

Then replace:

```js
await check('an active mirror still gets the legacy status-dot healthy class', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'active' }, NetBSD: { status: 'active' }, OpenBSD: { status: 'active' } },
        totals: {}
    }));
    await page.load();
    return expect(page.mirrors.freebsd.dot.className, 'status-dot healthy', 'dot className');
});

await check('a syncing mirror still drives the legacy status-indicator and pulse colour', async () => {
    const page = makePage();
    page.setFetch(async () => ok({
        mirrors: { FreeBSD: { status: 'active' }, NetBSD: { status: 'syncing' }, OpenBSD: { status: 'active' } },
        totals: {}
    }));
    await page.load();
    return all(
        expect(page.mirrors.netbsd.dot.className, 'status-dot syncing', 'dot className'),
        expect(page.overall.indicator.className, 'status-indicator syncing', 'indicator className'),
        expect(page.overall.pulse.style.background, 'var(--accent-primary)', 'pulse background')
    );
});

process.stdout.write(JSON.stringify(results));
```

with:

```js
await check(
    'the legacy status-dot, status-indicator, pulse and stat-card elements are present but never written',
    async () => {
        // One response that would reach every retired path: an active, a
        // syncing and an error mirror for the dot, indicator and pulse
        // writes, and totals.size plus a last_updated for the two .stat-card
        // "loading" removals.
        const page = makePage();
        const now = new Date().toISOString();
        page.setFetch(async () => ok({
            mirrors: {
                FreeBSD: { status: 'active', last_updated: now },
                NetBSD: { status: 'syncing' },
                OpenBSD: { status: 'error' }
            },
            totals: { size: '2.1 TB', files: '604,618' }
        }));
        await page.load();
        return page.writes.length === 0
            ? true
            : `unexpected className, classList or style writes: ${page.writes.join(', ')}`;
    }
);

process.stdout.write(JSON.stringify(results));
```

- [ ] **Step 4 (developer): update the docstring and the pinned list in `tests/test_public_states.py`.** The module docstring said the stream row is "markup this PR ships later", and that the three old writes "stay for now, because today's stylesheet and tests/js/contrast_harness.mjs still key off them". Both were true when Task 2 wrote them and false since Task 4. Replace:

```python
MirrorStatus now writes only a `data-state` attribute and a `.status-text`
word, on a mirror's card pill (#<id>-status), its stream row (#<id>-stream,
markup this PR ships later -- the lookup is null against today's page) and
the row's own .pill child alike, plus the overall card (#overallStatus),
whose title and sentence are chosen from every mirror's computed state at
once -- including the API-failure and no-mirror-online cases the old
className-only version could not represent. The three old writes stay for
now, because today's stylesheet and tests/js/contrast_harness.mjs still key
off them.

tests/js/states_harness.mjs runs the real main.js in a Node vm with a small
fake DOM (in tests/js/theme_harness.mjs's style) and stubbed fetch responses,
one per row of section 5.2's two tables plus these edge cases: an absent
mirror, an empty mirrors object, an API failure on the first load and after a
success, sentences naming two or three mirrors, the new #statFiles stat, the
[data-hostname] fill, and a run against today's sparser real markup to prove
every lookup is null-safe.
"""
```

with:

```python
MirrorStatus now writes only a `data-state` attribute and a `.status-text`
word, on a mirror's card pill (#<id>-status), its stream row (#<id>-stream)
and the row's own .pill child alike, plus the overall card (#overallStatus),
whose title and sentence are chosen from every mirror's computed state at
once -- including the API-failure and no-mirror-online cases the old
className-only version could not represent. The three old writes are gone,
and so is the .stat-card "loading" removal: style.css and
tests/js/contrast_harness.mjs key off data-state alone.

tests/js/states_harness.mjs runs the real main.js in a Node vm with a small
fake DOM (in tests/js/theme_harness.mjs's style) and stubbed fetch responses,
one per row of section 5.2's two tables plus these edge cases: an absent
mirror, an empty mirrors object, an API failure on the first load and after a
success, sentences naming two or three mirrors, the new #statFiles stat, the
[data-hostname] fill, a run against sparser markup with no stream rows to
prove every lookup is null-safe, and a run with the retired .status-dot,
.status-indicator, .pulse and .stat-card elements present to prove none of
them is ever written.
"""
```

Then replace the tail of `CHECKS`, renaming the null-safety check to match the harness:

```python
    # Null-safety against today's markup, and the legacy writes kept for now.
    "load does not throw against today's markup, which has no stream rows",
    "an active mirror still gets the legacy status-dot healthy class",
    "a syncing mirror still drives the legacy status-indicator and pulse colour",
]
```

with:

```python
    # Null-safety against sparser markup, and the retired legacy writes.
    "load does not throw against markup with no stream rows",
    "the legacy status-dot, status-indicator, pulse and stat-card elements are present but never written",
]
```

- [ ] **Step 5 (developer): run it and watch it fail.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_public_states.py; echo "rc=$?"`

Expected: `rc=1`, `1 failed, 23 passed, 4 warnings`. Only the new check fails, against Task 4's `main.js`, which still makes all seven of these writes:

```
AssertionError: unexpected className, classList or style writes: closest(".stat-card").classList.remove("loading"), closest(".stat-card").classList.remove("loading"), className = "status-dot healthy", className = "status-dot syncing", className = "status-dot error", className = "status-indicator degraded", style.background = "var(--status-error, #ef4444)"
```

In the order `load()` makes them: `updateStats`'s two `.stat-card` removals (one after `#statSize`, one after `#statLastSync`, which the `last_updated` reaches), the three `.status-dot` classNames (one per mirror: active, syncing, error), then `updateOverallStatus`'s error branch, which fires because one mirror is in error: the indicator's className and the pulse's `background`. The renamed null-safety check passes: its name changed in both files at once.

- [ ] **Step 6 (developer): remove the three write paths from `frontend/public/js/main.js`, and their markers.** `load()` stops calling the two legacy methods; replace:

```js
        this.updateMirrorStates(data.mirrors);
        this.updateStats(data);

        // --- Legacy, removed in Task 5: keeps today's .status-dot,
        // .status-indicator and .pulse writes going, alongside the
        // data-state model above, until the stylesheet that reads them is
        // replaced later in this PR. ---
        this.updateMirrorCards(data.mirrors);
        this.updateOverallStatus(data.mirrors);
    },
```

with:

```js
        this.updateMirrorStates(data.mirrors);
        this.updateStats(data);
    },
```

Then the `.stat-card` loading removal comes out of `updateStats`, and the two methods it fed are deleted outright, down to `formatRelativeTime`. Replace:

```js
    updateStats(data) {
        const statSize = document.getElementById('statSize');
        if (statSize && data.totals?.size) {
            statSize.textContent = data.totals.size;
            // --- Legacy, removed in Task 5: today's markup starts this
            // stat-card "loading"; the new markup this PR ships later
            // will not. ---
            statSize.closest('.stat-card')?.classList.remove('loading');
        }

        const statFiles = document.getElementById('statFiles');
        if (statFiles && data.totals?.files) {
            statFiles.textContent = data.totals.files;
        }

        const statLastSync = document.getElementById('statLastSync');
        if (statLastSync && data.mirrors) {
            const syncs = Object.values(data.mirrors)
                .map(m => m.last_updated)
                .filter(Boolean)
                .sort()
                .reverse();
            if (syncs.length > 0) {
                statLastSync.textContent = this.formatRelativeTime(new Date(syncs[0]));
                // --- Legacy, removed in Task 5: see above. ---
                statLastSync.closest('.stat-card')?.classList.remove('loading');
            }
        }
    },

    // --- Legacy: rewrites .status-dot's className, exactly as today.
    // Removed in Task 5 (docs/design/2026-09-25-reflection-redesign.md,
    // section 5.2 "Changes": "Data attributes, not class rewrites"). The
    // data-state model above already recomputes every mirror's state and its
    // .status-text; #<id>-size and #<id>-sync moved there too, so this keeps
    // only the one write nothing else needs. ---
    updateMirrorCards(mirrors) {
        for (const [name, mirror] of Object.entries(mirrors)) {
            const lowerName = name.toLowerCase();
            const statusEl = document.getElementById(`${lowerName}-status`);
            const dot = statusEl?.querySelector('.status-dot');
            if (!dot) continue;

            const statusClassMap = {
                'active': 'healthy',
                'syncing': 'syncing',
                'error': 'error',
                'disabled': ''
            };
            const statusClass = statusClassMap[mirror.status] || '';
            dot.className = 'status-dot' + (statusClass ? ' ' + statusClass : '');
        }
    },

    // --- Legacy: rewrites .status-indicator's className and .pulse's inline
    // background, exactly as today -- including today's own "all mirrors
    // online" logic, not the fixed table updateOverallState uses above.
    // Removed in Task 5. ---
    updateOverallStatus(mirrors) {
        const statusCard = document.getElementById('overallStatus');
        if (!statusCard) return;

        const statuses = Object.values(mirrors).map(m => m.status);
        const anyError = statuses.includes('error');
        const anySyncing = statuses.includes('syncing');
        const allActive = statuses.every(s => s === 'active');

        const indicator = statusCard.querySelector('.status-indicator');
        const pulse = statusCard.querySelector('.pulse');
        if (!indicator) return;

        if (anyError) {
            indicator.className = 'status-indicator degraded';
            if (pulse) pulse.style.background = 'var(--status-error, #ef4444)';
        } else if (anySyncing) {
            indicator.className = 'status-indicator syncing';
            if (pulse) pulse.style.background = 'var(--accent-primary)';
        } else if (allActive) {
            indicator.className = 'status-indicator healthy';
            if (pulse) pulse.style.background = 'var(--status-healthy)';
        } else {
            indicator.className = 'status-indicator healthy';
            if (pulse) pulse.style.background = 'var(--status-healthy)';
        }
    },

    formatRelativeTime(date) {
```

with:

```js
    updateStats(data) {
        const statSize = document.getElementById('statSize');
        if (statSize && data.totals?.size) {
            statSize.textContent = data.totals.size;
        }

        const statFiles = document.getElementById('statFiles');
        if (statFiles && data.totals?.files) {
            statFiles.textContent = data.totals.files;
        }

        const statLastSync = document.getElementById('statLastSync');
        if (statLastSync && data.mirrors) {
            const syncs = Object.values(data.mirrors)
                .map(m => m.last_updated)
                .filter(Boolean)
                .sort()
                .reverse();
            if (syncs.length > 0) {
                statLastSync.textContent = this.formatRelativeTime(new Date(syncs[0]));
            }
        }
    },

    formatRelativeTime(date) {
```

Two comments still describe the stream rows as markup to come. In the `MirrorStatus` header, replace:

```js
// docs/design/2026-09-25-reflection-redesign.md, section 5.2. Each mirror's
// card pill (#<id>-status), its stream row (#<id>-stream -- markup PR 2 adds
// later; on today's page the lookup is simply null) and the row's own .pill
// child all carry a data-state the stylesheet keys off, plus a worded
// .status-text. The overall card gets the same treatment, with its own
```

with:

```js
// docs/design/2026-09-25-reflection-redesign.md, section 5.2. Each mirror's
// card pill (#<id>-status), its stream row (#<id>-stream) and the row's own
// .pill child all carry a data-state the stylesheet keys off, plus a worded
// .status-text. The overall card gets the same treatment, with its own
```

And above `paintState`, replace:

```js
// Writes data-state and, where the element has one, its .status-text. Used
// for a mirror's card pill, its stream row, and the row's own .pill child
// alike -- every argument may be null or undefined, since the stream row and
// its pill do not exist until PR 2's new markup ships.
```

with:

```js
// Writes data-state and, where the element has one, its .status-text. Used
// for a mirror's card pill, its stream row, and the row's own .pill child
// alike. Any of them may be missing (null or undefined), and is skipped: a
// page without stream rows still gets its card pills painted.
```

The removal also takes out `main.js`'s last `var(--x)` reads, the three the `.pulse` writes used (`--status-error`, `--accent-primary`, `--status-healthy`). `tests/test_admin_js_escaping.py` checks every `var(--x)` read in `main.js` and `admin.js` against `tokens.css`, and the comment above that check says both files set inline styles from `var(--token)`; neither does now. In `tests/test_admin_js_escaping.py`, replace:

```python
# CSS custom properties read from JavaScript
#
# Both files set inline styles from var(--token). A token defined nowhere
# silently falls back to the inherited value, or to the literal fallback --
# which pins one theme's colour in both themes.
```

with:

```python
# CSS custom properties read from JavaScript
#
# Neither file reads a var(--token) any more: admin.js's inline styles moved
# into classes, and main.js's last reads went with its .pulse writes (spec
# section 5.2). The check stays for any read either file adds: a token
# defined nowhere silently falls back to the inherited value, or to the
# literal fallback -- which pins one theme's colour in both themes.
```

- [ ] **Step 7 (developer): confirm nothing is left.** `main.js` now assigns no `className` and no style anywhere, and removes no class from a mirror or stat element.

Run: `grep -n "className\|\.style\b\|classList" frontend/public/js/main.js`

Expected:

```
94:// className-only version could not represent (every() over an empty mirror
325:        toast.classList.add('show');
328:            toast.classList.remove('show');
```

Line 94 is prose inside a comment, describing the old behaviour, not a write. The one live pair left is the toast's own `classList.add('show')` / `classList.remove('show')` around its timeout (`Toast.show`): a class change unrelated to mirror status, and out of this task's scope.

Run: `grep -n "var(--" frontend/public/js/main.js frontend/public/admin/js/admin.js`

Expected: no output, as the new comment in `tests/test_admin_js_escaping.py` says.

- [ ] **Step 8 (devops-sre): drop the `.pulse` example from the CSP comment in `nginx/nginx.conf`.** Spec section 8, "Housekeeping in PR 1": "The `.pulse` writes stay until PR 2, which removes that part of the comment. The toast write stays until PR 3, which removes the rest." Find the exact text:

Run: `grep -n "pulse" nginx/nginx.conf`

Expected:

```
199:    #                         '...'` applies (the status pulse's
200:    #                         `pulse.style.background` in js/main.js, the
```

Replace:

```nginx
    #                         '...'` applies (the status pulse's
    #                         `pulse.style.background` in js/main.js, the
    #                         toast's `toast.style.animation` in
    #                         admin/js/admin.js) and so does `el.style.cssText`.
```

with:

```nginx
    #                         '...'` applies (the admin toast's
    #                         `toast.style.animation` in admin/js/admin.js)
    #                         and so does `el.style.cssText`.
```

The admin toast's example, which PR 3 removes, stays. Confirm the pulse is gone from the file:

Run: `grep -n "pulse" nginx/nginx.conf`

Expected: no output.

Confirm no test pins the wording removed here:

Run: `grep -rn "pulse.style.background\|status pulse" tests/`

Expected: no output. The one test that reads `nginx.conf` (`tests/test_public_page_csp.py`'s `nginx_csp()`) parses only the `map $host $csp_policy { default "..."; }` value, not this comment.

- [ ] **Step 9 (developer): run green, check the check, lint, contrast, and the whole suite.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_public_states.py; echo "rc=$?"`

Expected: `24 passed, 4 warnings`, `rc=0`.

Mutation check: put back only the `#statSize` card's `.stat-card` removal, in a copy of `main.js`, and read the new check's result straight from the harness:

```bash
docker compose run --rm -T test bash -c 'cp frontend/public/js/main.js /tmp/main.js && sed -i "s|statSize.textContent = data.totals.size;|&\n            statSize.closest(\".stat-card\")?.classList.remove(\"loading\");|" /tmp/main.js && node tests/js/states_harness.mjs /tmp/main.js 2>/dev/null | python3 -c "import json, sys; print(json.load(sys.stdin)[\"the legacy status-dot, status-indicator, pulse and stat-card elements are present but never written\"])"'
```

Expected: `[False, 'unexpected className, classList or style writes: closest(".stat-card").classList.remove("loading")']`. The check sees that one write alone. The copy lives in the container's `/tmp`, so nothing needs restoring.

Run the lint pair on the two Python files this task touches. Both are clean on the first run.
`docker compose run --rm -T test ruff check tests/test_public_states.py tests/test_admin_js_escaping.py; echo "rc=$?"` -> no output, `rc=0`.
`docker compose run --rm -T test ruff format --check tests/test_public_states.py tests/test_admin_js_escaping.py; echo "rc=$?"` -> `2 files already formatted`, `rc=0`.

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_contrast.py; echo "rc=$?"`

Expected: `218 passed, 4 warnings`, `rc=0`. This harness's checks fail on any page JS error, so a green run also shows `main.js` still parses and runs under headless Chrome with the three paths gone.

Run: `docker compose run --rm -T test; echo "rc=$?"`

Expected: `1529 passed, 7 warnings`, `rc=0`: one fewer than Task 4's `1530`, because two parametrised legacy-behaviour cases came out of `CHECKS` and one replaced them. Read the exit code directly, not through a `tail`.

- [ ] **Step 10 (developer): commit.**

```bash
git add frontend/public/js/main.js nginx/nginx.conf tests/js/states_harness.mjs tests/test_public_states.py tests/test_admin_js_escaping.py
git commit -m "Remove the old status class and style writes"
```

### Task 6: Bind the page-wide copy buttons and click them under the CSP

Section 5.1 gives the public page three more copy buttons beyond the
per-mirror "rsync URL" ones: the hero's "Copy rsync URL" button
(`data-copy="rsync-root"`) and the two access-row icon buttons
(`data-copy="https-root"`, `data-copy="rsync-root"`). Task 4 shipped their
markup; nothing has bound them since. This task is TDD end to end for that
binding: prove the gap with a real click first, then close it.

The binding was originally going to land as part of Task 2, alongside
`MirrorStatus`. A review of that plan found the same problem the whole
`tests/test_public_page_csp.py` file exists to catch in the first place --
code that looks wired (a function exists, is called from `DOMContentLoaded`)
but was never proven to run from an actual click -- so it moved here, where
`tests/js/csp_click_harness.mjs` can click it for real before it exists.
Because Task 2 never added it, today's `main.js` (as Task 5 left it) has no
`[data-copy]` binding at all: the red proof needs no reverting, just running
the new tests against what is already there.

`tests/js/csp_click_harness.mjs` drives real headless Chrome and always has
`navigator.clipboard`, so it cannot exercise the guard the new `copyUrl()`
helper adds: outside a secure context, and in older browsers,
`navigator.clipboard` itself is `undefined`, not a promise that rejects. That
path gets a second, small harness in the style of
`footer_version_harness.mjs` -- a Node `vm`, not a browser -- since removing
`navigator.clipboard` from an already-started Chrome to test the same thing
would be testing a browser quirk, not the guard.

`copyRsync`, behind the per-mirror buttons, has the same gap: it calls
`navigator.clipboard.writeText` unguarded, so with no Clipboard API a click
throws a `TypeError` instead of toasting. Spec section 5.2 lists the
per-mirror `data-copy-rsync` buttons as unchanged, so this task leaves
`copyRsync` as it is. Routing it through the guarded `copyUrl()` is a
follow-up after PR 2.

**Files:**
- Modify: `tests/js/csp_click_harness.mjs`
- Modify: `tests/test_public_page_csp.py`
- Create: `tests/js/copy_buttons_harness.mjs`, `tests/test_copy_buttons.py`
- Modify: `frontend/public/js/main.js`

- [ ] **Step 1 (developer): click every `[data-copy]` button too, in `tests/js/csp_click_harness.mjs`.** Today's per-mirror loop (`.mirror-actions button`, matched by index, with its negative control) stays exactly as it is; a second pass over `[data-copy]` follows it, with the same mechanics (clear the toast, hit-test the click point, dispatch a real trusted click, read the toast back), a different selector, and no `onclick`/`dataset.copyRsync` wiring to report, since these buttons have no inline-handler history to guard against. First, the doc comment. Replace:

```js
/**
 * Does clicking "Copy rsync URL" do anything, under the production CSP?
 *
 * Static inspection is what missed this bug in the first place -- an
 * onclick="..." attribute looks like working code -- so this harness does not
 * inspect. It serves frontend/public over HTTP with the exact
 * Content-Security-Policy from nginx/nginx.conf, drives real headless Chrome
 * over the DevTools Protocol, dispatches a genuine trusted mouse click on each
 * button, and reports what the page did.
 *
 * No npm packages: node's built-in http and WebSocket only, and whatever
 * Chrome is already installed.
 *
 * Usage:  node csp_click_harness.mjs <docroot> [chrome-binary]
 * Output: JSON {"buttons":[...], "cspViolations":[...]} on stdout.
 */
```

with:

```js
/**
 * Does clicking a copy button do anything, under the production CSP?
 *
 * Static inspection is what missed this bug in the first place -- an
 * onclick="..." attribute looks like working code -- so this harness does not
 * inspect. It serves frontend/public over HTTP with the exact
 * Content-Security-Policy from nginx/nginx.conf, drives real headless Chrome
 * over the DevTools Protocol, dispatches a genuine trusted mouse click on
 * every copy button on the page, and reports what each one did:
 *   - the three per-mirror "rsync URL" buttons (.mirror-actions button,
 *     matched by index, as today);
 *   - the three page-wide [data-copy] buttons: the hero's "Copy rsync URL"
 *     button, then the two access-row icon buttons
 *     (docs/design/2026-09-25-reflection-redesign.md, section 5.1).
 *
 * No npm packages: node's built-in http and WebSocket only, and whatever
 * Chrome is already installed.
 *
 * Usage:  node csp_click_harness.mjs <docroot> [chrome-binary]
 * Output: JSON {"buttons":[...], "dataCopyButtons":[...], "cspViolations":[...]} on stdout.
 */
```

Then the loop itself and the output line. Replace:

```js
        buttons.push({ ...wiring[i], toast });
    }

    process.stdout.write(JSON.stringify({
        docroot: DOCROOT, csp: CSP, buttons, cspViolations, consoleErrors
    }, null, 2) + '\n');
```

with:

```js
        buttons.push({ ...wiring[i], toast });
    }

    // After the per-mirror loop above: the page-wide [data-copy] buttons.
    // Same mechanics -- clear the toast, hit-test the click point, dispatch a
    // real trusted click, read the toast back -- just a different selector
    // and no onclick/dataset-copyRsync wiring to report, since these buttons
    // have no inline-handler history to guard against.
    const dataCopyWiring = await evaluate(`
        Array.from(document.querySelectorAll('[data-copy]')).map(b => ({
            dataCopy: b.dataset.copy ?? null
        }))
    `);

    const dataCopyButtons = [];
    for (let i = 0; i < dataCopyWiring.length; i++) {
        await evaluate(`(() => { const t = document.getElementById('toast');
                                 if (t) { t.textContent = ''; t.classList.remove('show'); } })()`);

        const box = await evaluate(`(() => {
            const b = document.querySelectorAll('[data-copy]')[${i}];
            b.scrollIntoView({ block: 'center', behavior: 'instant' });
            const r = b.getBoundingClientRect();
            const el = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
            return {
                x: r.x + r.width / 2, y: r.y + r.height / 2,
                hits: Boolean(el) && Boolean(el.closest('[data-copy], button'))
            };
        })()`);
        if (!box.hits) throw new Error(`data-copy button ${i} is not under its own click point (${box.x}, ${box.y})`);

        for (const type of ['mousePressed', 'mouseReleased']) {
            await cdp.send('Input.dispatchMouseEvent', {
                type, x: box.x, y: box.y, button: 'left', clickCount: 1
            }, sessionId);
        }
        await sleep(350);

        const toast = await evaluate(`(() => { const t = document.getElementById('toast');
            return t ? { text: t.textContent, shown: t.classList.contains('show') } : null; })()`);

        dataCopyButtons.push({ ...dataCopyWiring[i], toast });
    }

    process.stdout.write(JSON.stringify({
        docroot: DOCROOT, csp: CSP, buttons, dataCopyButtons, cspViolations, consoleErrors
    }, null, 2) + '\n');
```

This changes neither the argv shape (`<docroot> [chrome-binary]`), the "did not expose a DevTools endpoint" error, nor the kill-on-failure behaviour that `tests/test_chrome_harness_start.py` pins for this harness -- all three live entirely above this point in the file, untouched.

- [ ] **Step 2 (developer): assert on those clicks, in `tests/test_public_page_csp.py`.** Two tests, in the "Behavioural: a real click, in a real browser, under the real policy" section, right after the existing per-mirror `test_copy_button_responds_to_a_real_click`. The first pins the harness's own findings (order matches document order: the hero's button, then the two access rows'); the second is the parametrised behavioural check, keyed to the harness's `127.0.0.1` origin so each expected URL can be asserted in full rather than by substring. `test_no_csp_violations_on_load`, a few lines above and already module-scoped over the same `clicked` fixture, covers "no CSP violation" for these clicks too -- it runs once per harness invocation, not once per test. Replace:

```python
    assert (
        f"/{mirror}/" in button["toast"]["text"]
    ), f"{mirror} button copied the wrong URL: {button['toast']['text']!r}"


# ---------------------------------------------------------------------------
# Negative control
```

with:

```python
    assert (
        f"/{mirror}/" in button["toast"]["text"]
    ), f"{mirror} button copied the wrong URL: {button['toast']['text']!r}"


@requires_browser
def test_all_data_copy_buttons_are_found(clicked):
    """Document order: the hero's button, then the two access rows'
    (docs/design/2026-09-25-reflection-redesign.md, section 5.1)."""
    assert [b["dataCopy"] for b in clicked["dataCopyButtons"]] == [
        "rsync-root",
        "https-root",
        "rsync-root",
    ]


@requires_browser
@pytest.mark.parametrize(
    "index,data_copy,scheme",
    [(0, "rsync-root", "rsync"), (1, "https-root", "https"), (2, "rsync-root", "rsync")],
)
def test_data_copy_button_responds_to_a_real_click(clicked, index, data_copy, scheme):
    """The click harness serves on 127.0.0.1, so that is the host each built
    URL names. test_no_csp_violations_on_load already covers this same run,
    clicks included."""
    button = clicked["dataCopyButtons"][index]
    assert button["dataCopy"] == data_copy
    assert button["toast"][
        "shown"
    ], f"clicking the {data_copy} button produced no toast; the handler did not run"
    assert (
        button["toast"]["text"] == f"Copied: {scheme}://127.0.0.1/"
    ), f"{data_copy} button copied the wrong URL: {button['toast']['text']!r}"


# ---------------------------------------------------------------------------
# Negative control
```

- [ ] **Step 3 (developer): create `tests/js/copy_buttons_harness.mjs`.** A Node `vm` harness, in `footer_version_harness.mjs`'s style, for the one behaviour a real browser cannot easily be made to exhibit: a missing Clipboard API. It binds `main.js`'s real `bindDataCopyButtons()` against one fake `[data-copy]` button, fires a genuine click through the same `addEventListener` path the real page uses (not a direct call to the URL-copying helper, so the binding itself is exercised too), and reports the toast.

```js
/**
 * Copy-button harness for the page-wide [data-copy] buttons in
 * frontend/public/js/main.js.
 *
 * docs/design/2026-09-25-reflection-redesign.md, section 5.1. Binds the real
 * bindDataCopyButtons() against a fake [data-copy] button, fires a genuine
 * click through the same addEventListener path the page uses, and reports
 * what the toast said.
 *
 * tests/js/csp_click_harness.mjs already proves, in a real browser under the
 * production CSP, that these buttons copy the right URL -- but a real
 * browser always has navigator.clipboard, so it cannot exercise the guard
 * copyUrl() adds: outside a secure context, and in older browsers,
 * navigator.clipboard is undefined, not a promise that rejects. Missing that
 * check turns a click into a thrown TypeError instead of the "Failed to copy
 * URL" toast a rejected write gets. (The per-mirror copyRsync has no such
 * guard: spec section 5.2 keeps those buttons unchanged.) Deleting
 * navigator.clipboard from an already-started Chrome to test that would be a
 * browser quirk in its own right; a Node vm with no clipboard property at
 * all asks the question directly.
 *
 * There is no JS test runner in this repo (see escaping_harness.mjs, which
 * this follows): load the real main.js into a vm context with the smallest
 * DOM/navigator stub it needs, run a fixed list of scenarios, and report
 * which ones behaved.
 *
 * Usage:  node copy_buttons_harness.mjs <path-to-main.js>
 * Output: JSON {"checks":[{"name","ok","detail"}]} on stdout.
 *
 * Exit status is 0 even when checks fail: pytest reads the JSON and decides.
 */
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const sourcePath = process.argv[2];
const source = readFileSync(sourcePath, 'utf8');

const checks = [];
function check(name, ok, detail = '') {
    checks.push({ name, ok: !!ok, detail: String(detail) });
}

// main.js has no exports; the vm's completion value is how this gets at the
// binder (escaping_harness.mjs's EPILOGUE trick, also used by
// footer_version_harness.mjs and states_harness.mjs).
const EPILOGUE = `\n;({ bindDataCopyButtons });\n`;

/** One fake [data-copy] button: dataset.copy plus an addEventListener that
 * remembers its click handler for the harness to fire directly, since this
 * vm's DOM has no real event dispatch. */
function makeButton(dataCopy) {
    let onClick = null;
    return {
        dataset: { copy: dataCopy },
        addEventListener(type, handler) {
            if (type === 'click') onClick = handler;
        },
        click() {
            onClick?.();
        }
    };
}

/**
 * Bind main.js's real [data-copy] buttons against one fake button carrying
 * `dataCopy`, click it, and report what happened:
 *   - clipboardCalledWith: the URL passed to navigator.clipboard.writeText,
 *     or null if it was never called -- the no-clipboard guard path, or an
 *     unrecognised data-copy value that was never bound at all.
 *   - toastText/toastShown: #toast's state once the click's microtasks have
 *     settled. toastText is null if its setter was never touched.
 *   - threw: the error the click raised synchronously, if any -- the guard
 *     this harness exists to check is precisely what keeps this null.
 */
async function runScenario({ dataCopy, hasClipboard, hostname = 'mirror.test' }) {
    const button = makeButton(dataCopy);

    let toastText = null;
    let toastShown = false;
    const toast = {
        get textContent() { return toastText; },
        set textContent(v) { toastText = v; },
        classList: {
            add: (name) => { if (name === 'show') toastShown = true; },
            remove: (name) => { if (name === 'show') toastShown = false; }
        }
    };

    let clipboardCalledWith = null;
    const navigator = hasClipboard
        ? { clipboard: { writeText: (url) => { clipboardCalledWith = url; return Promise.resolve(); } } }
        : {};

    const sandbox = {
        console,
        setTimeout: () => 0,
        clearTimeout: () => {},
        document: {
            addEventListener: () => {},
            getElementById: (id) => (id === 'toast' ? toast : null),
            querySelectorAll: (sel) => (sel === '[data-copy]' ? [button] : [])
        },
        window: { location: { hostname } },
        navigator
    };
    sandbox.globalThis = sandbox;

    const mod = vm.runInNewContext(source + EPILOGUE, sandbox, { filename: sourcePath });
    mod.bindDataCopyButtons();

    let threw = null;
    try {
        button.click();
        // copyUrl's toast comes out of a Promise .then()/.catch(), which
        // settles on a microtask -- after click() returns, not during it.
        // This await runs on the harness's own, non-sandboxed event loop, so
        // one real macrotask trip is enough to let every microtask ahead of
        // it drain first.
        await new Promise((resolve) => setTimeout(resolve, 0));
    } catch (err) {
        threw = err;
    }

    return { toastText, toastShown, clipboardCalledWith, threw };
}

// ---------------------------------------------------------------------------
// Scenarios
// ---------------------------------------------------------------------------
const run = async () => {
    // Positive control: with the Clipboard API present, a bound button
    // copies its builder's URL and shows the toast. Without this passing
    // first, the guard check below would prove nothing -- it would also pass
    // for a harness that never actually clicked anything.
    {
        const r = await runScenario({ dataCopy: 'rsync-root', hasClipboard: true, hostname: 'mirror.test' });
        check(
            'a bound data-copy button copies its built URL and shows the toast',
            r.threw === null && r.clipboardCalledWith === 'rsync://mirror.test/'
                && r.toastShown && r.toastText === 'Copied: rsync://mirror.test/',
            r.threw
                ? `threw: ${r.threw}`
                : `clipboardCalledWith=${JSON.stringify(r.clipboardCalledWith)} `
                    + `toastShown=${r.toastShown} toastText=${JSON.stringify(r.toastText)}`
        );
    }

    // The guard this harness exists to check.
    {
        const r = await runScenario({ dataCopy: 'https-root', hasClipboard: false, hostname: 'mirror.test' });
        check(
            'a data-copy click with no navigator.clipboard toasts Failed to copy URL instead of throwing',
            r.threw === null && r.clipboardCalledWith === null
                && r.toastShown && r.toastText === 'Failed to copy URL',
            r.threw
                ? `threw: ${r.threw}`
                : `clipboardCalledWith=${JSON.stringify(r.clipboardCalledWith)} `
                    + `toastShown=${r.toastShown} toastText=${JSON.stringify(r.toastText)}`
        );
    }

    // An unrecognised data-copy value (e.g. a future markup typo) is left
    // unbound, not wired to a builder that would throw on `undefined`.
    {
        const r = await runScenario({ dataCopy: 'bogus', hasClipboard: true, hostname: 'mirror.test' });
        check(
            'an unrecognised data-copy value is left unbound rather than throwing',
            r.threw === null && r.clipboardCalledWith === null && !r.toastShown,
            r.threw
                ? `threw: ${r.threw}`
                : `clipboardCalledWith=${JSON.stringify(r.clipboardCalledWith)} toastShown=${r.toastShown}`
        );
    }
};

let loadError = null;
try {
    await run();
} catch (err) {
    loadError = err;
}

if (loadError) {
    process.stdout.write(JSON.stringify({
        loadError: `${loadError && loadError.stack ? loadError.stack : loadError}`,
        checks: []
    }));
} else {
    process.stdout.write(JSON.stringify({ checks }));
}
```

- [ ] **Step 4 (developer): create `tests/test_copy_buttons.py`.** Same shape as `test_footer_version.py`'s "Frontend wiring" section: run the harness once per module, a pinned `CHECKS` list, one parametrised test per check plus a completeness test. No mutation testing here -- unlike `main.js`'s bigger, longer-lived surfaces (`FooterVersion`, `MirrorStatus`), this is one small guard, and the click-based checks above already prove the binding itself.

```python
"""
The page-wide [data-copy] buttons: bound, and safe with no Clipboard API.

docs/design/2026-09-25-reflection-redesign.md, section 5.1. The hero's "Copy
rsync URL" button and the two access-row icon buttons carry a data-copy
attribute (rsync-root or https-root), separately from the per-mirror buttons'
data-copy-rsync wiring test_public_page_csp.py already covers.
tests/js/csp_click_harness.mjs proves, in a real browser under the production
CSP, that clicking each one shows the right toast -- but a real browser
always has navigator.clipboard, so it cannot exercise the guard copyUrl()
adds: outside a secure context, and in older browsers, navigator.clipboard is
undefined rather than a promise that rejects, so a missing guard turns a
click into a thrown TypeError instead of the "Failed to copy URL" toast a
rejected write gets. The per-mirror copyRsync has no such guard: spec section
5.2 keeps those buttons unchanged.

tests/js/copy_buttons_harness.mjs runs the real main.js in a Node vm (there is
no JS test runner in this repo -- see test_admin_js_escaping.py for the same
approach against admin.js), binds its real bindDataCopyButtons() against a
fake button, fires a genuine click through the same addEventListener path the
page uses, and reports what the toast said.
"""

import json
import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MAIN_JS = REPO_ROOT / "frontend" / "public" / "js" / "main.js"
HARNESS = REPO_ROOT / "tests" / "js" / "copy_buttons_harness.mjs"

NODE = shutil.which("node")
requires_node = pytest.mark.skipif(
    NODE is None, reason="node is not installed; the copy-button behaviour checks cannot run"
)


@pytest.fixture(scope="module")
def harness_results():
    proc = subprocess.run(
        [NODE, str(HARNESS), str(MAIN_JS)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert not payload.get("loadError"), f"harness failed to load main.js: {payload['loadError']}"
    return {c["name"]: (c["ok"], c["detail"]) for c in payload["checks"]}


CHECKS = [
    "a bound data-copy button copies its built URL and shows the toast",
    "a data-copy click with no navigator.clipboard toasts Failed to copy URL instead of throwing",
    "an unrecognised data-copy value is left unbound rather than throwing",
]


@requires_node
@pytest.mark.parametrize("name", CHECKS)
def test_copy_button_behaviour(harness_results, name):
    assert (
        name in harness_results
    ), f"harness did not run {name!r}; it reported {sorted(harness_results)}"
    ok, detail = harness_results[name]
    assert ok, detail


@requires_node
def test_the_harness_runs_exactly_these_checks(harness_results):
    """The parametrised list must not drift behind the harness."""
    assert sorted(harness_results) == sorted(CHECKS)
```

- [ ] **Step 5 (developer): run the tests, and watch them fail.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_copy_buttons.py tests/test_public_page_csp.py tests/test_chrome_harness_start.py; echo "rc=$?"`

Expected: `rc=1`, `3 failed, 23 passed, 4 warnings, 4 errors`. Two distinct causes, both against Task 5's `main.js`, which has no `[data-copy]` binding at all (Task 2 never added it):

- **All four of `tests/test_copy_buttons.py`'s tests error at fixture setup**, not fail: its module-scoped `harness_results` fixture raises before any test body runs, because loading `main.js` into the vm and immediately calling the epilogue's `bindDataCopyButtons` throws:

```
AssertionError: harness failed to load main.js: /repo/frontend/public/js/main.js:383
;({ bindDataCopyButtons });
    ^

ReferenceError: bindDataCopyButtons is not defined
```

- **The three parametrised `test_data_copy_button_responds_to_a_real_click` cases in `tests/test_public_page_csp.py` fail**, cleanly, one per button: a real click on an unbound `[data-copy]` button does nothing, so the toast this test looks for was never shown. The first reads:

```
AssertionError: clicking the rsync-root button produced no toast; the handler did not run
assert False
```

`test_all_data_copy_buttons_are_found` and `test_no_csp_violations_on_load` pass regardless: finding three static buttons, and raising no CSP violation while clicking dead ones, don't depend on any binding existing.

- [ ] **Step 6 (developer): add the binding, in `frontend/public/js/main.js`.** `copyRsync` and `bindCopyRsyncButtons()`, just above, stay byte-identical, because spec section 5.2 lists the per-mirror `data-copy-rsync` buttons as unchanged. The new pieces sit right after them: a `COPY_URL_BUILDERS` map keyed by `data-copy` value, a `copyUrl()` helper sharing `copyRsync`'s two toasts plus a guard for a missing Clipboard API, which `copyRsync` lacks too, and a `bindDataCopyButtons()` that wires `[data-copy]` elements the same way `bindCopyRsyncButtons()` wires `[data-copy-rsync]` ones. Replace:

```js
function bindCopyRsyncButtons() {
    document.querySelectorAll('[data-copy-rsync]').forEach(btn => {
        btn.addEventListener('click', () => copyRsync(btn.dataset.copyRsync));
    });
}

// Set hostname in UI
```

with:

```js
function bindCopyRsyncButtons() {
    document.querySelectorAll('[data-copy-rsync]').forEach(btn => {
        btn.addEventListener('click', () => copyRsync(btn.dataset.copyRsync));
    });
}

// Copy helper shared by the page-wide [data-copy] buttons: the hero's "Copy
// rsync URL" button and the two access-row icon buttons
// (docs/design/2026-09-25-reflection-redesign.md, section 5.1). Each maps to
// a URL builder keyed by its data-copy value.
const COPY_URL_BUILDERS = {
    'rsync-root': hostname => `rsync://${hostname}/`,
    'https-root': hostname => `https://${hostname}/`
};

// Same toasts as copyRsync above, plus a guard for a missing Clipboard API:
// outside a secure context and in older browsers, navigator.clipboard itself
// is undefined rather than a rejected promise. Without this check that reads
// as a thrown error, not one the .catch() below ever sees. copyRsync has the
// same gap, left alone because spec section 5.2 keeps the per-mirror buttons
// unchanged.
function copyUrl(url) {
    if (!navigator.clipboard) {
        Toast.show('Failed to copy URL');
        return;
    }
    navigator.clipboard.writeText(url).then(() => {
        Toast.show(`Copied: ${url}`);
    }).catch(() => {
        Toast.show('Failed to copy URL');
    });
}

// Wire up the page-wide copy buttons, the same way bindCopyRsyncButtons()
// above wires the per-mirror ones. An unrecognised data-copy value is left
// unbound rather than wired to a builder that does not exist.
function bindDataCopyButtons() {
    document.querySelectorAll('[data-copy]').forEach(btn => {
        const build = COPY_URL_BUILDERS[btn.dataset.copy];
        if (!build) return;
        btn.addEventListener('click', () => copyUrl(build(window.location.hostname)));
    });
}

// Set hostname in UI
```

Then call it from `DOMContentLoaded`, next to `bindCopyRsyncButtons()`. Replace:

```js
    ThemeManager.init();
    setHostname();
    bindCopyRsyncButtons();
    MirrorStatus.load();
```

with:

```js
    ThemeManager.init();
    setHostname();
    bindCopyRsyncButtons();
    bindDataCopyButtons();
    MirrorStatus.load();
```

- [ ] **Step 7 (developer): run green.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_copy_buttons.py tests/test_public_page_csp.py tests/test_chrome_harness_start.py tests/test_public_states.py; echo "rc=$?"`

Expected: `54 passed, 4 warnings`, `rc=0`. `tests/test_public_states.py` is included as a check that `main.js`'s existing `MirrorStatus` behaviour is unaffected: this task only adds code after `bindCopyRsyncButtons()` and one call in `DOMContentLoaded`, nothing `MirrorStatus` reads.

- [ ] **Step 8 (developer): lint.** Run the lint pair on the two Python files this task touches. Both are clean on the first run.
`docker compose run --rm -T test ruff check tests/test_copy_buttons.py tests/test_public_page_csp.py; echo "rc=$?"` -> no output, `rc=0`.
`docker compose run --rm -T test ruff format --check tests/test_copy_buttons.py tests/test_public_page_csp.py; echo "rc=$?"` -> `2 files already formatted`, `rc=0`.

- [ ] **Step 9 (developer): run the whole suite.**

Run: `docker compose run --rm -T test; echo "rc=$?"`

Expected: `1537 passed, 7 warnings`, `rc=0`: eight more than Task 5's `1529`. Four are in `tests/test_public_page_csp.py` (`test_all_data_copy_buttons_are_found` plus the three parametrised `test_data_copy_button_responds_to_a_real_click` cases), and four in the new `tests/test_copy_buttons.py` (three parametrised `test_copy_button_behaviour` cases plus `test_the_harness_runs_exactly_these_checks`). Read the exit code directly, not through a `tail`.

- [ ] **Step 10 (developer): commit.**

```bash
git add frontend/public/js/main.js tests/js/csp_click_harness.mjs tests/test_public_page_csp.py \
    tests/js/copy_buttons_harness.mjs tests/test_copy_buttons.py
git commit -m "Bind the page-wide copy buttons and click them under the CSP"
```

### Task 7: The error pages

Spec section 5.3: `404.html` and `50x.html` get the b|d mark as inline SVG, a new headline ("Page not found" / "Something went wrong on our side"), one explanatory sentence, and a "Back to the mirror" link to `/`. Task 4 already moved `error.css` onto the new palette -- its own Step 10 says so: "The error pages' own redesign is Task 7; this step only brings `error.css` in line with the new tokens" -- but left the markup and rules from before the redesign in place. This task is that redesign, plus the developer tests that pin what the two pages say and how the mark reaches them.

Both pages keep every constraint `tests/test_error_pages_inline_styles.py` already enforces: `tokens.css` and `error.css` only, `rel` before `href`, no `data-theme`, and every class defined in a stylesheet the page actually links. Because these pages load neither `style.css` nor `img/mark-glyph.svg`'s CSS mask, the mark can only reach them as an inline `<symbol>` -- the same regular geometry `index.html` inlines (spec section 4.5) -- with its own `.mark`/`.mark-glyph`/`.mark-axis` rules restated in `error.css`, since this stylesheet loads alone and has nothing to inherit them from. The dark `@media` block's four tokens (`--bg-primary`, `--text-primary`, `--text-secondary`, `--accent-primary`) don't change: the redesign moves what *uses* them (the mark, the pill-shaped link, `.error-title` in place of `.error-content h1`, and the focus ring), not which colour tokens the page needs. The one token `error.css` reads that it did not before is the invariant `--radius-full`, for the pill.

Three more constraints shape the files:
- **The 503 page can arrive without its stylesheets.** They share `general_limit` with the request that got the 503, and spec section 8 accepts that. An `<svg>` that nothing sizes lays out at 300×150, so both `<svg>`s carry `width` and `height` attributes: the mark lays out at 64px and the sprite at nothing. `error.css` overrides both whenever it loads, so the styled render does not change.
- **Reduced motion.** `error.css`'s body still fades colour on a theme change, so it keeps Task 4's `@media (prefers-reduced-motion: reduce)` block; `tests/test_reduced_motion.py` requires one for any transition.
- **Focus.** `error.css` gets its own `:focus-visible` ring, matching `style.css`'s, and `tests/test_focus_ring.py` now checks both sheets.

The role split is narrow: developer writes and runs the two test changes; web-designer does the markup, `error.css`, and the visual check; developer runs the final gate and commits.

**Files:**
- Create: `tests/test_error_pages_content.py`
- Modify: `tests/test_focus_ring.py` (`error.css` joins `STYLESHEETS`)
- Modify: `frontend/public/404.html`, `frontend/public/50x.html` (each `<title>` and everything from `<body>` to `</body>`)
- Modify: `frontend/public/css/error.css` (replaced in full)

- [ ] **Step 1 (developer): write `tests/test_error_pages_content.py`.** It parses each page with `html.parser.HTMLParser` into a small DOM-ish tree -- the same approach `tests/test_public_page_structure.py` uses for `index.html` -- rather than a handful of independent regexes, so "the one `<h1>` on the page" is the same question a browser would answer. It pins:
- the headline exactly (the spec gives it verbatim), and the link exactly ("Back to the mirror", `href="/"`);
- the mark in spec section 4.5's form: a hidden sprite holding `<symbol id="mark">`, identical element for element to `index.html`'s, with its `.mark-glyph` group and `.mark-axis` rect, drawn by one `<svg class="mark">` through a single `<use href="#mark">`, and no element carrying a presentation colour;
- both `<svg>`s' own `width` and `height` (64 for the mark, 0 for the sprite);
- no `var(--font-*)` in `error.css` (spec section 4.2's system font stack).

The explanatory sentence and the two `<title>`s aren't given verbatim by the spec, so only their shape is pinned, not their words.

```python
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
```

- [ ] **Step 2 (developer): extend `tests/test_focus_ring.py` to `error.css`.** Replace:

```python
Covers style.css. error.css joins STYLESHEETS once the error pages carry a
focus rule of their own (spec section 5.3).
"""
import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
STYLE_CSS = REPO_ROOT / "frontend" / "public" / "css" / "style.css"
STYLESHEETS = [STYLE_CSS]
```

with:

```python
Covers style.css and error.css. The error pages load error.css without
style.css (spec section 5.3), so it carries a ring of its own.
"""
import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
STYLE_CSS = REPO_ROOT / "frontend" / "public" / "css" / "style.css"
ERROR_CSS = REPO_ROOT / "frontend" / "public" / "css" / "error.css"
STYLESHEETS = [STYLE_CSS, ERROR_CSS]
```

- [ ] **Step 3 (developer): run them, and watch them fail.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_error_pages_content.py tests/test_focus_ring.py; echo "rc=$?"`

Expected: `rc=1`, `13 failed, 4 passed, 4 warnings`. Against the pages and `error.css` from before the redesign:
- `test_exactly_one_h1_with_the_new_headline[404.html]`: `AssertionError: assert '404 - Not Found' == 'Page not found'`.
- `test_exactly_one_h1_with_the_new_headline[50x.html]`: `AssertionError: assert 'Server Error' == 'Something we...g on our side'` (pytest shortens the long string).
- `test_each_page_has_exactly_one_explanatory_sentence`: `AssertionError: expected exactly one match for {'tag': 'p'}, found 2: [<p {}>, <p {}>]`. Today's link sits inside its own second `<p>`.
- `test_back_to_the_mirror_link[404.html]` and `[50x.html]`: `AssertionError: assert 'Return to homepage' == 'Back to the mirror'`.
- `test_the_mark_is_an_inline_symbol_drawn_by_one_use[404.html]` and `[50x.html]`: `AssertionError: 404.html has no <svg> -- no mark`, and likewise for `50x.html`.
- `test_the_mark_symbol_is_index_htmls_geometry_and_classes`, both pages: `AssertionError: expected one <symbol id="mark">, found 0`.
- `test_both_svgs_carry_their_own_size`, both pages: `AssertionError: expected one <svg class="mark">, found 0`.
- `test_error_css_uses_no_font_token`: `AssertionError: error.css reads a --font-* token`. Task 4's `body` rule still reads `font-family: var(--font-sans)`.
- `test_focus_visible_draws_a_2px_accent_outline_at_a_2px_offset[error.css]`: `AssertionError: error.css has 0 top-level :focus-visible rules, expected 1`.

The other four pass already: `test_no_script_tag_anywhere` (both pages; neither ever carried a `<script>`), `test_titles_are_sensible` (today's "Not Found - BSD Mirrors" / "Server Error - BSD Mirrors" already name the site and the two failures distinctly), and the focus ring's `style.css` case.

- [ ] **Step 4 (web-designer): `404.html`.** The `<title>` first. Replace:

```html
    <title>Not Found - BSD Mirrors</title>
```

with:

```html
    <title>Page not found · BSD Mirror</title>
```

Then the whole `<body>`. The mark is inlined here rather than referenced, because this page loads neither `style.css` nor a CSS mask: it has to carry its own copy of the regular geometry from `img/mark-glyph.svg` and `img/mark-axis.svg`. `.error-page` replaces `.error-content`; the link is no longer wrapped in its own `<p>`, so the page keeps exactly one (`test_each_page_has_exactly_one_explanatory_sentence` above). Replace:

```html
<body>
    <div class="error-content">
        <h1>404 - Not Found</h1>
        <p>The page you're looking for doesn't exist.</p>
        <p><a href="/">Return to homepage</a></p>
    </div>
</body>
```

with:

```html
<body>
    <!-- The b|d mark (docs/design/2026-09-25-reflection-redesign.md, section
         4.5): the same regular geometry index.html inlines, held here too
         because this page loads neither style.css nor img/mark-glyph.svg's
         mask -- it must draw itself from nothing but this file and
         error.css. Kept in the render tree (clipped, not display:none) so
         <use> can still resolve it. Both <svg>s carry a width and height,
         so the page still lays out if its stylesheets never arrive. -->
    <svg class="visually-hidden" width="0" height="0" aria-hidden="true" focusable="false">
        <defs>
            <symbol id="mark" viewBox="0 0 64 64">
                <g class="mark-glyph">
                    <rect x="5" y="6" width="7" height="52"/>
                    <path fill-rule="evenodd" d="M5 46a12 12 0 1 0 24 0a12 12 0 1 0-24 0ZM11 46a6 6 0 1 0 12 0a6 6 0 1 0-12 0Z"/>
                    <g transform="translate(64 0) scale(-1 1)">
                        <rect x="5" y="6" width="7" height="52"/>
                        <path fill-rule="evenodd" d="M5 46a12 12 0 1 0 24 0a12 12 0 1 0-24 0ZM11 46a6 6 0 1 0 12 0a6 6 0 1 0-12 0Z"/>
                    </g>
                </g>
                <rect class="mark-axis" x="30.7" y="3" width="2.6" height="58" rx="1.3"/>
            </symbol>
        </defs>
    </svg>

    <div class="error-page">
        <svg class="mark" viewBox="0 0 64 64" width="64" height="64" aria-hidden="true" focusable="false"><use href="#mark"></use></svg>
        <h1 class="error-title">Page not found</h1>
        <p class="error-text">The page you're looking for doesn't exist, or the link may be out of date.</p>
        <a class="error-link" href="/">Back to the mirror</a>
    </div>
</body>
```

- [ ] **Step 5 (web-designer): `50x.html`,** the same shape with its own copy and headline. Replace:

```html
    <title>Server Error - BSD Mirrors</title>
```

with:

```html
    <title>Server error · BSD Mirror</title>
```

Then replace:

```html
<body>
    <div class="error-content">
        <h1>Server Error</h1>
        <p>Something went wrong. Please try again later.</p>
        <p><a href="/">Return to homepage</a></p>
    </div>
</body>
```

with:

```html
<body>
    <!-- The b|d mark (docs/design/2026-09-25-reflection-redesign.md, section
         4.5): the same regular geometry index.html inlines, held here too
         because this page loads neither style.css nor img/mark-glyph.svg's
         mask -- it must draw itself from nothing but this file and
         error.css. Kept in the render tree (clipped, not display:none) so
         <use> can still resolve it. Both <svg>s carry a width and height,
         so the page still lays out if its stylesheets never arrive. -->
    <svg class="visually-hidden" width="0" height="0" aria-hidden="true" focusable="false">
        <defs>
            <symbol id="mark" viewBox="0 0 64 64">
                <g class="mark-glyph">
                    <rect x="5" y="6" width="7" height="52"/>
                    <path fill-rule="evenodd" d="M5 46a12 12 0 1 0 24 0a12 12 0 1 0-24 0ZM11 46a6 6 0 1 0 12 0a6 6 0 1 0-12 0Z"/>
                    <g transform="translate(64 0) scale(-1 1)">
                        <rect x="5" y="6" width="7" height="52"/>
                        <path fill-rule="evenodd" d="M5 46a12 12 0 1 0 24 0a12 12 0 1 0-24 0ZM11 46a6 6 0 1 0 12 0a6 6 0 1 0-12 0Z"/>
                    </g>
                </g>
                <rect class="mark-axis" x="30.7" y="3" width="2.6" height="58" rx="1.3"/>
            </symbol>
        </defs>
    </svg>

    <div class="error-page">
        <svg class="mark" viewBox="0 0 64 64" width="64" height="64" aria-hidden="true" focusable="false"><use href="#mark"></use></svg>
        <h1 class="error-title">Something went wrong on our side</h1>
        <p class="error-text">We're having trouble right now. Please try again in a few minutes.</p>
        <a class="error-link" href="/">Back to the mirror</a>
    </div>
</body>
```

- [ ] **Step 6 (web-designer): replace `frontend/public/css/error.css` in full.** In sections: the header comment (the system-font rationale replaces the `var(--font-sans)` one), `body`, `.visually-hidden` (copied from `style.css`, since this sheet loads alone and has nothing to inherit it from), the mark, page layout, the responsive breakpoint, focus, reduced motion, and the dark mapping. No `transition: all`. The colour tokens stay the four the dark block restates; the one new token is the invariant `--radius-full`, for the pill. `.error-title` takes `--text-primary` (matching `.hero-title` in `style.css`, which sets no colour of its own and inherits the same token from `body`) rather than the accent, so the accent stays reserved for the mark's axis, the one link and the focus ring. `.error-title` and `.error-text` drop their default margins, so `.error-page`'s gap spaces the mark, the headline, the sentence and the link evenly (the link adds 4px of its own; see Notes). The link becomes an outlined pill -- border and text both `--accent-primary` on the page's own `--bg-primary` -- rather than bare underlined text.

```css
/* BSD Mirror - Static Error Pages (404, 50x) */
/* Shared by frontend/public/404.html and frontend/public/50x.html.
   Design tokens live in css/tokens.css, linked ahead of this file.
   Do not declare custom properties here, apart from the dark mapping at the
   end, which restates four of tokens.css's dark values.

   Deliberately NOT linking css/style.css or css/fonts.css:

   - style.css is the full site stylesheet (header, hero, sync streams,
     mirror cards, status and access). These two pages render one heading,
     one explanatory sentence, the b|d mark and one link; loading it would be
     the "chases four stylesheets" failure mode the 50x page specifically
     cannot afford when the backend is down.
   - fonts.css declares the self-hosted @font-face rules for 'Instrument
     Sans' and 'Unbounded'. Rather than reference --font-sans/--font-display
     and rely on the named webfont silently failing to a fallback, the rules
     below spell out that fallback -- a literal system-font stack -- so
     nothing here depends on fonts.css ever having been requested, let alone
     having arrived: no failed request, no unstyled flash, just a plain
     system sans-serif from the very first paint (spec section 4.2, "Error
     pages: they use the system font stack only").

   Both files are still served solely as static files by nginx off the same
   document root as this stylesheet (nginx/sites/production/production.conf),
   so neither depends on the backend being up.

   No [data-theme="dark"] rules appear below on purpose: these pages carry no
   script, so nothing ever sets data-theme on <html>. Light is tokens.css's
   :root default, and dark follows the OS preference, through the
   prefers-color-scheme block at the end of this file. */

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background-color: var(--bg-primary);
    color: var(--text-primary);
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 100vh;
    margin: 0;
    transition: background-color var(--transition-fast), color var(--transition-fast);
}

/* Visually hidden but still reachable by <use href="#mark">: an SVG holding
   only <symbol>/<defs> content must stay in the render tree (unlike
   display:none, which some engines exclude referenced content from), so this
   is the standard clip-based hidden pattern rather than display:none. Copied
   from style.css rather than shared with it: this file loads on its own
   (see the header comment above), so the class has to be defined here too. */
.visually-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    margin: -1px;
    padding: 0;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
}

/* ===========================================================================
   The b|d mark (spec section 4.5). Each page inlines its own <symbol id=
   "mark"> holding the regular geometry -- the same one index.html and
   img/mark-glyph.svg/mark-axis.svg use -- since this stylesheet has no CSS
   mask to point at a shared file. One visible <svg class="mark"><use
   href="#mark"></use></svg> renders it. Colours are classes, not
   presentation attributes, so they follow the theme.
   =========================================================================== */
.mark {
    display: block;
    width: 64px;
    height: 64px;
}

.mark-glyph {
    fill: var(--text-primary);
}

.mark-axis {
    fill: var(--accent-primary);
}

/* ===========================================================================
   Page layout: the mark, a headline, one explanatory sentence, and a link
   back to "/" -- vertically centred by the flex rule on body above. The
   headline and the sentence drop their default margins, so .error-page's
   gap spaces all four evenly; the link's own 4px margin-top stands in for
   the line spacing the text above it carries and its border does not.
   =========================================================================== */
.error-page {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 20px;
    max-width: 26rem;
    padding: 0 24px;
    text-align: center;
}

.error-title {
    color: var(--text-primary);
    font-size: 2.5rem;
    font-weight: 700;
    line-height: 1.15;
    letter-spacing: -0.01em;
    margin: 0;
}

.error-text {
    color: var(--text-secondary);
    font-size: 1rem;
    line-height: 1.6;
    margin: 0;
}

.error-link {
    display: inline-flex;
    align-items: center;
    margin-top: 4px;
    padding: 10px 22px;
    border: 1px solid var(--accent-primary);
    border-radius: var(--radius-full);
    color: var(--accent-primary);
    font-weight: 600;
    font-size: 0.9375rem;
    text-decoration: none;
}

.error-link:hover {
    text-decoration: underline;
}

@media (max-width: 768px) {
    .mark {
        width: 48px;
        height: 48px;
    }

    .error-title {
        font-size: 1.75rem;
    }
}

/* ===========================================================================
   Focus -- matches style.css's global rule (spec section 9, "Focus"). The
   "Back to the mirror" link is the only focusable element on either page.
   =========================================================================== */
:focus-visible {
    outline: 2px solid var(--accent-primary);
    outline-offset: 2px;
}

/* Reduced motion (spec section 4.4): the body's colour fade above is this
   file's only motion, and it goes too. */
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        animation: none !important;
        transition: none !important;
    }
}

/* ---------------------------------------------------------------------------
   OS dark preference
   ---------------------------------------------------------------------------
   These pages ship no <script>, and this codebase picks its theme purely in
   JavaScript -- main.js sets data-theme on <html>, and there is no
   prefers-color-scheme rule anywhere else in frontend/. So without this block
   an error page renders tokens.css's :root (light) on every machine, including
   one whose entire desktop is dark. That is not "theme-aware"; it is "always
   light, in tokens", which is a different and less useful thing.

   The four tokens below are exactly the colour tokens these pages consume --
   by body, .error-title, .error-text, .error-link, .mark-glyph/.mark-axis and
   :focus-visible above -- mirroring tokens.css's [data-theme="dark"] block.
   They reference the same --c-* palette entries rather than restating hex,
   so a palette change still flows from one definition.
   test_error_page_dark_mapping_matches_tokens_css asserts the two agree --
   add a token to an error page and you must add it in both places or that
   test fails.

   :not([data-theme="light"]) so that an explicitly chosen light theme still
   wins if these pages ever gain scripting. Specificity (0,2,0) also puts this
   above tokens.css's bare :root (0,1,0), which is what makes it apply at all.

   Contrast in this mode, against --bg-primary #07080B:
     --text-primary    #EDEFF3  17.40:1  (.error-title, .mark-glyph)
     --text-secondary  #A2A9B6   8.48:1  (.error-text)
     --accent-primary  #FF5A60   6.56:1  (.error-link, .mark-axis; needs 4.5)
   --------------------------------------------------------------------------- */
@media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
        --bg-primary: var(--c-graphite-975);
        --text-primary: var(--c-graphite-75);
        --text-secondary: var(--c-graphite-400);
        --accent-primary: var(--c-red-400);
    }
}
```

Light contrast, against `--bg-primary` `#ECEEF1`: `--text-primary` `#0C0E12` 16.62:1 (`.error-title`, `.mark-glyph`); `--text-secondary` `#4E5563` 6.44:1 (`.error-text`); `--accent-primary` `#C8232C` 4.84:1 (`.error-link`, `.mark-axis` and the focus ring; the link text needs 4.5:1 at 15px, and the pill's border and the ring only 3:1). Dark contrast is the `@media` block's own comment above. Both themes clear every threshold.

- [ ] **Step 7 (web-designer): run green.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_error_pages_content.py tests/test_focus_ring.py tests/test_error_pages_inline_styles.py; echo "rc=$?"`

Expected: `26 passed, 4 warnings`, `rc=0`: the 15 content checks, both focus-ring cases, and the 9 `tests/test_error_pages_inline_styles.py` already had. Those 9 are unchanged: this task adds no inline `style=` and links no third stylesheet, and every new class (`.error-page`, `.error-title`, `.error-text`, `.error-link`, `.mark`, `.mark-glyph`, `.mark-axis`, `.visually-hidden`) is defined in `error.css`, which both pages still link alone with `tokens.css`.

- [ ] **Step 8 (web-designer): look at it.** Render the pages with the visual-check script Task 8 Step 1 gives in full, as Task 4's look step (Step 11) did. The controller wrote Task 8 Step 1's two scripts to `$SCRATCH/pr2/screens.sh` and `$SCRATCH/pr2/tiles.py` for that step, and passes `$SCRATCH`'s absolute path again when dispatching this one. The script renders both error pages at 1440, 768 and 400px, light and dark, and the 503 page once more without its stylesheets:

```bash
rm -rf "$SCRATCH/pr2/main-public" && mkdir -p "$SCRATCH/pr2/main-public"
git archive main frontend/public | tar -x -C "$SCRATCH/pr2/main-public"
bash "$SCRATCH/pr2/screens.sh" "$PWD" "$SCRATCH/pr2/main-public/frontend/public"; echo "rc=$?"
```

Expected: `admin login page: byte-identical to the base checkout`, nineteen `pr2-*.png` files listed, and `rc=0`. The admin line is the load-bearing one here too: this task touches no shared token, so the admin login page must render exactly as it did at the base checkout.

Open the twelve `pr2-404-*` and `pr2-50x-*` PNGs and `pr2-50x-unstyled-1440.png` with the Read tool, and check:
- The mark reads as a "b" and a mirrored "d" joined by a red axis, in `--text-primary` (near-black in light, near-white in dark) with the axis in `--accent-primary`, matching the header mark on the public page.
- The mark, the headline, the sentence and the pill-shaped "Back to the mirror" link are centred, in that order, evenly spaced, with no larger gap around the headline.
- The text is a plain system sans-serif, not Instrument Sans.
- Dark differs from light only by `prefers-color-scheme`: these pages carry no `data-theme` and no script, so nothing else could switch them.
- At 768 and 400px, the mark and headline shrink (the `max-width: 768px` rule applies at exactly 768px), and the sentence wraps without crowding the link.
- The 50x headline wraps to two lines at every width, stays centred, and doesn't crowd the mark above it.
- The unstyled 503 page shows a small mark at the top left, black on white, then the headline, the sentence and the link as plain text, all on the first screen.

Then measure the two things a still can only suggest: the gaps between the four blocks, and the unstyled mark's size. This finds each block's rows of ink and prints the blank rows between them, then the ink box of the unstyled mark:

```bash
docker compose run --rm -T test python -c '
import pathlib
from tests.test_images import png_rows


def shot(name):
    channels, rows = png_rows(pathlib.Path(f".screenshots/pr2-{name}.png").read_bytes())
    return [[row[x : x + 3] for x in range(0, len(row), channels)] for row in rows]


for name in ("404-light-1440", "50x-light-1440", "404-light-400"):
    pixels = shot(name)
    ground, bands = pixels[5][0], []
    for y, row in enumerate(pixels):
        if any(max(abs(a - b) for a, b in zip(p, ground)) > 40 for p in row):
            if bands and y - bands[-1][1] <= 12:
                bands[-1][1] = y
            else:
                bands.append([y, y])
    print(name, "gaps", [bands[i + 1][0] - bands[i][1] - 1 for i in range(len(bands) - 1)])

pixels = shot("50x-unstyled-1440")
ink = [(x, y) for y in range(110) for x in range(200) if max(pixels[y][x]) < 100]
xs, ys = [x for x, _ in ink], [y for _, y in ink]
print("unstyled mark", max(xs) - min(xs) + 1, "x", max(ys) - min(ys) + 1)
'
```

Expected:

```
404-light-1440 gaps [29, 26, 29]
50x-light-1440 gaps [29, 26, 32]
404-light-400 gaps [25, 28, 29]
unstyled mark 54 x 58
```

The gaps sit within a few pixels of each other. Without the headline's margin reset they read `[55, 53, 28]` at 1440px. The unstyled ink box is the mark's extent at one pixel per grid unit (the stems span x 5 to 59, the axis y 3 to 61), so the mark lays out at its 64px attribute size.

If anything doesn't read, it comes back to this step before Step 9: a static assertion cannot see crowding or a broken wrap.

- [ ] **Step 9 (developer): run green, the named regression files, lint, and the whole suite.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_error_pages_content.py tests/test_focus_ring.py tests/test_error_pages_inline_styles.py; echo "rc=$?"`

Expected: `26 passed, 4 warnings`, `rc=0` (unchanged from Step 7).

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_images.py; echo "rc=$?"`

Expected: `48 passed, 4 warnings`, `rc=0`. The three favicon links on both pages are untouched by this task, so `test_every_page_links_the_favicon_set` still passes for `404.html` and `50x.html`.

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_reduced_motion.py; echo "rc=$?"`

Expected: `8 passed, 4 warnings`, `rc=0`, including `test_a_sheet_with_any_motion_turns_it_off_under_reduced_motion`: `error.css`'s body still fades colour, and its reduced-motion block turns the fade off.

Run the lint pair on the two Python files this task touches. Both are clean on the first run. `ruff` does not lint `frontend/public/*.html` or `*.css`.
`docker compose run --rm -T test ruff check tests/test_error_pages_content.py tests/test_focus_ring.py; echo "rc=$?"` -> no output, `rc=0`.
`docker compose run --rm -T test ruff format --check tests/test_error_pages_content.py tests/test_focus_ring.py; echo "rc=$?"` -> `2 files already formatted`, `rc=0`.

Run: `docker compose run --rm -T test; echo "rc=$?"`

Expected: `1553 passed, 7 warnings`, `rc=0`: sixteen more than Task 6's `1537`. Fifteen are in the new file: `test_no_script_tag_anywhere` (2, parametrised), `test_exactly_one_h1_with_the_new_headline` (2), `test_each_page_has_exactly_one_explanatory_sentence` (1), `test_back_to_the_mirror_link` (2), `test_the_mark_is_an_inline_symbol_drawn_by_one_use` (2), `test_the_mark_symbol_is_index_htmls_geometry_and_classes` (2), `test_both_svgs_carry_their_own_size` (2), `test_error_css_uses_no_font_token` (1) and `test_titles_are_sensible` (1). The sixteenth is the focus ring's `error.css` case. Read the exit code directly, not through a `tail`.

- [ ] **Step 10 (developer): commit.**

```bash
git add tests/test_error_pages_content.py tests/test_focus_ring.py frontend/public/404.html frontend/public/50x.html frontend/public/css/error.css
git commit -m "Redesign the error pages around the b|d mark"
```

#### Notes

**Deviation for the user's OK: the two `<title>`s.** Spec section 1 limits copy changes to those sections 5.1, 5.2 and 5.3 list, and section 5.3 lists the headline, the sentence and the link, not the `<title>`. This task still rewords both titles, to "Page not found · BSD Mirror" and "Server error · BSD Mirror": they name the site the way `index.html` does ("BSD Mirror", not the old "BSD Mirrors"), and the 404 title matches its new headline. It needs the user's OK with this plan, and Task 9 lists it in the pull request with the other approved deviations. If the user declines, Steps 4 and 5 keep today's "Not Found - BSD Mirrors" and "Server Error - BSD Mirrors"; `test_titles_are_sensible` passes either way.

**Design decisions the spec didn't settle.**
- **The headline takes `--text-primary`, not the accent.** Today's `error.css` painted `.error-content h1` with `--accent-primary`; `.hero-title` in `style.css` sets no colour of its own and inherits `body`'s `--text-primary` instead. `.error-title` follows the public page's own convention, which also frees the accent to mean one thing on this page: the mark's axis, and the single available action.
- **The link is an outlined pill, not bare underlined text.** `--accent-primary` for both the border and the text, on the page's own `--bg-primary`: no new colour token, and the same 4.84:1 (light) / 6.56:1 (dark) ratio the accent already clears against that ground. A border only needs 3:1 (WCAG 2.1 SC 1.4.11), so the pill shape costs nothing in contrast terms.
- **Even spacing comes from the flex gap.** An `<h1>`'s default margins (0.67em, about 27px at 2.5rem) would double the space above and below the headline; the look step measured `[55, 53, 28]` before the reset. `.error-link` keeps a 4px `margin-top`, which stands in for the line spacing the text above it carries and its border does not.
- **The sentences are reworded, not copied.** They keep today's meaning ("The page you're looking for doesn't exist" / "Something went wrong, try again later"), reworded so the 50x one doesn't repeat its own headline.
- **The responsive breakpoint stays `max-width: 768px`,** this file's own pre-existing convention (unlike `style.css`'s `980px`/`639.98px` pair), since nothing here requires matching the public page's breakpoints: the two files never load together and this task touches no shared rule.

**Test decisions.**
- **The mark check pins spec section 4.5's form and `index.html`'s geometry.** Section 4.5 says `index.html` and the error pages "use an inline `<symbol>` of the same geometry, styled with CSS classes", so the test requires exactly that: one sprite with `<symbol id="mark">`, identical element for element to `index.html`'s (tags, attributes and nesting, with the whitespace between them ignored), and one visible `<svg class="mark">` drawing it through one `<use href="#mark">`. A geometry change in `index.html` must therefore reach both error pages in the same commit.
- **The size pin stands on its own.** Against this task's pages without the two `width`/`height` pairs, only `test_both_svgs_carry_their_own_size` fails, with `AssertionError: assert (None, None) == ('64', '64')`. Rendered styled, those pages and this task's are byte-identical at all twelve sizes: `error.css` overrides the attributes whenever it loads.
- **`test_no_script_tag_anywhere` checks both raw text and the parsed tree.** `tests/test_public_page_csp.py` already established that a banned string inside an HTML comment still counts in raw text, because a comment is invisible to a browser but not to a naive parser check; the same reasoning applies to `<script>` here, even though nothing on these two pages currently tries it.
- **The explanatory sentence and the titles are pinned by shape, not by string.** Spec section 5.3 quotes the headlines verbatim but not this copy, so pinning exact words would hand the developer test an opinion that belongs to web-designer. `test_each_page_has_exactly_one_explanatory_sentence` and `test_titles_are_sensible` instead pin what must stay true regardless of wording: one `<p>` per page, non-trivial, ending like a sentence, distinct between the two pages; a non-empty `<title>` naming the site, also distinct between the two pages, and using a word appropriate to each failure.

---

## Chunk 4: Visual check, and shipping PR 2

The controller's tasks: screenshots of the finished pages, with the admin login page compared byte for byte against `main`'s; then the gate, the reviews, the pull request, the merge and the deploy, each with the user's approval, and the deploy not before 2026-10-03 10:05 UTC.

### Task 8 (controller): The visual check

Spec section 10: screenshots of both themes at 1440, 768 and 400px, shared in the session. They cannot be attached to the pull request, so its body lists what was checked.

The admin console is covered two ways. `tests/test_legacy_admin_tokens.py` (Task 1) pins every token `admin.css` uses at its pre-PR value. As a smoke test, this task renders the admin login page from `main`'s files and from this branch's, and compares them byte for byte. The byte comparison covers the login page only; the token test covers the rest.

- [ ] **Step 1: write the scripts.**

`$SCRATCH/pr2/screens.sh`:

```bash
#!/usr/bin/env bash
# PR 2's visual check: the public page and both error pages at 1440, 768 and
# 400px, light and dark, rendered by the test image's Chromium over HTTP with a
# stubbed status API (FreeBSD online, NetBSD syncing, OpenBSD in error), and
# the 503 page without its stylesheets, and the admin login page rendered
# from two checkouts' frontend/public and compared byte for byte.
# Writes .screenshots/pr2-*.png in REPO_ROOT.
# Usage: screens.sh REPO_ROOT [BASE_PUBLIC]
#   BASE_PUBLIC: another frontend/public (for example main's) to compare the
#   admin login page against; omitted, the comparison is skipped.
set -euo pipefail
R=$(cd "${1:?usage: screens.sh REPO_ROOT [BASE_PUBLIC]}" && pwd)
BASE=${2:-}
mkdir -p "$R/.screenshots"
# A stale PNG from an earlier run must never pass for a new one.
rm -f "$R/.screenshots"/pr2-*.png
base_mount=()
if [ -n "$BASE" ]; then
    base_mount=(-v "$(cd "$BASE" && pwd):/base:ro")
fi

docker run --rm --network none -u "$(id -u):$(id -g)" --security-opt seccomp=unconfined -e HOME=/tmp \
    -v "$R/frontend/public:/site:ro" ${base_mount[@]+"${base_mount[@]}"} -v "$R/.screenshots:/out" \
    bsdmirror-test bash -c '
set -e
serve() {  # serve DIR PORT: static files plus a stubbed /api
    python3 - "$1" "$2" <<EOF &
import http.server, json, sys, datetime, functools
root, port = sys.argv[1], int(sys.argv[2])
now = datetime.datetime.now(datetime.timezone.utc)
def ago(hours):
    return (now - datetime.timedelta(hours=hours)).isoformat()
OVERVIEW = {
    "mirrors": {
        "FreeBSD": {"status": "active", "size": "799.9 GB", "last_updated": ago(2), "files": "201,113"},
        "NetBSD": {"status": "syncing", "size": "743.5 GB", "last_updated": ago(9), "files": "188,902"},
        "OpenBSD": {"status": "error", "size": "2.6 TB", "last_updated": ago(30), "files": "214,603"},
    },
    "totals": {"size": "4.2 TB", "size_bytes": 4200000000000, "files": "604,618", "files_count": 604618},
}
class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def do_GET(self):
        body = None
        if self.path.startswith("/api/stats/overview"):
            body = OVERVIEW
        elif self.path.startswith("/api/health"):
            body = {"status": "healthy", "version": "visual-check"}
        elif self.path.startswith("/api/"):
            self.send_error(404)
            return
        if body is None:
            return super().do_GET()
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
handler = functools.partial(Handler, directory=root)
http.server.ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()
EOF
    for _ in $(seq 1 50); do
        if python3 -c "import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:$2/index.html\")" 2>/dev/null; then
            return 0
        fi
        sleep 0.2
    done
    echo "the server on port $2 never answered" >&2
    return 1
}
shot() {  # shot URL OUT WIDTH HEIGHT SCHEME
    local flag=""; [ "$5" = dark ] && flag="--force-dark-mode"
    rm -f "$2"
    # Reduced motion switches transitions off, so a pill whose data-state the
    # stub API has just set shows its final colours instead of a frame caught
    # mid-transition. The sheen and the stream dots are still frames anyway.
    chromium --headless=new --disable-gpu --hide-scrollbars $flag --force-prefers-reduced-motion \
        --virtual-time-budget=4000 \
        --window-size="$3,$4" --screenshot="$2" "$1" >/dev/null 2>&1
    [ -s "$2" ] || { echo "no screenshot for $1 at $3px $5" >&2; return 1; }
}
mkdir -p /tmp/www && cp -R /site/. /tmp/www/
# The 503 page as it arrives when its stylesheets are rate-limited too (spec
# section 8 accepts that): it must still say what happened.
# (Double quotes here: this whole script is the single-quoted bash -c
# argument on the host side, which any single quote would end.)
grep -v "rel=\"stylesheet\"" /tmp/www/50x.html > /tmp/www/__50x-unstyled.html
serve /tmp/www 8765
for scheme in light dark; do
    shot http://127.0.0.1:8765/index.html /out/pr2-home-$scheme-1440.png 1440 2800 $scheme
    shot http://127.0.0.1:8765/index.html /out/pr2-home-$scheme-768.png 768 3400 $scheme
    shot http://127.0.0.1:8765/index.html /out/pr2-home-$scheme-400.png 400 4000 $scheme
    for page in 404 50x; do
        shot http://127.0.0.1:8765/$page.html /out/pr2-$page-$scheme-1440.png 1440 900 $scheme
        shot http://127.0.0.1:8765/$page.html /out/pr2-$page-$scheme-768.png 768 900 $scheme
        shot http://127.0.0.1:8765/$page.html /out/pr2-$page-$scheme-400.png 400 800 $scheme
    done
done
shot http://127.0.0.1:8765/__50x-unstyled.html /out/pr2-50x-unstyled-1440.png 1440 900 light
if [ -d /base ]; then
    mkdir -p /tmp/basewww && cp -R /base/. /tmp/basewww/
    serve /tmp/basewww 8766
    shot http://127.0.0.1:8765/admin/ /tmp/admin-branch.png 1440 1000 dark
    shot http://127.0.0.1:8766/admin/ /tmp/admin-base.png 1440 1000 dark
    if cmp -s /tmp/admin-branch.png /tmp/admin-base.png; then
        echo "admin login page: byte-identical to the base checkout"
    else
        cp /tmp/admin-branch.png /out/pr2-admin-branch.png
        cp /tmp/admin-base.png /out/pr2-admin-base.png
        echo "admin login page: DIFFERS from the base checkout; see pr2-admin-*.png" >&2
        exit 3
    fi
fi
'
ls -l "$R/.screenshots" | grep pr2- || true
```

`$SCRATCH/pr2/tiles.py` cuts the tall screenshots into tiles the Read tool shows at full size. Uncut, a 400×4000 image is shown at about 200 pixels wide.

```python
"""Cut a tall PNG screenshot into tiles the Read tool can show at full size.

Usage: tiles.py IN.png OUT_PREFIX [TILE_HEIGHT]
Writes OUT_PREFIX-1.png, OUT_PREFIX-2.png, ... (TILE_HEIGHT rows each, 1000 by
default) and stops at the first tile that is a single colour, the empty page
background below the content. Standard library only: runs in the test image.
Reads 8-bit, non-interlaced RGB or RGBA PNGs, which is what Chromium writes.
"""

import struct
import sys
import zlib


def rows_of(data):
    width, height = struct.unpack(">II", data[16:24])
    bit_depth, colour_type, interlace = data[24], data[25], data[28]
    if bit_depth != 8 or colour_type not in (2, 6) or interlace != 0:
        sys.exit("expected an 8-bit, non-interlaced RGB or RGBA PNG")
    bpp = 4 if colour_type == 6 else 3
    idat, pos = b"", 8
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos : pos + 8])
        if kind == b"IDAT":
            idat += data[pos + 8 : pos + 8 + length]
        pos += 12 + length
    raw, stride = zlib.decompress(idat), width * bpp
    rows, previous = [], bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        kind, row = raw[start], bytearray(raw[start + 1 : start + 1 + stride])
        for x in range(stride):
            a = row[x - bpp] if x >= bpp else 0
            b = previous[x]
            c = previous[x - bpp] if x >= bpp else 0
            if kind == 1:
                row[x] = (row[x] + a) & 0xFF
            elif kind == 2:
                row[x] = (row[x] + b) & 0xFF
            elif kind == 3:
                row[x] = (row[x] + (a + b) // 2) & 0xFF
            elif kind == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                row[x] = (row[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 0xFF
        rows.append(bytes(row))
        previous = row
    return width, colour_type, rows


def png(width, colour_type, rows):
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    header = struct.pack(">IIBBBBB", width, len(rows), 8, colour_type, 0, 0, 0)
    body = zlib.compress(b"".join(b"\x00" + row for row in rows))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", body) + chunk(b"IEND", b"")


def main():
    source, prefix = sys.argv[1], sys.argv[2]
    tile = int(sys.argv[3]) if len(sys.argv) > 3 else 1000
    with open(source, "rb") as handle:
        width, colour_type, rows = rows_of(handle.read())
    count = 0
    for top in range(0, len(rows), tile):
        part = rows[top : top + tile]
        if len({row for row in part}) == 1 and len(set(part[0])) <= 4:
            break
        count += 1
        with open(f"{prefix}-{count}.png", "wb") as handle:
            handle.write(png(width, colour_type, part))
    print(f"{source}: {count} tile(s) of up to {tile} rows")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: run the screenshots** against this checkout, comparing the admin login page with the files of `main` this branch started from:

```bash
rm -rf "$SCRATCH/pr2/main-public" && mkdir -p "$SCRATCH/pr2/main-public"
git archive "$(git merge-base HEAD origin/main)" frontend/public | tar -x -C "$SCRATCH/pr2/main-public"
bash "$SCRATCH/pr2/screens.sh" "$PWD" "$SCRATCH/pr2/main-public/frontend/public"; echo "rc=$?"
```

Expected:
- `admin login page: byte-identical to the base checkout`;
- nineteen `pr2-*.png` files listed;
- `rc=0`.

If the admin page differs, the legacy block (Task 1) missed a token. The script keeps both images as `pr2-admin-base.png` and `pr2-admin-branch.png` and exits 3. Find the token, fix it in Task 1's block and its snapshot test, and rerun. The script removes every `pr2-*.png` before it renders, so a rerun lists exactly nineteen again.

- [ ] **Step 3: tile the tall pages:**

```bash
rm -rf "$SCRATCH/pr2/tiles" && mkdir -p "$SCRATCH/pr2/tiles"
docker run --rm --network none -u "$(id -u):$(id -g)" -e PYTHONDONTWRITEBYTECODE=1 \
    -v "$PWD/.screenshots:/in:ro" -v "$SCRATCH/pr2/tiles:/out" -v "$SCRATCH/pr2:/tools:ro" bsdmirror-test \
    sh -c 'for f in /in/pr2-home-*.png; do python /tools/tiles.py "$f" "/out/$(basename "$f" .png)"; done'
ls "$SCRATCH/pr2/tiles"
```

Expected: one line per home page, each naming between 2 and 4 tiles, and the tiles listed.

- [ ] **Step 4: look.** Open every home tile, and every error-page PNG, with the Read tool. Check each item below. Anything that doesn't read goes back to its owner (web-designer for CSS and HTML, developer for `main.js`), and Steps 2 to 4 run again after the fix.
  - **Header:**
    - the mark and wordmark;
    - four anchors at 1440 and 768; at 400, only the toggle and Admin;
    - the toggle shows the moon in light and the sun in dark.
  - **Hero:**
    - the eyebrow, "Every BSD, mirrored.", the lede;
    - the three stats filled from the stub: 4.2 TB, 604,618, a relative time;
    - both actions;
    - the art: the mark, the floor and the faded reflection, with no sheen band left on it (the stills force reduced motion, which hides the sheen);
    - at 400px the art comes first, and the headline does not overflow.
  - **Streams:**
    - FreeBSD: a solid line, "Online";
    - NetBSD: dots, "Syncing";
    - OpenBSD: a broken dashed line with a ×, "Error";
    - each row shows the host `127.0.0.1`, and the pills sit at their content width;
    - at 400px "Upstream" and the host are gone.
  - **Cards:** three across at 1440, fewer below. Each has its logo tile, name, pill, description, size, last sync, "Browse files" and "rsync URL".
  - **Status:** "Degraded service" with the OpenBSD sentence, its title in the display face, the error dot.
  - **Access:** the HTTPS and rsync rows show `127.0.0.1`, and they stack at 400px.
  - **About and footer:** today's copy; `visual-check` as the version.
  - **Spacing:** the sections are evenly spaced, with no gap visibly larger than the others.
  - **Dark:** every surface dark, text light, the accent `#FF5A60`, no light panel left over.
  - **Error pages,** at 1440, 768 and 400, light and dark:
    - the mark, the headline, the sentence and the "Back to the mirror" link, evenly spaced;
    - the system font, not Instrument Sans.
  - **The unstyled 503 page** (`pr2-50x-unstyled-1440.png`): a small mark above readable text, all on the first screen.

- [ ] **Step 5: share.** Send the user these with SendUserFile, and say what was checked:
  - the 1440 light and dark home pages;
  - the first tile of the 768 and 400 home pages;
  - one error page in each theme;
  - the unstyled 503 page.

  Say precisely what the admin check covers: the login page rendered byte-identical to `main`'s, and the token test pins every token `admin.css` uses. Offer the rest on request. If SendUserFile is unavailable, give the user the paths.

  Rerun this task after any review fix in Task 9 that touches `frontend/public`.

### Task 9 (controller): Gate, review, pull request, merge and deploy

This may run in a later session. Recreate any `$SCRATCH` script from the task that defines it:
- `screens.sh` and `tiles.py` are in Task 8;
- `serve_production.sh` and `deploy_and_verify.sh` are in PR 1's plan (`docs/design/2026-09-25-reflection-pr1-plan.md`, Task 1 Step 5 and Task 8 Step 7).

**The soak period** (spec section 8): PR 2 may not deploy before **2026-10-03 10:05 UTC**, 7 days after PR 1a's deploy. `deploy.sh` deploys `origin/main` and knows nothing about the soak, so the merge is held too (Step 6).

- [ ] **Step 1: the full gate.** Run each and paste its summary line and `rc`:
  - the whole suite: `docker compose run --rm -T test; echo "rc=$?"`
  - the lint pair on `.`
  - shellcheck
  - `docker compose config -q; echo "rc=$?"`

  Every `rc` must be 0. If `ruff format --check .` flags a file this branch did not touch, report the file and stop.

- [ ] **Step 2: serve the production profile locally.** Only a comment in `nginx/nginx.conf` changed, but the pages are new and still served under the unchanged CSP. `serve_production.sh` already probes `/`, `/index.html`, `/404.html`, `/css/style.css` and `/js/main.js`; add the other files PR 2 changes:

```bash
bash "$SCRATCH/pr1/serve_production.sh" "$PWD" /css/tokens.css /css/error.css /50x.html
```

  Expected:
  - `nginx -t` passes;
  - `/css/tokens.css` and `/css/error.css` answer `200  cc=no-cache`;
  - `/50x.html` answers `200  cc=<none>`: `location = /50x.html` keeps no `Cache-Control`, per spec 8;
  - every row shows `security=5/5`;
  - the rest is as PR 1's Task 1 Step 5 lists: pages, CSS and JS `no-cache`; fonts and images `immutable`; missing CSS, JS and images are 404s; the admin assets 25/25 200s.

- [ ] **Step 3: two reviews, in parallel, both read-only.**
  - **`appsec-reviewer`** on `git diff main...HEAD`, focused on:
    - whether anything in the new markup, CSS or `main.js` needs a CSP exception (an inline style, an inline handler, a `data:` URI, a third-party request);
    - whether every DOM write in `main.js` is `textContent`, or `setAttribute` of a fixed attribute name;
    - the inline SVG in the pages;
    - the clipboard copies;
    - `rel` on the external links;
    - the error pages still rendering with the backend down, and with their stylesheets rate-limited.
  - **A final code review of the whole branch** (`superpowers:code-reviewer`), for cross-task consistency: this plan against the files, the tests against the files, and anything that would break CI or the deploy.

  Route each finding to its owner, and re-run Step 1 after any fix. Re-run Task 8 if a fix touches `frontend/public`, and Step 2 if one touches `nginx/`.

- [ ] **Step 4: push and open the pull request.**
  - Write the body to `$SCRATCH/pr2/body.md`, with no attribution lines. It gives:
    - the summary;
    - the changes by area: tokens and the legacy admin block, the page, the stylesheet, `main.js`, the error pages, the tests;
    - the evidence from Steps 1 to 3 and Task 8, with what the admin check covers stated as Task 8 states it;
    - what was not checked: browsers other than Chromium, and live motion (the stills force reduced motion);
    - the earliest deploy date, 2026-10-03 10:05 UTC;
    - the deviations the user approved with this plan;
    - follow-ups:
      - route `copyRsync` through the guarded `copyUrl`;
      - scope the favicon-link test to `<head>`;
      - move the console-list check in `tests/test_deploy_live_headers.py` to `HTMLParser` before PR 3;
      - add PR 2's new node suites to CI's no-skip `REQUIRED` list, a workflow edit the user applies by hand;
      - `admin.css`'s stale `--accent-gradient` comment, for PR 3.

```bash
git push -u origin feat/reflection-public-site
gh pr create --base main --head feat/reflection-public-site \
    --title "Redesign the public site and error pages" --body-file "$SCRATCH/pr2/body.md"
```

  - Call `get_status` from the `ccd_pr` tools, and `bind_pr` if it does not report the pull request. Offer the user Auto-fix.
  - **Do not poll CI.** Auto-fix wakes this session only on failures, merge conflicts and review comments, never on success. So tell the user CI is running, and end the turn. Call `get_status` once when the user returns, or when a `<ci-monitor-event>` arrives.

- [ ] **Step 5: CI.**
  - **When `get_status` reports every check passing,** confirm that the harnesses ran rather than skipped. Read the run's log once:

```bash
run=$(gh run list --branch feat/reflection-public-site --workflow ci.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run view "$run" --log > "$SCRATCH/pr2/ci-$run.log"
grep -oE 'tests/[A-Za-z0-9_/]+\.py [.sFEx]+' "$SCRATCH/pr2/ci-$run.log" \
    | grep -E 'test_(public_states|contrast|theme|public_page_csp|copy_buttons|focus_ring|reduced_motion|public_page_structure)\.py'
grep -oE 'tests/[A-Za-z0-9_/]+\.py [.sFEx]+' "$SCRATCH/pr2/ci-$run.log" | awk '$2 ~ /s/'
```

  Expected: each listed file shows only dots. The only skips are the two in `tests/test_health_check_redact.py`, which PR 1's CI had too.

  - **If a check fails,** read it with `gh run view "$run" --log-failed`, and route the failing lines to the owner of the file they point at. After the fix, re-run Step 1, and Task 8 if `frontend/public` changed, then push.
  - An Auto-fix event is routed to the owner the same way, never patched across roles.
  - CI runs Google Chrome where the dry run used Chromium. A contrast probe that measures differently there is a real finding: fix the colour, never the threshold.

- [ ] **Step 6: the merge, with the user's approval, held for the soak.**
  - Ask with AskUserQuestion, offering:
    - **"Hold the merge until 2026-10-03 10:05 UTC (Recommended)":** `main` stays deployable in the meantime;
    - **"Merge now":** then no deploy of `main` may run before 2026-10-03 10:05 UTC. Record that freeze in the memory until Step 7 has run.
  - When approved (and, for the first option, once the soak has ended), run `gh pr merge <number> --merge --delete-branch`.
  - **Check CI on the merge commit once,** right before asking to deploy:

```bash
git fetch -q origin
sha=$(git rev-parse origin/main)
gh run list --workflow ci.yml --branch main --limit 5 --json databaseId,headSha,status,conclusion \
    --jq ".[] | select(.headSha == \"$sha\") | \"\(.databaseId) \(.status) \(.conclusion)\""
```

  Expected: one line ending `completed success`. If the run is still going, don't poll: tell the user, end the turn, and check once more when they return. Anything else, stop and report.

- [ ] **Step 7: deploy, with the user's approval.**
  - First check the date, and what production runs now:

```bash
[ "$(date -u +%s)" -ge 1791021900 ] && echo "soak period over" || echo "STOP: PR 2 may not deploy before 2026-10-03 10:05 UTC"
deployed=$(curl -fsS --max-time 10 https://mirror.kalev.systems/api/health | sed -nE 's/.*"version" *: *"([0-9a-f]+)-.*/\1/p')
git fetch -q origin
echo "deployed: ${deployed:-unknown}"
if [ -n "$deployed" ] && git cat-file -e "$deployed^{commit}" 2>/dev/null; then
    git diff --name-only "$deployed" origin/main -- frontend/public
else
    echo "STOP: the live version names no commit this checkout knows"
fi
```

  1791021900 is 2026-10-03 10:05:00 UTC; a literal needs no `date` parsing. Expected:
  - `soak period over`;
  - the deployed version: `ec1c741` (PR 1b's merge), or later;
  - this pull request's files under `frontend/public`, which are `404.html`, `50x.html`, `css/error.css`, `css/style.css`, `css/tokens.css`, `index.html` and `js/main.js`. That is 7 files; call the count N.

  On either `STOP`, stop.

  - **Ask with AskUserQuestion.** Show the exact command, `ssh root@46.4.100.234 'cd /opt/bsdmirror && scripts/deploy.sh --yes main'`, and what the wrapper adds: the health-timer wait and the redaction.
  - If approved, run `bash "$SCRATCH/pr1/deploy_and_verify.sh" "$PWD" "$SCRATCH/pr2"` with `run_in_background: true`.
  - **If the permission layer refuses it,** nothing in the script ran. Stop, and hand the user the ssh command to run themselves, with a start time clear of the hourly health timer: between about :08 and :50 past the hour (`RandomizedDelaySec=5m`). Carry on with the checks below once they report the result.
  - **Expected in the wrapper's output:**
    - `deploy.sh rc=0`;
    - `[ OK ] all N changed frontend/public/ file(s) match the checkout byte-for-byte`;
    - `[ OK ] all 10 probed paths carry the full 5-header set`;
    - `[ OK ] one Content-Security-Policy value across all probed paths`;
    - `[ OK ] served Content-Security-Policy matches nginx/nginx.conf in this checkout`;
    - `[ OK ] pages, CSS and JS revalidate, fonts stay immutable, and the console loads twice with no 503`;
    - `[ OK ] all post-deploy checks passed`, then `DEPLOYED AND VERIFIED`, with `nginx  config applied and gracefully reloaded` (the comment change);
    - under `== live version ==`, the merge commit.

    Paste any `retrying` warnings; they are the retry doing its job.

  **Then check by hand:**

```bash
SITE=https://mirror.kalev.systems
curl -fsS --max-time 10 "$SITE/" | grep -c '>Every BSD, mirrored.</h1>'
code=$(curl -sS --max-time 10 -o "$SCRATCH/pr2/live-404.html" -w '%{http_code}' "$SITE/css/nope-visual-404.css"); echo "404 probe: $code"
grep -c '>Page not found</h1>' "$SCRATCH/pr2/live-404.html"
curl -fsS --max-time 10 "$SITE/api/stats/overview" | head -c 200; echo
```

  Expected:
  - `1`;
  - `404 probe: 404`: a missing stylesheet gets `try_files $uri =404` and then the 404 page, while a missing page path would get the home page;
  - `1`;
  - the overview JSON.

  If `deploy.sh` exits non-zero, or anything differs, stop. Report the output, and ask the user before any rollback or other production action.

- [ ] **Step 8: update the memory.** In `bsdmirror-reflection-redesign`, record:
  - that PR 2 is done, with its PR number, merge commit and deploy date;
  - that the admin console still runs on the legacy block until PR 3;
  - the follow-ups from Step 4 that PR 3 must pick up.

  Clear any deploy freeze recorded in Step 6.
