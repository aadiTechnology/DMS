import { Alert, Box, Button, Chip, MenuItem, Paper, Tab, Table, TableBody, TableCell, TableHead, TableRow, Tabs, TextField, Typography } from "@mui/material";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import { api, errorText } from "../api";
import { useCan } from "../App";
import ReasonDialog from "../components/ReasonDialog";
import { classTone, date, dateTime, label } from "../format";

interface Due {
  document_id: string;
  title: string;
  classification: string;
  lifecycle_state: string;
  due: { kind: string; date: string }[];
}
interface Request {
  id: string;
  document_id: string;
  title: string;
  classification: string;
  reason: string;
  requested_at: string;
}

const KIND: Record<string, string> = {
  retention_ending: "Keep-until date approaching",
  retention_ended: "Keep-until date has passed",
  review_due: "Review due",
  review_overdue: "Review overdue",
};

/** What is coming up for review or disposal, and deletion requests waiting for a second person to decide. */
export default function Retention() {
  const canDue = useCan("document.archive");
  const canDecide = useCan("document.approve_delete");
  const client = useQueryClient();
  const [tab, setTab] = useState<"due" | "deletions">(canDue ? "due" : "deletions");
  const [days, setDays] = useState(30);
  const [dialog, setDialog] = useState<{ request: Request; action: "approve" | "reject" } | null>(null);
  const [message, setMessage] = useState("");

  const due = useQuery({ queryKey: ["lifecycle-due", days], queryFn: () => api<Due[]>("/lifecycle/due", { params: { days } }), enabled: canDue && tab === "due" });
  const requests = useQuery({ queryKey: ["deletion-requests"], queryFn: () => api<Request[]>("/deletion-requests"), enabled: canDecide });
  const decide = useMutation({
    mutationFn: ({ id, action, reason }: { id: string; action: "approve" | "reject"; reason: string }) =>
      api(`/deletion-requests/${id}/${action}`, { body: { reason: reason || undefined } }),
    onSuccess: async (_d, v) => {
      setMessage(v.action === "approve" ? "Deleted. The stored files were removed and a record of the deletion remains." : "The request was rejected.");
      await client.invalidateQueries({ queryKey: ["deletion-requests"] });
      await client.invalidateQueries({ queryKey: ["search"] });
    },
  });

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 2 }}>Retention and disposal</Typography>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        {canDue && <Tab value="due" label="Due soon" />}
        {canDecide && <Tab value="deletions" label={`Deletion requests${requests.data?.length ? ` (${requests.data.length})` : ""}`} />}
      </Tabs>
      {message && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setMessage("")}>{message}</Alert>}
      {tab === "due" && (
        <>
          <TextField select size="small" label="Look ahead" value={days} onChange={(e) => setDays(Number(e.target.value))} sx={{ mb: 2, minWidth: 180 }}>
            {[30, 90, 180, 365].map((d) => <MenuItem key={d} value={d}>{d} days</MenuItem>)}
          </TextField>
          {due.error && <Alert severity="error">{errorText(due.error)}</Alert>}
          <Paper>
            <Table size="small">
              <TableHead><TableRow><TableCell>Document</TableCell><TableCell>Classification</TableCell><TableCell>What is due</TableCell></TableRow></TableHead>
              <TableBody>
                {due.data?.map((d) => (
                  <TableRow key={d.document_id}>
                    <TableCell><Typography component={RouterLink} to={`/documents/${d.document_id}`} color="primary" sx={{ fontWeight: 600, textDecoration: "none" }}>{d.title}</Typography></TableCell>
                    <TableCell><Chip size="small" variant="outlined" color={classTone(d.classification)} label={label(d.classification)} /></TableCell>
                    <TableCell>{d.due.map((x) => <div key={x.kind}>{KIND[x.kind] ?? x.kind}: {date(x.date)}</div>)}</TableCell>
                  </TableRow>
                ))}
                {due.data?.length === 0 && <TableRow><TableCell colSpan={3} align="center" sx={{ py: 4, color: "text.secondary" }}>Nothing is due in the next {days} days.</TableCell></TableRow>}
              </TableBody>
            </Table>
          </Paper>
        </>
      )}
      {tab === "deletions" && (
        <>
          <Alert severity="warning" sx={{ mb: 2 }}>Approving a deletion permanently removes the stored files. It cannot be undone, and it is refused while a legal hold applies or the keep-until date has not passed. You cannot decide your own request.</Alert>
          {requests.error && <Alert severity="error">{errorText(requests.error)}</Alert>}
          <Paper>
            <Table size="small">
              <TableHead><TableRow><TableCell>Document</TableCell><TableCell>Reason given</TableCell><TableCell>Requested</TableCell><TableCell align="right">Decision</TableCell></TableRow></TableHead>
              <TableBody>
                {requests.data?.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell><Typography component={RouterLink} to={`/documents/${r.document_id}`} color="primary" sx={{ fontWeight: 600, textDecoration: "none" }}>{r.title}</Typography></TableCell>
                    <TableCell>{r.reason}</TableCell>
                    <TableCell>{dateTime(r.requested_at)}</TableCell>
                    <TableCell align="right">
                      <Button size="small" color="error" onClick={() => setDialog({ request: r, action: "approve" })}>Approve deletion</Button>
                      <Button size="small" onClick={() => setDialog({ request: r, action: "reject" })}>Reject</Button>
                    </TableCell>
                  </TableRow>
                ))}
                {requests.data?.length === 0 && <TableRow><TableCell colSpan={4} align="center" sx={{ py: 4, color: "text.secondary" }}>No deletion requests are waiting.</TableCell></TableRow>}
              </TableBody>
            </Table>
          </Paper>
        </>
      )}
      <ReasonDialog
        open={!!dialog}
        title={dialog?.action === "approve" ? `Delete “${dialog.request.title}” permanently?` : `Reject the request for “${dialog?.request.title ?? ""}”`}
        description={dialog?.action === "approve" ? "The stored files are removed for good. Only a record that the document existed remains." : "Tell the requester why."}
        label={dialog?.action === "approve" ? "Note" : "Reason"}
        required={dialog?.action === "reject"}
        danger={dialog?.action === "approve"}
        confirmLabel={dialog?.action === "approve" ? "Delete permanently" : "Reject request"}
        onSubmit={(reason) => decide.mutateAsync({ id: dialog!.request.id, action: dialog!.action, reason })}
        onClose={() => setDialog(null)}
      />
    </Box>
  );
}
