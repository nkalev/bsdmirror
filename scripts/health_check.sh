#!/usr/bin/env bash
#
# bsdmirror - health check and alerting
#
# Why this exists
# ---------------
# On 2026-07-02 the OpenBSD upstream went away. The mirror then failed 58
# consecutive nights and nobody found out, because a stale mirror is
# indistinguishable from a healthy one unless something looks at the clock:
# the containers stay healthy, /api/health returns 200, nginx keeps serving
# the files that were already on disk, and the mirror still reports a status.
#
# An earlier version of this script existed for that whole period. Two things
# were wrong with it:
#
#   1. Nothing ever ran it. There was no timer and no cron entry.
#   2. It could not have alerted if it had run. Under `set -e` on bash 4+,
#      `check_health || ((errors++))` aborts the script the first time a check
#      fails, because `((errors++))` is the last command of an || list (so it
#      is NOT exempt from errexit) and post-increment from 0 evaluates to 0,
#      which is a false arithmetic result and therefore exit status 1. The
#      script died before reaching send_alert. Verified on bash 5.2.21
#      (Ubuntu 24.04, the deploy target): aborts at the first failing check.
#      Verified on bash 3.2.57 (macOS): does not abort -- bash 3.2 wrongly
#      exempted the whole || list, which is why this was never noticed on a
#      developer laptop. Every counter in this file uses `n=$((n + 1))`.
#
# What it does now
# ----------------
#   * Checks mirror STALENESS from the API, which is the check that would have
#     caught 2026-07-02, plus mirror status=error, API reachability, disk and
#     container health.
#   * Alerts on TRANSITION into a bad state, stays quiet while it persists,
#     alerts on recovery, and re-reminds daily. A channel that fires every
#     hour while a condition persists gets muted, and a muted channel is 58
#     silent nights with extra steps.
#   * Sends to Discord and/or Slack and/or email. The channel is explicit
#     configuration (ALERT_CHANNELS), never guessed from the webhook hostname,
#     because hostname sniffing breaks silently behind a proxy or against a
#     self-hosted endpoint.
#   * Never dies because its own notifier is down. A health checker that
#     crashes when the webhook is unreachable is worse than no health checker.
#
# Usage
# -----
#   scripts/health_check.sh                 run the checks, alert on transitions
#   scripts/health_check.sh --dry-run       run the checks, print the alert,
#                                           send nothing, persist nothing
#   scripts/health_check.sh --test-alert    send a test message and exit
#   scripts/health_check.sh --check-deps    verify prerequisites and exit
#   scripts/health_check.sh --show-state    print the dedup state and exit
#   scripts/health_check.sh --insecure-tls  skip TLS verification (staging cert)
#   scripts/health_check.sh --help
#
# Exit codes -- these are the contract:
#   0  every check passed
#   1  at least one condition is bad (whether or not an alert was delivered)
#   2  the script could not run: missing prerequisite, bad argument
#
# Secrets
# -------
# The webhook URL is a secret. It is read from .env (mode 0600, gitignored),
# it is never passed to curl as an argument -- curl reads it from a `--config -`
# stream on stdin, so it does not appear in `ps` -- it is never printed, and
# every line this script logs is filtered through redact() first, including
# curl's own error output.
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration. Every one of these is overridable from the environment or
# from .env; environment wins. None of them has to be edited here.
# ---------------------------------------------------------------------------
ENV_FILE="${ENV_FILE:-/opt/bsdmirror/.env}"

# Where to ask. The public endpoints are used on purpose: they need no
# credentials, so the alerter holds no token that could expire and take the
# alerting down with it.
#
# Left empty, this is derived from DOMAIN in .env exactly the way
# scripts/deploy.sh:960 derives BASE_URL, and for the same reason: the backend
# publishes no ports (docker-compose.yml gives it no `ports`, and the
# `backend` network is `internal: true`), so http://localhost:8000 -- the old
# default here -- cannot reach it from the host at all. nginx is the only way
# in.
API_URL="${API_URL:-}"
DOMAIN="${DOMAIN:-}"

# Only for a deployment still on a Let's Encrypt *staging* certificate, where
# the API check would otherwise fail forever and train everyone to ignore it.
INSECURE_TLS="${INSECURE_TLS:-0}"

# Staleness. The sync schedule is nightly (SYNC_SCHEDULE defaults to 0 4 * * *),
# so 36h is one missed night plus most of a day of slack -- late enough not to
# fire on a slow sync, early enough that a dead upstream is a next-morning
# problem rather than a two-month one.
STALE_AFTER_HOURS="${STALE_AFTER_HOURS:-36}"

# Disk. WARN is reported but is not a condition; CRIT is a condition.
DISK_WARN_PCT="${DISK_WARN_PCT:-85}"
DISK_CRIT_PCT="${DISK_CRIT_PCT:-95}"

# Dedup. A condition that is still bad is re-sent this often and not otherwise.
ALERT_REMIND_HOURS="${ALERT_REMIND_HOURS:-24}"

# systemd sets STATE_DIRECTORY from StateDirectory= in the unit; /var/lib is
# the fallback for a manual run.
HEALTH_STATE_FILE="${HEALTH_STATE_FILE:-${STATE_DIRECTORY:-/var/lib/bsdmirror}/health-state.json}"

# HTTP. Retries exist so a single blip does not produce an alert/recovery pair
# on an hourly timer.
HTTP_TIMEOUT="${HTTP_TIMEOUT:-15}"
HTTP_RETRIES="${HTTP_RETRIES:-3}"
HTTP_RETRY_DELAY="${HTTP_RETRY_DELAY:-5}"

# Webhook delivery: how many times to retry a 429, and the longest single
# backoff to honour. A notifier that sleeps for the retry_after a server asks
# for without a cap is a notifier that can hang the timer unit.
ALERT_MAX_ATTEMPTS="${ALERT_MAX_ATTEMPTS:-4}"
ALERT_MAX_BACKOFF="${ALERT_MAX_BACKOFF:-30}"

