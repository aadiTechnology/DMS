import { Box, Chip, Paper, Stack, Typography } from "@mui/material";
import { getSession } from "../api";
import { usePermissions } from "../App";
import { ChangePasswordCard, TwoStepCard } from "../components/SecurityCards";

export default function Account() {
  const permissions = [...usePermissions()].sort();
  const groups = new Map<string, string[]>();
  for (const p of permissions) {
    const [area = "", action = ""] = p.split(".");
    groups.set(area, [...(groups.get(area) ?? []), action]);
  }
  return (
    <Box sx={{ maxWidth: 760 }}>
      <Typography variant="h5" sx={{ mb: 2 }}>Account</Typography>
      <Paper sx={{ p: 3, mb: 2 }}>
        <Typography color="text.secondary" variant="body2">Signed in as</Typography>
        <Typography variant="h6">{getSession()?.email}</Typography>
      </Paper>
      <ChangePasswordCard />
      <TwoStepCard />
      <Paper sx={{ p: 3 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 600 }} gutterBottom>What your roles allow</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          These are the actions your roles permit. Access to each individual document also depends on its classification, ownership and sharing.
        </Typography>
        <Stack spacing={1.5}>
          {[...groups].map(([area, actions]) => (
            <Box key={area}>
              <Typography variant="body2" sx={{ fontWeight: 600, textTransform: "capitalize" }}>{area}</Typography>
              <Stack direction="row" gap={0.5} flexWrap="wrap">
                {actions.map((a) => <Chip key={a} size="small" label={a.replace(/_/g, " ")} />)}
              </Stack>
            </Box>
          ))}
        </Stack>
      </Paper>
    </Box>
  );
}
