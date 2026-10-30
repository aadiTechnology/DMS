"""Storage provider interface (ADR-0001, ADR-0002). DMS business logic depends on this, never on
an SDK.

Security contract every provider must keep:
- Objects are private. Callers get access only through short-lived, exact-key URLs that the API
  hands out *after* its own authorization check. Holding a key or URL is never authorization.
- Keys must pass `keys.assert_valid_key` before any operation.
- Existing objects are never overwritten (versions are immutable).
- Uploads are verified against a checksum; a mismatch is an error and leaves nothing behind.
- Failures are raised, never swallowed; messages must not contain credentials or signed URLs.
- Clients never receive provider credentials or bucket-wide upload tokens: the API receives the
  bytes, hashes them once, and hands the finished file to `put_file` (ADR-0002).
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

MAX_URL_TTL_SECONDS = 900
_CONTENT_TYPE = re.compile(r"^[A-Za-z0-9][\w.+-]*/[A-Za-z0-9][\w.+-]*$")
_HEX = re.compile(r"^[0-9a-f]+$")


class StorageError(Exception):
    """Base class. Messages are safe to show in logs (no secrets, no signed URLs)."""


class ObjectExists(StorageError):
    pass


class ObjectNotFound(StorageError):
    pass


class StorageConfigError(StorageError):
    pass


@dataclass(frozen=True)
class StoredObject:
    """What `put_file` reports; persist `file_id` so later reads can detect substitution."""

    file_id: str | None
    size_bytes: int
    sha1: str | None


@dataclass(frozen=True)
class ObjectInfo:
    size_bytes: int
    content_type: str | None
    sha1: str | None  # None when the provider has none (for example very large files)
    file_id: str | None = None


class StorageProvider(Protocol):
    def put_file(
        self,
        key: str,
        path: Path,
        *,
        content_type: str,
        sha1: str,
        sha256: str | None = None,
    ) -> StoredObject:
        """Store a finished local file as a new immutable object. Raises ObjectExists if the key
        is taken, StorageError on checksum/size mismatch (nothing is left behind)."""
        ...

    def stat(self, key: str) -> ObjectInfo | None:
        """Metadata of a stored object, or None. Used to verify uploads and detect substitution."""
        ...

    def read_stream(
        self, key: str, chunk_size: int = 1024 * 1024, *, file_id: str | None = None
    ) -> Iterator[bytes]:
        """Stream bytes for workers (scanning, extraction, checksums). Pass the stored `file_id`
        to read that exact version. Raises ObjectNotFound."""
        ...

    def create_download_url(
        self, key: str, *, ttl_seconds: int, filename: str, inline: bool = False
    ) -> str:
        """Short-lived exact-key link. `inline` (preview) is only for types the caller has
        verified are safe to render (PDF, PNG, JPEG); everything else is a forced download."""
        ...

    def copy(self, src_key: str, dst_key: str, *, src_file_id: str | None = None) -> StoredObject:
        """Server-side copy to a NEW key (restoring an old version creates a new immutable
        object; bytes are never mutated or shared). Raises ObjectExists/ObjectNotFound."""
        ...

    def delete(self, key: str) -> bool:
        """Remove every stored version of an object (only after lifecycle approval).
        True if something was removed. Failures raise."""
        ...

    def health(self) -> bool:
        """Can we reach and use the store? Never exposes paths or credentials."""
        ...


def check_ttl(ttl_seconds: int) -> None:
    if not 1 <= ttl_seconds <= MAX_URL_TTL_SECONDS:
        raise ValueError(f"ttl_seconds must be between 1 and {MAX_URL_TTL_SECONDS}")


def check_put(content_type: str, size_bytes: int, sha1: str, max_bytes: int) -> None:
    if not 0 < size_bytes <= max_bytes:
        raise ValueError(f"size_bytes must be between 1 and {max_bytes}")
    if not _CONTENT_TYPE.match(content_type or ""):
        raise ValueError("invalid content type")
    if len(sha1) != 40 or not _HEX.match(sha1):
        raise ValueError("sha1 must be 40 lowercase hex digits")
