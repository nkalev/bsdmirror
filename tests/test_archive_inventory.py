"""
Archive inventory: backend/app/core/archive_inventory.py and
GET /api/admin/archive-inventory.

Kinds of test, deliberately kept apart:

  1. Detection & classification, against tmp_path trees shaped like the
     production facts recorded in this feature's own task description
     (OpenBSD pub/OpenBSD/, NetBSD pub/NetBSD/, FreeBSD releases/ on
     2026-09-13).
  2. Risk & drift: an unprotected older release, a new major that makes
     latest_in_major alone unsafe (F1), partial coverage, and
     protected_not_on_disk / current_not_on_disk, each in isolation.
  3. Entry-type-aware coverage (F2): a symlink is covered only by a bare
     pattern, a real directory only by a `/***` pattern.
  4. The protect-filter pattern parser, against the real
     shared.protected_paths.PROTECTED_PATHS, against shapes it does not
     recognise, and against literal-looking rsync wildcards (F6).
  5. Filesystem hazards a bounded, untrusted walk has to survive: symlinks
     escaping the root, a symlink loop (including a self-looping release
     name), the entry cap (all three mirror types), a missing root, and a
     symlinked `releases` itself (F4).
  6. Non-UTF-8 names (F3): display-safe, never a 500.
  7. Unclassified names (F6) and per-entry errors (F4).
  8. The in-process cache (F5).

Two rules are pinned tightly enough that a regression in either fails an
existing test without any separate mutation harness:

  * at_risk now keys off `current` (shared.protected_paths.CURRENT_RELEASES),
    not `latest_in_major` -- test_a_new_major_release_is_at_risk_until_
    current_releases_is_updated builds the exact shape that used to hide a
    real EOL release forever (F1's own example).
  * entry type is part of coverage -- test_a_symlinked_anchored_release_is_
    not_covered and test_a_bare_only_covered_directory_is_not_full pin both
    directions of F2 without needing rsync (the real-rsync cross-check in
    tests/test_protected_paths.py proves the same two directions against
    the real binary).

Both properties, plus F3's backslashreplace step, were also verified by hand
during development: temporarily reverting each fix in
backend/app/core/archive_inventory.py and re-running this module under
`docker compose run --rm test` turned the corresponding test(s) red before
each fix was restored.
"""
import json
import os
import shutil
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import pytest
from sqlalchemy import select

from app.core import archive_inventory
from app.core.archive_inventory import (
    CompiledPattern,
    Location,
    UnknownPatternError,
    build_mirror_inventory,
    compile_pattern,
    compile_patterns,
    is_covered,
    is_targeted,
    pattern_matches,
    pattern_subject,
    read_archive_inventory,
    scan_freebsd_releases,
    scan_netbsd_releases,
    scan_openbsd_releases,
)
from shared.models import Mirror, MirrorStatus, MirrorType
from shared.protected_paths import PROTECTED_PATHS
from tests.conftest import auth_header

ALL_TYPES = {"freebsd", "netbsd", "openbsd"}


@pytest.fixture(autouse=True)
def _fresh_archive_inventory_cache():
    """get_archive_inventory_view caches process-wide for 60s (F5); without
    resetting it, whichever test happens to run first within that window
    would leak its result into every test after it."""
    archive_inventory.reset_cache()
    yield
    archive_inventory.reset_cache()


def _touch_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Production-shaped fixtures
# ---------------------------------------------------------------------------


def _build_openbsd_root(tmp_path: Path, extra_releases: Tuple[str, ...] = ()) -> Path:
    root = tmp_path / "openbsd" / "pub" / "OpenBSD"
    for name in (
        "7.5",
        "7.6",
        "7.7",
        "7.8",
        "7.9",
        *extra_releases,
        "Changelogs",
        "ftplist",
        "_hs",
        "LibreSSL",
        "OpenBGPD",
        "OpenIKED",
        "OpenNTPD",
        "OpenSSH",
        "patches",
        "rpki-client",
        "signify",
        "snapshots",
        "songs",
        "stable",
        "syspatch",
        "timestamp",
    ):
        _touch_dir(root / name)
    return root


def _build_netbsd_root(tmp_path: Path) -> Path:
    root = tmp_path / "netbsd" / "pub" / "NetBSD"
    for name in (
        "arch",
        "images",
        "iso",
        "NetBSD-10.0",
        "NetBSD-10.1",
        "NetBSD-11.0",
        "NetBSD-11.0_RC7",
        "NetBSD-7.2",
        "NetBSD-8.3",
        "NetBSD-9.0",
        "NetBSD-9.5",
        "packages",
        "README",
        "README.export-control",
        "security",
        "sup",
    ):
        _touch_dir(root / name)
    return root


# Every location of 14.3 "today", verbatim from the task's own production
# enumeration -- real directories, except the four arch-level convenience
# symlinks called out below (powerpc deliberately has none; see
# shared/protected_paths.py's module docstring).
_FREEBSD_143_REAL_DIRS = (
    "amd64/amd64/14.3-RELEASE",
    "amd64/amd64/ISO-IMAGES/14.3",
    "arm64/aarch64/14.3-RELEASE",
    "arm64/aarch64/ISO-IMAGES/14.3",
    "arm/armv7/ISO-IMAGES/14.3",
    "i386/i386/14.3-RELEASE",
    "i386/i386/ISO-IMAGES/14.3",
    "riscv/riscv64/14.3-RELEASE",
    "riscv/riscv64/ISO-IMAGES/14.3",
    "powerpc/14.3-RELEASE",
    "powerpc/powerpc/14.3-RELEASE",
    "powerpc/powerpc64/14.3-RELEASE",
    "powerpc/powerpc64le/14.3-RELEASE",
    "powerpc/powerpcspe/14.3-RELEASE",
    "powerpc/powerpc/ISO-IMAGES/14.3",
    "powerpc/powerpc64/ISO-IMAGES/14.3",
    "powerpc/powerpc64le/ISO-IMAGES/14.3",
    "powerpc/powerpcspe/ISO-IMAGES/14.3",
    "ISO-IMAGES/14.3",
    "VM-IMAGES/14.3-RELEASE",
    "CI-IMAGES/14.3-RELEASE",
    "OCI-IMAGES/14.3-RELEASE",
)
_FREEBSD_143_SYMLINKS = {
    "amd64/14.3-RELEASE": "amd64/14.3-RELEASE",
    "arm64/14.3-RELEASE": "aarch64/14.3-RELEASE",
    "i386/14.3-RELEASE": "i386/14.3-RELEASE",
    "riscv/14.3-RELEASE": "riscv64/14.3-RELEASE",
}


def _build_freebsd_143(releases: Path) -> None:
    for rel in _FREEBSD_143_REAL_DIRS:
        _touch_dir(releases / rel)
    for link_rel, target_rel in _FREEBSD_143_SYMLINKS.items():
        link = releases / link_rel
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target_rel)


def _add_freebsd_release(releases: Path, version: str) -> None:
    """A minimal-but-representative shape: one real per-arch directory, its
    arch-level symlink, and one ISO-IMAGES entry. 14.3 above already proves
    the full, exact production shape; this is enough to classify the other
    lines without re-typing ~20 locations each.
    """
    real = releases / "amd64" / "amd64" / f"{version}-RELEASE"
    _touch_dir(real)
    symlink = releases / "amd64" / f"{version}-RELEASE"
    symlink.symlink_to(f"amd64/{version}-RELEASE")
    _touch_dir(releases / "ISO-IMAGES" / version)


def _build_freebsd_root(tmp_path: Path) -> Path:
    root = tmp_path / "freebsd" / "pub" / "FreeBSD"
    releases = root / "releases"
    for name in (
        "amd64",
        "arm",
        "arm64",
        "CI-IMAGES",
        "i386",
        "ISO-IMAGES",
        "OCI-IMAGES",
        "PKGBASE-REPOS",
        "powerpc",
        "riscv",
        "VM-IMAGES",
    ):
        _touch_dir(releases / name)
    (releases / "README.TXT").write_text("x")
    (releases / "TIMESTAMP").write_text("x")

    _build_freebsd_143(releases)
    _add_freebsd_release(releases, "14.4")
    _add_freebsd_release(releases, "15.0")
    _add_freebsd_release(releases, "14.5")  # current, deliberately unprotected
    _add_freebsd_release(releases, "15.1")  # current, deliberately unprotected
    return root


