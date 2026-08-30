#!/usr/bin/env bash
#
# bsdmirror - gated deploy
#
# Why this exists
# ---------------
# This repo's first 36 commits contain 30 post-deploy "Fix ..." commits. The
# loop that produces them is: push, pull on the server, find out. On
# 2026-08-30 a push to main was pulled to production within minutes, before CI
# had finished its first run on that SHA; the same rebuild also moved bcrypt
# from 4.x to 5.0.0 in the login path unreviewed. Both were fine. Neither was
# checked.
#
# This script makes that specific sequence hard. It refuses to deploy a SHA
# whose CI is not green, refuses to deploy on top of uncommitted work, refuses
# to interrupt a running rsync, and verifies afterwards -- including a login
# round-trip, which is the check that would have caught a broken bcrypt bump.
#
# It touches only `backend` and `sync`. nginx, postgres and redis are never
# built, recreated or restarted by this script.
#
# Usage
# -----
#   scripts/deploy.sh [REF]                 deploy a ref (default: main)
#   scripts/deploy.sh --rollback <SHA>      redeploy a previous SHA
#   scripts/deploy.sh --ci-check-only <REF> evaluate the CI gate and exit
#   scripts/deploy.sh --help
#
# Exit codes -- these are the contract, do not renumber casually:
#   0  deployed and verified
#   1  usage or preflight error, nothing touched
#   2  a gate refused, nothing touched
#   3  deploy step failed; git may have moved, but the running containers
#      were NOT replaced -- the service is still up on the old images
#   4  deploy succeeded but verification failed -- NEW CODE IS SERVING
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration (every one of these is overridable, none has to be edited)
# ---------------------------------------------------------------------------
DEPLOY_DIR="${DEPLOY_DIR:-/opt/bsdmirror}"
REPO_SLUG="${REPO_SLUG:-}"                 # derived from origin if empty
REQUIRED_CHECK="${REQUIRED_CHECK:-CI}"     # aggregate job in .github/workflows/ci.yml
BASE_URL="${BASE_URL:-}"                   # derived from DOMAIN in .env if empty
SERVICES="backend sync"                    # deliberately not configurable
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"    # seconds to wait for backend healthy
SYNC_SETTLE="${SYNC_SETTLE:-20}"           # seconds to watch sync for a crash loop
API_TIMEOUT="${API_TIMEOUT:-90}"           # seconds to wait for /api/health
GITHUB_API="${GITHUB_API:-https://api.github.com}"

TARGET_REF="main"
MODE="deploy"                              # deploy | rollback | ci-check-only
ALLOW_DIRTY=0
FORCE_NO_CI=0
FORCE_SYNC_RESTART=0
ASSUME_YES=0
DRY_RUN=0
INSECURE_TLS=0

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    C_RED=$'\033[0;31m'; C_GRN=$'\033[0;32m'; C_YEL=$'\033[1;33m'
    C_BLU=$'\033[0;36m'; C_BLD=$'\033[1m';    C_OFF=$'\033[0m'
else
    C_RED=""; C_GRN=""; C_YEL=""; C_BLU=""; C_BLD=""; C_OFF=""
fi

info() { printf '%s[INFO]%s %s\n' "$C_GRN" "$C_OFF" "$*"; }
warn() { printf '%s[WARN]%s %s\n' "$C_YEL" "$C_OFF" "$*" >&2; }
err()  { printf '%s[ERROR]%s %s\n' "$C_RED" "$C_OFF" "$*" >&2; }
step() { printf '\n%s==>%s %s%s%s\n' "$C_BLU" "$C_OFF" "$C_BLD" "$*" "$C_OFF"; }
ok()   { printf '  %s[ OK ]%s %s\n' "$C_GRN" "$C_OFF" "$*"; }
bad()  { printf '  %s[FAIL]%s %s\n' "$C_RED" "$C_OFF" "$*" >&2; }

banner() {
    # banner COLOR TITLE [line...]
    local color="$1" title="$2"; shift 2
    printf '\n%s%s\n' "$color" "========================================================================"
    printf '  %s\n' "$title"
    printf '%s\n' "========================================================================$C_OFF"
    local line
    for line in "$@"; do printf '  %s\n' "$line"; done
    printf '%s\n' "${color}========================================================================${C_OFF}"
}

usage() {
    # Print the contiguous comment block after the shebang and stop at the
    # first line of code. A hardcoded line range here would silently start
    # leaking `set -euo pipefail` into --help the moment the header grew.
    awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "$0"
    cat <<'USAGE'

Options:
  --rollback SHA          Redeploy a previous commit (detached HEAD).
                          Mutually exclusive with a REF argument.
  --ci-check-only         Evaluate the CI gate for the ref and exit. Touches
                          nothing, needs no docker and no deploy directory.
  --dry-run               Run every gate, print the deploy commands, execute
                          none of them.
  --dir PATH              Deploy directory (default: /opt/bsdmirror).
  --repo OWNER/NAME       GitHub repo to read check-runs from. Default: derived
                          from `git remote get-url origin`.
  --required-check NAME   Aggregate check-run that must be green (default: CI).
  --url URL               Base URL for post-deploy verification. Default:
                          https://$DOMAIN, read from .env.
  --insecure-tls          Skip TLS verification when probing. Use only with a
                          Let's Encrypt *staging* certificate.
  -y, --yes               Do not prompt for confirmation.
  -h, --help              This text.

Escape hatches. Each prints a loud banner naming what it bypassed:
  --allow-dirty           Deploy even though tracked files are modified.
  --force-no-ci           Deploy even though CI is not green / has not run.
                          Requires an interactive typed confirmation; refuses
                          outright when stdin is not a terminal.
  --force-sync-restart    Restart the sync service even though an rsync is in
                          progress. This kills the transfer.

Environment: DEPLOY_DIR REPO_SLUG REQUIRED_CHECK BASE_URL HEALTH_TIMEOUT
             SYNC_SETTLE API_TIMEOUT GITHUB_API GITHUB_TOKEN NO_COLOR
GITHUB_TOKEN is optional. The repo is public, so the check-runs endpoint is
readable anonymously; a token only raises the 60-request/hour rate limit.
USAGE
}

