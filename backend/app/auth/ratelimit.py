"""In-process rate limiter for the auth endpoints (brute-force / signup spam).

Deliberately dependency-free (no slowapi): a per-``(client_ip, bucket)``
sliding-window counter held in memory. On multi-instance Cloud Run the window
is per-instance, which still raises the cost of a credential-stuffing run
meaningfully; pair with gateway/WAF limits for stronger guarantees.

Enforced only on Cloud Run by default so local dev and the test-suite (which
hammer ``/auth/*`` repeatedly) aren't throttled. Force it on anywhere with
``FINCOACH_AUTH_RATELIMIT_FORCE=1``.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict

from fastapi import HTTPException, Request, status

from app.settings import settings

_lock = threading.Lock()
# (ip, bucket) -> monotonic timestamps of recent hits within the window.
_hits: dict[tuple[str, str], list[float]] = defaultdict(list)


def _client_ip(request: Request) -> str:
    # Behind Firebase Hosting / Cloud Run the real client is in X-Forwarded-For;
    # the left-most entry is the original caller.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _enforced() -> bool:
    return settings.is_cloud_run or settings.auth_rate_limit_force


def rate_limit(bucket: str, *, limit: int, window_seconds: int = 60):
    """Build a FastAPI dependency that allows ``limit`` requests per window per IP.

    Returns 429 with a ``Retry-After`` header once the window is saturated.
    """

    def _dep(request: Request) -> None:
        if not _enforced():
            return
        now = time.monotonic()
        cutoff = now - window_seconds
        key = (_client_ip(request), bucket)
        with _lock:
            kept = [t for t in _hits[key] if t > cutoff]
            if len(kept) >= limit:
                _hits[key] = kept
                retry = int(window_seconds - (now - kept[0])) + 1
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="too many attempts, please slow down and try again shortly",
                    headers={"Retry-After": str(max(1, retry))},
                )
            kept.append(now)
            _hits[key] = kept

    return _dep
