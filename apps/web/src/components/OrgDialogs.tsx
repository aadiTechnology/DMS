import {
  Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Stack, Switch, TextField, Typography,
} from "@mui/material";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, errorText } from "../api";
import { date } from "../format";
import { useOrg, type OrgItem } from "../queries";

export type Kind = "departments" | "branches" | "projects" | "designations";
export interface Person {
  membership_id: string;
  full_name: string | null;
  department_id: string | null;
  branch_id: string | null;
  designation_id: string | null;
  employment_status: string | null;
}

const SINGULAR: Record<Kind, string> = { departments: "department", branches: "branch", projects: "project", designations: "designation" };

export function usePeople(enabled = true) {
  return useQuery({ queryKey: ["employees"], queryFn: () => api<Person[]>("/employees", { params: { limit: 200 } }), enabled });
}

/** Create or edit a department, branch, project or designation. Nothing here is ever deleted; items are switched off instead. */
export function OrgItemDialog({ kind, item, open, onClose }: { kind: Kind; item: OrgItem | null; open: boolean; onClose: () => void }) {
  const client = useQueryClient();
  const people = usePeople();
  const departments = useOrg("departments");
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [parent, setParent] = useState("");
  const [manager, setManager] = useState("");
  const [active, setActive] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    if (open) {
      setName(item?.name ?? ""); setCode(item?.code ?? ""); setParent((item as { parent_id?: string | null } | null)?.parent_id ?? ""); setManager(item?.manager_membership_id ?? ""); setActive(item ? item.status === "active" : true); setError("");
    }
  }, [open, item]);
  const hasCode = kind !== "designations";
  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = { name: name.trim() };
      if (hasCode) body.code = code.trim() || null;
      if (kind === "departments") body.parent_id = parent || null;
      if (kind === "departments" || kind === "projects") body.manager_membership_id = manager || null;
      if (item) return api(`/org/${kind}/${item.id}`, { method: "PATCH", body: { ...body, status: active ? "active" : "inactive" } });
      if (!body.code) delete body.code;
      return api(`/org/${kind}`, { body });
    },
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["org", kind] });
      onClose();
    },
    onError: (e) => setError(errorText(e)),
  });
  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{item ? `Edit ${item.name}` : `New ${SINGULAR[kind]}`}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField label="Name" value={name} onChange={(e) => setName(e.target.value)} required />
          {hasCode && <TextField label="Short code" value={code} onChange={(e) => setCode(e.target.value)} />}
          {kind === "departments" && (
            <TextField select label="Part of" value={parent} onChange={(e) => setParent(e.target.value)}>
              <MenuItem value="">Top level</MenuItem>
              {departments.data?.filter((d) => d.id !== item?.id && d.status === "active").map((d) => <MenuItem key={d.id} value={d.id}>{d.name}</MenuItem>)}
            </TextField>
          )}
          {(kind === "departments" || kind === "projects") && (
            <TextField select label="Manager" value={manager} onChange={(e) => setManager(e.target.value)} helperText="Managers see their department or project documents and can be a review step.">
              <MenuItem value="">None</MenuItem>
              {people.data?.map((p) => <MenuItem key={p.membership_id} value={p.membership_id}>{p.full_name ?? p.membership_id}</MenuItem>)}
            </TextField>
          )}
          {item && <FormControlLabel control={<Switch checked={active} onChange={(e) => setActive(e.target.checked)} />} label="In use (history is always kept)" />}
        </Stack>
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Cancel</Button><Button variant="contained" disabled={!name.trim() || save.isPending} onClick={() => save.mutate()}>Save</Button></DialogActions>
    </Dialog>
  );
}

interface Member {
  membership_id: string;
  project_role: string;
  starts_on: string;
  ends_on: string | null;
}

