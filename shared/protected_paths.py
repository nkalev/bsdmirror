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
existed, and again while writing this module, against a source tree that gets
a file changed (different size *and* mtime -- rsync's default quick-check is
size+mtime, and two 3-byte files written in the same second will falsely look
unchanged either way, which is what produced a wrong conclusion the first
time this was tried), a file added, and a file removed, diffed against an
unprotected sibling that behaves normally. See tests/test_protected_paths.py
for the automated version of that same proof, including the `**`
cross-directory case FreeBSD needs (below).

One real gap, also found empirically rather than assumed: `P name/***`
protects a *directory* and everything under it, but does not protect a bare
symlink named `name` -- `P name` (no `/***`) is what protects a symlink (or
any other single leaf entry). Where that matters, both forms are listed; see
FreeBSD below.

WHY THIS FILE IS IN shared/, NOT sync/
--------------------------------------------------------------------------
This started as sync/protected_paths.py: sync_service.py was its only
consumer, and it lived next to the module that reads it. That stopped being
true the moment the admin panel grew a read-only Protected Paths page
(`GET /api/admin/protected-paths`) -- the backend needed PROTECTED_PATHS too,
and `from sync.protected_paths import PROTECTED_PATHS` does not work there:
backend/Dockerfile COPYs only `backend/` and `shared/`, so `sync/` is not
part of that image in any environment, and a module-level import of it would
raise ModuleNotFoundError before the app finished starting.

The first fix was a hand-kept, byte-for-byte copy at
backend/app/core/protected_paths.py, with a test asserting the two dicts
stayed equal. That is the exact shape of bug shared/models/ already exists to
prevent for the ORM tables -- two declarations, kept honest only by a test
that can catch drift after it happens, not prevent it -- and that one drifted
seventeen ways before it was merged into one definition. A passing drift test
is not the same guarantee as a single definition; it is a rake that has not
been stepped on yet.

So this data lives here instead, the one place both images actually ship
(see shared/__init__.py: both Dockerfiles COPY shared/ into their WORKDIR,
preserving the package name, so `import shared.protected_paths` resolves the
same way in both). sync/sync_service.py imports `protect_filter_args` from
here directly, the same way it already imports `shared.models` and
`shared.settings_spec` -- no re-export, no try/except, and nothing left to
drift because there is only the one copy.

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

CURRENT_RELEASES, AND WHY IT IS DATA TOO, NOT A COMPUTED PROPERTY
-----------------------------------------------------------------
backend/app/core/archive_inventory.py used to infer "is this still served"
from version order alone: the highest release within a major line. That is
wrong the moment a new major ships. Once OpenBSD 8.0 exists, 7.9 is still --
and forever will be -- "the latest release in major 7" by that arithmetic,
even though it is no longer current, is not in PROTECTED_PATHS above, and is
one upstream prune away from vanishing with nothing left to show it existed.
An unprotected FreeBSD 13.5-RELEASE (major 13, long since superseded) is
hidden the same way: it is trivially "the latest in major 13" because
nothing else in that major exists any more. Version arithmetic cannot know
FreeBSD's 13.x line ended; only a human who read the release announcement
can, which is exactly why this is a second, explicit, reviewed list rather
than something derived from the first.

A name here must never also appear as a protected pattern's subject --
test_current_releases_are_never_protected (tests/test_protected_paths.py)
checks that on every run. A still-served release is exactly the one thing
the "WHY THE NEWEST RELEASE ... IS DELIBERATELY NOT HERE" section above
already says must keep mirroring faithfully, protected or not; the two
lists are meant to be non-overlapping -- never both naming the same release
-- not to jointly cover every release this project has ever shipped. An
old release that is neither protected nor current (an EOL line nobody has
gotten around to adding to PROTECTED_PATHS yet) is not a contradiction of
that rule; it is exactly the gap archive_inventory.py's `at_risk` exists to
surface.

THE UPGRADE PROCEDURE: when upstream ships a new release, in the same
change:
  1. Add the release CURRENT_RELEASES currently names for that mirror (or,
     for FreeBSD, the branch the new one supersedes) to PROTECTED_PATHS
     above -- it is now EOL and needs the same protection every other
     retired release gets -- with a one-line reason and today's date, like
     every other entry there.
  2. Replace that name in CURRENT_RELEASES below with the new one.
Doing only step 2 first is fine and self-correcting: the outgoing release is
briefly neither current nor protected, and archive_inventory.py's `at_risk`
rule (see that module) will correctly, loudly flag it until step 1 catches
up -- that is the mechanism working, not a bug to route around by reordering
the steps.
"""
from typing import Dict, List, Optional, Tuple

from shared.models import MirrorType

PROTECTED_PATHS: Dict[MirrorType, Tuple[str, ...]] = {
    # --- OpenBSD: pub/OpenBSD/ -----------------------------------------
    # Flat, one real directory per release (confirmed on the server: no
    # symlinks under pub/OpenBSD/), so one pattern each is enough.
    #
    # 7.9 is the current release and is deliberately left unprotected here
    # (see the "WHY THE NEWEST RELEASE ... IS DELIBERATELY NOT HERE" section
    # above) -- it is in CURRENT_RELEASES below instead. 7.5-7.8 are all
    # protected: 7.8 was OpenBSD's "previous" officially-supported release
    # when this list was written, and 7.5-7.7 are already EOL per the
    # project's own support policy, but upstream has not pruned any of the
    # four yet -- protecting all of them means none silently vanishes
    # whenever that prune happens, regardless of which of them still
    # happened to be inside the support window at the time.
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


# See "CURRENT_RELEASES, AND WHY IT IS DATA TOO" above for what this is and
# the upgrade procedure for keeping it correct. Every value here must be
# ABSENT from PROTECTED_PATHS -- a current release is never also listed as
# protected -- checked by test_current_releases_are_never_protected.
CURRENT_RELEASES: Dict[MirrorType, Tuple[str, ...]] = {
    MirrorType.OPENBSD: ("7.9",),
    MirrorType.NETBSD: ("NetBSD-11.0",),
    # FreeBSD supports two branches at once -- see PROTECTED_PATHS above.
    MirrorType.FREEBSD: ("14.5-RELEASE", "15.1-RELEASE"),
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
