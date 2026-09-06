"""Paths that survive `--delete` even after upstream stops carrying them.

THE PROBLEM
-----------
run_rsync (sync_service.py) passes `--delete --delete-delay` on every sync, so
the mirror is a faithful copy of upstream -- including faithfully removing a
release the day upstream prunes it. OpenBSD supports "current + previous";
when 46.4.100.234 was inspected on 2026-09-06, `pub/OpenBSD/` still held 7.5
through 7.9, and only 7.8/7.9 are the supported pair. 7.5-7.7 (~1.18 TB) are
already EOL and are one upstream housekeeping pass away from vanishing from
this mirror too, with nothing left afterwards but a `files_deleted` count on a
job row.

THE MECHANISM (verified against real rsync, not the manpage alone)
--------------------------------------------------------------------
rsync's protect filter, `-f "P <pattern>"`, removes a path from delete
eligibility on the *receiving* side without excluding it from the transfer:

    protected dir still receives updates       changed files still update
    new files inside it still arrive           an addition upstream still adds
    upstream deleting inside it does nothing   the local copy keeps the file

That was confirmed twice: once by hand in a container before this file
existed, and again while writing sync/protected_paths.py, against a source
tree that gets a file changed (different size *and* mtime -- rsync's default
quick-check is size+mtime, and two 3-byte files written in the same second
will falsely look unchanged either way, which is what produced a wrong
conclusion the first time this was tried), a file added, and a file removed,
diffed against an unprotected sibling that behaves normally. See
tests/test_protected_paths.py for the automated version of that same proof,
including the `**` cross-directory case FreeBSD needs (below).

One real gap, also found empirically rather than assumed: `P name/***`
protects a *directory* and everything under it, but does not protect a bare
symlink named `name` -- `P name` (no `/***`) is what protects a symlink (or
any other single leaf entry). Where that matters, both forms are listed; see
FreeBSD below.

WHY THIS LIST IS DATA, AND WHY IT LIVES HERE RATHER THAN IN
shared/settings_spec.py
--------------------------------------------------------------------------
settings_spec.py validates *operator-editable, database-backed* values: a
row in `settings`, written through PATCH /api/admin/settings or by hand, read
back and re-validated by the sync service on every reload. Nothing about that
fits this data:

  * It is structured (per-mirror lists of filter patterns), not one scalar
    per row, and settings_spec's parse/render contract is str -> scalar ->
    str.
  * There is no write path for it in this change -- adding one means an
    admin.js and admin.py surface, which belongs to `developer` too, but is a
    separate, larger decision (validating an arbitrary path-prefix list
    against a live filesystem is a different shape of problem than validating
    a cron string) and is not needed to fix the bug at hand.
  * Above all, "visible and reviewable" was the actual requirement, and nothing
    is more reviewable than a diff against a plain Python literal: a name, a
    date, a reason, right next to the value, checked in like every other
    change to this repo.

This mirrors how the three upstream URLs and the three default local paths
already live as plain constants (SyncConfig in sync_service.py,
default_mirrors in backend/app/main.py) rather than as settings rows --
"which mirror looks like what" has always been static, seeded configuration
here, not a live-editable value, and protection lists are the same kind of
fact.

Keyed by MirrorType rather than by Mirror.name: name is a display string with
no uniqueness enforced by type, mirror_type is the immutable column the seed
data and this dict both key off (PATCH /api/admin/settings' MirrorUpdateRequest
allows changing `enabled` and `upstream_url` only -- never name or
mirror_type).

TO PROTECT A NEW PATH: add the pattern below, in the block for that mirror,
with a one-line reason and a date. To stop protecting one (because it was
finally, deliberately deleted), remove the line -- do not comment it out and
leave it silently inert.

WHY THE NEWEST RELEASE ON EACH MIRROR IS DELIBERATELY *NOT* HERE
-----------------------------------------------------------------
Protecting a release that is still in service is arguably worse than the bug
this file exists to fix. A protect filter only ever matters when upstream has
removed something; for a frozen EOL tree that is always a prune we want to
survive, but for the release still being actively served, upstream can also
remove a single file on purpose -- a pulled package, a re-spun ISO with a
build fix, a security erratum replacing content in place -- and faithfully
propagating that is the correct behaviour, not a bug. So "newest" is excluded
per mirror (OpenBSD/NetBSD have one active line; FreeBSD, see below, has two),
using version order, not mtime: an older release can easily have the more
recent mtime because of ordinary maintenance on it, which is not the same
thing as it still being the actively-served head of a line. Concretely here:
NetBSD-9.5's directory was touched today (2026-09-06) and NetBSD-11.0 (final)
was not touched since 2026-08-23, and NetBSD-9.5 is still the one that is
correctly protected -- 11.0 is newer by release order regardless of which
directory rsync last wrote to.
"""
from typing import Dict, List, Optional, Tuple

from shared.models import MirrorType

