# Reflection redesign

- **Status:** proposed, 2026-09-25
- **Scope:** public site, error pages, admin console, favicons and mark
- **Direction:** "Reflection", chosen from three proposals on 2026-09-25

## 1. Summary

The site and the admin console get a new visual identity:

- **Palette:** chrome greys with one "daemon red" accent, in a light and a dark theme.
- **Type:** Unbounded for headlines, Instrument Sans for text, JetBrains Mono for URLs and times.
- **Mark:** a new `b|d` mark. In "bsd" the b and the d are mirror images of each other, and the mark keeps them and turns the s into the mirror line.
- **Public-site features:**
  - The mark stands on a reflective floor in the hero.
  - Each OS shows its sync stream from upstream to us.
  - The page moves in a few restrained, CSS-only ways.
- **Admin console:** gets the same system, plus a light theme it does not have today.

**What does not change:** URLs, the API, the CSP and the accessibility bar. The only copy changes are the ones listed in sections 5.1, 5.2 (status wording) and 5.3.

## 2. Decisions already made

| Question | Decision |
|---|---|
| Direction | Reflection |
| Delivery | Three PRs: foundation, then the public site with the error pages, then the admin console (section 11) |
| FreeBSD, NetBSD and OpenBSD logos on the mirror cards | Kept, restyled to fit |
| Admin theme | Light and dark, following the same saved choice as the public site |
| Hero headline | "Every BSD, mirrored." |

## 3. Constraints from the current code

These shape the design. Each was confirmed against the code on 2026-09-25.

1. **CSP.** `nginx/nginx.conf:222` allows `img-src 'self'`, `font-src 'self'`, `style-src 'self'` and `script-src 'self'`, with no `data:` and no `'unsafe-inline'`. Fonts and icons must therefore be same-origin files. Any script that runs before first paint must be an external file.
2. **No `<svg>` or `<img>` in admin markup.** `tests/js/escaping_harness.mjs:93` rejects both in every view the escaping harness renders, which is every admin view except the login page. The contrast harness renders the login page. For consistency, every admin icon and the admin mark are CSS masks on `<span>` elements (section 4.7), the login page included.
3. **The contrast tests pin the current design in detail.** They pin selectors, token lines and structure:
   - Every colour token in a pinned pair must resolve to a 6-digit hex value (`tests/test_contrast.py:186-193, 254-260`).
   - `.header` and `[data-theme="dark"] .header` must each keep a literal numeric `rgba()` background (`:301-312`).
   - `tokens.css` keeps its block structure: three `:root` blocks, one dark block and one admin block (`:225-229`).
   - Several token lines must appear exactly once, for the mutation tests.
   - `tests/test_error_pages_inline_styles.py` parses semantic tokens only in their `var(--c-*)` form, so semantic tokens keep referencing primitives, and primitives hold the hex values.

   The contrast tests are rewritten alongside the CSS in the same commit, never loosened.
4. **Caching.**
   - In `location /` (`nginx/sites/production/production.conf:265-279`), `.css`, `.js`, `.svg` and `.woff2` are served with `expires 7d` and `public, immutable`, and their filenames are unversioned.
   - The HTML pages and everything under `location /admin` (`:183-197`) carry no `Cache-Control` at all, so browsers cache them heuristically.
   - Section 8 changes this in PR 1.
5. **`tokens.css` is shared** by the public site, the admin console and both error pages. The admin console renders from the dark layer plus a small admin layer.
6. **`main.js` rewrites `.status-dot`'s whole `className` every 60 s** and writes theme glyphs (☀/☾), which `tests/js/theme_harness.mjs` pins.
   - `#overallStatus` ships as a hardcoded "All Systems Operational" (`index.html:221-227`).
   - `load()` returns early when the API fails (`main.js:92-93`), so an outage currently shows a false all-clear.
   - `/api/stats/overview` omits disabled mirrors entirely (`backend/app/api/stats.py:21`).
7. **The admin re-renders `#app` on every navigation, and every 30 s on the dashboard** (`admin.js:1834-1838`). Any control, including a theme toggle, must go through the existing `data-action` click delegation (`admin.js:1597-1621`). That delegation passes only `dataset.id` to its handlers.
8. **Fonts follow a documented convention.** `fonts.css` is generated, files are named `<family>-<subset>.woff2`, and `fonts/README.md` records provenance and SHA-256 sums. A file is never replaced in place.
9. **Rate limits cover static files.** Static requests under `location /` fall under `general_limit` (`nginx.conf:231`, 30 r/s per IP; `production.conf:260`, burst 30, nodelay). Rejections are 503s, and no `limit_req_status` is set.
   - A page that revalidates many small files on every view risks a 503, which turns a mask icon invisible.
   - `/admin/*` currently sits under `api_limit` (`production.conf:184`, burst 10), shared with `/api/`; section 8 moves the admin's CSS and JS out of it.
   - `scripts/deploy.sh`'s post-deploy checks go through the public URL, so they count against the same limits.

**Principle.** Keep every id and class name that JS or a test keys on, wherever that component still exists. Rename only what is new or gone.

## 4. Visual system