# ---------------------------------------------------------------------------
# Half-deploy reporting. PHASE is the single source of truth for what the
# stack looks like if we die unexpectedly, so nothing exits quietly from the
# middle of a deploy.
# ---------------------------------------------------------------------------
PHASE="startup"
PREV_SHA=""
TARGET_SHA=""

on_exit() {
    local rc=$?
    [ "$rc" -eq 0 ] && return 0
    case "$PHASE" in
        moving-git)
            banner "$C_RED" "STOPPED WHILE MOVING THE CHECKOUT" \
                "The git checkout may have moved, but no image was rebuilt and no" \
                "container was recreated. The stack is still serving the old code." \
                "" \
                "Restore the checkout with:" \
                "  cd $DEPLOY_DIR && git checkout ${PREV_SHA:-<previous sha>}"
            ;;
        building)
            banner "$C_YEL" "STOPPED DURING BUILD" \
                "Images were being rebuilt. No container was recreated, so the" \
                "stack is still serving the old code -- users are unaffected." \
                "" \
                "The checkout is now at ${TARGET_SHA:-<target>}; it was at ${PREV_SHA:-<unknown>}." \
                "  cd $DEPLOY_DIR && git checkout ${PREV_SHA:-<previous sha>}"
            ;;
        recreating|verifying)
            banner "$C_RED" "STOPPED WITH THE NEW CODE ALREADY SERVING" \
                "backend and/or sync were recreated on images built from" \
                "${TARGET_SHA:-<target>} and are handling live traffic RIGHT NOW." \
                "This deploy is NOT verified." \
                "" \
                "Roll back with:" \
                "  cd $DEPLOY_DIR && scripts/deploy.sh --rollback ${PREV_SHA:-<previous sha>}" \
                "" \
                "Inspect first with:" \
                "  docker compose ps && docker compose logs --tail=100 backend sync"
            ;;
    esac
    return 0
}
trap on_exit EXIT

die()      { err "$*"; exit 1; }
die_gate() { err "$*"; exit 2; }

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
ROLLBACK_SHA=""
positional_seen=0
while [ $# -gt 0 ]; do
    case "$1" in
        --rollback)          MODE="rollback"; ROLLBACK_SHA="${2:-}"; shift 2 || die "--rollback needs a SHA" ;;
        --ci-check-only)     MODE="ci-check-only"; shift ;;
        --dry-run)           DRY_RUN=1; shift ;;
        --dir)               DEPLOY_DIR="${2:-}"; shift 2 || die "--dir needs a path" ;;
        --repo)              REPO_SLUG="${2:-}"; shift 2 || die "--repo needs OWNER/NAME" ;;
        --required-check)    REQUIRED_CHECK="${2:-}"; shift 2 || die "--required-check needs a name" ;;
        --url)               BASE_URL="${2:-}"; shift 2 || die "--url needs a URL" ;;
        --insecure-tls)      INSECURE_TLS=1; shift ;;
        --allow-dirty)       ALLOW_DIRTY=1; shift ;;
        --force-no-ci)       FORCE_NO_CI=1; shift ;;
        --force-sync-restart) FORCE_SYNC_RESTART=1; shift ;;
        -y|--yes)            ASSUME_YES=1; shift ;;
        -h|--help)           usage; exit 0 ;;
        --) shift; break ;;
        -*) die "unknown option: $1  (try --help)" ;;
        *)
            [ "$positional_seen" -eq 1 ] && die "only one REF may be given (got a second: $1)"
            TARGET_REF="$1"; positional_seen=1; shift ;;
    esac
done

if [ "$MODE" = "rollback" ]; then
    [ -n "$ROLLBACK_SHA" ] || die "--rollback needs a SHA"
    [ "$positional_seen" -eq 0 ] || die "--rollback and a REF argument are mutually exclusive: pick one"
    TARGET_REF="$ROLLBACK_SHA"
fi

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
need_cmd() { command -v "$1" >/dev/null 2>&1 || die "required command not found: $1${2:+  ($2)}"; }

preflight_common() {
    need_cmd git
    need_cmd curl
    # The CI gate parses the GitHub API response. That parse decides whether a
    # deploy happens, so it is done with a real JSON parser -- a grep for
    # '"conclusion": "failure"' would also match the string inside a check run's
    # `output.text`, and would green-light a red deploy. python3 ships with
    # Debian/Ubuntu server; jq does not, and scripts/setup.sh installs neither.
    command -v python3 >/dev/null 2>&1 || die \
        "python3 is required to parse the GitHub check-runs API. Install it with: apt-get install -y python3"
}

preflight_deploy() {
    need_cmd docker
    docker compose version >/dev/null 2>&1 || die "'docker compose' (v2) is not available"
    [ -d "$DEPLOY_DIR" ]      || die "deploy directory does not exist: $DEPLOY_DIR"
    cd "$DEPLOY_DIR"
    git rev-parse --git-dir >/dev/null 2>&1 || die "$DEPLOY_DIR is not a git working tree"
    [ -f docker-compose.yml ] || die "$DEPLOY_DIR/docker-compose.yml not found"
    [ -f .env ] || warn "$DEPLOY_DIR/.env not found -- compose will substitute empty strings for every \${VAR}"
}

