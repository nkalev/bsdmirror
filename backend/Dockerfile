# BSD Mirrors Backend API

FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Create non-root user for security
RUN groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# EVERY COPY SOURCE BELOW IS RELATIVE TO THE REPO ROOT, NOT TO backend/.
# ---------------------------------------------------------------------------
# docker-compose.yml builds this with `context: .` so that backend/ and sync/
# share one models package, shared/ (they used to declare the same tables twice
# by hand, and drifted once -- 798ae79). `COPY requirements.txt` would now
# resolve to the repo root and fail the build; that is the good failure. The
# dangerous one is `COPY . .`, which from a root context would ship .env,
# .credentials, .git, tests/, frontend/ and the data/ symlink into a layer.
#
# So every COPY here is scoped to a named subtree. That is a structural
# guarantee, independent of .dockerignore: nothing outside backend/ can enter
# this image, whatever the ignore file says. Keep it that way.
#
# The shared models package has landed: the `COPY shared/ ./shared` below is
# that one scoped line, and `!shared` is in the root .dockerignore.

# Requirements first, for layer caching: this layer is rebuilt only when the
# pins change, not on every source edit.
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Build identity: which commit, and when.
# ---------------------------------------------------------------------------
# The only way to answer "what is deployed?" used to be SSH plus `git
# rev-parse`, or guessing from container uptime -- frontend/public/index.html
# hardcoded v1.0.1, config.py hardcoded VERSION = "1.0.0", and neither had ever
# changed, so a deploy could not be told apart from the last one. Settings in
# app/core/config.py reads GIT_SHA/BUILD_DATE from the environment at runtime,
# the same way it reads every other setting; ENV (not just ARG) is what makes
# that value visible past this build into the running container.
#
# AFTER the pip install above, deliberately. These two build args change on
# every commit, and any ARG/ENV invalidates every layer that follows it in the
# image -- ahead of the install, a one-line source edit would re-resolve and
# re-download the entire dependency set on every single deploy. Verified by
# building at two different SHAs and comparing the pip layer's cache ID, not
# assumed; see the PR description.
#
# The defaults are the other half of the design: nobody runs `docker build` by
# hand with --build-arg GIT_SHA=..., so whatever this reports then must not be
# mistakable for a real build. "unknown" cannot be; "0000000" or "0.0.0" could
# be mistaken for a real, just-wrong one, which is the exact failure mode this
# whole change exists to remove. docker-compose.yml wires the real value
# through as ${GIT_SHA:-unknown}, and scripts/deploy.sh's build_images() sets
# it to the short SHA it is actually deploying -- deploy.sh already resolved
# that SHA for the CI gate, so this reads it rather than recomputing it, which
# is exactly how the two hardcoded strings above went out of step in the first
# place.
ARG GIT_SHA=unknown
ARG BUILD_DATE=unknown
ENV GIT_SHA=${GIT_SHA} \
    BUILD_DATE=${BUILD_DATE}

# Application code. `backend/` with the trailing slash copies the CONTENTS of
# that directory into /app, which is what the old `COPY . .` from a ./backend
# context did -- the image layout is unchanged. backend/Dockerfile and
# backend/.dockerignore are excluded by the root .dockerignore.
COPY --chown=appuser:appgroup backend/ .

# The schema, shared with the sync image. `import shared.models` resolves
# because uvicorn puts its --app-dir (default ".") on sys.path and WORKDIR is
# /app. Trailing-slash form again: shared/ -> /app/shared/, keeping the package
# name importable rather than dumping its contents into /app.
COPY --chown=appuser:appgroup shared/ ./shared

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
