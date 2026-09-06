"""No file that can hold a credential may be committable.

This repository is public. `.gitignore` covered `.env` and `.credentials` and
nothing else -- not the backups of them, which is where the risk actually sits:

  scripts/backup.sh:8   BACKUP_DIR defaults to /opt/bsdmirror/backups, INSIDE
                        the git working tree, and line 31 copies .env there as
                        env_<ts>.backup next to a gzipped pg_dump of the whole
                        database. Every run adds another unignored copy.
  .deploy-bak/          deploy-time copies, including env.<ts>.bak
  .env.bak.<ts>         observed on the production host

Two such files exist on production today holding all four of
POSTGRES_PASSWORD, REDIS_PASSWORD, SECRET_KEY and ADMIN_PASSWORD in plaintext.
They are mode 600 and were never committed -- checked with `git log --all` over
those paths.

Calibrate the risk honestly: deployment is one-way, repo -> server. Nobody
commits from /opt/bsdmirror, so the production copies are not realistically
one command from being published. What this guards is the developer side,
where the same defaults apply and the direction of travel is toward the public
remote: `scripts/backup.sh` run in a local clone writes .env and a full
database dump into ./backups/, and before this file existed nothing there was
ignored. That is a plausible accident, not a hypothetical one.

The filenames below are the REAL ones observed on the host, not invented
examples. A pattern that matches a plausible name but not the actual one is
the failure this test exists to prevent.
"""

import pathlib
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

MUST_BE_IGNORED = [
    ".env",
    ".credentials",
    ".env.bak.20260829_222237",
    ".deploy-bak/env.20260831_141742.bak",
    ".deploy-bak/pre-alembic-20260901_073911.sql.gz",
    ".deploy-bak/production.conf.20260831_110448",
    "backups/env_20260906_120000.backup",
    "backups/db_20260906_120000.sql.gz",
]

MUST_NOT_BE_IGNORED = [
    "backend/app/main.py",
    "docker-compose.yml",
    ".gitignore",
    "scripts/backup.sh",
]


def _is_ignored(relpath: str) -> bool:
    """Ask git itself. Re-implementing .gitignore matching in the test would
    mean testing our reimplementation, not the file git actually obeys."""
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", "--no-index", relpath],
            cwd=REPO_ROOT,
            capture_output=True,
        )
    except (FileNotFoundError, OSError) as exc:
        # git is not in the test image, and a linked worktree's `.git` is a
        # file pointing at an absolute host path the container cannot follow.
        # Skipping is right here and wrong in CI, which is why this module is
        # named in ci.yml's skip-detector REQUIRED tuple.
        pytest.skip("git unusable in this environment: %s" % exc)
    if result.returncode not in (0, 1):
        pytest.skip("git check-ignore failed: %s" % result.stderr.decode()[:200])
    return result.returncode == 0


@pytest.mark.parametrize("relpath", MUST_BE_IGNORED)
def test_secret_bearing_paths_are_ignored(relpath):
    assert _is_ignored(relpath), (
        "%s is NOT ignored. This repository is public; a `git add -A` on the "
        "production host would commit it. Add a pattern to .gitignore." % relpath
    )


@pytest.mark.parametrize("relpath", MUST_NOT_BE_IGNORED)
def test_the_check_can_tell_the_difference(relpath):
    """A matcher that returns True for everything would pass the test above
    while proving nothing. These are tracked files; they must NOT be ignored."""
    assert not _is_ignored(relpath), (
        "%s is ignored, which means .gitignore has grown a pattern far too "
        "broad -- tracked source is being excluded." % relpath
    )


def test_no_credential_backup_was_ever_committed():
    """The decisive question, asserted rather than remembered.

    If this ever fails, .gitignore is not the fix: the credentials are in the
    public history and must be rotated.
    """
    try:
        result = subprocess.run(
            ["git", "log", "--all", "--format=%H", "--",
             "*.env.bak*", ".deploy-bak/*", "backups/*", "env_*.backup"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, OSError) as exc:
        pytest.skip("git unusable in this environment: %s" % exc)
    if result.returncode != 0:
        pytest.skip("git log unavailable: %s" % result.stderr[:200])
    commits = [c for c in result.stdout.split() if c]
    assert not commits, (
        "credential/backup paths appear in %d commit(s): %s. These are in the "
        "history of a PUBLIC repository -- rotate POSTGRES_PASSWORD, "
        "REDIS_PASSWORD, SECRET_KEY and ADMIN_PASSWORD, do not just gitignore "
        "them." % (len(commits), commits[:5])
    )
