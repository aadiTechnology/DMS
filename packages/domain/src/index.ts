export const SECURITY_CLASSIFICATIONS = [
  "public",
  "internal",
  "confidential",
  "highly_confidential",
] as const;
export type SecurityClassification = (typeof SECURITY_CLASSIFICATIONS)[number];

export const DOCUMENT_STATES = [
  "draft",
  "submitted",
  "under_review",
  "approved",
  "rejected",
  "archived",
] as const;
export type DocumentState = (typeof DOCUMENT_STATES)[number];

/** PRD STO-001: maximum individual file size, default 100 MB. */
export const DEFAULT_MAX_UPLOAD_BYTES = 100 * 1024 * 1024;

export * from "./permissions";
