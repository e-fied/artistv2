"""Event history and review inbox routes."""

from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.artist import Artist
from app.models.event import Event, EventReview
from app.services.event_lifecycle import apply_event_action

router = APIRouter()


# ── Event History ──────────────────────────────────────────────────────────

@router.get("/events")
def events_page(
    request: Request,
    db: Session = Depends(get_db),
    status: str = "",
    artist_id: int = 0,
    view: str = "upcoming",
    page: int = 1,
):
    """Render actionable events first, with history available on demand."""
    allowed_views = {"upcoming", "going", "past", "all"}
    allowed_statuses = {"confirmed", "possible", "rejected", "expired"}
    view = view if view in allowed_views else "upcoming"
    status = status if status in allowed_statuses else ""
    page = max(page, 1)
    per_page = 40
    today = date.today()

    query = db.query(Event).options(joinedload(Event.artist))

    if view == "upcoming":
        query = query.filter(
            Event.event_date >= today,
            Event.status.in_(["confirmed", "possible"]),
        )
    elif view == "going":
        query = query.filter(Event.is_attending.is_(True), Event.event_date >= today)
    elif view == "past":
        query = query.filter(
            (Event.event_date < today) | (Event.status == "expired")
        )

    if status:
        query = query.filter(Event.status == status)
    if artist_id:
        query = query.filter(Event.artist_id == artist_id)

    total_events = query.count()
    if view in {"upcoming", "going"}:
        query = query.order_by(
            Event.event_date.asc().nullslast(),
            Event.event_time.asc().nullslast(),
            Event.artist_id.asc(),
        )
    else:
        query = query.order_by(
            Event.event_date.desc().nullslast(), Event.first_seen_at.desc()
        )

    events = query.offset((page - 1) * per_page).limit(per_page).all()
    artists = db.query(Artist).order_by(Artist.name).all()

    filter_params = {"view": view}
    if status:
        filter_params["status"] = status
    if artist_id:
        filter_params["artist_id"] = artist_id
    return_to = f"/events?{urlencode(filter_params)}"
    page_count = max(1, (total_events + per_page - 1) // per_page)

    def page_url(target_page: int) -> str:
        return f"{return_to}&page={target_page}"

    return request.app.state.templates.TemplateResponse(request=request, name="events/index.html", context={
            "request": request,
            "events": events,
            "artists": artists,
            "filter_status": status,
            "filter_artist_id": artist_id,
            "current_view": view,
            "total_events": total_events,
            "page": page,
            "page_count": page_count,
            "previous_url": page_url(page - 1) if page > 1 else None,
            "next_url": page_url(page + 1) if page < page_count else None,
            "return_to": return_to,
        },
    )


def _safe_events_return(return_to: str) -> str:
    """Keep action redirects inside the Events screen."""
    return return_to if return_to.startswith("/events?") else "/events?view=upcoming"


@router.post("/events/{event_id}/delete")
def delete_event(
    event_id: int,
    db: Session = Depends(get_db),
    return_to: str = Form("/events?view=upcoming"),
):
    """Delete one event so a future scan can rediscover it."""
    event = db.query(Event).filter(Event.id == event_id).first()
    if event:
        db.delete(event)
        db.commit()
    return RedirectResponse(url=_safe_events_return(return_to), status_code=303)


@router.post("/events/{event_id}/attending")
def toggle_event_attending(
    event_id: int,
    attending: bool = Form(False),
    return_to: str = Form("/events?view=upcoming"),
    db: Session = Depends(get_db),
):
    """Mark one event as attending without pausing future artist scans."""
    event = db.query(Event).filter(Event.id == event_id).first()
    if event:
        apply_event_action(db, event_id, "going" if attending else "not_going")
    return RedirectResponse(url=_safe_events_return(return_to), status_code=303)


@router.post("/events/delete-filtered")
def delete_filtered_events(
    db: Session = Depends(get_db),
    status: str = Form(""),
    artist_id: int = Form(0),
    return_to: str = Form("/events?view=upcoming"),
):
    """Delete events matching the current filter for testing scan rediscovery."""
    query = db.query(Event)
    if status:
        query = query.filter(Event.status == status)
    if artist_id:
        query = query.filter(Event.artist_id == artist_id)

    for event in query.all():
        db.delete(event)
    db.commit()
    return RedirectResponse(url=_safe_events_return(return_to), status_code=303)


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
    if action in {"confirm", "confirm_silent", "reject"}:
        apply_event_action(db, event_id, action)
    elif action == "mark_source_bad":
        apply_event_action(db, event_id, "reject")
        # TODO: Increment source failure count

    if action not in {"confirm", "confirm_silent", "reject", "mark_source_bad"}:
        db.commit()
    return RedirectResponse(url="/review", status_code=303)
