import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_DB = ROOT / "backend" / "test_twinsphere.db"
if TEST_DB.exists():
    TEST_DB.unlink()
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB}")
os.environ.setdefault("RANDOM_SEED", "7")
# Phase 10: rate limiting is exercised explicitly in test_phase10_security with
# the limiter switched on; keep it off for the rest of the suite so repeated
# logins across tests never trip per-IP buckets.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

import pytest  # noqa: E402

from app.core.database import Base, engine, SessionLocal  # noqa: E402
from app.services.seed import init_db, seed_data  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _db():
    init_db()
    with SessionLocal() as db:
        seed_data(db)
    yield
    try:
        Base.metadata.drop_all(bind=engine)
    except Exception:
        pass
    if TEST_DB.exists():
        try:
            TEST_DB.unlink()
        except Exception:
            pass
