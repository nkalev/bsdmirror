# Reflection PR 1 (foundation) Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the redesign's foundation with no visible change except the favicon. That means the cache change and the deploy checks that prove it, then the fonts, the mark, the favicon set and the icon set.

**Architecture:** PR 1 ships as two pull requests.

- **PR 1a** changes nginx's cache headers and the admin assets' rate limit. It also teaches `scripts/deploy.sh` to retry a rate-limited probe and to check the new headers.
- **PR 1b** adds the asset files and their tests.

The split exists because `deploy.sh` is one deploy behind itself: a deploy runs the `deploy.sh` that was on disk when it started. PR 1a changes nothing under `frontend/public`, so the old `deploy.sh` has no files to fetch when 1a deploys. PR 1b's deploy, with 33 changed files under `frontend/public`, then runs 1a's `deploy.sh` and its retries.

**Tech stack:** nginx 1.25; bash (`scripts/deploy.sh`); pytest in the compose `test` service; Node 22 and headless Chromium over the DevTools protocol (`tests/js/`); hand-written SVG; the Python 3.12 standard library.

**Spec:** [2026-09-25-reflection-redesign.md](2026-09-25-reflection-redesign.md), sections 4.2, 4.5 to 4.7, 8, 10 and 11.

**Dry run.** Every code block in Tasks 1 to 16 was applied to a throwaway export of the repo and run in the test image, on 2026-09-25 and again on 2026-09-26 after the plan's review. So the fail and pass counts in the steps below are observed, not predicted. There are two exceptions:
- The font download itself (Task 10) waits for the user's approval. Its filter script ran against a synthetic Google response, and Task 11 against stand-in files: the repo's own Inter and JetBrains Mono files under the new names.
- The deploy steps (Tasks 8 and 18) touch production and were not run.

Executing PR 1a on 2026-09-26, each task's code review led to changes in Tasks 1, 4, 5 and 6, and the security review in Task 8 to one more in Task 5. The tests, code, comments and counts in this plan are what was built and committed, each re-verified against its commit.

The dry run also answered Task 13's open question (see its Step 4).

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
- Every commit leaves the suite green: run the whole suite before committing, and commit only on `rc=0`. A test written in one step is committed together with the change that makes it pass.

**`$SCRATCH`** is a directory outside the checkout: the controller's session scratchpad. Throwaway scripts and downloads go there, never into the repo. Every script this plan puts there is written out in full below, so a later session can recreate it. A dispatched subagent does not know `$SCRATCH`: the controller creates the directory a step needs and passes its absolute path.

**Shells and long waits.**
- The controller's shell may be zsh, and every block here works in zsh and bash alike. A glob that must expand inside a container is quoted into `sh -c '...'`, because zsh aborts on a glob that matches nothing on the host.
- Anything that can outlast a few minutes runs with the Bash tool's `run_in_background: true`, and the controller waits for its exit notification. That covers the CI waits and the deploy. The tool stops a foreground command after at most 10 minutes, and killing the ssh session mid-deploy can interrupt the deploy itself.

**Controller steps** are marked *controller*. The session that dispatches the tasks does them itself, because they ask the user something, touch GitHub or production, edit the working agreement in `CLAUDE.md`, or commit several owners' work together, with any one-line edit that has to ride in that commit.

## Files

**PR 1a:**

| File | Change | Owner |
|---|---|---|
| `nginx/sites/production/production.conf` | `expires epoch` for pages, CSS and JS; a nested location for CSS and JS; a new `location ~ ^/admin/(css\|js)/` under `general_limit` | devops-sre |
| `nginx/nginx.conf`, `nginx/sites/bootstrap/bootstrap.conf` | Stale comments corrected | devops-sre |
| `scripts/deploy.sh` | `fetch_with_retry()`; one request per probe; `verify_cache_headers()`; new probe paths; stale comments | devops-sre |
| `tests/test_nginx_cache_policy.py` | New. Resolves URIs through `production.conf` the way nginx does | developer |
| `tests/deploy_probe.py` | New. The curl, git and sleep stubs, shared by the deploy tests | developer |
| `tests/test_deploy_frontend_assets.py` | Uses `deploy_probe`; retry tests | developer |
| `tests/test_deploy_live_headers.py` | New. `verify_security_headers()` and `verify_cache_headers()` | developer |
| The spec and this plan | The 1a/1b split | controller |

**PR 1b:**

| File | Change | Owner |
|---|---|---|
| `frontend/public/fonts/`: four new `.woff2` files, `LICENSE-InstrumentSans.txt`, `LICENSE-Unbounded.txt` | From Google Fonts | controller downloads, web-designer adds |
| `frontend/public/css/fonts.css`, `frontend/public/fonts/README.md` | The new faces; provenance and checksums | web-designer |
| `CLAUDE.md`, `.dockerignore` | The web font count unpinned in one line each, as the new faces arrive | controller |
| `frontend/public/img/mark-glyph.svg`, `mark-axis.svg`, `icons/*.svg` (15), `README.md` | New | web-designer |
| `frontend/public/img/favicon.svg` | Redrawn | web-designer |
| `frontend/public/favicon.ico`, `frontend/public/img/apple-touch-icon.png` | Rendered by `scripts/render_icons.py` | devops-sre |
| `scripts/render_icons.py` | New | devops-sre |
| `index.html`, `admin/index.html`, `404.html`, `50x.html` | Three favicon links each | web-designer |
| `.gitignore` | `.screenshots/` | devops-sre |
| `tests/test_fonts.py` | New. The fonts, `fonts.css` and the fonts README | developer |
| `tests/test_images.py` | New. The mark, the icons, the logos and the favicon set | developer |
| `tests/js/favicon_harness.mjs`, `tests/test_favicon_dark_mode.py` | New. The favicon's dark rule under the production CSP | developer |
| `tests/test_chrome_harness_start.py`, `tests/test_gitignore_covers_secrets.py` | The new harness and the new ignore entry join their checks | developer |

---

## Chunk 1: PR 1a, the cache policy and the shared probe stub

Branch: `feat/reflection-foundation`, which already carries the spec (`328396c`).

### Task 1: Cache policy and admin asset limits in `production.conf`

**Files:**
- Create: `tests/test_nginx_cache_policy.py`
- Modify: `nginx/sites/production/production.conf`: `location /admin` (lines 183-197), a new block after it, and `location /` (lines 259-280)
- Create, outside the repo: `$SCRATCH/pr1/serve_production.sh`

- [ ] **Step 1 (developer): write the test.** Create `tests/test_nginx_cache_policy.py`:

```python
"""Which cache policy and which rate limit each kind of file gets in production.

docs/design/2026-09-25-reflection-redesign.md, section 8. The redesign ships
new HTML, CSS and JS across several pull requests under the same unversioned
filenames. Under the old `expires 7d` plus `immutable`, a returning visitor
would pair new HTML with week-old CSS. So, in the :443 server:

* pages, stylesheets and scripts revalidate on every load (`expires epoch`,
  which nginx sends as `Cache-Control: no-cache`; an unchanged file costs a
  304);
* fonts and images keep `expires 7d` and `public, immutable`, because they
  change only under a new filename;
* the admin console's CSS and JS move from api_limit (burst 10, shared with
  /api/) to general_limit (burst 30). Revalidating them on every load would
  otherwise stack them on top of the dashboard's own API calls.

These tests do not grep for directive strings. They parse
nginx/sites/production/production.conf, resolve each URI to the location nginx
would pick, in nginx's own order, and read the directives that location ends up
with after inheritance. A regex location added in the wrong place, or an
extension moved into the wrong block, changes the answer here the way it would
change it in production.

What this cannot prove is that nginx runs this file. scripts/deploy.sh's
verify_cache_headers() reads the live headers after every deploy.
"""

import pathlib
import re
from dataclasses import dataclass, field

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PRODUCTION_CONF = REPO_ROOT / "nginx" / "sites" / "production" / "production.conf"
SNIPPET = "/etc/nginx/host/snippets/security-headers-tls.conf"

TOKEN = re.compile(
    r"""
      (?P<comment>\#[^\n]*)
    | (?P<quoted>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
    | (?P<punct>[{};])
    | (?P<word>[^\s{};"'\#]+)
    """,
    re.X,
)


@dataclass
class Block:
    """A `name args { ... }` block: the file itself, a server or a location."""

    name: str
    args: list[str]
    parent: "Block | None" = None
    directives: list[list[str]] = field(default_factory=list)
    children: list["Block"] = field(default_factory=list)


def parse(text: str) -> Block:
    """Just enough of nginx's grammar for this file: words, quoted strings, `;`,
    `{}` and comments. `include`d files are not expanded. The snippets add only
    headers and the /health location, which no URI below reaches."""
    root = Block("file", [])
    stack = [root]
    words: list[str] = []
    for match in TOKEN.finditer(text):
        kind, token = match.lastgroup, match.group()
        if kind == "comment":
            continue
        if kind == "quoted":
            words.append(token[1:-1])
        elif kind == "word":
            words.append(token)
        elif token == ";":
            stack[-1].directives.append(words)
            words = []
        elif token == "{":
            block = Block(words[0], words[1:], parent=stack[-1])
            stack[-1].children.append(block)
            stack.append(block)
            words = []
        else:
            assert not words, f"unterminated directive before '}}': {words}"
            stack.pop()
    assert len(stack) == 1 and not words, "unbalanced braces"
    return root


def locations(block: Block) -> list[Block]:
    return [child for child in block.children if child.name == "location"]


def modifier(location: Block) -> str:
    return location.args[0] if len(location.args) == 2 else ""


def pattern(location: Block) -> str:
    return location.args[-1]


def label(location: Block) -> str:
    return "location " + " ".join(location.args)


def find_location(level: Block, uri: str) -> tuple[Block | None, bool]:
    """nginx's ngx_http_core_find_location(), for the syntax this file uses.

    An exact (`=`) match wins outright. Otherwise the longest plain prefix is
    remembered and its nested locations are searched; an exact or regex match
    there ends the search. Then this level's regexes, in file order, and the
    first match ends the search. Failing all of that, the remembered prefix.
    The flag in the result says whether the search ended (exact or regex) or
    only fell back to a prefix, which the caller's own regexes may override.
    """
    candidates = locations(level)
    for location in candidates:
        if modifier(location) not in ("", "=", "~", "~*"):
            raise NotImplementedError(f"{label(location)}: extend find_location() first")
    for location in candidates:
        if modifier(location) == "=" and pattern(location) == uri:
            return location, True
    prefixes = [
        location
        for location in candidates
        if modifier(location) == "" and uri.startswith(pattern(location))
    ]
    chosen = max(prefixes, key=lambda location: len(pattern(location)), default=None)
    if chosen is not None and locations(chosen):
        nested, final = find_location(chosen, uri)
        if final:
            return nested, True
        chosen = nested or chosen
    for location in candidates:
        flags = {"~": 0, "~*": re.IGNORECASE}.get(modifier(location))
        if flags is not None and re.search(pattern(location), uri, flags):
            nested = find_location(location, uri)[0] if locations(location) else None
            return nested or location, True
    return chosen, False


def own(location: Block, name: str) -> list[list[str]]:
    """The `name` directives set in this block itself. try_files is read this
    way, because a nested location does not inherit it."""
    return [directive for directive in location.directives if directive[0] == name]


def inherited(location: Block, name: str) -> list[list[str]]:
    """The `name` directives in force at a location: its own if it has any,
    otherwise its parent's, and so on up to the server. expires, limit_req and
    root inherit this way (nginx keeps root and alias as one setting)."""
    level = location
    while level is not None:
        found = own(level, name)
        if found:
            return found
        level = level.parent
    return []


def inherited_headers(location: Block) -> list[list[str]]:
    """The add_header set in force: that of the nearest level defining any
    header, counting an include of either security-header snippet as defining
    them all -- the TLS one carries HSTS, the plain one does not. One
    add_header at a level drops every inherited one; that is the trap
    nginx/snippets/ exists for."""
    level = location
    while level is not None:
        found = [
            directive
            for directive in level.directives
            if directive[0] == "add_header"
            or (directive[0] == "include" and "/snippets/security-headers" in directive[1])
        ]
        if found:
            return found
        level = level.parent
    return []


@pytest.fixture(scope="module")
def tls_server() -> Block:
    conf = parse(PRODUCTION_CONF.read_text(encoding="utf-8"))
    servers = [block for block in conf.children if block.name == "server"]
    tls = [server for server in servers if ["listen", "443", "ssl"] in server.directives]
    assert len(tls) == 1, "expected exactly one `listen 443 ssl` server"
    return tls[0]


def resolve(server: Block, uri: str) -> Block:
    location, _ = find_location(server, uri)
    assert location is not None, f"no location matches {uri}"
    return location


REVALIDATED = [
    "/",
    "/index.html",
    "/404.html",
    "/css/style.css",
    "/css/tokens.css",
    "/css/fonts.css",
    "/js/main.js",
    "/js/theme-init.js",
    "/admin/",
    "/admin/index.html",
    "/admin/css/admin.css",
    "/admin/js/admin.js",
]
LONG_CACHED = [
    "/fonts/jetbrains-mono-latin.woff2",
    "/img/favicon.svg",
    "/img/freebsd-logo.svg",
    "/img/icons/copy.svg",
    "/img/apple-touch-icon.png",
    "/favicon.ico",
]
ADMIN_ASSETS = ["/admin/css/admin.css", "/admin/js/admin.js"]

# The location nginx must pick for each URI. This pins find_location() to
# nginx's order as much as it pins the file.
SELECTION = [
    ("/api/auth/token", "location = /api/auth/token"),
    ("/api/health", "location /api/"),
    ("/admin/", "location /admin"),
    ("/admin/js/admin.js", "location ~ ^/admin/(css|js)/"),
    ("/admin/css/admin.css", "location ~ ^/admin/(css|js)/"),
    ("/index.html", "location /"),
    ("/css/style.css", r"location ~* \.(css|js)$"),
    ("/js/main.js", r"location ~* \.(css|js)$"),
    ("/img/favicon.svg", r"location ~* \.(png|jpg|jpeg|gif|ico|svg|woff|woff2)$"),
    ("/FreeBSD/README.TXT", "location /FreeBSD/"),
    # The nested blocks live in `location /`, so they never reach the mirror
    # trees.
    ("/FreeBSD/logo.svg", "location /FreeBSD/"),
    ("/FreeBSD/doc/style.css", "location /FreeBSD/"),
    ("/NetBSD/x.js", "location /NetBSD/"),
    ("/OpenBSD/x.css", "location /OpenBSD/"),
    ("/50x.html", "location = /50x.html"),
]


@pytest.mark.parametrize("uri, expected", SELECTION)
def test_each_uri_reaches_the_location_the_design_expects(tls_server, uri, expected):
    assert label(resolve(tls_server, uri)) == expected


@pytest.mark.parametrize("uri", REVALIDATED)
def test_pages_styles_and_scripts_revalidate_on_every_load(tls_server, uri):
    location = resolve(tls_server, uri)
    message = f"{uri} is served by `{label(location)}` without `expires epoch`"
    assert inherited(location, "expires") == [["expires", "epoch"]], message
    # expires epoch already sends Cache-Control: no-cache. An add_header
    # Cache-Control on top would send a second, contradicting value.
    cache_headers = [
        directive
        for directive in inherited_headers(location)
        if directive[:2] == ["add_header", "Cache-Control"]
    ]
    assert not cache_headers, f"{uri} would get two Cache-Control headers"


@pytest.mark.parametrize("uri", LONG_CACHED)
def test_fonts_and_images_stay_cached_for_a_week(tls_server, uri):
    location = resolve(tls_server, uri)
    assert inherited(location, "expires") == [["expires", "7d"]]
    assert ["add_header", "Cache-Control", "public, immutable"] in inherited_headers(location)


@pytest.mark.parametrize(
    "uri",
    ["/api/health", "/FreeBSD/README.TXT", "/NetBSD/README", "/OpenBSD/README", "/50x.html"],
)
def test_the_api_the_mirror_trees_and_the_error_page_set_no_expires(tls_server, uri):
    # expires belongs to the static-file blocks. Moved up to the server, it
    # would put no-cache on every mirror download and on the backend's replies.
    assert inherited(resolve(tls_server, uri), "expires") == []


@pytest.mark.parametrize("uri", [*REVALIDATED, *LONG_CACHED])
def test_every_static_response_keeps_the_security_headers(tls_server, uri):
    assert ["include", SNIPPET] in inherited_headers(resolve(tls_server, uri))


@pytest.mark.parametrize("uri", ADMIN_ASSETS)
def test_admin_css_and_js_share_the_static_file_limit(tls_server, uri):
    assert inherited(resolve(tls_server, uri), "limit_req") == [
        ["limit_req", "zone=general_limit", "burst=30", "nodelay"]
    ]


@pytest.mark.parametrize("uri", ["/admin/", "/admin/index.html"])
def test_the_admin_page_itself_stays_on_the_api_limit(tls_server, uri):
    assert inherited(resolve(tls_server, uri), "limit_req") == [
        ["limit_req", "zone=api_limit", "burst=10", "nodelay"]
    ]


@pytest.mark.parametrize("uri", ["/admin/", *ADMIN_ASSETS])
def test_the_admin_console_keeps_its_noindex_header(tls_server, uri):
    noindex = ["add_header", "X-Robots-Tag", "noindex, nofollow", "always"]
    assert noindex in inherited_headers(resolve(tls_server, uri))


@pytest.mark.parametrize("uri", ADMIN_ASSETS)
def test_admin_assets_are_read_from_the_files_the_alias_maps(tls_server, uri):
    # /admin uses `alias /var/www/public/admin`. The asset block serves from
    # the server root instead, which maps /admin/js/admin.js to the same file.
    location = resolve(tls_server, uri)
    assert inherited(location, "alias") == []
    assert inherited(location, "root") == [["root", "/var/www/public"]]


@pytest.mark.parametrize("uri", ["/css/style.css", "/js/main.js", *ADMIN_ASSETS])
def test_a_missing_stylesheet_or_script_is_a_404_not_a_page(tls_server, uri):
    # Each block that serves CSS or JS sets its own try_files, so a missing
    # file is a 404 rather than index.html served in its place, whatever the
    # block would otherwise inherit.
    assert own(resolve(tls_server, uri), "try_files") == [["try_files", "$uri", "=404"]]
```

- [ ] **Step 2 (developer): run it and watch it fail.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_nginx_cache_policy.py; echo "rc=$?"`

Expected: `rc=1`, with 25 failed and 44 passed. The failures:
- all 12 of `test_pages_styles_and_scripts_revalidate_on_every_load`, because nothing sets `expires epoch`;
- `test_each_uri_reaches_the_location_the_design_expects` for the two admin assets, `/css/style.css`, `/js/main.js` and `/img/favicon.svg`. Today the admin assets fall through to `location /admin`, and one nested location takes CSS, JS and images alike;
- both cases each of `test_admin_css_and_js_share_the_static_file_limit` and `test_admin_assets_are_read_from_the_files_the_alias_maps`;
- all 4 of `test_a_missing_stylesheet_or_script_is_a_404_not_a_page`. The two admin cases fail on behaviour: today a missing admin script comes back as the console's `index.html`. The two public cases fail only because today's nested block sets no `try_files` of its own. It already answers a missing file with 404, since `try_files` does not reach a nested location, but the test wants that stated where it cannot be lost.

The 44 that pass are the guards, and they must stay green through Step 4.

- [ ] **Step 3 (devops-sre): change `production.conf`.** Three edits.

In `location /admin`, add `expires epoch;` after `try_files`. Replace:

```nginx
        alias /var/www/public/admin;
        try_files $uri $uri/ /admin/index.html;

        # X-Robots-Tag is the only header this location actually wants, but
```

with:

```nginx
        alias /var/www/public/admin;
        try_files $uri $uri/ /admin/index.html;

        # The console's HTML revalidates on every load, like the public pages;
        # see `expires epoch` in `location /` below.
        expires epoch;

        # X-Robots-Tag is the only header this location actually wants, but
```

Directly after the closing `}` of `location /admin`, and before the `# FreeBSD Mirror` banner, insert:

```nginx

    # ===========================================
    # Admin Panel: stylesheets and scripts
    # ===========================================
    #
    # Under general_limit, like every other static file. These used to fall
    # through to `location /admin` above, whose api_limit (burst 10) is shared
    # with /api/. Once they revalidate on every load, a dashboard load would
    # stack them on top of its own API calls in that zone, and a 503 on
    # admin.css leaves the console unstyled.
    #
    # A regex location beats the /admin prefix, so this block takes these two
    # directories and nothing else; /admin/ itself stays above. It serves from
    # the server root, /var/www/public, which maps /admin/js/admin.js to the
    # same file the alias above does. A missing file is a plain 404 rather than
    # the console's index.html served in its place.
    location ~ ^/admin/(css|js)/ {
        limit_req zone=general_limit burst=30 nodelay;

        try_files $uri =404;
        expires epoch;

        # Include first, then add, for the same reason as `location /admin`.
        include /etc/nginx/host/snippets/security-headers-tls.conf;
        add_header X-Robots-Tag "noindex, nofollow" always;
    }
```

In `location /`, set `expires epoch` for the block, give stylesheets and scripts a nested location of their own, and narrow the existing nested location to fonts and images. Replace:

```nginx
        try_files $uri $uri/ /index.html;
        
        # Cache static assets
        location ~* \.(css|js|png|jpg|jpeg|gif|ico|svg|woff|woff2)$ {
            expires 7d;

            # A third instance of the same trap: this nested location adds
            # Cache-Control, so every stylesheet, script, font and image was
            # served with no CSP, no HSTS and no nosniff. nosniff matters most
            # here, and CSP matters on the SVGs -- /img/*.svg is navigable
            # directly, where an SVG renders as a document and any <script>
            # inside it executes.
```

(the blank line after `try_files` holds eight spaces) with:

