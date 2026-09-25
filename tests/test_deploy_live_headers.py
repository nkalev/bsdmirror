"""verify_security_headers() and verify_cache_headers() in scripts/deploy.sh.

Both read what the live site sends through the public URL, so every request
they make counts against nginx's per-IP rate limits the way a visitor's does.
They must not spend requests they do not need. Their probes go through
fetch_with_retry(), which repeats a request nginx answered with 503; the
console double-load in verify_cache_headers() does not, because a 503 is what
it looks for. Driven by the stubs in tests/deploy_probe.py, with no network.
"""

import pytest

from tests.deploy_probe import BASE_URL, marker, run_probe

CSP = "default-src 'self'; script-src 'self'"
SECURITY_HEADERS = (
    ("X-Frame-Options", "DENY"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ("Content-Security-Policy", CSP),
)
PROBE_404 = "/css/nope-deploy-probe-404.css"
SECURITY_PATHS = [
    "/",
    "/admin/",
    "/admin/js/admin.js",
    "/css/style.css",
    "/img/favicon.svg",
    "/api/health",
    "/health",
    "/404.html",
    PROBE_404,
    "/FreeBSD/",
]


@pytest.fixture
def workdir(tmp_path):
    """A checkout holding only what the checks read: the CSP in nginx.conf,
    the active profile in .env, and that profile's cache policy."""
    d = tmp_path / "checkout"
    (d / "nginx" / "sites" / "production").mkdir(parents=True)
    (d / "nginx" / "nginx.conf").write_text(
        'http {\n    map $host $csp_policy {\n        default "%s";\n    }\n}\n' % CSP
    )
    (d / "nginx" / "sites" / "production" / "production.conf").write_text(
        "server {\n    location / {\n        expires epoch;\n    }\n}\n"
    )
    (d / ".env").write_text("NGINX_SITE=production\n")
    return d


def served(path, code=None, headers=SECURITY_HEADERS):
    # In production a missing stylesheet is a real 404; every other path answers 200.
    if code is None:
        code = "404" if path == PROBE_404 else "200"
    return (BASE_URL + path, code, "", headers)


def with_csp(value):
    return tuple(
        (name, value) if name == "Content-Security-Policy" else (name, old)
        for name, old in SECURITY_HEADERS
    )


def probe_security(workdir, rows):
    return run_probe(workdir, "verify_security_headers", http_table=rows)


def test_admin_js_is_one_of_the_probed_paths(workdir):
    result = probe_security(workdir, [served(path) for path in SECURITY_PATHS])
    assert marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert BASE_URL + "/admin/js/admin.js" in result.calls


def test_each_path_is_requested_once_and_its_headers_reused_for_the_csp_check(workdir):
    result = probe_security(workdir, [served(path) for path in SECURITY_PATHS])
    assert marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert result.calls == [BASE_URL + path for path in SECURITY_PATHS]


def test_a_rate_limited_path_is_requested_again(workdir):
    rows = [
        served("/css/style.css", code="503", headers=()),
        *(served(path) for path in SECURITY_PATHS),
    ]
    result = probe_security(workdir, rows)
    assert marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert result.calls.count(BASE_URL + "/css/style.css") == 2
    assert result.sleeps == ["2"]


def test_a_path_missing_a_header_fails(workdir):
    rows = [served(path) for path in SECURITY_PATHS if path != "/admin/js/admin.js"]
    rows.append(served("/admin/js/admin.js", headers=SECURITY_HEADERS[1:]))
    result = probe_security(workdir, rows)
    assert marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert "1 of 10 probed paths failed the header check" in result.output


def test_a_path_that_does_not_answer_fails(workdir):
    rows = [served(path) for path in SECURITY_PATHS if path != "/FreeBSD/"]
    result = probe_security(workdir, rows)
    assert marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert f"/FreeBSD/ -- no response from {BASE_URL}" in result.output
    assert "1 of 10 probed paths failed the header check" in result.output


def test_a_csp_that_differs_from_the_checkout_fails(workdir):
    stale = with_csp("default-src *")
    result = probe_security(workdir, [served(path, headers=stale) for path in SECURITY_PATHS])
    assert marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert "does not match this checkout's nginx.conf" in result.output


def test_two_different_csp_values_fail(workdir):
    # Every header dump is read: here only the last path disagrees.
    rows = [served(path) for path in SECURITY_PATHS if path != "/FreeBSD/"]
    rows.append(served("/FreeBSD/", headers=with_csp("default-src 'none'")))
    result = probe_security(workdir, rows)
    assert marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert "2 different Content-Security-Policy values are being served" in result.output


def test_the_404_probe_must_get_a_404_in_production(workdir):
    rows = [served(path) for path in SECURITY_PATHS if path != PROBE_404]
    rows.append(served(PROBE_404, code="200"))
    result = probe_security(workdir, rows)
    assert marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert f"{PROBE_404} -- HTTP 200, expected 404" in result.output
    assert "1 of 10 probed paths failed the header check" in result.output


def test_outside_production_the_404_probe_may_get_the_spa_shell(workdir):
    (workdir / ".env").write_text("NGINX_SITE=dev\n")
    rows = [served(path) for path in SECURITY_PATHS if path != PROBE_404]
    rows.append(served(PROBE_404, code="200"))
    result = probe_security(workdir, rows)
    assert marker(result.output, "VERIFY_FAILURES") == 0, result.output


@pytest.mark.parametrize("code, calls", [("503", 4), ("502", 1)])
def test_a_path_answered_by_the_error_page_goes_unprobed(workdir, code, calls):
    # The stub repeats a URL's last row, so a lone 503 stays a 503 through
    # every retry. The error page carries the full header set, which proves
    # nothing about the block the path is meant to probe.
    rows = [served(path) for path in SECURITY_PATHS if path != "/css/style.css"]
    rows.append(served("/css/style.css", code=code))
    result = probe_security(workdir, rows)
    assert marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert f"/css/style.css -- HTTP {code}: the error page answered" in result.output
    assert result.calls.count(BASE_URL + "/css/style.css") == calls


def test_over_https_every_path_needs_hsts(workdir):
    https = "https://example.invalid"
    rows = [
        (https + path, "404" if path == PROBE_404 else "200", "", SECURITY_HEADERS)
        for path in SECURITY_PATHS
    ]
    result = run_probe(workdir, "verify_security_headers", http_table=rows, base_url=https)
    assert marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert "10 of 10 probed paths failed the header check" in result.output
    assert "strict-transport-security" in result.output
