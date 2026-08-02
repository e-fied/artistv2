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
    artist_source_columns = _sqlite_columns("artist_sources")
    event_columns = _sqlite_columns("events")
    scan_source_result_columns = _sqlite_columns("scan_source_results")

    with engine.begin() as conn:
        if "paused_until_date" not in artist_columns:
            conn.execute(text("ALTER TABLE artists ADD COLUMN paused_until_date DATE"))
        if "health_status" not in artist_source_columns:
            conn.execute(text("ALTER TABLE artist_sources ADD COLUMN health_status VARCHAR(20) DEFAULT 'unknown'"))
            conn.execute(text(
                "UPDATE artist_sources SET health_status = CASE "
                "WHEN consecutive_failures > 0 THEN 'warning' "
                "WHEN last_success_at IS NOT NULL THEN 'healthy' ELSE 'unknown' END"
            ))
        if "last_health_code" not in artist_source_columns:
            conn.execute(text("ALTER TABLE artist_sources ADD COLUMN last_health_code VARCHAR(50)"))
        if "last_recovered_at" not in artist_source_columns:
            conn.execute(text("ALTER TABLE artist_sources ADD COLUMN last_recovered_at DATETIME"))
        if "is_attending" not in event_columns:
            conn.execute(text("ALTER TABLE events ADD COLUMN is_attending BOOLEAN DEFAULT 0"))
        if "notification_status" not in event_columns:
            conn.execute(text("ALTER TABLE events ADD COLUMN notification_status VARCHAR(30) DEFAULT 'pending'"))
            # Existing rows are already known to the user; do not blast them after migration.
            conn.execute(text(
                "UPDATE events SET notification_status = "
                "CASE WHEN is_attending = 1 THEN 'attending' ELSE 'sent' END"
            ))
        if "source_provider" not in event_columns:
            conn.execute(text("ALTER TABLE events ADD COLUMN source_provider VARCHAR(50)"))
        if "source_event_id" not in event_columns:
            conn.execute(text("ALTER TABLE events ADD COLUMN source_event_id VARCHAR(200)"))
        if "extraction_mode" not in scan_source_result_columns:
            conn.execute(text("ALTER TABLE scan_source_results ADD COLUMN extraction_mode VARCHAR(30)"))
        if "structured_provider" not in scan_source_result_columns:
            conn.execute(text("ALTER TABLE scan_source_results ADD COLUMN structured_provider VARCHAR(200)"))
        if "health_status" not in scan_source_result_columns:
            conn.execute(text("ALTER TABLE scan_source_results ADD COLUMN health_status VARCHAR(20)"))
        if "health_code" not in scan_source_result_columns:
            conn.execute(text("ALTER TABLE scan_source_results ADD COLUMN health_code VARCHAR(50)"))
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
