"""
Archive inventory: what each mirror actually has on disk, and whether
shared/protected_paths.py would keep it the day upstream prunes it.

GET /api/admin/protected-paths (app.core.protected_paths_view) shows the raw
rsync `-f "P ..."` patterns, but a pattern is not a release: nobody can read
"/7.8/***" and "**/14.3-RELEASE/***" against a live tree and tell which
actual directories on disk are covered, which older releases would silently
vanish on the next upstream prune, or whether a pattern still matches
anything at all. This module is that read: a bounded, hardened filesystem
scan per mirror, classified against the real PROTECTED_PATHS and
CURRENT_RELEASES dicts, so the operator can decide an archive policy (e.g.
"keep the latest minor of every major") with the actual inventory in front
of them instead of the pattern list alone.

WHY EVERY SCANNING FUNCTION TAKES `root` AS A PLAIN ARGUMENT
--------------------------------------------------------------------------
Nothing here imports settings.MIRROR_DATA_PATH or queries a Mirror row
directly except read_archive_inventory, the one function that has to. Every
other function takes `root: Path` (or a Location relative to one) so a test
can point it at a tmp_path tree shaped like production instead of at
`/data/mirrors` -- which is read-only in every environment and does not
exist at all outside the production host.

PROTECTION IS COMPUTED, NEVER GUESSED
--------------------------------------------------------------------------
compile_pattern() recognises exactly the three `-f "P ..."` shapes
shared/protected_paths.py currently uses (see that module's docstring for
what each means to rsync): an anchored `/NAME/***`, a bare `**/NAME`, and a
`**/SEG[/SEG...]/***` matched at any depth by its own trailing segments. A
pattern that is not one of those three -- including one using an rsync
wildcard (`?`, `[`, `\\`) this parser does not model as anything other than
a literal name -- raises UnknownPatternError, and build_mirror_inventory
turns that into `protection: "unknown"` for every release on that mirror,
never a guess computed from whatever patterns did parse.

ENTRY TYPE IS PART OF COVERAGE, NOT JUST PATH
--------------------------------------------------------------------------
A location's path matching a pattern is necessary but not sufficient. rsync
draws a hard line at whether the matched entry is a directory: `NAME/***`
protects a directory and everything under it, but a same-named symlink is a
different kind of filesystem entry and is not covered by it; bare `NAME` is
the reverse -- it protects a symlink (or any other non-directory leaf) but,
checked against the real binary in the archive-inventory / real-rsync
cross-check in tests/test_protected_paths.py, does not stop `--delete` from
removing a file that vanishes from *inside* a same-named directory it also
happens to match. This module treats that as not protected at all: a
release whose contents keep disappearing one file at a time is not
meaningfully "kept" no matter how the classifier labels it. See
pattern_matches() and Location.

CURRENT VS NEWEST VS LATEST_IN_MAJOR
--------------------------------------------------------------------------
`newest` and `latest_in_major` are computed from parsed (major, minor)
tuples and are informational only. Neither is a safe stand-in for "upstream
still serves this": the day a new major ships, the previous major's last
release is `latest_in_major` forever, whether or not it is still current.
`current` instead comes from shared.protected_paths.CURRENT_RELEASES -- an
explicit, human-maintained list, for the same reason PROTECTED_PATHS is one
-- and is what `at_risk` actually keys off. See that module's own docstring
for the full reasoning and the upgrade procedure that keeps the list
correct.

NEVER FOLLOW A SYMLINK, AND NEVER TRUST A DIRECTORY'S TYPE TWICE
--------------------------------------------------------------------------
Every directory this module ever descends into is opened with `O_NOFOLLOW`,
never by reopening a path string a second time on the strength of an
earlier check: the FreeBSD walk opens every subdirectory via a directory
file descriptor (`os.open(name, O_DIRECTORY | O_NOFOLLOW, dir_fd=parent)`),
`releases` itself is opened the same way (after an `lstat` that exists only
to give a symlink there its own clear error message, not as the actual
defence), and the OpenBSD/NetBSD roots are opened the same way too -- a
mirror root that is itself a symlink is refused, not walked, on all three
mirror types. A directory swapped for a symlink between being listed and
being opened is refused (`ELOOP`) rather than silently followed, on every
level, not just the top one. A symlink is never descended into, matched or
not, which is also what makes a symlink loop harmless: this walk never
opens what a symlink points to, so it cannot loop through one. Every
location's mtime is captured from the same already-open directory entry
during the walk (`entry.stat(follow_symlinks=False)`), never re-resolved
from `root` afterward by reconstructing and reopening a path string, which
would mean trusting every intermediate segment a second time long after the
walk that already checked them has finished.

NON-UTF-8 NAMES ARE DISPLAYED, NEVER USED FOR MATCHING
--------------------------------------------------------------------------
rsync copies filename bytes verbatim; nothing upstream promises a directory
name is valid UTF-8. os.scandir hands such a name back as a `str` containing
lone surrogates (Python's usual surrogateescape round-trip), which is valid
Python text but not valid UTF-8. A plain `json.dumps(...)` call does not
raise on it -- the default `ensure_ascii=True` backslash-escapes it into
plain ASCII, which then encodes to UTF-8 bytes without incident. Starlette's
JSONResponse, which is what actually serialises this endpoint's body, calls
`json.dumps(..., ensure_ascii=False)` for compactness and then
`.encode("utf-8")`s the result -- and *that* raises UnicodeEncodeError on a
lone surrogate, which used to take down every mirror's inventory over one
bad name anywhere in the tree, an unhandled 500 that the 60s cache then
served to every caller until the TTL expired. A test that checks
`json.dumps(result)` alone, without `ensure_ascii=False` and an explicit
`.encode("utf-8")`, does not exercise this failure mode at all -- see
tests/test_archive_inventory.py's non-UTF-8 tests. _display_name() reverses
the surrogateescape encoding and re-decodes as UTF-8 with `backslashreplace`,
producing a `\\xNN`-escaped, always-encodable string for display; every
scanning function builds its labels and paths this way. `build_mirror_
inventory` also runs the whole per-mirror result through `_sanitize_for_json`
-- a recursive, defence-in-depth pass over every string in the response --
before returning it, and `get_archive_inventory_view` independently confirms
`json.dumps(result, ensure_ascii=False).encode("utf-8")` succeeds before
caching anything, so a spot this module's call sites missed cannot leave a
500-producing result cached for the TTL either. Matching, grouping and
filesystem access always use the original, un-sanitised name -- see
Location.

BLOCKING I/O AND CACHING
--------------------------------------------------------------------------
Every scan_* function and build_mirror_inventory do real, synchronous
filesystem I/O (os.scandir, os.lstat, os.open) and must never be awaited
directly. read_archive_inventory is the single blocking entry point that
touches every configured mirror's filesystem; get_archive_inventory_view is
what admin.py calls, offloading it via asyncio.to_thread the same way
app.core.disk and app.core.health_status already do.
tests/test_async_hygiene.py knows read_archive_inventory's name for the same
reason it already knows read_disk_usage's and read_health_status_document's.

Because any authenticated role can call the endpoint this backs, and a scan
is a bounded but real directory walk, get_archive_inventory_view caches the
whole result for CACHE_TTL_SECONDS behind a single asyncio.Lock: concurrent
callers during a cold cache share one scan rather than one each, and a
request inside the TTL costs nothing. The cache is process-wide and keyed on
nothing -- deliberately: the mirror list changes on the order of "someone
edited docker-compose", not per-request, so staleness for up to the TTL is
an acceptable trade against not scanning a slow-changing filesystem tree on
every poll. reset_cache() exists for tests.
"""
import asyncio
import errno
import itertools
import json
import os
import re
import stat
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