### 4.1 Colour tokens

Semantic tokens reference primitives (`var(--c-*)`). The primitives hold these hex values. The values give every pair in section 9 at least AA.

| Role | Token | Light | Dark |
|---|---|---|---|
| Page ground | `--bg-primary` | `#ECEEF1` | `#07080B` |
| Surface (cards, panels) | `--bg-card` | `#FFFFFF` | `#101217` |
| Raised surface (table heads, active nav, code, form fields) | `--bg-secondary` | `#F4F5F7` | `#161920` |
| Text | `--text-primary` | `#0C0E12` | `#EDEFF3` |
| Secondary and muted text | `--text-secondary`, `--text-muted` | `#4E5563` | `#A2A9B6` |
| Hairline (dividers, card edges) | `--border-color` | `#D9DDE3` | `#252932` |
| Control border, at least 3:1 (inputs, selects) | `--border-strong` (new) | `#8A919D` | `#5F6673` |
| Accent ("daemon red") | `--accent-primary` | `#C8232C` | `#FF5A60` |
| Text on accent | `--text-on-accent` | `#FFFFFF` | `#16060A` |
| Online | `--status-healthy` | `#1B7A48` | `#5AD69A` |
| Syncing, warning | `--status-syncing` | `#8C5A00` | `#F2C14E` |
| Error | `--status-error` | `#B42318` | `#FF7B72` |
| Info | `--status-info` | `#1F5FA8` | `#7CB7F2` |
| Incomplete | `--status-incomplete` (new) | `#6B3FA0` | `#C4A3F0` |
| Online tint | `--status-healthy-bg` | `#E3F4EA` | `#0F2A1D` |
| Syncing tint | `--status-syncing-bg` | `#FBF0DA` | `#2A2210` |
| Error tint | `--status-error-bg` | `#FBE4E2` | `#2D1415` |
| Info tint | `--status-info-bg` | `#E3EEFA` | `#10233A` |
| Incomplete tint | `--status-incomplete-bg` (new) | `#EFE7F8` | `#241A33` |
| Idle stream line, at least 3:1 | `--stream-line` (new) | `#7F8794` | `#5C6370` |

Non-colour tokens:

| Token | Value |
|---|---|
| `--font-display` (new) | Unbounded, with a system sans fallback |
| `--font-sans` | Instrument Sans, with a system sans fallback |
| `--font-mono` | JetBrains Mono, with a system mono fallback |
| `--radius-sm`, `-md`, `-lg`, `-xl`, `--radius-full` (new) | 8, 10, 12, 14, 999px |
| `--shadow-card` | Light: `0 1px 2px rgba(12,14,18,.06), 0 14px 30px -18px rgba(12,14,18,.35)`. Dark: `0 1px 2px rgba(0,0,0,.45), 0 16px 34px -18px rgba(0,0,0,.85)` |
| `--shadow-card-hover` | The same shape with the second layer's blur at 38px |
| `--sheen`, `--sheen-blend` (new) | Light: `rgba(255,255,255,.85)`, `soft-light`. Dark: `rgba(255,255,255,.16)`, `screen` |
| `--scrim` (new) | Light: `rgba(12,14,18,.45)`. Dark: `rgba(0,0,0,.6)` |
| `--transition-fast`, `--transition-base`, `--transition-lift` (new) | 150ms, 250ms, 400ms |
| `--container-max` | 1180px (was 1200) |
| `--header-height` | 64px |
| `--sidebar-width` | 188px (was 260), from PR 3 |

What happens to the existing tokens:

| Token | Fate |
|---|---|
| `--accent-gradient`, `--accent-secondary` | Removed in PR 2. The site drops gradient text and has one accent. Their contrast checks go with them. `admin.css` uses neither. |
| `--freebsd-color`, `--netbsd-color`, `--openbsd-color` | Removed in PR 2. The cards carry each project's logo instead. |
| `--terminal-bg`, `--terminal-prompt`, `--terminal-text` | Removed in PR 2. The access rows use `--bg-secondary` and the text colours. |
| `--status-healthy-tint`, `--status-syncing-tint`, `--status-error-tint` | Removed in PR 2, replaced by the `-bg` tints above. |
| `--bg-tertiary`, `--status-error-text`, `--status-info-text` | Kept only in PR 2's legacy admin block (section 7). Removed in PR 3, where pills use `--status-*` on `--status-*-bg` and fields use `--bg-secondary`. |
| Every other existing token | Kept, with the values above |

### 4.2 Typography

| Role | Face | Use |
|---|---|---|
| Display | Unbounded 600/700 | h1, section h2s, card titles, wordmark |
| Text | Instrument Sans 400/500/600 | Body text and UI. Figures such as stat and KPI values use Instrument Sans 600, never the display face |
| Mono | JetBrains Mono 500 | URLs, hostnames, times and sizes in tables |

- **Sizes:**
  - h1: `clamp(32px, 7.4vw, 70px)`, line-height .98, letter-spacing -0.04em.
  - Body: 14–15.5px, line-height 1.5.
