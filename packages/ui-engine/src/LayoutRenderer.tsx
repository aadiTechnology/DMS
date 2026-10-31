import LogoutIcon from "@mui/icons-material/Logout";
import SearchIcon from "@mui/icons-material/Search";
import {
  Box, Button, InputAdornment, List, ListItemButton, ListItemIcon, ListItemText, Paper, TextField, Tooltip, Typography,
} from "@mui/material";
import { alpha } from "@mui/material/styles";
import { useState, type ElementType, type FormEvent, type ReactNode } from "react";
import { useTemplate } from "./TemplateProvider";

export interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
}

export interface LayoutRendererProps {
  brand: string;
  /** Name of the current page, shown by the header variants that have a title. */
  title: string;
  navItems: NavItem[];
  /** Component used for navigation links (the router's link), receiving a `to` prop. */
  linkComponent: ElementType;
  userLabel: string;
  onSignOut: () => void;
  /** Called when something is typed into the header search box and submitted. */
  onSearch?: (query: string) => void;
  /** Content of the second column of the "rail-tree" layout (for example a folder tree). */
  secondaryPanel?: ReactNode;
  /** Extra buttons for the "toolbar" header. */
  headerActions?: ReactNode;
  children: ReactNode;
}

const widthOf = { fluid: "none", contained: 1180, narrow: 900 } as const;

/**
 * Draws the application shell (navigation and header) in the variant the template names. It
 * receives everything it shows as props; it does no data loading, authorization or routing.
 */
