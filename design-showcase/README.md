# DMS design showcase (Sprint T0)

Open `dms-design-showcase.html` in any browser (no server needed). Use the buttons along the top to switch between the five designs; use the left or top navigation to move through the eight screens (Dashboard, Documents, Document details, Upload, Approval workflow, Search and filters, Users, Reports). The same sample data is used in every design. **Template JSON** shows the configuration that is producing the current design.

| # | Template key | Look |
|---|---|---|
| 1 | `modern-enterprise` | White, blue, full sidebar, outlined cards, zebra tables |
| 2 | `premium-dark` | Navy, gold accent, glass cards, hero dashboard, tabbed details |
| 3 | `minimalist-productivity` | Top navigation, serif type, no borders, list explorer, spacious |
| 4 | `modern-saas` | Indigo, floating sidebar, gradient cards, pill buttons, card-grid explorer |
| 5 | `enterprise-productivity` | Icon rail plus folder tree, compact dense tables, workflow dashboard |

## Files

- `templates/*.json`: the five designs. They are the only source of the colors, layout and component styles; nothing about a design is written into the page code.
- `showcase.template.html`: the page, which reads whichever template is selected and applies it (CSS variables for the theme, fixed variants for layout and components).
- `build-showcase.mjs`: embeds the five JSON files into the page and writes `dms-design-showcase.html`.
- `check-templates.mjs`: checks that all templates have exactly the same structure and use only allowed values (the formal JSON Schema comes in the next sprint).

## Change or add a design

1. Edit a JSON file in `templates/` (values must come from the allowed lists in `check-templates.mjs`).
2. `node design-showcase/check-templates.mjs` then `node design-showcase/build-showcase.mjs`.

## What a template can control

Theme (colors, chart colors, font family from a fixed list, text scale, heading weight, corner radius, shadow), layout (sidebar variant and width, header variant, content width, page spacing, navigation position), density, one variant for each of eight components (card, button, table, input, dropdown, tabs, dialog, badge), a layout preset for four pages (dashboard, document explorer, document details, reports) and the dashboard widgets (visibility, order, width and height on a 12-column grid). A template contains no code, HTML or free-form styling.
