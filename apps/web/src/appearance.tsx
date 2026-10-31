import { validateTemplate, type UiTemplate } from "@aaditech/ui-engine";
import { Alert, Box, Button } from "@mui/material";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, type ReactNode } from "react";
import { api, errorText } from "./api";

/** Query key of the signed-in person's design preference; invalidate it after changing the choice. */
export const APPEARANCE_KEY = ["ui-preferences"] as const;

export interface Preview {
  id: string;
  template: UiTemplate;
}

interface PreviewState {
  preview: Preview | null;
  start: (id: string, config: unknown) => string | null;
  stop: () => void;
}

export const PreviewContext = createContext<PreviewState>({ preview: null, start: () => null, stop: () => {} });
export const usePreview = () => useContext(PreviewContext);

/** Validate then show a design temporarily (nothing is saved). Returns an error message or null. */
export function checkedPreview(config: unknown): { template: UiTemplate } | { error: string } {
  const result = validateTemplate(config);
  return result.valid ? { template: result.template } : { error: "This design did not pass the safety check and cannot be previewed." };
}

/** Save the person's choice (null resets to the default); the app restyles as soon as it is saved. */
export function useApplyDesign(onDone?: () => void) {
  const client = useQueryClient();
  const { stop } = usePreview();
  return useMutation({
    mutationFn: (templateId: string | null) => api("/me/ui-preferences", { method: "PUT", body: { template_id: templateId } }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: APPEARANCE_KEY });
      await client.invalidateQueries({ queryKey: ["ui-available"] });
      stop();
      onDone?.();
    },
  });
}

/** Shown over every page while a design is being previewed. */
export function PreviewBanner({ children }: { children?: ReactNode }) {
  const { preview, stop } = usePreview();
  const apply = useApplyDesign();
  if (!preview) return <>{children}</>;
  return (
    <>
      <Box role="status" sx={{ position: "fixed", left: 0, right: 0, bottom: 0, zIndex: 2000, p: 1.5, display: "flex", justifyContent: "center", pointerEvents: "none" }}>
        <Alert
          severity="info"
          variant="filled"
          sx={{ pointerEvents: "auto", boxShadow: 6, alignItems: "center" }}
          action={
            <>
              <Button color="inherit" size="small" onClick={() => apply.mutate(preview.id)} disabled={apply.isPending}>Apply this design</Button>
              <Button color="inherit" size="small" onClick={stop}>Stop previewing</Button>
            </>
          }
        >
          {apply.error ? errorText(apply.error) : `Previewing “${preview.template.name}”. Nothing is saved until you apply it.`}
        </Alert>
      </Box>
      {children}
    </>
  );
}