# Read one non-secret key out of .env. Deliberately narrow: this never sources
# .env and never prints a value it was not asked for. The four secrets in that
# file (POSTGRES_PASSWORD, REDIS_PASSWORD, SECRET_KEY, ADMIN_PASSWORD) must
# never be read here.
env_get() {
    local key="$1" default="${2:-}" value
    case "$key" in
        *PASSWORD*|SECRET_KEY|*TOKEN*)
            err "internal: env_get refused to read secret key '$key'"; return 1 ;;
    esac
    [ -f "$DEPLOY_DIR/.env" ] || { printf '%s' "$default"; return 0; }
    value=$(grep -m1 "^${key}=" "$DEPLOY_DIR/.env" 2>/dev/null | cut -d= -f2- || true)
    printf '%s' "${value:-$default}"
}

derive_repo_slug() {
    [ -n "$REPO_SLUG" ] && return 0
    local url
    url=$(git -C "$DEPLOY_DIR" remote get-url origin 2>/dev/null || echo "")
    case "$url" in
        *github.com[:/]*)
            REPO_SLUG=$(printf '%s' "$url" | sed -E 's#^.*github\.com[:/]##; s#\.git$##') ;;
    esac
    [ -n "$REPO_SLUG" ] || die "could not derive the GitHub repo from origin ($url); pass --repo OWNER/NAME"
}

# ---------------------------------------------------------------------------
# Gate 1: CI must be green for this exact SHA
# ---------------------------------------------------------------------------
CI_STATE=""

evaluate_ci() {
    local sha="$1"
    local body headers table url http rc
    body=$(mktemp); headers=$(mktemp); table=$(mktemp)
    # shellcheck disable=SC2064  # expand now: these paths must not change
    trap "rm -f '$body' '$headers' '$table'" RETURN

    url="$GITHUB_API/repos/$REPO_SLUG/commits/$sha/check-runs?per_page=100"
    info "GET $url"

    local curl_args
    curl_args=(-sS -o "$body" -D "$headers" -w '%{http_code}'
               --max-time 25 --retry 2 --retry-delay 2 --retry-connrefused
               -H 'Accept: application/vnd.github+json'
               -H 'X-GitHub-Api-Version: 2022-11-28')
    [ -n "${GITHUB_TOKEN:-}" ] && curl_args+=(-H "Authorization: Bearer $GITHUB_TOKEN")

    set +e
    http=$(curl "${curl_args[@]}" "$url")
    rc=$?
    set -e

    if [ "$rc" -ne 0 ]; then
        CI_STATE="APIERR"
        bad "curl failed (exit $rc) talking to $GITHUB_API"
        return 0
    fi

    case "$http" in
        200) : ;;
        422)
            # Verified against the live API on 2026-08-30: a well-formed SHA
            # that is not in the repository returns 422 "No commit found for
            # SHA", not 404. 404 from this endpoint means the *repository* is
            # unreadable. Both refuse, but they need different fixes.
            CI_STATE="NOTFOUND"
            bad "HTTP 422 - $REPO_SLUG has no commit $sha"
            bad "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("message","")[:200])' "$body" 2>/dev/null)"
            bad "the commit exists locally but was never pushed, or --repo is wrong"
            return 0 ;;
        404)
            CI_STATE="NOTFOUND"
            bad "HTTP 404 - $REPO_SLUG is not readable anonymously (missing, renamed, or private)"
            bad "fix --repo, or set GITHUB_TOKEN if the repository is private"
            return 0 ;;
        403|429)
            CI_STATE="APIERR"
            bad "HTTP $http from the GitHub API$(grep -i '^x-ratelimit-remaining:' "$headers" | tr -d '\r' | sed 's/^/ - /')"
            warn "anonymous rate limit is 60 requests/hour per IP; set GITHUB_TOKEN to raise it"
            return 0 ;;
        *)
            CI_STATE="APIERR"
            bad "HTTP $http from the GitHub API"
            return 0 ;;
    esac

    local summary
    summary=$(python3 - "$body" "$REQUIRED_CHECK" "$table" <<'PY'
import json, sys

path, required, table_path = sys.argv[1], sys.argv[2], sys.argv[3]

def emit(state, total=0, fetched=0, incomplete=0, failed=0, nonfail=0, req="-", note="-"):
    print(state, total, fetched, incomplete, failed, nonfail, req, note)
    sys.exit(0)

try:
    with open(path) as fh:
        doc = json.load(fh)
except Exception as exc:                       # noqa: BLE001
    emit("PARSE_ERROR", note=str(exc).replace(" ", "_")[:80])

if not isinstance(doc, dict) or not isinstance(doc.get("check_runs"), list):
    msg = doc.get("message", "unexpected_shape") if isinstance(doc, dict) else "unexpected_shape"
    emit("PARSE_ERROR", note=str(msg).replace(" ", "_")[:80])

runs = doc["check_runs"]
total = doc.get("total_count", len(runs))
fetched = len(runs)

with open(table_path, "w") as out:
    for r in sorted(runs, key=lambda r: (r.get("name") or "", r.get("started_at") or "")):
        out.write("%-34s %-11s %-14s %s\n" % (
            (r.get("name") or "?")[:34],
            r.get("status") or "?",
            str(r.get("conclusion")),
            r.get("started_at") or "",
        ))

# GitHub's non-failing conclusions. Anything else -- failure, cancelled,
# timed_out, action_required, stale, or a null conclusion on a "completed" run
# -- is treated as red. Fail closed on values this script has not seen before.
NONFAIL = {"success", "skipped", "neutral"}

incomplete = [r for r in runs if r.get("status") != "completed"]
failed = [r for r in runs if r.get("status") == "completed"
          and (r.get("conclusion") or "null") not in NONFAIL]
nonfail = fetched - len(incomplete) - len(failed)

# Duplicate names appear when one SHA produces more than one check suite (this
# workflow runs on both `push` and `pull_request`). Every run is evaluated, so
# one red suite is enough to refuse even if a second suite is green.
req_runs = [r for r in runs if r.get("name") == required]
req_state = "absent" if not req_runs else "/".join(
    sorted({(r.get("conclusion") or r.get("status") or "?") for r in req_runs}))

if fetched < total:
    emit("PAGINATED", total, fetched, len(incomplete), len(failed), nonfail, req_state)
if total == 0:
    emit("NONE", total, fetched, 0, 0, 0, req_state)
if incomplete:
    emit("PENDING", total, fetched, len(incomplete), len(failed), nonfail, req_state)
if failed:
    emit("RED", total, fetched, len(incomplete), len(failed), nonfail, req_state)
if not req_runs:
    emit("MISSING_REQUIRED", total, fetched, len(incomplete), len(failed), nonfail, req_state)
emit("GREEN", total, fetched, len(incomplete), len(failed), nonfail, req_state)
PY
)

    # Field-by-field read, never eval, and never `set -- $summary`: this string
    # is derived from a network response, so it must not be word-split into
    # positional parameters where a `*` would glob against the working
    # directory. `read` from a heredoc runs in this shell, so the assignments
    # stick.
    local total fetched incomplete failed nonfail reqstate note
    CI_STATE=""
    IFS=' ' read -r CI_STATE total fetched incomplete failed nonfail reqstate note <<EOF
