// Google and Microsoft sign-in by redirect. The browser comes back to /sso-callback with an ID token in the
// address fragment; the API checks it. Nothing here is trusted: the API verifies signature, audience and nonce.
export type SsoProvider = "google" | "microsoft";
const KEY = "dms.sso";

const ENDPOINT: Record<SsoProvider, string> = {
  google: "https://accounts.google.com/o/oauth2/v2/auth",
  microsoft: "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
};

function random(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function authorizeUrl(provider: SsoProvider, clientId: string, origin: string, state: string, nonce: string): string {
  const q = new URLSearchParams({
    client_id: clientId,
    redirect_uri: `${origin}/sso-callback`,
    response_type: "id_token",
    scope: "openid email profile",
    nonce,
    state,
  });
  if (provider === "microsoft") q.set("response_mode", "fragment");
  return `${ENDPOINT[provider]}?${q}`;
}

export function beginSso(provider: SsoProvider, clientId: string): void {
  const state = random();
  const nonce = random();
  sessionStorage.setItem(KEY, JSON.stringify({ provider, state, nonce }));
  window.location.assign(authorizeUrl(provider, clientId, window.location.origin, state, nonce));
}

export interface SsoReturn {
  provider: SsoProvider;
  idToken: string;
  nonce: string;
}

/** Reads the provider's answer; null when it does not match what this browser started. */
export function readSsoReturn(hash: string, stored: string | null): SsoReturn | null {
  if (!stored) return null;
  try {
    const mine = JSON.parse(stored) as { provider: SsoProvider; state: string; nonce: string };
    const q = new URLSearchParams(hash.replace(/^#/, ""));
    const idToken = q.get("id_token");
    if (!idToken || q.get("state") !== mine.state) return null;
    return { provider: mine.provider, idToken, nonce: mine.nonce };
  } catch {
    return null;
  }
}

export const storedSso = () => sessionStorage.getItem(KEY);
export const clearSso = () => sessionStorage.removeItem(KEY);

/** The email claim, for display only. Not used for any decision. */
export function emailFromIdToken(token: string): string {
  try {
    const part = token.split(".")[1] ?? "";
    const json = atob(part.replace(/-/g, "+").replace(/_/g, "/"));
    const c = JSON.parse(json) as { email?: string; preferred_username?: string };
    return c.email ?? c.preferred_username ?? "";
  } catch {
    return "";
  }
}
