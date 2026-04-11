"""Artist CRUD routes + scan + Ticketmaster attraction picker."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import load_settings
from app.database import get_db
from app.models.artist import Artist, ArtistLocation, ArtistSource
from app.models.location import LocationProfile

router = APIRouter(prefix="/artists")


@router.get("/new")
def add_artist_page(request: Request, db: Session = Depends(get_db)):
    """Render the add artist form."""
    locations = db.query(LocationProfile).order_by(LocationProfile.name).all()
    return request.app.state.templates.TemplateResponse(request=request, name="artists/form.html", context={
            "request": request,
            "artist": None,
            "locations": locations,
            "editing": False,
        },
    )


@router.post("/new")
def create_artist(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    artist_type: str = Form("music"),
    notes: str = Form(""),
    website_url: str = Form(""),
    location_ids: List[int] = Form(default=[]),
    travel_location_ids: List[int] = Form(default=[]),
):
    """Create a new artist."""
    artist = Artist(
        name=name.strip(),
        artist_type=artist_type,
        notes=notes.strip() or None,
    )
    db.add(artist)
    db.flush()

    # Create default Ticketmaster source
    tm_source = ArtistSource(
        artist_id=artist.id,
        source_type="ticketmaster",
        fetch_mode="auto",
    )
    db.add(tm_source)

    # Add website source if provided
    if website_url.strip():
        web_source = ArtistSource(
            artist_id=artist.id,
            source_type="official_website",
            url=website_url.strip(),
            fetch_mode="auto",
        )
        db.add(web_source)

    # Assign home locations
    for loc_id in location_ids:
        db.add(ArtistLocation(
            artist_id=artist.id,
            location_profile_id=loc_id,
            is_travel_city=False,
        ))

    # Assign travel locations
    for loc_id in travel_location_ids:
        if loc_id not in location_ids:
            db.add(ArtistLocation(
                artist_id=artist.id,
                location_profile_id=loc_id,
                is_travel_city=True,
            ))

    db.commit()
    return RedirectResponse(url="/", status_code=303)


@router.get("/{artist_id}/edit")
def edit_artist_page(
    request: Request, artist_id: int, db: Session = Depends(get_db)
):
    """Render the edit artist form."""
    artist = db.query(Artist).filter(Artist.id == artist_id).first()
    if not artist:
        return RedirectResponse(url="/", status_code=303)

    locations = db.query(LocationProfile).order_by(LocationProfile.name).all()
    artist_location_ids = [al.location_profile_id for al in artist.locations if not al.is_travel_city]
    artist_travel_ids = [al.location_profile_id for al in artist.locations if al.is_travel_city]

    return request.app.state.templates.TemplateResponse(request=request, name="artists/form.html", context={
            "request": request,
            "artist": artist,
            "locations": locations,
            "editing": True,
            "artist_location_ids": artist_location_ids,
            "artist_travel_ids": artist_travel_ids,
        },
    )


@router.post("/{artist_id}/edit")
def update_artist(
    request: Request,
    artist_id: int,
    db: Session = Depends(get_db),
    name: str = Form(...),
    artist_type: str = Form("music"),
    notes: str = Form(""),
    is_paused: bool = Form(False),
    notify_enabled: bool = Form(True),
    website_url: str = Form(""),
    location_ids: List[int] = Form(default=[]),
    travel_location_ids: List[int] = Form(default=[]),
):
    """Update an existing artist."""
    artist = db.query(Artist).filter(Artist.id == artist_id).first()
    if not artist:
        return RedirectResponse(url="/", status_code=303)

    artist.name = name.strip()
    artist.artist_type = artist_type
    artist.notes = notes.strip() or None
    artist.is_paused = is_paused
    artist.notify_enabled = notify_enabled

    # Update locations — clear and re-add
    db.query(ArtistLocation).filter(ArtistLocation.artist_id == artist_id).delete()
    for loc_id in location_ids:
        db.add(ArtistLocation(
            artist_id=artist.id,
            location_profile_id=loc_id,
            is_travel_city=False,
        ))
    for loc_id in travel_location_ids:
        if loc_id not in location_ids:
            db.add(ArtistLocation(
                artist_id=artist.id,
                location_profile_id=loc_id,
                is_travel_city=True,
            ))

    db.commit()
    return RedirectResponse(url="/", status_code=303)


@router.post("/{artist_id}/delete")
def delete_artist(artist_id: int, db: Session = Depends(get_db)):
    """Delete an artist and all related data."""
    artist = db.query(Artist).filter(Artist.id == artist_id).first()
    if artist:
        db.delete(artist)
        db.commit()
    return RedirectResponse(url="/", status_code=303)


@router.post("/{artist_id}/toggle-pause")
def toggle_pause(artist_id: int, db: Session = Depends(get_db)):
    """Toggle the paused state of an artist (HTMX)."""
    artist = db.query(Artist).filter(Artist.id == artist_id).first()
    if artist:
        artist.is_paused = not artist.is_paused
        db.commit()
    return RedirectResponse(url="/", status_code=303)


# ── Scan ───────────────────────────────────────────────────────────

@router.post("/{artist_id}/scan")
def scan_artist(artist_id: int):
    """Manual 'Check Now' for a single artist."""
    from app.services.scanner import scan_single_artist_manual

    result = scan_single_artist_manual(artist_id)
    return RedirectResponse(url="/", status_code=303)


@router.post("/scan-all")
def scan_all():
    """Manual 'Check All' button."""
    from app.services.scanner import scan_all_artists

    # Run in background thread to avoid blocking
    import threading
    t = threading.Thread(target=scan_all_artists, daemon=True)
    t.start()

    return RedirectResponse(url="/", status_code=303)


# ── Ticketmaster Attraction Picker ─────────────────────────────────

@router.get("/{artist_id}/tm-search")
def tm_search_page(request: Request, artist_id: int, db: Session = Depends(get_db)):
    """Search Ticketmaster for an artist's attraction and show picker."""
    artist = db.query(Artist).filter(Artist.id == artist_id).first()
    if not artist:
        return RedirectResponse(url="/", status_code=303)

    settings = load_settings()
    results = []

    if settings.ticketmaster_api_key:
        from app.services.ticketmaster import TicketmasterClient

        client = TicketmasterClient(settings.ticketmaster_api_key)
        results = client.search_attractions(artist.name, size=8)
        client.close()

    return request.app.state.templates.TemplateResponse(request=request, name="artists/tm_search.html", context={
            "request": request,
            "artist": artist,
            "results": results,
            "has_api_key": bool(settings.ticketmaster_api_key),
        },
    )


