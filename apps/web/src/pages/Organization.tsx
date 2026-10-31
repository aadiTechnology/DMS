import { Alert, Box, Button, Chip, Paper, Stack, Tab, Table, TableBody, TableCell, TableHead, TableRow, Tabs, Typography } from "@mui/material";
import { useState } from "react";
import { errorText } from "../api";
import { useCan } from "../App";
import { MembersDialog, OrgItemDialog, ProfileDialog, usePeople, type Kind, type Person } from "../components/OrgDialogs";
import { label } from "../format";
import { useOrg, type OrgItem } from "../queries";

type Tab_ = Kind | "employees";
const TABS: [Tab_, string][] = [
  ["departments", "Departments"],
  ["branches", "Branches"],
  ["projects", "Projects"],
  ["designations", "Designations"],
  ["employees", "Employees"],
];

function OrgTable({ kind, canEdit }: { kind: Kind; canEdit: boolean }) {
  const items = useOrg(kind);
  const people = usePeople(canEdit);
  const [editing, setEditing] = useState<OrgItem | "new" | null>(null);
  const [members, setMembers] = useState<OrgItem | null>(null);
  const manager = (id?: string | null) => (id ? (people.data?.find((p) => p.membership_id === id)?.full_name ?? "") : "");
  const showManager = kind === "departments" || kind === "projects";
  return (
    <>
      {canEdit && <Box sx={{ p: 1.5 }}><Button variant="contained" size="small" onClick={() => setEditing("new")}>Add</Button></Box>}
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Name</TableCell>
            <TableCell>Code</TableCell>
            {showManager && <TableCell>Manager</TableCell>}
            <TableCell>Status</TableCell>
            {canEdit && <TableCell align="right">Actions</TableCell>}
          </TableRow>
        </TableHead>
        <TableBody>
          {items.data?.map((i) => (
            <TableRow key={i.id}>
              <TableCell sx={{ fontWeight: 600 }}>{i.name}</TableCell>
              <TableCell>{i.code ?? "—"}</TableCell>
              {showManager && <TableCell>{manager(i.manager_membership_id) || "—"}</TableCell>}
              <TableCell><Chip size="small" label={label(i.status)} color={i.status === "active" ? "success" : "default"} /></TableCell>
              {canEdit && (
                <TableCell align="right">
                  <Button size="small" onClick={() => setEditing(i)}>Edit</Button>
                  {kind === "projects" && <Button size="small" onClick={() => setMembers(i)}>People</Button>}
                </TableCell>
              )}
            </TableRow>
          ))}
          {items.error && <TableRow><TableCell colSpan={5}><Alert severity="error">{errorText(items.error)}</Alert></TableCell></TableRow>}
        </TableBody>
      </Table>
      <OrgItemDialog kind={kind} item={editing === "new" ? null : editing} open={editing !== null} onClose={() => setEditing(null)} />
      <MembersDialog project={members} onClose={() => setMembers(null)} />
    </>
  );
}

function Employees() {
  const people = usePeople();
  const departments = useOrg("departments");
  const [editing, setEditing] = useState<Person | null>(null);
  const dept = (id: string | null) => departments.data?.find((d) => d.id === id)?.name ?? "—";
  return (
    <>
      <Table size="small">
        <TableHead>
          <TableRow><TableCell>Name</TableCell><TableCell>Department</TableCell><TableCell>Employment</TableCell><TableCell align="right">Actions</TableCell></TableRow>
        </TableHead>
        <TableBody>
          {people.data?.map((p) => (
            <TableRow key={p.membership_id}>
              <TableCell sx={{ fontWeight: 600 }}>{p.full_name ?? "—"}</TableCell>
              <TableCell>{dept(p.department_id)}</TableCell>
              <TableCell>{label(p.employment_status)}</TableCell>
              <TableCell align="right"><Button size="small" onClick={() => setEditing(p)}>Edit</Button></TableCell>
            </TableRow>
          ))}
          {people.error && <TableRow><TableCell colSpan={4}><Alert severity="error">{errorText(people.error)}</Alert></TableCell></TableRow>}
        </TableBody>
      </Table>
      <ProfileDialog person={editing} onClose={() => setEditing(null)} />
    </>
  );
}

/** The structure documents are filed against. Everyone can read it; administrators can change it. */
export default function Organization() {
  const [tab, setTab] = useState<Tab_>("departments");
  const canEdit = useCan("admin.manage_organization");
  return (
    <Box>
      <Stack direction="row" alignItems="baseline" spacing={2} sx={{ mb: 2 }}>
        <Typography variant="h5">Organization</Typography>
        {canEdit && <Typography variant="body2" color="text.secondary">Nothing is deleted; items are switched off and their history is kept.</Typography>}
      </Stack>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        {TABS.filter(([k]) => k !== "employees" || canEdit).map(([k, l]) => <Tab key={k} value={k} label={l} />)}
      </Tabs>
      <Paper>{tab === "employees" ? <Employees /> : <OrgTable kind={tab} canEdit={canEdit} />}</Paper>
    </Box>
  );
}
