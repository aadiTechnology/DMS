import hashlib
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import app
from app.storage import build_storage, dev_storage_enabled
from app.storage import keys as k
from app.storage.base import ObjectExists, ObjectNotFound, StorageError
from app.storage.local import LocalStorage

TENANT, DOC, OBJ = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def key_for(name="contract.pdf", version=1, tenant=TENANT, doc=DOC, obj=OBJ):
    return k.build_object_key(tenant, doc, version, obj, name)


# ---- key scheme -------------------------------------------------------------------------


def test_key_shape_matches_adr():
    key = key_for()
    assert key == f"tenants/{TENANT}/documents/{DOC}/versions/1/{OBJ}/contract.pdf"
    k.assert_valid_key(key)
    assert k.tenant_of(key) == TENANT


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "_._etc_passwd"),
        ("a/b\\c.txt", "a_b_c.txt"),
        ("..", "file"),
        ("   ", "file"),
        (".hidden", "hidden"),
        ("report.pdf.", "report.pdf"),
        ("CON.txt", "_CON.txt"),
        ("nul", "_nul"),
        ("a\x00b\x1f.txt", "a_b_.txt"),
        ('q?"<>|*:.doc', "q_______.doc"),
    ],
)
def test_filename_sanitizing(raw, expected):
    assert k.sanitize_filename(raw) == expected


def test_unicode_filenames_survive_and_long_names_are_bounded():
    assert k.sanitize_filename("अनुबंध करार.pdf") == "अनुबंध करार.pdf"
    assert k.sanitize_filename("प्रकल्प अहवाल.docx") == "प्रकल्प अहवाल.docx"
    long = k.sanitize_filename("अ" * 500 + ".pdf")
    assert long.endswith(".pdf") and len(long.encode()) <= k.MAX_FILENAME_BYTES
    k.assert_valid_key(key_for("अ" * 500 + ".pdf"))  # still a valid key (<= 1024 bytes)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "contract.pdf",
        f"tenants/{TENANT}/documents/{DOC}/versions/0/{OBJ}/a.pdf",
        f"tenants/{TENANT}/documents/{DOC}/versions/1/{OBJ}/../a.pdf",
        f"tenants/{TENANT}/documents/{DOC}/versions/1/{OBJ}//a.pdf",
        f"tenants/{TENANT}/documents/{DOC}/versions/1/{OBJ}/a/b.pdf",
        f"tenants/not-a-uuid/documents/{DOC}/versions/1/{OBJ}/a.pdf",
        f"other/{TENANT}/documents/{DOC}/versions/1/{OBJ}/a.pdf",
        f"tenants/{TENANT}/documents/{DOC}/versions/1/{OBJ}/a.pdf\n",
        f"/tenants/{TENANT}/documents/{DOC}/versions/1/{OBJ}/a.pdf",
    ],
)
def test_invalid_keys_are_rejected(bad):
    with pytest.raises(k.InvalidKey):
        k.assert_valid_key(bad)


def test_key_tenant_check():
    k.assert_key_belongs_to_tenant(key_for(), TENANT)
    with pytest.raises(k.InvalidKey):
        k.assert_key_belongs_to_tenant(key_for(), uuid.uuid4())
    with pytest.raises(k.InvalidKey):
        k.build_object_key(TENANT, DOC, 0, OBJ, "a.pdf")


# ---- local adapter ----------------------------------------------------------------------


@pytest.fixture
def storage(tmp_path, monkeypatch):
    s = LocalStorage(Settings(_env_file=None, STORAGE_LOCAL_DIR=str(tmp_path / "store")))
    monkeypatch.setattr("app.api.dev_storage.get_storage", lambda: s)
    return s


@pytest.fixture
def http():
    return TestClient(app)


def path_of(url: str) -> str:
    return urlparse(url).path


