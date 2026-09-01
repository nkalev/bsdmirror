#!/usr/bin/env bash
#
# bsdmirror - database migrations
#
# Why this exists
# ---------------
# Until now the schema came from `Base.metadata.create_all` at backend startup.
# create_all creates missing TABLES and nothing else: on a database where
# `mirrors` already exists it will not add a column, will not widen a type, will
# not touch an enum, and will not complain. So no schema change has ever been
# deployable, and the repo quietly depended on nobody making one.
#
# Alembic now owns the schema, and create_all is gone. This script is the only
# thing anyone should have to run.
#
# THE ONE THING TO UNDERSTAND BEFORE USING IT
# -------------------------------------------
# The production database ALREADY EXISTS AND IS FULL -- five populated tables,
# four enum types, 3.8 TB of mirror state behind them. Alembic is being adopted
# onto it, not used to build it. So the first revision, 0001_baseline, must
# never be *run* there; it must be *stamped*, which records "this database is
# already at that revision" and executes no DDL at all.
#
#     scripts/migrate.sh adopt      <- run ONCE, on the existing database
#     scripts/migrate.sh upgrade    <- every time after that
#
# `adopt` refuses unless the live schema really is what 0001_baseline describes,
# because a stamp is a claim nothing later re-checks.
#
# Where this runs
# ---------------
# Inside the backend image, via `docker compose run --rm --no-deps backend`.
# That image is where alembic, the migration scripts and shared/models/ all
# live, and it is on the `backend` compose network, which is `internal: true` --
# postgres is not reachable from the host at all. Running alembic from a
# checkout on the server would need a second Python environment and a database
# port that deliberately does not exist.
#
# A word about the image
# ----------------------
# Because everything runs from the image, every answer is an answer about the
# IMAGE, not about your working tree. If the image predates a model change,
# `revision --autogenerate` compares the OLD models against the database, finds
# nothing, and writes a migration whose upgrade() is `pass` -- successfully, with
# nothing in the output to suggest it is wrong. That is not hypothetical; it is
# what happened while this script was being written.
#
# Two defences:
#
#   * `revision` bind-mounts shared/ and backend/alembic/ from the checkout, so
#     it always generates against the code you just edited. It is the one
#     command that has to write, and the one where the working tree is what you
#     mean.
#   * Every other command first fingerprints shared/models/ and backend/alembic/
#     in the image and in the checkout (backend/alembic/fingerprint.py) and
#     refuses -- for the commands that change something -- when they differ.
#     `docker compose build backend` is the fix. --allow-stale-image overrides.
#
# During a deploy neither can trigger: scripts/deploy.sh moves the checkout and
# builds from it before it gets here.
#
# Usage
# -----
#   scripts/migrate.sh status              where the database is, and where head is
#   scripts/migrate.sh check               does shared/models/ match the live schema?
#   scripts/migrate.sh diff                same question, and works before adoption
#   scripts/migrate.sh sql                 print the SQL of pending migrations; apply nothing
#   scripts/migrate.sh upgrade             print that SQL, confirm, then apply it
#   scripts/migrate.sh downgrade <REV>     print the SQL, confirm, then apply it
#   scripts/migrate.sh adopt               ONE TIME: stamp an existing database
#   scripts/migrate.sh revision -m "text"  autogenerate a migration (development)
#   scripts/migrate.sh -- <alembic args>   escape hatch: raw alembic
#
# Options:
#   -y, --yes        do not prompt. scripts/deploy.sh passes this.
#   --allow-stale-image
#                    proceed even though the built image is not the code in this
#                    checkout. See "A word about the image" above.
#   --dir PATH       compose project directory. Default: the repo this script
#                    is in, or $DEPLOY_DIR if that is set.
#   -h, --help
#
# Exit codes -- these are the contract, scripts/deploy.sh reads them:
#   0  applied, or already up to date
#   1  usage or preflight error, nothing touched
#   2  a gate refused, nothing touched
#   3  the migration itself failed. Postgres has transactional DDL and env.py
#      wraps the whole run in one transaction, so the schema is UNCHANGED.
#   4  `check` / `diff` only: the models and the database disagree
#
set -euo pipefail

