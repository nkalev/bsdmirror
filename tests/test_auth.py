"""
Authentication lifecycle: login, /me, logout, token blacklisting, expiry.

These tests describe what backend/app/api/auth.py and
backend/app/core/security.py do *today*. Where current behaviour is a weakness
rather than a feature, the test asserts the weakness and says so in its
docstring, so that a later fix breaks the test loudly instead of silently.

Three such tests have now been through that cycle. They asserted, in order, that
an unknown username skipped bcrypt, that a disabled account got its own error
message, and that a failed login's audit row carried only the username. All
three were rewritten -- not deleted -- when the login handler was fixed; each
says what changed and why. See `test_login_does_equal_bcrypt_work_*`,
`test_login_disabled_user_is_indistinguishable_from_wrong_password` and
`test_failed_login_is_audited_with_attempted_username`.
"""
import asyncio
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt
from sqlalchemy import select

import app.core.security as security_module
from app.core.config import settings
from app.core.security import (
    TOKEN_BLACKLIST_PREFIX,
    blacklist_token,
    create_access_token,
    decode_access_token,
    hash_password,
    hash_password_async,
    is_token_blacklisted,
    verify_password,
    verify_password_async,
)
from shared.models import AuditLog, User
from tests.conftest import ADMIN_PASSWORD, READONLY_PASSWORD, auth_header, token_for

LOGIN_URL = "/api/auth/token"
ME_URL = "/api/auth/me"
LOGOUT_URL = "/api/auth/logout"


