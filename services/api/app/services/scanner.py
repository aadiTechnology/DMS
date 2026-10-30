"""Malware scanning behind a small interface (PRD STO-004).

Files are scanned on the API's temporary copy *before* they are stored, so an infected file
never reaches object storage. Anything other than a clean verdict (infected or scanner failure)
leaves the document unavailable.

- `clamav`: talks to a ClamAV daemon (clamd) over its INSTREAM socket protocol. Free and the
  standard open-source engine; deploy it as a sidecar container. Production requires it.
- `dev`: development stand-in. Flags only files containing DEV_VIRUS_MARKER. It is NOT a scanner.
"""

import socket
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.core.config import Settings

DEV_VIRUS_MARKER = b"DMS-DEV-VIRUS-TEST-MARKER"
CHUNK = 64 * 1024


@dataclass(frozen=True)
class ScanResult:
    status: str  # clean | infected | failed
    detail: str = ""


class Scanner(Protocol):
    def scan(self, path: Path) -> ScanResult: ...


class DevScanner:
    def scan(self, path: Path) -> ScanResult:
        tail = b""
        with path.open("rb") as handle:
            while chunk := handle.read(CHUNK):
                if DEV_VIRUS_MARKER in tail + chunk:
                    return ScanResult("infected", "dev-test-marker")
                tail = chunk[-len(DEV_VIRUS_MARKER) :]
        return ScanResult("clean")


class ClamdScanner:
    """clamd INSTREAM: 'zINSTREAM\\0', then length-prefixed chunks, then a zero length."""

    def __init__(self, host: str, port: int, timeout: float):
        self.host, self.port, self.timeout = host, port, timeout

    def scan(self, path: Path) -> ScanResult:
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
                sock.settimeout(self.timeout)
                sock.sendall(b"zINSTREAM\0")
                with path.open("rb") as handle:
                    while chunk := handle.read(CHUNK):
                        sock.sendall(struct.pack(">I", len(chunk)) + chunk)
                sock.sendall(struct.pack(">I", 0))
                reply = b""
                while not reply.endswith(b"\0") and (part := sock.recv(4096)):
                    reply += part
        except (OSError, TimeoutError):
            return ScanResult("failed", "scanner unreachable")
        text = reply.rstrip(b"\0").decode("utf-8", "replace").strip()
        if text.endswith("OK"):
            return ScanResult("clean")
        if text.endswith("FOUND"):
            signature = text.removeprefix("stream:").removesuffix("FOUND").strip()
            return ScanResult("infected", signature[:150])
        return ScanResult("failed", "scanner error")


def build_scanner(settings: Settings) -> Scanner:
    if settings.SCANNER_BACKEND == "clamav":
        return ClamdScanner(
            settings.CLAMD_HOST, settings.CLAMD_PORT, settings.CLAMD_TIMEOUT_SECONDS
        )
    return DevScanner()
