"""verify_frontend_assets() (scripts/deploy.sh) proves nginx is actually
serving frontend/public/ at the checkout's bytes, because nothing else in
verify_all() reads a single byte of what nginx serves from that bind mount.

The branch under test here is the deletion case. A deleted page falls back to
the SPA shell through `try_files $uri $uri/ /index.html` and answers HTTP 200
-- by design, not staleness -- while a deleted stylesheet, script, font or
image answers 404. The function therefore never gates on status code for a
deleted file; it compares live bytes to the pre-deletion content (read via
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
function directly, through the curl, git and sleep stubs in
tests/deploy_probe.py. The probe touches neither the network nor real
repository history.
"""

import pytest

from tests.deploy_probe import PREV_SHA, TARGET_SHA, url_for, write_file
from tests.deploy_probe import marker as _marker
from tests.deploy_probe import run_probe as _run_probe


@pytest.fixture
def workdir(tmp_path):
    d = tmp_path / "checkout"
    d.mkdir()
    return d


def run_probe(workdir, **kwargs):
    return _run_probe(workdir, "verify_frontend_assets", **kwargs)


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


RATE_LIMITED = "<html>503 Service Temporarily Unavailable</html>\n"


def test_each_file_is_fetched_with_one_request(workdir):
    # The status and the bytes come from the same response. The old form
    # hashed one request and read the status from a second one.
    rel = "frontend/public/app.js"
    content = "console.log('new');\n"
    write_file(workdir, rel, content)

    result = run_probe(
        workdir, changed_files=rel, http_table=[(url_for(rel), "200", content)], git_table=[]
    )
    assert _marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert result.calls == [url_for(rel)]


def test_a_rate_limited_file_is_fetched_again_after_a_pause(workdir):
    rel = "frontend/public/app.js"
    content = "console.log('new');\n"
    write_file(workdir, rel, content)

    result = run_probe(
        workdir,
        changed_files=rel,
        http_table=[(url_for(rel), "503", RATE_LIMITED), (url_for(rel), "200", content)],
        git_table=[],
    )
    assert _marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert result.calls == [url_for(rel)] * 2
    assert result.sleeps == ["2"]
    assert "503 (rate limited), retrying in 2s" in result.output
    assert "SERVING STALE CONTENT" not in result.output


def test_a_file_still_rate_limited_after_three_retries_fails_with_503(workdir):
    rel = "frontend/public/app.js"
    write_file(workdir, rel, "console.log('new');\n")

    result = run_probe(
        workdir, changed_files=rel, http_table=[(url_for(rel), "503", RATE_LIMITED)], git_table=[]
    )
    assert _marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert "HTTP 503 fetching a file that exists in the checkout" in result.output
    assert result.calls == [url_for(rel)] * 4
    assert result.sleeps == ["2"] * 3


@pytest.mark.parametrize("code", ["404", "500", "502", "000"])
def test_only_503_is_retried(workdir, code):
    rel = "frontend/public/app.js"
    write_file(workdir, rel, "console.log('new');\n")
    # 000 is curl's status when nothing answered: a URL with no row.
    rows = [] if code == "000" else [(url_for(rel), code, "error\n")]

    result = run_probe(workdir, changed_files=rel, http_table=rows, git_table=[])
    assert _marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert f"HTTP {code} fetching a file that exists in the checkout" in result.output
    assert result.calls == [url_for(rel)]
    assert result.sleeps == []


def test_a_deleted_file_is_fetched_with_one_request(workdir):
    rel = "frontend/public/old-page.html"
    result = run_probe(
        workdir,
        changed_files=rel,
        http_table=[(url_for(rel), "200", "<html>SPA shell</html>\n")],
        git_table=[(f"{PREV_SHA}:{rel}", "0", "<html>old page</html>\n")],
    )
    assert _marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert result.calls == [url_for(rel)]


def test_a_rate_limited_deleted_file_is_fetched_again(workdir):
    rel = "frontend/public/old-page.html"
    result = run_probe(
        workdir,
        changed_files=rel,
        http_table=[
            (url_for(rel), "503", RATE_LIMITED),
            (url_for(rel), "200", "<html>SPA shell</html>\n"),
        ],
        git_table=[(f"{PREV_SHA}:{rel}", "0", "<html>old page</html>\n")],
    )
    assert _marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert result.calls == [url_for(rel)] * 2
    assert result.sleeps == ["2"]
    assert "deleted, no longer serving the old bytes (HTTP 200)" in result.output


def test_no_response_is_not_read_as_the_previous_files_bytes(workdir):
    # One body file serves every fetch, and curl leaves it as it was when
    # nothing answers. Unless it is emptied first, a deleted file that gets no
    # response would be hashed as the previous file's bytes.
    kept, deleted = "frontend/public/a.html", "frontend/public/b.html"
    same = "<html>same bytes</html>\n"
    write_file(workdir, kept, same)

    result = run_probe(
        workdir,
        changed_files=f"{kept}\n{deleted}",
        http_table=[(url_for(kept), "200", same)],
        git_table=[(f"{PREV_SHA}:{deleted}", "0", same)],
    )
    assert _marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert "deleted, no longer serving the old bytes (HTTP 000)" in result.output