```nginx
        try_files $uri $uri/ /index.html;

        # Pages, stylesheets and scripts revalidate on every load. Their names
        # carry no content hash, and a redesign ships new HTML, CSS and JS
        # together; with a week-long cache, a returning visitor would pair new
        # HTML with old CSS. An unchanged file costs a 304.
        #
        # `expires epoch` sends Cache-Control: no-cache itself, without an
        # add_header, so this block keeps inheriting the 443 server's header
        # set. nginx applies it to 2xx and 3xx responses only, so the error
        # pages, served as 404 and 5xx, are unaffected. The nested locations
        # below inherit it; the second overrides it for fonts and images.
        expires epoch;

        # Stylesheets and scripts: revalidated like the pages, through the
        # `expires epoch` this block inherits. A missing one is a plain 404
        # rather than index.html served in its place.
        location ~* \.(css|js)$ {
            try_files $uri =404;
        }

        # Fonts and images: cached for a week and never revalidated. They change
        # only under a new filename (see fonts/README.md). The exceptions are
        # the favicon files, whose names are fixed: a new version reaches
        # returning visitors within the week.
        location ~* \.(png|jpg|jpeg|gif|ico|svg|woff|woff2)$ {
            expires 7d;

            # A third instance of the same trap: this nested location adds
            # Cache-Control, so everything it served, stylesheets and scripts
            # too until they got a location of their own, went out with no
            # CSP, no HSTS and no nosniff. CSP matters most on the SVGs --
            # /img/*.svg is navigable directly, where an SVG renders as a
            # document and any <script> inside it executes.
```

Leave the rest of the fonts-and-images block (the `Cache-Control` note and its two directives) as it is.

- [ ] **Step 4 (devops-sre): run the test, and lint it.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_nginx_cache_policy.py; echo "rc=$?"`
Expected: `69 passed`, `rc=0`.

Run the lint pair from the working rules on `tests/test_nginx_cache_policy.py`. Expected: both `rc=0`.

- [ ] **Step 5 (devops-sre): serve the profile for real.** The test models nginx; this runs it. It also covers the `nginx -t` in devops-sre's definition of done. CLAUDE.md's `docker compose exec nginx nginx -t` checks whichever profile is active locally, and `production.conf` cannot be checked on its own: it includes the generated, gitignored `snippets/tls-cert.conf`. So write `$SCRATCH/pr1/serve_production.sh`:

```bash
#!/usr/bin/env bash
# Serve a checkout's production nginx profile in a throwaway container and
# report what a browser would get: `nginx -t`, then the status, Cache-Control,
# security headers and X-Robots-Tag of each path, then which rate limit each
# admin path is under. It mirrors CI's "Serve the production profile" step
# without writing into the checkout: nginx/ is copied to a temporary directory,
# where the generated tls-cert.conf and a self-signed pair can live. Every
# request is made from inside the container.
#
# Usage: serve_production.sh REPO_ROOT [EXTRA_PATH...]
set -euo pipefail
R=$(cd "${1:?usage: serve_production.sh REPO_ROOT [EXTRA_PATH...]}" && pwd)
shift
NAME=pr1-nginx
T=$(mktemp -d)
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; rm -rf "$T"; }
trap cleanup EXIT
docker rm -f "$NAME" >/dev/null 2>&1 || true

cp -R "$R/nginx" "$T/nginx"
mkdir -p "$T/le/live/local.test"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=local.test" \
    -keyout "$T/le/live/local.test/privkey.pem" \
    -out "$T/le/live/local.test/fullchain.pem" 2>/dev/null
printf 'ssl_certificate /etc/letsencrypt/live/local.test/fullchain.pem;\nssl_certificate_key /etc/letsencrypt/live/local.test/privkey.pem;\n' \
    >"$T/nginx/snippets/tls-cert.conf"

docker run -d --name "$NAME" \
    -v "$T/nginx/loader.conf:/etc/nginx/nginx.conf:ro" \
    -v "$T/nginx:/etc/nginx/host:ro" \
    -v "$T/nginx/sites/production:/etc/nginx/sites-enabled:ro" \
    -v "$R/frontend/public:/var/www/public:ro" \
    -v "$T/le:/etc/letsencrypt:ro" \
    nginx:1.25-bookworm >/dev/null

up=0
for _ in $(seq 1 30); do
    [ "$(docker inspect -f '{{.State.Running}}' "$NAME")" = "true" ] || break
    if docker exec "$NAME" curl -sk -o /dev/null https://localhost/ 2>/dev/null; then
        up=1
        break
    fi
    sleep 1
done
if [ "$up" -ne 1 ]; then
    echo "nginx did not come up; its log:" >&2
    docker logs "$NAME" >&2
    exit 1
fi
docker exec "$NAME" nginx -t

echo "== status, Cache-Control, security headers, X-Robots-Tag =="
for p in "$@" / /index.html /nope-404 /404.html /css/style.css /js/main.js /css/nope.css \
         /admin/ /admin/css/admin.css /admin/js/admin.js /admin/js/nope.js \
         /fonts/jetbrains-mono-latin.woff2 /img/favicon.svg /img/nope.png; do
    h=$(docker exec "$NAME" curl -sk -o /dev/null -D - "https://localhost$p" | tr -d '\r')
    code=$(printf '%s\n' "$h" | awk '/^HTTP\//{print $2}')
    cc=$(printf '%s\n' "$h" | grep -i '^cache-control:' | cut -d' ' -f2- | paste -sd, - || true)
    sec=$(printf '%s\n' "$h" | awk -F: 'tolower($1) ~ /^(x-frame-options|x-content-type-options|referrer-policy|content-security-policy|strict-transport-security)$/ {print tolower($1)}' | sort -u | wc -l | tr -d ' ')
    robots=$(printf '%s\n' "$h" | grep -i '^x-robots-tag:' | cut -d' ' -f2- || true)
    printf '  %-36s %s  cc=%-36s security=%s/5 robots=%s\n' "$p" "$code" "${cc:-<none>}" "$sec" "${robots:-<none>}"
done

echo "== 25 back-to-back requests each; a 503 marks the limit =="
for p in /admin/js/admin.js /admin/css/admin.css /admin/; do
    sleep 3
    printf '  %-22s' "$p"
    docker exec "$NAME" sh -c "for i in \$(seq 1 25); do curl -sk -o /dev/null -w '%{http_code} ' https://localhost$p; done"
    echo
done
```

Run: `bash "$SCRATCH/pr1/serve_production.sh" "$PWD"`

Expected (observed in the dry run):
- `nginx -t` reports `syntax is ok` and `test is successful`.
- Every path shows `security=5/5`.
- `/`, `/index.html`, `/css/style.css`, `/js/main.js`, `/admin/`, `/admin/css/admin.css` and `/admin/js/admin.js` answer `200 cc=no-cache`.
- `/nope-404` answers `200 cc=no-cache`: it is the SPA shell, through `try_files`. `/404.html` also answers `200 cc=no-cache`, because a direct request is a 200.
- `/css/nope.css`, `/admin/js/nope.js` and `/img/nope.png` answer `404 cc=<none>`. A missing asset is not a page, and `expires` skips error responses.
- The font and `favicon.svg` answer `200 cc=max-age=604800,public, immutable`.
- The three admin paths show `robots=noindex, nofollow`, and every other path shows `robots=<none>`.
- The burst lines show 25 `200`s for each admin asset. `/admin/`, on `api_limit` burst 10, turns to `503` after about 11.

In the task report, name the checks from devops-sre's definition of done that cannot run here: the stack-health and smoke round-trip checks, because this container has no backend and the local stack runs the dev profile.

- [ ] **Step 6 (devops-sre): commit.**

```bash
git add tests/test_nginx_cache_policy.py nginx/sites/production/production.conf
git commit -m "Revalidate pages, CSS and JS; limit admin assets like static files"
```

### Task 2: A shared stub for the `deploy.sh` probes

A refactor, green to green: the harness in `tests/test_deploy_frontend_assets.py` moves to a module the new tests can share. It also learns `-o FILE` and `-D FILE`, a sequence of responses per URL, and a log of every request and pause.

**Files:**
- Create: `tests/deploy_probe.py`
- Modify: `tests/test_deploy_frontend_assets.py`: the docstring's second and last paragraphs, and lines 27-163, the imports through `_marker`

- [ ] **Step 1 (developer): record the baseline.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_deploy_frontend_assets.py; echo "rc=$?"`

Expected: `9 passed`, `rc=0`.

- [ ] **Step 2 (developer): create `tests/deploy_probe.py`.**

```python
"""Run one function from scripts/deploy.sh against scripted HTTP, git and sleep.

deploy.sh only runs main() when it is executed, so the probe sources it and
calls a single function, the way tests/test_deploy_sync_gate.py does. curl, git
and sleep are bash stubs, so nothing reaches the network, the repository's
history or the clock. DEPLOY_DIR is the test's own checkout directory, so
env_get() reads that directory's .env.

curl answers from a table with one row per response:
``url|code|base64(body)|base64(headers)``. Rows for the same URL are served in
order, one per request, and the last one repeats, so a test can script "503,
then 200". The stub understands the flags deploy.sh passes:

* ``-o FILE``: the body goes to FILE; without -o it goes to stdout.
* ``-D FILE``: the status line and headers go to FILE, or to stdout for ``-``.
* ``-w``: the status code is printed after the body.

A URL with no row behaves like a connection that produced no response: status
000 and exit 7. Like real curl, it then leaves an -o file as it was and
empties a -D file.

Every request's URL goes to a call log, and every sleep's argument to a sleep
log. run_probe() returns the subprocess result with three extra attributes:
``output`` (stdout and stderr), ``calls`` and ``sleeps``.
"""

import base64
import os
import pathlib
import re
import subprocess

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEPLOY_SH = REPO_ROOT / "scripts" / "deploy.sh"

PREV_SHA = "prevsha1"
TARGET_SHA = "targetsha2"
BASE_URL = "http://example.invalid"

PROBE = r"""
source "$DEPLOY_SH"

_stub_head() {
    printf 'HTTP/1.1 %s Stub\r\n' "$1"
    local line
    while IFS= read -r line || [ -n "$line" ]; do
        printf '%s\r\n' "$line"
    done < <(printf '%s' "$2" | base64 -d)
    printf '\r\n'
}

curl() {
    local out="" hdr="" want_code=0 prev="" a url
    for a in "$@"; do
        case "$prev" in
            -o) out="$a" ;;
            -D) hdr="$a" ;;
        esac
        [ "$a" = "-w" ] && want_code=1
        prev="$a"
    done
    url="${*: -1}"
    printf '%s\n' "$url" >>"$CALL_LOG"

    local n i=0 u code b h row=""
    n=$(grep -cxF -- "$url" "$CALL_LOG")
    while IFS='|' read -r u code b h; do
        [ "$u" = "$url" ] || continue
        i=$((i + 1))
        row="$code|$b|$h"
        [ "$i" -lt "$n" ] || break
    done <<< "$FAKE_HTTP_TABLE"

    if [ -z "$row" ]; then
        if [ -n "$hdr" ] && [ "$hdr" != "-" ]; then : >"$hdr"; fi
        if [ "$want_code" = 1 ]; then printf '000'; fi
        return 7
    fi

    IFS='|' read -r code b h <<< "$row"
    if [ "$hdr" = "-" ]; then
        _stub_head "$code" "$h"
    elif [ -n "$hdr" ]; then
        _stub_head "$code" "$h" >"$hdr"
    fi
    if [ -n "$out" ]; then
        printf '%s' "$b" | base64 -d >"$out"
    else
        printf '%s' "$b" | base64 -d
    fi
    if [ "$want_code" = 1 ]; then printf '%s' "$code"; fi
    return 0
}

git() {
    if [ "$1" = "show" ]; then
        local arg="$2" u rc b
        while IFS='|' read -r u rc b; do
            [ "$u" = "$arg" ] || continue
            [ "$rc" = "0" ] && printf '%s' "$b" | base64 -d
            return "$rc"
        done <<< "$FAKE_GIT_TABLE"
        return 128
    fi
    return 1
}

sleep() { printf '%s\n' "$*" >>"$SLEEP_LOG"; }

cd "$WORKDIR"
DEPLOY_DIR="$WORKDIR"
FRONTEND_TOUCHED="$FAKE_FRONTEND_TOUCHED"
FRONTEND_CHANGED_FILES="$FAKE_CHANGED_FILES"
BASE_URL="$FAKE_BASE_URL"
PREV_SHA="$FAKE_PREV_SHA"
TARGET_SHA="$FAKE_TARGET_SHA"

"$FUNCTION"
rc=$?
printf 'RC=%s\n' "$rc"
printf 'VERIFY_FAILURES=%s\n' "$VERIFY_FAILURES"
"""


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def _http_rows(rows) -> str:
    """Each row is (url, code, body) or (url, code, body, headers); headers is
    a sequence of (name, value) pairs, so a name can repeat."""
    lines = []
    for url, code, body, *rest in rows:
        headers = rest[0] if rest else ()
        head = "\n".join(f"{name}: {value}" for name, value in headers)
        lines.append(f"{url}|{code}|{_b64(body)}|{_b64(head)}")
    return "\n".join(lines)


def _git_rows(rows) -> str:
    return "\n".join(f"{key}|{rc}|{_b64(body)}" for key, rc, body in rows)


def url_for(rel: str) -> str:
    prefix = "frontend/public/"
    suffix = rel[len(prefix) :] if rel.startswith(prefix) else rel
    return f"{BASE_URL}/{suffix}"


def write_file(workdir, rel: str, content: str) -> None:
    path = workdir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def marker(output: str, name: str) -> int:
    match = re.search(rf"^{name}=(-?\d+)$", output, re.MULTILINE)
    assert match, f"{name} marker missing from probe output:\n{output}"
    return int(match.group(1))


def run_probe(
    workdir,
    function,
    *,
    frontend_touched=1,
    changed_files="",
    http_table=(),
    git_table=(),
    prev_sha=PREV_SHA,
    target_sha=TARGET_SHA,
    base_url=BASE_URL,
):
    root = workdir.parent
    probe = root / "probe.sh"
    probe.write_text(PROBE)
    call_log = root / "calls.log"
    sleep_log = root / "sleeps.log"
    call_log.write_text("")
    sleep_log.write_text("")
    result = subprocess.run(
        ["bash", str(probe)],
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(root),
            "NO_COLOR": "1",
            "DEPLOY_SH": str(DEPLOY_SH),
            "WORKDIR": str(workdir),
            "FUNCTION": function,
            "CALL_LOG": str(call_log),
            "SLEEP_LOG": str(sleep_log),
            "FAKE_FRONTEND_TOUCHED": str(frontend_touched),
            "FAKE_CHANGED_FILES": changed_files,
            "FAKE_BASE_URL": base_url,
            "FAKE_PREV_SHA": prev_sha,
            "FAKE_TARGET_SHA": target_sha,
            "FAKE_HTTP_TABLE": _http_rows(http_table),
            "FAKE_GIT_TABLE": _git_rows(git_table),
        },
        # Not a terminal, so nothing can read stdin and colour codes stay off.
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    result.output = result.stdout + result.stderr
    result.calls = call_log.read_text().splitlines()
    result.sleeps = sleep_log.read_text().splitlines()
    return result
```

- [ ] **Step 3 (developer): point `test_deploy_frontend_assets.py` at it.** The docstring's second paragraph has never been true for stylesheets, scripts, fonts and images. They answer a missing file with 404, because `try_files` does not reach a nested location. So correct that paragraph too. Replace:

```text
The branch under test here is the deletion case. Every location under
frontend/public/ inherits `try_files $uri $uri/ /index.html`, so nginx
answers a path deleted by this deploy with HTTP 200 and the SPA shell -- by
design, not staleness. The function therefore never gates on status code for
a deleted file; it compares live bytes to the pre-deletion content (read via
`git show $PREV_SHA:$rel`) and only fails when those two match, i.e. when
something is still serving the deleted file's own old bytes.
```

with:

```text
The branch under test here is the deletion case. A deleted page falls back to
the SPA shell through `try_files $uri $uri/ /index.html` and answers HTTP 200
-- by design, not staleness -- while a deleted stylesheet, script, font or
image answers 404. The function therefore never gates on status code for a
deleted file; it compares live bytes to the pre-deletion content (read via
`git show $PREV_SHA:$rel`) and only fails when those two match, i.e. when
something is still serving the deleted file's own old bytes.
```

Then replace the docstring's last paragraph:

```text
deploy.sh only runs main() when executed, so this sources it and calls the
function directly, the same way tests/test_deploy_sync_gate.py does. curl and
git are replaced with table-driven bash stubs so the probe touches neither
the network nor real repository history.
```

with:

```text
deploy.sh only runs main() when executed, so this sources it and calls the
function directly, through the curl, git and sleep stubs in
tests/deploy_probe.py. The probe touches neither the network nor real
repository history.
```

Then replace everything from `import base64` down to the end of `def _marker(...)` (lines 27-163) with:

```python
import pytest

from tests.deploy_probe import PREV_SHA, TARGET_SHA, url_for, write_file
from tests.deploy_probe import marker as _marker
from tests.deploy_probe import run_probe as _run_probe


@pytest.fixture
def workdir(tmp_path):
    d = tmp_path / "checkout"
    d.mkdir()
    return d


def run_probe(workdir, **kwargs):
    return _run_probe(workdir, "verify_frontend_assets", **kwargs)
```

The test functions below stay exactly as they are.

- [ ] **Step 4 (developer): run it, and lint both files.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_deploy_frontend_assets.py; echo "rc=$?"`
Expected: `9 passed`, `rc=0`, the same as the baseline.

Run the lint pair on `tests/deploy_probe.py tests/test_deploy_frontend_assets.py`. Expected: both `rc=0`.

- [ ] **Step 5 (developer): commit.**

```bash
git add tests/deploy_probe.py tests/test_deploy_frontend_assets.py
git commit -m "Move the deploy.sh probe stubs into a shared test module"
```

---

## Chunk 2: PR 1a, retries and the live header checks

Same branch as Chunk 1.

### Task 3: One request per file, retried on 503

**Files:**
- Modify: `tests/test_deploy_frontend_assets.py` (append)
- Modify: `scripts/deploy.sh`: after `curl_base()` (line 1153), and `verify_frontend_assets()` (lines 1541-1619)

- [ ] **Step 1 (developer): append the tests** to `tests/test_deploy_frontend_assets.py`:

```python
RATE_LIMITED = "<html>503 Service Temporarily Unavailable</html>\n"


def test_each_file_is_fetched_with_one_request(workdir):
    # The status and the bytes come from the same response. The old form
    # hashed one request and read the status from a second one.
    rel = "frontend/public/app.js"
    content = "console.log('new');\n"
    write_file(workdir, rel, content)

    result = run_probe(
        workdir, changed_files=rel, http_table=[(url_for(rel), "200", content)], git_table=[]
    )
    assert _marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert result.calls == [url_for(rel)]


def test_a_rate_limited_file_is_fetched_again_after_a_pause(workdir):
    rel = "frontend/public/app.js"
    content = "console.log('new');\n"
    write_file(workdir, rel, content)

    result = run_probe(
        workdir,
        changed_files=rel,
        http_table=[(url_for(rel), "503", RATE_LIMITED), (url_for(rel), "200", content)],
        git_table=[],
    )
    assert _marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert result.calls == [url_for(rel)] * 2
    assert result.sleeps == ["2"]
    assert "503 (rate limited), retrying in 2s" in result.output
    assert "SERVING STALE CONTENT" not in result.output


def test_a_file_still_rate_limited_after_three_retries_fails_with_503(workdir):
    rel = "frontend/public/app.js"
    write_file(workdir, rel, "console.log('new');\n")

    result = run_probe(
        workdir, changed_files=rel, http_table=[(url_for(rel), "503", RATE_LIMITED)], git_table=[]
    )
    assert _marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert "HTTP 503 fetching a file that exists in the checkout" in result.output
    assert result.calls == [url_for(rel)] * 4
    assert result.sleeps == ["2"] * 3


@pytest.mark.parametrize("code", ["404", "500", "502", "000"])
def test_only_503_is_retried(workdir, code):
    rel = "frontend/public/app.js"
    write_file(workdir, rel, "console.log('new');\n")
    # 000 is curl's status when nothing answered: a URL with no row.
    rows = [] if code == "000" else [(url_for(rel), code, "error\n")]

    result = run_probe(workdir, changed_files=rel, http_table=rows, git_table=[])
    assert _marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert f"HTTP {code} fetching a file that exists in the checkout" in result.output
    assert result.calls == [url_for(rel)]
    assert result.sleeps == []


def test_a_deleted_file_is_fetched_with_one_request(workdir):
    rel = "frontend/public/old-page.html"
    result = run_probe(
        workdir,
        changed_files=rel,
        http_table=[(url_for(rel), "200", "<html>SPA shell</html>\n")],
        git_table=[(f"{PREV_SHA}:{rel}", "0", "<html>old page</html>\n")],
    )
    assert _marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert result.calls == [url_for(rel)]


def test_a_rate_limited_deleted_file_is_fetched_again(workdir):
    rel = "frontend/public/old-page.html"
    result = run_probe(
        workdir,
        changed_files=rel,
        http_table=[
            (url_for(rel), "503", RATE_LIMITED),
            (url_for(rel), "200", "<html>SPA shell</html>\n"),
        ],
        git_table=[(f"{PREV_SHA}:{rel}", "0", "<html>old page</html>\n")],
    )
    assert _marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert result.calls == [url_for(rel)] * 2
    assert result.sleeps == ["2"]
    assert "deleted, no longer serving the old bytes (HTTP 200)" in result.output


def test_no_response_is_not_read_as_the_previous_files_bytes(workdir):
    # One body file serves every fetch, and curl leaves it as it was when
    # nothing answers. Unless it is emptied first, a deleted file that gets no
    # response would be hashed as the previous file's bytes.
    kept, deleted = "frontend/public/a.html", "frontend/public/b.html"
    same = "<html>same bytes</html>\n"
    write_file(workdir, kept, same)

    result = run_probe(
        workdir,
        changed_files=f"{kept}\n{deleted}",
        http_table=[(url_for(kept), "200", same)],
        git_table=[(f"{PREV_SHA}:{deleted}", "0", same)],
    )
    assert _marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert "deleted, no longer serving the old bytes (HTTP 000)" in result.output
