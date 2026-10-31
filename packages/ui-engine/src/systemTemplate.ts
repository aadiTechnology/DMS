import type { UiTemplate } from "./types";

/**
 * The built-in design, used when nothing else is available (not signed in, offline, or every
 * other template failed validation). It is the last step of the fallback chain, so it is code,
 * not data; it passes the same schema as every stored template (a test checks this).
 */
export const SYSTEM_TEMPLATE: UiTemplate = {
  schemaVersion: "1.0",
  key: "system-default",
  name: "System default",
  description: "The built-in design used when no other design applies.",
  version: "1.0.0",
  theme: {
    mode: "light",
    colors: {
      primary: "#1f4e8c",
      secondary: "#0f766e",
      background: "#f5f7fa",
      surface: "#ffffff",
      textPrimary: "#1f2937",
      textSecondary: "#4b5563",
      border: "#e2e8f0",
      success: "#15803d",
      warning: "#b45309",
      error: "#b91c1c",
      info: "#0369a1",
      chart: ["#1f4e8c", "#0f766e", "#f59e0b", "#7c3aed", "#94a3b8"],
    },
    typography: { fontFamily: "humanist", scale: 1, headingWeight: 600 },
    radius: 8,
    shadow: "none",
  },
  layout: {
    sidebarVariant: "full",
    sidebarWidth: 232,
    headerVariant: "minimal",
    contentWidth: "fluid",
    pageSpacing: 24,
    navigationPosition: "left",
  },
  density: "comfortable",
  components: {
    card: "outlined",
    button: "solid",
    table: "plain",
    input: "outlined",
    dropdown: "outlined",
    tabs: "underline",
    dialog: "standard",
    badge: "filled",
  },
  pages: {
    dashboard: {
      layout: "stats-and-panels",
      grid: { columns: 12 },
      widgets: [
        { id: "stat-documents", visible: true, order: 1, w: 3, h: 1 },
        { id: "stat-pending", visible: true, order: 2, w: 3, h: 1 },
        { id: "stat-shared", visible: true, order: 3, w: 3, h: 1 },
        { id: "stat-storage", visible: true, order: 4, w: 3, h: 1 },
        { id: "chart-uploads", visible: true, order: 5, w: 8, h: 2 },
        { id: "chart-classification", visible: true, order: 6, w: 4, h: 2 },
        { id: "recent-documents", visible: true, order: 7, w: 7, h: 2 },
        { id: "approvals-queue", visible: true, order: 8, w: 5, h: 2 },
        { id: "welcome", visible: false, order: 9, w: 12, h: 1 },
        { id: "activity", visible: false, order: 10, w: 6, h: 2 },
        { id: "expiring-soon", visible: false, order: 11, w: 6, h: 2 },
      ],
    },
    documentExplorer: { layout: "table" },
    documentDetails: { layout: "two-column" },
    reports: { layout: "grid" },
  },
};
