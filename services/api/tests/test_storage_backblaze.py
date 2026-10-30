"""Backblaze adapter tests.

These run the real adapter code against `b2sdk`'s own `RawSimulator` (the SDK's official test
double), so no network, bucket or credentials are involved. They prove our logic; they do NOT
prove live Backblaze behavior. See tests/test_storage_b2_live.py for the opt-in live test.
"""

import hashlib
import logging
import tempfile
import uuid
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from b2sdk.v2 import B2Api, B2HttpApiConfig, InMemoryAccountInfo, RawSimulator
from b2sdk.v2.exception import B2Error, Unauthorized

from app.core.config import Settings
from app.storage import keys as k
from app.storage.backblaze import REQUIRED_CAPABILITIES, BackblazeStorage
from app.storage.base import ObjectExists, ObjectNotFound, StorageConfigError, StorageError

TENANT, DOC = uuid.uuid4(), uuid.uuid4()
SETTINGS = Settings(
    _env_file=None,
    STORAGE_PROVIDER="backblaze",
    DMS_B2_KEY_ID="test-key-id",
    DMS_B2_APP_KEY="test-app-key-SECRET",
    DMS_B2_BUCKET_NAME="dms-test",
)


def key_for(name="contract.pdf", version=1, obj=None):
    return k.build_object_key(TENANT, DOC, version, obj or uuid.uuid4(), name)


def new_api():
    api = B2Api(InMemoryAccountInfo(), api_config=B2HttpApiConfig(_raw_api_class=RawSimulator))
    key_id, key = api.session.raw_api.create_account()
    api.authorize_account("production", key_id, key)
    return api


@pytest.fixture
def b2():
    api = new_api()
    bucket = api.create_bucket("dms-test", "allPrivate")
    storage = BackblazeStorage(SETTINGS, api_factory=lambda: api)
    storage.api, storage.sim_bucket = api, bucket  # handles for tests that play "an attacker"
    return storage


def put(storage, key, data: bytes, content_type="application/pdf", sha1=None, sha256=None):
    with tempfile.NamedTemporaryFile(delete=False) as handle:
        handle.write(data)
    path = Path(handle.name)
    try:
        return storage.put_file(
            key,
            path,
            content_type=content_type,
            sha1=sha1 or hashlib.sha1(data).hexdigest(),
            sha256=sha256,
        )
    finally:
        path.unlink(missing_ok=True)


# ---- connection and bucket safety -------------------------------------------------------


def test_public_bucket_is_refused():
    api = new_api()
    api.create_bucket("dms-test", "allPublic")
    storage = BackblazeStorage(SETTINGS, api_factory=lambda: api)
    with pytest.raises(StorageConfigError, match="private"):
        storage.stat(key_for())
    assert storage.health() is False


def test_missing_bucket_and_bad_credentials_fail_safely(caplog):
    storage = BackblazeStorage(SETTINGS, api_factory=new_api)  # no bucket named dms-test
    with pytest.raises(StorageConfigError) as excinfo:
        storage.stat(key_for())
    assert "test-app-key-SECRET" not in str(excinfo.value) and "dms-test" not in str(excinfo.value)

    def reject():
        raise Unauthorized("bad key test-app-key-SECRET for bucket dms-test", "unauthorized")

    bad = BackblazeStorage(SETTINGS, api_factory=reject)
    with caplog.at_level(logging.DEBUG), pytest.raises(StorageConfigError) as excinfo:
        bad.put_file(key_for(), Path(__file__), content_type="text/plain", sha1="0" * 40)
    leaked = str(excinfo.value) + caplog.text
    assert "test-app-key-SECRET" not in leaked and "test-key-id" not in leaked
    assert bad.health() is False


def test_health_and_connection_reuse(b2):
    assert b2.health() is True
    first = b2._bucket
    b2.stat(key_for())
    assert b2._bucket is first  # one authorized client and bucket per process


# ---- core operations --------------------------------------------------------------------


