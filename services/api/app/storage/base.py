"""Storage provider interface (ADR-0001). DMS business logic depends on this, never on an SDK.

Security contract every provider must keep:
- Objects are private. Callers get access only through short-lived, exact-key URLs that the API
  hands out *after* its own authorization check. Holding a key or URL is never authorization.
- Keys must pass `keys.assert_valid_key` before any operation.
- Existing objects are never overwritten (versions are immutable).
- Failures are raised, never swallowed; messages must not contain credentials or signed URLs.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

MAX_URL_TTL_SECONDS = 900
_CONTENT_TYPE = re.compile(r"^[A-Za-z0-9][\w.+-]*/[A-Za-z0-9][\w.+-]*$")


class StorageError(Exception):
    """Base class. Messages are safe to show in logs (no secrets, no signed URLs)."""


class ObjectExists(StorageError):
    pass


class ObjectNotFound(StorageError):
    pass


class StorageConfigError(StorageError):
    pass


@dataclass(frozen=True)
class UploadTarget:
    """Where and how the client sends the bytes directly to storage (never via our API memory)."""

    url: str
    method: str
    headers: dict[str, str] = field(default_factory=dict)
    expires_at: datetime | None = None


@dataclass(frozen=True)
class ObjectInfo:
    size_bytes: int
    content_type: str | None
    sha1: str | None  # provider-reported integrity hash where available


class StorageProvider(Protocol):
    def create_upload_target(
        self, key: str, *, content_type: str, size_bytes: int, ttl_seconds: int
    ) -> UploadTarget: ...

    def stat(self, key: str) -> ObjectInfo | None:
        """Metadata of a stored object, or None. Used to verify upload completion server-side."""
        ...

    def read_stream(self, key: str, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        """Stream bytes for workers (scanning, extraction, checksums). Raises ObjectNotFound."""
        ...

    def create_download_url(self, key: str, *, ttl_seconds: int, filename: str) -> str: ...

    def delete(self, key: str) -> bool:
        """Remove an object (only after lifecycle approval). True if something was removed."""
        ...

    def health(self) -> bool:
        """Can we reach and use the store? Never exposes paths or credentials."""
        ...


def check_upload_request(
    content_type: str, size_bytes: int, ttl_seconds: int, max_bytes: int
) -> None:
    if not 0 < size_bytes <= max_bytes:
        raise ValueError(f"size_bytes must be between 1 and {max_bytes}")
    if not _CONTENT_TYPE.match(content_type or ""):
        raise ValueError("invalid content type")
    check_ttl(ttl_seconds)


def check_ttl(ttl_seconds: int) -> None:
    if not 1 <= ttl_seconds <= MAX_URL_TTL_SECONDS:
        raise ValueError(f"ttl_seconds must be between 1 and {MAX_URL_TTL_SECONDS}")
