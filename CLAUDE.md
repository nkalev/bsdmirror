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

- **No migrations.** Schema comes from `Base.metadata.create_all` (`backend/app/core/database.py:43`). Alembic is installed but unconfigured. Column changes are silently ignored on existing deployments.
- **Models are duplicated.** `sync/sync_service.py:452-512` mirrors `backend/app/models/` by hand. Until a shared package exists, model changes must land in both places in the same commit. They already drifted once (commit `798ae79`).
- **Tooling is installed but never runs.** `ruff`, `bandit`, `pytest`, `pytest-asyncio`, `pytest-cov` are in `backend/requirements.txt`; there is no CI, `pyproject.toml`, Makefile, or pre-commit, and zero test files.
- **nginx `add_header` does not inherit.** A lower level defining any `add_header` drops all inherited ones. `location /admin` (`nginx/sites/default.conf:112`) therefore serves the admin panel with **no CSP and no HSTS**.
- **The Google Fonts imports depend on that bug.** Both stylesheets `@import` Google Fonts, which the CSP at `default.conf:55` does not permit. Fixing the header inheritance breaks admin fonts — treat them as one change.
- **A stuck sync is unrecoverable.** If the sync container dies mid-`rsync`, the mirror stays `SYNCING` and `backend/app/api/admin.py:301` rejects every retry. No reaper exists.
- **Settings are unvalidated.** `backend/app/api/admin.py:513` accepts arbitrary strings; an invalid cron value wedges the scheduler in a silent 10-second retry loop.

## Commands

```bash
docker compose up -d --build                              # full stack
docker compose -f docker-compose.yml -f docker-compose.dev.yml up   # dev
docker compose config -q                                  # validate compose
docker compose exec nginx nginx -t                        # validate active nginx config
```

Setup generates `.env` and `.credentials`; both are gitignored and must stay that way.
