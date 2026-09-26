"""verify_security_headers() and verify_cache_headers() in scripts/deploy.sh.

Both read what the live site sends through the public URL, so every request
they make counts against nginx's per-IP rate limits the way a visitor's does.
They must not spend requests they do not need. Their probes go through
fetch_with_retry(), which repeats a request nginx answered with 503; the
console double-load in verify_cache_headers() does not, because a 503 is what
it looks for. Driven by the stubs in tests/deploy_probe.py, with no network.
"""

import re
import shutil

import pytest

from tests.deploy_probe import BASE_URL, DEPLOY_SH, REPO_ROOT, marker, run_probe

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


NO_CACHE = (("Cache-Control", "no-cache"), ("Expires", "Thu, 01 Jan 1970 00:00:01 GMT"))
A_WEEK_IMMUTABLE = (("Cache-Control", "max-age=604800"), ("Cache-Control", "public, immutable"))
REVALIDATED = ["/", "/css/style.css", "/admin/", "/admin/css/admin.css", "/admin/js/admin.js"]
FONT = "/fonts/jetbrains-mono-latin.woff2"
CONSOLE = [
    "/admin/",
    "/css/fonts.css",
    "/css/tokens.css",
    "/admin/css/admin.css",
    "/admin/js/admin.js",
]


def lowered(headers):
    # HTTP/2, which production speaks, sends every header name in lowercase.
    return tuple((name.lower(), value) for name, value in headers)


def cache_rows(overrides=None, lower=False):
    """A correctly configured site, except for the paths in `overrides`, each
    mapped to the rows served for it, in order."""
    rows = {path: [(BASE_URL + path, "200", "", NO_CACHE)] for path in {*REVALIDATED, *CONSOLE}}
    rows[FONT] = [(BASE_URL + FONT, "200", "", A_WEEK_IMMUTABLE)]
    rows.update(overrides or {})
    table = [row for path in sorted(rows) for row in rows[path]]
    if lower:
        table = [(*row[:3], lowered(row[3])) if len(row) > 3 else row for row in table]
    return table


def probe_cache(workdir, overrides=None, lower=False):
    return run_probe(workdir, "verify_cache_headers", http_table=cache_rows(overrides, lower))


def test_lowercase_security_header_names_pass(workdir):
    rows = [served(path, headers=lowered(SECURITY_HEADERS)) for path in SECURITY_PATHS]
    result = probe_security(workdir, rows)
    assert marker(result.output, "VERIFY_FAILURES") == 0, result.output


@pytest.mark.parametrize("lower", [False, True], ids=["http1", "http2"])
def test_a_correctly_configured_site_passes(workdir, lower):
    result = probe_cache(workdir, lower=lower)
    assert marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert "[FAIL]" not in result.output


def test_a_stylesheet_still_cached_for_a_week_fails(workdir):
    css = "/css/style.css"
    result = probe_cache(workdir, {css: [(BASE_URL + css, "200", "", A_WEEK_IMMUTABLE)]})
    assert marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert (
        f"{css} -- Cache-Control 'max-age=604800,public, immutable', want 'no-cache'"
        in result.output
    )


@pytest.mark.parametrize("lower", [False, True], ids=["http1", "http2"])
def test_a_second_cache_control_header_on_a_revalidated_path_fails(workdir, lower):
    # What an add_header left on top of `expires epoch` would send.
    js = "/admin/js/admin.js"
    both = (("Cache-Control", "no-cache"), ("Cache-Control", "public, immutable"))
    result = probe_cache(workdir, {js: [(BASE_URL + js, "200", "", both)]}, lower=lower)
    assert marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert f"{js} -- Cache-Control 'no-cache,public, immutable', want 'no-cache'" in result.output


def test_a_font_that_lost_immutable_fails(workdir):
    result = probe_cache(workdir, {FONT: [(BASE_URL + FONT, "200", "", NO_CACHE)]})
    assert marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert f"{FONT} -- HTTP 200, Cache-Control 'no-cache', want immutable" in result.output


def test_a_font_that_also_revalidates_fails(workdir):
    # The opposite mistake: the font block inheriting `expires epoch` while
    # keeping its own add_header.
    both = (("Cache-Control", "no-cache"), ("Cache-Control", "public, immutable"))
    result = probe_cache(workdir, {FONT: [(BASE_URL + FONT, "200", "", both)]})
    assert marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert "Cache-Control 'no-cache,public, immutable', want immutable" in result.output


