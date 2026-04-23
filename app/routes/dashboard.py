"""Dashboard route — main landing page."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import load_settings
from app.database import get_db
from app.models.artist import Artist, ArtistSource
from app.models.event import Event
from app.models.scan import ScanRun
from app.services.artist_status import get_artist_coming_windows, resume_artists_ready_for_scan

router = APIRouter()


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db), view: str = "all"):
    """Render the main dashboard page."""
    settings = load_settings()
    resume_artists_ready_for_scan(db, as_of=date.today())

    # Artists with eager status info
    artists = db.query(Artist).order_by(Artist.name).all()
    coming_windows = get_artist_coming_windows(db, as_of=date.today())

    # Aggregate counts
    total_confirmed = (
        db.query(func.count(Event.id))
        .filter(Event.status == "confirmed")
        .scalar()
        or 0
    )
    total_possible = (
        db.query(func.count(Event.id))
        .filter(Event.status == "possible")
        .scalar()
        or 0
    )

    # Failing sources (3+ consecutive failures)
    failing_sources = (
        db.query(func.count(ArtistSource.id))
        .filter(ArtistSource.consecutive_failures >= 3)
        .scalar()
        or 0
    )

    # Last scan run
    last_scan = (
        db.query(ScanRun)
        .order_by(ScanRun.started_at.desc())
        .first()
    )

    # Per-artist source health summary
    artist_summaries = []
    for artist in artists:
        sources = db.query(ArtistSource).filter(ArtistSource.artist_id == artist.id).all()
        event_count = (
            db.query(func.count(Event.id))
            .filter(Event.artist_id == artist.id, Event.status == "confirmed")
            .scalar()
            or 0
        )
        possible_count = (
            db.query(func.count(Event.id))
            .filter(Event.artist_id == artist.id, Event.status == "possible")
            .scalar()
            or 0
        )

        most_recent_check = None
        for s in sources:
            if s.last_checked_at:
                if most_recent_check is None or s.last_checked_at > most_recent_check:
                    most_recent_check = s.last_checked_at

        coming = coming_windows.get(artist.id, {})
        summary = {
            "artist": artist,
            "sources": sources,
            "event_count": event_count,
            "possible_count": possible_count,
            "last_checked": most_recent_check,
            "future_confirmed_count": int(coming.get("future_confirmed_count", 0)),
            "next_event_date": coming.get("next_event_date"),
            "last_event_date": coming.get("last_event_date"),
            "is_coming": bool(coming),
        }

        if view == "coming" and not summary["is_coming"]:
            continue
        if view == "not_coming" and summary["is_coming"]:
            continue

        artist_summaries.append(summary)

    return request.app.state.templates.TemplateResponse(request=request, name="dashboard.html", context={
            "request": request,
            "artists": artist_summaries,
            "total_confirmed": total_confirmed,
            "total_possible": total_possible,
            "failing_sources": failing_sources,
            "last_scan": last_scan,
            "scan_interval_hours": settings.scan_interval_hours,
            "current_view": view,
            "now": datetime.now(),
        },
    )
