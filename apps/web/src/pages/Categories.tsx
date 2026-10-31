import {
  Alert, Box, Button, Checkbox, Chip, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, IconButton, MenuItem, Paper,
  Stack, Switch, Tab, Table, TableBody, TableCell, TableHead, TableRow, Tabs, TextField, Typography,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, errorText } from "../api";
import { CLASSIFICATIONS, classTone, label } from "../format";

interface Cat {
  id: string;
  name: string;
  parent_id: string | null;
  path: string;
  depth: number;
  status: string;
  default_classification: string;
  current_version_number: number;
}
interface FieldDef {
  key: string;
  label: string;
  field_type: string;
  required: boolean;
  validation: Record<string, unknown>;
}
interface Step {
  type: "user" | "role" | "department_manager";
  ref?: string | null;
}
interface Detail extends Cat {
  version: {
    approval_required: boolean;
    required_dimensions: string[];
    allowed_extensions: string[] | null;
    retention_days: number | null;
    review_interval_days: number | null;
    reminder_days: number[];
    approval_steps: Step[];
    fields: FieldDef[];
  };
}
interface Tag {
  id: string;
  name: string;
  kind: string;
  status: string;
}

const FIELD_TYPES = ["text", "long_text", "number", "decimal", "date", "date_range", "boolean", "single_select", "multi_select", "employee_lookup", "department_lookup", "branch_lookup", "project_lookup", "tag_selector"];
const DIMENSIONS = ["department", "branch", "project", "employee"];
const numberOrNull = (v: string) => (v.trim() === "" ? null : Number(v));

