import { TemplateThumbnail, validateTemplate, type UiTemplate } from "@aaditech/ui-engine";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import {
  Alert, Box, Button, Card, CardActions, CardContent, Chip, Stack, Typography,
} from "@mui/material";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, errorText } from "../api";
import { useCan } from "../App";
import { APPEARANCE_KEY, checkedPreview, useApplyDesign, usePreview } from "../appearance";

interface Card {
  id: string;
  key: string;
  name: string;
  description: string;
  version: string;
  is_selected: boolean;
  is_default: boolean;
}
interface Detail {
  config: unknown;
}
interface Preferences {
  selected_template_id: string | null;
  effective: { source: string; template: { key: string } | null };
}

export default function Appearance() {
  const client = useQueryClient();
  const { preview, start, stop } = usePreview();
  const canSetDefault = useCan("admin.manage_organization");
  const [message, setMessage] = useState("");
  const cards = useQuery({ queryKey: ["ui-available"], queryFn: () => api<Card[]>("/ui-templates/available") });
  const prefs = useQuery({ queryKey: APPEARANCE_KEY, queryFn: () => api<Preferences>("/me/ui-preferences") });
  const details = useQueries({
    queries: (cards.data ?? []).map((c) => ({ queryKey: ["ui-template", c.id, c.version], queryFn: () => api<Detail>(`/ui-templates/available/${c.id}`), staleTime: 300_000 })),
  });
  const configOf = (id: string): unknown => details[(cards.data ?? []).findIndex((c) => c.id === id)]?.data?.config;
  const thumb = (id: string): UiTemplate | null => {
    const result = validateTemplate(configOf(id));
    return result.valid ? result.template : null;
  };

  const apply = useApplyDesign(() => setMessage("Your design has been saved. It follows you to any device you sign in on."));
  const setDefault = useMutation({
    mutationFn: (id: string | null) => api("/ui-templates/tenant-default", { method: "PUT", body: { template_id: id } }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["ui-available"] });
      await client.invalidateQueries({ queryKey: APPEARANCE_KEY });
      setMessage("The organization default was updated. People who have not chosen their own design will see it.");
    },
    onError: (e) => setMessage(errorText(e)),
  });

  const effectiveKey = prefs.data?.effective.template?.key;
  const hasChoice = !!prefs.data?.selected_template_id;

  function previewOf(c: Card) {
    const checked = checkedPreview(configOf(c.id));
    if ("error" in checked) setMessage(checked.error);
    else start(c.id, checked.template);
  }

  return (
    <Box>
      <Stack direction="row" alignItems="center" spacing={2} sx={{ mb: 1 }} flexWrap="wrap">
        <Typography variant="h5">Choose your design</Typography>
        <Box sx={{ flexGrow: 1 }} />
        <Button onClick={() => apply.mutate(null)} disabled={!hasChoice || apply.isPending}>Reset to default</Button>
        {canSetDefault && <Button onClick={() => setDefault.mutate(null)} disabled={setDefault.isPending}>Clear organization default</Button>}
      </Stack>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        Pick how the application looks for you. Your choice affects only your own account; it does not change any data or what you are allowed to do.
      </Typography>
      {message && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setMessage("")}>{message}</Alert>}
      {(cards.error || apply.error) && <Alert severity="error" sx={{ mb: 2 }}>{errorText(cards.error ?? apply.error)}</Alert>}
      {cards.data?.length === 0 && <Alert severity="info">No designs are published yet. The built-in design is in use.</Alert>}
      <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))" }}>
        {cards.data?.map((c) => {
          const t = thumb(c.id);
          const selected = c.is_selected;
          const inUse = !hasChoice && effectiveKey === c.key;
          return (
            <Card key={c.id} variant="outlined" data-testid={`design-${c.key}`} sx={selected ? { outline: 2, outlineStyle: "solid", outlineColor: "primary.main" } : undefined}>
              <CardContent>
                <Box sx={{ display: "flex", justifyContent: "center", mb: 1.5 }}>{t ? <TemplateThumbnail template={t} width={220} /> : <Box sx={{ height: 136 }} />}</Box>
                <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }} flexWrap="wrap">
                  <Typography fontWeight={700}>{c.name}</Typography>
                  {selected && <Chip size="small" color="primary" icon={<CheckCircleIcon />} label="Selected" />}
                  {inUse && <Chip size="small" label="In use (default)" />}
                  {c.is_default && <Chip size="small" variant="outlined" label="Organization default" />}
                  {preview?.id === c.id && <Chip size="small" color="info" label="Previewing" />}
                </Stack>
                <Typography variant="body2" color="text.secondary">{c.description}</Typography>
              </CardContent>
              <CardActions sx={{ px: 2, pb: 2, flexWrap: "wrap" }}>
                {preview?.id === c.id ? (
                  <Button size="small" onClick={stop}>Stop previewing</Button>
                ) : (
                  <Button size="small" onClick={() => previewOf(c)} disabled={!t}>Preview</Button>
                )}
                <Button size="small" variant="contained" onClick={() => apply.mutate(c.id)} disabled={selected || apply.isPending}>{selected ? "Selected" : "Select"}</Button>
                {canSetDefault && !c.is_default && <Button size="small" onClick={() => setDefault.mutate(c.id)} disabled={setDefault.isPending}>Make organization default</Button>}
              </CardActions>
            </Card>
          );
        })}
      </Box>
    </Box>
  );
}
