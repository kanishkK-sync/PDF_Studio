"""Single-process per-IP sliding windows, applied before reading API bodies."""

import math
import sys
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from threading import Lock

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import get_settings

WINDOW_SECONDS = 60


class SlidingWindowLimiter:
    """Keep only accepted requests in the previous minute; expire idle IPs."""

    def __init__(
        self, limit: int, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if limit < 1:
            raise ValueError("Rate limit must be positive")
        self.limit = limit
        self.clock = clock
        # Ordered by most recent accepted request, allowing cheap idle cleanup.
        self.windows: OrderedDict[str, deque[float]] = OrderedDict()
        self.lock = Lock()

    def retry_after(self, ip: str) -> int:
        """Record an allowed request (0), or return seconds until the next slot."""
        with self.lock:
            now = self.clock()
            cutoff = now - WINDOW_SECONDS
            while self.windows:
                oldest = next(iter(self.windows))
                if self.windows[oldest][-1] > cutoff:
                    break
                self.windows.popitem(last=False)

            window = self.windows.setdefault(ip, deque())
            while window and window[0] <= cutoff:
                window.popleft()
            if len(window) >= self.limit:
                return max(1, math.ceil(window[0] + WINDOW_SECONDS - now))
            window.append(now)
            self.windows.move_to_end(ip)
            return 0


class RateLimitMiddleware:
    """Use the ASGI client IP, as normalized by Uvicorn's trusted proxy layer.

    Never trust arbitrary X-Forwarded-For headers here. Tests opt in with
    enabled=True; normal pytest runs bypass the middleware automatically.
    Health checks and CORS preflights do not consume the API budget.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        enabled: bool | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.app = app
        self.enabled = enabled
        self.limiter = SlidingWindowLimiter(get_settings().rate_limit_per_minute, clock)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        enabled = self.enabled if self.enabled is not None else "pytest" not in sys.modules
        path = scope.get("path", "")
        if (
            enabled
            and scope["type"] == "http"
            and path.startswith("/api/")
            and path != "/api/health"
            and scope["method"] != "OPTIONS"
        ):
            client = scope.get("client")
            retry_after = self.limiter.retry_after(client[0] if client else "unknown")
            if retry_after:
                response = JSONResponse(
                    status_code=429,
                    content={"error": {
                        "code": "RATE_LIMITED",
                        "message": "Too many requests. Please wait a moment and try again.",
                    }},
                    headers={"Retry-After": str(retry_after)},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