- **Numerals:** `tabular-nums` only in columns.
- **Self-hosting:** Unbounded and Instrument Sans are added as variable woff2 files, in the latin and latin-ext subsets, following section 3's font convention.
  - The regeneration recipe in `fonts/README.md` records the latin/latin-ext subset filter, with OFL license files and SHA-256 sums.
  - JetBrains Mono's files stay.
  - Inter is removed in PR 3, once nothing uses it.
- **Error pages:** they use the system font stack only (section 5.3).

### 4.3 Layout

- **Public site:** max content width 1180px, 20px side gutter, sections separated by 72px on desktop and 48px under 640px.
- **Admin console:** sidebar 188px, content padding 20px, panel gap 14px.

### 4.4 Motion

All motion is CSS and none of it hides content: nothing starts at `opacity: 0`.

| Where | What | Timing |
|---|---|---|
| Hero mark | A sheen sweeps across the mark and its reflection | 7.5s, `cubic-bezier(.2,.8,.2,1)`, infinite, idle for the last 45% of each cycle |
| Stream row, syncing only | Dots flow from upstream to mirror | 0.9s linear, infinite |
| Status pill, syncing only | The dot's ring pulses outward | 1.5s, infinite |
| Cards | Lift 3px, with `--shadow-card-hover`, on hover | `--transition-lift` |
| Buttons | Lift 1px on hover | `--transition-base` |
| Theme toggle | The icon rotates -18° on hover | `--transition-lift` |

- **Explicit transitions:** `transition: all` is not used. Every transition names its properties.
- **Settle within the harness windows:** colour, background and border transitions use `--transition-fast` (150ms). The theme switch uses at most `--transition-base` (250ms). The contrast harness samples 250ms after a hover and 450ms after a theme switch. Transforms and shadows may take longer, because the harness does not measure them.
- **Reduced motion:** `@media (prefers-reduced-motion: reduce)` turns every animation and transition off. For that rule to win, no animation may be set as an inline style. `admin.js:336` sets the toast's animation inline today; PR 3 moves it to a class.

### 4.5 The mark

The mark is drawn on a 64×64 grid:

- **b:** a vertical stem plus a ring.
- **d:** the same shape mirrored (`translate(64 0) scale(-1 1)`).
- **Axis:** a vertical bar centred on x = 32.

| Size | Stem (x, width, y) | Bowl centre | Outer and inner radius | Axis (x, width, y, corner radius) |
|---|---|---|---|---|
| Regular (25px and larger) | 5, 7, 6–58 | (17, 46) | 12 / 6 | 30.7, 2.6, 3–61, 1.3 |
| Small (24px and smaller, favicons) | 4, 8, 8–57 | (16, 46) | 11 / 4.2 | 30, 4, 5–59, 2 |

The small geometry leaves 3 grid units between each bowl and the axis, so the parts do not merge at 16px.

- **Colours:** the glyph uses `--text-primary` and the axis uses `--accent-primary`.
- **Hero glyph:** filled with a vertical gradient, `#0C0E12`→`#4A515E` in light and `#EDEFF3`→`#8D95A3` in dark.
- **Files:**
  - `img/mark-glyph.svg` and `img/mark-axis.svg`: single-colour shapes, used as CSS masks by the admin console.
  - `index.html` and the error pages use an inline `<symbol>` of the same geometry, styled with CSS classes.

### 4.6 Favicons

- **Tile:** a rounded square at (1, 1), 62×62, rx 14, with a 2-unit edge. The small mark sits inside it, scaled to 78% and centred, with a 7-unit inset.
- **`img/favicon.svg`** keeps its name, so the existing references and the deploy probe stay valid.
  - Light: tile gradient `#FFFFFF`→`#CDD2DA`, glyph `#0C0E12`, axis `#C8232C`, edge `#C4C9D1`.
  - Dark, via one `@media (prefers-color-scheme: dark)` rule inside the SVG: tile `#1C1F26`→`#07080B`, glyph `#EDEFF3`, axis `#FF5A60`, edge `#2C313A`.
  - Presentation attributes only, no `style=` attributes.
  - A harness check (section 10) tests in Chromium whether the dark rule applies when the file is served with the production CSP header. If it does not, the file ships as the light tile only, which reads on both tab themes because of its edge.
- **`favicon.ico`** at the site root, holding 16, 32 and 48px PNGs.
- **`img/apple-touch-icon.png`**, 180px, light tile.
- **Generation:**
  - The PNG and ICO files are rendered from the SVG by a one-off `docker run` of the test image. The configured test service can't do this: it mounts the repo read-only and has no network.
  - The command first builds and tags the image from this checkout with `docker build -f Dockerfile.test -t bsdmirror-test .`, because `docker compose build` names the image after the checkout's directory, and a worktree would otherwise run an older `bsdmirror-test`. It then runs `docker run --rm -u "$(id -u):$(id -g)" --security-opt seccomp=unconfined -e HOME=/tmp -v "$PWD:/repo" -w /repo bsdmirror-test python scripts/render_icons.py`. Chromium needs the seccomp and HOME settings, as the test service in `docker-compose.yml` already gives it.
  - `scripts/render_icons.py` belongs to devops-sre, like the rest of `scripts/`.
  - Headless Chrome renders the PNGs, and a short Python packer builds the ICO.
  - The command is recorded in `img/README.md`, and the outputs are committed.
  - The rendered 16px PNG is checked by eye, since the bowl-to-axis gap is only about 0.6px at that size.