/** Who works on a project. Ending a membership keeps its history. */
export function MembersDialog({ project, onClose }: { project: OrgItem | null; onClose: () => void }) {
  const client = useQueryClient();
  const people = usePeople();
  const [person, setPerson] = useState("");
  const [role, setRole] = useState("member");
  const [error, setError] = useState("");
  const members = useQuery({ queryKey: ["project-members", project?.id], queryFn: () => api<Member[]>(`/projects/${project!.id}/members`), enabled: !!project });
  const refresh = () => client.invalidateQueries({ queryKey: ["project-members", project?.id] });
  const add = useMutation({
    mutationFn: () => api(`/projects/${project!.id}/members/${person}`, { method: "PUT", body: { project_role: role.trim() || "member" } }),
    onSuccess: async () => { setPerson(""); setError(""); await refresh(); },
    onError: (e) => setError(errorText(e)),
  });
  const end = useMutation({
    mutationFn: (id: string) => api(`/projects/${project!.id}/members/${id}`, { method: "DELETE" }),
    onSuccess: refresh,
    onError: (e) => setError(errorText(e)),
  });
  const name = (id: string) => people.data?.find((p) => p.membership_id === id)?.full_name ?? id;
  const current = members.data?.filter((m) => !m.ends_on || m.ends_on >= new Date().toISOString().slice(0, 10)) ?? [];
  return (
    <Dialog open={!!project} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>People on {project?.name}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error" onClose={() => setError("")}>{error}</Alert>}
          <Stack direction="row" spacing={1}>
            <TextField select size="small" label="Add a person" value={person} onChange={(e) => setPerson(e.target.value)} sx={{ flex: 2 }}>
              {people.data?.filter((p) => !current.some((m) => m.membership_id === p.membership_id)).map((p) => <MenuItem key={p.membership_id} value={p.membership_id}>{p.full_name ?? p.membership_id}</MenuItem>)}
            </TextField>
            <TextField size="small" label="Role on the project" value={role} onChange={(e) => setRole(e.target.value)} sx={{ flex: 1 }} />
            <Button variant="contained" disabled={!person || add.isPending} onClick={() => add.mutate()}>Add</Button>
          </Stack>
          {current.length === 0 && <Typography color="text.secondary" variant="body2">No one is on this project yet.</Typography>}
          {current.map((m) => (
            <Stack key={m.membership_id} direction="row" alignItems="center" spacing={1}>
              <Typography sx={{ flex: 1 }}>{name(m.membership_id)} · {m.project_role} · since {date(m.starts_on)}{m.ends_on ? ` · ends ${date(m.ends_on)}` : ""}</Typography>
              {!m.ends_on && <Button size="small" color="error" onClick={() => end.mutate(m.membership_id)}>End today</Button>}
            </Stack>
          ))}
        </Stack>
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Close</Button></DialogActions>
    </Dialog>
  );
}

/** Where a person sits in the organization (department, branch, designation) and whether they are still employed. */
export function ProfileDialog({ person, onClose }: { person: Person | null; onClose: () => void }) {
  const client = useQueryClient();
  const departments = useOrg("departments");
  const branches = useOrg("branches");
  const designations = useOrg("designations");
  const [fullName, setFullName] = useState("");
  const [dept, setDept] = useState("");
  const [branch, setBranch] = useState("");
  const [desig, setDesig] = useState("");
  const [status, setStatus] = useState("active");
  const [error, setError] = useState("");
  useEffect(() => {
    if (person) {
      setFullName(person.full_name ?? ""); setDept(person.department_id ?? ""); setBranch(person.branch_id ?? ""); setDesig(person.designation_id ?? ""); setStatus(person.employment_status ?? "active"); setError("");
    }
  }, [person]);
  const save = useMutation({
    mutationFn: () => api(`/employees/${person!.membership_id}/profile`, { method: "PUT", body: { full_name: fullName.trim(), department_id: dept || null, branch_id: branch || null, designation_id: desig || null, employment_status: status } }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["employees"] });
      onClose();
    },
    onError: (e) => setError(errorText(e)),
  });
  const pick = (label: string, value: string, set: (v: string) => void, items?: OrgItem[]) => (
    <TextField select label={label} value={value} onChange={(e) => set(e.target.value)}>
      <MenuItem value="">None</MenuItem>
      {items?.filter((i) => i.status === "active").map((i) => <MenuItem key={i.id} value={i.id}>{i.name}</MenuItem>)}
    </TextField>
  );
  return (
    <Dialog open={!!person} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Employee details</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField label="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} required />
          {pick("Department", dept, setDept, departments.data)}
          {pick("Branch", branch, setBranch, branches.data)}
          {pick("Designation", desig, setDesig, designations.data)}
          <TextField select label="Employment" value={status} onChange={(e) => setStatus(e.target.value)} helperText="Someone who has left keeps their history but loses department-based access.">
            <MenuItem value="active">Active</MenuItem>
            <MenuItem value="on_leave">On leave</MenuItem>
            <MenuItem value="exited">Has left</MenuItem>
          </TextField>
        </Stack>
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Cancel</Button><Button variant="contained" disabled={!fullName.trim() || save.isPending} onClick={() => save.mutate()}>Save</Button></DialogActions>
    </Dialog>
  );
}