ALEMBIC_INI=/app/alembic.ini          # path INSIDE the backend image
SERVICE=backend
BASELINE_REV=0001_baseline

ASSUME_YES=0
ALLOW_STALE=0
PROJECT_DIR="${DEPLOY_DIR:-}"

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

banner() {
    local color="$1" title="$2"; shift 2
    printf '\n%s%s\n' "$color" "========================================================================"
    printf '  %s\n' "$title"
    printf '%s\n' "========================================================================$C_OFF"
    local line
    for line in "$@"; do printf '  %s\n' "$line"; done
    printf '%s\n' "${color}========================================================================${C_OFF}"
}

die()      { err "$*"; exit 1; }
die_gate() { err "$*"; exit 2; }

usage() {
    # Print the contiguous comment block after the shebang and stop at the first
    # line of code, so --help cannot drift from the header above it.
    awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "$0"
}

# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------
COMMAND=""
RAW_ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        -y|--yes)   ASSUME_YES=1; shift ;;
        --allow-stale-image) ALLOW_STALE=1; shift ;;
        --dir)      PROJECT_DIR="${2:-}"; shift 2 || die "--dir needs a path" ;;
        -h|--help)  usage; exit 0 ;;
        --)         shift; COMMAND="${COMMAND:-raw}"; RAW_ARGS=("$@"); break ;;
        -*)
            # Once a command has been named, an unrecognised flag belongs to it,
            # not to this script: `migrate.sh revision -m "text"` has to reach
            # alembic. Before a command, an unknown flag is a typo.
            if [ -n "$COMMAND" ]; then
                RAW_ARGS+=("$1"); shift
            else
                die "unknown option: $1  (try --help)"
            fi ;;
        *)
            if [ -z "$COMMAND" ]; then
                COMMAND="$1"
            else
                RAW_ARGS+=("$1")
            fi
            shift ;;
    esac
done

[ -n "$COMMAND" ] || { usage; exit 1; }

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
if [ -z "$PROJECT_DIR" ]; then
    PROJECT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
fi
cd "$PROJECT_DIR" || die "cannot cd to $PROJECT_DIR"

command -v docker >/dev/null 2>&1 || die "docker not found"
docker compose version >/dev/null 2>&1 || die "'docker compose' not available (v2 plugin required)"
[ -f docker-compose.yml ] || die "no docker-compose.yml in $PROJECT_DIR (pass --dir)"

# compose reads .env for POSTGRES_PASSWORD and friends; without it every
# ${VAR} silently becomes the empty string and alembic connects as nobody.
[ -f .env ] || die ".env not found in $PROJECT_DIR. Run scripts/setup.sh first."

postgres_must_be_up() {
    local cid state health
    cid=$(docker compose ps -q postgres 2>/dev/null || true)
    if [ -z "$cid" ]; then
        die_gate "postgres is not running. This script deliberately does not start it.
       Bring it up first:  cd $PROJECT_DIR && docker compose up -d postgres"
    fi
    state=$(docker inspect -f '{{.State.Status}}' "$cid")
    [ "$state" = "running" ] || die_gate "postgres is '$state', not running."
    health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")
    case "$health" in
        healthy|none) ok "postgres is running${health:+ ($health)}" ;;
        *)            die_gate "postgres health is '$health'; refusing to migrate against it." ;;
    esac
}