$summary
EOF
    : "${CI_STATE:=PARSE_ERROR}" "${total:=0}" "${fetched:=0}" "${incomplete:=0}"
    : "${failed:=0}" "${nonfail:=0}" "${reqstate:=-}" "${note:=-}"

    if [ -s "$table" ]; then
        printf '\n  %-34s %-11s %-14s %s\n' "CHECK" "STATUS" "CONCLUSION" "STARTED"
        sed 's/^/  /' "$table"
        printf '\n'
    fi

    case "$CI_STATE" in
        GREEN)
            ok "CI is green for $sha"
            ok "$nonfail/$total check runs non-failing; required check '$REQUIRED_CHECK' = $reqstate" ;;
        RED)
            bad "CI is RED for $sha - $failed of $total check runs did not pass"
            bad "required check '$REQUIRED_CHECK' = $reqstate" ;;
        PENDING)
            bad "CI has not finished for $sha - $incomplete of $total check runs are still queued or running"
            bad "this is the exact case that produced the 2026-08-30 deploy: wait for it" ;;
        NONE)
            bad "NO CHECK RUNS EXIST for $sha (HTTP 200, total_count 0)"
            bad "this is NOT the same as green. A commit that was never pushed, was pushed"
            bad "to a branch the workflow ignores, or predates .github/workflows/ci.yml"
            bad "returns exactly this. Nothing has tested this SHA." ;;
        MISSING_REQUIRED)
            bad "no check run named '$REQUIRED_CHECK' exists for $sha, though $total others do"
            bad "the aggregate job in .github/workflows/ci.yml was renamed or did not run" ;;
        PAGINATED)
            bad "the API reports $total check runs but returned $fetched; this script does not paginate"
            bad "refusing rather than judging a partial result" ;;
        PARSE_ERROR)
            bad "could not parse the check-runs response: $note" ;;
        *)
            CI_STATE="PARSE_ERROR"; bad "unrecognised gate state" ;;
    esac
}

require_ci_green() {
    local sha="$1"
    step "Gate 1/3: CI status for $sha"
    evaluate_ci "$sha"

    [ "$CI_STATE" = "GREEN" ] && return 0

    if [ "$FORCE_NO_CI" -eq 1 ]; then
        banner "$C_RED" "BYPASSING THE CI GATE (--force-no-ci)" \
            "CI state for this SHA is: $CI_STATE" \
            "" \
            "You are about to put code on a live mirror that CI has not passed." \
            "The only routinely defensible use of this flag is rolling BACK to a" \
            "SHA that predates the CI workflow during an active incident."
        if [ ! -t 0 ]; then
            err "--force-no-ci requires an interactive terminal. Refusing."
            exit 2
        fi
        printf '  Type exactly: %sdeploy without ci%s\n  > ' "$C_BLD" "$C_OFF"
        local answer; read -r answer
        [ "$answer" = "deploy without ci" ] || die_gate "confirmation did not match; nothing was done"
        warn "CI gate bypassed by explicit operator confirmation"
        return 0
    fi

    err "refusing to deploy. Re-run when CI is green, or --force-no-ci to override."
    exit 2
}

