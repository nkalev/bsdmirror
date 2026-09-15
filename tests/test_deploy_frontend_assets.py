"""verify_frontend_assets() (scripts/deploy.sh) proves nginx is actually
serving frontend/public/ at the checkout's bytes, because nothing else in
verify_all() reads a single byte of what nginx serves from that bind mount.

The branch under test here is the deletion case. Every location under
frontend/public/ inherits `try_files $uri $uri/ /index.html`, so nginx
answers a path deleted by this deploy with HTTP 200 and the SPA shell -- by
design, not staleness. The function therefore never gates on status code for
a deleted file; it compares live bytes to the pre-deletion content (read via
`git show $PREV_SHA:$rel`) and only fails when those two match, i.e. when
something is still serving the deleted file's own old bytes.

The other thing worth being explicit about: verify_frontend_assets() never
returns non-zero. Every failure path calls vfail() (bad() + VERIFY_FAILURES
+= 1) and falls through to `return 0`; the caller (verify_all()) only checks
$VERIFY_FAILURES at the very end. A test that asserted "non-zero exit means
failure" here would pass for the wrong reason, so the assertions below check
$VERIFY_FAILURES and the printed [FAIL]/[ OK ] lines, never the function's
own return status as a stand-in for pass/fail.

deploy.sh only runs main() when executed, so this sources it and calls the
function directly, the same way tests/test_deploy_sync_gate.py does. curl and
git are replaced with table-driven bash stubs so the probe touches neither
the network nor real repository history.
"""

import base64
import os
import pathlib
import re
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEPLOY_SH = REPO_ROOT / "scripts" / "deploy.sh"

PREV_SHA = "prevsha1"
TARGET_SHA = "targetsha2"
BASE_URL = "http://example.invalid"

# curl() and git() below are driven by two tables, one row per URL (or git-show
# argument) that the probe cares about: "key|value|base64(body)". base64 keeps
# arbitrary body bytes (including "|" or a newline) out of the row delimiter.
PROBE = r"""
source "$DEPLOY_SH"

curl() {
    local want_code=0 a url u code b
    for a in "$@"; do [ "$a" = "-w" ] && want_code=1; done
    url="${@: -1}"
    while IFS='|' read -r u code b; do
        [ "$u" = "$url" ] || continue
        if [ "$want_code" = 1 ]; then
            printf '%s' "$code"
        else
            printf '%s' "$b" | base64 -d
        fi
        return 0
    done <<< "$FAKE_HTTP_TABLE"
    # Unknown URL: behave like a connection that produced no response.
    [ "$want_code" = 1 ] && printf '%s' "000"
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

cd "$WORKDIR"
FRONTEND_TOUCHED="$FAKE_FRONTEND_TOUCHED"
FRONTEND_CHANGED_FILES="$FAKE_CHANGED_FILES"
BASE_URL="$FAKE_BASE_URL"
PREV_SHA="$FAKE_PREV_SHA"
TARGET_SHA="$FAKE_TARGET_SHA"

verify_frontend_assets
rc=$?
printf 'RC=%s\n' "$rc"
printf 'VERIFY_FAILURES=%s\n' "$VERIFY_FAILURES"
"""


@pytest.fixture
def workdir(tmp_path):
    d = tmp_path / "checkout"
    d.mkdir()
    return d


def _b64(body: str) -> str:
    return base64.b64encode(body.encode()).decode()


def _table(rows) -> str:
    return "\n".join(f"{key}|{value}|{_b64(body)}" for key, value, body in rows)


def url_for(rel: str) -> str:
    prefix = "frontend/public/"
    suffix = rel[len(prefix) :] if rel.startswith(prefix) else rel
    return f"{BASE_URL}/{suffix}"


def write_file(workdir, rel: str, content: str) -> None:
    path = workdir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def run_probe(
    workdir,
    *,
    frontend_touched=1,
    changed_files,
    http_table,
    git_table,
    prev_sha=PREV_SHA,
    target_sha=TARGET_SHA,
    base_url=BASE_URL,
):
    probe = workdir.parent / "probe.sh"
    probe.write_text(PROBE)
    result = subprocess.run(
        ["bash", str(probe)],
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(workdir.parent),
            "NO_COLOR": "1",
            "DEPLOY_SH": str(DEPLOY_SH),
            "WORKDIR": str(workdir),
            "FAKE_FRONTEND_TOUCHED": str(frontend_touched),
            "FAKE_CHANGED_FILES": changed_files,
            "FAKE_BASE_URL": base_url,
            "FAKE_PREV_SHA": prev_sha,
            "FAKE_TARGET_SHA": target_sha,
            "FAKE_HTTP_TABLE": _table(http_table),
            "FAKE_GIT_TABLE": _table(git_table),
        },
        # Not a terminal, so nothing can read stdin and colour codes stay off.
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    result.output = result.stdout + result.stderr
    return result


def _marker(output: str, name: str) -> int:
    match = re.search(rf"^{name}=(-?\d+)$", output, re.MULTILINE)
    assert match, f"{name} marker missing from probe output:\n{output}"
    return int(match.group(1))


def test_no_frontend_changes_is_a_no_op(workdir):
    result = run_probe(
        workdir,
        frontend_touched=0,
        changed_files="",
        http_table=[],
        git_table=[],
    )
    assert result.returncode == 0, result.output
    assert _marker(result.output, "RC") == 0
    assert _marker(result.output, "VERIFY_FAILURES") == 0
    assert "no frontend/public/ changes in this deploy; nothing to prove" in result.output
    assert "[FAIL]" not in result.output