@router.post("/{artist_id}/tm-link")
def tm_link(
    artist_id: int,
    db: Session = Depends(get_db),
    attraction_id: str = Form(...),
    attraction_name: str = Form(...),
):
    """Link a Ticketmaster attraction to an artist."""
    artist = db.query(Artist).filter(Artist.id == artist_id).first()
    if artist:
        artist.ticketmaster_attraction_id = attraction_id
        artist.ticketmaster_attraction_name = attraction_name
        db.commit()
    return RedirectResponse(url=f"/artists/{artist_id}/edit", status_code=303)


@router.post("/{artist_id}/tm-unlink")
def tm_unlink(artist_id: int, db: Session = Depends(get_db)):
    """Unlink a Ticketmaster attraction from an artist."""
    artist = db.query(Artist).filter(Artist.id == artist_id).first()
    if artist:
        artist.ticketmaster_attraction_id = None
        artist.ticketmaster_attraction_name = None
        db.commit()
    return RedirectResponse(url=f"/artists/{artist_id}/edit", status_code=303)


# ── Sources ────────────────────────────────────────────────────────

@router.post("/{artist_id}/sources/add")
def add_source(
    artist_id: int,
    db: Session = Depends(get_db),
    source_type: str = Form("manual_url"),
    url: str = Form(""),
    fetch_mode: str = Form("auto"),
):
    """Add a new source to an artist."""
    source = ArtistSource(
        artist_id=artist_id,
        source_type=source_type,
        url=url.strip() or None,
        fetch_mode=fetch_mode,
    )
    db.add(source)
    db.commit()
    return RedirectResponse(url=f"/artists/{artist_id}/edit", status_code=303)


@router.post("/sources/{source_id}/delete")
def delete_source(source_id: int, db: Session = Depends(get_db)):
    """Delete a source."""
    source = db.query(ArtistSource).filter(ArtistSource.id == source_id).first()
    artist_id = source.artist_id if source else None
    if source:
        db.delete(source)
        db.commit()
    return RedirectResponse(url=f"/artists/{artist_id}/edit" if artist_id else "/", status_code=303)


@router.post("/{artist_id}/auto-find")
def auto_find_website(artist_id: int):
    """Trigger the LLM auto-finder for this artist's website."""
    # Run in background to avoid blocking
    from app.services.autofind import auto_find_tour_page
    import threading
    
    t = threading.Thread(target=auto_find_tour_page, args=(artist_id,), daemon=True)
    t.start()
    
    return RedirectResponse(url=f"/artists/{artist_id}/edit", status_code=303)
