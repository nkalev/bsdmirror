# BSD Mirror

A self-hosted mirror platform for FreeBSD, NetBSD, and OpenBSD distributions with a web UI, admin panel, and automated rsync synchronization.

## Features

- **Multi-BSD Support**: Mirror FreeBSD, NetBSD, and OpenBSD distributions
- **Web UI**: Public file browser with real-time status and statistics
- **Admin Panel**: Manage mirrors, upstream URLs, sync schedules, users, and settings
- **Multiple Protocols**: HTTP/HTTPS and rsync access
- **Automated Sync**: Cron-scheduled rsync with manual trigger support
- **Security**: Rate limiting, SSL/TLS, JWT authentication, RBAC (Admin/Operator/Readonly)
- **Docker Deployment**: Full stack deployed with Docker Compose

## Quick Start

### Prerequisites

- Ubuntu 22.04+ or similar Linux distribution
- Docker 24+ and Docker Compose v2
- Sufficient storage for mirrors (varies by distribution)
- Domain name with DNS configured (for production)

### Installation

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
   This generates a `.env` file with secure random passwords and configures upstream mirrors.

3. Create the database schema:
   ```bash
   docker compose up -d postgres
   ./scripts/migrate.sh upgrade
   ```
   The schema is owned by Alembic (`backend/alembic/`), not by the application.
   The backend used to create its own tables at startup with
   `Base.metadata.create_all`; that is gone, because create_all creates missing
   *tables* only — it silently ignores every column, type and constraint change
   on a table that already exists, which made schema changes undeployable.

   `migrate.sh` prints the SQL it is about to run before it runs it.

4. Start the services:
   ```bash
   docker compose up -d --build
   ```

   If you skip step 3, the backend refuses to start and says so:
   `The database has no alembic_version table...`. It is not a crash; it is the
   check that replaced create_all.

5. Access the services:
   - **Web UI**: https://your-domain.com
   - **Admin Panel**: https://your-domain.com/admin
   - **rsync**: rsync://your-domain.com/

   Admin credentials are displayed during setup and saved to `.credentials`.

### Adopting Alembic on a database that already exists

Only relevant once, and only on a deployment that predates the Alembic
adoption — its schema was built by `Base.metadata.create_all` and has no
`alembic_version` table.

**Do not run `migrate.sh upgrade` there.** The baseline revision contains the
full `CREATE TABLE` for all five tables; against a populated database it would
try to create tables over live data. Stamp it instead:

```bash
cd /opt/bsdmirror
./scripts/migrate.sh adopt
```

`adopt` writes one row into a new `alembic_version` table and executes no DDL —
no table is created, altered or dropped. Before it does, it refuses unless:

1. the live schema matches `shared/models/` exactly (`schema_diff.py`, which
   works before adoption where `alembic check` cannot), and
2. `0001_baseline` is still the only revision in the checkout.

Afterwards `./scripts/migrate.sh upgrade` is a no-op and every later migration
applies normally. If you get the wrong command, `migrate.sh upgrade` detects a
populated, unstamped database and refuses with a pointer to `adopt`.

### Database migrations

```bash
./scripts/migrate.sh status              # where the database is, where head is
./scripts/migrate.sh check               # does shared/models/ match the schema?
./scripts/migrate.sh sql                 # print the pending SQL, apply nothing
./scripts/migrate.sh upgrade             # print it, confirm, apply
./scripts/migrate.sh downgrade <REV>     # print it, confirm, apply
./scripts/migrate.sh revision -m "text"  # autogenerate (development only)
./scripts/migrate.sh --help
```

Everything runs inside the `backend` image, because the `backend` compose
network is `internal: true` and postgres is not reachable from the host. Every
command except `revision` therefore reports on the **built image**; if it does
not match your working tree, the read-only commands warn and the ones that
change something refuse, naming `docker compose build backend` as the fix.

`scripts/deploy.sh` runs migrations automatically, between the build and the
container recreate. See below.

### SSL Setup

For production with Let's Encrypt:
```bash
chmod +x scripts/ssl-setup.sh
./scripts/ssl-setup.sh
```

### Updating a running deployment

Use `scripts/deploy.sh`, not `git pull`. It refuses to deploy a commit whose
CI is not green, refuses to deploy on top of uncommitted edits, refuses to
interrupt a running rsync, and verifies the result afterwards.

