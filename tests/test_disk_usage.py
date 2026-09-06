"""Disk capacity for the mirror data volume (backend/app/core/disk.py).

The defect: nothing in this codebase has ever measured free space. The only
size figure anywhere is Mirror.total_size_bytes summed across mirrors, which
is what the mirrors *contain* -- never what the disk has *left*. That gap was
tolerable while rsync's --delete implicitly bounded the tree to roughly
upstream's own size; sync/protected_paths.py removes that bound on purpose
(EOL releases now survive upstream pruning), so the tree grows monotonically
and nothing would show an operator it approaching the disk's actual limit.

Three things have to be true for the fix to be real rather than decorative,
and this file is organised around them:

  1. The arithmetic (_usage_from_statvfs) matches `df`'s own convention, not
     used/total -- see the derivation's docstring in app/core/disk.py for why
     the two are not the same number.
  2. The reading is a real statvfs() against a real path in this container,
     not a plausible constant. Proved two ways: by varying the input (a
     monkeypatched os.statvfs, checked against the exact numbers that input
     implies) and by cross-checking against an independent statvfs() call
     against a real directory, taken in the test itself.
  3. GET /api/admin/dashboard degrades one field, not the whole response,
     when the configured path cannot be read.
"""
import inspect
import os
import textwrap
from types import SimpleNamespace

import pytest

from app.api import admin as admin_module
from app.core import disk
from app.core.disk import DiskUsage, get_disk_usage, read_disk_usage
from tests.conftest import auth_header

# ---------------------------------------------------------------------------
# 1. The arithmetic, as a table
# ---------------------------------------------------------------------------


def _fake_vfs(f_frsize, f_blocks, f_bfree, f_bavail):
    """Everything _usage_from_statvfs reads off an os.statvfs_result. A
    SimpleNamespace duck-types it without needing a real filesystem."""
    return SimpleNamespace(f_frsize=f_frsize, f_blocks=f_blocks, f_bfree=f_bfree, f_bavail=f_bavail)


CASES = [
    (
        "no_reserved_blocks",
        _fake_vfs(1, 100, 60, 60),
        DiskUsage(total_bytes=100, used_bytes=40, free_bytes=60, percent_used=40.0),
    ),
    (
        # ext4/xfs-shaped: f_bfree (500) > f_bavail (450) -- 50 blocks held
        # back for root. This is the case that tells used-from-free apart
        # from used-from-bfree, and free-as-bavail apart from free-as-bfree;
        # every other case below has bfree == bavail and cannot.
        "root_reserve_excluded_from_free_but_not_from_used",
        _fake_vfs(4096, 1000, 500, 450),
        DiskUsage(
            total_bytes=4_096_000,
            used_bytes=2_048_000,
            free_bytes=1_843_200,
            percent_used=52.6,
        ),
    ),
    (
        "empty_filesystem",
        _fake_vfs(4096, 1000, 1000, 1000),
        DiskUsage(total_bytes=4_096_000, used_bytes=0, free_bytes=4_096_000, percent_used=0.0),
    ),
    (
        "full_filesystem",
        _fake_vfs(4096, 1000, 0, 0),
        DiskUsage(total_bytes=4_096_000, used_bytes=4_096_000, free_bytes=0, percent_used=100.0),
    ),
    (
        "zero_sized_filesystem_does_not_divide_by_zero",
        _fake_vfs(4096, 0, 0, 0),
        DiskUsage(total_bytes=0, used_bytes=0, free_bytes=0, percent_used=0.0),
    ),
]


@pytest.mark.parametrize("name,vfs,expected", CASES, ids=[c[0] for c in CASES])
def test_usage_from_statvfs(name, vfs, expected):
    assert disk._usage_from_statvfs(vfs) == expected


# ---------------------------------------------------------------------------
# 1b. The arithmetic under mutation
#
# Same approach as the orphan reaper's decision table, the rsync classifier
# and the admin.js escaper: break the function on purpose and require the
# table above to notice. A table that still passes against a broken formula
# is not testing the formula.
# ---------------------------------------------------------------------------


def _usage_source() -> str:
    return textwrap.dedent(inspect.getsource(disk._usage_from_statvfs))


def _load_usage(source: str):
    namespace = {"os": os, "DiskUsage": DiskUsage}
    code_obj = compile(source, "<mutated _usage_from_statvfs>", "exec")
    # Controlled, locally-authored source (a mutated copy of _usage_from_statvfs
    # above); see the module docstring and tests/test_orphan_reaper.py for the
    # same technique used against sync_service.py's orphan-reaper decision.
    eval(code_obj, namespace)
    return namespace["_usage_from_statvfs"]


def _run_cases(fn) -> dict:
    results = {}
    for name, vfs, expected in CASES:
        try:
            results[name] = fn(vfs) == expected
        except Exception:
            results[name] = False
    return results


def test_the_unmutated_arithmetic_passes_its_own_table():
    """The harness has to agree with the real function before it can be
    trusted to judge a broken one."""
    results = _run_cases(_load_usage(_usage_source()))
    assert all(results.values()), [n for n, ok in results.items() if not ok]