PROTECTED_PATHS: Dict[MirrorType, Tuple[str, ...]] = {
    # --- OpenBSD: pub/OpenBSD/ -----------------------------------------
    # Flat, one real directory per release (confirmed on the server: no
    # symlinks under pub/OpenBSD/), so one pattern each is enough.
    #
    # 7.9 is the current release and 7.8 is "previous" -- both still
    # officially supported -- and are left mirroring faithfully. 7.5-7.7 are
    # already EOL per the project's own support policy and survive only
    # because upstream has not pruned them yet.
    MirrorType.OPENBSD: (
        "/7.5/***",
        "/7.6/***",
        "/7.7/***",
        "/7.8/***",
        # /7.9/*** deliberately absent -- current release, see module note.
    ),
    # --- NetBSD: pub/NetBSD/ --------------------------------------------
    # Same shape as OpenBSD: flat, one real directory per release, confirmed
    # on the server.
    #
    # NetBSD-11.0 is the newest (final supersedes the RC7 snapshot below it)
    # and is left mirroring faithfully. NetBSD-11.0_RC7 is not "current" by
    # the same reasoning that excludes 11.0: it was superseded the moment
    # 11.0 shipped and receives no further legitimate changes, so protecting
    # it costs nothing and only removes deletion risk once upstream tidies
    # pre-release snapshots away.
    MirrorType.NETBSD: (
        "/NetBSD-7.2/***",
        "/NetBSD-8.3/***",
        "/NetBSD-9.0/***",
        "/NetBSD-9.5/***",
        "/NetBSD-10.0/***",
        "/NetBSD-10.1/***",
        "/NetBSD-11.0_RC7/***",
        # /NetBSD-11.0/*** deliberately absent -- current release.
    ),
    # --- FreeBSD: pub/FreeBSD/, releases/ only ---------------------------
    #
    # Inspected on the server (read-only) rather than assumed, because it is
    # nothing like the other two. `releases/` is arch-first, not
    # version-first, and the same release exists in up to three different
    # shapes at once:
    #
    #   releases/<arch>/<V>                     symlink -> <subarch>/<V>
    #   releases/<arch>/<subarch>/<V>/...        the real content
    #   releases/{VM,CI,OCI,PKGBASE-REPOS...}/<V>/...   per-version artefacts,
    #                                            named <V> at the top of each
    #                                            of those trees directly
    #   releases/ISO-IMAGES/<major.minor>/...    ISOs, grouped by short
    #                                            version (e.g. "14.3", not
    #                                            "14.3-RELEASE"); nested per
    #                                            arch instead of shared for
    #                                            some architectures (e.g.
    #                                            releases/riscv/riscv64/ISO-IMAGES/14.3)
    #
    # <arch> and <subarch> also disagree with each other by architecture:
    # amd64 and i386 double-nest under a same-named subarch (amd64/amd64/...),
    # arm64 and riscv double-nest under a differently-named one
    # (arm64/aarch64/..., riscv/riscv64/...), and powerpc has no top-level
    # symlink layer at all -- version directories sit directly under
    # releases/powerpc/, alongside separate powerpc64/powerpc64le/powerpcspe
    # subarch trees. A hand-enumerated path list would need one entry per
    # (architecture, artefact tree) pair and would silently miss whichever
    # combination was not checked; several of the above were only found by
    # listing the real directories.
    #
    # So the protected *unit* here is a version string, matched wherever it
    # occurs with rsync's `**` (matches any number of path elements,
    # including none), not a hand-built list of paths:
    #
    #   "**/<V>"        bare -- protects a symlink literally named <V>
    #                   (P with a trailing /*** does not protect a bare
    #                   symlink; see the module docstring). Redundant and
    #                   harmless against a same-named real directory, which
    #                   the next pattern already covers.
    #   "**/<V>/***"    protects a directory literally named <V> and every
    #                   file under it, at whatever depth it is found.
    #
    # Verified against a synthetic tree shaped like this one --
    # tests/test_protected_paths.py -- including that "**" matches both
    # releases/amd64/amd64/<V> (two segments deep) and a shallower
    # releases/<other-arch>/<V> in the same run.
    #
    # Versions protected: 14.3-RELEASE, 14.4-RELEASE, 15.0-RELEASE. Excluded,
    # deliberately:
    #
    #   14.5-RELEASE and 15.1-RELEASE -- FreeBSD supports two branches at
    #   once (14.x and 15.x were both current when this was written), so
    #   there are two "newest" releases here, not one. 14.5-RELEASE actually
    #   has the most recent mtime of everything on this mirror (it shipped
    #   days before this file was written) despite belonging to the *older*
    #   branch -- more evidence for the module note above that "newest" has
    #   to mean release order, not mtime.
    #   14.5-BETA1/BETA2/BETA3/14.5-RC1 -- pre-release snapshots of the
    #   branch above, not releases the operator asked to keep; their normal
    #   lifecycle (replaced, cleaned up once the final ships) is exactly the
    #   upstream housekeeping that faithful mirroring should keep following.
    MirrorType.FREEBSD: (
        "**/14.3-RELEASE",
        "**/14.3-RELEASE/***",
        "**/ISO-IMAGES/14.3/***",
        "**/14.4-RELEASE",
        "**/14.4-RELEASE/***",
        "**/ISO-IMAGES/14.4/***",
        "**/15.0-RELEASE",
        "**/15.0-RELEASE/***",
        "**/ISO-IMAGES/15.0/***",
    ),
}


def protect_filter_args(mirror_type: Optional[MirrorType]) -> List[str]:
    """The `-f`/pattern argv pairs for mirror_type's protected paths.

    Returns [] for `None` or for a MirrorType with nothing configured --
    exactly what run_rsync already builds without this feature, so a mirror
    with no protected paths keeps mirroring exactly as faithfully as before.
    Order does not matter: every rule here is the same action (protect) over
    disjoint patterns, so nothing depends on which is listed first.
    """
    if mirror_type is None:
        return []
    args: List[str] = []
    for pattern in PROTECTED_PATHS.get(mirror_type, ()):
        args.extend(["-f", f"P {pattern}"])
    return args
