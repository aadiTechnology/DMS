"""Run text extraction in an isolated, time-limited subprocess (PRD 15.1: sandbox file parsers).

The API never parses an untrusted document in its own process. A parser that hangs is killed
after EXTRACT_TIMEOUT_SECONDS; one that crashes or is fed a malformed file reports a short error
code. Windows has no per-process memory limit here, so memory is bounded by the worker's own
caps (pages, part sizes, characters); containerized deployments should add a memory limit.
OCR for scanned files is out of MVP scope: images and legacy Office files are `unsupported`.
"""

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings

WORKER = Path(__file__).with_name("extract_worker.py")
SUPPORTED = frozenset({"pdf", "docx", "xlsx", "pptx", "txt", "csv"})


@dataclass(frozen=True)
class ExtractResult:
    status: str  # ok | unsupported | failed
    text: str = ""
    truncated: bool = False
    reason: str | None = None


def extract(path: Path, ext: str, settings: Settings) -> ExtractResult:
    ext = ext.lower()
    if ext not in SUPPORTED:
        return ExtractResult("unsupported", reason="format_not_supported")
    try:
        proc = subprocess.run(
            [sys.executable, "-I", str(WORKER), ext, str(path), str(settings.EXTRACT_MAX_CHARS)],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=settings.EXTRACT_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ExtractResult("failed", reason="extraction_timeout")
    except OSError:
        return ExtractResult("failed", reason="extractor_unavailable")
    try:
        payload = json.loads(proc.stdout.decode("utf-8", "replace") or "{}")
    except ValueError:
        return ExtractResult("failed", reason="extraction_error")
    if proc.returncode != 0 or "text" not in payload:
        reason = payload.get("error", "extraction_error")
        return ExtractResult("failed", reason=f"extract_{reason}"[:60])
    return ExtractResult("ok", text=payload["text"], truncated=bool(payload.get("truncated")))