# Every alembic invocation goes through here.
#
# --no-deps        postgres is checked above and must already be up; this must
#                  never start or recreate anything as a side effect.
# --rm             one container per invocation, removed after.
# -T               no TTY. deploy.sh captures this output, and `docker compose
#                  run` without -T mangles it (and fails outright with no tty).
#
# IF THE IMAGE DOES NOT EXIST, COMPOSE BUILDS IT. That is `docker compose run`'s
# behaviour and it cannot be turned off -- `run` has a `--build` flag to force a
# build but no `--no-build` to forbid one (checked against Compose v5.4.0). It
# is left alone rather than worked around, because the image it builds comes
# from THIS checkout, which is the same commit the migrations in it came from:
#
#   fresh install   there is no image yet; building one here is the right
#                   answer and removes a step from the documented sequence.
#   deploy          scripts/deploy.sh has already built, in its own phase, with
#                   its own failure banner. Nothing is left to build.
#   by hand         the checkout moved and was not rebuilt. Building means the
#                   migration scripts and the code that will run them are from
#                   the same commit, which is the safer of the two outcomes.
#
# The build output is deliberately NOT suppressed (--quiet-build exists). If a
# build happens during a migration, that should be visible in the log.
alembic_run() {
    docker compose run --rm --no-deps -T "$SERVICE" \
        alembic -c "$ALEMBIC_INI" "$@"
}

python_run() {
    docker compose run --rm --no-deps -T "$SERVICE" python "$@"
}

# ---------------------------------------------------------------------------
# Is the image the code in this checkout?
#
# `mode` is "warn" for the read-only commands and "refuse" for the ones that
# change something. Reading a stale answer wastes your time; applying one moves
# a database.
# ---------------------------------------------------------------------------
image_must_match_checkout() {
    local mode="$1" out rc=0
    out=$(docker compose run --rm --no-deps -T \
            -v "$PROJECT_DIR/shared:/checkout/shared:ro" \
            -v "$PROJECT_DIR/backend/alembic:/checkout/alembic:ro" \
            "$SERVICE" python /app/alembic/fingerprint.py /app /checkout 2>&1) || rc=$?

    if [ "$rc" -eq 0 ]; then
        ok "image is built from this checkout"
        return 0
    fi

    if [ "$rc" -ne 1 ]; then
        # Could not tell. Say so rather than implying either answer.
        warn "could not fingerprint the image (exit $rc):"
        printf '%s\n' "$out" | sed 's/^/       /' >&2
        return 0
    fi

    printf '%s\n' "$out" | grep -E '^[0-9a-f]{16}  ' | sed 's/^/       /' >&2

    if [ "$ALLOW_STALE" -eq 1 ]; then
        warn "image does NOT match this checkout; continuing (--allow-stale-image)"
        return 0
    fi

    if [ "$mode" = "warn" ]; then
        warn "image does NOT match this checkout -- the answer below describes the"
        warn "IMAGE, not your working tree. Rebuild first: docker compose build $SERVICE"
        return 0
    fi

    banner "$C_RED" "THE BUILT IMAGE IS NOT THIS CHECKOUT" \
        "shared/models/ and/or backend/alembic/ differ between the image and" \
        "the working tree, so this command would apply migrations from code" \
        "that is not the code you are looking at." \
        "" \
        "  cd $PROJECT_DIR && docker compose build $SERVICE" \
        "" \
        "Then run this again. --allow-stale-image proceeds anyway."
    exit 2
}

# ---------------------------------------------------------------------------
# Reading the current state
#
# `alembic current` writes the revision to stdout and its INFO logging to
# stderr, so stdout alone is parseable. Empty stdout means no alembic_version
# table -- an un-adopted database.
# ---------------------------------------------------------------------------
current_revision() {
    alembic_run current 2>/dev/null | awk 'NF {print $1; exit}'
}

head_revision() {
    alembic_run heads 2>/dev/null | awk 'NF {print $1; exit}'
}

confirm() {
    [ "$ASSUME_YES" -eq 1 ] && return 0
    if [ ! -t 0 ]; then
        die_gate "not a terminal and --yes was not given; refusing to apply migrations unattended"
    fi
    local reply
    printf '\n%s%s%s [y/N] ' "$C_BLD" "$*" "$C_OFF"
    read -r reply
    case "$reply" in [yY]|[yY][eE][sS]) return 0 ;; *) return 1 ;; esac
}

