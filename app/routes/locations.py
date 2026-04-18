"""Location profile CRUD routes."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.location import LocationAlias, LocationProfile

router = APIRouter(prefix="/locations")


KNOWN_CITY_COORDS = {
    ("denver", "CO", "US"): (39.7392, -104.9903),
    ("vancouver", "BC", "CA"): (49.2827, -123.1207),
    ("seattle", "WA", "US"): (47.6062, -122.3321),
    ("portland", "OR", "US"): (45.5152, -122.6784),
    ("los angeles", "CA", "US"): (34.0522, -118.2437),
    ("san francisco", "CA", "US"): (37.7749, -122.4194),
    ("las vegas", "NV", "US"): (36.1716, -115.1391),
    ("new york", "NY", "US"): (40.7128, -74.0060),
    ("chicago", "IL", "US"): (41.8781, -87.6298),
    ("austin", "TX", "US"): (30.2672, -97.7431),
    ("toronto", "ON", "CA"): (43.6532, -79.3832),
}


def _city_name_from_profile(name: str) -> str:
    """Use the first part of a profile name as the geocoding city."""
    return name.split("/")[0].strip()


def _resolve_coordinates(
    name: str,
    region_code: str,
    country_code: str,
    latitude: Optional[float],
    longitude: Optional[float],
) -> tuple[Optional[float], Optional[float], Optional[str]]:
    """Use supplied coordinates or geocode a city/region/country."""
    if latitude is not None and longitude is not None:
        return latitude, longitude, None

    city = _city_name_from_profile(name).lower()
    region = region_code.strip().upper()
    country = country_code.strip().upper()
    known = KNOWN_CITY_COORDS.get((city, region, country))
    if known:
        return known[0], known[1], None

    query_parts = [_city_name_from_profile(name)]
    if region:
        query_parts.append(region)
    if country:
        query_parts.append(country)

    try:
        response = httpx.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": ", ".join(query_parts),
                "format": "jsonv2",
                "limit": 1,
            },
            headers={"User-Agent": "TourTracker/2.0 location helper"},
            timeout=10.0,
        )
        response.raise_for_status()
        results = response.json()
    except Exception as e:
        return None, None, f"Could not look up coordinates for {name}: {e}"

    if not results:
        return None, None, f"Could not find coordinates for {name}. Add latitude/longitude manually."

    return float(results[0]["lat"]), float(results[0]["lon"]), None


def _form_values(**kwargs):
    return SimpleNamespace(**kwargs)


@router.get("/")
def locations_page(request: Request, db: Session = Depends(get_db)):
    """Render the locations management page."""
    profiles = db.query(LocationProfile).order_by(LocationProfile.name).all()
    return request.app.state.templates.TemplateResponse(request=request, name="locations/index.html", context={
            "request": request,
            "profiles": profiles,
        },
    )


@router.get("/new")
def new_location_page(request: Request):
    """Render the new location form."""
    return request.app.state.templates.TemplateResponse(request=request, name="locations/form.html", context={
            "request": request,
            "profile": None,
            "editing": False,
            "form_values": None,
        },
    )


@router.post("/new")
def create_location(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    radius_km: int = Form(50),
    country_code: str = Form("CA"),
    region_code: str = Form(""),
    is_default: bool = Form(False),
    aliases: str = Form(""),
):
    """Create a new location profile."""
    resolved_lat, resolved_lon, error = _resolve_coordinates(
        name=name,
        region_code=region_code,
        country_code=country_code,
        latitude=latitude,
        longitude=longitude,
    )
    if error:
        return request.app.state.templates.TemplateResponse(
            request=request,
            name="locations/form.html",
            context={
                "request": request,
                "profile": None,
                "editing": False,
                "error": error,
                "form_values": _form_values(
                    name=name,
                    latitude=latitude,
                    longitude=longitude,
                    radius_km=radius_km,
                    country_code=country_code,
                    region_code=region_code,
                    is_default=is_default,
                    aliases=aliases,
                ),
            },
            status_code=400,
        )

    profile = LocationProfile(
        name=name.strip(),
        latitude=resolved_lat,
        longitude=resolved_lon,
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
    return RedirectResponse(url="/locations/", status_code=303)


@router.get("/{profile_id}/edit")
def edit_location_page(
    request: Request, profile_id: int, db: Session = Depends(get_db)
):
    """Render the edit location form."""
    profile = db.query(LocationProfile).filter(LocationProfile.id == profile_id).first()
    if not profile:
        return RedirectResponse(url="/locations/", status_code=303)

    return request.app.state.templates.TemplateResponse(request=request, name="locations/form.html", context={
            "request": request,
            "profile": profile,
            "editing": True,
            "form_values": None,
        },
    )


@router.post("/{profile_id}/edit")
def update_location(
    request: Request,
    profile_id: int,
    db: Session = Depends(get_db),
    name: str = Form(...),
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    radius_km: int = Form(50),
    country_code: str = Form("CA"),
    region_code: str = Form(""),
    is_default: bool = Form(False),
    aliases: str = Form(""),
):
    """Update an existing location profile."""
    profile = db.query(LocationProfile).filter(LocationProfile.id == profile_id).first()
    if not profile:
        return RedirectResponse(url="/locations/", status_code=303)

    resolved_lat, resolved_lon, error = _resolve_coordinates(
        name=name,
        region_code=region_code,
        country_code=country_code,
        latitude=latitude,
        longitude=longitude,
    )
    if error:
        return request.app.state.templates.TemplateResponse(
            request=request,
            name="locations/form.html",
            context={
                "request": request,
                "profile": profile,
                "editing": True,
                "error": error,
                "form_values": _form_values(
                    name=name,
                    latitude=latitude,
                    longitude=longitude,
                    radius_km=radius_km,
                    country_code=country_code,
                    region_code=region_code,
                    is_default=is_default,
                    aliases=aliases,
                ),
            },
            status_code=400,
        )

    profile.name = name.strip()
    profile.latitude = resolved_lat
    profile.longitude = resolved_lon
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
    return RedirectResponse(url="/locations/", status_code=303)


@router.post("/{profile_id}/delete")
def delete_location(profile_id: int, db: Session = Depends(get_db)):
    """Delete a location profile."""
    profile = db.query(LocationProfile).filter(LocationProfile.id == profile_id).first()
    if profile:
        db.delete(profile)
        db.commit()
    return RedirectResponse(url="/locations/", status_code=303)
