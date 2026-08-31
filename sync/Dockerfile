# BSD Mirrors Sync Service

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Create non-root user
RUN groupadd --gid 1000 syncgroup && \
    useradd --uid 1000 --gid syncgroup --shell /bin/bash --create-home syncuser

WORKDIR /app

# Install rsync and other dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    rsync \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# EVERY COPY SOURCE BELOW IS RELATIVE TO THE REPO ROOT, NOT TO sync/.
# ---------------------------------------------------------------------------
# docker-compose.yml builds this with `context: .` so this image and the backend
# image can share one models package. See the longer note in backend/Dockerfile;
# the rule is the same here: scope every COPY to a named subtree, never `COPY .`,
# because the root of this context holds .env, .credentials, .git and the data/
# symlink.
#
# When the shared models package lands:
#     COPY --chown=syncuser:syncgroup shared/ ./shared
# and `!shared` in the root .dockerignore. sync/sync_service.py:452-512 then
# stops redeclaring Mirror, SyncJob, Setting and both enums by hand.

COPY sync/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Contents of sync/ into /app, exactly as the old ./sync context produced.
COPY --chown=syncuser:syncgroup sync/ .

# Switch to non-root user
USER syncuser

# Health check
HEALTHCHECK --interval=60s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

CMD ["python", "-m", "sync_service"]