- **Linked from:** `index.html`, `admin/index.html` and both error pages, all four in PR 1. The error-page test counts only `rel="stylesheet"` links, so a `rel="icon"` link does not disturb it.

### 4.7 Icons

- **Set:** one SVG file per icon under `img/icons/`, drawn on a 24px grid with 1.6px round strokes. The icons are dashboard, mirrors, sync-failures, protected-paths, users, audit-logs, settings, sun, moon, copy, sync, arrow-right, check, close and info.
- **Rendering:** every icon is a `<span class="icon icon-NAME" aria-hidden="true">` styled with `background-color: currentColor` and `mask: url(/img/icons/NAME.svg) center / contain no-repeat`. The rule also sets the `-webkit-mask` equivalent and uses absolute URLs.
- **Why masks:** they keep inline SVG out of admin markup (constraint 2), satisfy `img-src 'self'` (constraint 1), and let the icon take the text colour.
- **Caching:** icon files stay long-cached (section 8). A changed icon ships under a new filename.
- **Class names in `admin.js` are always written in full.** `class="icon icon-copy"`, or a lookup table of full class strings, never `icon-${name}`. The inline-styles test strips interpolations, and would otherwise see an undefined `icon-` class.
- **Labels:** every icon sits next to visible text, or inside a control with an `aria-label`.
- **Replaces:** the emoji now used in the admin navigation, stat cards, health list and toasts.

### 4.8 Status pills and meter

**Pills** are shared by the public site and the admin console. Each is a dot plus a word, coloured with the text token on its tint:

| Variant | Colours | Used for |
|---|---|---|
| online | `--status-healthy` on `--status-healthy-bg` | mirror `active`; job `completed` |
| syncing | `--status-syncing` on `--status-syncing-bg` | mirror `syncing`; job `running`; archive "At risk" |
| error | `--status-error` on `--status-error-bg` | mirror `error`; job `failed` |
| info | `--status-info` on `--status-info-bg` | archive "Current"; job `pending` |
| incomplete | `--status-incomplete` on `--status-incomplete-bg` | health check `health-incomplete`. Kept distinct from neutral, so "Incomplete" is never mistaken for "Unknown" (`admin.js:561-568`) |
| neutral | `--text-secondary` on `--bg-secondary` | mirror `disabled` ("Offline"); unknown values; job `cancelled` |

**Disk meter.** The accent is red, so it cannot also mean "normal". The fill therefore carries severity in neutral, amber and red:

| Part | Token |
|---|---|
| Fill below 85% | `--text-secondary` |
| Fill from 85% | `--status-syncing` |
| Fill from 95% | `--status-error` |
| Track | `--border-color` |
| Tick at 85% | `--text-primary`. It is 2px wide and extends 4px above and below the track, so it always shows against the card, whatever fill is under it |

- **The value is also text.** The tile keeps printing the percentage and today's sub-line wording, so the meter supplements the text rather than being the only way to read the value.
- **No data.** The backend sends `percent_used`, `total_bytes` and `free_bytes` as `null` when disk usage is unavailable (`admin.py:583-586`). The tile then shows today's "Unknown" and "Disk capacity unavailable", and the meter is left out, exactly as the trend badge already is (`admin.js:462-470`).
- **Contrast:** every fill is at least 3:1 against the track in both themes. The track itself is only 1.36:1 (light) and 1.29:1 (dark) against the card.
- **Thresholds:** the 85% threshold keeps its existing name, `DISK_USAGE_WARNING_PERCENT` (`admin.js:48`). The escaping harness references it by that name (`escaping_harness.mjs:51`). A new constant, `DISK_USAGE_CRITICAL_PERCENT = 95`, matches the default `DISK_CRIT_PCT` in `scripts/health_check.sh`.

## 5. Public site (PR 2)

### 5.1 Page structure

From top to bottom:

1. **Header:**
   - The mark and "BSD Mirror".
   - Navigation: Mirrors (`#mirrors`), Status (`#status`), Access (`#access`, a new anchor) and About (`#about`).
   - The theme toggle, `#themeToggle`: an icon button showing a moon in light and a sun in dark, with the same `aria-label`s as today.
   - The Admin link, `.nav-admin`.
   - The header stays sticky, with a literal `rgba()` background (constraint 3).
2. **Hero** (copy changes marked "new"):
   - Eyebrow "FreeBSD · NetBSD · OpenBSD" (new).
   - h1 "Every BSD, mirrored." (new).
   - Lede "High-speed access to releases, packages and documentation, synced from the official upstream mirrors." (new).
   - Three stats: total size (`#statSize`), files (`#statFiles`, new, from `totals.files`) and last sync (`#statLastSync`).
   - Two actions: "Browse mirrors", an anchor to `#mirrors`, and "Copy rsync URL", a button with `data-copy="rsync-root"`.
   - The art: the mark, the floor, its reflection and the sheen, all `aria-hidden`.
   - The static "3 BSD Distributions" stat is removed. It never left its loading state (`main.js:150-173`).