MUTATIONS = [
    (
        # The bug the derivation exists to avoid: computing used as
        # total - free instead of counting f_bfree directly. This folds the
        # root reserve into "used" -- invisible whenever bfree == bavail
        # (four of the five cases above), which is exactly why the reserve
        # case exists.
        "used_computed_as_total_minus_free",
        "    used = total - (vfs.f_frsize * vfs.f_bfree)",
        "    used = total - free",
        "root_reserve_excluded_from_free_but_not_from_used",
    ),
    (
        # "Free" as everything not allocated, rather than everything an
        # unprivileged process could actually write into.
        "free_uses_bfree_instead_of_bavail",
        "    free = vfs.f_frsize * vfs.f_bavail",
        "    free = vfs.f_frsize * vfs.f_bfree",
        "root_reserve_excluded_from_free_but_not_from_used",
    ),
    (
        # df's own convention (used / (used + avail)) replaced by the naive
        # used / total. They agree whenever there is no reserve, which is why
        # this, too, only shows up on the reserve case.
        "percent_uses_total_instead_of_used_plus_free",
        "    percent_used = round((used / denominator) * 100, 1) if denominator else 0.0",
        "    percent_used = round((used / total) * 100, 1) if total else 0.0",
        "root_reserve_excluded_from_free_but_not_from_used",
    ),
    (
        "drops_the_zero_denominator_guard",
        "    percent_used = round((used / denominator) * 100, 1) if denominator else 0.0",
        "    percent_used = round((used / denominator) * 100, 1)",
        "zero_sized_filesystem_does_not_divide_by_zero",
    ),
]


