# Generating and importing a new design

A design is one JSON file. You can ask Claude to write it, check it, and publish it from the Design catalogue. No programmer is needed and the application is not rebuilt or redeployed.

## 1. Ask Claude for the file

Copy the prompt below into Claude. Replace the text in `[brackets]`. Attach `design-showcase/templates/modern-enterprise.json` as the example and, if possible, `packages/ui-engine/schema/ui-template.schema.json`.

```
Create one JSON file for the Aadi DMS design template schema version 1.0.
Return only the JSON, with no comments and no explanation.

Design brief: [for example: a warm, friendly design for a school office, soft blues and sand, rounded, spacious, top navigation]

Rules:
- Follow the attached example file exactly: same keys, no extra keys.
- "key": lowercase words joined by hyphens, 3 to 64 characters, new and unique, for example "warm-school-office".
- "name" at most 80 characters and "description" at most 300; neither may contain the characters < or >.
- "version": three numbers like "1.0.0".
- Every color is six-digit hex like "#1d4ed8" (no names, no rgb(), no gradients). Give the five "chart" colors as a list of exactly five.
- Use only these values:
  theme.mode: light, dark
  theme.typography.fontFamily: system-sans, humanist, geometric, editorial, compact-sans
  theme.typography.scale: a number from 0.8 to 1.3; headingWeight: 400, 500, 600 or 700
  theme.radius: a whole number from 0 to 32
  theme.shadow: none, soft, medium, strong
  layout.sidebarVariant: full, floating, rail-tree, top
  layout.sidebarWidth: a whole number from 0 to 320 (use 0 only with top, and at least 48 for every other variant)
  layout.headerVariant: search, minimal, pill, toolbar
  layout.contentWidth: fluid, contained, narrow
  layout.pageSpacing: a whole number from 8 to 64
  layout.navigationPosition: top when sidebarVariant is top, otherwise left
  density: compact, comfortable, spacious
  components.card: outlined, elevated, flat, glass, gradient
  components.button: solid, soft, outline, pill
  components.table: zebra, plain, lined, dense
  components.input and components.dropdown: outlined, filled, underline
  components.tabs: underline, pills, segmented
  components.dialog: standard, rounded, flat
  components.badge: soft, filled, outlined, dot
  pages.dashboard.layout: stats-and-panels, dark-hero, focus-list, dense-grid
  pages.dashboard.grid.columns: 6, 8 or 12
  pages.dashboard.widgets: list every one of these exactly once, each with visible (true or false), order (1 to 50), w (1 to the number of grid columns), h (1 to 4): welcome, stat-documents, stat-pending, stat-shared, stat-storage, chart-uploads, chart-classification, recent-documents, approvals-queue, activity, expiring-soon. At least one must be visible.
  pages.documentExplorer.layout: table, list, grid, tree-table
  pages.documentDetails.layout: two-column, tabbed, stacked
  pages.reports.layout: grid, stacked
- Make sure text colors have good contrast against the background and surface colors.
```

Save Claude's answer as a `.json` file (for example `warm-school-office.json`).

## 2. Check and import it

**In the web app (recommended).** Sign in as a platform administrator, open **Design catalogue**, choose the file. The page shows either the problems found or the design's name, description and version, and whether it is new or a newer version of an existing design. Then:

1. **Save as draft** keeps it hidden from everyone, so you can look at it first (see step 3), or
2. **Save and publish** makes it available to every organization at once.

**From the server command line** (for example to load several files at once):

```
cd services/api
uv run python -m app.ui.seed path/to/folder
```

This validates and publishes every `.json` file in the folder; files whose version is already stored are skipped.

**Through the API** (for automation): `POST /api/v1/platform/ui-templates/validate` to check, `POST /api/v1/platform/ui-templates/import?publish=false` to save, `POST /api/v1/platform/ui-templates/{id}/publish` to publish, with the file as the request body. See `docs/architecture/API_REFERENCE.md`.

## 3. Look at it, then release it

A draft is not visible on the Appearance page. To see it first, publish it and preview it yourself; if you are not happy, **Archive** it (it disappears for everyone; people who chose it fall back to their next design). To change a design later, change the JSON, raise the `version` (for example `1.0.1`) and import it again: the earlier versions stay on record under **History**, and the new one is a draft until you publish it, so people keep seeing the old one until then. An archived design cannot be published again; import a new version instead.

## 4. If the file is rejected

The page lists each problem with its location, for example `theme.colors.primary: must match pattern "^#[0-9a-fA-F]{6}$"`. Common causes: a color that is not six-digit hex, a value outside the lists above, an extra key, a missing widget in the dashboard list, a widget wider than the grid, `top` navigation without a `top` sidebar, or text containing `<` or `>`. Paste the message back to Claude and ask it to fix the file.

## 5. What a design can and cannot do

It can change colors, fonts, spacing, corner rounding, shadows, the navigation and header style, the look of cards, buttons, tables, inputs, dropdowns, tabs, dialogs and badges, the preset layout of the document list, the document page, reports and dashboard, and which dashboard widgets show and in what order. It cannot add screens, buttons or fields, change what anyone is allowed to see or do, or contain code. Asking for something outside these options needs a one-time code change that adds a new allowed value; after that any design can use it (see `docs/architecture/UI_TEMPLATE_ARCHITECTURE.md`).
