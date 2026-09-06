"""
Admin-panel view over shared.protected_paths.PROTECTED_PATHS.

shared/protected_paths.py is the checked-in list of rsync `-f "P ..."` filter
patterns, per mirror, that keep `--delete` from removing an EOL release tree
once upstream prunes it -- real, deployed operational configuration, imported
directly by sync_service.py. Until GET /api/admin/protected-paths existed,
the only way to see what is currently protected was to open that Python file
on the server.

protected_paths_view() is the pure function the endpoint is built on: given
the currently configured Mirror rows, shape shared.protected_paths.PROTECTED_PATHS
into one entry per MirrorType, in enum declaration order -- not one per
PROTECTED_PATHS key, so a mirror type with nothing configured for it still
appears, with an empty pattern list, instead of silently vanishing the way
iterating PROTECTED_PATHS.items() would.

It used to shape a *second*, hand-maintained copy of PROTECTED_PATHS kept
here because the backend could not import sync/protected_paths.py (the
package is not part of backend/Dockerfile's build context) -- see
shared/protected_paths.py's own module docstring for why that copy is gone
and PROTECTED_PATHS now has exactly one definition. This module keeps only
the view-shaping logic, which is backend-specific (it needs Mirror rows from
this service's own database session) and has no reason to live in shared/.

No write path: there is no PATCH for this list anywhere in admin.py, and
there must not be. The list is edited by changing shared/protected_paths.py,
reviewed as a diff like any other change to this repo, and is not
operator-editable through this API.
"""
from collections import defaultdict
from typing import Dict, List, Sequence

from shared.models import Mirror, MirrorType
from shared.protected_paths import PROTECTED_PATHS


def protected_paths_view(mirrors: Sequence[Mirror]) -> List[dict]:
    """One entry per `MirrorType`, in enum declaration order -- see the
    module docstring for why that matters more than it looks like it should.

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
