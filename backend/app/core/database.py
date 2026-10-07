from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def _default_literal(col, dialect) -> str | None:
    default = col.default
    if default is None or not getattr(default, "is_scalar", False):
        return None
    val = default.arg
    if isinstance(val, bool):
        return "1" if dialect.name == "sqlite" else ("TRUE" if val else "FALSE")
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        return "'" + val.replace("'", "''") + "'"
    return None


def ensure_schema() -> None:
    """Create missing tables and additively migrate existing ones (never drops data).

    Fresh databases get the full schema from ``Base.metadata``. Databases created by
    an earlier revision only gain missing tables, columns and indexes so that a
    previously-seeded dev database keeps working. Alembic remains the formal
    migration tool (``alembic upgrade head``) for production deployments.
    """
    inspector = inspect(engine)
    preexisting = set(inspector.get_table_names())
    Base.metadata.create_all(bind=engine, checkfirst=True)
    inspector = inspect(engine)
    dialect = engine.dialect

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in preexisting:
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing_cols:
                    continue
                coltype = col.type.compile(dialect)
                default = _default_literal(col, dialect)
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {coltype}'
                if default is not None:
                    ddl += f" DEFAULT {default}"
                    if not col.nullable:
                        ddl += " NOT NULL"
                conn.execute(text(ddl))
                if col.unique:
                    conn.execute(text(
                        f'CREATE UNIQUE INDEX IF NOT EXISTS "uq_{table.name}_{col.name}" '
                        f'ON "{table.name}" ("{col.name}")'
                    ))
            for idx in table.indexes:
                if not idx.name:
                    continue
                cols = ", ".join(f'"{c.name}"' for c in idx.columns)
                conn.execute(text(
                    f'CREATE INDEX IF NOT EXISTS "{idx.name}" ON "{table.name}" ({cols})'
                ))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def db_status() -> bool:
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return True
    except Exception:
        return False
