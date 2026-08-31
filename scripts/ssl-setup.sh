#!/bin/bash
# BSD Mirrors - SSL Setup Script
# Run this AFTER initial setup to obtain SSL certificates from Let's Encrypt

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Configuration
INSTALL_DIR="${INSTALL_DIR:-/opt/bsdmirror}"
ENV_FILE="$INSTALL_DIR/.env"

# Load specific variables from .env file safely (handles special chars like cron)
load_env_var() {
    local var_name="$1"
    local value
    value=$(grep "^${var_name}=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2- | head -1)
    echo "$value"
}

# Load environment
if [[ ! -f "$ENV_FILE" ]]; then
    log_error ".env file not found at $ENV_FILE"
    exit 1
fi

DOMAIN=$(load_env_var "DOMAIN")
LETSENCRYPT_EMAIL=$(load_env_var "LETSENCRYPT_EMAIL")
ADMIN_EMAIL=$(load_env_var "ADMIN_EMAIL")
LETSENCRYPT_ENV=$(load_env_var "LETSENCRYPT_ENV")

# Validate required variables
if [[ -z "${DOMAIN:-}" ]]; then
    log_error "DOMAIN not set in .env file"
    exit 1
fi

if [[ -z "${LETSENCRYPT_EMAIL:-}" ]] && [[ -z "${ADMIN_EMAIL:-}" ]]; then
    log_error "LETSENCRYPT_EMAIL or ADMIN_EMAIL not set in .env file"
    exit 1
fi

EMAIL="${LETSENCRYPT_EMAIL:-$ADMIN_EMAIL}"
STAGING="${LETSENCRYPT_ENV:-staging}"

echo "========================================="
echo "  BSD Mirrors - SSL Certificate Setup"
echo "========================================="
echo
log_info "Domain: $DOMAIN"
log_info "Email: $EMAIL"
log_info "Environment: $STAGING"
echo

# Step 1: Start nginx in HTTP-only bootstrap mode for certificate acquisition
log_info "Step 1: Switching to HTTP-only mode for certificate acquisition..."

cd "$INSTALL_DIR"

# Stop nginx if running
docker compose stop nginx 2>/dev/null || true

# Start nginx with bootstrap config (HTTP only, no SSL certs needed)
log_info "Starting nginx in HTTP-only mode..."
# --force-recreate, not a plain `up -d`. Compose only recreates a container when
# its own definition changed, and NGINX_SITE is an interpolation inside a volume
# source: flipping it does change the resolved definition, but a container left
# over from a previous run of this script with the SAME value would be reused
# with whatever mounts it was created with. Recreating makes docker re-resolve
# every bind mount, which is the only way a mount change takes effect.
NGINX_SITE=bootstrap docker compose up -d --force-recreate nginx

# Wait for nginx to be ready
sleep 5

# Verify nginx is running
if ! docker compose ps nginx | grep -q "Up"; then
    log_error "Nginx failed to start. Check logs with: docker compose logs nginx"
    exit 1
fi
log_info "Nginx running in HTTP-only mode"

# Step 2: Obtain SSL certificate
log_info "Step 2: Obtaining SSL certificate from Let's Encrypt..."

# Determine staging flag
STAGING_FLAG=""
if [[ "$STAGING" == "staging" ]]; then
    log_warn "Using Let's Encrypt STAGING environment (certificates won't be trusted)"
    log_warn "Set LETSENCRYPT_ENV=production in .env for production certificates"
    STAGING_FLAG="--staging"
fi

# Delete any existing certificate for this domain to avoid conflicts
# (e.g., switching from staging to production requires removing old cert)
log_info "Removing any existing certificates for $DOMAIN..."
docker compose --profile ssl run --rm certbot delete --cert-name "$DOMAIN" 2>/dev/null || true

# Run certbot.
#
# `if ! cmd; then` rather than running it bare and testing $? afterwards. This
# script sets `set -euo pipefail` (line 5), so a failing certbot exited the
# script immediately and the diagnostic block below was unreachable -- the
# operator got a bare non-zero exit instead of the three things to check.
# A command in an `if` condition is exempt from errexit, which is what makes
# that guidance reachable.
if ! docker compose --profile ssl run --rm certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    --force-renewal \
    $STAGING_FLAG \
    -d "$DOMAIN"; then
    log_error "Failed to obtain SSL certificate"
    log_error "Make sure:"
    log_error "  1. Your domain $DOMAIN points to this server's IP"
    log_error "  2. Port 80 is open and accessible from the internet"
    log_error "  3. No other service is using port 80"
    exit 1
fi

log_info "SSL certificate obtained successfully!"

# Step 3: Point .env at the production site config
log_info "Step 3: Configuring nginx with SSL..."

# This step used to do:
#     cp nginx/sites/default.conf nginx/sites/production.conf
#     sed -i "s/mirror.example.com/$DOMAIN/g" nginx/sites/production.conf
#
# That made the file which actually served production untracked. git could not
# update it, so every nginx change committed after February reached the server
# and stopped there; CI could only validate a fresh re-creation of it, never the
# copy on disk; and by 2026-08-31 the real file had 5 add_header directives
# against default.conf's 21, with nothing anywhere reporting the difference.
#
# nginx/sites/production/production.conf is now tracked and contains no domain.
# The only domain-dependent lines left are the two certificate paths, which
# scripts/nginx-apply.sh renders into nginx/snippets/tls-cert.conf.
"$INSTALL_DIR/scripts/nginx-apply.sh" render

# Step 4: Update .env to use the production site and restart nginx with SSL
log_info "Step 4: Starting nginx with SSL enabled..."

# NGINX_SITE replaces NGINX_SITE_CONF. The old variable named a FILE under
# nginx/sites/; the new one names a DIRECTORY there, because docker-compose.yml
# now mounts that directory at /etc/nginx/sites-enabled rather than bind-mounting
# an individual file (which pinned an inode and stopped config changes reaching
# the container at all). Remove the retired key so a stale value cannot be read
# by anything that has not been updated.
sed -i "/^NGINX_SITE_CONF=/d" "$ENV_FILE"
if grep -q "^NGINX_SITE=" "$ENV_FILE"; then
    sed -i "s/^NGINX_SITE=.*/NGINX_SITE=production/" "$ENV_FILE"
else
    echo "NGINX_SITE=production" >> "$ENV_FILE"
fi

# Legacy artifact from the cp+sed above. Left in place it is inert -- nothing
# mounts it any more -- but it looks like the live config, which is how the
# 2026-08-31 outage stayed invisible for six months.
if [[ -f nginx/sites/production.conf ]]; then
    log_warn "Removing the obsolete generated nginx/sites/production.conf"
    rm -f nginx/sites/production.conf
fi

# --force-recreate so docker re-resolves the bind mounts against the new
# NGINX_SITE. `docker compose up -d` alone would reuse a running container.
docker compose up -d --force-recreate nginx

sleep 5

# Prove the container is serving THIS checkout before believing anything else.
if ! "$INSTALL_DIR/scripts/nginx-apply.sh" check; then
    log_error "nginx is running but is not serving the config in $INSTALL_DIR."
    exit 1
fi

# Verify HTTPS is working
if curl -sSf "https://$DOMAIN/health" > /dev/null 2>&1; then
    log_info "SSL is working! Site accessible at https://$DOMAIN"
elif curl -sSfk "https://$DOMAIN/health" > /dev/null 2>&1; then
    log_warn "SSL working (staging certificate - not trusted by browsers)"
    log_warn "Run with LETSENCRYPT_ENV=production when ready for production"
else
    log_warn "Could not verify HTTPS. Check: docker compose logs nginx"
fi

# Step 5: Set up auto-renewal
log_info "Step 5: Setting up certificate auto-renewal..."

cat > /etc/cron.d/certbot-renew << EOF
# Renew Let's Encrypt certificates twice daily
# nginx-apply.sh, not a bare "nginx -s reload". The old line reloaded without
# ever running "nginx -t", so a renewal that landed next to a broken config
# would have taken the site down at midnight with no operator present. It also
# could not tell a reload that picked up the new certificate from one that
# re-read a stale file, which is the failure this repo shipped on 2026-08-31.
0 0,12 * * * root cd $INSTALL_DIR && docker compose --profile ssl run --rm certbot renew --quiet && $INSTALL_DIR/scripts/nginx-apply.sh reload
EOF

log_info "Certificate auto-renewal configured"

echo
echo "========================================="
echo "  SSL Setup Complete!"
echo "========================================="
echo
log_info "Your site is now available at: https://$DOMAIN"
log_info "Admin panel: https://$DOMAIN/admin"
echo
if [[ "$STAGING" == "staging" ]]; then
    log_warn "You are using staging certificates (not trusted)."
    log_warn "To switch to production certificates:"
    log_warn "  1. Edit .env and set LETSENCRYPT_ENV=production"
    log_warn "  2. Run: docker compose --profile ssl run --rm certbot delete --cert-name $DOMAIN"
    log_warn "  3. Run this script again: ./scripts/ssl-setup.sh"
fi
echo
