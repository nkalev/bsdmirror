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
├── backend/          # FastAPI backend API
│   ├── app/
│   │   ├── api/      # API route handlers
│   │   ├── core/     # Configuration, security, database
│   │   └── models/   # SQLAlchemy models
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

### Key Technologies

- **Backend**: Python, FastAPI, SQLAlchemy (async), PostgreSQL
- **Frontend**: Vanilla JavaScript (no framework), CSS
- **Sync Service**: Python, asyncio, rsync
- **Infrastructure**: Docker, Nginx, Redis, PostgreSQL

## Code Style

- Python: Follow PEP 8 conventions
- JavaScript: Use modern ES6+ syntax
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
