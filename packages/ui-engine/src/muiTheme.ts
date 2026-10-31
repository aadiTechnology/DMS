import { alpha, createTheme, type Theme } from "@mui/material/styles";
import type { CSSObject } from "@mui/material/styles";
import { DENSITY, FONT_STACKS, SHADOW_VALUES } from "./tokens";
import type { UiTemplate } from "./types";

type Tone = "primary" | "secondary" | "success" | "warning" | "error" | "info";

/**
 * Component variant resolver: turns the template's named variants into MUI style rules. Every
 * variant is a fixed branch here; a template can only choose between them.
 */
export function buildMuiTheme(t: UiTemplate): Theme {
  const c = t.theme.colors;
  const d = DENSITY[t.density];
  const radius = t.theme.radius;
  const shadow = SHADOW_VALUES[t.theme.shadow];
  const dark = t.theme.mode === "dark";
  const tint = (amount: number) => alpha(c.primary, amount);
  const cm = t.components;

  const card = ((): CSSObject => {
    switch (cm.card) {
      case "elevated":
        return { border: "none", boxShadow: shadow };
      case "flat":
        return { border: "none", borderBottom: `1px solid ${c.border}`, borderRadius: 0, backgroundColor: "transparent", boxShadow: "none" };
      case "glass":
        return {
          border: `1px solid ${c.border}`,
          boxShadow: shadow,
          backgroundImage: "linear-gradient(145deg, rgba(255,255,255,.07), rgba(255,255,255,.02))",
          backdropFilter: "blur(6px)",
        };
      case "gradient":
        return {
          border: `1px solid ${c.border}`,
          boxShadow: shadow,
          backgroundImage: `linear-gradient(150deg, ${c.surface} 55%, ${alpha(c.primary, 0.07)})`,
        };
      default:
        return { border: `1px solid ${c.border}`, boxShadow: shadow };
    }
  })();

  const cell = ((): CSSObject => {
    const base: CSSObject = { paddingTop: d.cell, paddingBottom: d.cell, borderBottom: "none" };
    switch (cm.table) {
      case "lined":
        return { ...base, borderBottom: `1px solid ${c.border}` };
      case "dense":
        return { ...base, border: `1px solid ${c.border}`, paddingLeft: 8, paddingRight: 8 };
      case "zebra":
        return { ...base, borderBottom: `1px solid ${alpha(c.border, 0.6)}` };
      default:
        return { ...base, borderBottom: `1px solid ${alpha(c.border, 0.55)}` };
    }
  })();

  const field = (kind: "outlined" | "filled" | "underline"): CSSObject => {
    const common: CSSObject = { minHeight: d.control, borderRadius: radius };
    if (kind === "filled") {
      return {
        ...common,
        backgroundColor: tint(0.08),
        "& .MuiOutlinedInput-notchedOutline": { borderColor: "transparent", borderBottom: `1.5px solid ${c.border}` },
      };
    }
    if (kind === "underline") {
      return {
        ...common,
        borderRadius: 0,
        "& .MuiOutlinedInput-notchedOutline": { border: "none", borderBottom: `1px solid ${c.textSecondary}` },
      };
    }
    return { ...common, "& .MuiOutlinedInput-notchedOutline": { borderColor: c.border } };
  };

  const buttonTone = (tone: Tone): CSSObject => {
    switch (cm.button) {
      case "soft":
        return { backgroundColor: alpha(c[tone], 0.16), color: c[tone], "&:hover": { backgroundColor: alpha(c[tone], 0.26) } };
      case "outline":
        return { backgroundColor: "transparent", color: c.textPrimary, border: `1px solid ${c.textPrimary}`, "&:hover": { backgroundColor: alpha(c.textPrimary, 0.06) } };
      case "pill":
        return { backgroundImage: `linear-gradient(120deg, ${c[tone]}, ${alpha(c.secondary, 1)})`, color: "#fff" };
      default:
        return {};
    }
  };

  const chipRoot = (tone: Tone | "default"): CSSObject => {
    const color = tone === "default" ? c.textSecondary : c[tone];
    switch (cm.badge) {
      case "soft":
        return { backgroundColor: alpha(color, 0.15), color, border: "1px solid transparent" };
      case "outlined":
        return { backgroundColor: "transparent", color, border: `1px solid ${color}` };
      case "dot":
        return {
          backgroundColor: alpha(color, 0.1),
          color: c.textPrimary,
          border: "1px solid transparent",
          "&::before": { content: '""', width: 8, height: 8, borderRadius: "50%", backgroundColor: color, marginLeft: 8 },
        };
      default:
        return { backgroundColor: color, color: "#fff", border: "1px solid transparent" };
    }
  };

  return createTheme({
    palette: {
      mode: t.theme.mode,
      primary: { main: c.primary },
      secondary: { main: c.secondary },
      success: { main: c.success },
      warning: { main: c.warning },
      error: { main: c.error },
      info: { main: c.info },
      background: { default: c.background, paper: c.surface },
      text: { primary: c.textPrimary, secondary: c.textSecondary },
      divider: c.border,
    },
    shape: { borderRadius: radius },
    typography: {
      fontFamily: FONT_STACKS[t.theme.typography.fontFamily],
      fontSize: 14 * t.theme.typography.scale,
      h1: { fontWeight: t.theme.typography.headingWeight },
      h2: { fontWeight: t.theme.typography.headingWeight },
      h3: { fontWeight: t.theme.typography.headingWeight },
      h4: { fontWeight: t.theme.typography.headingWeight },
      h5: { fontWeight: t.theme.typography.headingWeight },
      h6: { fontWeight: t.theme.typography.headingWeight },
      button: { textTransform: "none", fontWeight: 600 },
    },
    components: {
      MuiCssBaseline: { styleOverrides: { body: { backgroundColor: c.background, colorScheme: dark ? "dark" : "light" } } },
      MuiPaper: {
        defaultProps: { variant: "outlined" },
        styleOverrides: { root: { backgroundImage: "none" } },
        variants: [{ props: { variant: "outlined" }, style: { ...card, padding: undefined } }],
      },
      MuiButton: {
        defaultProps: { disableElevation: true },
        styleOverrides: {
          root: { minHeight: d.control, borderRadius: cm.button === "pill" ? 999 : radius },
          containedPrimary: buttonTone("primary"),
          containedSecondary: buttonTone("secondary"),
          containedSuccess: buttonTone("success"),
          containedError: buttonTone("error"),
        },
      },
      MuiTableCell: {
        styleOverrides: {
          root: cell,
          head: { fontWeight: 600, color: c.textSecondary, ...(cm.table === "dense" ? { backgroundColor: tint(0.07) } : {}), ...(cm.table === "zebra" ? { borderBottom: `2px solid ${c.border}` } : {}) },
        },
      },
      MuiTableRow: {
        styleOverrides: {
          root: {
            ...(cm.table === "zebra" ? { "&:nth-of-type(even)": { backgroundColor: tint(0.04) } } : {}),
            "&.MuiTableRow-hover:hover": { backgroundColor: tint(0.06) },
          },
        },
      },
      MuiOutlinedInput: { styleOverrides: { root: field(cm.input) } },
      MuiSelect: { styleOverrides: { select: {} } },
      MuiTextField: {
        variants: [
          { props: { select: true }, style: { "& .MuiOutlinedInput-root": field(cm.dropdown) } },
        ],
      },
      MuiTabs: {
        styleOverrides: {
          root: cm.tabs === "segmented" ? { backgroundColor: tint(0.08), borderRadius: radius + 4, padding: 4, minHeight: 0, width: "fit-content" } : {},
          indicator: cm.tabs === "underline" ? {} : { display: "none" },
        },
      },
      MuiTab: {
        styleOverrides: {
          root:
            cm.tabs === "pills"
              ? { borderRadius: 999, minHeight: 36, "&.Mui-selected": { backgroundColor: tint(0.16) } }
              : cm.tabs === "segmented"
                ? { borderRadius: radius, minHeight: 36, "&.Mui-selected": { backgroundColor: c.surface, boxShadow: shadow } }
                : {},
        },
      },
      MuiDialog: {
        styleOverrides: {
          paper:
            cm.dialog === "rounded"
              ? { borderRadius: 24, border: `1px solid ${c.border}`, boxShadow: SHADOW_VALUES.strong }
              : cm.dialog === "flat"
                ? { boxShadow: "none", border: `1px solid ${c.textPrimary}` }
                : { borderRadius: radius, boxShadow: SHADOW_VALUES.strong },
        },
      },
      MuiChip: {
        styleOverrides: {
          root: ({ ownerState }) => {
            const tone = (ownerState.color ?? "default") as Tone | "default";
            return { borderRadius: cm.badge === "filled" || cm.badge === "outlined" ? Math.min(radius, 8) : 999, fontWeight: 600, ...chipRoot(tone === "primary" || tone === "secondary" || tone === "success" || tone === "warning" || tone === "error" || tone === "info" ? tone : "default") };
          },
        },
      },
    },
  });
}
