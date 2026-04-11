"""LLM event extraction service using Gemini."""

from __future__ import annotations

import logging
from typing import Optional

from google import genai
from google.genai import types

from app.config import AppSettings
from app.schemas.gemini import ExtractionResult

logger = logging.getLogger(__name__)


class ExtractorService:
    """Service for extracting structured event data from text using Gemini."""

    def __init__(self, settings: AppSettings):
        self.settings = settings
        self.client = None
        if settings.gemini_api_key:
            try:
                self.client = genai.Client(api_key=settings.gemini_api_key)
            except Exception as e:
                logger.error(f"Failed to initialize Gemini: {e}")

    def extract_events(self, markdown: str, artist_name: str) -> Optional[ExtractionResult]:
        """Parse markdown to extract upcoming events for the given artist."""
        if not self.client:
            logger.error("Gemini API key not configured")
            return None

        prompt = f"""
You are an expert event data extractor.
Review the following text from an artist's tour website and extract all UPCOMING events.

Target Artist: {artist_name}

Rules:
1. Only extract events that have not already passed (if a year is missing, assume the next upcoming instance of that date).
2. If the date is 'TBD' or just an announcement, leave date as TBD and confidence as LOW.
3. Be precise with the venue and city.
4. If it's a festival, put the festival name in the event_name field, otherwise use the tour name or artist name.
5. Provide a short, verbatim evidence_text excerpt from the text that proves the event exists.
6. Assess confidence: HIGH if date/city/venue are clear, MEDIUM if missing details, LOW if just rumors/TBD.

Website Content:
----------------
{markdown}
"""
        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ExtractionResult,
                    temperature=0.1,
                ),
            )
            
            # The structured output is available in response.parsed
            if hasattr(response, 'parsed') and response.parsed:
                return response.parsed
            else:
                logger.error("Gemini returned success but no parsed structured output.")
                return None
                
        except Exception as e:
            logger.error(f"Gemini extraction failed: {e}")
            return None
