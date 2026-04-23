"""Artist status helpers for dashboard state and smart pausing."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.artist import Artist
from app.models.event import Event


def resume_artists_ready_for_scan(db: Session, as_of: date | None = None) -> int:
    """Auto-resume artists whose pause-until date has already passed."""
    as_of = as_of or date.today()
    artists = (
        db.query(Artist)
        .filter(
            Artist.is_paused == True,
            Artist.paused_until_date.is_not(None),
            Artist.paused_until_date < as_of,
        )
        .all()
    )

    for artist in artists:
        artist.is_paused = False
        artist.paused_until_date = None

    if artists:
        db.commit()

    return len(artists)


def get_artist_coming_windows(db: Session, as_of: date | None = None) -> dict[int, dict[str, object]]:
    """Return future confirmed event windows keyed by artist id."""
    as_of = as_of or date.today()
    rows = (
        db.query(
            Event.artist_id,
            func.count(Event.id),
            func.min(Event.event_date),
            func.max(Event.event_date),
        )
        .filter(
            Event.status == "confirmed",
            Event.event_date.is_not(None),
            Event.event_date >= as_of,
        )
        .group_by(Event.artist_id)
        .all()
    )

    return {
        artist_id: {
            "future_confirmed_count": count,
            "next_event_date": next_date,
            "last_event_date": last_date,
        }
        for artist_id, count, next_date, last_date in rows
    }


def pause_artist_until_past_events(
    db: Session,
    artist_id: int,
    as_of: date | None = None,
) -> date | None:
    """Pause an artist until their current local run has passed."""
    as_of = as_of or date.today()
    last_event_date = (
        db.query(func.max(Event.event_date))
        .filter(
            Event.artist_id == artist_id,
            Event.status == "confirmed",
            Event.event_date.is_not(None),
            Event.event_date >= as_of,
        )
        .scalar()
    )

    artist = db.query(Artist).filter(Artist.id == artist_id).first()
    if not artist:
        return None

    if last_event_date:
        artist.is_paused = True
        artist.paused_until_date = last_event_date
        db.commit()

    return last_event_date
