# ruff: noqa: BLE001, S110  (a diagnostic must report any failure as text, never crash)
"""Operator self-check: are this container's settings actually working?

    python -m app.selfcheck            # run it inside the api container (Coolify: api service -> Terminal)

It reads the settings the application itself uses and tests each one for real: the database, the upload
folder, the document store (it stores, reads and deletes a tiny test file), the virus scanner, and the
email server (it logs in but sends nothing). Secrets are never printed; only whether they are set.
Exit status is 1 when something failed, so it can also gate a deployment.
"""

import hashlib
import smtplib
import socket
import sys
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import text

from app.core.config import DEV_SECRET, Settings

OK, WARN, FAIL = "OK  ", "WARN", "FAIL"
Result = tuple[str, str]


def _set(secret) -> str:
    value = secret.get_secret_value() if hasattr(secret, "get_secret_value") else secret
    return f"set ({len(value)} characters)" if value else "NOT set"


def check_settings(s: Settings) -> list[Result]:
    out: list[Result] = [
        (OK, f"environment: {s.ENVIRONMENT}"),
        (
            OK if s.SECRET_KEY != DEV_SECRET and len(s.SECRET_KEY) >= 32 else FAIL,
            f"SECRET_KEY: {'set' if s.SECRET_KEY != DEV_SECRET else 'still the development default'} ({len(s.SECRET_KEY)} characters, 32+ needed)",
        ),
    ]
    for name in ("APP_BASE_URL", "API_BASE_URL"):
        value = getattr(s, name)
        problems = []
        if not value.startswith(("http://", "https://")):
            problems.append("must start with http:// or https://")
        if value.endswith("/"):
            problems.append("remove the trailing slash")
        if s.ENVIRONMENT == "production" and value.startswith("http://"):
            problems.append("production should use https")
        if "localhost" in value and s.ENVIRONMENT == "production":
            problems.append("still points at localhost")
        out.append(
            (
                WARN if problems else OK,
                f"{name}: {value}" + (f" ({'; '.join(problems)})" if problems else ""),
            )
        )
    if s.APP_BASE_URL != s.API_BASE_URL:
        out.append(
            (
                WARN,
                "APP_BASE_URL and API_BASE_URL differ; with the one-address setup they should be equal",
            )
        )
    return out


def check_database(s: Settings) -> list[Result]:
    from app.db.session import get_engine

    try:
        with get_engine().connect() as c:
            revision = c.execute(text("SELECT version_num FROM alembic_version")).scalar()
            tenants = c.execute(text("SELECT count(*) FROM tenants")).scalar()
        host = s.POSTGRES_HOST or "from DATABASE_URL"
        return [
            (
                OK,
                f"database reachable ({host}); schema revision {revision}; organizations: {tenants}",
            )
        ]
    except Exception as exc:
        return [(FAIL, f"database: {type(exc).__name__}: {str(exc).splitlines()[0][:160]}")]


def check_upload_folder(s: Settings) -> list[Result]:
    directory = s.UPLOAD_TMP_DIR or tempfile.gettempdir()
    try:
        folder = Path(directory)
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=folder, prefix="selfcheck-"):
            pass
        import shutil

        free = shutil.disk_usage(folder).free // (1024 * 1024)
        need = s.DMS_MAX_UPLOAD_BYTES // (1024 * 1024)
        state = OK if free > need * 2 else WARN
        return [
            (
                state,
                f"upload folder {directory} is writable; {free} MB free (largest upload {need} MB)",
            )
        ]
    except Exception as exc:
        return [
            (
                FAIL,
                f"upload folder {directory} is not writable: {type(exc).__name__}: {str(exc)[:120]} (uploads will fail until this is fixed)",
            )
        ]


