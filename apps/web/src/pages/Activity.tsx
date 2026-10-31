import {
  Alert, Box, Button, Chip, Paper, Stack, Tab, Table, TableBody, TableCell, TableHead, TableRow, Tabs, TextField, Typography,
} from "@mui/material";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, errorText } from "../api";
import { useCan } from "../App";
import { dateTime } from "../format";

interface AuditEvent {
  id: string;
  occurred_at: string;
  actor_user_id: string | null;
  action: string;
  resource_type: string;
  outcome: string;
  privileged: boolean;
  details: Record<string, unknown>;
}
interface Person {
  user_id: string;
  full_name: string | null;
}
interface IndexStatus {
  counts: Record<string, number>;
  failures: { document_id: string; reason: string | null; attempts: number; updated_at: string }[];
}

const PAGE = 50;

function AuditLog() {
  const canPeople = useCan("admin.manage_organization");
  const [action, setAction] = useState("");
  const [applied, setApplied] = useState("");
  const [since, setSince] = useState("");
  const [offset, setOffset] = useState(0);
  const people = useQuery({ queryKey: ["employees"], queryFn: () => api<Person[]>("/employees", { params: { limit: 200 } }), enabled: canPeople });
  const events = useQuery({
    queryKey: ["audit", applied, since, offset],
    queryFn: () => api<AuditEvent[]>("/audit-events", { params: { action: applied, since: since ? new Date(since).toISOString() : undefined, limit: PAGE, offset } }),
  });
  const who = (id: string | null) => (id ? (people.data?.find((p) => p.user_id === id)?.full_name ?? "A person") : "The system");
  return (
    <>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ mb: 2 }} component="form" onSubmit={(e) => { e.preventDefault(); setApplied(action.trim()); setOffset(0); }}>
        <TextField size="small" label="Action (exact, for example document.uploaded)" value={action} onChange={(e) => setAction(e.target.value)} sx={{ minWidth: 340 }} />
        <TextField size="small" type="date" label="Since" value={since} onChange={(e) => { setSince(e.target.value); setOffset(0); }} slotProps={{ inputLabel: { shrink: true } }} />
        <Button type="submit" variant="contained">Filter</Button>
      </Stack>
      {events.error && <Alert severity="error">{errorText(events.error)}</Alert>}
      <Paper>
        <Table size="small">
          <TableHead><TableRow><TableCell>When</TableCell><TableCell>Who</TableCell><TableCell>What</TableCell><TableCell>Result</TableCell><TableCell>Details</TableCell></TableRow></TableHead>
          <TableBody>
            {events.data?.map((e) => (
              <TableRow key={e.id}>
                <TableCell sx={{ whiteSpace: "nowrap" }}>{dateTime(e.occurred_at)}</TableCell>
                <TableCell>{who(e.actor_user_id)}</TableCell>
                <TableCell>
                  <b>{e.action}</b>
                  {e.privileged && <Chip size="small" color="warning" label="privileged" sx={{ ml: 1 }} />}
                </TableCell>
                <TableCell><Chip size="small" label={e.outcome} color={e.outcome === "success" ? "success" : "error"} variant="outlined" /></TableCell>
                <TableCell sx={{ maxWidth: 360, wordBreak: "break-word" }}><Typography variant="caption" color="text.secondary">{Object.keys(e.details ?? {}).length ? JSON.stringify(e.details).slice(0, 160) : ""}</Typography></TableCell>
              </TableRow>
            ))}
            {events.data?.length === 0 && <TableRow><TableCell colSpan={5} align="center" sx={{ py: 4, color: "text.secondary" }}>No matching activity.</TableCell></TableRow>}
          </TableBody>
        </Table>
      </Paper>
      <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
        <Button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Newer</Button>
        <Button disabled={(events.data?.length ?? 0) < PAGE} onClick={() => setOffset(offset + PAGE)}>Older</Button>
      </Stack>
    </>
  );
}

function SearchIndex() {
  const client = useQueryClient();
  const [message, setMessage] = useState("");
  const status = useQuery({ queryKey: ["index-status"], queryFn: () => api<IndexStatus>("/search/index/status") });
  const run = useMutation({
    mutationFn: (action: "retry" | "run") => api<Record<string, number>>(`/search/index/${action}`, { method: "POST" }),
    onSuccess: async (r, action) => {
      setMessage(action === "retry" ? `${r.requeued ?? 0} failed documents were queued again.` : `Processed the queue: ${r.indexed ?? 0} indexed, ${r.failed ?? 0} failed, ${r.unsupported ?? 0} not readable.`);
      await client.invalidateQueries({ queryKey: ["index-status"] });
    },
    onError: (e) => setMessage(errorText(e)),
  });
  return (
    <>
      <Typography color="text.secondary" sx={{ mb: 2 }}>Search reads the text inside documents in the background. This shows how that is going; it lists no titles or content.</Typography>
      {message && <Alert severity="info" sx={{ mb: 2 }} onClose={() => setMessage("")}>{message}</Alert>}
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 2 }}>
        {Object.entries(status.data?.counts ?? {}).map(([k, v]) => <Chip key={k} label={`${k}: ${v}`} color={k === "failed" && v > 0 ? "error" : "default"} />)}
        {status.data && Object.keys(status.data.counts).length === 0 && <Typography color="text.secondary">No documents have been indexed yet.</Typography>}
      </Stack>
      <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
        <Button variant="contained" disabled={run.isPending} onClick={() => run.mutate("run")}>Process the queue now</Button>
        <Button disabled={run.isPending} onClick={() => run.mutate("retry")}>Retry failed documents</Button>
      </Stack>
      {status.data?.failures.length ? (
        <Paper>
          <Table size="small">
            <TableHead><TableRow><TableCell>Document</TableCell><TableCell>Reason</TableCell><TableCell>Attempts</TableCell><TableCell>Last tried</TableCell></TableRow></TableHead>
            <TableBody>
              {status.data.failures.map((f) => (
                <TableRow key={f.document_id}><TableCell sx={{ fontFamily: "monospace" }}>{f.document_id.slice(0, 8)}…</TableCell><TableCell>{f.reason ?? "unknown"}</TableCell><TableCell>{f.attempts}</TableCell><TableCell>{dateTime(f.updated_at)}</TableCell></TableRow>
              ))}
            </TableBody>
          </Table>
        </Paper>
      ) : null}
    </>
  );
}

/** What has happened in the organization (audit log) and the health of document text search. */
export default function Activity() {
  const canAudit = useCan("admin.view_audit");
  const canIndex = useCan("admin.manage_organization");
  const [tab, setTab] = useState<"log" | "index">(canAudit ? "log" : "index");
  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 2 }}>Activity</Typography>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        {canAudit && <Tab value="log" label="Audit log" />}
        {canIndex && <Tab value="index" label="Search index" />}
      </Tabs>
      {tab === "log" && canAudit && <AuditLog />}
      {tab === "index" && canIndex && <SearchIndex />}
    </Box>
  );
}
