import { Alert, Box, Chip, Paper, Tab, Table, TableBody, TableCell, TableHead, TableRow, Tabs, Typography } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import { api, errorText } from "../api";
import { classTone, dateTime, label } from "../format";

interface Share {
  document_id: string;
  title: string;
  classification: string;
  can_view: boolean;
  can_download: boolean;
  expires_at: string | null;
  created_at: string;
}

export default function Shared() {
  const [tab, setTab] = useState<"with-me" | "by-me">("with-me");
  const shares = useQuery({ queryKey: ["shares", tab], queryFn: () => api<Share[]>(`/shares/${tab}`) });
  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 2 }}>
        Shared documents
      </Typography>
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab value="with-me" label="Shared with me" />
        <Tab value="by-me" label="Shared by me" />
      </Tabs>
      {shares.error && <Alert severity="error">{errorText(shares.error)}</Alert>}
      <Paper>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Document</TableCell>
              <TableCell>Classification</TableCell>
              <TableCell>Access</TableCell>
              <TableCell>Shared on</TableCell>
              <TableCell>Expires</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {shares.data?.map((s) => (
              <TableRow key={`${s.document_id}${s.created_at}`} hover>
                <TableCell>
                  <Typography component={RouterLink} to={`/documents/${s.document_id}`} color="primary" sx={{ fontWeight: 600, textDecoration: "none" }}>
                    {s.title}
                  </Typography>
                </TableCell>
                <TableCell><Chip size="small" variant="outlined" color={classTone(s.classification)} label={label(s.classification)} /></TableCell>
                <TableCell>{s.can_download ? "View and download" : "View only"}</TableCell>
                <TableCell>{dateTime(s.created_at)}</TableCell>
                <TableCell>{s.expires_at ? dateTime(s.expires_at) : "No expiry"}</TableCell>
              </TableRow>
            ))}
            {shares.data?.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} align="center" sx={{ py: 4, color: "text.secondary" }}>
                  {tab === "with-me" ? "Nothing has been shared with you." : "You have not shared any documents."}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Paper>
    </Box>
  );
}
