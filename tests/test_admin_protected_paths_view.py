"""
Protected release paths, read-only: GET /api/admin/protected-paths.

sync/protected_paths.py is real, deployed operational configuration -- the
rsync `-f "P ..."` filters that keep --delete from removing an EOL release
once upstream prunes it -- and until now the only way to see what is
currently protected was to open a Python file on the server. This endpoint
is that view: display only, no write path, by design (see
app.core.protected_paths and sync/protected_paths.py's own module docstring
for why an operator cannot edit this list here or anywhere else).

Two things make this file larger than "call the endpoint, check the JSON":

  1. app.core.protected_paths.PROTECTED_PATHS is a hand-kept COPY of
     sync/protected_paths.py's dict, not an import of it -- the backend
     image does not ship sync/ (see that module's docstring for the
     Dockerfile boundary). test_backend_snapshot_matches_the_deployed_module
     below is the only thing standing between this view and one that quietly
     shows an operator a list that is no longer what rsync obeys.
  2. protected_paths_view()'s "every mirror type appears, even one with
     nothing configured" property cannot be exercised against today's real
     PROTECTED_PATHS -- all three mirror types currently have entries -- so
     it is proved against a stand-in dict instead, both directly and under
     mutation.
"""
import inspect
import textwrap
from collections import defaultdict
from typing import Dict, List, Sequence

import pytest
from sqlalchemy import select

from app.core import protected_paths as protected_paths_module
from app.core.protected_paths import PROTECTED_PATHS, protected_paths_view
from shared.models import Mirror, MirrorStatus, MirrorType
from tests.conftest import auth_header

ALL_TYPES = {"freebsd", "netbsd", "openbsd"}


def _mirror(mirror_id, name, mirror_type):
    return Mirror(
        id=mirror_id,
        name=name,
        mirror_type=mirror_type,
        upstream_url="rsync://example.test/",
        local_path="/data/mirrors/x",
        enabled=True,
        status=MirrorStatus.ACTIVE,
    )


# ---------------------------------------------------------------------------
# 1. The snapshot must not drift from the deployed module
# ---------------------------------------------------------------------------


def test_backend_snapshot_matches_the_deployed_sync_service_module():
    """The guard the whole design depends on: sync/protected_paths.py is
    what rsync actually obeys, app.core.protected_paths is a hand-kept copy
    of it for the reason explained in that module's docstring. Change one
    without the other and this fails `docker compose run --rm test` instead
    of quietly showing an operator a stale list."""
    from sync.protected_paths import PROTECTED_PATHS as DEPLOYED

    assert PROTECTED_PATHS == DEPLOYED


# ---------------------------------------------------------------------------
# 2. protected_paths_view -- pure function
# ---------------------------------------------------------------------------


def test_every_real_mirror_type_is_listed_with_its_real_patterns():
    groups = protected_paths_view([])
    by_type = {g["mirror_type"]: g for g in groups}

    assert set(by_type) == ALL_TYPES
    assert by_type["openbsd"]["patterns"] == list(PROTECTED_PATHS[MirrorType.OPENBSD])
    assert by_type["netbsd"]["patterns"] == list(PROTECTED_PATHS[MirrorType.NETBSD])
    assert by_type["freebsd"]["patterns"] == list(PROTECTED_PATHS[MirrorType.FREEBSD])


def test_mirror_names_are_empty_when_nothing_is_configured():
    groups = protected_paths_view([])
    assert all(g["mirror_names"] == [] for g in groups), groups


def test_mirror_names_list_every_configured_mirror_of_that_type_sorted():
    zeta = _mirror(1, "Zeta", MirrorType.FREEBSD)
    alpha = _mirror(2, "Alpha", MirrorType.FREEBSD)

    groups = protected_paths_view([zeta, alpha])

    freebsd = next(g for g in groups if g["mirror_type"] == "freebsd")
    assert freebsd["mirror_names"] == ["Alpha", "Zeta"]


def test_a_mirror_of_one_type_does_not_leak_into_another_types_group():
    openbsd_mirror = _mirror(1, "OpenBSD", MirrorType.OPENBSD)

    groups = protected_paths_view([openbsd_mirror])

    by_type = {g["mirror_type"]: g for g in groups}
    assert by_type["openbsd"]["mirror_names"] == ["OpenBSD"]
    assert by_type["freebsd"]["mirror_names"] == []
    assert by_type["netbsd"]["mirror_names"] == []


def test_a_mirror_type_with_nothing_configured_still_appears(monkeypatch):
    """Exercised against a stand-in dict, not the real PROTECTED_PATHS:
    every real mirror type currently has entries, so this property has no
    naturally-occurring case today."""
    monkeypatch.setattr(protected_paths_module, "PROTECTED_PATHS", {MirrorType.FREEBSD: ("x",)})

    groups = protected_paths_view([])
    by_type = {g["mirror_type"]: g for g in groups}

    assert set(by_type) == ALL_TYPES
    assert by_type["freebsd"]["patterns"] == ["x"]
    assert by_type["netbsd"]["patterns"] == []
    assert by_type["openbsd"]["patterns"] == []