3. **Streams:** one row per mirror, `#<os>-stream`, showing:
   - the name
   - the static word "Upstream"
   - a line
   - this mirror's own hostname, filled by the hostname fill (section 5.2)
   - a pill

   The upstream's own host is not shown; getting it would take a new API call. The line follows the pill's state:
   - online: a solid `--stream-line`
   - syncing: flowing dots
   - error: a broken dashed line with a ×
   - neutral: the line is hidden
4. **Mirror cards**, `.mirror-card[data-mirror]`, three of them. Each has:
   - The project's logo in a 40px raised tile.
   - The name in Unbounded 600, and the pill, `#<os>-status`.
   - The description, size (`#<os>-size`) and last sync (`#<os>-sync`).
   - "Browse files", the primary button, linking to `/<OS>/` as today.
   - The per-mirror copy button. Its opening tag stays byte-identical, and the three stay in `.mirror-actions` in FreeBSD, NetBSD, OpenBSD order: `tests/test_public_page_csp.py`'s negative control matches that exact string, and its harness selects the buttons by index.
     - Opening tag: `<button class="btn btn-secondary" data-copy-rsync="FreeBSD">`.
     - Label: "rsync URL" (new; was "Copy rsync URL").
5. **Status and access**, `#status` and `#access`:
   - The overall status card, `#overallStatus`: a dot, a title and a sentence.
   - An HTTPS row (`data-copy="https-root"`, which copies `https://<host>/`) and an rsync row (`data-copy="rsync-root"`, which copies `rsync://<host>/`), each with a copy button.
6. **About:** today's copy.
7. **Footer:** the copyright line and `.footer-version`.

**Breakpoints:**
- **980px and wider:** the hero is two columns and the cards are three across.
- **Under 980px:** the cards use `repeat(auto-fit, minmax(260px, 1fr))`, going to two across and then one.
- **Under 640px:**
  - The hero stacks, with the art first.
  - The navigation collapses to the toggle and the Admin link.
  - Stream rows drop their "Upstream" and host labels.
  - The access rows stack.

### 5.2 States and behaviour (`main.js`)

**State model.** Each of `#<os>-status`, `#<os>-stream` and `#overallStatus` carries a `data-state`. CSS keys only off that attribute.

| Situation | `data-state` | Text |
|---|---|---|
| As shipped in the HTML, before any data | `unknown` | Pills "Checking…". Overall title "Checking mirror status…", no sentence |
| API `active` | `online` | "Online" |
| API `syncing` | `syncing` | "Syncing" |
| API `error` | `error` | "Error" |
| API `disabled`, or a mirror absent from a successful response (disabled mirrors are omitted) | `disabled` | "Offline" |
| Any other API value | `unknown` | "Unknown" |
| The API request fails | Overall `unknown`; mirror pills keep their last state | Overall title "Status unavailable", sentence "The status service didn't answer. The mirrors themselves may still be reachable." |

On the first failure, the pills stay "Checking…".

**The overall card** after a successful load, checked in this order:

| Mirrors | `data-state` | Title | Sentence |
|---|---|---|---|
| Any in error | `error` | "Degraded service" | "OpenBSD is experiencing issues." (names the failing mirrors) |
| Else any syncing | `syncing` | "Sync in progress" | "NetBSD is syncing now." |
| Else every mirror online | `online` | "All systems operational" | "All mirrors are synchronized and available." |
| Else at least one online, others offline or unknown | `online` | "Systems operational" | "Some mirrors are offline; the rest are available." |
| Else, with none online (every mirror offline, unknown or absent) | `disabled` | "No mirrors online" | "No mirror is reporting as online right now." |

The last row replaces today's behaviour, where `every()` over an empty list shows "All Systems Operational" with no mirrors at all.

**Unchanged:**
- the API calls and the 60-second refresh
- the footer version and the toast
- the per-mirror `data-copy-rsync` buttons

**Changes:**
- **Data attributes, not class rewrites.** `MirrorStatus` writes `data-state` and text instead of rewriting class names. It removes the `.pulse.style.background` writes, leaving the page with no style writes from JS.
- **The new files stat.** `#statFiles` is filled from `totals.files`.
- **New copy buttons.** The copy handler also handles the `data-copy` values above.
- **Hostname fill.** It still fills `#hostname` and `#rsynchost`, and now also every `[data-hostname]` element, which is how the stream rows get the host.
- **Status wording.** The pills say "Syncing" instead of "Syncing...".
- **Theme icon.** `ThemeManager` stops writing glyphs. It sets `data-icon="sun|moon"` on `.theme-icon`, and the icon is a mask. Its `aria-label`s, storage key, system-preference fallback and `theme-init.js` are unchanged.

### 5.3 Error pages

`404.html` and `50x.html` each get:
- the mark, as inline SVG
- a headline: "Page not found" (new) or "Something went wrong on our side" (new)
- one explanatory sentence
- a "Back to the mirror" link

