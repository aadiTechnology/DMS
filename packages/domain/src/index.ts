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

/** Mirrors services/api/app/services/metadata.py FIELD_TYPES (a backend test keeps them identical). */
export const METADATA_FIELD_TYPES = [
  "text",
  "long_text",
  "number",
  "decimal",
  "date",
  "date_range",
  "boolean",
  "single_select",
  "multi_select",
  "employee_lookup",
  "department_lookup",
  "branch_lookup",
  "project_lookup",
  "tag_selector",
] as const;
export type MetadataFieldType = (typeof METADATA_FIELD_TYPES)[number];

export const REQUIRED_DIMENSIONS = ["department", "branch", "project", "employee"] as const;
export type OrganizationDimension = (typeof REQUIRED_DIMENSIONS)[number];
