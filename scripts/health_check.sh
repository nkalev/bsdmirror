#!/bin/bash
# BSD Mirrors - Health Check Script
# Run periodically to check mirror health

set -euo pipefail

# Configuration
API_URL="${API_URL:-http://localhost:8000}"
SLACK_WEBHOOK="${SLACK_WEBHOOK:-}"
EMAIL_RECIPIENT="${EMAIL_RECIPIENT:-}"

# Check health endpoint
check_health() {
    local response
    response=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/api/health" 2>/dev/null || echo "000")
    
    if [[ "$response" == "200" ]]; then
        echo "✓ API is healthy"
        return 0
    else
        echo "✗ API health check failed (HTTP $response)"
        return 1
    fi
}

# Check mirror sync status
check_mirrors() {
    local data
    data=$(curl -s "$API_URL/api/stats/health" 2>/dev/null || echo '{"status":"error"}')
    
    local status
    status=$(echo "$data" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
    
    if [[ "$status" == "healthy" ]]; then
        echo "✓ All mirrors are healthy"
        return 0
    elif [[ "$status" == "updating" ]]; then
        echo "⟳ Mirrors are syncing"
        return 0
    else
        echo "✗ Mirror status: $status"
        return 1
    fi
}

# Check disk space
check_disk() {
    local usage
    usage=$(df /data/mirrors 2>/dev/null | tail -1 | awk '{print $5}' | tr -d '%' || echo "0")
    
    if [[ "$usage" -lt 85 ]]; then
        echo "✓ Disk usage: ${usage}%"
        return 0
    elif [[ "$usage" -lt 95 ]]; then
        echo "⚠ Disk usage warning: ${usage}%"
        return 0
    else
        echo "✗ Disk usage critical: ${usage}%"
        return 1
    fi
}

# Check Docker containers
check_containers() {
    local unhealthy
    unhealthy=$(docker ps --filter "health=unhealthy" --format "{{.Names}}" 2>/dev/null | grep bsdmirrors || true)
    
    if [[ -z "$unhealthy" ]]; then
        echo "✓ All containers are healthy"
        return 0
    else
        echo "✗ Unhealthy containers: $unhealthy"
        return 1
    fi
}

# Send alert
send_alert() {
    local message="$1"
    
    # Slack webhook
    if [[ -n "$SLACK_WEBHOOK" ]]; then
        curl -s -X POST -H 'Content-type: application/json' \
            --data "{\"text\":\"🚨 BSD Mirror Alert: $message\"}" \
            "$SLACK_WEBHOOK" >/dev/null 2>&1 || true
    fi
    
    # Email (requires mailx)
    if [[ -n "$EMAIL_RECIPIENT" ]] && command -v mailx &>/dev/null; then
        echo "$message" | mailx -s "BSD Mirror Alert" "$EMAIL_RECIPIENT" || true
    fi
}

# Main
main() {
    echo "BSD Mirrors Health Check - $(date)"
    echo "================================"
    
    local errors=0
    
    check_health || ((errors++))
    check_mirrors || ((errors++))
    check_disk || ((errors++))
    check_containers || ((errors++))
    
    echo "================================"
    
    if [[ "$errors" -gt 0 ]]; then
        echo "Health check completed with $errors error(s)"
        send_alert "Health check failed with $errors error(s)"
        exit 1
    else
        echo "All checks passed"
        exit 0
    fi
}

main "$@"
