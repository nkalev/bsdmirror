#!/usr/bin/env bash
#
# bsdmirror - regenerate the hash-pinned dependency lockfiles
#
# Why this exists
# ---------------
# backend/requirements.in and sync/requirements.in are the human-edited direct
# dependency lists -- the packages this repo actually imports or invokes.
# backend/requirements.txt and sync/requirements.txt are GENERATED from them:
# the full transitive closure, hash-pinned with --generate-hashes, and are
# what backend/Dockerfile, sync/Dockerfile and Dockerfile.test actually
# install. Never hand-edit a .txt file here; it will not survive the next
# regeneration and it will not carry hashes for whatever you added by hand.
#
# The one thing that makes this two files, not two independent runs
# -------------------------------------------------------------------
# backend and sync overlap on eight direct packages (asyncpg, croniter, httpx,
# pydantic-settings, python-dotenv, redis, sqlalchemy, structlog), and
# Dockerfile.test and CI's "Install backend and sync requirements in a single
# resolve" step install BOTH files in one pip invocation. If the two closures
# pinned a shared transitive package (anyio, h11, certifi, ...) to different
# versions, that combined install -- and --require-hashes, which activates
# the moment any requirement in the set carries a hash -- would fail.
#
# So sync's lock is not compiled independently: it is compiled with the
# freshly-generated backend/requirements.txt passed as a CONSTRAINT
# (pip-compile --constraint). A constraint pins a package's version if sync
# needs it at all, whether or not it is one of the eight shared direct names,
# without forcing sync to depend on anything backend does not already need
# too. That is why the order below is fixed: backend first, sync second,
# every time. backend/requirements.txt is already treated as the authority on
# shared tooling versions elsewhere in CI (the ruff and bandit jobs install
# "at the version pinned in backend/requirements.txt"); this is the same
# convention applied to the dependency graph.
#
# Where this runs
# ----------------
# Inside python:3.12-slim -- the exact base image backend/Dockerfile,
# sync/Dockerfile and Dockerfile.test all build from (CI's "Interpreter must
# match the container base image" step asserts this) -- not on the host.
# pip-tools resolves markers (sys_platform, platform_system, ...) against the
# interpreter it runs under, and this repo's images are always Linux
# regardless of which machine builds them; running the compiler anywhere else
# risks a resolution that differs from what the containers will actually see
# (an extra it needlessly pulls on macOS, a version whose Linux wheel does not
# exist yet on the day of compiling). --platform linux/amd64 is pinned in
# addition, to match CI's ubuntu-24.04 runners and the production host
# byte-for-byte -- see the note below on why that does not narrow the lock to
# amd64-only machines.
#
# Does the lock still work on an arm64 dev machine?
# --------------------------------------------------
# Yes. --generate-hashes records the hash of every file PyPI hosts for the
# resolved version -- every wheel for every platform and Python tag, plus the
# sdist -- not just the one matching the machine that ran pip-compile. Verified
# empirically while adding this file: a lock compiled with --platform
# linux/amd64 for cryptography==50.0.1 carries linux/aarch64, macOS and
# Windows wheel hashes alongside the linux/amd64 one. `docker compose build`
# on Apple Silicon (no `platform:` is pinned in docker-compose.yml, so it
# builds native arm64 images) downloads the aarch64 wheel and finds its hash
# already in the file. What --platform linux/amd64 controls here is dependency
# RESOLUTION (which versions and environment-marker branches get selected),
# not hash COVERAGE.
#
# Usage
# -----
#   scripts/compile-requirements.sh                 backend, then sync (default)
#   scripts/compile-requirements.sh backend          backend/requirements.txt only
#   scripts/compile-requirements.sh sync             sync/requirements.txt only,
#                                                     constrained by whatever
#                                                     backend/requirements.txt
#                                                     already says on disk
#   scripts/compile-requirements.sh --upgrade        allow transitive packages to
#                                                     move to newer compatible
#                                                     releases (security patches,
#                                                     routine refresh); direct
#                                                     pins in the .in files are
#                                                     untouched -- edit those by
#                                                     hand to change one
#
# After regenerating, this script does not run the suite for you:
#   docker compose build backend sync test
#   docker compose run --rm test
#   docker compose run --rm --entrypoint ruff test check .
#   docker run --rm -v "$PWD:/repo:ro" -w /repo python:3.12-slim bash -c \
#     'pip install --quiet pip-audit && pip-audit -r backend/requirements.txt -r sync/requirements.txt'
# pip-audit is deliberately not baked into any image (it would need network
# egress to query the advisory database, and the `test` service runs with
# `network_mode: none`) -- run it standalone, the same way this script itself
# compiles, rather than in a container that can never reach the network by
# design.
#
# A lock that only changes what pip resolves, with nothing to prove it still
# installs, still passes the suite and still has no known vulnerability, is
# not done -- see README.md#dependency-lockfiles.
#
# Pinned tool versions
# ---------------------
# pip and pip-tools are pinned below (not left to float) so two people
# regenerating the same .in files on the same day get the same .txt file.
# Bump them here deliberately, in the same commit as whatever prompted the
# regeneration, not as a side effect of one.

