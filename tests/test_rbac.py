"""
Role-based access control matrix for the admin API.

Table-driven on purpose: the point of this file is that adding a route to
backend/app/api/admin.py without adding a row here is visible, and that the
allow/deny decision for every existing route is stated in one place.

The gates are require_admin / require_operator / get_current_user in
backend/app/api/auth.py.

For allowed roles the test asserts the endpoint's real success status, not
merely "not 403" -- otherwise a route that 500s would read as authorised.
"""
from dataclasses import dataclass, field
from typing import Optional

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.models.mirror import Mirror
from app.models.sync_job import SyncJob
from app.models.user import User
from tests.conftest import auth_header

ROLES = ["admin", "operator", "readonly"]

# Gate -> the 403 detail string that gate raises.
GATE_MESSAGE = {
    "require_admin": "Admin access required",
    "require_operator": "Operator access required",
}


@dataclass(frozen=True)
class Case:
    id: str
    method: str
    path: str  # may contain {mirror_id} / {job_id} / {victim_id}
    gate: str
    allowed: frozenset
    ok_status: int
    body: Optional[dict] = field(default=None)


MATRIX = [
    # --- User management: admin only -------------------------------------
    Case("list-users", "GET", "/api/admin/users",
         "require_admin", frozenset({"admin"}), 200),
    Case("create-user", "POST", "/api/admin/users",
         "require_admin", frozenset({"admin"}), 201,
         {"username": "brand-new-user", "password": "a-sufficiently-long-password",
          "role": "readonly"}),
    Case("update-user", "PATCH", "/api/admin/users/{victim_id}",
         "require_admin", frozenset({"admin"}), 200,
         {"email": "updated@example.test"}),
    Case("delete-user", "DELETE", "/api/admin/users/{victim_id}",
         "require_admin", frozenset({"admin"}), 204),

    # --- Mirror management: operator and above ---------------------------
    Case("update-mirror", "PATCH", "/api/admin/mirrors/{mirror_id}",
         "require_operator", frozenset({"admin", "operator"}), 200,
         {"enabled": True}),
    Case("trigger-sync", "POST", "/api/admin/mirrors/{mirror_id}/sync",
         "require_operator", frozenset({"admin", "operator"}), 200),

    # --- Audit and settings: admin only ----------------------------------
    Case("audit-logs", "GET", "/api/admin/audit-logs",
         "require_admin", frozenset({"admin"}), 200),
    Case("get-settings", "GET", "/api/admin/settings",
         "require_admin", frozenset({"admin"}), 200),
    Case("update-settings", "PATCH", "/api/admin/settings",
         "require_admin", frozenset({"admin"}), 200,
         {"settings": {"sync_schedule": "30 5 * * *"}}),

    # --- Any authenticated user ------------------------------------------
    # Note: these two are gated on get_current_user only, so a readonly account
    # can read the dashboard and the full rsync output of any sync job.
    Case("dashboard", "GET", "/api/admin/dashboard",
         "get_current_user", frozenset(ROLES), 200),
    Case("sync-job-logs", "GET", "/api/admin/sync-jobs/{job_id}/logs",
         "get_current_user", frozenset(ROLES), 200),
]


def url_for(case: Case, seed) -> str:
    return case.path.format(
        mirror_id=seed["mirror_id"],
        job_id=seed["job_id"],
        victim_id=seed["users"]["victim"].id,
    )


async def call(client, case: Case, seed, headers=None):
    return await client.request(
        case.method,
        url_for(case, seed),
        headers=headers or {},
        json=case.body,
    )


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("case", MATRIX, ids=[c.id for c in MATRIX])
async def test_rbac_matrix(client, seed, case, role):
    resp = await call(client, case, seed, auth_header(seed["users"][role]))

    if role in case.allowed:
        assert resp.status_code == case.ok_status, (
            f"{role} should be allowed {case.id}, got {resp.status_code}: {resp.text}"
        )
    else:
        assert resp.status_code == 403, (
            f"{role} should be denied {case.id}, got {resp.status_code}: {resp.text}"
        )
        assert resp.json()["detail"] == GATE_MESSAGE[case.gate]


@pytest.mark.parametrize("case", MATRIX, ids=[c.id for c in MATRIX])
async def test_admin_api_rejects_anonymous(client, seed, case):
    resp = await call(client, case, seed)
    assert resp.status_code == 401, f"{case.id} was reachable without a token"


