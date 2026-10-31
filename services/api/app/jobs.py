"""Scheduled maintenance for every organization, run by a scheduler (for example a Coolify
scheduled task):

    python -m app.jobs expire-uploads     # abandon unfinished uploads and remove leftovers
    python -m app.jobs index-content      # extract text for documents waiting in the search queue
    python -m app.jobs all

Safe to run often and from more than one place at once: both jobs use row locks that skip rows
another worker already holds. Prints counts only, never document titles or content.
"""

import logging
import sys
from collections.abc import Sequence
from functools import partial

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Tenant
from app.db.tenant_session import auth_session, tenant_session
from app.services import search, uploads
from app.storage import get_storage

logger = logging.getLogger("dms.jobs")
JOBS = ("expire-uploads", "index-content")
INDEX_BATCH = 25


def _tenant_ids(engine=None) -> list:
    with auth_session(engine) as db:
        return list(db.scalars(select(Tenant.id).where(Tenant.status == "active")))


def run(names: Sequence[str], engine=None, storage=None) -> dict[str, int]:
    storage = storage or get_storage()
    totals = {"abandoned": 0, "delete_failures": 0, "indexed": 0, "index_failed": 0}
    tenants = _tenant_ids(engine)
    for tenant_id in tenants:
        if "expire-uploads" in names:
            with tenant_session(tenant_id, engine) as db:
                abandoned, failures = uploads.expire_stale(db, tenant_id, storage)
            totals["abandoned"] += abandoned
            totals["delete_failures"] += failures
        if "index-content" in names:
            stats = search.process_pending(
                tenant_id, storage, get_settings(), limit=INDEX_BATCH,
                tenant_session=partial(tenant_session, engine=engine),
            )  # fmt: skip
            totals["indexed"] += stats.indexed
            totals["index_failed"] += stats.failed
    totals["tenants"] = len(tenants)
    return totals


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or args[0] not in (*JOBS, "all"):
        print(f"usage: python -m app.jobs [{'|'.join((*JOBS, 'all'))}]", file=sys.stderr)
        return 2
    names = JOBS if args[0] == "all" else (args[0],)
    logging.basicConfig(level=logging.INFO)
    try:
        totals = run(names)
    except Exception:
        logger.exception("job failed")
        return 1
    print(" ".join(f"{k}={v}" for k, v in totals.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
