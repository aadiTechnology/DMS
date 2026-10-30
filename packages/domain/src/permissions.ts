/** Mirrors services/api/app/core/permissions.py (a backend test keeps them identical). */
export const PERMISSIONS = [
  "document.view_metadata",
  "document.preview",
  "document.download",
  "document.upload",
  "document.edit_metadata",
  "document.upload_version",
  "document.share",
  "document.approve",
  "document.reject",
  "document.archive",
  "document.restore",
  "document.request_delete",
  "document.approve_delete",
  "document.manage_permissions",
  "admin.manage_taxonomy",
  "admin.manage_users",
  "admin.manage_organization",
  "admin.view_audit",
] as const;
export type Permission = (typeof PERMISSIONS)[number];
