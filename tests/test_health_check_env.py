"""health_check.sh must let .env change a setting that has a default.

README.md documents STALE_AFTER_HOURS, ALERT_REMIND_HOURS, DISK_WARN_PCT,
DISK_CRIT_PCT and MIRROR_DATA_PATH as `.env` settings, and scripts/setup.sh
writes the first two into every new .env. The script ignored all five: it
assigned their defaults as it loaded, and load_env only filled in variables
that were still empty, which a defaulted one never is. Under the systemd timer,
whose unit sets no Environment=, .env is the only place to set them, so tuning
a threshold there changed nothing and said nothing.

The precedence is the environment, then .env, then the default. These tests
run the script's own load_env in bash rather than restating that rule in
Python: the script is run with its final `main "$@"` line removed, which
defines everything and runs no check.
"""

import os
import pathlib
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "health_check.sh"

# (key, built-in default, a different value). The defaults are asserted by
# test_default_applies_when_nothing_sets_it, so a stale entry here fails
# rather than quietly making the other tests vacuous.
DEFAULTED = [
    ("STALE_AFTER_HOURS", "36", "12"),
    ("ALERT_REMIND_HOURS", "24", "6"),
    ("DISK_WARN_PCT", "85", "70"),
    ("DISK_CRIT_PCT", "95", "90"),
    ("MIRROR_DATA_PATH", "/data/mirrors", "/srv/mirrors"),
]

PRINT_CONFIG = """
QUIET=1
load_env
for key in "${DOTENV_KEYS[@]}"; do printf '%s=%s\\n' "$key" "${!key}"; done
"""


def _definitions_only():
    text = SCRIPT.read_text()
    body, entry, rest = text.rpartition('\nmain "$@"\n')
    assert entry and not rest, 'health_check.sh must end with its `main "$@"` call'
    return body + "\n"


def load_config(tmp_path, environ, dotenv):
    """Run load_env and return every DOTENV_KEYS variable it leaves behind.

    `environ` is the whole environment apart from PATH and ENV_FILE, so nothing
    set on the machine running the suite can leak into the result. A `dotenv`
    of None means no .env file exists.
    """
    env_file = tmp_path / ".env"
    if dotenv is not None:
        env_file.write_text(dotenv)
    # A file, not `bash -c` (an argument has a size limit the script is heading
    # for) and not stdin (a command that reads stdin would eat the script).
    probe = tmp_path / "probe.sh"
    probe.write_text(_definitions_only() + PRINT_CONFIG)
    result = subprocess.run(
        ["bash", str(probe)],
        env={"PATH": os.environ["PATH"], "ENV_FILE": str(env_file), **environ},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    config = {}
    for line in result.stdout.splitlines():
        key, _, value = line.partition("=")
        config[key] = value
    return config


@pytest.mark.parametrize(("key", "default", "other"), DEFAULTED)
def test_default_applies_when_nothing_sets_it(tmp_path, key, default, other):
    config = load_config(tmp_path, environ={}, dotenv="UNRELATED=1\n")
    assert config[key] == default


@pytest.mark.parametrize(("key", "default", "other"), DEFAULTED)
def test_dotenv_replaces_the_default(tmp_path, key, default, other):
    # Before the fix this came back as the default for every one of the five.
    config = load_config(tmp_path, environ={}, dotenv=f"{key}={other}\n")
    assert config[key] == other


@pytest.mark.parametrize(("key", "default", "other"), DEFAULTED)
def test_environment_wins_over_dotenv(tmp_path, key, default, other):
    # The environment value IS the default, on purpose: a fix that asked "is it
    # still the default?" instead of "did the environment set it?" would let
    # .env win here.
    config = load_config(tmp_path, environ={key: default}, dotenv=f"{key}={other}\n")
    assert config[key] == default


def test_empty_environment_value_does_not_block_dotenv(tmp_path):
    config = load_config(
        tmp_path, environ={"STALE_AFTER_HOURS": ""}, dotenv="STALE_AFTER_HOURS=12\n"
    )
    assert config["STALE_AFTER_HOURS"] == "12"


def test_every_dotenv_key_is_read(tmp_path):
    keys = set(load_config(tmp_path, environ={}, dotenv=None))
    assert {key for key, _, _ in DEFAULTED} <= keys
    dotenv = "".join(f"{key}=from-dotenv-{key}\n" for key in sorted(keys))
    config = load_config(tmp_path, environ={}, dotenv=dotenv)
    assert config == {key: f"from-dotenv-{key}" for key in keys}