def test_put_stat_read_delete_roundtrip(b2):
    key, data = key_for("अनुबंध.pdf"), b"%PDF-1.7 payload" * 1000
    assert b2.stat(key) is None
    stored = put(b2, key, data, sha256="ab" * 32)
    assert stored.file_id and stored.size_bytes == len(data)
    info = b2.stat(key)
    assert (info.size_bytes, info.sha1, info.file_id) == (
        len(data),
        hashlib.sha1(data).hexdigest(),
        stored.file_id,
    )
    assert info.content_type == "application/pdf"
    assert b"".join(b2.read_stream(key, chunk_size=1000)) == data
    version = b2.sim_bucket.get_file_info_by_name(key)
    assert version.file_info["sha256"] == "ab" * 32
    assert version.cache_control == "private, no-store"
    assert b2.delete(key) is True
    assert b2.delete(key) is False
    assert b2.stat(key) is None
    with pytest.raises(ObjectNotFound):
        list(b2.read_stream(key))


def test_existing_objects_are_never_overwritten(b2):
    key = key_for()
    put(b2, key, b"version one")
    with pytest.raises(ObjectExists):
        put(b2, key, b"overwrite attempt")
    assert b"".join(b2.read_stream(key)) == b"version one"
    assert len(list(b2.sim_bucket.list_file_versions(key))) == 1


def test_checksum_mismatch_stores_nothing(b2):
    key = key_for()
    with pytest.raises(StorageError):
        put(b2, key, b"payload", sha1="0" * 40)
    assert b2.stat(key) is None


def test_larger_file_roundtrip(b2):
    data = (b"0123456789abcdef" * 1024) * 700  # about 11 MB, constant-memory path
    key = key_for("big.bin")
    put(b2, key, data, content_type="application/octet-stream")
    assert b2.stat(key).size_bytes == len(data)
    assert (
        hashlib.sha256(b"".join(b2.read_stream(key))).hexdigest()
        == hashlib.sha256(data).hexdigest()
    )


def test_inputs_are_validated_before_any_network_call(b2, tmp_path):
    f = tmp_path / "f"
    f.write_bytes(b"x")
    good = hashlib.sha1(b"x").hexdigest()
    with pytest.raises(k.InvalidKey):
        b2.put_file("not/a/key", f, content_type="text/plain", sha1=good)
    for bad in ("../x", "", f"tenants/{TENANT}/x"):
        for call in (b2.stat, b2.delete, lambda key: list(b2.read_stream(key))):
            with pytest.raises(k.InvalidKey):
                call(bad)
    with pytest.raises(ValueError):
        b2.put_file(key_for(), f, content_type="bad type", sha1=good)
    with pytest.raises(ValueError):
        b2.put_file(key_for(), f, content_type="text/plain", sha1="short")
    over = tmp_path / "over"
    over.write_bytes(b"x")
    small = BackblazeStorage(
        SETTINGS.model_copy(update={"DMS_MAX_UPLOAD_BYTES": 0}), api_factory=lambda: b2.api
    )
    with pytest.raises(ValueError):
        small.put_file(key_for(), over, content_type="text/plain", sha1=good)
    assert b2._bucket is None  # nothing above needed a connection


# ---- tenant isolation and substitution --------------------------------------------------


def test_substituted_version_is_detectable_and_pinned_reads_stay_correct(b2):
    """Another uploader can create a newer version under the same name only by knowing the
    UUID key. If that ever happened, the stored file id would no longer match the latest."""
    key = key_for()
    stored = put(b2, key, b"genuine document")
    b2.sim_bucket.upload_bytes(b"forged replacement", key)  # attacker with raw bucket access
    assert b2.stat(key).file_id != stored.file_id  # detection: compare with the recorded id
    assert b"".join(b2.read_stream(key, file_id=stored.file_id)) == b"genuine document"


def test_delete_removes_every_version_and_only_that_key(b2):
    key, other = key_for(), key_for("other.pdf")
    put(b2, key, b"one")
    put(b2, other, b"keep me")
    b2.sim_bucket.upload_bytes(b"two", key)  # a second version of the same name
    assert len(list(b2.sim_bucket.list_file_versions(key))) == 2
    assert b2.delete(key) is True
    assert list(b2.sim_bucket.list_file_versions(key)) == []
    assert b"".join(b2.read_stream(other)) == b"keep me"


