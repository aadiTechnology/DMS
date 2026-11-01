# ruff: noqa: F811
import re

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app import provision
from app.core.config import Settings, get_settings
from app.services.scanner import NoScanner, build_scanner
from tests.test_rbac import auth, env  # noqa: F401  (fixtures)

PROD = {
    "ENVIRONMENT": "production",
    "SECRET_KEY": "x" * 40,
    "EMAIL_BACKEND": "smtp",
    "STORAGE_PROVIDER": "backblaze",
    "DMS_B2_KEY_ID": "id",
    "DMS_B2_APP_KEY": "k",
    "DMS_B2_BUCKET_NAME": "dms-prod",
}


def token_of(link: str) -> str:
    return re.search(r"/reset-password\?token=([\w-]+)$", link).group(1)


def test_a_new_organization_and_its_administrator_can_sign_in_with_the_printed_link(env):
    with Session(env.engine) as db, db.begin():
        link = provision.create_org(db, "Fresh Org", "Boss@Fresh.example", "Fresh Boss", "fresh")
    assert link.startswith(get_settings().APP_BASE_URL)
    reset = env.client.post(
        "/api/v1/auth/reset-password",
        json={"token": token_of(link), "password": "A-long-first-passphrase-77"},
    )
    assert reset.status_code == 204
    login = env.client.post(
        "/api/v1/auth/login",
        json={"email": "boss@fresh.example", "password": "A-long-first-passphrase-77"},
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    perms = env.client.get("/api/v1/me/permissions", headers=headers).json()["permissions"]
    assert "admin.manage_users" in perms and "admin.manage_taxonomy" in perms
    people = env.client.get("/api/v1/employees", headers=headers).json()
    assert [p["full_name"] for p in people] == ["Fresh Boss"]
    again = env.client.post(
        "/api/v1/auth/reset-password",
        json={"token": token_of(link), "password": "A-long-second-passphrase-88"},
    )
    assert again.status_code == 400  # the link works once


def test_link_for_an_existing_account_and_refusals(env):
    with Session(env.engine) as db, db.begin():
        link = provision.make_link(db, "admin-a@x.test")
    assert token_of(link)
    with Session(env.engine) as db, db.begin():
        with pytest.raises(LookupError):
            provision.make_link(db, "nobody@example.com")
        with pytest.raises(ValueError):
            provision.create_org(db, " ", "a@b.example", "A", None)
        with pytest.raises(ValueError):
            provision.create_org(db, "Org", "not-an-email", "A", None)


def test_command_line_prints_the_link_once_and_reports_refusals(env, monkeypatch, capsys):
    monkeypatch.setattr(provision, "get_engine", lambda: env.engine)
    code = provision.main(
        ["create-org", "--name", "Cli Org", "--admin-email", "cli@x.example", "--admin-name", "Cli"]
    )
    out = capsys.readouterr().out
    assert code == 0 and "/reset-password?token=" in out
    assert provision.main(["link", "nobody@example.com"]) == 1
    assert "Refused" in capsys.readouterr().err


def test_skipping_the_virus_scan_in_production_must_be_deliberate():
    with pytest.raises(ValidationError, match="ALLOW_UNSCANNED_UPLOADS"):
        Settings(_env_file=None, SCANNER_BACKEND="none", **PROD)
    with pytest.raises(ValidationError, match="clamav"):
        Settings(_env_file=None, SCANNER_BACKEND="dev", **PROD)
    off = Settings(_env_file=None, SCANNER_BACKEND="none", ALLOW_UNSCANNED_UPLOADS=True, **PROD)
    assert isinstance(build_scanner(off), NoScanner)
    assert Settings(_env_file=None, SCANNER_BACKEND="clamav", **PROD)


def test_the_unscanned_mode_says_so_and_never_blocks(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"anything")
    result = NoScanner().scan(f)
    assert (result.status, result.detail) == ("clean", "not scanned")
