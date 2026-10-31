import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { renderToString } from "react-dom/server";
import { forwardRef } from "react";
import { describe, expect, it } from "vitest";
import {
  LayoutRenderer, SYSTEM_TEMPLATE, TemplateProvider, buildMuiTheme, cssVariables, readCachedTemplate, resolveAppearance,
  resolveDashboard, uiTemplateSchema, validateTemplate, writeCachedTemplate, type UiTemplate,
} from "./index";

const here = dirname(fileURLToPath(import.meta.url));
const dir = join(here, "../../../design-showcase/templates");
const shipped: UiTemplate[] = readdirSync(dir).filter((f) => f.endsWith(".json")).map((f) => JSON.parse(readFileSync(join(dir, f), "utf8")));
const base = shipped.find((t) => t.key === "modern-enterprise")!;
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));

const Link = forwardRef<HTMLAnchorElement, { to: string; children?: unknown; className?: string }>(function Link({ to, children, ...rest }, ref) {
  return (
    <a ref={ref} href={to} {...rest}>
      {children as never}
    </a>
  );
});

const nav = [
  { to: "/documents", label: "Documents", icon: <span>d</span> },
  { to: "/upload", label: "Upload", icon: <span>u</span> },
];

function layout(t: UiTemplate) {
  return renderToString(
    <TemplateProvider template={t}>
      <LayoutRenderer brand="DMS" title="Documents" navItems={nav} linkComponent={Link} userLabel="asha@demo.test" onSignOut={() => {}} onSearch={() => {}} secondaryPanel={<span>tree-panel</span>}>
        <p>page-content</p>
      </LayoutRenderer>
    </TemplateProvider>,
  );
}

describe("the built-in system template", () => {
  it("passes the same schema as every stored template", () => {
    expect(validateTemplate(SYSTEM_TEMPLATE).errors).toEqual([]);
  });
});

describe("component variant resolver", () => {
  it("builds a theme for every shipped template", () => {
    for (const t of shipped) {
      const theme = buildMuiTheme(t);
      expect(theme.palette.mode).toBe(t.theme.mode);
      expect(theme.palette.primary.main).toBe(t.theme.colors.primary);
      expect(theme.shape.borderRadius).toBe(t.theme.radius);
    }
  });

  it("accepts every value the schema allows for every component and layout choice", () => {
    const props = (uiTemplateSchema as any).properties;
    const combos: [string[], unknown[]][] = [
      ...Object.entries(props.components.properties).map(([k, v]: [string, any]) => [["components", k], v.enum] as [string[], unknown[]]),
      [["density"], props.density.enum],
      [["theme", "mode"], props.theme.properties.mode.enum],
      [["theme", "shadow"], props.theme.properties.shadow.enum],
      [["theme", "typography", "fontFamily"], props.theme.properties.typography.properties.fontFamily.enum],
    ];
    let built = 0;
    for (const [path, values] of combos) {
      for (const value of values) {
        const t = clone(base) as any;
        let node = t;
        for (const p of path.slice(0, -1)) node = node[p];
        node[path[path.length - 1]!] = value;
        expect(() => buildMuiTheme(t)).not.toThrow();
        built += 1;
      }
    }
    expect(built).toBeGreaterThan(30);
  });

  it("changes component styles when the variant changes", () => {
    const a = clone(base);
    const b = clone(base);
    a.components.button = "soft";
    b.components.button = "pill";
    const ta = buildMuiTheme(a).components!.MuiButton!.styleOverrides as any;
    const tb = buildMuiTheme(b).components!.MuiButton!.styleOverrides as any;
    expect(ta.containedPrimary.color).toBe(a.theme.colors.primary);
    expect(tb.root.borderRadius).toBe(999);
    expect(ta.root.borderRadius).toBe(a.theme.radius);
  });

  it("density changes control height", () => {
    const compact = clone(base);
    const spacious = clone(base);
    compact.density = "compact";
    spacious.density = "spacious";
    expect((buildMuiTheme(compact).components!.MuiButton!.styleOverrides as any).root.minHeight).toBe(28);
    expect((buildMuiTheme(spacious).components!.MuiButton!.styleOverrides as any).root.minHeight).toBe(44);
  });
});

describe("css variables", () => {
  it("come only from validated template values", () => {
    const vars = cssVariables(base);
    expect(vars["--dms-primary"]).toBe(base.theme.colors.primary);
    expect(vars["--dms-chart-5"]).toBe(base.theme.colors.chart[4]);
    expect(Object.values(vars).every((v) => !/[<>;{}]/.test(v.replace(/rgba?\([^)]*\)/g, "")) || v.includes(","))).toBe(true);
  });
});