import structlog

from shared.models import Mirror, MirrorType
from shared.protected_paths import CURRENT_RELEASES, PROTECTED_PATHS

logger = structlog.get_logger(__name__)

# "A find to depth 4 under releases/ visits 1,103 entries in about 5 ms" (the
# real production count). 20,000 is headroom over that, not a ceiling tuned
# to today's tree -- applied uniformly to all three mirrors (see
# _read_capped): OpenBSD/NetBSD had no cap at all before this constant was
# extended to them.
MAX_ENTRIES_VISITED = 20_000

# releases/amd64/amd64/ISO-IMAGES/14.3 is the deepest real path this module
# has to find -- 4 segments below releases/ itself.
MAX_WALK_DEPTH = 4

# Real FreeBSD locations per version top out at ~20 today. 50 is
# response-size headroom, not a measured ceiling.
MAX_LOCATIONS_PER_VERSION = 50

# Untrusted, upstream-controlled lists (a scan error message can embed an
# attacker/upstream-chosen path; an unclassified name is by definition
# something this module did not expect) get the same "cap the response
# size" treatment as everything else untrusted in this codebase.
MAX_ERRORS_PER_MIRROR = 20
MAX_UNCLASSIFIED_PER_MIRROR = 50

CACHE_TTL_SECONDS = 60


class Location(NamedTuple):
    """One release path, relative to the mirror root (Mirror.local_path).

    `is_dir` is from lstat -- never resolved through a symlink -- because
    coverage depends on it: see pattern_matches().
    """

    segments: Tuple[str, ...]
    is_dir: bool


class ScanResult(NamedTuple):
    groups: List[dict]
    truncated: bool
    errors: List[str]
    unclassified: List[str]
    # Location -> mtime, captured from the already-open directory entry
    # during the walk itself -- see the module docstring's "NEVER TRUST A
    # DIRECTORY'S TYPE TWICE" section. Absent entries (a stat() that failed
    # during the walk) simply have no mtime; _newest_mtime treats that the
    # same as any other unknown mtime.
    mtimes: Dict[Location, float]
    # FreeBSD only: True if a non-matched, real (non-symlink) directory at
    # MAX_WALK_DEPTH had at least one subdirectory of its own that this walk
    # therefore never visited -- see scan_freebsd_releases and
    # build_mirror_inventory's `incomplete`. Always False for OpenBSD/NetBSD,
    # whose flat scan has no depth limit to hit.
    depth_limited: bool = False


def _display_name(raw: str) -> str:
    """A filesystem name (or a string that may embed one, such as an OSError
    message), made safe to put in a JSON response body.

    See the module docstring's "NON-UTF-8 NAMES" section. Never use this for
    anything that is about to touch the filesystem or a dict key derived
    from a real path -- it is one-way and does not round-trip.
    """
    return os.fsencode(raw).decode("utf-8", "backslashreplace")


def _display_segments(segments: Sequence[str]) -> str:
    """Every raw path segment, joined and made display-safe -- the same
    treatment `_display_path` gives a Location, for the places (an error
    label built from the walk's own `rel` tuple) that only have the raw
    segments, not a Location. Never build a label by joining raw segments
    and escaping only the last one; a non-UTF-8 ancestor directory name is
    just as untrusted as the leaf.
    """
    return "/".join(_display_name(s) for s in segments)


def _display_path(location: Location) -> str:
    return _display_segments(location.segments)


def _sanitize_for_json(value):
    """Recursively pass every `str` through `_display_name` -- a
    defence-in-depth pass over the entire built result, run once at the end
    of build_mirror_inventory, so a non-UTF-8 name that reached some string
    in the response WITHOUT going through `_display_name`/`_display_path`
    or `_display_segments` at its point of construction still cannot reach
    json.dumps un-sanitised. `_display_name` is idempotent on a string that
    is already display-safe (plain ASCII round-trips through
    fsencode/decode unchanged), so re-applying it here to strings built
    correctly the first time is a safe no-op, not a double-mangling.
    """
    if isinstance(value, str):
        return _display_name(value)
    if isinstance(value, dict):
        return {
            (_display_name(k) if isinstance(k, str) else k): _sanitize_for_json(v)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_for_json(v) for v in value]
    return value


def _record_capped(items: List[str], value: str, cap: int) -> None:
    if len(items) < cap:
        items.append(value)


# ---------------------------------------------------------------------------
# Release-name detection
#
# `re.fullmatch` (never `re.match` + a trailing `$`, which -- without
# re.MULTILINE -- still matches just before a trailing newline, not only at
# the true end of the string) and `[0-9]` (never `\d`, which matches any
# Unicode decimal digit, not only ASCII 0-9) throughout: both were real gaps
# an upstream-controlled name could exploit to slip past these checks.
# ---------------------------------------------------------------------------

_OPENBSD_RELEASE_RE = re.compile(r"(?P<major>[0-9]+)\.(?P<minor>[0-9]+)")

_NETBSD_RELEASE_RE = re.compile(
    r"NetBSD-(?P<major>[0-9]+)\.(?P<minor>[0-9]+)(?:_(?P<pre>(?:RC|BETA|ALPHA)[0-9]*))?"
)