set -euo pipefail

PIP_VERSION="26.2.1"
PIP_TOOLS_VERSION="7.6.1"
PYTHON_IMAGE="python:3.12-slim"
PLATFORM="linux/amd64"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

TARGET="all"
# Seeded with the flags every run needs, not left empty: bash 3.2 (the
# /bin/bash macOS ships) treats "${arr[@]}" on a zero-element array as unset
# under `set -u` and aborts with "unbound variable". Keeping this at three
# elements or more, always, sidesteps the bash-version question entirely
# rather than relying on a workaround that only some bash versions need.
PIP_COMPILE_ARGS=(--generate-hashes --allow-unsafe --resolver=backtracking)
for arg in "$@"; do
    case "$arg" in
        all|backend|sync) TARGET="$arg" ;;
        --upgrade)        PIP_COMPILE_ARGS+=("--upgrade") ;;
        -h|--help)
            awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "$0"
            exit 0 ;;
        *)
            echo "unknown argument: $arg (expected: all | backend | sync | --upgrade)" >&2
            exit 1 ;;
    esac
done

for f in backend/requirements.in sync/requirements.in; do
    if [ ! -f "$REPO_ROOT/$f" ]; then
        echo "error: $f is missing -- this script compiles it, it does not create it" >&2
        exit 1
    fi
done

run_pip_compile() {
    # $1: description, everything after: the pip-compile argv
    local desc="$1"; shift
    echo "==> $desc"
    docker run --rm \
        --platform "$PLATFORM" \
        --user "$(id -u):$(id -g)" \
        -e HOME=/tmp \
        -e PIP_CACHE_DIR=/tmp/pip-cache \
        -e PIP_DISABLE_PIP_VERSION_CHECK=1 \
        -e PIP_VERSION="$PIP_VERSION" \
        -e PIP_TOOLS_VERSION="$PIP_TOOLS_VERSION" \
        -v "$REPO_ROOT:/repo" \
        -w /repo \
        "$PYTHON_IMAGE" \
        bash -c '
            set -euo pipefail
            pip install --quiet --user "pip==$PIP_VERSION" "pip-tools==$PIP_TOOLS_VERSION"
            export PATH="/tmp/.local/bin:$PATH"
            pip-compile "$@"
        ' bash "$@"
}

if [ "$TARGET" = "all" ] || [ "$TARGET" = "backend" ]; then
    run_pip_compile "compiling backend/requirements.txt" \
        "${PIP_COMPILE_ARGS[@]}" \
        --output-file=backend/requirements.txt backend/requirements.in
fi

if [ "$TARGET" = "all" ] || [ "$TARGET" = "sync" ]; then
    if [ ! -f "$REPO_ROOT/backend/requirements.txt" ]; then
        echo "error: backend/requirements.txt does not exist yet -- run this script with" >&2
        echo "       no argument, or with 'backend' first, so sync has something to be" >&2
        echo "       constrained by" >&2
        exit 1
    fi
    run_pip_compile "compiling sync/requirements.txt (constrained by backend/requirements.txt)" \
        "${PIP_COMPILE_ARGS[@]}" \
        --constraint=backend/requirements.txt \
        --output-file=sync/requirements.txt sync/requirements.in
fi

echo "==> done. Diff the .txt files, then:"
echo "      docker compose build backend sync test"
echo "      docker compose run --rm test"
echo "      docker compose run --rm --entrypoint ruff test check ."
echo "      docker run --rm -v \"\$PWD:/repo:ro\" -w /repo python:3.12-slim bash -c \\"
echo "        'pip install --quiet pip-audit && pip-audit -r backend/requirements.txt -r sync/requirements.txt'"
