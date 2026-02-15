#!/bin/bash
# BSD Mirrors - Setup Script
# Usage: ./setup.sh [--mode dev|production] [--domain DOMAIN] [--email EMAIL]

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ===========================================
# Parse Arguments
# ===========================================
MODE=""
DOMAIN="${DOMAIN:-}"
ADMIN_EMAIL="${ADMIN_EMAIL:-}"
CLEAN=false

usage() {
    echo "Usage: $0 --mode <dev|production> [--domain DOMAIN] [--email EMAIL] [--clean]"
    echo
    echo "Arguments:"
    echo "  --mode dev          Development setup (HTTP only, no SSL, no firewall)"
    echo "  --mode production   Production setup (SSL, firewall, fail2ban)"
    echo "  --domain DOMAIN     Domain name (required for production, optional for dev)"
    echo "  --email EMAIL       Admin email (required for production SSL)"
    echo "  --clean             Remove existing Docker volumes (fresh database/redis)"
    echo
    echo "Examples:"
    echo "  $0 --mode dev"
    echo "  $0 --mode production --domain mirror.example.com --email admin@example.com"
    echo "  $0 --mode production --domain mirror.example.com --email admin@example.com --clean"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --mode)
            MODE="$2"
            shift 2
            ;;
        --domain)
            DOMAIN="$2"
            shift 2
            ;;
        --email)
            ADMIN_EMAIL="$2"
            shift 2
            ;;
        --clean)
            CLEAN=true
            shift
            ;;
        --help|-h)
            usage
            ;;
        *)
            log_error "Unknown argument: $1"
            usage
            ;;
    esac
done

# Validate mode
if [[ -z "$MODE" ]]; then
    log_error "Missing required --mode argument"
    usage
fi

if [[ "$MODE" != "dev" && "$MODE" != "production" ]]; then
    log_error "Invalid mode: $MODE (must be 'dev' or 'production')"
    usage
fi

# Production requires domain and email
if [[ "$MODE" == "production" ]]; then
    if [[ -z "$DOMAIN" ]]; then
        read -p "Enter your domain name (e.g., mirror.example.com): " DOMAIN
    fi
    if [[ -z "$ADMIN_EMAIL" ]]; then
        read -p "Enter admin email for SSL certificates: " ADMIN_EMAIL
    fi
    if [[ -z "$DOMAIN" || -z "$ADMIN_EMAIL" ]]; then
        log_error "Domain and email are required for production mode"
        exit 1
    fi
fi

# Dev defaults
if [[ "$MODE" == "dev" ]]; then
    DOMAIN="${DOMAIN:-localhost}"
    ADMIN_EMAIL="${ADMIN_EMAIL:-admin@localhost}"
fi

# Check if running as root (required for production, optional for dev)
if [[ "$MODE" == "production" && $EUID -ne 0 ]]; then
    log_error "Production setup must be run as root"
    exit 1
fi

echo "========================================="
echo "  BSD Mirrors Server Setup ($MODE)"
echo "========================================="
echo

log_info "Mode: $MODE"
log_info "Domain: $DOMAIN"
if [[ "$MODE" == "production" ]]; then
    log_info "Email: $ADMIN_EMAIL"
fi
echo

# Variables
INSTALL_DIR="${INSTALL_DIR:-/opt/bsdmirror}"
DATA_DIR="${DATA_DIR:-/data/mirrors}"

if [[ "$MODE" == "dev" ]]; then
    INSTALL_DIR="${INSTALL_DIR:-$(pwd)}"
    DATA_DIR="${DATA_DIR:-$(pwd)/data/mirrors}"
fi

# ===========================================
# System Updates (production only)
# ===========================================
if [[ "$MODE" == "production" ]]; then
    log_info "Updating system packages..."
    apt-get update
    apt-get upgrade -y
fi

# ===========================================
# Install Dependencies (production only)
# ===========================================
if [[ "$MODE" == "production" ]]; then
    log_info "Installing required packages..."
    apt-get install -y \
        apt-transport-https \
        ca-certificates \
        curl \
        gnupg \
        lsb-release \
        ufw \
        fail2ban \
        rsync \
        htop \
        iotop \
        ncdu
fi

# ===========================================
# Install Docker
# ===========================================
install_docker() {
    # Add Docker's official GPG key
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    # Add the Docker repository
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null

    # Update package index
    apt-get update

    # Install Docker Engine and Compose plugin
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    # Enable Docker service
    systemctl enable docker
    systemctl start docker
}

if ! command -v docker &> /dev/null; then
    if [[ "$MODE" == "production" ]]; then
        log_info "Installing Docker..."
        install_docker
    else
        log_error "Docker is not installed. Please install Docker and Docker Compose first."
        exit 1
    fi