_FREEBSD_RELEASE_RE = re.compile(
    r"(?P<major>[0-9]+)\.(?P<minor>[0-9]+)-(?P<label>RELEASE|BETA[0-9]*|RC[0-9]*|ALPHA[0-9]*)"
)
# X.Y directly under a directory named ISO-IMAGES -- no RELEASE/BETA/RC
# suffix of its own, so it is only ever grouped with the FINAL release of
# its line (see scan_freebsd_releases).
_FREEBSD_ISO_SHORT_RE = re.compile(r"(?P<major>[0-9]+)\.(?P<minor>[0-9]+)")


def is_final_release_name(mirror_type: MirrorType, name: str) -> bool:
    """Does `name` look like a FINAL release directory name for
    `mirror_type` -- the same shape scan_*_releases groups under
    kind == "release" (a plain OpenBSD/NetBSD release, or a FreeBSD name
    whose label is exactly RELEASE, never BETA/RC/ALPHA)?

    Not used by the scan itself -- each scan_*_releases function already
    encodes this directly against the entry it is looking at. Exposed so
    shared/protected_paths.py's CURRENT_RELEASES can be validated against
    it: see tests/test_protected_paths.py's
    test_every_current_release_matches_its_mirrors_final_release_shape,
    which fails CI the day CURRENT_RELEASES gains an entry that is not
    actually a final release name for its mirror (a pre-release, a typo, or
    a value copied from the wrong mirror's block).
    """
    if mirror_type == MirrorType.OPENBSD:
        return bool(_OPENBSD_RELEASE_RE.fullmatch(name))
    if mirror_type == MirrorType.NETBSD:
        m = _NETBSD_RELEASE_RE.fullmatch(name)
        return bool(m) and not m.group("pre")
    if mirror_type == MirrorType.FREEBSD:
        m = _FREEBSD_RELEASE_RE.fullmatch(name)
        return bool(m) and m.group("label") == "RELEASE"
    return False


def _looks_unclassified_openbsd(name: str) -> bool:
    return bool(name) and name[0].isdigit()


def _looks_unclassified_netbsd(name: str) -> bool:
    return name.startswith("NetBSD-")


def _looks_unclassified_freebsd(name: str) -> bool:
    return bool(name) and name[0].isdigit() and ("-" in name or "." in name)


def _read_capped(scandir_iterable, remaining: int) -> List:
    """At most `remaining + 1` entries, sorted by name.

    The "+1" is enough to tell "there were more than the remaining budget"
    (so the caller can set `truncated`) without reading -- or sorting -- a
    pathologically large directory in full first. Reading the whole
    directory and checking the cap only afterwards (the previous shape of
    this code) let the cap bound the *report* without bounding the *work*.
    """
    return sorted(itertools.islice(scandir_iterable, remaining + 1), key=lambda e: e.name)


def _is_fd_exhaustion(exc: OSError) -> bool:
    """EMFILE (this process's fd table is full) or ENFILE (the system-wide
    table is full) -- see MAX_WALK_DEPTH's fd-budget note. Both mean the
    scan could not see everything it should have, which build_mirror_
    inventory needs to treat as an incomplete result (`truncated`), not a
    single skipped entry (an ordinary `errors` addition, which is all any
    other OSError here gets)."""
    return exc.errno in (errno.EMFILE, errno.ENFILE)


def scan_openbsd_releases(root: Path, max_entries: int = MAX_ENTRIES_VISITED) -> ScanResult:
    """Direct children of `root` matching X.Y.

    Flat, one real directory per release in practice, but `is_dir` is
    checked with `follow_symlinks=False` and a matching symlink is recorded
    as a location too (never as a followed directory) -- a same-named,
    possibly self-looping symlink must never reach a syscall that would
    resolve it. `root` itself is opened with O_NOFOLLOW: a *symlinked* root
    is refused (raises OSError, which build_mirror_inventory turns into
    `available: false`) rather than walked.
    """
    groups: List[dict] = []
    errors: List[str] = []
    unclassified: List[str] = []
    mtimes: Dict[Location, float] = {}

    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with os.scandir(root_fd) as it:
            entries = _read_capped(it, max_entries)
    finally:
        os.close(root_fd)
    truncated = len(entries) > max_entries
    entries = entries[:max_entries]

    for entry in entries:
        try:
            is_symlink = entry.is_symlink()
            is_real_dir = False if is_symlink else entry.is_dir(follow_symlinks=False)
        except OSError as exc:
            _record_capped(
                errors,
                f"{_display_name(entry.name)}: {_display_name(str(exc))}",
                MAX_ERRORS_PER_MIRROR,
            )
            continue
        if not is_symlink and not is_real_dir:
            continue  # a plain file

        m = _OPENBSD_RELEASE_RE.fullmatch(entry.name)
        if not m:
            if _looks_unclassified_openbsd(entry.name):
                _record_capped(unclassified, _display_name(entry.name), MAX_UNCLASSIFIED_PER_MIRROR)
            continue

        line = f"{m.group('major')}.{m.group('minor')}"
        location = Location((entry.name,), is_real_dir)
        try:
            mtimes[location] = entry.stat(follow_symlinks=False).st_mtime
        except OSError:
            pass
        groups.append(
            {
                "version": entry.name,
                "line": line,
                "kind": "release",
                "locations": [location],
            }
        )
    return ScanResult(groups, truncated, errors, unclassified, mtimes)


def scan_netbsd_releases(root: Path, max_entries: int = MAX_ENTRIES_VISITED) -> ScanResult:
    """Direct children of `root` matching NetBSD-X.Y[_RC/BETA/ALPHAn].

    Same shape, and the same symlink handling (including the O_NOFOLLOW
    root open), as scan_openbsd_releases.
    """
    groups: List[dict] = []
    errors: List[str] = []
    unclassified: List[str] = []
    mtimes: Dict[Location, float] = {}

    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with os.scandir(root_fd) as it:
            entries = _read_capped(it, max_entries)
    finally:
        os.close(root_fd)
    truncated = len(entries) > max_entries
    entries = entries[:max_entries]

    for entry in entries:
        try:
            is_symlink = entry.is_symlink()
            is_real_dir = False if is_symlink else entry.is_dir(follow_symlinks=False)
        except OSError as exc:
            _record_capped(
                errors,
                f"{_display_name(entry.name)}: {_display_name(str(exc))}",
                MAX_ERRORS_PER_MIRROR,
            )
            continue
        if not is_symlink and not is_real_dir:
            continue

        m = _NETBSD_RELEASE_RE.fullmatch(entry.name)
        if not m:
            if _looks_unclassified_netbsd(entry.name):
                _record_capped(unclassified, _display_name(entry.name), MAX_UNCLASSIFIED_PER_MIRROR)
            continue

        line = f"{m.group('major')}.{m.group('minor')}"
        kind = "prerelease" if m.group("pre") else "release"
        location = Location((entry.name,), is_real_dir)
        try:
            mtimes[location] = entry.stat(follow_symlinks=False).st_mtime
        except OSError:
            pass
        groups.append(
            {
                "version": entry.name,
                "line": line,
                "kind": kind,
                "locations": [location],
            }
        )
    return ScanResult(groups, truncated, errors, unclassified, mtimes)


