import { Alert, Box, Button, Paper, Stack, TextField, Typography } from "@mui/material";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import QRCode from "qrcode";
import { useEffect, useState } from "react";
import { api, errorText } from "../api";
import { PasswordPair } from "../pages/PublicPages";

export function ChangePasswordCard() {
  const [current, setCurrent] = useState("");
  const [pw, setPw] = useState<[string, string]>(["", ""]);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const save = useMutation({
    mutationFn: () => api("/auth/change-password", { body: { current_password: current, new_password: pw[0] } }),
    onSuccess: () => { setDone(true); setError(""); setCurrent(""); setPw(["", ""]); },
    onError: (e) => { setDone(false); setError(errorText(e)); },
  });
  const mismatch = pw[0] !== pw[1];
  return (
    <Paper sx={{ p: 3, mb: 2 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 600 }} gutterBottom>Change password</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>Your other sign-ins (other browsers and devices) are signed out. This one stays.</Typography>
      <Stack spacing={2} sx={{ maxWidth: 420 }}>
        {error && <Alert severity="error">{error}</Alert>}
        {done && <Alert severity="success">Password changed. Other devices were signed out.</Alert>}
        <TextField label="Current password" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        <PasswordPair value={pw} onChange={setPw} label="New password" />
        <Box><Button variant="contained" disabled={!current || !pw[0] || mismatch || save.isPending} onClick={() => save.mutate()}>Change password</Button></Box>
      </Stack>
    </Paper>
  );
}

function Qr({ text }: { text: string }) {
  const [src, setSrc] = useState("");
  useEffect(() => { void QRCode.toDataURL(text, { margin: 1, width: 200 }).then(setSrc).catch(() => setSrc("")); }, [text]);
  return src ? <img src={src} width={200} height={200} alt="QR code to scan with your authenticator app" /> : null;
}

/** Turn two-step verification on (scan, confirm with a code, keep the recovery codes) or off. */
export function TwoStepCard() {
  const client = useQueryClient();
  const status = useQuery({ queryKey: ["mfa"], queryFn: () => api<{ enabled: boolean }>("/auth/mfa") });
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [recovery, setRecovery] = useState<string[] | null>(null);
  const [disabling, setDisabling] = useState(false);
  const [error, setError] = useState("");
  const refresh = () => client.invalidateQueries({ queryKey: ["mfa"] });
  const begin = useMutation({ mutationFn: () => api<{ secret: string; otpauth_uri: string }>("/auth/mfa/setup", { method: "POST", body: {} }), onSuccess: (r) => { setSetup(r); setError(""); }, onError: (e) => setError(errorText(e)) });
  const enable = useMutation({
    mutationFn: () => api<{ recovery_codes: string[] }>("/auth/mfa/enable", { body: { code: code.trim() } }),
    onSuccess: async (r) => { setRecovery(r.recovery_codes); setSetup(null); setCode(""); setError(""); await refresh(); },
    onError: (e) => setError(errorText(e)),
  });
  const disable = useMutation({
    mutationFn: () => api("/auth/mfa/disable", { body: { code: code.trim(), password } }),
    onSuccess: async () => { setDisabling(false); setCode(""); setPassword(""); setError(""); await refresh(); },
    onError: (e) => setError(errorText(e)),
  });
  const on = status.data?.enabled;
  return (
    <Paper sx={{ p: 3, mb: 2 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 600 }} gutterBottom>Two-step verification: {status.data ? (on ? "on" : "off") : "…"}</Typography>
      <Stack spacing={2} sx={{ maxWidth: 460 }}>
        {error && <Alert severity="error">{error}</Alert>}
        {recovery && (
          <Alert severity="warning">
            <Typography variant="body2" sx={{ mb: 1 }}>Two-step verification is on. Keep these recovery codes somewhere safe. Each works once if you lose your phone, and they are not shown again.</Typography>
            <Box component="pre" sx={{ m: 0, fontFamily: "monospace" }}>{recovery.join("\n")}</Box>
            <Button size="small" sx={{ mt: 1 }} onClick={() => setRecovery(null)}>I have saved them</Button>
          </Alert>
        )}
        {status.data && !on && !setup && (
          <>
            <Typography variant="body2" color="text.secondary">Adds a 6-digit code from an authenticator app (Google Authenticator, Microsoft Authenticator, Authy) to your password.</Typography>
            <Box><Button variant="contained" disabled={begin.isPending} onClick={() => begin.mutate()}>Set up two-step verification</Button></Box>
          </>
        )}
        {setup && (
          <>
            <Typography variant="body2">1. Scan this picture with your authenticator app, or type the key by hand.</Typography>
            <Qr text={setup.otpauth_uri} />
            <Typography variant="body2" sx={{ fontFamily: "monospace", wordBreak: "break-all" }}>{setup.secret}</Typography>
            <Typography variant="body2">2. Enter the 6-digit code the app shows.</Typography>
            <TextField label="Code" value={code} onChange={(e) => setCode(e.target.value)} autoComplete="one-time-code" />
            <Stack direction="row" spacing={1}>
              <Button variant="contained" disabled={code.trim().length < 6 || enable.isPending} onClick={() => enable.mutate()}>Turn on</Button>
              <Button onClick={() => { setSetup(null); setCode(""); }}>Cancel</Button>
            </Stack>
          </>
        )}
        {on && !disabling && <Box><Button color="error" onClick={() => { setDisabling(true); setRecovery(null); }}>Turn off</Button></Box>}
        {on && disabling && (
          <>
            <Typography variant="body2" color="text.secondary">Enter your password and a current code (or a recovery code) to turn it off.</Typography>
            <TextField label="Password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            <TextField label="Code" value={code} onChange={(e) => setCode(e.target.value)} autoComplete="one-time-code" />
            <Stack direction="row" spacing={1}>
              <Button color="error" variant="contained" disabled={!password || code.trim().length < 6 || disable.isPending} onClick={() => disable.mutate()}>Turn off</Button>
              <Button onClick={() => { setDisabling(false); setCode(""); setPassword(""); }}>Cancel</Button>
            </Stack>
          </>
        )}
      </Stack>
    </Paper>
  );
}