```

- [ ] **Step 2 (developer): run them and watch them fail.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_deploy_frontend_assets.py; echo "rc=$?"`

Expected: `rc=1`, with 9 failed and 10 passed. Each new test except the last fails because today's code makes two requests per file and never retries:
- `test_a_rate_limited_file_is_fetched_again_after_a_pause` also reports `SERVING STALE CONTENT`, which is the misreport this change removes.
- The persistent-503 test sees 2 calls, not 4.

`test_no_response_is_not_read_as_the_previous_files_bytes` passes today: the old code never reuses a file. It guards the shared body file that Step 4 introduces, and Step 5 proves that it bites.

- [ ] **Step 3 (devops-sre): add `fetch_with_retry()`.** In `scripts/deploy.sh`, insert after the closing `}` of `curl_base()`:

```bash

# One GET, repeated while nginx's limit_req answers 503.
#
# Every probe below goes through the public URL, so it counts against the same
# per-IP limits as a visitor. nginx.conf defines the zones and their rates
# (general_limit 30 r/s, api_limit 10 r/s); sites/production/production.conf
# sets each location's burst (30 for pages and static files, 10 for /admin/,
# 20 for /api/, 50 for the mirror trees). A deploy that changes a few dozen
# frontend files can use up a burst on its own, and a 503 there would report
# a good deploy as failed. Same back-off idea as verify_login_roundtrip() uses
# for /api/auth/token.
#
# The body and the status come from ONE request (-o plus -w), and a retry
# repeats the whole request. The old two-request form hashed one response and
# read the status from another, so a 503 on the first reported the 50x page as
# stale content. Any status other than 503 returns at once.
#
# Usage: code=$(fetch_with_retry BODY_FILE URL [CURL_ARGS...])
# Prints the final status: 000 when nothing answered.
FETCH_ATTEMPTS=4
FETCH_RETRY_PAUSE=2

fetch_with_retry() {
    local out="$1" url="$2" opts code attempt=1
    shift 2
    opts=$(curl_base)
    while :; do
        # curl leaves an -o file untouched when nothing answers, and callers
        # reuse one file for many fetches: empty it first.
        : >"$out"
        set +e
        # shellcheck disable=SC2086
        code=$(curl $opts -o "$out" -w '%{http_code}' "$@" "$url" 2>/dev/null)
        set -e
        [ -n "$code" ] || code=000
        if [ "$code" = "503" ] && [ "$attempt" -lt "$FETCH_ATTEMPTS" ]; then
            warn "$url -> 503 (rate limited), retrying in ${FETCH_RETRY_PAUSE}s"
            sleep "$FETCH_RETRY_PAUSE"
            attempt=$((attempt + 1))
            continue
        fi
        printf '%s' "$code"
        return 0
    done
}
```

- [ ] **Step 4 (devops-sre): fetch each file once.** Replace the whole `verify_frontend_assets()` function, from `verify_frontend_assets() {` to its closing `}`, with the version below. The deleted-file comment now says which paths answer 200 and which answer 404; everything after the loop is unchanged apart from the added `rm -f`.

```bash
verify_frontend_assets() {
    if [ "$FRONTEND_TOUCHED" -ne 1 ]; then
        ok "no frontend/public/ changes in this deploy; nothing to prove"
        return 0
    fi

    step "Proving nginx is serving this checkout's frontend/public/"
    local rel url want got code body fails=0 checked=0
    # Each file's body lands here, and its status comes from the same request.
    body=$(mktemp)

    while IFS= read -r rel; do
        [ -n "$rel" ] || continue
        url="$BASE_URL/${rel#frontend/public/}"
        checked=$((checked + 1))

        if [ ! -f "$rel" ]; then
            # Deleted by this deploy. NOT checked as "must not be 200": a
            # deleted page falls back to the SPA shell through `try_files $uri
            # $uri/ /index.html` (or .../admin/index.html under the alias) and
            # answers 200 by design, while a deleted stylesheet, script, font or
            # image answers 404. Neither is a stale mount, and asserting either
            # status here would fail legitimate deletions.
            #
            # The actual failure this must catch is narrower: something still
            # serving the FILE'S OWN pre-deletion bytes -- a stale mount, a
            # cached layer, or a dangling alias that never noticed the delete.
            # So compare live bytes to the pre-deletion content instead of
            # reasoning about status codes at all.
            local old
            old=$(git show "$PREV_SHA:$rel" 2>/dev/null | sha256sum | cut -d' ' -f1) || old=""
            code=$(fetch_with_retry "$body" "$url")
            got=$(sha256sum <"$body" | cut -d' ' -f1)
            if [ -n "$old" ] && [ "$got" = "$old" ]; then
                bad "$url -- deleted in $TARGET_SHA but still serving its old bytes (HTTP $code)"
                fails=$((fails + 1))
            else
                ok "$url -- deleted, no longer serving the old bytes (HTTP $code)"
            fi
            continue
        fi

        want=$(sha256sum "$rel" | cut -d' ' -f1)
        code=$(fetch_with_retry "$body" "$url")
        got=$(sha256sum <"$body" | cut -d' ' -f1)

        if [ "$code" != "200" ]; then
            bad "$url -- HTTP $code fetching a file that exists in the checkout"
            fails=$((fails + 1))
        elif [ "$got" != "$want" ]; then
            bad "$url -- SERVING STALE CONTENT"
            bad "    checkout  $rel  ${want:0:12}"
            bad "    live      $url  ${got:0:12}"
            fails=$((fails + 1))
        else
            ok "$url  ${want:0:12}"
        fi
    done <<EOF
$FRONTEND_CHANGED_FILES
EOF
    rm -f "$body"

    if [ "$fails" -ne 0 ]; then
        vfail "$fails of $checked changed frontend/public/ file(s) do not match this checkout"
        bad "backend and sync may be on the new code; nginx's view of frontend/public/ is not."
        bad "docker-compose.yml uses a directory mount, so this should be impossible -- if it"
        bad "just happened anyway, recreate nginx so docker re-resolves it:"
        bad "  cd $DEPLOY_DIR && docker compose up -d --force-recreate nginx"
        return 0
    fi
    ok "all $checked changed frontend/public/ file(s) match the checkout byte-for-byte"
}
```

- [ ] **Step 5 (devops-sre): run the tests, prove the guard bites, and check the shell.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_deploy_frontend_assets.py; echo "rc=$?"`
Expected: `19 passed`, `rc=0`.

Mutation check: delete the line `: >"$out"` from `fetch_with_retry()` and re-run.
- Expected: exactly `test_no_response_is_not_read_as_the_previous_files_bytes` fails, with `still serving its old bytes (HTTP 000)`.
- Restore the line and re-run: `19 passed`.

Run shellcheck as in the working rules. Expected: no output, `rc=0`.

Run the lint pair on `tests/test_deploy_frontend_assets.py`. Expected: both `rc=0`.

- [ ] **Step 6 (devops-sre): commit.**

```bash
git add tests/test_deploy_frontend_assets.py scripts/deploy.sh
git commit -m "Retry rate-limited deploy probes and fetch each file once"
```

### Task 4: Security headers: one request per path, and new probe paths

Two paths change:
- `/admin/js/admin.js` joins, because it now has its own location block.
- `/nope-deploy-probe-404` becomes `/css/nope-deploy-probe-404.css`. The old path was never a 404: `try_files` answers it with the SPA shell and a 200. A missing stylesheet is a real 404, before Task 1 and after it, so the new path tests what the comment claims: that `always` keeps the headers on a 4xx. It still does after a rollback.

Each answer's status is checked too, where only a 000 was before:
- A 5xx means the error page answered, whether rate limited after the retries or with a backend down. Its headers come from `location = /50x.html`, so the path's own block went unprobed.
- In production, the 404 probe must get a 404. Under its old name it got the SPA shell and a 200 for years, and nothing noticed. `dev.conf` and `bootstrap.conf` answer it with the SPA shell by design, so elsewhere a 200 is fine.

**Files:**
- Create: `tests/test_deploy_live_headers.py`
- Modify: `scripts/deploy.sh`: the path comment above `verify_security_headers()` and the function itself

- [ ] **Step 1 (developer): write the tests.** Create `tests/test_deploy_live_headers.py`:

```python
"""verify_security_headers() and verify_cache_headers() in scripts/deploy.sh.

Both read what the live site sends through the public URL, so every request
they make counts against nginx's per-IP rate limits the way a visitor's does.
They must not spend requests they do not need. Their probes go through
fetch_with_retry(), which repeats a request nginx answered with 503; the
console double-load in verify_cache_headers() does not, because a 503 is what
it looks for. Driven by the stubs in tests/deploy_probe.py, with no network.
"""

import pytest

from tests.deploy_probe import BASE_URL, marker, run_probe

CSP = "default-src 'self'; script-src 'self'"
SECURITY_HEADERS = (
    ("X-Frame-Options", "DENY"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ("Content-Security-Policy", CSP),
)
PROBE_404 = "/css/nope-deploy-probe-404.css"
SECURITY_PATHS = [
    "/",
    "/admin/",
    "/admin/js/admin.js",
    "/css/style.css",
    "/img/favicon.svg",
    "/api/health",
    "/health",
    "/404.html",
    PROBE_404,
    "/FreeBSD/",
]


@pytest.fixture
def workdir(tmp_path):
    """A checkout holding only what the checks read: the CSP in nginx.conf,
    the active profile in .env, and that profile's cache policy."""
    d = tmp_path / "checkout"
    (d / "nginx" / "sites" / "production").mkdir(parents=True)
    (d / "nginx" / "nginx.conf").write_text(
        'http {\n    map $host $csp_policy {\n        default "%s";\n    }\n}\n' % CSP
    )
    (d / "nginx" / "sites" / "production" / "production.conf").write_text(
        "server {\n    location / {\n        expires epoch;\n    }\n}\n"
    )
    (d / ".env").write_text("NGINX_SITE=production\n")
    return d


def served(path, code=None, headers=SECURITY_HEADERS):
    # In production a missing stylesheet is a real 404; every other path answers 200.
    if code is None:
        code = "404" if path == PROBE_404 else "200"
    return (BASE_URL + path, code, "", headers)


def with_csp(value):
    return tuple(
        (name, value) if name == "Content-Security-Policy" else (name, old)
        for name, old in SECURITY_HEADERS
    )


def probe_security(workdir, rows):
    return run_probe(workdir, "verify_security_headers", http_table=rows)


def test_admin_js_is_one_of_the_probed_paths(workdir):
    result = probe_security(workdir, [served(path) for path in SECURITY_PATHS])
    assert marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert BASE_URL + "/admin/js/admin.js" in result.calls


def test_each_path_is_requested_once_and_its_headers_reused_for_the_csp_check(workdir):
    result = probe_security(workdir, [served(path) for path in SECURITY_PATHS])
    assert marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert result.calls == [BASE_URL + path for path in SECURITY_PATHS]


def test_a_rate_limited_path_is_requested_again(workdir):
    rows = [
        served("/css/style.css", code="503", headers=()),
        *(served(path) for path in SECURITY_PATHS),
    ]
    result = probe_security(workdir, rows)
    assert marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert result.calls.count(BASE_URL + "/css/style.css") == 2
    assert result.sleeps == ["2"]


def test_a_path_missing_a_header_fails(workdir):
    rows = [served(path) for path in SECURITY_PATHS if path != "/admin/js/admin.js"]
    rows.append(served("/admin/js/admin.js", headers=SECURITY_HEADERS[1:]))
    result = probe_security(workdir, rows)
    assert marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert "1 of 10 probed paths failed the header check" in result.output


def test_a_path_that_does_not_answer_fails(workdir):
    rows = [served(path) for path in SECURITY_PATHS if path != "/FreeBSD/"]
    result = probe_security(workdir, rows)
    assert marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert f"/FreeBSD/ -- no response from {BASE_URL}" in result.output
    assert "1 of 10 probed paths failed the header check" in result.output


def test_a_csp_that_differs_from_the_checkout_fails(workdir):
    stale = with_csp("default-src *")
    result = probe_security(workdir, [served(path, headers=stale) for path in SECURITY_PATHS])
    assert marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert "does not match this checkout's nginx.conf" in result.output


def test_two_different_csp_values_fail(workdir):
    # Every header dump is read: here only the last path disagrees.
    rows = [served(path) for path in SECURITY_PATHS if path != "/FreeBSD/"]
    rows.append(served("/FreeBSD/", headers=with_csp("default-src 'none'")))
    result = probe_security(workdir, rows)
    assert marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert "2 different Content-Security-Policy values are being served" in result.output


def test_the_404_probe_must_get_a_404_in_production(workdir):
    rows = [served(path) for path in SECURITY_PATHS if path != PROBE_404]
    rows.append(served(PROBE_404, code="200"))
    result = probe_security(workdir, rows)
    assert marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert f"{PROBE_404} -- HTTP 200, expected 404" in result.output
    assert "1 of 10 probed paths failed the header check" in result.output


def test_outside_production_the_404_probe_may_get_the_spa_shell(workdir):
    (workdir / ".env").write_text("NGINX_SITE=dev\n")
    rows = [served(path) for path in SECURITY_PATHS if path != PROBE_404]
    rows.append(served(PROBE_404, code="200"))
    result = probe_security(workdir, rows)
    assert marker(result.output, "VERIFY_FAILURES") == 0, result.output


@pytest.mark.parametrize("code, calls", [("503", 4), ("502", 1)])
def test_a_path_answered_by_the_error_page_goes_unprobed(workdir, code, calls):
    # The stub repeats a URL's last row, so a lone 503 stays a 503 through
    # every retry. The error page carries the full header set, which proves
    # nothing about the block the path is meant to probe.
    rows = [served(path) for path in SECURITY_PATHS if path != "/css/style.css"]
    rows.append(served("/css/style.css", code=code))
    result = probe_security(workdir, rows)
    assert marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert f"/css/style.css -- HTTP {code}: the error page answered" in result.output
    assert result.calls.count(BASE_URL + "/css/style.css") == calls


def test_over_https_every_path_needs_hsts(workdir):
    https = "https://example.invalid"
    rows = [
        (https + path, "404" if path == PROBE_404 else "200", "", SECURITY_HEADERS)
        for path in SECURITY_PATHS
    ]
    result = run_probe(workdir, "verify_security_headers", http_table=rows, base_url=https)
    assert marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert "10 of 10 probed paths failed the header check" in result.output
    assert "strict-transport-security" in result.output
```

- [ ] **Step 2 (developer): run them and watch them fail.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_deploy_live_headers.py; echo "rc=$?"`

Expected: `rc=1`, with all 12 failed.
- Today's code probes `/nope-deploy-probe-404`, which has no row here, so every test finds at least one of 9 probed paths without its headers, and never reaches the CSP comparison. That alone fails the dev-profile test, which expects no failure.
- The first two tests would also fail on their own: today's path list has no `/admin/js/admin.js`, and every path is requested twice.
- The rest look for messages today's code never prints: its summary says "missing security headers", not "failed the header check", and it checks no status but 000.

- [ ] **Step 3 (devops-sre): rewrite the path comment.** Above the function, replace every line from `# Paths chosen to cover every block in sites/production/production.conf that` down to and including `#   /FreeBSD/            autoindex, the highest-traffic path on the site` with:

```bash
# Paths chosen to cover every block in sites/production/production.conf that
# defines an add_header of its own, plus ones that define none:
#   /                    server-level set, static location, no add_header
#   /admin/              adds X-Robots-Tag  -> must not lose the other five
#   /admin/js/admin.js   the admin's CSS and JS block: the same
#                        include-then-add, under general_limit
#   /css/style.css       the CSS and JS nested location, which adds no header
#                        of its own and inherits the server set
#   /img/favicon.svg     the fonts-and-images nested location: adds
#                        Cache-Control, same trap, and the one where CSP
#                        actually matters
#   /api/health          proxied to backend, no add_header at that level
#   /health              nginx's own endpoint, an `include`d location in both
#                        the :80 and :443 servers. Headers only here; the bytes
#                        are asserted by verify_health_endpoint() above, which
#                        exists because this function reported "200, 5/5" on a
#                        /health that was serving the homepage.
#   /404.html            the error page itself, asked for directly (a 200)
#   /css/nope-deploy-probe-404.css
#                        a real 404: a missing stylesheet gets the error page,
#                        not the SPA shell, so this proves `always` on a 4xx
#   /FreeBSD/            autoindex, the highest-traffic path on the site
```

- [ ] **Step 4 (devops-sre): rewrite the function's first half.** Replace everything from `verify_security_headers() {` down to and including the line `    ok "one Content-Security-Policy value across all probed paths"` with:

```bash
verify_security_headers() {
    local scheme
    case "$BASE_URL" in https://*) scheme=https ;; *) scheme=http ;; esac

    # HSTS is set only in the 443 server, and deliberately absent from dev.conf
    # and bootstrap.conf: it is meaningless over plaintext (RFC 6797 sec. 7.2)
    # and pinning it from a dev box would poison localhost for every other
    # project on that machine.
    local -a want=(x-frame-options x-content-type-options referrer-policy content-security-policy)
    [ "$scheme" = "https" ] && want+=(strict-transport-security)

    # A missing stylesheet is a 404 only where the production profile gives
    # stylesheets a location of their own; dev.conf and bootstrap.conf answer
    # it with the SPA shell.
    local probe404=/css/nope-deploy-probe-404.css site
    site=$(env_get NGINX_SITE dev)

    local -a paths=(/ /admin/ /admin/js/admin.js /css/style.css /img/favicon.svg /api/health /health /404.html "$probe404" /FreeBSD/)
    local path hdrs missing h code fails=0 dir i
    # The PATH column is 32 wide: /css/nope-deploy-probe-404.css is 30.
    # One header dump per path, kept for the CSP comparison below, so each
    # path costs one request against the rate limit rather than two.
    dir=$(mktemp -d)

    printf '  %-32s %-5s %s\n' "PATH" "CODE" "HEADERS"
    for i in "${!paths[@]}"; do
        path="${paths[$i]}"
        code=$(fetch_with_retry /dev/null "$BASE_URL$path" -D "$dir/$i")
        if [ "$code" = "000" ]; then
            bad "$path -- no response from $BASE_URL"
            fails=$((fails + 1))
            continue
        fi
        # A 5xx is the error page answering, still rate limited after the
        # retries or with a backend down. Its headers come from
        # `location = /50x.html`, not from the block this path is meant to probe.
        case "$code" in
            5??)
                bad "$path -- HTTP $code: the error page answered, so its own block went unprobed"
                fails=$((fails + 1))
                continue
                ;;
        esac
        # The probe that proves `always` on a 4xx has to get one. Under its old
        # name it got the SPA shell and a 200 for years, and nothing noticed.
        if [ "$path" = "$probe404" ] && [ "$site" = "production" ] && [ "$code" != "404" ]; then
            bad "$path -- HTTP $code, expected 404: a missing stylesheet must not get a page"
            fails=$((fails + 1))
            continue
        fi
        hdrs=$(tr -d '\r' <"$dir/$i" | tr '[:upper:]' '[:lower:]')
        missing=""
        for h in "${want[@]}"; do
            printf '%s\n' "$hdrs" | grep -q "^$h:" || missing="$missing $h"
        done
        if [ -n "$missing" ]; then
            printf '  %-32s %-5s %sMISSING:%s%s\n' "$path" "$code" "$C_RED" "$C_OFF" "$missing"
            fails=$((fails + 1))
        else
            printf '  %-32s %-5s %s%d/%d ok%s\n' "$path" "$code" "$C_GRN" "${#want[@]}" "${#want[@]}" "$C_OFF"
        fi
    done

    if [ "$fails" -ne 0 ]; then
        rm -rf "$dir"
        # One vfail, then plain bad() for the advice. vfail increments
        # VERIFY_FAILURES, and three calls for one problem would report
        # "3 checks failed" for a single cause.
        vfail "$fails of ${#paths[@]} probed paths failed the header check"
        bad "if this deploy changed nginx/, the change did not take effect --"
        bad "run 'scripts/nginx-apply.sh check' before believing anything else"
        return 0
    fi
    ok "all ${#paths[@]} probed paths carry the full ${#want[@]}-header set"

    # The CSP is defined once, by the map in nginx/nginx.conf, and every block
    # that includes a security-header snippet emits it. If two of them
    # disagree, one of them is stale. Read from the header dumps above rather
    # than requesting every path a second time.
    local served_values policies served_csp checkout_csp
    served_values=$(for i in "${!paths[@]}"; do
        tr -d '\r' <"$dir/$i" | grep -i '^content-security-policy:' | cut -d' ' -f2-
    done | sort -u)
    rm -rf "$dir"
    policies=$(printf '%s\n' "$served_values" | sed '/^$/d' | wc -l | tr -d ' ')
    if [ "$policies" != "1" ]; then
        vfail "$policies different Content-Security-Policy values are being served"
        bad "the map in nginx/nginx.conf is the single source; a block is stale"
        return 0
    fi
    ok "one Content-Security-Policy value across all probed paths"
```

The rest of the function, from the `# THE CHECK THAT WAS STILL MISSING...` comment to its closing `}`, stays exactly as it is.

