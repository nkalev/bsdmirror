"""scripts/backup.sh must keep backups out of the checkout and prune only its own files.

A backup is a full database dump plus a copy of .env. Its default location used
to be /opt/bsdmirror/backups, inside the git working tree of a public
repository; it is now /var/backups/bsdmirror. The script also deletes old
backups, so it refuses a BACKUP_DIR that is "/" or inside the checkout, and its
cleanup only ever matches the three file names it writes -- a dump kept there by
hand (the pre-Alembic one, for instance) is never pruned.

`docker exec ... pg_dump` is replaced by an exported bash function, so these
tests need neither Docker nor a database.
"""

import os
import pathlib
import re
import subprocess
import time

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "backup.sh"

# The function stands in for `docker exec bsdmirrors-postgres pg_dump ...`.
WITH_FAKE_DOCKER = 'docker() { printf "%s\\n" "-- fake dump"; }; export -f docker; exec bash "$SCRIPT"'


def run_backup(tmp_path, backup_dir, install_dir):
    return subprocess.run(
        ["bash", "-c", WITH_FAKE_DOCKER],
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "SCRIPT": str(SCRIPT),
            "BACKUP_DIR": str(backup_dir),
            "INSTALL_DIR": str(install_dir),
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def make_install(tmp_path):
    install = tmp_path / "opt" / "bsdmirror"
    (install / "nginx").mkdir(parents=True)
    (install / "nginx" / "site.conf").write_text("server {}\n")
    (install / ".env").write_text("SECRET_KEY=not-a-real-secret\n")
    return install


def test_the_default_backup_dir_is_outside_the_default_checkout():
    text = SCRIPT.read_text()
    backup = re.search(r'^BACKUP_DIR="\$\{BACKUP_DIR:-([^}]+)\}"', text, re.M)
    install = re.search(r'^INSTALL_DIR="\$\{INSTALL_DIR:-([^}]+)\}"', text, re.M)
    assert backup and install
    assert backup.group(1) == "/var/backups/bsdmirror"
    assert not backup.group(1).startswith(install.group(1).rstrip("/") + "/")


@pytest.mark.parametrize("inside", ["", "backups", "nested/deeper"], ids=["checkout", "child", "grandchild"])
def test_a_backup_dir_inside_the_checkout_is_refused(tmp_path, inside):
    install = make_install(tmp_path)
    target = install / inside if inside else install
    result = run_backup(tmp_path, target, install)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "Refusing BACKUP_DIR" in result.stderr
    if inside:
        assert not target.exists()


def test_the_filesystem_root_is_refused(tmp_path):
    install = make_install(tmp_path)
    result = run_backup(tmp_path, "/", install)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "Refusing BACKUP_DIR" in result.stderr


def test_backups_are_written_privately_outside_the_checkout(tmp_path):
    install = make_install(tmp_path)
    backups = tmp_path / "var" / "backups" / "bsdmirror"
    result = run_backup(tmp_path, backups, install)
    assert result.returncode == 0, result.stdout + result.stderr
    assert backups.stat().st_mode & 0o777 == 0o700
    names = [p.name for p in backups.iterdir()]
    assert any(re.fullmatch(r"db_[0-9_]+\.sql\.gz", n) for n in names), names
    assert any(re.fullmatch(r"env_[0-9_]+\.backup", n) for n in names), names
    assert any(re.fullmatch(r"nginx_[0-9_]+\.tar\.gz", n) for n in names), names
    for path in backups.iterdir():
        assert path.stat().st_mode & 0o777 == 0o600, path.name


def test_cleanup_prunes_only_the_files_this_script_writes(tmp_path):
    install = make_install(tmp_path)
    backups = tmp_path / "var" / "backups" / "bsdmirror"
    backups.mkdir(parents=True)
    month_ago = time.time() - 30 * 86400
    own_old = backups / "db_20200101_000000.sql.gz"
    hand_kept = backups / "pre-alembic-20260901_073911.sql.gz"
    for path in (own_old, hand_kept):
        path.write_bytes(b"x")
        os.utime(path, (month_ago, month_ago))

    result = run_backup(tmp_path, backups, install)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not own_old.exists()
    assert hand_kept.exists()
