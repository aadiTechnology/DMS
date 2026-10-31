import type { CSSProperties } from "react";
import type { UiTemplate } from "./types";

/**
 * A small drawn preview of a design, built from the template's own colors and layout choices, so
 * every template has a thumbnail without any image file. Purely visual (hidden from screen readers).
 */
export function TemplateThumbnail({ template, width = 220 }: { template: UiTemplate; width?: number }) {
  const c = template.theme.colors;
  const { sidebarVariant: side } = template.layout;
  const r = Math.min(template.theme.radius, 10);
  const card = template.components.card;
  const box: CSSProperties = {
    background: card === "flat" ? "transparent" : c.surface,
    borderRadius: r,
    border: card === "elevated" || card === "gradient" ? "none" : `1px solid ${c.border}`,
    boxShadow: template.theme.shadow === "none" || card === "flat" ? "none" : "0 3px 8px rgba(0,0,0,.18)",
  };
  const line = (w: string, color = c.textSecondary): CSSProperties => ({ height: 4, width: w, borderRadius: 2, background: color, opacity: 0.55 });
  const nav = side === "top" ? null : (
    <div style={{ width: side === "rail-tree" ? "10%" : "24%", background: side === "rail-tree" ? c.primary : c.surface, borderRight: `1px solid ${c.border}`, margin: side === "floating" ? 5 : 0, borderRadius: side === "floating" ? r + 2 : 0, boxShadow: side === "floating" ? "0 3px 8px rgba(0,0,0,.16)" : "none", padding: 4, display: "flex", flexDirection: "column", gap: 4 }}>
      {[0, 1, 2, 3].map((i) => (
        <div key={i} style={{ height: 5, borderRadius: 2, background: i === 0 ? c.primary : c.textSecondary, opacity: i === 0 ? 1 : 0.35, width: side === "rail-tree" ? "70%" : "85%" }} />
      ))}
    </div>
  );
  return (
    <div
      aria-hidden="true"
      data-testid="template-thumbnail"
      style={{ width, height: width * 0.62, background: c.background, borderRadius: r, overflow: "hidden", display: "flex", flexDirection: "column", border: `1px solid ${c.border}` }}
    >
      {side === "top" && (
        <div style={{ display: "flex", gap: 5, alignItems: "center", padding: "5px 8px", borderBottom: `1px solid ${c.border}` }}>
          <div style={{ width: 8, height: 8, borderRadius: 2, background: c.primary }} />
          {[0, 1, 2, 3].map((i) => (
            <div key={i} style={line("12%", i === 0 ? c.textPrimary : c.textSecondary)} />
          ))}
        </div>
      )}
      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        {nav}
        <div style={{ flex: 1, padding: 6, display: "flex", flexDirection: "column", gap: 5, minWidth: 0 }}>
          <div style={{ display: "flex", gap: 4 }}>
            <div style={{ height: 6, width: "40%", borderRadius: r / 2, background: c.surface, border: `1px solid ${c.border}` }} />
            <div style={{ flex: 1 }} />
            <div style={{ height: 6, width: 14, borderRadius: template.components.button === "pill" ? 3 : 1, background: c.primary }} />
          </div>
          <div style={{ display: "flex", gap: 4 }}>
            {[c.chart[0], c.chart[1], c.chart[2]].map((color, i) => (
              <div key={i} style={{ ...box, flex: 1, padding: 4, display: "flex", flexDirection: "column", gap: 3 }}>
                <div style={line("60%")} />
                <div style={{ height: 6, width: "45%", borderRadius: 2, background: color }} />
              </div>
            ))}
          </div>
          <div style={{ ...box, flex: 1, padding: 5, display: "flex", flexDirection: "column", gap: 4 }}>
            {[0, 1, 2].map((i) => (
              <div key={i} style={{ display: "flex", gap: 4, alignItems: "center", background: template.components.table === "zebra" && i % 2 ? `${c.primary}14` : "transparent" }}>
                <div style={{ width: 6, height: 6, borderRadius: 1, background: c.chart[i] }} />
                <div style={line(`${60 - i * 12}%`)} />
                <div style={{ flex: 1 }} />
                <div style={{ width: 12, height: 5, borderRadius: template.components.badge === "dot" ? 3 : 2, background: i === 1 ? c.warning : c.success, opacity: 0.8 }} />
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
