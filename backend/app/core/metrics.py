"""Phase 11 — safe, bounded in-process operational counters.

Thread-safe counters with a hard key cap so memory cannot grow without
bound.  Pure Python (no external dependency) — meant for dashboards and
smoke checks, not billing-grade observability.
"""
from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_counters: dict[str, int] = {}
_started = time.time()
_MAX_KEYS = 400


def inc(name: str, n: int = 1) -> None:
    """Increment counter *name* by *n* (no-op if key cap reached)."""
    global _counters
    with _lock:
        if name in _counters or len(_counters) < _MAX_KEYS:
            _counters[name] = _counters.get(name, 0) + n


def gauge(name: str, value: float) -> None:
    """Set a gauge (last write wins).  Bounded by the same key cap."""
    with _lock:
        if name in _counters or len(_counters) < _MAX_KEYS:
            _counters[name] = int(value) if float(value).is_integer() else value


def snapshot() -> dict:
    """Return a point-in-time copy of all counters plus uptime."""
    with _lock:
        return {
            "uptime_s": round(time.time() - _started, 1),
            "counters": dict(_counters),
        }


def reset() -> None:
    """Test helper: clear all counters and restart the uptime clock."""
    global _counters, _started
    with _lock:
        _counters = {}
        _started = time.time()
