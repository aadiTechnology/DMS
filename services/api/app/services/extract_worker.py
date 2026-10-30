"""Text extraction, run as a SEPARATE short-lived process (see extraction.py).

Usage: python -I extract_worker.py <extension> <path> <max_chars>
Prints one JSON object: {"text": ..., "truncated": bool} or {"error": "<code>"} (exit code 3).
Self-contained on purpose (standard library + pypdf + defusedxml, no application imports), so a
hostile document can only hang, crash or exhaust this process, never the API. Error codes never
include exception text, which could echo document content.
"""

import json
import sys
import zipfile

MAX_PART_BYTES = 50 * 1024 * 1024
MAX_PDF_PAGES = 500
MAX_TEXT_FILE_BYTES = 20 * 1024 * 1024


class Collector:
    def __init__(self, limit: int):
        self.limit, self.size, self.parts, self.truncated = limit, 0, [], False

    @property
    def full(self) -> bool:
        return self.truncated

    def add(self, text: str) -> None:
        if self.truncated or not text:
            return
        room = self.limit - self.size
        if len(text) > room:
            text, self.truncated = text[:room], True
        self.parts.append(text)
        self.size += len(text)

    def result(self) -> dict:
        return {"text": " ".join(self.parts), "truncated": self.truncated}


def xml_text(archive: zipfile.ZipFile, name: str, out: Collector) -> None:
    from defusedxml.ElementTree import iterparse

    info = archive.getinfo(name)
    if info.file_size > MAX_PART_BYTES:
        raise ValueError("part_too_large")
    with archive.open(name) as handle:
        for _event, element in iterparse(handle, events=("end",)):
            tag = element.tag.rsplit("}", 1)[-1]
            if tag == "t" and element.text:
                out.add(element.text)
            element.clear()
            if out.full:
                return


def from_ooxml(ext: str, path: str, out: Collector) -> None:
    patterns = {
        "docx": lambda n: n == "word/document.xml",
        "xlsx": lambda n: n == "xl/sharedStrings.xml" or n.startswith("xl/worksheets/"),
        "pptx": lambda n: n.startswith("ppt/slides/slide") and n.endswith(".xml"),
    }[ext]
    with zipfile.ZipFile(path) as archive:
        for name in sorted(n for n in archive.namelist() if patterns(n)):
            xml_text(archive, name, out)
            if out.full:
                return


def from_pdf(path: str, out: Collector) -> None:
    from pypdf import PdfReader

    reader = PdfReader(path)
    if reader.is_encrypted:
        raise ValueError("encrypted")
    for index, page in enumerate(reader.pages):
        if index >= MAX_PDF_PAGES:
            out.truncated = True
            return
        out.add(page.extract_text() or "")
        if out.full:
            return


def from_text(path: str, out: Collector) -> None:
    with open(path, "rb") as handle:
        data = handle.read(MAX_TEXT_FILE_BYTES + 1)
    if len(data) > MAX_TEXT_FILE_BYTES:
        out.truncated = True
        data = data[:MAX_TEXT_FILE_BYTES]
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16", errors="replace")
    else:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("cp1252", errors="replace")
    out.add(text)


def main() -> int:
    ext, path, limit = sys.argv[1], sys.argv[2], int(sys.argv[3])
    out = Collector(limit)
    try:
        if ext == "pdf":
            from_pdf(path, out)
        elif ext in ("docx", "xlsx", "pptx"):
            from_ooxml(ext, path, out)
        elif ext in ("txt", "csv"):
            from_text(path, out)
        else:
            print(json.dumps({"error": "unsupported"}))
            return 3
    except ValueError as exc:
        code = str(exc) if str(exc) in ("encrypted", "part_too_large") else "parse_error"
        print(json.dumps({"error": code}))
        return 3
    except Exception:  # noqa: BLE001  (corrupt or hostile input of any kind)
        print(json.dumps({"error": "parse_error"}))
        return 3
    print(json.dumps(out.result()))  # ASCII-escaped: safe whatever the console encoding is
    return 0


if __name__ == "__main__":
    sys.exit(main())