def put(storage, key, data: bytes, content_type="application/pdf", sha1=None, tmp_dir=None):
    """Write `data` to a temp file and store it the way the upload sprint will."""
    with tempfile.NamedTemporaryFile(delete=False, dir=tmp_dir) as handle:
        handle.write(data)
    path = Path(handle.name)
    try:
        return storage.put_file(
            key, path, content_type=content_type, sha1=sha1 or hashlib.sha1(data).hexdigest()
        )
    finally:
        path.unlink(missing_ok=True)


def test_upload_verify_download_delete_roundtrip(storage, http):
    key, data = key_for("अनुबंध.pdf"), b"%PDF-1.7 hello" * 100
    assert storage.stat(key) is None
    stored = put(storage, key, data)
    assert stored.size_bytes == len(data) and stored.sha1 == hashlib.sha1(data).hexdigest()
    info = storage.stat(key)
    assert info.size_bytes == len(data) and info.content_type == "application/pdf"
    assert info.sha1 == hashlib.sha1(data).hexdigest()
    assert b"".join(storage.read_stream(key, chunk_size=64)) == data
    url = storage.create_download_url(key, ttl_seconds=60, filename="अनुबंध.pdf")
    got = http.get(path_of(url))
    assert got.status_code == 200 and got.content == data
    assert got.headers["cache-control"] == "private, no-store"
    assert got.headers["x-content-type-options"] == "nosniff"
    assert unquote(got.headers["content-disposition"].split("''")[1]) == "अनुबंध.pdf"
    assert storage.delete(key) is True and storage.delete(key) is False
    assert storage.stat(key) is None
    with pytest.raises(ObjectNotFound):
        list(storage.read_stream(key))


def test_objects_are_immutable(storage):
    key = key_for()
    put(storage, key, b"v1")
    with pytest.raises(ObjectExists):
        put(storage, key, b"v2-overwrite")
    assert b"".join(storage.read_stream(key)) == b"v1"


def test_checksum_mismatch_is_rejected_and_leaves_nothing(storage):
    key = key_for()
    with pytest.raises(StorageError, match="checksum"):
        put(storage, key, b"payload", sha1="0" * 40)
    assert storage.stat(key) is None
    assert list(storage.root.rglob("*.part")) == []


def test_streamed_size_is_enforced_without_leaving_partial_files(storage):
    key = key_for()
    with pytest.raises(StorageError, match="larger"):
        storage.write_exclusive(
            key, iter([b"123", b"456"]), content_type="text/plain", expected_size=5
        )
    with pytest.raises(StorageError, match="smaller"):
        storage.write_exclusive(key, iter([b"12"]), content_type="text/plain", expected_size=5)
    assert storage.stat(key) is None
    assert list(storage.root.rglob("*.part")) == []


def test_put_request_limits(storage, tmp_path):
    key = key_for()
    good = hashlib.sha1(b"x").hexdigest()
    path = tmp_path / "f"
    path.write_bytes(b"x")
    for kwargs in (
        {"content_type": "not a type", "sha1": good},
        {"content_type": "application/pdf", "sha1": "XYZ"},
        {"content_type": "application/pdf", "sha1": good.upper()},
    ):
        with pytest.raises(ValueError):
            storage.put_file(key, path, **kwargs)
    empty = tmp_path / "empty"
    empty.write_bytes(b"")
    with pytest.raises(ValueError):
        storage.put_file(key, empty, content_type="application/pdf", sha1=good)
    with pytest.raises(ValueError):
        storage.create_download_url(key, ttl_seconds=901, filename="a.pdf")


