"""Optional TOTP multi-factor authentication (RFC 6238) with single-use recovery codes.

Applies to password sign-in. SSO sign-in relies on the identity provider's own MFA.
TOTP secrets are encrypted at rest (Fernet); recovery codes are stored hashed.
"""

import base64
import hashlib
import hmac
import logging
import secrets
import struct
import time
from datetime import UTC, datetime

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import hash_token, verify_password
from app.db.models import MfaRecoveryCode, TenantMembership, User
from app.db.rls import AUTH_ROLE
from app.db.tenant_session import acting_as
from app.services import audit
from app.services.org import Conflict, Invalid, NotFound

STEP_SECONDS = 30
DIGITS = 6
WINDOW = 1  # accept one step either side for clock drift
RECOVERY_CODES = 8
ISSUER = "DMS"
logger = logging.getLogger("dms.mfa")


def generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 10**DIGITS:0{DIGITS}d}"


def totp_at(secret: str, timestamp: float) -> str:
    return _hotp(secret, int(timestamp // STEP_SECONDS))


def match_step(secret: str, code: str, last_used_step: int, now: float | None = None) -> int | None:
    """Return the matching time step if `code` is valid and newer than the last accepted step
    (a code cannot be replayed), else None."""
    now = time.time() if now is None else now
    current = int(now // STEP_SECONDS)
    code = code.strip().replace(" ", "")
    for step in range(current - WINDOW, current + WINDOW + 1):
        if step > last_used_step and hmac.compare_digest(_hotp(secret, step), code):
            return step
    return None


def provisioning_uri(secret: str, email: str) -> str:
    return f"otpauth://totp/{ISSUER}:{email}?secret={secret}&issuer={ISSUER}&digits={DIGITS}"


def _fernet(settings: Settings) -> Fernet:
    key = settings.MFA_ENCRYPTION_KEY.encode() if settings.MFA_ENCRYPTION_KEY else None
    if key is None:
        digest = hashlib.sha256(("dms-mfa:" + settings.SECRET_KEY).encode()).digest()
        key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def _encrypt(settings: Settings, secret: str) -> str:
    return _fernet(settings).encrypt(secret.encode()).decode()


def _decrypt(settings: Settings, token: str) -> str:
    return _fernet(settings).decrypt(token.encode()).decode()


def _user_secret(settings: Settings, user: User) -> str | None:
    """Decrypted TOTP secret, or None if absent or unreadable (e.g. the key was rotated)."""
    if not user.mfa_secret_encrypted:
        return None
    try:
        return _decrypt(settings, user.mfa_secret_encrypted)
    except InvalidToken:
        logger.error("cannot decrypt TOTP secret for user %s; check MFA_ENCRYPTION_KEY", user.id)
        return None


def _new_recovery_codes() -> list[str]:
    return [f"{secrets.token_hex(3)}-{secrets.token_hex(3)}" for _ in range(RECOVERY_CODES)]


def begin_setup(db: Session, settings: Settings, user: User) -> tuple[str, str]:
    if user.mfa_enabled:
        raise Conflict("Two-step verification is already on")
    secret = generate_secret()
    user.mfa_secret_encrypted = _encrypt(settings, secret)
    return secret, provisioning_uri(secret, user.email)


def confirm_setup(db: Session, settings: Settings, user: User, code: str) -> list[str]:
    secret = _user_secret(settings, user)
    if user.mfa_enabled or secret is None:
        raise Invalid("Start setup first")
    step = match_step(secret, code, user.mfa_last_used_step)
    if step is None:
        raise Invalid("That code is not correct")
    user.mfa_enabled = True
    user.mfa_last_used_step = step
    db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id))
    codes = _new_recovery_codes()
    db.add_all(MfaRecoveryCode(user_id=user.id, code_hash=hash_token(c)) for c in codes)
    return codes


def verify_second_factor(db: Session, settings: Settings, user: User, code: str) -> bool:
    """Authenticator code first, then a single-use recovery code."""
    secret = _user_secret(settings, user)
    if not user.mfa_enabled or secret is None or not code:
        return False
    step = match_step(secret, code, user.mfa_last_used_step)
    if step is not None:
        user.mfa_last_used_step = step
        return True
    row = db.scalars(
        select(MfaRecoveryCode).where(
            MfaRecoveryCode.user_id == user.id,
            MfaRecoveryCode.code_hash == hash_token(code.strip().lower()),
            MfaRecoveryCode.used_at.is_(None),
        )
    ).first()
    if row is None:
        return False
    row.used_at = datetime.now(UTC)
    return True


def _clear(db: Session, user: User) -> None:
    user.mfa_enabled = False
    user.mfa_secret_encrypted = None
    user.mfa_last_used_step = 0
    db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id))


def disable(db: Session, settings: Settings, user: User, password: str, code: str) -> None:
    """Turning protection off needs both the password and a second factor."""
    if not user.mfa_enabled:
        raise Conflict("Two-step verification is not on")
    if not verify_password(user.password_hash, password) or not verify_second_factor(
        db, settings, user, code
    ):
        raise Invalid("Password or code is not correct")
    _clear(db, user)


def admin_reset(db: Session, tenant_id, actor_id, membership_id) -> None:
    """Help-desk recovery for a lost device; runs in tenant context, audited."""
    membership = db.get(TenantMembership, membership_id)
    if membership is None or membership.tenant_id != tenant_id:
        raise NotFound("employee")
    with acting_as(db, AUTH_ROLE):
        user = db.get(User, membership.user_id)
        _clear(db, user)
    audit.record(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_id,
        action="auth.mfa_reset_by_admin",
        resource_type="employee",
        resource_id=membership_id,
        privileged=True,
    )