def _by_version(releases: List[dict]) -> Dict[str, dict]:
    return {r["version"]: r for r in releases}


def _loc(*segments: str, is_dir: bool = True) -> Location:
    return Location(segments, is_dir)


# ---------------------------------------------------------------------------
# 1. Detection & classification against the production-shaped trees
# ---------------------------------------------------------------------------


def test_openbsd_classification_matches_the_production_facts(tmp_path):
    root = _build_openbsd_root(tmp_path)
    result = build_mirror_inventory(
        MirrorType.OPENBSD, str(root), PROTECTED_PATHS[MirrorType.OPENBSD]
    )

    assert result["available"] is True
    assert result["truncated"] is False
    assert result["errors"] == []
    assert result["incomplete"] is False
    by_version = _by_version(result["releases"])
    assert set(by_version) == {"7.5", "7.6", "7.7", "7.8", "7.9"}

    for version in ("7.5", "7.6", "7.7", "7.8"):
        r = by_version[version]
        assert r["protection"] == "full", r
        assert r["kind"] == "release"
        assert r["current"] is False
        assert r["at_risk"] is False, r

    newest = by_version["7.9"]
    assert newest["protection"] == "none"
    assert newest["newest"] is True
    assert newest["current"] is True
    assert newest["at_risk"] is False, "the current release must never be at_risk"
    assert result["protected_not_on_disk"] == []
    assert result["current_not_on_disk"] == []
    # newest first
    assert result["releases"][0]["version"] == "7.9"


def test_netbsd_classification_matches_the_production_facts(tmp_path):
    root = _build_netbsd_root(tmp_path)
    result = build_mirror_inventory(
        MirrorType.NETBSD, str(root), PROTECTED_PATHS[MirrorType.NETBSD]
    )

    assert result["available"] is True
    assert result["incomplete"] is False
    by_version = _by_version(result["releases"])
    assert set(by_version) == {
        "NetBSD-7.2",
        "NetBSD-8.3",
        "NetBSD-9.0",
        "NetBSD-9.5",
        "NetBSD-10.0",
        "NetBSD-10.1",
        "NetBSD-11.0_RC7",
        "NetBSD-11.0",
    }

    for version in (
        "NetBSD-7.2",
        "NetBSD-8.3",
        "NetBSD-9.0",
        "NetBSD-9.5",
        "NetBSD-10.0",
        "NetBSD-10.1",
    ):
        assert by_version[version]["protection"] == "full"
        assert by_version[version]["kind"] == "release"
        assert by_version[version]["at_risk"] is False

    rc7 = by_version["NetBSD-11.0_RC7"]
    assert rc7["kind"] == "prerelease"
    assert rc7["protection"] == "full"
    assert rc7["current"] is False
    assert rc7["at_risk"] is False, "a fully-protected prerelease is never at_risk"

    final = by_version["NetBSD-11.0"]
    assert final["protection"] == "none"
    assert final["current"] is True
    assert final["at_risk"] is False
    assert result["protected_not_on_disk"] == []
    assert result["current_not_on_disk"] == []


def test_freebsd_classification_matches_the_production_facts(tmp_path):
    root = _build_freebsd_root(tmp_path)
    result = build_mirror_inventory(
        MirrorType.FREEBSD, str(root), PROTECTED_PATHS[MirrorType.FREEBSD]
    )

    assert result["available"] is True
    assert result["truncated"] is False
    assert result["incomplete"] is False
    by_version = _by_version(result["releases"])
    assert set(by_version) == {
        "14.3-RELEASE",
        "14.4-RELEASE",
        "14.5-RELEASE",
        "15.0-RELEASE",
        "15.1-RELEASE",
    }

    full_143 = by_version["14.3-RELEASE"]
    assert full_143["protection"] == "full", full_143
    assert full_143["location_count"] == len(_FREEBSD_143_REAL_DIRS) + len(_FREEBSD_143_SYMLINKS)
    assert full_143["unprotected_locations"] == []
    # The arch-level symlinks and the ISO directories are both in the mix,
    # not just the "obvious" real per-arch directories.
    assert "releases/amd64/14.3-RELEASE" in full_143["locations"]
    assert "releases/amd64/amd64/ISO-IMAGES/14.3" in full_143["locations"]
    assert full_143["at_risk"] is False

    for version in ("14.4-RELEASE", "15.0-RELEASE"):
        r = by_version[version]
        assert r["protection"] == "full", r
        assert r["at_risk"] is False

    current_145 = by_version["14.5-RELEASE"]
    assert current_145["protection"] == "none"
    assert current_145["current"] is True
    assert current_145["at_risk"] is False, "14.5-RELEASE is current; must not be at_risk"

    current_151 = by_version["15.1-RELEASE"]
    assert current_151["protection"] == "none"
    assert current_151["current"] is True
    assert current_151["at_risk"] is False

    assert result["protected_not_on_disk"] == []
    assert result["current_not_on_disk"] == []
    assert result["releases"][0]["version"] == "15.1-RELEASE"


def test_freebsd_modified_is_iso8601_utc(tmp_path):
    root = _build_freebsd_root(tmp_path)
    result = build_mirror_inventory(MirrorType.FREEBSD, str(root), ())
    r = _by_version(result["releases"])["14.3-RELEASE"]
    assert r["modified"] is not None
    parsed = datetime.fromisoformat(r["modified"])
    assert parsed.utcoffset().total_seconds() == 0


def test_an_mtime_datetime_fromtimestamp_cannot_represent_gives_modified_null(tmp_path):
    """F6: the `fromtimestamp` guard in _newest_mtime, pinned directly
    rather than just asserted to exist. A 64-bit filesystem can store an
    mtime far beyond datetime.MAXYEAR (9999); that must degrade `modified`
    to null for this one release, not raise for the whole mirror.
    """
    root = _build_freebsd_root(tmp_path)
    releases = root / "releases"
    target = releases / "amd64" / "amd64" / "14.4-RELEASE"
    huge = 99999999999999.0  # far beyond what datetime.fromtimestamp can hold
    os.utime(target, (huge, huge))

    result = build_mirror_inventory(MirrorType.FREEBSD, str(root), ())
    r = _by_version(result["releases"])["14.4-RELEASE"]
    assert r["modified"] is None


# ---------------------------------------------------------------------------
# 2. Risk & drift
# ---------------------------------------------------------------------------


def test_an_unprotected_older_final_release_is_at_risk(tmp_path):
    """OpenBSD 7.4: older than the protected 7.5-7.8 band, not current, and
    not covered by any pattern -- exactly the case this feature exists to
    surface before upstream prunes it out from under the mirror."""
    root = _build_openbsd_root(tmp_path, extra_releases=("7.4",))
    result = build_mirror_inventory(
        MirrorType.OPENBSD, str(root), PROTECTED_PATHS[MirrorType.OPENBSD]
    )

    r = _by_version(result["releases"])["7.4"]
    assert r["protection"] == "none"
    assert r["current"] is False
    assert r["at_risk"] is True


