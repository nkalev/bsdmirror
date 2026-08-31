# Contributing to BSD Mirror

Thank you for your interest in contributing to the BSD Mirror project! This document provides guidelines and information for contributors.

## How to Contribute

### Reporting Issues

- Use [GitHub Issues](https://github.com/nkalev/bsdmirror/issues) to report bugs or request features
- Search existing issues before creating a new one
- Include relevant details: error messages, logs, steps to reproduce

### Submitting Changes

1. Fork the repository
2. Create a feature branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. Make your changes and commit with clear, descriptive messages
4. Push to your fork and open a Pull Request against `main`

### Pull Request Guidelines

- Keep PRs focused on a single change
- Include a clear description of what the PR does and why
- Test your changes locally with `docker compose up -d --build`
- Ensure existing functionality is not broken

## Development Setup

### Prerequisites

- Docker 24+ and Docker Compose v2
- Git

### Local Development

1. Clone the repository:
   ```bash
   git clone https://github.com/nkalev/bsdmirror.git
   cd bsdmirror
   ```

2. Run the setup script:
   ```bash
   chmod +x scripts/setup.sh
   ./scripts/setup.sh
   ```

3. Start the services:
   ```bash
   docker compose up -d --build
   ```

4. Access locally:
   - Web UI: http://localhost
   - Admin Panel: http://localhost/admin
   - API docs: http://localhost/api/docs

### Project Structure

```
bsdmirror/
├── shared/           # Code imported by BOTH Python services
│   └── models/       # The SQLAlchemy schema. One definition, see below.
├── backend/          # FastAPI backend API
│   ├── app/
│   │   ├── api/      # API route handlers
│   │   └── core/     # Configuration, security, database engine/session
│   └── Dockerfile
├── frontend/         # Static frontend files
│   └── public/
│       ├── admin/    # Admin panel SPA
│       ├── css/      # Stylesheets
│       ├── js/       # Public site JavaScript
│       └── img/      # Images and logos
├── sync/             # Rsync sync service
│   ├── sync_service.py
│   └── Dockerfile
├── nginx/            # Nginx configuration
│   ├── nginx.conf
│   └── sites/        # Site configurations
├── rsync/            # Rsync server
├── scripts/          # Setup and maintenance scripts
└── docker-compose.yml
```

### The database schema lives in `shared/models/`, once

`mirrors`, `sync_jobs`, `settings`, `users` and `audit_logs` are declared in
exactly one place. Both services import them:

```python
from shared.models import Mirror, MirrorStatus, SyncJob, SyncStatus
```

They used to be declared twice -- SQLAlchemy 2.0 `Mapped`/`mapped_column` in
`backend/app/models/`, and hand-written `Column(...)` at the bottom of
`sync/sync_service.py` under a comment asking that the two be kept identical.
Nothing checked that, and they had drifted in seventeen distinct ways by the
time they were merged, one of which reached production (commit `798ae79`, a
Postgres enum type mismatch). The last one still open was
`mirrors.mirror_type`: a native `mirror_type` enum in the database, declared
`String(20)` by the sync service. It never corrupted anything only because the
sync service happens never to write that column.

Three things about this package are load-bearing:

- **Neither service is pip-installed.** `shared/` sits at the repo root because
  that is where it can be imported identically everywhere: `pythonpath` in
  `pyproject.toml` already includes `"."` for tests, and each Dockerfile does
  one scoped `COPY shared/ ./shared` into its `/app` WORKDIR. The sync image
  contains no `backend/`, so the package could not have lived under it.

- **`Base.metadata.create_all` has exactly one caller**: `init_db()` in
  `backend/app/core/database.py`. The sync service imports the models but
  deliberately not `Base`. create_all creates missing *tables* only, so with no
  migrations the first process to run it fixes the schema permanently, and both
  containers start together, so a second caller is also a race on `CREATE TYPE`.
  `tests/test_shared_models.py::test_create_all_has_exactly_one_caller` walks
  the AST of every file in the repo and fails if a second one appears.

- **Enums are stored by NAME, not by value.** Every enum is
  `class X(str, Enum)` with lowercase values (`ACTIVE = "active"`), but
  SQLAlchemy's `Enum` persists `.name`, so Postgres holds `'ACTIVE'` and the
  type is `ENUM('ACTIVE','SYNCING','ERROR','DISABLED')` in that order. Adding
  `values_callable=` to any of those columns would silently invert this and make
  every existing row unreadable. `tests/test_shared_models.py` pins the labels,
  their order, and the round trip in both directions.

Changing the schema still needs care for the reason that has not gone away:
there are no migrations, and `create_all` will not alter an existing table.
Adding a column to a model changes nothing in a database that already has that
table. That is the next task, not this one.

### Key Technologies

- **Backend**: Python, FastAPI, SQLAlchemy (async), PostgreSQL
- **Frontend**: Vanilla JavaScript (no framework), CSS
- **Sync Service**: Python, asyncio, rsync
- **Infrastructure**: Docker, Nginx, Redis, PostgreSQL

## Continuous Integration

`.github/workflows/ci.yml` runs on every push and on pull requests into `main`.
Seven jobs, all independent, plus a `ci` job that aggregates them:

| Job | Command | Catches |
|---|---|---|
| `ruff` | `ruff check .` | lint and dead-code errors |
| `bandit` | `bandit -r backend/app sync` | insecure Python patterns |
| `pytest` | `pytest` | the test suite in `tests/` |
| `compose` | `docker compose config -q` | compose syntax, and `${VAR}` references that exist nowhere |
| `nginx` | `nginx -t` | every site profile under `nginx/sites/*/`, mounted the way `docker-compose.yml` mounts them, plus the headers on the wire |
| `shellcheck` | `shellcheck scripts/*.sh` | quoting and `set -e` bugs in the deploy-time shell |
| `systemd` | `systemd-analyze verify` | unit files that would fail at `systemctl start`, not at install |
| `ci` | — | **the one check to require in branch protection**; fails unless every job above succeeded |

`ci` is the check to put in the branch protection rule. Requiring the seven
individually means remembering to add the eighth by hand, which is exactly the
step that gets skipped — so `ci` `needs:` all of them, and a step in that job
parses this workflow and fails if a job exists that `needs` does not name.

Run the whole Python side locally before pushing:

```bash
pip install -r backend/requirements.txt   # ruff, bandit and pytest are already pinned in it
ruff check .
bandit -r backend/app sync --severity-level medium --skip B104
pytest
```

A few things about these jobs are deliberate and worth knowing before you change
them:

- **Python 3.12, matching `python:3.12-slim` in the Dockerfiles.** The `pytest`
  job asserts the two agree and fails if a Dockerfile moves to another
  interpreter. Bump `PYTHON_VERSION` in the workflow in the same commit.
- **ruff and bandit are installed from the pins in `backend/requirements.txt`,**
  not from `latest`. If a pin disappears, the job fails instead of guessing.
- **The bandit gate is `--severity-level medium --skip B104`.** An unfiltered run
  reports three findings, all accepted by design: two LOW string-heuristic false
  positives (`token_type="bearer"`, a Redis key prefix) and B104 for the sync
  service's health server binding `0.0.0.0` — that service publishes no ports, so
  it is only reachable from the compose networks. The full unfiltered report is
  still printed in the job log. If you fix these at the source with `# nosec`,
  drop the floor to LOW in the same change.
- **The `compose` job writes a placeholder `.env`** containing exactly the
  variables that have no default in `docker-compose.yml`, then fails if compose
  warns about any *other* unset variable. Adding a `${VAR}` to compose therefore
  means adding it to that fixture and to the environment table in `README.md`.
  Never put a real secret there.
- **The `pytest` job refuses to let the browser-driven suites skip.**
  `tests/test_admin_js_escaping.py` and `tests/test_public_page_csp.py` shell out
  to `node`, and the second one drives headless Chrome over CDP. Both carry a
  `pytest.mark.skipif` so a contributor without Chrome still gets the rest of the
  suite — locally that is what you want. In CI it is not: a skip there turns
  "the XSS-escaping and CSP coverage did not run" into a green build. So the job
  asserts both binaries are present *before* pytest, prints their resolved paths
  and versions, and afterwards re-reads the JUnit report and fails if either
  module skipped a test or contributed none at all. The presence check imports
  the two test modules and reads the same `NODE` / `CHROME` values the `skipif`
  decorators use, so it cannot drift from the discovery logic it guards. If a
  runner image ever drops one, install it in the job — do not relax the gate.
- **`nginx -t` runs inside `nginx:1.25-bookworm`,** the same image compose uses,
  against each site profile under `nginx/sites/*/` in turn. The `-v` flags are
  **derived from `docker compose config`** by `scripts/ci-nginx-mounts.py`, not
  written in the workflow: a hardcoded recipe made CI an independent guess at
  what production looked like, and the guess was wrong from February to August
  2026 without anything going red. If compose grows an `/etc/nginx` mount the
  script cannot map, the job fails instead of validating the old layout.

  It runs `nginx -T` rather than `-t` and asserts the `# configuration file`
  banners name `/etc/nginx/host/nginx.conf` and the snippets, because an empty
  mount list makes `nginx -t` validate the *stock image config* and print "test
  is successful" — verified, and exactly the kind of green-with-nothing-under-it
  this repo keeps getting caught by.

  A final step starts the production profile for real and asserts the five
  security headers on six paths over TLS. `nginx -t` cannot prove a header
  reaches a client; only a request can.

  It still does not prove that `backend:8000` resolves or that `/data/mirrors`
  exists; those need the full stack and belong to `scripts/deploy.sh`.

## Rendering HTML in the admin panel

`frontend/public/admin/js/admin.js` builds its markup as template literals and
injects it. Escaping there used to be opt-in — an `escapeHtml()` you had to
remember to call — and three render paths drifted without it. It is now the
default, and the raw path is gone.

**The contract, in four lines:**

```js
html`<td>${user.username}</td>`   // every ${...} is escaped
html`<tr>${rows}</tr>`            // SafeHtml, and arrays of it, pass through
setHtml(el, html`...`)            // the only way to write innerHTML
trustedHtml(s)                    // the escape hatch; zero uses today
```

- **Every template literal that becomes HTML must be tagged `html`.** An
  untagged one produces a plain string, and `setHtml()` throws a `TypeError`
  rather than injecting it. Nested literals inside `${...}` need the tag too.
- **Never assign `innerHTML` directly.** `setHtml()` accepts `SafeHtml` and
  nothing else, which is what makes a forgotten tag a loud failure instead of a
  silent injection.
- **Do not call `escapeHtml()` from inside an `html` literal** — it escapes
  twice and renders `&amp;lt;` on the page.
- **Return arrays from `.map()`, do not `.join('')` them.** `html` flattens an
  array of `SafeHtml`; joining first collapses them into a plain string that
  then gets escaped.
- **`trustedHtml()` is a review point.** It is deliberately ugly and greppable.
  If you add a use, say why in the commit message.

`escapeHtml()` escapes `& < > " '` and a backtick, which covers element text and
*quoted* attribute values. It does not make these safe, and there are none in
the file today — `tests/test_admin_js_escaping.py` fails if one appears:

| Context | Why escaping is not enough |
|---|---|
| `href="${x}"`, `src="${x}"` | `javascript:alert(1)` contains no HTML metacharacter |
| `value=${x}` (unquoted) | a space or `=` ends the value; neither is escaped |
| `style="${x}"` | CSS context, not HTML |
| `onclick="${x}"` | script context; use `data-action` and the existing delegation |
| inside `<script>`/`<style>` | not HTML text at all |

### Testing it

`tests/test_admin_js_escaping.py` covers this two ways: it shells out to
`node tests/js/escaping_harness.mjs`, which loads the real `admin.js` into a vm
and drives the renderers with attack strings, and it parses `admin.js` as text
to enforce the invariants above. Both mutation-test themselves — the escaper is
deliberately broken twelve ways, and each break must turn a named check red.

**The JS checks need `node` on `PATH`** and skip without it, so a local run with
no node reports a smaller number than CI. There is no JS test runner and no
`package.json`; this is a plain script on purpose.

What this proves: the escaping is correct as a string transformation, and every
render path routes untrusted fields through it. What it does not prove: browser
behaviour. There is no DOM in the harness, so parser-level attacks (mXSS,
`<svg>`/`<math>` foreign content) are out of scope. Defence in depth for those
is a CSP on `/admin/`, which `nginx/sites/production/production.conf` now serves
(via `nginx/snippets/security-headers-tls.conf`).

## No inline event handlers

The production CSP is `script-src 'self'` (`nginx/nginx.conf`, the
`map $host $csp_policy` block). That blocks `onclick="..."` and every other
inline handler attribute outright — the handler is never compiled, so the
element simply does nothing when clicked, with the only sign a console error
the user never sees.

This is not hypothetical. `index.html` shipped three
`onclick="copyRsync('FreeBSD')"` buttons that were dead for every visitor for
the life of the deployment. Reading the HTML did not catch it, because an
`onclick` attribute looks like working code and the policy that kills it lives
in another file owned by another role.

Bind events in JavaScript instead. Put whatever the handler needs in a `data-`
attribute:

```html
<button class="btn btn-secondary" data-copy-rsync="FreeBSD">
```

```js
document.querySelectorAll('[data-copy-rsync]').forEach(btn => {
    btn.addEventListener('click', () => copyRsync(btn.dataset.copyRsync));
});
```

Bind inside the existing `DOMContentLoaded` handler in `main.js`, or via the
document-level delegation `admin.js` already uses for `[data-action]`.

`tests/test_public_page_csp.py` enforces this. It serves `frontend/public` with
the exact policy string from `nginx/nginx.conf`, runs headless Chrome, and
dispatches a real trusted click at each button, so a dead control fails the
build instead of shipping. **It needs `node` and Chrome** and skips without
them. Never add `'unsafe-inline'` to make a control work; that trades the
policy protecting the whole site for one button.

## Code Style

- Python: Follow PEP 8 conventions
- JavaScript: Use modern ES6+ syntax; no build step and no dependencies
- Admin-panel markup: see *Rendering HTML in the admin panel* above
- Use clear, descriptive variable and function names
- Add comments for non-obvious logic

## Areas for Contribution

- Bug fixes and error handling improvements
- UI/UX improvements to the public site or admin panel
- Documentation improvements
- New mirror protocol support
- Performance optimizations
- Test coverage

## License

By contributing, you agree that your contributions will be licensed under the BSD 3-Clause License.
