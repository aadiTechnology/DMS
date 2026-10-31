# UI template schema (version 1.0)

A UI template is a small JSON document that describes a look and layout. It is data only: fixed choices, bounded numbers and `#rrggbb` colors. It cannot contain code, HTML, URLs for styling, or free-form CSS, and the engine never executes it.

- **Schema (single source of truth):** `packages/ui-engine/schema/ui-template.schema.json` (JSON Schema draft-07, `additionalProperties: false` everywhere).
- **Browser validator:** `@aaditech/ui-engine` -> `validateTemplate()` (Ajv).
- **Server validator:** `services/api/app/ui/templates.py` -> `validate_template()` (jsonschema). The API image carries its own copy of the schema file; a test fails if it differs from the shared one.
- **Extra rules** that JSON Schema cannot express (applied identically on both sides): each dashboard widget appears once; at least one widget is visible; a widget is not wider than the grid; `navigationPosition` is `top` exactly when `sidebarVariant` is `top`; a sidebar is at least 48 px wide.
- **Shared test cases:** `packages/ui-engine/fixtures/invalid-cases.json` (49 unsafe or malformed templates) is run by both the TypeScript and the Python test suites, and both also validate the five shipped templates.

## Sections

| Section | Controls | Allowed values |
|---|---|---|
| Identity | `key`, `name`, `description`, `version`, optional `previewImage` | key: lowercase words with hyphens; name and description without `<` or `>`; semantic version; image only `https://...` or `/ui-previews/...` with png, jpg or webp |
| `theme` | mode, 11 colors plus 5 chart colors, font family, text scale, heading weight, corner radius, shadow | colors `#rrggbb`; fonts: system-sans, humanist, geometric, editorial, compact-sans; scale 0.8 to 1.3; weight 400 to 700; radius 0 to 32; shadow none, soft, medium, strong |
| `layout` | sidebar variant and width, header variant, content width, page spacing, navigation position | sidebar: full, floating, rail-tree, top; header: search, minimal, pill, toolbar; width: fluid, contained, narrow |
| `density` | compact, comfortable, spacious | |
| `components` | card, button, table, input, dropdown, tabs, dialog, badge | one named variant each, from a fixed list |
| `pages` | dashboard, documentExplorer, documentDetails, reports | preset layout names; dashboard also has grid columns (6, 8 or 12) and the widget list (id, visible, order, width, height) |

Widget ids: welcome, stat-documents, stat-pending, stat-shared, stat-storage, chart-uploads, chart-classification, recent-documents, approvals-queue, activity, expiring-soon.

Files over 64 KB are refused on the server before parsing. Validation never throws for bad input and never changes it.
