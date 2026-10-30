"""Content-based file validation (PRD STO-003): extension allow-list, declared MIME type, and the
actual file signature must all agree. The filename and the client's Content-Type are never
trusted on their own. Unsupported or mismatched files are rejected before anything is stored.
"""

import zipfile
from dataclasses import dataclass
from pathlib import Path

MAX_ZIP_ENTRIES = 5_000
MAX_ZIP_UNCOMPRESSED = 1 << 30  # 1 GiB
MAX_ZIP_RATIO = 200  # archive-bomb guard
TEXT_SAMPLE = 64 * 1024

OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ZIP = b"PK\x03\x04"
OOXML_PREFIX = {"docx": "word/", "xlsx": "xl/", "pptx": "ppt/"}


@dataclass(frozen=True)
class FileKind:
    mime: str
    signature: str  # pdf | ole | ooxml | jpeg | png | text
    accepted_declared: frozenset[str]


def _kind(mime: str, signature: str, *extra: str) -> FileKind:
    return FileKind(mime, signature, frozenset({mime, "application/octet-stream", *extra}))


KINDS: dict[str, FileKind] = {
    "pdf": _kind("application/pdf", "pdf"),
    "doc": _kind("application/msword", "ole"),
    "docx": _kind(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "ooxml"
    ),
    "xls": _kind("application/vnd.ms-excel", "ole"),
    "xlsx": _kind("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "ooxml"),
    "ppt": _kind("application/vnd.ms-powerpoint", "ole"),
    "pptx": _kind(
        "application/vnd.openxmlformats-officedocument.presentationml.presentation", "ooxml"
    ),
    "txt": _kind("text/plain", "text"),
    "csv": _kind("text/csv", "text", "text/plain", "application/vnd.ms-excel"),
    "jpg": _kind("image/jpeg", "jpeg"),
    "jpeg": _kind("image/jpeg", "jpeg"),
    "png": _kind("image/png", "png"),
}
ALLOWED_EXTENSIONS = frozenset(KINDS)


class FileRejected(Exception):
    """`code` is a stable machine reason; `status` the HTTP status the API should answer with."""

    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def extension_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def check_extension(filename: str, category_allowed: list[str] | None) -> str:
    ext = extension_of(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise FileRejected(
            "extension_not_supported", f"File type .{ext or '?'} is not supported", 415
        )
    if category_allowed is not None and ext not in category_allowed:
        raise FileRejected(
            "extension_not_allowed_for_category",
            f".{ext} files are not accepted in this category (allowed: {', '.join(category_allowed)})",
            415,
        )
    return ext


def check_declared_type(ext: str, declared: str) -> None:
    base = declared.split(";", 1)[0].strip().lower()
    if base not in KINDS[ext].accepted_declared:
        raise FileRejected(
            "mime_mismatch", f"The declared type {base!r} does not match a .{ext} file", 415
        )


def detect(ext: str, path: Path) -> str:
    """Verify the real content matches the extension; returns the canonical MIME type."""
    kind = KINDS[ext]
    with path.open("rb") as handle:
        head = handle.read(TEXT_SAMPLE)
    if not head:
        raise FileRejected("empty_file", "The file is empty")
    ok = {
        "pdf": lambda: head.startswith(b"%PDF-"),
        "ole": lambda: head.startswith(OLE),
        "jpeg": lambda: head.startswith(b"\xff\xd8\xff"),
        "png": lambda: head.startswith(b"\x89PNG\r\n\x1a\n"),
        "text": lambda: _looks_like_text(head),
        "ooxml": lambda: head.startswith(ZIP),
    }[kind.signature]()
    if not ok:
        raise FileRejected("signature_mismatch", f"The content is not a valid .{ext} file")
    if kind.signature == "ooxml":
        _check_ooxml(ext, path)
    return kind.mime


def _looks_like_text(head: bytes) -> bool:
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):  # UTF-16 byte-order mark
        return True
    if b"\x00" in head:
        return False
    control = sum(1 for b in head if b < 32 and b not in (9, 10, 12, 13))
    return control / len(head) < 0.01


def _check_ooxml(ext: str, path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                raise FileRejected("archive_too_large", "The document contains too many parts")
            total = sum(i.file_size for i in infos)
            packed = sum(i.compress_size for i in infos) or 1
            if total > MAX_ZIP_UNCOMPRESSED or total / packed > MAX_ZIP_RATIO:
                raise FileRejected("archive_bomb", "The document expands to an unsafe size")
            names = {i.filename for i in infos}
    except zipfile.BadZipFile:
        raise FileRejected(
            "signature_mismatch", f"The content is not a valid .{ext} file"
        ) from None
    if "[Content_Types].xml" not in names or not any(
        n.startswith(OOXML_PREFIX[ext]) for n in names
    ):
        raise FileRejected("signature_mismatch", f"The content is not a valid .{ext} file")