- [ ] **Step 5 (devops-sre): run the tests and the checks.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_deploy_live_headers.py tests/test_deploy_frontend_assets.py; echo "rc=$?"`
Expected: `31 passed`, `rc=0`.

Run shellcheck (expected `rc=0`) and the lint pair on `tests/test_deploy_live_headers.py` (expected both `rc=0`).

- [ ] **Step 6 (devops-sre): commit.**

```bash
git add tests/test_deploy_live_headers.py scripts/deploy.sh
git commit -m "Probe admin.js and a real 404 for headers; reuse each dump"
```

### Task 5: `verify_cache_headers()`

Like every other check in `deploy.sh`, this one compares the live site against the checkout. It checks only when the active profile's config in the checkout sets `expires epoch`. So these pass cleanly: a rollback to a commit from before the policy, and the dev and bootstrap profiles.

**Files:**
- Modify: `tests/test_deploy_live_headers.py` (append)
- Modify: `scripts/deploy.sh`: a new function after `verify_security_headers()`, and `verify_all()`

- [ ] **Step 1 (developer): append the tests** to `tests/test_deploy_live_headers.py`. First add `import re` and `import shutil` above `import pytest`, with a blank line before `import pytest`, and `DEPLOY_SH` and `REPO_ROOT` to the `tests.deploy_probe` import, so it reads `from tests.deploy_probe import BASE_URL, DEPLOY_SH, REPO_ROOT, marker, run_probe`.

```python
NO_CACHE = (("Cache-Control", "no-cache"), ("Expires", "Thu, 01 Jan 1970 00:00:01 GMT"))
A_WEEK_IMMUTABLE = (("Cache-Control", "max-age=604800"), ("Cache-Control", "public, immutable"))
REVALIDATED = ["/", "/css/style.css", "/admin/", "/admin/css/admin.css", "/admin/js/admin.js"]
FONT = "/fonts/jetbrains-mono-latin.woff2"
CONSOLE = [
    "/admin/",
    "/css/fonts.css",
    "/css/tokens.css",
    "/admin/css/admin.css",
    "/admin/js/admin.js",
]


def lowered(headers):
    # HTTP/2, which production speaks, sends every header name in lowercase.
    return tuple((name.lower(), value) for name, value in headers)


def cache_rows(overrides=None, lower=False):
    """A correctly configured site, except for the paths in `overrides`, each
    mapped to the rows served for it, in order."""
    rows = {path: [(BASE_URL + path, "200", "", NO_CACHE)] for path in {*REVALIDATED, *CONSOLE}}
    rows[FONT] = [(BASE_URL + FONT, "200", "", A_WEEK_IMMUTABLE)]
    rows.update(overrides or {})
    table = [row for path in sorted(rows) for row in rows[path]]
    if lower:
        table = [(*row[:3], lowered(row[3])) if len(row) > 3 else row for row in table]
    return table


def probe_cache(workdir, overrides=None, lower=False):
    return run_probe(workdir, "verify_cache_headers", http_table=cache_rows(overrides, lower))


def test_lowercase_security_header_names_pass(workdir):
    rows = [served(path, headers=lowered(SECURITY_HEADERS)) for path in SECURITY_PATHS]
    result = probe_security(workdir, rows)
    assert marker(result.output, "VERIFY_FAILURES") == 0, result.output


@pytest.mark.parametrize("lower", [False, True], ids=["http1", "http2"])
def test_a_correctly_configured_site_passes(workdir, lower):
    result = probe_cache(workdir, lower=lower)
    assert marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert "[FAIL]" not in result.output


def test_a_stylesheet_still_cached_for_a_week_fails(workdir):
    css = "/css/style.css"
    result = probe_cache(workdir, {css: [(BASE_URL + css, "200", "", A_WEEK_IMMUTABLE)]})
    assert marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert (
        f"{css} -- Cache-Control 'max-age=604800,public, immutable', want 'no-cache'"
        in result.output
    )


@pytest.mark.parametrize("lower", [False, True], ids=["http1", "http2"])
def test_a_second_cache_control_header_on_a_revalidated_path_fails(workdir, lower):
    # What an add_header left on top of `expires epoch` would send.
    js = "/admin/js/admin.js"
    both = (("Cache-Control", "no-cache"), ("Cache-Control", "public, immutable"))
    result = probe_cache(workdir, {js: [(BASE_URL + js, "200", "", both)]}, lower=lower)
    assert marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert f"{js} -- Cache-Control 'no-cache,public, immutable', want 'no-cache'" in result.output


def test_a_font_that_lost_immutable_fails(workdir):
    result = probe_cache(workdir, {FONT: [(BASE_URL + FONT, "200", "", NO_CACHE)]})
    assert marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert f"{FONT} -- HTTP 200, Cache-Control 'no-cache', want immutable" in result.output


def test_a_font_that_also_revalidates_fails(workdir):
    # The opposite mistake: the font block inheriting `expires epoch` while
    # keeping its own add_header.
    both = (("Cache-Control", "no-cache"), ("Cache-Control", "public, immutable"))
    result = probe_cache(workdir, {FONT: [(BASE_URL + FONT, "200", "", both)]})
    assert marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert "Cache-Control 'no-cache,public, immutable', want immutable" in result.output


def test_the_console_is_loaded_twice_after_a_pause_without_retries(workdir):
    result = probe_cache(workdir)
    assert marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert result.sleeps == ["2"]
    probes = [BASE_URL + path for path in [*REVALIDATED, FONT]]
    load = [BASE_URL + path for path in CONSOLE]
    assert result.calls == probes + load + load


def test_the_console_list_is_what_admin_index_html_loads():
    # deploy.sh runs one deploy behind itself, so when the console's page
    # gains or renames a stylesheet or script, its list must change a deploy
    # ahead. This test is what notices.
    html = (REPO_ROOT / "frontend" / "public" / "admin" / "index.html").read_text(encoding="utf-8")
    assets = re.findall(r'<link rel="stylesheet" href="([^"]+)"|<script src="([^"]+)"', html)
    assert ["/admin/", *(css or js for css, js in assets)] == CONSOLE


def test_a_503_while_loading_the_console_fails_and_is_not_retried(workdir):
    tokens = "/css/tokens.css"
    rows = [(BASE_URL + tokens, "200", "", NO_CACHE), (BASE_URL + tokens, "503", "")]
    result = probe_cache(workdir, {tokens: rows})
    assert marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert f"{tokens} (load 2 of 2) -- HTTP 503" in result.output
    assert result.calls.count(BASE_URL + tokens) == 2


def test_a_rate_limited_cache_probe_is_retried(workdir):
    js = "/admin/js/admin.js"
    rows = [(BASE_URL + js, "503", ""), (BASE_URL + js, "200", "", NO_CACHE)]
    result = probe_cache(workdir, {js: rows})
    assert marker(result.output, "VERIFY_FAILURES") == 0, result.output
    # The retry's pause, then the pause before the console loads.
    assert result.sleeps == ["2", "2"]
    # The probe, its retry, and one request per load.
    assert result.calls.count(BASE_URL + js) == 4


def test_a_checkout_without_the_policy_is_not_checked(workdir):
    # A rollback to a commit from before the policy restores the old headers,
    # and the deploy doing it must not fail for that.
    conf = workdir / "nginx" / "sites" / "production" / "production.conf"
    conf.write_text("server {\n    location / {\n    }\n}\n")
    result = probe_cache(workdir)
    assert marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert result.calls == []
    assert "production profile in this checkout sets no revalidation policy" in result.output
    # Expected right after such a rollback, and a warning any other time.
    assert "[WARN]" in result.output


def test_a_respaced_directive_still_counts(workdir):
    conf = workdir / "nginx" / "sites" / "production" / "production.conf"
    conf.write_text("server {\n    location / {\n        expires epoch ;\n    }\n}\n")
    result = probe_cache(workdir)
    assert marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert result.calls, "`expires epoch ;` was not recognised, and the check skipped"


@pytest.mark.parametrize(
    "site, checked", [("production", True), ("dev", False), ("bootstrap", False)]
)
def test_the_checkout_s_own_profiles_are_read_as_intended(workdir, site, checked):
    # The real nginx/sites/, so a directive respaced or moved into an include
    # cannot switch the check off in production without this failing.
    shutil.copytree(REPO_ROOT / "nginx" / "sites", workdir / "nginx" / "sites", dirs_exist_ok=True)
    (workdir / ".env").write_text(f"NGINX_SITE={site}\n")
    result = probe_cache(workdir)
    assert marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert bool(result.calls) is checked


def test_the_active_profile_decides(workdir):
    # The dev and bootstrap profiles set no cache policy, even when the
    # production one does.
    dev = workdir / "nginx" / "sites" / "dev"
    dev.mkdir()
    (dev / "dev.conf").write_text("server {\n    location / {\n    }\n}\n")
    (workdir / ".env").write_text("NGINX_SITE=dev\n")
    result = probe_cache(workdir)
    assert marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert result.calls == []
    assert "dev profile in this checkout sets no revalidation policy" in result.output


@pytest.mark.parametrize(
    "line", ['NGINX_SITE="production"', "NGINX_SITE=production # the live profile"]
)
def test_a_profile_name_that_names_no_directory_fails(workdir, line):
    # docker compose strips the quotes and the comment and mounts production;
    # read raw, the value names no profile, and a skip would pass unchecked.
    (workdir / ".env").write_text(line + "\n")
    result = probe_cache(workdir)
    assert marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert "names no directory under nginx/sites/" in result.output
    assert result.calls == []


def test_verify_all_runs_the_cache_check():
    source = DEPLOY_SH.read_text(encoding="utf-8")
    body = re.search(r"^verify_all\(\) \{\n(.*?)^\}", source, re.M | re.S)
    assert body, "verify_all() not found in scripts/deploy.sh"
    assert re.search(r"^\s+verify_cache_headers$", body.group(1), re.M)
```

- [ ] **Step 2 (developer): run them and watch them fail.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_deploy_live_headers.py; echo "rc=$?"`

Expected: `rc=1`, with 19 failed and 14 passed.
- The eighteen probe tests fail with `VERIFY_FAILURES marker missing`, because `verify_cache_headers: command not found` ends the probe. The `verify_all` test fails its search.
- The 14 that pass are Task 4's 12, the lowercase security-header case, and the console-list test, which reads only `admin/index.html`.

- [ ] **Step 3 (devops-sre): add the function.** Insert after the closing `}` of `verify_security_headers()`:

```bash

# ---------------------------------------------------------------------------
# Cache headers, probed on the live site
# ---------------------------------------------------------------------------
#
# docs/design/2026-09-25-reflection-redesign.md, section 8. Pages, CSS and JS
# keep unversioned names and change together, so they must revalidate on every
# load: `expires epoch`, which nginx sends as Cache-Control: no-cache. Fonts and
# images stay cached for a week as immutable. tests/test_nginx_cache_policy.py
# proves that of the checkout; this proves it of what the live site sends.
#
# Then the console's page, stylesheets and script are loaded twice in a row,
# with no retry, and must get no 503. That shows they are served, and that a
# plain reload of them fits the limits. It cannot show which zone limits which
# path, and a browser's reload also makes the console's API calls, in
# parallel; tests/test_nginx_cache_policy.py pins the zones.
#
# deploy.sh runs one deploy behind itself, so the deploy that changes the
# policy for a path probed here runs the previous copy of these lists. Loosen
# a path's expectation a deploy ahead of the nginx change that alters it, or
# of the change that renames a probed file.

# Prints every value of header $2, matched case-insensitively, from the curl
# -D dump in $1, one per line.
header_values() {
    tr -d '\r' <"$1" | awk -v want="$2" '
        BEGIN { want = tolower(want) }
        {
            i = index($0, ":")
            if (i > 1 && tolower(substr($0, 1, i - 1)) == want) {
                value = substr($0, i + 1)
                sub(/^[ \t]+/, "", value)
                print value
            }
        }'
}

verify_cache_headers() {
    # Compared against the checkout, like the checks above. A rollback to a
    # commit from before the policy, and the dev and bootstrap profiles, have
    # no `expires epoch` to find and nothing to check.
    local site
    site=$(env_get NGINX_SITE dev)
    # docker compose strips quotes and inline comments from .env; env_get does
    # not. A value it cannot resolve would otherwise read as "no policy" and
    # pass unchecked.
    if [ ! -d "nginx/sites/$site" ]; then
        vfail "NGINX_SITE='$site' in .env names no directory under nginx/sites/; cache headers not checked"
        return 0
    fi
    if ! grep -qsE '^[[:space:]]*expires[[:space:]]+epoch[[:space:]]*;' nginx/sites/"$site"/*.conf; then
        if [ "$site" = "production" ]; then
            # Expected right after a rollback to a commit from before the
            # policy. Any other time it means this check stopped finding it.
            warn "the production profile in this checkout sets no revalidation policy; cache headers not checked"
        else
            ok "the $site profile in this checkout sets no revalidation policy; no cache headers to check"
        fi
        return 0
    fi

    local -a revalidated=(/ /css/style.css /admin/ /admin/css/admin.css /admin/js/admin.js)
    local immutable=/fonts/jetbrains-mono-latin.woff2
    # What a browser requests to show the console once its fonts and images
    # are cached; they are immutable, so a reload does not ask for them again.
    local -a console=(/admin/ /css/fonts.css /css/tokens.css /admin/css/admin.css /admin/js/admin.js)
    local path code values opts round dump fails=0
    dump=$(mktemp)

    for path in "${revalidated[@]}"; do
        code=$(fetch_with_retry /dev/null "$BASE_URL$path" -D "$dump")
        values=$(header_values "$dump" cache-control | paste -sd, -)
        if [ "$code" != "200" ]; then
            bad "$path -- HTTP $code"
            fails=$((fails + 1))
        elif [ "$values" != "no-cache" ]; then
            bad "$path -- Cache-Control '${values:-<none>}', want 'no-cache'"
            fails=$((fails + 1))
        else
            ok "$path  Cache-Control: no-cache"
        fi
    done

    code=$(fetch_with_retry /dev/null "$BASE_URL$immutable" -D "$dump")
    values=$(header_values "$dump" cache-control | paste -sd, -)
    rm -f "$dump"
    if [ "$code" = "200" ] && [[ "$values" == *immutable* ]] && [[ "$values" != *no-cache* ]]; then
        ok "$immutable  Cache-Control: $values"
    else
        bad "$immutable -- HTTP $code, Cache-Control '${values:-<none>}', want immutable"
        fails=$((fails + 1))
    fi

    # Let the probes above drain out of the limiter first, so both loads start
    # from a full burst, as a visitor's would.
    sleep "$FETCH_RETRY_PAUSE"
    opts=$(curl_base)
    for round in 1 2; do
        for path in "${console[@]}"; do
            set +e
            # shellcheck disable=SC2086
            code=$(curl $opts -o /dev/null -w '%{http_code}' "$BASE_URL$path" 2>/dev/null)
            set -e
            if [ "$code" != "200" ]; then
                bad "$path (load $round of 2) -- HTTP $code"
                fails=$((fails + 1))
            fi
        done
    done

    if [ "$fails" -ne 0 ]; then
        vfail "$fails cache-header check(s) failed on the live site"
        bad "if this deploy changed nginx/, run 'scripts/nginx-apply.sh check' before believing anything else"
        return 0
    fi
    ok "pages, CSS and JS revalidate, fonts stay immutable, and the console loads twice with no 503"
}
```

- [ ] **Step 4 (devops-sre): call it from `verify_all()`.** Replace:

```bash
    step "Verifying security headers on the live site"
    verify_security_headers
```

with:

```bash
    step "Verifying security headers on the live site"
    verify_security_headers
    step "Verifying cache headers on the live site"
    verify_cache_headers
```

- [ ] **Step 5 (devops-sre): run the tests and the checks.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_deploy_live_headers.py tests/test_deploy_frontend_assets.py; echo "rc=$?"`
Expected: `52 passed`, `rc=0`.

Run shellcheck (expected `rc=0`) and the lint pair on `tests/test_deploy_live_headers.py` (expected both `rc=0`).

- [ ] **Step 6 (devops-sre): commit.**

```bash
git add tests/test_deploy_live_headers.py scripts/deploy.sh
git commit -m "Check the live cache headers after every deploy"
```

---

## Chunk 3: PR 1a, stale comments, and shipping 1a

Same branch as Chunks 1 and 2.

### Task 6: Stale comments

Comments only, so there is no test. The spec lists the fonts README, the `nginx.conf` line numbers and "exactly one script". Four other stale spots turned up while planning:
- the KNOWN BREAKAGE and COMPROMISE paragraphs, which describe a policy that no longer exists;
- the "four blocks" counts, which Task 1 made wrong;
- the `default.conf` references.

The fonts README is under `frontend/public`, so it waits for PR 1b (Task 11).

Each edit below leaves untouched the comment line that lists the absent script constructs; that line starts `#                         eval, no`. Neither an edit's old text nor its new text includes that line.

**Files:**
- Modify: `nginx/nginx.conf`: the CSP comment and the `limit_conn` comment
- Modify: `scripts/deploy.sh`: the `/api/auth/token` retry comment and the `nginx_csp_from_checkout()` comment
- Modify: `nginx/sites/bootstrap/bootstrap.conf`: the HSTS comment

- [ ] **Step 1 (devops-sre): `nginx/nginx.conf`, the map's "four blocks".** Replace:

```nginx
    # exactly one place even though four blocks emit it, so the copies cannot
```

with:

```nginx
    # exactly one place even though several blocks emit it, so the copies cannot
```

- [ ] **Step 2 (devops-sre): `nginx/nginx.conf`, the start of the `script-src` entry.** Replace these three lines:

```nginx
    #   script-src  'self'    index.html and admin/index.html load exactly one
    #                         external <script> each (/js/main.js,
    #                         /admin/js/admin.js). No inline <script>, no
```

with:

```nginx
    #   script-src  'self'    External scripts only, all from this origin:
    #                         index.html loads /js/theme-init.js (in <head>, so
    #                         the theme is set before first paint) and
    #                         /js/main.js; admin/index.html loads
    #                         /admin/js/admin.js. No inline <script>, no inline
    #                         event handler, no
```

The two lines that follow stay as they are.

- [ ] **Step 3 (devops-sre): `nginx/nginx.conf`, the two stale paragraphs.** Replace everything from `#                         KNOWN BREAKAGE, pre-existing: index.html lines` down to and including `#                         error pages with no error message.` with:

```nginx
    #                         tests/test_public_page_csp.py clicks the public
    #                         page's copy buttons in Chrome under this policy.
```

That removes the KNOWN BREAKAGE paragraph, since the copy buttons use listeners now, and the `style-src 'self' 'unsafe-inline'` COMPROMISE entry. The `style-src 'self'` paragraph further down, which records the removal of `'unsafe-inline'`, stays.

- [ ] **Step 4 (devops-sre): `nginx/nginx.conf`, the `img-src`, `font-src` and `connect-src` entries.** Replace:

```nginx
    #   img-src     'self'    /img/*.svg and /img/favicon.svg. 'data:' was
    #                         dropped: no data: or base64 image URI exists in
    #                         any html, css or js under frontend/public.
    #   font-src    'self'    all 13 @font-face url() in css/fonts.css point at
    #                         /fonts/*.woff2. Nothing reaches fonts.gstatic.com
    #                         any more; the only googleapis.com string left in
    #                         the tree is a provenance comment.
    #   connect-src 'self'    both clients fetch a relative '/api' base
    #                         (js/main.js:31, admin/js/admin.js:11). No
    #                         WebSocket, no EventSource.
```

with:

```nginx
    #   img-src     'self'    everything under /img/. 'data:' was dropped: no
    #                         data: or base64 image URI exists in any html, css
    #                         or js under frontend/public.
    #   font-src    'self'    every @font-face url() in css/fonts.css points at
    #                         /fonts/*.woff2. Nothing reaches fonts.gstatic.com
    #                         any more; the only googleapis.com strings left
    #                         under frontend/public are provenance comments.
    #   connect-src 'self'    both clients fetch a relative '/api' base
    #                         (`baseUrl` in js/main.js, `apiBase` in
    #                         admin/js/admin.js). No WebSocket, no EventSource.
```

`/favicon.ico` is left out of `img-src` here: it arrives in PR 1b, and Task 14 adds it to this comment together with the file.

- [ ] **Step 5 (devops-sre): `nginx/nginx.conf`, the CSSOM line numbers.** Replace:

```nginx
    #                         assumed: CSSOM assignment. `el.style.background =
    #                         '...'` applies (js/main.js:79-100 status pulse,
    #                         admin.js:299 toast) and so does `el.style.cssText`.
```

with:

```nginx
    #                         assumed: CSSOM assignment. `el.style.background =
    #                         '...'` applies (the status pulse's
    #                         `pulse.style.background` in js/main.js, the
    #                         toast's `toast.style.animation` in
    #                         admin/js/admin.js) and so does `el.style.cssText`.
```

Names instead of line numbers, so the reference survives edits. PR 2 removes the pulse half and PR 3 the toast half (spec section 8).

- [ ] **Step 6 (devops-sre): `nginx/nginx.conf`, the `limit_conn` paragraph.** Replace:

```nginx
    # Not wired up in this change on purpose. The place it belongs is the three
    # mirror locations in default.conf, and per-IP connection caps there are a
    # traffic decision that needs real numbers: a NAT'd university or a
    # parallel poudriere fetch legitimately opens many connections, and the
    # failure mode is a silent 503 to a real downloader. This repo has already
    # shipped exactly that bug once with limit_conn on login. It wants its own
    # change with load evidence, which is:
```

with:

```nginx
    # Not wired up in this change on purpose. The place it belongs is the three
    # mirror locations in sites/production/production.conf, and per-IP
    # connection caps there are a traffic decision that needs real numbers: a
    # NAT'd university or a parallel poudriere fetch legitimately opens many
    # connections, and the failure mode is a silent 503 to a real downloader.
    # This repo has already shipped exactly that bug once with limit_conn on
    # login. It wants its own change with load evidence, which is:
```

- [ ] **Step 7 (devops-sre): `scripts/deploy.sh`, two comments.** Replace:

```bash
        # nginx applies `limit_req zone=auth_limit ... rate=3r/s` to this exact
        # location (nginx/sites/default.conf:65). Back off rather than reporting
        # a rate limit as an auth failure.
```

with:

```bash
        # nginx applies `limit_req zone=auth_limit ... rate=3r/s` to this exact
        # location (`location = /api/auth/token` in
        # nginx/sites/production/production.conf). Back off rather than
        # reporting a rate limit as an auth failure.
