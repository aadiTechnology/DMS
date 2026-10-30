"""Backblaze B2 adapter on the native API via `b2sdk` (ADR-0001, ADR-0002).

Reused from the ERP integration (audit section 10): server-side credentials, lazy SDK use,
in-memory account info, download authorizations. Improved for the DMS: a dedicated private
bucket that is *verified* private at connect time, exact-key short-lived download links with
forced `attachment` disposition, immutable objects, checksums verified on upload, deletion of
every version with errors raised, and no credentials or signed URLs in messages or logs.

Uploads go through the API (streamed to disk and hashed once, then `put_file`). Native B2 upload
tokens are bucket-wide and last 24 hours, so they are never handed to clients.
"""

import logging
import tempfile
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

from b2sdk.v2 import B2Api, B2HttpApiConfig, InMemoryAccountInfo
from b2sdk.v2.exception import B2Error, FileNotPresent

from app.core.config import Settings
from app.storage import keys
from app.storage.base import (
    ObjectExists,
    ObjectInfo,
    ObjectNotFound,
    StorageConfigError,
    StorageError,
    StoredObject,
    check_put,
    check_ttl,
)

logger = logging.getLogger("dms.storage.b2")

REQUIRED_CAPABILITIES = frozenset(
    {"listBuckets", "listFiles", "readFiles", "writeFiles", "deleteFiles", "shareFiles"}
)
USER_AGENT = "dms-api"


@dataclass(frozen=True)
class CapabilityReport:
    """Result of `verify_capabilities`; used by operations and the live integration test."""

    missing: tuple[str, ...]
    extra: tuple[str, ...]
    bucket_restricted: bool

    @property
    def ok(self) -> bool:
        return not self.missing and self.bucket_restricted


def _fail(operation: str, exc: Exception) -> StorageError:
    """Error text carries only the operation and exception class/code, never details that could
    include key names, URLs or credentials."""
    code = getattr(exc, "code", None)
    return StorageError(
        f"storage {operation} failed ({type(exc).__name__}{f': {code}' if code else ''})"
    )


