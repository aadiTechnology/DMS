// Structural check of the template files (the formal JSON Schema arrives in the next sprint).
// Every template must have exactly the same shape and use only the allowed values.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const ORDER = ["modern-enterprise", "premium-dark", "minimalist-productivity", "modern-saas", "enterprise-productivity"];

const ALLOWED = {
  "theme.mode": ["light", "dark"],
  "theme.typography.fontFamily": ["system-sans", "humanist", "geometric", "editorial", "compact-sans"],
  "theme.shadow": ["none", "soft", "medium", "strong"],
  "layout.sidebarVariant": ["full", "floating", "rail-tree", "top"],
  "layout.headerVariant": ["search", "minimal", "pill", "toolbar"],
  "layout.contentWidth": ["fluid", "contained", "narrow"],
  "layout.navigationPosition": ["left", "top"],
  density: ["compact", "comfortable", "spacious"],
  "components.card": ["outlined", "elevated", "flat", "glass", "gradient"],
  "components.button": ["solid", "soft", "outline", "pill"],
  "components.table": ["zebra", "plain", "lined", "dense"],
  "components.input": ["outlined", "filled", "underline"],
  "components.dropdown": ["outlined", "filled", "underline"],
  "components.tabs": ["underline", "pills", "segmented"],
  "components.dialog": ["standard", "rounded", "flat"],
  "components.badge": ["soft", "filled", "outlined", "dot"],
  "pages.dashboard.layout": ["stats-and-panels", "dark-hero", "focus-list", "dense-grid"],
  "pages.documentExplorer.layout": ["table", "list", "grid", "tree-table"],
  "pages.documentDetails.layout": ["two-column", "tabbed", "stacked"],
  "pages.reports.layout": ["grid", "stacked"],
};
const WIDGETS = ["welcome", "stat-documents", "stat-pending", "stat-shared", "stat-storage", "chart-uploads", "chart-classification", "recent-documents", "approvals-queue", "activity", "expiring-soon"];
const COLOR = /^#[0-9a-fA-F]{6}$/;

const get = (o, p) => p.split(".").reduce((a, k) => a?.[k], o);

function shape(value, prefix = "") {
  if (Array.isArray(value)) return [prefix + "[]"];
  if (value && typeof value === "object") return Object.keys(value).sort().flatMap((k) => shape(value[k], `${prefix}${k}.`));
  return [prefix.replace(/\.$/, "")];
}

export function checkOne(file, template) {
  const out = [];
  const bad = (m) => out.push(`${file}: ${m}`);
  for (const [path, values] of Object.entries(ALLOWED)) if (!values.includes(get(template, path))) bad(`${path} must be one of ${values.join(", ")}`);
  for (const [k, v] of Object.entries(template.theme.colors)) {
    if (k === "chart") {
      if (!Array.isArray(v) || v.length !== 5 || !v.every((c) => COLOR.test(c))) bad("theme.colors.chart needs five hex colors");
    } else if (!COLOR.test(v)) bad(`theme.colors.${k} must be a #rrggbb color`);
  }
  if (!/^\d+\.\d+\.\d+$/.test(template.version)) bad("version must be x.y.z");
  if (template.schemaVersion !== "1.0") bad("schemaVersion must be 1.0");
  if (!Number.isInteger(template.theme.radius) || template.theme.radius < 0 || template.theme.radius > 32) bad("radius must be 0-32");
  const ids = template.pages.dashboard.widgets.map((w) => w.id);
  if (new Set(ids).size !== ids.length || ids.slice().sort().join() !== WIDGETS.slice().sort().join()) bad("dashboard widgets must list each known widget exactly once");
  for (const w of template.pages.dashboard.widgets) {
    if (w.w < 1 || w.w > template.pages.dashboard.grid.columns) bad(`widget ${w.id} width outside the grid`);
    if (typeof w.visible !== "boolean") bad(`widget ${w.id} visible must be true or false`);
  }
  if (!template.pages.dashboard.widgets.some((w) => w.visible)) bad("at least one widget must be visible");
  return out;
}

export function checkAll(dir) {
  const problems = [];
  const files = fs.readdirSync(dir).filter((f) => f.endsWith(".json")).sort();
  if (files.join() !== ORDER.map((k) => `${k}.json`).sort().join()) problems.push(`expected exactly: ${ORDER.join(", ")}`);
  let reference = null;
  const keys = new Set();
  for (const f of files) {
    let t;
    try {
      t = JSON.parse(fs.readFileSync(path.join(dir, f), "utf8"));
    } catch (e) {
      problems.push(`${f}: not valid JSON (${e.message})`);
      continue;
    }
    if (t.key !== f.replace(/\.json$/, "")) problems.push(`${f}: key must equal the file name`);
    if (keys.has(t.key)) problems.push(`${f}: duplicate key`);
    keys.add(t.key);
    problems.push(...checkOne(f, t));
    const s = shape(t).join("|");
    if (reference === null) reference = s;
    else if (s !== reference) problems.push(`${f}: structure differs from the other templates`);
  }
  return problems;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const problems = checkAll(path.join(path.dirname(fileURLToPath(import.meta.url)), "templates"));
  console.log(problems.length ? problems.join("\n") : `OK: ${ORDER.length} templates share one structure and use only allowed values`);
  process.exit(problems.length ? 1 : 0);
}