# ---------------------------------------------------------------------------
# Gate 2: the working tree must be clean, ignoring mode-only churn
# ---------------------------------------------------------------------------
# scripts/setup.sh:458 runs `chmod +x "$INSTALL_DIR/scripts/"*.sh`, but only
# scripts/ssl-setup.sh is 100755 in git; backup.sh, health_check.sh and
# setup.sh are 100644. So a correctly set up server permanently shows three
# mode-only diffs. Blocking on those would train the operator to reach for
# --allow-dirty on every deploy, which would then also wave through real edits.
# `-c core.fileMode=false` makes git ignore the executable bit for one
# invocation; content changes still show.
require_clean_tree() {
    step "Gate 2/3: working tree at $DEPLOY_DIR"
    local raw content
    raw=$(git status --porcelain --untracked-files=no || true)
    content=$(git -c core.fileMode=false status --porcelain --untracked-files=no || true)

    if [ -n "$raw" ] && [ -z "$content" ]; then
        ok "only mode-only differences, ignoring them (setup.sh chmod +x):"
        printf '%s\n' "$raw" | sed 's/^/        /'
        return 0
    fi

    if [ -z "$content" ]; then
        ok "clean (no modified tracked files)"
        return 0
    fi

    bad "tracked files have uncommitted content changes:"
    printf '%s\n' "$content" | sed 's/^/        /'
    printf '\n'
    git -c core.fileMode=false --no-pager diff --stat | sed 's/^/        /' || true

    if [ "$ALLOW_DIRTY" -eq 1 ]; then
        banner "$C_RED" "BYPASSING THE CLEAN-TREE GATE (--allow-dirty)" \
            "The files listed above differ from the committed tree. Whatever is in" \
            "them is about to be built into the images and served." \
            "" \
            "These edits exist only on this server. They are not in git, they were" \
            "not reviewed, CI never saw them, and the next 'git pull --ff-only'" \
            "will fail or silently discard them."
        return 0
    fi

    err "refusing to deploy. Commit, stash, or restore these files -- or --allow-dirty to override."
    exit 2
}

# ---------------------------------------------------------------------------
# Gate 3: do not interrupt a running rsync
# ---------------------------------------------------------------------------
# `docker compose up -d sync` recreates the container, which SIGTERMs the sync
# service, which terminates the in-flight rsync (sync_service.py:804-810) and
# then has 10 seconds before docker SIGKILLs it. Two consequences: hours of
# transfer are thrown away, and if the DB write does not land in that window
# the mirror is left at MirrorStatus.SYNCING, which admin.py:301 then treats as
# "already syncing" and rejects every manual retry. There is no reaper. That
# state is not recoverable from the UI.
require_no_sync_in_progress() {
    step "Gate 3/3: sync activity"
    local pg_user pg_db running
    pg_user=$(env_get POSTGRES_USER bsdmirrors)
    pg_db=$(env_get POSTGRES_DB bsdmirrors)

    set +e
    running=$(docker compose exec -T postgres \
        psql -U "$pg_user" -d "$pg_db" -tAc \
        "SELECT count(*) FROM sync_jobs WHERE upper(status::text) = 'RUNNING'" 2>/dev/null | tr -d ' \r')
    local rc=$?
    set -e

    if [ "$rc" -ne 0 ] || [ -z "$running" ] || ! printf '%s' "$running" | grep -q '^[0-9]\+$'; then
        warn "could not determine sync state (psql query failed or returned '$running')"
        warn "proceeding would restart the sync container blind"
        if [ "$ASSUME_YES" -eq 1 ] || [ "$FORCE_SYNC_RESTART" -eq 1 ]; then
            warn "continuing anyway (--yes / --force-sync-restart)"
            return 0
        fi
        confirm "Continue without knowing whether an rsync is running?" || die_gate "aborted"
        return 0
    fi

    if [ "$running" -eq 0 ]; then
        ok "no sync_jobs in RUNNING state"
        return 0
    fi

    bad "$running sync job(s) are RUNNING right now"
    docker compose exec -T postgres psql -U "$pg_user" -d "$pg_db" -tAc \
        "SELECT m.name, j.started_at FROM sync_jobs j JOIN mirrors m ON m.id = j.mirror_id
         WHERE upper(j.status::text) = 'RUNNING'" 2>/dev/null | sed 's/^/        /' || true

    if [ "$FORCE_SYNC_RESTART" -eq 1 ]; then
        banner "$C_RED" "BYPASSING THE SYNC GATE (--force-sync-restart)" \
            "Recreating the sync container will SIGTERM the running rsync." \
            "" \
            "You will lose the in-progress transfer, and if the status write does" \
            "not complete inside docker's 10s grace period the mirror is left at" \
            "SYNCING with no way to clear it from the admin UI (admin.py:301" \
            "rejects retries while a mirror is SYNCING, and no reaper exists)." \
            "" \
            "Clearing it afterwards needs a manual UPDATE against postgres."
        return 0
    fi

    err "refusing to deploy. Wait for the sync to finish, or --force-sync-restart to override."
    exit 2
}

