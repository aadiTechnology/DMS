export const CLASSIFICATIONS = [
  ["public", "Public"],
  ["internal", "Internal"],
  ["confidential", "Confidential"],
  ["highly_confidential", "Highly confidential"],
] as const;

export const STATES: Record<string, string> = {
  draft: "Draft",
  submitted: "Submitted",
  under_review: "Under review",
  approved: "Approved",
  rejected: "Rejected",
  archived: "Archived",
  deleted: "Deleted",
};

export const label = (value: string | null | undefined) =>
  value ? (STATES[value] ?? value.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())) : "";

export function size(bytes: number | null | undefined) {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export const date = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" }) : "";

export const dateTime = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString(undefined, { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "";

export type Tone = "default" | "primary" | "success" | "warning" | "error" | "info";
export const stateTone = (s: string): Tone =>
  ({ approved: "success", submitted: "warning", under_review: "warning", rejected: "error", archived: "default" })[s] as Tone ?? "default";
export const classTone = (c: string): Tone =>
  ({ public: "success", internal: "info", confidential: "warning", highly_confidential: "error" })[c] as Tone ?? "default";
