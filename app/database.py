"""SQLAlchemy engine, session, and Base for the Tour Tracker database."""

from __future__ import annotations

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DATA_DIR, DB_PATH


class Base(DeclarativeBase):
    """Declarative base for all models."""
    pass


# Ensure data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    echo=False,
    connect_args={"check_same_thread": False, "timeout": 30},
)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


def _sqlite_columns(table_name: str) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table_name})"))
        return {row[1] for row in rows}


def ensure_sqlite_schema() -> None:
    """Apply lightweight SQLite column adds for small forward-only migrations."""
    artist_columns = _sqlite_columns("artists")
    scan_source_result_columns = _sqlite_columns("scan_source_results")

    with engine.begin() as conn:
        if "paused_until_date" not in artist_columns:
            conn.execute(text("ALTER TABLE artists ADD COLUMN paused_until_date DATE"))
        if "llm_model" not in scan_source_result_columns:
            conn.execute(text("ALTER TABLE scan_source_results ADD COLUMN llm_model VARCHAR(80)"))
        if "llm_input_tokens" not in scan_source_result_columns:
            conn.execute(text("ALTER TABLE scan_source_results ADD COLUMN llm_input_tokens INTEGER DEFAULT 0"))
        if "llm_output_tokens" not in scan_source_result_columns:
            conn.execute(text("ALTER TABLE scan_source_results ADD COLUMN llm_output_tokens INTEGER DEFAULT 0"))
        if "llm_estimated_cost_usd" not in scan_source_result_columns:
            conn.execute(text("ALTER TABLE scan_source_results ADD COLUMN llm_estimated_cost_usd FLOAT DEFAULT 0.0"))
        if "llm_cost_is_estimated" not in scan_source_result_columns:
            conn.execute(text("ALTER TABLE scan_source_results ADD COLUMN llm_cost_is_estimated BOOLEAN DEFAULT 1"))


def get_db():
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
