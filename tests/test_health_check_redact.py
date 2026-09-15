"""redact() in scripts/health_check.sh must work under BSD/onetrue awk, not
only under mawk/gawk.

redact_register builds REDACT_LIST as a newline-separated blob (one secret per
line), and main() registers DISCORD_WEBHOOK_URL and SLACK_WEBHOOK once either
is 12+ characters. redact() used to hand that blob to awk with `-v
secrets="$REDACT_LIST"`. BSD/onetrue awk -- what macOS ships, and what a
contributor's manual run or `--test-alert` from a laptop uses (see the comment
above check_containers in the script) -- refuses a `-v name=value` whose value
contains a literal newline, with "newline in string", so every line the script
tried to print broke there the moment a webhook was configured. mawk and
gawk, on the Ubuntu deploy target, silently accept it, which is why production
never showed this. The fix passes the secret list through that one awk
process's environment instead (`REDACT_SECRETS="$REDACT_LIST" awk '...
ENVIRON["REDACT_SECRETS"] ...'`), which is not parsed as a `-v` assignment and
is immune to embedded newlines.

Redaction is security-critical: every logged line and every status.json string
passes through redact() first (see test_health_check_status.py's own
Redaction section for the status.json half of that contract), so a regression
here is a webhook URL reaching a terminal, the journal, or the admin
dashboard.

These tests run scripts/health_check.sh with its own trailing `main "$@"`
stripped -- the same trick test_health_check_env.py and
test_health_check_status.py use -- and then call redact_register/redact
directly. Each behavioural run gets a PATH built from scratch containing only
`bash` and one specific `awk` binary (symlinked in as the literal name
`awk`), so the test controls exactly which awk implementation redact()'s
`awk` invocation resolves to, independent of whatever the ambient PATH
happens to offer.
"""

import pathlib
import shlex
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "health_check.sh"

DEFAULT_AWK = shutil.which("awk")
ORIGINAL_AWK = shutil.which("original-awk")

assert DEFAULT_AWK is not None, "no awk at all on PATH -- nothing here can run"

# original-awk is Debian's package for onetrue-awk, the "one true awk" lineage
# macOS ships as /usr/bin/awk (see Dockerfile.test's comment on the apt line
# that installs it for `docker compose run --rm test`). It is deliberately
# NOT required: the bare ubuntu-24.04 runner .github/workflows/ci.yml's
# `pytest` job uses has no step installing it, and workflow files are out of
# scope for the change that added this file, so that job can only ever
# exercise the "awk" (mawk there) case below until someone gives it the
# package too.
ORIGINAL_AWK_SKIP_REASON = (
    "original-awk not on PATH -- Dockerfile.test installs it for the `test` "
    "compose service, but ubuntu-24.04's bare `pytest` CI job has no "
    "workflow step that does, and workflow files are out of scope here"
)

AWK_VARIANTS = [
    pytest.param(DEFAULT_AWK, id="awk"),
    pytest.param(
        ORIGINAL_AWK,
        id="original-awk",
        marks=pytest.mark.skipif(ORIGINAL_AWK is None, reason=ORIGINAL_AWK_SKIP_REASON),
    ),
]

# One secret carries every regex metacharacter redact()'s header comment
# warns about (. * ? [ ] + ( )), to prove the awk-side match is index()'s
# literal substring search and not a pattern match -- matching too much here
# is the dangerous direction. The other is a plain-looking webhook URL. Both
# are well over the 12-character floor; SHORT_STRING is well under it.
SECRET_WITH_METACHARS = "https://discord.com/api/webhooks/123/a.b*c?d[e]+(f)"
SECRET_PLAIN = "https://hooks.slack.com/services/T000/B000/XXXXXXXXXXXXXXXXXXXXXXXX"
SHORT_STRING = "short"

assert len(SECRET_WITH_METACHARS) >= 12
assert len(SECRET_PLAIN) >= 12
assert len(SHORT_STRING) < 12

# Built once and rendered twice (real secrets, then the redaction marker) so
# the "everything else is unchanged" claim is structural rather than
# eyeballed: every word other than {a}/{b}/{s} is byte-for-byte identical
# between INPUT_TEXT and EXPECTED_OUTPUT below. Line 2 repeats the
# metacharacter secret twice on one line, on purpose.
_LINE_TEMPLATES = [
    "alpha {a} bravo",
    "{a} charlie {a}",
    "delta {b} echo {s} foxtrot",
    "golf hotel india",
]


def _render(secret_a: str, secret_b: str, short: str) -> str:
    return "\n".join(t.format(a=secret_a, b=secret_b, s=short) for t in _LINE_TEMPLATES)


INPUT_TEXT = _render(SECRET_WITH_METACHARS, SECRET_PLAIN, SHORT_STRING)
EXPECTED_OUTPUT = _render("<redacted>", "<redacted>", SHORT_STRING)


def _definitions_only():
    text = SCRIPT.read_text()
    body, entry, rest = text.rpartition('\nmain "$@"\n')
    assert entry and not rest, 'health_check.sh must end with its `main "$@"` call'
    return body + "\n"


