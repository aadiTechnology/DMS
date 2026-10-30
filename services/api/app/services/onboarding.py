"""Invitations, password setup/reset and self-registration approval.

Two calling contexts:
- tenant context (dms_app, tenant set): admin actions. Global-table steps run inside
  `acting_as(db, AUTH_ROLE)` so the whole action is one atomic transaction.
- authentication context (dms_auth): public actions that start from an emailed token or a slug.
  Tenant-table steps run inside `acting_as(db, APP_ROLE, tenant_id)`.
Functions return the emails to send; the caller delivers them only after commit.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import (
    hash_password,
    hash_token,
    new_refresh_token,
    validate_password,
)
from app.db.models import (
    AuthToken,
    RegistrationRequest,
    Role,
    Tenant,
    TenantMembership,
    User,
    UserSession,
)
from app.db.rls import APP_ROLE, AUTH_ROLE
from app.db.tenant_session import acting_as
from app.services import audit, org, rbac
from app.services.auth import TokenPair, issue_session
from app.services.email import EmailMessage, invitation_email, password_reset_email
from app.services.org import Conflict, Invalid, NotFound

__all__ = ["Conflict", "Invalid", "NotFound"]

RESET_THROTTLE_SECONDS = 60


def _now() -> datetime:
    return datetime.now(UTC)


def _norm(email: str) -> str:
    return email.strip().lower()


def _issue_token(
    db: Session, purpose: str, user_id, tenant_id, membership_id, ttl: timedelta
) -> str:
    """Create a single-use token (dms_auth context). Older unused tokens of the same kind for the
    same user/membership are invalidated, so only the newest link works."""
    stmt = update(AuthToken).where(
        AuthToken.user_id == user_id, AuthToken.purpose == purpose, AuthToken.used_at.is_(None)
    )
    if membership_id is not None:
        stmt = stmt.where(AuthToken.membership_id == membership_id)
    db.execute(stmt.values(used_at=_now()))
    raw = new_refresh_token()
    db.add(
        AuthToken(
            purpose=purpose,
            user_id=user_id,
            tenant_id=tenant_id,
            membership_id=membership_id,
            token_hash=hash_token(raw),
            expires_at=_now() + ttl,
        )
    )
    db.flush()
    return raw


def _find_token(db: Session, raw: str, purpose: str) -> AuthToken | None:
    row = db.scalars(select(AuthToken).where(AuthToken.token_hash == hash_token(raw))).first()
    if row is None or row.purpose != purpose or row.used_at is not None or row.expires_at <= _now():
        return None
    return row


# ---- admin side (tenant context) --------------------------------------------------------


def invite(
    db: Session,
    settings: Settings,
    tenant_id,
    actor_id,
    *,
    email: str,
    full_name: str,
    role_id=None,
    employee_number: str | None = None,
) -> tuple[TenantMembership, list[EmailMessage]]:
    email = _norm(email)
    if role_id is None:
        role = db.scalars(
            select(Role).where(Role.tenant_id == tenant_id, Role.name == "employee")
        ).first()
    else:
        role = db.get(Role, role_id)
    if role is None or role.tenant_id != tenant_id or role.status != "active":
        raise Invalid("role_id: must be an active role of this organization")

    with acting_as(db, AUTH_ROLE):
        user = db.scalars(select(User).where(func.lower(User.email) == email)).first()
        if user is None:
            user_id = uuid.uuid4()
            db.execute(insert(User.__table__).values(id=user_id, email=email))
        elif user.status != "active":
            raise Invalid("This account is disabled")
        else:
            user_id = user.id

    membership = db.scalars(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id, TenantMembership.user_id == user_id
        )
    ).first()
    if membership is not None and membership.status == "active":
        raise Conflict("That person is already a member of this organization")
    if membership is None:
        membership = TenantMembership(
            tenant_id=tenant_id, user_id=user_id, status="invited", employee_number=employee_number
        )
        db.add(membership)
    else:
        membership.status = "invited"
    db.flush()

    org.upsert_profile(
        db, tenant_id, actor_id, membership.id, {"full_name": full_name, "work_email": email}
    )
    rbac.assign_role(db, tenant_id, actor_id, membership.id, role.id)
    with acting_as(db, AUTH_ROLE):
        raw = _issue_token(
            db,
            "invite",
            user_id,
            tenant_id,
            membership.id,
            timedelta(hours=settings.INVITE_TTL_HOURS),
        )
    org_name = db.get(Tenant, tenant_id).name
    audit.record(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_id,
        action="invitation.created",
        resource_type="employee",
        resource_id=membership.id,
        details={"role": role.name},
    )
    return membership, [invitation_email(settings, email, org_name, raw)]


def resend_invitation(db: Session, settings: Settings, tenant_id, actor_id, membership_id):
    membership = db.get(TenantMembership, membership_id)
    if membership is None or membership.tenant_id != tenant_id or membership.status != "invited":
        raise NotFound("invitation")
    profile = org.get_employee(db, tenant_id, membership_id)[1]
    with acting_as(db, AUTH_ROLE):
        raw = _issue_token(
            db,
            "invite",
            membership.user_id,
            tenant_id,
            membership.id,
            timedelta(hours=settings.INVITE_TTL_HOURS),
        )
    audit.record(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_id,
        action="invitation.resent",
        resource_type="employee",
        resource_id=membership.id,
    )
    return [invitation_email(settings, profile.work_email, db.get(Tenant, tenant_id).name, raw)]


def revoke_invitation(db: Session, tenant_id, actor_id, membership_id) -> None:
    membership = db.get(TenantMembership, membership_id)
    if membership is None or membership.tenant_id != tenant_id or membership.status != "invited":
        raise NotFound("invitation")
    membership.status = "inactive"
    with acting_as(db, AUTH_ROLE):
        db.execute(
            update(AuthToken)
            .where(AuthToken.membership_id == membership_id, AuthToken.used_at.is_(None))
            .values(used_at=_now())
        )
    audit.record(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_id,
        action="invitation.revoked",
        resource_type="employee",
        resource_id=membership_id,
    )


def list_registrations(db: Session, tenant_id, status="pending", limit=50, offset=0):
    stmt = select(RegistrationRequest).where(RegistrationRequest.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(RegistrationRequest.status == status)
    stmt = stmt.order_by(RegistrationRequest.created_at, RegistrationRequest.id)
    return list(db.scalars(stmt.limit(max(1, min(limit, 200))).offset(max(0, offset))))


def decide_registration(
    db: Session, settings: Settings, tenant_id, actor_id, request_id, approve: bool, note=None
) -> list[EmailMessage]:
    row = db.get(RegistrationRequest, request_id)
    if row is None or row.tenant_id != tenant_id:
        raise NotFound("registration request")
    if row.status != "pending":
        raise Conflict("This request was already decided")
    messages: list[EmailMessage] = []
    if approve:
        _, messages = invite(
            db, settings, tenant_id, actor_id, email=row.email, full_name=row.full_name
        )
    row.status = "approved" if approve else "rejected"
    row.decided_at = _now()
    row.decided_by_user_id = actor_id
    row.decision_note = (note or "")[:300] or None
    audit.record(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_id,
        action=f"registration.{row.status}",
        resource_type="registration_request",
        resource_id=row.id,
    )
    return messages


def set_self_registration(db: Session, tenant_id, actor_id, enabled: bool) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if tenant.self_registration_enabled != enabled:
        tenant.self_registration_enabled = enabled
        audit.record(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_id,
            action="tenant.settings.updated",
            resource_type="tenant",
            resource_id=tenant_id,
            details={"self_registration_enabled": enabled},
        )
    return tenant


# ---- public side (authentication context) -----------------------------------------------


def accept_invitation(
    db: Session, settings: Settings, token: str, password: str | None
) -> TokenPair | None:
    """None means the link is invalid, expired, used or revoked (one generic answer)."""
    row = _find_token(db, token, "invite")
    if row is None:
        return None
    user = db.get(User, row.user_id)
    if user is None or user.status != "active":
        return None
    with acting_as(db, APP_ROLE, row.tenant_id):
        membership = db.get(TenantMembership, row.membership_id)
        if membership is None or membership.status != "invited":
            return None
        membership.status = "active"
        audit.record(
            db,
            tenant_id=row.tenant_id,
            actor_user_id=user.id,
            action="invitation.accepted",
            resource_type="employee",
            resource_id=membership.id,
        )
    if user.password_hash is None:
        if not password:
            raise Invalid("A password is required to set up your account")
        try:
            validate_password(password, user.email)
        except ValueError as exc:
            raise Invalid(str(exc)) from None
        user.password_hash = hash_password(password)
    # An existing account keeps its password: an emailed invitation never replaces credentials.
    row.used_at = _now()
    user.last_login_at = _now()
    tokens = issue_session(db, settings, user.id, row.tenant_id)
    audit.record(
        db,
        tenant_id=row.tenant_id,
        actor_user_id=user.id,
        action="auth.login",
        resource_type="session",
        details={"via": "invitation"},
    )
    return tokens


def request_password_reset(db: Session, settings: Settings, email: str) -> list[EmailMessage]:
    """Always succeeds from the caller's view; returns an email only for a real active account."""
    user = db.scalars(select(User).where(func.lower(User.email) == _norm(email))).first()
    if user is None or user.status != "active":
        return []
    recent = db.scalar(
        select(func.count(AuthToken.id)).where(
            AuthToken.user_id == user.id,
            AuthToken.purpose == "password_reset",
            AuthToken.created_at > _now() - timedelta(seconds=RESET_THROTTLE_SECONDS),
        )
    )
    if recent:
        return []
    raw = _issue_token(
        db, "password_reset", user.id, None, None, timedelta(minutes=settings.RESET_TTL_MINUTES)
    )
    return [password_reset_email(settings, user.email, raw)]