@pytest.mark.parametrize("name,old,new,must_fail", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_mutation_is_caught(name, old, new, must_fail):
    source = _usage_source()
    assert source.count(old) == 1, (
        f"mutation {name!r} no longer matches _usage_from_statvfs exactly once "
        f"(found {source.count(old)}). Update the mutation, do not delete it."
    )

    mutated = _load_usage(source.replace(old, new))
    results = _run_cases(mutated)
    failed = sorted(n for n, ok in results.items() if not ok)

    assert failed, (
        f"mutation {name!r} broke the arithmetic and every case still passed. "
        f"The table does not test what it claims to."
    )
    assert must_fail in failed, (
        f"mutation {name!r} was expected to fail {must_fail!r}, " f"but the failures were {failed}"
    )


# ---------------------------------------------------------------------------
# 2. The reading is real, not a plausible constant
# ---------------------------------------------------------------------------


def test_read_disk_usage_responds_to_the_statvfs_result_it_is_given(monkeypatch):
    """A hardcoded, plausible-looking return (e.g. an 8.9 TB total) would
    pass every test above without ever calling statvfs. Feed os.statvfs a
    value nobody would pick by coincidence and require the exact numbers that
    input implies, and nothing else."""
    probe = _fake_vfs(f_frsize=2048, f_blocks=123_457, f_bfree=222, f_bavail=111)
    monkeypatch.setattr(disk.os, "statvfs", lambda path: probe)

    usage = read_disk_usage("/this/path/is/never/opened -- statvfs is mocked")

    assert usage.total_bytes == 2048 * 123_457
    assert usage.free_bytes == 2048 * 111
    assert usage.used_bytes == 2048 * (123_457 - 222)


def test_read_disk_usage_against_a_real_filesystem_inside_this_container(tmp_path):
    """Cross-checked against an INDEPENDENT statvfs() call on the same
    directory, taken here rather than reused from app.core.disk -- so a
    hardcoded return in read_disk_usage would not coincidentally match.

    total_bytes is checked exactly: tmpfs capacity is fixed at mount time and
    does not move between the two calls. free_bytes/used_bytes are checked as
    bounds, not equality -- tmpfs free space is backed by live host memory,
    and this test genuinely flaked in CI with an exact-equality assertion
    here: two statvfs() calls on /tmp a full HTTP round trip apart (the
    dashboard test below, before it was rewritten to a controlled input)
    disagreed by a few blocks under real memory pressure, on a filesystem
    this test does not otherwise write to. That a bound can still be wrong is
    exactly what the next two tests (mocked, and error-path) exist to catch
    without depending on the host's memory state.

    How this was actually checked while writing the test: running
        docker compose run --rm test python3 -c \
            "import os, tempfile; print(os.statvfs(tempfile.gettempdir()))"
    against this repo's own test image confirmed pytest's tmp_path resolves
    to a real, non-trivial filesystem in the container (the tmpfs backing
    /tmp -- see Dockerfile.test's HOME=/tmp and docker-compose.yml's `test`
    service tmpfs mount), not a zeroed-out stub.
    """
    vfs = os.statvfs(str(tmp_path))
    usage = read_disk_usage(str(tmp_path))

    assert usage.total_bytes == vfs.f_frsize * vfs.f_blocks
    assert usage.total_bytes > 0, "a real filesystem was expected to report a nonzero size"
    assert 0 <= usage.free_bytes <= usage.total_bytes
    assert 0 <= usage.used_bytes <= usage.total_bytes


def test_read_disk_usage_is_not_itself_defensive():
    """read_disk_usage raises on a bad path exactly as os.statvfs does. The
    None-on-failure behaviour below belongs to get_disk_usage; if this
    function stopped raising, the contrast the next test relies on to prove
    the wrapper does something would disappear."""
    with pytest.raises(OSError):
        read_disk_usage("/path/that/almost-certainly/does-not-exist/on/this/box")


async def test_get_disk_usage_returns_none_for_an_unreadable_path():
    result = await get_disk_usage("/path/that/almost-certainly/does-not-exist/on/this/box")
    assert result is None


async def test_get_disk_usage_returns_real_data_for_a_readable_path(tmp_path):
    result = await get_disk_usage(str(tmp_path))
    assert result is not None
    assert result.total_bytes > 0


# ---------------------------------------------------------------------------
# 3. GET /api/admin/dashboard
# ---------------------------------------------------------------------------


async def test_dashboard_storage_matches_the_statvfs_result_for_the_configured_path(
    client, seed, tmp_path, monkeypatch
):
    """End to end: point MIRROR_DATA_PATH at a real directory, and require the
    JSON body to equal exactly what that statvfs() result implies.

    os.statvfs itself is mocked here, deliberately -- not to avoid touching a
    real filesystem (test_read_disk_usage_against_a_real_filesystem_inside_this_container
    and test_get_disk_usage_returns_real_data_for_a_readable_path already do,
    for the "is this actually a live syscall" half of the proof), but because
    an EARLIER version of this test took its own statvfs() snapshot and
    compared it to the dashboard's, one full HTTP round trip apart, and
    flaked: tmpfs free space tracks live host memory, which moved between the
    two calls under real memory pressure and made an exact-equality assertion
    wrong roughly once per full suite run. A controlled input removes that
    variable and proves the thing this test actually owns -- that
    MIRROR_DATA_PATH reaches get_disk_usage and the result is serialised
    without being altered on the way -- deterministically.
    """
    probe = SimpleNamespace(f_frsize=4096, f_blocks=2_000_000, f_bfree=900_000, f_bavail=850_000)
    calls = []

    def fake_statvfs(path):
        calls.append(path)
        return probe

    monkeypatch.setattr(disk.os, "statvfs", fake_statvfs)
    monkeypatch.setattr(admin_module.settings, "MIRROR_DATA_PATH", str(tmp_path))

    resp = await client.get("/api/admin/dashboard", headers=auth_header(seed["users"]["readonly"]))
    assert resp.status_code == 200
    storage = resp.json()["storage"]

    # The configured path is what actually reached statvfs -- not the
    # container's hardcoded /data/mirrors default, and not tmp_path's parent.
    assert calls == [str(tmp_path)]

    assert storage["path"] == str(tmp_path)
    assert storage["total_bytes"] == 4096 * 2_000_000
    assert storage["free_bytes"] == 4096 * 850_000
    assert storage["used_bytes"] == 4096 * (2_000_000 - 900_000)
    assert storage["percent_used"] == disk._usage_from_statvfs(probe).percent_used


async def test_dashboard_storage_is_null_not_a_500_when_the_mount_is_missing(
    client, seed, tmp_path, monkeypatch
):
    """The failure this is guarding against: MIRROR_DATA_PATH pointing at a
    directory that does not exist -- a host misconfiguration or a lost bind
    mount. The dashboard must still be a 200; one field goes to null, not the
    endpoint."""
    missing = tmp_path / "does-not-exist"
    monkeypatch.setattr(admin_module.settings, "MIRROR_DATA_PATH", str(missing))

    resp = await client.get("/api/admin/dashboard", headers=auth_header(seed["users"]["readonly"]))
    assert resp.status_code == 200
    assert resp.json()["storage"] == {
        "path": str(missing),
        "total_bytes": None,
        "used_bytes": None,
        "free_bytes": None,
        "percent_used": None,
    }


async def test_dashboard_storage_degrades_with_the_containers_own_default_path(client, seed):
    """No monkeypatch: MIRROR_DATA_PATH keeps its real default, /data/mirrors,
    which this test container never mounts (docker-compose.yml's `test`
    service bind-mounts only the repo, read-only). This is the same
    RBAC-relevant call as test_rbac.py's "dashboard" case, asserted again here
    so a regression in this field specifically fails under this file's name
    instead of only inside that suite's much larger matrix -- and so that if
    a future compose change ever does mount something at /data/mirrors in the
    test service, this stops passing for the right reason (see the test
    above for the "mounted" half of this contract).
    """
    resp = await client.get("/api/admin/dashboard", headers=auth_header(seed["users"]["readonly"]))
    assert resp.status_code == 200
    storage = resp.json()["storage"]
    assert storage["path"] == "/data/mirrors"
    assert storage["total_bytes"] is None
