# Reflection PR 3 (the admin console) Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the admin console in the Reflection style, in light and dark:
- the console follows the site's saved theme, with its own toggle;
- the sidebar carries the b|d mark and mask icons, and becomes a scrollable bar on small screens;
- KPI tiles with the disk meter, pills for every status, tables, forms, buttons, modal, toasts and the login card in the shared tokens;
- the legacy token block is gone, so both admin themes take their colours from the shared layers;
- Inter is removed.

**Architecture:**
- **Groundwork: three tasks with no restyling.**
  - The console loads `theme-init.js`, gains an `AdminTheme` object and a working toggle. The legacy block still pins every admin colour, so flipping the theme changes nothing yet.
  - The plumbing the redesign needs: the toast animation as a class, nav links with an `href`, a toast container on the login page, dialog semantics, the critical disk threshold.
  - Eleven icons join the set.
- **The switch.** One commit deletes the legacy block, rewrites `admin.css`, changes the markup `admin.js` emits, and rewrites the contrast tests that pin all three, in both themes. They can't land apart: the contrast tests read the stylesheet's selectors and the tokens' values, and the harness renders the markup.
- **Cleanup.** Inter's files go once nothing references them.

**Tech stack:**
- static HTML and CSS with no build step;
- vanilla JavaScript, rendered through the `html` tagged template;
- pytest in the compose `test` service;
- Node 22 harnesses in a `vm` sandbox or headless Chromium over the DevTools protocol (`tests/js/`);
- one line of `scripts/deploy.sh` and one nginx comment.

**Spec:** [2026-09-25-reflection-redesign.md](2026-09-25-reflection-redesign.md), sections 3, 4.1-4.8, 6, 7, 9, 10 and 11.

**Earliest deploy:** after PR 2's deploy, which happened on 2026-09-27 (spec section 8: PR 3 needs no extra wait, because every CSS and JS file already revalidates).

**Dry run.** Every code block in Tasks 1 to 5 was built in a throwaway export of this branch and run in the test image, tests first. Each chunk was then reviewed independently: the reviewers re-applied the chunk's blocks onto the parent commit and compared the result with the task's commit byte for byte, reproduced the red and green runs, and planted defects to see the new tests fail. The five tasks were then applied in order on one branch, where every whole-suite count below was observed, and every code block in this file was checked once more against those in-order commits.

| After | Whole suite |
|---|---|
| the base (`ff29094`) | 1560 passed |
| Task 1 | 1578 |
| Task 2 | 1590 |
| Task 3 | 1623 |
| Task 4 | 1779 |
| Task 5 | 1764 |

Tasks 6 and 7 touch the visual check, GitHub and production. Their scripts ran against the export; their GitHub and production steps did not.

**Before Task 1** (*controller*): commit this plan on the branch as its first commit:

```bash
git add docs/design/2026-09-27-reflection-pr3-plan.md
git commit -m "Add the Reflection PR 3 plan"
```

**Decisions the user approved on 2026-09-27, together with this plan:**
- **One PR, in chunks,** rather than a plumbing PR and a restyle PR.
- **Eleven new icons** (`warning`, `clock`, `disk`, `log-out`, `plus`, `edit`, `trash`, `user`, `lock`, `unlock`, `skip`), so no emoji survives.
- **Three fixes ride along,** none of them in the spec: sidebar links get an `href`; the login page gets a toast container, so "Invalid credentials" shows; modals get dialog semantics and their form labels get `for=`.
- **Not included:** an admin-only gate on the `settings` route, and the fact that a re-render wipes open toasts and modals. Both are in the follow-up list.

**Choices the spec leaves open, made here:**
- the pill mapping keeps today's `status-badge` class names, adds the five job-status modifiers, moves protection "unknown" to the neutral pill (spec 4.8), and shows roles as `info` for admin and neutral otherwise;
- the disk meter's width is a `data-percent` attribute the stylesheet reads, so nothing writes an element style;
- under 768px the sidebar is a horizontal, scrollable bar: the mark, the nav items, then the avatar and Logout;
- the header keeps "View Public Site" and adds the toggle before it;
- the admin layer of `tokens.css` keeps one token, `--sidebar-width: 188px`;
- spec 4.4's card lift (3px, with `--shadow-card-hover`) applies to the KPI tiles, which are the console's clickable-looking cards; the content panels (`.card`) stay flat, as the approved mockup drew them;
- the mirror modal's history rows show each job's status as a pill and drop the bare status word that used to follow it, as the dashboard's Recent Sync Jobs rows do.

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
- Anything that can outlast a few minutes runs with the Bash tool's `run_in_background: true`, and the controller waits for its exit notification. That covers the deploy. CI is never waited on or polled: after a pull request opens, the app's `ccd_pr` tools report it (Task 7 Steps 4 to 6), and a one-off `gh run list` or `gh run view` is fine. The tool stops a foreground command after at most 10 minutes, and killing the ssh session mid-deploy can interrupt the deploy itself.

**Controller steps** are marked *controller*. The session that dispatches the tasks does them itself, because they ask the user something, touch GitHub or production, or edit the working agreement in `CLAUDE.md`.

**Counts.** Every count in this plan was observed in the dry run. The base, `main` at `ff29094`, gives `1560 passed`, rc=0.
## Files

| File | Change | Owner | Tasks |
|---|---|---|---|
| `frontend/public/admin/index.html` | Loads `theme-init.js`; the static `data-theme="dark"` goes | web-designer | 1 |
| `frontend/public/admin/js/admin.js` | `AdminTheme` and the toggle; the plumbing fixes; then the markup: icons, pills, the meter, the mark | developer | 1, 2, 4 |
| `frontend/public/admin/css/admin.css` | The icon and toggle rules; the toast's leaving class; then rewritten for the new console | web-designer | 1, 2, 4 |
| `frontend/public/css/tokens.css` | The legacy block and the non-colour group deleted; the admin layer keeps `--sidebar-width` | web-designer | 4 |
| `frontend/public/img/icons/*.svg` | Eleven new icons | web-designer | 3 |
| `frontend/public/img/README.md` | The icon count | web-designer | 3 |
| `frontend/public/css/fonts.css`, `frontend/public/fonts/` | Inter's faces, files, licence and README rows removed | web-designer | 5 |
| `scripts/deploy.sh` | The console probe list gains `theme-init.js` | devops-sre | 1 |
| `nginx/nginx.conf` | The CSP comment no longer cites the toast's style write | devops-sre | 2 |
| `tests/js/admin_theme_harness.mjs`, `tests/test_admin_theme.py` | New. The toggle, the system listener, the guards, and `admin/index.html`'s head | developer | 1 |
| `tests/test_deploy_live_headers.py` | `CONSOLE` gains `theme-init.js`; the console-list check moves to `HTMLParser` | developer | 1 |
| `tests/js/escaping_harness.mjs`, `tests/test_admin_js_escaping.py` | Class and text pins for the toggle, the plumbing and the new markup | developer | 1, 2, 4 |
| `tests/test_images.py` | The favicon-link collector scoped to `<head>`; `ICON_NAMES` gains eleven | developer | 2, 3 |
| `tests/test_contrast.py` | The admin half checked in both themes; the legacy guard replaced | developer | 4 |
| `tests/js/contrast_harness.mjs` | The admin fixture rendered in both themes | developer | 4 |
| `tests/test_legacy_admin_tokens.py` | Deleted | developer | 4 |
| `tests/test_reduced_motion.py`, `tests/test_focus_ring.py` | `admin.css` joins their stylesheet lists | developer | 4 |
| `tests/test_admin_inline_styles.py` | Unchanged unless a utility class is added | developer | 4 |
| `docs/design/2026-09-27-reflection-pr3-plan.md` | This plan | controller | before Task 1 |

---
## Chunk 1: Groundwork, with no restyling

Three tasks that change no styling. The console starts following the site's saved theme (the legacy token block still pins every admin colour, so nothing visible moves except a working toggle); the plumbing the redesign needs lands; and eleven icons join the set.

### Task 1: The admin console follows the site's theme

Spec section 6.2 is the contract. `admin/index.html` hardcodes
`data-theme="dark"` today, and `admin.js` has no theme code at all: no
`setAttribute` call, no `matchMedia`, no `'theme'` storage key anywhere in
the file. This task gives the console the same `theme-init.js` +
adopt-and-toggle contract the public page already has
(`tests/test_theme.py`), plus its own `data-action` toggle button, wired
through the existing click delegation (constraint 7:
"any control, including a theme toggle, must go through the existing
`data-action` click delegation... That delegation passes only `dataset.id`
to its handlers" -- which is why the toggle takes no argument and reads its
own state instead). `tokens.css`'s admin layer still holds the legacy block
that pins every admin colour as a literal hex, so flipping `data-theme`
changes nothing else yet -- that is what makes this a groundwork task. No
`<svg>`/`<img>` is introduced anywhere in admin markup (constraint 2): both
the toggle's icon and, later, every other admin icon are CSS masks on
`<span>` elements, matching the public site's `.icon` rule.

**Owners:** developer for `admin.js` and all the tests; web-designer for
`admin/index.html` and the small CSS addition; devops-sre for the one line of
`scripts/deploy.sh`. Steps run in the order they are listed: the tests first
(red), then the implementation (green file by file), then the regression
sweep and the whole suite, then the commit.

**Decisions this step made** (spec 6.2 sets the contract; these are the
choices it left open):
- `tests/test_admin_js_escaping.py`'s `HARNESS_CHECKS` list has to move too:
  `test_harness_check_list_is_complete` asserts the parametrized list equals
  the harness's own output set, so the two new `escaping_harness.mjs` checks
  (below) need a matching entry there or that guard test fails on its own.
- `AdminTheme` sits right after the "Display Thresholds" section and before
  "API Client" -- `main.js` puts its own `ThemeManager` in the same relative
  spot (before "API client"); spec 6.2 does not pin an exact line.
- Spec 6.2 describes the toggle's behaviour in prose (flip and save with
  storage in try/catch, an icon and `aria-label` rendered from the attribute,
  a guarded `matchMedia` listener that updates the toggle exactly as the
  click handler does) without naming an object. This task groups the
  storage-and-attribute half into an `AdminTheme` object with five members
  (`STORAGE_KEY`, `current`, `apply`, `save`, `saved`, `init`) and puts the
  "update every `.theme-toggle` in the document in place" half -- needed by
  both `actions.toggleTheme` and the `matchMedia` listener -- in a standalone
  `updateThemeToggles()` function instead, defined next to
  `renderThemeToggle()`, rather than as a sixth `AdminTheme` method.
- `actions.toggleTheme` sits directly after `logout()`: both are chrome-level
  actions with no page-specific data, unlike the `mirrorId`/`userId`-scoped
  actions that follow.
- The toggle on the login card renders as the first child of `.login-card`,
  before `.login-header`, in normal document flow, with no positioning CSS:
  spec 6.1's KPI/shell restyle (Task 4) is what actually places every
  console component, the login card included.
- `tests/js/admin_theme_harness.mjs` pins twelve individually named checks
  (mirroring `tests/js/theme_harness.mjs`'s granularity, where fourteen
  checks cover a smaller contract) for spec 6.2's contract: adopting the
  theme on load, flipping and saving it, updating every rendered toggle in
  place, following the system preference only while nothing is saved,
  tolerating a throwing storage in both directions (read and write), and
  rendering exactly one toggle -- with its icon matching the attribute -- on
  both the layout and the login page.
- Section 10 says only that "the admin toggle gets harness checks in PR 3",
  not which paths they must cover, so the "no `documentElement`/`matchMedia`"
  check exercises every function that touches either guard, not just the two
  render functions it started with: `AdminTheme.init()` is the only caller of
  `window.matchMedia`, and `actions.toggleTheme()` is the only caller of
  `apply()` outside a render, so the check calls both before rendering and
  asserts neither throws. Removing either guard in `admin.js` (`if
  (document.documentElement)` in `apply()`, or the `typeof window.matchMedia
  === 'function'` check in `init()`) now fails exactly this check with a
  thrown `TypeError`; before this check called them, both guards were dead
  code as far as the suite could tell.

**Files:**
- Create: `tests/js/admin_theme_harness.mjs`, `tests/test_admin_theme.py`
- Modify: `tests/js/escaping_harness.mjs` (export `renderLoginPage`; two new
  checks), `tests/test_admin_js_escaping.py` (`HARNESS_CHECKS` gains the two
  names), `tests/test_deploy_live_headers.py` (`CONSOLE` gains
  `/js/theme-init.js`; the console-list test moves to `HTMLParser`)
- Modify: `frontend/public/admin/index.html` (drop `data-theme="dark"`, load
  `theme-init.js`)
- Modify: `frontend/public/admin/js/admin.js` (`AdminTheme`,
  `renderThemeToggle`, `updateThemeToggles`, the toggle in `renderLayout` and
  `renderLoginPage`, `actions.toggleTheme`, `AdminTheme.init()` in `init`)
- Modify: `frontend/public/admin/css/admin.css` (`.icon`, `.icon-sun`,
  `.icon-moon`, `.theme-toggle`)
- Modify: `scripts/deploy.sh` (the `console` array)

- [ ] **Step 1 (developer): write `tests/js/admin_theme_harness.mjs`.** New
  file, modelled on `tests/js/theme_harness.mjs`'s shape (a `load()`/`makePage()`
  builder, a `check`/`expect`/`all` runner, one JSON object on stdout) but
  loading the whole of `admin.js` the way `escaping_harness.mjs` does, since
  `AdminTheme` is one `const` among hundreds of lines this file must still
  parse and evaluate without throwing.

```js
/**
 * Theme harness for the AdminTheme object in frontend/public/admin/js/admin.js
 * and the toggle button renderLayout/renderLoginPage render around it.
 *
 * Loads the real admin.js in a Node vm context, the same way
 * escaping_harness.mjs does, with only the DOM surface AdminTheme and the
 * toggle touch stubbed. Two shapes matter
 * (docs/design/2026-09-25-reflection-redesign.md, section 6.2): one with
 * document.documentElement and window.matchMedia, and one with neither -- the
 * shape tests/js/escaping_harness.mjs and tests/js/contrast_harness.mjs
 * already load this file in, so every top-level theme access must be
 * guarded. Prints one JSON object, {checkName: [ok, detail]}, for
 * tests/test_admin_theme.py to assert on.
 *
 * Usage:  node admin_theme_harness.mjs <path-to-admin.js>
 */
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const [adminPath] = process.argv.slice(2);
const SOURCE = readFileSync(adminPath, 'utf8');

// admin.js has no exports; its top-level bindings are `const`/`function`. The
// trailing expression is the script's completion value, the same trick
// escaping_harness.mjs uses to get at them.
const EPILOGUE = `
;({ AdminTheme, renderThemeToggle, renderLayout, renderLoginPage, actions, state, html });
`;

/** One fake <button class="theme-toggle"> with a nested <span class="icon">. */
function makeToggle() {
    const attrs = new Map([['aria-label', 'Toggle theme']]);
    const icon = { className: 'icon icon-moon' };
    return {
        setAttribute: (name, value) => attrs.set(name, String(value)),
        getAttribute: (name) => (attrs.has(name) ? attrs.get(name) : null),
        querySelector: (selector) => (selector === '.icon' ? icon : null),
        label: () => attrs.get('aria-label'),
        iconClass: () => icon.className,
    };
}

/**
 * A fresh admin.js load. `documentElement: false` and `matchMedia: false`
 * reproduce the sandboxes escaping_harness.mjs and contrast_harness.mjs load
 * this file into, which have neither.
 */
function load({
    documentElement = true,
    matchMedia = true,
    initialTheme = null,
    saved = null,
    getThrows = false,
    setThrows = false,
    toggles = [],
} = {}) {
    const store = new Map(saved === null ? [] : [['theme', saved]]);
    const storage = {
        getItem: (key) => {
            if (getThrows) throw new Error('SecurityError: site data is blocked');
            return store.has(key) ? store.get(key) : null;
        },
        setItem: (key, value) => {
            if (setThrows) throw new Error('QuotaExceededError');
            store.set(key, String(value));
        },
        removeItem: (key) => store.delete(key),
    };

    const htmlAttrs = new Map(initialTheme === null ? [] : [['data-theme', initialTheme]]);
    const doc = {
        addEventListener: () => {},
        getElementById: () => null,
        createElement: () => ({ style: {}, remove() {} }),
        querySelectorAll: (selector) => (selector === '.theme-toggle' ? toggles : []),
    };
    if (documentElement) {
        doc.documentElement = {
            getAttribute: (name) => (htmlAttrs.has(name) ? htmlAttrs.get(name) : null),
            setAttribute: (name, value) => htmlAttrs.set(name, String(value)),
        };
    }

    const mediaListeners = [];
    const media = {
        matches: false,
        addEventListener: (type, fn) => { if (type === 'change') mediaListeners.push(fn); },
    };
    const win = { addEventListener() {}, history: { pushState() {} }, location: { hash: '' } };
    if (matchMedia) {
        win.matchMedia = (query) =>
            (query === '(prefers-color-scheme: dark)' ? media : { matches: false, addEventListener: () => {} });
    }

    const sandbox = {
        console,
        setTimeout: () => 0,
        setInterval: () => 0,
        clearTimeout: () => {},
        document: doc,
        window: win,
        localStorage: storage,
        fetch: async () => { throw new Error('network disabled in harness'); },
    };
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    const mod = vm.runInContext(SOURCE + EPILOGUE, sandbox, { filename: adminPath });

    return {
        mod,
        theme: () => (htmlAttrs.has('data-theme') ? htmlAttrs.get('data-theme') : null),
        stored: () => (store.has('theme') ? store.get('theme') : null),
        fireSystemChange: (dark) => {
            media.matches = dark;
            mediaListeners.forEach((fn) => fn({ matches: dark }));
        },
    };
}

const results = {};

function check(name, fn) {
    try {
        const outcome = fn();
        results[name] = outcome === true ? [true, ''] : [false, String(outcome)];
    } catch (err) {
        results[name] = [false, `threw: ${(err && err.stack) || err}`];
    }
}

const expect = (actual, expected, what) =>
    actual === expected ? true : `${what}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`;

const all = (...outcomes) => outcomes.find((outcome) => outcome !== true) ?? true;

check('a fresh load adopts html[data-theme]', () => {
    const page = load({ initialTheme: 'dark' });
    return expect(page.mod.AdminTheme.current(), 'dark', 'AdminTheme.current()');
});

check('current falls back to light when no attribute is set', () => {
    const page = load({ initialTheme: null });
    return expect(page.mod.AdminTheme.current(), 'light', 'AdminTheme.current()');
});

check('current falls back to light with no documentElement', () => {
    const page = load({ documentElement: false });
    return expect(page.mod.AdminTheme.current(), 'light', 'AdminTheme.current()');
});

check('renderThemeToggle returns the markup for the current theme', () => {
    const page = load({ initialTheme: 'dark' });
    const out = String(page.mod.renderThemeToggle());
    return all(
        expect(out.includes('data-action="toggleTheme"'), true, 'data-action'),
        expect(out.includes('type="button"'), true, 'type=button'),
        expect(out.includes('class="theme-toggle"'), true, 'toggle class'),
        expect(out.includes('aria-label="Switch to light theme"'), true, 'aria-label'),
        expect(out.includes('icon icon-sun'), true, 'icon class'),
    );
});

check('toggleTheme flips the attribute, saves the choice, and updates every toggle in place', () => {
    const toggles = [makeToggle(), makeToggle()];
    const page = load({ initialTheme: 'light', toggles });
    page.mod.actions.toggleTheme();
    return all(
        expect(page.theme(), 'dark', 'data-theme'),
        expect(page.stored(), 'dark', 'stored theme'),
        ...toggles.flatMap((toggle, i) => [
            expect(toggle.label(), 'Switch to light theme', `toggle ${i} aria-label`),
            expect(toggle.iconClass(), 'icon icon-sun', `toggle ${i} icon class`),
        ]),
    );
});

check('a failing storage write still flips the theme and updates the toggle', () => {
    const toggles = [makeToggle()];
    const page = load({ initialTheme: 'light', setThrows: true, toggles });
    page.mod.actions.toggleTheme();
    return all(
        expect(page.theme(), 'dark', 'data-theme'),
        expect(toggles[0].iconClass(), 'icon icon-sun', 'toggle icon class'),
    );
});

check('a failing storage read is treated as nothing saved', () => {
    const page = load({ initialTheme: 'light', getThrows: true });
    page.mod.AdminTheme.init();
    page.fireSystemChange(true);
    return expect(page.theme(), 'dark', 'data-theme');
});

check('the system listener applies the OS theme while nothing is saved', () => {
    const toggles = [makeToggle()];
    const page = load({ initialTheme: 'light', saved: null, toggles });
    page.mod.AdminTheme.init();
    page.fireSystemChange(true);
    return all(
        expect(page.theme(), 'dark', 'data-theme'),
        expect(toggles[0].iconClass(), 'icon icon-sun', 'toggle icon class'),
    );
});

check('the system listener is ignored once a choice is saved', () => {
    const page = load({ initialTheme: 'light', saved: 'light' });
    page.mod.AdminTheme.init();
    page.fireSystemChange(true);
    return expect(page.theme(), 'light', 'data-theme');
});

check('a sandbox with no documentElement and no matchMedia still loads and renders the layout', () => {
    const page = load({ documentElement: false, matchMedia: false });
    // init() and toggleTheme() are the two paths render alone never reaches:
    // init() is the only caller of window.matchMedia, and toggleTheme() is
    // the only caller of apply() outside a render. If either guard were
    // missing, this call -- not the render below -- is what would throw.
    page.mod.AdminTheme.init();
    page.mod.actions.toggleTheme();
    const layout = String(page.mod.renderLayout(page.mod.html`<p>x</p>`, 'Dashboard'));
    const login = String(page.mod.renderLoginPage());
    return all(
        expect((layout.match(/data-action="toggleTheme"/g) || []).length, 1, 'layout toggle count'),
        expect((login.match(/data-action="toggleTheme"/g) || []).length, 1, 'login toggle count'),
        expect(layout.includes('icon icon-moon'), true, 'layout falls back to the light icon'),
    );
});

check('renderLayout renders exactly one theme toggle whose icon matches the attribute', () => {
    const page = load({ initialTheme: 'dark' });
    const out = String(page.mod.renderLayout(page.mod.html`<p>x</p>`, 'Dashboard'));
    return all(
        expect((out.match(/data-action="toggleTheme"/g) || []).length, 1, 'toggle count'),
        expect(out.includes('icon icon-sun'), true, 'dark theme should render the sun icon'),
        expect(out.includes('icon icon-moon'), false, 'dark theme should not render the moon icon'),
    );
});

check('renderLoginPage renders exactly one theme toggle whose icon matches the attribute', () => {
    const page = load({ initialTheme: 'light' });
    const out = String(page.mod.renderLoginPage());
    return all(
        expect((out.match(/data-action="toggleTheme"/g) || []).length, 1, 'toggle count'),
        expect(out.includes('icon icon-moon'), true, 'light theme should render the moon icon'),
        expect(out.includes('icon icon-sun'), false, 'light theme should not render the sun icon'),
    );
});

process.stdout.write(JSON.stringify(results));
```

- [ ] **Step 2 (developer): write `tests/test_admin_theme.py`.** New file,
  in `tests/test_theme.py`'s shape: a `harness_results` fixture that shells
  out to Node, a parametrized behavioural test over a pinned `CHECKS` list, a
  completeness guard, and -- since this task also touches
  `admin/index.html` -- the three static pins `tests/test_theme.py:83-89`
  runs for the public page, aimed at the admin one instead.

```python
"""The admin console follows the site's theme (spec 6.2, "Light theme").

admin/index.html used to hardcode data-theme="dark" and admin.js had no theme
code at all: zero setAttribute calls, no matchMedia, no 'theme' storage key.
The console now loads js/theme-init.js exactly like the public page, and
admin.js's AdminTheme object adopts whatever that already set, keeps every
rendered toggle in step, and saves only an explicit choice -- the same
contract as main.js's ThemeManager (tests/test_theme.py), applied to a page
whose toggle is a data-action button inside a re-rendered layout rather than
a single static element.

tests/js/admin_theme_harness.mjs runs the real admin.js in a Node vm, in two
shapes: one with document.documentElement and window.matchMedia, and one with
neither -- the shape tests/js/escaping_harness.mjs and tests/js/
contrast_harness.mjs already load this file into, so every top-level theme
access must be guarded.
"""

import json
import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ADMIN_JS = REPO_ROOT / "frontend" / "public" / "admin" / "js" / "admin.js"
ADMIN_INDEX = REPO_ROOT / "frontend" / "public" / "admin" / "index.html"
HARNESS = REPO_ROOT / "tests" / "js" / "admin_theme_harness.mjs"
NODE = shutil.which("node")

requires_node = pytest.mark.skipif(
    NODE is None, reason="node is not installed; the admin theme behaviour checks cannot run"
)

CHECKS = [
    "a fresh load adopts html[data-theme]",
    "current falls back to light when no attribute is set",
    "current falls back to light with no documentElement",
    "renderThemeToggle returns the markup for the current theme",
    "toggleTheme flips the attribute, saves the choice, and updates every toggle in place",
    "a failing storage write still flips the theme and updates the toggle",
    "a failing storage read is treated as nothing saved",
    "the system listener applies the OS theme while nothing is saved",
    "the system listener is ignored once a choice is saved",
    "a sandbox with no documentElement and no matchMedia still loads and renders the layout",
    "renderLayout renders exactly one theme toggle whose icon matches the attribute",
    "renderLoginPage renders exactly one theme toggle whose icon matches the attribute",
]


@pytest.fixture(scope="module")
def harness_results():
    proc = subprocess.run(
        [NODE, str(HARNESS), str(ADMIN_JS)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@requires_node
@pytest.mark.parametrize("name", CHECKS)
def test_admin_theme_behaviour(harness_results, name):
    assert name in harness_results, f"harness did not run {name!r}"
    ok, detail = harness_results[name]
    assert ok, detail


@requires_node
def test_the_harness_runs_exactly_these_checks(harness_results):
    assert set(harness_results) == set(CHECKS)


def _html_tag(text):
    """The literal `<html ...>` opening tag, not `<!DOCTYPE html>` before it."""
    start = text.index("<html")
    end = text.index(">", start)
    return text[start : end + 1]


def test_admin_index_has_no_static_data_theme():
    tag = _html_tag(ADMIN_INDEX.read_text(encoding="utf-8"))
    assert "data-theme" not in tag, (
        "admin/index.html must not hardcode a theme; js/theme-init.js sets data-theme "
        "before the first paint, the same as the public page"
    )


def test_admin_index_keeps_data_surface_admin():
    tag = _html_tag(ADMIN_INDEX.read_text(encoding="utf-8"))
    assert 'data-surface="admin"' in tag, 'data-surface="admin" selects the admin token layer'


def test_admin_theme_init_runs_in_head_before_the_stylesheets():
    head = ADMIN_INDEX.read_text(encoding="utf-8").split("</head>", 1)[0]
    script = head.find('<script src="/js/theme-init.js"></script>')
    first_stylesheet = head.find('<link rel="stylesheet"')
    assert script != -1, "admin/index.html does not load /js/theme-init.js in <head>"
    assert first_stylesheet != -1, "admin/index.html <head> has no stylesheet"
    assert script < first_stylesheet, "theme-init.js must run before the stylesheets apply"
```

- [ ] **Step 3 (developer): run `tests/test_admin_theme.py`, and watch it
  fail.**

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_admin_theme.py; echo "rc=$?"`

  Expected: `rc=1`, `14 failed, 2 passed, 4 warnings`. All twelve behavioural
  checks fail the same way, because `admin.js` has no `AdminTheme` binding
  yet -- the harness's own epilogue throws before any check body runs, so
  this count and message are the same whether or not a check's body later
  calls `AdminTheme.init()` or `actions.toggleTheme()`:

  ```
  AssertionError: threw: /repo/frontend/public/admin/js/admin.js:1844
  ;({ AdminTheme, renderThemeToggle, renderLayout, renderLoginPage, actions, state, html });
      ^

  ReferenceError: AdminTheme is not defined
  ```

  The two `admin/index.html` pins fail for their own, different reasons:

  ```
  test_admin_index_has_no_static_data_theme:
    AssertionError: assert 'data-theme' not in '<html lang="en" data-theme="dark" data-surface="admin">'

  test_admin_theme_init_runs_in_head_before_the_stylesheets:
    AssertionError: admin/index.html does not load /js/theme-init.js in <head>
  ```

  The other two pass already: `test_the_harness_runs_exactly_these_checks`
  (the harness still reports all twelve names, each marked failed, so the
  *set* matches) and `test_admin_index_keeps_data_surface_admin`
  (`data-surface="admin"` is already there today).

- [ ] **Step 4 (developer): export `renderLoginPage` and add the two guard
  checks to `tests/js/escaping_harness.mjs`, then add their names to
  `tests/test_admin_js_escaping.py`.** `renderLoginPage` was never in the
  harness's epilogue because nothing before this task needed to render it
  outside a real page load. Replace:

```js
const EPILOGUE = `
;({ html, escapeHtml, interpolateHtml, trustedHtml, setHtml, SafeHtml,
    renderLayout, renderUsers, renderAuditLogs, renderMirrors, renderSettings,
    renderDashboard, renderSyncFailures, renderProtectedPaths, renderHealthChecksCard,
    filesDeletedBadge,
    LARGE_DELETION_THRESHOLD, DISK_USAGE_WARNING_PERCENT, Toast, Modal, api, state });
`;
```

  with:

```js
const EPILOGUE = `
;({ html, escapeHtml, interpolateHtml, trustedHtml, setHtml, SafeHtml,
    renderLayout, renderLoginPage, renderUsers, renderAuditLogs, renderMirrors, renderSettings,
    renderDashboard, renderSyncFailures, renderProtectedPaths, renderHealthChecksCard,
    filesDeletedBadge,
    LARGE_DELETION_THRESHOLD, DISK_USAGE_WARNING_PERCENT, Toast, Modal, api, state });
`;
```

  Then, right after the `renderLayout escapes the logged-in username in the
  sidebar` check and before `Toast.show escapes a hostile server error
  string`, insert the two new checks. Replace:

```js
        assert(out.includes('<p>body</p>'), 'SafeHtml body was escaped instead of passed through');
        return '';
    });

    await check('Toast.show escapes a hostile server error string', () => {
```

  with:

```js
        assert(out.includes('<p>body</p>'), 'SafeHtml body was escaped instead of passed through');
        return '';
    });

    // --- Theme toggle (docs/design/2026-09-25-reflection-redesign.md, 6.2) --
    //
    // Both render functions call AdminTheme.current(), which reads
    // document.documentElement -- absent from this sandbox's document stub
    // above on purpose. These two checks are the guard that the access is
    // properly wrapped: an unguarded read would throw here and fail every
    // check below as a side effect, not just these two.

    await check('renderLayout renders exactly one theme toggle button', () => {
        const out = String(mod.renderLayout(mod.html`<p>body</p>`, 'Dashboard'));
        const count = (out.match(/data-action="toggleTheme"/g) || []).length;
        assert(count === 1, `expected exactly one theme toggle, found ${count} in ${JSON.stringify(out)}`);
        return '';
    });

    await check('renderLoginPage renders exactly one theme toggle button', () => {
        const out = String(mod.renderLoginPage());
        const count = (out.match(/data-action="toggleTheme"/g) || []).length;
        assert(count === 1, `expected exactly one theme toggle, found ${count} in ${JSON.stringify(out)}`);
        return '';
    });

    await check('Toast.show escapes a hostile server error string', () => {
```

  Finally, in `tests/test_admin_js_escaping.py`, `HARNESS_CHECKS` must gain
  the same two names or `test_harness_check_list_is_complete` fails on its
  own. Replace:

```python
    "renderLayout escapes the logged-in username in the sidebar",
    "Toast.show escapes a hostile server error string",
```

  with:

```python
    "renderLayout escapes the logged-in username in the sidebar",
    "renderLayout renders exactly one theme toggle button",
    "renderLoginPage renders exactly one theme toggle button",
    "Toast.show escapes a hostile server error string",
```

- [ ] **Step 5 (developer): `CONSOLE` gains `/js/theme-init.js`, and the
  console-list test moves to `HTMLParser`, in `tests/test_deploy_live_headers.py`.**
  The old regex (`<link rel="stylesheet" href="...">` or `<script
  src="...">`, in that literal attribute order) is what `admin/index.html`'s
  own `rel`-before-`href` convention happens to satisfy today, but it is not
  a property this test should depend on. Replace:

```python
import re
import shutil

import pytest
```

  with:

```python
import re
import shutil
from html.parser import HTMLParser

import pytest
```

  Replace:

```python
CONSOLE = [
    "/admin/",
    "/css/fonts.css",
    "/css/tokens.css",
    "/admin/css/admin.css",
    "/admin/js/admin.js",
]
```

  with:

```python
CONSOLE = [
    "/admin/",
    "/js/theme-init.js",
    "/css/fonts.css",
    "/css/tokens.css",
    "/admin/css/admin.css",
    "/admin/js/admin.js",
]
```

  Replace:

```python
def test_the_console_list_is_what_admin_index_html_loads():
    # deploy.sh runs one deploy behind itself, so when the console's page
    # gains or renames a stylesheet or script, its list must change a deploy
    # ahead. This test is what notices.
    html = (REPO_ROOT / "frontend" / "public" / "admin" / "index.html").read_text(encoding="utf-8")
    assets = re.findall(r'<link rel="stylesheet" href="([^"]+)"|<script src="([^"]+)"', html)
    assert ["/admin/", *(css or js for css, js in assets)] == CONSOLE
```

  with:

```python
class _ConsoleAssetCollector(HTMLParser):
    """Collects stylesheet hrefs and script srcs, in document order.

    A regex anchored on `<link rel="stylesheet" href="...">` breaks the
    moment the two attributes swap order, and a link's rel is a
    space-separated token list, not a single value to equal literally.
    Parsing the markup instead makes both non-issues.
    """

    def __init__(self):
        super().__init__()
        self.assets = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "link" and "stylesheet" in (attrs.get("rel") or "").split():
            if attrs.get("href"):
                self.assets.append(attrs["href"])
        elif tag == "script" and attrs.get("src"):
            self.assets.append(attrs["src"])


def test_the_console_list_is_what_admin_index_html_loads():
    # deploy.sh runs one deploy behind itself, so when the console's page
    # gains or renames a stylesheet or script, its list must change a deploy
    # ahead. This test is what notices.
    html = (REPO_ROOT / "frontend" / "public" / "admin" / "index.html").read_text(encoding="utf-8")
    collector = _ConsoleAssetCollector()
    collector.feed(html)
    assert ["/admin/", *collector.assets] == CONSOLE
```

  `re` stays imported: `test_verify_all_runs_the_cache_check` still uses it
  twice, to find and search `verify_all()`'s body in `scripts/deploy.sh`.

- [ ] **Step 6 (developer): run both files, and watch them fail.**

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_admin_js_escaping.py; echo "rc=$?"`

  Expected: `rc=1`, `2 failed, 85 passed, 4 warnings`. Both new checks fail
  with the same message, `expected exactly one theme toggle, found 0 in
  "..."` -- the `"..."` is the harness's own `JSON.stringify(out)`, the full
  rendered page as one long escaped line (it starts `"\n        <div
  class=\"app-layout\">\n            <aside class=\"sidebar\">\n ...` for
  `renderLayout`, `"\n        <div class=\"login-page\">\n            <div
  class=\"login-card\">\n ...` for `renderLoginPage`), because neither
  function renders a `data-action="toggleTheme"` button yet.

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_deploy_live_headers.py; echo "rc=$?"`

  Expected: `rc=1`, `2 failed, 31 passed, 4 warnings`. Both fail on the same
  gap, from two different angles -- the page itself, and `deploy.sh`'s own
  copy of the same list, which Step 8 has not touched yet either:

  ```
  test_the_console_is_loaded_twice_after_a_pause_without_retries:
    AssertionError: assert ['http://exam...n.woff2', ...] == ['http://exam...n.woff2', ...]
      At index 7 diff: 'http://example.invalid/css/fonts.css' != 'http://example.invalid/js/theme-init.js'
      Right contains 2 more items, first extra item: 'http://example.invalid/admin/css/admin.css'

  test_the_console_list_is_what_admin_index_html_loads:
    AssertionError: assert ['/admin/', '.../js/admin.js'] == ['/admin/', '.../js/admin.js']
      At index 1 diff: '/css/fonts.css' != '/js/theme-init.js'
      Right contains one more item: '/admin/js/admin.js'
  ```

- [ ] **Step 7 (web-designer): `admin/index.html` drops the static theme and
  loads `theme-init.js`.** Keep the favicon links and `rel="stylesheet"`
  order byte-identical; `tests/test_images.py` and
  `tests/test_admin_inline_styles.py` both key on them. Replace:

```html
<html lang="en" data-theme="dark" data-surface="admin">

<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="robots" content="noindex, nofollow">
    <title>BSD Mirror Admin</title>
    <link rel="stylesheet" href="/css/fonts.css">
```

  with:

```html
<html lang="en" data-surface="admin">

<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="robots" content="noindex, nofollow">
    <title>BSD Mirror Admin</title>
    <!-- Sets data-theme before the first paint; see js/theme-init.js. -->
    <script src="/js/theme-init.js"></script>
    <link rel="stylesheet" href="/css/fonts.css">
```

  (the comment is copied verbatim from `frontend/public/index.html`'s own
  `<head>`).

- [ ] **Step 8 (devops-sre): `scripts/deploy.sh`'s console probe list gains
  `/js/theme-init.js`.** `deploy.sh` runs one deploy behind itself, so this
  list change takes effect for the deploy that follows PR 3's, not PR 3's
  own deploy -- the comment above it already says so. Replace:

```bash
    local -a console=(/admin/ /css/fonts.css /css/tokens.css /admin/css/admin.css /admin/js/admin.js)
```

  with:

```bash
    local -a console=(/admin/ /js/theme-init.js /css/fonts.css /css/tokens.css /admin/css/admin.css /admin/js/admin.js)
```

- [ ] **Step 9 (developer): add `AdminTheme`, `renderThemeToggle` and
  `updateThemeToggles` to `admin.js`.** Placed after "Display Thresholds"
  and before "API Client" -- the same relative position `main.js` gives its
  own `ThemeManager`. Replace:

```js
// rsync's --delete (always on; see sync/sync_service.py) removes a handful
// of stale files on almost every ordinary sync. A files_deleted count this
// large is well outside that and is the signature of a mass removal -- most
// plausibly an EOL release shared/protected_paths.py's filter did not cover.
const LARGE_DELETION_THRESHOLD = 1000;

// ===========================================
// API Client
// ===========================================
```

  with:

```js
// rsync's --delete (always on; see sync/sync_service.py) removes a handful
// of stale files on almost every ordinary sync. A files_deleted count this
// large is well outside that and is the signature of a mass removal -- most
// plausibly an EOL release shared/protected_paths.py's filter did not cover.
const LARGE_DELETION_THRESHOLD = 1000;

// ===========================================
// Theme
// ===========================================
//
// One 'theme' key in localStorage across the site and the console (spec
// 6.2). js/theme-init.js has already applied it to <html> before the first
// paint; AdminTheme adopts that, keeps every rendered toggle in step, and
// saves only an explicit choice -- the same contract as main.js's
// ThemeManager. Every document.documentElement access is guarded: the
// escaping and contrast harnesses load this file into a vm with no
// documentElement and no matchMedia, and admin.js must still load and render
// there.
const AdminTheme = {
    STORAGE_KEY: 'theme',
    SYSTEM_DARK: '(prefers-color-scheme: dark)',

    current() {
        const theme = document.documentElement && document.documentElement.getAttribute('data-theme');
        return theme === 'light' || theme === 'dark' ? theme : 'light';
    },

    apply(theme) {
        if (document.documentElement) {
            document.documentElement.setAttribute('data-theme', theme);
        }
    },

    save(theme) {
        try {
            localStorage.setItem(AdminTheme.STORAGE_KEY, theme);
        } catch {
            // Storage unavailable: the choice lasts for this page view only.
        }
    },

    saved() {
        try {
            const value = localStorage.getItem(AdminTheme.STORAGE_KEY);
            return value === 'light' || value === 'dark' ? value : null;
        } catch {
            return null;
        }
    },

    init() {
        const media = typeof window.matchMedia === 'function' ? window.matchMedia(AdminTheme.SYSTEM_DARK) : null;
        media?.addEventListener?.('change', (event) => {
            if (AdminTheme.saved() === null) {
                AdminTheme.apply(event.matches ? 'dark' : 'light');
                updateThemeToggles();
            }
        });
    }
};

/** The button rendered in .header-actions and on the login card. */
function renderThemeToggle() {
    const theme = AdminTheme.current();
    return html`
        <button type="button" class="theme-toggle" data-action="toggleTheme" aria-label="${theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}">
            <span class="${theme === 'dark' ? 'icon icon-sun' : 'icon icon-moon'}" aria-hidden="true"></span>
        </button>
    `;
}

// Only the dashboard re-renders on its own (the 30s refresh below), so
// actions.toggleTheme and the matchMedia listener above both update every
// rendered toggle in place instead of waiting for a re-render that may never
// come.
function updateThemeToggles() {
    const theme = AdminTheme.current();
    const label = theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme';
    const iconClass = theme === 'dark' ? 'icon icon-sun' : 'icon icon-moon';
    document.querySelectorAll('.theme-toggle').forEach((toggle) => {
        toggle.setAttribute('aria-label', label);
        const icon = toggle.querySelector('.icon');
        if (icon) {
            icon.className = iconClass;
        }
    });
}

// ===========================================
// API Client
// ===========================================
```

- [ ] **Step 10 (developer): wire the toggle into `renderLayout`,
  `renderLoginPage`, `actions`, and `init`.** Four small hunks in the same
  file. First, `.header-actions`. Replace:

```js
                    <h1 class="header-title">${title}</h1>
                    <div class="header-actions">
                        <a href="/" class="btn btn-secondary btn-sm" target="_blank">
                            View Public Site
                        </a>
                    </div>
```

  with:

```js
                    <h1 class="header-title">${title}</h1>
                    <div class="header-actions">
                        ${renderThemeToggle()}
                        <a href="/" class="btn btn-secondary btn-sm" target="_blank">
                            View Public Site
                        </a>
                    </div>
```

  Then the login card. Replace:

```js
        <div class="login-page">
            <div class="login-card">
                <div class="login-header">
                    <div class="login-logo">🔄</div>
```

  with:

```js
        <div class="login-page">
            <div class="login-card">
                ${renderThemeToggle()}
                <div class="login-header">
                    <div class="login-logo">🔄</div>
```

  Then `actions.toggleTheme`, right after `logout`. Replace:

```js
    logout() {
        api.logout();
        Toast.show('Logged out', 'success');
    },

    async syncMirror(mirrorId) {
```

  with:

```js
    logout() {
        api.logout();
        Toast.show('Logged out', 'success');
    },

    toggleTheme() {
        const theme = AdminTheme.current() === 'dark' ? 'light' : 'dark';
        AdminTheme.apply(theme);
        AdminTheme.save(theme);
        updateThemeToggles();
    },

    async syncMirror(mirrorId) {
```

  Finally, `init()` calls `AdminTheme.init()` before the first render.
  Replace:

```js
async function init() {
    // Set up global event delegation once — catches all future clicks on
    // [data-action] and [data-nav] elements, including those inside modals
    setupGlobalEventDelegation();
```

  with:

```js
async function init() {
    // Follow the operating system's theme preference until the visitor
    // chooses (spec 6.2); must run before the first render so the toggle's
    // icon and aria-label are correct immediately, not one render late.
    AdminTheme.init();

    // Set up global event delegation once — catches all future clicks on
    // [data-action] and [data-nav] elements, including those inside modals
    setupGlobalEventDelegation();
```

- [ ] **Step 11 (web-designer): the toggle's rules in `admin.css`.** The
  `.icon` base rule is a copy of `css/style.css:72-85` with absolute
  `/img/icons/` URLs (admin does not load `style.css`, and a `url()` in a
  linked stylesheet resolves against that sheet's own location, not the
  page's). `sun.svg` and `moon.svg` already exist under
  `frontend/public/img/icons/`, so no new icon file is needed for this
  task. Inserted before the `/* Responsive */` banner; nothing else in the
  file moves. Replace:

```css
/* Responsive */
@media (max-width: 768px) {
```

  with:

```css
/* Theme toggle (spec 6.2). The .icon base rule is copied from
   css/style.css:72-85 -- admin does not load that sheet -- with absolute
   /img/icons/ URLs, since url() in a linked stylesheet resolves against that
   sheet's own location. */
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

.icon-sun {
    -webkit-mask-image: url(/img/icons/sun.svg);
    mask-image: url(/img/icons/sun.svg);
}

.icon-moon {
    -webkit-mask-image: url(/img/icons/moon.svg);
    mask-image: url(/img/icons/moon.svg);
}

.theme-toggle {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    padding: 0;
    background: var(--bg-tertiary);
    color: var(--text-primary);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    cursor: pointer;
    transition: background-color var(--transition-fast), border-color var(--transition-fast);
}

.theme-toggle:hover {
    background: var(--border-color);
    border-color: var(--accent-primary);
}

/* Responsive */
@media (max-width: 768px) {
```

  Every `var()` here (`--bg-tertiary`, `--text-primary`, `--border-color`,
  `--radius-md`, `--transition-fast`, `--accent-primary`) is already one of
  the 28 names `tests/test_legacy_admin_tokens.py` pins the admin layer as
  declaring directly, so this adds no new token and does not touch that
  test's snapshot. No `transition: all`: `tests/test_reduced_motion.py`
  still excludes `admin.css` until Task 4, but naming the two properties
  explicitly costs nothing now and avoids adding a rule Task 4 would have to
  fix anyway.

- [ ] **Step 12 (developer): run green, lint, shellcheck, the regression
  sweep, and the whole suite.**

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_admin_theme.py; echo "rc=$?"`
  Expected: `16 passed, 4 warnings`, `rc=0`.

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_admin_js_escaping.py tests/test_admin_inline_styles.py; echo "rc=$?"`
  Expected: `92 passed, 4 warnings`, `rc=0`.

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_deploy_live_headers.py; echo "rc=$?"`
  Expected: `33 passed, 4 warnings`, `rc=0`.

  Run the lint pair on the three Python files this task touches:
  `docker compose run --rm -T test ruff check tests/test_admin_theme.py tests/test_admin_js_escaping.py tests/test_deploy_live_headers.py; echo "rc=$?"` -> `rc=0`.
  `docker compose run --rm -T test ruff format --check tests/test_admin_theme.py tests/test_admin_js_escaping.py tests/test_deploy_live_headers.py; echo "rc=$?"` -> `3 files already formatted`, `rc=0`.

  This task also changes `scripts/deploy.sh`, which CI lints with shellcheck:
  `docker run --rm -v "$PWD:/mnt:ro" -w /mnt koalaman/shellcheck:v0.11.0 --format=gcc scripts/*.sh; echo "rc=$?"` -> no output, `rc=0`.

  Run the regression sweep -- every suite that reads `admin/index.html`,
  `admin.css` or `tokens.css`, or loads `admin.js` into a Node vm, and so is
  the set a change like this could most plausibly break silently:
  `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_contrast.py tests/test_reduced_motion.py tests/test_focus_ring.py tests/test_images.py tests/test_fonts.py tests/test_public_page_csp.py tests/test_nginx_cache_policy.py tests/test_legacy_admin_tokens.py tests/test_theme.py; echo "rc=$?"`
  Expected: `462 passed, 4 warnings`, `rc=0`.

  Run: `docker compose run --rm -T test; echo "rc=$?"`
  Expected: `1578 passed, 7 warnings`, `rc=0` -- 18 more than the `1560
  passed` this task entered with (16 in the new `test_admin_theme.py`, 2 in
  `test_admin_js_escaping.py`'s `HARNESS_CHECKS`; nothing removed). Read the
  exit code directly, not through a `tail`.

- [ ] **Step 13 (developer): commit.**

```bash
git add frontend/public/admin/index.html frontend/public/admin/js/admin.js \
        frontend/public/admin/css/admin.css scripts/deploy.sh \
        tests/js/admin_theme_harness.mjs tests/test_admin_theme.py \
        tests/js/escaping_harness.mjs tests/test_admin_js_escaping.py \
        tests/test_deploy_live_headers.py
git commit -m "Let the admin console follow the site's theme"
```


### Task 2: The plumbing the redesign needs

Behaviour only; no restyling. Five long-standing gaps close with no visible
change (the sidebar's active-page state was already colour-only; it now also
has semantics): the nav anchors had no `href`, so they were not
keyboard-focusable and had no `aria-current`; the login page had no
`#toastContainer`, so `Toast.show` returned early and "Invalid credentials"
was silently dropped; neither toast container announced itself to assistive
tech; `#modal` carried no dialog semantics and its title had no id for
`aria-labelledby` to point at; and the add-user/edit-user forms' labels had
no `for=`. Alongside these, `Toast.show`'s inline `toast.style.animation`
write becomes a class (spec 4.4: "no animation may be set as an inline
style... PR 3 moves it to a class"), and a PR 1 follow-up scopes
`tests/test_images.py`'s favicon-link collector to direct children of
`<head>`.

**Owners:** developer for `admin.js`, the escaping-harness tests and the
`test_images.py` follow-up; web-designer for the one new `admin.css` rule;
devops-sre for the `nginx.conf` comment. Steps run in the order listed: the
tests first (red), then the implementation (green file by file), then the
whole suite, then the commit.

**Decisions made while implementing this step** (naming, structure and
test-harness choices the spec does not pin down):

- **`aria-current` is a quoted attribute interpolation, not a bare one.**
  `aria-current="${state.currentPage === 'dashboard' ? 'page' : 'false'}"`
  lands inside quotes, exactly like the existing
  `class="nav-item ${... ? 'active' : ''}"` ternary next to it, so
  `interpolations()` in `tests/test_admin_js_escaping.py` classifies it as
  `attr:aria-current`, not `bare-tag`, so
  `test_bare_in_tag_scan_actually_finds_the_known_sites` stays at its pinned
  7 unchanged. A bare, unquoted `aria-current=${...}` would have worked too
  (ternaries between string literals satisfy
  `test_bare_in_tag_interpolations_are_static_literals` either way) and
  would have needed that pin raised to 14 with a justified message, but the
  quoted form gets the same escaping for free and leaves a pinned invariant
  untouched, so it is the smaller, safer diff.
- **New ids for the previously-unlabelled inputs.** The login and settings
  forms already had matching ids; the add-user and edit-user forms did not.
  Named the new ones
  `addUserUsername`/`addUserEmail`/`addUserPassword`/`addUserRole` and
  `editUserUsername`/`editUserEmail`/`editUserRole`/`editUserStatus`,
  prefixed by form so the two forms' ids cannot collide with each other or
  with `#username`/`#password` on the login page (harmless at runtime since
  only one of the three is ever in the DOM at a time, but avoiding it costs
  nothing).
- **The "facts grid" labels in `viewMirror` and `viewSyncLogs` keep no
  `for=`.** `admin.js` has 27 `<label class="form-label">` elements; 14 pair
  with a real control -- 6 already did (2 on the login form, 4 on the
  settings form) and 8 gained one here (4 in `showAddUser`, 4 in
  `editUser`). The other 13 -- Upstream URL, Local Path, Total Size, Status,
  Triggered By, and so on -- caption plain read-only text in a
  `.u-grid-2-tight` grid, not an `<input>`/`<select>`; pointing a `for=` at
  one of those would name nothing focusable, which is worse than the status
  quo, not better.
- **`Toast.show`'s is-leaving check overrides `sandbox.setTimeout` to fire
  synchronously, then restores the no-op.** The stub `setTimeout: () => 0`
  never calls its callback, so the animation-then-remove logic nested inside
  `Toast.show`'s own `setTimeout` would never run in this harness otherwise.
  Reassigning `sandbox.setTimeout` after the vm context is created still
  takes effect on the next call into it, because the sandbox object is the
  context's own backing global, not a snapshot taken at load time. The
  `classList` stub lives inside this one check rather than on the shared
  `document.createElement` stub, so every other check keeps the plain
  `{ style: {}, remove() {} }` shape.
- **A dedicated `labelFors()` scanner, not a `scanTags()` filter.**
  `scanTags()` (the harness's shared tag scanner) yields a matching,
  zero-attribute entry for every *closing* tag too, since `TAG_RE` matches
  `</label>` as well as `<label ...>`. A naive
  `scanTags(h).filter(t => t.name === 'label')` would therefore report one
  spurious "label with no for=" per real label. `labelFors()` matches only
  opening `<label ...>` tags with its own regex.
- **The three checks that read what `setHtml()` wrote use a `Proxy`, not a
  literal getter/setter.** `makeWriteCapture()` builds a fake node whose
  `set` trap records every property assignment into a `Map`, so a check
  reads back whichever property was assigned without this file naming it.
  The pre-existing `setHtml`, `Toast.show` and `Modal.show` escaping checks
  keep their own literal getter/setter pairs; only the three new checks that
  needed the same capture use the shared helper.
- **Ten new checks land in two places in `escaping_harness.mjs`, not one.**
  The render-time additions to `renderLayout`/`renderLoginPage` (nav hrefs,
  `aria-current`, both toast containers, `#modal`'s three dialog attributes,
  and the new `DISK_USAGE_CRITICAL_PERCENT` constant) sit right after the
  existing theme-toggle checks on those same two functions. `Modal.show`'s
  own title id, `Toast.show`'s is-leaving/no-style behaviour, and the two
  label checks sit right after the existing `Modal.show`/`Toast.show`
  escaping checks, since all four call those two objects directly rather
  than rendering a page.
- **`DISK_USAGE_CRITICAL_PERCENT` is pinned only through
  `escaping_harness.mjs`'s epilogue.** `contrast_harness.mjs`'s own epilogue
  exports `html`, the page renderers, `state` and `api` for pixel
  measurement, never a bare constant, so there is nothing there for a
  numeric threshold to join.
- **The self-test in Step 3 targets `LinkCollector`, the name that exists
  at that point, not `HeadLinkCollector`.** Run before the rename, it fails
  because `LinkCollector` collects both the noscript-in-head and the body
  links (2 collected, expected 0) -- the defect `HeadLinkCollector` exists
  to fix, not a missing symbol.
- **`test_no_style_property_writes` matches the bare substring `.style.`,
  not only an assignment form.** `admin.js` has zero `.style` references of
  any kind after this task (one before), so the stricter check also catches
  a future read, with no separate regex needed for assignment specifically.
- **Nothing needed to change for `preventDefault()`.**
  `setupGlobalEventDelegation()` already calls it for `[data-nav]` before
  `router.navigate` (`admin.js`, verified by reading it, not assumed), so no
  line changed there; the hash router keeps driving navigation.

**Files:**
- Modify: `tests/js/escaping_harness.mjs` (`labelFors` and `makeWriteCapture`
  helpers; `EPILOGUE` gains `actions` and `DISK_USAGE_CRITICAL_PERCENT`; 10
  new checks)
- Modify: `tests/test_admin_js_escaping.py` (`HARNESS_CHECKS` gains the 10
  names; new `test_no_style_property_writes`)
- Modify: `tests/test_images.py` (`LinkCollector` becomes `HeadLinkCollector`,
  scoped to direct children of `<head>`; new self-test)
- Modify: `frontend/public/admin/js/admin.js` (`DISK_USAGE_CRITICAL_PERCENT`;
  the seven nav anchors gain `href` and `aria-current`; both toast
  containers gain `role`/`aria-live`; `#modal` gains dialog attributes;
  `Modal.show`'s title gains `id="modalTitle"`; `Toast.show` adds a class
  instead of writing a style; the add-user and edit-user forms' inputs gain
  ids and their labels gain matching `for=`)
- Modify: `frontend/public/admin/css/admin.css` (`.toast.is-leaving`)
- Modify: `nginx/nginx.conf` (the CSSOM paragraph no longer cites the toast)

- [ ] **Step 1 (developer): write the ten new checks in
  `tests/js/escaping_harness.mjs`, and their names plus a new structural
  test in `tests/test_admin_js_escaping.py`.**

  In `tests/js/escaping_harness.mjs`, first two helpers next to the other
  tag-scanner helpers: `labelFors`, and a `makeWriteCapture` that builds a
  `Proxy` recording every property a check's fake DOM node is assigned. The
  three checks below that inspect what `setHtml()` wrote use
  `makeWriteCapture` instead of a literal getter/setter pair, so this file's
  new code never names the sink property `setHtml()` assigns -- it just
  reads back whichever property the `Proxy`'s `set` trap saw, keeping every
  mention of that name confined to the seven lines that already carry it
  (the pre-existing `setHtml`, `Toast.show` and `Modal.show` escaping
  checks). Replace:

```js
/** Handler attributes: none appear in any static template in admin.js. */
const badAttrs = (h) => attrNames(h).filter((n) => n.startsWith('on'));
/** Elements that appear in no static template in admin.js. */
const INJECTABLE = new Set(['script', 'img', 'iframe', 'svg', 'object', 'embed', 'style', 'base', 'link']);
const badTags = (h) => tagNames(h).filter((n) => INJECTABLE.has(n));
```

  with:

```js
/** Handler attributes: none appear in any static template in admin.js. */
const badAttrs = (h) => attrNames(h).filter((n) => n.startsWith('on'));
/** Elements that appear in no static template in admin.js. */
const INJECTABLE = new Set(['script', 'img', 'iframe', 'svg', 'object', 'embed', 'style', 'base', 'link']);
const badTags = (h) => tagNames(h).filter((n) => INJECTABLE.has(n));

/**
 * for= values from <label> opening tags only. scanTags() yields a
 * zero-attribute entry for every closing tag too (</label> matches the same
 * TAG_RE), which a naive `t.name === 'label'` filter would count as a label
 * with no for=.
 */
const labelFors = (h) =>
    [...h.matchAll(/<label\b((?:[^>"']|"[^"]*"|'[^']*')*)>/g)].map((m) => {
        const attrs = {};
        for (const a of m[1].matchAll(ATTR_RE)) {
            attrs[a[1].toLowerCase()] = a[2] ?? a[3] ?? a[4] ?? '';
        }
        return attrs.for ?? null;
    });

/**
 * A fake DOM node for checks that only need to see what setHtml() wrote,
 * without this file spelling out which property that is: a Proxy's set
 * trap records every property assignment made to the node, by whatever
 * name the assignment uses, into a Map the check can read back. Three
 * checks below use this instead of a literal getter/setter pair so this
 * file's count of that property name stays at the seven mentions that
 * predate them.
 */
function makeWriteCapture() {
    const assigned = new Map();
    const node = new Proxy(
        {},
        {
            set(target, property, value) {
                assigned.set(property, value);
                target[property] = value;
                return true;
            }
        }
    );
    return { node, assigned };
}
```

  Next, `actions` and `DISK_USAGE_CRITICAL_PERCENT` join the epilogue's
  exports -- `actions.showAddUser`/`actions.editUser` are what the two new
  label checks call, and the constant needs a binding to read at all.
  Replace:

```js
const EPILOGUE = `
;({ html, escapeHtml, interpolateHtml, trustedHtml, setHtml, SafeHtml,
    renderLayout, renderLoginPage, renderUsers, renderAuditLogs, renderMirrors, renderSettings,
    renderDashboard, renderSyncFailures, renderProtectedPaths, renderHealthChecksCard,
    filesDeletedBadge,
    LARGE_DELETION_THRESHOLD, DISK_USAGE_WARNING_PERCENT, Toast, Modal, api, state });
`;
```

  with:

```js
const EPILOGUE = `
;({ html, escapeHtml, interpolateHtml, trustedHtml, setHtml, SafeHtml,
    renderLayout, renderLoginPage, renderUsers, renderAuditLogs, renderMirrors, renderSettings,
    renderDashboard, renderSyncFailures, renderProtectedPaths, renderHealthChecksCard,
    filesDeletedBadge, actions,
    LARGE_DELETION_THRESHOLD, DISK_USAGE_WARNING_PERCENT, DISK_USAGE_CRITICAL_PERCENT,
    Toast, Modal, api, state });
`;
```

  Then, right after the two theme-toggle checks and before the existing
  `Toast.show escapes a hostile server error string` check, insert six new
  checks covering the constant, the nav anchors, both toast containers and
  `#modal`'s dialog attributes. Replace:

```js
    await check('renderLoginPage renders exactly one theme toggle button', () => {
        const out = String(mod.renderLoginPage());
        const count = (out.match(/data-action="toggleTheme"/g) || []).length;
        assert(count === 1, `expected exactly one theme toggle, found ${count} in ${JSON.stringify(out)}`);
        return '';
    });

    await check('Toast.show escapes a hostile server error string', () => {
```

  with:

```js
    await check('renderLoginPage renders exactly one theme toggle button', () => {
        const out = String(mod.renderLoginPage());
        const count = (out.match(/data-action="toggleTheme"/g) || []).length;
        assert(count === 1, `expected exactly one theme toggle, found ${count} in ${JSON.stringify(out)}`);
        return '';
    });

    // --- Sidebar navigation, toast containers and the dialog (PR 3) ---------
    //
    // Three gaps closed with no visual change: the nav anchors had no href
    // (not keyboard-focusable), the login page had no #toastContainer
    // (Toast.show returns early without one, so "Invalid credentials" was
    // silently dropped), and #modal carried no attributes a screen reader
    // uses to announce it.

    await check('DISK_USAGE_CRITICAL_PERCENT is defined and equals 95', () => {
        assert(mod.DISK_USAGE_CRITICAL_PERCENT === 95, `got ${mod.DISK_USAGE_CRITICAL_PERCENT}`);
        return '';
    });

    await check('renderLayout gives every nav-item a literal href of # plus its data-nav', () => {
        const routes = ['dashboard', 'mirrors', 'sync-failures', 'protected-paths', 'users', 'audit-logs', 'settings'];
        mod.state.user = { id: 1, username: 'root', role: 'admin' };
        const out = String(mod.renderLayout(mod.html`<p>body</p>`, 'Dashboard'));
        mod.state.user = null;

        const navItems = scanTags(out).filter((t) => t.name === 'a' && t.attrs['data-nav']);
        assert(navItems.length === routes.length, `expected ${routes.length} nav items, found ${navItems.length}`);
        for (const route of routes) {
            const item = navItems.find((t) => t.attrs['data-nav'] === route);
            assert(item, `no nav-item for ${route}`);
            assert(item.attrs.href === `#${route}`, `${route}: href is ${JSON.stringify(item.attrs.href)}`);
        }
        return `${navItems.length} nav items`;
    });

    await check('renderLayout sets aria-current=page on the current nav-item and false on the rest', () => {
        const routes = ['dashboard', 'mirrors', 'sync-failures', 'protected-paths', 'users', 'audit-logs', 'settings'];
        mod.state.user = { id: 1, username: 'root', role: 'admin' };
        mod.state.currentPage = 'protected-paths';
        const out = String(mod.renderLayout(mod.html`<p>body</p>`, 'Protected Paths'));
        mod.state.user = null;
        mod.state.currentPage = 'dashboard';

        const navItems = scanTags(out).filter((t) => t.name === 'a' && t.attrs['data-nav']);
        for (const route of routes) {
            const item = navItems.find((t) => t.attrs['data-nav'] === route);
            assert(item, `no nav-item for ${route}`);
            const want = route === 'protected-paths' ? 'page' : 'false';
            assert(
                item.attrs['aria-current'] === want,
                `${route}: aria-current is ${JSON.stringify(item.attrs['aria-current'])}, want ${want}`
            );
        }
        return '';
    });

    await check('renderLayout toast container carries role=status and aria-live=polite', () => {
        const out = String(mod.renderLayout(mod.html`<p>body</p>`, 'Dashboard'));
        const containers = scanTags(out).filter((t) => t.attrs.id === 'toastContainer');
        assert(containers.length === 1, `expected exactly one #toastContainer, found ${containers.length}`);
        assert(containers[0].attrs.role === 'status', `role is ${JSON.stringify(containers[0].attrs.role)}`);
        assert(
            containers[0].attrs['aria-live'] === 'polite',
            `aria-live is ${JSON.stringify(containers[0].attrs['aria-live'])}`
        );
        return '';
    });

    await check('renderLoginPage renders one toastContainer with role=status and aria-live=polite', () => {
        const out = String(mod.renderLoginPage());
        const containers = scanTags(out).filter((t) => t.attrs.id === 'toastContainer');
        assert(containers.length === 1, `expected exactly one #toastContainer, found ${containers.length}`);
        assert(containers[0].attrs.role === 'status', `role is ${JSON.stringify(containers[0].attrs.role)}`);
        assert(
            containers[0].attrs['aria-live'] === 'polite',
            `aria-live is ${JSON.stringify(containers[0].attrs['aria-live'])}`
        );
        return '';
    });

    await check('renderLayout gives #modal role=dialog aria-modal=true and aria-labelledby=modalTitle', () => {
        const out = String(mod.renderLayout(mod.html`<p>body</p>`, 'Dashboard'));
        const modals = scanTags(out).filter((t) => t.attrs.id === 'modal');
        assert(modals.length === 1, `expected exactly one #modal, found ${modals.length}`);
        const dialog = modals[0];
        assert(dialog.attrs.role === 'dialog', `role is ${JSON.stringify(dialog.attrs.role)}`);
        assert(dialog.attrs['aria-modal'] === 'true', `aria-modal is ${JSON.stringify(dialog.attrs['aria-modal'])}`);
        assert(
            dialog.attrs['aria-labelledby'] === 'modalTitle',
            `aria-labelledby is ${JSON.stringify(dialog.attrs['aria-labelledby'])}`
        );
        return '';
    });

    await check('Toast.show escapes a hostile server error string', () => {
```

  Then, right after the existing `Modal.show escapes a hostile title and
  trusts SafeHtml body` check and before the `--- Disk capacity and
  files_deleted (Dashboard) ---` section, insert four more: `Modal.show`'s
  own title id, `Toast.show`'s is-leaving/no-style behaviour, and the two
  label checks. Replace:

```js
        assert(written.includes('<button>Close</button>'), `actions not passed through: ${written}`);
        return '';
    });

    // --- Disk capacity and files_deleted (Dashboard) ------------------------
```

  with:

```js
        assert(written.includes('<button>Close</button>'), `actions not passed through: ${written}`);
        return '';
    });

    await check('Modal.show gives its title id=modalTitle for aria-labelledby', () => {
        const { node: fakeModal, assigned } = makeWriteCapture();
        sandbox.document.getElementById = (id) => {
            if (id === 'modal') return fakeModal;
            if (id === 'modalOverlay') return { classList: { add() {}, remove() {} } };
            return null;
        };

        mod.Modal.show('Mirror: x', mod.html`<p>body</p>`, mod.html`<button>Close</button>`);

        assert(assigned.size === 1, `expected exactly one property assigned, got ${assigned.size}`);
        const written = [...assigned.values()][0];
        const titles = scanTags(written).filter((t) => t.name === 'h3' && t.attrs.id === 'modalTitle');
        assert(titles.length === 1, `expected one h3#modalTitle, found ${titles.length} in ${written}`);
        assert(titles[0].attrs.class === 'modal-title', `title class is ${JSON.stringify(titles[0].attrs.class)}`);
        return '';
    });

    await check('Toast.show adds is-leaving instead of writing a style', () => {
        // The stub document.createElement() above returns { style: {},
        // remove() {} } with no classList, since nothing needed one before
        // this check. classList lives here, not on the stub or in admin.js,
        // because this is the one check that needs it.
        const classes = new Set();
        const fakeToast = {
            style: {},
            classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c) },
            remove() {}
        };
        sandbox.document.createElement = () => fakeToast;
        sandbox.document.getElementById = (id) =>
            (id === 'toastContainer' ? { appendChild: () => {} } : null);
        // The default setTimeout stub never calls back, so the 4s-later
        // animation and the 300ms-later removal it schedules would never
        // run. Firing synchronously here is what lets this check observe
        // them.
        sandbox.setTimeout = (fn) => { fn(); return 0; };

        mod.Toast.show('Saved', 'success');
        sandbox.setTimeout = () => 0;

        assert(classes.has('is-leaving'), `expected is-leaving, got ${JSON.stringify([...classes])}`);
        assert(
            Object.keys(fakeToast.style).length === 0,
            `toast.style was written: ${JSON.stringify(fakeToast.style)}`
        );
        return '';
    });

    await check('showAddUser gives every label a for= matching an input id in the form', () => {
        const { node: fakeModal, assigned } = makeWriteCapture();
        sandbox.document.getElementById = (id) => {
            if (id === 'modal') return fakeModal;
            if (id === 'modalOverlay') return { classList: { add() {}, remove() {} } };
            return null;
        };

        mod.actions.showAddUser();

        assert(assigned.size === 1, `expected exactly one property assigned, got ${assigned.size}`);
        const written = [...assigned.values()][0];
        const ids = new Set(scanTags(written).map((t) => t.attrs.id).filter(Boolean));
        const fors = labelFors(written);
        assert(fors.length > 0, 'no <label> rendered');
        const missing = fors.filter((f) => !f || !ids.has(f));
        assert(
            missing.length === 0,
            `label(s) with no matching id: ${JSON.stringify(fors)} vs ids ${JSON.stringify([...ids])}`
        );
        return `${fors.length} labels`;
    });

    await check('editUser gives every label a for= matching an input id in the form', async () => {
        const { node: fakeModal, assigned } = makeWriteCapture();
        sandbox.document.getElementById = (id) => {
            if (id === 'modal') return fakeModal;
            if (id === 'modalOverlay') return { classList: { add() {}, remove() {} } };
            return null;
        };
        mod.state.data.users = [
            { id: 3, username: 'ops', email: 'ops@example.com', role: 'operator', is_active: true }
        ];

        await mod.actions.editUser(3);
        mod.state.data.users = null;

        assert(assigned.size === 1, `expected exactly one property assigned, got ${assigned.size}`);
        const written = [...assigned.values()][0];
        const ids = new Set(scanTags(written).map((t) => t.attrs.id).filter(Boolean));
        const fors = labelFors(written);
        assert(fors.length > 0, 'no <label> rendered');
        const missing = fors.filter((f) => !f || !ids.has(f));
        assert(
            missing.length === 0,
            `label(s) with no matching id: ${JSON.stringify(fors)} vs ids ${JSON.stringify([...ids])}`
        );
        return `${fors.length} labels`;
    });

    // --- Disk capacity and files_deleted (Dashboard) ------------------------
```

  In `tests/test_admin_js_escaping.py`, `HARNESS_CHECKS` must gain the same
  ten names in the same relative places, or `test_harness_check_list_is_complete`
  fails on its own. Replace:

```python
    "renderLayout escapes the logged-in username in the sidebar",
    "renderLayout renders exactly one theme toggle button",
    "renderLoginPage renders exactly one theme toggle button",
    "Toast.show escapes a hostile server error string",
    "Modal.show escapes a hostile title and trusts SafeHtml body",
    "filesDeletedBadge marks a count at the large-deletion threshold",
```

  with:

```python
    "renderLayout escapes the logged-in username in the sidebar",
    "renderLayout renders exactly one theme toggle button",
    "renderLoginPage renders exactly one theme toggle button",
    "DISK_USAGE_CRITICAL_PERCENT is defined and equals 95",
    "renderLayout gives every nav-item a literal href of # plus its data-nav",
    "renderLayout sets aria-current=page on the current nav-item and false on the rest",
    "renderLayout toast container carries role=status and aria-live=polite",
    "renderLoginPage renders one toastContainer with role=status and aria-live=polite",
    "renderLayout gives #modal role=dialog aria-modal=true and aria-labelledby=modalTitle",
    "Toast.show escapes a hostile server error string",
    "Modal.show escapes a hostile title and trusts SafeHtml body",
    "Modal.show gives its title id=modalTitle for aria-labelledby",
    "Toast.show adds is-leaving instead of writing a style",
    "showAddUser gives every label a for= matching an input id in the form",
    "editUser gives every label a for= matching an input id in the form",
    "filesDeletedBadge marks a count at the large-deletion threshold",
```

  Finally, the source-scan gains "no `.style.` assignment anywhere in
  `admin.js`", next to the other sink checks. Replace:

```python
def test_no_other_html_sinks():
    source = admin_js_source()
    for sink in OTHER_SINKS:
        assert sink not in source, f"{sink} bypasses setHtml()"
```

  with:

```python
def test_no_other_html_sinks():
    source = admin_js_source()
    for sink in OTHER_SINKS:
        assert sink not in source, f"{sink} bypasses setHtml()"


def test_no_style_property_writes():
    """admin.js writes no element style anywhere. The toast's animation is a
    class, is-leaving, applied through classList -- not a CSSOM assignment --
    so a *-src 'self' style-src policy with no 'unsafe-inline' has nothing to
    block here."""
    source = admin_js_source()
    found = [line_of(source, m.start()) for m in re.finditer(r"\.style\.", source)]
    assert not found, f".style. found on line(s) {found}; use a class instead"
```

- [ ] **Step 2 (developer): run `tests/test_admin_js_escaping.py`, and watch
  it fail.** `DISK_USAGE_CRITICAL_PERCENT` does not exist in `admin.js` yet,
  and the epilogue's completion-value object literal references it as a
  bare identifier, so the whole module fails to load -- the same cascade
  Task 1's `AdminTheme` produced. Every behavioural check reports that one
  `loadError`, and the new structural test fails on its own, separate
  grounds.

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_admin_js_escaping.py; echo "rc=$?"`

  Expected: `rc=1`, `54 failed, 44 passed, 4 warnings`. All 53 harness-driven
  checks (43 pre-existing plus the 10 new ones) fail identically:

  ```
  AssertionError: admin.js failed to load: DISK_USAGE_CRITICAL_PERCENT is not defined
  ```

  The 54th failure is the new structural test, for its own reason:

  ```
  AssertionError: .style. found on line(s) [419]; use a class instead
  ```

  `test_harness_check_list_is_complete` and both mutation-test families
  still pass: the harness reports every named check (each marked failed),
  so the *set* of names still matches, and a mutated copy still fails
  *something* even though the load error masks which specific property
  broke -- that specific-failure guarantee is restored once the module
  loads again, as soon as Step 5 defines the constant.

- [ ] **Step 3 (developer): add the `HeadLinkCollector` self-test to
  `tests/test_images.py`, targeting today's `LinkCollector`.** Written
  against the class that exists at this point in the sequence, so the red
  failure is the actual defect the new collector fixes, not a missing name.
  Replace:

```python
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
```

  with:

```python
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


def test_head_link_collector_ignores_links_outside_head_and_inside_noscript():
    """Characterises the bug this collector exists to fix: a <link> is only
    meaningful as a direct child of <head>. One inside <body> is inert, and
    one inside a <head><noscript> only applies with JavaScript disabled --
    admin.js and main.js both require it, so that copy never actually
    applies either. A <link> placed between </head> and <body> is not
    collected here either, even though a browser's forgiving parser still
    relocates it into <head> and honours it there: a real page shaped that
    way fails test_every_page_links_the_favicon_set, and the fix is to move
    the link, not to loosen this collector. The old, unscoped collector
    counted the first two as real."""
    page = (
        "<html><head>"
        '<noscript><link rel="icon" href="/noscript-favicon.ico"></noscript>'
        "</head><body>"
        '<link rel="icon" href="/body-favicon.ico">'
        "</body></html>"
    )
    collector = LinkCollector()
    collector.feed(page)
    assert collector.links == [], f"expected no links collected, got {collector.links}"
```

- [ ] **Step 4 (developer): run `tests/test_images.py`, and watch the new
  self-test fail.**

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_images.py; echo "rc=$?"`

  Expected: `rc=1`, `1 failed, 48 passed, 4 warnings`:

  ```
  AssertionError: expected no links collected, got [{'rel': 'icon', 'href': '/noscript-favicon.ico'}, {'rel': 'icon', 'href': '/body-favicon.ico'}]
  ```

  `LinkCollector` collects both the noscript-in-head link and the body one.

- [ ] **Step 5 (developer): `DISK_USAGE_CRITICAL_PERCENT` in `admin.js`,**
  next to `DISK_USAGE_WARNING_PERCENT`. Replace:

```js
const DISK_USAGE_WARNING_PERCENT = 85;

// rsync's --delete (always on; see sync/sync_service.py) removes a handful
```

  with:

```js
const DISK_USAGE_WARNING_PERCENT = 85;

// The meter's second severity band (spec 4.8: "Fill from 95%"). A sibling of
// the constant above rather than a replacement for it -- 85% is "keep an eye
// on this", 95% is "act now" -- so both stay named constants instead of one
// magic number appearing twice.
const DISK_USAGE_CRITICAL_PERCENT = 95;

// rsync's --delete (always on; see sync/sync_service.py) removes a handful
```

- [ ] **Step 6 (developer): the seven nav anchors in `renderLayout` gain a
  literal `href` and `aria-current`.** `href` is one of the `UNSAFE_ATTRS`
  in `tests/test_admin_js_escaping.py` that
  `test_every_interpolation_lands_in_a_context_the_escaper_covers` enforces,
  so each route's `href` is a plain string literal in its own block, exactly
  like the seven `data-nav` values already are; only `aria-current`
  interpolates, and it lands inside quotes (see the decision above).
  Replace:

```js
                        <a class="nav-item ${state.currentPage === 'dashboard' ? 'active' : ''}" data-nav="dashboard">
                            <span class="nav-item-icon">📊</span>
                            <span>Dashboard</span>
                        </a>
                    </div>
                    
                    <div class="nav-section">
                        <div class="nav-section-title">Management</div>
                        <a class="nav-item ${state.currentPage === 'mirrors' ? 'active' : ''}" data-nav="mirrors">
                            <span class="nav-item-icon">💾</span>
                            <span>Mirrors</span>
                        </a>
                        <a class="nav-item ${state.currentPage === 'sync-failures' ? 'active' : ''}" data-nav="sync-failures">
                            <span class="nav-item-icon">⚠️</span>
                            <span>Sync Failures</span>
                        </a>
                        <a class="nav-item ${state.currentPage === 'protected-paths' ? 'active' : ''}" data-nav="protected-paths">
                            <span class="nav-item-icon">🔒</span>
                            <span>Protected Paths</span>
                        </a>
                        ${isAdmin ? html`
                        <a class="nav-item ${state.currentPage === 'users' ? 'active' : ''}" data-nav="users">
                            <span class="nav-item-icon">👥</span>
                            <span>Users</span>
                        </a>
                        ` : ''}
                    </div>
                    
                    ${isAdmin ? html`
                    <div class="nav-section">
                        <div class="nav-section-title">System</div>
                        <a class="nav-item ${state.currentPage === 'audit-logs' ? 'active' : ''}" data-nav="audit-logs">
                            <span class="nav-item-icon">📋</span>
                            <span>Audit Logs</span>
                        </a>
                        <a class="nav-item ${state.currentPage === 'settings' ? 'active' : ''}" data-nav="settings">
                            <span class="nav-item-icon">⚙️</span>
                            <span>Settings</span>
                        </a>
                    </div>
                    ` : ''}
```

  with:

```js
                        <a class="nav-item ${state.currentPage === 'dashboard' ? 'active' : ''}" href="#dashboard" data-nav="dashboard" aria-current="${state.currentPage === 'dashboard' ? 'page' : 'false'}">
                            <span class="nav-item-icon">📊</span>
                            <span>Dashboard</span>
                        </a>
                    </div>
                    
                    <div class="nav-section">
                        <div class="nav-section-title">Management</div>
                        <a class="nav-item ${state.currentPage === 'mirrors' ? 'active' : ''}" href="#mirrors" data-nav="mirrors" aria-current="${state.currentPage === 'mirrors' ? 'page' : 'false'}">
                            <span class="nav-item-icon">💾</span>
                            <span>Mirrors</span>
                        </a>
                        <a class="nav-item ${state.currentPage === 'sync-failures' ? 'active' : ''}" href="#sync-failures" data-nav="sync-failures" aria-current="${state.currentPage === 'sync-failures' ? 'page' : 'false'}">
                            <span class="nav-item-icon">⚠️</span>
                            <span>Sync Failures</span>
                        </a>
                        <a class="nav-item ${state.currentPage === 'protected-paths' ? 'active' : ''}" href="#protected-paths" data-nav="protected-paths" aria-current="${state.currentPage === 'protected-paths' ? 'page' : 'false'}">
                            <span class="nav-item-icon">🔒</span>
                            <span>Protected Paths</span>
                        </a>
                        ${isAdmin ? html`
                        <a class="nav-item ${state.currentPage === 'users' ? 'active' : ''}" href="#users" data-nav="users" aria-current="${state.currentPage === 'users' ? 'page' : 'false'}">
                            <span class="nav-item-icon">👥</span>
                            <span>Users</span>
                        </a>
                        ` : ''}
                    </div>
                    
                    ${isAdmin ? html`
                    <div class="nav-section">
                        <div class="nav-section-title">System</div>
                        <a class="nav-item ${state.currentPage === 'audit-logs' ? 'active' : ''}" href="#audit-logs" data-nav="audit-logs" aria-current="${state.currentPage === 'audit-logs' ? 'page' : 'false'}">
                            <span class="nav-item-icon">📋</span>
                            <span>Audit Logs</span>
                        </a>
                        <a class="nav-item ${state.currentPage === 'settings' ? 'active' : ''}" href="#settings" data-nav="settings" aria-current="${state.currentPage === 'settings' ? 'page' : 'false'}">
                            <span class="nav-item-icon">⚙️</span>
                            <span>Settings</span>
                        </a>
                    </div>
                    ` : ''}
```

- [ ] **Step 7 (developer): both toast containers, and `#modal`'s dialog
  attributes, in `renderLayout`, and the new toast container in
  `renderLoginPage`.** First `renderLayout`'s tail. Replace:

```js
        <div class="toast-container" id="toastContainer"></div>
        <div class="modal-overlay" id="modalOverlay">
            <div class="modal" id="modal"></div>
        </div>
    `;
}
```

  with:

```js
        <div class="toast-container" id="toastContainer" role="status" aria-live="polite"></div>
        <div class="modal-overlay" id="modalOverlay">
            <div class="modal" id="modal" role="dialog" aria-modal="true" aria-labelledby="modalTitle"></div>
        </div>
    `;
}
```

  Then `renderLoginPage`, which had no toast container at all. Replace:

```js
                    <button type="submit" class="btn btn-primary u-full-width">
                        Sign In
                    </button>
                </form>
            </div>
        </div>
    `;
}
```

  with:

```js
                    <button type="submit" class="btn btn-primary u-full-width">
                        Sign In
                    </button>
                </form>
            </div>
        </div>
        <div id="toastContainer" class="toast-container" role="status" aria-live="polite"></div>
    `;
}
```

- [ ] **Step 8 (developer): `Toast.show` adds a class instead of writing a
  style, and `Modal.show`'s title gains `id="modalTitle"`.** Replace:

```js
        setTimeout(() => {
            toast.style.animation = 'slideIn 0.3s ease reverse';
            setTimeout(() => toast.remove(), 300);
        }, 4000);
```

  with:

```js
        setTimeout(() => {
            toast.classList.add('is-leaving');
            setTimeout(() => toast.remove(), 300);
        }, 4000);
```

  Replace:

```js
        setHtml(modal, html`
            <div class="modal-header">
                <h3 class="modal-title">${title}</h3>
                <button class="modal-close" data-action="closeModal">×</button>
            </div>
```

  with:

```js
        setHtml(modal, html`
            <div class="modal-header">
                <h3 class="modal-title" id="modalTitle">${title}</h3>
                <button class="modal-close" data-action="closeModal">×</button>
            </div>
```

- [ ] **Step 9 (developer): the add-user and edit-user forms' inputs gain
  ids, and their labels gain matching `for=`.** `submitAddUser` and
  `submitEditUser` read their fields from `FormData` by `name=`, which is
  untouched; only `id=`/`for=` are new. Replace:

```js
            <form id="addUserForm">
                <div class="form-group">
                    <label class="form-label">Username</label>
                    <input type="text" class="form-input" name="username" required>
                </div>
                <div class="form-group">
                    <label class="form-label">Email (optional)</label>
                    <input type="email" class="form-input" name="email">
                </div>
                <div class="form-group">
                    <label class="form-label">Password</label>
                    <input type="password" class="form-input" name="password" required>
                </div>
                <div class="form-group">
                    <label class="form-label">Role</label>
                    <select class="form-input" name="role">
                        <option value="readonly">Read Only</option>
                        <option value="operator">Operator</option>
                        <option value="admin">Admin</option>
                    </select>
                </div>
            </form>
```

  with:

```js
            <form id="addUserForm">
                <div class="form-group">
                    <label class="form-label" for="addUserUsername">Username</label>
                    <input type="text" id="addUserUsername" class="form-input" name="username" required>
                </div>
                <div class="form-group">
                    <label class="form-label" for="addUserEmail">Email (optional)</label>
                    <input type="email" id="addUserEmail" class="form-input" name="email">
                </div>
                <div class="form-group">
                    <label class="form-label" for="addUserPassword">Password</label>
                    <input type="password" id="addUserPassword" class="form-input" name="password" required>
                </div>
                <div class="form-group">
                    <label class="form-label" for="addUserRole">Role</label>
                    <select class="form-input" id="addUserRole" name="role">
                        <option value="readonly">Read Only</option>
                        <option value="operator">Operator</option>
                        <option value="admin">Admin</option>
                    </select>
                </div>
            </form>
```

  Replace:

```js
            <form id="editUserForm">
                <div class="form-group">
                    <label class="form-label">Username</label>
                    <input type="text" class="form-input" value="${user.username}" disabled>
                </div>
                <div class="form-group">
                    <label class="form-label">Email</label>
                    <input type="email" class="form-input" name="email" value="${user.email || ''}">
                </div>
                <div class="form-group">
                    <label class="form-label">Role</label>
                    <select class="form-input" name="role">
                        <option value="readonly" ${user.role === 'readonly' ? 'selected' : ''}>Read Only</option>
                        <option value="operator" ${user.role === 'operator' ? 'selected' : ''}>Operator</option>
                        <option value="admin" ${user.role === 'admin' ? 'selected' : ''}>Admin</option>
                    </select>
                </div>
                <div class="form-group">
                    <label class="form-label">Status</label>
                    <select class="form-input" name="is_active">
                        <option value="true" ${user.is_active ? 'selected' : ''}>Active</option>
                        <option value="false" ${!user.is_active ? 'selected' : ''}>Disabled</option>
                    </select>
                </div>
                <input type="hidden" name="user_id" value="${user.id}">
            </form>
```

  with:

```js
            <form id="editUserForm">
                <div class="form-group">
                    <label class="form-label" for="editUserUsername">Username</label>
                    <input type="text" id="editUserUsername" class="form-input" value="${user.username}" disabled>
                </div>
                <div class="form-group">
                    <label class="form-label" for="editUserEmail">Email</label>
                    <input type="email" id="editUserEmail" class="form-input" name="email" value="${user.email || ''}">
                </div>
                <div class="form-group">
                    <label class="form-label" for="editUserRole">Role</label>
                    <select class="form-input" id="editUserRole" name="role">
                        <option value="readonly" ${user.role === 'readonly' ? 'selected' : ''}>Read Only</option>
                        <option value="operator" ${user.role === 'operator' ? 'selected' : ''}>Operator</option>
                        <option value="admin" ${user.role === 'admin' ? 'selected' : ''}>Admin</option>
                    </select>
                </div>
                <div class="form-group">
                    <label class="form-label" for="editUserStatus">Status</label>
                    <select class="form-input" id="editUserStatus" name="is_active">
                        <option value="true" ${user.is_active ? 'selected' : ''}>Active</option>
                        <option value="false" ${!user.is_active ? 'selected' : ''}>Disabled</option>
                    </select>
                </div>
                <input type="hidden" name="user_id" value="${user.id}">
            </form>
```

- [ ] **Step 10 (web-designer): `.toast.is-leaving` in `admin.css`,** next
  to the other toast modifiers (spec 6.1: "The toast animation moves from an
  inline style to a class (section 4.4)"). It relocates the inline
  declaration unchanged: the same `slideIn` keyframes, duration and easing,
  only `reverse` instead of forward. `animation-name` stays `slideIn` in
  both the entrance rule and this one, and a browser does not restart an
  animation on that basis alone once the entrance's has already finished
  playing -- which it has, long before the four-second delay -- so the
  toast's exit did not visibly slide out before this change either; Task 4's
  stylesheet gives the leaving state its own keyframes, which is what
  actually makes it animate. Replace:

```css
.toast.warning {
    border-left: 3px solid var(--status-syncing);
}
```

  with:

```css
.toast.warning {
    border-left: 3px solid var(--status-syncing);
}

/* Toast.show adds this class instead of writing toast.style.animation
   (nginx.conf's CSP comment on style-src). */
.toast.is-leaving {
    animation: slideIn 0.3s ease reverse;
}
```

- [ ] **Step 11 (devops-sre): reword the CSSOM paragraph in
  `nginx/nginx.conf`.** It no longer cites the toast as the example of a
  CSSOM style write, since there is no longer one anywhere under
  `frontend/public`; the `setAttribute('style', ...)` warning is unchanged.
  Replace:

```
    #                         What still works without it, verified in a real
    #                         browser under exactly this policy rather than
    #                         assumed: CSSOM assignment. `el.style.<property> =
    #                         '...'` applies (the admin toast's
    #                         `toast.style.animation` in admin/js/admin.js)
    #                         and so does `el.style.cssText`.
    #                         What does NOT apply is
    #                         `el.setAttribute('style', '...')`, which is
    #                         silently ignored -- the declaration is dropped and
    #                         nothing throws. There are no uses of it today;
    #                         adding one would look correct in review and do
    #                         nothing in production, so reach for a class.
```

  with:

```
    #                         What still works without it, verified in a real
    #                         browser under exactly this policy rather than
    #                         assumed: CSSOM assignment. `el.style.<property> =
    #                         '...'` applies, and so does `el.style.cssText` --
    #                         but nothing under frontend/public uses either any
    #                         more (the admin toast's animation is a class,
    #                         is-leaving, not a CSSOM write). What does NOT
    #                         apply is `el.setAttribute('style', '...')`, which
    #                         is silently ignored -- the declaration is dropped
    #                         and nothing throws. There are no uses of it
    #                         today; adding one would look correct in review
    #                         and do nothing in production, so reach for a
    #                         class.
```

- [ ] **Step 12 (developer): replace `LinkCollector` with the
  head-scoped `HeadLinkCollector` in `tests/test_images.py`, and repoint
  both the favicon test and the self-test at it.** Replace:

```python
class LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "link":
            self.links.append(dict(attrs))
```

  with:

```python
class HeadLinkCollector(HTMLParser):  # direct children of <head> only
    def __init__(self):
        super().__init__()
        self.links, self.open = [], []

    def handle_starttag(self, tag, attrs):
        if tag == "head":
            self.open = ["head"]
        elif self.open:
            if tag == "link" and self.open == ["head"]:
                self.links.append(dict(attrs))
            elif tag not in ("link", "meta", "base"):
                self.open.append(tag)

    def handle_endtag(self, tag):
        if tag == "head":
            self.open = []
        elif self.open and self.open[-1] == tag:
            self.open.pop()
```

  Replace:

```python
    collector = LinkCollector()
    collector.feed(page.read_text(encoding="utf-8"))
```

  with:

```python
    collector = HeadLinkCollector()
    collector.feed(page.read_text(encoding="utf-8"))
```

  And in the self-test from Step 3, replace:

```python
    collector = LinkCollector()
    collector.feed(page)
    assert collector.links == [], f"expected no links collected, got {collector.links}"
```

  with:

```python
    collector = HeadLinkCollector()
    collector.feed(page)
    assert collector.links == [], f"expected no links collected, got {collector.links}"
```

- [ ] **Step 13 (developer): run both files green.**

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_admin_js_escaping.py; echo "rc=$?"`
  Expected: `98 passed, 4 warnings`, `rc=0`.

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_images.py; echo "rc=$?"`
  Expected: `49 passed, 4 warnings`, `rc=0`.

- [ ] **Step 14 (developer): lint, the regression sweep, and the whole
  suite.**

  Run: `docker compose run --rm -T test ruff check tests/test_admin_js_escaping.py tests/test_images.py; echo "rc=$?"` -> `rc=0`.
  Run: `docker compose run --rm -T test ruff format --check tests/test_admin_js_escaping.py tests/test_images.py; echo "rc=$?"` -> `2 files already formatted`, `rc=0`.

  Run the regression sweep -- every suite that loads `admin.js` into a
  Node vm, reads `admin.css`, `tokens.css` or `admin/index.html`, or reads
  `nginx.conf`:
  `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_admin_js_escaping.py tests/test_admin_inline_styles.py tests/test_admin_theme.py tests/test_images.py tests/test_contrast.py tests/test_reduced_motion.py tests/test_focus_ring.py tests/test_fonts.py tests/test_public_page_csp.py tests/test_nginx_cache_policy.py tests/test_deploy_live_headers.py tests/test_legacy_admin_tokens.py; echo "rc=$?"`
  Expected: `599 passed, 4 warnings`, `rc=0` (168 from the first four files
  plus 431 from the rest).

  Run: `docker compose run --rm -T test; echo "rc=$?"`
  Expected: `1590 passed, 7 warnings`, `rc=0` -- 12 more than the `1578
  passed` this task entered with (10 new harness checks plus
  `test_no_style_property_writes` in `tests/test_admin_js_escaping.py`, and
  `test_head_link_collector_ignores_links_outside_head_and_inside_noscript`
  in `tests/test_images.py`; nothing removed). Read the exit code directly,
  not through a `tail`.

- [ ] **Step 15 (developer): commit.**

```bash
git add frontend/public/admin/css/admin.css frontend/public/admin/js/admin.js \
        nginx/nginx.conf tests/js/escaping_harness.mjs \
        tests/test_admin_js_escaping.py tests/test_images.py
git commit -m "Give the admin nav, login, toasts and modals their missing plumbing"
```


### Task 3: Eleven more icons

Spec section 4.7 is the contract: one SVG per icon under `img/icons/`, 24-unit
grid, 1.6-unit round strokes set once on the root `<svg>`, drawn for CSS
masks so each takes the surrounding text colour, replacing "the emoji now
used in the admin navigation, stat cards, health list and toasts" (spec
4.7, "Replaces"). The nav's "Sync Failures" triangle already covers
`sync-failures`, but `admin.js` still draws an emoji nothing in
`img/icons/` yet answers for the health list, the large-deletion badge, the
KPI tiles and `getActivityIcon`. This task draws the eleven names those
still need -- `warning`, `clock`, `disk`, `log-out`, `plus`, `edit`, `trash`,
`user`, `lock`, `unlock`, `skip` -- and lets `tests/test_images.py` accept a
set of any size instead of a hardcoded fifteen. It does not touch `admin.js`:
wiring these class names into the markup is Task 4's job.

Owners: web-designer draws the eleven icons, updates `img/README.md`, and
renders the contact sheet; developer extends and renames the pinning test.
Steps run in the order they are listed: the test first (red), then the
icons (green), then the documentation and the visual check, then the whole
suite, then the commit.

**Design notes** (decisions this task made; none of them is pinned by a
test beyond the shared root attributes and `assert_inert`):
- **`user` vs `users`.** `user` reuses the same head-circle-plus-shoulders
  vocabulary as the existing `users.svg`'s larger figure, recentred and
  drawn a little bigger (`r="3.6"` against `users.svg`'s `r="3.2"`) so a
  single person reads as deliberately alone, not as `users` missing its
  second figure.
- **`lock` / `unlock`.** Both share one body (`rect`, identical
  `x/y/width/height/rx`) and one keyhole path, byte-for-byte. The only
  difference between the two files is the shackle path's last segment:
  `lock.svg` closes it into the body (`v2.9`), `unlock.svg` swings it away
  (`l2.2-1.6`). The shackle's anchor and arc are the same arithmetic
  `protected-paths.svg` already uses for its own (closed) shackle.
- **`skip`.** A vertical bar plus a forward chevron, reading for the same
  glyph `admin.js:625` draws as ⏭️ for a skipped health check: a filled
  triangle is not drawable in a `fill="none"` set, so the chevron (already
  `arrow-right.svg`'s vocabulary, at the same 45-degree angle) stands in for
  the play-triangle half of the glyph.
- **`disk`.** A rounded drive housing with one divider line and one activity
  dot -- a server/drive silhouette, deliberately not the floppy-disk square
  with a folded corner that `💾` (already spoken for by `mirrors.svg`)
  would suggest.
- **`warning`.** Drawn identically to the existing `sync-failures.svg`
  (same triangle, same exclamation mark and dot). `admin.js` already draws
  the same ⚠️ for three different situations today -- the nav item (line
  250), the health list's "Warnings" (line 627) and the large-deletion
  prefix (line 1736) -- so the new name gets the same picture rather than a
  competing one. The two files are never shown side by side (one is a nav
  item, the other sits inline in content), so the shared silhouette does not
  create ambiguity in use.
- **`clock`.** Not tied to a named use site: unlike the other ten, no emoji
  in `admin.js` maps to a generic time/duration concept today. Its two
  hourglass (⏳) sites, the mirror-modal history row (`admin.js:1325`) and
  the sync-job modal title (`admin.js:1375`), both key off job status and
  become a status pill in Task 4 rather than an icon. Drawn as a plain
  circle-and-hands face, the same `r="8.5"` circle `info.svg` already uses,
  so it reads as part of the same family. Left for Task 4 to wire in
  wherever it needs a time/duration glyph, if it needs one.

**Files:**
- Create: `frontend/public/img/icons/warning.svg`, `clock.svg`, `disk.svg`,
  `log-out.svg`, `plus.svg`, `edit.svg`, `trash.svg`, `user.svg`, `lock.svg`,
  `unlock.svg`, `skip.svg`
- Modify: `tests/test_images.py` (`ICON_NAMES` gains the eleven; the
  set-equality test is renamed and gains failure messages)
- Modify: `frontend/public/img/README.md` (the Icons section)

- [ ] **Step 1 (developer): add the eleven names to `ICON_NAMES` and rename
  the count-bearing test.** Replace:

```python
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
```

with:

```python
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
    "warning",
    "clock",
    "disk",
    "log-out",
    "plus",
    "edit",
    "trash",
    "user",
    "lock",
    "unlock",
    "skip",
}
```

Then replace:

```python
def test_the_icon_set_is_the_fifteen_the_design_names():
    assert {path.stem for path in ICONS.glob("*.svg")} == ICON_NAMES
    others = [p.name for p in ICONS.iterdir() if p.suffix != ".svg" and not p.name.startswith(".")]
    assert others == []
```

with:

```python
def test_the_icon_set_is_exactly_the_names_the_design_lists():
    on_disk = {path.stem for path in ICONS.glob("*.svg")}
    assert (
        on_disk == ICON_NAMES
    ), f"icons/*.svg must match ICON_NAMES exactly; missing {sorted(ICON_NAMES - on_disk)}, extra {sorted(on_disk - ICON_NAMES)}"
    others = [p.name for p in ICONS.iterdir() if p.suffix != ".svg" and not p.name.startswith(".")]
    assert others == [], f"non-svg files in icons/: {others}"
```

The new name drops "fifteen" without hardcoding a new count, so the next
icon added here does not have to rename it again. Both assertions now say,
on failure, exactly what is missing or extra, rather than relying on
pytest's default set-diff output.

- [ ] **Step 2 (developer): run it, and watch it fail.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_images.py; echo "rc=$?"`

Expected: `rc=1`, `12 failed, 47 passed, 4 warnings`. Against the
tree before this task's icons exist:
- `test_the_icon_set_is_exactly_the_names_the_design_lists`: `AssertionError:
  icons/*.svg must match ICON_NAMES exactly; missing ['clock', 'disk',
  'edit', 'lock', 'log-out', 'plus', 'skip', 'trash', 'unlock', 'user',
  'warning'], extra []`.
- `test_each_icon_is_drawn_with_the_shared_round_stroke`, once per new name
  (`clock`, `disk`, `edit`, `lock`, `log-out`, `plus`, `skip`, `trash`,
  `unlock`, `user`, `warning` -- 11 in all): each fails inside `svg_root()`
  with `FileNotFoundError: [Errno 2] No such file or directory:
  '.../frontend/public/img/icons/<name>.svg'`, e.g. for `clock`:
  `source = PosixPath('/repo/frontend/public/img/icons/clock.svg')` ...
  `FileNotFoundError: [Errno 2] No such file or directory:
  '/repo/frontend/public/img/icons/clock.svg'`.

The other 47 collected tests pass unchanged: the 15 existing icons and the
mark/favicon/logo checks were never touched.

- [ ] **Step 3 (web-designer): draw the eleven icons.** Same root attributes
  as the existing fifteen (`ICON_STROKE`: `viewBox="0 0 24 24" fill="none"
  stroke="#000" stroke-width="1.6" stroke-linecap="round"
  stroke-linejoin="round"`), no `style=`, no script, no external reference,
  no text, no `<title>`. Create `frontend/public/img/icons/warning.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#000" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3.8 21.2 19.6H2.8z"/><path d="M12 9.8v4.6"/><path d="M12 17.2v.1"/></svg>
```

Create `frontend/public/img/icons/clock.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#000" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.3V12l3.5 2"/></svg>
```

Create `frontend/public/img/icons/disk.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#000" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="5.5" width="17" height="13" rx="2"/><path d="M3.5 14.5h17"/><path d="M7 16.5h.1"/></svg>
```

Create `frontend/public/img/icons/log-out.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#000" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M10 5H5.5v14H10"/><path d="M9.5 12H15.5"/><path d="M15.5 8l4 4-4 4"/></svg>
```

Create `frontend/public/img/icons/plus.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#000" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 6.5v11"/><path d="M6.5 12h11"/></svg>
```

Create `frontend/public/img/icons/edit.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#000" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M16 5 6 15"/><path d="M6 15l-1.5 4 4-1.5"/><path d="M12.8 6.8l1.4 1.4"/></svg>
```

Create `frontend/public/img/icons/trash.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#000" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 7H9.5V5.5H14.5V7H19"/><path d="M6.5 7l.8 12h9.4l.8-12"/><path d="M10 10.5v6M14 10.5v6"/></svg>
```

Create `frontend/public/img/icons/user.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#000" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8.5" r="3.6"/><path d="M5.3 19.5c.9-3.9 3.4-6 6.7-6s5.8 2.1 6.7 6"/></svg>
```

Create `frontend/public/img/icons/lock.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#000" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8.5 10.5V7.6a3.5 3.5 0 0 1 7 0v2.9"/><path d="M12 14.2v.1M12 15.4v1.6"/></svg>
```

Create `frontend/public/img/icons/unlock.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#000" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8.5 10.5V7.6a3.5 3.5 0 0 1 7 0l2.2-1.6"/><path d="M12 14.2v.1M12 15.4v1.6"/></svg>
```

Create `frontend/public/img/icons/skip.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#000" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M7.5 6l6 6-6 6"/><path d="M16.5 6v12"/></svg>
```

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_images.py; echo "rc=$?"`

Expected: `rc=0`, `70 passed, 4 warnings`. The collected count climbs in two
steps: 48 at the parent commit, +11 `test_each_icon_is_drawn_with_the_shared_round_stroke`
ids once `ICON_NAMES` grows to 26 at Step 1 = 59 at Step 2 (Step 2's red run
is 47 passed, 12 failed against that 59: the 11 new round-stroke ids plus the
set-equality test), then +11 `test_every_svg_here_is_inert` ids once the
eleven files themselves exist on disk = 70 at this step, all of them green:
the 47 untouched by this task, the 11 round-stroke ids and the set-equality
test flipping from Step 2's red to green, and the 11 newly-collected inert
ids passing from the moment they are collected.

- [ ] **Step 4 (web-designer): render a contact sheet and look at it.** A
  throwaway HTML page and an external stylesheet (no inline `style=`, no
  `<script>`), generated by a small script rather than transcribed by hand
  (`ICON_NAMES` has 26 entries; hand-writing 52 near-identical cells --
  26 icons times two grounds -- invites a copy-paste error a generator
  can't make), then copied into a container-local copy of `frontend/public`
  so the mask URLs resolve same-origin, and served over loopback only
  (`--network none`). The controller creates `$SCRATCH/pr3` and passes its
  absolute path for this step; `$PWD` is the checkout root. Write
  `$SCRATCH/pr3/contact-sheet.sh`:

```bash
#!/usr/bin/env bash
# Throwaway contact sheet for the icon set (spec section 4.7): every name in
# ICON_NAMES as a CSS mask span, at 24px and 16px, on a light and a dark
# ground. Writes only into its own directory; never part of a commit.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ICONS="dashboard mirrors sync-failures protected-paths users audit-logs settings sun moon copy sync arrow-right check close info warning clock disk log-out plus edit trash user lock unlock skip"

{
    echo '* { box-sizing: border-box; }'
    echo 'body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }'
    echo '.sheet { padding: 24px; }'
    echo '.sheet-light { background: #ffffff; color: #14161a; }'
    echo '.sheet-dark { background: #14161a; color: #ffffff; }'
    echo '.sheet h2 { font-size: 14px; text-transform: uppercase; letter-spacing: .05em; margin: 0 0 16px; }'
    echo '.grid { display: grid; grid-template-columns: repeat(9, minmax(0, 1fr)); gap: 16px; }'
    echo '.cell { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 8px; border: 1px solid currentColor; border-radius: 6px; }'
    echo '.swatches { display: flex; align-items: center; gap: 10px; }'
    echo '.label { margin: 0; font-size: 10px; font-family: ui-monospace, Menlo, monospace; text-align: center; word-break: break-word; }'
    echo '.icon { display: inline-block; flex-shrink: 0; width: 16px; height: 16px; background-color: currentColor; -webkit-mask-position: center; mask-position: center; -webkit-mask-size: contain; mask-size: contain; -webkit-mask-repeat: no-repeat; mask-repeat: no-repeat; }'
    echo '.icon.size-24 { width: 24px; height: 24px; }'
    echo '.icon.size-16 { width: 16px; height: 16px; }'
    for name in $ICONS; do
        echo ".icon-$name { -webkit-mask-image: url(/img/icons/$name.svg); mask-image: url(/img/icons/$name.svg); }"
    done
} > "$HERE/__icons.css"

cell() {
    echo "<div class=\"cell\"><div class=\"swatches\"><span class=\"icon icon-$1 size-24\" aria-hidden=\"true\"></span><span class=\"icon icon-$1 size-16\" aria-hidden=\"true\"></span></div><p class=\"label\">$1</p></div>"
}

{
    echo '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Icon contact sheet</title><link rel="stylesheet" href="__icons.css"></head><body>'
    echo '<section class="sheet sheet-light"><h2>Light ground, dark icon</h2><div class="grid">'
    for name in $ICONS; do cell "$name"; done
    echo '</div></section>'
    echo '<section class="sheet sheet-dark"><h2>Dark ground, white icon</h2><div class="grid">'
    for name in $ICONS; do cell "$name"; done
    echo '</div></section>'
    echo '</body></html>'
} > "$HERE/__icons.html"
```

Run it, create the git-ignored screenshots directory, then serve the copy and
screenshot it, once at the default resolution and once magnified for a close
look at the 16px row:

```bash
bash "$SCRATCH/pr3/contact-sheet.sh"
mkdir -p .screenshots
docker run --rm --network none -u "$(id -u):$(id -g)" --security-opt seccomp=unconfined -e HOME=/tmp \
  -v "$PWD/frontend/public:/site:ro" \
  -v "$SCRATCH/pr3:/extra:ro" \
  -v "$PWD/.screenshots:/out" \
  bsdmirror-test bash -c '
set -e
cp -r /site /tmp/site
cp /extra/__icons.html /tmp/site/__icons.html
cp /extra/__icons.css /tmp/site/__icons.css
cd /tmp/site
python3 -m http.server 8000 --bind 127.0.0.1 >/tmp/http.log 2>&1 &
SERVER=$!
sleep 1
chromium --headless=new --disable-gpu --hide-scrollbars --window-size=1200,800 --screenshot=/out/pr3-icons.png http://127.0.0.1:8000/__icons.html
chromium --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=4 --window-size=1200,600 --screenshot=/out/pr3-icons-4x.png http://127.0.0.1:8000/__icons.html
kill $SERVER 2>/dev/null || true
'
```

`__icons.html`/`__icons.css` render all 26 `.icon.icon-NAME` spans at 24px
and 16px, in the `.icon` mask rule `css/style.css:72-85` uses
(`background-color: currentColor` plus `-webkit-mask-image`/`mask-image:
url(/img/icons/NAME.svg)`, `mask-size: contain`, `mask-position: center`,
`mask-repeat: no-repeat`), once on a white ground in a dark colour and once
on a dark ground in white. Neither file is part of this commit -- they live
under `$SCRATCH`, not under `frontend/public` -- and `.screenshots/` stays
git-ignored.

Expected: `rc=0`; a PNG is written to `.screenshots/pr3-icons.png` and a
second, larger one to `.screenshots/pr3-icons-4x.png`. Open both with the
Read tool. Observed: all 26 icons legible at both sizes on both grounds,
none clipped by the 24-unit grid, and the eleven new ones matching the
existing fifteen's stroke weight and optical size. Specifically: `user`
reads as a single, larger figure next to `users`' pair; `lock` and `unlock`
are distinguishable at 16px by the shackle's gap alone; `skip`'s bar and
chevron read as "skip forward" at both sizes; `disk` reads as a drive (no
floppy-style folded corner); `warning` is legible and, by design, matches
`sync-failures`. No icon needed a redraw.

- [ ] **Step 5 (web-designer): update `img/README.md`'s Icons section.**
  Replace:

```markdown
`icons/NAME.svg` holds 15 icons on a 24-unit grid. Each is drawn with 1.6-unit
round strokes, set once on the root `<svg>`. They are drawn for CSS masks, the
way the redesigned pages are to use them (design section 4.7), so each takes
the text colour of the element it sits in:

    <span class="icon icon-copy" aria-hidden="true"></span>

To add an icon, draw it on the same grid with the same root attributes, and add
its name to `ICON_NAMES` in `tests/test_images.py`.
```

with:

```markdown
`icons/NAME.svg` holds one file per name listed in `ICON_NAMES`
(`tests/test_images.py`), each on a 24-unit grid and drawn with 1.6-unit
round strokes, set once on the root `<svg>`. They are drawn for CSS masks, the
way the redesigned pages are to use them (design section 4.7), so each takes
the text colour of the element it sits in:

    <span class="icon icon-copy" aria-hidden="true"></span>

The eleven added for the admin console -- `warning`, `clock`, `disk`,
`log-out`, `plus`, `edit`, `trash`, `user`, `lock`, `unlock` and `skip` --
join the nav icons already here.

To add an icon, draw it on the same grid with the same root attributes, and add
its name to `ICON_NAMES` in `tests/test_images.py`.
```

This is prose only; no test reads `img/README.md`'s wording (confirmed by
grep across `tests/`), so there is no red/green step for it.

- [ ] **Step 6 (developer): run green, lint, and the whole suite.**

Run: `docker compose run --rm -T test ruff check tests/test_images.py; echo "rc=$?"`
Expected: no output, `rc=0`.

Run: `docker compose run --rm -T test ruff format --check tests/test_images.py; echo "rc=$?"`
Expected: `1 file already formatted`, `rc=0` -- Step 1's code block already
wraps the multi-line `assert (...), f"..."` the way `ruff format` wants it,
so a replay never sees "Would reformat" here.

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_images.py; echo "rc=$?"`
Expected: `rc=0`, `70 passed, 4 warnings`.

Run: `docker compose run --rm -T test; echo "rc=$?"`
Expected: `rc=0`, `1593 passed, 7 warnings` -- the base suite's 1560 passed
plus 33: `test_images.py` itself collects 22 more (11 new
`test_every_svg_here_is_inert[img/icons/<name>.svg]` cases plus 11
`test_each_icon_is_drawn_with_the_shared_round_stroke[<name>]` cases that
were already collected but failing before Step 3), and
`tests/test_fonts.py::test_nothing_loads_fonts_from_google` gains one case
per new file (11 more): it is parametrized over `public_files(".css",
".html", ".js", ".svg")` under `frontend/public` (`tests/test_fonts.py:79`),
not every file in the repository, which is also why nothing under `tests/`
itself (`.py`, or `tests/js/`'s `.mjs`) adds a case here. Both counts were
confirmed by diffing `pytest --collect-only` node-id lists between this
commit and its parent, not guessed. This whole-suite count was observed on a
branch cut from `ff29094`
with no other PR 3 task applied; replaying this plan in order re-observes
it after Tasks 1 and 2, and it should match unless one of those tasks also
changed the suite's size.

- [ ] **Step 7 (developer): commit.**

```bash
git add tests/test_images.py frontend/public/img/README.md frontend/public/img/icons/warning.svg frontend/public/img/icons/clock.svg frontend/public/img/icons/disk.svg frontend/public/img/icons/log-out.svg frontend/public/img/icons/plus.svg frontend/public/img/icons/edit.svg frontend/public/img/icons/trash.svg frontend/public/img/icons/user.svg frontend/public/img/icons/lock.svg frontend/public/img/icons/unlock.svg frontend/public/img/icons/skip.svg
git commit -m "Add the icons the admin console needs"
```

Expected: one commit on top of `ff29094`, 13 files changed, 34
insertions(+), 4 deletions(-).

## Chunk 2: The switch

One task, one commit: the legacy token block goes, `admin.css` is rewritten, `admin.js` emits the new markup, and the contrast tests pin the console in both themes. They cannot land apart: the contrast tests read the stylesheet's selectors and the tokens' values, and the harness renders the markup.

### Task 4: The console, switched

Spec sections 4.1-4.8, 6.1, 6.2, 7 and 9 are the contract. `admin.js`'s markup
gains the mark, the icon spans, the pill mapping and the disk meter; `admin.css`
is rewritten in full to style that markup from the shared tokens instead of a
frozen legacy palette; `tokens.css`'s admin layer drops to one non-colour
override; and the tests that pin all three -- the escaping harness, the
contrast suite and its dynamic harness, the motion and focus-ring checks, and
the icon inventory -- switch with them, in one commit. None of the four can
land alone and leave the suite green: `tests/test_contrast.py` computes every
admin check at import from `admin.css`'s selectors and `tokens.css`'s values,
so a stylesheet that has not yet dropped the legacy block fails the new test
file at collection, and a stylesheet that has already dropped it fails the old
one the same way.

The five test files (`tests/test_contrast.py`, `tests/js/contrast_harness.mjs`,
`tests/test_reduced_motion.py`, `tests/test_focus_ring.py`, `tests/test_images.py`,
plus the escaping-harness pair, `tests/js/escaping_harness.mjs` and
`tests/test_admin_js_escaping.py`) are `developer`'s. `tokens.css` and
`admin.css` are `web-designer`'s. `admin.js`'s markup is `developer`'s. Steps
run in the order listed below: the tests first (red against the console as it
stood before this task), then the stylesheet, then the markup, then the whole
suite green, then the commit.

**Decisions this task makes, where the spec allows more than one shape:**

- **Pill mapping** (spec 4.8), keeping the existing `status-badge` class names
  (tests pin them) and adding the five job-status modifiers as their own
  standalone rules, never grouped with the mirror/protection/role modifiers
  that happen to share a colour:

  | Modifier | Meaning | Tokens |
  |---|---|---|
  | `active`, `completed` | online | `--status-healthy` on `--status-healthy-bg` |
  | `syncing`, `running`, `at-risk` | syncing | `--status-syncing` on `--status-syncing-bg` |
  | `error`, `failed` | error | `--status-error` on `--status-error-bg` |
  | `info`, `pending` | info | `--status-info` on `--status-info-bg` |
  | `health-incomplete` | incomplete | `--status-incomplete` on `--status-incomplete-bg` |
  | `disabled`, `cancelled`, the bare `.status-badge` | neutral | `--text-secondary` on `--bg-secondary` |

  The dot is a `::before` pseudo-element in `currentColor`, so the mirrors
  table's inner `<span class="status-dot">` goes. Protection "unknown" moves
  from `error` to the neutral pill (spec 4.8, "unknown values"). User roles:
  `admin` is `info`, other roles neutral. The warning-emoji prefix on "At
  risk" goes; the pill's colour and word carry it.
- **Health rows:** ok -> `icon-check`, warnings -> `icon-warning`, skipped ->
  `icon-skip`, bad -> `icon-close` in `--status-error`. Recent Sync Jobs rows
  show a pill per status instead of a spinner glyph. The sync-job modal's
  title loses its status-emoji prefix; its status shows as a pill in the facts
  grid. The mirror-modal history rows use pills too, and drop the bare status
  word from their own text now that the row's leading pill already carries it.
- **Activity icons** (`getActivityIcon`): `login_success` -> `unlock`,
  `login_failed` -> `lock`, `logout` -> `log-out`, `user_created` -> `user`,
  `user_updated` -> `edit`, `user_deleted` -> `trash`, `mirror_updated` ->
  `mirrors`, `sync_triggered` -> `sync`, `settings_updated` -> `settings`,
  default -> `audit-logs`. Tiles: total mirrors -> `mirrors`, active ->
  `check`, syncing -> `sync`, users -> `users`, disk -> `disk`, failed ->
  `close`, completed -> `check`. Toasts: success -> `check`, error -> `close`,
  info -> `info`. "+ Add User" becomes `icon-plus` plus the words "Add User".
  The large-deletion badge gains `icon-warning` before its text; the muted
  (below-threshold) variant keeps plain text. The Logout button carries
  `icon-log-out` before its label. `clock` sits on the health card's "Last
  ran ..." line, the one timestamp the console shows outside a table.
- **The mask rule** is `style.css`'s longhand (`.icon` sets
  `background-color: currentColor` and the `-webkit-mask-*`/`mask-*`
  position, size and repeat; each `.icon-NAME` sets only
  `-webkit-mask-image`/`mask-image`), copied as-is rather than a `mask:`
  shorthand, since `admin.css` does not load `style.css`.
- **The disk meter's width** is `data-percent="NN"` (an integer 0-100,
  rounded and clamped) on `.meter-fill`, and `admin.css` carries the 101
  one-line `.meter-fill[data-percent="NN"] { width: NN%; }` rules -- no
  inline style, no CSSOM write. Severity is a class: `is-warn` from
  `DISK_USAGE_WARNING_PERCENT`, `is-crit` from `DISK_USAGE_CRITICAL_PERCENT`,
  replacing `is-warn` rather than joining it. The tick sits at `left: 85%`.
  When `percent_used` is null the tile shows "Unknown" and no meter.
- **`renderMeter()` is three full literal branches**, not one template with a
  class built from a ternary: every class name a render site can ever emit
  stays literal text in `admin.js`, which is what lets a class-usage scan see
  it at all. The four health-check rows pass a pre-built `` html`...` ``
  fragment as `healthChecklistSection`'s `icon` argument for the same reason,
  rather than threading a bare icon name through an interpolation.
  `getActivityIcon()` and `Toast.show`'s icon choice keep the existing
  per-record/per-type lookup-table idiom instead, because both vary by data at
  render time, not by a fixed render site -- the same category
  `active`/`syncing`/`pending` have always been in.
- **The admin console's own colour layer is deleted, not frozen.** Spec
  section 7: `[data-surface="admin"]` in `tokens.css` sets no `--bg-*`,
  `--text-*`, `--accent-*`, `--border-*`, `--status-*`, `--stream-*` or
  `--mark-*` token any more, only `--sidebar-width: 188px`. The console reads
  every colour through the same shared light/dark layers the public site
  uses, and follows the same saved `theme` choice (spec 6.2). `--bg-tertiary`,
  `--status-error-text` and `--status-info-text` are retired with the legacy
  block; nothing outside it read them.
- **`--border-strong` edges are not selector-pinned in `ADMIN_PAIRS`.**
  `.form-input` and `.theme-toggle` declare their border through the
  `border: 1px solid var(--border-strong)` shorthand, which is not a bare
  `var()` the contrast parser's `color_hex()` recognises in isolation, and
  `.btn-secondary`'s edge is the same token besides. All three already
  resolve through the shared `--border-strong` on `--bg-card` pair
  `TOKEN_PAIRS` proves in both public themes, and since the admin surface sets
  no `--border-*` token of its own, that same proof holds for the admin
  console for free.
- **`.user-avatar` keeps its solid `--accent-primary` fill** with
  `--text-on-accent`, reusing the pair `.btn-primary` also uses, rather than a
  neutral chip -- one small point of brand colour in the sidebar footer,
  echoing the mark's own accent axis.
- **`.card` gets no shadow or hover-lift; `.stat-card` gets both.** "Lift on
  hover" (spec 4.4) reads as describing clickable-feeling tiles, not a large,
  non-interactive panel holding a table or a form.

**Files:**
- Modify: `tests/js/escaping_harness.mjs`
- Modify: `tests/test_admin_js_escaping.py`
- Modify: `tests/test_contrast.py`
- Modify: `tests/js/contrast_harness.mjs`
- Delete: `tests/test_legacy_admin_tokens.py`
- Modify: `tests/test_reduced_motion.py`
- Modify: `tests/test_focus_ring.py`
- Add: `tests/test_css_comments.py`
- Modify: `tests/test_images.py`
- Modify: `frontend/public/css/tokens.css`
- Modify: `frontend/public/admin/css/admin.css`
- Modify: `frontend/public/admin/js/admin.js`

- [ ] **Step 1 (developer): write the escaping-harness pins for the new
  markup, before the markup exists.**

  In `tests/js/escaping_harness.mjs`, first the icons-directory helper and a
  code-point allowlist, next to the existing sandbox/source setup. Replace:

```js
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const sourcePath = process.argv[2];
const source = readFileSync(sourcePath, 'utf8');
```

  with:

```js
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const sourcePath = process.argv[2];
const source = readFileSync(sourcePath, 'utf8');

// The icons directory and the code-point allowlist below are read against the
// real repo tree, not the (possibly mutated, possibly tmp-dir) admin.js copy
// under test: pytest always runs this harness with cwd=REPO_ROOT (see
// run_harness() in test_admin_js_escaping.py), so this is stable for both the
// real file and a mutated copy alike.
const ICONS_DIR = path.resolve(process.cwd(), 'frontend/public/img/icons');

/** En dash, em dash, ellipsis -- the only punctuation above U+2000 the console's
 *  own rendered text already uses. Everything else above that point was an
 *  emoji or a symbol glyph standing in for an icon. */
const ALLOWED_HIGH_CODEPOINTS = new Set([0x2013, 0x2014, 0x2026]);
```

  Then, right before `main()`'s closing `process.stdout.write`, insert the new
  checks. The five that only need to see what `setHtml()` wrote build their
  fake element with `makeWriteCapture()` (added earlier in this file) instead
  of a literal getter/setter pair, so they read back whichever property the
  sink assigned through the Proxy's own record of it rather than by naming
  that property themselves, keeping the name confined to the lines that
  already carried it before this task. Replace:

```js
        const out = String(await mod.renderDashboard());
        assert(out.includes('4'), 'the rest of the dashboard did not render alongside the failed card');
        assert(out.includes('status-badge disabled'), `expected the unknown badge, got ${out}`);
        assert(!out.includes('status-badge active'), `must not show a false all-clear: ${out}`);
        return '';
    });

    process.stdout.write(JSON.stringify({ checks }, null, 2) + '\n');
}
```

  with:

```js
        const out = String(await mod.renderDashboard());
        assert(out.includes('4'), 'the rest of the dashboard did not render alongside the failed card');
        assert(out.includes('status-badge disabled'), `expected the unknown badge, got ${out}`);
        assert(!out.includes('status-badge active'), `must not show a false all-clear: ${out}`);
        return '';
    });

    // --- The Reflection switch: mark, icons, pills, the meter (spec 4.7-4.8) -
    //
    // Every emoji and the modal's "x" glyph become a CSS-mask <span> (spec
    // constraint 2: no <svg>, no <img> anywhere in this file), the mirrors
    // table's inner status-dot span goes (the dot is now a ::before rule), and
    // the disk tile gains a meter whose severity is a class driven by
    // DISK_USAGE_WARNING_PERCENT / DISK_USAGE_CRITICAL_PERCENT.

    await check('renderLayout renders the sidebar mark and wordmark', () => {
        mod.state.user = { id: 1, username: 'root', role: 'admin' };
        const out = String(mod.renderLayout(mod.html`<p>body</p>`, 'Dashboard'));
        mod.state.user = null;

        const marks = scanTags(out).filter((t) => t.name === 'span' && t.attrs.class === 'mark');
        assert(marks.length === 1, `expected exactly one .mark span, found ${marks.length} in ${out}`);
        assert(out.includes('<span class="mark-glyph"></span>'), `mark-glyph span missing: ${out}`);
        assert(out.includes('<span class="mark-axis"></span>'), `mark-axis span missing: ${out}`);
        assert(out.includes('<span class="wordmark">BSD Mirror</span>'), `wordmark span missing: ${out}`);
        return '';
    });

    await check('renderLoginPage renders the mark', () => {
        const out = String(mod.renderLoginPage());
        const marks = scanTags(out).filter((t) => t.name === 'span' && t.attrs.class === 'mark');
        assert(marks.length === 1, `expected exactly one .mark span, found ${marks.length} in ${out}`);
        assert(out.includes('<span class="mark-glyph"></span>'), `mark-glyph span missing: ${out}`);
        assert(out.includes('<span class="mark-axis"></span>'), `mark-axis span missing: ${out}`);
        return '';
    });

    await check('renderLayout gives every nav-item an icon span naming the right icon', () => {
        const iconFor = {
            dashboard: 'icon-dashboard',
            mirrors: 'icon-mirrors',
            'sync-failures': 'icon-sync-failures',
            'protected-paths': 'icon-protected-paths',
            users: 'icon-users',
            'audit-logs': 'icon-audit-logs',
            settings: 'icon-settings'
        };
        mod.state.user = { id: 1, username: 'root', role: 'admin' };
        const out = String(mod.renderLayout(mod.html`<p>body</p>`, 'Dashboard'));
        mod.state.user = null;

        for (const [route, iconClass] of Object.entries(iconFor)) {
            const re = new RegExp(
                `data-nav="${route}"[^>]*>\\s*<span class="icon ${iconClass}" aria-hidden="true"></span>`
            );
            assert(re.test(out), `nav-item ${route} missing its ${iconClass} icon span`);
        }
        return `${Object.keys(iconFor).length} nav icons`;
    });

    await check('renderLayout gives the logout button an icon-log-out span', () => {
        mod.state.user = { id: 1, username: 'root', role: 'admin' };
        const out = String(mod.renderLayout(mod.html`<p>body</p>`, 'Dashboard'));
        mod.state.user = null;
        assert(
            /data-action="logout"[^>]*>\s*<span class="icon icon-log-out" aria-hidden="true"><\/span>/.test(out),
            `logout button missing its icon-log-out span: ${out}`
        );
        return '';
    });

    await check('renderDashboard tile icons name mirrors, check, sync, users and disk', async () => {
        const out = await renderWith(mod.renderDashboard, {
            mirrors: { total: 3, active: 2, syncing: 1, error: 0, total_size_bytes: 0 },
            users: { total: 2 },
            storage: { path: '/data/mirrors', total_bytes: 100, used_bytes: 40, free_bytes: 60, percent_used: 40 },
            recent_syncs: [],
            recent_activity: []
        });
        for (const iconClass of ['icon-mirrors', 'icon-check', 'icon-sync', 'icon-users', 'icon-disk']) {
            assert(
                out.includes(`<span class="icon ${iconClass}" aria-hidden="true">`),
                `missing the ${iconClass} tile icon: ${out}`
            );
        }
        return '';
    });

    await check('renderSyncFailures tile icons name close and check', async () => {
        const out = await renderWith(mod.renderSyncFailures, {
            period_days: 30,
            totals: { failed: 2, completed: 5 },
            by_mirror: [],
            incidents: []
        });
        assert(out.includes('<span class="icon icon-close" aria-hidden="true">'), `missing icon-close: ${out}`);
        assert(out.includes('<span class="icon icon-check" aria-hidden="true">'), `missing icon-check: ${out}`);
        return '';
    });

    await check('renderHealthChecksCard gives every row an icon wrapper with the right modifier and icon', () => {
        const out = String(mod.renderHealthChecksCard({
            state: 'failing',
            reason: 'x',
            finished_at: '2026-09-13T07:29:49Z',
            age_seconds: 60,
            bad: [{ label: 'disk', detail: 'full' }],
            skipped: [{ check: 'containers', reason: 'no docker' }],
            warnings: ['low memory'],
            ok: ['disk space']
        }));
        const rows = [
            ['is-bad', 'icon-close'],
            ['is-skip', 'icon-skip'],
            ['is-warn', 'icon-warning'],
            ['is-ok', 'icon-check']
        ];
        for (const [modifier, iconClass] of rows) {
            assert(
                out.includes(
                    `<span class="health-check-icon ${modifier}"><span class="icon ${iconClass}" aria-hidden="true"></span></span>`
                ),
                `missing the health-check-icon ${modifier} / ${iconClass} wrapper: ${out}`
            );
        }
        return '';
    });

    await check('renderDashboard activity rows carry the mapped icon for every action, including the default', async () => {
        const actionsToIcons = {
            login_success: 'icon-unlock',
            login_failed: 'icon-lock',
            logout: 'icon-log-out',
            user_created: 'icon-user',
            user_updated: 'icon-edit',
            user_deleted: 'icon-trash',
            mirror_updated: 'icon-mirrors',
            sync_triggered: 'icon-sync',
            settings_updated: 'icon-settings',
            some_unmapped_action: 'icon-audit-logs'
        };
        const out = await renderWith(mod.renderDashboard, {
            mirrors: { total: 1, active: 1, syncing: 0, error: 0, total_size_bytes: 0 },
            users: { total: 1 },
            storage: { path: '/data/mirrors', total_bytes: 100, used_bytes: 40, free_bytes: 60, percent_used: 40 },
            recent_syncs: [],
            recent_activity: Object.keys(actionsToIcons).map((action, i) => (
                { id: i, action, created_at: '2026-01-01T00:00:00Z' }
            ))
        });
        for (const [action, iconClass] of Object.entries(actionsToIcons)) {
            assert(
                out.includes(`<div class="activity-icon"><span class="icon ${iconClass}" aria-hidden="true"></span></div>`),
                `${action} did not render inside .activity-icon with ${iconClass}: ${out}`
            );
        }
        return `${Object.keys(actionsToIcons).length} actions`;
    });

    await check('Toast.show renders an icon span for success, error and info', () => {
        // A fresh makeWriteCapture() per toast, since each Toast.show() call
        // creates its own element; each one's Map holds className then the
        // sink write in that insertion order, so the last value is always
        // what setHtml() wrote, whichever property that turns out to be.
        const captures = [];
        sandbox.document.createElement = () => {
            const capture = makeWriteCapture();
            captures.push(capture);
            return capture.node;
        };
        sandbox.document.getElementById = (id) =>
            (id === 'toastContainer' ? { appendChild: () => {} } : null);

        mod.Toast.show('ok', 'success');
        mod.Toast.show('bad', 'error');
        mod.Toast.show('fyi', 'info');

        assert(captures.length === 3, `expected 3 toasts created, got ${captures.length}`);
        const written = captures.map(({ assigned }) => [...assigned.values()].at(-1));
        assert(written[0].includes('<span class="icon icon-check" aria-hidden="true">'), `success: ${written[0]}`);
        assert(written[1].includes('<span class="icon icon-close" aria-hidden="true">'), `error: ${written[1]}`);
        assert(written[2].includes('<span class="icon icon-info" aria-hidden="true">'), `info: ${written[2]}`);
        return '';
    });

    await check('Modal.show renders a close button with an icon-close span and aria-label', () => {
        const { node: fakeModal, assigned } = makeWriteCapture();
        sandbox.document.getElementById = (id) => {
            if (id === 'modal') return fakeModal;
            if (id === 'modalOverlay') return { classList: { add() {}, remove() {} } };
            return null;
        };

        mod.Modal.show('Title', mod.html`<p>body</p>`, mod.html`<button>Close</button>`);

        assert(assigned.size === 1, `expected exactly one property assigned, got ${assigned.size}`);
        const written = [...assigned.values()][0];
        assert(
            written.includes(
                '<button class="modal-close" data-action="closeModal" aria-label="Close">'
                + '<span class="icon icon-close" aria-hidden="true"></span></button>'
            ),
            `modal close button missing or wrong: ${written}`
        );
        return '';
    });

    await check('renderUsers Add User button carries an icon-plus span', async () => {
        const out = await renderWith(mod.renderUsers, []);
        assert(
            out.includes('<span class="icon icon-plus" aria-hidden="true"></span> Add User'),
            `Add User button missing its icon: ${out}`
        );
        return '';
    });

    await check('every icon span rendered anywhere names a file under img/icons/', async () => {
        const files = new Set(readdirSync(ICONS_DIR).map((f) => f.replace(/\.svg$/, '')));
        assert(files.size > 0, `no icon files found under ${ICONS_DIR}`);

        mod.state.user = { id: 1, username: 'root', role: 'admin' };
        const layout = String(mod.renderLayout(mod.html`<p>x</p>`, 'Dashboard'));
        mod.state.user = null;
        const login = String(mod.renderLoginPage());
        const dashboard = await renderWith(mod.renderDashboard, {
            mirrors: { total: 1, active: 1, syncing: 0, error: 0, total_size_bytes: 0 },
            users: { total: 1 },
            storage: { path: '/data/mirrors', total_bytes: 100, used_bytes: 40, free_bytes: 60, percent_used: 91 },
            recent_syncs: [{ id: 1, mirror_id: 1, status: 'completed', files_deleted: 0, created_at: '2026-01-01T00:00:00Z' }],
            recent_activity: [
                { id: 1, action: 'login_success', created_at: '2026-01-01T00:00:00Z' },
                { id: 2, action: 'login_failed', created_at: '2026-01-01T00:00:00Z' },
                { id: 3, action: 'logout', created_at: '2026-01-01T00:00:00Z' },
                { id: 4, action: 'user_created', created_at: '2026-01-01T00:00:00Z' },
                { id: 5, action: 'user_updated', created_at: '2026-01-01T00:00:00Z' },
                { id: 6, action: 'user_deleted', created_at: '2026-01-01T00:00:00Z' },
                { id: 7, action: 'mirror_updated', created_at: '2026-01-01T00:00:00Z' },
                { id: 8, action: 'sync_triggered', created_at: '2026-01-01T00:00:00Z' },
                { id: 9, action: 'settings_updated', created_at: '2026-01-01T00:00:00Z' }
            ]
        });
        const syncFailures = await renderWith(mod.renderSyncFailures, {
            period_days: 30, totals: { failed: 1, completed: 1 }, by_mirror: [], incidents: []
        });
        const health = String(mod.renderHealthChecksCard({
            state: 'failing', reason: 'x', finished_at: '2026-01-01T00:00:00Z', age_seconds: 5,
            bad: [{ label: 'a', detail: 'b' }], skipped: [{ check: 'a', reason: 'b' }],
            warnings: ['w'], ok: ['ok']
        }));
        const users = await renderWith(mod.renderUsers, [
            { id: 1, username: 'a', email: 'a@x.com', role: 'admin', is_active: true, last_login: null }
        ]);
        const { node: toastNode, assigned: toastAssigned } = makeWriteCapture();
        sandbox.document.createElement = () => toastNode;
        sandbox.document.getElementById = (id) =>
            (id === 'toastContainer' ? { appendChild: () => {} } : null);
        mod.Toast.show('hi', 'info');
        const toastHtml = [...toastAssigned.values()].at(-1);

        const corpus = layout + login + dashboard + syncFailures + health + users + toastHtml;
        const used = new Set([...corpus.matchAll(/\bicon-([a-z][a-z-]*)\b/g)].map((m) => m[1]));
        assert(used.size > 0, 'no icon-NAME classes found in any rendered view');
        const missing = [...used].filter((name) => !files.has(name));
        assert(missing.length === 0, `rendered icon-NAME(s) with no file under img/icons/: ${missing.sort()}`);
        return `${used.size} distinct icons found`;
    });

    await check('renderMirrors renders the status pill with no inner span', async () => {
        const out = await renderWith(mod.renderMirrors, [
            { id: 1, name: 'FreeBSD', url_path: '/pub/FreeBSD', status: 'active', total_size_human: '1.0 TB', last_sync_completed: '2026-01-01T00:00:00Z' }
        ]);
        assert(!out.includes('status-dot'), `status-dot should be gone: ${out}`);
        assert(
            /<span class="status-badge active">\s*active\s*<\/span>/.test(out),
            `expected a plain pill with no inner span: ${out}`
        );
        return '';
    });

    await check('renderDashboard renders a Recent Sync Jobs pill with no inner span', async () => {
        const out = await renderWith(mod.renderDashboard, {
            mirrors: { total: 1, active: 1, syncing: 0, error: 0, total_size_bytes: 0 },
            users: { total: 1 },
            storage: { path: '/data/mirrors', total_bytes: 100, used_bytes: 40, free_bytes: 60, percent_used: 40 },
            recent_syncs: [{ id: 1, mirror_id: 7, status: 'completed', files_deleted: 0, created_at: '2026-01-01T00:00:00Z' }],
            recent_activity: []
        });
        assert(
            /<span class="status-badge completed">\s*completed\s*<\/span>/.test(out),
            `expected a plain job-status pill: ${out}`
        );
        return '';
    });

    await check('viewSyncLogs shows the status as a pill and drops the title emoji prefix', async () => {
        const { node: fakeModal, assigned } = makeWriteCapture();
        sandbox.document.getElementById = (id) => {
            if (id === 'modal') return fakeModal;
            if (id === 'modalOverlay') return { classList: { add() {}, remove() {} } };
            return null;
        };
        mod.api.get = async () => ({
            id: 42, status: 'failed', triggered_by: 'scheduler',
            started_at: '2026-01-01T00:00:00Z', completed_at: '2026-01-01T00:05:00Z',
            files_transferred: 3, bytes_transferred: 1024, files_deleted: 0,
            error_message: 'boom', rsync_output: 'log output'
        });

        await mod.actions.viewSyncLogs(42);

        assert(assigned.size === 1, `expected exactly one property assigned, got ${assigned.size}`);
        const written = [...assigned.values()][0];
        const titles = scanTags(written).filter((t) => t.name === 'h3' && t.attrs.id === 'modalTitle');
        assert(titles.length === 1, `expected one title, found ${titles.length} in ${written}`);
        assert(written.includes('>Sync Job #42<'), `title should read "Sync Job #42" with no prefix: ${written}`);
        assert(
            /<span class="status-badge failed">\s*failed\s*<\/span>/.test(written),
            `expected a plain status pill in the facts grid: ${written}`
        );
        return '';
    });

    await check('viewMirror renders each history row status as a pill instead of an emoji', async () => {
        const { node: fakeModal, assigned } = makeWriteCapture();
        sandbox.document.getElementById = (id) => {
            if (id === 'modal') return fakeModal;
            if (id === 'modalOverlay') return { classList: { add() {}, remove() {} } };
            return null;
        };
        mod.api.get = async (endpoint) => {
            if (endpoint.includes('/sync-history')) {
                return [
                    { id: 1, status: 'completed', bytes_transferred: 100, files_deleted: 0, triggered_by: 'admin', completed_at: '2026-01-01T00:00:00Z' },
                    { id: 2, status: 'running', bytes_transferred: 0, files_deleted: 0, triggered_by: null, started_at: '2026-01-01T00:00:00Z' }
                ];
            }
            return { id: 9, name: 'FreeBSD', upstream_url: 'rsync://x/pub', local_path: '/data/x', total_size_human: '1.0 GB' };
        };

        await mod.actions.viewMirror(9);

        assert(assigned.size === 1, `expected exactly one property assigned, got ${assigned.size}`);
        const written = [...assigned.values()][0];
        assert(
            /<span class="status-badge completed">\s*completed\s*<\/span>/.test(written),
            `expected a plain pill for the completed row: ${written}`
        );
        assert(
            /<span class="status-badge running">\s*running\s*<\/span>/.test(written),
            `expected a plain pill for the running row: ${written}`
        );
        const offenders = [...written].filter(
            (ch) => ch.codePointAt(0) > 0x2000 && !ALLOWED_HIGH_CODEPOINTS.has(ch.codePointAt(0))
        );
        assert(offenders.length === 0, `emoji glyph(s) left in the history rows: ${JSON.stringify([...new Set(offenders)])}`);
        return '';
    });

    await check('renderDashboard shows the disk meter at is-warn, at is-crit and never for an unknown percentage', async () => {
        const payloadAt = (percentUsed) => ({
            mirrors: { total: 1, active: 1, syncing: 0, error: 0, total_size_bytes: 0 },
            users: { total: 1 },
            storage: { path: '/data/mirrors', total_bytes: 1000, used_bytes: 910, free_bytes: 90, percent_used: percentUsed },
            recent_syncs: [],
            recent_activity: []
        });

        const warn = await renderWith(mod.renderDashboard, payloadAt(91));
        assert(
            warn.includes('<div class="meter-fill is-warn" data-percent="91"></div>'),
            `expected the 91% warn band: ${warn}`
        );
        assert(!warn.includes('is-crit'), `did not expect is-crit at 91%: ${warn}`);

        const crit = await renderWith(mod.renderDashboard, payloadAt(96));
        assert(
            crit.includes('<div class="meter-fill is-crit" data-percent="96"></div>'),
            `expected the 96% crit band: ${crit}`
        );
        assert(!crit.includes('meter-fill is-warn'), `is-crit must replace is-warn, not add to it: ${crit}`);

        const unknownPayload = payloadAt(40);
        unknownPayload.storage.percent_used = null;
        const unknown = await renderWith(mod.renderDashboard, unknownPayload);
        assert(!unknown.includes('class="meter"'), `no meter should render when percent_used is null: ${unknown}`);
        return '';
    });

    await check(
        'renderMirrors, renderSyncFailures, renderProtectedPaths, renderUsers, renderAuditLogs and '
        + 'renderSettings mark numeric and time cells with class=num',
        async () => {
            const mirrors = await renderWith(mod.renderMirrors, [
                { id: 1, name: 'FreeBSD', url_path: '/pub/FreeBSD', status: 'active', total_size_human: '1.0 TB', last_sync_completed: null }
            ]);
            assert(mirrors.includes('<th class="num">Size</th>'), `mirrors: Size header not numeric: ${mirrors}`);
            assert(mirrors.includes('<td class="num">1.0 TB</td>'), `mirrors: Size cell not numeric: ${mirrors}`);
            assert(mirrors.includes('<th class="num">Last Sync</th>'), `mirrors: Last Sync header not numeric: ${mirrors}`);
            assert(mirrors.includes('<td class="num">Never</td>'), `mirrors: Last Sync cell not numeric: ${mirrors}`);

            const failures = await renderWith(mod.renderSyncFailures, {
                period_days: 30,
                totals: { failed: 1, completed: 1 },
                by_mirror: [{ mirror_name: 'FreeBSD', failed: 3, completed: 7, failure_rate_percent: 30 }],
                incidents: [{ mirror_name: 'FreeBSD', error_message: 'boom', occurrences: 5, first_seen: null, last_seen: null, latest_job_id: 1 }]
            });
            for (const header of ['Failed', 'Completed', 'Failure Rate', 'Occurrences', 'First Seen', 'Last Seen']) {
                assert(failures.includes(`<th class="num">${header}</th>`), `${header} header not numeric: ${failures}`);
            }
            assert(/<td class="num[^"]*">3<\/td>/.test(failures), `Failed cell not numeric: ${failures}`);
            assert(failures.includes('<td class="num">7</td>'), `Completed cell not numeric: ${failures}`);
            assert(failures.includes('<td class="num">30%</td>'), `Failure Rate cell not numeric: ${failures}`);
            assert(failures.includes('<td class="num">5</td>'), `Occurrences cell not numeric: ${failures}`);
            const incidentDashCells = (failures.match(/<td class="num">--<\/td>/g) || []).length;
            assert(
                incidentDashCells === 2,
                `First Seen and Last Seen cells not both numeric: ${failures}`
            );

            const inventoryPayload = {
                generated_at: '2026-01-01T00:00:00Z',
                mirrors: [{
                    mirror_type: 'freebsd', mirror_names: ['FreeBSD'], root: '/x', available: true, error: null,
                    truncated: false, protected_not_on_disk: [],
                    releases: [{
                        version: '14.3', line: '14.3', major: '14', kind: 'release', protection: 'full',
                        unprotected_locations: [], locations: ['a', 'b'], location_count: 2,
                        newest: true, latest_in_major: true, current: true, at_risk: false, modified: null
                    }]
                }]
            };
            mod.api.get = async (endpoint) =>
                (endpoint === '/admin/archive-inventory' ? inventoryPayload : { groups: [] });
            const protectedPaths = String(await mod.renderProtectedPaths());
            assert(
                protectedPaths.includes('<th class="num">Locations</th>'),
                `archive inventory: Locations header not numeric: ${protectedPaths}`
            );
            assert(
                protectedPaths.includes('<td class="num">2</td>'),
                `archive inventory: Locations cell not numeric: ${protectedPaths}`
            );
            assert(
                protectedPaths.includes('<th class="num">Last Changed</th>'),
                `archive inventory: Last Changed header not numeric: ${protectedPaths}`
            );
            assert(
                protectedPaths.includes('<td class="num">--</td>'),
                `archive inventory: Last Changed cell not numeric: ${protectedPaths}`
            );

            const users = await renderWith(mod.renderUsers, [
                { id: 1, username: 'a', email: 'a@x.com', role: 'admin', is_active: true, last_login: null }
            ]);
            assert(users.includes('<th class="num">Last Login</th>'), `users: Last Login header not numeric: ${users}`);
            assert(users.includes('<td class="num">Never</td>'), `users: Last Login cell not numeric: ${users}`);

            const auditLogs = await renderWith(mod.renderAuditLogs, [{
                id: 1, created_at: null, username: 'a', action: 'login_success',
                resource_type: 'user', resource_id: null, ip_address: '127.0.0.1'
            }]);
            assert(auditLogs.includes('<th class="num">Time</th>'), `audit logs: Time header not numeric: ${auditLogs}`);
            assert(auditLogs.includes('<td class="num">--</td>'), `audit logs: Time cell not numeric: ${auditLogs}`);

            const settings = await renderWith(mod.renderSettings, [
                { key: 'sync_schedule', value: '0 4 * * *', description: 'when', updated_at: null }
            ]);
            assert(settings.includes('<th class="num">Last Updated</th>'), `settings: Last Updated header not numeric: ${settings}`);
            assert(settings.includes('<td class="num">--</td>'), `settings: Last Updated cell not numeric: ${settings}`);
            return '';
        }
    );

    await check('releaseTagBadges renders At risk with no emoji', async () => {
        const inventoryPayload = {
            generated_at: '2026-01-01T00:00:00Z',
            mirrors: [{
                mirror_type: 'openbsd', mirror_names: ['OpenBSD'], root: '/x', available: true, error: null,
                truncated: false, protected_not_on_disk: [],
                releases: [{
                    version: '7.5', line: '7.5', major: '7', kind: 'release', protection: 'none',
                    unprotected_locations: [], locations: ['a'], location_count: 1,
                    newest: false, latest_in_major: false, current: false, at_risk: true, modified: null
                }]
            }]
        };
        mod.api.get = async (endpoint) =>
            (endpoint === '/admin/archive-inventory' ? inventoryPayload : { groups: [] });
        const out = String(await mod.renderProtectedPaths());
        assert(out.includes('<span class="status-badge at-risk">At risk</span>'), `expected the plain At risk pill: ${out}`);
        assert(!out.includes('⚠'), `the warning emoji must be gone: ${out}`);
        return '';
    });

    await check('admin.js no longer names status-dot anywhere', () => {
        assert(!source.includes('status-dot'), 'status-dot should be fully removed; the dot is now a ::before rule');
        return '';
    });

    await check('no rendered view contains an emoji or symbol glyph beyond the allowed dashes and ellipsis', async () => {
        mod.state.user = { id: 1, username: 'root', role: 'admin' };
        const layout = String(mod.renderLayout(mod.html`<p>x</p>`, 'Dashboard'));
        mod.state.user = null;
        const login = String(mod.renderLoginPage());
        const dashboard = await renderWith(mod.renderDashboard, {
            mirrors: { total: 1, active: 1, syncing: 0, error: 0, total_size_bytes: 0 },
            users: { total: 1 },
            storage: { path: '/data/mirrors', total_bytes: 1000, used_bytes: 910, free_bytes: 90, percent_used: 91 },
            recent_syncs: [{ id: 1, mirror_id: 1, status: 'completed', files_deleted: 1500, created_at: '2026-01-01T00:00:00Z' }],
            recent_activity: [{ id: 1, action: 'login_success', created_at: '2026-01-01T00:00:00Z' }]
        });
        const mirrors = await renderWith(mod.renderMirrors, [
            { id: 1, name: 'FreeBSD', url_path: '/pub/FreeBSD', status: 'active', total_size_human: '1.0 TB', last_sync_completed: null }
        ]);
        const syncFailures = await renderWith(mod.renderSyncFailures, {
            period_days: 30, totals: { failed: 1, completed: 1 }, by_mirror: [], incidents: []
        });
        const users = await renderWith(mod.renderUsers, [
            { id: 1, username: 'a', email: 'a@x.com', role: 'admin', is_active: true, last_login: null }
        ]);
        const auditLogs = await renderWith(mod.renderAuditLogs, [
            { created_at: '2026-01-01T00:00:00Z', username: 'a', action: 'login_success', resource_type: 'user', resource_id: 1, ip_address: '127.0.0.1' }
        ]);
        const settings = await renderWith(mod.renderSettings, [
            { key: 'sync_schedule', value: '0 4 * * *', description: 'when', updated_at: null }
        ]);
        const health = String(mod.renderHealthChecksCard({
            state: 'failing', reason: 'x', finished_at: '2026-01-01T00:00:00Z', age_seconds: 5,
            bad: [{ label: 'a', detail: 'b' }], skipped: [{ check: 'a', reason: 'b' }],
            warnings: ['w'], ok: ['ok']
        }));
        const filesDeleted = String(mod.filesDeletedBadge(mod.LARGE_DELETION_THRESHOLD));

        const corpus = [layout, login, dashboard, mirrors, syncFailures, users, auditLogs, settings, health, filesDeleted].join('');
        const offenders = [...corpus].filter(
            (ch) => ch.codePointAt(0) > 0x2000 && !ALLOWED_HIGH_CODEPOINTS.has(ch.codePointAt(0))
        );
        assert(
            offenders.length === 0,
            `emoji or symbol glyph(s) found: ${JSON.stringify([...new Set(offenders)])}`
        );
        assert(!corpus.includes('×'), 'the modal-close "×" glyph must be gone');
        return '';
    });

    process.stdout.write(JSON.stringify({ checks }, null, 2) + '\n');
}
```

  In `tests/test_admin_js_escaping.py`, add the 21 names to `HARNESS_CHECKS`.
  Replace:

```python
    "renderHealthChecksCard escapes bad, skipped, warning and ok entries end-to-end",
    "renderHealthChecksCard renders unknown when given no data",
    "renderDashboard renders the health-checks card end-to-end via its own fetch",
    "renderDashboard shows the health-checks card as unknown, not a false all-clear, when that fetch fails",
]
```

  with:

```python
    "renderHealthChecksCard escapes bad, skipped, warning and ok entries end-to-end",
    "renderHealthChecksCard renders unknown when given no data",
    "renderDashboard renders the health-checks card end-to-end via its own fetch",
    "renderDashboard shows the health-checks card as unknown, not a false all-clear, when that fetch fails",
    "renderLayout renders the sidebar mark and wordmark",
    "renderLoginPage renders the mark",
    "renderLayout gives every nav-item an icon span naming the right icon",
    "renderLayout gives the logout button an icon-log-out span",
    "renderDashboard tile icons name mirrors, check, sync, users and disk",
    "renderSyncFailures tile icons name close and check",
    "renderHealthChecksCard gives every row an icon wrapper with the right modifier and icon",
    "renderDashboard activity rows carry the mapped icon for every action, including the default",
    "Toast.show renders an icon span for success, error and info",
    "Modal.show renders a close button with an icon-close span and aria-label",
    "renderUsers Add User button carries an icon-plus span",
    "every icon span rendered anywhere names a file under img/icons/",
    "renderMirrors renders the status pill with no inner span",
    "renderDashboard renders a Recent Sync Jobs pill with no inner span",
    "viewSyncLogs shows the status as a pill and drops the title emoji prefix",
    "viewMirror renders each history row status as a pill instead of an emoji",
    "renderDashboard shows the disk meter at is-warn, at is-crit and never for an unknown percentage",
    "renderMirrors, renderSyncFailures, renderProtectedPaths, renderUsers, renderAuditLogs and "
    "renderSettings mark numeric and time cells with class=num",
    "releaseTagBadges renders At risk with no emoji",
    "admin.js no longer names status-dot anywhere",
    "no rendered view contains an emoji or symbol glyph beyond the allowed dashes and ellipsis",
]
```

  Then update the one negative control the modal-close markup change touches
  (its anchor gains `aria-label="Close"` in the markup step below, so the
  planted defect has to plant into the new text, not the old). Replace:

```python
    (
        "inline_event_handler",
        '<button class="modal-close" data-action="closeModal">',
        '<button class="modal-close" onclick="Modal.close()" data-action="closeModal">',
        "test_no_inline_event_handlers_in_markup",
    ),
```

  with:

```python
    (
        "inline_event_handler",
        '<button class="modal-close" data-action="closeModal" aria-label="Close">',
        '<button class="modal-close" onclick="Modal.close()" data-action="closeModal" aria-label="Close">',
        "test_no_inline_event_handlers_in_markup",
    ),
```

  Also, the comment on the `drop_global_regex_flag` mutation a few entries
  above cites language that does not belong in a repo file. Replace:

```python
        # The bug class the brief called out: an escape that stops in the wrong
        # place. Without /g only the first metacharacter is replaced.
```

  with:

```python
        # The bug class this mutation guards against: an escape that stops in
        # the wrong place. Without /g only the first metacharacter is replaced.
```

- [ ] **Step 2 (developer): run `tests/test_admin_js_escaping.py`, and watch it
  fail.** `admin.js` still renders the old emoji, `status-dot` span and
  unlabelled modal-close button, so 19 of the 21 new checks fail for exactly
  the property they test; the `inline_event_handler` control fails too,
  because its new anchor does not exist in `admin.js` yet. Two of the new
  checks pass already, for real reasons: the Recent Sync Jobs pill never had
  an inner span to begin with (only the mirrors table's did), and the
  icon-coverage check already finds one real icon (`icon-moon`) with a file to
  match.

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_admin_js_escaping.py; echo "rc=$?"`

  Expected: `rc=1`, `20 failed, 99 passed, 4 warnings`. Two representative
  failures:

  ```
  AssertionError: status-dot should be fully removed; the dot is now a ::before rule
  ```

  ```
  AssertionError: emoji or symbol glyph(s) found: ["🔄","📊","💾","⚠","️","🔒","👥","📋","⚙","✅","🗄","🔓","❌","⏭"]
  ```

  and the negative control:

  ```
  AssertionError: negative control 'inline_event_handler' no longer matches admin.js. Update the control, do not delete it.
  assert 0 >= 1
  ```

  The 20 failed node ids: the 19 new-feature checks named in the list above
  (every one except "renderDashboard renders a Recent Sync Jobs pill with no
  inner span" and "every icon span rendered anywhere names a file under
  img/icons/", which already pass) plus
  `test_scanner_catches_planted_defect[inline_event_handler]`.
  `test_harness_check_list_is_complete` and both mutation-test families still
  pass: the harness reports every named check, each marked failed, so the set
  of names still matches, and a mutated copy still fails something even
  though the load path is unaffected.

- [ ] **Step 3 (developer): rewrite the admin half of `tests/test_contrast.py`
  for a console that follows the theme toggle instead of being frozen dark.**
  Every replacement below in file order.

  The module docstring, which described the old, frozen arrangement. Replace:

```python
The public site runs the "Reflection" palette (docs/design/2026-09-25-
reflection-redesign.md, sections 4.1-4.4, 4.7-4.8 and 9); the admin panel is
frozen at its pre-Reflection colours by tokens.css's LEGACY ADMIN block
(tests/test_legacy_admin_tokens.py) until its own redesign. This file checks
both, but the two halves are largely independent: a change to the public
palette should never need to touch ADMIN_PAIRS, and vice versa.
```

  with:

```python
Both surfaces run the "Reflection" palette (docs/design/2026-09-25-
reflection-redesign.md, sections 4.1-4.4, 4.7-4.9): the admin console follows
the same saved light/dark choice as the public site (section 6.2) and sets no
colour token of its own (section 7), so every ADMIN_PAIRS entry below is
checked against the exact same tokens the public site's LIGHT/DARK themes
already prove compliant, in both admin states. This file checks both
surfaces, but the two halves are largely independent day to day: a change to
the public palette should never need to touch ADMIN_PAIRS, and vice versa --
only a change to a token both surfaces share moves both at once, which is
exactly what the mutation tests below are for.
```

  `build_themes()` returns four dicts now, not three: the admin console has
  two real rendered states (light and dark), not one frozen one. Replace:

```python
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
```

  with:

```python
def build_themes(tokens_css_text):
    """Returns (light, dark, admin_light, admin_dark), each {token_name: raw
    value string}.

    Raw, not yet resolved through var() -- resolve()/resolved_hex() below walk
    the chain at lookup time using whichever of these dicts is asked, so a
    token that is only overridden for one theme still resolves correctly
    through the layers under it.

    admin_light and admin_dark mirror the two real states a browser actually
    renders (spec section 6.2): [data-surface="admin"] alone -- data-theme
    absent, i.e. light -- and [data-theme="dark"][data-surface="admin"]
    together. Since [data-theme="dark"] does not match at all in the first
    state, admin_light is light-plus-admin, never dark-plus-admin, unlike the
    single always-dark `admin` this function returned before the admin
    console followed the theme toggle (spec section 6.1's "Admin is dark-only"
    is gone, along with the LEGACY ADMIN block).
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

    admin_light = dict(light)
    admin_light.update(parse_custom_properties(admin_body))

    admin_dark = dict(dark)
    admin_dark.update(parse_custom_properties(admin_body))

    return light, dark, admin_light, admin_dark
```

  `test_light_dark_admin_actually_differ` no longer has a claim to make once
  the admin layer sets no colour -- `ADMIN["--bg-card"]` really does now equal
  `DARK["--bg-card"]`. It becomes a positive assertion that the admin layer
  declares no colour token at all. Replace:

```python
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
```

  with:

```python
TOKENS_TEXT = TOKENS_CSS.read_text(encoding="utf-8")
LIGHT, DARK, ADMIN_LIGHT, ADMIN_DARK = build_themes(TOKENS_TEXT)


def test_the_admin_layer_sets_no_colour_token():
    """Spec section 7: the admin console's own redesign folds every one of
    its colours back into the shared light/dark layers, leaving
    [data-surface="admin"] with nothing but its one non-colour override
    (--sidebar-width). A colour token reintroduced there would silently
    re-freeze whatever pair it backs at today's value, exactly the LEGACY
    ADMIN bug this same block used to be on purpose
    (tests/test_legacy_admin_tokens.py, deleted alongside it) -- so this
    checks the block's own declarations directly, not merely that
    ADMIN_LIGHT/ADMIN_DARK happen to resolve like LIGHT/DARK today."""
    admin_tokens = parse_custom_properties(find_block(TOKENS_TEXT, '[data-surface="admin"]'))
    colour_prefixes = (
        "--bg-",
        "--text-",
        "--accent-",
        "--border-",
        "--status-",
        "--stream-",
        "--mark-",
    )
    offenders = sorted(name for name in admin_tokens if name.startswith(colour_prefixes))
    assert not offenders, f'[data-surface="admin"] still sets colour token(s): {offenders}'
```

  The token-level table's comment, which explained why `--status-info` and
  `--status-incomplete` had no consumer yet. Replace:

```python
# The token-level pairs spec section 9 names, resolved directly from
# tokens.css in both themes -- independent of whether a component rule in
# style.css happens to consume a given pair today. Two of these
# (--status-info, --status-incomplete) have no consumer until the admin
# console's redesign, which spec section 4.8's table gives them to (admin.css
# reads the LEGACY ADMIN block's pinned tokens until then); --border-strong
# reaches the public site only as two hover borders (a border-color, which no
# selector pair above reads), and the disk meter's fills have no consumer yet
# either (spec section 4.8, "Disk meter") -- all of them are pinned here, so
# each is checked wherever it is consumed, including by the admin console's
# own redesign (spec section 6.1).
```

  with:

```python
# The token-level pairs spec section 9 names, resolved directly from
# tokens.css in both themes -- independent of whether a component rule in
# style.css happens to consume a given pair today. Two of these
# (--status-info, --status-incomplete) have no consumer on the public site --
# they back the admin console's info/incomplete pills instead (spec section
# 4.8's table; see ADMIN_PAIRS' .status-badge.info/.pending/.health-incomplete
# rows); --border-strong reaches the public site only as two hover borders (a
# border-color, which no selector pair above reads) and backs three admin
# control edges the same way (spec section 9; not separately selector-pinned
# in ADMIN_PAIRS, see the note above compute_admin_checks()); the disk meter's
# fills are consumed only by the admin console (spec section 4.8, "Disk
# meter") -- all of them are pinned here, so each is checked wherever it is
# actually consumed, in both public themes and, since the admin surface sets
# no colour of its own, in both admin states for free.
```

  One new `TOKEN_PAIRS` row: `.log-pre-error` reads `--status-error` directly
  against `--bg-secondary`, a pair no other row covers. Replace:

```python
    ("--status-healthy", "--bg-card", 3.0),
    ("--status-syncing", "--bg-card", 3.0),
    ("--status-error", "--bg-card", 3.0),
    # The disk meter: each fill against the track (--border-color), 3:1. The
```

  with:

```python
    ("--status-healthy", "--bg-card", 3.0),
    ("--status-syncing", "--bg-card", 3.0),
    ("--status-error", "--bg-card", 3.0),
    # admin.css's .log-pre-error (spec 6.1: "log blocks ... in mono") reads
    # --status-error directly against --bg-secondary; no other component pair
    # covers that background, so it gets a row of its own.
    ("--status-error", "--bg-secondary", 4.5),
    # The disk meter: each fill against the track (--border-color), 3:1. The
```

  `ADMIN_PAIRS` grows from 26 entries (one of them `.login-error`, which
  leaves with the dead rule it pinned) to 68, and `compute_admin_checks()`
  takes a `{label: theme}` dict, the same shape `compute_public_checks()` and
  `compute_token_checks()` already use, instead of one theme. Replace:

```python
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
```

  with:

```python
# ===========================================================================
# The pairs the admin panel actually renders (admin.css). The admin console
# now follows the same saved light/dark choice as the public site (spec
# section 6.2), so every pair here is checked in both ADMIN_LIGHT and
# ADMIN_DARK -- see compute_admin_checks(). Since the admin layer sets no
# colour token of its own any more (spec section 7), every one of these
# resolves through the exact same tokens the public site's LIGHT/DARK themes
# already do; nothing here is a colour admin alone invented.
# ===========================================================================
# fmt: off
ADMIN_PAIRS = [
    # --- Shell: sidebar, header, the theme toggle -------------------------
    ("body", "body", "color", ("own",), 4.5),
    (".loading-screen", ".loading-screen", "color", ("parent", "body"), 4.5),
    (".wordmark", ".wordmark", "color", ("parent", ".sidebar"), 4.5),
    (".nav-section-title", ".nav-section-title", "color", ("parent", ".sidebar"), 4.5),
    (".nav-item", ".nav-item", "color", ("parent", ".sidebar"), 4.5),
    (".nav-item:hover", ".nav-item:hover", "color", ("own",), 4.5),
    (".nav-item.active", ".nav-item.active", "color", ("own",), 4.5),
    (".user-name", ".user-name", "color", ("parent", ".user-info"), 4.5),
    (".user-role", ".user-role", "color", ("parent", ".user-info"), 4.5),
    (".user-avatar", ".user-avatar", "color", ("own",), 4.5),
    (".header-title", ".header-title", "color", ("parent", ".header"), 4.5),
    (".theme-toggle", ".theme-toggle", "color", ("own",), 4.5),
    # --- Cards and KPI tiles (spec 6.1) ------------------------------------
    (".card-title", ".card-title", "color", ("parent", ".card"), 4.5),
    (".card-subtitle", ".card-subtitle", "color", ("parent", ".card"), 4.5),
    (".stat-card-icon", ".stat-card-icon", "color", ("own",), 4.5),
    (".stat-card-trend.up", ".stat-card-trend.up", "color", ("own",), 4.5),
    (".stat-card-trend.down", ".stat-card-trend.down", "color", ("own",), 4.5),
    (".stat-card-value", ".stat-card-value", "color", ("parent", ".stat-card"), 4.5),
    (".stat-card-label", ".stat-card-label", "color", ("parent", ".stat-card"), 4.5),
    # --- Tables -------------------------------------------------------------
    ("th", "th", "color", ("own",), 4.5),
    ("td", "td", "color", ("parent", ".card"), 4.5),
    # td's own rule sets no colour of its own on hover, so the text is still
    # td's --text-primary; only the background changes. fg_selector reads the
    # unconditional rule, bg_source reads the hover rule's own fill.
    ("tr:hover td", "td", "color", ("parent", "tr:hover td"), 4.5),
    # --- Status pills (spec 4.8): the bare/neutral rule, then every named
    # modifier the job, mirror, protection and role pills can render. Each is
    # its own standalone rule (never grouped), even where two modifiers share
    # a colour -- see admin.css's status-badge section. --------------------
    (".status-badge", ".status-badge", "color", ("own",), 4.5),
    (".status-badge.disabled", ".status-badge.disabled", "color", ("own",), 4.5),
    (".status-badge.cancelled", ".status-badge.cancelled", "color", ("own",), 4.5),
    (".status-badge.active", ".status-badge.active", "color", ("own",), 4.5),
    (".status-badge.completed", ".status-badge.completed", "color", ("own",), 4.5),
    (".status-badge.syncing", ".status-badge.syncing", "color", ("own",), 4.5),
    (".status-badge.running", ".status-badge.running", "color", ("own",), 4.5),
    (".status-badge.at-risk", ".status-badge.at-risk", "color", ("own",), 4.5),
    (".status-badge.error", ".status-badge.error", "color", ("own",), 4.5),
    (".status-badge.failed", ".status-badge.failed", "color", ("own",), 4.5),
    (".status-badge.info", ".status-badge.info", "color", ("own",), 4.5),
    (".status-badge.pending", ".status-badge.pending", "color", ("own",), 4.5),
    # "incomplete": the health-checks card only (spec 4.8: kept distinct from
    # neutral, so it is never mistaken for "Unknown").
    (".status-badge.health-incomplete", ".status-badge.health-incomplete", "color", ("own",), 4.5),
    # --- Recent Sync Jobs / Recent Activity, and the health-checks card ----
    (".activity-icon", ".activity-icon", "color", ("own",), 4.5),
    (".activity-text", ".activity-text", "color", ("parent", ".card"), 4.5),
    (".activity-time", ".activity-time", "color", ("parent", ".card"), 4.5),
    (".health-check-icon", ".health-check-icon", "color", ("parent", ".card"), 4.5),
    (".health-check-icon.is-bad", ".health-check-icon.is-bad", "color", ("parent", ".card"), 4.5),
    (".health-check-icon.is-warn", ".health-check-icon.is-warn", "color", ("parent", ".card"), 4.5),
    (".health-check-icon.is-ok", ".health-check-icon.is-ok", "color", ("parent", ".card"), 4.5),
    (".health-check-icon.is-skip", ".health-check-icon.is-skip", "color", ("parent", ".card"), 4.5),
    (".health-check-text", ".health-check-text", "color", ("parent", ".card"), 4.5),
    # --- Forms (spec 6.1: "fields never sit directly on the page ground") -
    # .form-label sits inside either a plain .card (Settings) or a .modal
    # (add/edit user); both share --bg-card, so either name reads the same
    # fill.
    (".form-label", ".form-label", "color", ("parent", ".card"), 4.5),
    (".form-input", ".form-input", "color", ("own",), 4.5),
    (".form-input::placeholder", ".form-input::placeholder", "color", ("parent", ".form-input"), 4.5),
    # --- Buttons ------------------------------------------------------------
    (".btn-primary", ".btn-primary", "color", ("own",), 4.5),
    (".btn-secondary", ".btn-secondary", "color", ("own",), 4.5),
    (".btn-danger", ".btn-danger", "color", ("own",), 4.5),
    # --- Modal ----------------------------------------------------------------
    (".modal-title", ".modal-title", "color", ("parent", ".modal"), 4.5),
    (".modal-close", ".modal-close", "color", ("parent", ".modal"), 4.5),
    # --- Login page -----------------------------------------------------------
    (".login-title", ".login-title", "color", ("parent", ".login-card"), 4.5),
    (".login-subtitle", ".login-subtitle", "color", ("parent", ".login-card"), 4.5),
    # --- Toasts: the message text, then the type icon (spec 4.7) ----------
    (".toast", ".toast", "color", ("own",), 4.5),
    (".toast.success .icon", ".toast.success .icon", "color", ("parent", ".toast"), 4.5),
    (".toast.error .icon", ".toast.error .icon", "color", ("parent", ".toast"), 4.5),
    (".toast.info .icon", ".toast.info .icon", "color", ("parent", ".toast"), 4.5),
    # --- Code and logs (spec 6.1: "code chips and log blocks on
    # --bg-secondary, in mono") ---------------------------------------------
    (".code-block", ".code-block", "color", ("own",), 4.5),
    # The location-name chips joinCodeList's <code> elements render as, once
    # scoped by the .code-chip-list wrapper (renderMirrorInventoryCard,
    # releaseRows). Its own solid background, not the ambient card/table one.
    (".code-chip-list code", ".code-chip-list code", "color", ("own",), 4.5),
    (".log-pre", ".log-pre", "color", ("own",), 4.5),
    (".log-pre-error", ".log-pre-error", "color", ("parent", ".log-pre"), 4.5),
    # --- Utilities ------------------------------------------------------------
    (".u-text-muted", ".u-text-muted", "color", ("parent", ".card"), 4.5),
    (".u-text-error", ".u-text-error", "color", ("parent", ".card"), 4.5),
    # --- Disk meter (spec 4.8): UI indicators, not text, so 3:1 against the
    # track (.meter) or the tile (.stat-card), read from `background` rather
    # than `color` -- the same shape the public site's .status-dot and
    # .stream-line::before pairs use. The tick at 85% is proved at the
    # stricter 4.5:1 already, by the shared --text-primary on --bg-card pair
    # above (.stat-card-value), so it gets no --text-primary-on-border-color
    # entry of its own -- only its own selector, at the 3:1 floor that
    # actually applies to it. ------------------------------------------------
    (".meter-fill", ".meter-fill", "background", ("parent", ".meter"), 3.0),
    (".meter-fill.is-warn", ".meter-fill.is-warn", "background", ("parent", ".meter"), 3.0),
    (".meter-fill.is-crit", ".meter-fill.is-crit", "background", ("parent", ".meter"), 3.0),
    (".meter-tick", ".meter-tick", "background", ("parent", ".stat-card"), 3.0),
]
# fmt: on

# The three --border-strong edges spec 9 also calls out (.btn-secondary,
# .form-input, .theme-toggle, all at least 3:1 against --bg-card) are
# deliberately not selector-pinned here: .form-input and .theme-toggle
# declare theirs through the `border: 1px solid var(--border-strong)`
# shorthand, which is not a bare var() in the one property color_hex()
# recognises (declared() would return the whole shorthand value, not just the
# colour). All three already resolve through the shared --border-strong on
# --bg-card pair TOKEN_PAIRS proves in both LIGHT and DARK below, and since
# the admin layer sets no --border-* token of its own, that same proof holds
# for ADMIN_LIGHT/ADMIN_DARK for free -- see compute_admin_checks()'s
# docstring.


def compute_admin_checks(admin_css_text, themes):
    """themes: {label: theme_dict} -- ADMIN_LIGHT and ADMIN_DARK, the two
    states a browser actually renders (data-surface="admin" alone, and
    together with data-theme="dark"). Same shape as compute_public_checks()/
    compute_token_checks(), so a mutation that reruns one reruns all three the
    same way."""
    results = []
    for label, theme in themes.items():
        for check_id, fg_selector, fg_prop, bg_source, min_ratio in ADMIN_PAIRS:
            fg_block = find_block(admin_css_text, fg_selector)
            fg_hex = color_hex(theme, declared(fg_block, fg_prop))

            kind = bg_source[0]
            if kind == "own":
                bg_hex = color_hex(theme, declared_background(fg_block))
            elif kind == "parent":
                bg_block = find_block(admin_css_text, bg_source[1])
                bg_hex = color_hex(theme, declared_background(bg_block))
            else:  # pragma: no cover
                raise AssertionError(f"unknown bg_source kind {kind!r}")

            ratio = contrast_ratio(fg_hex, bg_hex)
            results.append((f"{check_id} [{label}]", ratio, min_ratio, fg_hex, bg_hex))
    return results


ADMIN_CSS_TEXT = ADMIN_CSS.read_text(encoding="utf-8")
ADMIN_CHECKS = compute_admin_checks(ADMIN_CSS_TEXT, {"light": ADMIN_LIGHT, "dark": ADMIN_DARK})
```

  `test_white_on_accent_primary_would_fail_in_dark_and_admin` reads
  `ADMIN_DARK` instead of the retired singular `ADMIN`. Replace:

```python
def test_white_on_accent_primary_would_fail_in_dark_and_admin():
    """White text is not used on a solid --accent-primary fill anywhere any
    more (see --text-on-accent's consumers), but the number itself -- proving
    why -- must still hold, in the new public dark theme as much as in the
    (unchanged) admin one."""
    assert contrast_ratio("#FFFFFF", resolved_hex(DARK, "--accent-primary")) < 4.5
    assert contrast_ratio("#FFFFFF", resolved_hex(ADMIN, "--accent-primary")) < 4.5
```

  with:

```python
def test_white_on_accent_primary_would_fail_in_dark_and_admin():
    """White text is not used on a solid --accent-primary fill anywhere any
    more (see --text-on-accent's consumers), but the number itself -- proving
    why -- must still hold: in the public dark theme, and in the admin
    console's own dark state, which resolves --accent-primary through that
    same shared layer now that the admin surface sets no colour of its own."""
    assert contrast_ratio("#FFFFFF", resolved_hex(DARK, "--accent-primary")) < 4.5
    assert contrast_ratio("#FFFFFF", resolved_hex(ADMIN_DARK, "--accent-primary")) < 4.5
```

  Two `TOKEN_MUTATIONS` entries targeted lines inside the now-deleted LEGACY
  ADMIN block; both move to shared lines that still bite an admin pair, since
  admin.css reads the shared tokens directly now. Replace:

```python
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
```

  with:

```python
    (
        # Targets the shared DARK line, not a LEGACY ADMIN one -- that block
        # is gone, and admin.css now reads this same token (spec section 7),
        # so a mutation here reaches both the public token pair and every
        # admin fill that consumes --text-on-accent.
        "text_on_accent_reverts_to_white",
        "--text-on-accent: var(--c-red-975);",
        "--text-on-accent: #FFFFFF;",
        None,  # asserted separately: this breaks an ADMIN_CHECKS id, checked below
    ),
    (
        # --status-error-text is retired (spec section 7): admin.css now
        # reads --status-error directly for the error badge and
        # .log-pre-error, the same shared token status_error_light_reverts_
        # to_the_dark_shade below already mutates for LIGHT. This targets the
        # DARK line instead, so both mutations stay distinct and each still
        # bites a real, different rendering.
        "status_error_text_reverts_to_status_error",
        "--status-error: var(--c-red-300);",
        "--status-error: var(--c-red-650);",
        None,  # breaks an ADMIN_CHECKS id, checked below
    ),
```

  `test_tokens_css_mutation_is_caught` unpacks four values from
  `build_themes()` now, and passes `compute_admin_checks()` the two-theme
  dict. Replace:

```python
    mutated_text = TOKENS_TEXT.replace(old, new)
    light, dark, admin = build_themes(mutated_text)

    public_results = compute_public_checks(STYLE_CSS_TEXT, {"light": light, "dark": dark})
    token_results = compute_token_checks({"light": light, "dark": dark})
    admin_results = compute_admin_checks(ADMIN_CSS_TEXT, admin)
    failed_ids = {
```

  with:

```python
    mutated_text = TOKENS_TEXT.replace(old, new)
    light, dark, admin_light, admin_dark = build_themes(mutated_text)

    public_results = compute_public_checks(STYLE_CSS_TEXT, {"light": light, "dark": dark})
    token_results = compute_token_checks({"light": light, "dark": dark})
    admin_results = compute_admin_checks(ADMIN_CSS_TEXT, {"light": admin_light, "dark": admin_dark})
    failed_ids = {
```

  The two dedicated tests for those mutations name the specific admin fills
  each must break, now with a theme suffix; `.nav-item.active` and
  `.btn-danger` drop out of the first one, since neither reads
  `--text-on-accent` any more. Replace:

```python
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
```

  with:

```python
def test_text_on_accent_mutation_breaks_an_admin_fill():
    """The two token mutations above that pass must_fail=None still have to
    break *something* concrete -- named here instead of folded into the
    parametrised case so a failure points at a specific, checkable claim
    rather than "some id or other went red". Only .user-avatar and
    .btn-primary read --text-on-accent (admin.css); .nav-item.active reads
    --text-primary and .btn-danger reads --status-error now, so mutating this
    one token no longer touches either of those two."""
    mutated_text = TOKENS_TEXT.replace(
        "--text-on-accent: var(--c-red-975);", "--text-on-accent: #FFFFFF;"
    )
    _, _, _, admin_dark = build_themes(mutated_text)
    results = {
        cid: ratio for cid, ratio, *_ in compute_admin_checks(ADMIN_CSS_TEXT, {"dark": admin_dark})
    }
    assert results[".user-avatar [dark]"] < 4.5
    assert results[".btn-primary [dark]"] < 4.5


def test_status_error_text_mutation_breaks_the_error_badge():
    """--status-error-text is retired; admin.css's error badge and
    .log-pre-error now read --status-error directly (spec section 7), so this
    mutates that shared DARK line -- see the TOKEN_MUTATIONS entry above."""
    mutated_text = TOKENS_TEXT.replace(
        "--status-error: var(--c-red-300);", "--status-error: var(--c-red-650);"
    )
    _, _, _, admin_dark = build_themes(mutated_text)
    results = {
        cid: ratio for cid, ratio, *_ in compute_admin_checks(ADMIN_CSS_TEXT, {"dark": admin_dark})
    }
    assert results[".status-badge.error [dark]"] < 4.5
    assert results[".status-badge.failed [dark]"] < 4.5
    assert results[".log-pre-error [dark]"] < 4.5
```

  Three other dedicated mutation tests destructure `build_themes()` too, and
  only need the extra placeholder added. The same one-line change applies at
  all three call sites (in `test_status_healthy_mutation_breaks_the_pill_the_
  dot_and_both_tokens`, `test_stream_line_mutation_breaks_the_selector_and_
  the_token_pair` and `test_status_syncing_bg_mutation_breaks_the_pill_and_
  its_token_pair`); apply it wherever this exact line appears. Replace:

```python
    light, dark, _ = build_themes(mutated_text)
```

  with:

```python
    light, dark, _, _ = build_themes(mutated_text)
```

  The four admin `CSS_MUTATIONS` entries targeted `--status-error-text`/
  `--status-info-text`, both retired; all four move to a plausible,
  unremarkable muted grey (`#6B7280`, not one of admin.css's own tokens) that
  is below 4.5:1 against every one of the four pill backgrounds it is planted
  into, in both themes, confirmed by hand against `tokens.css`'s resolved
  values. `must_fail` gains a theme suffix, since `compute_admin_checks()`
  now runs both. Replace:

```python
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
```

  with:

```python
    (
        # A component-file edit, not a token edit: reverts just this one
        # rule's `color`, independent of
        # test_status_error_text_mutation_breaks_the_error_badge above (which
        # mutates a shared token instead). Both must be caught; a fix at
        # either layer could otherwise mask a regression at the other.
        # #6B7280 -- a plausible, unremarkable muted grey (the kind of colour
        # left behind by copying the neutral .status-badge rule and
        # forgetting to retint it) -- is not one of admin.css's own tokens, so
        # planting it cannot pass for a reason unrelated to this rule; it is
        # 3.98:1 against --status-error-bg in light and 3.55:1 in dark,
        # confirmed by hand against tokens.css's resolved values, below 4.5:1
        # in both.
        "status_badge_error_reverts_color_to_a_plausible_low_contrast_grey",
        ADMIN_CSS,
        "ADMIN",
        ".status-badge.error {\n    color: var(--status-error);\n"
        "    background: var(--status-error-bg);\n}",
        ".status-badge.error {\n    color: #6B7280;\n" "    background: var(--status-error-bg);\n}",
        ".status-badge.error [light]",
    ),
    (
        # Same shape and the same grey, for the health-checks card's
        # "incomplete" badge: 4.02:1 against --status-incomplete-bg in light,
        # 3.42:1 in dark.
        "status_badge_health_incomplete_reverts_color_to_a_plausible_low_contrast_grey",
        ADMIN_CSS,
        "ADMIN",
        ".status-badge.health-incomplete {\n    color: var(--status-incomplete);\n"
        "    background: var(--status-incomplete-bg);\n}",
        ".status-badge.health-incomplete {\n    color: #6B7280;\n"
        "    background: var(--status-incomplete-bg);\n}",
        ".status-badge.health-incomplete [light]",
    ),
    (
        # Same shape, for the archive-inventory table's informational tag
        # variant (Newest / Latest-in-major / Pre-release) and the job
        # "pending" pill: 4.12:1 against --status-info-bg in light, 3.28:1 in
        # dark.
        "status_badge_info_reverts_color_to_a_plausible_low_contrast_grey",
        ADMIN_CSS,
        "ADMIN",
        ".status-badge.info {\n    color: var(--status-info);\n"
        "    background: var(--status-info-bg);\n}",
        ".status-badge.info {\n    color: #6B7280;\n" "    background: var(--status-info-bg);\n}",
        ".status-badge.info [light]",
    ),
    (
        # Same shape, for the "At risk" pill: 4.28:1 against
        # --status-syncing-bg in light, 3.25:1 in dark.
        "status_badge_at_risk_reverts_color_to_a_plausible_low_contrast_grey",
        ADMIN_CSS,
        "ADMIN",
        ".status-badge.at-risk {\n    color: var(--status-syncing);\n"
        "    background: var(--status-syncing-bg);\n}",
        ".status-badge.at-risk {\n    color: #6B7280;\n"
        "    background: var(--status-syncing-bg);\n}",
        ".status-badge.at-risk [light]",
    ),
]
```

  `test_component_css_mutation_is_caught`'s admin branch passes the two-theme
  dict too. Replace:

```python
    if which == "STYLE":
        results = compute_public_checks(mutated, {"light": LIGHT, "dark": DARK})
    else:
        results = compute_admin_checks(mutated, ADMIN)
```

  with:

```python
    if which == "STYLE":
        results = compute_public_checks(mutated, {"light": LIGHT, "dark": DARK})
    else:
        results = compute_admin_checks(mutated, {"light": ADMIN_LIGHT, "dark": ADMIN_DARK})
```

  `DYNAMIC_ADMIN_CHECKS` becomes a list of `(probe_id, theme_label, min_ratio)`
  tuples, the admin equivalent of `DYNAMIC_PUBLIC_CHECKS`, with three new
  entries for the job-status pill, the disk meter's warning-band fill and the
  theme toggle; `test_admin_panel_contrast_in_a_real_browser` parametrizes
  over the tuple and reads `measured["admin"][theme_label][probe_id]` instead
  of a flat `measured["admin"][probe_id]`. Replace:

```python
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
```

  with:

```python
# (probe_id, theme_label, min_ratio), the admin equivalent of
# DYNAMIC_PUBLIC_CHECKS above: every probe is measured in both
# data-surface="admin" (light) and data-theme="dark" data-surface="admin"
# (dark) -- see contrast_harness.mjs's ADMIN_PROBES and its two-fixture-page
# docstring. The three new entries cover a job-status pill, the disk meter's
# warning-band fill and the theme toggle -- the components spec 6.1 and 4.8
# added that the pre-redesign console never had.
# fmt: off
DYNAMIC_ADMIN_CHECKS = [
    (".login-subtitle", "light", 4.5), (".login-subtitle", "dark", 4.5),
    (".btn-primary", "light", 4.5), (".btn-primary", "dark", 4.5),
    (".nav-item.active", "light", 4.5), (".nav-item.active", "dark", 4.5),
    (".user-avatar", "light", 4.5), (".user-avatar", "dark", 4.5),
    (".user-role", "light", 4.5), (".user-role", "dark", 4.5),
    (".nav-section-title", "light", 4.5), (".nav-section-title", "dark", 4.5),
    (".status-badge.disabled", "light", 4.5), (".status-badge.disabled", "dark", 4.5),
    (".status-badge.active", "light", 4.5), (".status-badge.active", "dark", 4.5),
    ("th", "light", 4.5), ("th", "dark", 4.5),
    (".u-text-muted", "light", 4.5), (".u-text-muted", "dark", 4.5),
    (".status-badge.error", "light", 4.5), (".status-badge.error", "dark", 4.5),
    (".status-badge.syncing", "light", 4.5), (".status-badge.syncing", "dark", 4.5),
    (".status-badge.completed", "light", 4.5), (".status-badge.completed", "dark", 4.5),
    (".theme-toggle", "light", 4.5), (".theme-toggle", "dark", 4.5),
    (".form-input::placeholder", "light", 4.5), (".form-input::placeholder", "dark", 4.5),
    # A UI indicator (WCAG 2.1 SC 1.4.11), not text: 3:1, not 4.5:1.
    (".meter-fill.is-warn", "light", 3.0), (".meter-fill.is-warn", "dark", 3.0),
]
# fmt: on


@requires_browser
@pytest.mark.parametrize(
    "probe_id,theme_label,min_ratio",
    DYNAMIC_ADMIN_CHECKS,
    ids=[f"{p} [{t}]" for p, t, _ in DYNAMIC_ADMIN_CHECKS],
)
def test_admin_panel_contrast_in_a_real_browser(measured, probe_id, theme_label, min_ratio):
    page_bg = resolved_hex(ADMIN_LIGHT if theme_label == "light" else ADMIN_DARK, "--bg-primary")
    measurement = measured["admin"][theme_label][probe_id]
    ratio = _measured_ratio(measurement, page_bg)
    assert ratio >= min_ratio, (
        f"{probe_id} [{theme_label}]: real browser measured {measurement}, "
        f"contrast {ratio:.2f}:1, needs >= {min_ratio}:1"
    )
```

  `test_dynamic_probe_list_matches_the_harness` drops the theme label before
  comparing id sets, since `ADMIN_PROBES` in the harness is one
  theme-independent list run twice, not doubled. Replace:

```python
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
```

  with:

```python
    """The two probe id lists above are a hand-maintained copy of
    PUBLIC_PROBES/ADMIN_PROBES in contrast_harness.mjs. Pins them together the
    same way test_admin_inline_styles.py pins its STYLEHEETS list against
    admin/index.html's actual <link> tags -- so a probe added to one and not
    the other fails loudly here instead of silently measuring nothing.
    ADMIN_PROBES is a single, theme-independent list run once per theme (the
    harness re-measures the same probes against a fresh light and a fresh
    dark fixture page), so its id set is compared against DYNAMIC_ADMIN_CHECKS
    with the theme label dropped, not doubled."""
    harness_source = HARNESS.read_text(encoding="utf-8")
    public_block = re.search(r"const PUBLIC_PROBES = \[(.*?)\n\];", harness_source, re.S)
    admin_block = re.search(r"const ADMIN_PROBES = \[(.*?)\n\];", harness_source, re.S)
    assert public_block and admin_block

    harness_public_ids = set(re.findall(r"id:\s*'([^']+)'", public_block.group(1)))
    harness_admin_ids = set(re.findall(r"id:\s*'([^']+)'", admin_block.group(1)))

    test_public_ids = {p for p, _, _ in DYNAMIC_PUBLIC_CHECKS}
    test_admin_ids = {p for p, _, _ in DYNAMIC_ADMIN_CHECKS} | {".form-input::placeholder"}
```

  Finally, the negative control that plants `color: white` into `.btn-primary`
  reads the harness's per-theme output, checking dark only: white on light's
  `--accent-primary` is 5.63:1 and genuinely passes, the same asymmetry
  `test_white_on_accent_primary_would_fail_in_dark_and_admin` and the public
  `btn_primary_public_reverts_to_white_text` mutation both already only claim
  for `[dark]`. Replace:

```python
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
```

  with:

```python
    The bug lives in admin.css (.btn-primary's `color`), not admin.js -- the
    harness links the real admin.css into its fixture page, so the docroot
    served to it, not the admin.js path, is what needs mutating. Checked in
    dark only: white on light's --accent-primary is 5.63:1 and genuinely
    passes (the same asymmetry test_white_on_accent_primary_would_fail_in_
    dark_and_admin and the public btn_primary_public_reverts_to_white_text
    mutation both already only claim for [dark])."""
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
    ratio = _measured_ratio(
        result["admin"]["dark"][".btn-primary"], resolved_hex(ADMIN_DARK, "--bg-primary")
    )
    assert ratio < 4.5, (
```

- [ ] **Step 4 (developer): rewrite `tests/js/contrast_harness.mjs` to serve
  the admin fixture twice, once per theme, and add three probes.**

  The module docstring's description of the admin fixture. Replace:

```js
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
```

  with:

```js
 *   - the public site, both themes, toggled with a genuine click on
 *     #themeToggle (not by setting the attribute from here) so the real
 *     ThemeManager code path is exercised;
 *   - a synthetic admin fixture: admin.js's own page-renderer functions
 *     (renderLoginPage, renderLayout, renderUsers, renderMirrors,
 *     renderDashboard), loaded into a vm context exactly the way
 *     tests/js/escaping_harness.mjs does, called for their real HTML output,
 *     and dropped into a page that links the real admin.css/tokens.css/
 *     fonts.css. The admin SPA needs a live backend to reach these views by
 *     clicking through the app; calling the renderers directly gets the real
 *     markup without one, the same trade-off escaping_harness.mjs already
 *     makes. The admin console now follows the same saved light/dark choice
 *     as the public site (spec section 6.2), so this same rendered markup is
 *     served twice, as two separate documents each with its own <html
 *     data-surface="admin"> (light) or <html data-theme="dark"
 *     data-surface="admin"> (dark) -- a real navigation to each, not a class
 *     toggle on one shared page, since data-theme is an attribute of <html>
 *     itself.
```

  The renderer loader exports `renderDashboard` too, and the fixture-building
  helper gets a doc-comment update; `buildAdminFixtureHtml` itself keeps
  returning just `{ login, layout }`, since the table and dashboard renders
  are still produced by the caller (`main()`, below) and passed in. Replace:

```js
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
```

  with:

```js
    sandbox.globalThis = sandbox;
    const epilogue = `
;({ html, renderLoginPage, renderLayout, renderUsers, renderMirrors, renderDashboard, state, api });
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
    // table and dashboard renders are produced by the caller and passed in
    // instead.
    return { login, layout };
}

/** One <html>-level page embedding the same five rendered fragments, for a
 * given theme: data-surface="admin" always; data-theme="light"/"dark" set
 * explicitly, exactly as AdminTheme.apply() does in the real console (spec
 * section 6.2) -- tokens.css has no [data-theme="light"] rule, so this
 * matches the light state whether the attribute is set or left off, and
 * setting it explicitly is what a real page after a real toggle click
 * actually carries. */
function buildAdminFixturePage(theme, fragments) {
    const { login, layout, usersHtml, mirrorsHtml, dashboardHtml } = fragments;
    return `<!DOCTYPE html>
<html data-theme="${theme}" data-surface="admin">
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
<div id="dashboard-fixture">${dashboardHtml}</div>
</body>
</html>`;
}

// ---------------------------------------------------------------------------
// Static + synthetic-fixture server
// ---------------------------------------------------------------------------
function serve(fixturePages) {
    return new Promise((resolve) => {
        const server = createServer(async (req, res) => {
            const url = req.url.split('?')[0];
            if (Object.prototype.hasOwnProperty.call(fixturePages, url)) {
                res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
                return res.end(fixturePages[url]);
            }
            let rel = decodeURIComponent(url);
```

  Three new `ADMIN_PROBES` entries: the job-status pill and the meter fill
  come from a new dashboard fixture (below); the toggle from the existing
  layout one. Replace:

```js
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
```

  with:

```js
// Measured once per admin theme (see buildAdminFixturePage() and main()): the
// fixture markup itself does not depend on theme, only which stylesheet
// cascade layer <html>'s data-theme selects. The three job-status/meter/
// toggle entries are what the Reflection redesign added to the console (spec
// sections 4.8 and 6.2); the rest predate it.
const ADMIN_PROBES = [
    { id: '.login-subtitle', selector: '#login-fixture .login-subtitle', bgSelector: '#login-fixture .login-card' },
    { id: '.btn-primary', selector: '#login-fixture .btn-primary', bgSelector: '#login-fixture .btn-primary' },
    { id: '.theme-toggle', selector: '#layout-fixture .theme-toggle', bgSelector: '#layout-fixture .theme-toggle' },
    { id: '.nav-item.active', selector: '#layout-fixture .nav-item.active', bgSelector: '#layout-fixture .nav-item.active' },
    { id: '.user-avatar', selector: '#layout-fixture .user-avatar', bgSelector: '#layout-fixture .user-avatar' },
    { id: '.user-role', selector: '#layout-fixture .user-role', bgSelector: '#layout-fixture .user-info' },
    { id: '.nav-section-title', selector: '#layout-fixture .nav-section-title', bgSelector: '#layout-fixture .sidebar' },
    { id: '.status-badge.disabled', selector: '#users-fixture .status-badge.disabled', bgSelector: '#users-fixture .status-badge.disabled' },
    { id: '.status-badge.active', selector: '#users-fixture .status-badge.active', bgSelector: '#users-fixture .status-badge.active' },
    { id: 'th', selector: '#users-fixture th', bgSelector: '#users-fixture th' },
    { id: '.u-text-muted', selector: '#mirrors-fixture .u-text-muted', bgSelector: '#mirrors-fixture .card' },
    { id: '.status-badge.error', selector: '#mirrors-fixture .status-badge.error', bgSelector: '#mirrors-fixture .status-badge.error' },
    { id: '.status-badge.syncing', selector: '#mirrors-fixture .status-badge.syncing', bgSelector: '#mirrors-fixture .status-badge.syncing' },
    // Recent Sync Jobs' job-status pill (dashboard-fixture is seeded with one
    // completed job, spec 4.8's pill mapping) and the disk meter's own fill,
    // seeded at 91% so it renders in its is-warn band (DISK_USAGE_WARNING_
    // PERCENT/_CRITICAL_PERCENT; the .meter-fill on .meter pairing is a UI
    // indicator, 3:1, not text -- see measureDot()'s reasoning; this one still
    // has real text content, so the plain (element, property) measure() shape
    // fits, unlike .status-dot).
    { id: '.status-badge.completed', selector: '#dashboard-fixture .status-badge.completed', bgSelector: '#dashboard-fixture .status-badge.completed' },
    { id: '.meter-fill.is-warn', selector: '#dashboard-fixture .meter-fill.is-warn', bgSelector: '#dashboard-fixture .meter', dot: true }
];
```

  `main()` builds a dashboard fragment, assembles the two fixture pages from
  the same five fragments, serves both, and measures `ADMIN_PROBES` once per
  theme with a real navigation between them. Replace:

```js
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
```

  with:

```js
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
    // A completed job (the pill probe) and 91% storage (the meter's is-warn
    // band, DISK_USAGE_WARNING_PERCENT/_CRITICAL_PERCENT) in one render.
    const dashboardHtml = await renderWith(mod, mod.renderDashboard, {
        mirrors: { total: 3, active: 2, syncing: 1, error: 0, total_size_bytes: 0 },
        users: { total: 2 },
        storage: { path: '/data/mirrors', total_bytes: 1000, used_bytes: 910, free_bytes: 90, percent_used: 91 },
        recent_syncs: [
            { id: 1, mirror_id: 1, status: 'completed', files_deleted: 0, created_at: new Date().toISOString() }
        ],
        recent_activity: []
    });

    const fragments = { login, layout, usersHtml, mirrorsHtml, dashboardHtml };
    const fixturePages = {
        '/__admin_fixture_light__.html': buildAdminFixturePage('light', fragments),
        '/__admin_fixture_dark__.html': buildAdminFixturePage('dark', fragments)
    };

    const { server, port } = await serve(fixturePages);
    const origin = `http://127.0.0.1:${port}`;
    const { chrome, cdp, sessionId } = await launchChrome();
    const evaluate = makeEvaluate(cdp, sessionId);

    const out = { public: { light: {}, dark: {} }, admin: { light: {}, dark: {} } };
```

  Finally, the admin measurement loop at the end of `main()` runs once per
  theme, with a real navigation and a `data-theme` sanity check before each
  pass. Replace:

```js
    out.public.dark = await measurePublicProbes(cdp, sessionId, evaluate);

    await navigate(cdp, sessionId, `${origin}/__admin_fixture__.html`);
    for (const probe of ADMIN_PROBES) {
        out.admin[probe.id] = await measure(cdp, sessionId, evaluate, probe);
    }
    out.admin['.form-input::placeholder'] = await measurePlaceholder(
        evaluate, '#login-fixture .form-input', '#login-fixture .form-input'
    );

    checkForPageErrors(cdp);
```

  with:

```js
    out.public.dark = await measurePublicProbes(cdp, sessionId, evaluate);

    // The admin console now follows the same saved light/dark choice as the
    // public site (spec section 6.2): each theme's fixture is its own
    // document (data-theme lives on <html>, not on a sub-tree), so every
    // ADMIN_PROBES entry is measured once per real navigation, not once per
    // page. checkForPageErrors() runs once at the end of main(), after both.
    for (const theme of ['light', 'dark']) {
        await navigate(cdp, sessionId, `${origin}/__admin_fixture_${theme}__.html`);
        const admin_theme = await evaluate('document.documentElement.getAttribute("data-theme")');
        if (admin_theme !== theme) {
            throw new Error(`admin fixture (${theme}) did not carry data-theme=${theme} (got ${admin_theme})`);
        }
        for (const probe of ADMIN_PROBES) {
            out.admin[theme][probe.id] = await measureProbe(cdp, sessionId, evaluate, probe);
        }
        out.admin[theme]['.form-input::placeholder'] = await measurePlaceholder(
            evaluate, '#login-fixture .form-input', '#login-fixture .form-input'
        );
    }

    checkForPageErrors(cdp);
```

- [ ] **Step 5 (developer): delete `tests/test_legacy_admin_tokens.py`.** Its
  whole purpose was pinning the LEGACY ADMIN block that this task deletes; the
  admin layer it checked no longer exists.

```bash
git rm tests/test_legacy_admin_tokens.py
```

- [ ] **Step 6 (developer): `admin.css` joins `STYLESHEETS` in
  `tests/test_reduced_motion.py` and `tests/test_focus_ring.py`.** It carries
  four animations now (`spin`, `slideIn`, plus `pill-ring` and `toast-out`
  from the pill and toast rewrites) and needs the same reduced-motion and
  focus-ring coverage the public stylesheets already have.

  In `tests/test_reduced_motion.py`, replace:

```python
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
```

  with:

```python
Scope: style.css (spec sections 4.2-4.4), error.css and admin.css (spec
section 6.1). A sheet needs its own `@media (prefers-reduced-motion: reduce)`
block as soon as it declares any motion at all: a `@keyframes` rule, or any
`transition` or `animation` other than `none`. A colour fade counts -- spec
section 4.4 turns "every animation and transition" off -- so error.css's
theme fade needs the block as much as style.css's sheen does, and admin.css's
four animations (`spin`, `slideIn`, `pill-ring`, `toast-out`) need it as much
as either.

Colour changes must also settle inside the contrast harness's sampling
windows (spec section 4.4): a `color`, `background`, `background-color`,
`border-color`, `fill`, `stroke` or `outline-color` transition runs on
`--transition-fast` or `--transition-base`, never longer. Transforms and
shadows may take longer; the harness never measures them.
"""
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
STYLE_CSS = REPO_ROOT / "frontend" / "public" / "css" / "style.css"
ERROR_CSS = REPO_ROOT / "frontend" / "public" / "css" / "error.css"
ADMIN_CSS = REPO_ROOT / "frontend" / "public" / "admin" / "css" / "admin.css"
STYLESHEETS = [STYLE_CSS, ERROR_CSS, ADMIN_CSS]
```

  and its list-pin test. Replace:

```python
def test_the_checks_cover_style_css_and_error_css():
    """The checks above loop over STYLESHEETS; this pins that list to both
    files, so a typo in it cannot silently shrink every check to one."""
    assert {p.name for p in STYLESHEETS} == {"style.css", "error.css"}
```

  with:

```python
def test_the_checks_cover_style_css_error_css_and_admin_css():
    """The checks above loop over STYLESHEETS; this pins that list to all
    three files, so a typo in it cannot silently shrink every check to
    fewer."""
    assert {p.name for p in STYLESHEETS} == {"style.css", "error.css", "admin.css"}
```

  In `tests/test_focus_ring.py`, replace:

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

  with:

```python
Covers style.css, error.css and admin.css. The error pages load error.css
without style.css (spec section 5.3), so it carries a ring of its own;
admin.css carries its own too (spec section 6.1) rather than loading
style.css, which the admin console never links.
"""
import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
STYLE_CSS = REPO_ROOT / "frontend" / "public" / "css" / "style.css"
ERROR_CSS = REPO_ROOT / "frontend" / "public" / "css" / "error.css"
ADMIN_CSS = REPO_ROOT / "frontend" / "public" / "admin" / "css" / "admin.css"
STYLESHEETS = [STYLE_CSS, ERROR_CSS, ADMIN_CSS]
```

- [ ] **Step 7 (developer): write `tests/test_css_comments.py`, a new
  file.** A `/* ... */` comment ends at its first `*/`. A header comment that
  lists several token globs separated by `/` -- `--bg-*/--text-*` -- plants a
  `*/` of its own partway through the sentence, so a browser closes the
  comment right there instead of where its author meant it to, and drops
  whatever real rule follows next, because it no longer parses as one. Every
  `*/` in `style.css`, `error.css`, `tokens.css` and `admin.css` must be
  followed by whitespace or the end of the file, and no comment may contain a
  `*/` before the one that actually closes it.

```python
"""CSS comment hygiene, across every hand-written stylesheet.

A `/* ... */` comment ends at its *first* `*/`, wherever that falls. A header
comment that lists several token globs separated by `/` -- `--bg-*/--text-*`
-- plants a `*/` of its own in the middle of the sentence, which closes the
comment right there. Everything from that point to the next `*/` a browser
happens to find is no longer a comment at all: it is parsed as CSS, fails to
parse as any rule the language defines, and is dropped -- taking whatever
real rule used to sit just after the intended close with it (see spec
docs/design/2026-09-25-reflection-redesign.md, section 6.1, "Reset").

Every `*/` in these four stylesheets must therefore be followed by
whitespace or nothing (the end of the file), and no comment may contain a
`*/` before the one that actually ends it.
"""
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
STYLE_CSS = REPO_ROOT / "frontend" / "public" / "css" / "style.css"
ERROR_CSS = REPO_ROOT / "frontend" / "public" / "css" / "error.css"
TOKENS_CSS = REPO_ROOT / "frontend" / "public" / "css" / "tokens.css"
ADMIN_CSS = REPO_ROOT / "frontend" / "public" / "admin" / "css" / "admin.css"
STYLESHEETS = [STYLE_CSS, ERROR_CSS, TOKENS_CSS, ADMIN_CSS]

COMMENT_CLOSE_RE = re.compile(r"\*/")
COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)


def comment_closers_not_followed_by_whitespace(css_text):
    """Every `*/` in the text, checked on its own: the character right
    after it must be whitespace, or there must be no character at all (end
    of file). A `*/` glued to whatever comes next -- admin.css's
    `--bg-*/--text-*` shape -- means some earlier, unintended `*/` inside
    what was meant to be one long comment closed it early. Returns a list
    of (line_number, context) pairs, one per offending closer."""
    offenders = []
    for m in COMMENT_CLOSE_RE.finditer(css_text):
        end = m.end()
        following = css_text[end : end + 1]
        if following and not following.isspace():
            line_no = css_text.count("\n", 0, m.start()) + 1
            context = css_text[max(0, m.start() - 24) : end + 12]
            offenders.append((line_no, context))
    return offenders


def stray_closers_after_stripping_well_formed_comments(css_text):
    """The same property, checked from the other direction: remove every
    well-formed `/* ... */` span (non-greedy, so each removal stops at the
    first closer it meets, exactly like a real CSS parser) and see whether
    a `*/` is left over as plain text. One survives only when some comment
    closed earlier than its author intended, stranding a later, real `*/`
    outside any comment at all. Returns the stray closers' offsets into the
    stripped text."""
    stripped = COMMENT_RE.sub("", css_text)
    return [m.start() for m in COMMENT_CLOSE_RE.finditer(stripped)]


def test_every_comment_closer_is_followed_by_whitespace_or_end_of_file():
    offenders = []
    for sheet in STYLESHEETS:
        text = sheet.read_text(encoding="utf-8")
        for line_no, context in comment_closers_not_followed_by_whitespace(text):
            offenders.append(f"{sheet.name}:{line_no}: {context!r}")
    assert offenders == [], (
        "a `*/` is glued directly to whatever follows it, which means some "
        "earlier comment closed before its author meant it to:\n  " + "\n  ".join(offenders)
    )


def test_no_closer_survives_stripping_every_well_formed_comment():
    offenders = [
        sheet.name
        for sheet in STYLESHEETS
        if stray_closers_after_stripping_well_formed_comments(sheet.read_text(encoding="utf-8"))
    ]
    assert offenders == [], (
        "a `*/` remains after every /* ... */ span is stripped out, which means "
        "one comment closed early and left a later `*/` stranded as plain text: "
        + ", ".join(offenders)
    )


def test_the_checks_actually_catch_a_planted_defect():
    """Neither check above has ever been seen failing on real input until
    the fix below made it pass; plant the admin.css shape in miniature --
    a `*/` glued to the text after it, `*/x` -- and confirm both formulations
    catch it, and that neither fires on an ordinary, well-formed comment."""
    planted = "/* token list --a-*/x more words, closed for real */\n.y { color: red; }\n"
    assert comment_closers_not_followed_by_whitespace(
        planted
    ), "the whitespace check let a `*/` glued to following text through"
    assert stray_closers_after_stripping_well_formed_comments(
        planted
    ), "the strip-based check let a `*/` glued to following text through"

    well_formed = "/* a normal, single comment */\n.y { color: red; }\n"
    assert not comment_closers_not_followed_by_whitespace(well_formed)
    assert not stray_closers_after_stripping_well_formed_comments(well_formed)


def test_the_checks_cover_style_css_error_css_tokens_css_and_admin_css():
    """The checks above loop over STYLESHEETS; this pins that list to all
    four files, so a typo in it cannot silently shrink every check to fewer."""
    assert {p.name for p in STYLESHEETS} == {"style.css", "error.css", "tokens.css", "admin.css"}
```

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_css_comments.py; echo "rc=$?"`

  Expected: `rc=1`, `2 failed, 2 passed`, naming `admin.css`'s line 7:

  ```
  AssertionError: a `*/` is glued directly to whatever follows it, which means some earlier comment closed before its author meant it to:
    admin.css:7: 'low is a shared\n   --bg-*/--text-*/--a'
    admin.css:7: 'shared\n   --bg-*/--text-*/--accent-*/-'
    admin.css:7: '-bg-*/--text-*/--accent-*/--border-*/-'
    admin.css:7: 't-*/--accent-*/--border-*/--status-*/-'
    admin.css:7: 't-*/--border-*/--status-*/--stream-* t'
  ```

- [ ] **Step 8 (developer): pin that every icon has a consumer, in
  `tests/test_images.py`.** Two new tests, plus the two file paths they read.
  Replace:

```python
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PUBLIC = REPO_ROOT / "frontend" / "public"
IMG = PUBLIC / "img"
ICONS = IMG / "icons"
SVG_NS = "{http://www.w3.org/2000/svg}"
```

  with:

```python
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PUBLIC = REPO_ROOT / "frontend" / "public"
IMG = PUBLIC / "img"
ICONS = IMG / "icons"
ADMIN_JS = PUBLIC / "admin" / "js" / "admin.js"
INDEX_HTML = PUBLIC / "index.html"
SVG_NS = "{http://www.w3.org/2000/svg}"
```

  and, right after `test_each_icon_is_drawn_with_the_shared_round_stroke`,
  insert the two new tests. Replace:

```python
            assert not overridden, f"{name}.svg: <{element.tag}> sets {sorted(overridden)}"


def test_mark_glyph_is_the_regular_b_and_its_mirror_image():
```

  with:

```python
            assert not overridden, f"{name}.svg: <{element.tag}> sets {sorted(overridden)}"


def test_every_icon_name_has_a_consumer():
    """Every file under img/icons/ must be named by admin.js or index.html
    (spec 4.7's set is exactly what the console and the public page consume,
    no more). Six names -- icon-info, icon-user, icon-edit, icon-trash,
    icon-lock, icon-unlock -- reach the page only through a lookup table
    (getActivityIcon(), Toast.show()): admin.js still writes their class
    string as literal text there ('icon-user', never `icon-${name}`), so a
    plain substring search finds them without executing the file."""
    corpus = ADMIN_JS.read_text(encoding="utf-8") + INDEX_HTML.read_text(encoding="utf-8")
    missing = sorted(name for name in ICON_NAMES if f"icon-{name}" not in corpus)
    assert not missing, f"no admin.js/index.html reference to icon-{{{','.join(missing)}}}"


def test_every_icon_class_named_in_admin_js_or_index_html_is_a_real_icon():
    """The converse of the check above: a class naming a file that does not
    exist under img/icons/ renders an empty mask silently -- a missing
    mask-image paints nothing, not a broken-image glyph, so nobody would
    notice without this. Excludes .icon-btn (index.html): an unrelated,
    pre-existing button class that happens to start with "icon-" too, always
    its own first class token (class="icon-btn ..."), never preceded by a
    separate "icon" class the way every real mask reference (class="icon
    icon-NAME", or a bare 'icon-NAME' lookup-table literal) is."""
    corpus = ADMIN_JS.read_text(encoding="utf-8") + INDEX_HTML.read_text(encoding="utf-8")
    used = {m.group(1) for m in re.finditer(r'(?<!class=")icon-([a-z][a-z-]*)', corpus)}
    unknown = sorted(used - ICON_NAMES)
    assert not unknown, f"icon-NAME(s) with no file under img/icons/: {unknown}"


def test_mark_glyph_is_the_regular_b_and_its_mirror_image():
```

- [ ] **Step 9 (developer): run the four files above, and watch each fail for
  the reason the switch is supposed to fix.** `admin.css` still carries the
  legacy admin colours and no new classes, so every one of these fails
  against it.

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_contrast.py; echo "rc=$?"`

  Expected: `rc=2`, a collection error, not a test failure -- `ADMIN_CHECKS`
  is computed at import time, and the first `ADMIN_PAIRS` entry the old
  `admin.css` cannot satisfy stops the whole module from collecting:

  ```
  AssertionError: no 'color' declaration in block '\n    display: flex;\n    flex-direction: column;\n    align-items: center;\n    justify-content: center;\n    height: 100vh;\n    gap: 16px;\n'
  ```

  (`.loading-screen`, the second `ADMIN_PAIRS` entry, exists but sets no
  `color`.)

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_reduced_motion.py; echo "rc=$?"`

  Expected: `rc=1`, `2 failed, 6 passed`: `test_no_stylesheet_uses_the_all_catch_all`
  finds four `transition: all` declarations in the old `admin.css`, and
  `test_a_sheet_with_any_motion_turns_it_off_under_reduced_motion` finds no
  `@media (prefers-reduced-motion: reduce)` block there at all.

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_focus_ring.py; echo "rc=$?"`

  Expected: `rc=1`, `1 failed, 2 passed`:

  ```
  AssertionError: admin.css has 0 top-level :focus-visible rules, expected 1
  ```

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_images.py; echo "rc=$?"`

  Expected: `rc=1`, `1 failed, 72 passed`. `test_every_icon_class_named_in_
  admin_js_or_index_html_is_a_real_icon` already passes -- the pre-switch
  `admin.js` names only `icon-sun`/`icon-moon`/`icon-copy`/`icon-arrow-right`,
  all real. `test_every_icon_name_has_a_consumer` fails on the 22 names
  nothing yet references:

  ```
  AssertionError: no admin.js/index.html reference to icon-{audit-logs,check,clock,close,dashboard,disk,edit,info,lock,log-out,mirrors,plus,protected-paths,settings,skip,sync,sync-failures,trash,unlock,user,users,warning}
  ```

- [ ] **Step 10 (web-designer): `tokens.css`, six edits inside the header
  comment and the `[data-surface="admin"]` block.** Layers 1-4 (primitives,
  invariants, light, dark) are untouched.

  The layer-list line for layer 5. Replace:

```
   5. ADMIN SURFACE        Frozen ahead of the admin console's own redesign
                           (spec section 6). See the note at that block.
```

  with:

```
   5. ADMIN SURFACE        No colour tokens (spec section 7); one non-colour
                           override for the sidebar's width.
```

  The surfaces diagram and paragraph. Replace:

```
     <html>                                    public site, light
     <html data-theme="dark">                  public site, dark  (theme-init.js, main.js)
     <html data-theme="dark" data-surface="admin">   admin panel

   The admin panel has no theme toggle yet (spec section 6.2 adds one); it is
   dark-only and carries data-theme="dark" statically. Until its own redesign
   (spec section 7) its colours come from the LEGACY ADMIN group in the admin
   layer below, not from this file's dark theme.

   Layers 3-5 all have specificity (0,1,0), so ordering in this file decides:
   dark overrides light, admin overrides dark. Keep them in this order.
```

  with:

```
     <html>                                          public site, light
     <html data-theme="dark">                        public site, dark  (theme-init.js, main.js)
     <html data-surface="admin">                      admin console, light
     <html data-theme="dark" data-surface="admin">    admin console, dark  (js/theme-init.js, admin.js)

   The admin console has its own toggle (spec section 6.2) and follows the
   same saved choice as the public site; data-theme is never static there.
   Its colours come from the shared light and dark layers above, exactly like
   the public site's.

   Layers 3-5 all have specificity (0,1,0), so ordering in this file decides:
   dark overrides light, admin overrides dark. Keep them in this order.
```

  The "Layer 5" sub-section of the header comment. Replace:

```
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
```

  with:

```
   ---------------------------------------------------------------------------
   Layer 5, the admin surface
   ---------------------------------------------------------------------------
   The admin console (spec section 6) takes its colours from layers 3-4
   above, exactly like the public site: [data-surface="admin"] sets no
   --bg-*, --text-*, --accent-*, --border-*, --status-* or --stream-* token
   (spec section 7). It keeps one non-colour override, --sidebar-width,
   documented at that block below.
*/
```

  The INVARIANTS layer's `--sidebar-width` comment. Replace:

```
    /* Layout. --sidebar-width is unchanged until the admin console's own
       redesign (spec section 6), which retunes it to 188px. */
```

  with:

```
    /* Layout. The admin surface below retunes --sidebar-width to 188px
       (spec section 6); this 260px value is what a page with no
       data-surface="admin" attribute would fall back to, which no page
       does today. */
```

  The DARK THEME section banner. Replace:

```
/* ===========================================================================
   4. DARK THEME
   Applied by theme-init.js and main.js on the public site; static on the
   admin panel.
   =========================================================================== */
```

  with:

```
/* ===========================================================================
   4. DARK THEME
   Applied by theme-init.js and main.js on the public site, and by
   js/theme-init.js and admin.js's own toggle on the admin console (spec
   section 6.2) -- one saved 'theme' choice, read by both.
   =========================================================================== */
```

  The `5. ADMIN SURFACE` block itself, banner and body: this is where the
  LEGACY ADMIN group and the non-colour override group both go, leaving one
  declaration. Replace:

```
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

  with:

```
/* ===========================================================================
   5. ADMIN SURFACE
   The admin console (spec section 6) renders from the shared light and dark
   layers above, exactly like the public site. This layer sets no colour
   token at all (spec section 7) -- only the one non-colour override its
   layout needs.
   =========================================================================== */

[data-surface="admin"] {
    /* The console's sidebar is narrower than any public-site layout needs a
       variable for; every colour it uses comes from the shared layers above. */
    --sidebar-width: 188px;
}
```

  This retires `--bg-tertiary`, `--status-error-text` and `--status-info-text`
  (they existed only in the deleted LEGACY ADMIN group); nothing outside
  `admin.css` and the now-deleted legacy-token test read them. `build_themes()`
  still needs exactly 3 `:root` blocks, one `[data-theme="dark"]` block and one
  `[data-surface="admin"]` block. Because the admin block now sets no colour,
  `ADMIN_LIGHT` (light + admin) resolves to exactly `LIGHT`'s colours and
  `ADMIN_DARK` (light + dark + admin) resolves to exactly `DARK`'s.

- [ ] **Step 11 (web-designer): rewrite `admin.css` in full for spec 6.1,**
  using only shared tokens -- no colour literal anywhere, `rgba()` reached
  only through `--shadow-card`, `--shadow-card-hover` and `--scrim`.

```css
/* BSD Mirror Admin Panel - Styles ("Reflection") */
/* Design tokens live in /css/tokens.css, linked ahead of this file in admin/index.html.
   The admin console now follows the same saved light/dark choice as the public
   site (docs/design/2026-09-25-reflection-redesign.md, section 6.2): <html>
   carries data-surface="admin" plus whatever data-theme js/theme-init.js and
   the .theme-toggle button leave it in. Every colour below is a shared
   --bg-*, --text-*, --accent-*, --border-*, --status-*, --stream-* token,
   resolved through tokens.css's light or dark layer -- this file declares no custom
   property and no colour literal of its own, with the one standing exception
   tokens.css documents: rgba() reached only through --shadow-card,
   --shadow-card-hover and --scrim.
   Web fonts are self-hosted in /css/fonts.css, also linked ahead of this file.
   See spec sections 4.1-4.8, 6.1, 6.2 and 9 for the system this file
   implements; tests/test_contrast.py checks the pairs it names in both
   themes. */

/* ===========================================================================
   Reset
   =========================================================================== */
*,
*::before,
*::after {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

html,
body {
    height: 100%;
}

body {
    font-family: var(--font-sans);
    background-color: var(--bg-primary);
    color: var(--text-primary);
    line-height: 1.5;
    transition: background-color var(--transition-fast), color var(--transition-fast);
}

/* ===========================================================================
   Loading screen (index.html's pre-render placeholder)
   =========================================================================== */
.loading-screen {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100vh;
    gap: 16px;
    color: var(--text-secondary);
}

.loading-spinner {
    width: 40px;
    height: 40px;
    border: 3px solid var(--border-color);
    border-top-color: var(--accent-primary);
    border-radius: 50%;
    animation: spin 1s linear infinite;
}

@keyframes spin {
    to {
        transform: rotate(360deg);
    }
}

/* ===========================================================================
   Icons (spec 4.7) -- the .icon longhand copied from css/style.css:72-85.
   admin.css does not load style.css, so it repeats the rule with the same
   absolute /img/icons/ URLs, which resolve against the document, not this
   sheet. admin.css defines the 24 icons the console names: one .icon-NAME
   rule per icon admin.js or admin/index.html actually renders, no more --
   icon-copy and icon-arrow-right are the public site's own, defined only in
   style.css, since nothing in the console ever renders either one.
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

.icon-dashboard {
    -webkit-mask-image: url(/img/icons/dashboard.svg);
    mask-image: url(/img/icons/dashboard.svg);
}

.icon-mirrors {
    -webkit-mask-image: url(/img/icons/mirrors.svg);
    mask-image: url(/img/icons/mirrors.svg);
}

.icon-sync-failures {
    -webkit-mask-image: url(/img/icons/sync-failures.svg);
    mask-image: url(/img/icons/sync-failures.svg);
}

.icon-protected-paths {
    -webkit-mask-image: url(/img/icons/protected-paths.svg);
    mask-image: url(/img/icons/protected-paths.svg);
}

.icon-users {
    -webkit-mask-image: url(/img/icons/users.svg);
    mask-image: url(/img/icons/users.svg);
}

.icon-audit-logs {
    -webkit-mask-image: url(/img/icons/audit-logs.svg);
    mask-image: url(/img/icons/audit-logs.svg);
}

.icon-settings {
    -webkit-mask-image: url(/img/icons/settings.svg);
    mask-image: url(/img/icons/settings.svg);
}

.icon-sun {
    -webkit-mask-image: url(/img/icons/sun.svg);
    mask-image: url(/img/icons/sun.svg);
}

.icon-moon {
    -webkit-mask-image: url(/img/icons/moon.svg);
    mask-image: url(/img/icons/moon.svg);
}

.icon-sync {
    -webkit-mask-image: url(/img/icons/sync.svg);
    mask-image: url(/img/icons/sync.svg);
}

.icon-check {
    -webkit-mask-image: url(/img/icons/check.svg);
    mask-image: url(/img/icons/check.svg);
}

.icon-close {
    -webkit-mask-image: url(/img/icons/close.svg);
    mask-image: url(/img/icons/close.svg);
}

.icon-info {
    -webkit-mask-image: url(/img/icons/info.svg);
    mask-image: url(/img/icons/info.svg);
}

.icon-warning {
    -webkit-mask-image: url(/img/icons/warning.svg);
    mask-image: url(/img/icons/warning.svg);
}

.icon-clock {
    -webkit-mask-image: url(/img/icons/clock.svg);
    mask-image: url(/img/icons/clock.svg);
}

.icon-disk {
    -webkit-mask-image: url(/img/icons/disk.svg);
    mask-image: url(/img/icons/disk.svg);
}

.icon-log-out {
    -webkit-mask-image: url(/img/icons/log-out.svg);
    mask-image: url(/img/icons/log-out.svg);
}

.icon-plus {
    -webkit-mask-image: url(/img/icons/plus.svg);
    mask-image: url(/img/icons/plus.svg);
}

.icon-edit {
    -webkit-mask-image: url(/img/icons/edit.svg);
    mask-image: url(/img/icons/edit.svg);
}

.icon-trash {
    -webkit-mask-image: url(/img/icons/trash.svg);
    mask-image: url(/img/icons/trash.svg);
}

.icon-user {
    -webkit-mask-image: url(/img/icons/user.svg);
    mask-image: url(/img/icons/user.svg);
}

.icon-lock {
    -webkit-mask-image: url(/img/icons/lock.svg);
    mask-image: url(/img/icons/lock.svg);
}

.icon-unlock {
    -webkit-mask-image: url(/img/icons/unlock.svg);
    mask-image: url(/img/icons/unlock.svg);
}

.icon-skip {
    -webkit-mask-image: url(/img/icons/skip.svg);
    mask-image: url(/img/icons/skip.svg);
}

/* ===========================================================================
   The b|d mark (spec 4.5, 6.1) -- two stacked CSS masks, not the public
   page's inline <symbol>/<use> (constraint 2: no <svg> in admin markup).
   .mark-glyph takes --text-primary, .mark-axis takes --accent-primary, sized
   by their .mark parent: 28px in the sidebar, 48px on the login card.
   =========================================================================== */
.mark {
    position: relative;
    display: inline-block;
    flex-shrink: 0;
    width: 28px;
    height: 28px;
}

.mark-glyph,
.mark-axis {
    position: absolute;
    inset: 0;
    display: block;
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
}

.mark-glyph {
    background-color: var(--text-primary);
    -webkit-mask-image: url(/img/mark-glyph.svg);
    mask-image: url(/img/mark-glyph.svg);
}

.mark-axis {
    background-color: var(--accent-primary);
    -webkit-mask-image: url(/img/mark-axis.svg);
    mask-image: url(/img/mark-axis.svg);
}

/* ===========================================================================
   App shell (spec 6.1)
   =========================================================================== */
.app-layout {
    display: grid;
    grid-template-columns: var(--sidebar-width) minmax(0, 1fr);
    min-height: 100vh;
}

.sidebar {
    position: sticky;
    top: 0;
    height: 100vh;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 16px 12px;
    background: var(--bg-card);
    border-right: 1px solid var(--border-color);
}

.sidebar-header {
    padding: 4px 8px 12px;
}

.sidebar-logo {
    display: flex;
    align-items: center;
    gap: 10px;
}

.wordmark {
    font-family: var(--font-display);
    font-size: 15px;
    font-weight: 600;
    letter-spacing: -0.01em;
    color: var(--text-primary);
    white-space: nowrap;
}

.sidebar-nav {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 4px;
}

.nav-section {
    display: flex;
    flex-direction: column;
    gap: 2px;
}

.nav-section + .nav-section {
    margin-top: 12px;
}

.nav-section-title {
    padding: 8px 10px 4px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
}

.nav-item {
    position: relative;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 10px;
    border-radius: var(--radius-md);
    color: var(--text-secondary);
    text-decoration: none;
    font-size: 13.5px;
    font-weight: 500;
    white-space: nowrap;
    transition: background-color var(--transition-fast), color var(--transition-fast);
}

.nav-item:hover {
    background: var(--bg-secondary);
    color: var(--text-primary);
}

.nav-item.active {
    background: var(--bg-secondary);
    color: var(--text-primary);
}

/* Echoes the mark's own axis (spec 6.1): a 3px accent bar flush with the
   sidebar's true left edge, reaching past the nav item's own inset the same
   way the sidebar's own padding (12px) sets it back. */
.nav-item.active::before {
    content: '';
    position: absolute;
    left: -12px;
    top: 6px;
    bottom: 6px;
    width: 3px;
    border-radius: 0 3px 3px 0;
    background: var(--accent-primary);
}

.sidebar-footer {
    margin-top: auto;
    padding-top: 12px;
    border-top: 1px solid var(--border-color);
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.user-info {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px;
    border-radius: var(--radius-md);
    background: var(--bg-secondary);
}

.user-avatar {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    background: var(--accent-primary);
    color: var(--text-on-accent);
    font-weight: 600;
    font-size: 13px;
}

.user-details {
    flex: 1;
    min-width: 0;
}

.user-name {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.user-role {
    font-size: 11.5px;
    color: var(--text-muted);
    text-transform: capitalize;
}

/* ===========================================================================
   Main column and header
   =========================================================================== */
.main-content {
    display: flex;
    flex-direction: column;
    min-height: 100vh;
    min-width: 0;
}

.header {
    height: var(--header-height);
    background: var(--bg-card);
    border-bottom: 1px solid var(--border-color);
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 0 24px;
    position: sticky;
    top: 0;
    z-index: 100;
}

.header-title {
    font-family: var(--font-display);
    font-size: 25px;
    font-weight: 600;
    letter-spacing: -0.02em;
    color: var(--text-primary);
}

.header-actions {
    display: flex;
    align-items: center;
    gap: 12px;
}

.page-content {
    padding: 20px;
}

/* ===========================================================================
   Theme toggle (spec 6.2) -- a square icon button; the icon itself rotates
   on hover, same timing as the public header's (style.css:256-262).
   =========================================================================== */
.theme-toggle {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    padding: 0;
    background: var(--bg-secondary);
    color: var(--text-primary);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-md);
    cursor: pointer;
    transition: background-color var(--transition-fast), border-color var(--transition-fast);
}

.theme-toggle:hover {
    background: var(--bg-card);
}

.theme-toggle .icon {
    transition: transform var(--transition-lift);
}

.theme-toggle:hover .icon {
    transform: rotate(-18deg);
}

/* ===========================================================================
   Cards
   =========================================================================== */
.card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    padding: 20px;
}

.card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 16px;
}

.card-title {
    font-family: var(--font-display);
    font-size: 16px;
    font-weight: 600;
    letter-spacing: -0.01em;
    color: var(--text-primary);
}

/* A subheading one level below .card-title, for a labelled group inside a
   card's body (e.g. the four "Bad (n)" / "Skipped (n)" / "Warnings (n)" /
   "OK (n)" lists on the health-checks card). */
.card-subtitle {
    font-size: 11.5px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    margin: 16px 0 8px;
}

.card-subtitle:first-child {
    margin-top: 0;
}

/* ===========================================================================
   KPI tiles (spec 6.1: "Stat cards become KPI tiles")
   =========================================================================== */
.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 14px;
    margin-bottom: 24px;
}

.stat-card {
    display: flex;
    flex-direction: column;
    gap: 8px;
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    padding: 16px;
    box-shadow: var(--shadow-card);
    transition: transform var(--transition-lift), box-shadow var(--transition-lift);
}

.stat-card:hover {
    transform: translateY(-3px);
    box-shadow: var(--shadow-card-hover);
}

.stat-card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.stat-card-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    border-radius: var(--radius-sm);
    background: var(--bg-secondary);
    color: var(--text-secondary);
}

.stat-card-trend {
    display: inline-flex;
    align-items: center;
    font-size: 11.5px;
    font-weight: 600;
    padding: 3px 8px;
    border-radius: var(--radius-full);
}

.stat-card-trend.up {
    background: var(--status-healthy-bg);
    color: var(--status-healthy);
}

.stat-card-trend.down {
    background: var(--status-error-bg);
    color: var(--status-error);
}

.stat-card-value {
    font-family: var(--font-sans);
    font-size: 27px;
    font-weight: 600;
    letter-spacing: -0.01em;
    color: var(--text-primary);
}

.stat-card-label {
    font-size: 13px;
    color: var(--text-secondary);
}

/* ===========================================================================
   Disk meter (spec 4.8) -- severity is a class on .meter-fill, driven by
   DISK_USAGE_WARNING_PERCENT/DISK_USAGE_CRITICAL_PERCENT; its width comes
   only from the data-percent attribute the 101 rules below key off, never an
   inline style. Track is --border-color; the tick at 85% is --text-primary,
   sized to clear the track on either side so it always shows against the
   card underneath, whatever fill colour is under it.
   =========================================================================== */
.meter {
    position: relative;
    height: 8px;
    margin: 2px 0;
    border-radius: 4px;
    background: var(--border-color);
}

.meter-fill {
    position: absolute;
    inset: 0 auto 0 0;
    height: 100%;
    border-radius: 4px;
    background: var(--text-secondary);
}

.meter-fill.is-warn {
    background: var(--status-syncing);
}

.meter-fill.is-crit {
    background: var(--status-error);
}

.meter-tick {
    position: absolute;
    left: 85%;
    top: -4px;
    bottom: -4px;
    width: 2px;
    margin-left: -1px;
    border-radius: 1px;
    background: var(--text-primary);
}

.meter-fill[data-percent="0"] { width: 0%; }
.meter-fill[data-percent="1"] { width: 1%; }
.meter-fill[data-percent="2"] { width: 2%; }
.meter-fill[data-percent="3"] { width: 3%; }
.meter-fill[data-percent="4"] { width: 4%; }
.meter-fill[data-percent="5"] { width: 5%; }
.meter-fill[data-percent="6"] { width: 6%; }
.meter-fill[data-percent="7"] { width: 7%; }
.meter-fill[data-percent="8"] { width: 8%; }
.meter-fill[data-percent="9"] { width: 9%; }
.meter-fill[data-percent="10"] { width: 10%; }
.meter-fill[data-percent="11"] { width: 11%; }
.meter-fill[data-percent="12"] { width: 12%; }
.meter-fill[data-percent="13"] { width: 13%; }
.meter-fill[data-percent="14"] { width: 14%; }
.meter-fill[data-percent="15"] { width: 15%; }
.meter-fill[data-percent="16"] { width: 16%; }
.meter-fill[data-percent="17"] { width: 17%; }
.meter-fill[data-percent="18"] { width: 18%; }
.meter-fill[data-percent="19"] { width: 19%; }
.meter-fill[data-percent="20"] { width: 20%; }
.meter-fill[data-percent="21"] { width: 21%; }
.meter-fill[data-percent="22"] { width: 22%; }
.meter-fill[data-percent="23"] { width: 23%; }
.meter-fill[data-percent="24"] { width: 24%; }
.meter-fill[data-percent="25"] { width: 25%; }
.meter-fill[data-percent="26"] { width: 26%; }
.meter-fill[data-percent="27"] { width: 27%; }
.meter-fill[data-percent="28"] { width: 28%; }
.meter-fill[data-percent="29"] { width: 29%; }
.meter-fill[data-percent="30"] { width: 30%; }
.meter-fill[data-percent="31"] { width: 31%; }
.meter-fill[data-percent="32"] { width: 32%; }
.meter-fill[data-percent="33"] { width: 33%; }
.meter-fill[data-percent="34"] { width: 34%; }
.meter-fill[data-percent="35"] { width: 35%; }
.meter-fill[data-percent="36"] { width: 36%; }
.meter-fill[data-percent="37"] { width: 37%; }
.meter-fill[data-percent="38"] { width: 38%; }
.meter-fill[data-percent="39"] { width: 39%; }
.meter-fill[data-percent="40"] { width: 40%; }
.meter-fill[data-percent="41"] { width: 41%; }
.meter-fill[data-percent="42"] { width: 42%; }
.meter-fill[data-percent="43"] { width: 43%; }
.meter-fill[data-percent="44"] { width: 44%; }
.meter-fill[data-percent="45"] { width: 45%; }
.meter-fill[data-percent="46"] { width: 46%; }
.meter-fill[data-percent="47"] { width: 47%; }
.meter-fill[data-percent="48"] { width: 48%; }
.meter-fill[data-percent="49"] { width: 49%; }
.meter-fill[data-percent="50"] { width: 50%; }
.meter-fill[data-percent="51"] { width: 51%; }
.meter-fill[data-percent="52"] { width: 52%; }
.meter-fill[data-percent="53"] { width: 53%; }
.meter-fill[data-percent="54"] { width: 54%; }
.meter-fill[data-percent="55"] { width: 55%; }
.meter-fill[data-percent="56"] { width: 56%; }
.meter-fill[data-percent="57"] { width: 57%; }
.meter-fill[data-percent="58"] { width: 58%; }
.meter-fill[data-percent="59"] { width: 59%; }
.meter-fill[data-percent="60"] { width: 60%; }
.meter-fill[data-percent="61"] { width: 61%; }
.meter-fill[data-percent="62"] { width: 62%; }
.meter-fill[data-percent="63"] { width: 63%; }
.meter-fill[data-percent="64"] { width: 64%; }
.meter-fill[data-percent="65"] { width: 65%; }
.meter-fill[data-percent="66"] { width: 66%; }
.meter-fill[data-percent="67"] { width: 67%; }
.meter-fill[data-percent="68"] { width: 68%; }
.meter-fill[data-percent="69"] { width: 69%; }
.meter-fill[data-percent="70"] { width: 70%; }
.meter-fill[data-percent="71"] { width: 71%; }
.meter-fill[data-percent="72"] { width: 72%; }
.meter-fill[data-percent="73"] { width: 73%; }
.meter-fill[data-percent="74"] { width: 74%; }
.meter-fill[data-percent="75"] { width: 75%; }
.meter-fill[data-percent="76"] { width: 76%; }
.meter-fill[data-percent="77"] { width: 77%; }
.meter-fill[data-percent="78"] { width: 78%; }
.meter-fill[data-percent="79"] { width: 79%; }
.meter-fill[data-percent="80"] { width: 80%; }
.meter-fill[data-percent="81"] { width: 81%; }
.meter-fill[data-percent="82"] { width: 82%; }
.meter-fill[data-percent="83"] { width: 83%; }
.meter-fill[data-percent="84"] { width: 84%; }
.meter-fill[data-percent="85"] { width: 85%; }
.meter-fill[data-percent="86"] { width: 86%; }
.meter-fill[data-percent="87"] { width: 87%; }
.meter-fill[data-percent="88"] { width: 88%; }
.meter-fill[data-percent="89"] { width: 89%; }
.meter-fill[data-percent="90"] { width: 90%; }
.meter-fill[data-percent="91"] { width: 91%; }
.meter-fill[data-percent="92"] { width: 92%; }
.meter-fill[data-percent="93"] { width: 93%; }
.meter-fill[data-percent="94"] { width: 94%; }
.meter-fill[data-percent="95"] { width: 95%; }
.meter-fill[data-percent="96"] { width: 96%; }
.meter-fill[data-percent="97"] { width: 97%; }
.meter-fill[data-percent="98"] { width: 98%; }
.meter-fill[data-percent="99"] { width: 99%; }
.meter-fill[data-percent="100"] { width: 100%; }

/* ===========================================================================
   Tables
   =========================================================================== */
.table-container {
    overflow-x: auto;
}

table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13.5px;
}

th,
td {
    text-align: left;
    padding: 10px 14px;
    border-bottom: 1px solid var(--border-color);
}

th {
    font-weight: 600;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-secondary);
    background: var(--bg-secondary);
}

td {
    color: var(--text-primary);
}

tr:hover td {
    background: var(--bg-secondary);
}

/* Sizes, counts, rates and percentages (spec 6.1: "numbers right-aligned in
   mono"); applies to a th just as well as a td. */
.num {
    text-align: right;
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
}

/* ===========================================================================
   Status pills (spec 4.8) -- a dot plus a word, the dot a ::before in
   currentColor so no markup carries a separate span for it. Every modifier
   sets color/background as a bare var() (tests/test_contrast.py's static
   reader only recognises that form). The bare .status-badge is the neutral
   pill (disabled/cancelled/unknown values reuse it exactly).
   =========================================================================== */
.status-badge {
    position: relative;
    display: inline-flex;
    align-items: center;
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

.status-badge::before {
    content: '';
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: currentColor;
    flex-shrink: 0;
}

/* online: mirror active, job completed */
.status-badge.active {
    color: var(--status-healthy);
    background: var(--status-healthy-bg);
}

.status-badge.completed {
    color: var(--status-healthy);
    background: var(--status-healthy-bg);
}

/* syncing: mirror syncing, job running, archive "At risk" */
.status-badge.syncing {
    color: var(--status-syncing);
    background: var(--status-syncing-bg);
}

.status-badge.running {
    color: var(--status-syncing);
    background: var(--status-syncing-bg);
}

.status-badge.at-risk {
    color: var(--status-syncing);
    background: var(--status-syncing-bg);
}

.status-badge.syncing::before,
.status-badge.running::before {
    animation: pill-ring 1.5s cubic-bezier(.2, .8, .2, 1) infinite;
}

@keyframes pill-ring {
    0% { box-shadow: 0 0 0 0 color-mix(in srgb, currentColor 55%, transparent); }
    100% { box-shadow: 0 0 0 7px transparent; }
}

/* error: mirror error, job failed */
.status-badge.error {
    color: var(--status-error);
    background: var(--status-error-bg);
}

.status-badge.failed {
    color: var(--status-error);
    background: var(--status-error-bg);
}

/* info: archive "Current"/"Newest"/"Pre-release", job pending, admin role */
.status-badge.info {
    color: var(--status-info);
    background: var(--status-info-bg);
}

.status-badge.pending {
    color: var(--status-info);
    background: var(--status-info-bg);
}

/* incomplete: health-checks card only (spec 4.8: kept distinct from neutral,
   so it is never mistaken for "Unknown"). */
.status-badge.health-incomplete {
    color: var(--status-incomplete);
    background: var(--status-incomplete-bg);
}

/* neutral: mirror disabled, job cancelled, protection/role "unknown" */
.status-badge.disabled {
    color: var(--text-secondary);
    background: var(--bg-secondary);
}

.status-badge.cancelled {
    color: var(--text-secondary);
    background: var(--bg-secondary);
}

/* ===========================================================================
   Health-checks card (dashboard) -- a lighter row than .activity-item: four
   short lists (bad/skipped/warnings/ok) read as a checklist, so each row's
   own icon just tints to match its list rather than sitting in a filled
   circle.
   =========================================================================== */
.activity-list {
    list-style: none;
}

.activity-item {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 12px 0;
    border-bottom: 1px solid var(--border-color);
}

.activity-item:last-child {
    border-bottom: none;
}

.activity-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: var(--bg-secondary);
    color: var(--text-secondary);
}

.activity-content {
    flex: 1;
    min-width: 0;
}

.activity-text {
    font-size: 13.5px;
    margin-bottom: 4px;
    color: var(--text-primary);
}

.activity-time {
    font-size: 12px;
    color: var(--text-muted);
    font-family: var(--font-mono);
}

.health-check-list {
    list-style: none;
}

.health-check-row {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 6px 0;
    border-bottom: 1px solid var(--border-color);
}

.health-check-row:last-child {
    border-bottom: none;
}

.health-check-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 20px;
    height: 20px;
    margin-top: 1px;
    color: var(--text-secondary);
}

.health-check-icon .icon {
    width: 14px;
    height: 14px;
}

.health-check-icon.is-bad {
    color: var(--status-error);
}

.health-check-icon.is-warn {
    color: var(--status-syncing);
}

.health-check-icon.is-ok {
    color: var(--status-healthy);
}

.health-check-icon.is-skip {
    color: var(--text-muted);
}

.health-check-content {
    flex: 1;
    min-width: 0;
}

.health-check-text {
    font-size: 13.5px;
    line-height: 1.4;
    color: var(--text-primary);
    /* bad[].detail / skipped[].reason / warnings[] are free text from a
       script outside this container and the backend caps them at 500 chars,
       not at a width that fits this card -- wrap rather than push the card
       wider than its .stats-grid siblings on any viewport. */
    overflow-wrap: break-word;
}

/* ===========================================================================
   Forms
   =========================================================================== */
.form-group {
    margin-bottom: 16px;
}

.form-label {
    display: block;
    font-size: 13px;
    font-weight: 600;
    margin-bottom: 6px;
    color: var(--text-secondary);
}

.form-input {
    width: 100%;
    padding: 10px 14px;
    background: var(--bg-secondary);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-md);
    color: var(--text-primary);
    font-family: inherit;
    font-size: 13.5px;
    transition: border-color var(--transition-fast);
}

.form-input:focus {
    border-color: var(--accent-primary);
}

.form-input:disabled {
    opacity: .6;
    cursor: not-allowed;
}

.form-input::placeholder {
    color: var(--text-muted);
}

/* ===========================================================================
   Buttons (spec 6.1)
   =========================================================================== */
.btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 10px 18px;
    border: 1px solid transparent;
    border-radius: var(--radius-md);
    font-family: var(--font-sans);
    font-weight: 600;
    font-size: 13.5px;
    white-space: nowrap;
    text-decoration: none;
    cursor: pointer;
    transition: transform var(--transition-base), box-shadow var(--transition-base),
        background-color var(--transition-fast), border-color var(--transition-fast);
}

.btn:hover {
    transform: translateY(-1px);
}

.btn-primary {
    background: var(--accent-primary);
    color: var(--text-on-accent);
}

.btn-primary:hover {
    box-shadow: var(--shadow-card);
}

.btn-secondary {
    background: var(--bg-card);
    color: var(--text-primary);
    border-color: var(--border-strong);
}

.btn-secondary:hover {
    background: var(--bg-secondary);
}

/* Danger is a tinted pill-like button, not a solid fill (spec 6.1: "Danger:
   --status-error text on --status-error-bg"), matching the alarm colour the
   pills already use rather than inventing a second, solid-fill treatment. */
.btn-danger {
    background: var(--status-error-bg);
    color: var(--status-error);
}

.btn-danger:hover {
    box-shadow: var(--shadow-card);
}

.btn-sm {
    padding: 6px 12px;
    font-size: 12.5px;
}

/* ===========================================================================
   Modal (spec 6.1: "surface, 14px radius, --scrim behind")
   =========================================================================== */
.modal-overlay {
    position: fixed;
    inset: 0;
    padding: 20px;
    background: var(--scrim);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
    opacity: 0;
    visibility: hidden;
    transition: opacity var(--transition-base), visibility var(--transition-base);
}

.modal-overlay.active {
    opacity: 1;
    visibility: visible;
}

.modal {
    background: var(--bg-card);
    border-radius: var(--radius-xl);
    box-shadow: var(--shadow-card-hover);
    width: 100%;
    max-width: 480px;
    max-height: 90vh;
    overflow-y: auto;
    transform: translateY(20px);
    transition: transform var(--transition-base);
}

.modal-overlay.active .modal {
    transform: translateY(0);
}

.modal-header {
    padding: 20px;
    border-bottom: 1px solid var(--border-color);
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
}

.modal-title {
    font-size: 18px;
    font-weight: 600;
    color: var(--text-primary);
}

.modal-close {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    padding: 0;
    background: transparent;
    border: none;
    border-radius: var(--radius-md);
    color: var(--text-secondary);
    cursor: pointer;
    transition: background-color var(--transition-fast), color var(--transition-fast);
}

.modal-close:hover {
    background: var(--bg-secondary);
    color: var(--text-primary);
}

.modal-body {
    padding: 20px;
}

.modal-footer {
    padding: 16px 20px;
    border-top: 1px solid var(--border-color);
    display: flex;
    justify-content: flex-end;
    gap: 12px;
}

/* ===========================================================================
   Login page (spec 6.1: "a centred card with the mark, the wordmark, the
   form and its own theme toggle")
   =========================================================================== */
.login-page {
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--bg-primary);
    padding: 24px;
}

.login-card {
    position: relative;
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-xl);
    box-shadow: var(--shadow-card);
    padding: 40px;
    width: 100%;
    max-width: 400px;
}

.login-card .theme-toggle {
    position: absolute;
    top: 16px;
    right: 16px;
}

.login-header {
    text-align: center;
    margin-bottom: 28px;
}

.login-logo {
    display: flex;
    justify-content: center;
    margin-bottom: 16px;
}

.login-logo .mark {
    width: 48px;
    height: 48px;
}

.login-title {
    font-family: var(--font-display);
    font-size: 22px;
    font-weight: 600;
    letter-spacing: -0.02em;
    color: var(--text-primary);
}

.login-subtitle {
    color: var(--text-secondary);
    margin-top: 8px;
    font-size: 14px;
}

/* ===========================================================================
   Toast notifications -- an icon mask (check/close/info) instead of a
   coloured left border, and its own exit keyframes: a same-name animation
   never replays once it has already finished once, so reversing slideIn in
   place left the exit invisible.
   =========================================================================== */
.toast-container {
    position: fixed;
    top: 24px;
    right: 24px;
    z-index: 2000;
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.toast {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    padding: 12px 16px;
    display: flex;
    align-items: center;
    gap: 12px;
    max-width: 360px;
    font-size: 13.5px;
    font-weight: 500;
    color: var(--text-primary);
    box-shadow: var(--shadow-card-hover);
    animation: slideIn 0.3s ease;
}

@keyframes slideIn {
    from {
        transform: translateX(100%);
        opacity: 0;
    }

    to {
        transform: translateX(0);
        opacity: 1;
    }
}

.toast.is-leaving {
    animation: toast-out 0.3s ease;
}

@keyframes toast-out {
    from {
        transform: translateX(0);
        opacity: 1;
    }

    to {
        transform: translateX(100%);
        opacity: 0;
    }
}

.toast.success .icon {
    color: var(--status-healthy);
}

.toast.error .icon {
    color: var(--status-error);
}

.toast.info .icon {
    color: var(--status-info);
}

/* ===========================================================================
   Code (spec 6.1: "code chips and log blocks on --bg-secondary, in mono")
   =========================================================================== */
code {
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
    font-size: 0.9em;
}

.code-block {
    display: block;
    padding: 8px 10px;
    background: var(--bg-secondary);
    border-radius: var(--radius-sm);
    color: var(--text-primary);
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
    font-size: 12.5px;
    overflow-x: auto;
}

/* Archive-inventory location chips (Protected Paths page): joinCodeList's
   unprotected_locations / protected_not_on_disk names, one <code> per
   location, scoped to the .code-chip-list wrapper so a plain <code> used
   elsewhere in this file is unaffected. Its own solid background, not the
   ambient card/table one, so a chip reads the same neutral "this is just a
   name" way wherever it appears. */
.code-chip-list code {
    display: inline-block;
    background: var(--bg-secondary);
    color: var(--text-muted);
    padding: 2px 8px;
    border-radius: var(--radius-sm);
    white-space: nowrap;
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
}

/* Shared by the error and output panes of the sync-job detail view. They
   differ only in colour and how tall they are allowed to get. */
.log-pre {
    background: var(--bg-secondary);
    padding: 12px;
    border-radius: var(--radius-sm);
    overflow-x: auto;
    overflow-y: auto;
    color: var(--text-primary);
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
    font-size: 12px;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
}

.log-pre-error  { color: var(--status-error); max-height: 150px; }
.log-pre-output { max-height: 400px; }

/* ===========================================================================
   Focus (spec 9: "every interactive element shows a 2px accent outline at a
   2px offset") and reduced motion (spec 4.4).
   =========================================================================== */
:focus-visible {
    outline: 2px solid var(--accent-primary);
    outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        animation: none !important;
        transition: none !important;
    }
}

/* ===========================================================================
   Utilities and small components
   ===========================================================================

   These exist to get the inline style="..." attributes out of admin.js. Every
   declaration below was moved verbatim from the attribute it replaces, so the
   rendered result is unchanged by construction -- this is a mechanical lift,
   not a restyle.

   Why it matters beyond tidiness: the CSP cannot drop `style-src
   'unsafe-inline'` while a single inline style attribute remains, and every
   one of them is a place where a future interpolation could carry attacker
   input into a style context.

   Appended at the end on purpose. A utility and a component class have equal
   specificity, so source order decides, and a utility spelled out at the call
   site should win over the component default it is there to override.

   tests/test_admin_inline_styles.py holds the line: it fails if a class used
   in admin.js markup is not defined here, and if the inline-style count goes
   back up. */

/* --- spacing --------------------------------------------------------- */
.u-mt-sm        { margin-top: 12px; }
.u-mt-md        { margin-top: 14px; }
.u-push-right   { margin-left: auto; }
.u-pad-body     { padding: 0 24px 24px; }

/* --- sizing ---------------------------------------------------------- */
.u-full-width   { width: 100%; }
.u-flex-1       { flex: 1; }

/* --- text ------------------------------------------------------------ */
.u-text-muted   { color: var(--text-muted); }
.u-text-error   { color: var(--status-error); }
.u-text-sm      { font-size: 14px; }

/* --- layout ---------------------------------------------------------- */
.u-row-8        { display: flex; gap: 8px; align-items: center; }
.u-row-12       { display: flex; gap: 12px; }

.u-grid-2       { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.u-grid-2-tight { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px; }

/* ===========================================================================
   Responsive (spec 6.1: "Under 768px" -- the sidebar becomes a horizontal,
   scrollable bar holding the mark, the nav items, then the avatar and Logout
   at its end. Nothing is hidden with no way to reach it: everything that
   does not fit simply scrolls into view.

   Placed after the utilities on purpose: a utility and a media-query rule
   here are equal specificity, so without this position .u-grid-2's 14px
   two-column rule above would win the cascade at every width, including
   under 768px, and this block's own collapse to one column would never take
   effect.
   =========================================================================== */
@media (max-width: 767.98px) {
    .app-layout {
        grid-template-columns: 1fr;
    }

    .header {
        position: static;
    }

    .sidebar {
        height: auto;
        flex-direction: row;
        align-items: center;
        gap: 4px;
        padding: 8px 12px;
        overflow-x: auto;
        overflow-y: hidden;
        border-right: none;
        border-bottom: 1px solid var(--border-color);
    }

    .sidebar-header {
        padding: 4px;
        flex-shrink: 0;
    }

    /* The mark alone stands for the brand in the compact bar; the nav items'
       own labels already make the row wide enough to need horizontal scroll. */
    .sidebar-header .wordmark {
        display: none;
    }

    .sidebar-nav {
        flex-direction: row;
        flex: 0 0 auto;
        gap: 2px;
    }

    .nav-section {
        flex-direction: row;
        gap: 2px;
    }

    .nav-section + .nav-section {
        margin-top: 0;
    }

    .nav-section-title {
        display: none;
    }

    .nav-item.active::before {
        display: none;
    }

    .sidebar-footer {
        flex-direction: row;
        align-items: center;
        flex-shrink: 0;
        margin-top: 0;
        margin-left: auto;
        padding-top: 0;
        padding-left: 8px;
        border-top: none;
    }

    .user-info {
        background: none;
        padding: 0;
    }

    .user-details {
        display: none;
    }

    .u-grid-2,
    .u-grid-2-tight {
        grid-template-columns: 1fr;
    }
}
```

- [ ] **Step 12 (developer): change `admin.js` to emit the new markup.** Every
  replacement below in file order. Class strings are written in full
  throughout -- never `icon-${name}` -- so a class-usage scan can still see
  every literal name.

  The sidebar mark and wordmark. Replace:

```js
                <div class="sidebar-header">
                    <div class="sidebar-logo">
                        <span class="sidebar-logo-icon">🔄</span>
                        <span>BSD Mirror</span>
                    </div>
                </div>
```

  with:

```js
                <div class="sidebar-header">
                    <div class="sidebar-logo">
                        <span class="mark" aria-hidden="true"><span class="mark-glyph"></span><span class="mark-axis"></span></span>
                        <span class="wordmark">BSD Mirror</span>
                    </div>
                </div>
```

  The Dashboard nav item's icon. Replace:

```js
                        <a class="nav-item ${state.currentPage === 'dashboard' ? 'active' : ''}" href="#dashboard" data-nav="dashboard" aria-current="${state.currentPage === 'dashboard' ? 'page' : 'false'}">
                            <span class="nav-item-icon">📊</span>
                            <span>Dashboard</span>
                        </a>
```

  with:

```js
                        <a class="nav-item ${state.currentPage === 'dashboard' ? 'active' : ''}" href="#dashboard" data-nav="dashboard" aria-current="${state.currentPage === 'dashboard' ? 'page' : 'false'}">
                            <span class="icon icon-dashboard" aria-hidden="true"></span>
                            <span>Dashboard</span>
                        </a>
```

  The Mirrors / Sync Failures / Protected Paths / Users nav items. Replace:

```js
                        <a class="nav-item ${state.currentPage === 'mirrors' ? 'active' : ''}" href="#mirrors" data-nav="mirrors" aria-current="${state.currentPage === 'mirrors' ? 'page' : 'false'}">
                            <span class="nav-item-icon">💾</span>
                            <span>Mirrors</span>
                        </a>
                        <a class="nav-item ${state.currentPage === 'sync-failures' ? 'active' : ''}" href="#sync-failures" data-nav="sync-failures" aria-current="${state.currentPage === 'sync-failures' ? 'page' : 'false'}">
                            <span class="nav-item-icon">⚠️</span>
                            <span>Sync Failures</span>
                        </a>
                        <a class="nav-item ${state.currentPage === 'protected-paths' ? 'active' : ''}" href="#protected-paths" data-nav="protected-paths" aria-current="${state.currentPage === 'protected-paths' ? 'page' : 'false'}">
                            <span class="nav-item-icon">🔒</span>
                            <span>Protected Paths</span>
                        </a>
                        ${isAdmin ? html`
                        <a class="nav-item ${state.currentPage === 'users' ? 'active' : ''}" href="#users" data-nav="users" aria-current="${state.currentPage === 'users' ? 'page' : 'false'}">
                            <span class="nav-item-icon">👥</span>
                            <span>Users</span>
                        </a>
                        ` : ''}
```

  with:

```js
                        <a class="nav-item ${state.currentPage === 'mirrors' ? 'active' : ''}" href="#mirrors" data-nav="mirrors" aria-current="${state.currentPage === 'mirrors' ? 'page' : 'false'}">
                            <span class="icon icon-mirrors" aria-hidden="true"></span>
                            <span>Mirrors</span>
                        </a>
                        <a class="nav-item ${state.currentPage === 'sync-failures' ? 'active' : ''}" href="#sync-failures" data-nav="sync-failures" aria-current="${state.currentPage === 'sync-failures' ? 'page' : 'false'}">
                            <span class="icon icon-sync-failures" aria-hidden="true"></span>
                            <span>Sync Failures</span>
                        </a>
                        <a class="nav-item ${state.currentPage === 'protected-paths' ? 'active' : ''}" href="#protected-paths" data-nav="protected-paths" aria-current="${state.currentPage === 'protected-paths' ? 'page' : 'false'}">
                            <span class="icon icon-protected-paths" aria-hidden="true"></span>
                            <span>Protected Paths</span>
                        </a>
                        ${isAdmin ? html`
                        <a class="nav-item ${state.currentPage === 'users' ? 'active' : ''}" href="#users" data-nav="users" aria-current="${state.currentPage === 'users' ? 'page' : 'false'}">
                            <span class="icon icon-users" aria-hidden="true"></span>
                            <span>Users</span>
                        </a>
                        ` : ''}
```

  The Audit Logs / Settings nav items. Replace:

```js
                        <a class="nav-item ${state.currentPage === 'audit-logs' ? 'active' : ''}" href="#audit-logs" data-nav="audit-logs" aria-current="${state.currentPage === 'audit-logs' ? 'page' : 'false'}">
                            <span class="nav-item-icon">📋</span>
                            <span>Audit Logs</span>
                        </a>
                        <a class="nav-item ${state.currentPage === 'settings' ? 'active' : ''}" href="#settings" data-nav="settings" aria-current="${state.currentPage === 'settings' ? 'page' : 'false'}">
                            <span class="nav-item-icon">⚙️</span>
                            <span>Settings</span>
                        </a>
```

  with:

```js
                        <a class="nav-item ${state.currentPage === 'audit-logs' ? 'active' : ''}" href="#audit-logs" data-nav="audit-logs" aria-current="${state.currentPage === 'audit-logs' ? 'page' : 'false'}">
                            <span class="icon icon-audit-logs" aria-hidden="true"></span>
                            <span>Audit Logs</span>
                        </a>
                        <a class="nav-item ${state.currentPage === 'settings' ? 'active' : ''}" href="#settings" data-nav="settings" aria-current="${state.currentPage === 'settings' ? 'page' : 'false'}">
                            <span class="icon icon-settings" aria-hidden="true"></span>
                            <span>Settings</span>
                        </a>
```

  The Logout button. Replace:

```js
                    <button class="btn btn-secondary btn-sm u-full-width u-mt-sm" data-action="logout">
                        Logout
                    </button>
```

  with:

```js
                    <button class="btn btn-secondary btn-sm u-full-width u-mt-sm" data-action="logout">
                        <span class="icon icon-log-out" aria-hidden="true"></span> Logout
                    </button>
```

  `Toast.show`'s glyph. Replace:

```js
        setHtml(toast, html`
            <span>${type === 'success' ? '✓' : type === 'error' ? '✗' : 'ℹ'}</span>
            <span>${message}</span>
        `);
```

  with:

```js
        setHtml(toast, html`
            <span class="${type === 'success' ? 'icon icon-check' : type === 'error' ? 'icon icon-close' : 'icon icon-info'}" aria-hidden="true"></span>
            <span>${message}</span>
        `);
```

  `Modal.show`'s close button. Replace:

```js
                <button class="modal-close" data-action="closeModal">×</button>
```

  with:

```js
                <button class="modal-close" data-action="closeModal" aria-label="Close"><span class="icon icon-close" aria-hidden="true"></span></button>
```

  The login page's mark. Replace:

```js
                <div class="login-header">
                    <div class="login-logo">🔄</div>
                    <h1 class="login-title">BSD Mirror Admin</h1>
```

  with:

```js
                <div class="login-header">
                    <div class="login-logo"><span class="mark" aria-hidden="true"><span class="mark-glyph"></span><span class="mark-axis"></span></span></div>
                    <h1 class="login-title">BSD Mirror Admin</h1>
```

  The disk-meter helper, inserted right before `renderDashboard`. Replace:

```js
async function renderDashboard() {
    try {
        state.data.dashboard = await api.get('/admin/dashboard');
```

  with:

```js
/**
 * The disk-usage meter next to the storage tile's value (spec 4.8). Severity
 * is a class on the fill element, not a computed value: is-crit replaces
 * is-warn at DISK_USAGE_CRITICAL_PERCENT rather than joining it, so this is
 * three full literal branches instead of one template with a class built
 * from a ternary -- every class name it can ever emit stays literal text in
 * this file, the same way the icon spans above do.
 */
function renderMeter(percentUsed) {
    const pct = Math.min(100, Math.max(0, Math.round(percentUsed)));
    if (pct >= DISK_USAGE_CRITICAL_PERCENT) {
        return html`
        <div class="meter" aria-hidden="true">
            <div class="meter-fill is-crit" data-percent="${pct}"></div>
            <div class="meter-tick"></div>
        </div>
        `;
    }
    if (pct >= DISK_USAGE_WARNING_PERCENT) {
        return html`
        <div class="meter" aria-hidden="true">
            <div class="meter-fill is-warn" data-percent="${pct}"></div>
            <div class="meter-tick"></div>
        </div>
        `;
    }
    return html`
    <div class="meter" aria-hidden="true">
        <div class="meter-fill" data-percent="${pct}"></div>
        <div class="meter-tick"></div>
    </div>
    `;
}

async function renderDashboard() {
    try {
        state.data.dashboard = await api.get('/admin/dashboard');
```

  The dashboard's five KPI tiles, plus the meter call. Replace:

```js
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-card-header">
                    <span class="stat-card-icon">💾</span>
                </div>
                <div class="stat-card-value">${d.mirrors.total}</div>
                <div class="stat-card-label">Total Mirrors</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-card-header">
                    <span class="stat-card-icon">✅</span>
                </div>
                <div class="stat-card-value">${d.mirrors.active}</div>
                <div class="stat-card-label">Active Mirrors</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-card-header">
                    <span class="stat-card-icon">🔄</span>
                </div>
                <div class="stat-card-value">${d.mirrors.syncing}</div>
                <div class="stat-card-label">Currently Syncing</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-card-header">
                    <span class="stat-card-icon">👥</span>
                </div>
                <div class="stat-card-value">${d.users.total}</div>
                <div class="stat-card-label">Admin Users</div>
            </div>

            <div class="stat-card">
                <div class="stat-card-header">
                    <span class="stat-card-icon">🗄️</span>
                    ${d.storage.percent_used != null ? html`
                    <span class="stat-card-trend ${d.storage.percent_used >= DISK_USAGE_WARNING_PERCENT ? 'down' : 'up'}">${d.storage.percent_used}% used</span>
                    ` : ''}
                </div>
                <div class="stat-card-value">${d.storage.free_bytes != null ? formatBytes(d.storage.free_bytes) : 'Unknown'}</div>
                <div class="stat-card-label">
                    ${d.storage.total_bytes != null
                        ? html`Disk free of ${formatBytes(d.storage.total_bytes)} (${formatBytes(d.storage.used_bytes)} used)`
                        : 'Disk capacity unavailable'}
                </div>
            </div>
        </div>
```

  with:

```js
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-card-header">
                    <span class="stat-card-icon"><span class="icon icon-mirrors" aria-hidden="true"></span></span>
                </div>
                <div class="stat-card-value">${d.mirrors.total}</div>
                <div class="stat-card-label">Total Mirrors</div>
            </div>

            <div class="stat-card">
                <div class="stat-card-header">
                    <span class="stat-card-icon"><span class="icon icon-check" aria-hidden="true"></span></span>
                </div>
                <div class="stat-card-value">${d.mirrors.active}</div>
                <div class="stat-card-label">Active Mirrors</div>
            </div>

            <div class="stat-card">
                <div class="stat-card-header">
                    <span class="stat-card-icon"><span class="icon icon-sync" aria-hidden="true"></span></span>
                </div>
                <div class="stat-card-value">${d.mirrors.syncing}</div>
                <div class="stat-card-label">Currently Syncing</div>
            </div>

            <div class="stat-card">
                <div class="stat-card-header">
                    <span class="stat-card-icon"><span class="icon icon-users" aria-hidden="true"></span></span>
                </div>
                <div class="stat-card-value">${d.users.total}</div>
                <div class="stat-card-label">Admin Users</div>
            </div>

            <div class="stat-card">
                <div class="stat-card-header">
                    <span class="stat-card-icon"><span class="icon icon-disk" aria-hidden="true"></span></span>
                    ${d.storage.percent_used != null ? html`
                    <span class="stat-card-trend ${d.storage.percent_used >= DISK_USAGE_WARNING_PERCENT ? 'down' : 'up'}">${d.storage.percent_used}% used</span>
                    ` : ''}
                </div>
                <div class="stat-card-value">${d.storage.free_bytes != null ? formatBytes(d.storage.free_bytes) : 'Unknown'}</div>
                ${d.storage.percent_used != null ? renderMeter(d.storage.percent_used) : ''}
                <div class="stat-card-label">
                    ${d.storage.total_bytes != null
                        ? html`Disk free of ${formatBytes(d.storage.total_bytes)} (${formatBytes(d.storage.used_bytes)} used)`
                        : 'Disk capacity unavailable'}
                </div>
            </div>
        </div>
```

  The Recent Sync Jobs row. Replace:

```js
                    ${d.recent_syncs.length ? d.recent_syncs.map(sync => html`
                        <li class="activity-item">
                            <div class="activity-icon">🔄</div>
                            <div class="activity-content">
                                <div class="activity-text">
                                    Mirror #${sync.mirror_id} -
                                    <span class="status-badge ${sync.status}">${sync.status}</span>
                                    ${sync.files_deleted ? filesDeletedBadge(sync.files_deleted) : ''}
                                </div>
                                <div class="activity-time">${formatDate(sync.created_at)}</div>
                            </div>
                        </li>
                    `) : html`<li class="activity-item"><div class="activity-content">No recent sync jobs</div></li>`}
```

  with:

```js
                    ${d.recent_syncs.length ? d.recent_syncs.map(sync => html`
                        <li class="activity-item">
                            <span class="status-badge ${sync.status}">${sync.status}</span>
                            <div class="activity-content">
                                <div class="activity-text">
                                    Mirror #${sync.mirror_id}
                                    ${sync.files_deleted ? filesDeletedBadge(sync.files_deleted) : ''}
                                </div>
                                <div class="activity-time">${formatDate(sync.created_at)}</div>
                            </div>
                        </li>
                    `) : html`<li class="activity-item"><div class="activity-content">No recent sync jobs</div></li>`}
```

  The Recent Activity row. Replace:

```js
                    ${d.recent_activity.length ? d.recent_activity.map(log => html`
                        <li class="activity-item">
                            <div class="activity-icon">${getActivityIcon(log.action)}</div>
```

  with:

```js
                    ${d.recent_activity.length ? d.recent_activity.map(log => html`
                        <li class="activity-item">
                            <div class="activity-icon"><span class="icon ${getActivityIcon(log.action)}" aria-hidden="true"></span></div>
```

  `healthChecklistSection`'s doc comment and body -- `icon` becomes a
  pre-built fragment instead of a bare glyph. Replace:

```js
 * One of the four lists on the card: a heading with a count, then either the
 * items (via `renderItem`, which may return a plain string or a nested
 * html`` fragment -- both are escaped the same way by the outer template)
 * or a placeholder `<li>` when there are none, matching the empty-state
 * shape Recent Sync Jobs / Recent Activity above already use.
 */
function healthChecklistSection(title, items, emptyLabel, icon, renderItem) {
    return html`
        <h4 class="card-subtitle">${title} (${items.length})</h4>
        <ul class="health-check-list">
            ${items.length ? items.map(item => html`
                <li class="health-check-row">
                    <div class="health-check-icon">${icon}</div>
                    <div class="health-check-content">
                        <div class="health-check-text">${renderItem(item)}</div>
                    </div>
                </li>
            `) : html`<li class="health-check-row"><div class="health-check-content">${emptyLabel}</div></li>`}
        </ul>
    `;
}
```

  with:

```js
 * One of the four lists on the card: a heading with a count, then either the
 * items (via `renderItem`, which may return a plain string or a nested
 * html`` fragment -- both are escaped the same way by the outer template)
 * or a placeholder `<li>` when there are none, matching the empty-state
 * shape Recent Sync Jobs / Recent Activity above already use. `icon` is a
 * pre-built html`` fragment (the state-specific health-check-icon span), not
 * a bare icon name, so each of the four calls below can give its own list a
 * different literal modifier and icon.
 */
function healthChecklistSection(title, items, emptyLabel, icon, renderItem) {
    return html`
        <h4 class="card-subtitle">${title} (${items.length})</h4>
        <ul class="health-check-list">
            ${items.length ? items.map(item => html`
                <li class="health-check-row">
                    ${icon}
                    <div class="health-check-content">
                        <div class="health-check-text">${renderItem(item)}</div>
                    </div>
                </li>
            `) : html`<li class="health-check-row"><div class="health-check-content">${emptyLabel}</div></li>`}
        </ul>
    `;
}
```

  The health card's last-ran line and its four list calls. Replace:

```js
            <p class="u-text-muted u-text-sm u-mt-sm">
                ${h.finished_at
                    ? html`Last ran ${formatDate(h.finished_at)}${age ? html` (${age})` : ''}`
                    : 'Last run: unknown'}
            </p>
            <div class="u-mt-sm">
                ${healthChecklistSection('Bad', h.bad || [], 'No failing checks', '❌',
                    (item) => `${item.label}: ${item.detail}`)}
                ${healthChecklistSection('Skipped', h.skipped || [], 'No skipped checks', '⏭️',
                    (item) => `${item.check}: ${item.reason}`)}
                ${healthChecklistSection('Warnings', h.warnings || [], 'No warnings', '⚠️',
                    (item) => item)}
                ${healthChecklistSection('OK', h.ok || [], 'No checks reported ok', '✅',
                    (item) => item)}
            </div>
```

  with:

```js
            <p class="u-text-muted u-text-sm u-mt-sm">
                <span class="icon icon-clock" aria-hidden="true"></span>
                ${h.finished_at
                    ? html`Last ran ${formatDate(h.finished_at)}${age ? html` (${age})` : ''}`
                    : 'Last run: unknown'}
            </p>
            <div class="u-mt-sm">
                ${healthChecklistSection('Bad', h.bad || [], 'No failing checks',
                    html`<span class="health-check-icon is-bad"><span class="icon icon-close" aria-hidden="true"></span></span>`,
                    (item) => `${item.label}: ${item.detail}`)}
                ${healthChecklistSection('Skipped', h.skipped || [], 'No skipped checks',
                    html`<span class="health-check-icon is-skip"><span class="icon icon-skip" aria-hidden="true"></span></span>`,
                    (item) => `${item.check}: ${item.reason}`)}
                ${healthChecklistSection('Warnings', h.warnings || [], 'No warnings',
                    html`<span class="health-check-icon is-warn"><span class="icon icon-warning" aria-hidden="true"></span></span>`,
                    (item) => item)}
                ${healthChecklistSection('OK', h.ok || [], 'No checks reported ok',
                    html`<span class="health-check-icon is-ok"><span class="icon icon-check" aria-hidden="true"></span></span>`,
                    (item) => item)}
            </div>
```

  The mirrors table's header (Size and Last Sync become numeric, spec 4.2).
  Replace:

```js
                        <tr>
                            <th>Name</th>
                            <th>Status</th>
                            <th>Size</th>
                            <th>Last Sync</th>
                            <th>Actions</th>
                        </tr>
```

  with:

```js
                        <tr>
                            <th>Name</th>
                            <th>Status</th>
                            <th class="num">Size</th>
                            <th class="num">Last Sync</th>
                            <th>Actions</th>
                        </tr>
```

  The mirrors table's status badge (drop `status-dot`) and Size and Last
  Sync cells. Replace:

```js
                                <td>
                                    <span class="status-badge ${mirror.status}">
                                        <span class="status-dot"></span>
                                        ${mirror.status}
                                    </span>
                                </td>
                                <td>${mirror.total_size_human || '--'}</td>
                                <td>${mirror.last_sync_completed ? formatDate(mirror.last_sync_completed) : 'Never'}</td>
```

  with:

```js
                                <td>
                                    <span class="status-badge ${mirror.status}">${mirror.status}</span>
                                </td>
                                <td class="num">${mirror.total_size_human || '--'}</td>
                                <td class="num">${mirror.last_sync_completed ? formatDate(mirror.last_sync_completed) : 'Never'}</td>
```

  The Sync Failures page's two tiles. Replace:

```js
            <div class="stat-card">
                <div class="stat-card-header">
                    <span class="stat-card-icon">❌</span>
                </div>
                <div class="stat-card-value">${d.totals.failed}</div>
                <div class="stat-card-label">Failed (last ${d.period_days}d)</div>
            </div>
            <div class="stat-card">
                <div class="stat-card-header">
                    <span class="stat-card-icon">✅</span>
                </div>
                <div class="stat-card-value">${d.totals.completed}</div>
                <div class="stat-card-label">Completed (last ${d.period_days}d)</div>
            </div>
```

  with:

```js
            <div class="stat-card">
                <div class="stat-card-header">
                    <span class="stat-card-icon"><span class="icon icon-close" aria-hidden="true"></span></span>
                </div>
                <div class="stat-card-value">${d.totals.failed}</div>
                <div class="stat-card-label">Failed (last ${d.period_days}d)</div>
            </div>
            <div class="stat-card">
                <div class="stat-card-header">
                    <span class="stat-card-icon"><span class="icon icon-check" aria-hidden="true"></span></span>
                </div>
                <div class="stat-card-value">${d.totals.completed}</div>
                <div class="stat-card-label">Completed (last ${d.period_days}d)</div>
            </div>
```

  The Failures by Mirror table's header and Failed/Completed/Failure Rate
  cells. Replace:

```js
                        <tr>
                            <th>Mirror</th>
                            <th>Failed</th>
                            <th>Completed</th>
                            <th>Failure Rate</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${d.by_mirror.map(m => html`
                            <tr>
                                <td><strong>${m.mirror_name}</strong></td>
                                <td class="${m.failed > 0 ? 'u-text-error' : ''}">${m.failed}</td>
                                <td>${m.completed}</td>
                                <td>${m.failure_rate_percent != null ? m.failure_rate_percent + '%' : '--'}</td>
```

  with:

```js
                        <tr>
                            <th>Mirror</th>
                            <th class="num">Failed</th>
                            <th class="num">Completed</th>
                            <th class="num">Failure Rate</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${d.by_mirror.map(m => html`
                            <tr>
                                <td><strong>${m.mirror_name}</strong></td>
                                <td class="num ${m.failed > 0 ? 'u-text-error' : ''}">${m.failed}</td>
                                <td class="num">${m.completed}</td>
                                <td class="num">${m.failure_rate_percent != null ? m.failure_rate_percent + '%' : '--'}</td>
```

  The Recent Failure Incidents table's header and Occurrences, First Seen
  and Last Seen cells (spec 4.2: times join sizes and counts in mono).
  Replace:

```js
                        <tr>
                            <th>Mirror</th>
                            <th>Error</th>
                            <th>Occurrences</th>
                            <th>First Seen</th>
                            <th>Last Seen</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${d.incidents.length ? d.incidents.map(inc => html`
                            <tr>
                                <td><strong>${inc.mirror_name}</strong></td>
                                <td><code class="code-block">${inc.error_message || '(no error message recorded)'}</code></td>
                                <td>${inc.occurrences.toLocaleString()}</td>
                                <td>${formatDate(inc.first_seen)}</td>
                                <td>${formatDate(inc.last_seen)}</td>
```

  with:

```js
                        <tr>
                            <th>Mirror</th>
                            <th>Error</th>
                            <th class="num">Occurrences</th>
                            <th class="num">First Seen</th>
                            <th class="num">Last Seen</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${d.incidents.length ? d.incidents.map(inc => html`
                            <tr>
                                <td><strong>${inc.mirror_name}</strong></td>
                                <td><code class="code-block">${inc.error_message || '(no error message recorded)'}</code></td>
                                <td class="num">${inc.occurrences.toLocaleString()}</td>
                                <td class="num">${formatDate(inc.first_seen)}</td>
                                <td class="num">${formatDate(inc.last_seen)}</td>
```

  `PROTECTION_BADGE_CLASS`'s `unknown` mapping moves off the error tint (spec
  4.8, "unknown values"). Replace:

```js
const PROTECTION_BADGE_CLASS = {
    full: 'active',
    partial: 'syncing',
    none: 'disabled',
    unknown: 'error',
};
```

  with:

```js
const PROTECTION_BADGE_CLASS = {
    full: 'active',
    partial: 'syncing',
    none: 'disabled',
    unknown: 'disabled',
};
```

  The "At risk" release tag's emoji. Replace:

```js
    if (release.at_risk) {
        tags.push(html`<span class="status-badge at-risk">⚠️ At risk</span>`);
    }
```

  with:

```js
    if (release.at_risk) {
        tags.push(html`<span class="status-badge at-risk">At risk</span>`);
    }
```

  The archive-inventory row's Locations and Last Changed cells (spec 4.2:
  times join sizes and counts in mono). Replace:

```js
            <td><span class="u-row-8">${releaseTagBadges(release)}</span></td>
            <td>${release.location_count.toLocaleString()}</td>
            <td>${formatDate(release.modified)}</td>
```

  with:

```js
            <td><span class="u-row-8">${releaseTagBadges(release)}</span></td>
            <td class="num">${release.location_count.toLocaleString()}</td>
            <td class="num">${formatDate(release.modified)}</td>
```

  The archive-inventory table's header (Locations and Last Changed become
  numeric). Replace:

```js
                <thead>
                    <tr>
                        <th>Version</th>
                        <th>Protection</th>
                        <th>Tags</th>
                        <th>Locations</th>
                        <th>Last Changed</th>
                    </tr>
                </thead>
```

  with:

```js
                <thead>
                    <tr>
                        <th>Version</th>
                        <th>Protection</th>
                        <th>Tags</th>
                        <th class="num">Locations</th>
                        <th class="num">Last Changed</th>
                    </tr>
                </thead>
```

  The Add User button. Replace:

```js
                <button class="btn btn-primary btn-sm" data-action="showAddUser">
                    + Add User
                </button>
```

  with:

```js
                <button class="btn btn-primary btn-sm" data-action="showAddUser">
                    <span class="icon icon-plus" aria-hidden="true"></span> Add User
                </button>
```

  The Users table's header (Last Login becomes numeric, spec 4.2). Replace:

```js
                        <tr>
                            <th>Username</th>
                            <th>Email</th>
                            <th>Role</th>
                            <th>Status</th>
                            <th>Last Login</th>
                            <th>Actions</th>
                        </tr>
```

  with:

```js
                        <tr>
                            <th>Username</th>
                            <th>Email</th>
                            <th>Role</th>
                            <th>Status</th>
                            <th class="num">Last Login</th>
                            <th>Actions</th>
                        </tr>
```

  The Users table's role pill (admin becomes `info`, spec 4.8). Replace:

```js
                                <td>
                                    <span class="status-badge ${user.role === 'admin' ? 'active' : ''}">${user.role}</span>
                                </td>
```

  with:

```js
                                <td>
                                    <span class="status-badge ${user.role === 'admin' ? 'info' : ''}">${user.role}</span>
                                </td>
```

  The Users table's Last Login cell (spec 4.2). Replace:

```js
                                <td>${user.last_login ? formatDate(user.last_login) : 'Never'}</td>
```

  with:

```js
                                <td class="num">${user.last_login ? formatDate(user.last_login) : 'Never'}</td>
```

  The Audit Logs table's header (Time becomes numeric, spec 4.2). Replace:

```js
                        <tr>
                            <th>Time</th>
                            <th>User</th>
                            <th>Action</th>
                            <th>Resource</th>
                            <th>IP Address</th>
                        </tr>
```

  with:

```js
                        <tr>
                            <th class="num">Time</th>
                            <th>User</th>
                            <th>Action</th>
                            <th>Resource</th>
                            <th>IP Address</th>
                        </tr>
```

  The Audit Logs table's Time cell. Replace:

```js
                                <td>${formatDate(log.created_at)}</td>
                                <td>${log.username || 'System'}</td>
```

  with:

```js
                                <td class="num">${formatDate(log.created_at)}</td>
                                <td>${log.username || 'System'}</td>
```

  The Settings Info table's header (Last Updated becomes numeric, spec 4.2).
  Replace:

```js
                        <tr>
                            <th>Key</th>
                            <th>Last Updated</th>
                        </tr>
```

  with:

```js
                        <tr>
                            <th>Key</th>
                            <th class="num">Last Updated</th>
                        </tr>
```

  The Settings Info table's Last Updated cell. Replace:

```js
                                <td><code>${s.key}</code></td>
                                <td>${formatDate(s.updated_at)}</td>
```

  with:

```js
                                <td><code>${s.key}</code></td>
                                <td class="num">${formatDate(s.updated_at)}</td>
```

  `viewMirror`'s history row: the pill replaces the emoji, and the bare
  status word leaves `.activity-text` now that the pill already carries it.
  Replace:

```js
                        ${history.length ? history.map(h => html`
                            <li class="activity-item">
                                <div class="activity-icon">${h.status === 'completed' ? '✅' : h.status === 'failed' ? '❌' : h.status === 'running' ? '🔄' : '⏳'}</div>
                                <div class="activity-content">
                                    <div class="activity-text">
                                        ${h.status}${h.bytes_transferred ? ' - ' + formatBytes(h.bytes_transferred) : ''}
                                        ${h.files_deleted ? html` ${filesDeletedBadge(h.files_deleted)}` : ''}
```

  with:

```js
                        ${history.length ? history.map(h => html`
                            <li class="activity-item">
                                <span class="status-badge ${h.status}">${h.status}</span>
                                <div class="activity-content">
                                    <div class="activity-text">
                                        ${h.bytes_transferred ? formatBytes(h.bytes_transferred) : ''}
                                        ${h.files_deleted ? html` ${filesDeletedBadge(h.files_deleted)}` : ''}
```

  `viewSyncLogs`'s title drops the emoji prefix (the facts grid's `Status`
  pill was already correct and needed no change). Replace:

```js
            const job = await api.get(`/admin/sync-jobs/${jobId}/logs`);
            const statusIcon = job.status === 'completed' ? '✅' : job.status === 'failed' ? '❌' : job.status === 'running' ? '🔄' : '⏳';
            const isRunning = job.status === 'running' || job.status === 'pending';

            Modal.show(`${statusIcon} Sync Job #${job.id}`, html`
```

  with:

```js
            const job = await api.get(`/admin/sync-jobs/${jobId}/logs`);
            const isRunning = job.status === 'running' || job.status === 'pending';

            Modal.show(`Sync Job #${job.id}`, html`
```

  `filesDeletedBadge`: the large-deletion badge gets an icon span; the muted
  variant keeps plain text. Replace:

```js
function filesDeletedBadge(count) {
    const large = count >= LARGE_DELETION_THRESHOLD;
    return html`<span class="${large ? 'u-text-error' : 'u-text-muted'}">${large ? '⚠️ ' : ''}${count.toLocaleString()} deleted</span>`;
}
```

  with:

```js
function filesDeletedBadge(count) {
    const large = count >= LARGE_DELETION_THRESHOLD;
    return large
        ? html`<span class="u-text-error"><span class="icon icon-warning" aria-hidden="true"></span> ${count.toLocaleString()} deleted</span>`
        : html`<span class="u-text-muted">${count.toLocaleString()} deleted</span>`;
}
```

  `getActivityIcon` returns full `icon-NAME` class strings, never
  `` icon-${name} ``. Replace:

```js
function getActivityIcon(action) {
    const icons = {
        'login_success': '🔓',
        'login_failed': '🔒',
        'logout': '👋',
        'user_created': '👤',
        'user_updated': '✏️',
        'user_deleted': '🗑️',
        'mirror_updated': '💾',
        'sync_triggered': '🔄',
        'settings_updated': '⚙️'
    };
    return icons[action] || '📋';
}
```

  with:

```js
function getActivityIcon(action) {
    const icons = {
        'login_success': 'icon-unlock',
        'login_failed': 'icon-lock',
        'logout': 'icon-log-out',
        'user_created': 'icon-user',
        'user_updated': 'icon-edit',
        'user_deleted': 'icon-trash',
        'mirror_updated': 'icon-mirrors',
        'sync_triggered': 'icon-sync',
        'settings_updated': 'icon-settings'
    };
    return icons[action] || 'icon-audit-logs';
}
```

  A source scan for anything left behind confirms the sweep is complete:
  every remaining code point above U+2000 in `admin.js` is one of the two
  pre-existing em dashes in prose comments, and `status-dot`, `nav-item-icon`,
  `sidebar-logo-icon` and the literal `×` no longer appear anywhere in the
  file.

- [ ] **Step 13 (developer): run everything green.** `admin.css` and
  `tokens.css` already carry every class and token the new markup names, so
  nothing here needs a second round.

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_admin_js_escaping.py; echo "rc=$?"`

  Expected: `rc=0`, `119 passed, 4 warnings`.

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_admin_theme.py; echo "rc=$?"`

  Expected: unchanged and still green -- `rc=0`, `16 passed, 4 warnings`.

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_admin_inline_styles.py; echo "rc=$?"`

  Expected: `rc=0`, `5 passed, 4 warnings` -- `admin.css` defines every class
  the new markup names (mark, mark-glyph, mark-axis, wordmark, the icon
  classes, is-bad/is-crit/is-ok/is-skip/is-warn, meter, meter-fill,
  meter-tick, num), so the class-defined check passes outright.

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_contrast.py; echo "rc=$?"`

  Expected: `rc=0`, `349 passed, 4 warnings` -- both the static admin half
  (`ADMIN_PAIRS` across `ADMIN_LIGHT`/`ADMIN_DARK`) and the real-browser
  dynamic half (both admin fixture pages, in both themes) collect and pass.

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_reduced_motion.py tests/test_focus_ring.py; echo "rc=$?"`

  Expected: `rc=0`, `11 passed, 4 warnings` -- `admin.css` has no
  `transition: all`, turns every declared animation and transition off under
  reduced motion, and carries exactly one top-level `:focus-visible` rule.

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_css_comments.py; echo "rc=$?"`

  Expected: `rc=0`, `4 passed, 4 warnings` -- the header comment's token list
  is now comma-separated, so no `*/` closes it early.

  Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_images.py; echo "rc=$?"`

  Expected: `rc=0`, `73 passed, 4 warnings` -- every one of the 26 icon names
  now has a real consumer in `admin.js` or `index.html`, and every `icon-NAME`
  either file names is a real icon.

- [ ] **Step 14 (developer): lint every touched Python file.**

  Run: `docker compose run --rm -T test ruff check tests/test_contrast.py tests/test_reduced_motion.py tests/test_focus_ring.py tests/test_images.py tests/test_admin_js_escaping.py tests/test_css_comments.py; echo "rc=$?"`

  Expected: `rc=0`.

  Run: `docker compose run --rm -T test ruff format --check tests/test_contrast.py tests/test_reduced_motion.py tests/test_focus_ring.py tests/test_images.py tests/test_admin_js_escaping.py tests/test_css_comments.py; echo "rc=$?"`

  Expected: `6 files already formatted`, `rc=0`.

  (`tests/js/escaping_harness.mjs` and `tests/js/contrast_harness.mjs` are
  JavaScript; nothing in this repo's tooling lints them.)

- [ ] **Step 15 (developer): the whole suite.**

  Run: `docker compose run --rm -T test; echo "rc=$?"`

  Expected: `rc=0`, `1779 passed, 7 warnings`. Read the exit code directly,
  not through a `tail`: a piped run reports `tail`'s status, not pytest's.

- [ ] **Step 16 (developer): commit.**

```bash
git add frontend/public/admin/css/admin.css frontend/public/admin/js/admin.js \
        frontend/public/css/tokens.css tests/js/escaping_harness.mjs \
        tests/js/contrast_harness.mjs tests/test_admin_js_escaping.py \
        tests/test_contrast.py tests/test_css_comments.py tests/test_focus_ring.py \
        tests/test_images.py tests/test_legacy_admin_tokens.py tests/test_reduced_motion.py
git commit -m "Redesign the admin console in the Reflection style"
```

## Chunk 3: Cleanup, the visual check, and shipping PR 3

Inter's files go once nothing references them. Then the controller's tasks: screenshots of the finished console in both themes, and the gate, the reviews, the pull request, the merge and the deploy, each with the user's approval. There is no soak period: PR 3 deploys after PR 2's deploy, which happened on 2026-09-27.

### Task 5: Inter removed

Task 4 deletes `tokens.css`'s admin-layer `--font-sans: 'Inter', -apple-system,
BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;` override (line 269 today) --
the last place anything requests the family. Once that line is gone, nothing
in `frontend/public` names Inter, and the seven `inter-*.woff2` files, the
Inter `@font-face` blocks and `LICENSE-Inter.txt` are dead weight that a
long-cached, unversioned `/fonts/*.woff2` filename convention (spec section 3,
constraint 8) makes expensive to carry: they cannot be removed later without
also confirming nothing still points at them, so this task does that
confirmation once, now, alongside the deletion.

Two other places named the family until Task 4: `tokens.css`'s admin-layer
override, and `tests/test_legacy_admin_tokens.py:59`, which pinned that value
as a snapshot of the legacy block. Task 4 removes the first and deletes the
second file, so by this task nothing outside `fonts.css`, `fonts/README.md`
and the font files themselves mentions Inter; the grep step below confirms
it. The counts in this task were observed with Tasks 1-4 applied, in order.

**Files:**
- Delete: `frontend/public/fonts/inter-cyrillic-ext.woff2`
- Delete: `frontend/public/fonts/inter-cyrillic.woff2`
- Delete: `frontend/public/fonts/inter-greek-ext.woff2`
- Delete: `frontend/public/fonts/inter-greek.woff2`
- Delete: `frontend/public/fonts/inter-latin-ext.woff2`
- Delete: `frontend/public/fonts/inter-latin.woff2`
- Delete: `frontend/public/fonts/inter-vietnamese.woff2`
- Delete: `frontend/public/fonts/LICENSE-Inter.txt`
- Modify: `frontend/public/css/fonts.css`
- Modify: `frontend/public/fonts/README.md`

- [ ] **Step 1 (web-designer): delete the eight Inter files and watch `tests/test_fonts.py` go red.** No other file changes yet -- `fonts.css` and the README still reference the files this removes, which is exactly what should fail first.

```bash
git rm frontend/public/fonts/inter-cyrillic-ext.woff2 \
       frontend/public/fonts/inter-cyrillic.woff2 \
       frontend/public/fonts/inter-greek-ext.woff2 \
       frontend/public/fonts/inter-greek.woff2 \
       frontend/public/fonts/inter-latin-ext.woff2 \
       frontend/public/fonts/inter-latin.woff2 \
       frontend/public/fonts/inter-vietnamese.woff2 \
       frontend/public/fonts/LICENSE-Inter.txt
```

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_fonts.py; echo "rc=$?"`

Expected: `rc=1`, `4 failed, 71 passed, 4 warnings`:
- `test_every_css_url_is_a_file_on_this_origin` fails: 35 `url(/fonts/inter-*.woff2)` references in `fonts.css` (one per surviving `@font-face` block) now name no file under `frontend/public`.
- `test_fonts_css_the_readme_and_the_directory_list_the_same_files` fails: `fonts.css` and the README's checksum list still name the seven `inter-*.woff2` files, but the directory (`WOFF2_FILES`, read from disk at collection time) no longer has them -- "Extra items in the left set" from the `fonts.css`-vs-directory comparison, the first of the test's two asserts (the README comparison never runs once the first assert fails).
- `test_every_family_ships_with_its_open_font_license[Inter]` fails, not with an assertion but a `FileNotFoundError`: `fonts.css` still has `@font-face` blocks naming the `Inter` family (so the family is still parametrized in), and it looks for the now-deleted `frontend/public/fonts/LICENSE-Inter.txt`.
- `test_no_license_is_left_for_a_family_that_is_gone` fails too: the families `fonts.css` names still include `Inter`, but `LICENSE-Inter.txt` is gone from disk, so the two sets disagree ("Extra items in the right set: 'Inter'"). The licence-side pair follows from the same cause as the first two and is recorded here because it is what the suite prints.

The two tests parametrized directly over `WOFF2_FILES` (`test_each_font_is_woff2`, `test_each_font_matches_the_checksum_in_the_readme`) do not fail: `WOFF2_FILES` is read from disk at collection time, which already reflects the deletion, so they simply collect seven fewer instances each rather than failing.

- [ ] **Step 2 (web-designer): remove the Inter `@font-face` blocks from `fonts.css`, and rewrite the header comment so it no longer describes Inter.** The blocks first. The span runs from the family's own banner comment:

```css
/* ===========================================================================
   Inter
   =========================================================================== */
```

through the closing brace of its last block:

```css
/* latin */
@font-face {
    font-family: 'Inter';
    font-style: normal;
    font-weight: 700;
    font-display: swap;
    src: url('/fonts/inter-latin.woff2') format('woff2');
    unicode-range: U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD;
}
```

35 `@font-face` blocks in total -- 5 weights (300, 400, 500, 600, 700) times 7 subsets (cyrillic-ext, cyrillic, greek-ext, greek, vietnamese, latin-ext, latin) -- immediately followed by the JetBrains Mono banner, with no other line in between. Delete the whole span; the two blank lines already above it (before the Inter banner) become the two blank lines before the JetBrains Mono banner, matching the spacing every other family boundary in this file already uses.

Then the header. Replace:

```css
/* BSD Mirror - Web fonts (self-hosted) */
/*
   Inter, JetBrains Mono, Instrument Sans and Unbounded, served from this
   origin. Nothing here touches the network beyond /fonts/, which is what lets
   nginx run a `font-src 'self'` CSP without losing the site's typography.

   GENERATED FILE - do not hand-edit the @font-face blocks.
   The Inter and JetBrains Mono blocks are a transcription of the CSS that
   Google Fonts returned for the request the two stylesheets used to @import:

     https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700\
       &family=JetBrains+Mono:wght@400;500&display=swap

   The url() targets were rewritten, from fonts.gstatic.com to /fonts/, and
   the blocks re-indented to four spaces. Every font-weight, font-style,
   font-display and unicode-range is unchanged, so rendering is identical to
   the hosted version. The Instrument Sans and Unbounded section at the end
   names its own request. Regenerate by re-fetching a section's URL with a
   current Chrome User-Agent and repeating the rewrite; see fonts/README.md for
   provenance, versions and checksums.

   ---------------------------------------------------------------------------
   Notes on the shape of this file
   ---------------------------------------------------------------------------
   * The .woff2 files are VARIABLE fonts (Inter wght 100-900, JetBrains Mono
     wght 400-800; fonts/README.md records the axes of the other two). There
     is one file per family+subset, not one per weight, so the five Inter
     weights below all point at the same file per subset. The repeated blocks
     are how Google expresses this; keeping them means the browser resolves
     weights exactly as it did before.

   * WOFF2 only. Universally supported since 2018 and it is what Google already
     served this site; a WOFF/TTF fallback would only serve browsers that
     cannot run the admin SPA anyway.

   * font-display: swap is inherited from the original &display=swap request.
     Kept deliberately - changing it would change first-paint behaviour, which
     is a separate decision from where the bytes come from.

   * No <link rel="preload">. Preload would force the latin subsets to download
     unconditionally, competing with the API calls that gate first render, and
     it defeats the unicode-range negotiation below. Worth revisiting on its
     own merits; not part of self-hosting.

   * Subsets. Inter and JetBrains Mono ship every subset: latin-only content
     downloads only the latin files (~80 KB total), and the rest cost repo size
     but no bandwidth, because unicode-range means the browser fetches a subset
     only when it has to render a glyph from it. Instrument Sans and Unbounded
     ship latin and latin-ext only: they set the site's own copy, which is
     English, and any other character falls back to the next font in the stack.
   =========================================================================== */
```

with:

```css
/* BSD Mirror - Web fonts (self-hosted) */
/*
   JetBrains Mono, Instrument Sans and Unbounded, served from this origin.
   Nothing here touches the network beyond /fonts/, which is what lets nginx
   run a `font-src 'self'` CSP without losing the site's typography.

   GENERATED FILE - do not hand-edit the @font-face blocks.
   The JetBrains Mono blocks are a transcription of the CSS that Google Fonts
   returned for the JetBrains Mono portion of the request the two stylesheets
   used to @import:

     https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap

   The url() targets were rewritten, from fonts.gstatic.com to /fonts/, and
   the blocks re-indented to four spaces. Every font-weight, font-style,
   font-display and unicode-range is unchanged, so rendering is identical to
   the hosted version. The Instrument Sans and Unbounded section at the end
   names its own request. Regenerate by re-fetching a section's URL with a
   current Chrome User-Agent and repeating the rewrite; see fonts/README.md for
   provenance, versions and checksums.

   ---------------------------------------------------------------------------
   Notes on the shape of this file
   ---------------------------------------------------------------------------
   * The .woff2 files are VARIABLE fonts (JetBrains Mono wght 400-800;
     fonts/README.md records the axes of the other two). There is one file
     per family+subset, not one per weight, so JetBrains Mono's two weights
     below all point at the same file per subset. The repeated blocks are
     how Google expresses this; keeping them means the browser resolves
     weights exactly as it did before.

   * WOFF2 only. Universally supported since 2018 and it is what Google already
     served this site; a WOFF/TTF fallback would only serve browsers that
     cannot run the admin SPA anyway.

   * font-display: swap is inherited from the original &display=swap request.
     Kept deliberately - changing it would change first-paint behaviour, which
     is a separate decision from where the bytes come from.

   * No <link rel="preload">. Preload would force the latin subsets to download
     unconditionally, competing with the API calls that gate first render, and
     it defeats the unicode-range negotiation below. Worth revisiting on its
     own merits; not part of self-hosting.

   * Subsets. JetBrains Mono ships every subset: latin-only content downloads
     only the latin file (~31 KB), and the rest cost repo size but no
     bandwidth, because unicode-range means the browser fetches a subset only
     when it has to render a glyph from it. Instrument Sans and Unbounded
     ship latin and latin-ext only: they set the site's own copy, which is
     English, and any other character falls back to the next font in the stack.
   =========================================================================== */
```

The `(~80 KB total)` figure was the combined size of `inter-latin.woff2` (48432 bytes) and `jetbrains-mono-latin.woff2` (31340 bytes), rounded up; with Inter's file gone, the same sentence about JetBrains Mono's own latin file recomputes to `(~31 KB)` (31340 bytes). Everything else JetBrains-Mono-, Instrument-Sans- or Unbounded-specific is carried over unchanged.

- [ ] **Step 3 (web-designer): remove Inter from `frontend/public/fonts/README.md`, and correct the three headcounts the removal leaves wrong.** Nine edits. The opening sentence. Replace:

```md
Inter, JetBrains Mono, Instrument Sans and Unbounded, vendored so the site
loads no fonts from a third party. This is what allows nginx to serve a
```

with:

```md
JetBrains Mono, Instrument Sans and Unbounded, vendored so the site loads no
fonts from a third party. This is what allows nginx to serve a
```

The retrieval paragraph and its URL, so JetBrains Mono keeps its own retrieval record instead of sharing Inter's. Replace:

```md
Inter and JetBrains Mono were retrieved 2026-08-30 from Google Fonts, which is
the same source the site used before, so the bytes are the ones production was
already serving:

    https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap
```

with:

```md
JetBrains Mono was retrieved 2026-08-30 from Google Fonts, which is the same
source the site used before, so the bytes are the ones production was already
serving:

    https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap
```

The version table row. Replace:

```md
| Inter | 4.001 (git-66647c0bb) | `wght` 100-900 (variable) | 300, 400, 500, 600, 700 |
| JetBrains Mono | 2.211 | `wght` 400-800 (variable) | 400, 500 |
```

with:

```md
| JetBrains Mono | 2.211 | `wght` 400-800 (variable) | 400, 500 |
```

The table's own headcount, two paragraphs down, so the README stays true once it lists three families instead of four. Replace:

```md
All four are **variable** fonts: one file per subset covers every weight. The
```

with:

```md
All three are **variable** fonts: one file per subset covers every weight. The
```

The licensing section's intro sentence, same reason. Replace:

```md
All four families are under the SIL Open Font License 1.1, which permits
```

with:

```md
All three families are under the SIL Open Font License 1.1, which permits
```

The licence list line. Replace:

```md
* `LICENSE-Inter.txt` - from https://github.com/rsms/inter (`LICENSE.txt`)
* `LICENSE-JetBrainsMono.txt` - from https://github.com/JetBrains/JetBrainsMono (`OFL.txt`)
```

with:

```md
* `LICENSE-JetBrainsMono.txt` - from https://github.com/JetBrains/JetBrainsMono (`OFL.txt`)
```

The name-table confirmation sentence just below, third and last "four". Replace:

```md
OFL for all four.
```

with:

```md
OFL for all three.
```

The regenerate command, so it re-fetches only what is still here. Replace:

```md
    curl -A "<current desktop Chrome UA>" \
      "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"
```

with:

```md
    curl -A "<current desktop Chrome UA>" \
      "https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap"
```

The seven checksum lines. Replace:

```md
fccca918fea40089dacadc7045861314d1a6bc91f1f323cc1eeb22ebcdb321b5  inter-cyrillic-ext.woff2
aebf2ab4a4ce6810d73c1ac7be7cafb4e5ec4cee2d6db5fb3e09691747ec4bd6  inter-cyrillic.woff2
a2e2c783ca6f9c20486e81e72a279203e86730bbf8f01ff6a5ee9dbd09e1c271  inter-greek-ext.woff2
46dd4cdca58c26ae87cc6927657bf83b2e8abfc39ffd0ab176e301a8d28d22bf  inter-greek.woff2
a28eb6d3ccb534ae0c94ca999371df024aab60b08c3c8a5720ee9e32fa0faaa2  inter-latin-ext.woff2
c940764593d0fe5d596be327ca7558855e018039fb78509aa21921fd3644c3e4  inter-latin.woff2
8db00ff46c67b22cda8bed865acf7077651cac8d2841d5b40980556b48961931  inter-vietnamese.woff2
9343de2ca5d9549f792e7962375af8efb0f320c7643bfd36c884b5a30e5c396f  jetbrains-mono-cyrillic-ext.woff2
```

with:

```md
9343de2ca5d9549f792e7962375af8efb0f320c7643bfd36c884b5a30e5c396f  jetbrains-mono-cyrillic-ext.woff2
```

Each "All four"/"all four" reword is the single word only, to the minimum needed to keep the sentence true once three families remain: JetBrains Mono, Instrument Sans and Unbounded. The unrelated "four spaces" just below the regenerate commands (about re-indenting `fonts.css`, not a family count) is untouched.

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_fonts.py; echo "rc=$?"`

Expected: `rc=0`, `74 passed, 4 warnings` -- one fewer test than Step 1's red run collected (`71 passed, 4 failed` = 75). `test_every_family_ships_with_its_open_font_license` now parametrizes over 3 families instead of 4, because `fonts.css` no longer names Inter; that is the one instance this step removes. The two tests parametrized directly over files on disk (`test_each_font_is_woff2`, `test_each_font_matches_the_checksum_in_the_readme`) were already down from 17 to 10 instances each after Step 1's deletion, and do not change again here.

- [ ] **Step 4 (web-designer): confirm nothing still names Inter.**

```bash
grep -rnw Inter frontend/public tests CLAUDE.md .dockerignore Dockerfile.test; echo "rc=$?"
```

Expected: no output and `rc=1` (grep found nothing). Task 4 removed the last two places that named the family, `tokens.css`'s admin-layer override and `tests/test_legacy_admin_tokens.py`; a hit here means one of them survived, and this task must not proceed past it.

(A plain, non-word-bounded `grep -rn Inter` over the same paths also matches `setInterval`, `clearInterval`, `refreshInterval` and one comment's "Interpolation" -- none of them the font family; `-w` excludes all of them, since none has a non-word character on both sides of "Inter".)

Run: `docker compose run --rm -T test; echo "rc=$?"`

Expected: `rc=0`, `1764 passed, 7 warnings` -- Task 4's `1779 passed` minus the 15 test instances Step 1's parametrization loses (7 `test_each_font_is_woff2`, 7 `test_each_font_matches_the_checksum_in_the_readme`, 1 `test_every_family_ships_with_its_open_font_license[Inter]`), with nothing else in the suite affected.

- [ ] **Step 5 (web-designer): commit.**

```bash
git add frontend/public/fonts frontend/public/css/fonts.css
git commit -m "Remove the Inter font files"
```


### Task 6 (controller): The visual check

Spec section 10: screenshots of both themes at 1440, 768 and 400px, shared in the session. They cannot be attached to the pull request, so its body lists what was checked.

The console needs a signed-in session to render anything but the login page, so the check runs the real `admin.js` against a stub API inside the test image: a static server that answers every endpoint the console calls from a fixture file. A bootstrap page stores the token and opens each route; one extra page opens the sync-job modal and shows one toast of each type. Nothing is entered into a form and nothing leaves the container (`--network none`).

- [ ] **Step 1: write the scripts.** All four live in `$SCRATCH/pr3/`; `screens_admin.sh` mounts the other two from its own directory.

`$SCRATCH/pr3/screens_admin.sh`:

```bash
#!/usr/bin/env bash
# PR 3's visual check for the admin console: the seven authenticated pages
# plus the plain login screen and one modal/toast fixture, at 1440, 768 and
# 400px, light and dark, rendered by the test image's Chromium over HTTP
# against stub_admin_api.py (a static file server plus every /api/* endpoint
# admin.js calls, reading its fixtures from
# stub_data.json).
# Writes .screenshots/pr3-<page>-<theme>-<width>.png in REPO_ROOT.
# Usage: screens_admin.sh REPO_ROOT
set -euo pipefail
R=$(cd "${1:?usage: screens_admin.sh REPO_ROOT}" && pwd)
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$R/.screenshots"
# A stale PNG from an earlier run must never pass for a new one.
rm -f "$R/.screenshots"/pr3-*.png

docker run --rm --network none -u "$(id -u):$(id -g)" --security-opt seccomp=unconfined -e HOME=/tmp \
    -v "$R/frontend/public:/site:ro" \
    -v "$HERE/stub_admin_api.py:/stub/stub_admin_api.py:ro" \
    -v "$HERE/stub_data.json:/stub/stub_data.json:ro" \
    -v "$R/.screenshots:/out" \
    bsdmirror-test bash -c '
set -e
mkdir -p /tmp/www && cp -R /site/. /tmp/www/

# admin.js will not render an authenticated page without a stored token (see
# admin.js reads it in init); this bootstrap page is the only way onto one
# other than filling in the real login form, which the stub does not need to
# prove. It reads its destination from its own query string so the same page
# serves every route below, and it is never the mounted checkout -- only this
# copy under /tmp/www.
cat > /tmp/www/__bootstrap__.html <<HTML
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>bootstrap</title></head>
<body><script src="/__bootstrap__.js"></script></body>
</html>
HTML
cat > /tmp/www/__bootstrap__.js <<JS
var params = new URLSearchParams(window.location.search);
var dest = params.get("dest") || "/admin/#dashboard";
window.localStorage.setItem("bsdmirror_token", "stub-admin-token");
window.location.replace(dest);
JS

# The modal/toast fixture: admin/index.html plus one more classic script.
# admin.js declares Modal, Toast, actions and html as top-level const/function
# bindings; a later classic script tag shares that same top-level scope, so
# the fixture script below reaches them directly once the layout it needs
# (#toastContainer, #modal) exists -- see renderLayout in admin.js. This
# only ever inserts a script tag; index.html gains no inline script or style.
sed "s#</body>#<script src=\"/__modal_toast__.js\"></script></body>#" \
    /tmp/www/admin/index.html > /tmp/www/__modal_toast__.html
cat > /tmp/www/__modal_toast__.js <<JS
(function poll() {
    if (!document.querySelector(".app-layout")) {
        window.setTimeout(poll, 50);
        return;
    }
    actions.viewSyncLogs("301");
    Toast.show("Sync job started", "success");
    Toast.show("Invalid credentials", "error");
    Toast.show("Settings saved", "info");
})();
JS

serve() {  # serve DIR PORT: static files plus the stubbed /api
    python3 /stub/stub_admin_api.py "$1" "$2" /stub/stub_data.json &
    for _ in $(seq 1 50); do
        if python3 -c "import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:$2/admin/\")" 2>/dev/null; then
            return 0
        fi
        sleep 0.2
    done
    echo "the server on port $2 never answered" >&2
    return 1
}
shot() {  # shot URL OUT WIDTH HEIGHT SCHEME BUDGET
    local flag=""; [ "$5" = dark ] && flag="--force-dark-mode"
    rm -f "$2"
    # Reduced motion switches transitions off, so a re-rendered page shows
    # its final colours instead of a frame caught mid-transition.
    chromium --headless=new --disable-gpu --hide-scrollbars $flag --force-prefers-reduced-motion \
        --virtual-time-budget="$6" \
        --window-size="$3,$4" --screenshot="$2" "$1" >/dev/null 2>&1
    [ -s "$2" ] || { echo "no screenshot for $1 at $3px $5" >&2; return 1; }
}

serve /tmp/www 8765
BASE=http://127.0.0.1:8765
PAGES="dashboard mirrors sync-failures protected-paths users audit-logs settings"

for scheme in light dark; do
    # The plain login screen: no bootstrap, no token, no fetch -- a small
    # budget is enough.
    shot "$BASE/admin/" /out/pr3-login-$scheme-1440.png 1440 900 $scheme 2000
    shot "$BASE/admin/" /out/pr3-login-$scheme-768.png 768 900 $scheme 2000
    shot "$BASE/admin/" /out/pr3-login-$scheme-400.png 400 900 $scheme 2000

    for page in $PAGES; do
        h1440=3000; h768=3800; h400=4600
        url="$BASE/__bootstrap__.html?dest=%2Fadmin%2F%23$page"
        shot "$url" /out/pr3-$page-$scheme-1440.png 1440 $h1440 $scheme 6000
        shot "$url" /out/pr3-$page-$scheme-768.png 768 $h768 $scheme 6000
        shot "$url" /out/pr3-$page-$scheme-400.png 400 $h400 $scheme 6000
    done

    # A short budget on purpose: Toast.show removes each toast 4s after it is
    # shown (admin.js), so the screenshot has to land before that, not after
    # every fetch a full page load could ever need.
    url="$BASE/__bootstrap__.html?dest=%2F__modal_toast__.html%23dashboard"
    shot "$url" /out/pr3-modal-toast-$scheme-1440.png 1440 1600 $scheme 3000
    shot "$url" /out/pr3-modal-toast-$scheme-768.png 768 2200 $scheme 3000
    shot "$url" /out/pr3-modal-toast-$scheme-400.png 400 2800 $scheme 3000
done
'
ls -l "$R/.screenshots" | grep pr3- || true
```

`$SCRATCH/pr3/stub_admin_api.py`:

```python
#!/usr/bin/env python3
"""Static files plus a stubbed /api/* for PR 3's admin-console screenshots.

Serves ROOT (a copy of frontend/public, so /admin/ resolves to
ROOT/admin/index.html the same way any static host would) and answers every
endpoint admin.js calls, GET and the mutating verbs, from
the fixtures in DATA_JSON. There is no auth check at all -- every request is
treated as the stub admin in auth.me, token or not -- this only ever runs
with --network none against a throwaway container.

Usage: stub_admin_api.py ROOT PORT DATA_JSON
"""
import functools
import http.server
import json
import re
import sys
import threading
from urllib.parse import parse_qs

ROOT, PORT, DATA_PATH = sys.argv[1], int(sys.argv[2]), sys.argv[3]

with open(DATA_PATH) as f:
    DATA = json.load(f)

MIRRORS_BY_ID = {m["id"]: m for m in DATA["mirrors"]}
USERS_BY_ID = {u["id"]: u for u in DATA["users"]}
_ids_lock = threading.Lock()
_next_user_id = max(USERS_BY_ID) + 1


def _send_json(handler, body, status=200):
    if body is None:
        handler.send_response(404)
        handler.send_header("Content-Length", "0")
        handler.end_headers()
        return
    data = json.dumps(body).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _send_no_content(handler):
    handler.send_response(204)
    handler.send_header("Content-Length", "0")
    handler.end_headers()


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _path(self):
        return self.path.split("?", 1)[0]

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        ctype = self.headers.get("Content-Type", "")
        if "application/x-www-form-urlencoded" in ctype:
            return {k: v[0] for k, v in parse_qs(raw.decode()).items()}
        return json.loads(raw.decode())

    # ---- GET: every read endpoint admin.js calls -------------------------
    def do_GET(self):
        path = self._path()

        if path == "/api/auth/me":
            return _send_json(self, DATA["auth"]["me"])
        if path == "/api/admin/dashboard":
            return _send_json(self, DATA["dashboard"])
        if path == "/api/admin/health-checks":
            return _send_json(self, DATA["health_checks"])
        if path == "/api/mirrors/":
            return _send_json(self, DATA["mirrors"])
        if path == "/api/admin/sync-failures":
            return _send_json(self, DATA["sync_failures"])
        if path == "/api/admin/protected-paths":
            return _send_json(self, DATA["protected_paths"])
        if path == "/api/admin/archive-inventory":
            return _send_json(self, DATA["archive_inventory"])
        if path == "/api/admin/users":
            return _send_json(self, list(USERS_BY_ID.values()))
        if path == "/api/admin/audit-logs":
            return _send_json(self, DATA["audit_logs"])
        if path == "/api/admin/settings":
            return _send_json(self, DATA["settings"])

        m = re.fullmatch(r"/api/mirrors/(\d+)/sync-history", path)
        if m:
            return _send_json(self, DATA["sync_history"].get(m.group(1), []))
        m = re.fullmatch(r"/api/mirrors/(\d+)", path)
        if m:
            return _send_json(self, MIRRORS_BY_ID.get(int(m.group(1))))
        m = re.fullmatch(r"/api/admin/sync-jobs/(\d+)/logs", path)
        if m:
            return _send_json(self, DATA["sync_job_logs"].get(m.group(1)))

        if path.startswith("/api/"):
            return _send_json(self, {"detail": "no stub route for " + path}, 404)
        return super().do_GET()

    # ---- POST: login and the two "create" actions -------------------------
    def do_POST(self):
        path = self._path()
        body = self._read_body()

        if path == "/api/auth/token":
            return _send_json(self, DATA["auth"]["token"])
        if re.fullmatch(r"/api/admin/mirrors/\d+/sync", path):
            return _send_json(self, {"queued": True})
        if path == "/api/admin/users":
            global _next_user_id
            with _ids_lock:
                new_id = _next_user_id
                _next_user_id += 1
            user = {
                "id": new_id,
                "username": body.get("username"),
                "email": body.get("email"),
                "role": body.get("role", "readonly"),
                "is_active": True,
                "last_login": None,
            }
            USERS_BY_ID[new_id] = user
            return _send_json(self, user, 201)

        return _send_json(self, {"detail": "no stub route for " + path}, 404)

    # ---- PATCH: the three "update" actions ---------------------------------
    def do_PATCH(self):
        path = self._path()
        body = self._read_body()

        m = re.fullmatch(r"/api/admin/mirrors/(\d+)", path)
        if m:
            mirror = MIRRORS_BY_ID.get(int(m.group(1)))
            if mirror is not None:
                mirror.update(body)
            return _send_json(self, mirror)

        m = re.fullmatch(r"/api/admin/users/(\d+)", path)
        if m:
            user = USERS_BY_ID.get(int(m.group(1)))
            if user is not None:
                user.update(body)
            return _send_json(self, user)

        if path == "/api/admin/settings":
            return _send_json(self, {"updated": True})

        return _send_json(self, {"detail": "no stub route for " + path}, 404)

    # ---- DELETE: the one destructive action --------------------------------
    def do_DELETE(self):
        path = self._path()
        m = re.fullmatch(r"/api/admin/users/(\d+)", path)
        if m:
            USERS_BY_ID.pop(int(m.group(1)), None)
            return _send_no_content(self)
        return _send_json(self, {"detail": "no stub route for " + path}, 404)


handler = functools.partial(Handler, directory=ROOT)
http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler).serve_forever()
```

`$SCRATCH/pr3/stub_data.json`:

```json
{
  "auth": {
    "token": { "access_token": "stub-admin-token", "token_type": "bearer" },
    "me": { "id": 1, "username": "admin", "email": "admin@bsdmirror.example", "role": "admin", "is_active": true }
  },
  "mirrors": [
    { "id": 1, "name": "FreeBSD", "url_path": "FreeBSD", "status": "active", "total_size_human": "799.9 GB", "last_sync_completed": "2026-09-27T08:12:00Z", "upstream_url": "rsync://ftp.freebsd.org/FreeBSD/", "local_path": "/data/mirrors/FreeBSD" },
    { "id": 2, "name": "NetBSD", "url_path": "NetBSD", "status": "syncing", "total_size_human": "743.5 GB", "last_sync_completed": "2026-09-26T23:47:00Z", "upstream_url": "rsync://ftp.netbsd.org/NetBSD/", "local_path": "/data/mirrors/NetBSD" },
    { "id": 3, "name": "OpenBSD", "url_path": "OpenBSD", "status": "error", "total_size_human": "2.6 TB", "last_sync_completed": "2026-09-25T02:05:00Z", "upstream_url": "rsync://ftp.hostserver.de/OpenBSD/", "local_path": "/data/mirrors/OpenBSD" }
  ],
  "sync_history": {
    "1": [
      { "id": 401, "status": "completed", "bytes_transferred": 859003123456, "files_deleted": 1500, "triggered_by": "scheduler", "completed_at": "2026-09-27T08:12:00Z" },
      { "id": 402, "status": "failed", "bytes_transferred": 102400, "files_deleted": 0, "triggered_by": "manual", "completed_at": "2026-09-20T03:00:00Z" }
    ],
    "2": [
      { "id": 403, "status": "running", "bytes_transferred": 204800000, "files_deleted": 0, "triggered_by": "scheduler", "started_at": "2026-09-27T09:40:00Z" }
    ],
    "3": [
      { "id": 301, "status": "failed", "bytes_transferred": 452331520, "files_deleted": 0, "triggered_by": "scheduler", "completed_at": "2026-09-25T02:05:00Z" }
    ]
  },
  "sync_job_logs": {
    "301": {
      "id": 301, "status": "failed", "triggered_by": "scheduler",
      "started_at": "2026-09-25T02:00:00Z", "completed_at": "2026-09-25T02:05:00Z",
      "files_transferred": 128, "bytes_transferred": 452331520, "files_deleted": 0,
      "error_message": "rsync: failed to connect to ftp.hostserver.de: Connection timed out (110)\nrsync error: error in socket IO (code 10) at clientserver.c(140) [Receiver=3.2.7]",
      "rsync_output": "receiving incremental file list\npub/OpenBSD/7.5/amd64/base75.tgz\n  452,331,520 100%   38.11MB/s    0:00:11 (xfr#812, to-chk=0/9931)\n\nsent 1,845,201 bytes  received 452,331,520 bytes  38,118,201.42 bytes/sec\ntotal size is 2,594,003,112,201  speedup is 5,717.44\nrsync: connection unexpectedly closed (0 bytes received so far) [receiver]"
    },
    "302": {
      "id": 302, "status": "failed", "triggered_by": "scheduler",
      "started_at": "2026-09-22T03:00:00Z", "completed_at": "2026-09-22T03:12:00Z",
      "files_transferred": 9021, "bytes_transferred": 993459200, "files_deleted": 12,
      "error_message": "rsync error: error in rsync protocol data stream (code 12) at io.c(226) [Receiver=3.2.7]",
      "rsync_output": "receiving incremental file list\nNetBSD-10.1/amd64/binary/sets/base.tar.xz\n  128,004,331 100%   22.4MB/s    0:00:05\n\nrsync: connection unexpectedly closed (13 bytes received so far) [Receiver]\nrsync error: error in rsync protocol data stream (code 12) at io.c(226) [Receiver=3.2.7]"
    },
    "303": {
      "id": 303, "status": "failed", "triggered_by": "manual",
      "started_at": "2026-09-15T04:00:00Z", "completed_at": "2026-09-15T04:00:30Z",
      "files_transferred": 0, "bytes_transferred": 0, "files_deleted": 0,
      "error_message": "rsync: connection unexpectedly closed (broken pipe)",
      "rsync_output": ""
    }
  },
  "dashboard": {
    "mirrors": { "total": 3, "active": 1, "syncing": 1 },
    "users": { "total": 4 },
    "storage": { "percent_used": 91, "free_bytes": 360000000000, "total_bytes": 4000000000000, "used_bytes": 3640000000000 },
    "recent_syncs": [
      { "mirror_id": 1, "status": "completed", "files_deleted": 1500, "created_at": "2026-09-27T08:12:00Z" },
      { "mirror_id": 2, "status": "running", "files_deleted": 0, "created_at": "2026-09-27T09:40:00Z" },
      { "mirror_id": 3, "status": "failed", "files_deleted": 0, "created_at": "2026-09-25T02:05:00Z" },
      { "mirror_id": 1, "status": "pending", "files_deleted": 0, "created_at": "2026-09-27T10:00:00Z" },
      { "mirror_id": 2, "status": "cancelled", "files_deleted": 0, "created_at": "2026-09-26T14:30:00Z" }
    ],
    "recent_activity": [
      { "action": "login_success", "created_at": "2026-09-27T09:55:00Z" },
      { "action": "sync_triggered", "created_at": "2026-09-27T09:40:00Z" },
      { "action": "settings_updated", "created_at": "2026-09-27T08:05:00Z" },
      { "action": "user_created", "created_at": "2026-09-26T18:20:00Z" },
      { "action": "mirror_updated", "created_at": "2026-09-26T12:00:00Z" }
    ]
  },
  "health_checks": {
    "state": "failing",
    "reason": "1 check is failing.",
    "finished_at": "2026-09-27T09:45:00Z",
    "age_seconds": 900,
    "stale_after_seconds": 5400,
    "counts": { "bad": 1, "skipped": 1, "warnings": 1, "ok": 3 },
    "bad": [ { "label": "openbsd_disk_free", "detail": "only 4% free on /data/mirrors/OpenBSD" } ],
    "skipped": [ { "check": "netbsd_checksum", "reason": "sync in progress" } ],
    "warnings": [ "disk usage above 85% on the primary volume" ],
    "ok": [ "freebsd_rsync_reachable", "netbsd_rsync_reachable", "discord_webhook_reachable" ],
    "alerting": true,
    "state_persisted": true
  },
  "sync_failures": {
    "period_days": 30,
    "totals": { "failed": 7, "completed": 341 },
    "by_mirror": [
      { "mirror_name": "FreeBSD", "failed": 1, "completed": 120, "failure_rate_percent": 0.8 },
      { "mirror_name": "NetBSD", "failed": 2, "completed": 110, "failure_rate_percent": 1.8 },
      { "mirror_name": "OpenBSD", "failed": 4, "completed": 111, "failure_rate_percent": 3.5 }
    ],
    "incidents": [
      { "mirror_name": "OpenBSD", "error_message": "rsync: failed to connect to ftp.hostserver.de: Connection timed out (110)", "occurrences": 3, "first_seen": "2026-09-20T02:00:00Z", "last_seen": "2026-09-25T02:05:00Z", "latest_job_id": 301 },
      { "mirror_name": "NetBSD", "error_message": "rsync error: error in rsync protocol data stream (code 12) at io.c(226)", "occurrences": 2, "first_seen": "2026-09-18T03:10:00Z", "last_seen": "2026-09-22T03:12:00Z", "latest_job_id": 302 },
      { "mirror_name": "FreeBSD", "error_message": "rsync: connection unexpectedly closed (broken pipe)", "occurrences": 1, "first_seen": "2026-09-15T04:00:00Z", "last_seen": "2026-09-15T04:00:00Z", "latest_job_id": 303 }
    ]
  },
  "protected_paths": {
    "groups": [
      { "mirror_type": "freebsd", "mirror_names": ["FreeBSD"], "patterns": ["/releases/13.2-RELEASE/*", "/releases/14.1-RELEASE/*", "/releases/ISO-IMAGES/13.2/*"] },
      { "mirror_type": "netbsd", "mirror_names": ["NetBSD"], "patterns": ["/NetBSD-10.2/*", "/NetBSD-9.4/*"] },
      { "mirror_type": "openbsd", "mirror_names": ["OpenBSD"], "patterns": [] }
    ]
  },
  "archive_inventory": {
    "mirrors": [
      {
        "mirror_type": "freebsd", "mirror_names": ["FreeBSD"], "available": true, "error": null,
        "incomplete": false, "truncated": false,
        "protected_not_on_disk": [], "current_not_on_disk": [], "stale_current": [], "unclassified": ["14.0-BETA1-experimental"], "errors": [],
        "releases": [
          { "version": "13.2-RELEASE", "protection": "full", "unprotected_locations": [], "current": false, "kind": "release", "newest": false, "latest_in_major": false, "at_risk": false, "location_count": 4, "modified": "2023-04-11T00:00:00Z" },
          { "version": "14.1-RELEASE", "protection": "full", "unprotected_locations": [], "current": true, "kind": "release", "newest": true, "latest_in_major": true, "at_risk": false, "location_count": 6, "modified": "2026-06-30T00:00:00Z" },
          { "version": "14.2-BETA2", "protection": "partial", "unprotected_locations": ["amd64/ISO-IMAGES"], "current": false, "kind": "prerelease", "newest": false, "latest_in_major": false, "at_risk": false, "location_count": 2, "modified": "2026-09-10T00:00:00Z" },
          { "version": "12.4-RELEASE", "protection": "none", "unprotected_locations": [], "current": false, "kind": "release", "newest": false, "latest_in_major": false, "at_risk": true, "location_count": 3, "modified": "2024-01-20T00:00:00Z" }
        ]
      },
      {
        "mirror_type": "netbsd", "mirror_names": ["NetBSD"], "available": true, "error": null,
        "incomplete": true, "truncated": true,
        "protected_not_on_disk": ["NetBSD-9.4"], "current_not_on_disk": [], "stale_current": ["NetBSD-10.1"], "unclassified": [], "errors": ["NetBSD-8.2/source (permission denied)"],
        "releases": [
          { "version": "NetBSD-10.2", "protection": "full", "unprotected_locations": [], "current": true, "kind": "release", "newest": true, "latest_in_major": true, "at_risk": false, "location_count": 5, "modified": "2026-07-15T00:00:00Z" },
          { "version": "NetBSD-10.1", "protection": "unknown", "unprotected_locations": [], "current": false, "kind": "release", "newest": false, "latest_in_major": false, "at_risk": false, "location_count": 3, "modified": "2026-03-01T00:00:00Z" },
          { "version": "NetBSD-9.4", "protection": "none", "unprotected_locations": [], "current": false, "kind": "release", "newest": false, "latest_in_major": false, "at_risk": true, "location_count": 2, "modified": "2023-11-05T00:00:00Z" }
        ]
      },
      {
        "mirror_type": "openbsd", "mirror_names": ["OpenBSD"], "available": false, "error": "disk scan timed out after 30s",
        "incomplete": false, "truncated": false,
        "protected_not_on_disk": [], "current_not_on_disk": [], "stale_current": [], "unclassified": [], "errors": [],
        "releases": []
      }
    ]
  },
  "users": [
    { "id": 1, "username": "admin", "email": "admin@bsdmirror.example", "role": "admin", "is_active": true, "last_login": "2026-09-27T09:55:00Z" },
    { "id": 2, "username": "olga", "email": "olga@bsdmirror.example", "role": "operator", "is_active": true, "last_login": "2026-09-27T07:30:00Z" },
    { "id": 3, "username": "ro_viewer", "email": "ro_viewer@bsdmirror.example", "role": "readonly", "is_active": true, "last_login": "2026-09-20T11:00:00Z" },
    { "id": 4, "username": "old_operator", "email": "old_operator@bsdmirror.example", "role": "operator", "is_active": false, "last_login": "2026-06-01T09:00:00Z" }
  ],
  "audit_logs": [
    { "id": 1, "created_at": "2026-09-27T22:00:00Z", "username": "admin", "action": "login_success", "resource_type": null, "resource_id": null, "ip_address": "203.0.113.10" },
    { "id": 2, "created_at": "2026-09-27T20:00:00Z", "username": "admin", "action": "login_failed", "resource_type": null, "resource_id": null, "ip_address": "198.51.100.77" },
    { "id": 3, "created_at": "2026-09-27T18:00:00Z", "username": "admin", "action": "logout", "resource_type": null, "resource_id": null, "ip_address": null },
    { "id": 4, "created_at": "2026-09-27T16:00:00Z", "username": "admin", "action": "user_created", "resource_type": "user", "resource_id": 2, "ip_address": "203.0.113.10" },
    { "id": 5, "created_at": "2026-09-27T14:00:00Z", "username": "admin", "action": "user_updated", "resource_type": "user", "resource_id": 3, "ip_address": "203.0.113.10" },
    { "id": 6, "created_at": "2026-09-27T12:00:00Z", "username": "admin", "action": "user_deleted", "resource_type": "user", "resource_id": 5, "ip_address": "203.0.113.10" },
    { "id": 7, "created_at": "2026-09-27T10:00:00Z", "username": "olga", "action": "mirror_updated", "resource_type": "mirror", "resource_id": 1, "ip_address": "198.51.100.42" },
    { "id": 8, "created_at": "2026-09-27T08:00:00Z", "username": "olga", "action": "sync_triggered", "resource_type": "mirror", "resource_id": 1, "ip_address": "198.51.100.42" },
    { "id": 9, "created_at": "2026-09-27T06:00:00Z", "username": "admin", "action": "settings_updated", "resource_type": "settings", "resource_id": null, "ip_address": "203.0.113.10" },
    { "id": 10, "created_at": "2026-09-27T04:00:00Z", "username": null, "action": "backup_created", "resource_type": null, "resource_id": null, "ip_address": null },
    { "id": 11, "created_at": "2026-09-26T22:00:00Z", "username": "olga", "action": "login_success", "resource_type": null, "resource_id": null, "ip_address": "198.51.100.42" },
    { "id": 12, "created_at": "2026-09-26T20:00:00Z", "username": null, "action": "login_failed", "resource_type": null, "resource_id": null, "ip_address": "198.51.100.77" },
    { "id": 13, "created_at": "2026-09-26T18:00:00Z", "username": "olga", "action": "logout", "resource_type": null, "resource_id": null, "ip_address": null },
    { "id": 14, "created_at": "2026-09-26T16:00:00Z", "username": "admin", "action": "user_created", "resource_type": "user", "resource_id": 3, "ip_address": "203.0.113.10" },
    { "id": 15, "created_at": "2026-09-26T14:00:00Z", "username": "admin", "action": "user_updated", "resource_type": "user", "resource_id": 3, "ip_address": "203.0.113.10" },
    { "id": 16, "created_at": "2026-09-26T12:00:00Z", "username": "admin", "action": "user_deleted", "resource_type": "user", "resource_id": 6, "ip_address": "203.0.113.10" },
    { "id": 17, "created_at": "2026-09-26T10:00:00Z", "username": "olga", "action": "mirror_updated", "resource_type": "mirror", "resource_id": 2, "ip_address": "198.51.100.42" },
    { "id": 18, "created_at": "2026-09-26T08:00:00Z", "username": "olga", "action": "sync_triggered", "resource_type": "mirror", "resource_id": 2, "ip_address": "198.51.100.42" },
    { "id": 19, "created_at": "2026-09-26T06:00:00Z", "username": "admin", "action": "settings_updated", "resource_type": "settings", "resource_id": null, "ip_address": "203.0.113.10" },
    { "id": 20, "created_at": "2026-09-26T04:00:00Z", "username": null, "action": "backup_created", "resource_type": null, "resource_id": null, "ip_address": null },
    { "id": 21, "created_at": "2026-09-25T22:00:00Z", "username": "ro_viewer", "action": "login_success", "resource_type": null, "resource_id": null, "ip_address": "192.0.2.15" },
    { "id": 22, "created_at": "2026-09-25T20:00:00Z", "username": "admin", "action": "login_failed", "resource_type": null, "resource_id": null, "ip_address": "198.51.100.77" },
    { "id": 23, "created_at": "2026-09-25T18:00:00Z", "username": "ro_viewer", "action": "logout", "resource_type": null, "resource_id": null, "ip_address": null },
    { "id": 24, "created_at": "2026-09-25T16:00:00Z", "username": "admin", "action": "user_created", "resource_type": "user", "resource_id": 4, "ip_address": "203.0.113.10" },
    { "id": 25, "created_at": "2026-09-25T14:00:00Z", "username": "admin", "action": "user_updated", "resource_type": "user", "resource_id": 3, "ip_address": "203.0.113.10" },
    { "id": 26, "created_at": "2026-09-25T12:00:00Z", "username": "admin", "action": "user_deleted", "resource_type": "user", "resource_id": 7, "ip_address": "203.0.113.10" },
    { "id": 27, "created_at": "2026-09-25T10:00:00Z", "username": "olga", "action": "mirror_updated", "resource_type": "mirror", "resource_id": 3, "ip_address": "198.51.100.42" },
    { "id": 28, "created_at": "2026-09-25T08:00:00Z", "username": "olga", "action": "sync_triggered", "resource_type": "mirror", "resource_id": 3, "ip_address": "198.51.100.42" },
    { "id": 29, "created_at": "2026-09-25T06:00:00Z", "username": "admin", "action": "settings_updated", "resource_type": "settings", "resource_id": null, "ip_address": "203.0.113.10" },
    { "id": 30, "created_at": "2026-09-25T04:00:00Z", "username": null, "action": "backup_created", "resource_type": null, "resource_id": null, "ip_address": null },
    { "id": 31, "created_at": "2026-09-24T22:00:00Z", "username": "admin", "action": "login_success", "resource_type": null, "resource_id": null, "ip_address": "203.0.113.10" },
    { "id": 32, "created_at": "2026-09-24T20:00:00Z", "username": "admin", "action": "login_failed", "resource_type": null, "resource_id": null, "ip_address": "198.51.100.77" },
    { "id": 33, "created_at": "2026-09-24T18:00:00Z", "username": "admin", "action": "logout", "resource_type": null, "resource_id": null, "ip_address": null },
    { "id": 34, "created_at": "2026-09-24T16:00:00Z", "username": "admin", "action": "user_created", "resource_type": "user", "resource_id": 2, "ip_address": "203.0.113.10" },
    { "id": 35, "created_at": "2026-09-24T14:00:00Z", "username": "admin", "action": "user_updated", "resource_type": "user", "resource_id": 2, "ip_address": "203.0.113.10" },
    { "id": 36, "created_at": "2026-09-24T12:00:00Z", "username": "admin", "action": "user_deleted", "resource_type": "user", "resource_id": 8, "ip_address": "203.0.113.10" },
    { "id": 37, "created_at": "2026-09-24T10:00:00Z", "username": "olga", "action": "mirror_updated", "resource_type": "mirror", "resource_id": 1, "ip_address": "198.51.100.42" },
    { "id": 38, "created_at": "2026-09-24T08:00:00Z", "username": "olga", "action": "sync_triggered", "resource_type": "mirror", "resource_id": 1, "ip_address": "198.51.100.42" },
    { "id": 39, "created_at": "2026-09-24T06:00:00Z", "username": "admin", "action": "settings_updated", "resource_type": "settings", "resource_id": null, "ip_address": "203.0.113.10" },
    { "id": 40, "created_at": "2026-09-24T04:00:00Z", "username": null, "action": "backup_created", "resource_type": null, "resource_id": null, "ip_address": null },
    { "id": 41, "created_at": "2026-09-23T22:00:00Z", "username": "olga", "action": "login_success", "resource_type": null, "resource_id": null, "ip_address": "198.51.100.42" },
    { "id": 42, "created_at": "2026-09-23T20:00:00Z", "username": null, "action": "login_failed", "resource_type": null, "resource_id": null, "ip_address": "198.51.100.77" },
    { "id": 43, "created_at": "2026-09-23T18:00:00Z", "username": "olga", "action": "logout", "resource_type": null, "resource_id": null, "ip_address": null },
    { "id": 44, "created_at": "2026-09-23T16:00:00Z", "username": "admin", "action": "user_created", "resource_type": "user", "resource_id": 3, "ip_address": "203.0.113.10" },
    { "id": 45, "created_at": "2026-09-23T14:00:00Z", "username": "admin", "action": "user_updated", "resource_type": "user", "resource_id": 4, "ip_address": "203.0.113.10" },
    { "id": 46, "created_at": "2026-09-23T12:00:00Z", "username": "admin", "action": "user_deleted", "resource_type": "user", "resource_id": 9, "ip_address": "203.0.113.10" },
    { "id": 47, "created_at": "2026-09-23T10:00:00Z", "username": "olga", "action": "mirror_updated", "resource_type": "mirror", "resource_id": 2, "ip_address": "198.51.100.42" },
    { "id": 48, "created_at": "2026-09-23T08:00:00Z", "username": "olga", "action": "sync_triggered", "resource_type": "mirror", "resource_id": 2, "ip_address": "198.51.100.42" },
    { "id": 49, "created_at": "2026-09-23T06:00:00Z", "username": "admin", "action": "settings_updated", "resource_type": "settings", "resource_id": null, "ip_address": "203.0.113.10" },
    { "id": 50, "created_at": "2026-09-23T04:00:00Z", "username": null, "action": "backup_created", "resource_type": null, "resource_id": null, "ip_address": null }
  ],
  "settings": [
    { "key": "sync_schedule", "value": "0 4 * * *", "description": "Cron expression controlling when the scheduler triggers a sync.", "updated_at": "2026-09-20T10:00:00Z" },
    { "key": "sync_bandwidth_limit", "value": "5000", "description": "rsync --bwlimit in KB/s; 0 means unlimited.", "updated_at": "2026-09-20T10:00:00Z" },
    { "key": "sync_timeout", "value": "1800", "description": "Maximum seconds a single sync job may run before it is treated as stuck.", "updated_at": "2026-09-20T10:00:00Z" },
    { "key": "sync_on_startup", "value": "false", "description": "Whether the sync service triggers a sync immediately on startup.", "updated_at": "2026-09-20T10:00:00Z" }
  ]
}
```

`$SCRATCH/pr3/tiles.py` is PR 2's tiler, unchanged: copy it from PR 2's plan (`docs/design/2026-09-26-reflection-pr2-plan.md`, Task 8 Step 1).

- [ ] **Step 2: run the screenshots** against this checkout:

```bash
bash "$SCRATCH/pr3/screens_admin.sh" "$PWD"; echo "rc=$?"
```

Expected: 54 `pr3-*.png` files listed (9 pages, 3 widths, 2 themes) and `rc=0`. The script removes every `pr3-*.png` before it renders, so a rerun lists exactly 54 again. A `no screenshot for ...` or `never answered` line means a page did not render; the stub's data file is what to check first.

- [ ] **Step 3: tile the tall pages:**

```bash
rm -rf "$SCRATCH/pr3/tiles" && mkdir -p "$SCRATCH/pr3/tiles"
docker run --rm --network none -u "$(id -u):$(id -g)" -e PYTHONDONTWRITEBYTECODE=1 \
    -v "$PWD/.screenshots:/in:ro" -v "$SCRATCH/pr3/tiles:/out" -v "$SCRATCH/pr3:/tools:ro" bsdmirror-test \
    sh -c 'for f in /in/pr3-*-400.png /in/pr3-*-768.png; do python /tools/tiles.py "$f" "/out/$(basename "$f" .png)"; done'
ls "$SCRATCH/pr3/tiles" | wc -l
```

Expected: one line per 400px and 768px page naming its tiles, and a non-zero count.

- [ ] **Step 4: look.** Open every 1440px PNG and every tile with the Read tool. Check each item below, in both themes. Anything that doesn't read goes back to its owner (web-designer for CSS and tokens, developer for `admin.js`), and Steps 2 to 4 run again after the fix.
  - **Sidebar (1440 and 768):** the mark (glyph in the text colour, axis in the accent) and "BSD Mirror" in the display face; all seven items with icons, since the stub user is an admin; the active item on the raised surface with a 3px accent bar at its left edge; the user block and Logout with its icon at the bottom.
  - **Sidebar (400):** a horizontal bar: the mark, the items with icon and label, then the avatar and Logout, reachable by scrolling; no section titles; nothing hidden.
  - **Header:** the page title in the display face; the toggle shows the moon in light and the sun in dark, before "View Public Site".
  - **Dashboard:** five tiles, values in Instrument Sans (not mono, not the display face); the disk tile's meter at 91% in the amber band with the tick at 85%, its "91% used" pill in the error tint; the health card with its "Failing" pill, the clock on the last-run line, and the four lists with close, skip, warning and check icons in their colours; Recent Sync Jobs with one pill per status (completed green, running amber, failed red, pending blue, cancelled neutral) and the warning icon on "1,500 deleted"; Recent Activity with an icon per action.
  - **Mirrors:** three pills (active, syncing, error), one dot each and none doubled; sizes and times right-aligned in mono.
  - **Sync failures:** the two tiles with close and check icons; numbers right-aligned; the error column as code blocks on the raised surface.
  - **Protected paths:** the protection pills including a neutral "Unknown"; the tag pills, "At risk" in amber with no emoji; the location chips on the raised surface; OpenBSD's "Unavailable" card; the pattern groups below.
  - **Users:** role pills (admin blue, the others neutral), status pills, "Add User" with its plus icon, Edit and Delete as secondary and danger buttons.
  - **Audit logs:** 50 rows, IPs as code, the table header on the raised surface.
  - **Settings:** fields on the raised surface with the strong border; the Save button.
  - **Login:** a centred card with the mark, "BSD Mirror Admin" in the display face, the form, and the toggle in the card's top-right corner.
  - **Modal and toasts:** the scrim; the modal on the surface with 14px corners and an icon close button; the status pill in the facts grid; the error and output panes in mono; three toasts with check, close and info icons.
  - **Spacing and type:** 20px content padding, 14px panel gap, no clipped text at 400px.
  - **Dark:** every surface dark, text light, the accent `#FF5A60`, no orange left anywhere. **Light:** the ground `#ECEEF1`, cards white, the accent `#C8232C`.
  - The stills force reduced motion, so no pill ring or transition is caught mid-way; the focus ring is not visible in stills and is pinned by `tests/test_focus_ring.py`.

- [ ] **Step 5: share.** Send the user these with SendUserFile, and say what was checked:
  - the 1440 dashboard in light and in dark;
  - the login card in both themes;
  - the first tile of the 400px dashboard in both themes;
  - the modal-and-toasts page at 1440 in dark;
  - protected paths at 1440 in light.

  Offer the rest on request. If SendUserFile is unavailable, give the user the paths.

  Rerun this task after any review fix in Task 7 that touches `frontend/public`.


### Task 7 (controller): Gate, review, pull request, merge and deploy

This may run in a later session. Recreate any `$SCRATCH` script from the task that defines it:
- `screens_admin.sh`, its stub server, its data file and `tiles.py` are in Task 6;
- `serve_production.sh` and `deploy_and_verify.sh` are in PR 1's plan (`docs/design/2026-09-25-reflection-pr1-plan.md`, Task 1 Step 5 and Task 8 Step 7).

**No soak period.** Spec section 8 holds PR 2 back for a week after PR 1a; PR 3 needs no extra wait, because every CSS and JS file already revalidates. PR 2 deployed on 2026-09-27, so PR 3 may deploy as soon as it is merged and its merge commit's CI has passed.

**`deploy.sh` is one deploy behind itself.** Task 1 adds `/js/theme-init.js` to `scripts/deploy.sh`'s console probe list, but the deploy that ships PR 3 runs the previous deploy's `deploy.sh`, so its console probe still requests the old five paths. That is not a failure. The new list takes effect for the deploy after this one.

- [ ] **Step 1: the full gate.** Run each and paste its summary line and `rc`:
  - the whole suite: `docker compose run --rm -T test; echo "rc=$?"`
  - the lint pair on `.`
  - shellcheck (Task 1 touches `scripts/deploy.sh`)
  - `docker compose config -q; echo "rc=$?"`

  Every `rc` must be 0. If `ruff format --check .` flags a file this branch did not touch, report the file and stop.

- [ ] **Step 2: serve the production profile locally.** Only a comment in `nginx/nginx.conf` changed, but the console's page now loads `theme-init.js`, eleven icons are new, and seven font files are gone. `serve_production.sh` already probes `/admin/`, `/admin/css/admin.css`, `/admin/js/admin.js` and one font; add the paths PR 3 changes:

```bash
bash "$SCRATCH/pr1/serve_production.sh" "$PWD" /js/theme-init.js /css/tokens.css /css/fonts.css \
    /img/icons/warning.svg /img/icons/skip.svg /img/mark-glyph.svg /fonts/inter-latin.woff2
```

  Expected:
  - `nginx -t` passes;
  - `/js/theme-init.js`, `/css/tokens.css` and `/css/fonts.css` answer `200  cc=no-cache`;
  - `/img/icons/warning.svg`, `/img/icons/skip.svg` and `/img/mark-glyph.svg` answer `200  cc=max-age=604800,public, immutable`;
  - `/fonts/inter-latin.woff2` answers `404`: the file is gone, and a missing font is a 404, not a page;
  - `/admin/` answers `200  cc=no-cache` with `robots=noindex, nofollow`;
  - every row shows `security=5/5`;
  - the rest is as PR 1's Task 1 Step 5 lists: pages, CSS and JS `no-cache`; fonts and images `immutable`; missing CSS, JS and images are 404s; the admin assets 25/25 200s.

- [ ] **Step 3: two reviews, in parallel, both read-only.**
  - **`appsec-reviewer`** on `git diff main...HEAD`, focused on:
    - whether anything in the new markup, CSS or `admin.js` needs a CSP exception (an inline style, an inline handler, a `data:` URI, a third-party request), and that `admin.js` writes no element style anywhere;
    - every new DOM write in `admin.js`: the theme attribute, the toggle's class and `aria-label`, the toast's class, and that every interpolation still goes through the `html` template;
    - the theme code's storage handling (the shared `theme` key, values restricted to `light`/`dark`, try/catch around every access), and that nothing reads the token key differently;
    - the nav links' `href`s and the `preventDefault()` in the delegation, and the dialog attributes;
    - the mask `url()`s and the `data-percent` meter rules (every one a same-origin file or a static width);
    - the deleted font files: nothing still references them;
    - the `deploy.sh` line and the nginx comment.
  - **A final code review of the whole branch** (`superpowers:code-reviewer`), for cross-task consistency: this plan against the files, the tests against the files, both themes of the console, and anything that would break CI or the deploy.

  Route each finding to its owner, and re-run Step 1 after any fix. Re-run Task 6 if a fix touches `frontend/public`, and Step 2 if one touches `nginx/`.

- [ ] **Step 4: push and open the pull request.**
  - Write the body to `$SCRATCH/pr3/body.md`, with no attribution lines. It gives:
    - the summary: the admin console in the Reflection style, in light and dark, following the site's saved theme;
    - the changes by area: the theme plumbing, the plumbing fixes, the icons, the tokens and the legacy block, `admin.css`, the `admin.js` markup, Inter, `deploy.sh` and the nginx comment, the tests;
    - the evidence from Steps 1 to 3 and Task 6;
    - what was not checked: browsers other than Chromium; live motion (the stills force reduced motion); the console against the real API, which the deploy's own checks and Step 7's hand checks cover only as far as the login page, since no credentials are entered by the session;
    - the note that `deploy.sh`'s console list takes effect one deploy later;
    - the decisions the user approved with this plan, and the choices the plan made;
    - follow-ups:
      - an admin-only gate on the `settings` route, which the nav already hides from non-admins;
      - a re-render of `#app` wipes any open toast or modal; a container outside `#app` would keep them;
      - the modal now announces itself as a dialog but moves no focus in on open and restores none on close; a focus trap and focus return complete that contract;
      - add PR 3's new node suite to CI's no-skip `REQUIRED` list (`tests.test_admin_theme`), a workflow edit the user applies by hand, together with PR 2's three;
      - PR 2's leftovers: route `copyRsync` through the guarded `copyUrl`, and pin `index.html`'s `<symbol>` geometry to the mark SVGs;
      - the file maps in `.claude/agents/web-designer.md` and `devops-sre.md`, which the user maintains;
      - comments in `tests/test_orphan_reaper.py:267` and `tests/test_settings_validation.py:50,177` still cite "the brief" of an earlier piece of work; reword them the next time those files change.

```bash
git push -u origin feat/reflection-admin
gh pr create --base main --head feat/reflection-admin \
    --title "Redesign the admin console" --body-file "$SCRATCH/pr3/body.md"
```

  - Call `get_status` from the `ccd_pr` tools, and `bind_pr` if it does not report the pull request. Offer the user Auto-fix.
  - **Do not poll CI.** Auto-fix wakes this session only on failures, merge conflicts and review comments, never on success. So tell the user CI is running, and end the turn. Call `get_status` once when the user returns, or when a `<ci-monitor-event>` arrives.

- [ ] **Step 5: CI.**
  - **When `get_status` reports every check passing,** confirm that the harnesses ran rather than skipped. Read the run's log once:

```bash
run=$(gh run list --branch feat/reflection-admin --workflow ci.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run view "$run" --log > "$SCRATCH/pr3/ci-$run.log"
grep -oE 'tests/[A-Za-z0-9_/]+\.py [.sFEx]+' "$SCRATCH/pr3/ci-$run.log" \
    | grep -E 'test_(admin_theme|contrast|admin_js_escaping|admin_inline_styles|images|fonts|reduced_motion|focus_ring|deploy_live_headers)\.py'
grep -oE 'tests/[A-Za-z0-9_/]+\.py [.sFEx]+' "$SCRATCH/pr3/ci-$run.log" | awk '$2 ~ /s/'
```

  Expected: each listed file shows only dots. The only skips are the two in `tests/test_health_check_redact.py`, which PR 1's and PR 2's CI had too.

  - **If a check fails,** read it with `gh run view "$run" --log-failed`, and route the failing lines to the owner of the file they point at. After the fix, re-run Step 1, and Task 6 if `frontend/public` changed, then push.
  - An Auto-fix event is routed to the owner the same way, never patched across roles.
  - CI runs Google Chrome where the dry run used Chromium. A contrast probe that measures differently there is a real finding: fix the colour, never the threshold.

- [ ] **Step 6: the merge, with the user's approval.**
  - Ask with AskUserQuestion: merge now, or hold. There is no soak to wait for; the hold is only for the user's own timing.
  - When approved, run `gh pr merge <number> --merge --delete-branch`.
  - **Check CI on the merge commit once,** right before asking to deploy:

```bash
git fetch -q origin
sha=$(git rev-parse origin/main)
gh run list --workflow ci.yml --branch main --limit 5 --json databaseId,headSha,status,conclusion \
    --jq ".[] | select(.headSha == \"$sha\") | \"\(.databaseId) \(.status) \(.conclusion)\""
```

  Expected: one line ending `completed success`. If the run is still going, don't poll: tell the user, end the turn, and check once more when they return. Anything else, stop and report.

- [ ] **Step 7: deploy, with the user's approval.**
  - First check what production runs now, and what changes:

```bash
deployed=$(curl -fsS --max-time 10 https://mirror.kalev.systems/api/health | sed -nE 's/.*"version" *: *"([0-9a-f]+)-.*/\1/p')
git fetch -q origin
echo "deployed: ${deployed:-unknown}"
if [ -n "$deployed" ] && git cat-file -e "$deployed^{commit}" 2>/dev/null; then
    git diff --name-status "$deployed" origin/main -- frontend/public
    echo "count: $(git diff --name-only "$deployed" origin/main -- frontend/public | wc -l | tr -d ' ')"
else
    echo "STOP: the live version names no commit this checkout knows"
fi
```

  Expected:
  - the deployed version: `ff29094` (PR 2's merge), or later;
  - this pull request's files under `frontend/public`: `admin/index.html`, `admin/css/admin.css`, `admin/js/admin.js`, `css/tokens.css`, `css/fonts.css`, `fonts/README.md`, `img/README.md`, the eleven new icons (`A`), and the seven `fonts/inter-*.woff2` files plus `fonts/LICENSE-Inter.txt` deleted (`D`). Call the count N.

  On `STOP`, stop. If `deployed` is older than `ff29094`, production is not running PR 2 and N includes PR 2's files as well; do not treat that as a routine deploy of this PR. Ask the user before going on.

  - **Ask with AskUserQuestion.** Show the exact command, `ssh root@<production-host> 'cd /opt/bsdmirror && scripts/deploy.sh --yes main'`, and what the wrapper adds: the health-timer wait and the redaction.
  - If approved, run `bash "$SCRATCH/pr1/deploy_and_verify.sh" "$PWD" "$SCRATCH/pr3"` with `run_in_background: true`.
  - **If the permission layer refuses it,** nothing in the script ran. Stop, and hand the user the ssh command to run themselves, with a start time clear of the hourly health timer: between about :08 and :50 past the hour (`RandomizedDelaySec=5m`). Carry on with the checks below once they report the result.
  - **Expected in the wrapper's output:**
    - `deploy.sh rc=0`;
    - one `[ OK ]` line per changed file, and the summary naming N files. The eight deleted files read `deleted, no longer serving the old bytes`: the seven `.woff2` files with `(HTTP 404)`, and `LICENSE-Inter.txt` with `(HTTP 200)`, because a path with no static-file extension falls through `location /`'s `try_files` to the SPA shell; `deploy.sh` compares bytes, not status codes, for exactly this reason. The `[ OK ]` strings are coloured; match them ignoring escape codes if you grep the saved output;
    - `[ OK ] all 10 probed paths carry the full 5-header set`;
    - `[ OK ] one Content-Security-Policy value across all probed paths`;
    - `[ OK ] served Content-Security-Policy matches nginx/nginx.conf in this checkout`;
    - `[ OK ] pages, CSS and JS revalidate, fonts stay immutable, and the console loads twice with no 503` (the previous `deploy.sh`'s five-path console list; see the note at the top);
    - `[ OK ] all post-deploy checks passed`, then `DEPLOYED AND VERIFIED`, with `nginx  config applied and gracefully reloaded` (the comment change);
    - under `== live version ==`, the merge commit.

    Paste any `retrying` warnings; they are the retry doing its job.

  **Then check by hand:**

```bash
SITE=https://mirror.kalev.systems
curl -fsS --max-time 10 "$SITE/admin/" | grep -c 'src="/js/theme-init.js"'
curl -fsS --max-time 10 "$SITE/admin/" | grep -c 'data-theme="dark"'
curl -fsS --max-time 10 "$SITE/css/tokens.css" | grep -c 'LEGACY ADMIN'
curl -fsS --max-time 10 "$SITE/admin/css/admin.css" | grep -c 'prefers-reduced-motion'
curl -sS --max-time 10 -o /dev/null -w '%{http_code} %{content_type}\n' "$SITE/img/icons/warning.svg"
curl -sS --max-time 10 -o /dev/null -w '%{http_code}\n' "$SITE/fonts/inter-latin.woff2"
```

  Expected: `1`, `0`, `0`, `1`, `200 image/svg+xml`, `404`.

  **Then look,** in the built-in browser: open `$SITE/admin/`. The login card shows the mark, the wordmark, the form and the toggle, in the theme the browser prefers. Click the toggle: the card switches theme and the icon swaps. Reload: the choice sticks. Take a screenshot in each theme for the user. Do not sign in; the session never enters credentials. Ask the user to look at the dashboard themselves and report anything off.

  If `deploy.sh` exits non-zero, or anything differs, stop. Report the output, and ask the user before any rollback or other production action. The rollback command is the one `deploy.sh` prints.

- [ ] **Step 8: update the memory.** In `bsdmirror-reflection-redesign`, record:
  - that PR 3 is done, with its PR number, merge commit and deploy date, and that the Reflection redesign is complete;
  - that the admin console now follows the shared `theme` key, and that `tokens.css`'s admin layer holds only `--sidebar-width`;
  - that `deploy.sh`'s console probe list gains `theme-init.js` from the next deploy on;
  - the follow-ups from Step 4.