def check_storage(s: Settings) -> list[Result]:
    from app.storage import build_storage
    from app.storage.keys import build_object_key

    out: list[Result] = []
    if s.STORAGE_PROVIDER == "backblaze":
        out.append(
            (
                OK if s.DMS_B2_KEY_ID else FAIL,
                f"DMS_B2_KEY_ID: {'set' if s.DMS_B2_KEY_ID else 'NOT set'}",
            )
        )
        out.append(
            (
                OK if s.DMS_B2_APP_KEY.get_secret_value() else FAIL,
                f"DMS_B2_APP_KEY: {_set(s.DMS_B2_APP_KEY)}",
            )
        )
        out.append(
            (
                OK if s.DMS_B2_BUCKET_NAME else FAIL,
                f"DMS_B2_BUCKET_NAME: {s.DMS_B2_BUCKET_NAME or 'NOT set'}",
            )
        )
    else:
        out.append(
            (
                OK if s.ENVIRONMENT != "production" else FAIL,
                f"document store: local folder {s.STORAGE_LOCAL_DIR}",
            )
        )
    key = build_object_key(uuid.uuid4(), uuid.uuid4(), 1, uuid.uuid4(), "selfcheck.txt")
    data = b"DMS self-check file; safe to delete"
    path = None
    storage = None
    try:
        storage = build_storage(s)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as handle:
            handle.write(data)
            path = Path(handle.name)
        stored = storage.put_file(
            key, path, content_type="text/plain", sha1=hashlib.sha1(data).hexdigest()
        )
        back = b"".join(storage.read_stream(key, file_id=stored.file_id))
        out.append(
            (
                OK if back == data else FAIL,
                "document store: stored a test file and read it back"
                if back == data
                else "document store: read-back did not match",
            )
        )
        storage.delete(key)
        out.append((OK, "document store: removed the test file (delete permission works)"))
    except Exception as exc:
        out.append((FAIL, f"document store: {type(exc).__name__}: {str(exc)[:200]}"))
        if storage is not None:
            try:
                storage.delete(key)
            except Exception:
                pass
    finally:
        if path is not None:
            path.unlink(missing_ok=True)
    return out


def check_scanner(s: Settings) -> list[Result]:
    if s.SCANNER_BACKEND == "clamav":
        try:
            with socket.create_connection((s.CLAMD_HOST, s.CLAMD_PORT), timeout=5) as sock:
                sock.sendall(b"zPING\0")
                reply = sock.recv(64)
            ok = b"PONG" in reply
            return [
                (
                    OK if ok else FAIL,
                    f"virus scanner answers at {s.CLAMD_HOST}:{s.CLAMD_PORT}"
                    if ok
                    else "virus scanner gave an unexpected answer",
                )
            ]
        except OSError as exc:
            return [
                (
                    FAIL,
                    f"virus scanner unreachable at {s.CLAMD_HOST}:{s.CLAMD_PORT}: {exc} (uploads will be refused as 'scan unavailable')",
                )
            ]
    if s.SCANNER_BACKEND == "none":
        return [
            (
                WARN,
                "virus scanning is OFF (files are accepted without a scan and marked 'not scanned')",
            )
        ]
    return [(WARN, "scanner is the development stand-in (it does not scan)")]


def check_email(s: Settings) -> list[Result]:
    if s.EMAIL_BACKEND == "console":
        return [(WARN, "email: console mode (messages are written to the log, nothing is sent)")]
    if s.EMAIL_BACKEND == "outbox":
        return [(WARN, "email: test outbox")]
    missing = [
        n
        for n, v in (("EMAIL_SMTP_HOST", s.EMAIL_SMTP_HOST), ("EMAIL_FROM", s.EMAIL_FROM))
        if not v
    ]
    if missing:
        return [(FAIL, f"email: {', '.join(missing)} not set")]
    try:
        with smtplib.SMTP(s.EMAIL_SMTP_HOST, s.EMAIL_SMTP_PORT, timeout=15) as smtp:
            smtp.starttls()
            if s.EMAIL_SMTP_USER:
                smtp.login(s.EMAIL_SMTP_USER, s.EMAIL_SMTP_PASSWORD)
        return [
            (
                OK,
                f"email server accepted the login ({s.EMAIL_SMTP_HOST}:{s.EMAIL_SMTP_PORT}, user {s.EMAIL_SMTP_USER or 'none'}); nothing was sent. Sender: {s.EMAIL_FROM}",
            )
        ]
    except smtplib.SMTPAuthenticationError:
        return [
            (
                FAIL,
                "email: the server refused the user name or SMTP key (use the SMTP key, not the API key or the account password)",
            )
        ]
    except Exception as exc:
        return [(FAIL, f"email: {type(exc).__name__}: {str(exc)[:160]}")]


CHECKS: list[tuple[str, Callable[[Settings], list[Result]]]] = [
    ("Settings", check_settings),
    ("Database", check_database),
    ("Upload folder", check_upload_folder),
    ("Document store", check_storage),
    ("Virus scanner", check_scanner),
    ("Email", check_email),
]


def main() -> int:
    try:
        settings = Settings()
    except ValidationError as exc:
        print("The settings are not valid, so the application would not start:")
        for error in exc.errors():
            print(
                f"  {FAIL} {'.'.join(str(p) for p in error['loc']) or 'settings'}: {error['msg']}"
            )
        return 1
    failed = False
    for title, run in CHECKS:
        print(f"\n{title}")
        for state, line in run(settings):
            print(f"  {state} {line}")
            failed = failed or state == FAIL
    print("\n" + ("Something needs fixing (see FAIL above)." if failed else "No failures."))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
