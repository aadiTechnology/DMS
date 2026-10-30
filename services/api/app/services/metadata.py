"""Metadata field definitions and value validation (PRD 6.2, CAT-002).

Field types (PRD 6.2) and the typed JSON representation of their values:
  text, long_text        -> string          (min_length, max_length, pattern)
  number                 -> integer         (min, max)
  decimal                -> string "12.50"  (min, max, precision = max decimal places)
  date                   -> "YYYY-MM-DD"    (min, max)
  date_range             -> {"start","end"} (start <= end)
  boolean                -> true/false
  single_select          -> string in options
  multi_select           -> [string in options] (min_items, max_items)
  employee_lookup / department_lookup / branch_lookup / project_lookup -> UUID string
  tag_selector           -> [UUID string]
Decimals travel as strings so no precision is lost. Whether a looked-up id really exists in the
tenant is checked by the document service (database), not here.
"""

import re
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

FIELD_TYPES = (
    "text",
    "long_text",
    "number",
    "decimal",
    "date",
    "date_range",
    "boolean",
    "single_select",
    "multi_select",
    "employee_lookup",
    "department_lookup",
    "branch_lookup",
    "project_lookup",
    "tag_selector",
)
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
MAX_FIELDS_PER_VERSION = 60
MAX_OPTIONS = 200
MAX_TEXT = 10_000

_ALLOWED_RULES: dict[str, set[str]] = {
    "text": {"min_length", "max_length", "pattern"},
    "long_text": {"min_length", "max_length"},
    "number": {"min", "max"},
    "decimal": {"min", "max", "precision"},
    "date": {"min", "max"},
    "date_range": set(),
    "boolean": set(),
    "single_select": {"options"},
    "multi_select": {"options", "min_items", "max_items"},
    "employee_lookup": set(),
    "department_lookup": set(),
    "branch_lookup": set(),
    "project_lookup": set(),
    "tag_selector": {"min_items", "max_items"},
}


class MetadataInvalid(ValueError):
    """`errors` maps a field key (or "_") to a user-safe message."""

    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_date(value: Any) -> date:
    if not isinstance(value, str):
        raise ValueError("must be a date (YYYY-MM-DD)")  # noqa: TRY004  (callers catch ValueError only)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError("must be a date (YYYY-MM-DD)") from None


def _parse_decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError('must be a decimal number written as text, e.g. "12.50"')  # noqa: TRY004
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError('must be a decimal number written as text, e.g. "12.50"') from None
    if not result.is_finite():
        raise ValueError("must be a finite number")
    return result


def _is_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
        return isinstance(value, str)
    except ValueError:
        return False


# ---- definition (configuration time) ----------------------------------------------------


def validate_definition(field: dict[str, Any]) -> dict[str, Any]:
    """Check an administrator-supplied field definition and return it normalized."""
    errors: dict[str, str] = {}
    key = field.get("key")
    if not isinstance(key, str) or not KEY_PATTERN.match(key):
        raise MetadataInvalid(
            {"key": "must start with a letter; lowercase letters, digits, _; max 40"}
        )
    ftype = field.get("field_type")
    if ftype not in FIELD_TYPES:
        raise MetadataInvalid({key: f"unknown field type; use one of: {', '.join(FIELD_TYPES)}"})
    label = (field.get("label") or "").strip()
    if not label or len(label) > 120:
        errors[key] = "label is required (max 120 characters)"
    rules = dict(field.get("validation") or {})
    unknown = set(rules) - _ALLOWED_RULES[ftype]
    if unknown:
        errors[key] = f"rule(s) not valid for {ftype}: {', '.join(sorted(unknown))}"
    else:
        try:
            _check_rules(ftype, rules)
        except ValueError as exc:
            errors[key] = str(exc)
    normalized = {
        "key": key,
        "label": label,
        "field_type": ftype,
        "required": bool(field.get("required", False)),
        "searchable": bool(field.get("searchable", True)),
        "display_order": int(field.get("display_order", 0)),
        "validation": rules,
        "default_value": field.get("default_value"),
    }
    if not errors and normalized["default_value"] is not None:
        try:
            normalized["default_value"] = _check_value(ftype, rules, normalized["default_value"])
        except ValueError as exc:
            errors[key] = f"default value {exc}"
    if errors:
        raise MetadataInvalid(errors)
    return normalized


def _check_rules(ftype: str, rules: dict[str, Any]) -> None:
    for name in ("min_length", "max_length", "min_items", "max_items", "precision"):
        if name in rules and (not _is_int(rules[name]) or not 0 <= rules[name] <= MAX_TEXT):
            raise ValueError(f"{name} must be a whole number between 0 and {MAX_TEXT}")
    for low, high in (("min_length", "max_length"), ("min_items", "max_items")):
        if low in rules and high in rules and rules[low] > rules[high]:
            raise ValueError(f"{low} cannot exceed {high}")
    if "pattern" in rules:
        pattern = rules["pattern"]
        if not isinstance(pattern, str) or not 1 <= len(pattern) <= 200:
            raise ValueError("pattern must be text of 1-200 characters")
        try:
            re.compile(pattern)
        except re.error:
            raise ValueError("pattern is not a valid regular expression") from None
    if ftype == "number":
        for name in ("min", "max"):
            if name in rules and not _is_int(rules[name]):
                raise ValueError(f"{name} must be a whole number")
    if ftype == "decimal":
        for name in ("min", "max"):
            if name in rules:
                _parse_decimal(rules[name])
    if ftype == "date":
        for name in ("min", "max"):
            if name in rules:
                _parse_date(rules[name])
    if {"min", "max"} <= rules.keys():
        parse = {"number": int, "decimal": _parse_decimal, "date": _parse_date}.get(ftype)
        if parse and parse(rules["min"]) > parse(rules["max"]):
            raise ValueError("min cannot exceed max")
    if ftype in ("single_select", "multi_select"):
        options = rules.get("options")
        if (
            not isinstance(options, list)
            or not 1 <= len(options) <= MAX_OPTIONS
            or not all(isinstance(o, str) and 1 <= len(o.strip()) <= 100 for o in options)
            or len({o.strip().lower() for o in options}) != len(options)
        ):
            raise ValueError(
                f"options must be 1-{MAX_OPTIONS} distinct texts of up to 100 characters"
            )
        rules["options"] = [o.strip() for o in options]


