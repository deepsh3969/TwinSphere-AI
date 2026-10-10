#!/usr/bin/env python3
"""Phase 11 — repeatable API performance benchmark.

Usage:
    python backend/tests/benchmark_api.py [--iterations N] [--warmup W] [--json]

Runs a fixed set of read-heavy and write-light endpoints, collects latency
samples (after warmup), and reports p50/p95/p99 + payload sizes.  Defaults
to 127.0.0.1:8000 (matches smoke_api.py).  Exits 1 on any HTTP >= 500.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from typing import Callable

import httpx

BASE = "http://127.0.0.1:8000"


def _percentile(samples: list[float], p: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    k = (len(ordered) - 1) * (p / 100.0)
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    frac = k - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def _bench(fn: Callable[[], httpx.Response], iterations: int, warmup: int) -> dict:
    for _ in range(warmup):
        fn()
    samples: list[float] = []
    sizes: list[int] = []
    status = None
    for _ in range(iterations):
        t0 = time.perf_counter()
        r = fn()
        t1 = time.perf_counter()
        samples.append((t1 - t0) * 1000.0)
        sizes.append(len(r.content))
        status = r.status_code
    return {
        "p50_ms": round(_percentile(samples, 50), 2),
        "p95_ms": round(_percentile(samples, 95), 2),
        "p99_ms": round(_percentile(samples, 99), 2),
        "mean_ms": round(statistics.fmean(samples), 2),
        "min_ms": round(min(samples), 2),
        "max_ms": round(max(samples), 2),
        "payload_avg_bytes": int(statistics.fmean(sizes)),
        "status": status,
        "n": iterations,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="TwinSphere API benchmark")
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--iterations", type=int, default=40)
    ap.add_argument("--warmup", type=int, default=5)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    c = httpx.Client(base_url=args.base, timeout=30.0)

    # login (rate limiting applies if enabled — use a fresh token once)
    lr = c.post("/api/auth/login", json={"username": "operator", "password": "operator123"})
    if lr.status_code != 200:
        print(f"login failed: {lr.status_code} {lr.text[:200]}", file=sys.stderr)
        return 1
    tok = lr.json()["access_token"]
    hdr = {"Authorization": f"Bearer {tok}"}

    endpoints: list[tuple[str, Callable[[], httpx.Response]]] = [
        ("GET /health", lambda: c.get("/health")),
        ("GET /api/campus", lambda: c.get("/api/campus", headers=hdr)),
        ("GET /api/buildings/eng", lambda: c.get("/api/buildings/eng", headers=hdr)),
        ("GET /api/simulations", lambda: c.get("/api/simulations", headers=hdr)),
        ("GET /api/analytics/overview", lambda: c.get("/api/analytics/overview", headers=hdr)),
        ("GET /api/ai/analyst", lambda: c.get("/api/ai/analyst", headers=hdr)),
        ("GET /api/incidents", lambda: c.get("/api/incidents", headers=hdr)),
        ("GET /api/analytics/risk", lambda: c.get("/api/analytics/risk", headers=hdr)),
        ("GET /api/audit", lambda: c.get("/api/audit", headers=hdr)),
        ("GET /api/history/simulations", lambda: c.get("/api/history/simulations", headers=hdr)),
        ("GET /api/system/status", lambda: c.get("/api/system/status", headers=hdr)),
        ("GET /api/realtime/status", lambda: c.get("/api/realtime/status", headers=hdr)),
    ]

    results: dict[str, dict] = {}
    failed_5xx: list[str] = []
    for name, fn in endpoints:
        res = _bench(fn, args.iterations, args.warmup)
        results[name] = res
        if res["status"] and res["status"] >= 500:
            failed_5xx.append(name)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        header = f"{'endpoint':40s} {'p50':>7s} {'p95':>7s} {'p99':>7s} {'mean':>7s} {'bytes':>7s} {'code':>4s}"
        print(header)
        print("-" * len(header))
        for name, r in results.items():
            print(f"{name:40s} {r['p50_ms']:7.1f} {r['p95_ms']:7.1f} {r['p99_ms']:7.1f} "
                  f"{r['mean_ms']:7.1f} {r['payload_avg_bytes']:7d} {r['status'] or '?':>4d}")

    if failed_5xx:
        print(f"\nERROR: {len(failed_5xx)} endpoint(s) returned 5xx: {', '.join(failed_5xx)}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
