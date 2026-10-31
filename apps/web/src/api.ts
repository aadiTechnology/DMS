// Thin client for the DMS API. The tenant always comes from the signed-in session, never from the page.
export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(errorText({ status, detail }));
  }
}

export function errorText(e: unknown): string {
  const err = e as { status?: number; detail?: unknown; message?: string } | undefined;
  const d = err?.detail;
  if (typeof d === "string") return d;
  if (d && typeof d === "object") {
    const o = d as { message?: string; code?: string; fields?: Record<string, string> };
    if (o.fields) return Object.entries(o.fields).map(([k, v]) => `${k}: ${v}`).join("; ");
    if (o.message) return o.message;
    if (o.code) return o.code;
  }
  if (Array.isArray(d)) return d.map((x) => (x as { msg?: string }).msg ?? "invalid input").join("; ");
  return err?.message ?? "Something went wrong";
}

export interface Session {
  access: string;
  refresh: string;
  email: string;
}

const KEY = "dms.session";
export const signedOut = new EventTarget();

export function getSession(): Session | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}
export function setSession(s: Session | null) {
  try {
    if (s) sessionStorage.setItem(KEY, JSON.stringify(s));
    else sessionStorage.removeItem(KEY);
  } catch {
    /* storage unavailable: the session then lasts until reload */
  }
}

interface Tokens {
  access_token: string;
  refresh_token: string;
}

async function send(path: string, init: RequestInit, token?: string): Promise<Response> {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(`/api/v1${path}`, { ...init, headers });
}

let refreshing: Promise<boolean> | null = null;
async function refresh(): Promise<boolean> {
  const s = getSession();
  if (!s) return false;
  refreshing ??= (async () => {
    const r = await send("/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: s.refresh }),
    });
    if (!r.ok) return false;
    const t = (await r.json()) as Tokens;
    setSession({ ...s, access: t.access_token, refresh: t.refresh_token });
    return true;
  })().finally(() => {
    refreshing = null;
  });
  return refreshing;
}

export interface Options {
  method?: string;
  body?: unknown;
  raw?: BodyInit;
  params?: Record<string, string | number | boolean | undefined | null>;
}

export async function api<T = unknown>(path: string, opts: Options = {}): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(opts.params ?? {})) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const url = qs.size ? `${path}?${qs}` : path;
  const init: RequestInit = { method: opts.method ?? (opts.body || opts.raw ? "POST" : "GET") };
  if (opts.raw !== undefined) init.body = opts.raw;
  else if (opts.body !== undefined) {
    init.body = JSON.stringify(opts.body);
    init.headers = { "Content-Type": "application/json" };
  }
  let res = await send(url, init, getSession()?.access);
  if (res.status === 401 && getSession() && (await refresh())) {
    res = await send(url, init, getSession()?.access);
  }
  if (res.status === 401 && getSession()) {
    setSession(null);
    signedOut.dispatchEvent(new Event("out"));
  }
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      detail = ((await res.json()) as { detail?: unknown }).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export async function signIn(email: string, password: string, mfaCode?: string) {
  const res = await send("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, mfa_code: mfaCode || undefined }),
  });
  const body = (await res.json().catch(() => ({}))) as Partial<Tokens> & { detail?: unknown };
  if (!res.ok) throw new ApiError(res.status, body.detail);
  setSession({ access: body.access_token!, refresh: body.refresh_token!, email });
}

export async function signOut() {
  try {
    await api("/auth/logout", { method: "POST", body: {} });
  } catch {
    /* already invalid */
  }
  setSession(null);
}