export function LayoutRenderer(p: LayoutRendererProps) {
  const t = useTemplate();
  const { sidebarVariant: side, headerVariant, sidebarWidth, pageSpacing, contentWidth } = t.layout;
  const [query, setQuery] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (query.trim()) p.onSearch?.(query.trim());
  };

  const logo = (
    <Box sx={{ width: 30, height: 30, borderRadius: 1, bgcolor: "primary.main", color: "primary.contrastText", display: "grid", placeItems: "center", fontWeight: 800, fontSize: 14, flex: "none" }}>
      {p.brand.slice(0, 1)}
    </Box>
  );
  const brand = (
    <Box sx={{ display: "flex", alignItems: "center", gap: 1.25, fontWeight: 700, fontSize: "1.1em", color: "text.primary", px: side === "rail-tree" ? 0 : 1, py: 1 }}>
      {logo}
      {side !== "rail-tree" && p.brand}
    </Box>
  );

  const navList = (orientation: "column" | "row") => (
    <List sx={{ display: "flex", flexDirection: orientation, gap: 0.5, p: 0 }}>
      {p.navItems.map((item) => {
        const link = (
          <ListItemButton
            key={item.to}
            component={p.linkComponent}
            to={item.to}
            sx={{
              borderRadius: 1,
              color: "text.secondary",
              ...(orientation === "row" ? { px: 1.25, py: 0.5, width: "auto", borderRadius: 0, borderBottom: "1.5px solid transparent", "&.active": { borderBottomColor: "text.primary", color: "text.primary", bgcolor: "transparent" } } : {}),
              ...(side === "rail-tree" ? { justifyContent: "center", px: 1, color: "#a8c3c8", "&.active": { bgcolor: "rgba(255,255,255,.16)", color: "#fff" } } : {}),
              ...(orientation === "column" && side !== "rail-tree" ? { "&.active": { bgcolor: (th) => alpha(th.palette.primary.main, 0.14), color: "primary.main", fontWeight: 600 } } : {}),
              ...(side === "floating" ? { "&.active": { backgroundImage: (th) => `linear-gradient(120deg, ${th.palette.primary.main}, ${alpha(th.palette.secondary.main, 0.85)})`, color: "#fff", boxShadow: 2 } } : {}),
            }}
          >
            <ListItemIcon sx={{ color: "inherit", minWidth: orientation === "row" || side === "rail-tree" ? 0 : 40, display: orientation === "row" ? "none" : "flex", justifyContent: "center" }}>{item.icon}</ListItemIcon>
            {side !== "rail-tree" && <ListItemText primary={item.label} primaryTypographyProps={{ fontSize: orientation === "row" ? "0.95em" : undefined, fontWeight: "inherit" }} />}
          </ListItemButton>
        );
        return side === "rail-tree" ? <Tooltip key={item.to} title={item.label} placement="right">{link}</Tooltip> : link;
      })}
    </List>
  );

  const userBox = (
    <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
      <Typography variant="body2" data-testid="signed-in-as">{p.userLabel}</Typography>
      <Button size="small" startIcon={<LogoutIcon />} onClick={p.onSignOut}>Sign out</Button>
    </Box>
  );

  const searchField = (pill: boolean, width: number) => (
    <Box component="form" onSubmit={submit} sx={{ flex: 1, maxWidth: width }}>
      <TextField
        size="small"
        fullWidth
        placeholder="Search documents"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment>, sx: pill ? { borderRadius: 999 } : undefined } }}
        inputProps={{ "aria-label": "Search documents" }}
      />
    </Box>
  );

  const headerBar = (inner: ReactNode) => (
    <Box component="header" sx={{ display: "flex", alignItems: "center", gap: 2, px: `${pageSpacing}px`, py: 1.25, minHeight: 56, bgcolor: side === "floating" ? "transparent" : "background.paper", borderBottom: side === "floating" ? 0 : 1, borderColor: "divider" }}>
      {inner}
    </Box>
  );

  const header =
    side === "top"
      ? null
      : headerVariant === "search"
        ? headerBar(<>{searchField(false, 520)}<Box sx={{ flex: 1 }} />{userBox}</>)
        : headerVariant === "pill"
          ? headerBar(<><Box><Typography variant="caption" color="text.secondary">{p.brand}</Typography><Typography fontWeight={700}>{p.title}</Typography></Box><Box sx={{ flex: 1 }} />{searchField(true, 340)}{userBox}</>)
          : headerVariant === "toolbar"
            ? headerBar(<><Typography variant="caption" color="text.secondary">{p.brand} / {p.title}</Typography><Box sx={{ flex: 1 }} />{searchField(false, 300)}{p.headerActions}{userBox}</>)
            : headerBar(<><Typography fontWeight={700}>{p.title}</Typography><Box sx={{ flex: 1 }} />{userBox}</>);

  const content = (
    <Box component="main" sx={{ flex: 1, minWidth: 0, overflow: "auto", p: `${pageSpacing}px` }}>
      <Box sx={{ maxWidth: widthOf[contentWidth], mx: contentWidth === "fluid" ? 0 : "auto" }}>{p.children}</Box>
    </Box>
  );

  if (side === "top") {
    return (
      <Box sx={{ minHeight: "100vh", display: "flex", flexDirection: "column", bgcolor: "background.default" }} data-layout="top">
        <Box component="nav" sx={{ display: "flex", alignItems: "center", gap: 1, px: `${pageSpacing}px`, pt: 2.5, pb: 0.5, maxWidth: widthOf[contentWidth === "fluid" ? "contained" : contentWidth] + 100, width: "100%", mx: "auto" }}>
          {brand}
          <Box sx={{ ml: 3 }}>{navList("row")}</Box>
          <Box sx={{ flex: 1 }} />
          {userBox}
        </Box>
        {content}
      </Box>
    );
  }

  const sidebar =
    side === "rail-tree" ? (
      <Box component="nav" sx={{ width: 64, flex: "none", bgcolor: "primary.dark", color: "#fff", display: "flex", flexDirection: "column", alignItems: "center", gap: 1, py: 1.5 }}>
        {brand}
        {navList("column")}
      </Box>
    ) : (
      <Paper
        component="nav"
        square={side !== "floating"}
        sx={{
          width: sidebarWidth, flex: "none", display: "flex", flexDirection: "column", gap: 1, p: 1.5,
          ...(side === "floating" ? { m: 2, mr: 0, borderRadius: 3, border: 0, boxShadow: 3, height: "calc(100vh - 32px)", position: "sticky", top: 16 } : { borderTop: 0, borderBottom: 0, borderLeft: 0, borderRadius: 0, minHeight: "100vh", position: "sticky", top: 0, alignSelf: "flex-start", height: "100vh" }),
        }}
      >
        {brand}
        {navList("column")}
      </Paper>
    );

  return (
    <Box sx={{ minHeight: "100vh", display: "flex", bgcolor: "background.default", ...(side === "floating" ? { backgroundImage: (th) => `linear-gradient(160deg, ${th.palette.background.default}, ${alpha(th.palette.secondary.main, 0.1)})` } : {}) }} data-layout={side}>
      {sidebar}
      {side === "rail-tree" && p.secondaryPanel && (
        <Box sx={{ width: 232, flex: "none", bgcolor: "background.paper", borderRight: 1, borderColor: "divider", p: 1, overflow: "auto", height: "100vh", position: "sticky", top: 0 }}>{p.secondaryPanel}</Box>
      )}
      <Box sx={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", height: side === "floating" ? "100vh" : undefined }}>
        {header}
        {content}
      </Box>
    </Box>
  );
}