# ---- values (document time) -------------------------------------------------------------


def _check_value(ftype: str, rules: dict[str, Any], value: Any) -> Any:
    """Validate one value; returns the normalized value or raises ValueError(message)."""
    if ftype in ("text", "long_text"):
        if not isinstance(value, str):
            raise ValueError("must be text")
        if len(value) > MAX_TEXT:
            raise ValueError(f"is too long (max {MAX_TEXT})")
        if len(value) < rules.get("min_length", 0):
            raise ValueError(f"must be at least {rules['min_length']} characters")
        if len(value) > rules.get("max_length", MAX_TEXT):
            raise ValueError(f"must be at most {rules['max_length']} characters")
        if "pattern" in rules and not re.fullmatch(rules["pattern"], value):
            raise ValueError("does not match the required format")
        return value
    if ftype == "number":
        if not _is_int(value):
            raise ValueError("must be a whole number")
        if "min" in rules and value < rules["min"]:
            raise ValueError(f"must be at least {rules['min']}")
        if "max" in rules and value > rules["max"]:
            raise ValueError(f"must be at most {rules['max']}")
        return value
    if ftype == "decimal":
        number = _parse_decimal(value)
        places = max(0, -number.as_tuple().exponent)
        if places > rules.get("precision", 6):
            raise ValueError(f"allows at most {rules.get('precision', 6)} decimal places")
        if "min" in rules and number < _parse_decimal(rules["min"]):
            raise ValueError(f"must be at least {rules['min']}")
        if "max" in rules and number > _parse_decimal(rules["max"]):
            raise ValueError(f"must be at most {rules['max']}")
        return format(number, "f")
    if ftype == "date":
        parsed = _parse_date(value)
        if "min" in rules and parsed < _parse_date(rules["min"]):
            raise ValueError(f"must be on or after {rules['min']}")
        if "max" in rules and parsed > _parse_date(rules["max"]):
            raise ValueError(f"must be on or before {rules['max']}")
        return parsed.isoformat()
    if ftype == "date_range":
        if not isinstance(value, dict) or set(value) != {"start", "end"}:
            raise ValueError('must be {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}')
        start, end = _parse_date(value["start"]), _parse_date(value["end"])
        if start > end:
            raise ValueError("start must not be after end")
        return {"start": start.isoformat(), "end": end.isoformat()}
    if ftype == "boolean":
        if not isinstance(value, bool):
            raise ValueError("must be true or false")
        return value
    if ftype == "single_select":
        if value not in rules["options"]:
            raise ValueError("must be one of the allowed options")
        return value
    if ftype == "multi_select":
        if not isinstance(value, list) or len(set(value)) != len(value):
            raise ValueError("must be a list of distinct options")
        if any(v not in rules["options"] for v in value):
            raise ValueError("contains an option that is not allowed")
        _check_count(rules, len(value))
        return value
    if ftype == "tag_selector":
        if (
            not isinstance(value, list)
            or len(set(value)) != len(value)
            or not all(_is_uuid(v) for v in value)
        ):
            raise ValueError("must be a list of distinct tag ids")
        _check_count(rules, len(value))
        return value
    if not _is_uuid(value):  # the four lookup types
        raise ValueError("must be an id")
    return value


def _check_count(rules: dict[str, Any], count: int) -> None:
    if count < rules.get("min_items", 0):
        raise ValueError(f"needs at least {rules['min_items']} item(s)")
    if count > rules.get("max_items", MAX_OPTIONS):
        raise ValueError(f"allows at most {rules['max_items']} item(s)")


def validate_values(
    fields: list[dict[str, Any]], values: dict[str, Any], *, require_complete: bool = True
) -> dict[str, Any]:
    """Validate document metadata against a category version's fields. Unknown keys are rejected,
    defaults fill gaps, required fields must be present (unless saving a draft)."""
    by_key = {f["key"]: f for f in fields}
    errors: dict[str, str] = {}
    for key in values:
        if key not in by_key:
            errors[key] = "is not a field of this category"
    cleaned: dict[str, Any] = {}
    for key, field in by_key.items():
        supplied = key in values and values[key] is not None
        value = values.get(key) if supplied else field.get("default_value")
        if value is None:
            if field["required"] and require_complete:
                errors[key] = "is required"
            continue
        try:
            cleaned[key] = _check_value(field["field_type"], field["validation"], value)
        except ValueError as exc:
            errors[key] = str(exc)
    if errors:
        raise MetadataInvalid(errors)
    return cleaned


def validate_field_set(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(fields) > MAX_FIELDS_PER_VERSION:
        raise MetadataInvalid(
            {"_": f"at most {MAX_FIELDS_PER_VERSION} fields per category version"}
        )
    normalized = [validate_definition(f) for f in fields]
    keys = [f["key"] for f in normalized]
    if len(set(keys)) != len(keys):
        raise MetadataInvalid({"_": "field keys must be unique within a category version"})
    return normalized