else
    log_info "Docker already installed"
    # Ensure Docker Compose plugin is installed even if Docker exists
    if ! docker compose version &> /dev/null 2>&1; then
        if [[ "$MODE" == "production" ]]; then
            log_info "Installing Docker Compose plugin..."
            if [[ ! -f /etc/apt/sources.list.d/docker.list ]]; then
                install -m 0755 -d /etc/apt/keyrings
                curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
                chmod a+r /etc/apt/keyrings/docker.gpg
                echo \
                  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
                  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
                  tee /etc/apt/sources.list.d/docker.list > /dev/null
                apt-get update
            fi
            apt-get install -y docker-compose-plugin
        else
            log_error "Docker Compose is not installed. Please install the Docker Compose plugin."
            exit 1
        fi
    fi
fi

# Verify Docker Compose is working
if docker compose version &> /dev/null; then
    log_info "Docker Compose $(docker compose version --short) installed"
else
    log_error "Docker Compose installation failed"
    exit 1
fi

# ===========================================
# Create Directories
# ===========================================
log_info "Creating directories..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$DATA_DIR/freebsd/pub/FreeBSD"
mkdir -p "$DATA_DIR/netbsd/pub/NetBSD"
mkdir -p "$DATA_DIR/openbsd/pub/OpenBSD"
mkdir -p "$INSTALL_DIR/nginx/ssl"

# ===========================================
# Configure Firewall (production only)
# ===========================================
if [[ "$MODE" == "production" ]]; then
    log_info "Configuring firewall..."

    # Reset UFW
    ufw --force reset

    # Default policies
    ufw default deny incoming
    ufw default allow outgoing

    # Allow SSH (with rate limiting)
    ufw limit ssh

    # Allow HTTP and HTTPS
    ufw allow 80/tcp
    ufw allow 443/tcp

    # Allow rsync (optional, comment out if not needed)
    ufw allow 873/tcp

    # Enable UFW
    ufw --force enable

    log_info "Firewall configured"
fi

# ===========================================
# Configure Fail2Ban (production only)
# ===========================================
if [[ "$MODE" == "production" ]]; then
    log_info "Configuring Fail2Ban..."

    cat > /etc/fail2ban/jail.local << 'EOF'
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5
backend = systemd

