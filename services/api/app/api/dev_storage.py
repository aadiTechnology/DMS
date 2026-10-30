"""Stand-in for direct-to-storage transfers when STORAGE_PROVIDER=local (development and tests).
Not mounted in production. The signed token is the only credential: it names one exact key, one
method and an expiry, exactly like a real provider's upload/download URL.
"""

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from app.storage import get_storage
from app.storage.base import ObjectExists, ObjectNotFound, StorageError
from app.storage.local import URL_PREFIX, InvalidSignedUrl, LocalStorage

router = APIRouter(prefix=URL_PREFIX, tags=["dev-storage"], include_in_schema=False)

NO_CACHE = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


def _local() -> LocalStorage:
    storage = get_storage()
    if not isinstance(storage, LocalStorage):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return storage


@router.put("/{token}", status_code=status.HTTP_201_CREATED)
async def upload(token: str, request: Request):
    storage = _local()
    try:
        grant = storage.verify_token(token, "PUT")
    except InvalidSignedUrl:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Invalid or expired link") from None
    declared = request.headers.get("content-length")
    if declared is None or int(declared) != grant["s"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Content-Length must match")
    writer = storage.begin_write(grant["k"], content_type=grant["c"], expected_size=grant["s"])
    try:
        async for chunk in request.stream():  # streamed to disk; never held in memory
            writer.write(chunk)
        writer.commit()
    except ObjectExists:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Object already exists") from None
    except StorageError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Upload rejected") from None
    finally:
        writer.close()
    return Response(status_code=status.HTTP_201_CREATED)


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
        "Content-Disposition": storage.content_disposition(grant["f"]),
        "Content-Length": str(info.size_bytes),
    }
    return StreamingResponse(
        storage.read_stream(grant["k"]),
        media_type=info.content_type or "application/octet-stream",
        headers=headers,
    )
