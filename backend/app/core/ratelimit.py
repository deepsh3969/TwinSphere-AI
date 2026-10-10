"""Phase 10 §11 — per-category sliding-window rate limiting.

In-memory, per-process buckets keyed by ``category|identity``.  This is a
development / single-worker safeguard: for multi-worker production deployments
replace the store with a shared backend (e.g. Redis) — see docs/SECURITY.md
("Rate limiting limitations").  Buckets are pruned on access and the number of
tracked keys is capped so memory cannot grow without bound.
"""

from __future__ import annotations

import threading
import time

from fastapi import HTTPException, Request, status

from app.core.config import settings

# category -> (limit, window_seconds); "general" uses RATE_LIMIT_PER_MINUTE.
def _limits() -> dict[str, tuple[int, int]]:
    return {
        "general": (settings.RATE_LIMIT_PER_MINUTE, 60),
        "login": (settings.LOGIN_RATE_LIMIT_PER_MINUTE, 60),
        "register": (settings.REGISTER_RATE_LIMIT_PER_MINUTE, 60),
        "export": (settings.EXPORT_RATE_LIMIT_PER_MINUTE, 60),
        "ai": (settings.AI_RATE_LIMIT_PER_MINUTE, 60),
        "simulation": (settings.SIMULATION_RATE_LIMIT_PER_MINUTE, 60),
        "admin": (settings.ADMIN_RATE_LIMIT_PER_MINUTE, 60),
        "ws": (settings.WS_RATE_LIMIT_PER_MINUTE, 60),
    }


_lock = threading.Lock()
_buckets: dict[str, list[float]] = {}
_MAX_KEYS = 10_000


def client_ip(request: Request) -> str:
    """Best-effort client address (first X-Forwarded-For hop when present)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45] or "unknown"
    return request.client.host if request.client else "unknown"


def check(category: str, identity: str = "") -> None:
    """Raise 429 (with Retry-After) when *identity* exceeds *category* limits."""
    if not settings.RATE_LIMIT_ENABLED:
        return
    limits = _limits()
    limit, window = limits.get(category, limits["general"])
    key = f"{category}|{identity}" if identity else category
    now = time.time()
    with _lock:
        bucket = _buckets.get(key)
        if bucket is None:
            if len(_buckets) >= _MAX_KEYS:
                # Drop the coldest third of the keys (bounded memory).
                stale = sorted(_buckets, key=lambda k: _buckets[k][-1] if _buckets[k] else 0.0)
                for k in stale[: _MAX_KEYS // 3]:
                    _buckets.pop(k, None)
            bucket = []
            _buckets[key] = bucket
        bucket[:] = [t for t in bucket if now - t < window]
        if len(bucket) >= limit:
            from app.core import metrics

            metrics.inc(f"ratelimit.{category}.blocked")
            retry = int(window - (now - bucket[0])) + 1
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many requests — please retry later",
                headers={"Retry-After": str(max(retry, 1))},
            )
        bucket.append(now)


def rate_limit(request: Request, category: str = "general") -> None:
    """FastAPI dependency: limit by category + client IP (login adds username)."""
    check(category, client_ip(request))


def limit(category: str):
    """Factory for a FastAPI dependency enforcing *category* limits by IP."""

    def dep(request: Request) -> None:
        check(category, client_ip(request))

    return dep


def reset() -> None:
    """Test helper: clear all buckets."""
    with _lock:
        _buckets.clear()
