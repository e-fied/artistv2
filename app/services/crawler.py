"""Web content extraction service using Crawl4AI and Firecrawl fallback."""

from __future__ import annotations

import logging
from typing import Optional, Dict, Any

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
                return markdown, crawler
            
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
                
                # Depending on Crawl4AI version, it could be a list of results
                results = data.get("results")
                if results and len(results) > 0:
                    return results[0].get("markdown")
                # Fallback structure just in case
                if "markdown" in data:
                    return data["markdown"]
                
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
