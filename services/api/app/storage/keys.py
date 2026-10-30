"""Object-key scheme (ADR-0001, audit section 9.3):

    tenants/{tenant_id}/documents/{document_id}/versions/{version_number}/{object_id}/{filename}

Every id is server-generated. The filename is display metadata, sanitized here; it keeps Unicode
(Hindi/Marathi names must work, PRD I18N-003). Prefixes are organization hygiene only: tenant
isolation is enforced by API authorization and database rules, never by a key.
"""

import re
import unicodedata
import uuid

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_KEY = re.compile(
    rf"^tenants/(?P<tenant>{_UUID})/documents/(?P<document>{_UUID})"
    rf"/versions/(?P<version>[1-9][0-9]{{0,5}})/(?P<object>{_UUID})/(?P<filename>[^/]{{1,255}})$"
)
_FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
_WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
MAX_FILENAME_BYTES = 120


class InvalidKey(ValueError):
    pass


def sanitize_filename(name: str) -> str:
    """Safe last path segment: no separators or control characters, no traversal, no Windows
    reserved names or trailing dots, bounded length (extension kept), never empty."""
    name = unicodedata.normalize("NFC", name or "")
    name = _FORBIDDEN.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    name = name.lstrip(".")  # no hidden or dot-only names
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    if stem.lower() in _WINDOWS_RESERVED:
        stem = f"_{stem}"
    ext = ext[:16] if ext else ""
    budget = MAX_FILENAME_BYTES - (len(ext.encode()) + 1 if ext else 0)
    stem = stem.encode()[:budget].decode(errors="ignore").rstrip(" .")
    result = f"{stem}.{ext}" if ext and stem else (stem or ext)
    return result or "file"


def build_object_key(
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    version_number: int,
    object_id: uuid.UUID,
    filename: str,
) -> str:
    if version_number < 1:
        raise InvalidKey("version_number must be >= 1")
    key = (
        f"tenants/{tenant_id}/documents/{document_id}/versions/{version_number}"
        f"/{object_id}/{sanitize_filename(filename)}"
    )
    assert_valid_key(key)
    return key


def assert_valid_key(key: str) -> None:
    """Providers call this before every operation, so a key that did not come from
    `build_object_key` (for example from a client) can never reach storage."""
    if not isinstance(key, str) or len(key.encode()) > 1024 or not _KEY.match(key):
        raise InvalidKey("invalid object key")
    if unicodedata.normalize("NFC", key) != key or _FORBIDDEN.search(key.split("/", 7)[-1]):
        raise InvalidKey("invalid object key")
    if key.rsplit("/", 1)[-1] in {".", ".."}:
        raise InvalidKey("invalid object key")


def tenant_of(key: str) -> uuid.UUID:
    assert_valid_key(key)
    return uuid.UUID(_KEY.match(key).group("tenant"))


def assert_key_belongs_to_tenant(key: str, tenant_id: uuid.UUID) -> None:
    if tenant_of(key) != tenant_id:
        raise InvalidKey("invalid object key")