class BackblazeStorage:
    def __init__(self, settings: Settings, api_factory: Callable[[], B2Api] | None = None):
        self._settings = settings
        self._api_factory = api_factory or self._authorized_api
        self._lock = threading.Lock()
        self._api: B2Api | None = None
        self._bucket = None

    # ---- connection (one reused client per process) ----
    def _authorized_api(self) -> B2Api:
        api = B2Api(InMemoryAccountInfo(), api_config=B2HttpApiConfig(user_agent_append=USER_AGENT))
        api.authorize_account(
            "production",  # the B2 account realm, not an environment name
            self._settings.DMS_B2_KEY_ID,
            self._settings.DMS_B2_APP_KEY.get_secret_value(),
        )
        return api

    def _connect(self):
        with self._lock:
            if self._bucket is not None:
                return self._bucket
            try:
                api = self._api_factory()
                bucket = api.get_bucket_by_name(self._settings.DMS_B2_BUCKET_NAME)
            except B2Error as exc:
                raise StorageConfigError(
                    f"cannot use the configured bucket ({type(exc).__name__}); "
                    "check DMS_B2_KEY_ID, DMS_B2_APP_KEY and DMS_B2_BUCKET_NAME"
                ) from None
            if bucket.type_ != "allPrivate":
                raise StorageConfigError("the DMS bucket must be private (allPrivate)")
            self._api, self._bucket = api, bucket
            return bucket

    def _reset(self) -> None:
        with self._lock:
            self._api = self._bucket = None

    def _guard(self, operation: str, func):
        try:
            return func()
        except (StorageError, keys.InvalidKey, ValueError):
            raise
        except B2Error as exc:
            if type(exc).__name__ in {"InvalidAuthToken", "Unauthorized", "ExpiredAuthToken"}:
                self._reset()  # re-authorize on the next call
            logger.error("b2 %s failed: %s", operation, type(exc).__name__)
            raise _fail(operation, exc) from None

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

        def run() -> StoredObject:
            bucket = self._connect()
            if self._latest(bucket, key) is not None:
                raise ObjectExists("object already exists")
            info = {"sha256": sha256} if sha256 else None
            version = bucket.upload_local_file(
                local_file=str(path),
                file_name=key,
                content_type=content_type,
                file_info=info,
                sha1_sum=sha1,
                cache_control="private, no-store",
            )
            stored_sha1 = _sha1_of(version)
            if version.size != size or (stored_sha1 is not None and stored_sha1 != sha1):
                self._api.delete_file_version(version.id_, version.file_name)
                raise StorageError("storage integrity check failed; upload discarded")
            return StoredObject(file_id=version.id_, size_bytes=version.size, sha1=stored_sha1)

        return self._guard("upload", run)

    def stat(self, key: str) -> ObjectInfo | None:
        keys.assert_valid_key(key)

        def run() -> ObjectInfo | None:
            found = self._latest(self._connect(), key)
            if found is None:
                return None
            sha1 = _sha1_of(found)
            return ObjectInfo(found.size, found.content_type, sha1, found.id_)

        return self._guard("stat", run)

    def read_stream(
        self, key: str, chunk_size: int = 1024 * 1024, *, file_id: str | None = None
    ) -> Iterator[bytes]:
        keys.assert_valid_key(key)

        def download(directory: str) -> Path:
            bucket = self._connect()
            target = Path(directory) / "object"
            try:
                downloaded = (
                    bucket.download_file_by_id(file_id)
                    if file_id
                    else bucket.download_file_by_name(key)
                )
                downloaded.save_to(target)  # SDK verifies the SHA-1 where B2 holds one
            except FileNotPresent:
                raise ObjectNotFound("object not found") from None
            return target

        # One request, spooled to temporary disk so memory stays flat for 100 MB objects.
        with tempfile.TemporaryDirectory(prefix="dms-b2-") as directory:
            target = self._guard("download", lambda: download(directory))
            with target.open("rb") as handle:
                while chunk := handle.read(chunk_size):
                    yield chunk

    def create_download_url(
        self, key: str, *, ttl_seconds: int, filename: str, inline: bool = False
    ) -> str:
        keys.assert_valid_key(key)
        check_ttl(ttl_seconds)

        def run() -> str:
            bucket = self._connect()
            # Scoped to this exact key (object ids are unique, so no sibling shares the prefix).
            token = bucket.get_download_authorization(
                file_name_prefix=key, valid_duration_in_seconds=ttl_seconds
            )
            query = urlencode(
                {
                    "Authorization": token,
                    "b2ContentDisposition": _disposition(
                        filename, "inline" if inline else "attachment"
                    ),
                    "b2CacheControl": "private, no-store",
                }
            )
            return f"{bucket.get_download_url(key)}?{query}"

        return self._guard("download link", run)

    def delete(self, key: str) -> bool:
        keys.assert_valid_key(key)

        def run() -> bool:
            bucket = self._connect()
            versions = [v for v in bucket.list_file_versions(key) if v.file_name == key]
            for version in versions:  # every version, including hide markers; failures raise
                self._api.delete_file_version(version.id_, version.file_name)
            return bool(versions)

        return self._guard("delete", run)

    def health(self) -> bool:
        try:
            self._connect()
            return True
        except StorageError:
            return False

    # ---- operations support ----
    def verify_capabilities(self) -> CapabilityReport:
        """Compare the key's capabilities with what the DMS needs (least privilege check)."""
        self._connect()
        allowed = self._api.account_info.get_allowed()
        have = set(allowed.get("capabilities", []))
        return CapabilityReport(
            missing=tuple(sorted(REQUIRED_CAPABILITIES - have)),
            extra=tuple(sorted(have - REQUIRED_CAPABILITIES)),
            bucket_restricted=bool(allowed.get("bucketId")),
        )

    @staticmethod
    def _latest(bucket, key: str):
        try:
            return bucket.get_file_info_by_name(key)
        except FileNotPresent:
            return None


def _sha1_of(version) -> str | None:
    """SHA-1 whether B2 stored it directly or, for large (multi-part) files, in file info."""
    value = version.get_content_sha1()
    return None if value in (None, "none") else value


def _disposition(filename: str, kind: str = "attachment") -> str:
    from urllib.parse import quote

    return f"{kind}; filename*=UTF-8''{quote(keys.sanitize_filename(filename), safe='')}"