```

Then replace:

```bash
# down even though four blocks in nginx/ emit it (see the comment above that
```

with:

```bash
# down even though several blocks in nginx/ emit it (see the comment above that
```

- [ ] **Step 8 (devops-sre): `nginx/sites/bootstrap/bootstrap.conf`.** Replace:

```nginx
# working HTTPS yet to fall forward to. HSTS belongs only in the 443 server of
# default.conf, which is what scripts/ssl-setup.sh switches to afterwards.
```

with:

```nginx
# working HTTPS yet to fall forward to. HSTS belongs only in the 443 server of
# sites/production/production.conf, which is what scripts/ssl-setup.sh switches
# to afterwards.
```

- [ ] **Step 9 (devops-sre): check that nothing stale is left, and that nothing broke.**

Run: `grep -n -i -E 'load exactly one|KNOWN BREAKAGE|COMPROMISE|all 13 @font-face|main\.js:[0-9]|admin\.js:[0-9]|default\.conf|four blocks' nginx/nginx.conf nginx/sites/bootstrap/bootstrap.conf scripts/deploy.sh; echo "rc=$?"`
Expected: no matches, `rc=1`.

Run shellcheck. Expected: `rc=0`.

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_public_page_csp.py tests/test_error_pages_inline_styles.py tests/test_nginx_cache_policy.py; echo "rc=$?"`. The first two read `nginx.conf`. Expected: `rc=0`.

- [ ] **Step 10 (devops-sre): commit.**

```bash
git add nginx/nginx.conf nginx/sites/bootstrap/bootstrap.conf scripts/deploy.sh
git commit -m "Correct stale comments in the nginx and deploy configs"
```

### Task 7 (controller): The spec, and this plan

**Files:**
- Modify: `docs/design/2026-09-25-reflection-redesign.md`, sections 2, 4.6, 8 and 11
- Add: this plan

- [ ] **Step 1: sections 2 and 4.6.**
  - In section 2's `Delivery` row, replace `then the admin console (section 11)` with `then the admin console; the foundation ships as two pull requests, 1a and 1b (section 11)`.
  - Replace `- **`img/apple-touch-icon.png`**, 180px, light tile.` with `- **`img/apple-touch-icon.png`**, 180px: the light tile, full-bleed and opaque. iOS rounds the corners itself and paints transparent pixels black, so the tile's own corners and edge are left out.`
  - In the render command, replace `docker run --rm -u` with `docker run --rm --network none -u`. Then replace `as the test service in `docker-compose.yml` already gives it.` with `as the test service in `docker-compose.yml` already gives it. `--network none` keeps the render offline, as that service is.`
  - In the `**Linked from:**` bullet, replace `all four in PR 1.` with `all four in PR 1b.`

- [ ] **Step 2: section 8.**
  - Replace `PR 1 changes about 33 files there` with `PR 1b changes about 33 files there`.
  - In the soak paragraph, replace `fetched before PR 1 deploys` with `fetched before PR 1a deploys`, and `no earlier than 7 days after PR 1.` with `no earlier than 7 days after PR 1a.`
  - In the housekeeping list, replace `PR 1 updates the numbers.` with `PR 1 replaces the line numbers with names.`
  - In the table's error-pages row, replace `Their CSS revalidates like all CSS |` with `Their CSS revalidates like all CSS, so under a rate limit the 503 page can arrive unstyled: its stylesheets share `general_limit` with the request that got the 503. That is accepted; the page still says what happened |`.
  - In the table's fonts-and-images row, replace `The one exception is `favicon.svg`, whose name is fixed: its PR 1 redesign reaches returning visitors within 7 days |` with `The exceptions are the favicon files, whose names are fixed: the favicon's PR 1 redesign reaches returning visitors within 7 days |`.
  - At the end of the bullet `The admin page and its assets, loaded twice in a row, get no 503s.`, add ` This is a smoke test; the static test pins which zone limits each path.`
  - Insert this paragraph after the bullet `` - `nginx -t` runs in CI and during the deploy. `` and before `**Housekeeping in PR 1:**`, with a blank line on each side:

    ```markdown
    **Order.** A deploy runs the `deploy.sh` that was on disk when it started, so a change to `deploy.sh` protects only the deploys after it. PR 1 therefore ships as two pull requests (section 11):
    - **1a** carries the nginx change, the retries and the new probes, and nothing under `frontend/public`, so the previous `deploy.sh` has no files to fetch when 1a deploys. 1a's own cache headers are checked by hand after its deploy.
    - **1b** carries the asset files, and its deploy runs 1a's `deploy.sh`.
    ```

- [ ] **Step 3: section 11.** In the routine, replace `starting with PR 1's.` with `starting with PR 1's, which covers both 1a and 1b.` Replace the table's `1. Foundation` row with these two rows, and change the `2. Public site` row's last cell to `7 days after 1a's deploy, and after 1b's`. PR 2 needs 1b's fonts as well as 1a's cache change:

```markdown
| 1a. Cache and deploy checks | The cache change, the `/admin` asset limits and their tests (section 8); the `deploy.sh` retries and probes; the stale-reference fixes outside `frontend/public`; this spec and PR 1's plan | devops-sre for nginx and `deploy.sh`; developer for tests | None | After review |
| 1b. Assets | Unbounded and Instrument Sans self-hosted; the mark files; the favicon set, linked from all four pages; the icon set; the other PR 1 checks from section 10; the `.screenshots/` ignore entry; the `fonts/README.md` fix; the font count in `CLAUDE.md` and `.dockerignore` | devops-sre for `scripts/render_icons.py`; web-designer for assets; developer for tests | The favicon | After 1a's deploy |
```

- [ ] **Step 4: check that no replaced phrase is left.**

Run: `grep -n -E 'fetched before PR 1 deploys|after PR 1\.|all four in PR 1\.|PR 1 updates the numbers|PR 1 changes about 33|\| 1\. Foundation|180px, light tile|then the admin console \(section 11\)|starting with PR 1.s\.|after PR 1.s deploy|docker run --rm -u' docs/design/2026-09-25-reflection-redesign.md; echo "rc=$?"`
Expected: no matches, `rc=1`.

- [ ] **Step 5: commit both documents.**

```bash
git add docs/design/2026-09-25-reflection-redesign.md docs/design/2026-09-25-reflection-pr1-plan.md
git commit -m "Plan PR 1 of the Reflection redesign as two pull requests"
```

### Task 8 (controller): Gate, review, pull request, merge and deploy

- [ ] **Step 1: the full gate.** Run each and paste its summary line and `rc`:
  - the whole suite: `docker compose run --rm -T test; echo "rc=$?"`
  - the lint pair on `.`
  - shellcheck
  - `docker compose config -q; echo "rc=$?"`

  Every `rc` must be 0. If `ruff format --check .` flags a file this branch did not touch, report the file and stop; do not reformat it in this pull request.

- [ ] **Step 2: serve the production profile again.** Recreate `$SCRATCH/pr1/serve_production.sh` from Task 1 Step 5 if it is gone. Run `bash "$SCRATCH/pr1/serve_production.sh" "$PWD"`. Expected: the output Task 1 Step 5 lists.

- [ ] **Step 3: security review.** Dispatch `appsec-reviewer` on `git diff main...HEAD -- nginx scripts/deploy.sh` with these questions:
  - Does every location that adds a header still include the snippet first?
  - Can the new regex location serve anything outside `/var/www/public/admin/{css,js}/`?
  - Does any new `deploy.sh` code put secrets in argv or logs?
  - Is every temporary file removed on every return path?

  Route any finding to its owner, and re-run Steps 1 and 2 after a fix. A later fix to `nginx/` or `deploy.sh`, from review or from CI, sends it back through this review.

- [ ] **Step 4: push and open the pull request.** Write the body to `$SCRATCH/pr1a/body.md`, covering:
  - what changes and why, linking the spec;
  - the 1a/1b split and its reason;
  - the evidence from Steps 1 and 2;
  - what was not checked here: the live headers, which Step 7 checks by hand, because the `deploy.sh` that runs this deploy predates `verify_cache_headers()`;
  - an optional follow-up for the user, since workflow files are theirs to edit. CI's "Serve the production profile" step probes `/nope-404`, which `try_files` answers with the home page and a 200. The diff below makes that probe a real 404 and adds the new admin asset location. The fixture step gains an `admin.js`: without one, the probe would get the error page through `location /`, and pass without touching the new location.

    ```diff
    @@ Build the certificate and webroot fixtures
    -          mkdir -p ci-fixtures/www/admin ci-fixtures/www/css ci-fixtures/www/img
    +          mkdir -p ci-fixtures/www/admin/js ci-fixtures/www/css ci-fixtures/www/img
               echo ok      > ci-fixtures/www/index.html
               echo notfound> ci-fixtures/www/404.html
               echo admin   > ci-fixtures/www/admin/index.html
    +          echo '//'    > ci-fixtures/www/admin/js/admin.js
               echo 'body{}'> ci-fixtures/www/css/style.css
    @@ Serve the production profile and assert the headers on the wire
    -          for path in / /health /admin/ /css/style.css /img/favicon.svg /404.html /nope-404; do
    +          for path in / /health /admin/ /admin/js/admin.js /css/style.css /img/favicon.svg /404.html /css/nope-404.css; do
    ```

  No attribution lines. Then:

```bash
git push -u origin feat/reflection-foundation
gh pr create --base main --head feat/reflection-foundation \
    --title "Revalidate pages, CSS and JS; retry and extend the deploy's live checks" \
    --body-file "$SCRATCH/pr1a/body.md"
```

- [ ] **Step 5: CI.** Wait for the run with `gh pr checks <number> --watch --interval 30 >/dev/null 2>&1`, started with `run_in_background: true`. When it exits, gate on a fresh `gh pr checks <number>`. Its exit code must be 0, with every check `pass`. Do not gate on `--watch` output, which repeats early `pending` snapshots.

  If a check fails, read its log with `gh run view <run-id> --log-failed`, and route the failing lines to the owner of the file they point at. After the fix, re-run Steps 1 and 2 before pushing again.

- [ ] **Step 6: merge, with the user's approval.** Ask with AskUserQuestion. If approved, merge with `gh pr merge <number> --merge --delete-branch`. Then wait for CI on the merge commit with `$SCRATCH/pr1/wait_main_ci.sh`, started with `run_in_background: true`:

```bash
#!/usr/bin/env bash
# Wait for the CI run on origin/main's head (the merge commit) and report its
# conclusion. The push event takes a few seconds to become a workflow run, so
# this polls for up to 5 minutes before watching it. Exit status is
# `gh run watch`'s: non-zero unless the run passed.
# Usage: wait_main_ci.sh REPO_ROOT
set -uo pipefail
cd "${1:?usage: wait_main_ci.sh REPO_ROOT}" || exit 1
git fetch -q origin
sha=$(git rev-parse origin/main)
echo "merge commit: $sha"
run_id=
for _ in $(seq 1 30); do
    run_id=$(gh run list --workflow ci.yml --branch main --limit 10 --json databaseId,headSha \
        --jq ".[] | select(.headSha == \"$sha\") | .databaseId" 2>/dev/null | head -n 1)
    [ -n "$run_id" ] && break
    sleep 10
done
if [ -z "$run_id" ]; then
    echo "no ci.yml run for $sha after 5 minutes"
    exit 2
fi
echo "run: $run_id"
gh run watch "$run_id" --exit-status --interval 30 >/dev/null 2>&1
rc=$?
gh run view "$run_id" --json status,conclusion,headSha,url \
    --jq '"status=\(.status) conclusion=\(.conclusion) sha=\(.headSha) \(.url)"'
if [ "$rc" -ne 0 ]; then
    gh run view "$run_id" --json jobs \
        --jq '.jobs[] | select(.conclusion != "success") | "  \(.name): \(.conclusion)"'
fi
echo "watch rc=$rc"
exit "$rc"
```

Run: `bash "$SCRATCH/pr1/wait_main_ci.sh" "$PWD"`. Expected: `conclusion=success` and `watch rc=0`. On anything else, stop and report.

- [ ] **Step 7: deploy, with the user's approval.** Ask with AskUserQuestion. The question shows the exact command that deploys, `ssh root@46.4.100.234 'cd /opt/bsdmirror && scripts/deploy.sh --yes main'`, and says what the wrapper below adds around it: a wait if the hourly health run is due within 10 minutes, and a redacted copy of the output. If approved, run `$SCRATCH/pr1/deploy_and_verify.sh` with `run_in_background: true`. If the permission layer refuses it, nothing in the script ran, the timer check included. Stop, and hand the user the ssh command to run themselves, with the time to start it. For that time, run the script's timer one-liner on its own; it only reads. If that is refused too, tell them the timer fires hourly with up to 5 minutes of random delay (`RandomizedDelaySec=5m` in `scripts/systemd/bsdmirror-health.timer`), so a start between about :08 and :50 stays clear of it. Carry on with the checks below once they report the result.

```bash
#!/usr/bin/env bash
# Deploy origin/main to production and show what the deploy reported.
# The deploy itself is an ssh argument, never a script on ssh's stdin.
# Its output is redacted on the way in, so no copy on disk holds a secret
# even if a future deploy.sh prints one.
# Usage: deploy_and_verify.sh REPO_ROOT OUT_DIR
set -uo pipefail
cd "${1:?usage: deploy_and_verify.sh REPO_ROOT OUT_DIR}" || exit 1
OUT="${2:?usage: deploy_and_verify.sh REPO_ROOT OUT_DIR}"
mkdir -p "$OUT"
HOST=root@46.4.100.234
SITE=https://mirror.kalev.systems
git fetch -q origin
echo "== deploying $(git rev-parse --short=7 origin/main) =="

# Webhook URLs, anything JWT-shaped, and the user:password part of any URL,
# including redis://:password@ with no user.
redact() {
    sed -E -e 's#https?://[^[:space:]]*(webhook|hooks)[^[:space:]]*#<redacted-url>#g' \
           -e 's#eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+#<redacted-jwt>#g' \
           -e 's#://[^/[:space:]@:]*:[^/[:space:]@]+@#://<redacted-userinfo>@#g'
}

# Keep the backend recreate clear of the hourly health run: a run that lands
# while the backend is down reports the API as failing and posts a real alert.
# The remote side prints nothing when the timer has no next run.
next=$(ssh -o ConnectTimeout=10 "$HOST" \
    'v=$(systemctl show bsdmirror-health.timer -p NextElapseUSecRealtime --value); case "$v" in ""|n/a) ;; *) date -d "$v" +%s ;; esac' </dev/null)
case "$next" in ''|*[!0-9]*) next= ;; esac
now=$(date +%s)
if [ -z "$next" ]; then
    echo "  could not read the timer's next run; not waiting"
else
    echo "  next health run in $(( (next - now) / 60 )) min"
    if [ $(( next - now )) -lt 600 ] && [ $(( next - now )) -gt -60 ]; then
        wait_s=$(( next - now + 150 ))
        echo "  waiting ${wait_s}s so the deploy starts after that run has finished"
        sleep "$wait_s"
    fi
fi

ssh -o ConnectTimeout=10 "$HOST" 'cd /opt/bsdmirror && scripts/deploy.sh --yes main' </dev/null 2>&1 \
    | redact >"$OUT/deploy.out"
rc=${PIPESTATUS[0]}
echo "  deploy.sh rc=$rc"
grep -E -A1 'Gate 3/3' "$OUT/deploy.out" | sed 's/^/    /'
sed -n '/^==> Verifying$/,$p' "$OUT/deploy.out"
if [ "$rc" -ne 0 ]; then
    echo "== the last 60 lines of the deploy's output =="
    tail -n 60 "$OUT/deploy.out"
fi

echo "== live version =="
curl -fsS --max-time 10 "$SITE/api/health"; echo
exit "$rc"
```

Run: `bash "$SCRATCH/pr1/deploy_and_verify.sh" "$PWD" "$SCRATCH/pr1a"`.

Then run these live probes by hand. The `deploy.sh` that ran this deploy predates them:

```bash
SITE=https://mirror.kalev.systems
echo "== live cache and security headers =="
for p in / /css/style.css /admin/ /admin/css/admin.css /admin/js/admin.js \
         /fonts/jetbrains-mono-latin.woff2 /img/favicon.svg; do
    h=$(curl -sS --max-time 10 -o /dev/null -D - "$SITE$p" | tr -d '\r')
    code=$(printf '%s\n' "$h" | awk '/^HTTP\//{print $2}')
    cc=$(printf '%s\n' "$h" | grep -i '^cache-control:' | cut -d' ' -f2- | paste -sd, -)
    sec=$(printf '%s\n' "$h" | awk -F: 'tolower($1) ~ /^(x-frame-options|x-content-type-options|referrer-policy|content-security-policy|strict-transport-security)$/ {print tolower($1)}' | sort -u | wc -l | tr -d ' ')
    robots=$(printf '%s\n' "$h" | grep -i '^x-robots-tag:' | cut -d' ' -f2-)
    printf '  %-36s %s  cc=%-36s security=%s/5 robots=%s\n' "$p" "$code" "${cc:-<none>}" "$sec" "${robots:-<none>}"
done
sleep 2
echo "== the console, loaded twice, no retry =="
for round in 1 2; do
    printf '  load %s:' "$round"
    for p in /admin/ /css/fonts.css /css/tokens.css /admin/css/admin.css /admin/js/admin.js; do
        printf ' %s' "$(curl -sS --max-time 10 -o /dev/null -w '%{http_code}' "$SITE$p")"
    done
    echo
done
```

Then run the two new checks from the deployed `deploy.sh`, on the server. Sourcing the file defines its functions and runs nothing else, and both checks only send GET requests to the public site:

```bash
ssh -o ConnectTimeout=10 root@46.4.100.234 \
    'cd /opt/bsdmirror && BASE_URL=https://mirror.kalev.systems bash -c "source scripts/deploy.sh; verify_security_headers; verify_cache_headers; echo VERIFY_FAILURES=\$VERIFY_FAILURES"' </dev/null
echo "rc=$?"
```

Expected:
- `deploy.sh rc=0`, and the verification ends with `all post-deploy checks passed`. The frontend check reports no `frontend/public` changes.
- The live version is the merge commit.
- Every probed path shows `security=5/5`, and the three admin paths show `robots=noindex, nofollow`.
- The first five paths answer `200 cc=no-cache`. The font and the favicon answer `200 cc=max-age=604800,public, immutable`.
- Both loads print five `200`s.
- The server-side run prints no `[FAIL]` line. Its `[ OK ]` lines include `all 10 probed paths carry the full 5-header set` and `pages, CSS and JS revalidate, fonts stay immutable, and the console loads twice with no 503`. It ends with `VERIFY_FAILURES=0`, then `rc=0`. A missing `VERIFY_FAILURES` line means a check stopped the shell, which is a failure too.

If `deploy.sh` exits non-zero, or anything differs from this list, stop. Report what differs, with the output, and ask the user before any rollback or other production action.

- [ ] **Step 8: record the soak.** PR 2 may deploy 7 days after this deploy at the earliest. Put the date, 1a's PR number and its merge commit in the `bsdmirror-reflection-redesign` memory, and tell the user.

---

## Chunk 4: PR 1b, the fonts

Branch: `feat/reflection-assets`, from `main` after PR 1a has merged and deployed.

### Task 9: Branch, and pin today's font conventions

These checks pass against today's 13 font files. They are committed first, on their own, so they guard the conventions before any new file arrives, whatever the user decides in Task 10.

**Files:**
- Create: `tests/test_fonts.py`

- [ ] **Step 1 (controller): branch.**

```bash
git switch main && git pull --ff-only && git switch -c feat/reflection-assets
```

- [ ] **Step 2 (developer): write the tests.** Create `tests/test_fonts.py`:

```python
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
```

- [ ] **Step 3 (developer): run it and lint it.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_fonts.py; echo "rc=$?"`

Expected: `49 passed`, `rc=0`:
- 16 stylesheets, pages, scripts and SVGs free of Google hosts;
- the `url()` check;
- every `@font-face` parses, and `fonts/` holds nothing but fonts, licences and the README;
- the three-way list;
- 13 WOFF2 signatures and 13 checksums;
- 2 licences, each with no Reserved Font Name;
- the leftover-licence check.

Then the lint pair on `tests/test_fonts.py`, and the whole suite. Expected: every `rc=0`.

- [ ] **Step 4 (developer): commit.**

```bash
git add tests/test_fonts.py
git commit -m "Check the self-hosted fonts against fonts.css and their README"
```

### Task 10 (controller): The download request, and the downloads

No font is saved before the user approves. Step 2 reads Google's stylesheet into memory, the way a browser would, to learn which files it names, and asks for each file's size with a `HEAD` request. It writes three small text files to `$SCRATCH/fonts/`: the google/fonts commit, the font URLs with their names, and every file's status and size. After approval, the files land in `$SCRATCH/fonts/`, and are checked there before anything reaches the repo.

- [ ] **Step 1: the tools.** Write `$SCRATCH/fonts/filter_fonts.py`:

```python
"""Keep the latin and latin-ext @font-face blocks of a Google Fonts css2
response, rewritten the way css/fonts.css holds its blocks.

Usage: python filter_fonts.py GOOGLE_CSS FONTS_CSS DATE SECTION_OUT FILES_OUT
GOOGLE_CSS may be - for stdin. Writes the new fonts.css section, stamped with
DATE, to SECTION_OUT, and one "<url> <filename>" line per font file to
FILES_OUT.
"""

import re
import sys

KEEP = ("latin", "latin-ext")
REQUEST = (
    "https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600\\\n"
    "       &family=Unbounded:wght@600;700&display=swap"
)

google_css, fonts_css, date, section_out, files_out = sys.argv[1:6]
css = sys.stdin.read() if google_css == "-" else open(google_css, encoding="utf-8").read()
rule = re.search(r"^/\* (=+)$", open(fonts_css, encoding="utf-8").read(), re.M).group(1)
blocks = re.findall(r"/\* ([a-z-]+) \*/\n(@font-face \{\n.*?\n\})", css, re.S)
if not blocks:
    sys.exit("no @font-face blocks; was the CSS fetched with a Chrome User-Agent?")

by_family: dict[str, list[str]] = {}
by_name: dict[str, str] = {}
for subset, block in blocks:
    if subset not in KEEP:
        continue
    family = re.search(r"font-family: '([^']+)';", block).group(1)
    url = re.search(r"src: url\((https://fonts\.gstatic\.com/\S+?\.woff2)\)", block).group(1)
    name = f"{family.lower().replace(' ', '-')}-{subset}.woff2"
    if by_name.setdefault(name, url) != url:
        sys.exit(f"{name} would hold two different files: not a variable font")
    block = re.sub(r"(?m)^  ", "    ", block.replace(f"url({url})", f"url('/fonts/{name}')"))
    by_family.setdefault(family, []).append(f"/* {subset} */\n{block}")

intro = f"""

/* {rule}
   Added {date} for the Reflection redesign. GENERATED like the blocks
   above: the latin and latin-ext blocks of what Google Fonts returned for

     {REQUEST}

   with url() pointed at /fonts/ and re-indented to four spaces. Nothing else
   was altered. The other subsets were left out: these two faces set the
   site's own copy, which is English, and any other character falls back to
   the next font in the stack.
   {rule} */
"""
with open(section_out, "w", encoding="utf-8") as out:
    out.write(intro)
    for family, family_blocks in by_family.items():
        out.write(f"\n\n/* {rule}\n   {family}\n   {rule} */\n\n")
        out.write("\n".join(family_blocks) + "\n")
with open(files_out, "w", encoding="utf-8") as out:
    for name, url in by_name.items():
        out.write(f"{url} {name}\n")
```