They keep the constraints `tests/test_error_pages_inline_styles.py` pins:
- They load only `tokens.css` and `error.css`.
- They carry no `data-theme`.
- They take dark mode from `error.css`'s media block, which must equal the dark token values.

Because `fonts.css` stays out, error pages use the system font stack throughout. This is deliberate: they must render when everything else is failing, and the mark and colours carry the identity.

## 6. Admin console (PR 3)

### 6.1 Shell and components

- **Sidebar:**
  - The mark (two masks: glyph in text colour, axis in accent) and "BSD Mirror".
  - Navigation with icons for Dashboard, Mirrors, Sync failures, Protected paths, Users, Audit logs and Settings. The admin-only items stay admin-only.
  - The active item gets `--bg-secondary` and a 3px accent bar at its left edge, echoing the mark's axis.
  - The signed-in user and Logout sit at the bottom.
- **Under 768px:** the sidebar becomes a horizontal, scrollable bar. It holds the mark, the navigation items, then the user's avatar and Logout at its end. Today the sidebar is simply hidden, with no way to open it (`admin.css:815`; nothing ever adds `.open`).
- **Header:** the page title in Unbounded 600 at 25px; actions include the theme toggle.
- **Stat cards become KPI tiles:**
  - A label, the value in Instrument Sans 600 at 27px, and a sub-line.
  - The disk tile adds the meter from section 4.8. The existing `stat-card-trend` badge stays.
- **Status badges become the pills from section 4.8**, including every job-status value (`completed`, `failed`, `running`, `pending`, `cancelled`).
- **Tables:** a `--bg-secondary` header row and hairlines; numbers right-aligned in mono.
- **Forms:** fields on `--bg-secondary`, with a 1px `--border-strong` edge and a 2px accent focus ring. The edge reaches at least 3:1 against the surface (WCAG 1.4.11). Fields always sit on a card, panel or modal, never directly on the page ground, where `--border-strong` would reach only 2.73:1.
- **Buttons:**
  - Primary: accent background with `--text-on-accent`.
  - Secondary: surface with `--border-strong`.
  - Danger: `--status-error` text on `--status-error-bg`.
- **Modal:** surface, 14px radius, `--scrim` behind. **Toasts:** surface with an icon mask for success, error or info. The toast animation moves from an inline style to a class (section 4.4).
- **Login:** a centred card with the mark, the wordmark, the form and its own theme toggle.
- **Code:** code chips and log blocks on `--bg-secondary`, in mono.

### 6.2 Light theme

- **`admin/index.html`:**
  - Drops the static `data-theme="dark"` and keeps `data-surface="admin"`.
  - Loads `/js/theme-init.js` before its stylesheets. One `theme` key in localStorage means one choice across the site and the console.
- **The toggle, in `admin.js`:**
  - It is a `data-action="toggleTheme"` button. The name follows the existing camelCase actions.
  - It is handled in the existing click delegation. The handler finds its own button, because the delegation passes only `dataset.id`.
  - It flips `html[data-theme]` and saves the choice, with storage access in try/catch.
  - The icon and `aria-label` are rendered from `html[data-theme]` on every render, so a 30-second re-render cannot undo them.
  - Like the public site, the console follows the operating system's preference until the user chooses. A `matchMedia` listener does this; it is registered only when `window.matchMedia` exists. It updates the toggle's icon and `aria-label` exactly as the click handler does, because only the dashboard re-renders on its own.
  - Every `document.documentElement` access is guarded, so the harness sandboxes, which have none, still load.
  - The login page renders the toggle too.
- **Colours** come from the shared light and dark layers (section 7).

## 7. Token architecture and migration

- **Layers:** `tokens.css` keeps its structure: primitives, then invariants, then light (`:root`), then dark (`[data-theme="dark"]`), then admin (`[data-surface="admin"]`).
- **PR 2:**
  - It replaces the primitives and the light and dark values with the ones in section 4.1, and removes the tokens section 4.1 retires.
  - To keep the admin console looking exactly as it does today until PR 3, it also adds a commented "legacy admin" block to the admin layer. That block copies the 28 tokens `admin.css` uses at their current resolved values, including `--font-sans` for Inter.
  - The legacy block holds raw 6-digit hex values, because the old primitives are gone. It is the one stated exception to "semantic tokens reference primitives", and it lives only in the admin layer, which the error-page test does not parse.
  - The admin console keeps its static `data-theme="dark"` until PR 3.
  - `test_light_dark_admin_actually_differ` (`test_contrast.py:267-272`) relies on `--accent-secondary`, which PR 2 retires. PR 2 re-points it at a colour the legacy block still sets.
- **PR 3:**
  - It deletes the legacy block. The admin layer then holds only non-colour tokens, such as `--sidebar-width`, so both admin themes take their colours from the shared layers.
  - `tests/test_contrast.py` then models admin light as the light layer plus the admin layer, and admin dark as light plus dark plus admin. Every admin pair is checked in both themes.
  - The guard that the admin layer really changes something is replaced by one that asserts the admin layer sets no colour tokens.
- **Hex only in pinned pairs:** every token used in a contrast-pinned pair stays a 6-digit hex value reached through a primitive (constraint 3).

