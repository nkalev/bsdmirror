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
# can share one models package (they currently declare the same tables twice by
# hand, and drifted once -- 798ae79). `COPY requirements.txt` would now resolve
# to the repo root and fail the build; that is the good failure. The dangerous
# one is `COPY . .`, which from a root context would ship .env, .credentials,
# .git, tests/, frontend/ and the data/ symlink into a layer.
#
# So every COPY here is scoped to a named subtree. That is a structural
# guarantee, independent of .dockerignore: nothing outside backend/ can enter
# this image, whatever the ignore file says. Keep it that way.
#
# When the shared models package lands, it is ONE more scoped line here --
#     COPY --chown=appuser:appgroup shared/ ./shared
# -- plus `!shared` in the root .dockerignore. Nothing else changes.

# Requirements first, for layer caching: this layer is rebuilt only when the
# pins change, not on every source edit.
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code. `backend/` with the trailing slash copies the CONTENTS of
# that directory into /app, which is what the old `COPY . .` from a ./backend
# context did -- the image layout is unchanged. backend/Dockerfile and
# backend/.dockerignore are excluded by the root .dockerignore.
COPY --chown=appuser:appgroup backend/ .

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
