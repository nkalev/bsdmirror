# Rsync Server for BSD Mirrors

FROM debian:bookworm-slim

# Install rsync
RUN apt-get update && apt-get install -y --no-install-recommends rsync && \
    rm -rf /var/lib/apt/lists/*

# Create rsync user
RUN useradd --system --no-create-home rsync

# Create directories
RUN mkdir -p /data/mirrors && chown rsync:rsync /data/mirrors

# Copy configuration
COPY rsyncd.conf /etc/rsyncd.conf

# Expose rsync port
EXPOSE 873

# Run rsync daemon
CMD ["rsync", "--daemon", "--no-detach", "--config=/etc/rsyncd.conf"]
