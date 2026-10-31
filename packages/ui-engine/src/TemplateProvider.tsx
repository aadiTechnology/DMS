import { CssBaseline, ThemeProvider } from "@mui/material";
import { createContext, useContext, useMemo, type CSSProperties, type ReactNode } from "react";
import { buildMuiTheme } from "./muiTheme";
import { SYSTEM_TEMPLATE } from "./systemTemplate";
import { cssVariables } from "./tokens";
import type { UiTemplate } from "./types";

const TemplateContext = createContext<UiTemplate>(SYSTEM_TEMPLATE);

/** The template currently applied. Pages use it to pick a preset layout; they never read colors from it. */
export const useTemplate = (): UiTemplate => useContext(TemplateContext);

/**
 * Applies a validated template: the MUI theme (colors, type, component variants) and CSS custom
 * properties for anything outside MUI. It owns appearance only; it knows nothing about who the
 * user is, what they may do, or what the pages show.
 */
export function TemplateProvider({ template, children }: { template: UiTemplate; children: ReactNode }) {
  const theme = useMemo(() => buildMuiTheme(template), [template]);
  const vars = useMemo(() => ({ display: "contents", ...cssVariables(template) }) as CSSProperties, [template]);
  return (
    <TemplateContext.Provider value={template}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <div style={vars} data-dms-template={template.key} data-dms-mode={template.theme.mode}>
          {children}
        </div>
      </ThemeProvider>
    </TemplateContext.Provider>
  );
}