# Render the SQL for a revision range without touching the database.
#
# THIS IS THE REVIEW STEP AND IT IS NOT OPTIONAL.
#
# A migration that only exists as autogenerated Python is a migration nobody has
# read. `--sql` runs env.py in offline mode: no driver, no connection, no
# server, just the statements. The range is explicit (`from:to`) because offline
# mode cannot ask the database where it is.
render_sql() {
    local from="$1" to="$2"
    alembic_run upgrade "${from}:${to}" --sql 2>/dev/null
}

render_sql_downgrade() {
    local from="$1" to="$2"
    alembic_run downgrade "${from}:${to}" --sql 2>/dev/null
}

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

cmd_status() {
    postgres_must_be_up
    image_must_match_checkout warn
    step "Revision in the database"
    alembic_run current --verbose || true
    step "Revisions in this checkout"
    alembic_run history --indicate-current || alembic_run history
}

cmd_check() {
    postgres_must_be_up
    image_must_match_checkout warn
    step "alembic check: does shared/models/ match the live schema?"
    local rc=0
    alembic_run check || rc=$?
    if [ "$rc" -eq 0 ]; then
        ok "no difference between shared/models/ and the database"
        return 0
    fi
    banner "$C_YEL" "MODELS AND DATABASE DISAGREE" \
        "Either a model changed without a migration, or the database is not at" \
        "head. Generate the migration:" \
        "" \
        "  scripts/migrate.sh revision -m \"what changed\"" \
        "" \
        "If the database is simply behind, apply what already exists:" \
        "" \
        "  scripts/migrate.sh upgrade"
    exit 4
}

cmd_diff() {
    postgres_must_be_up
    image_must_match_checkout warn
    step "schema_diff.py: models vs live schema (works before adoption)"
    local rc=0
    python_run /app/alembic/schema_diff.py || rc=$?
    case "$rc" in
        0) ok "no difference"; return 0 ;;
        1) exit 4 ;;
        *) die "could not compare (exit $rc)" ;;
    esac
}

cmd_sql() {
    postgres_must_be_up
    image_must_match_checkout warn
    local cur head
    cur=$(current_revision)
    head=$(head_revision)
    [ -n "$head" ] || die "no migrations found in backend/alembic/versions/"

    if [ -z "$cur" ]; then
        banner "$C_YEL" "THIS DATABASE HAS NEVER BEEN STAMPED" \
            "There is no alembic_version table, so there is no starting point to" \
            "render from." \
            "" \
            "If it is an EXISTING database (production):   scripts/migrate.sh adopt" \
            "If it is EMPTY (fresh install):               scripts/migrate.sh upgrade"
        exit 2
    fi
    if [ "$cur" = "$head" ]; then
        info "database is at head ($head); nothing pending, no SQL to render"
        return 0
    fi
    step "SQL for $cur -> $head  (nothing is applied by this command)"
    render_sql "$cur" "$head"
}

cmd_upgrade() {
    postgres_must_be_up
    image_must_match_checkout refuse

    local cur head
    cur=$(current_revision)
    head=$(head_revision)
    [ -n "$head" ] || die "no migrations found in backend/alembic/versions/"

    if [ -z "$cur" ]; then
        # An un-stamped database is either brand new or is production before
        # adoption, and the two need opposite treatment. Telling them apart by
        # asking whether the tables exist is the only safe way to decide.
        step "No alembic_version table. Deciding whether this database is empty or existing"
        local rc=0
        python_run /app/alembic/schema_diff.py >/dev/null 2>&1 || rc=$?
        if [ "$rc" -eq 0 ]; then
            banner "$C_RED" "THIS DATABASE ALREADY HAS THE SCHEMA -- DO NOT UPGRADE IT" \
                "Its schema already matches shared/models/, but it has never been" \
                "stamped. Running 0001_baseline here would CREATE TABLE over live" \
                "data and fail on the first statement." \
                "" \
                "This is the production case. Adopt instead:" \
                "" \
                "  scripts/migrate.sh adopt"
            exit 2
        fi
        info "database does not match the models yet; treating it as a fresh install"
        step "Building the schema from scratch: base -> $head"
        render_sql base "$head" || warn "could not render the offline SQL; continuing to the confirmation"
        confirm "Create the schema in this database?" || die_gate "aborted; nothing was applied"
        run_upgrade "$head"
        return 0
    fi

    if [ "$cur" = "$head" ]; then
        info "already at head ($head); nothing to do"
        return 0
    fi

    step "Pending migrations: $cur -> $head"
    alembic_run history -r "${cur}:${head}" || true

    step "The SQL that will be applied (rendered offline; nothing has run yet)"
    render_sql "$cur" "$head"

    banner "$C_YEL" "READ THE SQL ABOVE BEFORE ANSWERING" \
        "It runs against a database with rows in it. env.py wraps the whole run" \
        "in one transaction, so a failure rolls back and leaves the schema" \
        "exactly as it is now -- but a SUCCESSFUL destructive statement is not" \
        "something a transaction saves you from."
    confirm "Apply $cur -> $head ?" || die_gate "aborted; nothing was applied"
    run_upgrade "$head"
}

