from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import get_settings

WINDOW = 60.0


def _heavy(request: Request) -> bool:
    p = request.url.path
    if p.startswith("/api/auth/") or p == "/api/predict":
        return True
    return request.method == "POST" and (p == "/api/companies" or p.endswith("/upload"))


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:
        super().__init__(app)
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _client(self, request: Request) -> str:
        if get_settings().trust_proxy:
            fwd = request.headers.get("x-forwarded-for", "")
            if fwd:
                return fwd.split(",")[0].strip()
        return request.client.host if request.client else "?"

    def _allow(self, key: tuple[str, str], limit: int, now: float) -> bool:
        q = self._hits[key]
        while q and now - q[0] > WINDOW:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True

    async def dispatch(self, request: Request, call_next):
        s = get_settings()
        if not request.url.path.startswith("/api/") or request.url.path == "/api/health":
            return await call_next(request)
        ip, now = self._client(request), time.monotonic()
        with self._lock:
            ok = (s.rate_limit_per_min <= 0 or self._allow((ip, "all"), s.rate_limit_per_min, now)) and \
                 (not _heavy(request) or s.rate_limit_heavy_per_min <= 0 or
                  self._allow((ip, "heavy"), s.rate_limit_heavy_per_min, now))
            if len(self._hits) > 50_000:
                self._hits.clear()
        if not ok:
            return JSONResponse(status_code=429, headers={"Retry-After": "60"},
                                content={"detail": "Слишком много запросов. Подождите минуту и попробуйте снова."})
        return await call_next(request)
