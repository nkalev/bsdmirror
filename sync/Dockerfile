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

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY --chown=syncuser:syncgroup . .

# Switch to non-root user
USER syncuser

# Health check
HEALTHCHECK --interval=60s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

CMD ["python", "-m", "sync_service"]
