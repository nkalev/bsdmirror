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
│   ├── models/       # The SQLAlchemy schema. One definition, see below.
│   ├── settings_spec.py  # What a `settings` row may hold. See below.
│   └── protected_paths.py  # Per-mirror EOL trees --delete may not remove
├── backend/          # FastAPI backend API
│   ├── app/
│   │   ├── api/      # API route handlers
│   │   └── core/     # Configuration, security, database engine/session
│   ├── alembic/      # Migrations. Owns the schema; see below.
│   │   └── versions/
│   ├── alembic.ini
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

- **`Base.metadata.create_all` has no callers at all.** It used to have exactly
  one, `init_db()` in `backend/app/core/database.py`. Alembic now owns the
  schema, so that call is gone and `init_db()` only *verifies* that the database
  is under Alembic's control. create_all creates missing *tables* only, so
  keeping it alongside migrations would mean two mechanisms defining one
  database with the winner decided by startup order — on a fresh install it
  would build the schema and the baseline migration would then fail trying to
  `CREATE TABLE` over it. `tests/test_shared_models.py::test_create_all_has_exactly_one_caller`
  walks the AST of every file in the repo and fails if any caller appears
  outside the test suite (the SQLite fixtures in `tests/` are the intended use).

- **Enums are stored by NAME, not by value.** Every enum is
  `class X(str, Enum)` with lowercase values (`ACTIVE = "active"`), but
  SQLAlchemy's `Enum` persists `.name`, so Postgres holds `'ACTIVE'` and the
  type is `ENUM('ACTIVE','SYNCING','ERROR','DISABLED')` in that order. Adding
  `values_callable=` to any of those columns would silently invert this and make
  every existing row unreadable. `tests/test_shared_models.py` pins the labels,
  their order, and the round trip in both directions.

### Changing the schema

Editing a model is half a change. The other half is a migration, and CI fails
without it: the `migrations` job runs `alembic upgrade head` on an empty
database and then `alembic check`, which reports any model change with no
corresponding operation.

```bash
docker compose up -d postgres
docker compose build backend                    # migrate.sh runs from the image
$EDITOR shared/models/mirror.py                 # 1. edit the model
./scripts/migrate.sh revision -m "what changed" # 2. autogenerate
$EDITOR backend/alembic/versions/2026*_*.py     # 3. READ IT. Fill in the
                                                #    checklist in its docstring.
./scripts/migrate.sh sql                        # 4. read the SQL it will run
./scripts/migrate.sh upgrade                    # 5. apply it locally
pytest                                          # 6. and the suite still passes
```

Step 3 is not optional. Autogenerate is a first draft: it does not see data
migrations, it renders `server_default` changes it cannot always express, and
it will happily generate a `DROP COLUMN` for a rename. The template in
`backend/alembic/script.py.mako` puts four questions in every new migration's
docstring — whether it touches populated tables, whether it takes a long lock,
whether it is safe for the code that is *currently* running, and whether
`downgrade()` loses data. Answer them in the file.

Two things are structural rather than advisory:

- **`revision` reads your working tree; everything else reads the built image.**
  `migrate.sh` runs alembic inside the `backend` image, because the `backend`
  compose network is `internal: true`. `revision` bind-mounts `shared/` and
  `backend/alembic/` from the checkout so it generates against the model you
  just edited; without that it compares the *image's* models, finds no
  difference, and writes a migration whose `upgrade()` is `pass`, successfully.
  Every other command fingerprints both and warns — or, if it would change
  something, refuses.

- **`0001_baseline` cannot be downgraded.** Its `downgrade()` raises. It exists
  to be *stamped* onto the production database, which already has the schema,
  not to be run there and not to be unapplied from there. Every later revision
  must implement a real `downgrade()`; the deploy path depends on it.

### Settings are validated in `shared/settings_spec.py`, not at the call site

The `settings` table is written by the API and read by the sync service. Both
import the same spec, and neither trusts the other.

If you add a settings key, add it to `SETTING_SPECS` and nowhere else.
`backend/app/main.py` seeds its default and description from there, the
`PATCH /api/admin/settings` validator accepts values through it, and
`SyncService.reload_settings` refuses anything it rejects. Three copies of "the
default schedule is `0 4 * * *`" is how they drift; one is how they cannot.

Two rules that are easy to get wrong:

