"""Road closure model (Phase 6 §42) — availability + traffic redistribution.

Pure helpers over the `state.roads` dict-of-dicts. No routing/A* here (Phase 7).
"""

from __future__ import annotations

from typing import Any

REDISTRIBUTION_STEP = 0.35


def close_road(roads: dict[str, dict], road_id: str,
               step: float = REDISTRIBUTION_STEP) -> dict[str, Any]:
    """Mark a road blocked and push traffic onto every other open road."""
    road = roads.get(road_id)
    if road is None:
        raise ValueError(f"Road '{road_id}' not found")
    road["blocked"] = True
    road["congestion"] = 0.0
    affected = []
    for other in roads.values():
        if other["id"] != road_id and not other.get("blocked"):
            other["congestion"] = min(1.0, other.get("congestion", 0.0) + step)
            affected.append(other["id"])
    return {"blocked": road_id, "affected": affected,
            "traffic_delta": step, "name": road.get("name", road_id)}


def reopen_road(roads: dict[str, dict], road_id: str) -> None:
    road = roads.get(road_id)
    if road:
        road["blocked"] = False
        road["congestion"] = 0.0
    for r in roads.values():
        r["congestion"] = 0.0


def road_impact(roads: dict[str, dict], road_id: str) -> dict[str, Any]:
    """Snapshot of closure impact for API/timeline payloads (§42)."""
    congested = sorted(
        (r["id"] for r in roads.values()
         if not r.get("blocked") and r.get("congestion", 0.0) > 0),
        key=lambda rid: -roads[rid].get("congestion", 0.0),
    )
    return {
        "road": road_id,
        "available": not roads.get(road_id, {}).get("blocked", False),
        "blocked_roads": [r["id"] for r in roads.values() if r.get("blocked")],
        "congested_roads": congested[:8],
        "max_congestion": max((r.get("congestion", 0.0) for r in roads.values()), default=0.0),
    }