class _FreeBSDWalker:
    """Depth-first walk of releases/ that holds open only the file
    descriptors of the directories on the path from `releases/` down to
    whichever one is currently being scanned -- at most MAX_WALK_DEPTH + 1
    at once, never one per sibling. Each child is opened right before
    `walk()` recurses into it and closed (in a `finally`) the moment that
    call returns, so a directory with thousands of subdirectories costs the
    same handful of open fds a shallow one does -- see scan_freebsd_releases
    and MAX_WALK_DEPTH's own note on the EMFILE bug this replaces.
    """

    def __init__(self, max_entries: int):
        self.max_entries = max_entries
        self.visited = 0
        self.truncated = False
        self.depth_limited = False
        self.groups: Dict[Tuple[str, str], dict] = {}
        self.errors: List[str] = []
        self.unclassified: List[str] = []
        self.mtimes: Dict[Location, float] = {}

    def walk(self, dir_fd: int, rel: Tuple[str, ...]) -> None:
        remaining = self.max_entries - self.visited
        try:
            with os.scandir(dir_fd) as it:
                entries = _read_capped(it, remaining)
        except OSError as exc:
            label = _display_segments(rel) or "releases"
            _record_capped(
                self.errors, f"{label}: {_display_name(str(exc))}", MAX_ERRORS_PER_MIRROR
            )
            if _is_fd_exhaustion(exc):
                self.truncated = True
            return

        if len(entries) > remaining:
            self.truncated = True
        entries = entries[:remaining]

        for entry in entries:
            self.visited += 1
            try:
                is_symlink = entry.is_symlink()
                is_real_dir = False if is_symlink else entry.is_dir(follow_symlinks=False)
            except OSError as exc:
                label = _display_segments((*rel, entry.name))
                _record_capped(
                    self.errors, f"{label}: {_display_name(str(exc))}", MAX_ERRORS_PER_MIRROR
                )
                continue

            if not is_symlink and not is_real_dir:
                continue  # a plain file

            new_rel = (*rel, entry.name)
            location = Location(("releases", *new_rel), is_real_dir)

            release_match = _FREEBSD_RELEASE_RE.fullmatch(entry.name)
            parent_is_iso = bool(rel) and rel[-1] == "ISO-IMAGES"
            iso_match = _FREEBSD_ISO_SHORT_RE.fullmatch(entry.name) if parent_is_iso else None

            if release_match:
                line = f"{release_match.group('major')}.{release_match.group('minor')}"
                if release_match.group("label") == "RELEASE":
                    key, version, kind = ("final", line), f"{line}-RELEASE", "release"
                else:
                    key, version, kind = ("pre", entry.name), entry.name, "prerelease"
                self._record_location(key, version, line, kind, location, entry)
                continue  # never descend into a matched version directory

            if iso_match:
                line = f"{iso_match.group('major')}.{iso_match.group('minor')}"
                self._record_location(
                    ("final", line), f"{line}-RELEASE", line, "release", location, entry
                )
                continue  # matched version directory; do not descend

            if _looks_unclassified_freebsd(entry.name):
                _record_capped(
                    self.unclassified, _display_name(entry.name), MAX_UNCLASSIFIED_PER_MIRROR
                )

            # Not a version match: maybe worth exploring further.
            if is_symlink:
                continue  # never follow a symlink when descending
            if len(new_rel) >= MAX_WALK_DEPTH:
                # A directory this walk, by design, will never look inside
                # (a matched version tree above) never reaches this line at
                # all -- both branches above `continue` first. Only count
                # this as data loss (`depth_limited`) if there was actually
                # something below to miss.
                if is_real_dir and self._has_subdirectory(dir_fd, entry.name):
                    self.depth_limited = True
                continue  # already at the depth cap; do not go deeper
            if self.visited >= self.max_entries:
                self.truncated = True
                continue  # budget exhausted; do not queue more work

            try:
                child_fd = os.open(
                    entry.name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=dir_fd,
                )
            except OSError as exc:
                label = _display_segments(new_rel)
                _record_capped(
                    self.errors, f"{label}: {_display_name(str(exc))}", MAX_ERRORS_PER_MIRROR
                )
                if _is_fd_exhaustion(exc):
                    self.truncated = True
                continue

            try:
                self.walk(child_fd, new_rel)
            finally:
                os.close(child_fd)

    def _record_location(self, key, version, line, kind, location, entry) -> None:
        group = self.groups.setdefault(
            key, {"version": version, "line": line, "kind": kind, "locations": []}
        )
        group["locations"].append(location)
        try:
            self.mtimes[location] = entry.stat(follow_symlinks=False).st_mtime
        except OSError:
            pass

    def _has_subdirectory(self, dir_fd: int, name: str) -> bool:
        """Peeked only for a real, non-matched directory the depth cap is
        about to skip entirely, and closed immediately after -- a transient
        fd, not one more held open for the rest of the walk. An unreadable
        or now-vanished directory here is simply "no signal either way",
        not another error to report: `walk()`'s own next pass over this
        same entry never happens (the cap means there is no next pass), so
        there is nothing to double-report.
        """
        try:
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)
        except OSError:
            return False
        try:
            with os.scandir(fd) as it:
                for child in it:
                    try:
                        if not child.is_symlink() and child.is_dir(follow_symlinks=False):
                            return True
                    except OSError:
                        continue
            return False
        except OSError:
            return False
        finally:
            os.close(fd)


