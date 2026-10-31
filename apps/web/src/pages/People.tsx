import {
  Alert, Box, Button, Checkbox, Chip, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Paper, Stack,
  Switch, Tab, Table, TableBody, TableCell, TableHead, TableRow, Tabs, TextField, Typography,
} from "@mui/material";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, errorText } from "../api";
import { useCan } from "../App";
import ReasonDialog from "../components/ReasonDialog";
import { dateTime, label } from "../format";

interface Employee {
  membership_id: string;
  membership_status: string;
  full_name: string | null;
  work_email: string | null;
  joined_at: string;
}
interface Role {
  id: string;
  name: string;
  description: string | null;
  status: string;
}
interface Assignment {
  id: string;
  membership_id: string;
  role_id: string;
}
interface JoinRequest {
  id: string;
  email: string;
  full_name: string;
  created_at: string;
}

const LIST = { limit: 200 };

function InviteDialog({ open, roles, onClose }: { open: boolean; roles: Role[]; onClose: () => void }) {
  const client = useQueryClient();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [error, setError] = useState("");
  const send = useMutation({
    mutationFn: () => api("/invitations", { body: { email: email.trim(), full_name: name.trim(), role_id: role || undefined } }),
    onSuccess: async () => {
      setEmail("");
      setName("");
      setRole("");
      setError("");
      await client.invalidateQueries({ queryKey: ["invitations"] });
      await client.invalidateQueries({ queryKey: ["employees"] });
      onClose();
    },
    onError: (e) => setError(errorText(e)),
  });
  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Invite someone</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <Typography variant="body2" color="text.secondary">They get a single-use link by email to set a password and join your organization. With no role chosen they join as an employee.</Typography>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField label="Work email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          <TextField label="Full name" value={name} onChange={(e) => setName(e.target.value)} required />
          <TextField select label="Role" value={role} onChange={(e) => setRole(e.target.value)}>
            <MenuItem value="">Employee (default)</MenuItem>
            {roles.filter((r) => r.status === "active").map((r) => <MenuItem key={r.id} value={r.id}>{r.name}</MenuItem>)}
          </TextField>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!email.trim() || !name.trim() || send.isPending} onClick={() => send.mutate()}>Send invitation</Button>
      </DialogActions>
    </Dialog>
  );
}

function RolesDialog({ person, roles, assignments, onClose }: { person: Employee | null; roles: Role[]; assignments: Assignment[]; onClose: () => void }) {
  const client = useQueryClient();
  const [error, setError] = useState("");
  const mine = assignments.filter((a) => a.membership_id === person?.membership_id);
  const refresh = () => client.invalidateQueries({ queryKey: ["assignments"] });
  const add = useMutation({
    mutationFn: (roleId: string) => api("/role-assignments", { body: { membership_id: person!.membership_id, role_id: roleId } }),
    onSuccess: refresh,
    onError: (e) => setError(errorText(e)),
  });
  const remove = useMutation({
    mutationFn: (assignmentId: string) => api(`/role-assignments/${assignmentId}`, { method: "DELETE" }),
    onSuccess: refresh,
    onError: (e) => setError(errorText(e)),
  });
  return (
    <Dialog open={!!person} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Roles for {person?.full_name ?? "this person"}</DialogTitle>
      <DialogContent>
        {error && <Alert severity="error" sx={{ mb: 1 }} onClose={() => setError("")}>{error}</Alert>}
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>Roles decide which actions a person may attempt. Which documents they can open is decided separately. Changes apply immediately.</Typography>
        {roles.filter((r) => r.status === "active").map((r) => {
          const held = mine.find((a) => a.role_id === r.id);
          return (
            <Box key={r.id}>
              <FormControlLabel
                control={<Checkbox checked={!!held} onChange={() => (held ? remove.mutate(held.id) : add.mutate(r.id))} disabled={add.isPending || remove.isPending} />}
                label={<><b>{r.name}</b>{r.description ? <Typography component="span" variant="body2" color="text.secondary"> · {r.description}</Typography> : null}</>}
              />
            </Box>
          );
        })}
      </DialogContent>
      <DialogActions><Button onClick={() => { setError(""); onClose(); }}>Close</Button></DialogActions>
    </Dialog>
  );
}

