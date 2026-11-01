import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from app.core.config import get_settings
from app.core.ratelimit import limit_auth_requests
from app.core.security import MAX_PASSWORD_LENGTH
from app.core.tenancy import Principal, get_principal
from app.db.tenant_session import auth_session
from app.services import auth as auth_service
from app.services import email as email_service
from app.services import onboarding

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])

INVALID = "Invalid email or password"


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    tenant_id: uuid.UUID | None = None
    mfa_code: str | None = Field(None, max_length=32)


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=200)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


class MeOut(BaseModel):
    user_id: uuid.UUID
    tenant_id: uuid.UUID


def _tokens(result: auth_service.AuthResult) -> TokenOut:
    t = result.tokens
    return TokenOut(
        access_token=t.access_token,
        refresh_token=t.refresh_token,
        token_type=t.token_type,
        expires_in=t.expires_in,
    )


@router.post("/login", response_model=TokenOut, dependencies=[Depends(limit_auth_requests)])
def login(body: LoginIn):
    # Commit happens when the session block exits, so failed-login counters persist.
    with auth_session() as db:
        result = auth_service.login(
            db, get_settings(), body.email, body.password, body.tenant_id, body.mfa_code
        )
    if result.status == "tenant_required":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "tenant_required",
                "tenants": [{"id": str(t["id"]), "name": t["name"]} for t in result.tenants],
            },
        )
    if result.status == "mfa_required":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"code": "mfa_required"})
    if result.status != "ok":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=INVALID)
    return _tokens(result)


@router.post("/refresh", response_model=TokenOut, dependencies=[Depends(limit_auth_requests)])
def refresh(body: RefreshIn):
    with auth_session() as db:
        result = auth_service.refresh(db, get_settings(), body.refresh_token)
    if result.status != "ok":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")
    return _tokens(result)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(principal: Principal = Depends(get_principal)):
    with auth_session() as db:
        auth_service.logout(db, principal.session_id)


@router.get("/me", response_model=MeOut)
def me(principal: Principal = Depends(get_principal)):
    return MeOut(user_id=principal.user_id, tenant_id=principal.tenant_id)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    new_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(limit_auth_requests)],
)
def change_password(body: ChangePasswordIn, principal: Principal = Depends(get_principal)):
    """Signed-in password change. Needs the current password; signs out the other sessions."""
    try:
        with auth_session() as db:
            auth_service.change_password(
                db,
                principal.user_id,
                principal.session_id,
                body.current_password,
                body.new_password,
            )
    except auth_service.PasswordError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None


# ---- onboarding and recovery (public; every answer is deliberately uniform) ---------------

GENERIC_LINK_ERROR = "This link is invalid or has expired"


class AcceptInviteIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str | None = Field(None, max_length=MAX_PASSWORD_LENGTH)


class ForgotIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)  # lookup only; no format oracle


class ResetIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class RegisterIn(BaseModel):
    tenant_slug: str = Field(min_length=1, max_length=63)
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)


@router.post("/accept-invite", response_model=TokenOut, dependencies=[Depends(limit_auth_requests)])
def accept_invite(body: AcceptInviteIn):
    try:
        with auth_session() as db:
            tokens = onboarding.accept_invitation(db, get_settings(), body.token, body.password)
    except onboarding.Invalid as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None
    if tokens is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=GENERIC_LINK_ERROR)
    return TokenOut(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
        expires_in=tokens.expires_in,
    )


@router.post(
    "/forgot-password",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(limit_auth_requests)],
)
def forgot_password(body: ForgotIn, background: BackgroundTasks):
    with auth_session() as db:
        messages = onboarding.request_password_reset(db, get_settings(), body.email)
    background.add_task(email_service.send, messages)
    return {"detail": "If that account exists, an email with instructions has been sent"}


@router.post(
    "/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(limit_auth_requests)],
)
def reset_password(body: ResetIn):
    try:
        with auth_session() as db:
            ok = onboarding.reset_password(db, body.token, body.password)
    except onboarding.Invalid as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None
    if not ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=GENERIC_LINK_ERROR)


@router.post(
    "/register",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(limit_auth_requests)],
)
def register(body: RegisterIn):
    """Request to join an organization that allows self-registration. Same answer always."""
    with auth_session() as db:
        onboarding.submit_registration(db, body.tenant_slug, body.email, body.full_name)
    return {"detail": "If registration is open, your request was sent to the administrators"}
