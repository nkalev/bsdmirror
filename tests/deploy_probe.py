"""Run one function from scripts/deploy.sh against scripted HTTP, git and sleep.

deploy.sh only runs main() when it is executed, so the probe sources it and
calls a single function, the way tests/test_deploy_sync_gate.py does. curl, git
and sleep are bash stubs, so nothing reaches the network, the repository's
history or the clock. DEPLOY_DIR is the test's own checkout directory, so
env_get() reads that directory's .env.

curl answers from a table with one row per response:
``url|code|base64(body)|base64(headers)``. Rows for the same URL are served in
order, one per request, and the last one repeats, so a test can script "503,
then 200". The stub understands the flags deploy.sh passes:

* ``-o FILE``: the body goes to FILE; without -o it goes to stdout.
* ``-D FILE``: the status line and headers go to FILE, or to stdout for ``-``.
* ``-w``: the status code is printed after the body.

A URL with no row behaves like a connection that produced no response: status
000 and exit 7. Like real curl, it then leaves an -o file as it was and
empties a -D file.

Every request's URL goes to a call log, and every sleep's argument to a sleep
log. run_probe() returns the subprocess result with three extra attributes:
``output`` (stdout and stderr), ``calls`` and ``sleeps``.
"""

import base64
import os
import pathlib
import re
import subprocess

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEPLOY_SH = REPO_ROOT / "scripts" / "deploy.sh"

PREV_SHA = "prevsha1"
TARGET_SHA = "targetsha2"
BASE_URL = "http://example.invalid"

PROBE = r"""
source "$DEPLOY_SH"

_stub_head() {
    printf 'HTTP/1.1 %s Stub\r\n' "$1"
    local line
    while IFS= read -r line || [ -n "$line" ]; do
        printf '%s\r\n' "$line"
    done < <(printf '%s' "$2" | base64 -d)
    printf '\r\n'
}

curl() {
    local out="" hdr="" want_code=0 prev="" a url
    for a in "$@"; do
        case "$prev" in
            -o) out="$a" ;;
            -D) hdr="$a" ;;
        esac
        [ "$a" = "-w" ] && want_code=1
        prev="$a"
    done
    url="${*: -1}"
    printf '%s\n' "$url" >>"$CALL_LOG"

    local n i=0 u code b h row=""
    n=$(grep -cxF -- "$url" "$CALL_LOG")
    while IFS='|' read -r u code b h; do
        [ "$u" = "$url" ] || continue
        i=$((i + 1))
        row="$code|$b|$h"
        [ "$i" -lt "$n" ] || break
    done <<< "$FAKE_HTTP_TABLE"

    if [ -z "$row" ]; then
        if [ -n "$hdr" ] && [ "$hdr" != "-" ]; then : >"$hdr"; fi
        if [ "$want_code" = 1 ]; then printf '000'; fi
        return 7
    fi

    IFS='|' read -r code b h <<< "$row"
    if [ "$hdr" = "-" ]; then
        _stub_head "$code" "$h"
    elif [ -n "$hdr" ]; then
        _stub_head "$code" "$h" >"$hdr"
    fi
    if [ -n "$out" ]; then
        printf '%s' "$b" | base64 -d >"$out"
    else
        printf '%s' "$b" | base64 -d
    fi
    if [ "$want_code" = 1 ]; then printf '%s' "$code"; fi
    return 0
}

git() {
    if [ "$1" = "show" ]; then
        local arg="$2" u rc b
        while IFS='|' read -r u rc b; do
            [ "$u" = "$arg" ] || continue
            [ "$rc" = "0" ] && printf '%s' "$b" | base64 -d
            return "$rc"
        done <<< "$FAKE_GIT_TABLE"
        return 128
    fi
    return 1
}

sleep() { printf '%s\n' "$*" >>"$SLEEP_LOG"; }

cd "$WORKDIR"
DEPLOY_DIR="$WORKDIR"
FRONTEND_TOUCHED="$FAKE_FRONTEND_TOUCHED"
FRONTEND_CHANGED_FILES="$FAKE_CHANGED_FILES"
BASE_URL="$FAKE_BASE_URL"
PREV_SHA="$FAKE_PREV_SHA"
TARGET_SHA="$FAKE_TARGET_SHA"

"$FUNCTION"
rc=$?
printf 'RC=%s\n' "$rc"
printf 'VERIFY_FAILURES=%s\n' "$VERIFY_FAILURES"
"""


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def _http_rows(rows) -> str:
    """Each row is (url, code, body) or (url, code, body, headers); headers is
    a sequence of (name, value) pairs, so a name can repeat."""
    lines = []
    for url, code, body, *rest in rows:
        headers = rest[0] if rest else ()
        head = "\n".join(f"{name}: {value}" for name, value in headers)
        lines.append(f"{url}|{code}|{_b64(body)}|{_b64(head)}")
    return "\n".join(lines)


def _git_rows(rows) -> str:
    return "\n".join(f"{key}|{rc}|{_b64(body)}" for key, rc, body in rows)


def url_for(rel: str) -> str:
    prefix = "frontend/public/"
    suffix = rel[len(prefix) :] if rel.startswith(prefix) else rel
    return f"{BASE_URL}/{suffix}"


def write_file(workdir, rel: str, content: str) -> None:
    path = workdir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def marker(output: str, name: str) -> int:
    match = re.search(rf"^{name}=(-?\d+)$", output, re.MULTILINE)
    assert match, f"{name} marker missing from probe output:\n{output}"
    return int(match.group(1))


def run_probe(
    workdir,
    function,
    *,
    frontend_touched=1,
    changed_files="",
    http_table=(),
    git_table=(),
    prev_sha=PREV_SHA,
    target_sha=TARGET_SHA,
    base_url=BASE_URL,
):
    root = workdir.parent
    probe = root / "probe.sh"
    probe.write_text(PROBE)
    call_log = root / "calls.log"
    sleep_log = root / "sleeps.log"
    call_log.write_text("")
    sleep_log.write_text("")
    result = subprocess.run(
        ["bash", str(probe)],
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(root),
            "NO_COLOR": "1",
            "DEPLOY_SH": str(DEPLOY_SH),
            "WORKDIR": str(workdir),
            "FUNCTION": function,
            "CALL_LOG": str(call_log),
            "SLEEP_LOG": str(sleep_log),
            "FAKE_FRONTEND_TOUCHED": str(frontend_touched),
            "FAKE_CHANGED_FILES": changed_files,
            "FAKE_BASE_URL": base_url,
            "FAKE_PREV_SHA": prev_sha,
            "FAKE_TARGET_SHA": target_sha,
            "FAKE_HTTP_TABLE": _http_rows(http_table),
            "FAKE_GIT_TABLE": _git_rows(git_table),
        },
        # Not a terminal, so nothing can read stdin and colour codes stay off.
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    result.output = result.stdout + result.stderr
    result.calls = call_log.read_text().splitlines()
    result.sleeps = sleep_log.read_text().splitlines()
    return result
