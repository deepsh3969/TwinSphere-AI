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

    DATABASE_URL = _env("DATABASE_URL", f"sqlite:///{BACKEND_DIR / 'twinsphere.db'}")
    JWT_SECRET = _env("JWT_SECRET", "dev-only-change-me-in-production")
    JWT_ALGORITHM = "HS256"
    JWT_EXPIRE_MINUTES = int(_env("JWT_EXPIRE_MINUTES", "720"))

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
    RATE_LIMIT_PER_MINUTE = int(_env("RATE_LIMIT_PER_MINUTE", "120"))

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


settings = Settings()