def scan_freebsd_releases(root: Path, max_entries: int = MAX_ENTRIES_VISITED) -> ScanResult:
    """A bounded walk of root/releases/, hardened against a hostile or
    merely racy tree.

    The same release exists at up to ~17 different paths under releases/,
    several architectures deep, some of them convenience symlinks rather
    than real directories -- see shared/protected_paths.py's module
    docstring for the full shape. This walk groups every location for one
    line into a single entry: `14.3-RELEASE` (however many arch trees it is
    found in) and the version-only `ISO-IMAGES/14.3` all fold into ONE
    "14.3-RELEASE" group, while a pre-release keeps its own separate group
    per exact identifier (`14.5-RC1` is not merged with `14.5-RELEASE`).

    Hardening, each exercised in tests/test_archive_inventory.py:

      * `releases` itself is lstat'd before it is opened (for a symlink's
        own clear error message) AND opened with O_NOFOLLOW (the actual
        defence: a symlink written in between is still refused even though
        the lstat a moment earlier said it wasn't one yet).
      * Every subdirectory, all the way down, is opened via `os.open(name,
        O_DIRECTORY | O_NOFOLLOW, dir_fd=parent)`, not by reconstructing
        and reopening a path string, and is opened only right before
        `_FreeBSDWalker.walk()` recurses into it -- never eagerly, while
        still iterating its siblings -- so at most MAX_WALK_DEPTH + 1 fds
        are open at once no matter how many entries one directory has. A
        directory swapped for a symlink between being listed and being
        opened is refused (O_NOFOLLOW) rather than followed.
      * A symlink is never descended into, matched or not, which is also
        what makes a symlink loop harmless: this walk never opens what a
        symlink points to, so it cannot loop through one.
      * `max_entries` bounds total scandir entries examined, not just
        directories found, via `_read_capped` -- a directory full of a
        million plain files trips `truncated` exactly like a million
        subdirectories would, without this walk reading all of them first.
      * A per-entry OSError (a permission error on one subdirectory, a
        removed-mid-scan entry) is recorded in a capped `errors` list and
        that one entry or subtree is skipped -- it is not this mirror's
        problem, only that entry's. EMFILE/ENFILE specifically also set
        `truncated`, since either means the walk could not see everything.
      * Every location's mtime is captured from the same os.DirEntry the
        match was found on (`entry.stat(follow_symlinks=False)`), not
        re-resolved from `root` afterward -- see _newest_mtime.
    """
    releases_path = root / "releases"

    # lstat, not stat: raises the same OSError a missing/unreadable root
    # already would (caught by build_mirror_inventory), but a *symlink*
    # here gets its own explicit message. This is a courtesy message, not
    # the defence -- see the O_NOFOLLOW open below, which is what actually
    # stops a symlink written in the gap after this check from being
    # followed.
    top_stat = os.lstat(releases_path)
    if stat.S_ISLNK(top_stat.st_mode):
        raise OSError(f"{releases_path} is a symlink; refusing to follow it")

    releases_fd = os.open(releases_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    walker = _FreeBSDWalker(max_entries)
    try:
        walker.walk(releases_fd, ())
    finally:
        os.close(releases_fd)

    return ScanResult(
        list(walker.groups.values()),
        walker.truncated,
        walker.errors,
        walker.unclassified,
        walker.mtimes,
        walker.depth_limited,
    )


# ---------------------------------------------------------------------------
# Protected-path pattern parser
# ---------------------------------------------------------------------------


class UnknownPatternError(ValueError):
    """Raised by compile_pattern() for a protect-filter shape this parser
    does not recognise. See the module docstring for why the caller must
    treat this as `protection: "unknown"` for the whole mirror rather than
    compute coverage from whatever patterns did parse.
    """


class CompiledPattern(NamedTuple):
    shape: str  # "anchored" | "bare" | "suffix"
    segments: Tuple[str, ...]
    raw: str


# Only a plain, literal name is allowed where these call `name`/`segs`: no
# rsync wildcard metacharacter (`*`, `?`, `[`) and no backslash (an escape
# character in some glob dialects, not a shape this parser models at all).
# `/7.[5]/***`, `**/14.?-RELEASE` and `/7\.5/***` all used to parse as if
# every character were literal, which is not what rsync does with them --
# see test_unknown_pattern_shapes_raise_instead_of_being_guessed.
_NAME_CHAR = r"[^/*?\[\\]"
_ANCHORED_RE = re.compile(rf"/(?P<name>{_NAME_CHAR}+)/\*\*\*")  # "/7.5/***"
_BARE_STAR_RE = re.compile(rf"\*\*/(?P<name>{_NAME_CHAR}+)")  # "**/14.3-RELEASE"
_SUFFIX_STAR_RE = re.compile(  # "**/ISO-IMAGES/14.3/***"
    rf"\*\*/(?P<segs>{_NAME_CHAR}+(?:/{_NAME_CHAR}+)*)/\*\*\*"
)


def compile_pattern(pattern: str) -> CompiledPattern:
    """Parse one shared.protected_paths.PROTECTED_PATHS entry.

    Raises UnknownPatternError for anything that is not one of the three
    shapes currently shipped, including a literal-looking name that
    actually contains an rsync wildcard -- see test_every_real_pattern_parses,
    which fails the day a fourth shape is added here without a matching
    case.
    """
    m = _ANCHORED_RE.fullmatch(pattern)
    if m:
        return CompiledPattern("anchored", (m.group("name"),), pattern)

    m = _BARE_STAR_RE.fullmatch(pattern)
    if m:
        return CompiledPattern("bare", (m.group("name"),), pattern)

    m = _SUFFIX_STAR_RE.fullmatch(pattern)
    if m:
        return CompiledPattern("suffix", tuple(m.group("segs").split("/")), pattern)

    raise UnknownPatternError(f"unrecognised protect-filter pattern: {pattern!r}")


def compile_patterns(patterns: Sequence[str]) -> List[CompiledPattern]:
    return [compile_pattern(p) for p in patterns]


def _path_matches(compiled: CompiledPattern, segments: Tuple[str, ...]) -> bool:
    """Does `segments` match this pattern's path, ignoring entry type?

    This is "targeted", not "protected" -- see pattern_matches() for the
    type-aware version _finalize_releases actually scores coverage with.
    Used on its own only where type does not matter: drift detection
    (_protected_not_on_disk) cares whether a name exists on disk AT ALL, not
    what kind of entry it is; and "targeted but not covered" is exactly the
    partial-coverage signal _finalize_releases needs.
    """
    if compiled.shape == "anchored":
        return segments == compiled.segments
    if compiled.shape == "bare":
        return bool(segments) and segments[-1] == compiled.segments[0]
    n = len(compiled.segments)
    return len(segments) >= n and segments[-n:] == compiled.segments


def _requires_directory(compiled: CompiledPattern) -> bool:
    """ "anchored" and "suffix" both carry rsync's trailing `/***`, which
    only ever protects a directory (and everything under it). "bare" is the
    one shape without it, and protects the opposite: a symlink or other
    non-directory leaf. See the module docstring's "ENTRY TYPE" section and
    shared/protected_paths.py's own empirical note on why both forms are
    listed for every FreeBSD release.
    """
    return compiled.shape in ("anchored", "suffix")


def pattern_matches(compiled: CompiledPattern, location: Location) -> bool:
    """Does this pattern actually protect `location`, in both path and
    entry type?

    A `/***`-style pattern whose path matches a symlink does not protect
    it; a bare pattern whose path matches a real directory protects only
    that directory's own entry, never (per real rsync, checked against the
    binary in tests/test_protected_paths.py's real-rsync cross-check) the
    files inside it --
    which this module treats as not protected at all, matching
    _requires_directory's docstring.
    """
    if not _path_matches(compiled, location.segments):
        return False
    return location.is_dir if _requires_directory(compiled) else not location.is_dir


def pattern_subject(compiled: CompiledPattern) -> str:
    """The human-readable name a pattern protects, for drift reporting
    (protected_not_on_disk) -- "14.3-RELEASE", "ISO-IMAGES/14.3"."""
    return "/".join(compiled.segments)


def is_covered(location: Location, compiled: Sequence[CompiledPattern]) -> bool:
    return any(pattern_matches(p, location) for p in compiled)


def is_targeted(location: Location, compiled: Sequence[CompiledPattern]) -> bool:
    """Does any pattern's path name this location, whether or not it
    actually protects it? See _path_matches and _finalize_releases."""
    return any(_path_matches(p, location.segments) for p in compiled)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _version_tuple(line: str) -> Tuple[int, int]:
    major_str, minor_str = line.split(".", 1)
    return int(major_str), int(minor_str)


def _newest_mtime(mtimes: Dict[Location, float], locations: Sequence[Location]) -> Optional[str]:
    """The newest mtime across `locations`, ISO-8601 UTC, from mtimes
    already captured DURING the walk (`entry.stat(follow_symlinks=False)`
    on the same os.DirEntry the match was found on -- see scan_openbsd/
    netbsd_releases and _FreeBSDWalker._record_location).

    Deliberately never re-resolves a path from a mirror root afterward:
    reconstructing `root.joinpath(*location.segments)` and lstat'ing it
    again would mean trusting every intermediate segment a second time,
    arbitrarily long after the walk that already checked them has
    finished -- see the module docstring's "NEVER TRUST A DIRECTORY'S TYPE
    TWICE" section.

    None if every location's mtime is unknown (its stat() failed during the
    walk -- a race with a sync in progress, or any other OS reason -- never
    a 500 for the whole mirror over one stale or strange entry), or if the
    newest known timestamp is not one datetime.fromtimestamp can represent
    (ValueError/OverflowError -- a corrupt or adversarial filesystem
    timestamp is not this module's problem to raise over).
    """
    known = [mtimes[location] for location in locations if location in mtimes]
    if not known:
        return None
    try:
        return datetime.fromtimestamp(max(known), tz=timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def _finalize_releases(
    raw_groups: Sequence[dict],
    mtimes: Dict[Location, float],
    compiled: Sequence[CompiledPattern],
    pattern_error: bool,
    mirror_type: MirrorType,
) -> List[dict]:
    """Raw scan groups -> the per-release dict shape the endpoint returns,
    minus the cross-release fields (newest/latest_in_major/at_risk) that
    need every release in the mirror at once -- see
    _annotate_cross_release_fields.
    """
    current_names = set(CURRENT_RELEASES.get(mirror_type, ()))
    releases = []
    for group in raw_groups:
        line = group["line"]
        unique_locations: List[Location] = sorted(set(group["locations"]))
        location_count = len(unique_locations)

        if pattern_error:
            protection = "unknown"
            unprotected_locations: List[str] = []
        else:
            covered = {loc for loc in unique_locations if is_covered(loc, compiled)}
            targeted = {loc for loc in unique_locations if is_targeted(loc, compiled)}
            if location_count and len(covered) == location_count:
                protection = "full"
            elif targeted:
                # Something in PROTECTED_PATHS names at least one of these
                # locations but does not fully cover it (wrong entry type,
                # or another location of the same release is not named at
                # all) -- see pattern_matches's docstring for why a
                # bare-only-protected directory lands here rather than
                # "full".
                protection = "partial"
            else:
                protection = "none"
            unprotected_locations = [
                _display_path(loc) for loc in unique_locations if loc not in covered
            ][:MAX_LOCATIONS_PER_VERSION]

        releases.append(
            {
                "version": group["version"],
                "line": line,
                "major": line.split(".", 1)[0],
                "kind": group["kind"],
                "protection": protection,
                "unprotected_locations": unprotected_locations,
                "locations": [
                    _display_path(loc) for loc in unique_locations[:MAX_LOCATIONS_PER_VERSION]
                ],
                "location_count": location_count,
                "current": group["version"] in current_names,
                "modified": _newest_mtime(mtimes, unique_locations),
            }
        )
    return releases


def _annotate_cross_release_fields(releases: List[dict], mirror_type: MirrorType) -> List[str]:
    """Sets newest, latest_in_major and at_risk in place. Returns
    stale_current -- see build_mirror_inventory's `stale_current` key.

    newest/latest_in_major are informational only -- see the module
    docstring's "CURRENT VS NEWEST VS LATEST_IN_MAJOR". at_risk is the rule
    that actually matters:

      * a final release is at_risk when it is not fully protected AND is
        not EFFECTIVELY current (`current` and not stale -- see below) --
        an EOL release nobody protected, regardless of whether some newer
        major has since made it "latest in its own major" forever.
      * a pre-release is at_risk only when something in PROTECTED_PATHS
        actually targets it (protection == "partial" can only mean that --
        see _finalize_releases) but does not fully cover it. An ordinary,
        never-protected pre-release's normal lifecycle (replaced, cleaned
        up once the final ships) is exactly the upstream housekeeping
        faithful mirroring should keep following, not a risk to flag.

    A STALE CURRENT_RELEASES ENTRY IS NOT TRUSTED FOR at_risk
    -----------------------------------------------------------------
    shared/protected_paths.py's upgrade procedure has two steps: protect
    the outgoing release, and REPLACE its name in CURRENT_RELEASES with the
    new one. Doing only the append half of step 2 -- adding the new name
    without removing the old one -- leaves both tagged `current`, and the
    old rule (`at_risk = protection != "full" and not current`) trusted
    `current` unconditionally, so the superseded one stayed "safe" forever.

    A current final release is *stale* when it is not the newest
    (OpenBSD/NetBSD) or not latest-in-its-major (FreeBSD) AMONG THE
    RELEASES CURRENT_RELEASES ITSELF NAMES for this mirror/major --
    deliberately not mirror-wide against every on-disk release. Mirror-wide
    would also catch a release that is current, alone, and simply not yet
    the newest thing physically on disk because a brand new, not-yet-
    reviewed release just appeared unprotected and unlisted -- exactly F1's
    own scenario (see test_a_new_major_release_is_at_risk_until_current_
    releases_is_updated), which must keep resolving by flagging the NEW,
    unreviewed release, not by un-flagging the one a human already vetted.
    Restricting the comparison to CURRENT_RELEASES' own membership is what
    tells the two situations apart: with one entry per mirror (or per
    FreeBSD major) it is trivially "the newest of one", so F1's scenario is
    unaffected; only an ACTUAL second, newer CURRENT_RELEASES entry in the
    same scope makes the older one stale.

    A stale entry keeps its honest `current: true` (it IS still, literally,
    in CURRENT_RELEASES -- that is a fact about the data file, not a
    verdict), is listed in `stale_current`, and -- the safe direction -- is
    treated as NOT current for at_risk specifically, so it is flagged
    unless fully protected.
    """
    finals = [r for r in releases if r["kind"] == "release"]
    newest_version = max((_version_tuple(r["line"]) for r in finals), default=None)

    latest_by_major: Dict[str, Tuple[int, int]] = {}
    for r in finals:
        v = _version_tuple(r["line"])
        if r["major"] not in latest_by_major or v > latest_by_major[r["major"]]:
            latest_by_major[r["major"]] = v

    for r in releases:
        is_final = r["kind"] == "release"
        v = _version_tuple(r["line"])
        r["newest"] = is_final and v == newest_version
        r["latest_in_major"] = is_final and v == latest_by_major.get(r["major"])

    current_finals = [r for r in finals if r["current"]]
    checks_mirror_wide = mirror_type in (MirrorType.OPENBSD, MirrorType.NETBSD)
    stale_versions = set()

    if checks_mirror_wide:
        current_newest = max((_version_tuple(r["line"]) for r in current_finals), default=None)
        for r in current_finals:
            if _version_tuple(r["line"]) != current_newest:
                stale_versions.add(r["version"])
    else:
        current_latest_by_major: Dict[str, Tuple[int, int]] = {}
        for r in current_finals:
            v = _version_tuple(r["line"])
            if r["major"] not in current_latest_by_major or v > current_latest_by_major[r["major"]]:
                current_latest_by_major[r["major"]] = v
        for r in current_finals:
            if _version_tuple(r["line"]) != current_latest_by_major[r["major"]]:
                stale_versions.add(r["version"])

    for r in releases:
        if r["kind"] == "release":
            effectively_current = r["current"] and r["version"] not in stale_versions
            r["at_risk"] = r["protection"] != "full" and not effectively_current
        elif r["kind"] == "prerelease":
            r["at_risk"] = r["protection"] == "partial"
        else:
            r["at_risk"] = False

    return sorted(stale_versions)


def _sort_key(release: dict) -> Tuple[int, int, int, str]:
    major, minor = _version_tuple(release["line"])
    # Newest first: highest line first; within the same line, the final
    # release sorts ahead of its own pre-releases.
    return (-major, -minor, 0 if release["kind"] == "release" else 1, release["version"])


def _protected_not_on_disk(
    raw_groups: Sequence[dict], compiled: Sequence[CompiledPattern]
) -> List[str]:
    """Protected names with no on-disk match anywhere (by path, regardless
    of entry type -- see _path_matches) -- protection configuration that has
    drifted from what actually exists, e.g. a release directory removed by
    hand instead of by deleting its line from shared/protected_paths.py
    (that module's own instructions for deliberately unprotecting
    something).
    """
    all_segments = [loc.segments for group in raw_groups for loc in group["locations"]]
    missing = {
        pattern_subject(p) for p in compiled if not any(_path_matches(p, s) for s in all_segments)
    }
    return sorted(missing)


def _current_not_on_disk(mirror_type: MirrorType, releases: Sequence[dict]) -> List[str]:
    """CURRENT_RELEASES names with no matching release found on disk --
    meaning that list itself has gone stale (see shared/protected_paths.py's
    upgrade procedure) and needs a human to update it, not that anything on
    this mirror is actually wrong.
    """
    on_disk = {r["version"] for r in releases}
    return sorted(name for name in CURRENT_RELEASES.get(mirror_type, ()) if name not in on_disk)


def _unavailable(mirror_type: MirrorType, root: Optional[str], error: str) -> dict:
    return _sanitize_for_json(
        {
            "mirror_type": mirror_type.value,
            "root": root,
            "available": False,
            "error": _display_name(error),
            "truncated": False,
            "incomplete": False,
            "releases": [],
            "protected_not_on_disk": [],
            "current_not_on_disk": [],
            "stale_current": [],
            "unclassified": [],
            "errors": [],
        }
    )


def build_mirror_inventory(
    mirror_type: MirrorType,
    root: Optional[str],
    patterns: Sequence[str],
    *,
    max_entries: int = MAX_ENTRIES_VISITED,
) -> dict:
    """The pure per-mirror-type entry point tests drive directly against a
    tmp_path tree. Never raises: a missing/unreadable root, a symlinked
    `releases`, or an unparseable pattern become `available: False` /
    `protection: "unknown"` respectively -- the "always 200, never a 500"
    contract the endpoint needs, satisfied here rather than with a
    try/except at the route. The whole return value is passed through
    _sanitize_for_json before it goes back to the caller -- see that
    function and the module docstring's "NON-UTF-8 NAMES" section: this is
    the defence-in-depth layer, not a substitute for building every label
    display-safe at its point of construction (see _display_name/
    _display_path/_display_segments throughout the scan_* functions).
    """
    if not root:
        return _unavailable(mirror_type, None, f"no mirror is configured for {mirror_type.value}")

    root_path = Path(root)
    try:
        if mirror_type == MirrorType.OPENBSD:
            scan = scan_openbsd_releases(root_path, max_entries=max_entries)
        elif mirror_type == MirrorType.NETBSD:
            scan = scan_netbsd_releases(root_path, max_entries=max_entries)
        else:
            scan = scan_freebsd_releases(root_path, max_entries=max_entries)
    except OSError as exc:
        logger.warning(
            "Archive inventory scan failed",
            mirror_type=mirror_type.value,
            root=root,
            error=str(exc),
        )
        return _unavailable(mirror_type, root, str(exc))

    try:
        compiled = compile_patterns(patterns)
        pattern_error = False
    except UnknownPatternError as exc:
        logger.error(
            "Unrecognised protect-filter pattern; reporting unknown protection",
            mirror_type=mirror_type.value,
            error=str(exc),
        )
        compiled = []
        pattern_error = True

    releases = _finalize_releases(scan.groups, scan.mtimes, compiled, pattern_error, mirror_type)
    stale_current = _annotate_cross_release_fields(releases, mirror_type)
    releases.sort(key=_sort_key)

    # See Location/MAX_WALK_DEPTH's own notes on each of these: `truncated`
    # (the entry cap or an EMFILE/ENFILE), a non-empty `errors` (a
    # permission error or similar on some subtree) or `unclassified` (a
    # release-looking name that failed the strict match), or the walk
    # skipping real content behind the depth cap (`scan.depth_limited`,
    # FreeBSD only) all mean this result may not be the full picture --
    # unlike a plain "protection: none", which is an ordinary, fully-known
    # state, not a sign anything was missed.
    incomplete = bool(scan.truncated or scan.errors or scan.unclassified or scan.depth_limited)

    return _sanitize_for_json(
        {
            "mirror_type": mirror_type.value,
            "root": root,
            "available": True,
            "error": None,
            "truncated": scan.truncated,
            "incomplete": incomplete,
            "releases": releases,
            "protected_not_on_disk": []
            if pattern_error
            else _protected_not_on_disk(scan.groups, compiled),
            "current_not_on_disk": _current_not_on_disk(mirror_type, releases),
            "stale_current": stale_current,
            "unclassified": scan.unclassified,
            "errors": scan.errors,
        }
    )


# ---------------------------------------------------------------------------
# Database-aware layer -- what admin.py calls
# ---------------------------------------------------------------------------


def read_archive_inventory(mirrors: Sequence[Mirror]) -> List[dict]:
    """Blocking: scans every configured mirror's filesystem tree. Run
    through asyncio.to_thread (see get_archive_inventory_view), never
    awaited directly from a coroutine -- tests/test_async_hygiene.py knows
    this function's name the same way it already knows read_disk_usage's
    and read_health_status_document's.

    One entry per MirrorType, in enum declaration order -- see
    app.core.protected_paths_view's own note on why that matters: a type
    with no configured Mirror row still has to appear, with
    available=False, rather than silently vanishing the way iterating only
    the configured rows would.
    """
    by_type: Dict[MirrorType, List[Mirror]] = {}
    for mirror in mirrors:
        by_type.setdefault(mirror.mirror_type, []).append(mirror)

    results = []
    for mirror_type in MirrorType:
        rows = by_type.get(mirror_type, [])
        mirror_names = sorted(m.name for m in rows)

        if not rows:
            entry = _unavailable(
                mirror_type, None, f"no mirror is configured for {mirror_type.value}"
            )
        else:
            # Today this is always exactly one row per type (see
            # protected_paths_view's own note); the lowest id is a stable,
            # deterministic pick if that ever stops being true.
            chosen = min(rows, key=lambda m: m.id)
            entry = build_mirror_inventory(
                mirror_type, chosen.local_path, PROTECTED_PATHS.get(mirror_type, ())
            )

        entry["mirror_names"] = mirror_names
        results.append(entry)
    return results


# In-process, single-flight, TTL cache for get_archive_inventory_view -- see
# the module docstring's "BLOCKING I/O AND CACHING" section. reset_cache()
# is for tests: without it every test after the first would see whatever
# the first one scanned, for up to CACHE_TTL_SECONDS of wall-clock time.
_cache_lock = asyncio.Lock()
_cached_result: Optional[dict] = None
_cached_at: float = 0.0


def reset_cache() -> None:
    global _cached_result, _cached_at
    _cached_result = None
    _cached_at = 0.0


def _scan_and_check_encodable(mirrors: Sequence[Mirror]) -> Tuple[List[dict], bool]:
    """read_archive_inventory, plus the pre-cache safety check
    get_archive_inventory_view needs: confirm the result can actually reach
    a client before letting it sit in the cache for CACHE_TTL_SECONDS.

    Runs inside the SAME to_thread worker as the scan itself (see the
    caller) rather than after awaiting it back on the event loop --
    `json.dumps` over a mirror's whole release list is real, if small, CPU
    work, and this module does not put blocking work on the event loop any
    more than the filesystem scan it is already offloading.

    `ensure_ascii=False` then `.encode("utf-8")` specifically, matching
    Starlette's own JSONResponse -- see the module docstring's "NON-UTF-8
    NAMES" section for why the default `json.dumps(result)` (ensure_ascii=
    True) would not catch the bug this exists to catch at all. build_mirror_
    inventory already sanitises every string it returns (_sanitize_for_json),
    so this should always succeed; it is the second, independent layer the
    task asked for, not the primary fix -- if it ever DOES fail, that is a
    gap in the sanitize pass to go fix, not something to paper over here.
    """
    mirrors_view = read_archive_inventory(mirrors)
    try:
        json.dumps(mirrors_view, ensure_ascii=False).encode("utf-8")
        encodable = True
    except (UnicodeEncodeError, UnicodeDecodeError, ValueError):
        logger.error(
            "Archive inventory result failed the pre-cache JSON safety check; "
            "serving it once, uncached"
        )
        encodable = False
    return mirrors_view, encodable


async def get_archive_inventory_view(mirrors: Sequence[Mirror]) -> dict:
    """Entry point admin.py calls: GET /api/admin/archive-inventory.

    Offloads the blocking scan to a worker thread, caches the result for
    CACHE_TTL_SECONDS, and always returns a 200-shaped payload -- see
    build_mirror_inventory for why nothing here raises for a filesystem
    error, a permission error, a symlink loop or an unrecognised
    protect-filter pattern. A result that fails the encodability check in
    _scan_and_check_encodable is still returned to THIS caller (best
    effort) but is never cached, so the next call gets a fresh scan instead
    of the same bad result for the rest of the TTL; a scan that raises
    entirely never reaches the cache assignment at all, for the same
    reason.

    The lock is held across the cache check AND the scan, not just the
    check: two callers racing on a cold cache both block here, and the
    second one sees a warm cache (populated by the first) once it acquires
    the lock, rather than both starting their own to_thread scan.
    """
    global _cached_result, _cached_at
    async with _cache_lock:
        now = time.monotonic()
        if _cached_result is not None and (now - _cached_at) < CACHE_TTL_SECONDS:
            return _cached_result

        mirrors_view, encodable = await asyncio.to_thread(_scan_and_check_encodable, mirrors)
        result = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mirrors": mirrors_view,
        }
        if encodable:
            _cached_result = result
            _cached_at = time.monotonic()
        return result
