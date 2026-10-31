// Types for a UI template (schema version 1.0). The JSON Schema in ../schema is the source of truth;
// these types describe a template that has already passed validation.

export type Color = string;

export interface TemplateColors {
  primary: Color;
  secondary: Color;
  background: Color;
  surface: Color;
  textPrimary: Color;
  textSecondary: Color;
  border: Color;
  success: Color;
  warning: Color;
  error: Color;
  info: Color;
  chart: [Color, Color, Color, Color, Color];
}

export type WidgetId =
  | "welcome"
  | "stat-documents"
  | "stat-pending"
  | "stat-shared"
  | "stat-storage"
  | "chart-uploads"
  | "chart-classification"
  | "recent-documents"
  | "approvals-queue"
  | "activity"
  | "expiring-soon";

export interface WidgetConfig {
  id: WidgetId;
  visible: boolean;
  order: number;
  w: number;
  h: number;
}

export interface UiTemplate {
  schemaVersion: "1.0";
  key: string;
  name: string;
  description: string;
  version: string;
  previewImage?: string;
  theme: {
    mode: "light" | "dark";
    colors: TemplateColors;
    typography: {
      fontFamily: "system-sans" | "humanist" | "geometric" | "editorial" | "compact-sans";
      scale: number;
      headingWeight: 400 | 500 | 600 | 700;
    };
    radius: number;
    shadow: "none" | "soft" | "medium" | "strong";
  };
  layout: {
    sidebarVariant: "full" | "floating" | "rail-tree" | "top";
    sidebarWidth: number;
    headerVariant: "search" | "minimal" | "pill" | "toolbar";
    contentWidth: "fluid" | "contained" | "narrow";
    pageSpacing: number;
    navigationPosition: "left" | "top";
  };
  density: "compact" | "comfortable" | "spacious";
  components: {
    card: "outlined" | "elevated" | "flat" | "glass" | "gradient";
    button: "solid" | "soft" | "outline" | "pill";
    table: "zebra" | "plain" | "lined" | "dense";
    input: "outlined" | "filled" | "underline";
    dropdown: "outlined" | "filled" | "underline";
    tabs: "underline" | "pills" | "segmented";
    dialog: "standard" | "rounded" | "flat";
    badge: "soft" | "filled" | "outlined" | "dot";
  };
  pages: {
    dashboard: {
      layout: "stats-and-panels" | "dark-hero" | "focus-list" | "dense-grid";
      grid: { columns: 6 | 8 | 12 };
      widgets: WidgetConfig[];
    };
    documentExplorer: { layout: "table" | "list" | "grid" | "tree-table" };
    documentDetails: { layout: "two-column" | "tabbed" | "stacked" };
    reports: { layout: "grid" | "stacked" };
  };
}

export type ValidationResult =
  | { valid: true; template: UiTemplate; errors: [] }
  | { valid: false; errors: string[] };
