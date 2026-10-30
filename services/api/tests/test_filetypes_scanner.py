import io
import socket
import struct
import threading
import zipfile

import pytest

from app.core.config import Settings
from app.services.filetypes import (
    ALLOWED_EXTENSIONS,
    FileRejected,
    check_declared_type,
    check_extension,
    detect,
    extension_of,
)
from app.services.scanner import (
    DEV_VIRUS_MARKER,
    ClamdScanner,
    DevScanner,
    ScanResult,
    build_scanner,
)


def write(tmp_path, name, data: bytes):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def ooxml(prefix: str, with_types=True) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if with_types:
            z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr(f"{prefix}document.xml", "<x/>")
    return buf.getvalue()


# ---- extension and declared type --------------------------------------------------------


def test_extension_rules():
    assert extension_of("Report.PDF") == "pdf" and extension_of("noext") == ""
    assert check_extension("a.PDF", None) == "pdf"
    for bad in ("run.exe", "x.js", "x.zip", "x.html", "x.svg", "noext", "x.pdf.exe"):
        with pytest.raises(FileRejected) as exc:
            check_extension(bad, None)
        assert exc.value.code == "extension_not_supported" and exc.value.status == 415
    with pytest.raises(FileRejected, match="not accepted in this category"):
        check_extension("a.docx", ["pdf"])
    assert check_extension("a.pdf", ["pdf", "docx"]) == "pdf"
    assert {"pdf", "docx", "xlsx", "pptx", "txt", "doc", "xls", "ppt"} <= ALLOWED_EXTENSIONS


def test_declared_type_must_agree():
    check_declared_type("pdf", "application/pdf")
    check_declared_type("pdf", "application/octet-stream")  # generic is fine; content decides
    check_declared_type("csv", "text/plain; charset=utf-8")
    with pytest.raises(FileRejected) as exc:
        check_declared_type("pdf", "image/png")
    assert exc.value.code == "mime_mismatch" and exc.value.status == 415


# ---- signatures -------------------------------------------------------------------------


def test_valid_files_are_detected(tmp_path):
    cases = {
        "pdf": b"%PDF-1.7\n...",
        "png": b"\x89PNG\r\n\x1a\n" + b"0" * 20,
        "jpg": b"\xff\xd8\xff\xe0" + b"0" * 20,
        "doc": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 20,
        "txt": "अनुबंध करार\nsecond line\n".encode(),
        "csv": b"a,b\n1,2\n",
        "docx": ooxml("word/"),
        "xlsx": ooxml("xl/"),
        "pptx": ooxml("ppt/"),
    }
    for ext, data in cases.items():
        assert detect(ext, write(tmp_path, f"f.{ext}", data)).count("/") == 1


@pytest.mark.parametrize(
    ("ext", "data", "code"),
    [
        ("pdf", b"MZ\x90\x00 this is an exe", "signature_mismatch"),
        ("pdf", b"<html><script>alert(1)</script></html>", "signature_mismatch"),
        ("png", b"%PDF-1.4", "signature_mismatch"),
        ("docx", b"%PDF-1.4", "signature_mismatch"),
        ("docx", ooxml("xl/"), "signature_mismatch"),  # a spreadsheet renamed .docx
        ("docx", ooxml("word/", with_types=False), "signature_mismatch"),
        ("docx", b"PK\x03\x04 not really a zip", "signature_mismatch"),
        ("txt", b"binary\x00\x01\x02 data", "signature_mismatch"),
        ("doc", b"plain text", "signature_mismatch"),
        ("pdf", b"", "empty_file"),
    ],
)
def test_mismatched_content_is_rejected(tmp_path, ext, data, code):
    with pytest.raises(FileRejected) as exc:
        detect(ext, write(tmp_path, f"f.{ext}", data))
    assert exc.value.code == code


def test_archive_bomb_and_oversized_zip_are_rejected(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/bomb.xml", b"0" * (50 * 1024 * 1024))  # compresses ~1000:1
    with pytest.raises(FileRejected) as exc:
        detect("docx", write(tmp_path, "bomb.docx", buf.getvalue()))
    assert exc.value.code == "archive_bomb"
    many = io.BytesIO()
    with zipfile.ZipFile(many, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        for i in range(5_001):
            z.writestr(f"word/p{i}.xml", "")
    with pytest.raises(FileRejected) as exc:
        detect("docx", write(tmp_path, "many.docx", many.getvalue()))
    assert exc.value.code == "archive_too_large"


# ---- scanners ---------------------------------------------------------------------------


def test_dev_scanner_flags_only_its_marker_even_across_chunks(tmp_path):
    assert DevScanner().scan(write(tmp_path, "ok", b"clean content")) == ScanResult("clean")
    assert (
        DevScanner().scan(write(tmp_path, "bad", b"x" + DEV_VIRUS_MARKER + b"y")).status
        == "infected"
    )
    pad = b"a" * (64 * 1024 - 10)  # marker straddles the 64 KiB read boundary
    assert DevScanner().scan(write(tmp_path, "split", pad + DEV_VIRUS_MARKER)).status == "infected"


class FakeClamd:
    """Minimal clamd: speaks the real INSTREAM protocol so ClamdScanner is tested end to end."""

    def __init__(self, verdict: bytes):
        self.verdict, self.received = verdict, b""
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        conn, _ = self.server.accept()
        with conn:
            assert self._read(conn, 10) == b"zINSTREAM\0"
            while (size := struct.unpack(">I", self._read(conn, 4))[0]) > 0:
                self.received += self._read(conn, size)
            conn.sendall(self.verdict)
        self.server.close()

    @staticmethod
    def _read(conn, n):
        data = b""
        while len(data) < n:
            data += conn.recv(n - len(data))
        return data


@pytest.mark.parametrize(
    ("verdict", "status", "detail"),
    [
        (b"stream: OK\0", "clean", ""),
        (b"stream: Eicar-Test-Signature FOUND\0", "infected", "Eicar-Test-Signature"),
        (b"INSTREAM size limit exceeded. ERROR\0", "failed", "scanner error"),
    ],
)
def test_clamd_scanner_speaks_instream(tmp_path, verdict, status, detail):
    fake = FakeClamd(verdict)
    payload = bytes(range(256)) * 1000
    result = ClamdScanner("127.0.0.1", fake.port, 5).scan(write(tmp_path, "f", payload))
    fake.thread.join(5)
    assert (result.status, result.detail) == (status, detail)
    assert fake.received == payload  # the whole file was streamed to the scanner


def test_unreachable_scanner_fails_closed(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]  # nothing listens here once closed
    result = ClamdScanner("127.0.0.1", port, 2).scan(write(tmp_path, "f", b"data"))
    assert result.status == "failed"  # never "clean"


def test_scanner_selection_and_production_rule():
    assert isinstance(build_scanner(Settings(_env_file=None)), DevScanner)
    assert isinstance(
        build_scanner(Settings(_env_file=None, SCANNER_BACKEND="clamav")), ClamdScanner
    )
    with pytest.raises(ValueError, match="clamav"):
        Settings(
            _env_file=None, ENVIRONMENT="production", SECRET_KEY="x" * 40, EMAIL_BACKEND="smtp",
            STORAGE_PROVIDER="backblaze", DMS_B2_KEY_ID="i", DMS_B2_APP_KEY="k", DMS_B2_BUCKET_NAME="b",
        )  # fmt: skip
