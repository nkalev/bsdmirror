"""shared/protected_paths.py: what is protected, and proof the mechanism works.

Two kinds of test, deliberately kept apart:

  * The `protect_filter_args`/`PROTECTED_PATHS` tests are pure -- no
    subprocess, no filesystem, no database -- and pin the seed lists this
    change was actually asked to add (which releases, and why the newest on
    each mirror is excluded).
  * The `test_real_rsync_*` tests below shell out to the *real* rsync binary
    against a throwaway tree under tmp_path, the way sync_service.py's own
    run_rsync does in production. Nothing here monkeypatches
    asyncio.create_subprocess_exec (contrast with the `rsync` fixture in
    conftest.py, used by tests/test_sync_job.py): the point is proof the
    argv this module builds does what it claims against the real binary, not
    another assertion about the argv itself.

    rsync's default quick-check is size + mtime. The first attempt at this
    file used two 3-byte files written in the same wall-clock second and
    concluded the protect filter was blocking updates, when rsync was really
    just skipping a file it believed was unchanged. Every "upstream changed
    this file" step below changes size *and* forces a distinct mtime for
    that reason -- see _touch().

Skips, loudly, if rsync is missing -- the same shape as test_public_page_csp's
NODE/CHROME handling. docker-compose.yml's `test` service installs it
(Dockerfile.test) for exactly this file, so it always runs there; a bare host
checkout without the binary reports fewer tests, same as a checkout without
node or Chrome does today.
"""
import os
import shutil
import time
from pathlib import Path

import pytest

from shared.models import MirrorType
from shared.protected_paths import PROTECTED_PATHS, protect_filter_args
from sync.sync_service import SyncService

RSYNC = shutil.which("rsync")
requires_rsync = pytest.mark.skipif(RSYNC is None, reason="needs the rsync binary")

# ---------------------------------------------------------------------------
# protect_filter_args / PROTECTED_PATHS: pure, no I/O
# ---------------------------------------------------------------------------


def test_no_mirror_type_protects_nothing():
    """The default. A mirror nobody has configured a list for keeps
    mirroring exactly as faithfully as it did before this file existed."""
    assert protect_filter_args(None) == []


def test_every_mirror_type_has_a_list_even_if_empty():
    # MirrorType.get(..., ()) is the real fallback run_rsync depends on; this
    # pins that every member resolves to *a tuple*, not a KeyError, even if a
    # future mirror type is added here without an entry.
    for mirror_type in MirrorType:
        assert isinstance(PROTECTED_PATHS.get(mirror_type, ()), tuple)


def test_protect_filter_args_emits_one_dash_f_pair_per_pattern():
    patterns = PROTECTED_PATHS[MirrorType.OPENBSD]
    args = protect_filter_args(MirrorType.OPENBSD)

    assert len(args) == 2 * len(patterns)
    assert args[0::2] == ["-f"] * len(patterns)
    assert args[1::2] == [f"P {pattern}" for pattern in patterns]


def test_openbsd_seed_covers_the_eol_trees_and_excludes_the_current_release():
    """7.5-7.7 are already EOL; 7.8/7.9 are OpenBSD's supported "current +
    previous" pair. 7.9 -- the current release -- is deliberately absent; see
    the "WHY THE NEWEST" section of the module docstring."""
    patterns = PROTECTED_PATHS[MirrorType.OPENBSD]
    for version in ("7.5", "7.6", "7.7", "7.8"):
        assert f"/{version}/***" in patterns
    assert "/7.9/***" not in patterns


def test_netbsd_seed_protects_the_superseded_rc_but_not_the_final_release():
    """NetBSD-11.0 (final) is the newest and is excluded. NetBSD-11.0_RC7 is
    not "current" by the same reasoning -- it was superseded the moment 11.0
    shipped -- so it is protected like every other already-superseded entry.
    """
    patterns = PROTECTED_PATHS[MirrorType.NETBSD]
    for version in (
        "NetBSD-7.2",
        "NetBSD-8.3",
        "NetBSD-9.0",
        "NetBSD-9.5",
        "NetBSD-10.0",
        "NetBSD-10.1",
        "NetBSD-11.0_RC7",
    ):
        assert f"/{version}/***" in patterns
    assert "/NetBSD-11.0/***" not in patterns


