"""Application configuration.

Loads settings from environment variables, with optional overrides
from /app/data/settings.json for values changed via the Settings UI.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = Path(os.getenv("APP_DATA_DIR", "/app/data"))
SETTINGS_PATH = DATA_DIR / "settings.json"
DB_PATH = DATA_DIR / "tourtracker.db"
LOG_DIR = DATA_DIR / "logs"
DEBUG_DIR = DATA_DIR / "debug"


# ---------------------------------------------------------------------------
# Settings model
# ---------------------------------------------------------------------------

class AppSettings(BaseModel):
    """All configurable settings. Secrets come from env; the rest can
    be changed via the UI and persisted to settings.json."""

    # --- Secrets (env-only, never written to JSON) ---
    ticketmaster_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    firecrawl_api_key: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None

    # --- Crawl4AI ---
    crawl4ai_base_url: str = Field(
        default="http://crawl4ai:11235",
        description="Base URL of the Crawl4AI sidecar container",
    )

    # --- Scheduling ---
    scan_interval_hours: int = Field(default=6, description="Hours between scans")
    timezone: str = Field(default="America/Vancouver")

    # --- Notifications ---
    notify_confirmed: bool = Field(default=True, description="Telegram on confirmed events")
    notify_review_summary: bool = Field(default=True, description="Telegram summary for possible events")
    daily_digest_enabled: bool = Field(default=False)
    daily_digest_time: str = Field(default="21:00")

    # --- Debug capture ---
    debug_scan_capture: bool = Field(
        default=False,
        description="Store scan debug artifacts with prompts, responses, and extracted events",
    )
    debug_scan_retention: int = Field(
        default=25,
        description="Number of scan debug artifacts to keep",
    )

    # --- Internal ---
    secret_fields: List[str] = Field(
        default=[
            "ticketmaster_api_key",
            "gemini_api_key",
            "firecrawl_api_key",
            "telegram_bot_token",
            "telegram_chat_id",
        ],
        exclude=True,
    )

    def redacted(self, field_name: str) -> str:
        """Return a redacted version of a secret value for display."""
        val = getattr(self, field_name, None)
        if not val:
            return ""
        if len(val) <= 8:
            return "••••••••"
        return "••••••••" + val[-4:]

    def is_secret(self, field_name: str) -> bool:
        return field_name in self.secret_fields


# ---------------------------------------------------------------------------
# Load / save helpers
# ---------------------------------------------------------------------------

_PERSIST_EXCLUDE = {
    "ticketmaster_api_key",
    "gemini_api_key",
    "firecrawl_api_key",
    "telegram_bot_token",
    "telegram_chat_id",
    "secret_fields",
}


def _settings_from_env() -> dict:
    """Read secret values from environment variables."""
    return {
        "ticketmaster_api_key": os.getenv("TICKETMASTER_API_KEY"),
        "gemini_api_key": os.getenv("GEMINI_API_KEY"),
        "firecrawl_api_key": os.getenv("FIRECRAWL_API_KEY"),
        "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN"),
        "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID"),
        "crawl4ai_base_url": os.getenv("CRAWL4AI_BASE_URL", "http://crawl4ai:11235"),
    }


def load_settings() -> AppSettings:
    """Load settings: env secrets + JSON overrides for other fields."""
    data = _settings_from_env()

    if SETTINGS_PATH.exists():
        try:
            json_data = json.loads(SETTINGS_PATH.read_text())
            data.update(json_data)
        except Exception:
            pass  # Corrupted JSON → fall back to env-only

    return AppSettings(**data)


def save_settings(settings: AppSettings) -> None:
    """Persist non-secret settings to JSON."""
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = settings.model_dump(exclude=_PERSIST_EXCLUDE)
    SETTINGS_PATH.write_text(json.dumps(data, indent=2))
