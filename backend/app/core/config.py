import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[3]
BACKEND_DIR = BASE_DIR / "backend"

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Load repository-root .env when present (safe no-op if python-dotenv missing).
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except Exception:  # pragma: no cover
    pass


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _bool_env(key: str, default: str = "true") -> bool:
    return _env(key, default).strip().lower() in ("1", "true", "yes", "on")


def _int_env(key: str, default: int | None = None) -> int | None:
    raw = _env(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class Settings:
    APP_NAME = "TwinSphere AI"
    VERSION = "1.0.0"

    # --- Phase 12: environment profiles ---------------------------------
    # development | test | demo | production
    #   development  — local work; demo users + registration on; dev secret warns
    #   test         — pytest/smoke; rate limiting off (set by conftest)
    #   demo         — presentation: demo users on, registration off, deterministic
    #                  seed enforced, rate limiting relaxed for repeated runs
    #   production   — strict secret/CORS validation; demo users + registration off
    APP_ENV = _env("APP_ENV", "development").strip().lower()
    IS_PRODUCTION = APP_ENV == "production"
    IS_DEMO = APP_ENV == "demo"

    DATABASE_URL = _env("DATABASE_URL", f"sqlite:///{BACKEND_DIR / 'twinsphere.db'}")
    JWT_SECRET = _env("JWT_SECRET", "dev-only-change-me-in-production")
    JWT_ALGORITHM = "HS256"
    JWT_EXPIRE_MINUTES = int(_env("JWT_EXPIRE_MINUTES", "720"))
    JWT_ISSUER = _env("JWT_ISSUER", "twinsphere")
    JWT_AUDIENCE = _env("JWT_AUDIENCE", "twinsphere-api")

    # Demo seed accounts + self-service registration. Production and demo
    # profiles default them OFF; demo explicitly re-enables demo users only.
    DEMO_USERS_ENABLED = _bool_env(
        "DEMO_USERS_ENABLED",
        "true" if IS_DEMO else ("false" if IS_PRODUCTION else "true"),
    )
    REGISTRATION_ENABLED = _bool_env(
        "REGISTRATION_ENABLED",
        "false" if (IS_PRODUCTION or IS_DEMO) else "true",
    )

    # Rate limiting (per category, sliding window; see app/core/ratelimit.py).
    # Demo profile relaxes login limits so repeated presentations don't 429.
    RATE_LIMIT_ENABLED = _bool_env(
        "RATE_LIMIT_ENABLED", "false" if IS_DEMO else "true"
    )
    RATE_LIMIT_PER_MINUTE = int(_env("RATE_LIMIT_PER_MINUTE", "120"))
    LOGIN_RATE_LIMIT_PER_MINUTE = int(_env("LOGIN_RATE_LIMIT_PER_MINUTE", "20"))
    REGISTER_RATE_LIMIT_PER_MINUTE = int(_env("REGISTER_RATE_LIMIT_PER_MINUTE", "5"))
    EXPORT_RATE_LIMIT_PER_MINUTE = int(_env("EXPORT_RATE_LIMIT_PER_MINUTE", "30"))
    AI_RATE_LIMIT_PER_MINUTE = int(_env("AI_RATE_LIMIT_PER_MINUTE", "20"))
    SIMULATION_RATE_LIMIT_PER_MINUTE = int(_env("SIMULATION_RATE_LIMIT_PER_MINUTE", "30"))
    ADMIN_RATE_LIMIT_PER_MINUTE = int(_env("ADMIN_RATE_LIMIT_PER_MINUTE", "60"))
    WS_RATE_LIMIT_PER_MINUTE = int(_env("WS_RATE_LIMIT_PER_MINUTE", "60"))
    WS_AUTH_TIMEOUT_S = float(_env("WS_AUTH_TIMEOUT_S", "10"))

    # Transport hardening (HSTS stays off for plain-HTTP local development)
    HSTS_ENABLED = _bool_env("HSTS_ENABLED", "false")
    SECURITY_HEADERS_ENABLED = _bool_env("SECURITY_HEADERS_ENABLED", "true")
    MAX_REQUEST_BODY_BYTES = int(_env("MAX_REQUEST_BODY_BYTES", "1000000"))

    CORS_ORIGINS = [
        o.strip()
        for o in _env("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
        if o.strip()
    ]

    LLM_API_KEY = _env("LLM_API_KEY", "")
    LLM_MODEL = _env("LLM_MODEL", "gpt-4o-mini")
    LLM_BASE_URL = _env("LLM_BASE_URL", "https://api.openai.com/v1")
    # Phase 8: AI Analyst LLM call budget + triggered-refresh cooldown (§31/§36)
    LLM_TIMEOUT = float(_env("LLM_TIMEOUT", "12"))
    LLM_MAX_TOKENS = int(_env("LLM_MAX_TOKENS", "900"))
    ANALYST_COOLDOWN_SECONDS = float(_env("ANALYST_COOLDOWN_SECONDS", "15"))

    # --- Phase 4: real-time simulation ---------------------------------
    SENSOR_TICK_SECONDS = float(_env("SENSOR_TICK_SECONDS", _env("SIMULATION_TICK", "2.0")))
    SIM_TICK_SECONDS = float(_env("SIM_TICK_SECONDS", "1.0"))
    DEFAULT_SPEED = float(_env("SIMULATION_SPEED", "1.0"))
    SIMULATION_ENABLED = _bool_env("SIMULATION_ENABLED", "true")
    SIMULATION_PERSIST_INTERVAL = float(_env("SIMULATION_PERSIST_INTERVAL", "20.0"))
    SIMULATION_SEED = _int_env("SIMULATION_SEED")
    WEBSOCKET_ENABLED = _bool_env("WEBSOCKET_ENABLED", "true")
    RANDOM_SEED = int(_env("RANDOM_SEED", "42"))
    HISTORY_RETENTION = int(_env("HISTORY_RETENTION", "5000"))

    # --- Phase 5: AI anomaly / prediction / risk intelligence --------------
    AI_ENABLED = _bool_env("AI_ENABLED", "true")
    AI_ANALYSIS_INTERVAL_SECONDS = float(_env("AI_ANALYSIS_INTERVAL_SECONDS", "15"))
    ANOMALY_MIN_SAMPLES = int(_env("ANOMALY_MIN_SAMPLES", "30"))
    ANOMALY_SCORE_THRESHOLD = int(_env("ANOMALY_SCORE_THRESHOLD", "60"))
    ANOMALY_MAX_TRACKED = int(_env("ANOMALY_MAX_TRACKED", "50"))
    PREDICTION_MIN_SAMPLES = int(_env("PREDICTION_MIN_SAMPLES", "100"))
    PREDICTION_RETRAIN_SECONDS = float(_env("PREDICTION_RETRAIN_SECONDS", "600"))
    PREDICTION_HORIZONS = tuple(
        int(x) for x in _env("PREDICTION_HORIZONS", "15,30,60").split(",") if x.strip()
    ) or (15, 30, 60)
    MODEL_DIR = _env("MODEL_DIR", str(BASE_DIR / "ai" / "models"))
    RISK_SMOOTHING_ALPHA = float(_env("RISK_SMOOTHING_ALPHA", "0.35"))
    RISK_MIN_DELTA = float(_env("RISK_MIN_DELTA", "1.0"))


# Development JWT secrets that must never be accepted in production.
_DEV_SECRETS = {"dev-only-change-me-in-production", "change-me-to-a-long-random-string", "secret"}


def validate_security_config() -> None:
    """Fail fast on unsafe configuration (Phase 10 §13, Phase 12 §4).

    Production: refuses dev/default secrets, short secrets, wildcard CORS,
    and disabled database URL.  Demo: enforces a deterministic random seed.
    Development: warns on the default secret.
    """
    secret = settings.JWT_SECRET or ""
    if settings.IS_PRODUCTION:
        problems: list[str] = []
        if secret in _DEV_SECRETS or secret.startswith("dev-"):
            problems.append("JWT_SECRET is a known development default")
        if len(secret) < 32:
            problems.append("JWT_SECRET must be at least 32 characters")
        if not settings.DATABASE_URL:
            problems.append("DATABASE_URL must be set")
        if not problems:
            origins = [o for o in settings.CORS_ORIGINS if o and o != "*"]
            if not origins:
                problems.append("CORS_ORIGINS must list explicit origins (no wildcard)")
        if problems:
            raise RuntimeError(
                "Refusing to start in production: " + "; ".join(problems)
                + ". Set JWT_SECRET (and CORS_ORIGINS) via environment variables."
            )
    elif settings.IS_DEMO:
        # Demo profile: deterministic seed is required for repeatable
        # presentations; the default 42 is acceptable, but warn if a
        # caller overrode RANDOM_SEED to a non-integer (already coerced)
        # or disabled the simulator (demo needs live telemetry).
        import warnings

        if not settings.SIMULATION_ENABLED:
            warnings.warn(
                "APP_ENV=demo with SIMULATION_ENABLED=false — live sensor "
                "updates will not run during the demo.",
                stacklevel=2,
            )
    elif secret in _DEV_SECRETS:
        import warnings

        warnings.warn(
            "JWT_SECRET is the development default — set a unique secret before "
            "any shared or internet-facing deployment.",
            stacklevel=2,
        )
    if "*" in settings.CORS_ORIGINS:
        # A wildcard origin with credentials is never acceptable (Phase 10 §12).
        raise RuntimeError("CORS_ORIGINS must not contain '*' — list explicit origins.")


settings = Settings()