run_upgrade() {
    local target="$1"
    step "Applying"
    if ! alembic_run upgrade "$target"; then
        banner "$C_RED" "MIGRATION FAILED -- SCHEMA UNCHANGED" \
            "env.py runs the whole upgrade inside one transaction and Postgres has" \
            "transactional DDL, so nothing was half-applied. The database is" \
            "exactly as it was before this command." \
            "" \
            "  scripts/migrate.sh status"
        exit 3
    fi
    ok "applied"
    step "Confirming the database now matches shared/models/"
    if alembic_run check; then
        ok "alembic check clean"
    else
        warn "alembic check is not clean after upgrading. The migration ran, but the"
        warn "models and the schema still disagree -- the migration is incomplete."
        exit 4
    fi
}

cmd_downgrade() {
    postgres_must_be_up
    image_must_match_checkout refuse
    local target="${RAW_ARGS[0]:-}"
    [ -n "$target" ] || die "downgrade needs a target revision: scripts/migrate.sh downgrade <REV>"

    local cur
    cur=$(current_revision)
    [ -n "$cur" ] || die_gate "database has no alembic_version row; there is nothing to downgrade"

    step "SQL for downgrade $cur -> $target  (nothing applied yet)"
    render_sql_downgrade "$cur" "$target" || warn "could not render the offline SQL"

    banner "$C_RED" "DOWNGRADES LOSE DATA" \
        "A downgrade that drops a column drops what is in it. There is no undo" \
        "and no transaction that helps once it commits." \
        "" \
        "Take a backup first:  scripts/backup.sh"
    confirm "Downgrade $cur -> $target ?" || die_gate "aborted; nothing was applied"
    alembic_run downgrade "$target" || exit 3
    ok "downgraded to $target"
}

