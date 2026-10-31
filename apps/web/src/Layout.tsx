import AccountCircle from "@mui/icons-material/AccountCircle";
import ApartmentIcon from "@mui/icons-material/Apartment";
import ArticleIcon from "@mui/icons-material/Article";
import FactCheckIcon from "@mui/icons-material/FactCheck";
import LogoutIcon from "@mui/icons-material/Logout";
import ShareIcon from "@mui/icons-material/Share";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import {
  AppBar, Box, Button, Drawer, List, ListItemButton, ListItemIcon, ListItemText, Toolbar, Typography,
} from "@mui/material";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { api, getSession, signOut } from "./api";
import { useCan } from "./App";

const WIDTH = 232;

export default function Layout({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const canUpload = useCan("document.upload");
  const queue = useQuery({ queryKey: ["approvals", "queue"], queryFn: () => api<unknown[]>("/approvals/queue") });
  const waiting = queue.data?.length ? ` (${queue.data.length})` : "";
  const items = [
    { to: "/documents", text: "Documents", icon: <ArticleIcon />, show: true },
    { to: "/upload", text: "Upload", icon: <UploadFileIcon />, show: canUpload },
    { to: "/approvals", text: `Approvals${waiting}`, icon: <FactCheckIcon />, show: true },
    { to: "/shared", text: "Shared", icon: <ShareIcon />, show: true },
    { to: "/organization", text: "Organization", icon: <ApartmentIcon />, show: true },
    { to: "/account", text: "Account", icon: <AccountCircle />, show: true },
  ];
  return (
    <Box sx={{ display: "flex", minHeight: "100vh" }}>
      <AppBar position="fixed" color="inherit" variant="outlined" sx={{ zIndex: 1201, borderLeft: 0, borderRight: 0, borderTop: 0 }}>
        <Toolbar>
          <Typography variant="h6" color="primary" sx={{ fontWeight: 700, flexGrow: 1 }}>
            DMS · Document Management
          </Typography>
          <Typography variant="body2" sx={{ mr: 2 }} data-testid="signed-in-as">
            {getSession()?.email}
          </Typography>
          <Button
            startIcon={<LogoutIcon />}
            onClick={async () => {
              await signOut();
              client.clear();
              window.location.assign("/");
            }}
          >
            Sign out
          </Button>
        </Toolbar>
      </AppBar>
      <Drawer variant="permanent" sx={{ width: WIDTH, "& .MuiDrawer-paper": { width: WIDTH, boxSizing: "border-box", pt: 8 } }}>
        <List>
          {items
            .filter((i) => i.show)
            .map((i) => (
              <ListItemButton key={i.to} component={NavLink} to={i.to} sx={{ "&.active": { bgcolor: "action.selected", color: "primary.main" } }}>
                <ListItemIcon sx={{ color: "inherit", minWidth: 40 }}>{i.icon}</ListItemIcon>
                <ListItemText primary={i.text} />
              </ListItemButton>
            ))}
        </List>
      </Drawer>
      <Box component="main" sx={{ flexGrow: 1, p: 3, mt: 8, minWidth: 0 }}>
        {children}
      </Box>
    </Box>
  );
}
