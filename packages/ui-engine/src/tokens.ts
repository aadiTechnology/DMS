import type { UiTemplate } from "./types";

// Fixed lookup tables: a template only ever names one of these, it can never supply CSS itself.
export const FONT_STACKS: Record<UiTemplate["theme"]["typography"]["fontFamily"], string> = {
  "system-sans": 'system-ui, "Segoe UI", Roboto, Arial, sans-serif',
  humanist: '"Segoe UI", "Trebuchet MS", Calibri, sans-serif',
  geometric: '"Century Gothic", "Avenir Next", "Segoe UI", Verdana, sans-serif',
  editorial: 'Georgia, "Iowan Old Style", "Times New Roman", serif',
  "compact-sans": '"Segoe UI", "Arial Narrow", Arial, sans-serif',
};

export const SHADOW_VALUES: Record<UiTemplate["theme"]["shadow"], string> = {
  none: "none",
  soft: "0 1px 3px rgba(15,23,42,.08), 0 1px 2px rgba(15,23,42,.05)",
  medium: "0 10px 28px rgba(60,60,160,.16)",
  strong: "0 14px 34px rgba(0,0,0,.5)",
};

export interface DensityTokens {
  /** vertical padding of a table cell, in px */
  cell: number;
  /** height of a button or input, in px */
  control: number;
  /** padding inside a card, in px */
  card: number;
}

export const DENSITY: Record<UiTemplate["density"], DensityTokens> = {
  compact: { cell: 4, control: 28, card: 12 },
  comfortable: { cell: 10, control: 36, card: 18 },
  spacious: { cell: 16, control: 44, card: 28 },
};

/** CSS custom properties for a template, for use by any page that needs a raw color or size. */
export function cssVariables(t: UiTemplate): Record<string, string> {
  const c = t.theme.colors;
  const d = DENSITY[t.density];
  const vars: Record<string, string> = {
    "--dms-primary": c.primary,
    "--dms-secondary": c.secondary,
    "--dms-background": c.background,
    "--dms-surface": c.surface,
    "--dms-text": c.textPrimary,
    "--dms-text-secondary": c.textSecondary,
    "--dms-border": c.border,
    "--dms-success": c.success,
    "--dms-warning": c.warning,
    "--dms-error": c.error,
    "--dms-info": c.info,
    "--dms-radius": `${t.theme.radius}px`,
    "--dms-shadow": SHADOW_VALUES[t.theme.shadow],
    "--dms-font": FONT_STACKS[t.theme.typography.fontFamily],
    "--dms-page-spacing": `${t.layout.pageSpacing}px`,
    "--dms-sidebar-width": `${t.layout.sidebarWidth}px`,
    "--dms-control-height": `${d.control}px`,
    "--dms-card-padding": `${d.card}px`,
    "--dms-cell-padding": `${d.cell}px`,
  };
  c.chart.forEach((color, i) => {
    vars[`--dms-chart-${i + 1}`] = color;
  });
  return vars;
}
