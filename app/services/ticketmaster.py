"""Ticketmaster Discovery API client.

Uses attractionId + latlong + radius for precise event matching.
Falls back to keyword search for attraction discovery.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Dict, List, Optional
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://app.ticketmaster.com/discovery/v2"


class TicketmasterClient:
    """Client for Ticketmaster Discovery API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.Client(timeout=30.0)

    def close(self):
        self.client.close()

    # ── Attraction Search ──────────────────────────────────────────────

    def search_attractions(self, keyword: str, size: int = 5) -> List[Dict[str, Any]]:
        """Search for attractions by keyword.
        
        Returns a list of attraction dicts with id, name, type, etc.
        Used during artist setup to find the correct attractionId.
        """
        try:
            response = self.client.get(
                f"{BASE_URL}/attractions.json",
                params={
                    "apikey": self.api_key,
                    "keyword": keyword,
                    "size": size,
                    "locale": "*",
                },
            )
            response.raise_for_status()
            data = response.json()

            attractions = data.get("_embedded", {}).get("attractions", [])
            results = []
            for a in attractions:
                classifications = a.get("classifications", [{}])
                segment = classifications[0].get("segment", {}).get("name", "") if classifications else ""
                genre = classifications[0].get("genre", {}).get("name", "") if classifications else ""

                results.append({
                    "id": a.get("id", ""),
                    "name": a.get("name", ""),
                    "segment": segment,
                    "genre": genre,
                    "url": a.get("url", ""),
                    "image_url": self._get_best_image(a.get("images", [])),
                    "upcoming_events": a.get("upcomingEvents", {}).get("_total", 0),
                })

            return results

        except httpx.HTTPStatusError as e:
            logger.error(f"Ticketmaster attraction search failed: {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"Ticketmaster attraction search error: {e}")
            return []

    def find_best_attraction_match(
        self,
        artist_name: str,
        artist_type: Optional[str] = None,
        size: int = 10,
    ) -> Optional[Dict[str, Any]]:
        """Find a strong attraction match for an artist by normalized exact name."""
        attractions = self.search_attractions(artist_name, size=size)
        target = self._normalize_name(artist_name)
        if not target:
            return None

        exact_matches = [
            attraction for attraction in attractions
            if self._normalize_name(attraction.get("name", "")) == target
        ]
        if artist_type:
            exact_matches = [
                attraction for attraction in exact_matches
                if self._attraction_matches_artist_type(attraction, artist_type)
            ] or exact_matches

        return exact_matches[0] if exact_matches else None

    # ── Event Search ───────────────────────────────────────────────────

    def search_events_by_attraction(
        self,
        attraction_id: str,
        latlong: Optional[str] = None,
        radius: Optional[int] = None,
        country_code: Optional[str] = None,
        size: int = 50,
    ) -> List[Dict[str, Any]]:
        """Search events by attractionId with optional geo-filtering.

        Args:
            attraction_id: Ticketmaster attraction ID
            latlong: "lat,lon" string for geo-radius search
            radius: Radius in km
            country_code: ISO country code (CA, US, etc.)
            size: Max results per page
        """
        params: Dict[str, Any] = {
            "apikey": self.api_key,
            "attractionId": attraction_id,
            "size": size,
            "sort": "date,asc",
            "locale": "*",
        }

        if latlong and radius:
            params["latlong"] = latlong
            params["radius"] = radius
            params["unit"] = "km"

        if country_code:
            params["countryCode"] = country_code

        try:
            response = self.client.get(
                f"{BASE_URL}/events.json",
                params=params,
            )
            response.raise_for_status()
            data = response.json()

            events_raw = data.get("_embedded", {}).get("events", [])
            events = []
            for e in events_raw:
                event = self._parse_event(e)
                if event:
                    events.append(event)

            logger.info(
                f"Ticketmaster: found {len(events)} events for attraction {attraction_id}"
            )
            return events

        except httpx.HTTPStatusError as e:
            logger.error(
                f"Ticketmaster event search failed: {e.response.status_code} — {e.response.text[:200]}"
            )
            return []
        except Exception as e:
            logger.error(f"Ticketmaster event search error: {e}")
            return []

    def search_events_by_keyword(
        self,
        keyword: str,
        artist_name: Optional[str] = None,
        artist_type: Optional[str] = None,
        latlong: Optional[str] = None,
        radius: Optional[int] = None,
        country_code: Optional[str] = None,
        size: int = 30,
    ) -> List[Dict[str, Any]]:
        """Fallback: search events by keyword (less precise)."""
        params: Dict[str, Any] = {
            "apikey": self.api_key,
            "keyword": keyword,
            "size": size,
            "sort": "date,asc",
            "locale": "*",
        }

        if latlong and radius:
            params["latlong"] = latlong
            params["radius"] = radius
            params["unit"] = "km"

        if country_code:
            params["countryCode"] = country_code

        try:
            response = self.client.get(
                f"{BASE_URL}/events.json",
                params=params,
            )
            response.raise_for_status()
            data = response.json()

            events_raw = data.get("_embedded", {}).get("events", [])
            events = []
            for e in events_raw:
                if artist_name and not self._event_matches_artist(e, artist_name, artist_type):
                    continue
                event = self._parse_event(e)
                if event:
                    events.append(event)

            return events

        except Exception as e:
            logger.error(f"Ticketmaster keyword search error: {e}")
            return []

    # ── Parsing ────────────────────────────────────────────────────────

    def _parse_event(self, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse a raw Ticketmaster event into a normalized dict."""
        try:
            # Date
            dates = raw.get("dates", {}).get("start", {})
            date_str = dates.get("localDate")
            time_str = dates.get("localTime")

            # Venue
            venues = raw.get("_embedded", {}).get("venues", [{}])
            venue = venues[0] if venues else {}
            venue_name = venue.get("name", "Unknown Venue")
            city = venue.get("city", {}).get("name", "")
            region = venue.get("state", {}).get("stateCode", "") or venue.get("state", {}).get("name", "")
            country = venue.get("country", {}).get("countryCode", "")
            venue_lat = None
            venue_lon = None
            location = venue.get("location", {})
            if location:
                venue_lat = float(location.get("latitude", 0)) or None
                venue_lon = float(location.get("longitude", 0)) or None

            # Ticket URL
            ticket_url = raw.get("url", "")

            # Event name
            event_name = raw.get("name", "")
            attractions = raw.get("_embedded", {}).get("attractions", [])
            attraction_names = [a.get("name", "") for a in attractions if a.get("name")]

            return {
                "ticketmaster_event_id": raw.get("id", ""),
                "event_name": event_name,
                "attraction_names": attraction_names,
                "venue": venue_name,
                "city": city,
                "region": region,
                "country": country,
                "date": date_str,
                "time": time_str,
                "ticket_url": ticket_url,
                "venue_lat": venue_lat,
                "venue_lon": venue_lon,
                "source_type": "ticketmaster",
            }
        except Exception as e:
            logger.warning(f"Failed to parse Ticketmaster event: {e}")
            return None

    def _get_best_image(self, images: List[Dict]) -> str:
        """Get the best quality image URL."""
        if not images:
            return ""
        # Prefer 16:9 ratio, larger sizes
        for img in sorted(images, key=lambda i: i.get("width", 0), reverse=True):
            if img.get("ratio") == "16_9":
                return img.get("url", "")
        return images[0].get("url", "") if images else ""

    def _event_matches_artist(
        self,
        raw_event: Dict[str, Any],
        artist_name: str,
        artist_type: Optional[str],
    ) -> bool:
        """Filter loose keyword matches so ambiguous artist names don't explode."""
        normalized_artist = self._normalize_name(artist_name)
        artist_tokens = self._meaningful_tokens(artist_name)

        attractions = raw_event.get("_embedded", {}).get("attractions", [])
        attraction_names = [attraction.get("name", "") for attraction in attractions if attraction.get("name")]
        normalized_attractions = [self._normalize_name(name) for name in attraction_names]

        if any(name == normalized_artist for name in normalized_attractions):
            if not artist_type:
                return True
            return any(
                self._attraction_matches_artist_type(
                    {
                        "segment": attraction.get("classifications", [{}])[0].get("segment", {}).get("name", ""),
                        "genre": attraction.get("classifications", [{}])[0].get("genre", {}).get("name", ""),
                    },
                    artist_type,
                )
                for attraction in attractions
            ) or True

        # Single-word artists like ROSÉ need an exact attraction match to avoid
        # broad keyword collisions like Guns N' Roses, Rose Gray, sports teams, etc.
        if len(artist_tokens) <= 1:
            return False

        combined_text = " ".join([raw_event.get("name", ""), *attraction_names])
        combined_tokens = set(self._meaningful_tokens(combined_text))
        if not artist_tokens:
            return False
        return all(token in combined_tokens for token in artist_tokens)

    def _attraction_matches_artist_type(self, attraction: Dict[str, Any], artist_type: str) -> bool:
        segment = self._normalize_name(attraction.get("segment", ""))
        genre = self._normalize_name(attraction.get("genre", ""))
        if artist_type == "comedy":
            return "comedy" in segment or "comedy" in genre
        if artist_type == "music":
            return "music" in segment
        return True

    def _meaningful_tokens(self, value: str) -> List[str]:
        normalized = self._normalize_name(value)
        stopwords = {"the", "a", "an", "and", "with", "of", "live", "tour", "world"}
        return [token for token in normalized.split() if token and token not in stopwords]

    def _normalize_name(self, value: str) -> str:
        ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
        ascii_text = ascii_text.lower()
        ascii_text = re.sub(r"[^a-z0-9]+", " ", ascii_text)
        return re.sub(r"\s+", " ", ascii_text).strip()
