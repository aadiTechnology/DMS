"""Validation of UI templates (JSON documents that describe a look and layout).

A template is data only: fixed choices, bounded numbers and #rrggbb colors. It is checked against
the JSON Schema shared with the web package (`packages/ui-engine/schema`; a test keeps the two
copies identical) plus a few rules a schema cannot express, which the TypeScript validator applies
in exactly the same way. Nothing here executes or renders a template.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator

SCHEMA_PATH = Path(__file__).with_name("ui-template.schema.json")
MAX_TEMPLATE_BYTES = 64 * 1024

_validator = Draft7Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


@dataclass
class TemplateResult:
    template: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return self.template is not None


def _where(error) -> str:
    return ".".join(str(p) for p in error.absolute_path) or "(template)"


def _semantic_errors(t: dict[str, Any]) -> list[str]:
    errors = []
    dashboard = t["pages"]["dashboard"]
    widgets, columns = dashboard["widgets"], dashboard["grid"]["columns"]
    ids = [w["id"] for w in widgets]
    if len(set(ids)) != len(ids):
        errors.append("pages.dashboard.widgets: each widget may appear only once")
    if not any(w["visible"] for w in widgets):
        errors.append("pages.dashboard.widgets: at least one widget must be visible")
    errors += [
        f"pages.dashboard.widgets: {w['id']} is wider than the {columns}-column grid"
        for w in widgets
        if w["w"] > columns
    ]
    layout = t["layout"]
    top = layout["sidebarVariant"] == "top"
    if top != (layout["navigationPosition"] == "top"):
        errors.append("layout: navigationPosition must be top exactly when sidebarVariant is top")
    if not top and layout["sidebarWidth"] < 48:
        errors.append("layout.sidebarWidth: a sidebar needs at least 48 pixels")
    return errors


def validate_template(raw: str | bytes | dict | Any) -> TemplateResult:
    """Check untrusted input (JSON text or a parsed value). Never raises for bad input."""
    value = raw
    if isinstance(raw, (str, bytes)):
        if len(raw) > MAX_TEMPLATE_BYTES:
            return TemplateResult(errors=["the file is larger than 64 KB"])
        try:
            value = json.loads(raw)
        except (ValueError, RecursionError):
            return TemplateResult(errors=["the file is not valid JSON"])
    problems = sorted(_validator.iter_errors(value), key=lambda e: list(map(str, e.absolute_path)))
    if problems:
        return TemplateResult(errors=[f"{_where(e)}: {e.message}"[:300] for e in problems[:25]])
    errors = _semantic_errors(value)
    return TemplateResult(errors=errors) if errors else TemplateResult(template=value)