def test_the_console_is_loaded_twice_after_a_pause_without_retries(workdir):
    result = probe_cache(workdir)
    assert marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert result.sleeps == ["2"]
    probes = [BASE_URL + path for path in [*REVALIDATED, FONT]]
    load = [BASE_URL + path for path in CONSOLE]
    assert result.calls == probes + load + load


def test_the_console_list_is_what_admin_index_html_loads():
    # deploy.sh runs one deploy behind itself, so when the console's page
    # gains or renames a stylesheet or script, its list must change a deploy
    # ahead. This test is what notices.
    html = (REPO_ROOT / "frontend" / "public" / "admin" / "index.html").read_text(encoding="utf-8")
    assets = re.findall(r'<link rel="stylesheet" href="([^"]+)"|<script src="([^"]+)"', html)
    assert ["/admin/", *(css or js for css, js in assets)] == CONSOLE


def test_a_503_while_loading_the_console_fails_and_is_not_retried(workdir):
    tokens = "/css/tokens.css"
    rows = [(BASE_URL + tokens, "200", "", NO_CACHE), (BASE_URL + tokens, "503", "")]
    result = probe_cache(workdir, {tokens: rows})
    assert marker(result.output, "VERIFY_FAILURES") == 1, result.output
    assert f"{tokens} (load 2 of 2) -- HTTP 503" in result.output
    assert result.calls.count(BASE_URL + tokens) == 2


def test_a_rate_limited_cache_probe_is_retried(workdir):
    js = "/admin/js/admin.js"
    rows = [(BASE_URL + js, "503", ""), (BASE_URL + js, "200", "", NO_CACHE)]
    result = probe_cache(workdir, {js: rows})
    assert marker(result.output, "VERIFY_FAILURES") == 0, result.output
    # The retry's pause, then the pause before the console loads.
    assert result.sleeps == ["2", "2"]
    # The probe, its retry, and one request per load.
    assert result.calls.count(BASE_URL + js) == 4


def test_a_checkout_without_the_policy_is_not_checked(workdir):
    # A rollback to a commit from before the policy restores the old headers,
    # and the deploy doing it must not fail for that.
    conf = workdir / "nginx" / "sites" / "production" / "production.conf"
    conf.write_text("server {\n    location / {\n    }\n}\n")
    result = probe_cache(workdir)
    assert marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert result.calls == []
    assert "production profile in this checkout sets no revalidation policy" in result.output
    # Expected right after such a rollback, and a warning any other time.
    assert "[WARN]" in result.output


def test_a_respaced_directive_still_counts(workdir):
    conf = workdir / "nginx" / "sites" / "production" / "production.conf"
    conf.write_text("server {\n    location / {\n        expires epoch ;\n    }\n}\n")
    result = probe_cache(workdir)
    assert marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert result.calls, "`expires epoch ;` was not recognised, and the check skipped"


@pytest.mark.parametrize(
    "site, checked", [("production", True), ("dev", False), ("bootstrap", False)]
)
def test_the_checkout_s_own_profiles_are_read_as_intended(workdir, site, checked):
    # The real nginx/sites/, so a directive respaced or moved into an include
    # cannot switch the check off in production without this failing.
    shutil.copytree(REPO_ROOT / "nginx" / "sites", workdir / "nginx" / "sites", dirs_exist_ok=True)
    (workdir / ".env").write_text(f"NGINX_SITE={site}\n")
    result = probe_cache(workdir)
    assert marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert bool(result.calls) is checked


def test_the_active_profile_decides(workdir):
    # The dev and bootstrap profiles set no cache policy, even when the
    # production one does.
    (workdir / ".env").write_text("NGINX_SITE=dev\n")
    result = probe_cache(workdir)
    assert marker(result.output, "VERIFY_FAILURES") == 0, result.output
    assert result.calls == []
    assert "dev profile in this checkout sets no revalidation policy" in result.output


def test_verify_all_runs_the_cache_check():
    source = DEPLOY_SH.read_text(encoding="utf-8")
    body = re.search(r"^verify_all\(\) \{\n(.*?)^\}", source, re.M | re.S)
    assert body, "verify_all() not found in scripts/deploy.sh"
    assert re.search(r"^\s+verify_cache_headers$", body.group(1), re.M)