# Channels. Explicit, comma or space separated, e.g. "discord" or
# "discord,email". Left empty, it is derived from which channel variable is
# configured -- from the variable NAME, never from the URL's hostname -- and
# the derivation is printed.
ALERT_CHANNELS="${ALERT_CHANNELS:-}"
DISCORD_WEBHOOK_URL="${DISCORD_WEBHOOK_URL:-}"
SLACK_WEBHOOK="${SLACK_WEBHOOK:-}"
EMAIL_RECIPIENT="${EMAIL_RECIPIENT:-}"

# Label used in the alert so a message from two deployments can be told apart.
ALERT_SOURCE_LABEL="${ALERT_SOURCE_LABEL:-}"

# Host path of the mirror data. .env already carries this; the previous
# version hardcoded the container path /data/mirrors, which is only correct
# because it happens to be the default.
MIRROR_DATA_PATH="${MIRROR_DATA_PATH:-/data/mirrors}"

DRY_RUN=0
MODE="run"        # run | test-alert | check-deps | show-state
QUIET=0

# State file is 0600: it is not secret, but there is no reason for it to be
# world readable either.
umask 077

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    C_RED=$'\033[0;31m'; C_GRN=$'\033[0;32m'; C_YEL=$'\033[1;33m'; C_OFF=$'\033[0m'
else
    C_RED=""; C_GRN=""; C_YEL=""; C_OFF=""
fi

# Everything printed goes through redact() so a webhook URL cannot reach a
# terminal, a log file, or journalctl by accident.
info() { [ "$QUIET" -eq 1 ] || printf '%s\n' "$(redact "$*")"; }
ok()   { [ "$QUIET" -eq 1 ] || printf '  %s[ OK ]%s %s\n' "$C_GRN" "$C_OFF" "$(redact "$*")"; }
bad()  { printf '  %s[FAIL]%s %s\n' "$C_RED" "$C_OFF" "$(redact "$*")" >&2; }
warn() { printf '  %s[WARN]%s %s\n' "$C_YEL" "$C_OFF" "$(redact "$*")" >&2; }
err()  { printf '%s[ERROR]%s %s\n' "$C_RED" "$C_OFF" "$(redact "$*")" >&2; }

usage() {
    # Print the contiguous comment block after the shebang, stopping at the
    # first line of code, so --help cannot drift from the header.
    awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "$0"
}

# ---------------------------------------------------------------------------
# redact
#
# Literal substring replacement, done in awk with index() rather than with
# sed or ${var//pat/rep}: both of those interpret their pattern, and a URL
# that happens to contain a metacharacter would either fail to match or match
# too much. Failing to match is the dangerous direction here.
# ---------------------------------------------------------------------------
REDACT_LIST=""

redact_register() {
    # A short string would match half the log. 12 characters is longer than
    # any scheme+host prefix we would want to hide by accident.
    local s="$1"
    if [ -n "$s" ] && [ "${#s}" -ge 12 ]; then
        REDACT_LIST="${REDACT_LIST}${s}"$'\n'
    fi
}

redact() {
    local text="$1"
    if [ -z "$REDACT_LIST" ]; then
        printf '%s' "$text"
        return 0
    fi
    printf '%s' "$text" | awk -v secrets="$REDACT_LIST" '
        BEGIN {
            n = split(secrets, s, "\n")
        }
        {
            line = $0
            for (i = 1; i <= n; i++) {
                if (s[i] == "") continue
                out = ""
                while ((p = index(line, s[i])) > 0) {
                    out = out substr(line, 1, p - 1) "<redacted>"
                    line = substr(line, p + length(s[i]))
                }
                line = out line
            }
            print line
        }'
}

