# UI template system: architecture

Purpose: let Aadi Technology add new looks for the DMS (and later other products) as plain configuration, and let every person choose their own look, without changing React code or redeploying. No visual editor and no drag-and-drop: a catalogue of designs to preview and select.

## 1. The pieces

| Piece | Where | Owns | Does not own |
|---|---|---|---|
| Template file (JSON) | `design-showcase/templates/*.json`, later any file uploaded by a platform administrator | One design: colors, type, shape, layout choices, component variants, page presets, dashboard widgets | Code, HTML, free CSS |
| Schema | `packages/ui-engine/schema/ui-template.schema.json` (copy at `services/api/app/ui/`) | What a template may contain; every value from a fixed list or a bounded range | Business rules |
| Validators | `@aaditech/ui-engine` (Ajv) and `services/api/app/ui/templates.py` (jsonschema) | Same schema plus the same extra rules, so both sides agree | |
| Catalogue and preferences | PostgreSQL: `ui_templates`, `ui_template_versions`, `user_ui_preferences`, `tenant_ui_defaults`; `platform_admins` | Templates, history, each person's choice, the organization default, who may publish | |
| Services and APIs | `services/api/app/ui/service.py`, `app/api/ui_templates.py`, `app/api/platform_ui.py` | Availability, fallback order, import, publish, archive | Sign-in and permissions (existing layers decide who may call) |
| Engine | `@aaditech/ui-engine` | Turning a validated template into a theme, shell and presets | Authentication, authorization, data loading, routing, tenant lookup |
| Web integration | `apps/web` (`App.tsx`, `Layout.tsx`, `appearance.tsx`, pages) | Loading the person's design, previews, the Appearance and Design catalogue pages | |

## 2. How a design reaches the screen

```
platform administrator            organization member
        |                                  |
  upload JSON file                  open the web app
        v                                  v
 validate (schema + rules)        GET /me/ui-preferences
        v                                  v
 draft  --publish-->  PostgreSQL  <--  user choice -> organization default
                                       -> product default -> built-in theme
                                          (each step skipped if unpublished,
                                           not available, or invalid)
                                           v
                          browser validates again (Ajv), caches per person
                                           v
                  TemplateProvider -> MUI theme + CSS variables
                  LayoutRenderer   -> sidebar/top, header
                  pages            -> explorer and details presets
```

Resolution order (server and browser): the person's own valid choice, the organization's default, the product default (`UI_DEFAULT_TEMPLATE_KEY`, normally `modern-enterprise`), then the built-in `SYSTEM_TEMPLATE`. The login page always uses the built-in design. A design is applied only if it is published, available to that organization (a platform template, or the organization's own) and passes validation, on the server **and** again in the browser.

## 3. Security boundaries

- **Templates are data.** The schema has `additionalProperties: false` everywhere, colors are `#rrggbb`, fonts are chosen from five named stacks, and every variant is an enum. Names and descriptions cannot contain `<` or `>`; preview image addresses are limited to `https://...` or `/ui-previews/...`. The engine maps names to fixed styles, so nothing in a file can become script, markup or CSS. 49 shared hostile or malformed cases are run by both the TypeScript and Python test suites.
- **Writing the catalogue is separate from tenant work.** Only the `dms_platform` database role can write templates; it has no access to any organization's data, and organization sessions can only read published platform templates and their own. The platform administrator list (`platform_admins`) can be changed only by the operator command, never by the web or API; the last administrator cannot be removed; access is checked on every request and the two-step verification rule applies in production.
- **A person's choice is theirs alone.** Preferences are rows per organization, person and product under row-level security; the API changes only the signed-in person's row. Choosing a design touches no document, permission or workflow data.
- **Audit.** Preference changes, organization default changes and every platform action (import, publish, archive) are audit events; platform actions are flagged privileged and recorded in the administrator's own organization log.
- **Size limits.** Template files over 64 KB are refused before parsing.

## 4. Extending it

| You want | What to do |
|---|---|
| A new look using existing options | Write a JSON file (see `docs/guides/GENERATING_UI_TEMPLATES.md`), upload it in the Design catalogue, publish. No code. |
| A new allowed value (a new button style, a new sidebar layout) | One code change: add it to the schema (both copies), the engine's style branch and the tests. After that any template can use it. |
| Dashboard or report screens that follow a design | Build the screens once; they read `useTemplate()` and `resolveDashboard()`. The dashboard and report presets already exist in the schema and templates but nothing draws them yet. |
| Another product (for example a CRM) | Use a different `product_code`; the same tables, APIs and engine apply. Not exercised yet. |
| Designs owned by one organization | The `tenant` scope and the read rules exist; there is no screen or API to create them yet. |

## 5. Known limits and decisions

- The built-in design's layout is close to, not identical to, the layout before the engine existed.
- `tree-table` in a template shows the plain table; the icon-rail layout's category panel provides the tree.
- Previews are drawn from the template, not uploaded images; `previewImage` is accepted by the schema but not yet shown.
- The browser caches the last design per person on that device so a reload does not flash the default; it is replaced as soon as the server answers.
- Fonts are system fonts only (no downloaded web fonts), so appearance can differ slightly between computers.
- Designs apply to the web app only; the mobile app will need its own mapping of the same configuration.
