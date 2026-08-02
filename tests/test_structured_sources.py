from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.services.scanner as scanner
from app.database import Base
from app.models.artist import Artist, ArtistSource
from app.models.location import LocationProfile
from app.models.scan import ScanRun, ScanSourceResult
from app.services.crawler import CrawlerService
from app.services.structured_sources import (
    STRUCTURED_EVENT_PREFIX,
    event_marker,
    extract_structured_events,
)


def _marker(provider: str = "seated") -> str:
    return event_marker(
        provider,
        {
            "source_event_id": "show-123",
            "event_name": "Who Is Me Tour",
            "date": "2026-08-29",
            "time": "19:00",
            "venue": "Stanley Park",
            "city": "Vancouver",
            "region": "BC",
            "country": "Canada",
            "ticket_url": "https://tickets.example/show-123",
        },
    )


def test_canonical_structured_marker_parses_without_llm():
    extraction = extract_structured_events(_marker(), "Adam Ray")

    assert extraction is not None
    assert extraction.providers == ("seated",)
    assert len(extraction.result.events) == 1
    event = extraction.result.events[0]
    assert event.event_name == "Who Is Me Tour"
    assert event.city == "Vancouver"
    assert event.source_provider == "seated"
    assert event.source_event_id == "show-123"


def test_clean_markdown_preserves_structured_markers_after_large_page():
    crawler = CrawlerService(SimpleNamespace(
        crawl4ai_base_url="http://crawl4ai:11235",
        firecrawl_api_key=None,
    ))
    cleaned = crawler.clean_markdown("x" * 60_000 + "\n" + _marker())

    assert len(cleaned) <= 50_000
    assert STRUCTURED_EVENT_PREFIX in cleaned
    assert extract_structured_events(cleaned, "Adam Ray") is not None


def test_scanner_bypasses_gemini_for_structured_adapter_events(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    artist = Artist(name="Adam Ray", artist_type="comedy")
    profile = LocationProfile(
        name="Vancouver / Lower Mainland",
        latitude=49.2827,
        longitude=-123.1207,
        radius_km=60,
        country_code="CA",
        region_code="BC",
        is_default=True,
    )
    db.add_all([artist, profile])
    db.flush()
    source = ArtistSource(
        artist_id=artist.id,
        source_type="official_website",
        url="https://adamraycomedy.com/tour",
    )
    scan_run = ScanRun(artist_id=artist.id, trigger="manual_single", status="running")
    db.add_all([source, scan_run])
    db.commit()

    class FakeCrawler:
        def __init__(self, _settings):
            pass

        def fetch_markdown(self, **_kwargs):
            return _marker(), "crawl4ai"

        def clean_markdown(self, markdown):
            return markdown

        def diagnose_event_content(self, *_args):
            return None

    class FailingExtractor:
        def __init__(self, _settings):
            self.last_debug = {}

        def extract_events(self, *_args):
            raise AssertionError("Gemini must not be called for adapter events")

    monkeypatch.setattr(scanner, "CrawlerService", FakeCrawler)
    monkeypatch.setattr(scanner, "ExtractorService", FailingExtractor)
    monkeypatch.setattr(scanner, "append_source_debug", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scanner, "_set_scan_progress", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scanner, "_notify_confirmed", lambda *_args, **_kwargs: None)

    found, confirmed, possible = scanner._scan_single_artist(
        db,
        artist,
        scan_run.id,
        SimpleNamespace(ticketmaster_api_key=None, debug_scan_capture=False),
    )

    result = db.query(ScanSourceResult).one()
    persisted_event = db.query(scanner.Event).one()
    assert (found, confirmed, possible) == (1, 1, 0)
    assert result.extraction_mode == "structured"
    assert result.structured_provider == "seated"
    assert result.llm_input_tokens == 0
    assert result.llm_estimated_cost_usd == 0
    assert persisted_event.source_provider == "seated"
    assert persisted_event.source_event_id == "show-123"
