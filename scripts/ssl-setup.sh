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
COMPOSE_FILE="$INSTALL_DIR/docker-compose.yml"

# Load environment
if [[ -f "$INSTALL_DIR/.env" ]]; then
    source "$INSTALL_DIR/.env"
else
    log_error ".env file not found at $INSTALL_DIR/.env"
    exit 1
fi

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

# Step 1: Switch to bootstrap nginx config (HTTP only)
log_info "Step 1: Switching to HTTP-only mode for certificate acquisition..."

cd "$INSTALL_DIR"

# Stop nginx if running
docker compose stop nginx 2>/dev/null || true

# Use bootstrap config
cp nginx/sites/bootstrap.conf nginx/sites/default.conf.bak 2>/dev/null || true
cp nginx/sites/bootstrap.conf nginx/sites/active.conf

# Update domain in bootstrap config
sed -i "s/server_name _;/server_name $DOMAIN;/g" nginx/sites/active.conf

# Create docker-compose override for bootstrap
cat > docker-compose.bootstrap.yml << EOF
services:
  nginx:
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/sites/active.conf:/etc/nginx/sites-enabled/default.conf:ro
      - ./frontend/public:/var/www/public:ro
      - \${MIRROR_DATA_PATH:-/data/mirrors}:/data/mirrors:ro
      - certbot-webroot:/var/www/certbot:ro
EOF

# Start nginx in bootstrap mode
log_info "Starting nginx in HTTP-only mode..."
docker compose -f docker-compose.yml -f docker-compose.bootstrap.yml up -d nginx

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

# Run certbot
docker compose run --rm certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
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

# Step 3: Update nginx config with your domain
log_info "Step 3: Configuring nginx with SSL..."

# Restore the SSL-enabled config
if [[ -f "nginx/sites/default.conf.original" ]]; then
    cp nginx/sites/default.conf.original nginx/sites/active.conf
else
    cp nginx/sites/default.conf nginx/sites/active.conf
fi

# Update domain in config
sed -i "s/mirror.example.com/$DOMAIN/g" nginx/sites/active.conf

# Stop bootstrap mode
docker compose -f docker-compose.yml -f docker-compose.bootstrap.yml down nginx

# Step 4: Start with full SSL config
log_info "Step 4: Starting nginx with SSL enabled..."

# Create SSL compose override
cat > docker-compose.ssl.yml << EOF
services:
  nginx:
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/sites/active.conf:/etc/nginx/sites-enabled/default.conf:ro
      - ./frontend/public:/var/www/public:ro
      - \${MIRROR_DATA_PATH:-/data/mirrors}:/data/mirrors:ro
      - certbot-webroot:/var/www/certbot:ro
      - certbot-certs:/etc/letsencrypt:ro
EOF

docker compose -f docker-compose.yml -f docker-compose.ssl.yml up -d nginx

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

# Create renewal script
cat > /etc/cron.d/certbot-renew << EOF
# Renew Let's Encrypt certificates twice daily
0 0,12 * * * root cd $INSTALL_DIR && docker compose run --rm certbot renew --quiet && docker compose exec nginx nginx -s reload
EOF

log_info "Certificate auto-renewal configured"

# Cleanup
rm -f docker-compose.bootstrap.yml
rm -f nginx/sites/default.conf.bak

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
    log_warn "  2. Run: docker compose run --rm certbot delete --cert-name $DOMAIN"
    log_warn "  3. Run this script again: ./scripts/ssl-setup.sh"
fi
echo