def test_delete_failure_is_raised_not_swallowed(b2, monkeypatch):
    key = key_for()
    put(b2, key, b"data")

    def boom(*_args, **_kwargs):
        raise B2Error("secret detail test-app-key-SECRET")

    monkeypatch.setattr(b2.api, "delete_file_version", boom)
    with pytest.raises(StorageError) as excinfo:
        b2.delete(key)
    assert "test-app-key-SECRET" not in str(excinfo.value)
    assert b2.stat(key) is not None  # still there; the caller knows the delete failed


# ---- download links ---------------------------------------------------------------------


def test_download_url_is_exact_key_short_lived_and_forces_attachment(b2):
    key = key_for("अनुबंध.pdf")
    put(b2, key, b"data")
    url = b2.create_download_url(key, ttl_seconds=120, filename="../../evil\\name.pdf")
    parsed = urlparse(url)
    assert parsed.path.endswith(key) or unquote(parsed.path).endswith(key)
    query = parse_qs(parsed.query)
    assert query["Authorization"][0].endswith("_120")  # simulator token encodes the duration
    assert query["b2CacheControl"] == ["private, no-store"]
    disposition = query["b2ContentDisposition"][0]
    assert disposition.startswith("attachment; filename*=UTF-8''")
    assert "evil" in unquote(disposition) and "/" not in unquote(disposition.split("''")[1])
    for ttl in (0, 901, 3600):
        with pytest.raises(ValueError):
            b2.create_download_url(key, ttl_seconds=ttl, filename="a.pdf")


# ---- least privilege --------------------------------------------------------------------


def _storage_with_key(capabilities, restrict_to_bucket=True):
    master = new_api()
    bucket = master.create_bucket("dms-test", "allPrivate")
    key = master.create_key(
        capabilities, "dms-key", bucket_id=bucket.id_ if restrict_to_bucket else None
    )
    api = B2Api(
        InMemoryAccountInfo(),
        api_config=B2HttpApiConfig(_raw_api_class=lambda _http: master.session.raw_api),
    )
    api.authorize_account("production", key.id_, key.application_key)
    return BackblazeStorage(SETTINGS, api_factory=lambda: api)


def test_capability_report_flags_missing_and_unrestricted_keys():
    exact = _storage_with_key(sorted(REQUIRED_CAPABILITIES))
    report = exact.verify_capabilities()
    assert report.ok and report.extra == () and report.bucket_restricted

    short = _storage_with_key(sorted(REQUIRED_CAPABILITIES - {"deleteFiles"}))
    assert short.verify_capabilities().missing == ("deleteFiles",)
    assert short.verify_capabilities().ok is False

    broad = _storage_with_key(sorted(REQUIRED_CAPABILITIES | {"writeKeys", "deleteBuckets"}), False)
    report = broad.verify_capabilities()
    assert report.bucket_restricted is False and "writeKeys" in report.extra
    assert report.ok is False  # a key that is not bucket-restricted is not least privilege


def test_secret_is_not_in_adapter_repr_or_settings_dump():
    assert "test-app-key-SECRET" not in repr(SETTINGS)
    assert "test-app-key-SECRET" not in str(SETTINGS.model_dump())


def test_inline_download_url_uses_inline_disposition(b2):
    key = key_for()
    put(b2, key, b"%PDF-1.7 data")
    query = parse_qs(
        urlparse(b2.create_download_url(key, ttl_seconds=60, filename="a.pdf", inline=True)).query
    )
    assert query["b2ContentDisposition"][0].startswith("inline; filename*=UTF-8''")


def test_copy_makes_an_independent_verified_object(b2):
    src, dst = key_for(), key_for("copy.pdf", version=2)
    stored = put(b2, src, b"restore me please")
    copied = b2.copy(src, dst, src_file_id=stored.file_id)
    assert copied.file_id != stored.file_id and copied.size_bytes == 17
    assert copied.sha1 == hashlib.sha1(b"restore me please").hexdigest()
    assert b"".join(b2.read_stream(dst)) == b"restore me please"
    assert b2.stat(dst).content_type == "application/pdf"
    with pytest.raises(ObjectExists):
        b2.copy(src, dst)
    with pytest.raises(ObjectNotFound):
        b2.copy(key_for("missing.pdf", version=3), key_for("nowhere.pdf", version=4))
    b2.delete(src)
    assert b"".join(b2.read_stream(dst)) == b"restore me please"
