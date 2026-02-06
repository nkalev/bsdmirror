# BSD Mirror Website

A comprehensive mirror website for FreeBSD, NetBSD, and OpenBSD with web UI and admin panel.

## Features

- **Multi-BSD Support**: Mirror FreeBSD, NetBSD, and OpenBSD distributions
- **Web UI**: Beautiful file browser with search and statistics
- **Admin Panel**: Manage mirrors, sync schedules, users, and settings
- **Multiple Protocols**: HTTP/HTTPS and rsync access
- **Security First**: Rate limiting, Fail2Ban, SSL/TLS, JWT authentication
- **Docker Ready**: Easy deployment with Docker Compose

## Quick Start

### Prerequisites

- Ubuntu 22.04+ or similar Linux distribution
- Docker 24+ and Docker Compose v2
- At least 4TB storage (for full mirrors)
- Domain name with DNS configured

### Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/bsdmirrors.git
cd bsdmirrors
```

2. Copy and configure environment:
```bash
cp .env.example .env
# Edit .env with your settings
```

3. Start the services:
```bash
docker compose up -d
```

4. Access the services:
- Web UI: https://your-domain.com
- Admin Panel: https://your-domain.com/admin
- rsync: rsync://your-domain.com/

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Nginx                                 │
│              (Reverse Proxy + File Serving)                  │
└─────────────────────┬───────────────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        │             │             │
   ┌────▼────┐  ┌─────▼─────┐  ┌───▼───┐
   │ Backend │  │  Web UI   │  │ rsync │
   │ (API)   │  │           │  │       │
   └────┬────┘  └───────────┘  └───────┘
        │
   ┌────┴────┐
   │ PostgreSQL │ Redis │
   └─────────────────────┘
```

## Directory Structure

```
/data/mirrors/
├── freebsd/pub/FreeBSD/
├── netbsd/pub/NetBSD/
└── openbsd/pub/OpenBSD/
```

## Configuration

See [docs/configuration.md](docs/configuration.md) for detailed configuration options.

## Security

- UFW firewall configuration included
- Fail2Ban jails for SSH and web services
- Nginx rate limiting
- SSL/TLS with Let's Encrypt
- JWT-based authentication for admin panel

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## License

BSD 3-Clause License - see [LICENSE](LICENSE) for details.
