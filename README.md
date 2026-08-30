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
| `FREEBSD_UPSTREAM` | FreeBSD rsync upstream URL | `rsync://ftp.freebsd.org/FreeBSD/` |
| `NETBSD_UPSTREAM` | NetBSD rsync upstream URL | `rsync://rsync.NetBSD.org/NetBSD/` |
| `OPENBSD_UPSTREAM` | OpenBSD rsync upstream URL | `rsync://ftp2.eu.openbsd.org/OpenBSD/` |
| `SYNC_SCHEDULE` | Cron schedule for sync | `0 4 * * *` |
| `SYNC_BANDWIDTH_LIMIT` | Rsync bandwidth limit (KB/s, 0=unlimited) | `0` |
| `MIRROR_DATA_PATH` | Local path for mirror data | `/data/mirrors` |
| `LOG_LEVEL` | Log level for the backend and sync services (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |

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

## Security

- Nginx rate limiting (API: 10r/s, Auth: 3r/s, General: 30r/s)
- SSL/TLS with Let's Encrypt
- JWT authentication with token revocation via Redis blacklist
- Role-based access control (Admin, Operator, Readonly)
- Non-root Docker containers with dropped capabilities
- Internal Docker network for database isolation

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

BSD 3-Clause License - see [LICENSE](LICENSE) for details.