```bash
cd /opt/bsdmirror
./scripts/deploy.sh                      # deploy origin/main
./scripts/deploy.sh --ci-check-only      # just ask "is main deployable?"
./scripts/deploy.sh --dry-run            # run every gate, change nothing
./scripts/deploy.sh --rollback <sha>     # go back to a previous commit
./scripts/deploy.sh --help               # all options and exit codes
```

Only `backend` and `sync` are rebuilt and recreated; `nginx`, `postgres` and
`redis` are never touched. The CI status comes from the public GitHub
check-runs API, so no token or deploy key is required.

Migrations run inside that sequence, in this order:

```
build images  ->  MIGRATE  ->  recreate backend and sync  ->  verify
```

Migrating before the recreate means a bad migration stops the deploy with the
**old containers still serving** (exit 3), rather than booting new code against
a schema it does not have. `env.py` wraps the upgrade in one transaction and
Postgres has transactional DDL, so a failure leaves the schema unchanged rather
than half applied. The cost is real and worth knowing: for the length of one
rebuild, the old code serves traffic against the new schema — fine for additive
migrations, which is what the review checklist in every generated migration
asks you to confirm. The SQL is rendered offline and printed before it is
applied, and `--dry-run` prints it without applying anything.

Post-deploy verification now includes `alembic check` against the freshly built
image, so a missing migration is a failed deploy rather than a 500 on the first
request that touches the new column. `--skip-migrations` opts out and says so
loudly in the final banner.

Exit codes: `0` deployed and verified, `1` preflight error, `2` a gate
refused and nothing was touched, `3` the deploy failed but the old containers
are still serving, `4` the new code is live but failed verification.

## Architecture

```
                    Internet
                       |
              ┌────────┴────────┐
              │      Nginx      │
              │  (Reverse Proxy │
              │  + File Server) │
              └───┬────┬────┬───┘
                  │    │    │
        ┌─────────┤    │    ├─────────┐
        │         │    │              │
   ┌────┴────┐  ┌─┴────┴──┐    ┌─────┴─────┐
   │ Backend │  │  Static  │    │   rsync   │
   │ (FastAPI│  │  Files   │    │  Server   │
   │   API)  │  │          │    │           │
   └────┬────┘  └──────────┘    └───────────┘
        │
   ┌────┴──────────┐
   │  PostgreSQL   │
   │  + Redis      │
   └───────────────┘
        │
   ┌────┴──────────┐
   │ Sync Service  │
   │ (rsync cron)  │
   └───────────────┘
```

