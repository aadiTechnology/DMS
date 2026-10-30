from app.db.models import TenantMembership
from app.db.repository import TenantRepository


class MembershipRepository(TenantRepository[TenantMembership]):
    model = TenantMembership
