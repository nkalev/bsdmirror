# bsdmirror — working agreement

Self-hosted mirror platform for FreeBSD, NetBSD, and OpenBSD. FastAPI + SQLAlchemy 2.0 async + Postgres + Redis; a separate async Python service that shells out to `rsync`; a dependency-free vanilla-JS admin SPA; nginx; Docker Compose.

## Roles

Four agents own this codebase. Route work to the owner rather than editing across boundaries.

| Agent | Owns |
|---|---|
| `devops-sre` | `docker-compose*.yml`, `nginx/`, Dockerfiles, `scripts/`, CI, migrations, sync-service *operations* |
| `developer` | `backend/app/**`, `sync/sync_service.py` logic, `admin.js` behavior, `main.js`, all tests |
| `web-designer` | `*.css`, `index.html`, error pages, `img/`, the *appearance* of `admin.js` markup |
| `appsec-reviewer` | Read-only audits across the config/code seams. Reports, never patches. |

### When to delegate

Routing to an owner is the default, but a subagent starts with **no context** and pays to
rediscover the repo on every run: `devops-sre`'s area is ~356 KB across 26 files, `developer`'s
~402 KB across 36, and a single `Read` of `scripts/deploy.sh` is ~16k tokens.

Delegate when the task needs roughly five or more file reads, crosses a boundary, or can run in
parallel with other work. Below that, a session already holding the context should just do it:
handing a three-line fix to a fresh agent costs more *and* produces worse work, because the agent
cannot see the conversation that explains why.

### The admin.js boundary

`frontend/public/admin/js/admin.js` is 1,162 lines, **456 of which contain HTML markup** plus 24 inline `style="..."` attributes. Two agents share this file:

- `developer` — control flow, state, `api.*`, routing, and every escaping decision.
- `web-designer` — how the rendered markup looks: classes, layout, spacing, color, type.

Restyling while fixing logic, or changing escaping while restyling, is a boundary violation. Flag it for the other owner instead.

## Definition of done

No change is complete on inspection alone. Each role has a verification gate in its own definition; the shared rule is **evidence before assertion** — paste real command output, and name any check you could not run and why.

This repo's first 36 commits include 30 `Fix ...` commits, almost all config/integration failures found *after* deploying. The gates exist to move that discovery earlier.

## Repo-wide constraints

Read these before touching anything; several are load-bearing.

- **Schema is owned by Alembic.** `create_all` is gone; `init_db()` only verifies `alembic_version` and logs the revision. Migrations run from `scripts/deploy.sh` between build and recreate, so a bad one stops the deploy with the old containers still serving. `scripts/migrate.sh upgrade` renders the SQL for review before applying. A fresh install must run `migrate.sh upgrade` before the backend will start; an existing database is adopted once with `migrate.sh adopt`, which refuses unless the live schema already matches `shared/models/` exactly.
- **Models live in one place.** `shared/models/` is imported by both `backend/app/` and `sync/sync_service.py`. They used to be declared twice and had drifted 17 ways, including a `VARCHAR(20)` where production has an enum and a missing `ON DELETE CASCADE`. Do not reintroduce a second definition. The sync service imports the models but deliberately not `Base`, so `create_all` is unreachable from it; AST tests enforce that.
- **Tooling runs, in CI and in a container.** `pyproject.toml` configures ruff, pytest, coverage and bandit. `.github/workflows/ci.yml` has 11 jobs with `ci` as the required aggregate. There are 526 tests (12 files) in `tests/`, plus two Node harnesses in `tests/js/` that drive real headless Chrome. Run them with `docker compose run --rm test` — never on the host. Read the **exit code**, not the last line: piping the run through `tail` reports tail's status and turns a red suite green.
- **nginx `add_header` does not inherit.** A level that defines any `add_header` drops every inherited one. That is why the headers now live in `nginx/snippets/security-headers.conf` and `security-headers-tls.conf` and are `include`d at each level that needs them, instead of being declared once at `server` and hoped for. Adding an `add_header` anywhere means re-including the snippet at that level. Site configs are `nginx/sites/{bootstrap,dev,production}/*.conf` — **directories**, not a flat `sites/*.conf`; a glob written the old way matches zero files and reports clean.
- **Fonts are self-hosted.** `frontend/public/css/fonts.css` holds the `@font-face` rules with `url()`s pointing at `/fonts/`, served from the 13 woff2 files in `frontend/public/fonts/` (see the README there for regenerating them). Nothing reaches fonts.googleapis.com or fonts.gstatic.com, and the CSP does not permit it. Do not reintroduce a Google `@import`.
- **Orphaned syncs are reaped by ownership, not by a timer.** The sync service tracks its own active job ids; a `RUNNING` row it does not own is one nothing will advance. There is deliberately no elapsed-time threshold — job 615 was a healthy 15h43m transfer and any timer would eventually kill one. The reaper does not cover a container that dies and never returns; that is the health check's job.
- **Settings are validated at the write boundary and defended at the reader.** Rules live once in `shared/settings_spec.py`. The API rejects an unusable value with a 422 before touching the ORM, and the sync service independently refuses a bad value that reached the database by another route, keeping the previous one and warning — it used to be `except ValueError: pass`.

## Commands

```bash
docker compose up -d --build                              # full stack
docker compose -f docker-compose.yml -f docker-compose.dev.yml up   # dev
docker compose run --rm test                              # test suite (profile `test`)
docker compose config -q                                  # validate compose
docker compose exec nginx nginx -t                        # validate active nginx config
```

Setup generates `.env` and `.credentials`; both are gitignored and must stay that way.
