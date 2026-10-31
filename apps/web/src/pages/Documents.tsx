import { useTemplate } from "@aaditech/ui-engine";
import SearchIcon from "@mui/icons-material/Search";
import {
  Alert, Box, Button, Card, CardActionArea, CardContent, Chip, ToggleButton, ToggleButtonGroup, InputAdornment, MenuItem, Paper, Stack, Table, TableBody,
  TableCell, TableHead, TablePagination, TableRow, TextField, Typography,
} from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
import { api, errorText } from "../api";
import { CLASSIFICATIONS, classTone, date, label, size, stateTone } from "../format";
import { categoryName, useCategories } from "../queries";

interface Item {
  id: string;
  title: string;
  category_id: string;
  classification: string;
  lifecycle_state: string;
  current_version_number: number | null;
  filename: string | null;
  size_bytes: number | null;
  updated_at: string;
}
interface Result {
  items: Item[];
  total: number;
  facets: Record<string, { value: string; count: number }[]>;
}

const STATUSES = ["approved", "submitted", "under_review", "rejected", "archived"];

export default function Documents() {
  const categories = useCategories();
  const layout = useTemplate().pages.documentExplorer.layout;
  const [params] = useSearchParams();
  const [text, setText] = useState(params.get("q") ?? "");
  const [q, setQ] = useState(params.get("q") ?? "");
  const [category, setCategory] = useState(params.get("category") ?? "");
  const [classification, setClassification] = useState("");
  const [status, setStatus] = useState("");
  const [mine, setMine] = useState(false);
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<{ user_id: string }>("/auth/me"), staleTime: 300_000 });
  const [page, setPage] = useState(0);
  const rows = 10;

  // The header search box and the category panel navigate here with ?q= and ?category=.
  useEffect(() => {
    setText(params.get("q") ?? "");
    setQ(params.get("q") ?? "");
    setCategory(params.get("category") ?? "");
    setPage(0);
  }, [params]);

  const result = useQuery({
    queryKey: ["search", q, category, classification, status, page, mine],
    queryFn: () =>
      api<Result>("/search", {
        params: { q, category_id: category, classification, status, uploader_id: mine ? me.data?.user_id : undefined, limit: rows, offset: page * rows, sort: q ? "relevance" : "date" },
      }),
  });
  const reset = <T,>(set: (v: T) => void) => (v: T) => {
    set(v);
    setPage(0);
  };
  const facet = (name: string, value: string) => result.data?.facets?.[name]?.find((f) => f.value === value)?.count;
  const items = result.data?.items ?? [];

  const chips = (d: Item) => (
    <>
      <Chip size="small" color={classTone(d.classification)} variant="outlined" label={label(d.classification)} />
      <Chip size="small" color={stateTone(d.lifecycle_state)} label={label(d.lifecycle_state)} />
    </>
  );
  const titleLink = (d: Item) => (
    <Typography component={RouterLink} to={`/documents/${d.id}`} color="primary" sx={{ fontWeight: 600, textDecoration: "none" }}>
      {d.title}
    </Typography>
  );

  const asTable = (
    <Paper>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Title</TableCell>
            <TableCell>Category</TableCell>
            <TableCell>Classification</TableCell>
            <TableCell>Status</TableCell>
            <TableCell>Version</TableCell>
            <TableCell>Size</TableCell>
            <TableCell>Updated</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {items.map((d) => (
            <TableRow key={d.id} hover>
              <TableCell>
                {titleLink(d)}
                <Typography variant="caption" display="block" color="text.secondary">{d.filename}</Typography>
              </TableCell>
              <TableCell>{categoryName(categories.data, d.category_id)}</TableCell>
              <TableCell><Chip size="small" color={classTone(d.classification)} variant="outlined" label={label(d.classification)} /></TableCell>
              <TableCell><Chip size="small" color={stateTone(d.lifecycle_state)} label={label(d.lifecycle_state)} /></TableCell>
              <TableCell>{d.current_version_number ? `v${d.current_version_number}` : "—"}</TableCell>
              <TableCell>{size(d.size_bytes)}</TableCell>
              <TableCell>{date(d.updated_at)}</TableCell>
            </TableRow>
          ))}
          {result.data && items.length === 0 && (
            <TableRow>
              <TableCell colSpan={7} align="center" sx={{ py: 4, color: "text.secondary" }}>
                No documents match. Only documents you are allowed to see are listed.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </Paper>
  );

  const asList = (
    <Box>
      {items.map((d) => (
        <Stack key={d.id} direction="row" alignItems="center" spacing={2} sx={{ py: 2.5, borderBottom: 1, borderColor: "divider" }}>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography variant="h6" component="div">{titleLink(d)}</Typography>
            <Typography variant="body2" color="text.secondary">
              {categoryName(categories.data, d.category_id)} · {date(d.updated_at)} · {d.current_version_number ? `v${d.current_version_number}` : "no version"} · {size(d.size_bytes)}
            </Typography>
          </Box>
          {chips(d)}
        </Stack>
      ))}
      {result.data && items.length === 0 && <Typography color="text.secondary" sx={{ py: 4 }}>No documents match.</Typography>}
    </Box>
  );

  const asGrid = (
    <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))" }}>
      {items.map((d) => (
        <Card key={d.id} variant="outlined">
          <CardActionArea component={RouterLink} to={`/documents/${d.id}`} sx={{ height: "100%" }}>
            <CardContent>
              <Typography fontWeight={700} gutterBottom>{d.title}</Typography>
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1.5 }}>
                {categoryName(categories.data, d.category_id)} · {date(d.updated_at)}
              </Typography>
              <Stack direction="row" gap={0.5} flexWrap="wrap">{chips(d)}</Stack>
            </CardContent>
          </CardActionArea>
        </Card>
      ))}
      {result.data && items.length === 0 && <Typography color="text.secondary">No documents match.</Typography>}
    </Box>
  );

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 2 }}>
        Documents
      </Typography>
      <ToggleButtonGroup exclusive size="small" value={mine ? "mine" : "all"} onChange={(_, v) => { if (v) { setMine(v === "mine"); setPage(0); } }} sx={{ mb: 2 }} aria-label="Which documents">
        <ToggleButton value="all">All documents</ToggleButton>
        <ToggleButton value="mine" disabled={!me.data}>Uploaded by me</ToggleButton>
      </ToggleButtonGroup>
      <Paper sx={{ p: 2, mb: 2 }}>
        <Stack
          direction={{ xs: "column", md: "row" }}
          spacing={2}
          component="form"
          onSubmit={(e) => {
            e.preventDefault();
            setQ(text.trim());
            setPage(0);
          }}
        >
          <TextField
            fullWidth
            size="small"
            placeholder="Search titles, file names, metadata and document text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon /></InputAdornment> } }}
            inputProps={{ "aria-label": "Search documents in this page" }}
          />
          <TextField select size="small" label="Category" value={category} onChange={(e) => reset(setCategory)(e.target.value)} sx={{ minWidth: 200 }}>
            <MenuItem value="">All categories</MenuItem>
            {categories.data?.map((c) => (
              <MenuItem key={c.id} value={c.id}>{c.path}</MenuItem>
            ))}
          </TextField>
          <TextField select size="small" label="Classification" value={classification} onChange={(e) => reset(setClassification)(e.target.value)} sx={{ minWidth: 180 }}>
            <MenuItem value="">All</MenuItem>
            {CLASSIFICATIONS.map(([v, l]) => (
              <MenuItem key={v} value={v}>{`${l}${facet("classification", v) ? ` (${facet("classification", v)})` : ""}`}</MenuItem>
            ))}
          </TextField>
          <TextField select size="small" label="Status" value={status} onChange={(e) => reset(setStatus)(e.target.value)} sx={{ minWidth: 150 }}>
            <MenuItem value="">All</MenuItem>
            {STATUSES.map((s) => (
              <MenuItem key={s} value={s}>{label(s)}</MenuItem>
            ))}
          </TextField>
          <Button type="submit" variant="contained">Search</Button>
        </Stack>
      </Paper>
      {result.error && <Alert severity="error">{errorText(result.error)}</Alert>}
      {layout === "list" ? asList : layout === "grid" ? asGrid : asTable}
      <TablePagination
        component="div"
        count={result.data?.total ?? 0}
        page={page}
        rowsPerPage={rows}
        rowsPerPageOptions={[rows]}
        onPageChange={(_, p) => setPage(p)}
      />
    </Box>
  );
}