[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 3600

[nginx-http-auth]
enabled = true
filter = nginx-http-auth
port = http,https
logpath = /var/log/nginx/error.log

[nginx-limit-req]
enabled = true
filter = nginx-limit-req
port = http,https
logpath = /var/log/nginx/error.log
maxretry = 10

[nginx-botsearch]
enabled = true
filter = nginx-botsearch
port = http,https
logpath = /var/log/nginx/access.log
maxretry = 2
EOF

    # Create nginx-limit-req filter if not exists
    cat > /etc/fail2ban/filter.d/nginx-limit-req.conf << 'EOF'
[Definition]
failregex = limiting requests, excess:.* by zone.*client: <HOST>
ignoreregex =
EOF

    # Restart Fail2Ban
    systemctl enable fail2ban
    systemctl restart fail2ban

    log_info "Fail2Ban configured"
fi

# ===========================================
# Clean existing Docker data (if --clean)
# ===========================================
if [[ "$CLEAN" == true ]]; then
    log_warn "Cleaning existing Docker data..."
    cd "$INSTALL_DIR"
    docker compose down -v 2>/dev/null || true
    log_info "Docker volumes removed (fresh database and redis)"
else
    # Warn if volumes already exist with old credentials
    if command -v docker &> /dev/null && docker volume ls -q 2>/dev/null | grep -q "bsdmirrors_postgres-data"; then
        echo
        log_warn "Existing database volume detected!"
        log_warn "If you are re-running setup, the new database password will NOT"
        log_warn "match the password stored in the existing Postgres volume."
        log_warn "Run with --clean to remove old volumes: $0 --mode $MODE --clean"
        echo
    fi
fi

# ===========================================
# Generate Secrets
# ===========================================
log_info "Generating secrets..."

SECRET_KEY=$(openssl rand -hex 32)
POSTGRES_PASSWORD=$(openssl rand -hex 24)
REDIS_PASSWORD=$(openssl rand -hex 24)
ADMIN_PASSWORD=$(openssl rand -hex 12)

# ===========================================
# Create Environment File
# ===========================================
log_info "Creating environment file..."

# Set mode-specific values
if [[ "$MODE" == "dev" ]]; then
    NGINX_SITE_CONF="dev.conf"
    JWT_EXPIRY_HOURS=24
    LETSENCRYPT_ENV="staging"
    DEBUG="true"
    CORS_ORIGINS='["http://localhost:3000","http://localhost:8080","http://localhost"]'
else
    NGINX_SITE_CONF="dev.conf"  # ssl-setup.sh will change this to production.conf
    JWT_EXPIRY_HOURS=8
    LETSENCRYPT_ENV="production"
    DEBUG="false"
    CORS_ORIGINS="[\"https://$DOMAIN\"]"
fi

cat > "$INSTALL_DIR/.env" << EOF
# BSD Mirrors Configuration
# Generated on $(date)
# Mode: $MODE

COMPOSE_PROJECT_NAME=bsdmirrors
DOMAIN=$DOMAIN
ADMIN_EMAIL=$ADMIN_EMAIL

# Nginx
NGINX_SITE_CONF=$NGINX_SITE_CONF

# Database
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=bsdmirrors
POSTGRES_USER=bsdmirrors
POSTGRES_PASSWORD=$POSTGRES_PASSWORD

# Redis
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=$REDIS_PASSWORD

# Backend
API_HOST=0.0.0.0
API_PORT=8000
SECRET_KEY=$SECRET_KEY
JWT_ALGORITHM=HS256
JWT_EXPIRY_HOURS=$JWT_EXPIRY_HOURS
ADMIN_USERNAME=admin
ADMIN_PASSWORD=$ADMIN_PASSWORD
DEBUG=$DEBUG
CORS_ORIGINS=$CORS_ORIGINS

# Mirror paths
MIRROR_DATA_PATH=$DATA_DIR

# FreeBSD
FREEBSD_ENABLED=true
FREEBSD_UPSTREAM=rsync://ftp.freebsd.org/FreeBSD/

# NetBSD
NETBSD_ENABLED=true
NETBSD_UPSTREAM=rsync://ftp.netbsd.org/pub/NetBSD/

# OpenBSD
OPENBSD_ENABLED=true
OPENBSD_UPSTREAM=rsync://ftp.openbsd.org/pub/OpenBSD/

# Sync
SYNC_SCHEDULE=0 4 * * *
SYNC_BANDWIDTH_LIMIT=0

# rsync server
RSYNC_ENABLED=true
RSYNC_PORT=873
RSYNC_MAX_CONNECTIONS=50

# SSL
LETSENCRYPT_EMAIL=$ADMIN_EMAIL
LETSENCRYPT_ENV=$LETSENCRYPT_ENV

# Logging
LOG_LEVEL=INFO
EOF

chmod 600 "$INSTALL_DIR/.env"

# ===========================================
# Save Credentials
# ===========================================
CREDS_FILE="$INSTALL_DIR/.credentials"
cat > "$CREDS_FILE" << EOF
# BSD Mirrors Credentials
# KEEP THIS FILE SAFE AND DELETE AFTER NOTING CREDENTIALS

Admin Username: admin
Admin Password: $ADMIN_PASSWORD

Database Password: $POSTGRES_PASSWORD
Redis Password: $REDIS_PASSWORD
Secret Key: $SECRET_KEY

Generated: $(date)
EOF
chmod 600 "$CREDS_FILE"

# Make scripts executable
chmod +x "$INSTALL_DIR/scripts/"*.sh 2>/dev/null || true

# ===========================================
# Summary
# ===========================================
echo
echo "========================================="
echo "  Setup Complete! ($MODE mode)"
echo "========================================="
echo
log_info "Installation directory: $INSTALL_DIR"
log_info "Data directory: $DATA_DIR"
log_info "Domain: $DOMAIN"
echo
log_warn "IMPORTANT: Credentials saved to $CREDS_FILE"
log_warn "Please note them down and delete this file!"
echo
echo "Admin Credentials:"
echo "  Username: admin"
echo "  Password: $ADMIN_PASSWORD"
echo

if [[ "$MODE" == "dev" ]]; then
    echo "========================================="
    echo "  NEXT STEPS (Development):"
    echo "========================================="
    echo
    echo "Start all services:"
    echo "  cd $INSTALL_DIR"
    echo "  docker compose up -d"
    echo
    echo "Access:"
    echo "  - Website: http://localhost"
    echo "  - Admin Panel: http://localhost/admin"
    echo "  - API Docs: http://localhost/api/docs"
    echo
else
    echo "========================================="
    echo "  NEXT STEPS (Production):"
    echo "========================================="
    echo
    echo "Step 1: Start the database and backend services:"
    echo "  cd $INSTALL_DIR"
    echo "  docker compose up -d"
    echo
    echo "Step 2: Obtain SSL certificate and switch to production nginx:"
    echo "  ./scripts/ssl-setup.sh"
    echo
    echo "Step 3: (Optional) Enable rsync server for other mirrors:"
    echo "  docker compose --profile rsync up -d"
    echo
    echo "After SSL setup, access:"
    echo "  - Website: https://$DOMAIN"
    echo "  - Admin Panel: https://$DOMAIN/admin"
    echo
    log_warn "Make sure your domain $DOMAIN points to this server's IP before running ssl-setup.sh!"
    echo
fi