@pytest.mark.parametrize("case", MATRIX, ids=[c.id for c in MATRIX])
async def test_admin_api_rejects_invalid_token(client, seed, case):
    resp = await call(client, case, seed, {"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# The role claim in the token must not be trusted
# ---------------------------------------------------------------------------

async def test_role_is_read_from_the_database_not_the_token(client, seed):
    """A validly signed token carrying role="admin" for a readonly account must
    still be denied: require_admin reads current_user.role, and get_current_user
    reloads the user by username on every request.

    This is the property that makes the `role` claim decorative. If someone
    later "optimises" the gate to read token_data.role, this test fails.
    """
    readonly = seed["users"]["readonly"]
    forged = create_access_token(
        data={"sub": readonly.username, "user_id": readonly.id, "role": "admin"}
    )
    resp = await client.get("/api/admin/users", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Admin access required"


async def test_forged_user_id_claim_does_not_select_the_user(client, seed):
    """get_current_user looks the user up by `sub`, never by `user_id`, so a
    mismatched user_id claim is inert rather than a privilege escalation."""
    readonly = seed["users"]["readonly"]
    admin = seed["users"]["admin"]
    forged = create_access_token(
        data={"sub": readonly.username, "user_id": admin.id, "role": "readonly"}
    )
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert me.status_code == 200
    assert me.json()["username"] == readonly.username
    assert me.json()["id"] == readonly.id


# ---------------------------------------------------------------------------
# Denied requests must not have side effects
# ---------------------------------------------------------------------------

async def test_denied_mirror_update_leaves_the_mirror_untouched(client, seed, db_session):
    resp = await client.patch(
        f"/api/admin/mirrors/{seed['mirror_id']}",
        headers=auth_header(seed["users"]["readonly"]),
        json={"enabled": False, "upstream_url": "rsync://attacker.example/"},
    )
    assert resp.status_code == 403

    mirror = db_session.execute(select(Mirror)).scalar_one()
    assert mirror.enabled is True
    assert mirror.upstream_url == "rsync://ftp.freebsd.org/FreeBSD/"


async def test_denied_sync_trigger_creates_no_job(client, seed, db_session):
    before = len(db_session.execute(select(SyncJob)).scalars().all())

    resp = await client.post(
        f"/api/admin/mirrors/{seed['mirror_id']}/sync",
        headers=auth_header(seed["users"]["readonly"]),
    )
    assert resp.status_code == 403

    after = len(db_session.execute(select(SyncJob)).scalars().all())
    assert after == before


async def test_denied_user_creation_creates_no_user(client, seed, db_session):
    before = len(db_session.execute(select(User)).scalars().all())

    resp = await client.post(
        "/api/admin/users",
        headers=auth_header(seed["users"]["operator"]),
        json={"username": "smuggled-in", "password": "a-sufficiently-long-password",
              "role": "admin"},
    )
    assert resp.status_code == 403

    assert len(db_session.execute(select(User)).scalars().all()) == before


# ---------------------------------------------------------------------------
# Admin self-protection rules
# ---------------------------------------------------------------------------

async def test_admin_cannot_delete_themselves(client, seed):
    admin = seed["users"]["admin"]
    resp = await client.delete(
        f"/api/admin/users/{admin.id}", headers=auth_header(admin)
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Cannot delete yourself"


async def test_admin_cannot_demote_themselves(client, seed):
    admin = seed["users"]["admin"]
    resp = await client.patch(
        f"/api/admin/users/{admin.id}",
        headers=auth_header(admin),
        json={"role": "readonly"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Cannot demote yourself"


async def test_admin_may_deactivate_themselves(client, seed, db_session):
    """No guard exists for this: an admin can lock themselves out via
    is_active=False, which the self-demotion check does not cover. Asserted as
    current behaviour, not endorsed."""
    admin = seed["users"]["admin"]
    resp = await client.patch(
        f"/api/admin/users/{admin.id}",
        headers=auth_header(admin),
        json={"is_active": False},
    )
    assert resp.status_code == 200
    db_session.refresh(admin)
    assert admin.is_active is False
    assert (await client.get("/api/auth/me", headers=auth_header(admin))).status_code == 401


# ---------------------------------------------------------------------------
# The unauthenticated surface, stated explicitly
# ---------------------------------------------------------------------------

PUBLIC_ENDPOINTS = [
    ("GET", "/"),
    ("GET", "/api/health"),
    ("GET", "/api/mirrors/"),
    ("GET", "/api/mirrors/status/summary"),
    ("GET", "/api/stats/overview"),
    ("GET", "/api/stats/sync-activity"),
    ("GET", "/api/stats/health"),
]


@pytest.mark.parametrize("method,path", PUBLIC_ENDPOINTS, ids=[p for _, p in PUBLIC_ENDPOINTS])
async def test_public_endpoints_need_no_authentication(client, seed, method, path):
    """These routes have no dependency on get_current_user. If one ever gains a
    gate, this test says so; if a new route is added without one, add it here
    deliberately."""
    resp = await client.request(method, path)
    assert resp.status_code == 200, resp.text


async def test_mirror_detail_and_history_are_public(client, seed):
    mirror_id = seed["mirror_id"]
    assert (await client.get(f"/api/mirrors/{mirror_id}")).status_code == 200
    assert (await client.get(f"/api/mirrors/{mirror_id}/sync-history")).status_code == 200
