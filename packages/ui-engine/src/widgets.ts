import type { UiTemplate, WidgetId } from "./types";

export interface ResolvedWidget {
  id: WidgetId;
  /** grid columns the widget spans (never more than the grid has) */
  span: number;
  /** relative height in rows */
  rows: number;
}

export interface ResolvedDashboard {
  layout: UiTemplate["pages"]["dashboard"]["layout"];
  columns: number;
  widgets: ResolvedWidget[];
}

/** Which dashboard widgets to show, in which order and size. Pure: the page decides how to draw each id. */
export function resolveDashboard(t: UiTemplate): ResolvedDashboard {
  const { layout, grid, widgets } = t.pages.dashboard;
  return {
    layout,
    columns: grid.columns,
    widgets: widgets
      .filter((w) => w.visible)
      .sort((a, b) => a.order - b.order || a.id.localeCompare(b.id))
      .map((w) => ({ id: w.id, span: Math.min(w.w, grid.columns), rows: w.h })),
  };
}
