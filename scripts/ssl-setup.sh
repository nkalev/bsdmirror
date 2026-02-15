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
NGINX_SITE_CONF=bootstrap.conf docker compose up -d nginx

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

# Run certbot
docker compose --profile ssl run --rm certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    --force-renewal \
    $STAGING_FLAG \
    -d "$DOMAIN"

if [[ $? -ne 0 ]]; then
    log_error "Failed to obtain SSL certificate"
    log_error "Make sure:"
    log_error "  1. Your domain $DOMAIN points to this server's IP"
    log_error "  2. Port 80 is open and accessible from the internet"
    log_error "  3. No other service is using port 80"
    exit 1
fi

log_info "SSL certificate obtained successfully!"

# Step 3: Create production SSL config with the correct domain
log_info "Step 3: Configuring nginx with SSL..."

# Escape domain for safe use in sed
ESCAPED_DOMAIN=$(printf '%s\n' "$DOMAIN" | sed 's/[&/\]/\\&/g')

# Copy default.conf to production.conf and substitute domain
cp nginx/sites/default.conf nginx/sites/production.conf
sed -i "s/mirror.example.com/$ESCAPED_DOMAIN/g" nginx/sites/production.conf

# Step 4: Update .env to use production config and restart nginx with SSL
log_info "Step 4: Starting nginx with SSL enabled..."

# Stop bootstrap nginx
docker compose stop nginx

# Update NGINX_SITE_CONF in .env to use production config
if grep -q "^NGINX_SITE_CONF=" "$ENV_FILE"; then
    sed -i "s/^NGINX_SITE_CONF=.*/NGINX_SITE_CONF=production.conf/" "$ENV_FILE"
else
    echo "NGINX_SITE_CONF=production.conf" >> "$ENV_FILE"
fi

# Start with production SSL config
docker compose up -d nginx

sleep 5

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
0 0,12 * * * root cd $INSTALL_DIR && docker compose --profile ssl run --rm certbot renew --quiet && docker compose exec nginx nginx -s reload
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
