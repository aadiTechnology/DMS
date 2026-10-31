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

## Storage and access (Sprint T2)

| Table | Holds | Who can touch it |
|---|---|---|
| `ui_templates` | One row per template: key, name, description, current `config_json` (JSONB), version, status (draft, published, archived), scope (platform or tenant) | Organizations can only **read** published platform templates and their own tenant templates. Only the `dms_platform` database role writes. |
| `ui_template_versions` | Every imported version of a template, with its publish time | `dms_platform` only (organizations cannot read it) |
| `user_ui_preferences` | One row per organization, person and product; `template_id` empty means "use the default" | The person's own organization (row-level security); the API only changes the signed-in person's row |
| `tenant_ui_defaults` | The organization's approved default design | Same; changed with `admin.manage_organization` |

Importing: `python -m app.ui.seed <folder>` (from `services/api`) validates each file, stores it and publishes it; re-running skips versions already stored. A higher version of an existing key is stored as a new version and, if imported without publishing, waits as a draft while the old version stays live. The same or an older version is refused.

What a person sees is decided in this order: their own valid choice, the organization default, the product default (`UI_DEFAULT_TEMPLATE_KEY`, default `modern-enterprise`), then the built-in system theme. A template that is unpublished, archived, from another organization, or no longer valid is skipped, never applied.

## Platform administrators and publishing (Sprint T3)

**Who:** a platform administrator is an ordinary user account listed in `platform_admins`. The list is changed **only** by an operator command, never through the web or API (the database roles used by the application cannot write it):

```
cd services/api
uv run python -m app.platform_admin grant person@example.com
uv run python -m app.platform_admin revoke person@example.com
uv run python -m app.platform_admin list
```

On a Coolify server run the same command in the `api` container's terminal. The last active administrator cannot be revoked. Access is checked on every request, so revoking takes effect immediately. When `PLATFORM_ADMIN_REQUIRE_MFA` is true (the default in production) an administrator must have two-step verification turned on.

**Importing a new design (no rebuild or redeployment):**
1. Generate the JSON file (see the next section), then check it: `POST /platform/ui-templates/validate` shows errors, the name and description, and whether the key and version are new.
2. `POST /platform/ui-templates/import` saves it as a **draft**. Drafts are invisible to organizations.
3. `POST /platform/ui-templates/{id}/publish` makes it appear in everyone's design list immediately.
4. `POST /platform/ui-templates/{id}/archive` withdraws an old design. People who chose it fall back to the next design in the chain.

A new version of an existing key is stored in `ui_template_versions`; the live version stays unchanged until the new one is published. The same or an older version is refused.

**Asking Claude for a new design:** give it `packages/ui-engine/schema/ui-template.schema.json` and one of the files in `design-showcase/templates/` as the example, ask for a JSON file only (a new `key`, `name`, `description` and `version`), then run it through the validate call before importing. Only values allowed by the schema will be accepted.

## The rendering engine (Sprint T4)

`@aaditech/ui-engine` turns a validated template into a working look. It owns appearance only: it receives everything it shows as props and does no sign-in, permission checks, routing or data loading.

| Piece | What it does |
|---|---|
| `resolveAppearance()` | Takes the server's `effective` answer, validates the configuration again in the browser and returns the template to use. Anything invalid is skipped: the last cached design for that person, else the built-in design |
| `readCachedTemplate()` / `writeCachedTemplate()` | Remember the last design per person on this device so a page load does not flash the default |
| `SYSTEM_TEMPLATE` | The built-in design, the last step of the fallback chain; it passes the same schema as stored templates |
| `buildMuiTheme()` | The component variant resolver: palette, type, corner radius, density and the eight component variants (card, button, table, input, dropdown, tabs, dialog, badge) as MUI theme rules. Each variant is a fixed branch; a template only chooses between them |
| `TemplateProvider` | Applies the theme and `--dms-*` CSS variables; `useTemplate()` lets a page read which preset layout to use |
| `LayoutRenderer` | The application shell: four navigation layouts (full sidebar, floating sidebar, icon rail with a side panel, top bar) and four headers (search, minimal, pill, toolbar) |
| `resolveDashboard()` | Visible widgets in order with sizes clamped to the grid |

**In the web app** the shell, theme, document list (table, list or grid presets) and document detail (two-column, stacked or tabbed presets) now follow the person's design. `tree-table` in a template is shown as the table preset (the category panel of the rail layout provides the tree). **The dashboard and reports page presets and widgets are resolved but not drawn yet, because those screens do not exist in the application.** Changing design never changes what is loaded or what the person may do.