confirm() {
    [ "$ASSUME_YES" -eq 1 ] && return 0
    if [ ! -t 0 ]; then
        err "stdin is not a terminal and --yes was not given: $1"
        return 1
    fi
    local answer
    printf '  %s [y/N] ' "$1"
    read -r answer
    case "$answer" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

# ---------------------------------------------------------------------------
# Ref resolution
# ---------------------------------------------------------------------------
CHECKOUT_STYLE=""   # branch | detached

resolve_target() {
    step "Resolving $TARGET_REF"
    info "git fetch --prune origin"
    if [ "$DRY_RUN" -eq 0 ] || true; then
        git fetch --prune --tags origin >/dev/null 2>&1 \
            || die "git fetch failed -- cannot verify the target ref against origin"
    fi

    if [ "$MODE" != "rollback" ] && git rev-parse --verify --quiet "refs/remotes/origin/$TARGET_REF" >/dev/null; then
        CHECKOUT_STYLE="branch"
        TARGET_SHA=$(git rev-parse --verify "refs/remotes/origin/$TARGET_REF^{commit}")
    elif git rev-parse --verify --quiet "${TARGET_REF}^{commit}" >/dev/null; then
        CHECKOUT_STYLE="detached"
        TARGET_SHA=$(git rev-parse --verify "${TARGET_REF}^{commit}")
    else
        die "cannot resolve '$TARGET_REF' to a commit, even after fetching origin"
    fi

    ok "$TARGET_REF -> $TARGET_SHA  ($CHECKOUT_STYLE checkout)"
    git --no-pager log -1 --format='        %h  %an  %ad%n        %s' --date=short "$TARGET_SHA"
}

# ---------------------------------------------------------------------------
# Deploy
# ---------------------------------------------------------------------------
run() {
    printf '  %s$%s %s\n' "$C_BLD" "$C_OFF" "$*"
    if [ "$DRY_RUN" -eq 1 ]; then
        printf '    (--dry-run: not executed)\n'
        return 0
    fi
    "$@"
}

dependencies_must_be_up() {
    # This script never touches postgres, redis or nginx. That is only safe if
    # they are already running: `up -d --no-deps backend sync` will happily
    # start a backend against a database that is not there.
    local svc cid state
    for svc in postgres redis nginx; do
        cid=$(docker compose ps -q "$svc" 2>/dev/null || true)
        if [ -z "$cid" ]; then
            die_gate "service '$svc' is not running. This script deploys only backend and sync and will not start it. Bring the stack up first: docker compose up -d"
        fi
        state=$(docker inspect -f '{{.State.Status}}' "$cid")
        [ "$state" = "running" ] || die_gate "service '$svc' is '$state', not running. Fix that before deploying."
        ok "$svc is running (left untouched)"
    done
}

move_checkout() {
    PHASE="moving-git"
    step "Moving the checkout to $TARGET_SHA"
    if [ "$CHECKOUT_STYLE" = "branch" ]; then
        local current
        current=$(git symbolic-ref --quiet --short HEAD || echo "")
        if [ "$current" != "$TARGET_REF" ]; then
            info "HEAD is on '${current:-detached HEAD}', switching to '$TARGET_REF'"
            run git checkout "$TARGET_REF"
        fi
        # `git merge --ff-only <sha>` rather than `git pull --ff-only`: same
        # fast-forward-or-refuse semantics, but it lands on the exact SHA whose
        # CI was just verified. A plain pull would take whatever origin/main
        # points at now, which is not necessarily what the gate approved.
        run git merge --ff-only "$TARGET_SHA"
    else
        run git checkout --detach "$TARGET_SHA"
    fi

    if [ "$DRY_RUN" -eq 0 ]; then
        local now; now=$(git rev-parse HEAD)
        [ "$now" = "$TARGET_SHA" ] || die "checkout landed on $now, expected $TARGET_SHA"
        ok "HEAD is $now"
    fi
}

build_and_up() {
    PHASE="building"
    step "Building images for: $SERVICES"
    # Build first, recreate second. A failed build then leaves the running
    # containers alone, so the mirror keeps serving while it is investigated.
    # shellcheck disable=SC2086  # SERVICES is a deliberate word-split list
    if ! run docker compose build $SERVICES; then
        PHASE="build-failed"
        banner "$C_YEL" "BUILD FAILED - NOTHING WAS RECREATED" \
            "The running containers were not touched. The mirror is still serving" \
            "the previous images and users are unaffected." \
            "" \
            "The checkout has moved to $TARGET_SHA (was $PREV_SHA)." \
            "Restore it with:  cd $DEPLOY_DIR && git checkout $PREV_SHA"
        exit 3
    fi
    ok "images built"

    PHASE="recreating"
    step "Recreating: $SERVICES  (--no-deps: nginx, postgres and redis untouched)"
    # shellcheck disable=SC2086
    if ! run docker compose up -d --no-deps $SERVICES; then
        banner "$C_RED" "RECREATE FAILED PART-WAY" \
            "docker compose up returned non-zero. One of backend/sync may be" \
            "running new code while the other is not." \
            "" \
            "  docker compose ps" \
            "  docker compose logs --tail=100 backend sync" \
            "  scripts/deploy.sh --rollback $PREV_SHA"
        exit 3
    fi
    ok "containers recreated"
}

# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
VERIFY_FAILURES=0
vfail() { bad "$*"; VERIFY_FAILURES=$((VERIFY_FAILURES + 1)); }

curl_base() {
    local args
    args=(-sS --max-time 20)
    [ "$INSECURE_TLS" -eq 1 ] && args+=(-k)
    printf '%s\n' "${args[@]}"
}

verify_container_health() {
    local cid health status timeout="$1" waited=0
    cid=$(docker compose ps -q backend 2>/dev/null || true)
    [ -n "$cid" ] || { vfail "backend has no container"; return 0; }

    while :; do
        health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")
        status=$(docker inspect -f '{{.State.Status}}' "$cid")
        [ "$status" = "running" ] || { vfail "backend container is '$status'"; return 0; }
        case "$health" in
            healthy) ok "backend is healthy (${waited}s)"; break ;;
            none)    warn "backend has no healthcheck; accepting 'running'"; break ;;
            unhealthy)
                vfail "backend healthcheck reports unhealthy"
                docker inspect -f '{{range .State.Health.Log}}{{.Output}}{{end}}' "$cid" | tail -5 | sed 's/^/        /'
                return 0 ;;
        esac
        [ "$waited" -ge "$timeout" ] && { vfail "backend still '$health' after ${timeout}s"; return 0; }
        sleep 5; waited=$((waited + 5))
    done

    # docker-compose.yml defines no healthcheck for `sync`, so "healthy" is not
    # available. Watch for a crash loop instead: a container that keeps dying is
    # restarted by `restart: unless-stopped` and looks "running" between deaths.
    cid=$(docker compose ps -q sync 2>/dev/null || true)
    [ -n "$cid" ] || { vfail "sync has no container"; return 0; }
    local r0 r1
    r0=$(docker inspect -f '{{.RestartCount}}' "$cid")
    info "watching sync for ${SYNC_SETTLE}s (no healthcheck defined for it)"
    sleep "$SYNC_SETTLE"
    status=$(docker inspect -f '{{.State.Status}}' "$cid")
    r1=$(docker inspect -f '{{.RestartCount}}' "$cid")
    if [ "$status" != "running" ]; then
        vfail "sync container is '$status' after ${SYNC_SETTLE}s"
        docker compose logs --tail=30 sync | sed 's/^/        /' || true
    elif [ "$r1" != "$r0" ]; then
        vfail "sync restarted $((r1 - r0)) time(s) in ${SYNC_SETTLE}s -- it is crash-looping"
        docker compose logs --tail=30 sync | sed 's/^/        /' || true
    else
        ok "sync is running and has not restarted (RestartCount $r1)"
    fi
}