def _decode_raw(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


def _audit_actions(db_session) -> list:
    return [row.action for row in db_session.execute(select(AuditLog)).scalars().all()]


class _BcryptSpy:
    """Records every bcrypt.checkpw the handler makes: which digest it was
    given, and on which thread.

    Patched at `bcrypt.checkpw` rather than at `verify_password`, because the
    property under test is about the bcrypt work itself. Patching the wrapper
    would still pass if the wrapper stopped calling bcrypt.
    """

    def __init__(self, monkeypatch):
        self.digests: list = []
        self.threads: list = []
        real = security_module.bcrypt.checkpw

        def spy(plain: bytes, digest: bytes) -> bool:
            self.digests.append(digest.decode())
            self.threads.append(threading.get_ident())
            return real(plain, digest)

        monkeypatch.setattr(security_module.bcrypt, "checkpw", spy)

    @property
    def calls(self) -> int:
        return len(self.digests)

    @property
    def cost_factors(self) -> list:
        # "$2b$12$<22-char salt><31-char digest>" -> "2b$12"
        return [d[1:6] for d in self.digests]


@pytest.fixture
def bcrypt_spy(monkeypatch) -> _BcryptSpy:
    return _BcryptSpy(monkeypatch)


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


async def test_login_does_equal_bcrypt_work_for_unknown_and_known_usernames(
    client, seed, bcrypt_spy
):
    """Username enumeration via timing, asserted deterministically.

    WAS `test_login_skips_password_hashing_for_unknown_user`, which asserted the
    opposite: that an unknown username reached bcrypt zero times. That was true
    of `if user is None or not verify_password(...)` -- `or` short-circuits, so
    the miss path returned in microseconds while the hit path paid ~0.2s, and
    the difference was readable over the network.

    auth.py now passes `user.password_hash if user is not None else None` into
    verify_password_async, which substitutes a dummy digest rather than skipping
    the comparison. Both paths now do exactly one checkpw.

    Counting calls, not wall-clock: same determinism as the original, no
    flakiness on a loaded machine. The cost-factor assertion is the other half
    of the property -- one call each is worthless if the dummy is cheaper than a
    real hash, which is why the dummy is built with gensalt() rather than
    hardcoded.
    """
    await client.post(LOGIN_URL, data={"username": "no-such-person", "password": "x"})
    assert bcrypt_spy.calls == 1, "unknown username must still reach bcrypt"

    await client.post(LOGIN_URL, data={"username": "alice-admin", "password": "x"})
    assert bcrypt_spy.calls == 2, "known username must reach bcrypt exactly once"

    miss_digest, hit_digest = bcrypt_spy.digests
    assert miss_digest != hit_digest, "the miss path must not be handed a real user's hash"
    assert bcrypt_spy.cost_factors[0] == bcrypt_spy.cost_factors[1], (
        f"dummy digest cost {bcrypt_spy.cost_factors[0]} differs from the stored "
        f"hash cost {bcrypt_spy.cost_factors[1]}; the timing oracle is back, inverted"
    )


async def test_login_does_equal_bcrypt_work_for_disabled_and_active_users(
    client, seed, db_session, bcrypt_spy
):
    """The disabled-account path must not be cheap either.

    Folding is_active into the same decision as the password would be a
    regression if it were checked *before* bcrypt: a disabled account would then
    answer faster than an enabled one, trading one oracle for another.
    """
    disabled = seed["users"]["readonly"]
    disabled.is_active = False
    db_session.commit()

    await client.post(
        LOGIN_URL, data={"username": disabled.username, "password": READONLY_PASSWORD}
    )
    assert bcrypt_spy.calls == 1

    await client.post(LOGIN_URL, data={"username": "alice-admin", "password": ADMIN_PASSWORD})
    assert bcrypt_spy.calls == 2


async def test_failed_login_is_audited_with_attempted_username(client, seed, db_session):
    """CHANGED: `details` now carries a `reason` alongside the username.

    The response was made uniform across unknown-user, wrong-password and
    disabled-account, which removed the only signal an operator had for telling
    a credential-stuffing run from one user fat-fingering a password. That
    signal moved to the audit row, which is admin-only and therefore not an
    oracle. `user_id` stays None on purpose -- see the comment at the call site.
    """
    await client.post(LOGIN_URL, data={"username": "no-such-person", "password": "x"})
    logs = db_session.execute(
        select(AuditLog).where(AuditLog.action == "login_failed")
    ).scalars().all()
    assert len(logs) == 1
    assert logs[0].user_id is None
    assert logs[0].details == {"username": "no-such-person", "reason": "unknown_user"}


@pytest.mark.parametrize(
    "username, password, expected_reason",
    [
        ("no-such-person", "irrelevant", "unknown_user"),
        ("alice-admin", "definitely-not-the-password", "bad_password"),
        ("rita-readonly", READONLY_PASSWORD, "account_disabled"),
    ],
    ids=["unknown-user", "bad-password", "account-disabled"],
)
async def test_failed_login_audit_records_why(
    client, seed, db_session, username, password, expected_reason
):
    seed["users"]["readonly"].is_active = False
    db_session.commit()

    await client.post(LOGIN_URL, data={"username": username, "password": password})

    log = db_session.execute(
        select(AuditLog).where(AuditLog.action == "login_failed")
    ).scalars().one()
    assert log.details["reason"] == expected_reason


async def test_login_disabled_user_is_indistinguishable_from_wrong_password(
    client, seed, db_session
):
    """The second enumeration oracle, asserted as fixed.

    WAS `test_login_disabled_user_gets_a_distinguishable_error`, which asserted
    that valid credentials on a disabled account returned "User account is
    disabled". is_active was checked *after* the password, so that message
    confirmed both a valid username and a valid password to a prober -- strictly
    more than a wrong password revealed.

    auth.py now folds is_active into the same decision and returns the same
    401 body, the same headers and the same status as any other failure. This
    test compares the two responses field by field rather than asserting a
    literal string, so a future change to the wording cannot make them diverge
    unnoticed.
    """
    user = seed["users"]["readonly"]
    user.is_active = False
    db_session.commit()

    disabled = await client.post(
        LOGIN_URL,
        data={"username": user.username, "password": READONLY_PASSWORD},
    )
    wrong_password = await client.post(
        LOGIN_URL,
        data={"username": "alice-admin", "password": "definitely-not-the-password"},
    )

    assert disabled.status_code == wrong_password.status_code == 401
    assert disabled.json() == wrong_password.json() == {
        "detail": "Incorrect username or password"
    }
    assert (
        disabled.headers.get("www-authenticate")
        == wrong_password.headers.get("www-authenticate")
        == "Bearer"
    )


async def test_login_disabled_user_with_wrong_password_gets_generic_error(client, seed, db_session):
    user = seed["users"]["readonly"]
    user.is_active = False
    db_session.commit()

    resp = await client.post(LOGIN_URL, data={"username": user.username, "password": "nope"})
    assert resp.json()["detail"] == "Incorrect username or password"


async def test_all_login_failures_share_one_response(client, seed, db_session):
    """The whole oracle surface in one assertion: every way to fail must produce
    a byte-identical body, so that nothing about which field was wrong leaks."""
    seed["users"]["readonly"].is_active = False
    db_session.commit()

    attempts = [
        ("no-such-person", "whatever"),                     # unknown username
        ("alice-admin", "definitely-not-the-password"),     # known user, bad password
        ("rita-readonly", READONLY_PASSWORD),               # valid creds, disabled
        ("rita-readonly", "definitely-not-the-password"),   # bad password, disabled
        ("ALICE-ADMIN", ADMIN_PASSWORD),                    # case-mismatched username
    ]
    responses = [
        await client.post(LOGIN_URL, data={"username": u, "password": p}) for u, p in attempts
    ]

    assert {r.status_code for r in responses} == {401}
    assert len({r.text for r in responses}) == 1, [r.text for r in responses]


async def test_login_still_401s_for_real_admin_with_wrong_password(client, seed):
    """scripts/deploy.sh gates every production deploy on this exact request:
    a POST to /api/auth/token with the real ADMIN_USERNAME and a random
    password, expecting 401. It reads 200 as "authentication is broken open"
    and 5xx as "bcrypt raised". This test pins that contract so a future change
    to the login handler cannot quietly break the deploy gate."""
    resp = await client.post(
        LOGIN_URL,
        data={"username": "alice-admin", "password": "deploy-verify-0123456789abcdef"},
    )
    assert resp.status_code == 401


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

async def test_login_runs_bcrypt_off_the_event_loop(client, seed, bcrypt_spy):
    """bcrypt must not execute on the event loop thread.

    Deterministic, not timed: the spy records threading.get_ident() inside
    checkpw, and the assertion is that it differs from the thread running the
    coroutine. A ~0.2s CPU burn on the loop thread stalls every other in-flight
    request on the worker, which is the actual defect; "ran somewhere else" is
    the property that fixes it, and it is observable exactly.
    """
    loop_thread = threading.get_ident()

    resp = await client.post(
        LOGIN_URL, data={"username": "alice-admin", "password": ADMIN_PASSWORD}
    )

    assert resp.status_code == 200, resp.text
    assert bcrypt_spy.calls == 1
    assert bcrypt_spy.threads[0] != loop_thread, (
        "bcrypt.checkpw ran on the event loop thread; verify_password_async is "
        "no longer offloading"
    )


async def test_create_user_runs_bcrypt_off_the_event_loop(client, seed, monkeypatch):
    """The same defect on the user-creation path. hash_password was called
    straight from `async def create_user` (admin.py) and from the lifespan
    admin-seeding block (main.py)."""
    loop_thread = threading.get_ident()
    threads = []
    real_hashpw = security_module.bcrypt.hashpw

    def spy(password, salt):
        threads.append(threading.get_ident())
        return real_hashpw(password, salt)

    monkeypatch.setattr(security_module.bcrypt, "hashpw", spy)

    resp = await client.post(
        "/api/admin/users",
        headers=auth_header(seed["users"]["admin"]),
        json={
            "username": "newcomer",
            "email": "newcomer@example.test",
            "password": "a-perfectly-fine-password",
            "role": "readonly",
        },
    )

    assert resp.status_code == 201, resp.text
    assert threads == [t for t in threads if t != loop_thread] and threads, (
        "bcrypt.hashpw ran on the event loop thread"
    )


async def test_event_loop_keeps_running_during_a_login():
    """Same property from the other side: while the bcrypt work is in flight,
    other coroutines still get scheduled.

    The thread-identity test above proves the offload structurally; this one
    proves the consequence that matters. bcrypt is replaced with a plain
    time.sleep so the duration is fixed rather than machine-dependent, and the
    tick threshold is set at ~1/5 of the ticks a free loop would manage, so the
    only way to fail is a genuinely blocked loop (which scores 0 or 1).
    """
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.005)
            ticks += 1

    def slow_blocking_call(_plain, _digest):
        time.sleep(0.25)
        return False

    task = asyncio.ensure_future(ticker())
    try:
        await asyncio.get_running_loop().run_in_executor(None, slow_blocking_call, "a", "b")
    finally:
        task.cancel()

    assert ticks >= 10, f"event loop only ticked {ticks} times during a 0.25s offload"