## 8. Caching

PR 1 changes `nginx/sites/production/production.conf`, in both `location /` and `location /admin`, as follows:

| Responses | Header | Why |
|---|---|---|
| HTML pages (`/`, `/index.html`, `/admin/`), `.css` and `.js` | `expires epoch`, which emits `Cache-Control: no-cache` without `add_header`, so the security-header snippets need no re-including | Browsers keep the files but revalidate on every load; an unchanged file costs a 304. A deploy takes effect on the next page load |
| The error pages | Unchanged | nginx's `expires` applies only to 2xx and 3xx responses, and the error pages are served as 404 and 5xx. A direct request for `/50x.html` hits `location = /50x.html` (`production.conf:288-290`), which also stays as it is. Their CSS revalidates like all CSS |
| `.woff2`, `.svg`, `.png`, `.ico` | `expires 7d` and `public, immutable`, as today | These change only under a new filename, so revalidating them on every view would only add requests against `general_limit` (constraint 9). The one exception is `favicon.svg`, whose name is fixed: its PR 1 redesign reaches returning visitors within 7 days |

**Soak period.** Copies of `.css` and `.js` fetched before PR 1 deploys stay fresh in visitors' browsers for up to 7 days. **PR 2 therefore deploys no earlier than 7 days after PR 1.** PR 3 needs no extra wait: by then, every CSS and JS file revalidates.

**Rate limits.** `/admin` sits under `api_limit` (`production.conf:184`, burst 10), which it shares with `/api/`. Once the admin's CSS and JS revalidate on every load, a dashboard load puts its asset requests on that zone on top of its own API calls. PR 1 therefore adds one location block that serves both `/admin/css/` and `/admin/js/` under `general_limit`, like every other static file. `/admin/` itself and `/api/` stay where they are.

**Tests:**
- A static test asserts the directives per location and file type in `production.conf`, including the `/admin` asset limits.
- `scripts/deploy.sh`'s post-deploy probe checks the live headers:
  - `/`, `/css/style.css`, `/admin/`, `/admin/css/admin.css` and `/admin/js/admin.js` answer with `Cache-Control: no-cache`.
  - One font file still answers with `immutable`, to catch the opposite mistake.
  - The admin page and its assets, loaded twice in a row, get no 503s.
  - `/admin/js/admin.js` joins `verify_security_headers`' path list (`deploy.sh:1682`), because it now has its own location block.
- **The deploy's own checks get a retry.** `verify_frontend_assets` fetches every changed file under `frontend/public` twice, with no pause (`deploy.sh:1125-1128, 1551-1608`), and `verify_security_headers` follows immediately. PR 1 changes about 33 files there, roughly 66 requests against a burst of 30. A 503 there would report a good deploy as failed.
  - PR 1 makes these checks, and the new probes above, retry a 503 up to three times with a short pause. This is the pattern `deploy.sh` already uses for `/api/auth/token` (`:1402-1408`).
  - Each fetch takes the body and the status code from a single `curl` (`-o` plus `-w '%{http_code}'`), and a retry repeats that whole request. Today `verify_frontend_assets` hashes one request and reads the status from a second (`:1587-1592`). A 503 serves `50x.html`, so a 503 on the hashed request would be misreported as "SERVING STALE CONTENT".
  - Any other status still fails at once.
- A CI probe would need a workflow edit, which you apply by hand, like the pending `ruff format --check` step. The deploy probe covers it without one.
- `nginx -t` runs in CI and during the deploy.

**Housekeeping in PR 1:** stale references are corrected:
- `fonts/README.md` cites `sites/default.conf:181`.
- `nginx.conf`'s comments give old line numbers for the `.pulse` writes in `main.js` and the admin toast's inline animation. PR 1 updates the numbers.
  - The `.pulse` writes stay until PR 2, which removes that part of the comment.
  - The toast write stays until PR 3, which removes the rest.
  - Both removals are devops-sre edits inside those PRs.
- The same comments say "exactly one script" per page; PR 1 corrects that.

## 9. Accessibility

- **Contrast:** text reaches 4.5:1 and indicators and control boundaries 3:1, in both themes, on both the public site and the admin console. The pinned pairs cover:
  - text, secondary text and accent text on the surface and on the ground
  - button labels on the accent
  - each pill's text on its tint
  - table header text and code text on `--bg-secondary`
  - `--border-strong` and `--stream-line` against the surface
  - each meter fill against the track, and the meter tick against the card
- **Focus:** every interactive element shows a 2px accent outline at a 2px offset.
- **Status never relies on colour alone:** every pill and every stream row carries a word.
- **Icons:** decorative icons are `aria-hidden`, and icon-only buttons have an `aria-label`.
- **Headings:** one h1 per page, with section h2s.
- **Motion:** reduced motion is honoured, with no inline animations (section 4.4).

## 10. Testing

Each PR updates the tests for what it changes, in the same commit as the change. Every PR runs the full suite, `ruff`, shellcheck, `nginx -t` and `docker compose config` in Docker before opening.