def test_a_new_major_release_is_at_risk_until_current_releases_is_updated(tmp_path):
    """The F1 bug, reproduced directly. Before this fix, at_risk trusted
    latest_in_major alone. Here OpenBSD 8.0 has just shipped (matches the
    release regex, unprotected, and -- realistically -- not yet added to
    CURRENT_RELEASES): it is both `newest` AND `latest_in_major` (trivially,
    being the only release in major 8), which is exactly the combination the
    old rule would have read as "safe". It is not -- our reviewed list has
    simply not caught up yet -- and the new rule, keyed on `current`, is not
    fooled by either informational field. 7.9 stays `latest_in_major` for
    its own (now superseded) major regardless, which is also why that field
    alone was never a safe signal.
    """
    root = _build_openbsd_root(tmp_path, extra_releases=("8.0",))
    result = build_mirror_inventory(
        MirrorType.OPENBSD, str(root), PROTECTED_PATHS[MirrorType.OPENBSD]
    )
    by_version = _by_version(result["releases"])

    assert by_version["7.9"]["current"] is True
    assert by_version["7.9"]["latest_in_major"] is True  # still true of major 7 specifically
    assert by_version["7.9"]["newest"] is False  # 8.0 outranks it mirror-wide now
    assert by_version["7.9"]["at_risk"] is False

    eight_oh = by_version["8.0"]
    assert eight_oh["current"] is False
    assert eight_oh["newest"] is True  # informational only -- not a safety signal
    assert eight_oh["latest_in_major"] is True  # ditto
    assert eight_oh["protection"] == "none"
    assert eight_oh["at_risk"] is True, (
        "8.0 is unprotected and not in CURRENT_RELEASES -- exactly the gap "
        "newest/latest_in_major alone used to hide"
    )


def test_an_unprotected_old_major_freebsd_release_is_at_risk(tmp_path):
    """FreeBSD 13.5-RELEASE: the only release in its (long-superseded)
    major, so it is trivially "latest_in_major" -- and, before F1, that
    alone was enough to call it safe."""
    root = _build_freebsd_root(tmp_path)
    releases = root / "releases"
    _add_freebsd_release(releases, "13.5")

    result = build_mirror_inventory(
        MirrorType.FREEBSD, str(root), PROTECTED_PATHS[MirrorType.FREEBSD]
    )
    r = _by_version(result["releases"])["13.5-RELEASE"]

    assert r["protection"] == "none"
    assert r["current"] is False
    assert r["latest_in_major"] is True
    assert r["at_risk"] is True


def test_partial_coverage_lists_its_unprotected_locations(tmp_path):
    """A synthetic pattern set that protects the release directory and its
    symlink but not its ISO-IMAGES entry -- partial, not full, with the ISO
    location named explicitly."""
    root = _build_freebsd_root(tmp_path)
    patterns = ("**/14.4-RELEASE", "**/14.4-RELEASE/***")  # no ISO-IMAGES pattern

    result = build_mirror_inventory(MirrorType.FREEBSD, str(root), patterns)
    r = _by_version(result["releases"])["14.4-RELEASE"]

    assert r["protection"] == "partial"
    assert r["unprotected_locations"] == ["releases/ISO-IMAGES/14.4"]


def test_protected_not_on_disk_when_a_protected_release_directory_is_missing(tmp_path):
    root = _build_openbsd_root(tmp_path)
    shutil.rmtree(root / "7.6")

    result = build_mirror_inventory(
        MirrorType.OPENBSD, str(root), PROTECTED_PATHS[MirrorType.OPENBSD]
    )

    assert "7.6" not in _by_version(result["releases"])
    assert result["protected_not_on_disk"] == ["7.6"]


def test_current_not_on_disk_when_the_current_release_is_missing(tmp_path):
    """CURRENT_RELEASES has drifted stale -- the operator's list still names
    a release that is no longer on disk at all."""
    root = _build_openbsd_root(tmp_path)
    shutil.rmtree(root / "7.9")

    result = build_mirror_inventory(
        MirrorType.OPENBSD, str(root), PROTECTED_PATHS[MirrorType.OPENBSD]
    )
    assert result["current_not_on_disk"] == ["7.9"]


def test_freebsd_prerelease_is_its_own_entry(tmp_path):
    root = _build_freebsd_root(tmp_path)
    releases = root / "releases"
    _touch_dir(releases / "amd64" / "amd64" / "14.5-RC1")

    result = build_mirror_inventory(MirrorType.FREEBSD, str(root), ())  # nothing protected
    by_version = _by_version(result["releases"])

    rc1 = by_version["14.5-RC1"]
    assert rc1["kind"] == "prerelease"
    assert rc1["line"] == "14.5"
    assert rc1["major"] == "14"
    assert rc1["current"] is False
    assert rc1["at_risk"] is False, "an unprotected, ordinary pre-release is never at_risk"
    # It must not have merged into the final 14.5-RELEASE entry's locations.
    assert "releases/amd64/amd64/14.5-RC1" not in by_version["14.5-RELEASE"]["locations"]


def test_a_targeted_but_incompletely_protected_prerelease_is_at_risk(tmp_path):
    """The other half of the prerelease at_risk rule: SOMETHING in
    PROTECTED_PATHS does target this exact prerelease (someone decided it
    should be kept, unlike the ordinary case above), but coverage is
    incomplete -- here, a bare-only pattern for a prerelease that has both a
    symlink and a real directory -- which is worth flagging, unlike a
    prerelease nobody ever tried to protect.
    """
    root = _build_freebsd_root(tmp_path)
    releases = root / "releases"
    real = releases / "amd64" / "amd64" / "14.5-RC1"
    _touch_dir(real)
    (releases / "amd64" / "14.5-RC1").symlink_to("amd64/14.5-RC1")

    # Bare only: covers the symlink, not the real directory (see F2 /
    # pattern_matches's docstring) -- targeted, but not fully protected.
    result = build_mirror_inventory(MirrorType.FREEBSD, str(root), ("**/14.5-RC1",))
    rc1 = _by_version(result["releases"])["14.5-RC1"]

    assert rc1["protection"] == "partial", rc1
    assert rc1["at_risk"] is True


def test_a_current_release_appended_not_replaced_flags_the_old_one_stale_openbsd(
    tmp_path, monkeypatch
):
    """A stale CURRENT_RELEASES entry, reproduced directly. 8.0 shipped and
    an operator appended it to CURRENT_RELEASES INSTEAD OF replacing "7.9"
    with it (shared/protected_paths.py's upgrade procedure, step 2, done
    only half-way). Both are now tagged `current`, and the old rule
    (`at_risk = protection != "full" and not current`) would have called
    both safe forever. 7.9 must be flagged `stale_current` and, being
    unprotected, `at_risk`; 8.0 -- the actually-current one -- must not be.
    """
    root = _build_openbsd_root(tmp_path, extra_releases=("8.0",))
    monkeypatch.setitem(archive_inventory.CURRENT_RELEASES, MirrorType.OPENBSD, ("7.9", "8.0"))

    result = build_mirror_inventory(
        MirrorType.OPENBSD, str(root), PROTECTED_PATHS[MirrorType.OPENBSD]
    )
    by_version = _by_version(result["releases"])

    assert result["stale_current"] == ["7.9"]
    assert by_version["7.9"]["current"] is True
    assert by_version["7.9"]["at_risk"] is True, "stale -- must not be trusted as current any more"
    assert by_version["8.0"]["current"] is True
    assert by_version["8.0"]["at_risk"] is False, "the freshest current entry is never stale"


def test_a_current_release_appended_not_replaced_flags_the_old_one_stale_freebsd(
    tmp_path, monkeypatch
):
    """Same bug, FreeBSD shape: "14.5-RELEASE once 14.6-RELEASE exists" --
    staleness is per-major, not mirror-wide, so 15.1-RELEASE (a different,
    untouched major) must be completely unaffected.
    """
    root = _build_freebsd_root(tmp_path)
    releases = root / "releases"
    _add_freebsd_release(releases, "14.6")
    monkeypatch.setitem(
        archive_inventory.CURRENT_RELEASES,
        MirrorType.FREEBSD,
        ("14.5-RELEASE", "14.6-RELEASE", "15.1-RELEASE"),
    )

    result = build_mirror_inventory(MirrorType.FREEBSD, str(root), ())  # nothing protected
    by_version = _by_version(result["releases"])

    assert result["stale_current"] == ["14.5-RELEASE"]
    assert by_version["14.5-RELEASE"]["current"] is True
    assert by_version["14.5-RELEASE"]["at_risk"] is True
    assert by_version["14.6-RELEASE"]["current"] is True
    assert by_version["14.6-RELEASE"]["at_risk"] is False
    assert by_version["15.1-RELEASE"]["current"] is True
    assert by_version["15.1-RELEASE"]["at_risk"] is False, "a different major is unaffected"


