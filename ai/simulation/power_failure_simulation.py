"""Power failure model (Phase 6 §41)."""

from __future__ import annotations

from typing import Any

# Building status chain (§41): NORMAL -> POWER_FAILURE -> BACKUP -> RECOVERY
POWER_STATUS_CHAIN = ("NORMAL", "POWER_FAILURE", "BACKUP_POWER", "RECOVERY")


def power_failure_effects(building: dict, tick: float) -> dict:
    """Services/energy state for a building that lost mains supply."""
    has_backup = building.get("has_backup_power", False)
    return {
        "power": False,
        "backup_power": has_backup,
        "energy": round(building.get("energy", 0.0) * (0.12 if has_backup else 0.0), 1),
        "status": "POWER_FAILURE",
        "services": ["HVAC", "lighting", "elevators", "lab equipment"] if not has_backup
        else ["HVAC (reduced)", "lighting (emergency)", "elevators (offline)"],
    }


def backup_state(building: Any) -> str:
    """'BACKUP' when running on generator, 'OFFLINE' without backup, 'ON' on mains."""
    power_ok = getattr(building, "power", True)
    if power_ok:
        return "ON"
    return "BACKUP" if getattr(building, "has_backup_power", False) else "OFFLINE"
