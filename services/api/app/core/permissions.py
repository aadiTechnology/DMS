"""Permission catalog (PRD 7.3) and default role templates (PRD 3, 7.5).

Roles are data in the database; these templates only seed each new tenant. A permission is an
action ceiling: it says what a role may attempt. Which specific documents it applies to is
decided later by resource-level policy (classification, ownership, grants, workflow state).
The same codes live in packages/domain/src/permissions.ts; a test keeps them identical.
"""

PERMISSIONS: tuple[str, ...] = (
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
)

_MANAGER = (
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
)

# name -> (description, permissions)
DEFAULT_ROLES: dict[str, tuple[str, tuple[str, ...]]] = {
    "org_admin": ("Organization administrator", PERMISSIONS),
    "department_manager": ("Department manager", _MANAGER),
    "project_manager": ("Project manager", _MANAGER),
    "reviewer": (
        "Reviewer / approver",
        (
            "document.view_metadata",
            "document.preview",
            "document.upload",
            "document.approve",
            "document.reject",
        ),
    ),
    "employee": (
        "Employee",
        (
            "document.view_metadata",
            "document.preview",
            "document.download",
            "document.upload",
            "document.edit_metadata",
            "document.upload_version",
            "document.share",
            "document.request_delete",
        ),
    ),
}

ADMIN_ROLE = "org_admin"