def test_a_single_current_release_is_never_stale_even_when_a_newer_unlisted_release_exists(
    tmp_path,
):
    """The negative case, so F1's and F2's fixes cannot cancel each other
    out: CURRENT_RELEASES is untouched (still just "7.9"), and 8.0 exists
    only on disk, unlisted -- test_a_new_major_release_is_at_risk_until_
    current_releases_is_updated already pins 7.9's at_risk staying False
    here; this pins `stale_current` staying empty too. Staleness is scoped
    to CURRENT_RELEASES' own membership, not compared against every
    on-disk release mirror-wide -- see _annotate_cross_release_fields.
    """
    root = _build_openbsd_root(tmp_path, extra_releases=("8.0",))
    result = build_mirror_inventory(
        MirrorType.OPENBSD, str(root), PROTECTED_PATHS[MirrorType.OPENBSD]
    )
    assert result["stale_current"] == []


# ---------------------------------------------------------------------------
# 3. Entry-type-aware coverage (F2), pure -- no rsync needed for the
# direction each half proves; the real-rsync cross-check in
# tests/test_protected_paths.py proves the same two properties against the
# real binary.
# ---------------------------------------------------------------------------


def test_a_symlinked_anchored_release_is_not_covered(tmp_path):
    """`/7.5/***` (anchored, carries the directory-only `/***`) must not
    protect a same-named SYMLINK."""
    root = tmp_path / "openbsd"
    real = root / "real75"
    _touch_dir(real)
    (root / "7.5").symlink_to("real75")

    result = build_mirror_inventory(MirrorType.OPENBSD, str(root), ("/7.5/***",))
    r = _by_version(result["releases"])["7.5"]
    assert r["protection"] != "full", r
    assert "7.5" in r["unprotected_locations"]


def test_a_bare_only_covered_directory_is_not_full(tmp_path):
    """A bare `**/NAME` must not fully protect a same-named real directory
    -- see pattern_matches's docstring on why (rsync still deletes files
    removed from inside it while it keeps being served)."""
    root = tmp_path / "freebsd"
    releases = root / "releases"
    _touch_dir(releases / "amd64" / "amd64" / "14.4-RELEASE")

    result = build_mirror_inventory(MirrorType.FREEBSD, str(root), ("**/14.4-RELEASE",))
    r = _by_version(result["releases"])["14.4-RELEASE"]

    assert r["protection"] == "partial", r  # targeted, but not fully covered
    assert r["unprotected_locations"] == ["releases/amd64/amd64/14.4-RELEASE"]


def test_a_symlink_is_covered_by_the_matching_bare_pattern():
    p = compile_pattern("**/14.3-RELEASE")
    symlink = _loc("amd64", "14.3-RELEASE", is_dir=False)
    real_dir = _loc("amd64", "amd64", "14.3-RELEASE", is_dir=True)
    assert pattern_matches(p, symlink) is True
    assert pattern_matches(p, real_dir) is False


def test_a_directory_is_covered_by_the_matching_suffix_pattern():
    p = compile_pattern("**/14.3-RELEASE/***")
    real_dir = _loc("amd64", "amd64", "14.3-RELEASE", is_dir=True)
    symlink = _loc("amd64", "14.3-RELEASE", is_dir=False)
    assert pattern_matches(p, real_dir) is True
    assert pattern_matches(p, symlink) is False


def test_is_targeted_is_true_even_when_the_type_does_not_match():
    """is_targeted (path only) must not agree with is_covered (path AND
    type) for a type-mismatched location -- that gap is exactly what turns
    "none" into "partial" in _finalize_releases."""
    p = compile_pattern("**/14.3-RELEASE/***")
    symlink = _loc("amd64", "14.3-RELEASE", is_dir=False)
    assert is_targeted(symlink, [p]) is True
    assert is_covered(symlink, [p]) is False


# ---------------------------------------------------------------------------
# 4. The protect-filter pattern parser
# ---------------------------------------------------------------------------


def test_every_real_pattern_parses():
    """Fails CI the day a fourth pattern shape is added to
    shared/protected_paths.py without a matching case in compile_pattern --
    the exact regression the module docstring calls out."""
    for mirror_type in MirrorType:
        compile_patterns(PROTECTED_PATHS[mirror_type])  # must not raise


def test_anchored_pattern_matches_only_the_exact_top_level_path():
    p = compile_pattern("/7.5/***")
    assert p == CompiledPattern("anchored", ("7.5",), "/7.5/***")
    assert pattern_matches(p, _loc("7.5")) is True
    assert pattern_matches(p, _loc("7.6")) is False
    assert pattern_matches(p, _loc("releases", "7.5")) is False


def test_bare_pattern_matches_the_last_segment_at_any_depth():
    p = compile_pattern("**/14.3-RELEASE")
    assert pattern_matches(p, _loc("14.3-RELEASE", is_dir=False)) is True
    assert pattern_matches(p, _loc("amd64", "14.3-RELEASE", is_dir=False)) is True
    assert pattern_matches(p, _loc("amd64", "amd64", "14.3-RELEASE", is_dir=False)) is True
    assert pattern_matches(p, _loc("amd64", "14.4-RELEASE", is_dir=False)) is False


def test_suffix_pattern_matches_its_trailing_segments_at_any_depth():
    p = compile_pattern("**/ISO-IMAGES/14.3/***")
    assert pattern_matches(p, _loc("ISO-IMAGES", "14.3")) is True
    assert pattern_matches(p, _loc("amd64", "amd64", "ISO-IMAGES", "14.3")) is True
    assert pattern_matches(p, _loc("riscv", "riscv64", "ISO-IMAGES", "14.3")) is True
    assert pattern_matches(p, _loc("ISO-IMAGES", "14.4")) is False
    assert pattern_matches(p, _loc("14.3")) is False  # missing the ISO-IMAGES segment


def test_pattern_subject_names_what_a_pattern_protects():
    assert pattern_subject(compile_pattern("/7.5/***")) == "7.5"
    assert pattern_subject(compile_pattern("**/14.3-RELEASE")) == "14.3-RELEASE"
    assert pattern_subject(compile_pattern("**/ISO-IMAGES/14.3/***")) == "ISO-IMAGES/14.3"


def test_is_covered_is_true_if_any_pattern_matches():
    compiled = compile_patterns(["**/14.3-RELEASE", "**/14.3-RELEASE/***"])
    assert is_covered(_loc("amd64", "14.3-RELEASE", is_dir=False), compiled) is True
    assert is_covered(_loc("amd64", "14.4-RELEASE", is_dir=False), compiled) is False


@pytest.mark.parametrize(
    "pattern",
    [
        "**/*.txt",  # a real glob character, not one of the three shapes
        "/a/b/c",  # anchored but missing the /*** suffix
        "***",  # nothing to anchor or suffix
        "**/a/b",  # suffix shape missing its /*** terminator
        "/a/***/b",  # anchored with trailing content after ***
        "/7.[5]/***",  # a character class -- rsync wildcard, not a literal name
        "**/14.?-RELEASE",  # a single-char wildcard
        r"/7\.5/***",  # a backslash -- not a shape this parser models
    ],
)
def test_unknown_pattern_shapes_raise_instead_of_being_guessed(pattern):
    with pytest.raises(UnknownPatternError):
        compile_pattern(pattern)


def test_an_unrecognised_pattern_makes_the_whole_mirror_unknown_not_a_500(tmp_path):
    root = _build_openbsd_root(tmp_path)
    result = build_mirror_inventory(MirrorType.OPENBSD, str(root), ("/7.5/***", "**/*.txt"))

    assert result["available"] is True  # the filesystem scan itself is fine
    for release in result["releases"]:
        assert release["protection"] == "unknown", release
        assert release["unprotected_locations"] == []
    assert result["protected_not_on_disk"] == [], "never guess drift from unparsed patterns either"


# ---------------------------------------------------------------------------
# 5. Filesystem hazards
# ---------------------------------------------------------------------------