verify_api_health() {
    local waited=0 code body opts
    opts=$(curl_base)
    while :; do
        set +e
        # shellcheck disable=SC2086
        code=$(curl $opts -o /dev/null -w '%{http_code}' "$BASE_URL/api/health" 2>/dev/null)
        set -e
        [ "$code" = "200" ] && break
        if [ "$waited" -ge "$API_TIMEOUT" ]; then
            vfail "GET $BASE_URL/api/health returned $code after ${API_TIMEOUT}s (want 200)"
            return 0
        fi
        sleep 5; waited=$((waited + 5))
    done
    # shellcheck disable=SC2086
    body=$(curl $opts "$BASE_URL/api/health" 2>/dev/null)
    case "$body" in
        *'"status"'*'"healthy"'*) ok "GET /api/health -> 200 healthy (${waited}s)" ;;
        *) vfail "GET /api/health -> 200 but body is not healthy: $body" ;;
    esac
}

verify_login_roundtrip() {
    # This is the check that would have caught a broken bcrypt bump.
    #
    # It must use a username that EXISTS. backend/app/api/auth.py:167 reads
    #     if user is None or not verify_password(...)
    # and `or` short-circuits, so a login for a nonexistent user returns 401
    # without ever calling bcrypt.checkpw. A 401 for "nosuchuser" therefore
    # proves nothing at all about bcrypt. With a real username and a wrong
    # password the comparison actually runs: 401 means checkpw executed and
    # returned False; 500 means it raised.
    #
    # Side effect, by design: each run appends one `login_failed` row to
    # audit_logs (auth.py:169-176), attributed to the admin username. There is
    # no lockout logic, so repeated runs are safe.
    local user pass code body opts
    user=$(env_get ADMIN_USERNAME admin)
    if command -v openssl >/dev/null 2>&1; then
        pass="deploy-verify-$(openssl rand -hex 16)"
    else
        pass="deploy-verify-$$-$(date +%s)-${RANDOM}${RANDOM}"
    fi
    opts=$(curl_base)

    local attempt=1
    while :; do
        set +e
        # shellcheck disable=SC2086
        body=$(curl $opts -o /dev/null -w '%{http_code}' \
            -X POST \
            --data-urlencode "username=$user" \
            --data-urlencode "password=$pass" \
            "$BASE_URL/api/auth/token" 2>/dev/null)
        set -e
        code="$body"
        # nginx applies `limit_req zone=auth_limit ... rate=3r/s` to this exact
        # location (nginx/sites/default.conf:65). Back off rather than reporting
        # a rate limit as an auth failure.
        if [ "$code" = "429" ] || [ "$code" = "503" ]; then
            [ "$attempt" -ge 4 ] && { vfail "POST /api/auth/token kept returning $code (nginx rate limit)"; return 0; }
            warn "POST /api/auth/token -> $code (rate limited), retrying in 5s"
            sleep 5; attempt=$((attempt + 1)); continue
        fi
        break
    done

    case "$code" in
        401) ok "POST /api/auth/token (user '$user', wrong password) -> 401; the bcrypt verify path ran" ;;
        200) vfail "POST /api/auth/token -> 200 for a random password. Authentication is BROKEN OPEN." ;;
        500|502|504)
            vfail "POST /api/auth/token -> $code. verify_password raised instead of returning False."
            vfail "That is the signature of an incompatible bcrypt; check the pin in backend/requirements.txt."
            docker compose logs --tail=40 backend | sed 's/^/        /' || true ;;
        *)  vfail "POST /api/auth/token -> $code (want 401)" ;;
    esac
}

verify_bcrypt_pin() {
    # Closes the loop on the reason this script exists: prove the container is
    # running the version requirements.txt asks for, not whatever the last
    # unpinned resolve happened to fetch.
    local pinned running
    pinned=$(grep -m1 -E '^bcrypt==' backend/requirements.txt 2>/dev/null | cut -d= -f3 || true)
    if [ -z "$pinned" ]; then
        warn "backend/requirements.txt has no exact 'bcrypt==' pin at this SHA; skipping the version check"
        return 0
    fi
    set +e
    running=$(docker compose exec -T backend python -c \
        'import importlib.metadata as m; print(m.version("bcrypt"))' 2>/dev/null | tr -d ' \r\n')
    set -e
    if [ -z "$running" ]; then
        warn "could not read the bcrypt version from the backend container; skipping"
        return 0
    fi
    if [ "$running" = "$pinned" ]; then
        ok "bcrypt $running in the container matches the pin in requirements.txt"
    else
        vfail "bcrypt mismatch: container has $running, requirements.txt pins $pinned"
        vfail "the image was not rebuilt from this checkout"
    fi
}

