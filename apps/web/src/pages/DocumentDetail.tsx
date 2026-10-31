import ArchiveIcon from "@mui/icons-material/Archive";
import DownloadIcon from "@mui/icons-material/Download";
import UnarchiveIcon from "@mui/icons-material/Unarchive";
import VisibilityIcon from "@mui/icons-material/Visibility";
import {
  Alert, Box, Button, Chip, Divider, Paper, Stack, Tab, Table, TableBody, TableCell, TableHead, TableRow, Tabs, Typography,
} from "@mui/material";
import Grid from "@mui/material/Grid2";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTemplate } from "@aaditech/ui-engine";
import { Fragment, useState } from "react";
import { Link as RouterLink, useParams } from "react-router-dom";
import { api, errorText } from "../api";
import { useCan } from "../App";
import { classTone, date, dateTime, label, size, stateTone } from "../format";
import { categoryName, useCategories } from "../queries";

interface Version {
  version_number: number;
  original_filename: string;
  content_type: string | null;
  size_bytes: number | null;
  review_status: string;
  status: string;
  comment: string | null;
  created_at: string;
}
interface Doc {
  id: string;
  title: string;
  category_id: string;
  classification: string;
  lifecycle_state: string;
  current_version_number: number | null;
  metadata: Record<string, unknown>;
  versions: Version[];
  access: { preview: boolean; download: boolean };
  created_at: string;
}
interface Lifecycle {
  retention_until: string | null;
  review_due_on: string | null;
  legal_hold: { reason: string } | null;
  deletion_request: { status: string } | null;
}
interface Request {
  id: string;
  version_number: number;
  status: string;
  current_step: number;
  total_steps: number;
  events: { id: string; action: string; comment: string | null; created_at: string }[];
}
interface Share {
  grantee_membership_id: string;
  grantee_name: string | null;
  can_download: boolean;
  expires_at: string | null;
}