def test_a_root_level_symlink_pointing_at_slash_is_not_descended_into(tmp_path):
    root = tmp_path / "freebsd"
    releases = root / "releases"
    _touch_dir(releases / "amd64" / "amd64" / "14.3-RELEASE")
    (releases / "escape").symlink_to("/")

    scan = scan_freebsd_releases(root)

    assert scan.truncated is False
    assert [g["line"] for g in scan.groups] == ["14.3"]


def test_a_symlink_pointing_outside_the_root_is_not_descended_into(tmp_path):
    outside = tmp_path / "outside"
    _touch_dir(outside / "99.9-RELEASE")  # a directory name that WOULD match if reached

    root = tmp_path / "freebsd"
    releases = root / "releases"
    _touch_dir(releases)
    (releases / "escape").symlink_to(outside)

    scan = scan_freebsd_releases(root)

    assert scan.groups == []
    assert scan.truncated is False


def test_a_symlink_loop_does_not_hang(tmp_path):
    root = tmp_path / "freebsd"
    releases = root / "releases"
    _touch_dir(releases)
    (releases / "loop_a").symlink_to("loop_b")
    (releases / "loop_b").symlink_to("loop_a")

    scan = scan_freebsd_releases(root)  # must return, not hang

    assert scan.groups == []
    assert scan.truncated is False


def test_a_self_looping_release_named_symlink_does_not_take_down_the_mirror(tmp_path):
    """F4: a single self-looping symlink named like a release (e.g. "7.10")
    must not reach a syscall that resolves it -- is_dir(follow_symlinks=True)
    on such an entry raises ELOOP, which used to propagate all the way up
    and mark the WHOLE mirror unavailable over one bad entry.
    """
    root = _build_openbsd_root(tmp_path)
    (root / "7.10").symlink_to("7.10")

    result = build_mirror_inventory(
        MirrorType.OPENBSD, str(root), PROTECTED_PATHS[MirrorType.OPENBSD]
    )

    assert result["available"] is True
    by_version = _by_version(result["releases"])
    assert set(by_version) >= {"7.5", "7.6", "7.7", "7.8", "7.9"}
    # The looping entry itself is recorded as a (necessarily unprotected,
    # non-directory) location, not silently dropped and not resolved.
    assert "7.10" in by_version
    assert by_version["7.10"]["locations"] == ["7.10"]


def test_a_symlinked_releases_directory_is_reported_not_walked(tmp_path):
    """F4: `releases` itself must be lstat'd before it is opened. A mirror
    root whose `releases` is a symlink must not be walked through -- it
    would mean scanning (and reporting on) a tree that is not actually this
    mirror's."""
    root = tmp_path / "freebsd"
    root.mkdir()
    elsewhere = tmp_path / "elsewhere"
    _touch_dir(elsewhere / "amd64" / "amd64" / "14.3-RELEASE")
    (root / "releases").symlink_to(elsewhere)

    with pytest.raises(OSError):
        scan_freebsd_releases(root)

    result = build_mirror_inventory(MirrorType.FREEBSD, str(root), ())
    assert result["available"] is False
    assert result["error"]


def test_a_symlinked_openbsd_root_is_reported_unavailable_not_followed(tmp_path):
    """F4: the OpenBSD root itself must be opened with O_NOFOLLOW, the same
    defence `releases` already had for FreeBSD -- a symlinked root is
    refused, not walked."""
    real_root = _build_openbsd_root(tmp_path)
    linked_root = tmp_path / "openbsd-link"
    linked_root.symlink_to(real_root)

    with pytest.raises(OSError):
        scan_openbsd_releases(linked_root)

    result = build_mirror_inventory(MirrorType.OPENBSD, str(linked_root), ())
    assert result["available"] is False
    assert result["error"]


def test_a_symlinked_netbsd_root_is_reported_unavailable_not_followed(tmp_path):
    """Same as above, NetBSD."""
    real_root = _build_netbsd_root(tmp_path)
    linked_root = tmp_path / "netbsd-link"
    linked_root.symlink_to(real_root)

    with pytest.raises(OSError):
        scan_netbsd_releases(linked_root)

    result = build_mirror_inventory(MirrorType.NETBSD, str(linked_root), ())
    assert result["available"] is False
    assert result["error"]


def test_a_dangling_symlink_locations_modified_time_is_its_own_lstat_time(tmp_path):
    """F4: mtime must come from entry.stat(follow_symlinks=False) on the
    symlink itself, captured DURING the walk -- never re-resolved through
    whatever it points at. Proven with a DANGLING symlink: if this ever
    tried to stat through it, the target does not exist, stat would raise
    ENOENT, and `modified` would come back null. A real timestamp instead
    proves the symlink's own lstat metadata was used.
    """
    root = tmp_path / "freebsd"
    releases = root / "releases"
    _touch_dir(releases / "amd64")
    link = releases / "amd64" / "14.4-RELEASE"
    link.symlink_to("amd64/does-not-exist-target")

    result = build_mirror_inventory(MirrorType.FREEBSD, str(root), ())
    r = _by_version(result["releases"])["14.4-RELEASE"]
    assert r["location_count"] == 1
    assert r["modified"] is not None


def test_every_directory_open_in_the_freebsd_walk_uses_o_nofollow(tmp_path, monkeypatch):
    """F4: every os.open() this walk makes for a directory -- `releases`
    itself and every subdirectory below it -- must carry O_NOFOLLOW. That
    is the actual defence against a directory swapped for a symlink
    between being listed and being opened; the lstat on `releases` is only
    a clearer error message for the common case, not the guarantee.
    """
    root = _build_freebsd_root(tmp_path)
    real_open = os.open
    flags_seen = []

    def spying_open(path, flags, *args, **kwargs):
        flags_seen.append(flags)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(archive_inventory.os, "open", spying_open)

    scan_freebsd_releases(root)

    assert flags_seen, "expected at least one os.open() call"
    for flags in flags_seen:
        assert flags & os.O_NOFOLLOW, f"a directory was opened without O_NOFOLLOW: {flags!r}"


def test_fd_exhaustion_is_handled_without_emfile_errors(tmp_path):
    """F3: children used to be opened when QUEUED, not when scanned -- a
    directory with 3000 subdirectories held 3001 fds at once well before
    any of them were actually looked at, which blew a 1024 soft limit,
    silently lost releases (truncated never got set), and starved other
    threads of fds too. Run in a SUBPROCESS with a deliberately low
    RLIMIT_NOFILE (never this test process's own fd table) and 300 sibling
    subdirectories -- comfortably more than a depth+1 fd budget could ever
    need at once, so any EMFILE here is this module's own bug, not an
    unreasonably low limit.
    """
    root = tmp_path / "freebsd"
    releases = root / "releases"
    _touch_dir(releases)
    for i in range(300):
        _touch_dir(releases / f"decoy-{i:04d}")
    _touch_dir(releases / "amd64" / "amd64" / "14.3-RELEASE")

    script = textwrap.dedent(
        f"""
        import json
        import resource
        from pathlib import Path

        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))

        from app.core.archive_inventory import scan_freebsd_releases

        scan = scan_freebsd_releases(Path({str(root)!r}))
        print(json.dumps({{
            "truncated": scan.truncated,
            "errors": scan.errors,
            "lines": sorted(g["line"] for g in scan.groups),
        }}))
    """
    )

    repo_root = Path(__file__).resolve().parent.parent
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{repo_root / 'backend'}:{repo_root}"

    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    output = json.loads(proc.stdout.strip().splitlines()[-1])

    assert output["lines"] == ["14.3"], output
    assert output["errors"] == [], output
    assert output["truncated"] is False, output


def test_the_entry_cap_sets_truncated_for_freebsd(tmp_path):
    root = tmp_path / "freebsd"
    releases = root / "releases"
    _touch_dir(releases)
    for i in range(25):
        _touch_dir(releases / f"decoy-{i:02d}")

    scan = scan_freebsd_releases(root, max_entries=10)

    assert scan.truncated is True
    assert scan.groups == []