verify_all() {
    PHASE="verifying"
    step "Verifying"
    verify_container_health "$HEALTH_TIMEOUT"
    verify_api_health
    verify_login_roundtrip
    verify_bcrypt_pin

    if [ "$VERIFY_FAILURES" -ne 0 ]; then
        banner "$C_RED" "DEPLOY COMPLETED BUT VERIFICATION FAILED ($VERIFY_FAILURES check(s))" \
            "The new code from $TARGET_SHA IS SERVING LIVE TRAFFIC." \
            "This is not a safe state to walk away from." \
            "" \
            "Roll back:" \
            "  cd $DEPLOY_DIR && scripts/deploy.sh --rollback $PREV_SHA" \
            "" \
            "Or investigate:" \
            "  docker compose ps" \
            "  docker compose logs --tail=200 backend sync"
        PHASE="done"
        exit 4
    fi
    ok "all post-deploy checks passed"
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
main() {
    preflight_common

    if [ "$MODE" = "ci-check-only" ]; then
        # Deliberately does not require docker or the deploy directory, so the
        # gate can be exercised anywhere -- including from a laptop, and from a
        # test that proves the red / green / no-run branches really differ.
        if [ -d "$DEPLOY_DIR/.git" ]; then cd "$DEPLOY_DIR"; fi
        derive_repo_slug
        local sha
        if printf '%s' "$TARGET_REF" | grep -qiE '^[0-9a-f]{40}$'; then
            sha="$TARGET_REF"
        else
            git rev-parse --git-dir >/dev/null 2>&1 \
                || die "--ci-check-only with a non-SHA ref needs a git checkout; pass a full 40-char SHA or --dir"
            git fetch --prune origin >/dev/null 2>&1 || warn "git fetch failed; resolving '$TARGET_REF' from local refs"
            sha=$(git rev-parse --verify --quiet "refs/remotes/origin/$TARGET_REF^{commit}" \
                  || git rev-parse --verify "${TARGET_REF}^{commit}") \
                  || die "cannot resolve '$TARGET_REF'"
        fi
        step "CI gate check only: $REPO_SLUG @ $sha"
        evaluate_ci "$sha"
        PHASE="done"
        [ "$CI_STATE" = "GREEN" ] && exit 0
        exit 2
    fi

    preflight_deploy
    derive_repo_slug

    PREV_SHA=$(git rev-parse HEAD)
    local prev_desc
    prev_desc=$(git --no-pager log -1 --format='%s' "$PREV_SHA")

    banner "$C_BLU" "bsdmirror deploy" \
        "directory       $DEPLOY_DIR" \
        "repo            $REPO_SLUG" \
        "services        $SERVICES  (nginx / postgres / redis untouched)" \
        "mode            $MODE$([ "$DRY_RUN" -eq 1 ] && printf ' (--dry-run)')" \
        "" \
        "CURRENT SHA     $PREV_SHA" \
        "                $prev_desc" \
        "" \
        "Roll back to the current state at any time with:" \
        "  scripts/deploy.sh --rollback $PREV_SHA"

    resolve_target

    if [ "$TARGET_SHA" = "$PREV_SHA" ] && [ "$MODE" != "rollback" ]; then
        info "already at $TARGET_SHA"
        confirm "Rebuild and recreate anyway?" || { info "nothing to do"; PHASE="done"; exit 0; }
    fi

    require_ci_green "$TARGET_SHA"
    require_clean_tree

    if [ "$DRY_RUN" -eq 0 ]; then
        step "Validating compose before touching anything"
        docker compose config -q || die_gate "docker compose config failed; refusing to deploy a stack that does not parse"
        ok "docker compose config -q clean"
        step "Dependencies"
        dependencies_must_be_up
        require_no_sync_in_progress
    else
        warn "--dry-run: skipping compose validation, dependency and sync-activity gates"
    fi

    # Verification targets the public URL because backend publishes no ports --
    # it is only reachable through nginx (docker-compose.yml has no `ports` for
    # it and the `backend` network is internal: true).
    if [ -z "$BASE_URL" ]; then
        local domain; domain=$(env_get DOMAIN "")
        if [ -n "$domain" ] && [ "$domain" != "localhost" ]; then
            BASE_URL="https://$domain"
        else
            BASE_URL="http://localhost"
        fi
    fi
    info "verification base URL: $BASE_URL"

    if [ "$DRY_RUN" -eq 0 ]; then
        confirm "Deploy $TARGET_SHA to $DEPLOY_DIR?" || die_gate "aborted by operator; nothing was done"
    fi

    move_checkout
    build_and_up

    if [ "$DRY_RUN" -eq 1 ]; then
        PHASE="done"
        banner "$C_BLU" "--dry-run finished" \
            "Every gate ran. No git, build or container command was executed."
        exit 0
    fi

    verify_all

    PHASE="done"
    banner "$C_GRN" "DEPLOYED AND VERIFIED" \
        "$PREV_SHA" \
        "  -> $TARGET_SHA" \
        "" \
        "Roll back with:" \
        "  cd $DEPLOY_DIR && scripts/deploy.sh --rollback $PREV_SHA"

    if [ "$CHECKOUT_STYLE" = "detached" ]; then
        warn "HEAD is detached at $TARGET_SHA."
        warn "The next 'git pull' here will do nothing useful. Return to the branch with:"
        warn "  cd $DEPLOY_DIR && scripts/deploy.sh main"
    fi
}

# Executing this file deploys. Sourcing it defines the gates without running
# anything, so require_clean_tree / evaluate_ci / require_no_sync_in_progress
# can be exercised on their own -- which is the only way to test a gate whose
# whole job is to refuse.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main "$@"
fi