- **Static contrast**, `tests/test_contrast.py`:
  - the new pair lists; admin pairs are checked in both themes from PR 3
  - structural pins updated to the new layers
  - mutation strings pointed at the new token lines
  - the checks for retired tokens removed together with those tokens
- **Dynamic contrast**, `tests/js/contrast_harness.mjs`:
  - probes for the new components
  - the admin fixture rendered in both themes, from PR 3
  - the probe-list pin kept in step
- **Theme**, `tests/test_theme.py` and its harness: the `data-icon` contract replaces the glyph checks; the admin toggle gets harness checks in PR 3.
- **Public states**, a new harness in the `theme_harness.mjs` style:
  - drives `MirrorStatus` through every row of section 5.2's state table and every row of its overall-card table, including an API failure, a missing mirror and no mirror online
  - asserts the resulting `data-state` values and text
- **CSP clicks**, `tests/test_public_page_csp.py`: the three per-mirror buttons keep today's checks, and the `data-copy` buttons are clicked too.
- **Admin escaping**, `tests/test_admin_js_escaping.py` and its harness:
  - class and text pins updated
  - the ban on `<svg>` and `<img>` stays
- **Inline styles and error pages:** the existing rules are unchanged.
- **New checks in PR 1:**
  - A static test on the cache directives (section 8).
  - Nothing under `frontend/public` references `fonts.googleapis.com` or `fonts.gstatic.com`.
  - Every `url(/img/…)` in CSS resolves to a file.
  - Every font file in `fonts.css` exists, with its SHA-256 listed in `fonts/README.md`.
  - The favicon set exists and is linked from all four HTML pages.
  - A harness check serves `favicon.svg` with the production CSP header and renders it as an image on a page set to `color-scheme: dark`, under a dark colour-scheme emulation. It checks that a tile pixel is dark.
    - A control render of the same file without the CSP header must also come out dark. Otherwise a light pixel could come from the embedding page rather than from CSP.
    - The check proves Chromium's behaviour only.
- **Reduced motion:** a static check that every `@keyframes` animation is switched off under reduced motion.
  - From PR 2 it covers `style.css` and `error.css`.
  - PR 3 extends it to `admin.css`, whose `spin` and `slideIn` animations stay until then.
- **Visual check:**
  - Screenshots of both themes at 1440, 768 and 400px, from a one-off headless-Chrome run of the test image (section 4.6), go to `.screenshots/`. PR 1 adds that directory to `.gitignore`.
  - They are shared with you in the session for each PR.
  - The PR description lists what was checked; it cannot host the images.

## 11. Delivery

**Routine per PR:**
1. Each PR gets its own implementation plan, starting with PR 1's.
2. Then a branch, tests in Docker, a PR and its CI.
3. Your approval, the merge, and CI on the merge commit.
4. A deploy clear of the hourly health check.
5. A check that the served files match `main`, including the new `Cache-Control` headers.

Owners follow CLAUDE.md.

| PR | Contents | Owners | Visible change | Earliest deploy |
|---|---|---|---|---|
| 1. Foundation | The cache change, the `/admin` asset limits and their tests (section 8); Unbounded and Instrument Sans self-hosted; the mark files; the favicon set, linked from all four pages; the icon set; the PR 1 checks from section 10; the `.screenshots/` ignore entry; the stale-reference fixes; this spec | devops-sre for nginx, deploy.sh and `scripts/render_icons.py`; web-designer for assets; developer for tests | The favicon | After review |
| 2. Public site | The new tokens, the retired tokens and the legacy admin block; `index.html`; the `style.css` rewrite; the `main.js` state and icon changes; the error pages; the `.pulse` part of the nginx comment; test updates | web-designer, developer; devops-sre for the nginx comment | The whole public site and both error pages | 7 days after PR 1's deploy |
| 3. Admin console | The legacy block removed; `admin/index.html`; `admin.css`; the `admin.js` toggle, class and toast changes; the mask icons; the responsive navigation; Inter removed; the rest of the nginx comment; test updates | web-designer, developer; devops-sre for the nginx comment | The whole admin console, including its light theme | After PR 2's deploy |

## 12. Risks

- **The contrast tests are strict.** Their rewrites are large but mechanical, and each lands in the same commit as the CSS it checks.
- **Returning visitors could see mismatched pages.** PR 1's cache change plus the 7-day soak before PR 2 prevents this.
- **The font files come from Google Fonts' CDN** (SIL OFL). Downloading them needs your OK, and the request will name each file, its source and its size.
- **The favicon's dark-mode rule may not apply under the production CSP header.** The harness checks it in Chromium before deploy; the fallback is the light tile only.
- **Unbounded is wide.** Headline sizes are clamped and checked at 400px.
- **Mask support:** current Chrome, Edge, Firefox and Safari support CSS masks, and the `-webkit-` prefixed properties are included as well.

## 13. Out of scope

- **Backend:** API or backend changes.
- **Admin features:** new pages or features, and pagination.
- **Disk threshold:** the admin's 85% disk warning (`DISK_USAGE_WARNING_PERCENT`) still ignores `DISK_WARN_PCT` from `.env`; that is a separate item. This redesign only adds the 95% constant alongside it.
- **Translations.**
