#!/bin/bash
# BSD Mirrors - Backup Script
# Backs up database and configuration

set -euo pipefail

# Configuration
BACKUP_DIR="${BACKUP_DIR:-/opt/bsdmirror/backups}"
INSTALL_DIR="${INSTALL_DIR:-/opt/bsdmirror}"
KEEP_DAYS="${KEEP_DAYS:-7}"

# Ensure backup directory exists
mkdir -p "$BACKUP_DIR"

# Timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

echo "BSD Mirrors Backup - $TIMESTAMP"
echo "================================"

# Backup PostgreSQL database
echo "Backing up database..."
docker exec bsdmirrors-postgres pg_dump -U bsdmirrors bsdmirrors | gzip > "$BACKUP_DIR/db_$TIMESTAMP.sql.gz"
echo "✓ Database backup: db_$TIMESTAMP.sql.gz"

# Backup environment file
echo "Backing up configuration..."
cp "$INSTALL_DIR/.env" "$BACKUP_DIR/env_$TIMESTAMP.backup"
echo "✓ Environment backup: env_$TIMESTAMP.backup"

# Backup nginx configuration
if [[ -d "$INSTALL_DIR/nginx" ]]; then
    tar -czf "$BACKUP_DIR/nginx_$TIMESTAMP.tar.gz" -C "$INSTALL_DIR" nginx/
    echo "✓ Nginx backup: nginx_$TIMESTAMP.tar.gz"
fi

# Clean old backups
echo "Cleaning backups older than $KEEP_DAYS days..."
find "$BACKUP_DIR" -type f -mtime +$KEEP_DAYS -delete
echo "✓ Cleanup complete"

# List current backups
echo ""
echo "Current backups:"
ls -lh "$BACKUP_DIR"

echo ""
echo "Backup completed successfully!"
