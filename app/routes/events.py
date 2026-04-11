"""Event history and review inbox routes."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.artist import Artist
from app.models.event import Event, EventReview

router = APIRouter()


# ── Event History ──────────────────────────────────────────────────────────

@router.get("/events")
def events_page(
    request: Request,
    db: Session = Depends(get_db),
    status: str = "",
    artist_id: int = 0,
):
    """Render the event history page with optional filters."""
    query = db.query(Event).options(joinedload(Event.artist))

    if status:
        query = query.filter(Event.status == status)
    if artist_id:
        query = query.filter(Event.artist_id == artist_id)

    events = query.order_by(Event.event_date.desc().nullslast(), Event.first_seen_at.desc()).limit(200).all()
    artists = db.query(Artist).order_by(Artist.name).all()

    return request.app.state.templates.TemplateResponse(request=request, name="events/index.html", context={
            "request": request,
            "events": events,
            "artists": artists,
            "filter_status": status,
            "filter_artist_id": artist_id,
        },
    )


# ── Review Inbox ───────────────────────────────────────────────────────────

@router.get("/review")
def review_inbox(request: Request, db: Session = Depends(get_db)):
    """Show all events needing review (status=possible)."""
    events = (
        db.query(Event)
        .options(joinedload(Event.artist))
        .filter(Event.status == "possible")
        .order_by(Event.first_seen_at.desc())
        .all()
    )

    return request.app.state.templates.TemplateResponse(request=request, name="review/index.html", context={
            "request": request,
            "events": events,
        },
    )


@router.post("/review/{event_id}/action")
def review_action(
    event_id: int,
    db: Session = Depends(get_db),
    action: str = Form(...),
    notes: str = Form(""),
):
    """Process a review action on an event."""
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        return RedirectResponse(url="/review", status_code=303)

    # Record the review
    review = EventReview(
        event_id=event_id,
        action=action,
        notes=notes.strip() or None,
    )
    db.add(review)

    # Apply action
    if action == "confirm":
        event.status = "confirmed"
    elif action == "confirm_silent":
        event.status = "confirmed"
        event.notified = True  # mark as already notified to prevent sending
    elif action == "reject":
        event.status = "rejected"
    elif action == "mark_source_bad":
        event.status = "rejected"
        # TODO: Increment source failure count

    db.commit()
    return RedirectResponse(url="/review", status_code=303)