async def test_verify_password_async_matches_the_blocking_primitive():
    digest = hash_password("correct horse battery staple")
    assert await verify_password_async("correct horse battery staple", digest) is True
    assert await verify_password_async("wrong horse", digest) is False


async def test_verify_password_async_returns_false_for_a_missing_hash():
    """The None branch: no user, no stored hash, still one bcrypt comparison,
    and it can never come back True."""
    assert await verify_password_async("anything at all", None) is False


async def test_verify_password_async_hashes_even_when_there_is_no_user(monkeypatch):
    calls = []
    real = security_module.bcrypt.checkpw

    def spy(plain, digest):
        calls.append(digest.decode())
        return real(plain, digest)

    monkeypatch.setattr(security_module.bcrypt, "checkpw", spy)

    await verify_password_async("anything at all", None)

    assert len(calls) == 1
    assert calls[0] == security_module._DUMMY_BCRYPT_DIGEST


def test_dummy_digest_is_a_real_bcrypt_hash_of_an_unknown_secret():
    """If the dummy were a fixed literal, or not a bcrypt hash at all, the miss
    path would either be forgeable or would raise instead of comparing."""
    digest = security_module._DUMMY_BCRYPT_DIGEST
    assert digest.startswith("$2")
    assert len(digest) == 60
    # Its plaintext is discarded at import. Nothing a caller can send verifies.
    for guess in ["", "password", digest, "admin"]:
        assert verify_password(guess, digest) is False


def test_dummy_digest_cost_matches_freshly_written_hashes():
    """The dummy is only a timing equaliser if it costs the same as the hashes
    the app writes. A hardcoded literal would drift the day bcrypt's default
    cost moves; gensalt() cannot."""
    fresh = hash_password("some new user's password")
    assert security_module._DUMMY_BCRYPT_DIGEST[:7] == fresh[:7]


async def test_hash_password_async_produces_a_verifiable_salted_hash():
    first = await hash_password_async("correct horse battery staple")
    second = await hash_password_async("correct horse battery staple")
    assert first != second
    assert verify_password("correct horse battery staple", first)


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
