import uuid
from datetime import timedelta
from types import SimpleNamespace

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core import ratelimit
from app.core.config import DEV_SECRET, Settings, get_settings
from app.core.security import create_access_token, hash_password, hash_token, verify_password
from app.main import app

PASSWORD = "correct-horse-battery"


@pytest.fixture
def env(migrated_engine, monkeypatch):
    monkeypatch.setattr("app.db.tenant_session.get_engine", lambda: migrated_engine)
    ratelimit.auth_limiter._hits.clear()
    e = SimpleNamespace(engine=migrated_engine, client=TestClient(app))
    with migrated_engine.begin() as c:
        e.t1 = c.execute(text("INSERT INTO tenants(name) VALUES ('Alpha') RETURNING id")).scalar()
        e.t2 = c.execute(text("INSERT INTO tenants(name) VALUES ('Beta') RETURNING id")).scalar()
        e.pw_hash = hash_password(PASSWORD)
        e.alice = _user(c, "alice@x.test", e.pw_hash)  # member of t1 only
        e.bob = _user(c, "bob@x.test", e.pw_hash)  # member of t1 and t2
        e.mem_alice = _member(c, e.t1, e.alice)
        _member(c, e.t1, e.bob)
        _member(c, e.t2, e.bob)
    return e


def _user(c, email, pw_hash):
    q = text("INSERT INTO users(email,password_hash) VALUES (:e,:p) RETURNING id")
    return c.execute(q, {"e": email, "p": pw_hash}).scalar()


def _member(c, tenant, user, status="active"):
    q = text(
        "INSERT INTO tenant_memberships(tenant_id,user_id,status) VALUES (:t,:u,:s) RETURNING id"
    )
    return c.execute(q, {"t": tenant, "u": user, "s": status}).scalar()


def login(env, email="alice@x.test", password=PASSWORD, **extra):
    body = {"email": email, "password": password, **extra}
    return env.client.post("/api/v1/auth/login", json=body)


def bearer(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_login_and_me(env):
    r = login(env)
    assert r.status_code == 200
    tokens = r.json()
    me = env.client.get("/api/v1/auth/me", headers=bearer(tokens))
    assert me.status_code == 200
    assert me.json() == {"user_id": str(env.alice), "tenant_id": str(env.t1)}


def test_wrong_password_and_unknown_user_look_identical(env):
    wrong = login(env, password="nope-nope-nope")
    unknown = login(env, email="ghost@x.test")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_email_is_case_insensitive(env):
    assert login(env, email="ALICE@X.TEST").status_code == 200


def test_lockout_after_repeated_failures_then_recovers(env):
    for _ in range(get_settings().LOGIN_MAX_FAILURES):
        assert login(env, password="wrong-wrong-wrong").status_code == 401
    assert login(env).status_code == 401  # correct password, but locked
    with env.engine.begin() as c:
        c.execute(text("UPDATE users SET locked_until = now() - interval '1 minute'"))
    assert login(env).status_code == 200


def test_success_resets_failure_counter(env):
    for _ in range(2):
        login(env, password="wrong-wrong-wrong")
    assert login(env).status_code == 200
    with env.engine.connect() as c:
        n = c.execute(text("SELECT failed_login_count FROM users WHERE id=:i"), {"i": env.alice})
        assert n.scalar() == 0


def test_multi_tenant_user_must_choose(env):
    r = login(env, email="bob@x.test")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "tenant_required"
    assert {t["name"] for t in detail["tenants"]} == {"Alpha", "Beta"}
    ok = login(env, email="bob@x.test", tenant_id=str(env.t2))
    assert ok.status_code == 200
    me = env.client.get("/api/v1/auth/me", headers=bearer(ok.json())).json()
    assert me["tenant_id"] == str(env.t2)


def test_cannot_log_into_tenant_without_membership(env):
    assert login(env, tenant_id=str(env.t2)).status_code == 401


def test_inactive_membership_or_disabled_user_cannot_login(env):
    with env.engine.begin() as c:
        c.execute(
            text("UPDATE tenant_memberships SET status='inactive' WHERE id=:i"),
            {"i": env.mem_alice},
        )
    assert login(env).status_code == 401
    with env.engine.begin() as c:
        c.execute(
            text("UPDATE tenant_memberships SET status='active' WHERE id=:i"), {"i": env.mem_alice}
        )
        c.execute(text("UPDATE users SET status='disabled' WHERE id=:i"), {"i": env.alice})
    assert login(env).status_code == 401


def test_user_without_password_cannot_login(env):
    with env.engine.begin() as c:
        c.execute(text("UPDATE users SET password_hash = NULL WHERE id=:i"), {"i": env.alice})
    assert login(env).status_code == 401


def test_password_stored_as_argon2_hash(env):
    with env.engine.connect() as c:
        stored = c.execute(
            text("SELECT password_hash FROM users WHERE id=:i"), {"i": env.alice}
        ).scalar()
    assert stored.startswith("$argon2") and PASSWORD not in stored
    assert verify_password(stored, PASSWORD)
    assert not verify_password(stored, "other")
    assert not verify_password(None, PASSWORD)


@pytest.mark.parametrize("header", [None, "Bearer garbage", "Basic abc"])
def test_protected_endpoint_rejects_bad_credentials(env, header):
    headers = {"Authorization": header} if header else {}
    assert env.client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_tampered_and_expired_tokens_rejected(env):
    tokens = login(env).json()
    forged = jwt.encode(
        {"sub": str(env.alice), "tid": str(env.t2), "sid": str(uuid.uuid4()), "exp": 9999999999},
        "wrong-secret-wrong-secret-wrong-secret",
        algorithm="HS256",
    )
    assert (
        env.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code
        == 401
    )
    with env.engine.connect() as c:
        sid = c.execute(text("SELECT id FROM user_sessions")).scalar()
    expired = create_access_token(get_settings(), env.alice, env.t1, sid, ttl=timedelta(seconds=-5))
    assert (
        env.client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"}
        ).status_code
        == 401
    )
    assert env.client.get("/api/v1/auth/me", headers=bearer(tokens)).status_code == 200