def test_changed_file_served_with_new_bytes_is_ok(workdir):
    rel = "frontend/public/app.js"
    content = "console.log('new');\n"
    write_file(workdir, rel, content)

    result = run_probe(
        workdir,
        changed_files=rel,
        http_table=[(url_for(rel), "200", content)],
        git_table=[],
    )
    assert result.returncode == 0, result.output
    assert _marker(result.output, "RC") == 0
    assert _marker(result.output, "VERIFY_FAILURES") == 0
    assert "[FAIL]" not in result.output
    assert f"{url_for(rel)}  " in result.output
    assert (
        "all 1 changed frontend/public/ file(s) match the checkout byte-for-byte" in result.output
    )


def test_changed_file_still_serving_old_bytes_is_a_failure_but_the_function_returns_zero(workdir):
    rel = "frontend/public/app.js"
    new_content = "console.log('new');\n"
    old_content = "console.log('old');\n"
    write_file(workdir, rel, new_content)

    result = run_probe(
        workdir,
        changed_files=rel,
        http_table=[(url_for(rel), "200", old_content)],
        git_table=[],
    )
    # The function's own contract: it never returns non-zero, even here.
    # Failure is reported through VERIFY_FAILURES and the [FAIL] line only.
    assert result.returncode == 0, result.output
    assert _marker(result.output, "RC") == 0
    assert _marker(result.output, "VERIFY_FAILURES") == 1
    assert "SERVING STALE CONTENT" in result.output
    assert "1 of 1 changed frontend/public/ file(s) do not match this checkout" in result.output


def test_changed_file_non_200_response_is_a_failure(workdir):
    rel = "frontend/public/style.css"
    content = "body {}\n"
    write_file(workdir, rel, content)

    result = run_probe(
        workdir,
        changed_files=rel,
        http_table=[(url_for(rel), "502", "Bad Gateway")],
        git_table=[],
    )
    assert result.returncode == 0, result.output
    assert _marker(result.output, "RC") == 0
    assert _marker(result.output, "VERIFY_FAILURES") == 1
    assert "HTTP 502 fetching a file that exists in the checkout" in result.output


@pytest.mark.parametrize(
    "code, body",
    [
        pytest.param("200", "<html>SPA shell</html>\n", id="spa-fallback-200"),
        pytest.param("404", "404 Not Found\n", id="not-found-404"),
    ],
)
def test_deleted_file_no_longer_serving_old_bytes_is_ok(workdir, code, body):
    rel = "frontend/public/old-page.html"
    old_content = "<html>old page</html>\n"
    # Deliberately not written to disk: this is the "deleted by this deploy"
    # case, so [ ! -f "$rel" ] must be true.

    result = run_probe(
        workdir,
        changed_files=rel,
        http_table=[(url_for(rel), code, body)],
        git_table=[(f"{PREV_SHA}:{rel}", "0", old_content)],
    )
    assert result.returncode == 0, result.output
    assert _marker(result.output, "RC") == 0
    assert _marker(result.output, "VERIFY_FAILURES") == 0
    assert f"deleted, no longer serving the old bytes (HTTP {code})" in result.output
    assert "[FAIL]" not in result.output


def test_deleted_file_still_serving_its_old_bytes_is_a_failure(workdir):
    rel = "frontend/public/old-page.html"
    old_content = "<html>old page</html>\n"

    result = run_probe(
        workdir,
        changed_files=rel,
        # A stale mount/alias/cache answering with the exact pre-deletion body.
        http_table=[(url_for(rel), "200", old_content)],
        git_table=[(f"{PREV_SHA}:{rel}", "0", old_content)],
    )
    assert result.returncode == 0, result.output
    assert _marker(result.output, "RC") == 0
    assert _marker(result.output, "VERIFY_FAILURES") == 1
    assert f"deleted in {TARGET_SHA} but still serving its old bytes (HTTP 200)" in result.output
    assert "1 of 1 changed frontend/public/ file(s) do not match this checkout" in result.output


def test_deleted_file_is_ok_when_git_cannot_produce_the_pre_deletion_content(workdir):
    # No row for this path in FAKE_GIT_TABLE, so the stub's `git show` returns
    # 128 the way a real one would for a ref this checkout does not have. The
    # function cannot prove staleness without the old content, so it does not
    # try -- this documents that fail-open edge rather than asserting it is
    # the ideal behaviour.
    rel = "frontend/public/old-page.html"

    result = run_probe(
        workdir,
        changed_files=rel,
        http_table=[(url_for(rel), "200", "whatever is being served now")],
        git_table=[],
    )
    assert result.returncode == 0, result.output
    assert _marker(result.output, "RC") == 0
    assert _marker(result.output, "VERIFY_FAILURES") == 0
    assert "deleted, no longer serving the old bytes (HTTP 200)" in result.output


def test_tally_counts_failures_across_multiple_changed_files(workdir):
    ok_rel = "frontend/public/a.js"
    stale_rel = "frontend/public/b.js"
    ok_content = "a-new\n"
    write_file(workdir, ok_rel, ok_content)
    write_file(workdir, stale_rel, "b-new\n")

    result = run_probe(
        workdir,
        changed_files=f"{ok_rel}\n{stale_rel}",
        http_table=[
            (url_for(ok_rel), "200", ok_content),
            (url_for(stale_rel), "200", "b-STALE\n"),
        ],
        git_table=[],
    )
    assert result.returncode == 0, result.output
    assert _marker(result.output, "RC") == 0
    # vfail() increments VERIFY_FAILURES by 1 per call, not by $fails: one
    # call covers the whole function regardless of how many files failed.
    assert _marker(result.output, "VERIFY_FAILURES") == 1
    assert "2 of 2" not in result.output
    assert "1 of 2 changed frontend/public/ file(s) do not match this checkout" in result.output