def reset_password(db: Session, token: str, password: str) -> bool:
    row = _find_token(db, token, "password_reset")
    if row is None:
        return False
    user = db.get(User, row.user_id)
    if user is None or user.status != "active":
        return False
    try:
        validate_password(password, user.email)
    except ValueError as exc:
        raise Invalid(str(exc)) from None
    user.password_hash = hash_password(password)
    user.failed_login_count = 0
    user.locked_until = None
    row.used_at = _now()
    # A reset signs the person out everywhere.
    db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=_now(), revoked_reason="password_reset")
    )
    tenants = db.scalars(
        select(TenantMembership.tenant_id).where(
            TenantMembership.user_id == user.id, TenantMembership.status == "active"
        )
    ).all()
    for tenant_id in tenants:
        audit.record(
            db,
            tenant_id=tenant_id,
            actor_user_id=user.id,
            action="auth.password_reset",
            resource_type="user",
            resource_id=user.id,
        )
    return True


def submit_registration(db: Session, slug: str, email: str, full_name: str) -> None:
    """Public. Silent on every outcome so tenants, accounts and settings cannot be probed."""
    tenant = db.scalars(
        select(Tenant).where(
            Tenant.slug == slug.strip().lower(),
            Tenant.status == "active",
            Tenant.self_registration_enabled.is_(True),
        )
    ).first()
    if tenant is None:
        return
    email = _norm(email)
    user = db.scalars(select(User).where(func.lower(User.email) == email)).first()
    if user is not None:
        member = db.scalars(
            select(TenantMembership.id).where(
                TenantMembership.tenant_id == tenant.id,
                TenantMembership.user_id == user.id,
                TenantMembership.status.in_(("active", "invited")),
            )
        ).first()
        if member is not None:
            return
    with acting_as(db, APP_ROLE, tenant.id):
        try:
            with db.begin_nested():
                req = RegistrationRequest(
                    tenant_id=tenant.id, email=email, full_name=full_name.strip()
                )
                db.add(req)
                db.flush()
        except IntegrityError:
            return  # already pending
        audit.record(
            db,
            tenant_id=tenant.id,
            actor_user_id=None,
            action="registration.requested",
            resource_type="registration_request",
            resource_id=req.id,
        )
