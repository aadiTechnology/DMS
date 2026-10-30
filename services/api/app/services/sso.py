"""Google / Microsoft sign-in by verifying an OpenID Connect ID token on the server.

The client (web or mobile) performs the provider login itself (authorization code + PKCE) and
sends us the ID token. We never accept an identity we have not verified:
signature (provider JWKS), audience (our client id), issuer, expiry, optional nonce.

Account rules (decision recorded in IMPLEMENTATION_STATUS.md, Sprint 7):
- Accounts are never created by SSO; people join by invitation or approved registration.
- A link is keyed on (provider, stable subject), never on email.
- First link requires a *trusted* email matching an active account: Google `email_verified`;
  Microsoft `xms_edov` (domain-owner-verified), because Entra's plain `email` claim can be set
  by an attacker-controlled tenant ("nOAuth").
- One link per provider per user; a different subject can never be re-bound silently.
"""

import hmac
from dataclasses import dataclass
from functools import lru_cache

import jwt
from jwt import PyJWKClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import IdentityLink, TenantMembership, User
from app.services import audit, onboarding
from app.services.auth import AuthResult, finish_login

JWKS = {
    "google": "https://www.googleapis.com/oauth2/v3/certs",
    "microsoft": "https://login.microsoftonline.com/common/discovery/v2.0/keys",
}
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
MS_ISSUER = "https://login.microsoftonline.com/{tid}/v2.0"


class SsoError(Exception):
    """Token or account not acceptable. Callers answer with one generic message."""


class ProviderDisabled(SsoError):
    pass


@dataclass(frozen=True)
class Identity:
    provider: str
    subject: str
    email: str
    email_trusted: bool


def client_id(settings: Settings, provider: str) -> str:
    return {"google": settings.SSO_GOOGLE_CLIENT_ID, "microsoft": settings.SSO_MICROSOFT_CLIENT_ID}[
        provider
    ]


@lru_cache
def _jwks_client(provider: str) -> PyJWKClient:
    return PyJWKClient(JWKS[provider], cache_keys=True, timeout=5)


def _signing_key(provider: str, token: str):
    """Isolated so tests can supply a local key instead of fetching the provider's JWKS."""
    return _jwks_client(provider).get_signing_key_from_jwt(token).key


def verify_id_token(
    settings: Settings, provider: str, token: str, nonce: str | None = None
) -> Identity:
    audience = client_id(settings, provider)
    if not audience:
        raise ProviderDisabled(provider)
    try:
        key = _signing_key(provider, token)
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=audience,
            options={"require": ["exp", "iss", "sub", "aud"]},
        )
    except Exception as exc:  # signature, expiry, audience, key lookup, malformed token
        raise SsoError("invalid token") from exc
    if nonce is not None and not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise SsoError("nonce mismatch")
    email = str(claims.get("email") or "").strip().lower()
    if provider == "google":
        if claims["iss"] not in GOOGLE_ISSUERS:
            raise SsoError("issuer")
        return Identity(provider, str(claims["sub"]), email, claims.get("email_verified") is True)
    tid = claims.get("tid")
    if not tid or claims["iss"] != MS_ISSUER.format(tid=tid):
        raise SsoError("issuer")
    trusted = claims.get("xms_edov") in (True, 1, "1", "true", "True")
    return Identity(provider, f"{tid}:{claims['sub']}", email, trusted)


def sso_login(
    db: Session,
    settings: Settings,
    identity: Identity,
    tenant_id,
    invite_token: str | None = None,
) -> AuthResult:
    """Authentication context. Returns the same results as password login."""
    link = db.scalars(
        select(IdentityLink).where(
            IdentityLink.provider == identity.provider, IdentityLink.subject == identity.subject
        )
    ).first()
    invite = onboarding.find_token(db, invite_token, "invite") if invite_token else None
    if invite_token and invite is None:
        return AuthResult("invalid")

    if link is not None:
        user = db.get(User, link.user_id)
    else:
        if not identity.email_trusted or not identity.email:
            return AuthResult("invalid")
        user = db.scalars(select(User).where(func.lower(User.email) == identity.email)).first()
        if user is None or user.status != "active":
            return AuthResult("invalid")
        has_membership = db.scalars(
            select(TenantMembership.id).where(
                TenantMembership.user_id == user.id, TenantMembership.status == "active"
            )
        ).first()
        if has_membership is None and (invite is None or invite.user_id != user.id):
            return AuthResult("invalid")
        if db.scalars(
            select(IdentityLink.id).where(
                IdentityLink.user_id == user.id, IdentityLink.provider == identity.provider
            )
        ).first():
            return AuthResult("invalid")  # already bound to a different external identity
    if user is None or user.status != "active":
        return AuthResult("invalid")

    if invite is not None:
        if invite.user_id != user.id or not onboarding.activate_invitation(db, invite, user):
            return AuthResult("invalid")
        invite.used_at = func.now()

    result = finish_login(db, settings, user, tenant_id, via=identity.provider)
    if result.status == "invalid":
        return result
    if link is None:
        db.add(
            IdentityLink(
                user_id=user.id,
                provider=identity.provider,
                subject=identity.subject,
                email_at_link=identity.email,
            )
        )
        for (tid,) in db.execute(
            select(TenantMembership.tenant_id).where(
                TenantMembership.user_id == user.id, TenantMembership.status == "active"
            )
        ):
            audit.record(
                db,
                tenant_id=tid,
                actor_user_id=user.id,
                action="auth.sso_linked",
                resource_type="user",
                resource_id=user.id,
                details={"provider": identity.provider},
            )
    else:
        link.last_login_at = func.now()
    return result
