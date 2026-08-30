"""
Authentication lifecycle: login, /me, logout, token blacklisting, expiry.

These tests describe what backend/app/api/auth.py and
backend/app/core/security.py do *today*. Where current behaviour is a weakness
rather than a feature, the test asserts the weakness and says so in its
docstring, so that a later fix breaks the test loudly instead of silently.
"""
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt
from sqlalchemy import select

from app.core.config import settings
from app.core.security import (
    TOKEN_BLACKLIST_PREFIX,
    blacklist_token,
    create_access_token,
    decode_access_token,
    hash_password,
    is_token_blacklisted,
    verify_password,
)
from app.models.audit_log import AuditLog
from app.models.user import User
from tests.conftest import ADMIN_PASSWORD, READONLY_PASSWORD, auth_header, token_for

LOGIN_URL = "/api/auth/token"
ME_URL = "/api/auth/me"
LOGOUT_URL = "/api/auth/logout"


def _decode_raw(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


def _audit_actions(db_session) -> list:
    return [row.action for row in db_session.execute(select(AuditLog)).scalars().all()]


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

async def test_login_success_returns_bearer_token(client, seed):
    resp = await client.post(
        LOGIN_URL,
        data={"username": "alice-admin", "password": ADMIN_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


async def test_login_token_carries_expected_claims(client, seed):
    resp = await client.post(
        LOGIN_URL,
        data={"username": "alice-admin", "password": ADMIN_PASSWORD},
    )
    claims = _decode_raw(resp.json()["access_token"])
    assert claims["sub"] == "alice-admin"
    assert claims["user_id"] == seed["users"]["admin"].id
    assert claims["role"] == "admin"
    assert claims["jti"]
    # Default expiry is JWT_EXPIRY_HOURS (8) from now.
    expires_in = datetime.fromtimestamp(claims["exp"], tz=timezone.utc) - datetime.now(timezone.utc)
    assert timedelta(hours=settings.JWT_EXPIRY_HOURS) - expires_in < timedelta(minutes=1)


async def test_login_stamps_last_login(client, seed, db_session):
    assert seed["users"]["admin"].last_login is None
    resp = await client.post(
        LOGIN_URL,
        data={"username": "alice-admin", "password": ADMIN_PASSWORD},
    )
    assert resp.status_code == 200
    db_session.refresh(seed["users"]["admin"])
    assert seed["users"]["admin"].last_login is not None


async def test_login_success_is_audited(client, seed, db_session):
    await client.post(LOGIN_URL, data={"username": "alice-admin", "password": ADMIN_PASSWORD})
    assert "login_success" in _audit_actions(db_session)


async def test_login_wrong_password_is_401(client, seed):
    resp = await client.post(
        LOGIN_URL,
        data={"username": "alice-admin", "password": "definitely-not-the-password"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Incorrect username or password"


async def test_login_unknown_user_is_401_with_identical_body(client, seed):
    """The *response* does not leak whether the username exists. See the next
    test for the channel that does."""
    wrong_password = await client.post(
        LOGIN_URL,
        data={"username": "alice-admin", "password": "definitely-not-the-password"},
    )
    unknown_user = await client.post(
        LOGIN_URL,
        data={"username": "no-such-person", "password": "definitely-not-the-password"},
    )
    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()


async def test_login_skips_password_hashing_for_unknown_user(client, seed, monkeypatch):
    """Username enumeration via timing, asserted deterministically.

    backend/app/api/auth.py: `if user is None or not verify_password(...)`.
    Python short-circuits `or`, so an unknown username never reaches bcrypt and
    returns in microseconds, while a real username pays ~170ms. Counting calls
    proves the branch without a flaky wall-clock assertion.

    This test documents a real weakness. When the handler is fixed to hash a
    dummy value on the miss path, this test should start failing and be updated
    to assert calls == 1 for both cases.
    """
    calls = []
    real_verify = verify_password

    def counting_verify(plain, hashed):
        calls.append(plain)
        return real_verify(plain, hashed)

    monkeypatch.setattr("app.api.auth.verify_password", counting_verify)

    await client.post(LOGIN_URL, data={"username": "no-such-person", "password": "x"})
    assert calls == [], "unknown username reached bcrypt; the timing oracle may be fixed"

    await client.post(LOGIN_URL, data={"username": "alice-admin", "password": "x"})
    assert len(calls) == 1, "known username must reach bcrypt"


async def test_failed_login_is_audited_with_attempted_username(client, seed, db_session):
    await client.post(LOGIN_URL, data={"username": "no-such-person", "password": "x"})
    logs = db_session.execute(
        select(AuditLog).where(AuditLog.action == "login_failed")
    ).scalars().all()
    assert len(logs) == 1
    assert logs[0].user_id is None
    assert logs[0].details == {"username": "no-such-person"}


async def test_login_disabled_user_gets_a_distinguishable_error(client, seed, db_session):
    """A second enumeration oracle, asserted as it currently behaves.

    is_active is checked *after* the password is verified, so a caller holding
    valid credentials for a disabled account gets "User account is disabled"
    instead of "Incorrect username or password". That confirms both the username
    and the password to anyone probing.
    """
    user = seed["users"]["readonly"]
    user.is_active = False
    db_session.commit()

    resp = await client.post(
        LOGIN_URL,
        data={"username": user.username, "password": READONLY_PASSWORD},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "User account is disabled"


async def test_login_disabled_user_with_wrong_password_gets_generic_error(client, seed, db_session):
    user = seed["users"]["readonly"]
    user.is_active = False
    db_session.commit()

    resp = await client.post(LOGIN_URL, data={"username": user.username, "password": "nope"})
    assert resp.json()["detail"] == "Incorrect username or password"


@pytest.mark.parametrize(
    "payload",
    [
        {"username": "alice-admin"},
        {"password": ADMIN_PASSWORD},
        {},
    ],
    ids=["no-password", "no-username", "empty"],
)
async def test_login_requires_both_form_fields(client, seed, payload):
    resp = await client.post(LOGIN_URL, data=payload)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /auth/me
# ---------------------------------------------------------------------------

async def test_me_returns_the_authenticated_user(client, seed):
    user = seed["users"]["operator"]
    resp = await client.get(ME_URL, headers=auth_header(user))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["username"] == user.username
    assert body["role"] == "operator"
    assert body["is_active"] is True
    assert "password_hash" not in body


async def test_me_without_a_token_is_401(client, seed):
    resp = await client.get(ME_URL)
    assert resp.status_code == 401


@pytest.mark.parametrize(
    "header",
    [
        {"Authorization": "Bearer not-a-jwt"},
        {"Authorization": "Bearer "},
        {"Authorization": "Basic YWxpY2U6c2VjcmV0"},
        {"Authorization": "alice-admin"},
    ],
    ids=["garbage", "empty-bearer", "basic-auth", "no-scheme"],
)
async def test_me_rejects_malformed_authorization(client, seed, header):
    resp = await client.get(ME_URL, headers=header)
    assert resp.status_code == 401


async def test_me_rejects_token_signed_with_another_key(client, seed):
    forged = jwt.encode(
        {
            "sub": "alice-admin",
            "user_id": seed["users"]["admin"].id,
            "role": "admin",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "jti": "forged",
        },
        "an-attacker-controlled-key",
        algorithm=settings.JWT_ALGORITHM,
    )
    resp = await client.get(ME_URL, headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401


async def test_me_rejects_expired_token(client, seed):
    header = auth_header(seed["users"]["admin"], expires_delta=timedelta(seconds=-30))
    resp = await client.get(ME_URL, headers=header)
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Could not validate credentials"


async def test_me_rejects_token_for_user_disabled_after_issue(client, seed, db_session):
    user = seed["users"]["readonly"]
    header = auth_header(user)
    assert (await client.get(ME_URL, headers=header)).status_code == 200

    user.is_active = False
    db_session.commit()

    assert (await client.get(ME_URL, headers=header)).status_code == 401


async def test_me_rejects_token_for_user_deleted_after_issue(client, seed, db_session):
    user = seed["users"]["victim"]
    header = auth_header(user)
    assert (await client.get(ME_URL, headers=header)).status_code == 200

    db_session.delete(user)
    db_session.commit()

    assert (await client.get(ME_URL, headers=header)).status_code == 401


# ---------------------------------------------------------------------------
# Logout and the blacklist
# ---------------------------------------------------------------------------

async def test_logout_blacklists_the_jti(client, seed, fake_redis):
    token = token_for(seed["users"]["admin"])
    jti = _decode_raw(token)["jti"]
    header = {"Authorization": f"Bearer {token}"}

    resp = await client.post(LOGOUT_URL, headers=header)
    assert resp.status_code == 200
    assert resp.json() == {"message": "Successfully logged out"}
    assert f"{TOKEN_BLACKLIST_PREFIX}{jti}" in fake_redis.store


async def test_blacklisted_token_is_rejected_everywhere(client, seed):
    header = auth_header(seed["users"]["admin"])
    assert (await client.get(ME_URL, headers=header)).status_code == 200

    await client.post(LOGOUT_URL, headers=header)

    assert (await client.get(ME_URL, headers=header)).status_code == 401
    assert (await client.get("/api/admin/users", headers=header)).status_code == 401
    assert (await client.post(LOGOUT_URL, headers=header)).status_code == 401


async def test_logout_ttl_tracks_remaining_token_life(client, seed, fake_redis):
    """The blacklist entry must outlive the token, or a revoked token becomes
    valid again once Redis forgets it."""
    token = token_for(seed["users"]["admin"], expires_delta=timedelta(minutes=30))
    jti = _decode_raw(token)["jti"]

    await client.post(LOGOUT_URL, headers={"Authorization": f"Bearer {token}"})

    ttl = fake_redis.ttls[f"{TOKEN_BLACKLIST_PREFIX}{jti}"]
    assert 29 * 60 <= ttl <= 30 * 60


async def test_logout_is_audited(client, seed, db_session):
    await client.post(LOGOUT_URL, headers=auth_header(seed["users"]["admin"]))
    assert "logout" in _audit_actions(db_session)


async def test_logout_without_a_token_is_401(client, seed):
    assert (await client.post(LOGOUT_URL)).status_code == 401


async def test_logout_of_another_users_token_does_not_affect_them(client, seed, fake_redis):
    admin_header = auth_header(seed["users"]["admin"])
    operator_header = auth_header(seed["users"]["operator"])

    await client.post(LOGOUT_URL, headers=admin_header)

    assert (await client.get(ME_URL, headers=admin_header)).status_code == 401
    assert (await client.get(ME_URL, headers=operator_header)).status_code == 200


# ---------------------------------------------------------------------------
# Unit-level: security.py
# ---------------------------------------------------------------------------

def test_hash_password_is_salted_and_verifiable():
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")
    assert first != second, "bcrypt must salt each hash"
    assert verify_password("correct horse battery staple", first)
    assert verify_password("correct horse battery staple", second)
    assert not verify_password("Correct Horse Battery Staple", first)


def test_decode_access_token_round_trips():
    token = create_access_token({"sub": "alice", "user_id": 1, "role": "admin"})
    data = decode_access_token(token)
    assert data is not None
    assert (data.username, data.user_id, data.role) == ("alice", 1, "admin")
    assert data.jti


@pytest.mark.parametrize(
    "token_factory",
    [
        lambda: "not-a-jwt",
        lambda: create_access_token(
            {"sub": "alice", "user_id": 1, "role": "admin"},
            expires_delta=timedelta(seconds=-1),
        ),
        lambda: jwt.encode(
            {"sub": "alice", "user_id": 1, "role": "admin", "exp": 9999999999},
            "wrong-key",
            algorithm=settings.JWT_ALGORITHM,
        ),
    ],
    ids=["malformed", "expired", "wrong-signing-key"],
)
def test_decode_access_token_returns_none_for_bad_tokens(token_factory):
    assert decode_access_token(token_factory()) is None


@pytest.mark.parametrize("missing", ["sub", "user_id"])
def test_decode_access_token_returns_none_when_required_claim_absent(missing):
    claims = {
        "sub": "alice",
        "user_id": 1,
        "role": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "jti": "abc",
    }
    del claims[missing]
    token = jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    assert decode_access_token(token) is None


async def test_blacklist_token_ignores_already_expired_expiry(fake_redis):
    """blacklist_token computes `ttl = exp - now` and skips the write when it is
    not positive. Harmless (the token is already rejected on expiry) but it
    means the blacklist is not a complete record of revocations."""
    past = datetime.now(timezone.utc) - timedelta(seconds=5)
    await blacklist_token(fake_redis, "some-jti", past)
    assert fake_redis.store == {}
    assert await is_token_blacklisted(fake_redis, "some-jti") is False


async def test_is_token_blacklisted_reflects_writes(fake_redis):
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    assert await is_token_blacklisted(fake_redis, "jti-1") is False
    await blacklist_token(fake_redis, "jti-1", future)
    assert await is_token_blacklisted(fake_redis, "jti-1") is True


async def test_seeded_user_password_hashes_are_real_bcrypt(seed, db_session):
    """Guards the cached_hash fixture helper: the suite must not accidentally
    start storing plaintext."""
    user = db_session.execute(
        select(User).where(User.username == "alice-admin")
    ).scalar_one()
    assert user.password_hash.startswith("$2")
    assert verify_password(ADMIN_PASSWORD, user.password_hash)