def test_freebsd_seed_pairs_a_bare_and_a_star_pattern_per_release():
    """Every "-RELEASE" identifier needs both forms: bare protects a
    convenience symlink sharing that name (releases/<arch>/<V> ->
    <subarch>/<V>); /*** protects the real directory tree, at whatever depth
    it is found. See test_real_rsync_freebsd_survives_an_eol_prune_across_
    every_shape_at_once for proof a bare /*** alone does not cover a symlink.
    """
    patterns = set(PROTECTED_PATHS[MirrorType.FREEBSD])
    for version in ("14.3-RELEASE", "14.4-RELEASE", "15.0-RELEASE"):
        assert f"**/{version}" in patterns
        assert f"**/{version}/***" in patterns
        assert f"**/ISO-IMAGES/{version.split('-')[0]}/***" in patterns
    # The two branches' current heads are excluded -- see the module
    # docstring on why FreeBSD has two "newest" releases, not one.
    for excluded in ("14.5-RELEASE", "15.1-RELEASE"):
        assert f"**/{excluded}" not in patterns
        assert f"**/{excluded}/***" not in patterns


# ---------------------------------------------------------------------------
# Real rsync, real files
# ---------------------------------------------------------------------------


def _touch(path: Path, content: str, mtime_offset: float) -> None:
    """Write `content` and force an unambiguous mtime -- see the module
    docstring on why both size and mtime need to move for a test like this to
    mean anything."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    when = time.time() + mtime_offset
    os.utime(path, (when, when))


def _real_rsync_service() -> SyncService:
    """A SyncService whose run_rsync shells out for real. Bypasses __init__
    the same way conftest.py's `service` fixture does (no live Postgres in
    this suite), keeping only what run_rsync itself reads."""
    svc = object.__new__(SyncService)
    svc.current_sync = None
    svc.sync_timeout = 60
    svc.sync_bandwidth_limit = 0
    return svc


@requires_rsync
async def test_real_rsync_protected_path_survives_deletion_and_keeps_updating(tmp_path):
    """The OpenBSD seed list end to end, against the real binary: 7.6
    (protected) keeps receiving updates and new files and survives upstream
    deleting a file from it; 7.9 (current, unprotected) loses a deleted file
    exactly as --delete is supposed to."""
    service = _real_rsync_service()
    source = tmp_path / "source"
    dest = tmp_path / "dest"

    _touch(source / "7.6" / "kept.txt", "version-one", mtime_offset=-10)
    _touch(source / "7.6" / "removed-by-upstream.txt", "still carried for now", mtime_offset=-10)
    _touch(source / "7.9" / "removed-by-upstream.txt", "still carried for now", mtime_offset=-10)

    ok, output, _ = await service.run_rsync(f"{source}/", str(dest), "OpenBSD", MirrorType.OPENBSD)
    assert ok is True, output
    assert (dest / "7.6" / "removed-by-upstream.txt").exists()
    assert (dest / "7.9" / "removed-by-upstream.txt").exists()

    # Upstream: 7.6 gets a real content change (different size *and* mtime)
    # and a new file; both 7.6's and 7.9's "removed-by-upstream.txt" are
    # pruned -- an EOL sweep that should only bite the unprotected one.
    _touch(source / "7.6" / "kept.txt", "version-two-is-longer", mtime_offset=10)
    _touch(source / "7.6" / "new-arrival.txt", "brand new", mtime_offset=10)
    (source / "7.6" / "removed-by-upstream.txt").unlink()
    (source / "7.9" / "removed-by-upstream.txt").unlink()

    ok, output, _ = await service.run_rsync(f"{source}/", str(dest), "OpenBSD", MirrorType.OPENBSD)
    assert ok is True, output

    assert (dest / "7.6" / "kept.txt").read_text() == "version-two-is-longer"
    assert (dest / "7.6" / "new-arrival.txt").exists()
    assert (dest / "7.6" / "removed-by-upstream.txt").exists(), "protected: must survive"
    assert not (dest / "7.9" / "removed-by-upstream.txt").exists(), "unprotected: must delete"


@requires_rsync
async def test_real_rsync_unprotected_mirror_still_deletes_everywhere(tmp_path):
    """No mirror_type at all (the pre-existing behaviour for any mirror this
    feature has not been configured for) must not change --delete anywhere."""
    service = _real_rsync_service()
    source = tmp_path / "source"
    dest = tmp_path / "dest"

    _touch(source / "anything" / "file.txt", "one", mtime_offset=-10)
    await service.run_rsync(f"{source}/", str(dest), "Untracked")

    (source / "anything" / "file.txt").unlink()
    ok, output, _ = await service.run_rsync(f"{source}/", str(dest), "Untracked")

    assert ok is True, output
    assert not (dest / "anything" / "file.txt").exists()


@requires_rsync
async def test_real_rsync_freebsd_survives_an_eol_prune_across_every_shape_at_once(tmp_path):
    """FreeBSD's real layout, in miniature, using the actual shipped filter
    list (not a stand-in pattern): the same release nested at two different
    depths (amd64/amd64/... vs arm64/aarch64/...), duplicated again as a
    top-level convenience symlink, and duplicated a third time under
    ISO-IMAGES's short-version naming. All three must survive upstream
    pruning 14.3-RELEASE everywhere it exists, while 15.1-RELEASE -- the
    current head of the other branch, not in the seed list -- keeps losing
    files normally.
    """
    service = _real_rsync_service()
    source = tmp_path / "source"
    dest = tmp_path / "dest"

    _touch(
        source / "releases" / "amd64" / "amd64" / "14.3-RELEASE" / "base.txz",
        "amd64-content",
        mtime_offset=-10,
    )
    _touch(
        source / "releases" / "arm64" / "aarch64" / "14.3-RELEASE" / "base.txz",
        "arm64-content",
        mtime_offset=-10,
    )
    _touch(
        source / "releases" / "ISO-IMAGES" / "14.3" / "disc1.iso",
        "iso-content",
        mtime_offset=-10,
    )
    _touch(
        source / "releases" / "amd64" / "amd64" / "15.1-RELEASE" / "base.txz",
        "current-branch-head",
        mtime_offset=-10,
    )
    (source / "releases" / "amd64" / "14.3-RELEASE").symlink_to("amd64/14.3-RELEASE")

    ok, output, _ = await service.run_rsync(f"{source}/", str(dest), "FreeBSD", MirrorType.FREEBSD)
    assert ok is True, output
    assert (dest / "releases" / "amd64" / "14.3-RELEASE").is_symlink()

    # Upstream prunes 14.3-RELEASE everywhere -- the real dirs at both
    # depths, the ISO tree, and the top-level symlink -- and, separately,
    # removes one file from 15.1-RELEASE as ordinary maintenance.
    shutil.rmtree(source / "releases" / "amd64" / "amd64" / "14.3-RELEASE")
    shutil.rmtree(source / "releases" / "arm64" / "aarch64" / "14.3-RELEASE")
    shutil.rmtree(source / "releases" / "ISO-IMAGES" / "14.3")
    (source / "releases" / "amd64" / "14.3-RELEASE").unlink()
    (source / "releases" / "amd64" / "amd64" / "15.1-RELEASE" / "base.txz").unlink()

    ok, output, _ = await service.run_rsync(f"{source}/", str(dest), "FreeBSD", MirrorType.FREEBSD)
    assert ok is True, output

    assert (dest / "releases" / "amd64" / "amd64" / "14.3-RELEASE" / "base.txz").exists()
    assert (dest / "releases" / "arm64" / "aarch64" / "14.3-RELEASE" / "base.txz").exists()
    assert (dest / "releases" / "ISO-IMAGES" / "14.3" / "disc1.iso").exists()
    assert (
        dest / "releases" / "amd64" / "14.3-RELEASE"
    ).is_symlink(), "the bare (non-/***) pattern must protect the convenience symlink too"
    assert not (
        dest / "releases" / "amd64" / "amd64" / "15.1-RELEASE" / "base.txz"
    ).exists(), "15.1-RELEASE is the current branch head and must stay faithful"


# ---------------------------------------------------------------------------
# Wiring: the Mirror row's mirror_type has to actually reach run_rsync
# ---------------------------------------------------------------------------


async def test_poll_pending_jobs_passes_the_mirrors_type_through(service, rsync, mirror):
    """mirror_type has to survive poll_pending_jobs -> sync_mirror_job ->
    _sync_mirror_job -> run_rsync, not just work when passed by hand -- this
    is the manual-trigger path (admin panel "sync now")."""
    calls = rsync(0, "")

    processed = await service.poll_pending_jobs()

    assert processed == 1
    assert "P /7.6/***" in calls[0]


async def test_run_scheduled_sync_also_passes_the_mirrors_type_through(service, rsync, mirror):
    """The other call site into sync_mirror_job -- the cron path."""
    calls = rsync(0, "")

    await service.run_scheduled_sync()

    assert len(calls) == 1
    assert "P /7.6/***" in calls[0]
