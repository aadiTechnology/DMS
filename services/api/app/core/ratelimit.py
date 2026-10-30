import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.core.config import get_settings


class SlidingWindowLimiter:
    """In-process limiter. Limitation: per-process memory, so with several API workers the
    effective limit is multiplied; move to a shared store when workers/deployment are chosen.
    Per-account lockout (database) is the primary brute-force control.
    """

    def __init__(self, window_seconds: int = 60):
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        hits = self._hits[key]
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True


auth_limiter = SlidingWindowLimiter()


def limit_auth_requests(request: Request) -> None:
    client = request.client.host if request.client else "unknown"
    if not auth_limiter.allow(client, get_settings().AUTH_RATE_LIMIT_PER_MINUTE):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Try again later.",
            headers={"Retry-After": "60"},
        )
