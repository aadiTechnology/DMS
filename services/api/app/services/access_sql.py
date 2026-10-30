"""SQL form of the document access policy for lists, search, counts and facets.

`visible_clause()` must select exactly the documents for which `access.decide(..., "view_metadata")`
allows access. tests/test_search.py proves the two agree for every kind of viewer, so the rules
cannot drift apart. Facts about the viewer are loaded once; the clause then uses simple EXISTS
checks that the database can optimize.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy import and_, exists, false, or_, select, true
from sqlalchemy.orm import Session

from app.db.models import (
    Department,
    Document,
    DocumentAccessGrant,
    DocumentAssociation,
    EmployeeProfile,
    Project,
    ProjectMembership,
    TenantMembership,
)
from app.services import rbac
from app.services.access import PRIVILEGE, PUBLISHED


@dataclass
class Viewer:
    user_id: uuid.UUID
    membership_id: uuid.UUID
    permissions: set[str]
    managed_departments: set = field(default_factory=set)
    profile_department: uuid.UUID | None = None
    project_ids: set = field(default_factory=set)


def load_viewer(db: Session, tenant_id, user_id) -> Viewer | None:
    membership = db.scalars(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == user_id,
            TenantMembership.status == "active",
        )
    ).first()
    if membership is None:
        return None
    today = date.today()
    profile = db.scalars(
        select(EmployeeProfile).where(
            EmployeeProfile.membership_id == membership.id,
            EmployeeProfile.employment_status != "exited",
        )
    ).first()
    managed_projects = db.scalars(
        select(Project.id).where(Project.manager_membership_id == membership.id)
    ).all()
    member_projects = db.scalars(
        select(ProjectMembership.project_id).where(
            ProjectMembership.membership_id == membership.id,
            (ProjectMembership.ends_on.is_(None)) | (ProjectMembership.ends_on >= today),
        )
    ).all()
    return Viewer(
        user_id=user_id,
        membership_id=membership.id,
        permissions=rbac.effective_permissions(db, tenant_id, user_id),
        managed_departments=set(
            db.scalars(
                select(Department.id).where(Department.manager_membership_id == membership.id)
            ).all()
        ),
        profile_department=profile.department_id if profile else None,
        project_ids=set(managed_projects) | set(member_projects),
    )


def _associated(dimension: str, ids):
    return exists().where(
        DocumentAssociation.document_id == Document.id,
        DocumentAssociation.dimension == dimension,
        DocumentAssociation.ref_id.in_(ids),
    )


def visible_clause(viewer: Viewer):
    """Boolean SQL expression over `documents` for the metadata-visibility rule."""
    if "document.view_metadata" not in viewer.permissions:
        return false()
    if PRIVILEGE in viewer.permissions:
        return true()  # privileged path: audited by the caller when results are returned
    published = Document.lifecycle_state.in_(PUBLISHED)
    restricted = and_(
        published, Document.classification.in_(("confidential", "highly_confidential"))
    )
    confidential = and_(published, Document.classification == "confidential")
    now = datetime.now(UTC)
    shared = exists().where(
        DocumentAccessGrant.document_id == Document.id,
        DocumentAccessGrant.grantee_membership_id == viewer.membership_id,
        DocumentAccessGrant.revoked_at.is_(None),
        DocumentAccessGrant.can_view.is_(True),
        (DocumentAccessGrant.expires_at.is_(None)) | (DocumentAccessGrant.expires_at > now),
    )
    conditions = [
        Document.owner_membership_id == viewer.membership_id,
        Document.created_by_user_id == viewer.user_id,
        and_(published, Document.classification.in_(("public", "internal"))),
        and_(restricted, shared),
    ]
    if viewer.managed_departments:
        conditions.append(and_(restricted, _associated("department", viewer.managed_departments)))
    if viewer.profile_department:
        conditions.append(
            and_(confidential, _associated("department", {viewer.profile_department}))
        )
    if viewer.project_ids:
        conditions.append(and_(confidential, _associated("project", viewer.project_ids)))
    return or_(*conditions)
