#!/usr/bin/env bash
#
# bsdmirror - install the health-check systemd timer
#
# Why this exists
# ---------------
# scripts/health_check.sh has been in this repo since the beginning and has
# never once been executed by anything. That is the entire reason the OpenBSD
# mirror could fail 58 consecutive nights unnoticed. A checker nobody schedules
# is a comment.
#
# Why a systemd timer rather than a cron entry
# --------------------------------------------
# There is precedent for cron here: scripts/ssl-setup.sh:164 writes
# /etc/cron.d/certbot-renew. That is the right call for certbot -- fire and
# forget, and certbot's own failure is visible the next time a browser loads
# the site. Alerting is the opposite: its failures are invisible by
# construction, so the scheduler itself has to be observable.
#
#   systemctl list-timers bsdmirror-health.timer   next run, last run, and
#                                                  how long ago -- a crontab
#                                                  line tells you none of that
#   journalctl -u bsdmirror-health                 every past run's full output
#                                                  with its exit status; cron
#                                                  mails root, which on this
#                                                  host goes nowhere
#   systemctl status bsdmirror-health              the last exit code
#   Persistent=true                                a run missed while the host
#                                                  was down is executed on the
#                                                  next boot. cron silently
#                                                  skips it -- and "silently
#                                                  skipped" is the bug
#   Environment / EnvironmentFile                  cron invites you to inline
#                                                  the webhook URL into the
#                                                  crontab, where it is world
#                                                  readable and shows up in ps
#
# It would be a poor joke to make the alerting itself unobservable.
#
# Usage
# -----
#   sudo scripts/install-health-timer.sh                 install and enable
#   sudo scripts/install-health-timer.sh --dry-run       print, change nothing
#   sudo scripts/install-health-timer.sh --uninstall     stop, disable, remove
#   scripts/install-health-timer.sh --help
#
# Idempotent: running it twice is a no-op the second time, and it reports
# which files it left alone.
#
# Exit codes:
#   0  installed (or already installed, or removed)
#   1  usage error / not root / systemd not present
#   2  refused: prerequisites missing, or no alert channel configured
#
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/bsdmirror}"
UNIT_DIR="${UNIT_DIR:-/etc/systemd/system}"
SRC_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/systemd"
UNITS="bsdmirror-health.service bsdmirror-health.timer"

# The literal path baked into the shipped unit files. Kept in one place so a
# change here and a change there cannot disagree.
UNIT_DEFAULT_DIR="/opt/bsdmirror"

DRY_RUN=0
ACTION="install"
ALLOW_NO_CHANNEL=0

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    C_RED=$'\033[0;31m'; C_GRN=$'\033[0;32m'; C_YEL=$'\033[1;33m'; C_OFF=$'\033[0m'
else
    C_RED=""; C_GRN=""; C_YEL=""; C_OFF=""
fi
info() { printf '%s[INFO]%s %s\n' "$C_GRN" "$C_OFF" "$*"; }
warn() { printf '%s[WARN]%s %s\n' "$C_YEL" "$C_OFF" "$*" >&2; }
err()  { printf '%s[ERROR]%s %s\n' "$C_RED" "$C_OFF" "$*" >&2; }
step() { printf '\n==> %s\n' "$*"; }

usage() {
    awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "$0"
    cat <<'USAGE'

Options:
  --dir PATH             Deployment directory (default: /opt/bsdmirror).
  --unit-dir PATH        systemd unit directory (default: /etc/systemd/system).
  --dry-run              Show every action, perform none. Does not need root.
  --uninstall            Stop and disable the timer and remove the units.
  --allow-no-channel     Install even though no alert channel is configured.
                         Refused by default: installing a checker that cannot
                         tell anyone is how this repo got here.
  -h, --help             This text.
USAGE
}

run() {
    if [ "$DRY_RUN" -eq 1 ]; then
        printf '    would run: %s\n' "$*"
        return 0
    fi
    "$@"
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [ "$#" -gt 0 ]; do
    case "$1" in
        --dir)              INSTALL_DIR="${2:-}"; shift 2 || { err "--dir needs a path"; exit 1; } ;;
        --unit-dir)         UNIT_DIR="${2:-}";    shift 2 || { err "--unit-dir needs a path"; exit 1; } ;;
        --dry-run)          DRY_RUN=1; shift ;;
        --uninstall)        ACTION="uninstall"; shift ;;
        --allow-no-channel) ALLOW_NO_CHANNEL=1; shift ;;
        -h|--help)          usage; exit 0 ;;
        *)                  err "unknown argument: $1"; err "try --help"; exit 1 ;;
    esac
done

[ -n "$INSTALL_DIR" ] || { err "--dir cannot be empty"; exit 1; }
[ -n "$UNIT_DIR" ]    || { err "--unit-dir cannot be empty"; exit 1; }

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
if [ "$DRY_RUN" -eq 0 ] && [ "$(id -u)" -ne 0 ]; then
    err "must run as root (it writes to $UNIT_DIR and calls systemctl)"
    err "re-run with sudo, or use --dry-run to see what it would do"
    exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
    err "systemctl not found: this host does not use systemd"
    err "on a non-systemd host, schedule $INSTALL_DIR/scripts/health_check.sh hourly by other means"
    exit 1
fi

for u in $UNITS; do
    if [ ! -f "$SRC_DIR/$u" ]; then
        err "missing unit file: $SRC_DIR/$u"
        exit 1
    fi
done

# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------
if [ "$ACTION" = "uninstall" ]; then
    step "Removing the bsdmirror health timer"
    run systemctl disable --now bsdmirror-health.timer 2>/dev/null || true
    run systemctl stop bsdmirror-health.service 2>/dev/null || true
    for u in $UNITS; do
        if [ -f "$UNIT_DIR/$u" ]; then
            info "removing $UNIT_DIR/$u"
            run rm -f "$UNIT_DIR/$u"
        else
            info "$UNIT_DIR/$u already absent"
        fi
    done
    run systemctl daemon-reload
    info "removed. /var/lib/bsdmirror/health-state.json was left in place."
    exit 0
fi

# ---------------------------------------------------------------------------
# Prerequisites the check itself needs
# ---------------------------------------------------------------------------
step "Checking prerequisites"

missing=""
for cmd in curl jq; do
    command -v "$cmd" >/dev/null 2>&1 || missing="$missing $cmd"
done
if [ -n "$missing" ]; then
    err "health_check.sh needs:$missing"
    err "install them first:  apt-get update && apt-get install -y$missing"
    exit 2
fi
info "curl and jq present"

CHECK_SCRIPT="$INSTALL_DIR/scripts/health_check.sh"
if [ ! -f "$CHECK_SCRIPT" ]; then
    err "$CHECK_SCRIPT does not exist"
    err "pass --dir if the deployment is not at $INSTALL_DIR"
    exit 2
fi
if [ ! -x "$CHECK_SCRIPT" ]; then
    warn "$CHECK_SCRIPT is not executable; fixing"
    run chmod +x "$CHECK_SCRIPT"
fi
info "found $CHECK_SCRIPT"

ENV_FILE="$INSTALL_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    err "$ENV_FILE not found -- run scripts/setup.sh first"
    exit 2
fi

# ---------------------------------------------------------------------------
# Refuse to install an alerter that cannot alert.
#
# Delegated to health_check.sh --check-deps rather than reimplemented here, so
# there is one definition of "a channel is configured" and it cannot drift.
# --check-deps prints the channel names; it never prints a URL.
# ---------------------------------------------------------------------------
step "Checking that an alert channel is configured"

if ENV_FILE="$ENV_FILE" "$CHECK_SCRIPT" --check-deps; then
    info "an alert channel is configured"
else
    err "no usable alert channel is configured in $ENV_FILE"
    err ""
    err "Add one, then re-run. For Discord, create a webhook under"
    err "  Server Settings > Integrations > Webhooks > New Webhook > Copy Webhook URL"
    err "and append to $ENV_FILE:"
    err ""
    err "    ALERT_CHANNELS=discord"
    err "    DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/<id>/<token>"
    err ""
    err "Keep $ENV_FILE at mode 0600. Then verify with:"
    err "    $CHECK_SCRIPT --test-alert"
    err ""
    if [ "$ALLOW_NO_CHANNEL" -eq 1 ]; then
        warn "--allow-no-channel given: installing a health check that cannot notify anyone"
    else
        err "refusing to install (pass --allow-no-channel to override)"
        exit 2
    fi
fi

# ---------------------------------------------------------------------------
# Install the units
# ---------------------------------------------------------------------------
step "Installing units into $UNIT_DIR"

run mkdir -p "$UNIT_DIR"

changed=0
for u in $UNITS; do
    tmp="$(mktemp)"
    # The units ship with /opt/bsdmirror written out literally so that they
    # are valid as committed and `systemd-analyze verify` can be run on the
    # repo copy. Rewrite only if this deployment lives elsewhere.
    if [ "$INSTALL_DIR" = "$UNIT_DEFAULT_DIR" ]; then
        cat "$SRC_DIR/$u" > "$tmp"
    else
        escaped=$(printf '%s\n' "$INSTALL_DIR" | sed 's/[&/\]/\\&/g')
        sed "s#${UNIT_DEFAULT_DIR}#${escaped}#g" "$SRC_DIR/$u" > "$tmp"
        if grep -q "$UNIT_DEFAULT_DIR" "$tmp"; then
            err "path substitution left '$UNIT_DEFAULT_DIR' in $u"
            rm -f "$tmp"
            exit 1
        fi
    fi

    if [ -f "$UNIT_DIR/$u" ] && cmp -s "$tmp" "$UNIT_DIR/$u"; then
        info "$u unchanged"
    else
        info "writing $UNIT_DIR/$u"
        if [ "$DRY_RUN" -eq 1 ]; then
            if [ -f "$UNIT_DIR/$u" ]; then
                printf '    would replace it; diff against the installed copy:\n'
                diff -u "$UNIT_DIR/$u" "$tmp" | sed 's/^/      /' || true
            else
                printf '    would create it (%s lines, new file)\n' "$(wc -l < "$tmp" | tr -d ' ')"
            fi
        else
            install -m 0644 -o root -g root "$tmp" "$UNIT_DIR/$u"
        fi
        changed=1
    fi
    rm -f "$tmp"
done

if [ "$changed" -eq 1 ]; then
    step "Reloading systemd"
    run systemctl daemon-reload
else
    info "no unit changed; skipping daemon-reload"
fi

step "Enabling the timer"
run systemctl enable --now bsdmirror-health.timer

# ---------------------------------------------------------------------------
# Show the operator what they now have
# ---------------------------------------------------------------------------
if [ "$DRY_RUN" -eq 0 ]; then
    step "Result"
    systemctl list-timers bsdmirror-health.timer --all --no-pager || true
    echo
    info "Run it once now, without waiting for the timer:"
    info "    systemctl start bsdmirror-health && journalctl -u bsdmirror-health -n 40 --no-pager"
    info "Send a test message through the configured channel:"
    info "    $CHECK_SCRIPT --test-alert"
    info "See what it would say without sending anything:"
    info "    $CHECK_SCRIPT --dry-run"
else
    echo
    info "--dry-run: nothing was changed"
fi
