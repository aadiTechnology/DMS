import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import Settings

_hasher = PasswordHasher()
# Verified against when the account does not exist, so response time does not reveal it.
_DUMMY_HASH = _hasher.hash("timing-equalizer-not-a-real-password")

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128
_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Refresh tokens are high-entropy random strings, so a fast hash is appropriate."""
    return hashlib.sha256(token.encode()).hexdigest()


def create_access_token(
    settings: Settings,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    ttl: timedelta | None = None,
) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "sid": str(session_id),
        "iat": now,
        "exp": now
        + (ttl if ttl is not None else timedelta(minutes=settings.ACCESS_TOKEN_TTL_MINUTES)),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=_ALGORITHM)


def decode_access_token(settings: Settings, token: str) -> dict:
    """Raises jwt.PyJWTError for any invalid, expired or tampered token."""
    return jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[_ALGORITHM],
        options={"require": ["exp", "sub", "tid", "sid"]},
    )