def test_the_entry_cap_sets_truncated_for_openbsd(tmp_path):
    """F5: OpenBSD/NetBSD had no cap at all before -- the same budget now
    applies to their single-directory scan too."""
    root = tmp_path / "openbsd"
    _touch_dir(root)
    for i in range(25):
        _touch_dir(root / f"{i}.0")

    scan = scan_openbsd_releases(root, max_entries=10)

    assert scan.truncated is True
    assert len(scan.groups) <= 10


def test_the_entry_cap_bounds_work_not_just_the_report(tmp_path, monkeypatch):
    """F5: the cap must be enforced by reading at most budget+1 entries
    (itertools.islice) before sorting, not by reading and sorting the whole
    directory first. Proven by making a full sort explode and confirming
    the capped scan still doesn't call it.
    """
    root = tmp_path / "openbsd"
    _touch_dir(root)
    for i in range(50):
        _touch_dir(root / f"{i}.0")

    real_sorted = sorted

    def exploding_sorted(iterable, **kwargs):
        materialized = list(iterable)
        if len(materialized) > 11:
            raise AssertionError("sorted() was given more than budget+1 entries")
        return real_sorted(materialized, **kwargs)

    monkeypatch.setattr(archive_inventory, "sorted", exploding_sorted, raising=False)
    scan = scan_openbsd_releases(root, max_entries=10)
    assert scan.truncated is True


def test_the_entry_cap_bounds_work_not_just_the_report_netbsd(tmp_path, monkeypatch):
    """F6: the OpenBSD version of this test does not exercise NetBSD's own
    (identically-shaped) call to _read_capped -- a regression there could
    still slip through with only the OpenBSD test in place."""
    root = tmp_path / "netbsd"
    _touch_dir(root)
    for i in range(50):
        _touch_dir(root / f"NetBSD-{i}.0")

    real_sorted = sorted

    def exploding_sorted(iterable, **kwargs):
        materialized = list(iterable)
        if len(materialized) > 11:
            raise AssertionError("sorted() was given more than budget+1 entries")
        return real_sorted(materialized, **kwargs)

    monkeypatch.setattr(archive_inventory, "sorted", exploding_sorted, raising=False)
    scan = scan_netbsd_releases(root, max_entries=10)
    assert scan.truncated is True


def test_the_entry_cap_bounds_work_not_just_the_report_freebsd(tmp_path, monkeypatch):
    """F6: FreeBSD's walk calls _read_capped once per directory level, with
    a SHRINKING budget each time (`remaining = max_entries - visited`) --
    the cap on "how many entries sorted() ever sees in one call" must hold
    across every one of those calls, not just the first."""
    root = tmp_path / "freebsd"
    releases = root / "releases"
    _touch_dir(releases)
    for i in range(50):
        _touch_dir(releases / f"decoy-{i:02d}")

    real_sorted = sorted

    def exploding_sorted(iterable, **kwargs):
        materialized = list(iterable)
        if len(materialized) > 11:
            raise AssertionError("sorted() was given more than budget+1 entries")
        return real_sorted(materialized, **kwargs)

    monkeypatch.setattr(archive_inventory, "sorted", exploding_sorted, raising=False)
    scan = scan_freebsd_releases(root, max_entries=10)
    assert scan.truncated is True


def test_a_missing_root_is_reported_as_unavailable_not_raised(tmp_path):
    missing = tmp_path / "does-not-exist"
    result = build_mirror_inventory(
        MirrorType.OPENBSD, str(missing), PROTECTED_PATHS[MirrorType.OPENBSD]
    )

    assert result["available"] is False
    assert result["error"]
    assert result["releases"] == []
    assert result["root"] == str(missing)


def test_no_root_configured_is_reported_as_unavailable():
    result = build_mirror_inventory(MirrorType.FREEBSD, None, ())
    assert result["available"] is False
    assert result["root"] is None
    assert "no mirror is configured" in result["error"]


def test_scan_functions_do_raise_oserror_directly_for_a_missing_root(tmp_path):
    """build_mirror_inventory is the layer that turns this into
    `available: false` -- the scan_* functions themselves are pure and are
    allowed to raise, exactly as os.scandir does."""
    missing = tmp_path / "does-not-exist"
    with pytest.raises(OSError):
        scan_openbsd_releases(missing)
    with pytest.raises(OSError):
        scan_netbsd_releases(missing)
    with pytest.raises(OSError):
        scan_freebsd_releases(missing)


def test_a_per_entry_permission_error_is_recorded_not_fatal(tmp_path):
    """F4: one unreadable subdirectory becomes that entry's problem (a
    capped `errors` list), not the whole mirror's."""
    root = tmp_path / "freebsd"
    releases = root / "releases"
    blocked = releases / "amd64"
    _touch_dir(blocked / "amd64" / "14.3-RELEASE")
    _add_freebsd_release(releases, "14.4")
    os.chmod(blocked, 0o000)
    try:
        scan = scan_freebsd_releases(root)
    finally:
        os.chmod(blocked, 0o755)  # tmp_path cleanup needs this back

    assert any("amd64" in e for e in scan.errors), scan.errors
    # 14.4, reached through a sibling directory, must still be found.
    assert any(g["line"] == "14.4" for g in scan.groups)


# ---------------------------------------------------------------------------
# 5b. `incomplete` (F5): a per-mirror signal that a scan may not be the
# full picture, distinct from an ordinary "nothing wrong here" result.
# ---------------------------------------------------------------------------


def test_incomplete_is_true_when_truncated(tmp_path):
    root = tmp_path / "openbsd"
    _touch_dir(root)
    for i in range(25):
        _touch_dir(root / f"{i}.0")

    result = build_mirror_inventory(MirrorType.OPENBSD, str(root), (), max_entries=10)
    assert result["truncated"] is True
    assert result["incomplete"] is True


def test_incomplete_is_true_when_errors_is_non_empty(tmp_path):
    root = tmp_path / "freebsd"
    releases = root / "releases"
    blocked = releases / "amd64"
    _touch_dir(blocked / "amd64" / "14.3-RELEASE")
    os.chmod(blocked, 0o000)
    try:
        result = build_mirror_inventory(MirrorType.FREEBSD, str(root), ())
    finally:
        os.chmod(blocked, 0o755)

    assert result["errors"]
    assert result["incomplete"] is True


def test_incomplete_is_true_when_unclassified_is_non_empty(tmp_path):
    root = _build_openbsd_root(tmp_path)
    _touch_dir(root / "7.5.1")  # release-looking, fails the strict match

    result = build_mirror_inventory(MirrorType.OPENBSD, str(root), ())
    assert result["unclassified"]
    assert result["incomplete"] is True


def test_incomplete_is_true_when_the_depth_limit_hides_real_content(tmp_path):
    """The walk stops at MAX_WALK_DEPTH (4 segments below releases/). A
    real, non-matched directory sitting exactly at that boundary, with a
    subdirectory of its own this walk therefore never visits, is exactly
    the silent-data-loss case `incomplete` exists to surface.
    """
    root = tmp_path / "freebsd"
    releases = root / "releases"
    # 4 segments below releases/: at the cap, non-matching, and non-empty.
    hidden = releases / "amd64" / "amd64" / "unexpected" / "deeper"
    _touch_dir(hidden / "even-deeper")

    result = build_mirror_inventory(MirrorType.FREEBSD, str(root), ())
    assert result["incomplete"] is True


def test_incomplete_stays_false_when_the_depth_limit_hits_an_empty_directory(tmp_path):
    """The other half: a non-matched directory AT the depth cap that has no
    subdirectories of its own is not data loss -- there was nothing below
    it to miss -- and must not make an otherwise-clean scan `incomplete`.
    Directories inside a MATCHED version tree (e.g. deeper inside a real
    14.3-RELEASE) are never descended into at all, by design, and must not
    count either -- otherwise every FreeBSD scan would be `incomplete`
    forever and the operator would learn to ignore the signal.
    """
    root = _build_freebsd_root(tmp_path)  # the full production-shaped tree
    releases = root / "releases"
    # 4 segments below releases/ (the depth cap), non-matching, and
    # genuinely empty: nothing below it for the walk to have missed.
    _touch_dir(releases / "amd64" / "amd64" / "unexpected" / "empty-leaf")

    result = build_mirror_inventory(MirrorType.FREEBSD, str(root), ())
    assert result["incomplete"] is False


