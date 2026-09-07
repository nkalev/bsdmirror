"""
The running system reporting which commit it is.

Two hardcoded version strings existed before this change and had already
disagreed: frontend/public/index.html's `v1.0.1` and
backend/app/core/config.py's `VERSION = "1.0.0"`. Neither had ever been
bumped. This file guards the replacement end to end:

  1. backend/app/core/config.py -- GIT_SHA/BUILD_DATE compose into
     Settings.VERSION, with an honest ("unknown", never a plausible-looking
     placeholder) default when neither is set.
  2. backend/app/api/health.py -- /api/health and /api/health/detailed report
     that same value, so there is exactly one source of truth on the backend.
  3. frontend/public/js/main.js -- FooterVersion.load() fetches it and writes
     it into .footer-version, or leaves the element untouched if the API is
     unreachable, non-2xx, unparsable, or missing the field. Exercised
     behaviourally by shelling out to `node tests/js/footer_version_harness.mjs`
     (there is no JS test runner in this repo -- see test_admin_js_escaping.py
     for the same approach against admin.js), then mutation-tested the same
     way: break FooterVersion on purpose, in a tmp_path copy, and require the
     suite to notice.
  4. Both hardcoded strings are gone as sources of truth, asserted
     structurally so a revert cannot silently reintroduce either.

What this does not prove: that a real browser renders the fetched value
in a live DOM (the harness stubs querySelector/fetch, same trade-off
escaping_harness.mjs makes for admin.js), and it does not prove nginx or the
built image actually carry a real GIT_SHA -- that half is
scripts/deploy.sh's verify_deployed_version(), exercised only on a live
deploy.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

from app.core.config import Settings, settings

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_PY = REPO_ROOT / "backend" / "app" / "core" / "config.py"
INDEX_HTML = REPO_ROOT / "frontend" / "public" / "index.html"
MAIN_JS = REPO_ROOT / "frontend" / "public" / "js" / "main.js"
HARNESS = REPO_ROOT / "tests" / "js" / "footer_version_harness.mjs"

NODE = shutil.which("node")
requires_node = pytest.mark.skipif(
    NODE is None,
    reason="node is not installed; the behavioural footer-version checks cannot run",
)

REQUIRED_SETTINGS_KWARGS = {
    "POSTGRES_PASSWORD": "x",
    "REDIS_PASSWORD": "x",
    "SECRET_KEY": "x",
    "ADMIN_PASSWORD": "x",
}


# ---------------------------------------------------------------------------
# 1. Settings.VERSION
# ---------------------------------------------------------------------------
def test_version_composes_git_sha_and_build_date():
    s = Settings(GIT_SHA="2250188", BUILD_DATE="2026-09-07", **REQUIRED_SETTINGS_KWARGS)
    assert s.VERSION == "2250188-2026-09-07"


def test_version_default_is_obviously_not_a_real_build():
    # _env_file=None: a real .env on the machine running this suite must not
    # leak in and make this test pass for the wrong reason.
    s = Settings(_env_file=None, **REQUIRED_SETTINGS_KWARGS)
    assert s.GIT_SHA == "unknown"
    assert s.BUILD_DATE == "unknown"
    assert s.VERSION == "unknown-unknown"
    # The brief's own bar: not a value that could pass for a real one.
    assert not s.VERSION[0].isdigit()


# ---------------------------------------------------------------------------
# 2. The API surfaces it, identically, everywhere it appears
# ---------------------------------------------------------------------------
async def test_api_health_reports_settings_version(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["version"] == settings.VERSION


async def test_health_and_detailed_health_report_the_same_version(client):
    basic = await client.get("/api/health")
    detailed = await client.get("/api/health/detailed")
    assert basic.status_code == 200
    assert detailed.status_code == 200
    assert basic.json()["version"] == settings.VERSION
    assert detailed.json()["version"] == settings.VERSION


async def test_root_endpoint_reports_settings_version(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert resp.json()["version"] == settings.VERSION


def test_fastapi_app_metadata_reports_settings_version():
    from app.main import app

    assert app.version == settings.VERSION


# ---------------------------------------------------------------------------
# 3. Frontend wiring: tests/js/footer_version_harness.mjs
# ---------------------------------------------------------------------------
def run_harness(source_path):
    """Run the node harness against `source_path`, return {name: (ok, detail)}."""
    proc = subprocess.run(
        [NODE, str(HARNESS), str(source_path)],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, (
        f"harness crashed (rc={proc.returncode})\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    payload = json.loads(proc.stdout)
    assert not payload.get("loadError"), f"harness failed to load main.js: {payload['loadError']}"
    return {c["name"]: (c["ok"], c["detail"]) for c in payload["checks"]}


@pytest.fixture(scope="module")
def harness_results():
    return run_harness(MAIN_JS)


HARNESS_CHECKS = [
    "load writes the reported version into .footer-version",
    "load requests /api/health for the version",
    "load leaves the footer untouched when the API is unreachable",
    "load leaves the footer untouched on a non-2xx response",
    "load leaves the footer untouched when the response has no version field",
    "load leaves the footer untouched on malformed JSON",
    "load does not throw when .footer-version is not on the page",
]


@requires_node
@pytest.mark.parametrize("check_name", HARNESS_CHECKS)
def test_footer_version_behaviour(harness_results, check_name):
    assert check_name in harness_results, (
        f"harness did not run {check_name!r}; it reported {sorted(harness_results)}"
    )
    ok, detail = harness_results[check_name]
    assert ok, detail


@requires_node
def test_harness_check_list_is_complete(harness_results):
    """The parametrised list must not drift behind the harness."""
    assert sorted(harness_results) == sorted(HARNESS_CHECKS)


# ---------------------------------------------------------------------------
# Mutation testing
#
# Same approach as test_admin_js_escaping.py: break FooterVersion on purpose,
# in a tmp_path copy (main.js on disk is never touched), and require the
# suite to notice. A test that passes against a deliberately broken wiring is
# not testing the wiring.
#
# (name, old, new, must_fail) -- must_fail names one check that has to go red,
# so a mutation cannot be "caught" by some unrelated assertion.
# ---------------------------------------------------------------------------
MUTATIONS = [
    (
        # The exact shape of the bug this whole change exists to prevent: the
        # value is fetched successfully and never actually written anywhere.
        "forgets_to_assign_the_fetched_value",
        "        el.textContent = data.version;",
        "        // forgot to assign",
        "load writes the reported version into .footer-version",
    ),
    (
        "queries_the_wrong_endpoint",
        "        const data = await API.get('/health');",
        "        const data = await API.get('/healthz');",
        "load requests /api/health for the version",
    ),
    (
        # Drops the guard that stops a response without "version" from being
        # written as the literal string "undefined".
        "drops_the_missing_version_guard",
        "        if (!data || !data.version) return;",
        "        if (!data) return;",
        "load leaves the footer untouched when the response has no version field",
    ),
    (
        # Drops the guard against a missing element -- a future markup change
        # would then throw out of an async handler nothing awaits.
        "drops_the_missing_element_guard",
        "        if (!el) return;\n\n        const data",
        "        const data",
        "load does not throw when .footer-version is not on the page",
    ),
]


@requires_node
@pytest.mark.parametrize(
    "name,old,new,must_fail", MUTATIONS, ids=[m[0] for m in MUTATIONS]
)
def test_mutation_is_caught(tmp_path, name, old, new, must_fail):
    source = MAIN_JS.read_text(encoding="utf-8")
    assert source.count(old) == 1, (
        f"mutation {name!r} no longer matches main.js exactly once "
        f"(found {source.count(old)}). Update the mutation, do not delete it."
    )

    mutated = tmp_path / "main.js"
    mutated.write_text(source.replace(old, new), encoding="utf-8")

    results = run_harness(mutated)
    failed = sorted(n for n, (ok, _) in results.items() if not ok)
    assert failed, (
        f"mutation {name!r} broke FooterVersion and every check still passed. "
        f"The suite does not test what it claims to."
    )
    assert must_fail in failed, (
        f"mutation {name!r} was expected to fail {must_fail!r}, "
        f"but the failures were {failed}"
    )


# ---------------------------------------------------------------------------
# 4. Both hardcoded strings are gone as sources of truth
# ---------------------------------------------------------------------------
def test_config_no_longer_hardcodes_a_version_string():
    source = CONFIG_PY.read_text(encoding="utf-8")
    assert '"1.0.0"' not in source
    assert "'1.0.0'" not in source


def test_index_html_no_longer_hardcodes_a_version_string():
    source = INDEX_HTML.read_text(encoding="utf-8")
    assert "v1.0.1" not in source
    assert 'class="footer-version"' in source, (
        "the element itself should still be there for main.js to populate"
    )
