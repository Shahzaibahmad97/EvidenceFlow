from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

MAX_BODY_BYTES = 256 * 1024
RATE_LIMIT_REQUESTS = 60
RATE_LIMIT_WINDOW_SECONDS = 60.0
GUARDED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass
class SlidingWindow:
    limit: int = RATE_LIMIT_REQUESTS
    window: float = RATE_LIMIT_WINDOW_SECONDS
    seen: dict[str, deque[float]] = field(default_factory=dict)

    def allows(self, client: str, moment: float | None = None) -> bool:
        moment = time.monotonic() if moment is None else moment
        hits = self.seen.setdefault(client, deque())
        while hits and hits[0] <= moment - self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(moment)
        return True


class RequestLimits(BaseHTTPMiddleware):
    def __init__(self, app, max_body_bytes: int = MAX_BODY_BYTES, window: SlidingWindow | None = None):
        super().__init__(app)
        self._max_body_bytes = max_body_bytes
        self._window = window or SlidingWindow()

    async def dispatch(self, request: Request, call_next):
        if request.method not in GUARDED_METHODS:
            return await call_next(request)

        declared = request.headers.get("content-length")
        if declared and int(declared) > self._max_body_bytes:
            return _refused(413, "request body too large")
        if not self._window.allows(request.client.host if request.client else "unknown"):
            return _refused(429, "too many requests")
        return await call_next(request)


def _refused(code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": {"code": code, "message": message}})