# ---------------------------------------------------------------------------
# 6. Non-UTF-8 names (F3)
# ---------------------------------------------------------------------------


def test_a_non_utf8_location_segment_is_display_safe(tmp_path):
    root = tmp_path / "freebsd"
    releases = root / "releases"
    bad_name = os.fsdecode(b"\xff\xfe")  # matches what scandir hands back for raw bad bytes
    _touch_dir(releases / bad_name / "14.3-RELEASE")

    result = build_mirror_inventory(MirrorType.FREEBSD, str(root), ())
    assert result["available"] is True
    r = _by_version(result["releases"])["14.3-RELEASE"]
    assert any(r"\xff\xfe" in loc for loc in r["locations"]), r["locations"]

    # ensure_ascii=False + encode("utf-8"): the exact way Starlette's
    # JSONResponse serialises the real response body (see the module
    # docstring's "NON-UTF-8 NAMES" section). The default json.dumps(result)
    # (ensure_ascii=True) never raises on a lone surrogate -- it backslash-
    # escapes it into plain ASCII instead -- so it would pass even with the
    # fix reverted and prove nothing.
    json.dumps(result, ensure_ascii=False).encode("utf-8")


def test_a_non_utf8_root_error_is_display_safe(tmp_path):
    bad_name = os.fsdecode(b"\xff\xfe")
    missing = tmp_path / bad_name
    result = build_mirror_inventory(MirrorType.OPENBSD, str(missing), ())
    assert result["available"] is False

    json.dumps(result, ensure_ascii=False).encode("utf-8")  # must not raise -- see above


def test_a_non_utf8_name_that_also_fails_to_open_is_display_safe_in_errors(tmp_path):
    """F3, the exact reported bug: a non-UTF-8 directory that ALSO fails to
    open (here, mode 000) puts its raw name into an OSError's own message
    (`str(exc)`, via its .filename), not just into a location path -- and
    that string used to go straight into `errors` unescaped. The suite
    runs as a non-root user, so mode 000 really is unreadable.
    """
    root = tmp_path / "freebsd"
    releases = root / "releases"
    bad_name = os.fsdecode(b"\xff\xfe-blocked")
    blocked = releases / bad_name
    _touch_dir(blocked)
    _add_freebsd_release(releases, "14.4")
    os.chmod(blocked, 0o000)
    try:
        result = build_mirror_inventory(MirrorType.FREEBSD, str(root), ())
    finally:
        os.chmod(blocked, 0o755)

    assert result["available"] is True
    assert any(g["line"] == "14.4" for g in result["releases"])
    assert result["errors"], "the blocked, non-UTF-8 entry should still be recorded as an error"
    json.dumps(result, ensure_ascii=False).encode("utf-8")  # must not raise


# ---------------------------------------------------------------------------
# 7. Unclassified names (F6)
# ---------------------------------------------------------------------------


def test_openbsd_unclassified_names_are_surfaced(tmp_path):
    root = _build_openbsd_root(tmp_path)
    _touch_dir(root / "7.5.1")  # looks like a release, does not match the strict regex

    result = build_mirror_inventory(MirrorType.OPENBSD, str(root), ())
    assert "7.5.1" in result["unclassified"]
    assert "7.5.1" not in _by_version(result["releases"])


def test_netbsd_unclassified_names_are_surfaced(tmp_path):
    root = _build_netbsd_root(tmp_path)
    _touch_dir(root / "NetBSD-7.1.2")

    result = build_mirror_inventory(MirrorType.NETBSD, str(root), ())
    assert "NetBSD-7.1.2" in result["unclassified"]


def test_freebsd_unclassified_names_are_surfaced(tmp_path):
    root = _build_freebsd_root(tmp_path)
    releases = root / "releases"
    _touch_dir(releases / "amd64" / "14.9-WEIRD")

    result = build_mirror_inventory(MirrorType.FREEBSD, str(root), ())
    assert "14.9-WEIRD" in result["unclassified"]


def test_unclassified_list_is_capped(tmp_path):
    root = tmp_path / "openbsd"
    _touch_dir(root)
    for i in range(archive_inventory.MAX_UNCLASSIFIED_PER_MIRROR + 10):
        _touch_dir(root / f"9.{i}.1")  # looks like a release, never matches
    result = build_mirror_inventory(MirrorType.OPENBSD, str(root), ())
    assert len(result["unclassified"]) == archive_inventory.MAX_UNCLASSIFIED_PER_MIRROR


def test_fullmatch_rejects_a_trailing_newline(tmp_path):
    """F6: `re.fullmatch` (never `re.match` + a trailing `$`, which --
    without re.MULTILINE -- still matches just before a trailing newline)
    throughout. A directory named with one is a valid, if unusual,
    filename on any POSIX filesystem and must not be classified as a
    release.
    """
    root = _build_openbsd_root(tmp_path)
    _touch_dir(root / "9.9\n")  # not one of the baseline fixture's own releases

    result = build_mirror_inventory(MirrorType.OPENBSD, str(root), ())
    by_version = _by_version(result["releases"])
    assert "9.9\n" not in by_version
    assert "9.9" not in by_version


def test_arabic_indic_digits_are_not_treated_as_ascii_release_digits(tmp_path):
    """F6: `[0-9]` (never `\\d`, which matches any Unicode decimal digit)
    throughout. Arabic-Indic digits satisfy Python's str.isdigit() -- so
    this name IS flagged `unclassified` -- but must never fullmatch the
    release regex itself.
    """
    root = _build_openbsd_root(tmp_path)
    # Arabic-Indic digits (U+0667 "7", U+0665 "5") for what a human would
    # read as "7.5" -- built with chr(), not the literal glyphs, so this
    # file itself doesn't trip a confusable-character scanner (ruff RUF001)
    # the way an upstream directory named this way would trip a human
    # skimming a listing.
    name = f"{chr(0x0667)}.{chr(0x0665)}"
    assert name.isdigit() is False  # "." isn't a digit; sanity-check the fixture
    assert name[0].isdigit() is True  # but str.isdigit() DOES accept the digit itself
    _touch_dir(root / name)

    result = build_mirror_inventory(MirrorType.OPENBSD, str(root), ())
    assert name not in _by_version(result["releases"])


# ---------------------------------------------------------------------------
# Database-aware layer, without the HTTP endpoint
# ---------------------------------------------------------------------------


def _mirror(mirror_id, name, mirror_type, local_path):
    return Mirror(
        id=mirror_id,
        name=name,
        mirror_type=mirror_type,
        upstream_url="rsync://example.test/",
        local_path=local_path,
        enabled=True,
        status=MirrorStatus.ACTIVE,
    )


def test_read_archive_inventory_lists_every_mirror_type_even_with_no_row(tmp_path):
    openbsd_root = _build_openbsd_root(tmp_path)
    mirrors = [_mirror(1, "OpenBSD", MirrorType.OPENBSD, str(openbsd_root))]

    results = read_archive_inventory(mirrors)
    by_type = {r["mirror_type"]: r for r in results}

    assert set(by_type) == ALL_TYPES
    assert by_type["openbsd"]["available"] is True
    assert by_type["openbsd"]["mirror_names"] == ["OpenBSD"]
    assert by_type["netbsd"]["available"] is False
    assert by_type["netbsd"]["mirror_names"] == []
    assert by_type["freebsd"]["mirror_names"] == []


def test_read_archive_inventory_picks_the_lowest_id_when_a_type_has_two_rows(tmp_path):
    root_a = _build_openbsd_root(tmp_path / "a")
    root_b = tmp_path / "b"
    mirrors = [
        _mirror(5, "Zeta", MirrorType.OPENBSD, str(root_b)),
        _mirror(2, "Alpha", MirrorType.OPENBSD, str(root_a)),
    ]

    results = read_archive_inventory(mirrors)
    openbsd = next(r for r in results if r["mirror_type"] == "openbsd")

    assert openbsd["root"] == str(root_a)
    assert openbsd["mirror_names"] == ["Alpha", "Zeta"]


