"""Authentication logic. Functions take an open dms_auth session and return result objects;
the caller commits (so failed-login counters persist) and then turns results into HTTP errors.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import (
    create_access_token,
    hash_token,
    new_refresh_token,
    verify_password,
)
from app.db.models import Tenant, TenantMembership, User, UserSession


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "bearer"


@dataclass
class AuthResult:
    status: str  # ok | invalid | tenant_required
    tokens: TokenPair | None = None
    tenants: list[dict] = field(default_factory=list)


def _now() -> datetime:
    return datetime.now(UTC)


def _issue(db: Session, settings: Settings, user_id, tenant_id) -> TokenPair:
    refresh = new_refresh_token()
    row = UserSession(
        user_id=user_id,
        tenant_id=tenant_id,
        refresh_hash=hash_token(refresh),
        expires_at=_now() + timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS),
    )
    db.add(row)
    db.flush()
    access = create_access_token(settings, user_id, tenant_id, row.id)
    return TokenPair(access, refresh, settings.ACCESS_TOKEN_TTL_MINUTES * 60)


def _active_memberships(db: Session, user_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
    rows = db.execute(
        select(Tenant.id, Tenant.name)
        .join(TenantMembership, TenantMembership.tenant_id == Tenant.id)
        .where(
            TenantMembership.user_id == user_id,
            TenantMembership.status == "active",
            Tenant.status == "active",
        )
        .order_by(Tenant.name)
    ).all()
    return [(r.id, r.name) for r in rows]


def login(
    db: Session, settings: Settings, email: str, password: str, tenant_id: uuid.UUID | None
) -> AuthResult:
    now = _now()
    user = db.scalars(select(User).where(func.lower(User.email) == email.strip().lower())).first()
    locked = bool(user and user.locked_until and user.locked_until > now)
    # Always verify (dummy hash when absent) so timing does not reveal account existence.
    valid = verify_password(user.password_hash if user else None, password)
    if user is None or locked or user.status != "active":
        return AuthResult("invalid")
    if not valid:
        user.failed_login_count += 1
        if user.failed_login_count >= settings.LOGIN_MAX_FAILURES:
            user.locked_until = now + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
            user.failed_login_count = 0
        return AuthResult("invalid")

    tenants = _active_memberships(db, user.id)
    if not tenants:
        return AuthResult("invalid")
    if tenant_id is not None:
        if tenant_id not in {t[0] for t in tenants}:
            return AuthResult("invalid")
    elif len(tenants) > 1:
        return AuthResult("tenant_required", tenants=[{"id": t[0], "name": t[1]} for t in tenants])
    else:
        tenant_id = tenants[0][0]

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    return AuthResult("ok", tokens=_issue(db, settings, user.id, tenant_id))


def refresh(db: Session, settings: Settings, refresh_token: str) -> AuthResult:
    now = _now()
    digest = hash_token(refresh_token)
    session = db.scalars(select(UserSession).where(UserSession.refresh_hash == digest)).first()
    if session is None:
        # A previously rotated token being replayed means it may have been stolen: kill the session.
        stale = db.scalars(
            select(UserSession).where(UserSession.prev_refresh_hash == digest)
        ).first()
        if stale is not None and stale.revoked_at is None:
            stale.revoked_at, stale.revoked_reason = now, "refresh_reuse"
        return AuthResult("invalid")
    if session.revoked_at is not None or session.expires_at <= now:
        return AuthResult("invalid")
    if not is_session_usable(db, session.id):
        session.revoked_at, session.revoked_reason = now, "access_removed"
        return AuthResult("invalid")

    new_refresh = new_refresh_token()
    session.prev_refresh_hash = session.refresh_hash
    session.refresh_hash = hash_token(new_refresh)
    session.last_used_at = now
    access = create_access_token(settings, session.user_id, session.tenant_id, session.id)
    return AuthResult(
        "ok", tokens=TokenPair(access, new_refresh, settings.ACCESS_TOKEN_TTL_MINUTES * 60)
    )


def is_session_usable(db: Session, session_id: uuid.UUID) -> bool:
    """Session live, user active and membership active (checked on every request)."""
    row = db.execute(
        select(UserSession.id)
        .join(User, User.id == UserSession.user_id)
        .join(
            TenantMembership,
            (TenantMembership.user_id == UserSession.user_id)
            & (TenantMembership.tenant_id == UserSession.tenant_id),
        )
        .join(Tenant, Tenant.id == UserSession.tenant_id)
        .where(
            UserSession.id == session_id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > func.now(),
            User.status == "active",
            TenantMembership.status == "active",
            Tenant.status == "active",
        )
    ).first()
    return row is not None


def logout(db: Session, session_id: uuid.UUID) -> None:
    session = db.get(UserSession, session_id)
    if session is not None and session.revoked_at is None:
        session.revoked_at, session.revoked_reason = _now(), "logout"
