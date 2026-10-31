import { LayoutRenderer, type NavItem } from "@aaditech/ui-engine";
import AccountCircle from "@mui/icons-material/AccountCircle";
import ApartmentIcon from "@mui/icons-material/Apartment";
import ArticleIcon from "@mui/icons-material/Article";
import FactCheckIcon from "@mui/icons-material/FactCheck";
import BrushIcon from "@mui/icons-material/Brush";
import FolderIcon from "@mui/icons-material/Folder";
import EventNoteIcon from "@mui/icons-material/EventNote";
import PaletteIcon from "@mui/icons-material/Palette";
import ShareIcon from "@mui/icons-material/Share";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import { Box, Button, List, ListItemButton, ListItemText, Typography } from "@mui/material";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { api, getSession, signOut } from "./api";
import { useCan } from "./App";
import { useCategories } from "./queries";

const TITLES: [string, string][] = [
  ["/upload", "Upload"],
  ["/approvals", "Approvals"],
  ["/shared", "Shared"],
  ["/organization", "Organization"],
  ["/retention", "Retention"],
  ["/appearance", "Appearance"],
  ["/platform/designs", "Design catalogue"],
  ["/account", "Account"],
  ["/documents", "Documents"],
];

/** Folder-style list of categories, shown beside the icons by designs that use the "rail-tree" layout. */
function CategoryPanel() {
  const categories = useCategories();
  return (
    <Box>
      <Typography variant="caption" color="text.secondary" sx={{ px: 1 }}>CATEGORIES</Typography>
      <List dense>
        <ListItemButton component={NavLink} to="/documents" end>
          <FolderIcon fontSize="small" sx={{ mr: 1 }} />
          <ListItemText primary="All documents" />
        </ListItemButton>
        {categories.data?.map((c) => (
          <ListItemButton key={c.id} component={NavLink} to={`/documents?category=${c.id}`} sx={{ pl: 1 + c.depth * 2 }}>
            <FolderIcon fontSize="small" sx={{ mr: 1 }} />
            <ListItemText primary={c.name} />
          </ListItemButton>
        ))}
      </List>
    </Box>
  );
}

export default function Layout({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const canUpload = useCan("document.upload");
  const canArchive = useCan("document.archive");
  const canDecideDeletion = useCan("document.approve_delete");
  const platform = useQuery({ queryKey: ["platform-admin"], queryFn: () => api<{ is_platform_admin: boolean }>("/me/platform-admin") });
  const queue = useQuery({ queryKey: ["approvals", "queue"], queryFn: () => api<unknown[]>("/approvals/queue") });
  const waiting = queue.data?.length ? ` (${queue.data.length})` : "";
  const items: (NavItem & { show: boolean })[] = [
    { to: "/documents", label: "Documents", icon: <ArticleIcon />, show: true },
    { to: "/upload", label: "Upload", icon: <UploadFileIcon />, show: canUpload },
    { to: "/approvals", label: `Approvals${waiting}`, icon: <FactCheckIcon />, show: true },
    { to: "/shared", label: "Shared", icon: <ShareIcon />, show: true },
    { to: "/organization", label: "Organization", icon: <ApartmentIcon />, show: true },
    { to: "/retention", label: "Retention", icon: <EventNoteIcon />, show: canArchive || canDecideDeletion },
    { to: "/appearance", label: "Appearance", icon: <PaletteIcon />, show: true },
    { to: "/platform/designs", label: "Design catalogue", icon: <BrushIcon />, show: platform.data?.is_platform_admin === true },
    { to: "/account", label: "Account", icon: <AccountCircle />, show: true },
  ];
  return (
    <LayoutRenderer
      brand="DMS"
      title={TITLES.find(([prefix]) => pathname.startsWith(prefix))?.[1] ?? "Documents"}
      navItems={items.filter((i) => i.show)}
      linkComponent={NavLink}
      userLabel={getSession()?.email ?? ""}
      onSignOut={async () => {
        await signOut();
        client.clear();
        window.location.assign("/");
      }}
      onSearch={(q) => navigate(`/documents?q=${encodeURIComponent(q)}`)}
      secondaryPanel={<CategoryPanel />}
      headerActions={
        canUpload ? (
          <Button component={NavLink} to="/upload" variant="contained" size="small">
            Upload
          </Button>
        ) : undefined
      }
    >
      {children}
    </LayoutRenderer>
  );
}
