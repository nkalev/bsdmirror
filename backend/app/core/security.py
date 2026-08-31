"""
Security utilities for authentication and authorization.
"""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

import bcrypt
from jose import JWTError, jwt
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)

# Token blacklist key prefix for Redis
TOKEN_BLACKLIST_PREFIX = "token_blacklist:"


class TokenData(BaseModel):
    """JWT token payload data."""
    username: str
    user_id: int
    role: str
    exp: datetime
    jti: str


# ---------------------------------------------------------------------------
# Passwords
#
# Two layers, on purpose:
#
#   verify_password / hash_password        blocking bcrypt primitives.
#   verify_password_async / hash_password_async
#                                          the ONLY forms an `async def` may
#                                          call. They hand the work to a worker
#                                          thread so the event loop keeps
#                                          serving other requests.
#
# bcrypt at cost 12 is ~0.2s of pure CPU. Called directly from a coroutine it
# stalls the whole worker for that long -- every other in-flight request,
# including ones that have nothing to do with authentication. The split is
# enforced by tests/test_async_hygiene.py, which walks the AST of every module
# under backend/app and sync/ and fails if a blocking primitive is called from
# inside an `async def`.
# ---------------------------------------------------------------------------


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash. BLOCKING -- see module note above.

    Deliberately does not catch anything. A malformed stored hash, or a bcrypt
    that no longer speaks the same API, must surface as a 500 rather than as an
    indistinguishable 401: scripts/deploy.sh keys its "authentication still
    works" gate on exactly that difference.
    """
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8")
    )


def hash_password(password: str) -> str:
    """Hash a password using bcrypt. BLOCKING -- see module note above."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


# Digest used when there is no user to compare against, so that a login attempt
# for an unknown username performs the same bcrypt work as one for a known
# username with the wrong password. Without it, `if user is None or not
# verify_password(...)` short-circuits and the miss path returns in microseconds
# while the hit path pays ~0.2s -- a username oracle readable over the network.
#
# Built at import from a random secret that is immediately discarded, so no
# password can ever verify against it. Generated with gensalt() rather than
# hardcoded so its cost factor always tracks the cost of hashes this codebase
# writes; the residual gap is a deployment whose stored hashes predate a change
# in bcrypt's default cost, which no per-user-independent dummy can close.
_DUMMY_BCRYPT_DIGEST = hash_password(secrets.token_urlsafe(32))


async def verify_password_async(
    plain_password: str,
    hashed_password: Optional[str]
) -> bool:
    """Verify a password off the event loop, in constant work.

    `hashed_password` is Optional on purpose. Callers that may not have found a
    user pass None rather than skipping the call: the comparison still runs,
    against `_DUMMY_BCRYPT_DIGEST`, and returns False. Taking None here instead
    of leaving the dummy-hash dance to each caller is what makes the timing
    oracle hard to reintroduce -- there is no "cheap" path to fall into.
    """
    known = hashed_password is not None
    digest = hashed_password if known else _DUMMY_BCRYPT_DIGEST
    matched = await run_in_threadpool(verify_password, plain_password, digest)
    # `and known` is belt-and-braces: the dummy's plaintext was discarded, so
    # `matched` cannot be True on that path, but the return value must not
    # depend on that argument holding.
    return matched and known


async def hash_password_async(password: str) -> str:
    """Hash a password off the event loop."""
    return await run_in_threadpool(hash_password, password)


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None
) -> str:
    """Create a JWT access token with a unique JTI for revocation support."""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRY_HOURS)

    to_encode.update({
        "exp": expire,
        "jti": str(uuid4()),
    })

    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def decode_access_token(token: str) -> Optional[TokenData]:
    """Decode and validate a JWT access token."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        username: str = payload.get("sub")
        user_id: int = payload.get("user_id")
        role: str = payload.get("role")
        exp: datetime = datetime.fromtimestamp(payload.get("exp"), tz=timezone.utc)
        jti: str = payload.get("jti", "")

        if username is None or user_id is None:
            return None

        return TokenData(
            username=username,
            user_id=user_id,
            role=role,
            exp=exp,
            jti=jti
        )
    except JWTError as e:
        logger.warning("JWT decode error", error=str(e))
        return None


async def blacklist_token(redis_client, jti: str, exp: datetime) -> None:
    """Add a token JTI to the blacklist in Redis with TTL matching token expiry."""
    ttl = int((exp - datetime.now(timezone.utc)).total_seconds())
    if ttl > 0:
        await redis_client.setex(f"{TOKEN_BLACKLIST_PREFIX}{jti}", ttl, "1")


async def is_token_blacklisted(redis_client, jti: str) -> bool:
    """Check if a token JTI is in the blacklist."""
    return await redis_client.exists(f"{TOKEN_BLACKLIST_PREFIX}{jti}") > 0
