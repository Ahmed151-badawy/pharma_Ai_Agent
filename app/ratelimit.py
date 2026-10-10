"""Small in-memory sliding-window rate limiter.

Per-process only: if you run several containers, move this to Redis (e.g. slowapi + redis).
"""
import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request

from app.auth import get_current_user
from app.config import get_settings
from app.models import User


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_seconds: float = 60.0) -> float:
        """Record a hit. Returns 0 if allowed, otherwise the seconds until a slot frees up."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                return window_seconds - (now - hits[0])
            hits.append(now)
            return 0.0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


def _enforce(key: str, limit: int) -> None:
    if not get_settings().rate_limit_enabled:
        return
    retry_after = limiter.check(key, limit)
    if retry_after > 0:
        raise HTTPException(status_code=429, detail="Too many requests.", headers={"Retry-After": str(int(retry_after) + 1)})


def login_rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    _enforce(f"login:{ip}", get_settings().login_rate_limit_per_minute)


def chat_rate_limit(user: User = Depends(get_current_user)) -> None:
    _enforce(f"chat:{user.username}", get_settings().chat_rate_limit_per_minute)
