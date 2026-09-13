"""shared/protected_paths.py: what is protected, and proof the mechanism works.

Three kinds of test, deliberately kept apart:

  * The `protect_filter_args`/`PROTECTED_PATHS`/`CURRENT_RELEASES` tests are
    pure -- no subprocess, no filesystem, no database -- and pin the seed
    lists this change was actually asked to add (which releases, and why
    the newest on each mirror is excluded).
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
  * The "archive-inventory / real rsync cross-check" section near the end
    shells out to the same real binary to prove
    backend/app/core/archive_inventory.py's hand-written pattern matcher
    agrees with it -- see that section's own docstring for the full
    reasoning. It lives in this module, not its own file, so that CI's
    no-skip guard (the `REQUIRED` tuple in .github/workflows/ci.yml, which
    already names `tests.test_protected_paths`) covers it too: that guard
    fails the build if any of its named modules skips a single test, and a
    real-rsync proof that skips silently (rsync missing) on an otherwise
    green build is exactly the kind of lost coverage that guard exists to
    catch. A separate module with the same skip condition would not be
    covered unless someone remembered to add it there too.

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

from app.core.archive_inventory import (
    build_mirror_inventory,
    compile_pattern,
    is_final_release_name,
    pattern_subject,
)
from shared.models import MirrorType
from shared.protected_paths import CURRENT_RELEASES, PROTECTED_PATHS, protect_filter_args
from sync.sync_service import SyncService
from tests.test_archive_inventory import (
    _build_freebsd_root,
    _build_netbsd_root,
    _build_openbsd_root,
    _touch_dir,
)

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


def test_current_releases_are_never_protected():
    """A name in CURRENT_RELEASES must never also be a protected pattern's
    subject -- see shared/protected_paths.py's "CURRENT_RELEASES, AND WHY IT
    IS DATA TOO" section. The two lists partition "every release this repo
    tracks" between them and must never overlap: a still-served release is
    exactly the one thing that must keep mirroring faithfully, protected or
    not.
    """
    for mirror_type in MirrorType:
        protected_subjects = {
            pattern_subject(compile_pattern(p)) for p in PROTECTED_PATHS[mirror_type]
        }
        current = set(CURRENT_RELEASES.get(mirror_type, ()))
        overlap = protected_subjects & current
        assert not overlap, f"{mirror_type}: current release(s) also protected: {overlap}"


def test_every_mirror_type_has_at_least_one_current_release():
    for mirror_type in MirrorType:
        assert CURRENT_RELEASES.get(mirror_type), mirror_type


# ---------------------------------------------------------------------------
# CURRENT_RELEASES validated against itself (archive_inventory.py's F2 fix):
# a stale entry left behind after an upgrade is only detectable at all if
# CURRENT_RELEASES' own shape stays what _annotate_cross_release_fields
# assumes -- at most one entry per mirror-wide "current" slot (OpenBSD/
# NetBSD) or per major (FreeBSD), and every entry an actual final release
# name for its mirror, not a pre-release or a typo.
# ---------------------------------------------------------------------------


def test_openbsd_and_netbsd_current_releases_have_exactly_one_entry():
    """OpenBSD/NetBSD have one "current" slot mirror-wide (see
    shared/protected_paths.py's module docstring) -- a second entry would
    silently change what "stale" means for the one already there, the
    exact upgrade-procedure mistake archive_inventory.py's `stale_current`
    exists to catch, not something to also allow deliberately.
    """
    assert len(CURRENT_RELEASES[MirrorType.OPENBSD]) == 1
    assert len(CURRENT_RELEASES[MirrorType.NETBSD]) == 1


def test_freebsd_current_releases_has_at_most_one_entry_per_major():
    """FreeBSD supports two branches at once, so up to one CURRENT_RELEASES
    entry per major is expected -- but never two for the SAME major, which
    would be exactly the "appended instead of replaced" mistake."""
    majors = [name.split(".", 1)[0] for name in CURRENT_RELEASES[MirrorType.FREEBSD]]
    assert len(majors) == len(set(majors)), majors


def test_every_current_release_matches_its_mirrors_final_release_shape():
    """Every CURRENT_RELEASES entry must be an actual FINAL release name
    for its own mirror type (is_final_release_name -- the same shape
    scan_*_releases groups under kind == "release") -- never a pre-release
    identifier, and never a name that would only make sense for a
    different mirror type.
    """
    for mirror_type in MirrorType:
        for name in CURRENT_RELEASES.get(mirror_type, ()):
            assert is_final_release_name(mirror_type, name), (mirror_type, name)


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
# --safe-links: refuse a symlink whose target escapes the transfer root
#
# sync_service.py's run_rsync now always includes --safe-links (see its
# comment there for the threat: plain rsync:// with no transport integrity,
# an nginx config that follows symlinks with autoindex on, and `-l` above
# copying a symlink's target verbatim with no validation of its own). rsync's
# own definition of "safe" is purely lexical -- does the target, resolved
# relative to the symlink's own directory, ever leave the transfer root --
# decided without regard to whether the target exists, which matters below:
# a target that resolves to nothing at all is refused exactly like one that
# resolves to something real.
# ---------------------------------------------------------------------------


@requires_rsync
async def test_real_rsync_safe_links_keeps_in_tree_relative_symlinks(tmp_path):
    """The legitimate shapes real mirrors depend on must keep working:
    FreeBSD's `releases/<arch>/<V> -> <subarch>/<V>` directory link, one of
    the ~422 `../`-laden file links inside `releases/*/ISO-IMAGES/X.Y/`, and
    NetBSD's `pub/NetBSD/iso -> images`. All three are relative and resolve
    to a target inside the transfer root, so --safe-links must not change
    anything about them.
    """
    service = _real_rsync_service()
    source = tmp_path / "source"
    dest = tmp_path / "dest"

    _touch(
        source / "releases" / "amd64" / "amd64" / "14.3-RELEASE" / "base.txz",
        "release-content",
        mtime_offset=-10,
    )
    (source / "releases" / "amd64" / "14.3-RELEASE").symlink_to("amd64/14.3-RELEASE")
    (source / "releases" / "ISO-IMAGES" / "14.3").mkdir(parents=True)
    (source / "releases" / "ISO-IMAGES" / "14.3" / "base.txz.link").symlink_to(
        "../../amd64/amd64/14.3-RELEASE/base.txz"
    )
    _touch(source / "images" / "netbsd.iso", "iso-content", mtime_offset=-10)
    (source / "iso").symlink_to("images")

    ok, output, _ = await service.run_rsync(f"{source}/", str(dest), "FreeBSD", MirrorType.FREEBSD)
    assert ok is True, output

    dir_link = dest / "releases" / "amd64" / "14.3-RELEASE"
    file_link = dest / "releases" / "ISO-IMAGES" / "14.3" / "base.txz.link"
    iso_link = dest / "iso"

    assert dir_link.is_symlink() and os.readlink(dir_link) == "amd64/14.3-RELEASE"
    assert (dir_link / "base.txz").read_text() == "release-content"

    assert file_link.is_symlink()
    assert os.readlink(file_link) == "../../amd64/amd64/14.3-RELEASE/base.txz"
    assert file_link.read_text() == "release-content"

    assert iso_link.is_symlink() and os.readlink(iso_link) == "images"
    assert (iso_link / "netbsd.iso").read_text() == "iso-content"


@requires_rsync
async def test_real_rsync_safe_links_refuses_absolute_and_escaping_symlinks(tmp_path):
    """The other half of the same coin, and the actual attack this change
    closes: an absolute target, and relative targets with enough `../` to
    walk out of the transfer root, must not be created at all -- not
    skipped-with-a-placeholder, not created pointing somewhere else, simply
    absent. `pub/OpenBSD/x -> /etc/passwd` served by nginx's autoindex is
    exactly this shape.

    The two `../`-escaping targets are NetBSD's own real ones (2026-09-13
    production scan, depth-4): `packages/distfiles` and
    `arch/hpcmips/cross/cross-netbsd.tgz`, both of which resolve outside
    `pub/NetBSD` -- the only tree this mirror syncs -- which is also why they
    are already dangling locally today, not merely unsafe in theory. rsync
    does not check whether a target exists before deciding it is unsafe, so
    a dangling escape is refused exactly like a live one -- proven here by
    also including a target (`evil-rel-dangling`) that resolves to nothing
    at all, real or not.

    Mutation-checked: removing --safe-links from run_rsync's argv makes this
    fail (the absolute link gets created), which is the whole point of it.
    """
    service = _real_rsync_service()
    source = tmp_path / "source"
    dest = tmp_path / "dest"

    (source / "sub").mkdir(parents=True)
    (source / "evil-abs").symlink_to("/etc/passwd")
    (source / "sub" / "evil-rel-dangling").symlink_to("../../nonexistent-target")
    (source / "packages").mkdir(parents=True)
    (source / "packages" / "distfiles").symlink_to("../../pkgsrc/distfiles")
    (source / "arch" / "hpcmips" / "cross").mkdir(parents=True)
    (source / "arch" / "hpcmips" / "cross" / "cross-netbsd.tgz").symlink_to(
        "../../../../incoming/sakamoto/cross-netbsd.tgz"
    )
    _touch(source / "sub" / "real.txt", "real", mtime_offset=-10)

    ok, output, _ = await service.run_rsync(f"{source}/", str(dest), "NetBSD", MirrorType.NETBSD)
    assert ok is True, output

    assert not os.path.lexists(dest / "evil-abs")
    assert not os.path.lexists(dest / "sub" / "evil-rel-dangling")
    assert not os.path.lexists(dest / "packages" / "distfiles")
    assert not os.path.lexists(dest / "arch" / "hpcmips" / "cross" / "cross-netbsd.tgz")
    assert (dest / "sub" / "real.txt").read_text() == "real"


@requires_rsync
async def test_real_rsync_safe_links_and_delete_on_a_pre_existing_unsafe_symlink(
    tmp_path, monkeypatch
):
    """What happens, on the very next --delete sync, to an unsafe symlink
    that is ALREADY on disk locally (planted before --safe-links existed, or
    by any other means) -- established against the real binary, in both an
    unprotected directory and one covered by a PROTECTED_PATHS pattern:

    Phase A -- upstream still serves the identical unsafe link at that path:
    rsync reports (with -v; run_rsync does not pass it, so this is silent in
    production) "ignoring unsafe symlink" and leaves the path completely
    alone -- not deleted, not overwritten, in EITHER directory. --safe-links
    only refuses to CREATE an unsafe link; it does not make --delete remove
    one that is already there while upstream keeps offering something at
    that path. So turning this flag on is not, by itself, a remediation for
    a link that already exists -- only for one that has not been planted yet.

    Phase B -- upstream stops serving that path at all: ordinary --delete
    rules resume. The unprotected copy is deleted like any other file
    upstream no longer has. The one inside the protected tree survives --
    the same protect-filter mechanism that saves an ordinary file, applied
    to a symlink instead.
    """
    monkeypatch.setitem(PROTECTED_PATHS, MirrorType.OPENBSD, ("/protected/***",))
    service = _real_rsync_service()
    source = tmp_path / "source"
    dest = tmp_path / "dest"

    for tree in ("unprotected", "protected"):
        (source / tree).mkdir(parents=True)
        (source / tree / "evil").symlink_to("/etc/passwd")
        (dest / tree).mkdir(parents=True)
        (dest / tree / "evil").symlink_to("/etc/passwd")

    # Phase A: upstream still serves the same unsafe link at both paths.
    ok, output, _ = await service.run_rsync(f"{source}/", str(dest), "OpenBSD", MirrorType.OPENBSD)
    assert ok is True, output
    assert os.path.lexists(
        dest / "unprotected" / "evil"
    ), "not a deletion candidate while upstream still serves it, protected or not"
    assert os.path.lexists(dest / "protected" / "evil")
    # Untouched, not merely present: still points exactly where it did before.
    assert os.readlink(dest / "unprotected" / "evil") == "/etc/passwd"
    assert os.readlink(dest / "protected" / "evil") == "/etc/passwd"

    # Phase B: upstream withdraws it entirely.
    (source / "unprotected" / "evil").unlink()
    (source / "protected" / "evil").unlink()
    ok, output, _ = await service.run_rsync(f"{source}/", str(dest), "OpenBSD", MirrorType.OPENBSD)
    assert ok is True, output
    assert not os.path.lexists(
        dest / "unprotected" / "evil"
    ), "ordinary --delete resumes once upstream drops the path entirely"
    assert os.path.lexists(
        dest / "protected" / "evil"
    ), "the protect filter still saves it, exactly as it would a regular file"


@requires_rsync
async def test_netbsds_known_escaping_symlinks_survive_the_next_sync(tmp_path):
    """The concrete, currently-live case (2026-09-13 production scan, depth-4
    below pub/NetBSD): two real symlinks already resolve outside the only
    tree this mirror syncs -- `packages/distfiles ->
    ../../pkgsrc/distfiles` and `arch/hpcmips/cross/cross-netbsd.tgz ->
    ../../../../incoming/sakamoto/cross-netbsd.tgz` -- and are therefore
    already dangling locally (this host has no `pkgsrc/` or `incoming/`
    sibling of `pub/NetBSD` for either target to resolve to).

    Per test_real_rsync_safe_links_and_delete_on_a_pre_existing_unsafe_symlink's
    Phase A: as long as upstream keeps serving these two exact paths, this
    fix's next nightly sync leaves both exactly as they are today. --delete
    does NOT remove them -- --safe-links stops a new escaping link from
    being planted, but these two predate it and are not retroactively
    cleaned up. Neither is covered by a PROTECTED_PATHS pattern (those only
    cover release directories), so removing them, if desired, is a separate,
    manual step, not something this change does for free.
    """
    service = _real_rsync_service()
    source = tmp_path / "source"
    dest = tmp_path / "dest"

    (source / "packages").mkdir(parents=True)
    (source / "packages" / "distfiles").symlink_to("../../pkgsrc/distfiles")
    (source / "arch" / "hpcmips" / "cross").mkdir(parents=True)
    (source / "arch" / "hpcmips" / "cross" / "cross-netbsd.tgz").symlink_to(
        "../../../../incoming/sakamoto/cross-netbsd.tgz"
    )
    # dest starts as an exact copy -- these were already synced before
    # --safe-links existed, not created by the run below.
    shutil.copytree(source, dest, symlinks=True)

    ok, output, _ = await service.run_rsync(f"{source}/", str(dest), "NetBSD", MirrorType.NETBSD)
    assert ok is True, output

    assert os.path.lexists(dest / "packages" / "distfiles")
    assert os.path.lexists(dest / "arch" / "hpcmips" / "cross" / "cross-netbsd.tgz")
    assert os.readlink(dest / "packages" / "distfiles") == "../../pkgsrc/distfiles"
    assert (
        os.readlink(dest / "arch" / "hpcmips" / "cross" / "cross-netbsd.tgz")
        == "../../../../incoming/sakamoto/cross-netbsd.tgz"
    )


# ---------------------------------------------------------------------------
# Archive-inventory / real-rsync cross-check: does the archive-inventory
# parser's "covered" verdict agree with what the REAL rsync binary actually
# protects?
#
# backend/app/core/archive_inventory.py's compile_pattern()/pattern_matches()
# is a hand-written re-implementation of what rsync's own `-f "P ..."` filter
# matching does. Every other test in tests/test_archive_inventory.py checks
# that re-implementation against itself; none of them prove it agrees with
# the real binary sync_service.py actually shells out to (the tests above in
# THIS module do that for protect_filter_args's own argv, but not for the
# parser that reads PROTECTED_PATHS back out for display). The two are made
# to agree BY CONSTRUCTION here, from one shared rsync run, rather than by
# two separate assertions that could silently drift apart -- the exact shape
# of bug shared/models/ already exists to prevent for the ORM tables (see
# that package's own module docstring).
#
# This is the dangerous direction to get wrong, not the safe one: the admin
# page tells an operator a release is `full`, the operator uses that to
# decide it needs no attention, and the day upstream prunes, rsync deletes
# it anyway because the real argv it received does not actually cover it.
# This section is built so that mistake fails a test instead of a mirror.
#
# This lives in this module rather than its own file so that CI's no-skip
# guard (see the module docstring at the top of this file) covers it --
# skips, loudly, if rsync is missing, the same as every other real-rsync
# test above.
#
# Method, per mirror type: build a tmp_path tree shaped like production (the
# same fixtures tests/test_archive_inventory.py itself uses -- the exact
# 14.3 enumeration, arch-level symlinks, nested and top-level ISO-IMAGES/X.Y,
# VM/CI/OCI-IMAGES), copy it into a destination, then rsync an EMPTY source
# into that destination the way sync_service.run_rsync does for a real sync:
# `-rlptHz --delete --delete-delay --delay-updates ...` plus
# `protect_filter_args(mirror_type)`, source with a trailing slash (see this
# module's own real-rsync tests above, which already prove this exact
# invocation shape against the real binary, and whose `_real_rsync_service()`
# and `requires_rsync` this section reuses rather than redefining a second
# time). An empty source is upstream pruning literally everything at once --
# the sharpest version of exactly the scenario shared/protected_paths.py
# exists for -- so whatever is still in the destination afterwards is
# exactly, and only, what the real `-f "P ..."` filters protected.
# ---------------------------------------------------------------------------


async def _prune_with_real_rsync(
    tmp_path: Path, name: str, mirror_type: MirrorType, tree: Path
) -> Path:
    """Copy `tree` into a working destination, then rsync an EMPTY source
    into it exactly the way sync_service.run_rsync does for `mirror_type`
    (`-rlptHz --delete --delete-delay --delay-updates ...` plus
    `protect_filter_args(mirror_type)`, source with a trailing slash). Returns
    the destination; whatever is still there afterwards is exactly what the
    real `-f "P ..."` filters protected against upstream pruning everything
    at once.
    """
    dest = tmp_path / f"{name}-dest"
    shutil.copytree(tree, dest, symlinks=True)
    source = tmp_path / f"{name}-empty-source"
    source.mkdir()

    service = _real_rsync_service()
    ok, output, _ = await service.run_rsync(f"{source}/", str(dest), name, mirror_type)
    assert ok, output
    return dest


def _assert_parser_agrees_with_rsync(inventory: dict, dest: Path) -> None:
    """For every location every release reports: the parser's covered/not
    verdict must equal whether that exact path still exists under `dest`
    after the prune -- `lexists`, not `exists`, so a symlink that survived
    but now points at nothing still counts as "survived" (a bare `**/NAME`
    protects the symlink itself, independent of its target -- see
    shared/protected_paths.py's module docstring on why that distinction is
    the whole point of that pattern shape).
    """
    for release in inventory["releases"]:
        survived = {loc: os.path.lexists(dest / loc) for loc in release["locations"]}

        for loc, did_survive in survived.items():
            parser_says_covered = loc not in release["unprotected_locations"]
            assert parser_says_covered == did_survive, (
                f"{release['version']} {loc!r}: parser says covered="
                f"{parser_says_covered}, but real rsync "
                f"{'kept' if did_survive else 'deleted'} it"
            )

        if release["protection"] == "full":
            assert all(
                survived.values()
            ), f"{release['version']}: protection=full but rsync deleted some of {survived}"
        if release["protection"] == "none":
            assert not any(
                survived.values()
            ), f"{release['version']}: protection=none but rsync kept some of {survived}"


@requires_rsync
async def test_openbsd_full_and_none_verdicts_match_real_rsync(tmp_path):
    """Includes 7.4 -- an older release nobody protected, the drift case the
    operator specifically does not want to lose -- alongside the real
    7.5-7.8 (full) / 7.9 (none, newest) seed list."""
    root = _build_openbsd_root(tmp_path, extra_releases=("7.4",))
    inventory = build_mirror_inventory(
        MirrorType.OPENBSD, str(root), PROTECTED_PATHS[MirrorType.OPENBSD]
    )

    dest = await _prune_with_real_rsync(tmp_path, "OpenBSD", MirrorType.OPENBSD, root)

    _assert_parser_agrees_with_rsync(inventory, dest)
    by_version = {r["version"]: r for r in inventory["releases"]}
    assert not os.path.lexists(dest / "7.4"), "7.4 is unprotected; rsync must have deleted it"
    assert by_version["7.4"]["at_risk"] is True


@requires_rsync
async def test_netbsd_full_and_none_verdicts_match_real_rsync(tmp_path):
    root = _build_netbsd_root(tmp_path)
    inventory = build_mirror_inventory(
        MirrorType.NETBSD, str(root), PROTECTED_PATHS[MirrorType.NETBSD]
    )

    dest = await _prune_with_real_rsync(tmp_path, "NetBSD", MirrorType.NETBSD, root)

    _assert_parser_agrees_with_rsync(inventory, dest)


@requires_rsync
async def test_freebsd_full_and_none_verdicts_match_real_rsync(tmp_path):
    """The full production shape: 14.3's exact enumeration (arch-nested real
    directories, arch-level symlinks, top-level and per-arch
    ISO-IMAGES/14.3, VM/CI/OCI-IMAGES), plus 14.4/15.0 (full) and 14.5/15.1
    (none -- one of them the newest)."""
    root = _build_freebsd_root(tmp_path)
    inventory = build_mirror_inventory(
        MirrorType.FREEBSD, str(root), PROTECTED_PATHS[MirrorType.FREEBSD]
    )

    dest = await _prune_with_real_rsync(tmp_path, "FreeBSD", MirrorType.FREEBSD, root)

    _assert_parser_agrees_with_rsync(inventory, dest)
    # The arch-level convenience symlink specifically -- the one location a
    # `/***`-only pattern would NOT protect (see shared/protected_paths.py) --
    # must have survived, not merely "some location of 14.3 survived".
    assert os.path.lexists(dest / "releases" / "amd64" / "14.3-RELEASE")


@requires_rsync
async def test_freebsd_partial_coverage_matches_real_rsync(tmp_path, monkeypatch):
    """One version (14.4) with only its ISO-IMAGES pattern struck from the
    REAL seed list -- a partial-coverage tree built from an actual
    production pattern set with one line removed, not a synthetic one -- to
    prove the per-location cross-check catches a MIXED verdict, not just the
    all-or-nothing full/none cases above.
    """
    root = _build_freebsd_root(tmp_path)
    patched = tuple(p for p in PROTECTED_PATHS[MirrorType.FREEBSD] if p != "**/ISO-IMAGES/14.4/***")
    # protect_filter_args (sync_service.run_rsync's own source of patterns)
    # reads shared.protected_paths.PROTECTED_PATHS by name at call time, so
    # mutating the dict object here reaches the real rsync invocation below
    # too -- the same pattern set on both sides of the comparison.
    monkeypatch.setitem(PROTECTED_PATHS, MirrorType.FREEBSD, patched)

    inventory = build_mirror_inventory(MirrorType.FREEBSD, str(root), patched)
    by_version = {r["version"]: r for r in inventory["releases"]}
    assert by_version["14.4-RELEASE"]["protection"] == "partial", by_version["14.4-RELEASE"]

    dest = await _prune_with_real_rsync(tmp_path, "FreeBSD", MirrorType.FREEBSD, root)

    _assert_parser_agrees_with_rsync(inventory, dest)
    assert os.path.lexists(dest / "releases" / "amd64" / "amd64" / "14.4-RELEASE")
    assert not os.path.lexists(dest / "releases" / "ISO-IMAGES" / "14.4")


@requires_rsync
async def test_freebsd_bare_pattern_alone_agrees_with_real_rsync(tmp_path, monkeypatch):
    """Isolates the bare `**/NAME` shape from its usual `/***` sibling, and
    documents the one deliberate divergence in this section between "the
    parser says covered" and "the entry survived an empty-source prune" --
    see the long comment below.

    Every entry PROTECTED_PATHS actually ships pairs `**/NAME` with
    `**/NAME/***` for the same name (see shared/protected_paths.py's module
    docstring on why both are listed). That pairing would hide a regression
    in either shape in every OTHER test in this section, since the `/***`
    pattern's path-only reach would redundantly line up with the bare
    pattern's for the very same symlink. Patching FreeBSD's real seed list
    down to bare-only for one version removes that redundancy.
    """
    root = _build_freebsd_root(tmp_path)
    monkeypatch.setitem(PROTECTED_PATHS, MirrorType.FREEBSD, ("**/14.4-RELEASE",))

    inventory = build_mirror_inventory(
        MirrorType.FREEBSD, str(root), PROTECTED_PATHS[MirrorType.FREEBSD]
    )
    by_version = {r["version"]: r for r in inventory["releases"]}
    r = by_version["14.4-RELEASE"]
    # F2: bare covers only the symlink, never the real directory (see
    # pattern_matches's docstring) -- targeted (the ISO location is a
    # different trailing segment, so it is not even that), but not fully
    # covered. "partial", not "full".
    assert r["protection"] == "partial", r
    symlink_loc = "releases/amd64/14.4-RELEASE"
    real_dir_loc = "releases/amd64/amd64/14.4-RELEASE"
    iso_loc = "releases/ISO-IMAGES/14.4"
    assert symlink_loc not in r["unprotected_locations"]
    assert real_dir_loc in r["unprotected_locations"]
    assert iso_loc in r["unprotected_locations"]

    dest = await _prune_with_real_rsync(tmp_path, "FreeBSD", MirrorType.FREEBSD, root)

    # The symlink: parser says covered, and it survives. Agree, as everywhere
    # else in this section.
    assert os.path.lexists(dest / symlink_loc), "bare **/NAME must protect the symlink"
    # The ISO directory: parser says not covered, and it is deleted. Agree.
    assert not os.path.lexists(dest / iso_loc), "a differently-named directory must not survive"

    # The real directory is the one deliberate divergence: the parser says
    # NOT covered (correctly -- see F2), but it still exists here, because an
    # EMPTY source never even looks inside a locally-matched entry to find
    # reasons to prune it, so the ENTRY survives this specific prune shape
    # regardless. That is exactly why this parser does not call bare-only
    # coverage of a directory "safe":
    # test_freebsd_bare_only_directory_loses_contents_from_a_nonempty_source
    # (below, same section) is the same pattern against a NON-empty source,
    # which this empty-source method cannot exercise, and shows a file
    # inside this very directory does NOT survive. "The shell survives an
    # all-at-once wipe" and "the contents survive ordinary upstream
    # housekeeping" are different claims; this module deliberately reports
    # the second, more useful one.
    assert os.path.lexists(dest / real_dir_loc), (
        "expected the directory ENTRY to survive an empty-source prune even though "
        "the parser correctly does not call it covered -- if this now fails, rsync's "
        "empty-source behaviour for a bare-matched directory has changed and the "
        "module docstring's reasoning needs re-checking, not just this assertion"
    )


@requires_rsync
async def test_freebsd_bare_only_directory_loses_contents_from_a_nonempty_source(
    tmp_path, monkeypatch
):
    """The other half of F2, and the reason bare-only coverage of a
    directory is not "full": a bare pattern keeps the ENTRY named
    14.4-RELEASE from being deleted outright (see the test above), but does
    nothing to protect a file removed from INSIDE it while the directory
    itself keeps being served -- the ordinary, non-empty-source case an
    all-at-once prune cannot exercise.
    """
    rel_dir = "releases/amd64/amd64/14.4-RELEASE"
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    (source / rel_dir).mkdir(parents=True)
    (source / rel_dir / "kept.txt").write_text("kept")
    # dest starts as a copy of source PLUS one extra file upstream is about
    # to remove -- the file this test proves is not actually protected.
    shutil.copytree(source, dest)
    (dest / rel_dir / "removed.txt").write_text("gone next sync")

    monkeypatch.setitem(PROTECTED_PATHS, MirrorType.FREEBSD, ("**/14.4-RELEASE",))
    inventory = build_mirror_inventory(
        MirrorType.FREEBSD, str(dest), PROTECTED_PATHS[MirrorType.FREEBSD]
    )
    assert (
        _by_version_helper(inventory)["14.4-RELEASE"]["protection"] == "partial"
    ), "a bare-only-covered directory must not be classified as fully protected"

    service = _real_rsync_service()
    ok, output, _ = await service.run_rsync(f"{source}/", str(dest), "FreeBSD", MirrorType.FREEBSD)
    assert ok, output

    assert (dest / rel_dir / "kept.txt").exists()
    assert (dest / rel_dir).exists(), "the bare-protected directory entry itself must survive"
    assert not (
        dest / rel_dir / "removed.txt"
    ).exists(), "a bare pattern must not protect a directory's CONTENTS from deletion"


@requires_rsync
async def test_openbsd_anchored_pattern_does_not_protect_a_symlinked_release(tmp_path):
    """F2: `/7.5/***` (anchored, carries rsync's directory-only `/***`) must
    NOT protect a same-named SYMLINK -- confirmed against the real binary,
    not assumed."""
    root = tmp_path / "openbsd"
    real = root / "real75"
    _touch_dir(real)
    (real / "kept.txt").write_text("x")
    (root / "7.5").symlink_to("real75")

    inventory = build_mirror_inventory(MirrorType.OPENBSD, str(root), ("/7.5/***",))
    r = _by_version_helper(inventory)["7.5"]
    assert r["protection"] != "full", r

    dest = await _prune_with_real_rsync(tmp_path, "OpenBSD-symlink", MirrorType.OPENBSD, root)
    _assert_parser_agrees_with_rsync(inventory, dest)
    assert not os.path.lexists(
        dest / "7.5"
    ), "the anchored pattern must not save a symlinked release"


@requires_rsync
async def test_freebsd_suffix_pattern_does_not_protect_a_symlinked_iso_directory(tmp_path):
    """F2: `**/ISO-IMAGES/14.3/***` must not protect ISO-IMAGES/14.3 if it
    is a symlink rather than a real directory -- there is no bare ISO
    pattern in the real seed list (see shared/protected_paths.py) to cover
    that shape, so it must be, and is, deleted."""
    root = tmp_path / "freebsd"
    releases = root / "releases"
    real_iso_target = releases / "real-iso-14.3"
    _touch_dir(real_iso_target)
    (real_iso_target / "disc1.iso").write_text("x")
    _touch_dir(releases / "ISO-IMAGES")
    (releases / "ISO-IMAGES" / "14.3").symlink_to("../real-iso-14.3")

    inventory = build_mirror_inventory(
        MirrorType.FREEBSD, str(root), PROTECTED_PATHS[MirrorType.FREEBSD]
    )
    r = _by_version_helper(inventory)["14.3-RELEASE"]
    assert r["protection"] != "full", r

    dest = await _prune_with_real_rsync(tmp_path, "FreeBSD-symlinked-iso", MirrorType.FREEBSD, root)
    _assert_parser_agrees_with_rsync(inventory, dest)
    assert not os.path.lexists(dest / "releases" / "ISO-IMAGES" / "14.3")


def _by_version_helper(inventory: dict) -> dict:
    return {r["version"]: r for r in inventory["releases"]}


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
