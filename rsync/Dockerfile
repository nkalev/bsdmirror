# Rsync Server for BSD Mirrors

FROM alpine:3.19

# Install rsync
RUN apk add --no-cache rsync

# Create rsync user
RUN adduser -D -H rsync

# Create directories
RUN mkdir -p /data/mirrors && chown rsync:rsync /data/mirrors

# Copy configuration
COPY rsyncd.conf /etc/rsyncd.conf

# Expose rsync port
EXPOSE 873

# Run rsync daemon
CMD ["rsync", "--daemon", "--no-detach", "--config=/etc/rsyncd.conf"]
