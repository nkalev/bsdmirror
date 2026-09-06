"""
Read-only view of sync/protected_paths.py for the admin panel.

sync/protected_paths.py is the checked-in list of rsync `-f "P ..."` filter
patterns, per mirror, that keep `--delete` from removing an EOL release tree
once upstream prunes it -- real, deployed operational configuration. Until
now the only way to see what is currently protected was to open a Python
file on the server.

WHY THIS DATA IS COPIED HERE INSTEAD OF IMPORTED
--------------------------------------------------------------------------
The obvious fix, `from sync.protected_paths import PROTECTED_PATHS`, does not
work, and would not fail quietly: it would take the whole backend down at
import time. backend/Dockerfile COPYs exactly `backend/` and `shared/` into
the image (see the "REPO-ROOT BUILD CONTEXT" comment on the `backend`
service in docker-compose.yml); `sync/` is not part of that image in any
environment, dev or prod -- docker-compose.dev.yml's per-service `volumes:`
mount `backend/app` and `shared/` into the backend container and mount
`shared/` (not `backend/app`) into sync's, but neither mounts `sync/` into
backend. A module-level `import sync...` here would raise
ModuleNotFoundError before the app finished starting, in every environment
that matters.

The durable fix is the one already applied once in this repo for the ORM
models: give this data a single home in shared/ that both
sync/protected_paths.py and this module import (see shared/models/'s
docstring for the 17-way drift that replaced). That needs a small change
inside sync/protected_paths.py itself -- turning its own PROTECTED_PATHS
into a re-export -- which is outside this change's boundary.

Until that lands, PROTECTED_PATHS below is a snapshot, hand-kept identical to
sync/protected_paths.py's copy, and is not trusted to stay that way by
convention: tests/test_admin_protected_paths_view.py imports both modules
and asserts they are equal, so a change to one without the other fails
`docker compose run --rm test` instead of quietly showing an operator a list
that is no longer what rsync obeys. Update both in the same commit, in this
order: sync/protected_paths.py first (it is what rsync actually reads), this
file second, copied verbatim from it.
"""
from collections import defaultdict
from typing import Dict, List, Sequence, Tuple

from shared.models import Mirror, MirrorType

# Keep byte-for-byte identical to sync/protected_paths.py's PROTECTED_PATHS --
# see the module docstring above for why this is a maintained copy rather
# than an import, and tests/test_admin_protected_paths_view.py for the test
# that fails the build the moment these two disagree.
PROTECTED_PATHS: Dict[MirrorType, Tuple[str, ...]] = {
    MirrorType.OPENBSD: (
        "/7.5/***",
        "/7.6/***",
        "/7.7/***",
        "/7.8/***",
    ),
    MirrorType.NETBSD: (
        "/NetBSD-7.2/***",
        "/NetBSD-8.3/***",
        "/NetBSD-9.0/***",
        "/NetBSD-9.5/***",
        "/NetBSD-10.0/***",
        "/NetBSD-10.1/***",
        "/NetBSD-11.0_RC7/***",
    ),
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


def protected_paths_view(mirrors: Sequence[Mirror]) -> List[dict]:
    """One entry per `MirrorType`, in enum declaration order -- not one per
    `PROTECTED_PATHS` key, so a mirror type with nothing configured for it
    still appears, with an empty pattern list, instead of silently vanishing
    the way iterating `PROTECTED_PATHS.items()` would.

    `mirror_names` lists every configured Mirror of that type, sorted by
    name. Today that is always zero or one -- main.py seeds exactly one
    mirror per type at startup and nothing deletes a Mirror row -- but this
    does not assume that stays true.
    """
    names_by_type: Dict[MirrorType, List[str]] = defaultdict(list)
    for mirror in mirrors:
        names_by_type[mirror.mirror_type].append(mirror.name)

    return [
        {
            "mirror_type": mirror_type.value,
            "mirror_names": sorted(names_by_type[mirror_type]),
            "patterns": list(PROTECTED_PATHS.get(mirror_type, ())),
        }
        for mirror_type in MirrorType
    ]