Then write `$SCRATCH/fonts/fontinfo.mjs`. It reads each WOFF2's name table and axes with Node's built-in brotli, so recording versions needs no package download. On the repo's own files it prints `Version 4.001;git-66647c0bb` / `wght 100-900` for Inter and `Version 2.211` / `wght 400-800` for JetBrains Mono, which is what `fonts/README.md` records.

```js
// Print each WOFF2 file's version (name ID 5), variation axes, licence URL
// (name ID 14) and copyright (name ID 0). Node built-ins only: WOFF2 is a
// brotli stream of the font's tables, and 'name' and 'fvar' are never
// transformed. Usage: node fontinfo.mjs FILE.woff2...
import { readFileSync } from 'node:fs';
import { brotliDecompressSync } from 'node:zlib';

// The WOFF2 specification's table of known tags, by flag index 0-62.
const KNOWN = ['cmap', 'head', 'hhea', 'hmtx', 'maxp', 'name', 'OS/2', 'post', 'cvt ', 'fpgm',
    'glyf', 'loca', 'prep', 'CFF ', 'VORG', 'EBDT', 'EBLC', 'gasp', 'hdmx', 'kern', 'LTSH',
    'PCLT', 'VDMX', 'vhea', 'vmtx', 'BASE', 'GDEF', 'GPOS', 'GSUB', 'EBSC', 'JSTF', 'MATH',
    'CBDT', 'CBLC', 'COLR', 'CPAL', 'SVG ', 'sbix', 'acnt', 'avar', 'bdat', 'bloc', 'bsln',
    'cvar', 'fdsc', 'feat', 'fmtx', 'fvar', 'gvar', 'hsty', 'just', 'lcar', 'mort', 'morx',
    'opbd', 'prop', 'trak', 'Zapf', 'Silf', 'Glat', 'Gloc', 'Feat', 'Sill'];

function tables(buf) {
    if (buf.toString('latin1', 0, 4) !== 'wOF2') throw new Error('not a WOFF2 file');
    const numTables = buf.readUInt16BE(12);
    const compressedSize = buf.readUInt32BE(20);
    let pos = 48;
    const base128 = () => {
        let value = 0;
        for (let i = 0; i < 5; i++) {
            const byte = buf[pos++];
            value = value * 128 + (byte & 0x7f);
            if (!(byte & 0x80)) return value;
        }
        throw new Error('bad UIntBase128');
    };
    const directory = [];
    for (let i = 0; i < numTables; i++) {
        const flags = buf[pos++];
        let tag = KNOWN[flags & 0x3f];
        if ((flags & 0x3f) === 63) {
            tag = buf.toString('latin1', pos, pos + 4);
            pos += 4;
        }
        const version = flags >> 6;
        const origLength = base128();
        // glyf and loca use transform 3 for "none"; every other table uses 0.
        const transformed = tag === 'glyf' || tag === 'loca' ? version !== 3 : version !== 0;
        directory.push({ tag, length: transformed ? base128() : origLength });
    }
    const data = brotliDecompressSync(buf.subarray(pos, pos + compressedSize));
    const found = {};
    let offset = 0;
    for (const { tag, length } of directory) {
        found[tag] = data.subarray(offset, offset + length);
        offset += length;
    }
    return found;
}

function names(table) {
    const count = table.readUInt16BE(2);
    const strings = table.readUInt16BE(4);
    const found = {};
    for (let i = 0; i < count; i++) {
        const [platform, , language, id, length, offset] = [0, 2, 4, 6, 8, 10]
            .map((o) => table.readUInt16BE(6 + 12 * i + o));
        if (platform !== 3 || language !== 0x409) continue;
        const utf16be = Buffer.from(table.subarray(strings + offset, strings + offset + length));
        found[id] = utf16be.swap16().toString('utf16le');
    }
    return found;
}

function axes(fvar) {
    if (!fvar) return 'none (static)';
    const first = fvar.readUInt16BE(4);
    const count = fvar.readUInt16BE(8);
    const size = fvar.readUInt16BE(10);
    return Array.from({ length: count }, (_, i) => {
        const at = first + i * size;
        const fixed = (o) => fvar.readInt32BE(at + o) / 65536;
        return `${fvar.toString('latin1', at, at + 4)} ${fixed(4)}-${fixed(12)}`;
    }).join(', ');
}

for (const file of process.argv.slice(2)) {
    const found = tables(readFileSync(file));
    const name = names(found.name);
    console.log(`${file}
  version:   ${name[5]}
  axes:      ${axes(found.fvar)}
  licence:   ${name[14] ?? '(none)'}
  copyright: ${name[0]}`);
}
```

- [ ] **Step 2: learn the files and their sizes, saving nothing but the list.**

```bash
F="$SCRATCH/fonts"; mkdir -p "$F"
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
CSS_URL='https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600&family=Unbounded:wght@600;700&display=swap'
head_of() {   # "<status> <content-length or unknown>", without downloading the file
    curl -sSI --max-time 20 "$1" | tr -d '\r' | awk '
        /^HTTP\// { code = $2 }
        tolower($1) == "content-length:" { size = $2 }
        END { print code, (size ? size : "unknown") }'
}
gh api repos/google/fonts/commits/main --jq .sha >"$F/fonts-commit"
SHA=$(cat "$F/fonts-commit")
css=$(curl -sS -f -A "$UA" "$CSS_URL")
if [ -z "$css" ] || [ -z "$SHA" ]; then
    echo "STOP: no stylesheet from Google, or no google/fonts commit"
elif printf '%s\n' "$css" | docker run --rm -i -u "$(id -u):$(id -g)" -v "$F:/work" \
        -v "$PWD/frontend/public/css:/css:ro" -w /work bsdmirror-test \
        python filter_fonts.py - /css/fonts.css unused /dev/null files.txt; then
    {
        printf 'google.css 200 %s %s\n' "$(printf '%s\n' "$css" | wc -c | tr -d ' ')" "$CSS_URL"
        while read -r url name; do
            printf '%s %s %s\n' "$name" "$(head_of "$url")" "$url"
        done <"$F/files.txt"
        for pair in instrumentsans:InstrumentSans unbounded:Unbounded; do
            url="https://raw.githubusercontent.com/google/fonts/$SHA/ofl/${pair%%:*}/OFL.txt"
            printf 'LICENSE-%s.txt %s %s\n' "${pair##*:}" "$(head_of "$url")" "$url"
        done
    } | tee "$F/approved.txt"
else
    echo "STOP: the filter refused Google's stylesheet"
fi
```

Expected: seven lines of `name status size url`, each with status `200` and a byte size:
- `google.css`;
- `instrument-sans-latin.woff2`, `instrument-sans-latin-ext.woff2`, `unbounded-latin.woff2` and `unbounded-latin-ext.woff2`;
- `LICENSE-InstrumentSans.txt` and `LICENSE-Unbounded.txt`, pinned to the google/fonts commit in `fonts-commit`.

If the output starts with `STOP`, or a status isn't 200, or a size is `unknown`, stop and report. If the filter's message is `not a variable font`, also ask the user: the spec assumes one variable file per family and subset. Unless the user wants to try again later, PR 1b then goes on as in Step 3's **Stop**, so the README fix still ships.

- [ ] **Step 3: ask the user.** Use AskUserQuestion. List each of the seven files from `approved.txt` with its name, its source URL and its size, and say:
  - Google's stylesheet was read once, into memory, to learn these names, and was not saved. The sizes come from `HEAD` requests, which download nothing, and the licences' google/fonts commit from GitHub's API. On approval the stylesheet is downloaded to `$SCRATCH` and stays there: its latin and latin-ext blocks go into `fonts.css`, and the file itself is not committed.
  - The four fonts and the two licences are committed to the repository, which is public on GitHub, and the site serves the fonts from `/fonts/`.
  - All six are under the SIL Open Font License 1.1, which allows both.

  The options:
  - **Approve.**
  - **Stop.** PR 1b then ships without the new fonts. Skip Step 4 onward and Task 11, say so in the PR description, and remind the user that PR 2 needs these faces (spec section 4.2). Task 9's checks are already committed and stay green. One part of Task 11 still ships, because the stale reference it fixes is PR 1's housekeeping: the web-designer replaces the `## Caching caveat` paragraph of `frontend/public/fonts/README.md` with the one in Task 11 Step 5's template, which names `production.conf` instead of `default.conf:181`, runs the whole suite, and commits it alone as `Point the fonts README at the production nginx config`.

- [ ] **Step 4: download what was approved, into `$SCRATCH` only.**

```bash
F="$SCRATCH/fonts"; mkdir -p "$F/files"
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
CSS_URL='https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600&family=Unbounded:wght@600;700&display=swap'
date -u +%F >"$F/retrieved"
if curl -sS -f -A "$UA" -o "$F/google.css" "$CSS_URL" \
    && docker run --rm -u "$(id -u):$(id -g)" -v "$F:/work" -v "$PWD/frontend/public/css:/css:ro" \
        -w /work bsdmirror-test \
        python filter_fonts.py google.css /css/fonts.css "$(cat "$F/retrieved")" section.css files.after.txt \
    && diff "$F/files.txt" "$F/files.after.txt"; then
    echo "same files as approved; downloading"
    while read -r name code size url; do
        [ "$name" = google.css ] && continue
        curl -sS -f -o "$F/files/$name" "$url" || echo "FAILED $name"
    done <"$F/approved.txt"
else
    echo "STOP: no font downloaded"
fi
```

Nothing but the stylesheet is downloaded unless the filter accepts it and names exactly the files the user approved. If the block prints `STOP`, either Google now names different files, which `diff` shows, or a step failed: ask again from Step 2. If it prints `FAILED`, go on to Step 5, which catches the missing file.

- [ ] **Step 5: check the downloads before anything reaches the repo.**

```bash
F="$SCRATCH/fonts"
while read -r name code size url; do
    [ "$name" = google.css ] && continue
    got=nothing
    [ -f "$F/files/$name" ] && got=$(wc -c <"$F/files/$name" | tr -d ' ')
    if [ "$got" = "$size" ]; then echo "size ok   $name $got"; else echo "SIZE DIFF $name approved $size, got $got"; fi
done <"$F/approved.txt"
# Named from the list, not globbed: zsh stops on a glob that matches nothing.
while read -r name code size url; do
    f="$F/files/$name"
    [ -f "$f" ] || continue
    case "$name" in
        *.woff2) printf '%s  %s\n' "$(head -c 4 "$f")" "$name" ;;
        LICENSE-*) echo "== $name"; sed -n '1,/This Font Software is licensed/p' "$f" ;;
    esac
done <"$F/approved.txt"
docker run --rm --network none -v "$F:/work:ro" bsdmirror-test \
    sh -c 'node /work/fontinfo.mjs /work/files/*.woff2' | tee "$F/fontinfo.txt"
```

Expected:
- **Sizes:** six `size ok` lines.
- **Signatures:** four `wOF2` lines.
- **Licences:** copyright lines with no `with Reserved Font Name "..."`. Every OFL text defines the term further down; only a name declared here matters.
- **Font info:** for each font, a version, a `wght` axis (and `wdth` for Instrument Sans, if Google kept it), an OFL licence URL, and a copyright line.
  - A family's latin and latin-ext files report the same version and the same axes.
  - Each family's copyright line names the same holder as the first line of its `LICENSE-*.txt`.

If any check fails, set the downloads aside with `mv "$F/files" "$F/rejected-$(date +%s)"` and stop. Tell the user what failed, and continue PR 1b as in Step 3's **Stop**. A reserved name matters because the OFL then forbids serving Google's subset build under that name.

### Task 11: The fonts

**Files:**
- Modify: `tests/test_fonts.py` (append)
- Create: the four `.woff2` files, `frontend/public/fonts/LICENSE-InstrumentSans.txt`, `frontend/public/fonts/LICENSE-Unbounded.txt`, all copied from `$SCRATCH/fonts/files/`
- Modify: `frontend/public/css/fonts.css` (the header comment, then append), `frontend/public/fonts/README.md` (rewritten)
- Modify: `CLAUDE.md` (the file count in the "Fonts are self-hosted" constraint), `.dockerignore` (the file count in its header comment)

- [ ] **Step 1 (developer): append the test** to `tests/test_fonts.py`:

```python
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
```

- [ ] **Step 2 (developer): run it and watch it fail.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_fonts.py; echo "rc=$?"`

Expected: `rc=1`. Both cases fail, with `fonts.css has no @font-face for Unbounded` and the same for Instrument Sans. The other 49 pass. Also run the lint pair on `tests/test_fonts.py` now, so a formatting slip in the appended test stays with its owner: both `rc=0`.

- [ ] **Step 3 (web-designer): add the files.**

```bash
cp "$SCRATCH"/fonts/files/*.woff2 "$SCRATCH"/fonts/files/LICENSE-*.txt frontend/public/fonts/
cat "$SCRATCH/fonts/section.css" >> frontend/public/css/fonts.css
```

- [ ] **Step 4 (web-designer): the `fonts.css` header.** Replace the file's header comment, from its first line down to and including the `   =========================================================================== */` line that closes the notes, with:

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

- [ ] **Step 5 (web-designer): `fonts/README.md`.** Replace the whole file with the text below. Fill each `{...}` from the named file in `$SCRATCH/fonts/`:
  - `{RETRIEVED}` from `retrieved`;
  - `{FONTS_COMMIT}` from `fonts-commit`;
  - the four version and axes cells from `fontinfo.txt`, written the way the Inter row is;
  - `{CHECKSUMS}` from `docker compose run --rm -T test sh -c 'cd frontend/public/fonts && sha256sum *.woff2'`, which lists 17 files.

````markdown
# Self-hosted web fonts

Inter, JetBrains Mono, Instrument Sans and Unbounded, vendored so the site
loads no fonts from a third party. This is what allows nginx to serve a
`font-src 'self'` CSP without losing the site's typography; before this, both
stylesheets `@import`ed `fonts.googleapis.com` and the admin panel `<link>`ed
it a second time.

The `@font-face` declarations that use these files live in
`frontend/public/css/fonts.css`, which is linked from `index.html` and
`admin/index.html`. Nothing else should reference these files directly.

## Provenance

Inter and JetBrains Mono were retrieved 2026-08-30 from Google Fonts, which is
the same source the site used before, so the bytes are the ones production was
already serving:

    https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap

Instrument Sans and Unbounded were retrieved {RETRIEVED} for the Reflection
redesign (`docs/design/2026-09-25-reflection-redesign.md`), from:

    https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600&family=Unbounded:wght@600;700&display=swap

Only that response's `latin` and `latin-ext` blocks were kept: these two faces
set the site's own copy, which is English.

Both requests were fetched with a current desktop Chrome User-Agent, which is
what makes Google return WOFF2. The CSS it returns names one file per
family+subset; those files were downloaded unmodified and renamed from Google's
opaque hashes to `<family>-<subset>.woff2`. No re-subsetting, re-compression or
other modification was performed.

| Family | Version | Axes | Weights used by this site |
|---|---|---|---|
| Inter | 4.001 (git-66647c0bb) | `wght` 100-900 (variable) | 300, 400, 500, 600, 700 |
| JetBrains Mono | 2.211 | `wght` 400-800 (variable) | 400, 500 |
| Instrument Sans | {INSTRUMENT_SANS_VERSION} | {INSTRUMENT_SANS_AXES} | 400, 500, 600 |
| Unbounded | {UNBOUNDED_VERSION} | {UNBOUNDED_AXES} | 600, 700 |

All four are **variable** fonts: one file per subset covers every weight. The
per-weight `@font-face` blocks in `fonts.css` all point at the same file.

## Licensing

All four families are under the SIL Open Font License 1.1, which permits
redistribution provided the license travels with the fonts:

* `LICENSE-Inter.txt` - from https://github.com/rsms/inter (`LICENSE.txt`)
* `LICENSE-JetBrainsMono.txt` - from https://github.com/JetBrains/JetBrainsMono (`OFL.txt`)
* `LICENSE-InstrumentSans.txt` - from https://github.com/google/fonts at commit {FONTS_COMMIT} (`ofl/instrumentsans/OFL.txt`)
* `LICENSE-Unbounded.txt` - from https://github.com/google/fonts at commit {FONTS_COMMIT} (`ofl/unbounded/OFL.txt`)

No family's copyright line declares a **Reserved Font Name**, so Google's
subset builds may keep their names, and we may redistribute them under those
names. The license URL embedded in each binary's name table (ID 14) confirms
OFL for all four.

## Caching caveat

nginx serves `*.woff2` with `expires 7d; Cache-Control: public, immutable`
(the fonts-and-images location in `nginx/sites/production/production.conf`)
and these filenames carry **no content hash**. A client that has cached a file
will not revalidate it for seven days and cannot be forced to. So do not
replace a file in place: if a font ever needs to change, give it a new filename
(or add a version suffix) and update `fonts.css` in the same commit.

## Regenerating

    curl -A "<current desktop Chrome UA>" \
      "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"

    curl -A "<current desktop Chrome UA>" \
      "https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600&family=Unbounded:wght@600;700&display=swap"

Download each `url()` from the responses and rename it to
`<family>-<subset>.woff2`. A file whose bytes differ from one already shipped
takes a new name instead, such as a version suffix (see the caching caveat
above). In the CSS, rewrite the `url()`s to `/fonts/` and re-indent the blocks
to four spaces, like the rest of `fonts.css`. From the second response keep
only the blocks under `/* latin */` and `/* latin-ext */`. Nothing else in the
returned CSS should be altered. List every new file's checksum below.

## Checksums (SHA-256)

```
{CHECKSUMS}
```
````

- [ ] **Step 6 (web-designer): run the tests, lint, and the whole suite.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_fonts.py; echo "rc=$?"`

Expected: `61 passed`, `rc=0`. The font checks now cover 17 files and four families: 16 files free of Google hosts, the `url()` check, the parse and directory checks, the three-way list, 17 signatures, 17 checksums, 4 licences, the leftover-licence check and the 2 new-family tests.

Then run the lint pair on `tests/test_fonts.py`, and the whole suite, which includes the CSP and contrast harnesses that load `fonts.css`. Expected: every `rc=0`.

- [ ] **Step 7 (controller): the font count elsewhere.** Four tracked files count the fonts, and the count is 17 from here on. This step edits two of them, and its check lists the other two. The README lists every file with its checksum, so neither edited file needs a count of its own:
  - `CLAUDE.md`'s "Fonts are self-hosted" constraint: replace `served from the 13 woff2 files in` with `served from the woff2 files in`. The controller makes this edit itself, like the documents in Task 7, rather than asking a dispatched agent to change the working agreement.
  - `.dockerignore`'s header comment, a devops-sre file: replace `plus 13 self-hosted woff2 font files` with `plus its self-hosted woff2 font files`. It is one comment line, so it rides in this commit.

Run: `git grep -n -E '13 (self-hosted )?woff2' -- . ':!docs/design'`
Expected: two lines, `.claude/agents/web-designer.md` and `.github/workflows/ci.yml`. Task 18 Step 4 offers both to the user: one is agent configuration and the other a workflow file, so neither is edited here. Any other file listed still counts 13: unpin it the same way.

- [ ] **Step 8 (controller): commit.** Commit only if Step 6's whole-suite run exited 0. No test reads `CLAUDE.md` or `.dockerignore`, so that run covers this commit. The web-designer's files and the two edits go in one commit:

```bash
git add tests/test_fonts.py frontend/public/fonts frontend/public/css/fonts.css CLAUDE.md .dockerignore
git commit -m "Self-host Unbounded and Instrument Sans"
```

---

## Chunk 5: PR 1b, the mark, the icons and the favicon

### Task 12: The mark, the icons and `favicon.svg`

**Files:**
- Create: `tests/test_images.py`
- Create: `frontend/public/img/mark-glyph.svg`, `frontend/public/img/mark-axis.svg`, 15 files in `frontend/public/img/icons/`, `frontend/public/img/README.md`
- Modify: `frontend/public/img/favicon.svg` (replaced)

- [ ] **Step 1 (developer): write the tests.** Create `tests/test_images.py`:

```python
"""Static checks on the images frontend/public serves: the b|d mark, the
icons, the logos and the favicon set.

docs/design/2026-09-25-reflection-redesign.md, sections 4.5 to 4.7. The CSP
loads images from this origin only (img-src 'self', no data:), an SVG opened
directly renders as a document, and nginx serves images with a week-long
`immutable` cache, so an image is never changed in place.
"""

import pathlib
import re
import xml.etree.ElementTree as ET

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
```

