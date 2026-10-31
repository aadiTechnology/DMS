import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, TextField } from "@mui/material";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, errorText } from "../api";

interface Field {
  key: string;
  label: string;
  field_type: string;
  required: boolean;
}

export interface Editable {
  id: string;
  title: string;
  category_id: string;
  category_version_number: number;
  row_version: number;
  metadata: Record<string, unknown>;
}

/** Change the title and extra fields. `row_version` makes sure nobody else's change is overwritten. */
export default function EditDetailsDialog({ doc, open, onClose }: { doc: Editable; open: boolean; onClose: () => void }) {
  const client = useQueryClient();
  const [title, setTitle] = useState(doc.title);
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState("");

  const category = useQuery({
    queryKey: ["category", doc.category_id, doc.category_version_number],
    queryFn: () => api<{ version: { fields: Field[] } }>(`/categories/${doc.category_id}`, { params: { version: doc.category_version_number } }),
    enabled: open,
  });
  useEffect(() => {
    if (open) {
      setTitle(doc.title);
      setValues(Object.fromEntries(Object.entries(doc.metadata ?? {}).map(([k, v]) => [k, String(v)])));
      setError("");
    }
  }, [open, doc.title, doc.metadata]);

  const save = useMutation({
    mutationFn: () => {
      const metadata: Record<string, unknown> = {};
      for (const f of category.data?.version.fields ?? []) {
        const v = (values[f.key] ?? "").trim();
        const before = doc.metadata?.[f.key];
        if (v === "" && before !== undefined) metadata[f.key] = null;
        else if (v !== "" && String(before ?? "") !== v) metadata[f.key] = f.field_type === "number" ? Number(v) : v;
      }
      return api(`/documents/${doc.id}`, { method: "PATCH", body: { row_version: doc.row_version, title: title.trim(), metadata } });
    },
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["doc", doc.id] });
      await client.invalidateQueries({ queryKey: ["search"] });
      onClose();
    },
    onError: (e) => setError(errorText(e)),
  });

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Edit details</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField label="Title" value={title} onChange={(e) => setTitle(e.target.value)} inputProps={{ maxLength: 300 }} required />
          {category.data?.version.fields.map((f) => (
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
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!title.trim() || save.isPending} onClick={() => save.mutate()}>Save changes</Button>
      </DialogActions>
    </Dialog>
  );
}
