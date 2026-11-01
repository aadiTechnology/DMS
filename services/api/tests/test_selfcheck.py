# ruff: noqa: F811
from app import selfcheck
from app.core.config import Settings
from tests.test_rbac import env  # noqa: F401  (fixture)


def states(results):
    return {state.strip() for state, _ in results}


def lines(results):
    return " | ".join(line for _, line in results)


def local(tmp_path, **extra):
    return Settings(
        _env_file=None,
        STORAGE_PROVIDER="local",
        STORAGE_LOCAL_DIR=str(tmp_path / "store"),
        UPLOAD_TMP_DIR=str(tmp_path / "tmp"),
        **extra,
    )


def test_a_healthy_setup_has_no_failures(tmp_path, env, monkeypatch):
    monkeypatch.setattr("app.db.session.get_engine", lambda: env.engine)
    s = local(tmp_path)
    assert "FAIL" not in states(selfcheck.check_upload_folder(s))
    storage = selfcheck.check_storage(s)
    assert "FAIL" not in states(storage) and "removed the test file" in lines(storage)
    assert not list((tmp_path / "store").rglob("*.txt"))  # the test file is gone
    db = selfcheck.check_database(s)
    assert states(db) == {"OK"} and "organizations" in lines(db)
    assert states(selfcheck.check_scanner(s)) == {"WARN"}


def test_an_unwritable_upload_folder_is_reported_as_the_cause_of_failing_uploads(tmp_path):
    blocker = tmp_path / "tmp"
    blocker.write_text("a file, not a folder")
    result = selfcheck.check_upload_folder(local(tmp_path))
    assert states(result) == {"FAIL"} and "uploads will fail" in lines(result)


def test_a_broken_document_store_is_reported(tmp_path):
    (tmp_path / "store").write_text("a file, not a folder")
    assert "FAIL" in states(selfcheck.check_storage(local(tmp_path)))


def test_missing_backblaze_values_are_named_without_printing_secrets(tmp_path):
    s = Settings(
        _env_file=None,
        STORAGE_PROVIDER="backblaze",
        DMS_B2_KEY_ID="id",
        DMS_B2_APP_KEY="s3cr3t-value",
        DMS_B2_BUCKET_NAME="dms-x",
    )
    out = lines(selfcheck.check_storage(s))
    assert "s3cr3t-value" not in out and "DMS_B2_APP_KEY: set (12 characters)" in out


def test_unreachable_scanner_and_mail_server_fail(tmp_path):
    s = local(tmp_path, SCANNER_BACKEND="clamav", CLAMD_HOST="127.0.0.1", CLAMD_PORT=1)
    assert states(selfcheck.check_scanner(s)) == {"FAIL"}
    mail = local(
        tmp_path,
        EMAIL_BACKEND="smtp",
        EMAIL_SMTP_HOST="127.0.0.1",
        EMAIL_SMTP_PORT=1,
        EMAIL_FROM="a@b.example",
    )
    assert states(selfcheck.check_email(mail)) == {"FAIL"}
    assert states(selfcheck.check_email(local(tmp_path, EMAIL_BACKEND="smtp"))) == {
        "FAIL"
    }  # host missing


def test_address_mistakes_are_warned_about(tmp_path):
    s = local(tmp_path, APP_BASE_URL="dms.example.com/", API_BASE_URL="http://localhost:8000")
    text = lines(selfcheck.check_settings(s))
    assert "must start with http" in text and "remove the trailing slash" in text


def test_unsafe_production_settings_stop_the_check_with_the_reason(monkeypatch, capsys):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "short")
    assert selfcheck.main() == 1
    assert "SECRET_KEY" in capsys.readouterr().out
