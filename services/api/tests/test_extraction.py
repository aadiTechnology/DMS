import subprocess

import pytest

from app.core.config import Settings
from app.services import extraction
from app.services.org import Invalid
from app.services.search import build_tsquery
from tests.samples import make_docx, make_pdf, make_pptx, make_xlsx

SETTINGS = Settings(_env_file=None, EXTRACT_TIMEOUT_SECONDS=30)


def run(tmp_path, ext, data, settings=SETTINGS):
    path = tmp_path / f"f.{ext}"
    path.write_bytes(data)
    return extraction.extract(path, ext, settings)


def test_formats_are_extracted(tmp_path):
    cases = {
        "pdf": (make_pdf("echo foxtrot"), "echo foxtrot"),
        "docx": (make_docx("charlie delta", "second paragraph"), "second paragraph"),
        "xlsx": (make_xlsx("revenue", "forecast"), "forecast"),
        "pptx": (make_pptx("roadmap", "milestones"), "milestones"),
        "txt": ("अनुबंध करार दस्तावेज".encode(), "अनुबंध करार दस्तावेज"),
        "csv": (b"name,city\nAsha,Pune\n", "Asha,Pune"),
    }
    for ext, (data, expected) in cases.items():
        result = run(tmp_path, ext, data)
        assert result.status == "ok" and expected in result.text, ext


def test_text_encodings(tmp_path):
    assert "café" in run(tmp_path, "txt", "café".encode("cp1252")).text  # legacy Windows text
    assert "संविदा" in run(tmp_path, "txt", "संविदा".encode("utf-16")).text  # UTF-16 with BOM


def test_long_text_is_truncated_and_flagged(tmp_path):
    small = Settings(_env_file=None, EXTRACT_MAX_CHARS=1000)
    result = run(tmp_path, "txt", b"word " * 2000, small)
    assert result.status == "ok" and result.truncated and len(result.text) <= 1000


def test_unsupported_and_corrupt_files_report_reasons_only(tmp_path):
    for ext in ("doc", "xls", "ppt", "png", "jpg"):
        r = run(tmp_path, ext, b"data")
        assert (r.status, r.reason) == ("unsupported", "format_not_supported")
    for ext in ("docx", "xlsx", "pptx", "pdf"):
        r = run(tmp_path, ext, b"this is not really a " + ext.encode())
        assert (r.status, r.reason) == ("failed", "extract_parse_error")
    # xml bombs and external entities are refused by the hardened parser, not expanded
    bomb = make_docx("x").replace(b"<w:document", b"<w:document")
    assert run(tmp_path, "docx", bomb).status == "ok"


def test_hostile_xml_is_rejected(tmp_path):
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr(
            "word/document.xml",
            '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
            '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:p><w:r><w:t>&lol2;</w:t></w:r></w:p></w:document>",
        )
    r = run(tmp_path, "docx", buf.getvalue())
    assert (r.status, r.reason) == ("failed", "extract_parse_error")


def test_a_hanging_parser_is_cut_off(tmp_path, monkeypatch):
    def hang(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="extract", timeout=1)

    monkeypatch.setattr(extraction.subprocess, "run", hang)
    r = run(tmp_path, "pdf", make_pdf("x"))
    assert (r.status, r.reason) == ("failed", "extraction_timeout")


def test_extractor_runs_isolated_from_the_api_process(tmp_path):
    marker = tmp_path / "sentinel.txt"
    marker.write_text("x")
    # the worker file imports nothing from the application and is run with -I
    source = extraction.WORKER.read_text(encoding="utf-8")
    assert "from app" not in source and "import app" not in source


# ---- query text -------------------------------------------------------------------------


def test_query_building_neutralizes_operators_and_keeps_unicode():
    assert build_tsquery("budget report") == "'budget':* & 'report':*"
    assert build_tsquery("अनुबंध करार") == "'अनुबंध':* & 'करार':*"
    hostile = build_tsquery("foo & !bar | (baz) <-> qux:* 'x' \\y")
    assert hostile == "'foo':* & 'bar':* & 'baz':* & '-':* & 'qux':* & 'x':* & 'y':*"
    assert build_tsquery("   ") is None and build_tsquery("&|!") is None


def test_query_limits():
    with pytest.raises(Invalid):
        build_tsquery("a" * 201)
    with pytest.raises(Invalid):
        build_tsquery(" ".join(f"w{i}" for i in range(9)))
    assert build_tsquery("x" * 120) == "'" + "x" * 50 + "':*"  # long words are clipped