# ---------------------------------------------------------------------------
# .env loading
#
# Deliberately not `source`: .env is data, and sourcing it would execute
# whatever is in it and would also clobber variables that were set on the
# command line for a one-off run. Environment wins over file.
# ---------------------------------------------------------------------------
env_lookup() {
    local key="$1" file="$2" value
    [ -f "$file" ] || return 1
    value=$(sed -n "s/^[[:space:]]*${key}=//p" "$file" | tail -n 1) || return 1
    [ -n "$value" ] || return 1
    # Strip one layer of matching quotes, the way a .env consumer would.
    case "$value" in
        \"*\") value="${value#\"}"; value="${value%\"}" ;;
        \'*\') value="${value#\'}"; value="${value%\'}" ;;
    esac
    printf '%s' "$value"
}

load_env() {
    local key value
    if [ ! -f "$ENV_FILE" ]; then
        info "note: $ENV_FILE not found; using environment and defaults only"
        return 0
    fi
    for key in DISCORD_WEBHOOK_URL SLACK_WEBHOOK EMAIL_RECIPIENT ALERT_CHANNELS \
               STALE_AFTER_HOURS ALERT_REMIND_HOURS DISK_WARN_PCT DISK_CRIT_PCT \
               MIRROR_DATA_PATH DOMAIN API_URL ALERT_SOURCE_LABEL; do
        # Only fill in what the environment did not already provide.
        eval "value=\${$key:-}"
        if [ -z "$value" ]; then
            if value=$(env_lookup "$key" "$ENV_FILE"); then
                eval "$key=\$value"
            fi
        fi
    done
}

# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------
require_deps() {
    local missing=0 cmd
    for cmd in curl jq awk sed date; do
        if ! command -v "$cmd" >/dev/null 2>&1; then
            err "required command not found: $cmd"
            missing=$((missing + 1))
        fi
    done
    if [ "$missing" -gt 0 ]; then
        err "on Ubuntu: apt-get install -y curl jq"
        return 1
    fi
    return 0
}

# ---------------------------------------------------------------------------
# Conditions
#
# A condition is one named thing that can be bad, and dedup is per condition.
# One global "errors > 0" flag would mean a NEW problem appearing while an old
# one persists gets swallowed by the old one's silence -- which is the failure
# mode this whole script exists to avoid.
#
# Records are delimited with US (ASCII 0x1f), NOT with a tab. Tab is an IFS
# *whitespace* character, so `IFS=$'\t' read` collapses a run of tabs into one
# separator and an empty column silently shifts every field after it. That is
# not theoretical: it read a RECOVERED record's empty detail column as the
# timestamp and reported "was bad for 20695d17h". A non-whitespace IFS
# character delimits every field, empty or not.
#
# `key` is stable across runs and is what the state file is keyed on, so it
# must not contain a timestamp or an age.
# ---------------------------------------------------------------------------
FS_US=$'\037'

BAD_RECORDS=()
CHECKS_OK=0
CHECKS_BAD=0
API_HEALTHY=0

add_condition() {
    local key="$1" label="$2" detail="$3"
    BAD_RECORDS+=("${key}${FS_US}${label}${FS_US}${detail}")
    CHECKS_BAD=$((CHECKS_BAD + 1))
    bad "$label: $detail"
}

pass_condition() {
    CHECKS_OK=$((CHECKS_OK + 1))
    ok "$1"
}

# carry_forward PREFIX
#
# Re-adds every previously-bad condition whose key starts with PREFIX, for use
# when the check that produces those conditions could not run at all this time.
#
# Without this, "the API is unreachable so I cannot see the mirrors" and "the
# mirrors are fine again" are indistinguishable to reconcile(), and an outage
# would produce a cheerful RECOVERED message for a mirror that is still dead.
# A condition carried forward neither re-alerts nor recovers: it simply stays
# where it was.
carry_forward() {
    local prefix="$1" key label detail n=0 rows
    rows=$(printf '%s' "$STATE_JSON" | jq -r --arg p "$prefix" '
        (.conditions // {}) | to_entries[]
        | select(.key | startswith($p))
        | [.key, (.value.label // .key), (.value.detail // "")]
        | map(tostring | gsub("[\n\r\u001f]"; " ")) | join("\u001f")' 2>/dev/null) || rows=""
    [ -n "$rows" ] || return 0
    while IFS="$FS_US" read -r key label detail; do
        [ -n "$key" ] || continue
        BAD_RECORDS+=("${key}${FS_US}${label}${FS_US}${detail}")
        CHECKS_BAD=$((CHECKS_BAD + 1))
        n=$((n + 1))
    done <<< "$rows"
    warn "carrying forward $n condition(s) matching \"$prefix\": this check could not run, which is not the same as passing"
}

# ---------------------------------------------------------------------------
# HTTP GET with retries.
#
# Sets HTTP_CODE and HTTP_BODY. Deliberately NOT `body=$(http_get ...)`: a
# command substitution runs the function in a subshell, so the status code it
# assigns would be discarded and every check would read an empty code. Called
# as a plain command, both globals survive.
#
# Never returns non-zero in a way errexit can act on: callers test HTTP_CODE.
# ---------------------------------------------------------------------------
HTTP_CODE=""
HTTP_BODY=""

http_get() {
    local url="$1" attempt=1 out rc
    while :; do
        HTTP_CODE="000"
        HTTP_BODY=""
        rc=0
        out=$(curl --silent --show-error --location \
                   ${INSECURE_TLS:+--insecure} \
                   --max-time "$HTTP_TIMEOUT" \
                   --write-out $'\n%{http_code}' \
                   "$url" 2>/dev/null) || rc=$?
        if [ "$rc" -eq 0 ]; then
            HTTP_CODE="${out##*$'\n'}"
            HTTP_BODY="${out%$'\n'*}"
            case "$HTTP_CODE" in
                2*) return 0 ;;
            esac
        fi
        if [ "$attempt" -ge "$HTTP_RETRIES" ]; then
            return 0
        fi
        attempt=$((attempt + 1))
        sleep "$HTTP_RETRY_DELAY"
    done
}

# ---------------------------------------------------------------------------
# Check: API reachable
# ---------------------------------------------------------------------------
check_api() {
    local status
    http_get "$API_URL/api/health"
    if [ "$HTTP_CODE" != "200" ]; then
        add_condition "api" "api" \
            "GET $API_URL/api/health returned HTTP $HTTP_CODE after $HTTP_RETRIES attempt(s)"
        return 1
    fi
    status=$(printf '%s' "$HTTP_BODY" | jq -r '.status // "unknown"' 2>/dev/null || echo "unparseable")
    if [ "$status" != "healthy" ]; then
        add_condition "api" "api" "/api/health returned HTTP 200 with status=\"$status\""
        return 1
    fi
    API_HEALTHY=1
    pass_condition "api responding (HTTP 200, status=healthy)"
    return 0
}

# ---------------------------------------------------------------------------
# Check: mirror staleness and mirror status
#
# This is the check that was missing. /api/stats/health returns, for every
# ENABLED mirror, its status and its last_sync (Mirror.last_sync_completed).
# The endpoint's own top-level "status" field is deliberately ignored: it
# collapses to healthy/updating/degraded and reports "healthy" for a mirror
# that has not synced since July.
#
# last_sync_completed is only trustworthy as of 405a090. Before cc0b9f6 it was
# cleared on every failed sync, so on a deployment that has not yet run a
# successful sync since that commit, the first run of this check may report a
# staleness that is really "we deleted the evidence". It self-corrects on the
# first successful sync.
#
# A mirror stuck in SYNCING is caught here for free: its last_sync_completed
# stops advancing, so it goes stale like any other.
# ---------------------------------------------------------------------------
check_mirrors() {
    local now max_age name state age_s
    http_get "$API_URL/api/stats/health"
    if [ "$HTTP_CODE" != "200" ]; then
        # If /api/health is already reported down, this is the same outage;
        # naming it twice is noise. If /api/health is UP and only this
        # endpoint is broken, that is its own problem and gets its own
        # condition.
        if [ "$API_HEALTHY" -eq 1 ]; then
            add_condition "mirror-api" "mirror-api" \
                "GET $API_URL/api/stats/health returned HTTP $HTTP_CODE; mirror freshness is UNKNOWN"
        else
            warn "mirror freshness UNKNOWN: /api/stats/health returned HTTP $HTTP_CODE (the api condition above covers it)"
        fi
        carry_forward "mirror-"
        return 1
    fi

    if ! printf '%s' "$HTTP_BODY" | jq -e '.mirrors' >/dev/null 2>&1; then
        add_condition "mirror-api" "mirror-api" \
            "/api/stats/health returned HTTP 200 but no .mirrors object; mirror freshness is UNKNOWN"
        carry_forward "mirror-stale:"
        carry_forward "mirror-error:"
        return 1
    fi

    now=$(date -u +%s)
    max_age=$(( STALE_AFTER_HOURS * 3600 ))

    # One jq program does the date arithmetic so the shell never has to parse
    # an ISO-8601 string. `date -d` would work on the Ubuntu target and not on
    # a macOS laptop; this works on both, and jq is already required.
    #
    # Emits, per mirror:  name US status US age_seconds|MISSING|UNPARSEABLE
    local parsed
    parsed=$(printf '%s' "$HTTP_BODY" | jq -r --argjson now "$now" '
        def iso2epoch:
          (. // "") | tostring
          | sub("\\.[0-9]+(?=(Z|[+-]|$))"; "")
          | if test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(Z|[+-][0-9]{2}:?[0-9]{2})?$")
            then capture("^(?<b>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(?<o>Z|[+-][0-9]{2}:?[0-9]{2})?$")
                 | (((.b + "Z") | strptime("%Y-%m-%dT%H:%M:%SZ") | mktime)) as $e
                 | ((.o // "Z")) as $off
                 | if $off == "Z" then $e
                   else ($off | capture("^(?<s>[+-])(?<h>[0-9]{2}):?(?<m>[0-9]{2})$"))
                        | ((((.h | tonumber) * 3600) + ((.m | tonumber) * 60))) as $d
                        | (if .s == "+" then $e - $d else $e + $d end)
                   end
            else null
            end;
        .mirrors
        | to_entries[]
        | .key as $name
        | (.value.status // "unknown") as $st
        | (.value.last_sync) as $ls
        | (if $ls == null then "MISSING"
           else (($ls | iso2epoch) as $e
                 | if $e == null then "UNPARSEABLE" else (($now - $e) | floor | tostring) end)
           end) as $age
        | [$name, $st, $age]
        | map(tostring | gsub("[\n\r\u001f]"; " ")) | join("\u001f")
    ' 2>/dev/null) || parsed=""

    if [ -z "$parsed" ]; then
        add_condition "mirror-api" "mirror-api" \
            "could not parse /api/stats/health; mirror freshness is UNKNOWN"
        carry_forward "mirror-stale:"
        carry_forward "mirror-error:"
        return 1
    fi

    local any_bad=0
    while IFS="$FS_US" read -r name state age_s; do
        [ -n "$name" ] || continue

        # status=error is its own condition, independent of freshness, so a
        # mirror that is both erroring and stale reports both and each
        # recovers on its own.
        if [ "$state" = "error" ]; then
            add_condition "mirror-error:$name" "$name status" \
                "mirror status is ERROR"
            any_bad=1
        fi

        case "$age_s" in
            MISSING)
                add_condition "mirror-stale:$name" "$name freshness" \
                    "has never completed a sync (last_sync is null), status=$state"
                any_bad=1
                ;;
            UNPARSEABLE)
                # Fail toward alerting: an unreadable timestamp is not
                # evidence of freshness.
                add_condition "mirror-stale:$name" "$name freshness" \
                    "last_sync could not be parsed as a timestamp, status=$state"
                any_bad=1
                ;;
            *)
                if [ "$age_s" -gt "$max_age" ]; then
                    add_condition "mirror-stale:$name" "$name freshness" \
                        "last completed sync $(human_age "$age_s") ago, threshold ${STALE_AFTER_HOURS}h, status=$state"
                    any_bad=1
                else
                    pass_condition "$name fresh (last sync $(human_age "$age_s") ago, status=$state)"
                fi
                ;;
        esac
        if [ "$state" != "error" ] && [ "$state" != "active" ] && [ "$state" != "syncing" ]; then
            warn "$name has unexpected status \"$state\""
        fi
    done <<< "$parsed"

    return "$any_bad"
}

human_age() {
    local s="$1" d h m
    d=$(( s / 86400 )); h=$(( (s % 86400) / 3600 )); m=$(( (s % 3600) / 60 ))
    if [ "$d" -gt 0 ]; then printf '%dd%dh' "$d" "$h"
    elif [ "$h" -gt 0 ]; then printf '%dh%dm' "$h" "$m"
    else printf '%dm' "$m"
    fi
}

# ---------------------------------------------------------------------------
# Check: disk
# ---------------------------------------------------------------------------
check_disk() {
    local usage
    if [ ! -d "$MIRROR_DATA_PATH" ]; then
        # Not being able to see the mirror data is a problem, not a pass.
        #
        # This used to warn, carry forward any earlier disk condition, and
        # return 0. With no earlier condition that carried nothing, so the run
        # ended "0 bad, N ok -- all checks passed" without ever looking at the
        # disk. That is what happened on 2026-09-12, when the unit's
        # ProtectHome=true hid /data (a symlink into /home) from this process:
        # hourly runs reported all clear with disk unchecked, on the check that
        # matters most now that EOL releases are protected from deletion.
        #
        # Same "disk" key as the usage conditions, so a later successful check
        # recovers it rather than leaving a stale entry, and an existing
        # over-threshold condition continues instead of alerting twice.
        add_condition "disk" "disk" \
            "cannot see $MIRROR_DATA_PATH: missing, unmounted, or hidden from this process by a sandbox"
        return 1
    fi
    usage=$(df -P "$MIRROR_DATA_PATH" 2>/dev/null | awk 'NR==2 {gsub(/%/,"",$5); print $5}') || usage=""
    if ! printf '%s' "$usage" | grep -Eq '^[0-9]+$'; then
        add_condition "disk" "disk" "could not read disk usage for $MIRROR_DATA_PATH"
        return 1
    fi
    if [ "$usage" -ge "$DISK_CRIT_PCT" ]; then
        add_condition "disk" "disk" \
            "$MIRROR_DATA_PATH is ${usage}% full, threshold ${DISK_CRIT_PCT}%"
        return 1
    fi
    if [ "$usage" -ge "$DISK_WARN_PCT" ]; then
        warn "disk usage ${usage}% on $MIRROR_DATA_PATH (warn at ${DISK_WARN_PCT}%, alert at ${DISK_CRIT_PCT}%)"
    fi
    pass_condition "disk usage ${usage}% on $MIRROR_DATA_PATH"
    return 0
}

# ---------------------------------------------------------------------------
# Check: containers
#
# `docker` absent is a skip, not a failure -- this script is also run by hand
# from a laptop. `docker` present but not answering IS a failure: on the
# deploy host that means the engine is down and nothing is being served.
# ---------------------------------------------------------------------------
check_containers() {
    local unhealthy rc=0
    if ! command -v docker >/dev/null 2>&1; then
        warn "container check skipped: docker not found on this host"
        carry_forward "containers"
        return 0
    fi
    unhealthy=$(docker ps --filter "health=unhealthy" --format '{{.Names}}' 2>/dev/null) || rc=$?
    if [ "$rc" -ne 0 ]; then
        add_condition "containers" "containers" "docker ps failed (exit $rc); is the engine running?"
        return 1
    fi
    unhealthy=$(printf '%s' "$unhealthy" | grep -i 'bsdmirror' || true)
    if [ -n "$unhealthy" ]; then
        add_condition "containers" "containers" \
            "unhealthy: $(printf '%s' "$unhealthy" | tr '\n' ' ')"
        return 1
    fi
    pass_condition "no unhealthy bsdmirror containers"
    return 0
}

# ---------------------------------------------------------------------------
# Dedup state
#
# {"version":1,"conditions":{"<key>":{"since":<epoch>,"last_notified":<epoch>,
#                                     "label":"...","detail":"..."}}}
#
# A missing, unreadable or corrupt state file is treated as "nothing is
# known", which makes every currently-bad condition a fresh transition and
# therefore alerts. That direction is deliberate: the failure mode being
# designed against is silence, so the state layer fails loud.
# ---------------------------------------------------------------------------
STATE_JSON='{"version":1,"conditions":{}}'
STATE_DEGRADED=0

state_load() {
    if [ ! -f "$HEALTH_STATE_FILE" ]; then
        info "no state file at $HEALTH_STATE_FILE; treating every current problem as new"
        return 0
    fi
    local content
    if ! content=$(cat "$HEALTH_STATE_FILE" 2>/dev/null); then
        warn "state file $HEALTH_STATE_FILE is unreadable; treating every current problem as new"
        STATE_DEGRADED=1
        return 0
    fi
    if ! printf '%s' "$content" | jq -e '.conditions | type == "object"' >/dev/null 2>&1; then
        warn "state file $HEALTH_STATE_FILE is corrupt; treating every current problem as new"
        STATE_DEGRADED=1
        return 0
    fi
    STATE_JSON="$content"
    return 0
}

state_save() {
    local dir tmp
    dir=$(dirname "$HEALTH_STATE_FILE")
    if ! mkdir -p "$dir" 2>/dev/null; then
        warn "cannot create $dir; dedup state will not persist and alerts will repeat"
        STATE_DEGRADED=1
        return 1
    fi
    tmp="${HEALTH_STATE_FILE}.tmp.$$"
    if ! printf '%s\n' "$STATE_JSON" > "$tmp" 2>/dev/null; then
        warn "cannot write $tmp; dedup state will not persist and alerts will repeat"
        STATE_DEGRADED=1
        rm -f "$tmp" 2>/dev/null || true
        return 1
    fi
    if ! mv -f "$tmp" "$HEALTH_STATE_FILE" 2>/dev/null; then
        warn "cannot replace $HEALTH_STATE_FILE; dedup state will not persist and alerts will repeat"
        STATE_DEGRADED=1
        rm -f "$tmp" 2>/dev/null || true
        return 1
    fi
    return 0
}

# ---------------------------------------------------------------------------
# Reconcile current conditions against the previous state.
#
# Sets TRANSITIONS to a list of five-column TAB-separated records:
#   kind  key  label  detail  bad_since_epoch
# where kind is NEW, REMIND or RECOVERED. RECOVERED has an empty detail;
# NEW has an empty bad_since. The column count is fixed on purpose so
# build_message can read all three kinds with one `read`.
#
# Also updates STATE_JSON, with last_notified left at its OLD value: that is
# only advanced once a channel has actually accepted the message, so a webhook
# outage during a transition does not swallow the alert.
#
# Sets globals rather than printing, and so must NOT be called through a
# command substitution -- that runs it in a subshell and silently discards
# every state update, which is a dedup that never dedups.
# ---------------------------------------------------------------------------
TRANSITIONS=""

reconcile() {
    local now="$1" current_json
    current_json=$(
        if [ "${#BAD_RECORDS[@]}" -gt 0 ]; then printf '%s\n' "${BAD_RECORDS[@]}"; fi \
        | jq -R -s '
            split("\n") | map(select(length > 0)) | map(split("\u001f"))
            | map({key: .[0], value: {label: (.[1] // ""), detail: (.[2] // "")}})
            | from_entries'
    )

    TRANSITIONS=$(printf '%s' "$STATE_JSON" | jq -r \
        --argjson now "$now" \
        --argjson remind "$(( ALERT_REMIND_HOURS * 3600 ))" \
        --argjson cur "$current_json" '
        # Any newline or US inside a field would break the line-and-field
        # framing, so squash both before joining.
        def rec: map(tostring | gsub("[\n\r\u001f]"; " ")) | join("\u001f");
        . as $old
        | ($old.conditions // {}) as $prev
        | [ $cur | to_entries[]
            | .key as $k
            | if (($prev | has($k)) | not) then
                ["NEW", $k, .value.label, .value.detail, ""] | rec
              elif ($now - ($prev[$k].last_notified // 0)) >= $remind then
                ["REMIND", $k, .value.label, .value.detail,
                 (($prev[$k].since // $now) | tostring)] | rec
              else empty end ]
        + [ $prev | to_entries[]
            | .key as $k
            | select((($cur | has($k)) | not))
            | ["RECOVERED", $k, (.value.label // $k), "",
               ((.value.since // $now) | tostring)] | rec ]
        | .[]')

    # New state: every currently-bad condition, keeping `since` and
    # `last_notified` from the previous state where they exist. Recovered
    # conditions are dropped entirely, which is what makes the next
    # occurrence a NEW transition rather than a reminder.
    STATE_JSON=$(printf '%s' "$STATE_JSON" | jq -c \
        --argjson now "$now" \
        --argjson cur "$current_json" '
        (.conditions // {}) as $prev
        | {version: 1,
           conditions: ($cur | with_entries(
               .key as $k
               | .value = {
                   since:        ($prev[$k].since // $now),
                   last_notified:($prev[$k].last_notified // 0),
                   label:        .value.label,
                   detail:       .value.detail
                 }))}')
}

state_mark_notified() {
    # $@ = condition keys that were successfully delivered
    local now="$1"; shift
    local keys_json
    keys_json=$(printf '%s\n' "$@" | jq -R -s 'split("\n") | map(select(length > 0))')
    STATE_JSON=$(printf '%s' "$STATE_JSON" | jq -c \
        --argjson now "$now" --argjson keys "$keys_json" '
        .conditions |= with_entries(
            if (.key as $k | $keys | index($k)) then .value.last_notified = $now else . end)')
}

# ===========================================================================
# Alert channels
#
# Adding a channel is three functions and one word in CHANNEL_REGISTRY:
#
#   channel_configured_<name>   0 if it has what it needs, 1 otherwise
#   channel_limit_<name>        maximum message length in characters, 0 = none
#   channel_send_<name>         send "$1"; return 0 on delivery, non-zero not
#
# No function here may exit, and none may let a failure escape: `main` runs
# with errexit, and a health check that dies because its notifier is down is
# worse than no health check.
# ===========================================================================
CHANNEL_REGISTRY="discord slack email"

# --- discord ---------------------------------------------------------------
# POST {"content": "..."} to https://discord.com/api/webhooks/<id>/<token>.
# Hard limit 2000 characters on `content`; over that Discord answers 400 and
# drops the message, which would be a silent alerting failure. Rate limited
# with 429 + a JSON body carrying retry_after in (fractional) seconds.
# shellcheck disable=SC2329  # dispatched indirectly, see CHANNEL_REGISTRY
channel_configured_discord() { [ -n "$DISCORD_WEBHOOK_URL" ]; }
# shellcheck disable=SC2329  # dispatched indirectly, see CHANNEL_REGISTRY
channel_limit_discord()      { printf '2000'; }
# shellcheck disable=SC2329  # dispatched indirectly, see CHANNEL_REGISTRY
channel_send_discord() {
    local msg="$1" body
    body=$(jq -n --arg c "$msg" '{content: $c}') || return 1
    webhook_post "$DISCORD_WEBHOOK_URL" "$body" "discord"
}

# --- slack -----------------------------------------------------------------
# POST {"text": "..."} to an incoming-webhook URL. Slack's documented limit
# for a block's text is 3000 characters; the top-level `text` of a legacy
# incoming webhook is more generous, so 3000 is the conservative choice.
# Slack answers a plain "ok" body, and rate limits with 429 + Retry-After.
# shellcheck disable=SC2329  # dispatched indirectly, see CHANNEL_REGISTRY
channel_configured_slack() { [ -n "$SLACK_WEBHOOK" ]; }
# shellcheck disable=SC2329  # dispatched indirectly, see CHANNEL_REGISTRY
channel_limit_slack()      { printf '3000'; }
# shellcheck disable=SC2329  # dispatched indirectly, see CHANNEL_REGISTRY
channel_send_slack() {
    local msg="$1" body
    body=$(jq -n --arg t "$msg" '{text: $t}') || return 1
    webhook_post "$SLACK_WEBHOOK" "$body" "slack"
}

# --- email -----------------------------------------------------------------
# shellcheck disable=SC2329  # dispatched indirectly, see CHANNEL_REGISTRY
channel_configured_email() { [ -n "$EMAIL_RECIPIENT" ] && command -v mailx >/dev/null 2>&1; }
# shellcheck disable=SC2329  # dispatched indirectly, see CHANNEL_REGISTRY
channel_limit_email()      { printf '0'; }
# shellcheck disable=SC2329  # dispatched indirectly, see CHANNEL_REGISTRY
channel_send_email() {
    local msg="$1"
    printf '%s\n' "$msg" | mailx -s "bsdmirror alert" "$EMAIL_RECIPIENT" >/dev/null 2>&1
}

# ---------------------------------------------------------------------------
# webhook_post URL BODY CHANNEL
#
# The URL is a secret, so it is handed to curl through `--config -` on stdin
# rather than as an argument: an argument is visible to anyone who can run
# `ps` for as long as the request lasts. The body goes through a 0600 temp
# file for the same reason, even though it is not itself secret.
#
# Returns 0 only when the endpoint accepted the message.
# ---------------------------------------------------------------------------
# shellcheck disable=SC2329  # only reached from channel_send_*, dispatched indirectly
webhook_post() {
    local url="$1" body="$2" channel="$3"
    local attempt=1 bodyfile errfile out rc code resp wait

    # Validated before it is written into a curl config stream. A quote or a
    # backslash would be an escape sequence there, and an embedded newline
    # would let a mangled .env value inject an extra config directive --
    # `grep -E` alone would not catch that, because it matches per line.
    case "$url" in
        *$'\n'*|*$'\r'*)
            warn "$channel: webhook URL contains a line break; refusing to send"
            return 1 ;;
    esac
    if ! printf '%s' "$url" | grep -Eq '^https?://[^[:space:]"\\]+$'; then
        warn "$channel: webhook URL is not a plain http(s) URL; refusing to send"
        return 1
    fi

    bodyfile=$(mktemp "${TMPDIR:-/tmp}/bsdmirror-alert.XXXXXX") || return 1
    errfile=$(mktemp "${TMPDIR:-/tmp}/bsdmirror-alert-err.XXXXXX") || { rm -f "$bodyfile"; return 1; }
    printf '%s' "$body" > "$bodyfile"

    while :; do
        rc=0
        # `url = "..."` on stdin keeps the secret out of argv.
        out=$(printf 'url = "%s"\n' "$url" \
              | curl --config - \
                     --silent --show-error \
                     --request POST \
                     --header 'Content-Type: application/json' \
                     --data-binary "@$bodyfile" \
                     --max-time "$HTTP_TIMEOUT" \
                     --write-out $'\n%{http_code}' \
                     2>"$errfile") || rc=$?

        if [ "$rc" -ne 0 ]; then
            # Unreachable host, DNS failure, TLS failure, timeout. Report and
            # give up on this channel; never propagate.
            warn "$channel: curl failed (exit $rc): $(tr '\n' ' ' < "$errfile")"
            rm -f "$bodyfile" "$errfile"
            return 1
        fi

        code="${out##*$'\n'}"
        resp="${out%$'\n'*}"

        case "$code" in
            2*)
                rm -f "$bodyfile" "$errfile"
                return 0
                ;;
            429)
                # Discord: {"retry_after": 0.53}. Slack: Retry-After header.
                # Fall back to the attempt number when neither is readable.
                wait=$(printf '%s' "$resp" | jq -r '(.retry_after // empty) | tostring' 2>/dev/null || true)
                case "$wait" in
                    ''|*[!0-9.]*) wait="$attempt" ;;
                esac
                # Integer seconds, at least 1, capped: honouring an arbitrary
                # server-supplied sleep is how a timer unit hangs.
                wait=${wait%%.*}
                [ -n "$wait" ] && [ "$wait" -ge 1 ] 2>/dev/null || wait=1
                [ "$wait" -le "$ALERT_MAX_BACKOFF" ] || wait="$ALERT_MAX_BACKOFF"
                if [ "$attempt" -ge "$ALERT_MAX_ATTEMPTS" ]; then
                    warn "$channel: rate limited (429) and out of attempts after $attempt tries"
                    rm -f "$bodyfile" "$errfile"
                    return 1
                fi
                info "$channel: rate limited (429), retrying in ${wait}s (attempt $attempt/$ALERT_MAX_ATTEMPTS)"
                sleep "$wait"
                attempt=$((attempt + 1))
                ;;
            *)
                warn "$channel: endpoint returned HTTP $code: $(printf '%s' "$resp" | tr '\n' ' ' | cut -c1-200)"
                rm -f "$bodyfile" "$errfile"
                return 1
                ;;
        esac
    done
}

# ---------------------------------------------------------------------------
# Channel selection
# ---------------------------------------------------------------------------
SELECTED_CHANNELS=""

select_channels() {
    local requested name found
    if [ -n "$ALERT_CHANNELS" ]; then
        requested=$(printf '%s' "$ALERT_CHANNELS" | tr 'A-Z,;' 'a-z  ')
        for name in $requested; do
            found=0
            for known in $CHANNEL_REGISTRY; do
                [ "$name" = "$known" ] && found=1
            done
            if [ "$found" -eq 0 ]; then
                err "ALERT_CHANNELS names an unknown channel \"$name\" (known: $CHANNEL_REGISTRY)"
                return 1
            fi
            if ! "channel_configured_$name"; then
                # Loud, not silent: "I configured a channel and heard nothing"
                # is the failure this script exists to prevent.
                err "ALERT_CHANNELS requests \"$name\" but it is not configured; nothing will be delivered through it"
                return 1
            fi
            SELECTED_CHANNELS="$SELECTED_CHANNELS $name"
        done
        info "alert channels (from ALERT_CHANNELS):$SELECTED_CHANNELS"
    else
        # Derived from which channel VARIABLE is set. This is not URL
        # sniffing: no hostname is inspected, and the derivation is printed
        # on every run so it cannot be wrong quietly.
        for name in $CHANNEL_REGISTRY; do
            if "channel_configured_$name"; then
                SELECTED_CHANNELS="$SELECTED_CHANNELS $name"
            fi
        done
        if [ -n "$SELECTED_CHANNELS" ]; then
            info "alert channels (derived from configured variables, set ALERT_CHANNELS to pin):$SELECTED_CHANNELS"
        else
            warn "no alert channel is configured: set ALERT_CHANNELS and the matching variable in $ENV_FILE"
            warn "checks will still run and still exit non-zero, but nobody will be told"
        fi
    fi
    return 0
}

# ---------------------------------------------------------------------------
# Message shaping
#
# Sanitised to printable ASCII plus newline before anything else happens.
# Two reasons: a control character in a mirror name or an API response should
# not be able to inject anything into a webhook payload or a log line, and
# once the text is single-byte, truncating by length cannot split a UTF-8
# sequence and hand Discord a 400 for malformed JSON.
# ---------------------------------------------------------------------------
sanitize() {
    printf '%s' "$1" | LC_ALL=C tr -c '\11\12\40-\176' '?'
}

truncate_msg() {
    local msg="$1" limit="$2" marker
    if [ "$limit" -le 0 ] || [ "${#msg}" -le "$limit" ]; then
        printf '%s' "$msg"
        return 0
    fi
    marker=$'\n'"[truncated: $(( ${#msg} - limit )) more characters]"
    printf '%s%s' "${msg:0:$(( limit - ${#marker} ))}" "$marker"
}

build_message() {
    # Reads TRANSITIONS (five TAB-separated columns per record).
    local now_iso host
    local new_block="" remind_block="" recovered_block=""
    local kind key label detail since n_new=0 n_rem=0 n_rec=0
    now_iso=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    host="$ALERT_SOURCE_LABEL"
    [ -n "$host" ] || host="${DOMAIN:-$(hostname 2>/dev/null || echo unknown-host)}"

    local now_epoch
    now_epoch=$(date -u +%s)
    while IFS="$FS_US" read -r kind key label detail since; do
        [ -n "$kind" ] || continue
        case "$kind" in
            NEW)
                new_block="${new_block}  * ${label}: ${detail}"$'\n'
                n_new=$((n_new + 1)) ;;
            REMIND)
                remind_block="${remind_block}  * ${label}: ${detail} (bad for $(human_age $(( now_epoch - since ))))"$'\n'
                n_rem=$((n_rem + 1)) ;;
            RECOVERED)
                recovered_block="${recovered_block}  * ${label}: recovered (was bad for $(human_age $(( now_epoch - since ))))"$'\n'
                n_rec=$((n_rec + 1)) ;;
        esac
    done <<< "$TRANSITIONS"

    local out=""
    if [ "$n_new" -gt 0 ] || [ "$n_rem" -gt 0 ]; then
        out="[bsdmirror] ALERT - $host"
    else
        out="[bsdmirror] RECOVERED - $host"
    fi
    out="${out}"$'\n'"${now_iso}"$'\n'

    [ "$n_new" -gt 0 ] && out="${out}"$'\n'"NEW PROBLEMS ($n_new)"$'\n'"${new_block}"
    [ "$n_rem" -gt 0 ] && out="${out}"$'\n'"STILL BROKEN (${ALERT_REMIND_HOURS}h reminder) ($n_rem)"$'\n'"${remind_block}"
    [ "$n_rec" -gt 0 ] && out="${out}"$'\n'"RECOVERED ($n_rec)"$'\n'"${recovered_block}"

    out="${out}"$'\n'"$CHECKS_BAD condition(s) bad, $CHECKS_OK ok. journalctl -u bsdmirror-health -n 50"
    if [ "$STATE_DEGRADED" -eq 1 ]; then
        out="${out}"$'\n'"WARNING: alert dedup state could not be read or written, so this alert may repeat every run."
    fi
    sanitize "$out"
}

dispatch() {
    # $1 = message. Returns 0 if at least one channel accepted it.
    local msg="$1" name limit shaped delivered=0
    if [ -z "$SELECTED_CHANNELS" ]; then
        warn "alert not delivered: no channel configured"
        return 1
    fi
    for name in $SELECTED_CHANNELS; do
        limit=$("channel_limit_$name")
        shaped=$(truncate_msg "$msg" "$limit")
        if "channel_send_$name" "$shaped"; then
            info "delivered alert via $name (${#shaped} chars, limit ${limit})"
            delivered=1
        else
            warn "delivery via $name FAILED; the alert will be retried on the next run"
        fi
    done
    [ "$delivered" -eq 1 ]
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
main() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --dry-run)     DRY_RUN=1 ;;
            --test-alert)  MODE="test-alert" ;;
            --check-deps)  MODE="check-deps" ;;
            --show-state)  MODE="show-state" ;;
            --quiet|-q)    QUIET=1 ;;
            --insecure-tls) INSECURE_TLS=1 ;;
            # `shift` past the end aborts under errexit, so the missing
            # argument is checked rather than assumed.
            --state-file)  shift
                           [ "$#" -gt 0 ] || { err "--state-file needs a path"; exit 2; }
                           HEALTH_STATE_FILE="$1" ;;
            --env-file)    shift
                           [ "$#" -gt 0 ] || { err "--env-file needs a path"; exit 2; }
                           ENV_FILE="$1" ;;
            -h|--help)     usage; exit 0 ;;
            *) err "unknown argument: $1"; err "try --help"; exit 2 ;;
        esac
        shift
    done

    load_env

    # Same rule as scripts/deploy.sh: the public URL, because the backend is
    # not reachable from the host any other way.
    if [ -z "$API_URL" ]; then
        if [ -n "$DOMAIN" ] && [ "$DOMAIN" != "localhost" ]; then
            API_URL="https://$DOMAIN"
        else
            API_URL="http://localhost"
        fi
    fi

    # `1` is truthy for ${INSECURE_TLS:+...}; anything falsey must be empty.
    case "$INSECURE_TLS" in 0|false|no|"") INSECURE_TLS="" ;; esac

    redact_register "$DISCORD_WEBHOOK_URL"
    redact_register "$SLACK_WEBHOOK"

    require_deps || exit 2

    case "$MODE" in
        check-deps)
            info "prerequisites present"
            select_channels || exit 2
            [ -n "$SELECTED_CHANNELS" ] || exit 2
            exit 0
            ;;
        show-state)
            state_load
            printf '%s\n' "$STATE_JSON" | jq .
            exit 0
            ;;
        test-alert)
            select_channels || exit 2
            local host
            host="$ALERT_SOURCE_LABEL"
            [ -n "$host" ] || host="${DOMAIN:-$(hostname 2>/dev/null || echo unknown-host)}"
            if dispatch "$(sanitize "[bsdmirror] test alert - $host
$(date -u +%Y-%m-%dT%H:%M:%SZ)

This is a test from scripts/health_check.sh --test-alert.
If you can read this, alerting is wired up.")"; then
                exit 0
            fi
            exit 1
            ;;
    esac

    info "bsdmirror health check - $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    info "api base URL: $API_URL${INSECURE_TLS:+ (TLS verification DISABLED)}"
    info "================================================"

    select_channels || exit 2
    state_load

    # No `|| ((errors++))` anywhere: see the header. Each check appends to
    # BAD_RECORDS itself, and `|| true` keeps errexit out of the control flow.
    check_api        || true
    check_mirrors    || true
    check_disk       || true
    check_containers || true

    info "================================================"
    info "$CHECKS_BAD bad, $CHECKS_OK ok"

    local now
    now=$(date -u +%s)
    # Plain call, NOT `x=$(reconcile ...)`: it updates STATE_JSON, and a
    # command substitution would run it in a subshell and throw that away.
    reconcile "$now"

    if [ -z "$TRANSITIONS" ]; then
        if [ "$CHECKS_BAD" -gt 0 ]; then
            info "no change since the last run; staying quiet (next reminder after ${ALERT_REMIND_HOURS}h)"
        else
            info "all checks passed"
        fi
    else
        local message
        message=$(build_message)
        if [ "$DRY_RUN" -eq 1 ]; then
            info "--dry-run: would send the following message:"
            printf -- '---8<---\n%s\n--->8---\n' "$message"
        else
            local notify_keys=()
            while IFS="$FS_US" read -r kind key _rest; do
                case "$kind" in NEW|REMIND) notify_keys+=("$key") ;; esac
            done <<< "$TRANSITIONS"
            if dispatch "$message"; then
                if [ "${#notify_keys[@]}" -gt 0 ]; then
                    state_mark_notified "$now" "${notify_keys[@]}"
                fi
            else
                # Not marked as notified on purpose: an undelivered alert must
                # be re-attempted next run, otherwise a webhook outage during
                # the transition suppresses that problem forever.
                warn "alert was not delivered to any channel; it will be retried next run"
            fi
        fi
    fi

    if [ "$DRY_RUN" -eq 0 ]; then
        state_save || true
    fi

    [ "$CHECKS_BAD" -eq 0 ] || exit 1
    exit 0
}

main "$@"
