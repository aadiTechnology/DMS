import { Alert, Box, Chip, Paper, Tab, Table, TableBody, TableCell, TableHead, TableRow, Tabs, Typography } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, errorText } from "../api";
import { useCan } from "../App";
import { label } from "../format";
import { useOrg } from "../queries";

type Kind = "departments" | "branches" | "projects" | "designations" | "employees";
const TABS: [Kind, string][] = [
  ["departments", "Departments"],
  ["branches", "Branches"],
  ["projects", "Projects"],
  ["designations", "Designations"],
  ["employees", "Employees"],
];

interface Employee {
  membership_id: string;
  full_name: string | null;
  work_email: string | null;
  employment_status: string | null;
  membership_status: string;
}

function OrgTable({ kind }: { kind: Exclude<Kind, "employees"> }) {
  const items = useOrg(kind);
  return (
    <Table size="small">
      <TableHead>
        <TableRow><TableCell>Name</TableCell><TableCell>Code</TableCell><TableCell>Status</TableCell></TableRow>
      </TableHead>
      <TableBody>
        {items.data?.map((i) => (
          <TableRow key={i.id}>
            <TableCell sx={{ fontWeight: 600 }}>{i.name}</TableCell>
            <TableCell>{i.code ?? "—"}</TableCell>
            <TableCell><Chip size="small" label={label(i.status)} color={i.status === "active" ? "success" : "default"} /></TableCell>
          </TableRow>
        ))}
        {items.error && <TableRow><TableCell colSpan={3}><Alert severity="error">{errorText(items.error)}</Alert></TableCell></TableRow>}
      </TableBody>
    </Table>
  );
}

function Employees() {
  const people = useQuery({ queryKey: ["employees"], queryFn: () => api<Employee[]>("/employees", { params: { limit: 200 } }) });
  return (
    <Table size="small">
      <TableHead>
        <TableRow><TableCell>Name</TableCell><TableCell>Employment</TableCell><TableCell>Account</TableCell></TableRow>
      </TableHead>
      <TableBody>
        {people.data?.map((p) => (
          <TableRow key={p.membership_id}>
            <TableCell sx={{ fontWeight: 600 }}>{p.full_name ?? "—"}</TableCell>
            <TableCell>{label(p.employment_status)}</TableCell>
            <TableCell>{label(p.membership_status)}</TableCell>
          </TableRow>
        ))}
        {people.error && <TableRow><TableCell colSpan={3}><Alert severity="error">{errorText(people.error)}</Alert></TableCell></TableRow>}
      </TableBody>
    </Table>
  );
}

export default function Organization() {
  const [tab, setTab] = useState<Kind>("departments");
  const canSeePeople = useCan("admin.manage_organization");
  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 2 }}>Organization</Typography>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        {TABS.filter(([k]) => k !== "employees" || canSeePeople).map(([k, l]) => <Tab key={k} value={k} label={l} />)}
      </Tabs>
      <Paper>{tab === "employees" ? <Employees /> : <OrgTable kind={tab} />}</Paper>
    </Box>
  );
}
