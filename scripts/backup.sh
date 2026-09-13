#!/bin/bash
# BSD Mirrors - Backup Script
# Backs up database and configuration

set -euo pipefail

# Configuration
#
# A backup is a full pg_dump plus a copy of .env -- every secret this
# deployment has -- so the default location is OUTSIDE the git working tree.
# It used to be /opt/bsdmirror/backups, inside the checkout of a public
# repository, where only .gitignore stood between it and a careless commit.
BACKUP_DIR="${BACKUP_DIR:-/var/backups/bsdmirror}"
INSTALL_DIR="${INSTALL_DIR:-/opt/bsdmirror}"
KEEP_DAYS="${KEEP_DAYS:-7}"

# Restrict file permissions for all created files
umask 077

# The cleanup below deletes files, so refuse any location it must never prune:
# the filesystem root, or the checkout itself or anything under it.
backup_real=$(realpath -m -- "$BACKUP_DIR")
install_real=$(realpath -m -- "$INSTALL_DIR")
case "$backup_real" in
    /|"$install_real"|"$install_real"/*)
        echo "Refusing BACKUP_DIR=$BACKUP_DIR: use a dedicated directory outside $INSTALL_DIR" >&2
        exit 2
        ;;
esac

# Ensure backup directory exists and stays private
mkdir -p "$BACKUP_DIR"
chmod 0700 "$BACKUP_DIR"

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

# Clean old backups: only the three kinds of file this script writes, never
# anything else kept in BACKUP_DIR (a hand-made dump, for example).
echo "Cleaning backups older than $KEEP_DAYS days..."
# KEEP_DAYS comes from the environment ("${KEEP_DAYS:-7}"), so quote it:
# an unquoted value word-splits into extra find predicates, and this
# line ends in -delete.
find "$BACKUP_DIR" -maxdepth 1 -type f \
    \( -name 'db_*.sql.gz' -o -name 'env_*.backup' -o -name 'nginx_*.tar.gz' \) \
    -mtime "+$KEEP_DAYS" -delete
echo "✓ Cleanup complete"

# List current backups
echo ""
echo "Current backups:"
ls -lh "$BACKUP_DIR"

echo ""
echo "Backup completed successfully!"