/** Create a category, or publish a new version of its rules. Existing documents keep the rules they were created under. */
function CategoryEditor({ category, categories, onClose }: { category: Cat | "new" | null; categories: Cat[]; onClose: () => void }) {
  const client = useQueryClient();
  const creating = category === "new";
  const existing = category && category !== "new" ? category : null;
  const detail = useQuery({ queryKey: ["category-admin", existing?.id], queryFn: () => api<Detail>(`/categories/${existing!.id}`), enabled: !!existing });
  const people = useQuery({ queryKey: ["employees"], queryFn: () => api<{ membership_id: string; full_name: string | null }[]>("/employees", { params: { limit: 200 } }), enabled: !!category, retry: false });
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => api<{ id: string; name: string }[]>("/roles"), enabled: !!category, retry: false });

  const [name, setName] = useState("");
  const [parent, setParent] = useState("");
  const [classification, setClassification] = useState("internal");
  const [approval, setApproval] = useState(false);
  const [dims, setDims] = useState<string[]>([]);
  const [ext, setExt] = useState("");
  const [retention, setRetention] = useState("");
  const [review, setReview] = useState("");
  const [reminders, setReminders] = useState("");
  const [steps, setSteps] = useState<Step[]>([]);
  const [fields, setFields] = useState<(FieldDef & { options: string })[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (creating) {
      setName(""); setParent(""); setClassification("internal"); setApproval(false); setDims([]); setExt(""); setRetention(""); setReview(""); setReminders(""); setSteps([]); setFields([]); setError("");
    }
  }, [creating, category]);
  useEffect(() => {
    const v = detail.data?.version;
    if (!v) return;
    setApproval(v.approval_required);
    setDims(v.required_dimensions);
    setExt((v.allowed_extensions ?? []).join(", "));
    setRetention(v.retention_days?.toString() ?? "");
    setReview(v.review_interval_days?.toString() ?? "");
    setReminders(v.reminder_days.join(", "));
    setSteps(v.approval_steps.map((s) => ({ type: s.type, ref: s.ref ?? null })));
    setFields(v.fields.map((f) => ({ ...f, options: Array.isArray(f.validation?.options) ? (f.validation.options as string[]).join(", ") : "" })));
    setError("");
  }, [detail.data]);

  const body = () => ({
    policy: {
      approval_required: approval,
      required_dimensions: dims,
      allowed_extensions: ext.trim() ? ext.split(",").map((x) => x.trim().replace(/^\./, "").toLowerCase()).filter(Boolean) : null,
      retention_days: numberOrNull(retention),
      review_interval_days: numberOrNull(review),
      reminder_days: reminders.split(",").map((x) => x.trim()).filter(Boolean).map(Number),
      approval_steps: approval ? steps.map((s) => ({ type: s.type, ref: s.type === "department_manager" ? undefined : s.ref })) : [],
    },
    fields: fields.map((f, i) => ({
      key: f.key.trim(), label: f.label.trim(), field_type: f.field_type, required: f.required, display_order: i + 1,
      validation: f.field_type === "single_select" || f.field_type === "multi_select" ? { options: f.options.split(",").map((x) => x.trim()).filter(Boolean) } : (f.validation && !("options" in f.validation) ? f.validation : {}),
    })),
  });
  const save = useMutation({
    mutationFn: () => (creating ? api("/categories", { body: { name: name.trim(), parent_id: parent || undefined, default_classification: classification, ...body() } }) : api(`/categories/${existing!.id}/versions`, { body: body() })),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["categories-all"] });
      await client.invalidateQueries({ queryKey: ["categories"] });
      onClose();
    },
    onError: (e) => setError(errorText(e)),
  });
  const setField = (i: number, patch: Partial<FieldDef & { options: string }>) => setFields(fields.map((f, j) => (j === i ? { ...f, ...patch } : f)));
  const setStep = (i: number, patch: Partial<Step>) => setSteps(steps.map((s, j) => (j === i ? { ...s, ...patch } : s)));

  return (
    <Dialog open={!!category} onClose={onClose} fullWidth maxWidth="md" scroll="paper">
      <DialogTitle>{creating ? "New category" : `Rules for ${existing?.name}`}</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2.5}>
          {error && <Alert severity="error">{error}</Alert>}
          {!creating && <Alert severity="info">Saving publishes a new version of these rules (now version {(existing?.current_version_number ?? 0) + 1}). Documents already filed keep the rules they were created under.</Alert>}
          {creating && (
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField label="Name" value={name} onChange={(e) => setName(e.target.value)} required sx={{ flex: 2 }} />
              <TextField select label="Inside" value={parent} onChange={(e) => setParent(e.target.value)} sx={{ flex: 2 }}>
                <MenuItem value="">Top level</MenuItem>
                {categories.filter((c) => c.status === "active").map((c) => <MenuItem key={c.id} value={c.id}>{c.path}</MenuItem>)}
              </TextField>
              <TextField select label="Default classification" value={classification} onChange={(e) => setClassification(e.target.value)} sx={{ flex: 2 }}>
                {CLASSIFICATIONS.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
              </TextField>
            </Stack>
          )}
          <Typography variant="subtitle1" fontWeight={600}>Rules</Typography>
          <FormControlLabel control={<Switch checked={approval} onChange={(e) => setApproval(e.target.checked)} />} label="Documents are reviewed before they are released" />
          {approval && (
            <Box sx={{ pl: 2, borderLeft: 3, borderColor: "divider" }}>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>Review steps, in order. With none, anyone with approval rights (except the person who submitted) can approve.</Typography>
              {steps.map((s, i) => (
                <Stack key={i} direction="row" spacing={1} sx={{ mb: 1 }} alignItems="center">
                  <Typography sx={{ width: 24 }}>{i + 1}.</Typography>
                  <TextField select size="small" label="Reviewer is" value={s.type} onChange={(e) => setStep(i, { type: e.target.value as Step["type"], ref: null })} sx={{ minWidth: 200 }}>
                    <MenuItem value="user">A named person</MenuItem>
                    <MenuItem value="role">Anyone holding a role</MenuItem>
                    <MenuItem value="department_manager">The department manager</MenuItem>
                  </TextField>
                  {s.type === "user" && (
                    <TextField select size="small" label="Person" value={s.ref ?? ""} onChange={(e) => setStep(i, { ref: e.target.value })} sx={{ minWidth: 220 }}>
                      {people.data?.map((p) => <MenuItem key={p.membership_id} value={p.membership_id}>{p.full_name ?? p.membership_id}</MenuItem>)}
                    </TextField>
                  )}
                  {s.type === "role" && (
                    <TextField select size="small" label="Role" value={s.ref ?? ""} onChange={(e) => setStep(i, { ref: e.target.value })} sx={{ minWidth: 220 }}>
                      {roles.data?.map((r) => <MenuItem key={r.id} value={r.id}>{r.name}</MenuItem>)}
                    </TextField>
                  )}
                  <IconButton aria-label="Remove step" onClick={() => setSteps(steps.filter((_, j) => j !== i))}><DeleteIcon /></IconButton>
                </Stack>
              ))}
              <Button size="small" disabled={steps.length >= 5} onClick={() => setSteps([...steps, { type: "role", ref: null }])}>Add a step</Button>
            </Box>
          )}
          <Box>
            <Typography variant="body2" color="text.secondary">People must link the document to:</Typography>
            {DIMENSIONS.map((d) => (
              <FormControlLabel key={d} control={<Checkbox checked={dims.includes(d)} onChange={(e) => setDims(e.target.checked ? [...dims, d] : dims.filter((x) => x !== d))} />} label={d} />
            ))}
          </Box>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
            <TextField label="Allowed file types (blank = all)" placeholder="pdf, docx, xlsx" value={ext} onChange={(e) => setExt(e.target.value)} sx={{ flex: 2 }} />
            <TextField label="Keep for (days)" type="number" value={retention} onChange={(e) => setRetention(e.target.value)} sx={{ flex: 1 }} />
            <TextField label="Review every (days)" type="number" value={review} onChange={(e) => setReview(e.target.value)} sx={{ flex: 1 }} />
            <TextField label="Remind before (days)" placeholder="30, 7" value={reminders} onChange={(e) => setReminders(e.target.value)} sx={{ flex: 1 }} />
          </Stack>
          <Typography variant="subtitle1" fontWeight={600}>Extra fields people fill in</Typography>
          {fields.map((f, i) => (
            <Stack key={i} direction={{ xs: "column", md: "row" }} spacing={1} alignItems={{ md: "center" }}>
              <TextField size="small" label="Key" placeholder="invoice_no" value={f.key} onChange={(e) => setField(i, { key: e.target.value })} sx={{ width: 150 }} />
              <TextField size="small" label="Label" value={f.label} onChange={(e) => setField(i, { label: e.target.value })} sx={{ flex: 1 }} />
              <TextField select size="small" label="Type" value={f.field_type} onChange={(e) => setField(i, { field_type: e.target.value })} sx={{ width: 190 }}>
                {FIELD_TYPES.map((t) => <MenuItem key={t} value={t}>{label(t)}</MenuItem>)}
              </TextField>
              {(f.field_type === "single_select" || f.field_type === "multi_select") && (
                <TextField size="small" label="Choices (comma separated)" value={f.options} onChange={(e) => setField(i, { options: e.target.value })} sx={{ flex: 1 }} />
              )}
              <FormControlLabel control={<Checkbox checked={f.required} onChange={(e) => setField(i, { required: e.target.checked })} />} label="Required" />
              <IconButton aria-label="Remove field" onClick={() => setFields(fields.filter((_, j) => j !== i))}><DeleteIcon /></IconButton>
            </Stack>
          ))}
          <Box><Button size="small" onClick={() => setFields([...fields, { key: "", label: "", field_type: "text", required: false, validation: {}, options: "" }])}>Add a field</Button></Box>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={save.isPending || (creating && !name.trim())} onClick={() => save.mutate()}>{creating ? "Create category" : "Publish new version"}</Button>
      </DialogActions>
    </Dialog>
  );
}

