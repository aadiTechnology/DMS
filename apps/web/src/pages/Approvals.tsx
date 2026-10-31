import {
  Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Paper, Stack, Table, TableBody,
  TableCell, TableHead, TableRow, TextField, Typography,
} from "@mui/material";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import { api, errorText } from "../api";
import { classTone, dateTime, label } from "../format";

interface Item {
  id: string;
  document_id: string;
  title: string;
  classification: string;
  version_number: number;
  current_step: number;
  total_steps: number;
  submitted_at: string;
}
interface Detail extends Item {
  status: string;
  can_decide: boolean;
  events: { id: string; action: string; comment: string | null; created_at: string; privileged: boolean }[];
}

export default function Approvals() {
  const client = useQueryClient();
  const queue = useQuery({ queryKey: ["approvals", "queue"], queryFn: () => api<Item[]>("/approvals/queue") });
  const [open, setOpen] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [error, setError] = useState("");
  const detail = useQuery({ queryKey: ["approval", open], queryFn: () => api<Detail>(`/approvals/${open}`), enabled: !!open });

  const decide = useMutation({
    mutationFn: (action: "approve" | "reject") =>
      api(`/approvals/${open}/${action}`, { body: action === "reject" ? { reason: comment } : { comment: comment || undefined } }),
    onSuccess: () => {
      setOpen(null);
      setComment("");
      client.invalidateQueries({ queryKey: ["approvals"] });
      client.invalidateQueries({ queryKey: ["search"] });
    },
    onError: (e) => setError(errorText(e)),
  });
  const close = () => {
    setOpen(null);
    setComment("");
    setError("");
  };

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 2 }}>Approvals waiting for you</Typography>
      {queue.error && <Alert severity="error">{errorText(queue.error)}</Alert>}
      <Paper>
        <Table size="small">
          <TableHead>
            <TableRow><TableCell>Document</TableCell><TableCell>Version</TableCell><TableCell>Classification</TableCell><TableCell>Step</TableCell><TableCell>Submitted</TableCell><TableCell /></TableRow>
          </TableHead>
          <TableBody>
            {queue.data?.map((r) => (
              <TableRow key={r.id} hover>
                <TableCell sx={{ fontWeight: 600 }}>{r.title}</TableCell>
                <TableCell>v{r.version_number}</TableCell>
                <TableCell><Chip size="small" variant="outlined" color={classTone(r.classification)} label={label(r.classification)} /></TableCell>
                <TableCell>{r.current_step} of {r.total_steps}</TableCell>
                <TableCell>{dateTime(r.submitted_at)}</TableCell>
                <TableCell align="right"><Button size="small" variant="contained" onClick={() => setOpen(r.id)}>Review</Button></TableCell>
              </TableRow>
            ))}
            {queue.data?.length === 0 && (
              <TableRow><TableCell colSpan={6} align="center" sx={{ py: 4, color: "text.secondary" }}>Nothing is waiting for your decision.</TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </Paper>
      <Dialog open={!!open} onClose={close} fullWidth maxWidth="sm">
        <DialogTitle>{detail.data?.title ?? "Review"}</DialogTitle>
        <DialogContent>
          {detail.data && (
            <Stack spacing={2} sx={{ mt: 1 }}>
              <Typography variant="body2">
                Version {detail.data.version_number} · {label(detail.data.status)} ·{" "}
                <RouterLink to={`/documents/${detail.data.document_id}`}>open the document</RouterLink> to read it before deciding.
              </Typography>
              {detail.data.events.filter((e) => e.action !== "step_started").map((e) => (
                <Typography key={e.id} variant="body2" color="text.secondary">
                  {dateTime(e.created_at)} — {label(e.action)}{e.comment ? `: ${e.comment}` : ""}
                </Typography>
              ))}
              {error && <Alert severity="error">{error}</Alert>}
              <TextField label="Comment (required to reject)" multiline minRows={2} value={comment} onChange={(e) => setComment(e.target.value)} />
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={close}>Close</Button>
          <Button color="error" disabled={!comment.trim() || !detail.data?.can_decide} onClick={() => decide.mutate("reject")}>Reject</Button>
          <Button variant="contained" disabled={!detail.data?.can_decide} onClick={() => decide.mutate("approve")}>Approve</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
