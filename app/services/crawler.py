"""Web content extraction service using Crawl4AI and Firecrawl fallback."""

from __future__ import annotations

import logging
import re
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

            if markdown:
                enriched_markdown = self._append_seated_events(url, markdown)
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
                    if isinstance(md_val, dict):
                        return md_val.get("fit_markdown") or md_val.get("raw") or str(md_val)
                    return md_val
                # Fallback structure just in case
                if "markdown" in data:
                    md_val = data["markdown"]
                    if isinstance(md_val, dict):
                        return md_val.get("fit_markdown") or md_val.get("raw") or str(md_val)
                    return md_val
                
                logger.error(f"Crawl4AI returned success but no markdown found: {data.keys()}")
                return None
        except Exception as e:
            logger.error(f"Crawl4AI error: {e}")
            return None

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

    def _append_seated_events(self, url: str, markdown: str) -> str:
        """Append Seated widget events when a tour page loads dates client-side."""
        seated_markdown = self._fetch_seated_events_markdown(url)
        if not seated_markdown:
            return markdown

        return f"{markdown}\n\n{seated_markdown}"

    def _fetch_seated_events_markdown(self, url: str) -> Optional[str]:
        """Fetch events directly from Seated's widget API if the page uses it."""
        try:
            with httpx.Client(timeout=20.0, follow_redirects=True) as client:
                page_response = client.get(url)
                page_response.raise_for_status()
                page_html = page_response.text

                artist_id = self._find_seated_artist_id(client, url, page_html)
                if not artist_id:
                    return None

                api_response = client.get(
                    f"https://cdn.seated.com/api/tour/{artist_id}",
                    params={"include": "tour-events"},
                    headers={"X-Client-Version": "tourtracker"},
                )
                api_response.raise_for_status()
                return self._seated_api_to_markdown(api_response.json())
        except Exception as e:
            logger.warning(f"Seated widget enrichment failed for {url}: {e}")
            return None

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