- [ ] **Step 2 (developer): run it and watch it fail.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_images.py; echo "rc=$?"`

Expected: `rc=1`, with 20 failed, 3 passed and 1 skipped:
- The inertness check fails on `favicon.svg`: today's favicon is the daemon drawing, with `style=` attributes. The three logos, the only other SVGs so far, pass it.
- The set test, the 15 icons and the two marks fail on missing files.
- `test_favicon_svg_is_the_small_mark_on_the_light_tile` fails: today's `viewBox` is `0 0 100 100`.
- `test_favicon_svg_turns_dark_with_one_media_rule_and_nothing_else` skips, because today's favicon has no `<style>`.

- [ ] **Step 3 (web-designer): the mark files.** These use the regular geometry from spec section 4.5, in one colour, for CSS masks.

`frontend/public/img/mark-glyph.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <!-- The b|d mark's glyph, regular geometry (img/README.md), used as a CSS mask. -->
  <defs>
    <g id="b">
      <rect x="5" y="6" width="7" height="52"/>
      <path fill-rule="evenodd" d="M5 46a12 12 0 1 0 24 0a12 12 0 1 0-24 0ZM11 46a6 6 0 1 0 12 0a6 6 0 1 0-12 0Z"/>
    </g>
  </defs>
  <use href="#b"/>
  <use href="#b" transform="translate(64 0) scale(-1 1)"/>
</svg>
```

`frontend/public/img/mark-axis.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <!-- The b|d mark's mirror line, regular geometry (img/README.md), used as a CSS mask. -->
  <rect x="30.7" y="3" width="2.6" height="58" rx="1.3"/>
</svg>
```

- [ ] **Step 4 (web-designer): the icons.** Each file is one line: this root, then the shapes.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#000" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">SHAPES</svg>
```

The first eleven are the ones the user saw in the approved proposal. The last four are new, in the same hand.

| File | SHAPES |
|---|---|
| `dashboard.svg` | `<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>` |
| `mirrors.svg` | `<ellipse cx="12" cy="6" rx="7.5" ry="2.6"/><path d="M4.5 6v12c0 1.4 3.4 2.6 7.5 2.6s7.5-1.2 7.5-2.6V6"/><path d="M4.5 12c0 1.4 3.4 2.6 7.5 2.6s7.5-1.2 7.5-2.6"/>` |
| `sync-failures.svg` | `<path d="M12 3.8 21.2 19.6H2.8z"/><path d="M12 9.8v4.6"/><path d="M12 17.2v.1"/>` |
| `protected-paths.svg` | `<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8.5 10.5V7.6a3.5 3.5 0 0 1 7 0v2.9"/>` |
| `users.svg` | `<circle cx="9" cy="8.5" r="3.2"/><path d="M3.5 19.5c.6-3.2 2.8-5 5.5-5s4.9 1.8 5.5 5"/><circle cx="16.8" cy="9.4" r="2.5"/><path d="M15.9 14.6c2.2.2 3.9 1.8 4.6 4.9"/>` |
| `audit-logs.svg` | `<path d="M9 6.5h11M9 12h11M9 17.5h11"/><path d="M4.5 6.5h.1M4.5 12h.1M4.5 17.5h.1"/>` |
| `settings.svg` | `<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>` |
| `sun.svg` | `<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.2M12 19.3v2.2M21.5 12h-2.2M4.7 12H2.5M18.7 5.3l-1.6 1.6M6.9 17.1l-1.6 1.6M18.7 18.7l-1.6-1.6M6.9 6.9 5.3 5.3"/>` |
| `moon.svg` | `<path d="M20 14.6A8 8 0 1 1 9.4 4a7.5 7.5 0 0 0 10.6 10.6z"/>` |
| `copy.svg` | `<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5V6A1.5 1.5 0 0 0 14 4.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5"/>` |
| `sync.svg` | `<path d="M19.5 9.5A7.5 7.5 0 0 0 5.8 6.9L4.5 8.4"/><path d="M4.5 4.4v4h4"/><path d="M4.5 14.5a7.5 7.5 0 0 0 13.7 2.6l1.3-1.5"/><path d="M19.5 19.6v-4h-4"/>` |
| `arrow-right.svg` | `<path d="M4.5 12h15"/><path d="M13.5 6l6 6-6 6"/>` |
| `check.svg` | `<path d="M5 12.5l4.5 4.5L19 7.5"/>` |
| `close.svg` | `<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>` |
| `info.svg` | `<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5"/><path d="M12 7.8v.1"/>` |

The moon's inner arc radius is 7.5, not the proposal's 6.4. Its chord is 15 units, so 6.4 was silently enlarged to about 7.5 by the renderer anyway; the drawing is unchanged. Writing 7.5 states what is drawn.

