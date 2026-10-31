import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, LinearProgress, Stack, TextField, Typography } from "@mui/material";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, errorText, getSession } from "../api";

/**
 * Add a new version of a document. `basedOn` is the newest version number the person has seen:
 * if someone added one meanwhile the server refuses and nothing is overwritten.
 */
export default function NewVersionDialog({ documentId, basedOn, open, onClose }: { documentId: string; basedOn: number; open: boolean; onClose: () => void }) {
  const client = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [comment, setComment] = useState("");
  const [result, setResult] = useState("");
  const [error, setError] = useState("");

  const upload = useMutation({
    mutationFn: async () => {
      const f = file!;
      const reserved = await api<{ version_id: string }>(`/documents/${documentId}/versions/uploads`, {
        body: { filename: f.name, content_type: f.type || "application/octet-stream", size_bytes: f.size, based_on_version: basedOn, comment: comment.trim() || undefined },
      });
      const sent = await fetch(`/api/v1/documents/uploads/${reserved.version_id}/content`, {
        method: "PUT",
        headers: { Authorization: `Bearer ${getSession()?.access}` },
        body: f,
      });
      if (!sent.ok) {
        const body = (await sent.json().catch(() => ({}))) as { detail?: unknown };
        throw new Error(errorText({ detail: body.detail ?? sent.statusText }));
      }
      return (await sent.json()) as { lifecycle_state: string };
    },
    onSuccess: async () => {
      setError("");
      setResult("The new version was uploaded and scanned. If this category needs approval, readers keep seeing the approved version until it is approved.");
      setFile(null);
      setComment("");
      await client.invalidateQueries({ queryKey: ["doc", documentId] });
      await client.invalidateQueries({ queryKey: ["search"] });
    },
    onError: (e) => {
      setResult("");
      setError(errorText(e));
    },
  });
  const close = () => {
    setResult("");
    setError("");
    setFile(null);
    onClose();
  };

  return (
    <Dialog open={open} onClose={close} fullWidth maxWidth="sm">
      <DialogTitle>Add a new version</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <Typography variant="body2" color="text.secondary">Earlier versions stay available. You are adding after version {basedOn}.</Typography>
          {error && <Alert severity="error">{error}</Alert>}
          {result && <Alert severity="success">{result}</Alert>}
          <Button variant="outlined" component="label">
            {file ? `${file.name} (${(file.size / 1024).toFixed(0)} KB)` : "Choose a file"}
            <input hidden type="file" aria-label="New version file" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setResult(""); }} />
          </Button>
          <TextField label="What changed (optional)" value={comment} onChange={(e) => setComment(e.target.value)} inputProps={{ maxLength: 500 }} />
          {upload.isPending && <LinearProgress />}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={close}>{result ? "Done" : "Cancel"}</Button>
        <Button variant="contained" disabled={!file || upload.isPending} onClick={() => upload.mutate()}>Upload version</Button>
      </DialogActions>
    </Dialog>
  );
}
