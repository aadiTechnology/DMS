import Ajv from "ajv";
import schema from "../schema/ui-template.schema.json";
import type { UiTemplate, ValidationResult } from "./types";

// strict:false only because the schema uses the plain "$id"/"definitions" style of draft-07.
const ajv = new Ajv({ allErrors: true, strict: false });
const checkSchema = ajv.compile(schema);

/** Rules a JSON Schema cannot express. The Python server applies exactly the same rules. */
function semanticErrors(t: UiTemplate): string[] {
  const errors: string[] = [];
  const { widgets, grid } = t.pages.dashboard;
  const ids = widgets.map((w) => w.id);
  if (new Set(ids).size !== ids.length) errors.push("pages.dashboard.widgets: each widget may appear only once");
  if (!widgets.some((w) => w.visible)) errors.push("pages.dashboard.widgets: at least one widget must be visible");
  for (const w of widgets) {
    if (w.w > grid.columns) errors.push(`pages.dashboard.widgets: ${w.id} is wider than the ${grid.columns}-column grid`);
  }
  const top = t.layout.sidebarVariant === "top";
  if (top !== (t.layout.navigationPosition === "top")) {
    errors.push("layout: navigationPosition must be top exactly when sidebarVariant is top");
  }
  if (!top && t.layout.sidebarWidth < 48) errors.push("layout.sidebarWidth: a sidebar needs at least 48 pixels");
  return errors;
}

/** Checks untrusted JSON (text or an already-parsed value). Never throws. */
export function validateTemplate(input: unknown): ValidationResult {
  let value = input;
  if (typeof input === "string") {
    try {
      value = JSON.parse(input);
    } catch {
      return { valid: false, errors: ["the file is not valid JSON"] };
    }
  }
  if (!checkSchema(value)) {
    const errors = (checkSchema.errors ?? []).map((e) => `${e.instancePath || "(template)"}: ${e.message ?? "invalid"}`);
    return { valid: false, errors: errors.length ? errors : ["the template does not match the schema"] };
  }
  const template = value as unknown as UiTemplate;
  const errors = semanticErrors(template);
  return errors.length ? { valid: false, errors } : { valid: true, template, errors: [] };
}

export { schema as uiTemplateSchema };