# ---------------------------------------------------------------------------
# 8. The in-process cache (F5)
# ---------------------------------------------------------------------------


async def test_cache_hit_within_the_ttl_reuses_the_scan(monkeypatch):
    calls = 0

    def counting(mirrors):
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(archive_inventory, "read_archive_inventory", counting)
    fake_now = [1_000.0]
    monkeypatch.setattr(archive_inventory.time, "monotonic", lambda: fake_now[0])

    first = await archive_inventory.get_archive_inventory_view([])
    fake_now[0] += archive_inventory.CACHE_TTL_SECONDS - 1
    second = await archive_inventory.get_archive_inventory_view([])

    assert calls == 1
    assert second is first

    fake_now[0] += 2  # now past the TTL
    await archive_inventory.get_archive_inventory_view([])
    assert calls == 2


async def test_concurrent_calls_on_a_cold_cache_share_one_scan(monkeypatch):
    import asyncio as _asyncio
    import time as _time

    calls = 0
    real = archive_inventory.read_archive_inventory

    def slow_counting(mirrors):
        nonlocal calls
        calls += 1
        _time.sleep(0.05)
        return real(mirrors)

    monkeypatch.setattr(archive_inventory, "read_archive_inventory", slow_counting)

    results = await _asyncio.gather(
        *(archive_inventory.get_archive_inventory_view([]) for _ in range(5))
    )

    assert calls == 1
    assert all(r is results[0] for r in results)


async def test_a_scan_that_raises_is_never_cached(monkeypatch):
    """F6: a scan that raises must not leave a stale (or empty) result
    sitting in the cache for the rest of the TTL -- the next call has to
    try again, not silently reuse a failure. The exception must also still
    propagate to the caller that hit the failure.
    """
    calls = 0

    def boom(mirrors):
        nonlocal calls
        calls += 1
        raise RuntimeError("filesystem exploded")

    monkeypatch.setattr(archive_inventory, "read_archive_inventory", boom)

    with pytest.raises(RuntimeError):
        await archive_inventory.get_archive_inventory_view([])
    assert calls == 1

    with pytest.raises(RuntimeError):
        await archive_inventory.get_archive_inventory_view([])
    assert calls == 2, "a raised scan must not be cached -- the next call must rescan"


async def test_a_result_that_fails_the_encodability_check_is_served_but_not_cached(monkeypatch):
    """F1's third layer, in isolation: even if a bad result somehow made it
    past every sanitize step, get_archive_inventory_view must still hand
    it to THIS caller (best effort) while refusing to poison the cache for
    everyone else -- the next call must rescan instead of replaying the
    same bad result for the rest of the TTL.
    """
    calls = 0

    def fake_scan_and_check(mirrors):
        nonlocal calls
        calls += 1
        return [{"mirror_type": "openbsd"}], False  # "encodable" is False

    monkeypatch.setattr(archive_inventory, "_scan_and_check_encodable", fake_scan_and_check)

    first = await archive_inventory.get_archive_inventory_view([])
    assert first["mirrors"] == [{"mirror_type": "openbsd"}]
    assert calls == 1

    await archive_inventory.get_archive_inventory_view([])
    assert calls == 2, "an unencodable result must not be cached -- the next call must rescan"


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------


async def test_archive_inventory_endpoint_200_and_shape(client, seed):
    resp = await client.get(
        "/api/admin/archive-inventory", headers=auth_header(seed["users"]["readonly"])
    )
    assert resp.status_code == 200
    body = resp.json()

    assert "generated_at" in body
    datetime.fromisoformat(body["generated_at"])
    by_type = {m["mirror_type"]: m for m in body["mirrors"]}
    assert set(by_type) == ALL_TYPES

    # seed() creates one FreeBSD Mirror row, but local_path points at
    # /data/mirrors/... which does not exist inside the test process --
    # this is the "root missing or unreadable" state, not a 500.
    assert by_type["freebsd"]["mirror_names"] == ["FreeBSD"]
    assert by_type["freebsd"]["available"] is False
    assert by_type["freebsd"]["error"]

    assert by_type["netbsd"]["available"] is False
    assert by_type["netbsd"]["mirror_names"] == []
    assert by_type["openbsd"]["available"] is False
    assert by_type["openbsd"]["mirror_names"] == []


async def test_archive_inventory_endpoint_matches_the_pure_function(client, seed, db_session):
    mirrors = db_session.execute(select(Mirror)).scalars().all()
    expected = read_archive_inventory(mirrors)

    resp = await client.get(
        "/api/admin/archive-inventory", headers=auth_header(seed["users"]["admin"])
    )
    assert resp.status_code == 200
    assert resp.json()["mirrors"] == expected


async def test_archive_inventory_endpoint_survives_a_non_utf8_directory_name(
    client, seed, db_session, tmp_path
):
    """F3, end to end: the HTTP-level test the builder-only tests above
    cannot stand in for -- json.dumps runs at the FastAPI response layer,
    not in build_mirror_inventory, so this is the layer that actually used
    to 500.
    """
    root = tmp_path / "freebsd"
    releases = root / "releases"
    bad_name = os.fsdecode(b"\xff\xfe")
    _touch_dir(releases / bad_name / "14.3-RELEASE")

    seed["mirror"].local_path = str(root)
    db_session.commit()

    resp = await client.get(
        "/api/admin/archive-inventory", headers=auth_header(seed["users"]["readonly"])
    )
    assert resp.status_code == 200
    body = resp.json()
    freebsd = next(m for m in body["mirrors"] if m["mirror_type"] == "freebsd")
    assert freebsd["available"] is True
    locations = freebsd["releases"][0]["locations"]
    assert any(r"\xff\xfe" in loc for loc in locations), locations


async def test_archive_inventory_endpoint_survives_a_non_utf8_mode_000_directory_and_recovers_after_ttl(
    client, seed, db_session, tmp_path, monkeypatch
):
    """F1/F3, the exact reported bug, end to end: a non-UTF-8 directory
    that ALSO fails to open (mode 000) put a lone surrogate into `errors`
    (via the OSError's own message, not just a location path), which then
    raised UnicodeEncodeError at the JSONResponse layer for ALL THREE
    mirrors, and the 60s cache then served that same 500 to every caller
    until the TTL expired. The suite runs as a non-root user, so mode 000
    really is unreadable. A second request after the TTL must ALSO
    succeed -- proving the fix rescans cleanly, not just that one lucky
    scan happened to get cached before anything went wrong.
    """
    root = tmp_path / "freebsd"
    releases = root / "releases"
    bad_name = os.fsdecode(b"\xff\xfe-blocked")
    blocked = releases / bad_name
    _touch_dir(blocked)
    _add_freebsd_release(releases, "14.4")
    os.chmod(blocked, 0o000)

    seed["mirror"].local_path = str(root)
    db_session.commit()

    archive_inventory.reset_cache()
    fake_now = [1_000.0]
    monkeypatch.setattr(archive_inventory.time, "monotonic", lambda: fake_now[0])

    try:
        resp = await client.get(
            "/api/admin/archive-inventory", headers=auth_header(seed["users"]["readonly"])
        )
        assert resp.status_code == 200
        freebsd = next(m for m in resp.json()["mirrors"] if m["mirror_type"] == "freebsd")
        assert freebsd["available"] is True
        assert any(g["line"] == "14.4" for g in freebsd["releases"])

        fake_now[0] += archive_inventory.CACHE_TTL_SECONDS + 1  # past the TTL
        resp2 = await client.get(
            "/api/admin/archive-inventory", headers=auth_header(seed["users"]["readonly"])
        )
        assert resp2.status_code == 200
    finally:
        os.chmod(blocked, 0o755)  # tmp_path cleanup needs this back


@pytest.mark.parametrize("method", ["post", "patch", "delete", "put"])
async def test_archive_inventory_has_no_write_path(client, seed, method):
    resp = await getattr(client, method)(
        "/api/admin/archive-inventory", headers=auth_header(seed["users"]["admin"])
    )
    assert resp.status_code == 405