The backend and the sync service are separate containers over one Postgres
database, and they share its schema through a single package, `shared/models/`,
copied into both images. Neither service redeclares a table. Only the backend
creates them: `Base.metadata.create_all` runs once, from `init_db()` at backend
startup, and the sync service deliberately does not import `Base`. See
[CONTRIBUTING.md](CONTRIBUTING.md#the-database-schema-lives-in-sharedmodels-once)
for why that boundary is enforced by a test rather than by convention.

## Configuration

Key environment variables in `.env`:

| Variable | Description | Default |
|----------|-------------|---------|
| `NGINX_SITE` | Which site profile nginx serves: a **directory** name under `nginx/sites/` — `dev`, `bootstrap` or `production`. `docker-compose.yml` mounts that directory *as* `/etc/nginx/sites-enabled`, so it decides the active config. `scripts/setup.sh` writes `dev`; `scripts/ssl-setup.sh` moves it to `production`. Changing it requires `docker compose up -d --force-recreate nginx` — docker resolves bind mounts at container creation, so a reload cannot pick it up. Replaces the retired `NGINX_SITE_CONF`, which named a file. | `dev` |
| `DOMAIN` | Public hostname. Used by `scripts/ssl-setup.sh` for the certificate, and by `scripts/nginx-apply.sh` to render the two `ssl_certificate` lines into `nginx/snippets/tls-cert.conf`. The site configs themselves contain no domain. | *(set at setup)* |
| `FREEBSD_UPSTREAM` | FreeBSD rsync upstream URL | `rsync://ftp.freebsd.org/FreeBSD/` |
| `NETBSD_UPSTREAM` | NetBSD rsync upstream URL | `rsync://rsync.NetBSD.org/NetBSD/` |
| `OPENBSD_UPSTREAM` | OpenBSD rsync upstream URL | `rsync://ftp2.eu.openbsd.org/OpenBSD/` |
| `SYNC_SCHEDULE` | Cron schedule for sync | `0 4 * * *` |
| `SYNC_BANDWIDTH_LIMIT` | Rsync bandwidth limit (KB/s, 0=unlimited) | `0` |
| `MIRROR_DATA_PATH` | Local path for mirror data | `/data/mirrors` |
| `LOG_LEVEL` | Log level for the backend and sync services (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |
| `ALERT_CHANNELS` | Comma-separated alert channels: `discord`, `slack`, `email`. Empty means "derive from whichever channel variable is set" | *(empty)* |
| `DISCORD_WEBHOOK_URL` | Discord incoming webhook. **Secret** | *(unset)* |
| `SLACK_WEBHOOK` | Slack incoming webhook. **Secret** | *(unset)* |
| `EMAIL_RECIPIENT` | Address for `mailx` alerts | *(unset)* |
| `STALE_AFTER_HOURS` | Alert when a mirror's last completed sync is older than this | `36` |
| `ALERT_REMIND_HOURS` | How often a still-broken condition is re-announced | `24` |
| `DISK_WARN_PCT` / `DISK_CRIT_PCT` | Disk usage that warns / alerts | `85` / `95` |
| `API_URL` | Base URL the health check probes. Empty derives `https://$DOMAIN` | *(derived)* |
| `ALERT_SOURCE_LABEL` | Name shown in alerts. Empty uses `DOMAIN`, then the hostname | *(derived)* |

Upstream URLs can also be changed from the admin panel without restarting services.

### Settings, and what the admin panel will not let you save

Four rows in the `settings` table are editable from the admin panel and read
back by the sync service. Every one of them is validated at the write boundary
(`PATCH /api/admin/settings`), and validated *again* by the sync service before
it is adopted. An unusable value is rejected with a `422` naming the key and the
value; a batch containing one is rejected in its entirety, so a save either
lands completely or not at all. An unknown key is still a `404`.

| Setting | Accepted | Why the bound |
|---|---|---|
| `sync_schedule` | Any cron expression `croniter` can advance: five or six fields, or a nickname such as `@daily`. `@reboot` is rejected. | Validated by running the exact call the scheduler runs. This is the one that used to take mirroring down: an invalid value threw inside the scheduler's `try`, the generic handler swallowed it, and the loop retried every ten seconds forever without syncing. |
| `sync_timeout` | `60`–`86400` seconds. `0` is rejected. | rsync's `--timeout` measures *I/O inactivity*, so the floor has to clear the quiet phases of a healthy run — file-list generation, and the `--delay-updates` / `--delete-delay` passes over half a million files. `0` means "no timeout" to rsync, which removes the only thing bounding a hung transfer. The `600` default remains the recommendation. |
| `sync_bandwidth_limit` | `0` (unlimited), or `128`–`10000000` KB/s. | A full OpenBSD file list is ~14 MB. Below ~128 KB/s that list alone takes longer to transfer than the default `--timeout`, so the sync aborts on its own metadata before moving a file. |
| `sync_on_startup` | `true`/`false` (also `1`/`0`, `yes`/`no`, `on`/`off`, `enabled`/`disabled`; case-insensitive). | Previously compared with `.lower() == "true"`, so any typo silently meant `false`. **Note:** the sync service currently reads the `SYNC_ON_STARTUP` *environment variable*, not this row — toggling it in the panel has no effect yet. |

Values are stored canonically: `  0 4 * * *  ` becomes `0 4 * * *`, `TRUE`
becomes `true`, `0600` becomes `600`. The rules live in
`shared/settings_spec.py`, imported by both the API and the sync service, so
there is one definition rather than one per service.

A value that reaches the table by some other route — `psql`, a restore from an
older dump, a deployment that predates the validation — is refused on read with
a `WARNING` naming the key, and the previous value is kept. If the schedule is
unusable at the moment it is used, the scheduler falls back to `0 4 * * *` and
logs an `ERROR`. A wrong schedule is a wrong schedule; a scheduler that never
runs again is an outage.

### Sync results

Pulling from a public mirror that is itself syncing means racing it. Upstream
writes each file to an rsync temp name (`.<original>.<6 random chars>`, mode 0600)
and then renames it into place. Lose that race one way and the file is gone before
we can read it; lose it the other way and it is there but unreadable. Neither is a
problem with the mirror, and rsync reports them with different exit codes.

**A sync that exits 24 is recorded as successful.** Exit 24 is rsync's "some files
vanished before they could be transferred" warning, and rsync returns it only when
nothing worse happened, so it is tolerated unconditionally.

**A sync that exits 23 is recorded as successful only if every error line is
explained.** Exit 23 — "some files/attrs were not transferred" — is a bucket, so it
is opened rather than trusted. The run succeeds only when every diagnostic line in
the output is either a vanished source file or a `Permission denied (13)` on a path
whose name has rsync's temp-file structure. **One line that is not** — a permission
error on real mirror content, an I/O error, a full disk, `IO error encountered --
skipping file deletion` — **and the whole run fails.** Anything the classifier does
not positively recognise counts as unrecognised, and an exit 23 with no readable
error lines at all is treated as unattributable and fails too. The bias is
deliberate: a spurious failure is loud and clears on the next run, while a mirror
wrongly marked `active` is published in that state and nobody finds out.

Tolerated runs are not silent. They are logged at `warning` with the number of temp
files and vanished files waved through and a sample of the paths, so a `completed`
job that was not perfectly clean can be told apart in `docker compose logs sync`.
Rejected ones are logged at `error` with the lines that were not recognised. In both
cases the full rsync output is kept on the job record.

Every other non-zero exit is a failure outright.

**A failed sync no longer clears "last synced".** The timestamp records when the
mirror was last known good, which is the one thing worth keeping when a sync fails.

### Abandoned syncs

If the sync container stops mid-`rsync` — OOM kill, host reboot, `SIGKILL` — the
job's completion step never runs. The `sync_jobs` row stays `running` and the
mirror stays `syncing`, and every manual retry is then refused with *"Mirror is
already syncing"*. Recovery used to be a hand-written `UPDATE`.

The sync service now clears these itself. The job is marked `failed` with an
explanation, and the mirror moves to `error` so it can be retried from the
panel. `last_sync_completed`, `total_size_bytes` and `file_count` are left
alone: a sync that died has no better answer to "when was this last good".

**It does not use elapsed time, and that is the whole design.** Duration cannot
tell a dead sync from a slow one. A full OpenBSD sync has run for 15 hours 43
minutes while perfectly healthy; the same mirror, incremental, finishes in 13
minutes. Any threshold either kills the first or never fires. Instead the
service asks whether *it* is running the job: it runs jobs one at a time and
knows their ids, so a `running` row it does not own is one that nothing is going
to advance. There is no threshold to tune and no way for a long transfer to be
mistaken for a corpse.

It runs at two moments:

- **on startup**, which is where a crash's leftovers get cleared — a process
  that has just started owns nothing, so every `running` row belongs to a
  process that is gone;
- **every ~5 minutes while running**, which covers a job stranded while the
  process kept going (an error between marking it started and marking it
  finished). Startup-only reaping would need a restart to clear those.

**What it does not cover:** a sync container that dies and never comes back.
Nothing inside the service can fix that. `restart: unless-stopped` brings it
back after a crash; a down host or an image that will not start needs the
external health check above.

It also assumes a **single** sync-service process, which `docker-compose.yml`
enforces by pinning the container name. Running two against one database would
let each reap the other's live jobs; doing that safely needs a claim both
processes can see, which means a new column, which means migrations.
The failure is visible in the mirror's status and error message and in the sync job
row instead.

**Size and file count are only updated by a successful sync.** A failed run's
statistics describe the fraction it transferred before dying, so recording them
would replace a correct total with a smaller wrong one.

**"Files" means regular files.** rsync reports its file list as, for example,
`Number of files: 5,582 (reg: 4,321, dir: 1,261)`; the mirror's file count is the
`reg:` figure. Earlier releases stored the leading total, which also counts
directories, symlinks and devices, so the counts shown on the public site and in the
admin panel were over-stated — by 29% in that example. **Counts will drop the first
time each mirror syncs after this change.** That is the correction, not a loss of
data; the byte totals are unaffected.

### Logging

Both services write newline-delimited JSON to stderr, so `docker compose logs backend`
and `docker compose logs sync` are one JSON object per line.

`LOG_LEVEL` sets the level of the services' own loggers (`app.*` in the backend, the
sync service's module logger) and is applied to stdlib `logging`, which is what
structlog's `filter_by_level` processor tests against. Third-party libraries keep
their own default levels, so raising `LOG_LEVEL` to `DEBUG` does not turn on
SQLAlchemy statement logging or aiohttp access logs. An unrecognised value falls
back to `INFO` rather than failing at startup.

## Monitoring and alerting

On 2026-07-02 the OpenBSD upstream went away. The mirror then failed **58
consecutive nights** and nobody found out. `scripts/health_check.sh` already
existed and would have caught it. Nothing had ever scheduled it, and it could
not have alerted if it had run (see *The errexit bug*, below).

### Which endpoint to point a monitor at

Three endpoints answer to the word "health" and they prove different things.
Picking the wrong one is how a mirror stays green while it is down.

| Endpoint | Served by | Proves | Depends on |
|---|---|---|---|
| `/health` | nginx, static string | this nginx process is up and serving | nothing |
| `/api/health` | backend | the FastAPI process is up | backend only |
| `/api/health/detailed` | backend | postgres and redis both answer within 5s; reports `degraded` and names the failing service when they do not | backend, postgres, redis |

**Point external monitoring at `/api/health/detailed` and alert on the JSON
`status` field.** `/health` is a hardcoded 200 that stays green while every
backing service is down — it is the nginx container's own liveness probe
(`docker-compose.yml` runs `curl -f http://localhost/health`) and
`scripts/deploy.sh` refuses to deploy while nginx is not up, so it must *not*
depend on postgres or redis: a database outage would otherwise mark nginx
unhealthy and block the deploy that fixes it. That narrowness is deliberate, and
it is exactly why it is the wrong thing for an external monitor to watch.

`/health` answers identically on `http://` and `https://` — `200`, `text/plain`,
the three bytes `OK\n`. It did not until 2026-08-31: `location = /health` existed
only in the `:80` server, so over TLS it fell through to `try_files ... /index.html`
and returned **200 with the homepage**, which every status-code monitor reads as
healthy. The definition now lives in `nginx/snippets/health.conf` and is included
by every server block; `scripts/ci-nginx-health.py` fails CI if one is missing,
and CI plus `scripts/deploy.sh verify_health_endpoint()` assert the response
*bytes* rather than its status code.

Note what `/api/health/detailed` still cannot tell you: whether the mirrors are
actually being synced. Postgres and redis answer happily for a mirror that has
not updated since July. That is what the staleness check below is for.

### What is checked

| Condition | Alerts when |
|---|---|
| `api` | `GET $API_URL/api/health` is not 200, or its `status` is not `healthy` |
| `mirror-api` | `/api/stats/health` is unreachable or unparseable — mirror freshness is then **unknown**, which is treated as bad |
| `mirror-stale:<name>` | `last_sync_completed` is older than `STALE_AFTER_HOURS`, is `null` (never synced), or is not a parseable timestamp |
| `mirror-error:<name>` | the mirror's status is `error` |
| `disk` | `MIRROR_DATA_PATH` is at or above `DISK_CRIT_PCT` |
| `containers` | any `bsdmirror*` container is unhealthy, or `docker ps` fails |

Staleness is the one that matters. A mirror that has not synced since July still
returns a `status`, still serves the files already on disk, and its containers stay
healthy — every other check passes. Only the clock gives it away.

Mirror state comes from `/api/stats/health`, which needs no credentials, so the
alerter holds no token that can expire and take the alerting down with it. The
endpoint's own top-level `status` field is deliberately ignored: it collapses to
`healthy`/`updating`/`degraded` and reports `healthy` for a mirror that has not
synced in two months. The per-mirror `last_sync` is what is read.

A mirror stuck in `SYNCING` is caught for free here too: its
`last_sync_completed` stops advancing, so it goes stale like any other. It is no
longer unrecoverable — see [Abandoned syncs](#abandoned-syncs) — but the alert
still fires if the sync service is not running to clear it, which is exactly the
case the reaper cannot cover.

### Not crying wolf

A channel that fires every hour while a problem persists gets muted, and a muted
channel is 58 silent nights with extra steps. Each condition is tracked
independently in `/var/lib/bsdmirror/health-state.json`:

| Transition | Message |
|---|---|
| ok → bad | **sent** (new problem) |
| bad → bad | silent, until `ALERT_REMIND_HOURS` have passed since the last message |
| bad → bad, reminder due | **sent** (still broken, with how long it has been bad) |
| bad → ok | **sent** (recovered, with how long it was bad) |
| ok → ok | silent |

Conditions are tracked separately so a *new* problem appearing while an old one
persists is not swallowed by the old one's silence.

A missing, unreadable or corrupt state file makes every currently-bad condition
look new, so it **alerts**. So does an unwritable state directory, and the message
says the alert may repeat. The state layer fails loud, never quiet.

An alert that no channel accepted is **not** recorded as sent, so it is retried on
the next run — a webhook outage during the transition cannot swallow the alert
permanently.

### Configuring a channel

Discord and Slack take different payloads (`{"content": ...}` vs `{"text": ...}`)
and have different length limits, so the channel is **explicit configuration, not
guessed from the webhook hostname** — hostname sniffing breaks silently behind a
proxy or against a self-hosted endpoint. Add to `.env`:

```
ALERT_CHANNELS=discord
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/<id>/<token>
```

Discord: *Server Settings → Integrations → Webhooks → New Webhook → Copy Webhook
URL*. Then:

```bash
./scripts/health_check.sh --test-alert   # send a test message
./scripts/health_check.sh --dry-run      # run the checks, print, send nothing
```

`ALERT_CHANNELS=discord,slack` sends to both. Naming a channel that is not
configured is a hard error rather than a silent no-op.

**The webhook URL is a bearer credential.** It lives in `.env` (mode 0600,
gitignored), is never passed to `curl` as an argument — `curl` reads it from a
`--config -` stream on stdin, so it does not appear in `ps` — and every line the
script prints, including `curl`'s own error output, is filtered through a literal
redactor first, so it cannot reach `journalctl` either.

Adding a fourth channel is three functions and one word in `CHANNEL_REGISTRY`;
the contract is documented above the channel section of the script.

### Scheduling

```bash
sudo ./scripts/install-health-timer.sh          # idempotent
sudo ./scripts/install-health-timer.sh --dry-run
sudo ./scripts/install-health-timer.sh --uninstall
```

It refuses to install unless an alert channel is configured (`--allow-no-channel`
overrides), because installing a checker that cannot tell anyone is how this repo
got here.

A **systemd timer**, not a cron entry. There is precedent for cron —
`scripts/ssl-setup.sh:164` writes `/etc/cron.d/certbot-renew` — and it is the right
call there, because certbot's failure becomes visible the next time a browser loads
the site. Alerting is the opposite: its failures are invisible by construction, so
the scheduler itself has to be observable.

```bash
systemctl list-timers bsdmirror-health.timer   # next run, last run
journalctl -u bsdmirror-health -n 50           # every past run, with exit status
systemctl start bsdmirror-health               # run it now
```

`Persistent=true` is the single most important line in the timer: a run missed
while the host was down is executed on the next boot instead of being silently
skipped, and "silently skipped" is the bug being fixed.

The check runs hourly. Because of the dedup above, a persistent problem still
produces exactly one message plus a daily reminder; the only thing the shorter
interval buys is that a new problem is noticed within an hour.

Exit 1 means "a condition is bad" and is allowed to fail the unit, so
`systemctl --failed` is a second signal alongside the webhook. Exit 2 means the
script could not run at all.

### The errexit bug

The previous `health_check.sh` counted failures with:

```bash
check_health || ((errors++))
```

Under `set -euo pipefail` on **bash 4 and later**, this aborts the script at the
first failing check, before `send_alert` is ever reached. `((errors++))`
post-increments from `0`, evaluates to `0`, and therefore exits 1; as the last
command of an `||` list it is not exempt from `errexit`. Confirmed on bash 5.2.21
(Ubuntu 24.04, the deploy target). bash 3.2.57 (macOS) wrongly exempts the whole
list and does *not* abort, which is why it survived review on a laptop. Every
counter in the script now uses `n=$((n + 1))`.

## Security

- Nginx rate limiting (API: 10r/s, Auth: 3r/s, General: 30r/s)
- SSL/TLS with Let's Encrypt
- JWT authentication with token revocation via Redis blacklist
- Role-based access control (Admin, Operator, Readonly)
- Non-root Docker containers with dropped capabilities
- Internal Docker network for database isolation
- Admin panel output is escaped by construction: markup is built with a
  tagged template that escapes every interpolation, and `innerHTML` has a
  single writer that rejects unescaped strings. See
  [CONTRIBUTING.md](CONTRIBUTING.md#rendering-html-in-the-admin-panel).

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

BSD 3-Clause License - see [LICENSE](LICENSE) for details.
