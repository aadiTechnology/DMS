import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { validateTemplate } from "./validator";

const here = dirname(fileURLToPath(import.meta.url));
const templatesDir = join(here, "../../../design-showcase/templates");
const cases = JSON.parse(readFileSync(join(here, "../fixtures/invalid-cases.json"), "utf8")).cases as Case[];

interface Case {
  name: string;
  path: string;
  value?: unknown;
  remove?: boolean;
  repeat?: { char: string; times: number };
}

const load = (file: string) => JSON.parse(readFileSync(join(templatesDir, file), "utf8"));
const base = () => load("modern-enterprise.json");

function apply(template: any, c: Case) {
  const parts = c.path.split(".");
  const last = parts.pop()!;
  let targets: any[] = [template];
  for (const p of parts) {
    targets = targets.flatMap((t) => (p === "*" ? t : [t[p]]));
  }
  for (const t of targets) {
    const keys = last === "*" ? Object.keys(t) : [last];
    for (const k of keys) {
      if (c.remove) delete t[k];
      else t[k] = c.repeat ? c.repeat.char.repeat(c.repeat.times) : c.value;
    }
  }
  return template;
}

describe("the five shipped templates", () => {
  for (const file of readdirSync(templatesDir).filter((f) => f.endsWith(".json"))) {
    it(`${file} is valid`, () => {
      const result = validateTemplate(load(file));
      expect(result.errors).toEqual([]);
      expect(result.valid).toBe(true);
    });
  }
});

describe("unsafe or malformed templates are rejected", () => {
  for (const c of cases) {
    it(c.name, () => {
      const result = validateTemplate(apply(base(), c));
      expect(result.valid).toBe(false);
      expect(result.errors.length).toBeGreaterThan(0);
    });
  }
});

describe("input handling", () => {
  it("accepts JSON text", () => {
    expect(validateTemplate(JSON.stringify(base())).valid).toBe(true);
  });
  it("rejects text that is not JSON without throwing", () => {
    expect(validateTemplate("{ nope").valid).toBe(false);
  });
  it.each([null, 5, "x", [], true])("rejects %j", (v) => {
    expect(validateTemplate(v).valid).toBe(false);
  });
  it("does not change the template it is given", () => {
    const t = base();
    const before = JSON.stringify(t);
    validateTemplate(t);
    expect(JSON.stringify(t)).toBe(before);
  });
  it("accepts a https preview image and an application preview path", () => {
    expect(validateTemplate({ ...base(), previewImage: "https://cdn.example.com/previews/a.png" }).valid).toBe(true);
    expect(validateTemplate({ ...base(), previewImage: "/ui-previews/modern-enterprise.webp" }).valid).toBe(true);
  });
  it("tolerates prototype-pollution style keys by rejecting them", () => {
    const t = JSON.parse('{"__proto__": {"polluted": true}, "schemaVersion": "1.0"}');
    expect(validateTemplate(t).valid).toBe(false);
    expect(({} as any).polluted).toBeUndefined();
  });
});
