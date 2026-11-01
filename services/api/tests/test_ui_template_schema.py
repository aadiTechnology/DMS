import copy
import json
from pathlib import Path

import pytest

from app.ui.templates import SCHEMA_PATH, validate_template

ROOT = Path(__file__).resolve().parents[3]
SHARED_SCHEMA = ROOT / "packages" / "ui-engine" / "schema" / "ui-template.schema.json"
TEMPLATES = sorted((ROOT / "design-showcase" / "templates").glob("*.json"))
CASES = json.loads(
    (ROOT / "packages" / "ui-engine" / "fixtures" / "invalid-cases.json").read_text("utf-8")
)["cases"]


def load(path):
    return json.loads(path.read_text("utf-8"))


def base():
    return load(ROOT / "design-showcase" / "templates" / "modern-enterprise.json")


def apply(template, case):
    parts = case["path"].split(".")
    last = parts.pop()
    targets = [template]
    for p in parts:
        targets = [
            x
            for t in targets
            for x in (t if p == "*" else [t[int(p) if isinstance(t, list) else p]])
        ]
    for t in targets:
        keys = (
            list(range(len(t)))
            if last == "*" and isinstance(t, list)
            else list(t)
            if last == "*"
            else [int(last) if isinstance(t, list) else last]
        )
        for k in keys:
            if case.get("remove"):
                del t[k]
            elif "repeat" in case:
                t[k] = case["repeat"]["char"] * case["repeat"]["times"]
            else:
                t[k] = case["value"]
    return template


def test_server_copy_of_the_schema_is_identical_to_the_shared_one():
    assert SCHEMA_PATH.read_bytes().replace(b"\r\n", b"\n") == SHARED_SCHEMA.read_bytes().replace(
        b"\r\n", b"\n"
    )


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_shipped_templates_are_valid(path):
    result = validate_template(load(path))
    assert result.errors == [] and result.valid


def test_there_are_five_shipped_templates():
    assert len(TEMPLATES) == 5


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_unsafe_or_malformed_templates_are_rejected(case):
    result = validate_template(apply(base(), copy.deepcopy(case)))
    assert not result.valid and result.errors


def test_json_text_and_bytes_are_accepted():
    text = json.dumps(base())
    assert validate_template(text).valid
    assert validate_template(text.encode()).valid


@pytest.mark.parametrize("bad", ["{ nope", "", "null", "[]", "5", b"\xff\xfe", "[" * 5000])
def test_garbage_is_rejected_without_raising(bad):
    assert not validate_template(bad).valid


@pytest.mark.parametrize("value", [None, 5, "x", [], True])
def test_non_objects_are_rejected(value):
    assert not validate_template(value).valid


def test_oversized_files_are_rejected_before_parsing():
    result = validate_template(" " * (64 * 1024 + 1))
    assert result.errors == ["the file is larger than 64 KB"]


def test_validation_does_not_change_its_input():
    t = base()
    before = json.dumps(t)
    validate_template(t)
    assert json.dumps(t) == before


def test_error_messages_point_at_the_problem_and_stay_short():
    t = base()
    t["theme"]["colors"]["primary"] = "red"
    result = validate_template(t)
    assert result.errors[0].startswith("theme.colors.primary:")
    assert all(len(e) <= 300 for e in result.errors)


def test_the_designs_shipped_in_the_api_image_match_the_showcase_files():
    shipped = ROOT / "services" / "api" / "app" / "ui" / "templates"
    originals = {p.name: p.read_bytes() for p in TEMPLATES}
    copies = {p.name: p.read_bytes() for p in shipped.glob("*.json")}
    assert (
        originals == copies
    )  # run `cp design-showcase/templates/*.json services/api/app/ui/templates/` after editing a design
