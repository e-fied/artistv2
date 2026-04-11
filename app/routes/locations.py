"""Location profile CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.location import LocationAlias, LocationProfile

router = APIRouter(prefix="/locations")


@router.get("/")
def locations_page(request: Request, db: Session = Depends(get_db)):
    """Render the locations management page."""
    profiles = db.query(LocationProfile).order_by(LocationProfile.name).all()
    return request.app.state.templates.TemplateResponse(
        "locations/index.html",
        {
            "request": request,
            "profiles": profiles,
        },
    )


@router.get("/new")
def new_location_page(request: Request):
    """Render the new location form."""
    return request.app.state.templates.TemplateResponse(
        "locations/form.html",
        {
            "request": request,
            "profile": None,
            "editing": False,
        },
    )


@router.post("/new")
def create_location(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    radius_km: int = Form(50),
    country_code: str = Form("CA"),
    region_code: str = Form(""),
    is_default: bool = Form(False),
    aliases: str = Form(""),
):
    """Create a new location profile."""
    profile = LocationProfile(
        name=name.strip(),
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        country_code=country_code.strip().upper(),
        region_code=region_code.strip().upper() or None,
        is_default=is_default,
    )
    db.add(profile)
    db.flush()

    # Add aliases (comma-separated)
    for alias in aliases.split(","):
        alias = alias.strip()
        if alias:
            db.add(LocationAlias(
                location_profile_id=profile.id,
                alias_city=alias,
            ))

    db.commit()
    return RedirectResponse(url="/locations", status_code=303)


@router.get("/{profile_id}/edit")
def edit_location_page(
    request: Request, profile_id: int, db: Session = Depends(get_db)
):
    """Render the edit location form."""
    profile = db.query(LocationProfile).filter(LocationProfile.id == profile_id).first()
    if not profile:
        return RedirectResponse(url="/locations", status_code=303)

    return request.app.state.templates.TemplateResponse(
        "locations/form.html",
        {
            "request": request,
            "profile": profile,
            "editing": True,
        },
    )


@router.post("/{profile_id}/edit")
def update_location(
    request: Request,
    profile_id: int,
    db: Session = Depends(get_db),
    name: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    radius_km: int = Form(50),
    country_code: str = Form("CA"),
    region_code: str = Form(""),
    is_default: bool = Form(False),
    aliases: str = Form(""),
):
    """Update an existing location profile."""
    profile = db.query(LocationProfile).filter(LocationProfile.id == profile_id).first()
    if not profile:
        return RedirectResponse(url="/locations", status_code=303)

    profile.name = name.strip()
    profile.latitude = latitude
    profile.longitude = longitude
    profile.radius_km = radius_km
    profile.country_code = country_code.strip().upper()
    profile.region_code = region_code.strip().upper() or None
    profile.is_default = is_default

    # Replace aliases
    db.query(LocationAlias).filter(
        LocationAlias.location_profile_id == profile_id
    ).delete()
    for alias in aliases.split(","):
        alias = alias.strip()
        if alias:
            db.add(LocationAlias(
                location_profile_id=profile.id,
                alias_city=alias,
            ))

    db.commit()
    return RedirectResponse(url="/locations", status_code=303)


@router.post("/{profile_id}/delete")
def delete_location(profile_id: int, db: Session = Depends(get_db)):
    """Delete a location profile."""
    profile = db.query(LocationProfile).filter(LocationProfile.id == profile_id).first()
    if profile:
        db.delete(profile)
        db.commit()
    return RedirectResponse(url="/locations", status_code=303)
