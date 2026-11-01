import { resolveDashboard, useTemplate, type ResolvedWidget, type WidgetId } from "@aaditech/ui-engine";
import { Box, Button, Chip, Link, List, ListItem, ListItemText, Paper, Skeleton, Stack, Typography, Alert } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link as RouterLink } from "react-router-dom";
import { api, getSession } from "../api";
import { classTone, CLASSIFICATIONS, date, dateTime, label, size, stateTone } from "../format";

interface Dashboard {
  generated_at: string;
  stats: { documents: number; pending_reviews: number; shared_with_me: number; storage_bytes: number };
  uploads_by_day: { date: string; count: number }[];
  by_classification: { value: string; count: number }[];
  recent_documents: { id: string; title: string; classification: string; lifecycle_state: string; created_at: string }[];
  approvals_queue: { request_id: string; document_id: string; title: string; submitted_at: string }[];
  expiring_soon: { total: number; items: { id: string; title: string; retention_until: string | null; review_due_on: string | null }[] };
  activity: { action: string; outcome: string; occurred_at: string; actor: string | null }[] | null;
}

const CLASS_NAME = Object.fromEntries(CLASSIFICATIONS) as Record<string, string>;

function Card({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <Paper sx={{ p: 2, height: "100%", display: "flex", flexDirection: "column" }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>{title}</Typography>
        {action}
      </Stack>
      {children}
    </Paper>
  );
}

function Stat({ title, value, to, hint }: { title: string; value: string; to?: string; hint?: string }) {
  const body = (
    <Paper sx={{ p: 2, height: "100%" }}>
      <Typography variant="body2" color="text.secondary">{title}</Typography>
      <Typography variant="h4" sx={{ fontWeight: 700, my: 0.5 }}>{value}</Typography>
      {hint && <Typography variant="caption" color="text.secondary">{hint}</Typography>}
    </Paper>
  );
  return to ? <Link component={RouterLink} to={to} underline="none" color="inherit" sx={{ display: "block", height: "100%" }}>{body}</Link> : body;
}

const Empty = ({ children }: { children: ReactNode }) => <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>{children}</Typography>;

/** Daily uploads for the last 30 days as plain bars (no chart library). */
function UploadsChart({ days }: { days: Dashboard["uploads_by_day"] }) {
  const max = Math.max(1, ...days.map((d) => d.count));
  const total = days.reduce((n, d) => n + d.count, 0);
  if (total === 0) return <Empty>No documents were added in the last 30 days.</Empty>;
  return (
    <Box>
      <Box role="img" aria-label={`Documents added per day, last 30 days: ${total} in total`} sx={{ display: "flex", alignItems: "flex-end", gap: "2px", height: 110, color: "primary.main" }}>
        {days.map((d) => (
          <Box key={d.date} title={`${date(d.date)}: ${d.count}`} sx={{ flex: 1, height: `${Math.max((d.count / max) * 100, d.count ? 4 : 1)}%`, bgcolor: "currentColor", opacity: d.count ? 0.85 : 0.2, borderRadius: "2px 2px 0 0" }} />
        ))}
      </Box>
      <Stack direction="row" justifyContent="space-between" sx={{ mt: 0.5 }}>
        <Typography variant="caption" color="text.secondary">{date(days[0]!.date)}</Typography>
        <Typography variant="caption" color="text.secondary">{total} added in 30 days</Typography>
        <Typography variant="caption" color="text.secondary">{date(days[days.length - 1]!.date)}</Typography>
      </Stack>
    </Box>
  );
}

function ClassificationChart({ rows }: { rows: Dashboard["by_classification"] }) {
  const total = rows.reduce((n, r) => n + r.count, 0);
  if (!total) return <Empty>No documents yet.</Empty>;
  return (
    <Stack spacing={1}>
      {rows.map((r) => (
        <Box key={r.value}>
          <Stack direction="row" justifyContent="space-between"><Typography variant="body2">{CLASS_NAME[r.value] ?? label(r.value)}</Typography><Typography variant="body2">{r.count}</Typography></Stack>
          <Box sx={{ height: 8, borderRadius: 4, bgcolor: "action.hover" }}>
            <Box sx={{ height: 8, borderRadius: 4, width: `${(r.count / total) * 100}%`, bgcolor: `${classTone(r.value) === "default" ? "primary" : classTone(r.value)}.main` }} />
          </Box>
        </Box>
      ))}
    </Stack>
  );
}

function widgetBody(id: WidgetId, d: Dashboard): ReactNode {
  switch (id) {
    case "welcome": {
      const name = (getSession()?.email ?? "").split("@")[0]!.replace(/[._]/g, " ");
      return (
        <Paper sx={{ p: 3, height: "100%" }}>
          <Typography variant="h5" sx={{ textTransform: "capitalize" }}>Welcome, {name}</Typography>
          <Typography color="text.secondary">Here is what is happening with the documents you can see.</Typography>
        </Paper>
      );
    }
    case "stat-documents":
      return <Stat title="Documents" value={String(d.stats.documents)} to="/documents" hint="you can see" />;
    case "stat-pending":
      return <Stat title="Waiting for your review" value={String(d.stats.pending_reviews)} to="/approvals" />;
    case "stat-shared":
      return <Stat title="Shared with you" value={String(d.stats.shared_with_me)} to="/shared" />;
    case "stat-storage":
      return <Stat title="Storage" value={size(d.stats.storage_bytes) || "0 B"} hint="current versions you can see" />;
    case "chart-uploads":
      return <Card title="Added in the last 30 days"><UploadsChart days={d.uploads_by_day} /></Card>;
    case "chart-classification":
      return <Card title="By classification"><ClassificationChart rows={d.by_classification} /></Card>;
    case "recent-documents":
      return (
        <Card title="Recent documents" action={<Button size="small" component={RouterLink} to="/documents">All</Button>}>
          {d.recent_documents.length === 0 ? <Empty>No documents yet.</Empty> : (
            <List dense disablePadding>
              {d.recent_documents.map((r) => (
                <ListItem key={r.id} disableGutters secondaryAction={<Chip size="small" label={label(r.lifecycle_state)} color={stateTone(r.lifecycle_state)} variant="outlined" />}>
                  <ListItemText primary={<Link component={RouterLink} to={`/documents/${r.id}`} underline="hover">{r.title}</Link>} secondary={`${CLASS_NAME[r.classification] ?? r.classification} · ${dateTime(r.created_at)}`} />
                </ListItem>
              ))}
            </List>
          )}
        </Card>
      );
    case "approvals-queue":
      return (
        <Card title="Your review queue" action={<Button size="small" component={RouterLink} to="/approvals">Open</Button>}>
          {d.approvals_queue.length === 0 ? <Empty>Nothing is waiting for you.</Empty> : (
            <List dense disablePadding>
              {d.approvals_queue.map((r) => (
                <ListItem key={r.request_id} disableGutters>
                  <ListItemText primary={<Link component={RouterLink} to="/approvals" underline="hover">{r.title}</Link>} secondary={`Submitted ${dateTime(r.submitted_at)}`} />
                </ListItem>
              ))}
            </List>
          )}
        </Card>
      );
    case "expiring-soon":
      return (
        <Card title="Due soon (30 days)" action={d.expiring_soon.total > 0 ? <Button size="small" component={RouterLink} to="/retention">{d.expiring_soon.total} in all</Button> : undefined}>
          {d.expiring_soon.items.length === 0 ? <Empty>No retention or review dates are coming up.</Empty> : (
            <List dense disablePadding>
              {d.expiring_soon.items.map((r) => (
                <ListItem key={r.id} disableGutters>
                  <ListItemText
                    primary={<Link component={RouterLink} to={`/documents/${r.id}`} underline="hover">{r.title}</Link>}
                    secondary={[r.retention_until && `Keep until ${date(r.retention_until)}`, r.review_due_on && `Review by ${date(r.review_due_on)}`].filter(Boolean).join(" · ")}
                  />
                </ListItem>
              ))}
            </List>
          )}
        </Card>
      );
    case "activity":
      return (
        <Card title="Recent activity" action={d.activity ? <Button size="small" component={RouterLink} to="/activity">Audit log</Button> : undefined}>
          {d.activity === null ? <Empty>The activity feed is shown to administrators.</Empty> : d.activity.length === 0 ? <Empty>No activity yet.</Empty> : (
            <List dense disablePadding>
              {d.activity.map((a, i) => (
                <ListItem key={i} disableGutters>
                  <ListItemText primary={`${a.actor ?? "The system"} · ${a.action.replace(/[._]/g, " ")}`} secondary={dateTime(a.occurred_at)} />
                </ListItem>
              ))}
            </List>
          )}
        </Card>
      );
  }
}

export default function Dashboard() {
  const template = useTemplate();
  const plan = resolveDashboard(template);
  const data = useQuery({ queryKey: ["dashboard"], queryFn: () => api<Dashboard>("/dashboard"), refetchOnMount: "always" });
  // "focus-list" shows the same widgets as one calm column; the other presets use the grid of the design.
  const focus = plan.layout === "focus-list";
  const columns = focus ? 1 : plan.columns;
  // On a phone the grid has two columns: the four figures sit two to a row, every card takes the full width.
  const place = (w: ResolvedWidget) => ({ gridColumn: { xs: w.id.startsWith("stat-") ? "span 1" : "span 2", md: focus ? "auto" : `span ${Math.min(w.span, columns)}` } });
  return (
    <Box sx={{ maxWidth: focus ? 880 : undefined }}>
      <Stack direction="row" alignItems="baseline" justifyContent="space-between" sx={{ mb: 2 }}>
        <Typography variant="h5">Dashboard</Typography>
        {data.data && <Typography variant="caption" color="text.secondary">Updated {dateTime(data.data.generated_at)}</Typography>}
      </Stack>
      {data.isError && <Alert severity="error">The dashboard could not be loaded.</Alert>}
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "repeat(2, minmax(0, 1fr))", md: `repeat(${columns}, minmax(0, 1fr))` }, gap: 2, alignItems: "stretch" }} data-dashboard-layout={plan.layout}>
        {plan.widgets.map((w) => (
          <Box key={w.id} sx={{ ...place(w), minHeight: { md: focus || w.rows < 2 || w.id === "welcome" ? undefined : 150 * w.rows - 40 }, ...(plan.layout === "dark-hero" && w.id === "welcome" ? { "& .MuiPaper-root": { bgcolor: "primary.main", color: "primary.contrastText", "& .MuiTypography-colorTextSecondary, & .MuiTypography-root": { color: "inherit" } } } : {}) }}>
            {data.data ? widgetBody(w.id, data.data) : <Skeleton variant="rounded" height={w.rows > 1 ? 160 : 90} />}
          </Box>
        ))}
      </Box>
    </Box>
  );
}
