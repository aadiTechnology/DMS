# ruff: noqa: F811
import re
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import text

from app.core.config import get_settings
from app.services import email as email_service
from tests.test_rbac import PASSWORD, _member, _user, auth, env  # noqa: F401  (fixtures)

GOOGLE_AUD = "google-client-id.apps.example"
MS_AUD = "ms-client-id"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
TID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture(autouse=True)
def sso_setup(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "SSO_GOOGLE_CLIENT_ID", GOOGLE_AUD)
    monkeypatch.setattr(settings, "SSO_MICROSOFT_CLIENT_ID", MS_AUD)
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "outbox")
    monkeypatch.setattr("app.services.sso._signing_key", lambda provider, token: KEY.public_key())
    email_service.OUTBOX.clear()


def google_token(
    email="admin-a@x.test",
    sub="g-123",
    verified=True,
    aud=GOOGLE_AUD,
    iss="https://accounts.google.com",
    key=KEY,
    exp=300,
    **extra,
):
    claims = {
        "iss": iss,
        "aud": aud,
        "sub": sub,
        "email": email,
        "email_verified": verified,
        "iat": int(time.time()),
        "exp": int(time.time()) + exp,
        **extra,
    }
    return jwt.encode(claims, key, algorithm="RS256")


def ms_token(email="admin-a@x.test", sub="m-1", tid=TID, edov=True, iss=None, **extra):
    claims = {
        "iss": iss or f"https://login.microsoftonline.com/{tid}/v2.0",
        "aud": MS_AUD,
        "sub": sub,
        "tid": tid,
        "email": email,
        "exp": int(time.time()) + 300,
        **extra,
    }
    if edov is not None:
        claims["xms_edov"] = edov
    return jwt.encode(claims, KEY, algorithm="RS256")


def sso(env, provider, token, **body):
    return env.client.post(f"/api/v1/auth/sso/{provider}", json={"id_token": token, **body})


def links(env):
    with env.engine.connect() as c:
        return c.execute(text("SELECT provider, subject FROM identity_links")).all()


def test_providers_list_only_configured(env, monkeypatch):
    got = {
        p["provider"]: p["client_id"] for p in env.client.get("/api/v1/auth/sso/providers").json()
    }
    assert got == {"google": GOOGLE_AUD, "microsoft": MS_AUD}
    monkeypatch.setattr(get_settings(), "SSO_MICROSOFT_CLIENT_ID", "")
    assert [p["provider"] for p in env.client.get("/api/v1/auth/sso/providers").json()] == [
        "google"
    ]
    assert sso(env, "microsoft", ms_token()).status_code == 404


def test_google_first_link_then_subject_based_login(env):
    r = sso(env, "google", google_token())
    assert r.status_code == 200
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert env.client.get("/api/v1/auth/me", headers=h).json()["user_id"] == str(env.admin_a)
    assert links(env) == [("google", "g-123")]
    # after linking, the stable subject identifies the person even if the email changes/unverified
    again = sso(env, "google", google_token(email="renamed@example.com", verified=False))
    assert again.status_code == 200
    log = [
        e["action"]
        for e in env.client.get("/api/v1/audit-events", params={"limit": 100}, headers=h).json()
    ]
    assert "auth.sso_linked" in log and log.count("auth.login") == 2


@pytest.mark.parametrize(
    "token_kwargs",
    [
        {"verified": False},  # email not verified by Google
        {"email": "stranger@example.com"},  # no such account
        {"aud": "someone-elses-client"},
        {"exp": -10},
        {"key": OTHER_KEY},  # signature from a different key
        {"iss": "https://evil.example.com"},
    ],
)
def test_bad_google_tokens_are_rejected_without_detail(env, token_kwargs):
    r = sso(env, "google", google_token(**token_kwargs))
    assert r.status_code == 401 and r.json()["detail"] == "Sign-in failed"
    assert links(env) == []


def test_nonce_must_match_when_supplied(env):
    token = google_token(nonce="n-123")
    assert sso(env, "google", token, nonce="n-456").status_code == 401
    assert sso(env, "google", token, nonce="n-123").status_code == 200


