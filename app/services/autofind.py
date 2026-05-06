"""Auto-discovery of official artist/comedian tour websites using Gemini with Google Search."""

from __future__ import annotations

import logging
from typing import Optional

from google import genai
from google.genai import types
from pydantic import BaseModel, HttpUrl

from app.config import DEFAULT_GEMINI_AUTOFIND_MODELS, load_settings
from app.database import SessionLocal
from app.models.artist import Artist, ArtistSource

logger = logging.getLogger(__name__)

class AutoFindResult(BaseModel):
    """The structured result of our LLM search for an official tour site."""
    official_website: Optional[str]
    confidence: str  # high, medium, low
    notes: Optional[str]


def auto_find_tour_page(artist_id: int) -> bool:
    """Uses Gemini with Google Search grounding to find an artist's tour/events page."""
    settings = load_settings()
    if not settings.gemini_api_key:
        logger.error("Gemini API key is required for auto-finding tour pages.")
        return False

    db = SessionLocal()
    try:
        artist = db.query(Artist).filter(Artist.id == artist_id).first()
        if not artist:
            return False

        # First verify they don't already have an official_website source
        existing = db.query(ArtistSource).filter(
            ArtistSource.artist_id == artist_id,
            ArtistSource.source_type == "official_website",
        ).first()
        if existing:
            return True

        client = genai.Client(api_key=settings.gemini_api_key)
        
        prompt = f"""
Find the officially recognized main website, tour page, or live dates page for the {artist.artist_type} "{artist.name}".
Do not provide a ticketing site like Ticketmaster, LiveNation, Stubhub, or SeatGeek unless it's strictly their ONLY page.
Prioritize their official personal website (e.g. artistname.com/tour).
Return the exact URL and evaluate your confidence (high if it's clearly their main official site, low if unsure or it's a generic aggregator).
"""

        model_candidates = settings.gemini_autofind_models or list(DEFAULT_GEMINI_AUTOFIND_MODELS)
        temperature = settings.gemini_autofind_temperature

        response = None
        last_error = None
        for model in model_candidates:
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=AutoFindResult,
                        temperature=temperature,
                        tools=[{"google_search": {}}],  # Enable Google Search Grounding
                    ),
                )
                break
            except Exception as e:
                last_error = e
                logger.warning("Gemini model %s failed during auto-find, trying fallback: %s", model, e)

        if response is None:
            raise last_error or RuntimeError("Gemini auto-find request failed")

        if response.parsed and response.parsed.official_website:
            url = str(response.parsed.official_website)
            if "ticketmaster" not in url.lower() and "livenation" not in url.lower():
                # Add it as a source
                source = ArtistSource(
                    artist_id=artist.id,
                    source_type="official_website",
                    url=url,
                    fetch_mode="auto",
                    is_approved=True if response.parsed.confidence == "high" else False
                )
                db.add(source)
                db.commit()
                logger.info(f"Auto-found tour page for {artist.name}: {url}")
                return True
        return False

    except Exception as e:
        logger.error(f"Auto-find failed for artist {artist_id}: {e}")
        return False
    finally:
        db.close()