function EditCategory({ category, categories, onClose }: { category: Cat | null; categories: Cat[]; onClose: () => void }) {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [parent, setParent] = useState("");
  const [classification, setClassification] = useState("internal");
  const [active, setActive] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    if (category) {
      setName(category.name); setParent(category.parent_id ?? ""); setClassification(category.default_classification); setActive(category.status === "active"); setError("");
    }
  }, [category]);
  const save = useMutation({
    mutationFn: () => api(`/categories/${category!.id}`, { method: "PATCH", body: { name: name.trim(), parent_id: parent || null, default_classification: classification, status: active ? "active" : "inactive" } }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["categories-all"] });
      await client.invalidateQueries({ queryKey: ["categories"] });
      onClose();
    },
    onError: (e) => setError(errorText(e)),
  });
  return (
    <Dialog open={!!category} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Rename or move “{category?.name}”</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField label="Name" value={name} onChange={(e) => setName(e.target.value)} />
          <TextField select label="Inside" value={parent} onChange={(e) => setParent(e.target.value)}>
            <MenuItem value="">Top level</MenuItem>
            {categories.filter((c) => c.id !== category?.id && c.status === "active").map((c) => <MenuItem key={c.id} value={c.id}>{c.path}</MenuItem>)}
          </TextField>
          <TextField select label="Default classification" value={classification} onChange={(e) => setClassification(e.target.value)}>
            {CLASSIFICATIONS.map(([v, l]) => <MenuItem key={v} value={v}>{l}</MenuItem>)}
          </TextField>
          <FormControlLabel control={<Switch checked={active} onChange={(e) => setActive(e.target.checked)} />} label="In use (new documents can be filed here)" />
        </Stack>
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Cancel</Button><Button variant="contained" onClick={() => save.mutate()} disabled={!name.trim() || save.isPending}>Save</Button></DialogActions>
    </Dialog>
  );
}

