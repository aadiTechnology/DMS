"""Local-disk adapter for development and automated tests. Never allowed in production
(Settings refuses it). Mirrors the contract of the real provider, including short-lived signed
URLs that are bound to one exact key and one method, and refusal to overwrite objects.
"""

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

from app.core.config import Settings
from app.storage import keys
from app.storage.base import (
    ObjectExists,
    ObjectInfo,
    ObjectNotFound,
    StorageError,
    StoredObject,
    check_put,
    check_ttl,
)

URL_PREFIX = "/api/v1/dev-storage"


class InvalidSignedUrl(StorageError):
    pass


class LocalStorage:
    def __init__(self, settings: Settings):
        self._settings = settings
        self.root = Path(settings.STORAGE_LOCAL_DIR).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._secret = hashlib.sha256(("dms-storage:" + settings.SECRET_KEY).encode()).digest()

    # ---- paths ----
    def _path(self, key: str) -> Path:
        keys.assert_valid_key(key)
        path = (self.root / key).resolve()
        if self.root not in path.parents:  # belt and braces; the key regex already forbids ".."
            raise keys.InvalidKey("invalid object key")
        return path

    @staticmethod
    def _meta_path(path: Path) -> Path:
        return path.with_name(path.name + ".meta.json")

    # ---- signed URLs ----
    def _sign(self, payload: dict) -> str:
        body = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode()
        ).decode()
        sig = hmac.new(self._secret, body.encode(), hashlib.sha256).hexdigest()
        return f"{body}.{sig}"

    def verify_token(self, token: str, method: str) -> dict:
        try:
            body, sig = token.rsplit(".", 1)
            expected = hmac.new(self._secret, body.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, expected):
                raise InvalidSignedUrl("bad signature")
            payload = json.loads(base64.urlsafe_b64decode(body.encode()))
        except (ValueError, KeyError) as exc:
            raise InvalidSignedUrl("malformed link") from exc
        if payload.get("m") != method or payload.get("e", 0) < time.time():
            raise InvalidSignedUrl("link expired or not valid for this action")
        try:
            keys.assert_valid_key(payload.get("k"))
        except keys.InvalidKey as exc:
            raise InvalidSignedUrl("invalid key in link") from exc
        return payload

    def _url(self, payload: dict) -> str:
        return f"{self._settings.API_BASE_URL}{URL_PREFIX}/{self._sign(payload)}"

    # ---- StorageProvider ----
    def put_file(
        self,
        key: str,
        path: Path,
        *,
        content_type: str,
        sha1: str,
        sha256: str | None = None,
    ) -> StoredObject:
        keys.assert_valid_key(key)
        size = path.stat().st_size
        check_put(content_type, size, sha1, self._settings.DMS_MAX_UPLOAD_BYTES)
        writer = self.begin_write(key, content_type=content_type, expected_size=size)
        digest = hashlib.sha1(usedforsecurity=False)
        try:
            with path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
                    writer.write(chunk)
            if digest.hexdigest() != sha1:
                raise StorageError("checksum mismatch")
            writer.commit()
        finally:
            writer.close()
        return StoredObject(file_id=None, size_bytes=size, sha1=sha1)

    def create_download_url(
        self, key: str, *, ttl_seconds: int, filename: str, inline: bool = False
    ) -> str:
        keys.assert_valid_key(key)
        check_ttl(ttl_seconds)
        payload = {
            "k": key,
            "m": "GET",
            "e": int(time.time()) + ttl_seconds,
            "f": keys.sanitize_filename(filename),
            "d": "inline" if inline else "attachment",
        }
        return self._url(payload)

    def copy(self, src_key: str, dst_key: str, *, src_file_id: str | None = None) -> StoredObject:
        source = self._path(src_key)
        if not source.is_file():
            raise ObjectNotFound("object not found")
        size = source.stat().st_size
        content_type = self._content_type(source) or "application/octet-stream"
        writer = self.begin_write(dst_key, content_type=content_type, expected_size=size)
        digest = hashlib.sha1(usedforsecurity=False)
        try:
            for chunk in self.read_stream(src_key):
                digest.update(chunk)
                writer.write(chunk)
            writer.commit()
        finally:
            writer.close()
        return StoredObject(file_id=None, size_bytes=size, sha1=digest.hexdigest())

    def stat(self, key: str) -> ObjectInfo | None:
        path = self._path(key)
        if not path.is_file():
            return None
        sha1 = hashlib.sha1(usedforsecurity=False)
        for chunk in self.read_stream(key):
            sha1.update(chunk)
        return ObjectInfo(path.stat().st_size, self._content_type(path), sha1.hexdigest(), None)

    def read_stream(
        self, key: str, chunk_size: int = 1024 * 1024, *, file_id: str | None = None
    ) -> Iterator[bytes]:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFound("object not found")
        with path.open("rb") as handle:
            while chunk := handle.read(chunk_size):
                yield chunk

    def delete(self, key: str) -> bool:
        path = self._path(key)
        existed = path.is_file()
        path.unlink(missing_ok=True)
        self._meta_path(path).unlink(missing_ok=True)
        return existed

    def health(self) -> bool:
        probe = self.root / f".health-{uuid.uuid4().hex}"
        try:
            probe.write_bytes(b"ok")
            return probe.read_bytes() == b"ok"
        except OSError:
            return False
        finally:
            probe.unlink(missing_ok=True)

    # ---- helpers used by the dev router ----
    def _content_type(self, path: Path) -> str | None:
        try:
            return json.loads(self._meta_path(path).read_text()).get("content_type")
        except (OSError, ValueError):
            return None

    def begin_write(self, key: str, *, content_type: str, expected_size: int) -> "ExclusiveWriter":
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        return ExclusiveWriter(self, path, content_type, expected_size)

    def write_exclusive(
        self, key: str, chunks: Iterator[bytes], *, content_type: str, expected_size: int
    ) -> int:
        writer = self.begin_write(key, content_type=content_type, expected_size=expected_size)
        try:
            for chunk in chunks:
                writer.write(chunk)
            return writer.commit()
        finally:
            writer.close()

    @staticmethod
    def content_disposition(filename: str, disposition: str = "attachment") -> str:
        return f"{disposition}; filename*=UTF-8''{quote(filename, safe='')}"


class ExclusiveWriter:
    """Streams a new object to a temporary file, then publishes it atomically. Refuses to
    overwrite (versions are immutable) and removes partial data unless `commit` succeeds."""

    def __init__(self, storage: LocalStorage, path: Path, content_type: str, expected_size: int):
        self._storage, self._path = storage, path
        self._content_type, self._expected = content_type, expected_size
        self._tmp = path.with_name(f".{uuid.uuid4().hex}.part")
        self._handle = self._tmp.open("wb")
        self.written = 0

    def write(self, chunk: bytes) -> None:
        self.written += len(chunk)
        if self.written > self._expected:
            raise StorageError("body larger than declared size")
        self._handle.write(chunk)

    def commit(self) -> int:
        self._handle.close()
        if self.written != self._expected:
            raise StorageError("body smaller than declared size")
        try:
            os.link(self._tmp, self._path)
        except FileExistsError as exc:
            raise ObjectExists("object already exists") from exc
        self._storage._meta_path(self._path).write_text(
            json.dumps({"content_type": self._content_type})
        )
        return self.written

    def close(self) -> None:
        self._handle.close()
        self._tmp.unlink(missing_ok=True)
