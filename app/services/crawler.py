"""Web content extraction service using Crawl4AI and Firecrawl fallback."""

from __future__ import annotations

import logging
import json
import re
from datetime import datetime, timezone
from html import unescape
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from firecrawl import FirecrawlApp

from app.config import AppSettings

logger = logging.getLogger(__name__)


def hash_content(text: str) -> str:
    """Generate a SHA-256 hash of the content to detect changes."""
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class CrawlerService:
    """Service for fetching and cleaning markdown from tour pages."""

    def __init__(self, settings: AppSettings):
        self.settings = settings
        self.crawl4ai_url = settings.crawl4ai_base_url.rstrip("/")
        
        self.firecrawl = None
        if settings.firecrawl_api_key:
            try:
                self.firecrawl = FirecrawlApp(api_key=settings.firecrawl_api_key)
            except Exception as e:
                logger.error(f"Failed to initialize Firecrawl: {e}")

    def fetch_markdown(self, url: str, preferred_crawler: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
        """Fetch content from a URL. Returns (markdown_text, crawler_used)."""
        logger.info(f"Crawling {url}...")
        
        # Try preferred crawler first, then fallback
        crawlers_to_try = []
        if preferred_crawler == "firecrawl" and self.firecrawl:
            crawlers_to_try = ["firecrawl", "crawl4ai"]
        else:
            crawlers_to_try = ["crawl4ai", "firecrawl"]

        for crawler in crawlers_to_try:
            markdown = None
            if crawler == "crawl4ai":
                markdown = self._fetch_crawl4ai(url)
            elif crawler == "firecrawl" and self.firecrawl:
                markdown = self._fetch_firecrawl(url)

            if markdown is not None:
                enriched_markdown = self._append_embedded_events(url, markdown)
                if enriched_markdown.strip():
                    return enriched_markdown, crawler
            
            logger.warning(f"{crawler} failed for {url}. Falling back...")

        logger.error(f"All crawlers failed for {url}")
        return None, None

    def _fetch_crawl4ai(self, url: str) -> Optional[str]:
        """Fetch URL using Crawl4AI docker API."""
        try:
            with httpx.Client(timeout=45.0) as client:
                response = client.post(
                    f"{self.crawl4ai_url}/crawl",
                    json={
                        "urls": [url],
                        "browser_config": {
                            "headless": True,
                            "verbose": False
                        },
                        "crawler_config": {
                            "word_count_threshold": 10
                        }
                    }
                )
                response.raise_for_status()
                data = response.json()
                
                results = data.get("results")
                if results and len(results) > 0:
                    md_val = results[0].get("markdown")
                    return self._crawl_markdown_to_text(md_val)
                # Fallback structure just in case
                if "markdown" in data:
                    md_val = data["markdown"]
                    return self._crawl_markdown_to_text(md_val)
                
                logger.error(f"Crawl4AI returned success but no markdown found: {data.keys()}")
                return None
        except Exception as e:
            logger.error(f"Crawl4AI error: {e}")
            return None

    def _crawl_markdown_to_text(self, markdown_value) -> Optional[str]:
        """Normalize Crawl4AI markdown values without leaking Python dict text."""
        if markdown_value is None:
            return None

        if isinstance(markdown_value, str):
            return markdown_value

        if isinstance(markdown_value, dict):
            for key in ("fit_markdown", "raw_markdown", "markdown_with_citations", "raw"):
                value = markdown_value.get(key)
                if isinstance(value, str) and value.strip():
                    return value
            return ""

        return str(markdown_value)

    def _fetch_firecrawl(self, url: str) -> Optional[str]:
        """Fetch URL using Firecrawl API."""
        try:
            scrape_result = self.firecrawl.scrape_url(
                url, 
                params={'formats': ['markdown']}
            )
            return scrape_result.get("markdown")
        except Exception as e:
            logger.error(f"Firecrawl error: {e}")
            return None

    def _append_embedded_events(self, url: str, markdown: str) -> str:
        """Append event data exposed outside Crawl4AI's rendered markdown."""
        embedded_markdown = self._fetch_embedded_events_markdown(url)
        if not embedded_markdown:
            return markdown

        return f"{markdown}\n\n{embedded_markdown}"

    def _fetch_embedded_events_markdown(self, url: str) -> Optional[str]:
        """Fetch events from common structured-data and widget backends."""
        try:
            with httpx.Client(timeout=20.0, follow_redirects=True) as client:
                page_response = client.get(url)
                page_response.raise_for_status()
                page_html = page_response.text

                sections = []
                is_punchup = urlparse(url).netloc.lower() == "punchup.live"

                try:
                    json_ld_markdown = self._json_ld_events_to_markdown(page_html)
                    if json_ld_markdown:
                        sections.append(json_ld_markdown)
                except Exception as e:
                    logger.debug(f"JSON-LD event enrichment failed for {url}: {e}")

                if is_punchup:
                    try:
                        punchup_markdown = self._fetch_punchup_api_events_markdown(client, url, page_html)
                        if punchup_markdown:
                            sections.append(punchup_markdown)
                    except Exception as e:
                        logger.debug(f"Punchup event enrichment failed for {url}: {e}")

                try:
                    artist_id = self._find_seated_artist_id(client, url, page_html)
                    if artist_id:
                        seated_markdown = self._fetch_seated_api_events_markdown(client, artist_id)
                        if seated_markdown:
                            sections.append(seated_markdown)
                except Exception as e:
                    logger.debug(f"Seated event enrichment failed for {url}: {e}")

                if not is_punchup:
                    try:
                        punchup_markdown = self._fetch_punchup_api_events_markdown(client, url, page_html)
                        if punchup_markdown:
                            sections.append(punchup_markdown)
                    except Exception as e:
                        logger.debug(f"Punchup event enrichment failed for {url}: {e}")

                return "\n\n".join(sections) if sections else None
        except Exception as e:
            logger.warning(f"Embedded event enrichment failed for {url}: {e}")
            return None

    def _fetch_seated_api_events_markdown(self, client: httpx.Client, artist_id: str) -> Optional[str]:
        """Fetch events directly from Seated's widget API."""
        api_response = client.get(
            f"https://cdn.seated.com/api/tour/{artist_id}",
            params={"include": "tour-events"},
            headers={"X-Client-Version": "tourtracker"},
        )
        api_response.raise_for_status()
        return self._seated_api_to_markdown(api_response.json())

    def _find_seated_artist_id(self, client: httpx.Client, page_url: str, page_html: str) -> Optional[str]:
        """Find Seated's artist id in initial HTML or same-origin Nuxt chunks."""
        match = re.search(r'data-artist-id=["\']([^"\']+)["\']', page_html)
        if match:
            return unescape(match.group(1))

        parsed_url = urlparse(page_url)
        same_origin = f"{parsed_url.scheme}://{parsed_url.netloc}"
        script_paths = set(re.findall(r'(?:src|href)=["\']([^"\']+\.js)["\']', page_html))

        for script_path in script_paths:
            script_url = urljoin(page_url, unescape(script_path))
            parsed_script_url = urlparse(script_url)
            if f"{parsed_script_url.scheme}://{parsed_script_url.netloc}" != same_origin:
                continue

            try:
                script_response = client.get(script_url)
                script_response.raise_for_status()
            except Exception as e:
                logger.debug(f"Failed to fetch script while looking for Seated artist id: {script_url}: {e}")
                continue

            match = re.search(r'data-artist-id["\']?\s*:\s*["\']([^"\']+)["\']', script_response.text)
            if match:
                return unescape(match.group(1))

            match = re.search(r'data-artist-id["\']?\s*,\s*["\']([^"\']+)["\']', script_response.text)
            if match:
                return unescape(match.group(1))

        return None

    def _fetch_punchup_api_events_markdown(
        self,
        client: httpx.Client,
        page_url: str,
        page_html: str,
    ) -> Optional[str]:
        """Fetch Punchup's client-loaded tour events from its shows API."""
        parsed_url = urlparse(page_url)
        if parsed_url.netloc.lower() != "punchup.live":
            return None

        comedian_id = self._find_punchup_comedian_id(page_url, page_html)
        if not comedian_id:
            return None

        start_datetime = (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        api_response = client.get(
            "https://punchup.live/api/shows",
            params={
                "comedianId": comedian_id,
                "startDatetime": start_datetime,
            },
            headers={
                "Accept": "application/json",
                "X-Client-Version": "tourtracker",
            },
        )
        api_response.raise_for_status()
        return self._punchup_api_to_markdown(api_response.json(), page_url, comedian_id)

    def _find_punchup_comedian_id(self, page_url: str, page_html: str) -> Optional[str]:
        """Find Punchup's comedian id in initial Next.js HTML/RSC data."""
        parsed_url = urlparse(page_url)
        slug = parsed_url.path.strip("/").split("/", 1)[0]
        uuid_pattern = r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"

        patterns = [
            rf'\\?"comedian\\?"\s*:\s*\{{\s*\\?"id\\?"\s*:\s*\\?"{uuid_pattern}\\?"',
        ]
        if slug:
            escaped_slug = re.escape(slug)
            patterns.extend(
                [
                    rf'\\?"id\\?"\s*:\s*\\?"{uuid_pattern}\\?".{{0,500}}?\\?"slug\\?"\s*:\s*\\?"{escaped_slug}\\?"',
                    rf'\\?"slug\\?"\s*:\s*\\?"{escaped_slug}\\?".{{0,500}}?\\?"id\\?"\s*:\s*\\?"{uuid_pattern}\\?"',
                ]
            )

        for pattern in patterns:
            match = re.search(pattern, page_html, flags=re.DOTALL)
            if match:
                return unescape(match.group(1))

        return None

    def _json_ld_events_to_markdown(self, page_html: str) -> Optional[str]:
        """Convert embedded schema.org Event JSON-LD into LLM-friendly lines."""
        events = []
        scripts = re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            page_html,
            flags=re.IGNORECASE | re.DOTALL,
        )

        for script in scripts:
            payload = unescape(script).strip()
            if not payload:
                continue

            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue

            events.extend(self._collect_json_ld_events(data))

        if not events:
            return None

        lines = ["Structured event data from page JSON-LD:"]
        for event in events:
            name = self._json_ld_text(event.get("name")) or "Event"
            date = self._json_ld_text(event.get("startDate")) or "Date TBD"
            location = event.get("location") or {}
            venue = ""
            address = ""
            if isinstance(location, dict):
                venue = self._json_ld_text(location.get("name"))
                address = self._json_ld_address(location.get("address"))
            offers = event.get("offers") or {}
            ticket_url = self._json_ld_text(offers.get("url")) if isinstance(offers, dict) else ""

            line = f"- {date} | {name}"
            if venue:
                line = f"{line} | {venue}"
            if address:
                line = f"{line} | {address}"
            if ticket_url:
                line = f"{line} | Tickets: {ticket_url}"
            lines.append(line)

        return "\n".join(lines)

    def _collect_json_ld_events(self, data) -> list[dict]:
        """Recursively collect schema.org Event-ish objects from JSON-LD."""
        found = []
        if isinstance(data, list):
            for item in data:
                found.extend(self._collect_json_ld_events(item))
            return found

        if not isinstance(data, dict):
            return found

        item_type = data.get("@type")
        types = item_type if isinstance(item_type, list) else [item_type]
        if any(isinstance(t, str) and t.lower().endswith("event") for t in types):
            found.append(data)

        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in data:
                found.extend(self._collect_json_ld_events(data[key]))

        return found

    def _json_ld_text(self, value) -> str:
        """Return a readable scalar from common JSON-LD value shapes."""
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for key in ("name", "url", "@id"):
                if value.get(key):
                    return str(value[key])
        if isinstance(value, list):
            return ", ".join(filter(None, (self._json_ld_text(item) for item in value)))
        return str(value)

    def _json_ld_address(self, value) -> str:
        """Return a readable address from schema.org address shapes."""
        if isinstance(value, str):
            return value
        if not isinstance(value, dict):
            return ""

        parts = [
            value.get("streetAddress"),
            value.get("addressLocality"),
            value.get("addressRegion"),
            value.get("postalCode"),
            value.get("addressCountry"),
        ]
        return ", ".join(str(part) for part in parts if part)

    def diagnose_event_content(self, url: str, markdown: str, extracted_count: int) -> Optional[str]:
        """Explain likely reasons a successful crawl produced no events."""
        if extracted_count > 0:
            return None

        text = (markdown or "").strip()
        lower_text = text.lower()
        text_len = len(text)

        bot_patterns = [
            "access denied",
            "captcha",
            "cf-chl",
            "cloudflare",
            "enable cookies",
            "forbidden",
            "robot",
            "unusual traffic",
            "verify you are human",
        ]
        if any(pattern in lower_text for pattern in bot_patterns):
            return "Crawler reached the page, but the content looks like a bot protection or access-denied page."

        no_event_patterns = [
            "no upcoming events",
            "no tour dates",
            "no shows",
            "nothing scheduled",
            "check back soon",
        ]
        if any(pattern in lower_text for pattern in no_event_patterns):
            return "Crawler reached the page and it appears to say there are no upcoming dates."

        date_hits = re.findall(
            r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b",
            lower_text,
        )
        event_words = ("tour", "tickets", "venue", "show", "event", "dates")
        event_word_hits = sum(1 for word in event_words if word in lower_text)

        if text_len < 500:
            return "Crawler returned very little page text. The page may be blank, blocked, or rendering tour dates after load."

        if event_word_hits >= 2 and not date_hits:
            return "Crawler found tour-related text but no date-like content. The listing may be loaded by JavaScript, a ticketing widget, or an unsupported API."

        if not date_hits:
            return "Crawler fetched readable content, but no date-like text was found for extraction."

        return "Crawler found date-like text, but Gemini extracted zero events. The page may use an unsupported format or the dates may not be for this artist."

    def _seated_api_to_markdown(self, data: dict) -> Optional[str]:
        """Convert Seated JSON:API tour events into LLM-friendly markdown."""
        included = data.get("included") or []
        events = [item for item in included if item.get("type") == "tour-events"]
        if not events:
            return None

        artist_name = ((data.get("data") or {}).get("attributes") or {}).get("name", "Artist")
        lines = [f"Seated widget tour events for {artist_name}:"]

        for event in events:
            attrs = event.get("attributes") or {}
            date = attrs.get("starts-at-date-local") or attrs.get("starts-at-short") or "Date TBD"
            venue = attrs.get("venue-name") or "Venue TBD"
            address = attrs.get("formatted-address") or ""
            details = attrs.get("details") or ""
            ticket_url = f"https://link.seated.com/{event.get('id')}" if event.get("id") else ""

            line = f"- {date} | {venue}"
            if address:
                line = f"{line} | {address}"
            if details:
                line = f"{line} | {details}"
            if ticket_url:
                line = f"{line} | Tickets: {ticket_url}"
            lines.append(line)

        return "\n".join(lines)

    def _punchup_api_to_markdown(self, data, page_url: str, comedian_id: str) -> Optional[str]:
        """Convert Punchup show API events into LLM-friendly markdown."""
        if not isinstance(data, list):
            return None

        visible_events = []
        for show in data:
            if not isinstance(show, dict):
                continue

            show_comedians = show.get("show_comedians") or []
            matching_entries = [
                entry
                for entry in show_comedians
                if isinstance(entry, dict) and entry.get("id") == comedian_id
            ]
            if matching_entries and matching_entries[0].get("hidden_from_comedian_page") is not False:
                continue

            visible_events.append(show)

        if not visible_events:
            return None

        artist_name = (
            self._punchup_text((visible_events[0].get("comedian") or {}).get("display_name"))
            or self._punchup_text((visible_events[0].get("comedian") or {}).get("name"))
            or "Artist"
        )
        lines = [f"Punchup API tour events for {artist_name}:"]

        for show in visible_events:
            event_id = self._punchup_text(show.get("id"))
            date = self._punchup_text(show.get("datetime")) or "Date TBD"
            title = self._punchup_text(show.get("title")) or artist_name
            venue = self._punchup_text(show.get("venue")) or "Venue TBD"
            location = self._punchup_text(show.get("location"))
            metadata = self._punchup_text(show.get("metadata_text"))
            ticket_url = self._punchup_text(show.get("ticket_link"))
            vip_ticket_url = self._punchup_text(show.get("vip_ticket_link"))
            presale_code = self._punchup_text(show.get("presale_code"))
            event_url = urljoin(page_url, f"/e/{event_id}") if event_id else ""

            line = f"- {date} | {title} | {venue}"
            if location:
                line = f"{line} | {location}"
            if metadata:
                line = f"{line} | {metadata}"
            if show.get("is_sold_out"):
                line = f"{line} | Sold out"
            if presale_code:
                line = f"{line} | Presale code: {presale_code}"
            if ticket_url:
                line = f"{line} | Tickets: {ticket_url}"
            if vip_ticket_url:
                line = f"{line} | VIP tickets: {vip_ticket_url}"
            if event_url:
                line = f"{line} | Event page: {event_url}"
            lines.append(line)

        return "\n".join(lines)

    def _punchup_text(self, value) -> str:
        """Return readable text from Punchup API scalar values."""
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        return str(value).strip()

    def clean_markdown(self, markdown: str) -> str:
        """Strip links, images, and boilerplate from markdown to save tokens."""
        if not markdown:
            return ""
        
        lines = markdown.split("\n")
        cleaned_lines = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Very basic cleanup — the LLM handles noise well, 
            # we mainly just want to remove obvious boilerplate if needed.
            # But preserving content is safer for Gemini.
            cleaned_lines.append(line)
            
        # Return at most 50k characters to prevent gigantic context
        return "\n".join(cleaned_lines)[:50000]
