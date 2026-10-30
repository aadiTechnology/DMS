"""Stand-in for the provider's download URLs when STORAGE_PROVIDER=local (development and tests).
Not mounted in production. The signed token is the only credential: it names one exact key, one
method and an expiry, like a real provider's authorized download link.
"""

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from app.storage import get_storage
from app.storage.base import ObjectNotFound
from app.storage.local import URL_PREFIX, InvalidSignedUrl, LocalStorage

router = APIRouter(prefix=URL_PREFIX, tags=["dev-storage"], include_in_schema=False)

NO_CACHE = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


def _local() -> LocalStorage:
    storage = get_storage()
    if not isinstance(storage, LocalStorage):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return storage


@router.get("/{token}")
def download(token: str):
    storage = _local()
    try:
        grant = storage.verify_token(token, "GET")
        info = storage.stat(grant["k"])
        if info is None:
            raise ObjectNotFound("missing")
    except InvalidSignedUrl:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Invalid or expired link") from None
    except ObjectNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found") from None
    headers = {
        **NO_CACHE,
        "Content-Disposition": storage.content_disposition(
            grant["f"], grant.get("d", "attachment")
        ),
        "Content-Length": str(info.size_bytes),
    }
    return StreamingResponse(
        storage.read_stream(grant["k"]),
        media_type=info.content_type or "application/octet-stream",
        headers=headers,
    )
