from __future__ import annotations

import logging
from typing import Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from app.config import DB_PATH

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler: Optional[BackgroundScheduler] = None


def create_scheduler() -> BackgroundScheduler:
    """Create and return the APScheduler instance with SQLite persistence."""
    global scheduler

    jobstores = {
        "default": SQLAlchemyJobStore(
            url=f"sqlite:///{DB_PATH}",
            engine_options={"connect_args": {"check_same_thread": False, "timeout": 30}}
        )
    }

    scheduler = BackgroundScheduler(
        jobstores=jobstores,
        job_defaults={
            "coalesce": True,       # Combine missed runs into one
            "max_instances": 1,     # Never run overlapping scans
            "misfire_grace_time": 3600,  # Allow 1h late execution
        },
    )

    return scheduler


def start_scheduler(interval_hours: int = 6) -> None:
    """Start the scheduler with the configured scan interval."""
    global scheduler

    if scheduler is None:
        scheduler = create_scheduler()

    # Remove existing scan job if present (to allow reconfiguration)
    try:
        scheduler.remove_job("scan_all_artists")
    except Exception:
        pass

    # Add the scan job
    scheduler.add_job(
        _run_scan_all,
        trigger="interval",
        hours=interval_hours,
        id="scan_all_artists",
        name="Scan all artists",
        replace_existing=True,
    )

    if not scheduler.running:
        scheduler.start()
        logger.info(f"Scheduler started: scanning every {interval_hours} hours")


def shutdown_scheduler() -> None:
    """Gracefully shutdown the scheduler."""
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down")


def _run_scan_all() -> None:
    """Execute the scheduled scan of all active artists."""
    logger.info("Scheduled scan triggered")
    try:
        from app.services.scanner import scan_all_artists
        scan_all_artists()
    except Exception as e:
        logger.error(f"Scheduled scan failed: {e}")
