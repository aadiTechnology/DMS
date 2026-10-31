import { Alert, Box, Button, Link, Paper, Stack, TextField, Typography } from "@mui/material";
import { useState } from "react";
import { ApiError, api, errorText, signIn } from "../api";

export default function Login({ onSignedIn }: { onSignedIn: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [needCode, setNeedCode] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setNotice("");
    setBusy(true);
    try {
      await signIn(email.trim(), password, code.trim());
      onSignedIn();
    } catch (err) {
      const d = err instanceof ApiError ? (err.detail as { code?: string } | string) : undefined;
      if (typeof d === "object" && d?.code === "mfa_required") {
        setNeedCode(true);
        setError("Enter the 6-digit code from your authenticator app.");
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
            {needCode && <TextField label="Verification code" value={code} onChange={(e) => setCode(e.target.value)} autoComplete="one-time-code" required />}
            <Button type="submit" variant="contained" size="large" disabled={busy}>
              {busy ? "Signing in…" : "Sign in"}
            </Button>
            <Link component="button" type="button" variant="body2" onClick={forgot} sx={{ alignSelf: "center" }}>
              Forgot password
            </Link>
          </Stack>
        </form>
      </Paper>
    </Box>
  );
}
