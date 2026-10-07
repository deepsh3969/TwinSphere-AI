"""Fire scenario parameters, bands and derived status (Phase 6 §9/§13/§14/§19/§20).

All functions are pure and deterministic — no RNG, no I/O.
"""

from __future__ import annotations

from typing import Any

# §9 — fire intensity on the operator-facing 1-5 scale.
# The propagation model takes this level directly (`power = intensity / 5`),
# so 1 => slow spread (0.2x) ... 5 => very rapid spread (1.0x).
INTENSITY_LEVELS: dict[int, str] = {
    1: "LOW", 2: "MODERATE", 3: "HIGH", 4: "SEVERE", 5: "EXTREME",
}

# §9 — permitted wind directions.
WIND_DIRECTIONS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW", "NONE")

# §14 — smoke severity bands on the 0-100 index.
SMOKE_BANDS = (
    (0, 20, "CLEAR"), (21, 40, "LIGHT"), (41, 60, "MODERATE"),
    (61, 80, "HEAVY"), (81, 100, "CRITICAL"),
)

# Zone smoke units run 0..300 in the propagation model; the severity index
# normalises them to 0..100 for bands/UI.
SMOKE_UNITS_MAX = 300.0

# §19 — occupancy weight of a zone by its hazard status.
STATUS_WEIGHTS = {"FIRE": 1.0, "SMOKE": 0.6, "AFFECTED": 0.3, "NORMAL": 0.0}

# Legacy engines/tests pass intensity up to 10; the UI uses 1..5 (§9).
INTENSITY_MIN, INTENSITY_MAX = 1.0, 10.0


def intensity_label(level: float) -> str:
    """1..5 label (LOW..EXTREME); values above 5 clamp to EXTREME."""
    return INTENSITY_LEVELS.get(max(1, min(5, int(round(level)))), "EXTREME")


def severity_weight(status: str) -> float:
    return STATUS_WEIGHTS.get(status, 0.0)


def smoke_severity(smoke_units: float) -> int:
    """Zone smoke units (0..300) -> severity index (0..100)."""
    return int(max(0.0, min(100.0, smoke_units * 100.0 / SMOKE_UNITS_MAX)))


def smoke_band(severity: int) -> str:
    for lo, hi, name in SMOKE_BANDS:
        if lo <= severity <= hi:
            return name
    return "CRITICAL" if severity > 100 else "CLEAR"


def building_status(*, any_fire: bool = False, burning_zones: int = 0,
                    max_fire: float = 0.0, smoke_severity_idx: int = 0,
                    affected_zones: int = 0) -> str:
    """§20 — NORMAL -> ALERT -> DANGER -> CRITICAL from live fire state.

    State-driven, not time-gated: ignition opens at ALERT (or DANGER for hot
    fires >= 0.45), a second burning zone or deep burn (>= 0.7) escalates to
    CRITICAL; recovery walks the same ladder back down.
    """
    if burning_zones >= 2 or max_fire >= 0.7:
        return "CRITICAL"
    if burning_zones >= 1 and max_fire >= 0.45:
        return "DANGER"
    if any_fire or affected_zones >= 1 or smoke_severity_idx >= 6:
        return "ALERT"
    return "NORMAL"


def validate_fire_params(params: dict[str, Any], zones: dict[str, Any],
                         target_id: str | None) -> dict[str, Any]:
    """§52 — validate/normalise fire parameters. Raises ValueError on bad input."""
    out = dict(params)
    intensity = float(out.get("intensity", 5))
    if not (INTENSITY_MIN <= intensity <= INTENSITY_MAX):
        raise ValueError(
            f"Fire intensity must be between {INTENSITY_MIN:.0f} and {INTENSITY_MAX:.0f} "
            f"(1-5 recommended: 1=LOW ... 5=EXTREME); got {intensity}")
    out["intensity"] = intensity

    wind = str(out.get("wind", "E")).upper()
    if wind not in WIND_DIRECTIONS:
        raise ValueError(f"Wind direction must be one of {list(WIND_DIRECTIONS)}; got {out.get('wind')}")
    out["wind"] = wind

    ignition = out.get("ignition_zone") or out.get("initial_zone")
    if ignition is not None:
        target_zones = [z for z in zones.values()
                        if target_id is None or getattr(z, "building_id", None) == target_id]
        valid = {getattr(z, "id", z.get("id") if isinstance(z, dict) else None) for z in target_zones}
        if ignition not in valid:
            raise ValueError(
                f"Ignition zone '{ignition}' does not belong to building "
                f"'{target_id or 'campus'}'")
        out["ignition_zone"] = ignition

    if "initial_occupancy" in out and out["initial_occupancy"] is not None:
        occ = int(out["initial_occupancy"])
        if occ < 0:
            raise ValueError("initial_occupancy must be >= 0")
        out["initial_occupancy"] = occ
    return out