def test_garbage_and_alg_none_tokens(env):
    assert sso(env, "google", "x" * 40).status_code == 401
    unsigned = jwt.encode(
        {
            "iss": "https://accounts.google.com",
            "aud": GOOGLE_AUD,
            "sub": "s",
            "exp": int(time.time()) + 300,
            "email": "admin-a@x.test",
            "email_verified": True,
        },
        None,
        algorithm="none",
    )
    assert sso(env, "google", unsigned).status_code == 401


def test_sso_never_creates_accounts_or_enters_without_membership(env):
    with env.engine.begin() as c:
        _user(c, "loner@example.com")  # account exists but belongs to no organization
    assert (
        sso(env, "google", google_token(email="loner@example.com", sub="g-loner")).status_code
        == 401
    )
    assert (
        sso(env, "google", google_token(email="new-person@example.com", sub="g-new")).status_code
        == 401
    )
    with env.engine.connect() as c:
        assert (
            c.execute(
                text("SELECT count(*) FROM users WHERE email='new-person@example.com'")
            ).scalar()
            == 0
        )


def test_link_cannot_be_rebound_and_disabled_users_are_blocked(env):
    assert sso(env, "google", google_token(sub="g-1")).status_code == 200
    assert (
        sso(env, "google", google_token(sub="g-attacker")).status_code == 401
    )  # same email, new subject
    with env.engine.begin() as c:
        c.execute(text("UPDATE users SET status='disabled' WHERE id=:i"), {"i": env.admin_a})
    assert sso(env, "google", google_token(sub="g-1")).status_code == 401


def test_microsoft_requires_domain_verified_email_for_first_link(env):
    assert (
        sso(env, "microsoft", ms_token(edov=None)).status_code == 401
    )  # plain email claim is not trusted
    assert sso(env, "microsoft", ms_token(edov=False)).status_code == 401
    assert (
        sso(
            env, "microsoft", ms_token(iss="https://login.microsoftonline.com/other/v2.0")
        ).status_code
        == 401
    )
    assert sso(env, "microsoft", ms_token()).status_code == 200
    assert links(env) == [("microsoft", f"{TID}:m-1")]
    # already linked: login by subject needs no email claim at all
    assert sso(env, "microsoft", ms_token(email="", edov=None)).status_code == 200
    # same user id in a different Entra tenant is a different identity
    assert (
        sso(
            env, "microsoft", ms_token(tid="99999999-0000-0000-0000-000000000000", edov=None)
        ).status_code
        == 401
    )


def test_multi_organization_user_must_choose(env):
    with env.engine.begin() as c:
        u = _user(c, "both@example.com")
        _member(c, env.ta, u)
        _member(c, env.tb, u)
    t = google_token(email="both@example.com", sub="g-both")
    r = sso(env, "google", t)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "tenant_required"
    ok = sso(env, "google", t, tenant_id=str(env.tb))
    assert ok.status_code == 200
    h = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    assert env.client.get("/api/v1/auth/me", headers=h).json()["tenant_id"] == str(env.tb)


def test_accepting_an_invitation_with_sso_instead_of_a_password(env):
    admin = auth(env, "admin-a@x.test")
    inv = env.client.post(
        "/api/v1/invitations", json={"email": "joiner@example.com", "full_name": "J"}, headers=admin
    )
    assert inv.status_code == 201
    token = re.search(r"token=([\w-]+)", email_service.OUTBOX[0].body).group(1)
    wrong = google_token(email="someone-else@example.com", sub="g-x")
    assert sso(env, "google", wrong, invite_token=token).status_code == 401
    r = sso(
        env, "google", google_token(email="joiner@example.com", sub="g-join"), invite_token=token
    )
    assert r.status_code == 200
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert env.client.get("/api/v1/auth/me", headers=h).json()["tenant_id"] == str(env.ta)
    assert (
        sso(
            env,
            "google",
            google_token(email="joiner@example.com", sub="g-join"),
            invite_token=token,
        ).status_code
        == 401
    )  # link used
    with env.engine.connect() as c:
        pw = c.execute(
            text("SELECT password_hash FROM users WHERE email='joiner@example.com'")
        ).scalar()
    assert pw is None  # no password was ever set; SSO is their only way in
    assert (
        env.client.post(
            "/api/v1/auth/login", json={"email": "joiner@example.com", "password": PASSWORD}
        ).status_code
        == 401
    )


def test_invalid_invite_token_blocks_sso(env):
    assert sso(env, "google", google_token(), invite_token="z" * 30).status_code == 401
