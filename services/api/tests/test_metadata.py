import uuid
from pathlib import Path

import pytest

from app.services.metadata import (
    FIELD_TYPES,
    MetadataInvalid,
    validate_definition,
    validate_field_set,
    validate_values,
)


def field(key="f", ftype="text", **kw):
    return {"key": key, "label": kw.pop("label", "Field"), "field_type": ftype, **kw}


def fields(*defs):
    return validate_field_set(list(defs))


def bad(*defs_and_values):
    with pytest.raises(MetadataInvalid) as exc:
        validate_values(*defs_and_values)
    return exc.value.errors


# ---- definitions ------------------------------------------------------------------------


def test_all_prd_field_types_are_supported():
    assert set(FIELD_TYPES) == {
        "text", "long_text", "number", "decimal", "date", "date_range", "boolean",
        "single_select", "multi_select", "employee_lookup", "department_lookup",
        "branch_lookup", "project_lookup", "tag_selector",
    }  # fmt: skip
    for ftype in FIELD_TYPES:
        extra = {"validation": {"options": ["a", "b"]}} if ftype.endswith("_select") else {}
        assert validate_definition(field("x", ftype, **extra))["field_type"] == ftype


@pytest.mark.parametrize(
    ("definition", "fragment"),
    [
        (field("Bad Key"), "key"),
        (field("1abc"), "key"),
        (field("a" * 41), "key"),
        (field("x", "nonsense"), "unknown field type"),
        (field("x", label=" "), "label"),
        (field("x", "number", validation={"min_length": 1}), "not valid for number"),
        (field("x", "text", validation={"min_length": 5, "max_length": 2}), "cannot exceed"),
        (field("x", "text", validation={"pattern": "([a-z"}), "regular expression"),
        (field("x", "text", validation={"pattern": "a" * 201}), "1-200"),
        (field("x", "number", validation={"min": 5, "max": 1}), "min cannot exceed max"),
        (field("x", "number", validation={"min": 1.5}), "whole number"),
        (field("x", "date", validation={"min": "2025-13-01"}), "date"),
        (field("x", "single_select"), "options"),
        (field("x", "single_select", validation={"options": ["a", "A"]}), "distinct"),
        (field("x", "single_select", validation={"options": [""]}), "options"),
        (field("x", "number", default_value="abc"), "default value"),
        (
            field("x", "single_select", validation={"options": ["a"]}, default_value="z"),
            "default value",
        ),
    ],
)
def test_invalid_definitions_are_rejected(definition, fragment):
    with pytest.raises(MetadataInvalid) as exc:
        validate_definition(definition)
    assert fragment in " ".join(exc.value.errors.values()).lower() or fragment in str(exc.value)


def test_field_set_limits_and_duplicates():
    with pytest.raises(MetadataInvalid, match="unique"):
        fields(field("a"), field("a"))
    with pytest.raises(MetadataInvalid, match="at most"):
        validate_field_set([field(f"k{i}") for i in range(61)])


# ---- values -----------------------------------------------------------------------------


def test_text_rules_and_unicode():
    f = fields(
        field("code", validation={"min_length": 2, "max_length": 8, "pattern": r"[A-Z]{2}-\d+"})
    )
    assert validate_values(f, {"code": "AB-12"}) == {"code": "AB-12"}
    assert "format" in bad(f, {"code": "ab-12"})["code"]
    assert "at least" in bad(f, {"code": "A"})["code"]
    assert "at most" in bad(f, {"code": "AB-1234567"})["code"]
    free = fields(field("note", "long_text"))
    text = "अनुबंध करार – प्रकल्प अहवाल"
    assert validate_values(free, {"note": text}) == {"note": text}  # I18N-003


def test_numbers_decimals_dates():
    f = fields(
        field("qty", "number", validation={"min": 1, "max": 10}),
        field("amount", "decimal", validation={"min": "0", "max": "1000.00", "precision": 2}),
        field("when", "date", validation={"min": "2025-01-01", "max": "2030-12-31"}),
    )
    ok = validate_values(f, {"qty": 3, "amount": "12.50", "when": "2026-02-03"})
    assert ok == {"qty": 3, "amount": "12.50", "when": "2026-02-03"}
    errors = bad(f, {"qty": 11, "amount": "12.505", "when": "2031-01-01"})
    assert set(errors) == {"qty", "amount", "when"}
    assert "whole number" in bad(f, {"qty": 2.5})["qty"]
    assert "whole number" in bad(f, {"qty": True})["qty"]  # booleans are not numbers
    assert (
        "decimal" in bad(f, {"amount": "NaN"})["amount"]
        or "finite" in bad(f, {"amount": "NaN"})["amount"]
    )
    assert "date" in bad(f, {"when": "03/02/2026"})["when"]


def test_date_range_boolean_and_selects():
    f = fields(
        field("period", "date_range"),
        field("signed", "boolean"),
        field("status", "single_select", validation={"options": ["draft", "final"]}),
        field(
            "units",
            "multi_select",
            validation={"options": ["a", "b", "c"], "min_items": 1, "max_items": 2},
        ),
    )
    ok = validate_values(
        f,
        {"period": {"start": "2026-01-01", "end": "2026-12-31"}, "signed": False,
         "status": "final", "units": ["a", "c"]},
    )  # fmt: skip
    assert ok["units"] == ["a", "c"]
    assert "after" in bad(f, {"period": {"start": "2026-12-31", "end": "2026-01-01"}})["period"]
    assert "true or false" in bad(f, {"signed": "yes"})["signed"]
    assert "allowed" in bad(f, {"status": "other"})["status"]
    assert "at most" in bad(f, {"units": ["a", "b", "c"]})["units"]
    assert "distinct" in bad(f, {"units": ["a", "a"]})["units"]
    assert "not allowed" in bad(f, {"units": ["z"]})["units"]


def test_lookups_and_tags_need_ids():
    f = fields(
        field("owner", "employee_lookup"),
        field("labels", "tag_selector", validation={"max_items": 2}),
    )
    a, b, c = (str(uuid.uuid4()) for _ in range(3))
    assert validate_values(f, {"owner": a, "labels": [b, c]}) == {"owner": a, "labels": [b, c]}
    assert "id" in bad(f, {"owner": "not-an-id"})["owner"]
    assert "at most" in bad(f, {"labels": [a, b, c]})["labels"]


def test_required_defaults_unknown_keys_and_drafts():
    f = fields(
        field("must", required=True),
        field(
            "level", "single_select", validation={"options": ["low", "high"]}, default_value="low"
        ),
    )
    assert bad(f, {}) == {"must": "is required"}
    assert validate_values(f, {}, require_complete=False) == {
        "level": "low"
    }  # draft save + default
    assert validate_values(f, {"must": "x", "level": "high"}) == {"must": "x", "level": "high"}
    assert "not a field" in bad(f, {"must": "x", "other": 1})["other"]
    assert (
        validate_values(f, {"must": "x", "level": None})["level"] == "low"
    )  # None falls back to default


def test_field_types_match_typescript_contract():
    ts = (
        Path(__file__)
        .parents[3]
        .joinpath("packages/domain/src/index.ts")
        .read_text(encoding="utf-8")
    )
    block = ts[ts.index("METADATA_FIELD_TYPES") :]
    listed = tuple(
        x
        for x in block.split("[", 1)[1]
        .split("]", 1)[0]
        .replace('"', "")
        .replace("\n", "")
        .split(",")
        if x.strip()
    )
    assert tuple(s.strip() for s in listed) == FIELD_TYPES
