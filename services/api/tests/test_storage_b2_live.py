"""Opt-in live test against a real, dedicated, NON-production Backblaze test bucket.

Skipped unless you configure it. To run (PowerShell, values come from your own secret store, and
must never be pasted into chat or committed):

    $env:DMS_B2_LIVE_TEST = "1"
    $env:STORAGE_PROVIDER = "backblaze"
    $env:DMS_B2_KEY_ID = "<test key id>"
    $env:DMS_B2_APP_KEY = "<test application key>"
    $env:DMS_B2_BUCKET_NAME = "<dms test bucket>"
    uv run pytest tests/test_storage_b2_live.py -v

Everything it writes lives under a random tenant prefix and is deleted afterwards.
"""

import hashlib
import os
import tempfile
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import unquote

import pytest

from app.core.config import Settings
from app.storage import keys as k
from app.storage.backblaze import BackblazeStorage
from app.storage.base import ObjectExists

pytestmark = pytest.mark.skipif(
    os.environ.get("DMS_B2_LIVE_TEST") != "1" or os.environ.get("ENVIRONMENT") == "production",
    reason="live Backblaze test is opt-in (see module docstring)",
)


@pytest.fixture(scope="module")
def storage():
    s = BackblazeStorage(Settings())  # reads STORAGE_PROVIDER / DMS_B2_* from the environment
    return s


@pytest.fixture
def key():
    key = k.build_object_key(uuid.uuid4(), uuid.uuid4(), 1, uuid.uuid4(), "live-test.txt")
    yield key
    # never leave test objects behind, even if an assertion failed
    BackblazeStorage(Settings()).delete(key)


def _put(storage, key, data: bytes):
    with tempfile.NamedTemporaryFile(delete=False) as handle:
        handle.write(data)
    path = Path(handle.name)
    try:
        return storage.put_file(
            key,
            path,
            content_type="text/plain",
            sha1=hashlib.sha1(data).hexdigest(),
            sha256=hashlib.sha256(data).hexdigest(),
        )
    finally:
        path.unlink(missing_ok=True)


def test_connection_bucket_is_private_and_key_is_least_privilege(storage):
    assert storage.health() is True  # connect also refuses a non-private bucket
    report = storage.verify_capabilities()
    assert report.missing == (), f"key lacks capabilities: {report.missing}"
    assert report.bucket_restricted, "the application key must be restricted to the DMS bucket"


def test_roundtrip_immutability_and_download_link(storage, key):
    data = b"live backblaze test payload\n" * 50
    stored = _put(storage, key, data)
    assert stored.file_id and stored.size_bytes == len(data)
    info = storage.stat(key)
    assert info.size_bytes == len(data) and info.file_id == stored.file_id
    assert b"".join(storage.read_stream(key)) == data
    assert b"".join(storage.read_stream(key, file_id=stored.file_id)) == data
    with pytest.raises(ObjectExists):
        _put(storage, key, b"must not overwrite")

    url = storage.create_download_url(key, ttl_seconds=60, filename="report.txt")
    with urllib.request.urlopen(url, timeout=30) as response:
        assert response.read() == data
        disposition = unquote(response.headers.get("Content-Disposition", ""))
        assert disposition.startswith("attachment"), "download must be forced to attachment"

    # an unauthenticated request for the same object must fail (bucket is private)
    bare = url.split("?")[0]
    with pytest.raises(Exception) as denied:  # urllib raises HTTPError (401)
        urllib.request.urlopen(bare, timeout=30)
    assert "401" in str(denied.value) or "403" in str(denied.value)

    assert storage.delete(key) is True
    assert storage.stat(key) is None
