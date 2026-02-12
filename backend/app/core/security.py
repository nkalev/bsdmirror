"""
Security utilities for authentication and authorization.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Token blacklist key prefix for Redis
TOKEN_BLACKLIST_PREFIX = "token_blacklist:"


class TokenData(BaseModel):
    """JWT token payload data."""
    username: str
    user_id: int
    role: str
    exp: datetime
    jti: str


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)


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
