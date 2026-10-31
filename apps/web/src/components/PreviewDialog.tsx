import { Alert, Box, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle } from "@mui/material";
import { useQuery } from "@tanstack/react-query";
import { api, errorText } from "../api";

interface Link {
  url: string;
  content_type: string | null;
  filename: string;
}

/** Shows a PDF or image inside the page using a short-lived link; other file types have no preview. */
export default function PreviewDialog({ documentId, version, open, onClose }: { documentId: string; version: number; open: boolean; onClose: () => void }) {
  const link = useQuery({
    queryKey: ["preview", documentId, version, open],
    queryFn: () => api<Link>(`/documents/${documentId}/versions/${version}/preview-url`),
    enabled: open,
    staleTime: 0,
    gcTime: 0,
  });
  const isImage = link.data?.content_type?.startsWith("image/");
  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="lg">
      <DialogTitle>{link.data?.filename ?? "Preview"}</DialogTitle>
      <DialogContent sx={{ height: "70vh", p: 0 }}>
        {link.isLoading && <Box sx={{ display: "grid", placeItems: "center", height: "100%" }}><CircularProgress /></Box>}
        {link.error && (
          <Alert severity="info" sx={{ m: 2 }}>
            {(link.error as { status?: number }).status === 415 ? "This file type has no preview. Download it to open it." : errorText(link.error)}
          </Alert>
        )}
        {link.data && (isImage ? (
          <Box component="img" src={link.data.url} alt={link.data.filename} sx={{ maxWidth: "100%", maxHeight: "100%", display: "block", mx: "auto" }} />
        ) : (
          <iframe title="Document preview" src={link.data.url} style={{ width: "100%", height: "100%", border: 0 }} />
        ))}
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Close</Button></DialogActions>
    </Dialog>
  );
}
