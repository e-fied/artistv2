"""Tour Tracker v2 — FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import LOG_DIR, load_settings
from app.database import Base, SessionLocal, engine
from app.seed import seed_locations

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "app.log"),
        logging.StreamHandler(),
    ],
    force=True,
)
logger = logging.getLogger("tourtracker")


# ---------------------------------------------------------------------------
# Lifespan (replaces @app.on_event)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown hooks."""
    # ── Startup ──
    logger.info("Tour Tracker v2 starting up")

    # Create tables (Alembic will handle migrations later, but this ensures
    # tables exist on first run or dev without Alembic)
    Base.metadata.create_all(bind=engine)

    # Seed default data
    db = SessionLocal()
    try:
        seed_locations(db)
    finally:
        db.close()

    # Start scheduler
    from app.scheduler import start_scheduler
    settings = load_settings()
    start_scheduler(interval_hours=settings.scan_interval_hours)

    yield

    # ── Shutdown ──
    from app.scheduler import shutdown_scheduler
    shutdown_scheduler()
    logger.info("Tour Tracker v2 shut down")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

load_dotenv()

app = FastAPI(
    title="Tour Tracker",
    version="2.0.0",
    lifespan=lifespan,
)

# Static files
STATIC_DIR = Path(__file__).parent / "app" / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Templates
TEMPLATE_DIR = Path(__file__).parent / "app" / "templates"
TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def localtime(value, fmt: str = "%b %d, %I:%M %p") -> str:
    """Format UTC database timestamps in the configured app timezone."""
    if not value:
        return "Never"

    settings = load_settings()
    try:
        tz = ZoneInfo(settings.timezone)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("America/Vancouver")

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(tz).strftime(fmt)


templates.env.filters["localtime"] = localtime
app.state.templates = templates

# ---------------------------------------------------------------------------
# Register routers
# ---------------------------------------------------------------------------

from app.routes.health import router as health_router  # noqa: E402
from app.routes.dashboard import router as dashboard_router  # noqa: E402
from app.routes.settings_routes import router as settings_router  # noqa: E402
from app.routes.artists import router as artists_router  # noqa: E402
from app.routes.locations import router as locations_router  # noqa: E402
from app.routes.events import router as events_router  # noqa: E402
from app.routes.scans import router as scans_router  # noqa: E402
from app.routes.sources import router as sources_router  # noqa: E402
from app.routes.logs import router as logs_router  # noqa: E402

app.include_router(health_router)
app.include_router(dashboard_router)
app.include_router(settings_router)
app.include_router(artists_router)
app.include_router(locations_router)
app.include_router(events_router)
app.include_router(scans_router)
app.include_router(sources_router)
app.include_router(logs_router)