function Tags() {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const tags = useQuery({ queryKey: ["tags-all"], queryFn: () => api<Tag[]>("/tags") });
  const policy = useQuery({ queryKey: ["tag-policy"], queryFn: () => api<{ allow_employee_tags: boolean }>("/tags/policy") });
  const refresh = () => client.invalidateQueries({ queryKey: ["tags-all"] });
  const add = useMutation({
    mutationFn: () => api("/tags", { body: { name: name.trim(), kind: "standard" } }),
    onSuccess: async () => { setName(""); setError(""); await refresh(); },
    onError: (e) => setError(errorText(e)),
  });
  const patch = useMutation({
    mutationFn: (v: { id: string; body: Record<string, string> }) => api(`/tags/${v.id}`, { method: "PATCH", body: v.body }),
    onSuccess: refresh,
    onError: (e) => setError(errorText(e)),
  });
  const setPolicy = useMutation({
    mutationFn: (on: boolean) => api("/tags/policy", { method: "PUT", body: { allow_employee_tags: on } }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["tag-policy"] }),
    onError: (e) => setError(errorText(e)),
  });
  return (
    <>
      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>{error}</Alert>}
      <Stack direction="row" spacing={2} sx={{ mb: 2 }} alignItems="center" flexWrap="wrap" useFlexGap>
        <TextField size="small" label="New standard tag" value={name} onChange={(e) => setName(e.target.value)} />
        <Button variant="contained" disabled={!name.trim() || add.isPending} onClick={() => add.mutate()}>Add tag</Button>
        {policy.data && <FormControlLabel control={<Switch checked={policy.data.allow_employee_tags} onChange={(e) => setPolicy.mutate(e.target.checked)} />} label="Let employees create their own tags" />}
      </Stack>
      <Paper>
        <Table size="small">
          <TableHead><TableRow><TableCell>Tag</TableCell><TableCell>Kind</TableCell><TableCell>Status</TableCell><TableCell align="right">Actions</TableCell></TableRow></TableHead>
          <TableBody>
            {tags.data?.map((t) => (
              <TableRow key={t.id}>
                <TableCell sx={{ fontWeight: 600 }}>{t.name}</TableCell>
                <TableCell>{label(t.kind)}</TableCell>
                <TableCell><Chip size="small" label={label(t.status)} color={t.status === "active" ? "success" : "default"} /></TableCell>
                <TableCell align="right">
                  {t.kind === "system" ? <Typography variant="caption" color="text.secondary">Built in</Typography> : (
                    <Button size="small" onClick={() => patch.mutate({ id: t.id, body: { status: t.status === "active" ? "inactive" : "active" } })}>{t.status === "active" ? "Turn off" : "Turn on"}</Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Paper>
    </>
  );
}

/** Categories (the rules for each kind of document) and tags. */
export default function Categories() {
  const [tab, setTab] = useState<"categories" | "tags">("categories");
  const [editor, setEditor] = useState<Cat | "new" | null>(null);
  const [rename, setRename] = useState<Cat | null>(null);
  const cats = useQuery({ queryKey: ["categories-all"], queryFn: () => api<Cat[]>("/categories") });
  return (
    <Box>
      <Stack direction="row" alignItems="center" sx={{ mb: 1 }}>
        <Typography variant="h5" sx={{ flex: 1 }}>Categories and tags</Typography>
        {tab === "categories" && <Button variant="contained" onClick={() => setEditor("new")}>New category</Button>}
      </Stack>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab value="categories" label="Categories" />
        <Tab value="tags" label="Tags" />
      </Tabs>
      {tab === "tags" && <Tags />}
      {tab === "categories" && (
        <Paper>
          {cats.error && <Alert severity="error">{errorText(cats.error)}</Alert>}
          <Table size="small">
            <TableHead><TableRow><TableCell>Category</TableCell><TableCell>Default classification</TableCell><TableCell>Rules version</TableCell><TableCell>Status</TableCell><TableCell align="right">Actions</TableCell></TableRow></TableHead>
            <TableBody>
              {cats.data?.map((c) => (
                <TableRow key={c.id}>
                  <TableCell sx={{ fontWeight: 600, pl: 2 + c.depth * 2 }}>{c.name}</TableCell>
                  <TableCell><Chip size="small" variant="outlined" color={classTone(c.default_classification)} label={label(c.default_classification)} /></TableCell>
                  <TableCell>v{c.current_version_number}</TableCell>
                  <TableCell><Chip size="small" label={label(c.status)} color={c.status === "active" ? "success" : "default"} /></TableCell>
                  <TableCell align="right">
                    <Button size="small" onClick={() => setEditor(c)}>Rules</Button>
                    <Button size="small" onClick={() => setRename(c)}>Rename or move</Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Paper>
      )}
      <CategoryEditor category={editor} categories={cats.data ?? []} onClose={() => setEditor(null)} />
      <EditCategory category={rename} categories={cats.data ?? []} onClose={() => setRename(null)} />
    </Box>
  );
}
