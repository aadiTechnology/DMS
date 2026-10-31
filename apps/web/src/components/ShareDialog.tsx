import {
  Alert, Autocomplete, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack, TextField, Typography,
} from "@mui/material";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, errorText } from "../api";
import { date } from "../format";

interface Person {
  membership_id: string;
  full_name: string;
  department: string | null;
}
interface Share {
  grantee_membership_id: string;
  grantee_name: string | null;
  can_download: boolean;
  expires_at: string | null;
}

/** Share a document with a colleague (view, or view and download, optionally until a date) and stop sharing. */
export default function ShareDialog({ documentId, title, open, onClose }: { documentId: string; title: string; open: boolean; onClose: () => void }) {
  const client = useQueryClient();
  const [text, setText] = useState("");
  const [search, setSearch] = useState("");
  const [person, setPerson] = useState<Person | null>(null);
  const [access, setAccess] = useState<"view" | "download">("view");
  const [until, setUntil] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const t = setTimeout(() => setSearch(text), 250);
    return () => clearTimeout(t);
  }, [text]);

  const people = useQuery({ queryKey: ["directory", search], queryFn: () => api<Person[]>("/directory", { params: { q: search } }), enabled: open });
  const shares = useQuery({ queryKey: ["doc", documentId, "shares"], queryFn: () => api<Share[]>(`/documents/${documentId}/shares`), enabled: open });

  const refresh = () => client.invalidateQueries({ queryKey: ["doc", documentId, "shares"] });
  const add = useMutation({
    mutationFn: () =>
      api(`/documents/${documentId}/shares`, {
        body: {
          grantee_membership_id: person!.membership_id,
          can_view: true,
          can_download: access === "download",
          expires_at: until ? new Date(`${until}T23:59:00`).toISOString() : undefined,
        },
      }),
    onSuccess: async () => {
      setPerson(null);
      setText("");
      setUntil("");
      setError("");
      await refresh();
    },
    onError: (e) => setError(errorText(e)),
  });
  const revoke = useMutation({
    mutationFn: (membershipId: string) => api(`/documents/${documentId}/shares/${membershipId}`, { method: "DELETE" }),
    onSuccess: refresh,
    onError: (e) => setError(errorText(e)),
  });

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Share “{title}”</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error" onClose={() => setError("")}>{error}</Alert>}
          <Autocomplete
            options={people.data ?? []}
            value={person}
            onChange={(_, v) => setPerson(v)}
            inputValue={text}
            onInputChange={(_, v) => setText(v)}
            getOptionLabel={(o) => o.full_name}
            getOptionKey={(o) => o.membership_id}
            isOptionEqualToValue={(a, b) => a.membership_id === b.membership_id}
            filterOptions={(x) => x}
            noOptionsText="No colleague matches"
            renderOption={(props, o) => (
              <li {...props} key={o.membership_id}>
                {o.full_name}
                {o.department && <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>{o.department}</Typography>}
              </li>
            )}
            renderInput={(params) => <TextField {...params} label="Colleague" placeholder="Start typing a name" />}
          />
          <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
            <TextField select label="Access" value={access} onChange={(e) => setAccess(e.target.value as "view" | "download")} sx={{ minWidth: 220 }}>
              <MenuItem value="view">View only</MenuItem>
              <MenuItem value="download">View and download</MenuItem>
            </TextField>
            <TextField type="date" label="Expires (optional)" value={until} onChange={(e) => setUntil(e.target.value)} slotProps={{ inputLabel: { shrink: true } }} />
            <Box sx={{ flex: 1 }} />
            <Button variant="contained" disabled={!person || add.isPending} onClick={() => add.mutate()}>Share</Button>
          </Stack>
          <Typography variant="body2" color="text.secondary">
            Sharing never gives more than the person’s role allows. You can stop sharing at any time, and it takes effect for every version at once.
          </Typography>
          <Typography variant="subtitle2">Shared with</Typography>
          {shares.data?.length === 0 && <Typography variant="body2" color="text.secondary">Not shared with anyone yet.</Typography>}
          {shares.data?.map((s) => (
            <Stack key={s.grantee_membership_id} direction="row" alignItems="center" spacing={1}>
              <Typography sx={{ flex: 1 }}>
                {s.grantee_name ?? "A colleague"} · {s.can_download ? "view and download" : "view only"}
                {s.expires_at ? ` · until ${date(s.expires_at)}` : ""}
              </Typography>
              <Button size="small" color="error" onClick={() => revoke.mutate(s.grantee_membership_id)} disabled={revoke.isPending}>Stop sharing</Button>
            </Stack>
          ))}
        </Stack>
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Close</Button></DialogActions>
    </Dialog>
  );
}
