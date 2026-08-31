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

3. Start the services:
   ```bash
   docker compose up -d --build
   ```

4. Access the services:
   - **Web UI**: https://your-domain.com
   - **Admin Panel**: https://your-domain.com/admin
   - **rsync**: rsync://your-domain.com/

   Admin credentials are displayed during setup and saved to `.credentials`.

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

A mirror stuck in `SYNCING` — the unrecoverable case in `backend/app/api/admin.py`
— is caught for free here: its `last_sync_completed` stops advancing, so it goes
stale like any other.

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
