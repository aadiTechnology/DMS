import { Alert, Button, Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle, TextField } from "@mui/material";
import { useState } from "react";
import { errorText } from "../api";

/** Asks for a written reason (or just a confirmation when `required` is false) before a significant action. */
export default function ReasonDialog({
  open, title, description, label = "Reason", confirmLabel, danger = false, required = true, onSubmit, onClose,
}: {
  open: boolean;
  title: string;
  description?: string;
  label?: string;
  confirmLabel: string;
  danger?: boolean;
  required?: boolean;
  onSubmit: (reason: string) => Promise<unknown>;
  onClose: () => void;
}) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError("");
    try {
      await onSubmit(reason.trim());
      setReason("");
      onClose();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        {description && <DialogContentText sx={{ mb: 2 }}>{description}</DialogContentText>}
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        <TextField label={required ? label : `${label} (optional)`} multiline minRows={2} fullWidth value={reason} onChange={(e) => setReason(e.target.value)} inputProps={{ maxLength: 500 }} autoFocus />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" color={danger ? "error" : "primary"} disabled={busy || (required && !reason.trim())} onClick={submit}>{confirmLabel}</Button>
      </DialogActions>
    </Dialog>
  );
}