/** People administration: who is in the organization and what roles they hold, invitations and join requests. */
export default function People() {
  const client = useQueryClient();
  const canOrg = useCan("admin.manage_organization");
  const [tab, setTab] = useState<"people" | "invitations" | "requests">("people");
  const [invite, setInvite] = useState(false);
  const [rolesFor, setRolesFor] = useState<Employee | null>(null);
  const [resetFor, setResetFor] = useState<Employee | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const employees = useQuery({ queryKey: ["employees"], queryFn: () => api<Employee[]>("/employees", { params: LIST }), enabled: canOrg });
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => api<Role[]>("/roles") });
  const assignments = useQuery({ queryKey: ["assignments"], queryFn: () => api<Assignment[]>("/role-assignments") });
  const invitations = useQuery({ queryKey: ["invitations"], queryFn: () => api<Employee[]>("/invitations") });
  const requests = useQuery({ queryKey: ["join-requests"], queryFn: () => api<JoinRequest[]>("/registration-requests", { params: { status: "pending" } }) });
  const settings = useQuery({ queryKey: ["tenant-settings"], queryFn: () => api<{ self_registration_enabled: boolean }>("/tenant/settings"), enabled: canOrg });

  const roleName = (id: string) => roles.data?.find((r) => r.id === id)?.name ?? "role";
  const rolesOf = (membershipId: string) => (assignments.data ?? []).filter((a) => a.membership_id === membershipId);

  const fail = (e: unknown) => setError(errorText(e));
  const resend = useMutation({
    mutationFn: (id: string) => api(`/invitations/${id}/resend`, { method: "POST" }),
    onSuccess: () => setMessage("The invitation was sent again; the earlier link no longer works."),
    onError: fail,
  });
  const revoke = useMutation({
    mutationFn: (id: string) => api(`/invitations/${id}`, { method: "DELETE" }),
    onSuccess: async () => {
      setMessage("The invitation was withdrawn.");
      await client.invalidateQueries({ queryKey: ["invitations"] });
    },
    onError: fail,
  });
  const decide = useMutation({
    mutationFn: (v: { id: string; action: "approve" | "reject" }) => api(`/registration-requests/${v.id}/${v.action}`, { method: "POST" }),
    onSuccess: async (_d, v) => {
      setMessage(v.action === "approve" ? "Approved. An invitation was sent." : "The request was rejected.");
      await client.invalidateQueries({ queryKey: ["join-requests"] });
      await client.invalidateQueries({ queryKey: ["invitations"] });
    },
    onError: fail,
  });
  const toggle = useMutation({
    mutationFn: (on: boolean) => api("/tenant/settings", { method: "PATCH", body: { self_registration_enabled: on } }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["tenant-settings"] }),
    onError: fail,
  });

  return (
    <Box>
      <Stack direction="row" alignItems="center" sx={{ mb: 1 }} spacing={2}>
        <Typography variant="h5">People</Typography>
        <Box sx={{ flex: 1 }} />
        <Button variant="contained" onClick={() => setInvite(true)}>Invite someone</Button>
      </Stack>
      {message && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setMessage("")}>{message}</Alert>}
      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError("")}>{error}</Alert>}
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab value="people" label="Employees" />
        <Tab value="invitations" label={`Invitations${invitations.data?.length ? ` (${invitations.data.length})` : ""}`} />
        <Tab value="requests" label={`Join requests${requests.data?.length ? ` (${requests.data.length})` : ""}`} />
      </Tabs>

      {tab === "people" && (
        <Paper>
          <Table size="small">
            <TableHead><TableRow><TableCell>Name</TableCell><TableCell>Status</TableCell><TableCell>Roles</TableCell><TableCell align="right">Actions</TableCell></TableRow></TableHead>
            <TableBody>
              {employees.data?.filter((p) => p.membership_status !== "invited").map((p) => (
                <TableRow key={p.membership_id}>
                  <TableCell sx={{ fontWeight: 600 }}>{p.full_name ?? "—"}</TableCell>
                  <TableCell><Chip size="small" label={label(p.membership_status)} color={p.membership_status === "active" ? "success" : "default"} /></TableCell>
                  <TableCell>{rolesOf(p.membership_id).map((a) => <Chip key={a.id} size="small" variant="outlined" label={roleName(a.role_id)} sx={{ mr: 0.5 }} />)}</TableCell>
                  <TableCell align="right">
                    <Button size="small" onClick={() => setRolesFor(p)}>Roles</Button>
                    <Button size="small" onClick={() => setResetFor(p)}>Reset two-step</Button>
                  </TableCell>
                </TableRow>
              ))}
              {employees.error && <TableRow><TableCell colSpan={4}><Alert severity="error">{errorText(employees.error)}</Alert></TableCell></TableRow>}
            </TableBody>
          </Table>
        </Paper>
      )}

      {tab === "invitations" && (
        <Paper>
          <Table size="small">
            <TableHead><TableRow><TableCell>Name</TableCell><TableCell>Email</TableCell><TableCell>Invited</TableCell><TableCell align="right">Actions</TableCell></TableRow></TableHead>
            <TableBody>
              {invitations.data?.map((p) => (
                <TableRow key={p.membership_id}>
                  <TableCell sx={{ fontWeight: 600 }}>{p.full_name ?? "—"}</TableCell>
                  <TableCell>{p.work_email ?? "—"}</TableCell>
                  <TableCell>{dateTime(p.joined_at)}</TableCell>
                  <TableCell align="right">
                    <Button size="small" onClick={() => resend.mutate(p.membership_id)}>Resend</Button>
                    <Button size="small" color="error" onClick={() => revoke.mutate(p.membership_id)}>Withdraw</Button>
                  </TableCell>
                </TableRow>
              ))}
              {invitations.data?.length === 0 && <TableRow><TableCell colSpan={4} align="center" sx={{ py: 4, color: "text.secondary" }}>No invitations are waiting to be accepted.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </Paper>
      )}

      {tab === "requests" && (
        <>
          {canOrg && settings.data && (
            <FormControlLabel
              sx={{ mb: 1 }}
              control={<Switch checked={settings.data.self_registration_enabled} onChange={(e) => toggle.mutate(e.target.checked)} />}
              label="Let people ask to join (requests wait here for approval)"
            />
          )}
          <Paper>
            <Table size="small">
              <TableHead><TableRow><TableCell>Name</TableCell><TableCell>Email</TableCell><TableCell>Asked</TableCell><TableCell align="right">Decision</TableCell></TableRow></TableHead>
              <TableBody>
                {requests.data?.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell sx={{ fontWeight: 600 }}>{r.full_name}</TableCell>
                    <TableCell>{r.email}</TableCell>
                    <TableCell>{dateTime(r.created_at)}</TableCell>
                    <TableCell align="right">
                      <Button size="small" onClick={() => decide.mutate({ id: r.id, action: "approve" })}>Approve and invite</Button>
                      <Button size="small" color="error" onClick={() => decide.mutate({ id: r.id, action: "reject" })}>Reject</Button>
                    </TableCell>
                  </TableRow>
                ))}
                {requests.data?.length === 0 && <TableRow><TableCell colSpan={4} align="center" sx={{ py: 4, color: "text.secondary" }}>No one is waiting to join.</TableCell></TableRow>}
              </TableBody>
            </Table>
          </Paper>
        </>
      )}

      <InviteDialog open={invite} roles={roles.data ?? []} onClose={() => setInvite(false)} />
      <RolesDialog person={rolesFor} roles={roles.data ?? []} assignments={assignments.data ?? []} onClose={() => setRolesFor(null)} />
      <ReasonDialog
        open={!!resetFor}
        title={`Reset two-step verification for ${resetFor?.full_name ?? "this person"}`}
        description="Use this when someone has lost their device. Their authenticator and recovery codes stop working, and they sign in with just a password until they set it up again. This is recorded as a privileged action."
        required={false}
        label="Note"
        confirmLabel="Reset two-step verification"
        danger
        onSubmit={async () => {
          await api(`/employees/${resetFor!.membership_id}/mfa/reset`, { method: "POST" });
          setMessage("Two-step verification was reset.");
        }}
        onClose={() => setResetFor(null)}
      />
    </Box>
  );
}