- **Bound the value, not just its type.** `sync_timeout=1` is a valid integer
  and breaks every sync as surely as a malformed one. Every bound in that file
  is derived from an observed run and carries the derivation in a comment; a new
  one should too.
- **Name the key in the error message.** The admin panel renders pydantic's
  `msg` field and nothing else — not `loc` — so `"must be positive"` reaches the
  operator as a sentence about nothing.

`tests/test_settings_validation.py` covers all three layers, including values
written straight to the table with the API bypassed.

### The sync service owns the jobs it is running

`SyncService.active_job_ids` holds the ids of the jobs this process is currently
executing, and `reap_orphaned_jobs` treats any `running` row that is *not* in it
as abandoned. That set is the entire basis for deciding whether a sync is dead,
so:

- **`sync_mirror_job` is the only thing that may write to it.** A structural
  test enforces that. Adding a second writer is a way to protect a dead job or
  expose a live one.
- **The claim is taken before the row is marked `running`, and released after it
  is marked finished**, with no `await` in between either time. The reaper is a
  coroutine on the same event loop, so it can only observe the pair in a
  consistent state. Reorder that and a live sync becomes reapable.
- **Do not add an elapsed-time condition.** A healthy full sync has run for
  15h43m; an incremental of the same mirror takes 13 minutes. There is no
  threshold that separates them, and a false positive kills a 2.5 TB transfer at
  hour fifteen. `_orphan_verdict` reports elapsed time for the log line and is
  structurally prevented from consulting it.

`tests/test_orphan_reaper.py` mutation-tests that decision: it rewrites
`_orphan_verdict` with each plausible wrong version — including the naive
one-hour threshold — and fails if the decision table does not go red.

### Key Technologies

- **Backend**: Python, FastAPI, SQLAlchemy (async), PostgreSQL
- **Frontend**: Vanilla JavaScript (no framework), CSS
- **Sync Service**: Python, asyncio, rsync
- **Infrastructure**: Docker, Nginx, Redis, PostgreSQL

## Continuous Integration

`.github/workflows/ci.yml` runs on every push and on pull requests into `main`.
Nine jobs, all independent, plus a `ci` job that aggregates them:

| Job | Command | Catches |
|---|---|---|
| `ruff` | `ruff check .` | lint and dead-code errors |
| `bandit` | `bandit -r backend/app sync backend/alembic` | insecure Python patterns |
| `pytest` | `pytest` | the test suite in `tests/` |
| `migrations` | `alembic upgrade head` + `alembic check` | a model change with no migration, a branched revision history, and an `alembic.ini`/`versions/` tree that does not work *from inside the built image* |
| `compose` | `docker compose config -q` | compose syntax, and `${VAR}` references that exist nowhere |
| `nginx` | `nginx -t` | every site profile under `nginx/sites/*/`, mounted the way `docker-compose.yml` mounts them, plus the headers on the wire |
| `shellcheck` | `shellcheck scripts/*.sh` | quoting and `set -e` bugs in the deploy-time shell |
| `systemd` | `systemd-analyze verify` | unit files that would fail at `systemctl start`, not at install |
| `ci` | — | **the one check to require in branch protection**; fails unless every job above succeeded |

`ci` is the check to put in the branch protection rule. Requiring them
individually means remembering to add the next one by hand, which is exactly the
step that gets skipped — so `ci` `needs:` all of them, and a step in that job
parses this workflow and fails if a job exists that `needs` does not name.

Run the whole Python side locally before pushing:

```bash
pip install -r backend/requirements.txt   # ruff, bandit and pytest are already pinned in it
ruff check .
bandit -r backend/app sync backend/alembic --severity-level medium --skip B104
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
- **The `migrations` job runs everything inside the built backend image,**
  against a real Postgres of the version `docker-compose.yml` pins. A migration
  that works from a checkout and not from the image is the exact failure this
  repo keeps having, and only building the image proves the difference. Its last
  step is a control experiment: it builds a second database with
  `Base.metadata.create_all` — which is how the production database got its
  schema — and `pg_dump`s both, requiring them to be identical. That closes the
  chain *migrations → models → production*, because
  `tests/test_shared_models.py` separately pins the models against a dump of the
  live database. It is the only `create_all` left anywhere near this repo, and
  it exists to be compared against, not to build anything.
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