describe("template resolver", () => {
  const answer = (config: unknown, source: any = "user") => ({ source, template: { config } });

  it("uses a valid template from the server", () => {
    const r = resolveAppearance(answer(shipped[1]), null);
    expect(r.source).toBe("user");
    expect(r.template.key).toBe(shipped[1]!.key);
  });

  it("never applies an invalid template, falling back to the cache and then the built-in design", () => {
    const bad = clone(base) as any;
    bad.name = "<script>alert(1)</script>";
    expect(resolveAppearance(answer(bad), shipped[2]!)).toMatchObject({ source: "cache" });
    expect(resolveAppearance(answer(bad), null)).toMatchObject({ source: "fallback", template: SYSTEM_TEMPLATE });
  });

  it("uses the built-in design when the server says there is none, and survives garbage", () => {
    expect(resolveAppearance({ source: "system", template: null })).toMatchObject({ source: "system", template: SYSTEM_TEMPLATE });
    expect(resolveAppearance(undefined).template).toBe(SYSTEM_TEMPLATE);
    expect(resolveAppearance(null, shipped[3]!).source).toBe("cache");
    expect(resolveAppearance(answer("not an object")).template).toBe(SYSTEM_TEMPLATE);
  });

  it("caches the last template per person and ignores damaged cache entries", () => {
    const data = new Map<string, string>();
    const storage = { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v) };
    writeCachedTemplate(storage, "a@x.test", shipped[1]!);
    expect(readCachedTemplate(storage, "a@x.test")?.key).toBe(shipped[1]!.key);
    expect(readCachedTemplate(storage, "b@x.test")).toBeNull();
    data.set("dms.ui.template.a@x.test", '{"key":"x"}');
    expect(readCachedTemplate(storage, "a@x.test")).toBeNull();
    expect(readCachedTemplate(undefined, "a@x.test")).toBeNull();
    expect(() => writeCachedTemplate({ getItem: () => null, setItem: () => { throw new Error("full"); } }, "a", base)).not.toThrow();
  });
});

describe("dashboard widget resolver", () => {
  it("returns visible widgets in order with spans inside the grid", () => {
    const t = clone(base);
    const d = resolveDashboard(t);
    expect(d.widgets.map((w) => w.id)).toEqual(["stat-documents", "stat-pending", "stat-shared", "stat-storage", "chart-uploads", "chart-classification", "recent-documents", "approvals-queue"]);
    expect(d.columns).toBe(12);
    expect(d.widgets.every((w) => w.span >= 1 && w.span <= d.columns)).toBe(true);
  });

  it("follows order, visibility and clamps spans", () => {
    const t = clone(base);
    t.pages.dashboard.widgets.forEach((w) => (w.visible = false));
    const set = (id: string, order: number, w: number) => Object.assign(t.pages.dashboard.widgets.find((x) => x.id === id)!, { visible: true, order, w });
    set("activity", 1, 12);
    set("welcome", 2, 4);
    t.pages.dashboard.grid.columns = 6;
    expect(resolveDashboard(t).widgets).toEqual([{ id: "activity", span: 6, rows: 2 }, { id: "welcome", span: 4, rows: 1 }]);
  });
});

describe("layout renderer", () => {
  const sidebars = ["full", "floating", "rail-tree", "top"] as const;
  const headers = ["search", "minimal", "pill", "toolbar"] as const;

  for (const sidebar of sidebars) {
    for (const header of headers) {
      it(`renders ${sidebar} navigation with a ${header} header`, () => {
        const t = clone(SYSTEM_TEMPLATE);
        t.layout.sidebarVariant = sidebar;
        t.layout.headerVariant = header;
        t.layout.navigationPosition = sidebar === "top" ? "top" : "left";
        t.layout.sidebarWidth = sidebar === "top" ? 0 : t.layout.sidebarWidth;
        const html = layout(t);
        expect(html).toContain(`data-layout="${sidebar}"`);
        expect(html).toContain("page-content");
        expect(html).toContain("/documents");
        expect(html).toContain("asha@demo.test");
        expect(html).toContain("Sign out");
        expect(html.includes("tree-panel")).toBe(sidebar === "rail-tree");
      });
    }
  }

  it("applies the template colors, mode and key to the page", () => {
    const html = layout(shipped.find((t) => t.key === "premium-dark")!);
    expect(html).toContain('data-dms-template="premium-dark"');
    expect(html).toContain('data-dms-mode="dark"');
    expect(html).toContain("--dms-primary:#8aa4ff");
  });

  it("escapes anything it displays", () => {
    const html = renderToString(
      <TemplateProvider template={SYSTEM_TEMPLATE}>
        <LayoutRenderer brand="DMS" title="x" navItems={nav} linkComponent={Link} userLabel={"<img src=x onerror=alert(1)>"} onSignOut={() => {}}>
          <p />
        </LayoutRenderer>
      </TemplateProvider>,
    );
    expect(html).not.toContain("<img src=x");
    expect(html).toContain("&lt;img");
  });
});
