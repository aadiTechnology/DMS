import { Alert, Box, Button, Link, MenuItem, Paper, Stack, TextField, Typography } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
import { ApiError, api, errorText, signIn } from "../api";
import { beginSso, type SsoProvider } from "../sso";

const NOTICES: Record<string, string> = {
  invited: "Your account is ready. Sign in with the password you just chose.",
  reset: "Your password was changed. Sign in with the new one.",
};
const PROVIDER_NAME: Record<string, string> = { google: "Google", microsoft: "Microsoft" };
interface TenantChoice { id: string; name: string }

export default function Login({ onSignedIn }: { onSignedIn: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [needCode, setNeedCode] = useState(false);
  const [error, setError] = useState("");
  const [params] = useSearchParams();
  const [notice, setNotice] = useState(NOTICES[params.get("notice") ?? ""] ?? "");
  const [tenants, setTenants] = useState<TenantChoice[]>([]);
  const [tenant, setTenant] = useState("");
  const providers = useQuery({ queryKey: ["sso-providers"], queryFn: () => api<{ provider: string; client_id: string }[]>("/auth/sso/providers") });
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setNotice("");
    setBusy(true);
    try {
      await signIn(email.trim(), password, code.trim(), tenant);
      onSignedIn();
    } catch (err) {
      const d = err instanceof ApiError ? (err.detail as { code?: string; tenants?: TenantChoice[] } | string) : undefined;
      if (typeof d === "object" && d?.code === "mfa_required") {
        setNeedCode(true);
        setError("Enter the 6-digit code from your authenticator app.");
      } else if (typeof d === "object" && d?.code === "tenant_required") {
        setTenants(d.tenants ?? []);
        setError("Your account belongs to more than one organization. Choose one.");
      } else {
        setError(errorText(err));
      }
    } finally {
      setBusy(false);
    }
  }

  async function forgot() {
    setError("");
    if (!email.trim()) return setError("Enter your email first.");
    try {
      const r = await api<{ detail?: string; message?: string }>("/auth/forgot-password", { body: { email: email.trim() } });
      setNotice(r?.message ?? r?.detail ?? "If the account exists, a reset link has been sent.");
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <Box sx={{ minHeight: "100vh", display: "grid", placeItems: "center", bgcolor: "background.default", p: 2 }}>
      <Paper sx={{ p: 4, width: 400, maxWidth: "100%" }}>
        <Typography variant="h5" color="primary" gutterBottom>
          DMS
        </Typography>
        <Typography color="text.secondary" sx={{ mb: 3 }}>
          Sign in to your document workspace.
        </Typography>
        <form onSubmit={submit}>
          <Stack spacing={2}>
            {error && <Alert severity="error">{error}</Alert>}
            {notice && <Alert severity="info">{notice}</Alert>}
            <TextField label="Email" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
            <TextField label="Password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            {tenants.length > 0 && (
              <TextField select label="Organization" value={tenant} onChange={(e) => setTenant(e.target.value)} required>
                {tenants.map((t) => <MenuItem key={t.id} value={t.id}>{t.name}</MenuItem>)}
              </TextField>
            )}
            {needCode && <TextField label="Verification code" value={code} onChange={(e) => setCode(e.target.value)} autoComplete="one-time-code" required />}
            <Button type="submit" variant="contained" size="large" disabled={busy}>
              {busy ? "Signing in…" : "Sign in"}
            </Button>
            <Link component="button" type="button" variant="body2" onClick={forgot} sx={{ alignSelf: "center" }}>
              Forgot password
            </Link>
            {providers.data?.map((p) => (
              <Button key={p.provider} variant="outlined" onClick={() => beginSso(p.provider as SsoProvider, p.client_id)}>
                Continue with {PROVIDER_NAME[p.provider] ?? p.provider}
              </Button>
            ))}
            <Link component={RouterLink} to="/register" variant="body2" sx={{ alignSelf: "center" }}>
              New here? Ask to join an organization
            </Link>
          </Stack>
        </form>
      </Paper>
    </Box>
  );
}
