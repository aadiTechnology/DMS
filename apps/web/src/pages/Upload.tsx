import {
  Alert, Box, Button, LinearProgress, MenuItem, Paper, Stack, TextField, Typography,
} from "@mui/material";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import { api, errorText, getSession } from "../api";
import { CLASSIFICATIONS } from "../format";
import { useCategories, useOrg } from "../queries";

interface Field {
  key: string;
  label: string;
  field_type: string;
  required: boolean;
}
interface CategoryDetail {
  default_classification: string;
  version: { approval_required?: boolean; required_dimensions?: string[]; allowed_extensions?: string[] | null; fields: Field[] };
}

const ORDER = CLASSIFICATIONS.map(([v]) => v as string);

export default function Upload() {
  const client = useQueryClient();
  const categories = useCategories();
  const departments = useOrg("departments");
  const projects = useOrg("projects");
  const [categoryId, setCategoryId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [classification, setClassification] = useState("");
  const [department, setDepartment] = useState("");
  const [project, setProject] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<{ id: string; waiting: boolean } | null>(null);

  const detail = useQuery({
    queryKey: ["category", categoryId],
    queryFn: () => api<CategoryDetail>(`/categories/${categoryId}`),
    enabled: !!categoryId,
  });
  const policy = detail.data?.version;
  const effective = classification || detail.data?.default_classification || "internal";
  const needsDepartment = policy?.required_dimensions?.includes("department");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !detail.data) return;
    setBusy(true);
    setError("");
    setDone(null);
    try {
      const metadata: Record<string, unknown> = {};
      for (const f of detail.data.version.fields) {
        const v = values[f.key];
        if (v !== undefined && v !== "") metadata[f.key] = f.field_type === "number" ? Number(v) : v;
      }
      const associations: Record<string, string[]> = {};
      if (department) associations.department = [department];
      if (project) associations.project = [project];
      const reserved = await api<{ document_id: string; version_id: string }>("/documents/uploads", {
        body: {
          category_id: categoryId,
          filename: file.name,
          content_type: file.type || "application/octet-stream",
          size_bytes: file.size,
          title: title.trim() || undefined,
          classification: classification || undefined,
          associations,
          metadata,
        },
      });
      const sent = await fetch(`/api/v1/documents/uploads/${reserved.version_id}/content`, {
        method: "PUT",
        headers: { Authorization: `Bearer ${getSession()?.access}` },
        body: file,
      });
      if (!sent.ok) {
        const body = (await sent.json().catch(() => ({}))) as { detail?: unknown };
        throw new Error(errorText({ detail: body.detail ?? sent.statusText }));
      }
      const result = (await sent.json()) as { lifecycle_state: string };
      client.invalidateQueries({ queryKey: ["search"] });
      client.invalidateQueries({ queryKey: ["approvals"] });
      setDone({ id: reserved.document_id, waiting: result.lifecycle_state !== "approved" });
      setFile(null);
      setTitle("");
      setValues({});
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Box sx={{ maxWidth: 720 }}>
      <Typography variant="h5" sx={{ mb: 2 }}>Upload a document</Typography>
      <Paper sx={{ p: 3 }}>
        <form onSubmit={submit}>
          <Stack spacing={2}>
            {error && <Alert severity="error">{error}</Alert>}
            {done && (
              <Alert severity="success">
                Uploaded and scanned. {done.waiting ? "It is waiting for approval and is visible only to you and the reviewers until then. " : ""}
                <RouterLink to={`/documents/${done.id}`}>Open the document</RouterLink>
              </Alert>
            )}
            <TextField select required label="Category" value={categoryId} onChange={(e) => { setCategoryId(e.target.value); setValues({}); setClassification(""); }}>
              {categories.data?.map((c) => <MenuItem key={c.id} value={c.id}>{c.path}</MenuItem>)}
            </TextField>
            {policy?.approval_required && <Alert severity="info">Documents in this category are reviewed before they are released to readers.</Alert>}
            <Button variant="outlined" component="label">
              {file ? `${file.name} (${(file.size / 1024).toFixed(0)} KB)` : "Choose a file"}
              <input hidden type="file" aria-label="File" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </Button>
            {policy?.allowed_extensions?.length ? <Typography variant="caption" color="text.secondary">Allowed types: {policy.allowed_extensions.join(", ")}</Typography> : null}
            <TextField label="Title (defaults to the file name)" value={title} onChange={(e) => setTitle(e.target.value)} />
            <TextField select label="Classification" value={effective} onChange={(e) => setClassification(e.target.value)} helperText="Cannot be lower than the category default">
              {CLASSIFICATIONS.filter(([v]) => ORDER.indexOf(v) >= ORDER.indexOf(detail.data?.default_classification ?? "public")).map(([v, l]) => (
                <MenuItem key={v} value={v}>{l}</MenuItem>
              ))}
            </TextField>
            <TextField select required={!!needsDepartment} label="Department" value={department} onChange={(e) => setDepartment(e.target.value)}>
              <MenuItem value="">None</MenuItem>
              {departments.data?.map((d) => <MenuItem key={d.id} value={d.id}>{d.name}</MenuItem>)}
            </TextField>
            <TextField select label="Project" value={project} onChange={(e) => setProject(e.target.value)}>
              <MenuItem value="">None</MenuItem>
              {projects.data?.map((d) => <MenuItem key={d.id} value={d.id}>{d.name}</MenuItem>)}
            </TextField>
            {detail.data?.version.fields.map((f) => (
              <TextField
                key={f.key}
                label={f.label}
                required={f.required}
                type={f.field_type === "number" ? "number" : f.field_type === "date" ? "date" : "text"}
                slotProps={f.field_type === "date" ? { inputLabel: { shrink: true } } : undefined}
                value={values[f.key] ?? ""}
                onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}
              />
            ))}
            {busy && <LinearProgress />}
            <Button type="submit" variant="contained" size="large" disabled={busy || !file || !categoryId}>Upload</Button>
          </Stack>
        </form>
      </Paper>
    </Box>
  );
}
