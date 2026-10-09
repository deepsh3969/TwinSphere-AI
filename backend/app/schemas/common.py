from typing import Any, Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=4, max_length=128)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: str = Field(min_length=5, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    # NOTE (Phase 10 §9): no `role` field — self-service registration can only
    # ever create VIEWER accounts.  Privileged roles are granted via /api/users
    # by an ADMIN.  Extra JSON fields (e.g. "role": "ADMIN") are ignored.


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class SimulationCreate(BaseModel):
    # plain str: engine validation (spec A52) reports unknown scenarios as 400
    scenario: str = Field(min_length=1, max_length=40)
    target_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class RouteCalculate(BaseModel):
    """Phase 7 §25 — route calculation request (engine validates graph nodes)."""
    origin: str = Field(min_length=1, max_length=60)
    destination: str = Field(min_length=1, max_length=60)
    mode: str = Field(default="balanced", max_length=20)
    simulation_id: str | None = Field(default=None, max_length=60)
    people: float = Field(default=0.0, ge=0.0, le=100_000.0)
    alternatives: int = Field(default=1, ge=0, le=3)


class RouteRecalculate(BaseModel):
    mode: str | None = Field(default=None, max_length=20)
    reason: str = Field(default="manual", max_length=120)
    simulation_id: str | None = Field(default=None, max_length=60)


class IncidentCreate(BaseModel):
    title: str = Field(min_length=3, max_length=140)
    kind: str = Field(default="MANUAL", max_length=40)
    building_id: str | None = None
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    description: str = Field(default="", max_length=1000)


class AnalyzeRequest(BaseModel):
    question: str = Field(default="", max_length=500)
    focus: str | None = None          # legacy alias for mode (Phase 5)
    # Phase 8: explicit analysis mode (auto-detected when omitted)
    mode: str | None = Field(default=None, max_length=20)


class RecommendationDecision(BaseModel):
    """Phase 8 §24 — human-in-the-loop decision on an analyst recommendation."""
    decision: Literal["ACCEPTED", "DISMISSED"]


class SettingsUpdate(BaseModel):
    speed: float | None = Field(default=None, ge=0.1, le=10.0)
    sensor_interval: float | None = Field(default=None, ge=0.5, le=30.0)
    random_seed: int | None = Field(default=None, ge=0, le=1_000_000)


class RealtimeSpeed(BaseModel):
    """Phase 4 realtime simulator speed — membership in ALLOWED_SPEEDS is
    validated in the route so every invalid value gets a helpful 400."""
    speed: float


# ---------------------------------------------------------------- Phase 10

class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: str = Field(min_length=5, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    role: Literal["ADMIN", "OPERATOR", "ANALYST", "VIEWER"] = "VIEWER"


class UserUpdate(BaseModel):
    """Partial update — role and/or is_active.  Never accepts password or
    id fields (mass-assignment protection, Phase 10 §9)."""
    role: Literal["ADMIN", "OPERATOR", "ANALYST", "VIEWER"] | None = None
    is_active: bool | None = None