export default function DocumentDetail() {
  const { id = "" } = useParams();
  const client = useQueryClient();
  const categories = useCategories();
  const canArchive = useCan("document.archive");
  const canRestore = useCan("document.restore");
  const [message, setMessage] = useState("");
  const [tab, setTab] = useState(0);
  const layout = useTemplate().pages.documentDetails.layout;

  const doc = useQuery({ queryKey: ["doc", id], queryFn: () => api<Doc>(`/documents/${id}`) });
  const life = useQuery({ queryKey: ["doc", id, "life"], queryFn: () => api<Lifecycle>(`/documents/${id}/lifecycle`), enabled: doc.isSuccess });
  const reviews = useQuery({ queryKey: ["doc", id, "reviews"], queryFn: () => api<Request[]>(`/documents/${id}/approvals`), enabled: doc.isSuccess });
  const shares = useQuery({ queryKey: ["doc", id, "shares"], queryFn: () => api<Share[]>(`/documents/${id}/shares`), enabled: doc.isSuccess });

  const change = useMutation({
    mutationFn: (action: "archive" | "unarchive") => api(`/documents/${id}/${action}`, { method: "POST" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["doc", id] }),
    onError: (e) => setMessage(errorText(e)),
  });

  async function open(version: number, kind: "download" | "preview") {
    setMessage("");
    try {
      const link = await api<{ url: string }>(`/documents/${id}/versions/${version}/${kind}-url`);
      window.open(link.url, "_blank", "noopener");
    } catch (e) {
      setMessage(kind === "preview" ? "This file type has no preview. Download it instead." : errorText(e));
    }
  }

  if (doc.error) return <Alert severity="warning">This document does not exist or you do not have access to it.</Alert>;
  const d = doc.data;
  if (!d) return null;
  const meta = Object.entries(d.metadata ?? {});

  const detailsCard = (
  <Paper sx={{ p: 2 }}>
    <Typography variant="subtitle1" sx={{ fontWeight: 600 }} gutterBottom>Details</Typography>
    <Table size="small">
      <TableBody>
        <TableRow><TableCell width={180}>Category</TableCell><TableCell>{categoryName(categories.data, d.category_id)}</TableCell></TableRow>
        <TableRow><TableCell>Created</TableCell><TableCell>{dateTime(d.created_at)}</TableCell></TableRow>
        {meta.map(([k, v]) => (
          <TableRow key={k}><TableCell sx={{ textTransform: "capitalize" }}>{k.replace(/_/g, " ")}</TableCell><TableCell>{String(v)}</TableCell></TableRow>
        ))}
        {life.data?.retention_until && <TableRow><TableCell>Keep until</TableCell><TableCell>{date(life.data.retention_until)}</TableCell></TableRow>}
        {life.data?.review_due_on && <TableRow><TableCell>Review due</TableCell><TableCell>{date(life.data.review_due_on)}</TableCell></TableRow>}
        {life.data?.legal_hold && <TableRow><TableCell>Legal hold</TableCell><TableCell>{life.data.legal_hold.reason}</TableCell></TableRow>}
      </TableBody>
    </Table>
  </Paper>
  );
  const versionsCard = (
  <Paper sx={{ p: 2 }}>
    <Typography variant="subtitle1" sx={{ fontWeight: 600 }} gutterBottom>Versions</Typography>
    <Table size="small">
      <TableHead>
        <TableRow><TableCell>Version</TableCell><TableCell>File</TableCell><TableCell>Size</TableCell><TableCell>Review</TableCell><TableCell>Added</TableCell><TableCell align="right">Open</TableCell></TableRow>
      </TableHead>
      <TableBody>
        {d.versions.map((v) => (
          <TableRow key={v.version_number}>
            <TableCell>
              v{v.version_number} {v.version_number === d.current_version_number && <Chip size="small" label="Current" color="primary" sx={{ ml: 0.5 }} />}
            </TableCell>
            <TableCell>
              {v.original_filename}
              {v.comment && <Typography variant="caption" display="block" color="text.secondary">{v.comment}</Typography>}
            </TableCell>
            <TableCell>{size(v.size_bytes)}</TableCell>
            <TableCell>{v.review_status === "none" ? "Not required" : label(v.review_status)}</TableCell>
            <TableCell>{date(v.created_at)}</TableCell>
            <TableCell align="right">
              <Button size="small" startIcon={<VisibilityIcon />} disabled={!d.access.preview} onClick={() => open(v.version_number, "preview")}>Preview</Button>
              <Button size="small" startIcon={<DownloadIcon />} disabled={!d.access.download} onClick={() => open(v.version_number, "download")}>Download</Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  </Paper>
  );
  const approvalCard = (
  <Paper sx={{ p: 2 }}>
    <Typography variant="subtitle1" sx={{ fontWeight: 600 }} gutterBottom>Approval history</Typography>
    {!reviews.data?.length && <Typography color="text.secondary" variant="body2">No review is recorded for this document, or it is not visible to you.</Typography>}
    {reviews.data?.map((r) => (
      <Box key={r.id} sx={{ mb: 2 }}>
        <Typography variant="body2" sx={{ fontWeight: 600 }}>
          Version {r.version_number} · {label(r.status)} · step {r.current_step} of {r.total_steps}
        </Typography>
        {r.events.filter((e) => e.action !== "step_started").map((e) => (
          <Typography key={e.id} variant="body2" color="text.secondary">
            {dateTime(e.created_at)} — {label(e.action)}{e.comment ? `: ${e.comment}` : ""}
          </Typography>
        ))}
        <Divider sx={{ mt: 1 }} />
      </Box>
    ))}
  </Paper>
  );
  const sharesCard = shares.data ? (
    <Paper sx={{ p: 2 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 600 }} gutterBottom>Shared with</Typography>
      {shares.data.length === 0 && <Typography color="text.secondary" variant="body2">Not shared with anyone.</Typography>}
      {shares.data.map((s) => (
        <Typography key={s.grantee_membership_id} variant="body2">
          {s.grantee_name ?? s.grantee_membership_id} · {s.can_download ? "view and download" : "view only"}
          {s.expires_at ? ` · until ${date(s.expires_at)}` : ""}
        </Typography>
      ))}
    </Paper>
  ) : null;
  const stack = (...parts: (JSX.Element | null)[]) => <Stack spacing={2}>{parts.map((part, i) => <Fragment key={i}>{part}</Fragment>)}</Stack>;
  const tabs = ["Overview", "Versions", "Approvals", "Sharing"];

  return (
    <Box>
      <Button component={RouterLink} to="/documents" size="small" sx={{ mb: 1 }}>← Documents</Button>
      <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }} flexWrap="wrap">
        <Typography variant="h5" data-testid="doc-title">{d.title}</Typography>
        <Chip size="small" color={classTone(d.classification)} variant="outlined" label={label(d.classification)} />
        <Chip size="small" color={stateTone(d.lifecycle_state)} label={label(d.lifecycle_state)} />
        <Box sx={{ flexGrow: 1 }} />
        {d.lifecycle_state === "approved" && canArchive && (
          <Button startIcon={<ArchiveIcon />} onClick={() => change.mutate("archive")}>Archive</Button>
        )}
        {d.lifecycle_state === "archived" && canRestore && (
          <Button startIcon={<UnarchiveIcon />} onClick={() => change.mutate("unarchive")}>Restore from archive</Button>
        )}
      </Stack>
      {message && <Alert severity="info" sx={{ mb: 2 }} onClose={() => setMessage("")}>{message}</Alert>}
      {layout === "stacked" ? (
        stack(detailsCard, versionsCard, approvalCard, sharesCard)
      ) : layout === "tabbed" ? (
        <>
          <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
            {tabs.map((x) => <Tab key={x} label={x} />)}
          </Tabs>
          {tab === 0 && detailsCard}
          {tab === 1 && versionsCard}
          {tab === 2 && approvalCard}
          {tab === 3 && (sharesCard ?? <Typography color="text.secondary">Sharing details are not visible to you.</Typography>)}
        </>
      ) : (
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, md: 7 }}>{stack(detailsCard, versionsCard)}</Grid>
          <Grid size={{ xs: 12, md: 5 }}>{stack(approvalCard, sharesCard)}</Grid>
        </Grid>
      )}
    </Box>
  );
}
