#!/usr/bin/env python3
"""Phase 12 — controlled load test for representative endpoints.

Uses only the Python standard library (http.client + threading) so no extra
dependency is required.  Designed for a local development machine: default
concurrency levels are 1 and 4 with 20 iterations each — deliberately modest
to avoid destabilising the host.

Usage:
    python backend/tests/load_test.py [--iterations 20] [--concurrency 1,4] [--json]

Requires a running server on 127.0.0.1:8000 (or --base URL).  Exits 1 if any
request returns HTTP >= 500.
"""
from __future__ import annotations

import argparse
import http.client
import json
import statistics
import sys
import threading
import time
from typing import Callable


def _percentile(samples: list[float], p: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    k = (len(ordered) - 1) * (p / 100.0)
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    frac = k - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def _worker(host: str, port: int, path: str, token: str | None,
            iterations: int, results: list, lock: threading.Lock) -> None:
    conn = http.client.HTTPConnection(host, port, timeout=30)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    for _ in range(iterations):
        t0 = time.perf_counter()
        try:
            conn.request("GET", path, headers=headers)
            resp = conn.getresponse()
            body = resp.read()
            status = resp.status
        except Exception:
            status = 0
            body = b""
        t1 = time.perf_counter()
        with lock:
            results.append((status, (t1 - t0) * 1000.0, len(body)))
    conn.close()


def _run_level(host: str, port: int, path: str, token: str | None,
               concurrency: int, iterations: int) -> dict:
    lock = threading.Lock()
    results: list[tuple[int, float, int]] = []
    threads = [
        threading.Thread(target=_worker,
                         args=(host, port, path, token, iterations, results, lock))
        for _ in range(concurrency)
    ]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    duration = time.perf_counter() - t0

    ok = [r for r in results if 200 <= r[0] < 300]
    err5xx = [r for r in results if r[0] >= 500]
    errOther = [r for r in results if r[0] and not (200 <= r[0] < 300) and r[0] < 500]
    latencies = [r[1] for r in results]
    return {
        "concurrency": concurrency,
        "requests": len(results),
        "duration_s": round(duration, 2),
        "success": len(ok),
        "errors_5xx": len(err5xx),
        "errors_other": len(errOther),
        "throughput_rps": round(len(results) / duration, 1) if duration > 0 else 0,
        "error_rate_pct": round(100.0 * (len(err5xx) + len(errOther)) / len(results), 2)
        if results else 0,
        "p50_ms": round(_percentile(latencies, 50), 2),
        "p95_ms": round(_percentile(latencies, 95), 2),
        "p99_ms": round(_percentile(latencies, 99), 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="TwinSphere load test")
    ap.add_argument("--base", default="127.0.0.1:8000")
    ap.add_argument("--iterations", type=int, default=20)
    ap.add_argument("--concurrency", default="1,4",
                    help="comma-separated concurrency levels, e.g. 1,4,8")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    host, _, port_s = args.base.partition(":")
    port = int(port_s or "8000")
    levels = [int(x) for x in args.concurrency.split(",") if x.strip()]

    # login once
    conn = http.client.HTTPConnection(host, port, timeout=10)
    conn.request("POST", "/api/auth/login",
                 body=json.dumps({"username": "operator", "password": "operator123"}),
                 headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    if resp.status != 200:
        print(f"login failed: {resp.status}", file=sys.stderr)
        return 1
    token = json.loads(resp.read())["access_token"]
    conn.close()

    endpoints = [
        ("GET /health", "/health", None),
        ("GET /api/campus", "/api/campus", token),
        ("GET /api/system/status", "/api/system/status", token),
        ("GET /api/simulations", "/api/simulations", token),
        ("GET /api/analytics/overview", "/api/analytics/overview", token),
    ]

    all_results: dict[str, list[dict]] = {}
    failed = False
    for name, path, tok in endpoints:
        levels_out = []
        for lvl in levels:
            r = _run_level(host, port, path, tok, lvl, args.iterations)
            levels_out.append(r)
            if r["errors_5xx"] > 0:
                failed = True
        all_results[name] = levels_out

    if args.json:
        print(json.dumps(all_results, indent=2))
    else:
        print(f"{'endpoint':32s} {'conc':>4s} {'reqs':>5s} {'ok':>5s} {'5xx':>4s} "
              f"{'rps':>6s} {'p50':>7s} {'p95':>7s} {'p99':>7s} {'err%':>6s}")
        print("-" * 96)
        for name, levels_out in all_results.items():
            for r in levels_out:
                print(f"{name:32s} {r['concurrency']:4d} {r['requests']:5d} "
                      f"{r['success']:5d} {r['errors_5xx']:4d} {r['throughput_rps']:6.1f} "
                      f"{r['p50_ms']:7.1f} {r['p95_ms']:7.1f} {r['p99_ms']:7.1f} "
                      f"{r['error_rate_pct']:6.2f}")
        print("\nNote: local single-machine results; not production capacity.")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
