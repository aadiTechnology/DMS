import { SYSTEM_TEMPLATE } from "./systemTemplate";
import type { UiTemplate } from "./types";
import { validateTemplate } from "./validator";

export type TemplateSource = "user" | "tenant" | "product" | "system" | "cache" | "fallback";

export interface Appearance {
  template: UiTemplate;
  source: TemplateSource;
}

/** The part of the preferences API answer that the resolver needs. */
export interface EffectiveAnswer {
  source: "user" | "tenant" | "product" | "system";
  template: { config: unknown } | null;
}

/**
 * Turn the server's answer into something safe to render. The server already validated the
 * template, but the browser checks again: anything that fails is skipped in favour of the
 * built-in design, never applied. Never throws.
 */
export function resolveAppearance(answer: EffectiveAnswer | null | undefined, cached?: UiTemplate | null): Appearance {
  if (answer && answer.template) {
    const result = validateTemplate(answer.template.config);
    if (result.valid) return { template: result.template, source: answer.source };
    if (cached) return { template: cached, source: "cache" };
    return { template: SYSTEM_TEMPLATE, source: "fallback" };
  }
  if (answer && answer.source === "system") return { template: SYSTEM_TEMPLATE, source: "system" };
  return cached ? { template: cached, source: "cache" } : { template: SYSTEM_TEMPLATE, source: "fallback" };
}

const CACHE_PREFIX = "dms.ui.template.";

interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

/** The last design shown to this person, so the next page load does not flash the default. */
export function readCachedTemplate(storage: StorageLike | undefined, userKey: string): UiTemplate | null {
  try {
    const raw = storage?.getItem(CACHE_PREFIX + userKey);
    if (!raw) return null;
    const result = validateTemplate(raw);
    return result.valid ? result.template : null;
  } catch {
    return null;
  }
}

export function writeCachedTemplate(storage: StorageLike | undefined, userKey: string, template: UiTemplate): void {
  try {
    storage?.setItem(CACHE_PREFIX + userKey, JSON.stringify(template));
  } catch {
    /* storage unavailable: the design is simply fetched again next time */
  }
}