def test_signed_urls_are_bound_to_key_method_and_time(storage, http):
    key, other = key_for(), key_for("other.pdf", obj=uuid.uuid4())
    put(storage, key, b"secret")
    put(storage, other, b"other")
    dl = path_of(storage.create_download_url(key, ttl_seconds=60, filename="x.pdf"))
    assert http.get(dl).content == b"secret"
    assert http.put(dl, content=b"x").status_code == 405  # there is no upload route any more
    # tampering with the token (e.g. swapping the key) breaks the signature
    body, sig = dl.rsplit("/", 1)[1].rsplit(".", 1)
    forged = f"{body[:-2]}AA.{sig}"
    assert http.get(f"/api/v1/dev-storage/{forged}").status_code == 403
    assert http.get("/api/v1/dev-storage/garbage").status_code == 403
    # wrong method inside a validly signed token, and expired links
    wrong = storage._sign({"k": key, "m": "PUT", "e": int(time.time()) + 60, "f": "x.pdf"})
    assert http.get(f"/api/v1/dev-storage/{wrong}").status_code == 403
    expired = storage._sign({"k": key, "m": "GET", "e": int(time.time()) - 1, "f": "x.pdf"})
    assert http.get(f"/api/v1/dev-storage/{expired}").status_code == 403


def test_signed_key_must_still_be_a_valid_key(storage, http):
    token = storage._sign(
        {"k": "../../outside.txt", "m": "GET", "e": int(time.time()) + 60, "f": "x"}
    )
    assert http.get(f"/api/v1/dev-storage/{token}").status_code == 403


def test_adapter_rejects_foreign_keys(storage):
    for bad in ("../x", "tenants/x", ""):
        for call in (storage.stat, storage.delete):
            with pytest.raises(k.InvalidKey):
                call(bad)


def test_health_and_download_of_missing_object(storage, http):
    assert storage.health() is True
    url = storage.create_download_url(key_for(), ttl_seconds=60, filename="a.pdf")
    assert http.get(path_of(url)).status_code == 404


# ---- configuration safety ---------------------------------------------------------------

PROD = {"ENVIRONMENT": "production", "SECRET_KEY": "x" * 40, "EMAIL_BACKEND": "smtp"}
B2 = {
    "STORAGE_PROVIDER": "backblaze",
    "DMS_B2_KEY_ID": "id",
    "DMS_B2_APP_KEY": "k",
    "DMS_B2_BUCKET_NAME": "dms-prod",
}


def test_production_requires_backblaze_and_complete_config():
    with pytest.raises(ValidationError, match="backblaze"):
        Settings(_env_file=None, **PROD)  # local storage not allowed
    for missing in ("DMS_B2_KEY_ID", "DMS_B2_APP_KEY", "DMS_B2_BUCKET_NAME"):
        cfg = {**PROD, **B2, missing: ""}
        with pytest.raises(ValidationError, match=missing):
            Settings(_env_file=None, **cfg)
    assert Settings(_env_file=None, **PROD, **B2).DMS_B2_BUCKET_NAME == "dms-prod"


@pytest.mark.parametrize("erp_bucket", ["attachmentserp-b2", "aaditech-erp-test-v2"])
def test_erp_buckets_are_refused(erp_bucket):
    with pytest.raises(ValidationError, match="DMS-only"):
        Settings(_env_file=None, **{**B2, "DMS_B2_BUCKET_NAME": erp_bucket})


def test_b2_secret_never_appears_in_repr_or_dump():
    s = Settings(_env_file=None, **{**B2, "DMS_B2_APP_KEY": "super-secret-application-key"})
    assert "super-secret-application-key" not in repr(s)
    assert "super-secret-application-key" not in str(s.model_dump())
    assert s.DMS_B2_APP_KEY.get_secret_value() == "super-secret-application-key"


def test_factory_and_dev_router_gating(tmp_path):
    local = Settings(_env_file=None, STORAGE_LOCAL_DIR=str(tmp_path))
    assert isinstance(build_storage(local), LocalStorage)
    assert dev_storage_enabled(local) is True
    b2 = Settings(_env_file=None, **B2)
    assert dev_storage_enabled(b2) is False
    assert (
        type(build_storage(b2)).__name__ == "BackblazeStorage"
    )  # connects lazily; no network here
    assert dev_storage_enabled(Settings(_env_file=None, **PROD, **B2)) is False
