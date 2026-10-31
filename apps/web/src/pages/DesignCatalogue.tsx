import {
  Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Paper, Stack, Table, TableBody, TableCell,
  TableHead, TableRow, Typography,
} from "@mui/material";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, errorText } from "../api";
import { dateTime, label } from "../format";

interface Row {
  id: string;
  key: string;
  name: string;
  description: string;
  version: string;
  status: string;
  updated_at: string;
}
interface Check {
  valid: boolean;
  errors: string[];
  key: string | null;
  name: string | null;
  description: string | null;
  version: string | null;
  outcome: string | null;
  current_version: string | null;
}
interface Version {
  version: string;
  created_at: string;
  published_at: string | null;
}

const OUTCOME: Record<string, string> = {
  new_template: "This is a new design.",
  new_version: "This is a newer version of an existing design; the earlier versions stay on record.",
  conflict: "This version already exists or is older than the stored one.",
};

/** Platform administrators only: check, save, publish and withdraw the designs everyone can choose from. */
export default function DesignCatalogue() {
  const client = useQueryClient();
  const [text, setText] = useState<string | null>(null);
  const [fileName, setFileName] = useState("");
  const [check, setCheck] = useState<Check | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [history, setHistory] = useState<Row | null>(null);

  const list = useQuery({ queryKey: ["platform-templates"], queryFn: () => api<Row[]>("/platform/ui-templates") });
  const versions = useQuery({
    queryKey: ["platform-templates", history?.id, "versions"],
    queryFn: () => api<Version[]>(`/platform/ui-templates/${history!.id}/versions`),
    enabled: !!history,
  });

  async function choose(file: File | undefined) {
    setCheck(null);
    setMessage("");
    setError("");
    if (!file) return;
    setFileName(file.name);
    const body = await file.text();
    setText(body);
    try {
      setCheck(await api<Check>("/platform/ui-templates/validate", { raw: body }));
    } catch (e) {
      setError(errorText(e));
    }
  }

  const refresh = async () => {
    await client.invalidateQueries({ queryKey: ["platform-templates"] });
    await client.invalidateQueries({ queryKey: ["ui-available"] });
  };
  const save = useMutation({
    mutationFn: (publish: boolean) => api("/platform/ui-templates/import", { raw: text!, params: { publish } }),
    onSuccess: async (_d, publish) => {
      setMessage(publish ? "Saved and published. People can choose it now, with no redeployment." : "Saved as a draft. It is not visible to anyone until you publish it.");
      setText(null);
      setCheck(null);
      setFileName("");
      await refresh();
    },
    onError: (e) => setError(errorText(e)),
  });
  const move = useMutation({
    mutationFn: ({ id, action }: { id: string; action: "publish" | "archive" }) => api(`/platform/ui-templates/${id}/${action}`, { method: "POST" }),
    onSuccess: refresh,
    onError: (e) => setError(errorText(e)),
  });

  if (list.error) return <Alert severity="warning">{errorText(list.error)}</Alert>;
  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 1 }}>Design catalogue</Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        Add a design by uploading its JSON file. It is checked first and saved as a draft; publishing makes it available to every organization straight away.
      </Typography>
      {message && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setMessage("")}>{message}</Alert>}
      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>{error}</Alert>}
      <Paper sx={{ p: 2, mb: 3 }}>
        <Stack spacing={2}>
          <Button variant="outlined" component="label" sx={{ alignSelf: "flex-start" }}>
            {fileName || "Choose a design file (.json)"}
            <input hidden type="file" accept=".json,application/json" aria-label="Design file" onChange={(e) => { void choose(e.target.files?.[0]); e.target.value = ""; }} />
          </Button>
          {check && !check.valid && (
            <Alert severity="error">
              <b>This file cannot be used.</b>
              <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                {check.errors.slice(0, 8).map((e) => <li key={e}>{e}</li>)}
              </ul>
            </Alert>
          )}
          {check?.valid && (
            <Alert severity="success">
              <b>{check.name}</b> <Chip size="small" label={`version ${check.version}`} sx={{ ml: 1 }} />
              <Typography variant="body2">{check.description}</Typography>
              <Typography variant="caption" color="text.secondary">Key: {check.key} · {OUTCOME[check.outcome ?? ""] ?? ""}</Typography>
            </Alert>
          )}
          <Stack direction="row" spacing={1}>
            <Button variant="contained" disabled={!check?.valid || save.isPending} onClick={() => save.mutate(false)}>Save as draft</Button>
            <Button variant="outlined" disabled={!check?.valid || save.isPending} onClick={() => save.mutate(true)}>Save and publish</Button>
          </Stack>
        </Stack>
      </Paper>
      <Paper>
        <Table size="small">
          <TableHead>
            <TableRow><TableCell>Design</TableCell><TableCell>Key</TableCell><TableCell>Version</TableCell><TableCell>Status</TableCell><TableCell>Updated</TableCell><TableCell align="right">Actions</TableCell></TableRow>
          </TableHead>
          <TableBody>
            {list.data?.map((t) => (
              <TableRow key={t.id}>
                <TableCell><b>{t.name}</b><Typography variant="caption" display="block" color="text.secondary">{t.description}</Typography></TableCell>
                <TableCell>{t.key}</TableCell>
                <TableCell>{t.version}</TableCell>
                <TableCell><Chip size="small" label={label(t.status)} color={t.status === "published" ? "success" : t.status === "draft" ? "warning" : "default"} /></TableCell>
                <TableCell>{dateTime(t.updated_at)}</TableCell>
                <TableCell align="right">
                  {t.status === "draft" && <Button size="small" onClick={() => move.mutate({ id: t.id, action: "publish" })}>Publish</Button>}
                  {t.status !== "archived" && <Button size="small" color="error" onClick={() => move.mutate({ id: t.id, action: "archive" })}>Archive</Button>}
                  <Button size="small" onClick={() => setHistory(t)}>History</Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>
      <Dialog open={!!history} onClose={() => setHistory(null)} fullWidth maxWidth="xs">
        <DialogTitle>{history?.name}: versions</DialogTitle>
        <DialogContent>
          {versions.data?.map((v) => (
            <Typography key={v.version} variant="body2" sx={{ py: 0.5 }}>
              <b>{v.version}</b> · added {dateTime(v.created_at)} · {v.published_at ? `published ${dateTime(v.published_at)}` : "not published"}
            </Typography>
          ))}
        </DialogContent>
        <DialogActions><Button onClick={() => setHistory(null)}>Close</Button></DialogActions>
      </Dialog>
    </Box>
  );
}