- [ ] **Step 5 (web-designer): replace `frontend/public/img/favicon.svg`.** It uses the small geometry, on the tile from spec section 4.6.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <style>
    @media (prefers-color-scheme: dark) {
      .tile-from { stop-color: #1C1F26 }
      .tile-to { stop-color: #07080B }
      .edge { stroke: #2C313A }
      .glyph { fill: #EDEFF3 }
      .axis { fill: #FF5A60 }
    }
  </style>
  <defs>
    <linearGradient id="tile" x1="0" y1="0" x2="1" y2="1">
      <stop class="tile-from" offset="0" stop-color="#FFFFFF"/>
      <stop class="tile-to" offset="1" stop-color="#CDD2DA"/>
    </linearGradient>
    <!-- The b of the small mark: a stem and a ring (img/README.md). -->
    <g id="b">
      <rect x="4" y="8" width="8" height="49"/>
      <path fill-rule="evenodd" d="M5 46a11 11 0 1 0 22 0a11 11 0 1 0-22 0ZM11.8 46a4.2 4.2 0 1 0 8.4 0a4.2 4.2 0 1 0-8.4 0Z"/>
    </g>
  </defs>
  <rect class="edge" x="1" y="1" width="62" height="62" rx="14" fill="url(#tile)" stroke="#C4C9D1" stroke-width="2"/>
  <g transform="translate(7 7) scale(.78125)">
    <use class="glyph" href="#b" fill="#0C0E12"/>
    <use class="glyph" href="#b" fill="#0C0E12" transform="translate(64 0) scale(-1 1)"/>
    <rect class="axis" x="30" y="5" width="4" height="54" rx="2" fill="#C8232C"/>
  </g>
</svg>
```

`scale(.78125)` is 50/64: the 64-unit mark shrinks to 50 units, leaving the 7-unit inset on each side.

- [ ] **Step 6 (web-designer): `frontend/public/img/README.md`.** Task 13 replaces the `favicon.svg` item, and Task 14 adds the other two favicon files.

```markdown
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
```

- [ ] **Step 7 (web-designer): run the tests, lint, and the whole suite.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_images.py; echo "rc=$?"`

Expected: `41 passed`, `rc=0`: 21 inert SVGs, the set, 15 icons, 2 marks and the favicon's 2. Then the lint pair on `tests/test_images.py`, and the whole suite. Expected: every `rc=0`. The visual check comes in Task 17.

- [ ] **Step 8 (web-designer): commit.**

```bash
git add tests/test_images.py frontend/public/img
git commit -m "Add the b|d mark, the 15-icon set and the b|d favicon"
```

### Task 13: The favicon's dark rule under the production CSP

`favicon.svg`, committed in Task 12, turns dark with one `@media (prefers-color-scheme: dark)` rule in a `<style>` element, and nginx serves it with `style-src 'self'`. Whether Chromium applies that header to an SVG it draws as an image is browser behaviour, so this task asks Chromium, and keeps asking in CI.

The file already exists, so this task measures it rather than changing it, and its tests are expected to pass the first time they run. No red run comes first. What shows the measurement works are the controls, and a check that each copy arrived with the right header.

**Files:**
- Create: `tests/js/favicon_harness.mjs`, `tests/test_favicon_dark_mode.py`
- Modify: `tests/test_chrome_harness_start.py` (the docstring's first four lines, and `HARNESSES`)
- Modify: `frontend/public/img/README.md` (the `favicon.svg` item)

- [ ] **Step 1 (developer): create `tests/js/favicon_harness.mjs`.**

```js
/**
 * Does favicon.svg's dark-theme rule survive the production CSP header?
 *
 * favicon.svg keeps its light colours in presentation attributes and switches
 * to its dark tile with one `@media (prefers-color-scheme: dark)` rule in a
 * <style> element. nginx serves every file with `style-src 'self'`, which
 * blocks an inline <style> in a document. Whether Chromium applies an image's
 * own CSP header to the SVG it draws as that image is browser behaviour, so
 * this asks Chromium instead of reading a spec.
 *
 * It draws three copies as 64px <img>s on a mid-grey page whose colour scheme
 * is dark, with prefers-color-scheme emulated as dark, and reads back one
 * pixel of each tile:
 *   withCsp       the file, served with the production CSP header
 *   withoutCsp    the file, served without it: must read dark
 *   withoutStyle  the file without its <style>: must read light
 * The last two are the controls. Together they show that the sampled pixel is
 * on the tile and that a dark reading comes from the <style> rule. If either
 * control fails, the withCsp reading means nothing. A copy that did not draw
 * reads the grey page, which is neither tile. Before reading any pixel, the
 * harness checks that each copy arrived with the CSP header it stands for.
 *
 * No npm packages: node's built-in http, zlib and WebSocket only.
 *
 * Usage:  node favicon_harness.mjs <favicon.svg> <csp> [chrome-binary]
 * Output: JSON {"withCsp": [r, g, b, a], "withoutCsp": [...], "withoutStyle": [...]}
 */
import { createServer } from 'node:http';
import { readFile, mkdtemp } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { tmpdir } from 'node:os';
import { inflateSync } from 'node:zlib';
import path from 'node:path';

const SVG_PATH = path.resolve(process.argv[2]);
const CSP = process.argv[3];
const CHROME = process.argv[4]
    || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

// How long Chrome gets to write DevToolsActivePort: the same limit and the
// same override as the other harnesses (tests/test_chrome_harness_start.py).
const DEFAULT_CHROME_START_TIMEOUT_MS = 30_000;
const CHROME_START_TIMEOUT_MS = Number(process.env.CHROME_START_TIMEOUT_MS) > 0
    ? Number(process.env.CHROME_START_TIMEOUT_MS)
    : DEFAULT_CHROME_START_TIMEOUT_MS;

// The Chrome this run started, so a failed run can stop it.
let chromeProcess = null;

// Each copy is drawn 64px square, so one CSS pixel is one unit of the
// favicon's 64-unit grid. (32, 6) is inside the tile, above the axis and clear
// of the edge and the glyph (design sections 4.5 and 4.6).
const SIZE = 64;
const SAMPLE = { x: 32, y: 6 };
const COPIES = ['withCsp', 'withoutCsp', 'withoutStyle'];

const PAGE = `<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="color-scheme" content="dark">
<style>
html, body { margin: 0; background: #808080; }
img { display: block; width: ${SIZE}px; height: ${SIZE}px; }
</style></head>
<body>${COPIES.map((copy) => `<img src="/${copy}/favicon.svg" alt="">`).join('')}</body></html>`;

function serve(svg) {
    const unstyled = Buffer.from(svg.toString('utf8').replace(/<style\b[^>]*>[\s\S]*?<\/style>/, ''));
    return new Promise((resolve) => {
        const server = createServer((req, res) => {
            const url = req.url.split('?')[0];
            if (url === '/page.html') {
                res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
                return res.end(PAGE);
            }
            const copy = COPIES.find((c) => url === `/${c}/favicon.svg`);
            if (copy) {
                const headers = { 'Content-Type': 'image/svg+xml' };
                if (copy === 'withCsp') headers['Content-Security-Policy'] = CSP;
                res.writeHead(200, headers);
                return res.end(copy === 'withoutStyle' ? unstyled : svg);
            }
            res.writeHead(404);
            return res.end();
        });
        server.listen(0, '127.0.0.1', () => resolve({ server, port: server.address().port }));
    });
}

// ---------------------------------------------------------------------------
// Minimal CDP client: csp_click_harness.mjs's, without its event handlers
// ---------------------------------------------------------------------------
class CDP {
    constructor(ws) {
        this.ws = ws;
        this.id = 0;
        this.pending = new Map();
        ws.addEventListener('message', (ev) => {
            const msg = JSON.parse(ev.data);
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

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitFor(check, what, timeoutMs = 10_000) {
    const deadline = Date.now() + timeoutMs;
    while (!(await check())) {
        if (Date.now() > deadline) throw new Error(`timed out after ${timeoutMs}ms waiting for ${what}`);
        await sleep(50);
    }
}

/** [r, g, b, a] of a 1x1 PNG, as Page.captureScreenshot returns it. With no
 * pixel to the left or above, every PNG row filter leaves the bytes as they
 * are, so no unfiltering is needed. */
function onePixel(base64) {
    const png = Buffer.from(base64, 'base64');
    const idat = [];
    let channels = 0;
    for (let pos = 8; pos < png.length;) {
        const length = png.readUInt32BE(pos);
        const type = png.toString('latin1', pos + 4, pos + 8);
        const data = png.subarray(pos + 8, pos + 8 + length);
        if (type === 'IHDR') {
            if (data.readUInt32BE(0) !== 1 || data.readUInt32BE(4) !== 1 || data[8] !== 8) {
                throw new Error('expected a 1x1, 8-bit screenshot');
            }
            channels = { 2: 3, 6: 4 }[data[9]] ?? 0;
            if (!channels) throw new Error(`unexpected PNG colour type ${data[9]}`);
        } else if (type === 'IDAT') {
            idat.push(data);
        }
        pos += 12 + length;
    }
    const pixel = [...inflateSync(Buffer.concat(idat)).subarray(1, 1 + channels)];
    return channels === 3 ? [...pixel, 255] : pixel;
}

async function main() {
    const svg = await readFile(SVG_PATH);
    const { server, port } = await serve(svg);
    const userDataDir = await mkdtemp(path.join(tmpdir(), 'favicon-chrome-'));

    const chrome = spawn(CHROME, [
        '--headless=new',
        '--remote-debugging-port=0',
        `--user-data-dir=${userDataDir}`,
        '--no-first-run', '--no-default-browser-check',
        '--disable-gpu', '--disable-extensions', '--mute-audio', '--hide-scrollbars'
    ], { stdio: ['ignore', 'ignore', 'pipe'] });
    chromeProcess = chrome;

    // Drain Chrome's stderr, keeping the tail for the error below. An unread
    // pipe can block Chrome before it ever writes DevToolsActivePort (see
    // csp_click_harness.mjs).
    let chromeStderr = '';
    chrome.stderr.setEncoding('utf8');
    chrome.stderr.on('data', (chunk) => {
        chromeStderr = (chromeStderr + chunk).slice(-8192);
    });

    let wsUrl = null;
    const deadline = Date.now() + CHROME_START_TIMEOUT_MS;
    while (!wsUrl && Date.now() < deadline) {
        await sleep(100);
        try {
            const portFile = path.join(userDataDir, 'DevToolsActivePort');
            const [p] = (await readFile(portFile, 'utf8')).split('\n');
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
    const evaluate = async (expression) => {
        const { result, exceptionDetails } = await cdp.send('Runtime.evaluate', {
            expression, awaitPromise: true, returnByValue: true
        }, sessionId);
        if (exceptionDetails) {
            throw new Error(`${expression}: ${exceptionDetails.exception?.description ?? exceptionDetails.text}`);
        }
        return result.value;
    };

    await cdp.send('Emulation.setEmulatedMedia', {
        features: [{ name: 'prefers-color-scheme', value: 'dark' }]
    }, sessionId);
    await cdp.send('Emulation.setDeviceMetricsOverride', {
        width: 320, height: 240, deviceScaleFactor: 1, mobile: false
    }, sessionId);
    await cdp.send('Page.navigate', { url: `http://127.0.0.1:${port}/page.html` }, sessionId);
    await waitFor(
        () => evaluate(`document.readyState === 'complete' && document.images.length === ${COPIES.length}`),
        'the page to load'
    );
    // decode() rejects for an image that failed to load, so a broken file
    // fails here instead of being read as the page behind it.
    await evaluate('Promise.all([...document.images].map((img) => img.decode())).then(() => true)');

    // The copies differ only in what the server sends, so check that first: a
    // withCsp copy that arrived without its header would pass for nothing.
    const served = await evaluate(`Promise.all(${JSON.stringify(COPIES)}.map((copy) =>
        fetch('/' + copy + '/favicon.svg').then((r) => r.headers.get('content-security-policy'))))`);
    const expected = COPIES.map((copy) => (copy === 'withCsp' ? CSP : null));
    if (JSON.stringify(served) !== JSON.stringify(expected)) {
        throw new Error(`the copies arrived with the wrong CSP headers: ${JSON.stringify(served)}`);
    }

    const pixels = {};
    for (const [index, copy] of COPIES.entries()) {
        const { data } = await cdp.send('Page.captureScreenshot', {
            format: 'png',
            clip: { x: SAMPLE.x, y: index * SIZE + SAMPLE.y, width: 1, height: 1, scale: 1 }
        }, sessionId);
        pixels[copy] = onePixel(data);
    }
    process.stdout.write(JSON.stringify(pixels) + '\n');

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

- [ ] **Step 2 (developer): create `tests/test_favicon_dark_mode.py`.**

```python
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
```

- [ ] **Step 3 (developer): add the harness to `tests/test_chrome_harness_start.py`.** Replace the docstring's first four lines:

```text
"""Both Chrome harnesses give Chrome time to start, and stop it when a run fails.

tests/js/contrast_harness.mjs and tests/js/csp_click_harness.mjs each start
headless Chrome and wait for it to write DevToolsActivePort before driving it.
```

with:

```text
"""Every Chrome harness gives Chrome time to start, and stops it when a run fails.

tests/js/contrast_harness.mjs, csp_click_harness.mjs and favicon_harness.mjs
each start headless Chrome and wait for it to write DevToolsActivePort before
driving it.
```

In `HARNESSES`, add after the `"csp"` entry:

```python
    "favicon": (
        JS_DIR / "favicon_harness.mjs",
        [PUBLIC / "img" / "favicon.svg", "default-src 'self'"],
    ),
```

- [ ] **Step 4 (developer): run the tests, and act on the harness's answer.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_favicon_dark_mode.py tests/test_chrome_harness_start.py; echo "rc=$?"`

The favicon has carried its dark rule since Task 12, so these tests pass the first time if Chromium applies the rule. They guard against a later change to the CSP, to `favicon.svg` or to Chrome that stops the dark tile from showing. The favicon harness's three start/stop cases guard what they guard for the other harnesses: the 30 s limit for Chrome to start, and Chrome being stopped when a run fails. Three outcomes:

- **`12 passed`, `rc=0`:** the three dark-mode tests and the nine start/stop tests, the favicon harness's three among them. The dark rule works under the production CSP in Chromium; keep `favicon.svg` as it is. The dry run saw exactly this: both dark copies read `[21, 24, 30, 255]`, and the unstyled copy read light.
- **Only `test_the_dark_rule_applies_under_the_production_csp` fails, and it says the tile read light:** Chromium blocks the rule, so take the design's fallback. *Controller:* record it for the PR description and the user. The web-designer deletes the `<style>` element from `favicon.svg`. Re-run: the dark-mode tests then skip, and Task 12's dark-rule test skips too.
- **A control fails, the CSP test says the copy read neither tile, all three error at setup because the harness exited non-zero, or any other test fails, such as a start/stop case:** the harness or its fixture is broken, not the favicon's CSP handling. One exception: if only the no-CSP control reads light, check `favicon.svg`'s dark rule first; Task 12's dark-rule test would fail with it. Debug it with superpowers:systematic-debugging before going on, and do not take the fallback on a broken measurement.

- [ ] **Step 5 (web-designer): the README's `favicon.svg` item.** In `frontend/public/img/README.md`, replace the whole `favicon.svg` item, from ``- **`favicon.svg`:**`` to the end of the file, according to Step 4's outcome.

If the rule works:

```markdown
- **`favicon.svg`:** the small mark on a rounded tile. It is light by default,
  and one `@media (prefers-color-scheme: dark)` rule in its `<style>` turns it
  into the dark tile.
  - The light colours are presentation attributes, which the CSP's
    `style-src 'self'` never blocks.
  - `tests/test_favicon_dark_mode.py` checks, in Chromium, that the dark rule
    survives the production CSP header.
```

If the fallback was taken:

```markdown
- **`favicon.svg`:** the small mark on the light tile, whose edge keeps it
  readable on a dark tab strip. It has no dark variant: Chromium applies the
  production CSP header to the SVG and blocks its own `<style>`.
  `tests/test_favicon_dark_mode.py` measured that; it skips while the file has
  no dark rule to check.
```

- [ ] **Step 6 (developer): lint, and the whole suite.** Run the lint pair on `tests/test_favicon_dark_mode.py tests/test_chrome_harness_start.py`, then the whole suite. Expected: every `rc=0`.

- [ ] **Step 7 (developer): commit.** If the rule works:

```bash
git add tests/js/favicon_harness.mjs tests/test_favicon_dark_mode.py \
    tests/test_chrome_harness_start.py frontend/public/img/README.md
git commit -m "Check the favicon's dark rule under the production CSP"
```

If the fallback was taken, add `frontend/public/img/favicon.svg` to the `git add`, and use the subject `Drop the favicon's dark rule, which the production CSP blocks`.

---

## Chunk 6: PR 1b, the favicon files, the links, and shipping 1b

### Task 14: `favicon.ico` and the Apple touch icon

**Files:**
- Modify: `tests/test_images.py` (append)
- Create: `scripts/render_icons.py` (mode 755), `frontend/public/favicon.ico`, `frontend/public/img/apple-touch-icon.png`
- Modify: `frontend/public/img/README.md` (the favicon section), `nginx/nginx.conf` (the `img-src` entry of the CSP comment)

- [ ] **Step 1 (developer): append the tests.** Add `import struct` and `import zlib` to the imports of `tests/test_images.py`, then append:

```python
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
```

The Paeth predictor above picks the first of `left`, `up` and `up_left` at the smallest distance. That is the PNG specification's tie order.

- [ ] **Step 2 (developer): run them and watch them fail.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_images.py -k "favicon_ico or touch_icon"; echo "rc=$?"`

Expected: `2 failed`, both `FileNotFoundError`; `rc=1`.

- [ ] **Step 3 (devops-sre): create `scripts/render_icons.py`.**

```python
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
```

Then `chmod 755 scripts/render_icons.py`, to match the other `scripts/*.py`.

- [ ] **Step 4 (devops-sre): render.**

```bash
docker run --rm --network none -u "$(id -u):$(id -g)" --security-opt seccomp=unconfined \
    -e HOME=/tmp -v "$PWD:/repo" -w /repo bsdmirror-test python scripts/render_icons.py
```

Expected: `wrote frontend/public/favicon.ico (N bytes)` and `wrote frontend/public/img/apple-touch-icon.png (N bytes)`. The dry run wrote 4579 and 9406 bytes.

Then, in the CSP comment in `nginx/nginx.conf`, which lists what each directive covers, name the new file. Replace:

```nginx
    #   img-src     'self'    everything under /img/. 'data:' was dropped: no
    #                         data: or base64 image URI exists in any html, css
    #                         or js under frontend/public.
```

with:

```nginx
    #   img-src     'self'    everything under /img/, and /favicon.ico. 'data:'
    #                         was dropped: no data: or base64 image URI exists
    #                         in any html, css or js under frontend/public.
```

- [ ] **Step 5 (web-designer): finish the README's favicon section.** Append to the end of `frontend/public/img/README.md`:

```markdown
- **`../favicon.ico` and `apple-touch-icon.png`:** rendered from `favicon.svg`,
  always in its light colours.
  - The ICO holds 16, 32 and 48px images.
  - The touch icon is 180px, with the tile full-bleed, because iOS rounds the
    corners itself and paints transparent pixels black.

  Re-render both whenever `favicon.svg` changes. The render runs offline, in
  the test image:

      docker build -f Dockerfile.test -t bsdmirror-test .
      docker run --rm --network none -u "$(id -u):$(id -g)" \
          --security-opt seccomp=unconfined -e HOME=/tmp -v "$PWD:/repo" -w /repo \
          bsdmirror-test python scripts/render_icons.py

  Then look at the 16px image enlarged, eight times or so: at that size the
  axis is less than a pixel wide.
```

- [ ] **Step 6 (devops-sre): run the tests and the linters.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_images.py; echo "rc=$?"`
Expected: `43 passed`, `rc=0`: Task 12's 41 and these 2. If Task 13 took the fallback, `42 passed, 1 skipped`: the dark-rule test skips.

Run the lint pair on `scripts/render_icons.py tests/test_images.py`, then the whole suite. Expected: every `rc=0`. If the format check fails, format the files with the command in the working rules.

- [ ] **Step 7 (devops-sre): commit.**

```bash
git add tests/test_images.py scripts/render_icons.py frontend/public/favicon.ico \
    frontend/public/img/apple-touch-icon.png frontend/public/img/README.md nginx/nginx.conf
git commit -m "Render favicon.ico and the Apple touch icon from favicon.svg"
```

The 16px image is checked by eye in Task 17, which says what to do if it doesn't read.

### Task 15: The favicon links on all four pages

**Files:**
- Modify: `tests/test_images.py` (append)
- Modify: `frontend/public/index.html`, `frontend/public/admin/index.html`, `frontend/public/404.html`, `frontend/public/50x.html` (each `<head>`)

- [ ] **Step 1 (developer): append the test.** Add `from html.parser import HTMLParser` to the imports of `tests/test_images.py`, then append:

```python
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
```

`test_pages_lists_every_html_page` passes from the start. It guards the list itself: a fifth page fails it instead of shipping without the favicon set. Matching `rel` as tokens catches the legacy `rel="shortcut icon"`, which Chromium would show instead of the SVG.

- [ ] **Step 2 (developer): run it and watch it fail.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_images.py -k favicon_set; echo "rc=$?"`

Expected: `4 failed`, `rc=1`. The two main pages have only the SVG link, and the error pages have none.

- [ ] **Step 3 (web-designer): the links.** The same three lines go in every page, ICO first. Chrome prefers the SVG while the ICO says `sizes="32x32"`.

In `index.html` and `admin/index.html`, replace:

```html
    <link rel="icon" type="image/svg+xml" href="/img/favicon.svg">
```

with:

```html
    <link rel="icon" href="/favicon.ico" sizes="32x32">
    <link rel="icon" type="image/svg+xml" href="/img/favicon.svg">
    <link rel="apple-touch-icon" href="/img/apple-touch-icon.png">
```

In `404.html` and `50x.html`, insert the same three lines after `<link rel="stylesheet" href="/css/error.css">`.

- [ ] **Step 4 (web-designer): run the whole suite and lint.** The pages feed the CSP, contrast and theme harnesses.

Run: `docker compose run --rm -T test; echo "rc=$?"`
Expected: `rc=0`.

Run the lint pair on `tests/test_images.py`. Expected: both `rc=0`.

- [ ] **Step 5 (web-designer): commit.**

```bash
git add tests/test_images.py frontend/public/index.html frontend/public/admin/index.html \
    frontend/public/404.html frontend/public/50x.html
git commit -m "Link the favicon set from every page"
```

### Task 16: Ignore the visual-check screenshots

The test joins `tests/test_gitignore_covers_secrets.py`, which has an `_is_ignored()` helper for exactly this. That helper skips cleanly where git is unusable, such as in a linked worktree, and CI's no-skip `REQUIRED` list already names the module.

**Files:**
- Modify: `tests/test_gitignore_covers_secrets.py` (append)
- Modify: `.gitignore`

- [ ] **Step 1 (developer): append the test** to `tests/test_gitignore_covers_secrets.py`:

```python
def test_visual_check_screenshots_are_ignored():
    """Not a secret, but the same kind of mistake. The redesign's visual checks
    (docs/design/2026-09-25-reflection-redesign.md, section 10) write full-page
    screenshots into .screenshots/, and they are shared, never committed."""
    assert _is_ignored(".screenshots/home-dark-400.png"), ".screenshots/ is not in .gitignore"
```

- [ ] **Step 2 (developer): run it and watch it fail.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_gitignore_covers_secrets.py -k screenshots; echo "rc=$?"`

Expected: `1 failed`, `rc=1`, with `.screenshots/ is not in .gitignore`.

- [ ] **Step 3 (devops-sre): the entry.** Append to `.gitignore`:

```gitignore

# Visual-check screenshots (docs/design/2026-09-25-reflection-redesign.md,
# section 10). Shared in the session, never committed.
.screenshots/
```

- [ ] **Step 4 (devops-sre): run the module, lint, and the whole suite.**

Run: `docker compose run --rm -T test pytest -q -p no:cacheprovider tests/test_gitignore_covers_secrets.py; echo "rc=$?"`
Expected: `14 passed`, `rc=0`. Read the count as well as the code: `_is_ignored()` skips where git is unusable, and a run in which all 14 skip also exits 0.

Run the lint pair on `tests/test_gitignore_covers_secrets.py`, then the whole suite. Expected: every `rc=0`.

- [ ] **Step 5 (devops-sre): commit.**

```bash
git add tests/test_gitignore_covers_secrets.py .gitignore
git commit -m "Ignore visual-check screenshots"
```

### Task 17 (controller): The visual check

PR 1 changes no page layout, so this contact sheet stands in for spec section 10's page screenshots at 1440, 768 and 400px. Those start with PR 2.

- [ ] **Step 1: build the contact sheet.** Write `$SCRATCH/pr1b/contact_sheet.sh`:

```bash
#!/usr/bin/env bash
# A contact sheet of PR 1b's assets, rendered by the test image's Chromium over
# HTTP (CSS masks need a real origin), once in light and once in dark:
#  - favicon.svg at 16, 32 and 64px;
#  - favicon.ico's own three images, and its 16px one at 8x;
#  - the touch icon;
#  - the mark as two masks;
#  - the 15 icons as masks at 16, 24 and 48px.
# Writes .screenshots/pr1b-assets-{light,dark}.png in the checkout.
# Usage: contact_sheet.sh REPO_ROOT
set -euo pipefail
R=$(cd "${1:?usage: contact_sheet.sh REPO_ROOT}" && pwd)
S=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$R/.screenshots"

icons=(dashboard mirrors sync-failures protected-paths users audit-logs settings
       sun moon copy sync arrow-right check close info)
{
cat <<'HTML'
<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="color-scheme" content="light dark">
<title>PR 1b assets</title><style>
:root { --ground: #ECEEF1; --ink: #0C0E12; --muted: #4E5563; --accent: #C8232C; }
@media (prefers-color-scheme: dark) {
  :root { --ground: #07080B; --ink: #EDEFF3; --muted: #A2A9B6; --accent: #FF5A60; }
}
body { margin: 0; padding: 20px; background: var(--ground); color: var(--ink); font: 12px/1.4 system-ui, sans-serif; }
h2 { font-size: 12px; margin: 16px 0 8px; color: var(--muted); font-weight: 600; }
.row { display: flex; flex-wrap: wrap; gap: 16px; align-items: end; }
figure { margin: 0; display: grid; justify-items: center; gap: 4px; }
figcaption { color: var(--muted); }
.px { image-rendering: pixelated; }
.mask { display: inline-block; background-color: currentColor;
  -webkit-mask: var(--m) center / contain no-repeat; mask: var(--m) center / contain no-repeat; }
.mark { position: relative; display: inline-block; }
.mark > .mask { position: absolute; inset: 0; }
.mark > .axis { color: var(--accent); }
</style></head><body>
<h2>favicon.svg at 16, 32, 64 · favicon.ico's 16, 32, 48 · the 16px image at 8x · apple-touch-icon.png at 90</h2>
<div class="row">
<img src="/img/favicon.svg" width="16" height="16" alt="">
<img src="/img/favicon.svg" width="32" height="32" alt="">
<img src="/img/favicon.svg" width="64" height="64" alt="">
<img src="/__ico-16.png" alt=""><img src="/__ico-32.png" alt=""><img src="/__ico-48.png" alt="">
<img class="px" src="/__ico-16.png" width="128" height="128" alt="">
<img src="/img/apple-touch-icon.png" width="90" height="90" alt="">
</div>
<h2>The mark as two masks: glyph in text colour, axis in accent</h2>
<div class="row">
HTML
for s in 24 28 48 96; do
    printf '<span class="mark" style="width:%spx;height:%spx"><span class="mask" style="--m:url(/img/mark-glyph.svg)"></span><span class="mask axis" style="--m:url(/img/mark-axis.svg)"></span></span>\n' "$s" "$s"
done
echo '</div><h2>Icons as masks at 16, 24 and 48px</h2><div class="row">'
for i in "${icons[@]}"; do
    printf '<figure><div class="row">'
    for s in 16 24 48; do
        printf '<span class="mask" style="--m:url(/img/icons/%s.svg);width:%spx;height:%spx"></span>' "$i" "$s" "$s"
    done
    printf '</div><figcaption>%s</figcaption></figure>\n' "$i"
done
echo '</div></body></html>'
} >"$S/sheet.html"

docker run --rm --network none -u "$(id -u):$(id -g)" --security-opt seccomp=unconfined -e HOME=/tmp \
    -v "$R/frontend/public:/site:ro" -v "$S:/sheet:ro" -v "$R/.screenshots:/out" \
    bsdmirror-test bash -c '
set -e
mkdir -p /tmp/www && cp -R /site/. /tmp/www/ && cp /sheet/sheet.html /tmp/www/__sheet.html
python3 - <<EOF
import struct
data = open("/tmp/www/favicon.ico", "rb").read()
for i in range(struct.unpack("<HHH", data[:6])[2]):
    w, _, _, _, _, _, length, offset = struct.unpack("<BBBBHHII", data[6 + 16 * i : 22 + 16 * i])
    open(f"/tmp/www/__ico-{w}.png", "wb").write(data[offset : offset + length])
EOF
cd /tmp/www && python3 -m http.server 8765 --bind 127.0.0.1 >/dev/null 2>&1 &
up=0
for _ in $(seq 1 50); do
    if python3 -c "import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:8765/__sheet.html\")" 2>/dev/null; then
        up=1
        break
    fi
    sleep 0.2
done
[ "$up" = 1 ] || { echo "the sheet server never answered" >&2; exit 1; }
for scheme in light dark; do
    flag=""; [ "$scheme" = dark ] && flag="--force-dark-mode"
    chromium --headless=new --no-sandbox --disable-gpu --hide-scrollbars $flag \
        --window-size=1200,900 --screenshot=/out/pr1b-assets-$scheme.png \
        http://127.0.0.1:8765/__sheet.html
done
'
ls -l "$R/.screenshots"
```

Run: `bash "$SCRATCH/pr1b/contact_sheet.sh" "$PWD"`

Expected: `pr1b-assets-light.png` and `pr1b-assets-dark.png`, each about 70 KB, listed at the end. Chromium may print a harmless `dbus` error first.

- [ ] **Step 2: look.** Open both PNGs with the Read tool and check:
  - **Favicon:** readable at 16px. In the dark sheet, `favicon.svg` is the dark tile, unless Task 13 took the fallback.
  - **ICO and touch icon:** light in both sheets. The touch icon is full-bleed, with no dark corners.
  - **Mark:** the masks line up, with the axis red between the bowls.
  - **Icons:** every one is recognisable at 16px, with no clipped strokes.
  - **The 16px ICO image at 8x:** the geometry keeps the bowls clear of the axis. The axis itself is 0.78px wide and centred on a pixel boundary, so it lands as two columns at about 40% coverage: a faint red line, which the dry run showed.

  If the dark sheet looks light everywhere, `--force-dark-mode` did not take effect; say so rather than calling it checked. Anything else that doesn't read goes back to the owner of the file, and the sheet is rebuilt after the fix:
  - an icon or the mark: web-designer fixes Task 12's file, and the developer updates any value Task 12's tests pin;
  - the `favicon.svg` drawing: web-designer fixes the file, the developer updates the values Task 12's tests pin, and devops-sre re-renders the ICO and the touch icon (Task 14 Step 4) and re-runs `tests/test_images.py`. Both renders come from `favicon.svg`, and no test compares them with it, so a fix without the re-render would ship stale icons;
  - either way, a change to the mark's or the favicon's geometry or colours is a change to spec sections 4.5 and 4.6: ask the user first;
  - the ICO or the touch icon alone, such as a wrong size or dark corners: devops-sre fixes `render_icons.py` and re-renders (Task 14).

  If the 16px image loses more than its axis, for example the bowls merging into the stems, stop and show the user the 8x view. Offer three options:
  - accept it;
  - render the ICO's 16px image from a pixel-fitted variant: a follow-up pull request that changes `render_icons.py`, so it does not hold up Task 18;
  - change the small geometry, which is a spec change.

- [ ] **Step 3: share.** Send both screenshots with SendUserFile, and say what was checked. Point out the 16px image's faint red axis in the 8x view, and offer the pixel-fitted 16px variant as a follow-up in case the user wants a crisp line there. If SendUserFile is unavailable, give the user the two paths.

### Task 18 (controller): Gate, review, pull request, merge and deploy

This may run in a later session than PR 1a. Recreate any `$SCRATCH` script from the task that defines it:
- `serve_production.sh` from Task 1 Step 5;
- `wait_main_ci.sh` and `deploy_and_verify.sh` from Task 8;
- `contact_sheet.sh` from Task 17.

- [ ] **Step 1: the full gate,** as in Task 8 Step 1.

- [ ] **Step 2: serve the production profile locally,** adding the new assets:

```bash
bash "$SCRATCH/pr1/serve_production.sh" "$PWD" /favicon.ico /img/apple-touch-icon.png \
    /fonts/unbounded-latin.woff2 /fonts/instrument-sans-latin.woff2 /img/icons/copy.svg /img/mark-glyph.svg
```

Expected: each new path answers `200 cc=max-age=604800,public, immutable security=5/5`, and everything else answers as Task 1 Step 5 lists. If Task 10 ended in **Stop**, leave out the two font paths.

- [ ] **Step 3: security review.** Dispatch `appsec-reviewer` on `git diff main...HEAD`, focused on these questions:
  - Is every new SVG inert when opened directly as a document?
  - Does anything under `frontend/public` reach a third party?
  - Do the favicon links change any page's CSP exposure?
  - Does `scripts/render_icons.py` load anything but the checkout's own file?

  Route any finding to its owner, and re-run Step 1 after a fix.

- [ ] **Step 4: push and open the pull request.** Write the body to `$SCRATCH/pr1b/body.md`, with no attribution lines. Start from 1a's: `gh pr list --state merged --head feat/reflection-foundation --json number,title` finds its number, and `gh pr view <number> --json body -q .body` prints it. Keep its summary of the redesign and of the 1a/1b split. Replace its change list with 1b's files, and its evidence with the output of Steps 1 and 2 above, so none of 1a's counts reads as 1b's. Drop its "not checked here" item, which does not hold for 1b because this deploy runs 1a's checks, and its CI follow-up, which was 1a's to offer. Then add:
  - the fonts' provenance and licences, or that they are pending if Task 10 ended in **Stop**;
  - the favicon harness's answer, and the fallback if Task 13 took it. The harness proves Chromium only; another browser at worst shows the light tile;
  - the contact sheets, which cannot be attached, so the body lists what was checked. They stand in for section 10's page screenshots, since PR 1 changes no layout;
  - unless Task 10 ended in **Stop**, that the fonts commit also changed the working agreement: `CLAUDE.md` no longer counts the font files;
  - optional follow-ups for the user, in files this plan does not edit:
    - the file map in `.claude/agents/web-designer.md` gives line counts that have drifted: it says `style.css` has 680 lines, and the file had 749 when this plan was written. Unless Task 10 ended in **Stop**, its "13 self-hosted woff2" is out of date as well;
    - unless Task 10 ended in **Stop**, a comment in `.github/workflows/ci.yml`, in the build-context notes, still counts `frontend/` "with 13 woff2 fonts": replace `with 13 woff2 fonts` with `with its woff2 fonts`.

```bash
git push -u origin feat/reflection-assets
gh pr create --base main --head feat/reflection-assets \
    --title "Add the Reflection fonts, mark, favicon set and icons" \
    --body-file "$SCRATCH/pr1b/body.md"
```

If Task 10 ended in **Stop**, leave the fonts out of the title: `Add the Reflection mark, favicon set and icons`.

- [ ] **Step 5: CI,** as in Task 8 Step 5. CI runs Google Chrome, where the dry run used Debian's Chromium, so the favicon harness can answer differently there. Read its failures as Task 13 Step 4 does:
  - **Only `test_the_dark_rule_applies_under_the_production_csp` fails, saying the tile read light:** take the fallback in this pull request.
    - *web-designer:* delete the `<style>` element from `favicon.svg`. In `frontend/public/img/README.md`, replace the `favicon.svg` item with the fallback text from Task 13 Step 5, with `Google Chrome` in place of `Chromium`: here local Chromium applied the rule and CI's Chrome blocked it. Replace only that item: since Task 14, the ``- **`../favicon.ico` and `apple-touch-icon.png`:**`` item follows it, and it stays.
    - No re-render: `render_icons.py` leaves the `<style>` out of both renders, so the ICO and the touch icon do not change.
    - Re-run Steps 1 and 2, commit with Task 13 Step 7's fallback subject, `Drop the favicon's dark rule, which the production CSP blocks`, and push.
    - *Controller:* rebuild the contact sheets (Task 17 Step 1), whose dark sheet showed the dark tile. Add the fallback and the reason, that Google Chrome in CI blocked the rule which Chromium applied locally, to the body. Update it with `gh pr edit <number> --body-file "$SCRATCH/pr1b/body.md"`, and send the user the new dark sheet.
  - **Anything else in the harness fails:** Task 13 Step 4's third outcome applies. Debug the harness, and do not take the fallback.

- [ ] **Step 6: merge, with the user's approval,** as in Task 8 Step 6.

- [ ] **Step 7: deploy, with the user's approval.** First note what production runs now, and how many files under `frontend/public` this deploy changes. `/api/health` reports its version as `<short sha>-<build date>`:

```bash
deployed=$(curl -fsS --max-time 10 https://mirror.kalev.systems/api/health | sed -nE 's/.*"version" *: *"([0-9a-f]+)-.*/\1/p')
git fetch -q origin
echo "deployed: ${deployed:-unknown}"
if [ -n "$deployed" ] && git cat-file -e "$deployed^{commit}" 2>/dev/null; then
    git diff --name-only "$deployed" origin/main -- frontend/public | wc -l
else
    echo "STOP: the live version names no commit this checkout knows"
fi
```

Expected: 1a's merge commit, or a later one, and 33 files, or 26 if Task 10 ended in **Stop**. Call that number N. On `STOP`, find out what production runs before asking to deploy.

Then ask as in Task 8 Step 7. If approved, run `bash "$SCRATCH/pr1/deploy_and_verify.sh" "$PWD" "$SCRATCH/pr1b"` with `run_in_background: true`. Task 8's hand-run cache probes are not needed this time: this deploy runs 1a's `deploy.sh`, whose own checks now cover the cache headers too. Expected in its verification section:
  - `all N changed frontend/public/ file(s) match the checkout byte-for-byte`. Any `retrying` warnings along the way are the retry doing its job; paste them.
  - `all 10 probed paths carry the full 5-header set`, then `one Content-Security-Policy value across all probed paths` and `served Content-Security-Policy matches nginx/nginx.conf in this checkout`.
  - `pages, CSS and JS revalidate, fonts stay immutable, and the console loads twice with no 503`.
  - `all post-deploy checks passed`, and `deploy.sh rc=0`.

  Then check by hand:

```bash
SITE=https://mirror.kalev.systems
for p in /favicon.ico /img/apple-touch-icon.png /img/favicon.svg /fonts/unbounded-latin.woff2; do
    printf '%-32s %s\n' "$p" "$(curl -sS --max-time 10 -o /dev/null -w '%{http_code} %{content_type} %{size_download}B' "$SITE$p")"
done
```

  Expected: four `200`s, with `image/x-icon` (or `image/vnd.microsoft.icon`), `image/png`, `image/svg+xml` and `font/woff2`. If Task 10 ended in **Stop**, the font is not deployed: leave it out of the loop and expect three.

  If `deploy.sh` exits non-zero, or anything differs, stop. Report it with the output, and ask the user before any rollback or other production action.

- [ ] **Step 8: update the memory.** In `bsdmirror-reflection-redesign`, record that PR 1 is done: the 1a and 1b PR numbers and deploy dates, the harness's answer on the favicon, whether the fonts shipped, and PR 2's earliest deploy date.