def _awk_only_path(tmp_path, awk_path):
    """A PATH containing only `bash` and `awk` (symlinked to awk_path).

    Narrower than test_health_check_status.py's allowlist shim on purpose:
    these tests call nothing but redact_register/redact, which -- unlike
    write_status or the real checks -- shell out to nothing but awk, so
    nothing else needs to be reachable.
    """
    shim = tmp_path / "shim-bin"
    shim.mkdir(exist_ok=True)
    bash_path = shutil.which("bash")
    assert bash_path, "bash must be on PATH to run the probe at all"
    (shim / "bash").symlink_to(bash_path)
    (shim / "awk").symlink_to(awk_path)
    return str(shim)


def run_probe(tmp_path, awk_path, script_body):
    """Run `script_body` appended after the script's own definitions, with
    PATH pinned so `awk` resolves to exactly `awk_path`.

    A fresh probe.sh per call, matching test_health_check_env.py and
    test_health_check_status.py: a file rather than `bash -c` or stdin.
    """
    probe = tmp_path / "probe.sh"
    probe.write_text(_definitions_only() + script_body)
    env = {"PATH": _awk_only_path(tmp_path, awk_path)}
    return subprocess.run(
        ["bash", str(probe)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


# ---------------------------------------------------------------------------
# Behaviour: literal secrets are redacted, everything else is untouched,
# under both the default awk (mawk here, the same family as the Ubuntu
# deploy target) and original-awk (the BSD/onetrue lineage macOS ships).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("awk_path", AWK_VARIANTS)
def test_redact_replaces_literal_secrets_and_leaves_everything_else(tmp_path, awk_path):
    script = f"""
redact_register {shlex.quote(SECRET_WITH_METACHARS)}
redact_register {shlex.quote(SECRET_PLAIN)}
redact_register {shlex.quote(SHORT_STRING)}
printf '%s' "$(redact {shlex.quote(INPUT_TEXT)})"
"""
    result = run_probe(tmp_path, awk_path, script)
    assert result.returncode == 0, result.stderr
    assert "newline in string" not in result.stderr
    assert result.stdout == EXPECTED_OUTPUT
    assert SECRET_WITH_METACHARS not in result.stdout
    assert SECRET_PLAIN not in result.stdout
    # redact_register's own 12-character floor must still drop this one --
    # confirms the assertion above is exercising redact(), not a no-op.
    assert SHORT_STRING in result.stdout
    assert result.stdout.count("<redacted>") == 4


@pytest.mark.parametrize("awk_path", AWK_VARIANTS)
def test_redact_is_a_noop_with_nothing_registered(tmp_path, awk_path):
    script = f"printf '%s' \"$(redact {shlex.quote(INPUT_TEXT)})\"\n"
    result = run_probe(tmp_path, awk_path, script)
    assert result.returncode == 0, result.stderr
    assert result.stdout == INPUT_TEXT


# ---------------------------------------------------------------------------
# Structure: the secret list must never reach awk via `-v`, must never be
# exported into the rest of the script's environment, and must never appear
# in argv (where a co-tenant's `ps` would show it).
# ---------------------------------------------------------------------------


def _redact_function_body():
    source = SCRIPT.read_text()
    start = source.index("\nredact() {")
    end = source.index("\n}\n", start)
    return source[start:end]


def test_redact_does_not_pass_secrets_via_dash_v():
    body = _redact_function_body()
    assert "awk" in body, "sanity: redact() must still shell out to awk"
    assert "-v" not in body, (
        "redact() must not pass the secret list via `awk -v`: BSD/onetrue awk "
        "rejects a -v value containing a literal newline with 'newline in "
        "string', and REDACT_LIST is newline-separated the moment two "
        "secrets are registered"
    )
    assert (
        'ENVIRON["REDACT_SECRETS"]' in body
    ), "redact() must read the secret list back out of ENVIRON inside the awk program"
    # REDACT_LIST appears exactly twice: the early emptiness guard, and the
    # prefix assignment that hands it to that one awk process's own
    # environment (`NAME=value awk ...`) -- not as a `-v` assignment (checked
    # above) and not as a trailing argv word, which is what `ps` would show a
    # co-tenant on the box.
    assert body.count("REDACT_LIST") == 2
    assert 'REDACT_SECRETS="$REDACT_LIST" awk' in body


def test_redact_secrets_are_never_exported_into_the_script():
    source = SCRIPT.read_text()
    assert "export REDACT_LIST" not in source
    assert "export REDACT_SECRETS" not in source


def test_redact_secrets_env_var_does_not_leak_into_the_shell_environment(tmp_path):
    # Runtime counterpart to the static export check above: `export -p` is a
    # bash builtin listing only exported variables, so REDACT_SECRETS -- a
    # prefix assignment scoped to the single awk command -- must never show up
    # in it, even after a real redact() call has run.
    script = f"""
redact_register {shlex.quote(SECRET_PLAIN)}
redact "trigger a call so the assignment actually executes" >/dev/null
export -p
"""
    result = run_probe(tmp_path, DEFAULT_AWK, script)
    assert result.returncode == 0, result.stderr
    assert "REDACT_SECRETS" not in result.stdout
    assert "REDACT_LIST" not in result.stdout
