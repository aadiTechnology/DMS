import { Alert, Box, Button, Link, MenuItem, Paper, Stack, TextField, Typography } from "@mui/material";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link as RouterLink, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, errorText, publicPost, startSession } from "../api";
import { clearSso, emailFromIdToken, readSsoReturn, storedSso } from "../sso";

export const PASSWORD_HINT = "At least 10 characters, not containing your email name.";

export function Shell({ title, intro, children }: { title: string; intro?: string; children: ReactNode }) {
  return (
    <Box sx={{ minHeight: "100vh", display: "grid", placeItems: "center", bgcolor: "background.default", p: 2 }}>
      <Paper sx={{ p: 4, width: 420, maxWidth: "100%" }}>
        <Typography variant="h5" color="primary" gutterBottom>DMS</Typography>
        <Typography variant="h6" sx={{ mb: 0.5 }}>{title}</Typography>
        {intro && <Typography color="text.secondary" sx={{ mb: 2 }}>{intro}</Typography>}
        {children}
      </Paper>
    </Box>
  );
}

function BackToSignIn() {
  return <Link component={RouterLink} to="/" variant="body2" sx={{ alignSelf: "center" }}>Back to sign in</Link>;
}

/** Two password boxes that must match. */
export function PasswordPair({ value, onChange, label = "Password" }: { value: [string, string]; onChange: (v: [string, string]) => void; label?: string }) {
  const mismatch = value[1] !== "" && value[0] !== value[1];
  return (
    <>
      <TextField label={label} type="password" autoComplete="new-password" value={value[0]} onChange={(e) => onChange([e.target.value, value[1]])} helperText={PASSWORD_HINT} />
      <TextField label="Repeat password" type="password" autoComplete="new-password" value={value[1]} onChange={(e) => onChange([value[0], e.target.value])} error={mismatch} helperText={mismatch ? "The two passwords differ" : " "} />
    </>
  );
}