def test_valid_signature_but_unknown_session_rejected(env):
    token = create_access_token(get_settings(), env.alice, env.t1, uuid.uuid4())
    assert (
        env.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code
        == 401
    )


def test_refresh_rotates_and_old_token_triggers_revocation(env):
    first = login(env).json()
    second = env.client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert second.status_code == 200
    second = second.json()
    assert second["refresh_token"] != first["refresh_token"]
    assert env.client.get("/api/v1/auth/me", headers=bearer(second)).status_code == 200
    # Replaying the old refresh token = possible theft: the whole session is killed.
    replay = env.client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert replay.status_code == 401
    assert env.client.get("/api/v1/auth/me", headers=bearer(second)).status_code == 401
    again = env.client.post("/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]})
    assert again.status_code == 401


def test_logout_revokes_access_and_refresh(env):
    tokens = login(env).json()
    assert env.client.post("/api/v1/auth/logout", headers=bearer(tokens)).status_code == 204
    assert env.client.get("/api/v1/auth/me", headers=bearer(tokens)).status_code == 401
    r = env.client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401


def test_deactivating_membership_invalidates_live_tokens_immediately(env):
    tokens = login(env).json()
    assert env.client.get("/api/v1/auth/me", headers=bearer(tokens)).status_code == 200
    with env.engine.begin() as c:
        c.execute(
            text("UPDATE tenant_memberships SET status='inactive' WHERE id=:i"),
            {"i": env.mem_alice},
        )
    assert env.client.get("/api/v1/auth/me", headers=bearer(tokens)).status_code == 401
    assert env.client.get("/api/v1/org/departments", headers=bearer(tokens)).status_code == 401
    r = env.client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401


def test_only_token_hashes_are_stored(env):
    tokens = login(env).json()
    with env.engine.connect() as c:
        stored = c.execute(text("SELECT refresh_hash FROM user_sessions")).scalar()
    assert stored == hash_token(tokens["refresh_token"]) != tokens["refresh_token"]


def test_app_role_cannot_read_users_or_sessions(env):
    with env.engine.begin() as c:
        c.execute(text("SET LOCAL ROLE dms_app"))
        for table in ("users", "user_sessions"):
            with pytest.raises(Exception, match="permission denied"), c.begin_nested():
                c.execute(text(f"SELECT 1 FROM {table}"))


def test_login_rate_limited(env, monkeypatch):
    monkeypatch.setattr(get_settings(), "AUTH_RATE_LIMIT_PER_MINUTE", 3)
    codes = [login(env, password="wrong-wrong-wrong").status_code for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]


def test_limiter_window_expires():
    lim = ratelimit.SlidingWindowLimiter(window_seconds=60)
    assert lim.allow("k", 2, now=0) and lim.allow("k", 2, now=1)
    assert not lim.allow("k", 2, now=2)
    assert lim.allow("k", 2, now=61)


def test_production_rejects_default_or_short_secret():
    with pytest.raises(ValueError):
        Settings(_env_file=None, ENVIRONMENT="production")
    with pytest.raises(ValueError):
        Settings(_env_file=None, ENVIRONMENT="production", SECRET_KEY="short")
    assert Settings(
        _env_file=None, ENVIRONMENT="production", SECRET_KEY="x" * 40, EMAIL_BACKEND="smtp"
    )
    assert DEV_SECRET  # development default exists only for local use
