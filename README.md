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

Upstream URLs can also be changed from the admin panel without restarting services.

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