export function AcceptInvite() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const navigate = useNavigate();
  const [pw, setPw] = useState<[string, string]>(["", ""]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (!token) return <Shell title="Invitation"><Alert severity="error">This link is missing its code. Open the link from your invitation email again.</Alert></Shell>;
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (pw[0] !== pw[1]) return setError("The two passwords differ");
    setError(""); setBusy(true);
    try {
      await publicPost("/auth/accept-invite", { token, password: pw[0] || undefined });
      navigate("/?notice=invited", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError && err.status === 400 ? "This invitation link is invalid, already used or has expired. Ask your administrator to send a new one." : errorText(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Shell title="Accept your invitation" intro="Choose a password to finish setting up your account.">
      <form onSubmit={submit}>
        <Stack spacing={2}>
          {error && <Alert severity="error">{error}</Alert>}
          <PasswordPair value={pw} onChange={setPw} />
          <Typography variant="caption" color="text.secondary">Already have an account with us? Leave both boxes empty; your existing password stays.</Typography>
          <Button type="submit" variant="contained" size="large" disabled={busy}>{busy ? "Setting up…" : "Join"}</Button>
          <BackToSignIn />
        </Stack>
      </form>
    </Shell>
  );
}

export function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const navigate = useNavigate();
  const [pw, setPw] = useState<[string, string]>(["", ""]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (!token) return <Shell title="Reset password"><Alert severity="error">This link is missing its code. Use "Forgot password" on the sign-in page to get a new one.</Alert></Shell>;
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (pw[0] !== pw[1]) return setError("The two passwords differ");
    setError(""); setBusy(true);
    try {
      await publicPost("/auth/reset-password", { token, password: pw[0] });
      navigate("/?notice=reset", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError && err.status === 400 ? "This link is invalid or has expired. Ask for a new one from the sign-in page." : errorText(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Shell title="Choose a new password" intro="You will be signed out everywhere else.">
      <form onSubmit={submit}>
        <Stack spacing={2}>
          {error && <Alert severity="error">{error}</Alert>}
          <PasswordPair value={pw} onChange={setPw} label="New password" />
          <Button type="submit" variant="contained" size="large" disabled={busy || !pw[0]}>{busy ? "Saving…" : "Save password"}</Button>
          <BackToSignIn />
        </Stack>
      </form>
    </Shell>
  );
}

export function Register() {
  const [params] = useSearchParams();
  const [slug, setSlug] = useState(params.get("org") ?? "");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [done, setDone] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(""); setBusy(true);
    try {
      const r = await publicPost<{ detail: string }>("/auth/register", { tenant_slug: slug.trim().toLowerCase(), email: email.trim(), full_name: name.trim() });
      setDone(r.detail);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  if (done) {
    return (
      <Shell title="Request sent">
        <Stack spacing={2}>
          <Alert severity="success">{done}. If an administrator approves it you will get an email with a link to set your password.</Alert>
          <BackToSignIn />
        </Stack>
      </Shell>
    );
  }
  return (
    <Shell title="Ask to join an organization" intro="Your organization's administrators review every request.">
      <form onSubmit={submit}>
        <Stack spacing={2}>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField label="Organization code" value={slug} onChange={(e) => setSlug(e.target.value)} helperText="The short name from your invitation or your organization's web address." required autoFocus />
          <TextField label="Your name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" required />
          <TextField label="Work email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required />
          <Button type="submit" variant="contained" size="large" disabled={busy}>{busy ? "Sending…" : "Send request"}</Button>
          <BackToSignIn />
        </Stack>
      </form>
    </Shell>
  );
}

interface Tenant { id: string; name: string }

/** Where Google or Microsoft sends the browser back. The API verifies the token; nothing is trusted here. */
export function SsoCallback({ onSignedIn }: { onSignedIn: () => void }) {
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [tenant, setTenant] = useState("");
  const ret = useRef(readSsoReturn(window.location.hash, storedSso()));
  async function complete(tenantId?: string) {
    const r = ret.current;
    if (!r) return;
    setError("");
    try {
      const t = await publicPost<{ access_token: string; refresh_token: string }>(`/auth/sso/${r.provider}`, { id_token: r.idToken, nonce: r.nonce, tenant_id: tenantId });
      startSession(t, emailFromIdToken(r.idToken));
      clearSso();
      onSignedIn();
      navigate("/", { replace: true });
    } catch (err) {
      const d = err instanceof ApiError ? (err.detail as { code?: string; tenants?: Tenant[] } | string) : undefined;
      if (typeof d === "object" && d?.code === "tenant_required") setTenants(d.tenants ?? []);
      else {
        clearSso();
        setError(err instanceof ApiError && err.status === 401 ? "That account could not be signed in. It must already exist here; ask an administrator to invite you." : errorText(err));
      }
    }
  }
  useEffect(() => { void complete(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  if (!ret.current) return <Shell title="Sign-in could not finish"><Stack spacing={2}><Alert severity="error">The sign-in answer did not match a request from this browser. Please start again.</Alert><BackToSignIn /></Stack></Shell>;
  if (tenants.length) {
    return (
      <Shell title="Choose an organization" intro="This account belongs to more than one.">
        <Stack spacing={2}>
          <TextField select label="Organization" value={tenant} onChange={(e) => setTenant(e.target.value)}>
            {tenants.map((t) => <MenuItem key={t.id} value={t.id}>{t.name}</MenuItem>)}
          </TextField>
          <Button variant="contained" disabled={!tenant} onClick={() => void complete(tenant)}>Continue</Button>
        </Stack>
      </Shell>
    );
  }
  return (
    <Shell title="Signing you in…">
      <Stack spacing={2}>{error ? <><Alert severity="error">{error}</Alert><BackToSignIn /></> : <Typography color="text.secondary">One moment.</Typography>}</Stack>
    </Shell>
  );
}