# ---------------------------------------------------------------------------
# 3. protected_paths_view under mutation
# ---------------------------------------------------------------------------


def _view_source():
    return textwrap.dedent(inspect.getsource(protected_paths_module.protected_paths_view))


def _load_view(source, patterns):
    namespace = {
        "defaultdict": defaultdict,
        "Dict": Dict,
        "List": List,
        "Sequence": Sequence,
        "Mirror": Mirror,
        "MirrorType": MirrorType,
        "PROTECTED_PATHS": patterns,
    }
    exec(compile(source, "<mutated protected_paths_view>", "exec"), namespace)
    return namespace["protected_paths_view"]


def test_the_unmutated_view_lists_every_mirror_type_even_with_nothing_configured():
    """Guards the guard: the harness has to agree with the real function
    before a mutation of it means anything."""
    fn = _load_view(_view_source(), {MirrorType.FREEBSD: ("x",)})
    groups = fn([])
    assert {g["mirror_type"] for g in groups} == ALL_TYPES


def test_mutation_iterating_only_configured_types_is_caught():
    """The mistake this guards against: `for mirror_type in PROTECTED_PATHS`
    instead of `for mirror_type in MirrorType` looks identical today, because
    every real mirror type happens to have an entry -- and silently drops a
    future mirror type from this view the day one is added without a
    protected-paths entry yet."""
    source = _view_source()
    old = "for mirror_type in MirrorType"
    assert source.count(old) == 1, (
        "mutation no longer matches protected_paths_view exactly once; "
        "update the mutation, do not delete it"
    )

    fn = _load_view(
        source.replace(old, "for mirror_type in PROTECTED_PATHS"), {MirrorType.FREEBSD: ("x",)}
    )
    groups = fn([])
    types = {g["mirror_type"] for g in groups}

    assert types != ALL_TYPES, (
        "mutation was supposed to drop unconfigured mirror types, but every "
        "type still appeared -- this mutation no longer exercises the "
        "property it is meant to guard"
    )
    assert types == {"freebsd"}


def test_mutation_dropping_the_mirror_names_sort_is_caught():
    zeta = _mirror(1, "Zeta", MirrorType.FREEBSD)
    alpha = _mirror(2, "Alpha", MirrorType.FREEBSD)

    source = _view_source()
    old = '"mirror_names": sorted(names_by_type[mirror_type]),'
    assert source.count(old) == 1, (
        "mutation no longer matches protected_paths_view exactly once; "
        "update the mutation, do not delete it"
    )

    fn = _load_view(
        source.replace(old, '"mirror_names": names_by_type[mirror_type],'), PROTECTED_PATHS
    )
    groups = fn([zeta, alpha])
    freebsd = next(g for g in groups if g["mirror_type"] == "freebsd")

    assert freebsd["mirror_names"] == ["Zeta", "Alpha"], (
        "mutation was supposed to drop the sort (insertion order, not "
        "alphabetical); if this reads alphabetically the mutation no longer "
        "exercises the sort"
    )


# ---------------------------------------------------------------------------
# 4. The endpoint, against a real (SQLite) database
# ---------------------------------------------------------------------------


async def test_protected_paths_endpoint_lists_all_three_mirror_types(client, seed):
    """conftest's `seed` fixture creates exactly one Mirror (FreeBSD), so
    this also proves netbsd/openbsd appear despite having no configured
    Mirror row in this database."""
    resp = await client.get(
        "/api/admin/protected-paths", headers=auth_header(seed["users"]["readonly"])
    )
    assert resp.status_code == 200

    by_type = {g["mirror_type"]: g for g in resp.json()["groups"]}
    assert set(by_type) == ALL_TYPES
    assert by_type["freebsd"]["mirror_names"] == ["FreeBSD"]
    assert by_type["netbsd"]["mirror_names"] == []
    assert by_type["openbsd"]["mirror_names"] == []
    assert len(by_type["openbsd"]["patterns"]) == len(PROTECTED_PATHS[MirrorType.OPENBSD])


async def test_protected_paths_endpoint_matches_the_pure_function(client, seed, db_session):
    mirrors = db_session.execute(select(Mirror)).scalars().all()
    expected = protected_paths_view(mirrors)

    resp = await client.get(
        "/api/admin/protected-paths", headers=auth_header(seed["users"]["admin"])
    )
    assert resp.status_code == 200
    assert resp.json()["groups"] == expected


@pytest.mark.parametrize("method", ["post", "patch", "delete", "put"])
async def test_protected_paths_has_no_write_path(client, seed, method):
    """Display only, deliberately: there is no PATCH for this list anywhere
    in admin.py, and there must not be. A 405 here is the route table
    itself proving that, not merely this test's intent."""
    resp = await getattr(client, method)(
        "/api/admin/protected-paths", headers=auth_header(seed["users"]["admin"])
    )
    assert resp.status_code == 405
