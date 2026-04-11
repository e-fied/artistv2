"""Ticketmaster Discovery API client.

Uses attractionId + latlong + radius for precise event matching.
Falls back to keyword search for attraction discovery.
"""

from __future__ import annotations

import logging
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

            return {
                "ticketmaster_event_id": raw.get("id", ""),
                "event_name": event_name,
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