cmd_adopt() {
    postgres_must_be_up
    image_must_match_checkout refuse

    local cur
    cur=$(current_revision)
    if [ -n "$cur" ]; then
        banner "$C_GRN" "ALREADY ADOPTED" \
            "alembic_version says this database is at $cur. Adoption is a one-time" \
            "operation and has already been done here." \
            "" \
            "  scripts/migrate.sh status"
        return 0
    fi

    step "Gate 1/2: the live schema must be exactly what $BASELINE_REV describes"
    # This is the whole safety of `stamp`. Stamping writes a claim -- "this
    # database is at 0001_baseline" -- that no later command re-derives. If the
    # schema is not actually that, every future autogenerate is computed from a
    # false starting point.
    local rc=0
    python_run /app/alembic/schema_diff.py || rc=$?
    case "$rc" in
        0) ok "the live schema matches shared/models/ exactly" ;;
        1)
            banner "$C_RED" "REFUSING TO STAMP: THE SCHEMA DOES NOT MATCH" \
                "The differences are listed above. Stamping now would record a" \
                "baseline that is not true, and every migration generated" \
                "afterwards would be computed from the wrong starting point." \
                "" \
                "Reconcile the schema and the models first, by hand, and run this" \
                "again."
            exit 2 ;;
        *) die "could not compare the schema (exit $rc); refusing to stamp blind" ;;
    esac

    step "Gate 2/2: $BASELINE_REV must be the only revision in this checkout"
    # Adoption stamps the BASELINE. If someone has already added revision 2,
    # stamping the baseline would leave the database claiming to be one
    # migration behind a schema it actually has, and the next `upgrade` would
    # re-apply revision 2 on top of itself.
    local head
    head=$(head_revision)
    if [ "$head" != "$BASELINE_REV" ]; then
        banner "$C_RED" "REFUSING TO STAMP: HEAD IS NOT THE BASELINE" \
            "head is '$head', not '$BASELINE_REV'." \
            "" \
            "Gate 1 says the live schema already matches the models at HEAD, so" \
            "this database is at $head, not at the baseline. Stamp the revision" \
            "that is actually true:" \
            "" \
            "  docker compose run --rm --no-deps -T backend \\" \
            "      alembic -c $ALEMBIC_INI stamp $head" \
            "" \
            "and check that claim by hand before you do."
        exit 2
    fi
    ok "head is $BASELINE_REV"

    banner "$C_YEL" "ABOUT TO STAMP AN EXISTING DATABASE" \
        "This writes ONE ROW into a new alembic_version table and executes no" \
        "DDL. No table is created, altered or dropped. It is reversible with" \
        "  DELETE FROM alembic_version;" \
        "" \
        "After it, 'scripts/migrate.sh upgrade' is a no-op and every later" \
        "migration applies normally."
    confirm "Stamp this database at $BASELINE_REV ?" || die_gate "aborted; nothing was written"

    alembic_run stamp "$BASELINE_REV" || exit 3

    step "Verifying"
    alembic_run current --verbose | head -5
    if alembic_run check; then
        banner "$C_GRN" "ADOPTED" \
            "The database is at $BASELINE_REV and agrees with shared/models/." \
            "From here on, schema changes go through:" \
            "" \
            "  scripts/migrate.sh revision -m \"what changed\"   (development)" \
            "  scripts/migrate.sh upgrade                      (deploy, or via deploy.sh)"
    else
        err "stamped, but 'alembic check' is not clean. Investigate before deploying."
        exit 4
    fi
}

# The one command that has to WRITE, and therefore the one that cannot use
# alembic_run().
#
# The backend service is `read_only: true` in docker-compose.yml, so the image's
# /app/alembic/versions is not writable -- and even if it were, the new file
# would live inside a `--rm` container and vanish. So the checkout's versions
# directory is bind-mounted over the image's, which also guarantees alembic is
# looking at exactly the migrations in this working tree.
#
# --user: the image runs as uid 1000 (appuser). Without this, a file generated
# on a Linux host is owned by 1000:1000, which is usually not the person who
# ran the command, and `git add` then works while `$EDITOR` does not.
cmd_revision() {
    postgres_must_be_up
    # Autogenerate compares the models against a live database, so it needs one
    # that is AT HEAD. On a developer machine that is the local stack; it must
    # not be production, and this script has no way to reach production anyway.
    warn "autogenerate compares shared/models/ against the database this compose"
    warn "project points at. Make sure that is a development database."
    step "Generating"
    docker compose run --rm --no-deps -T \
        --user "$(id -u):$(id -g)" \
        -v "$PROJECT_DIR/backend/alembic/versions:/app/alembic/versions" \
        "$SERVICE" alembic -c "$ALEMBIC_INI" revision --autogenerate "${RAW_ARGS[@]}"
    info "Written to backend/alembic/versions/ -- READ IT, fill in the review"
    info "checklist in its docstring, then: scripts/migrate.sh sql"
}

case "$COMMAND" in
    status)     cmd_status ;;
    check)      cmd_check ;;
    diff)       cmd_diff ;;
    sql)        cmd_sql ;;
    upgrade)    cmd_upgrade ;;
    downgrade)  cmd_downgrade ;;
    adopt)      cmd_adopt ;;
    revision)   cmd_revision ;;
    raw)        postgres_must_be_up; alembic_run "${RAW_ARGS[@]}" ;;
    *)          err "unknown command: $COMMAND"; usage; exit 1 ;;
esac
