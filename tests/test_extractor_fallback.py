from __future__ import annotations

from app.config import AppSettings
from app.services.extractor import ExtractorService


def test_fallback_extracts_markdown_table_events():
    extractor = ExtractorService(AppSettings(gemini_api_key=None))
    markdown = """
## Tour Dates
| [May 15, 2026](https://example.com/may15a) | [New Westminster, BC](https://example.com/may15a) | [House of Comedy (7:30 pm)](https://example.com/may15a) | [Buy Tickets](https://tickets.example.com/a) |
| --- | --- | --- | --- |
| [May 16, 2026](https://example.com/may16a) | [Campbell River, BC](https://example.com/may16a) | [Tidemark Theatre](https://example.com/may16a) | [Buy Tickets](https://tickets.example.com/b) |
"""

    result = extractor.extract_events(markdown, "Chris D Elia")

    assert result is not None
    assert len(result.events) == 2
    assert result.events[0].date == "2026-05-15"
    assert result.events[0].time == "19:30"
    assert result.events[0].venue == "House of Comedy"
    assert result.events[0].city == "New Westminster"
    assert result.events[0].region == "BC"
    assert result.events[1].ticket_url == "https://tickets.example.com/b"


def test_fallback_extracts_punchup_api_events():
    extractor = ExtractorService(AppSettings(gemini_api_key=None))
    markdown = """
Punchup API tour events for Ahren Belisle:
- 2026-04-23T19:00:00 | Ahren Belisle | The Rec Room (St John's) | St. John's, NL | Tickets: https://tickets.example.com/1 | Event page: https://punchup.live/e/1
- 2026-05-03T19:00:00 | Ahren Belisle Live in Montreal | Stand-Up Comedy Show | May 3rd 2026 | Estrella restaurant | Montreal, QC | Tickets: https://tickets.example.com/2 | Event page: https://punchup.live/e/2
"""

    result = extractor.extract_events(markdown, "Ahren Belisle")

    assert result is not None
    assert len(result.events) == 2
    assert result.events[0].date == "2026-04-23"
    assert result.events[0].time == "19:00"
    assert result.events[0].venue == "The Rec Room (St John's)"
    assert result.events[0].city == "St. John's"
    assert result.events[0].region == "NL"
    assert result.events[1].event_name == "Ahren Belisle Live in Montreal | Stand-Up Comedy Show | May 3rd 2026"
    assert result.events[1].venue == "Estrella restaurant"
    assert result.events[1].city == "Montreal"
    assert result.events[1].region == "QC"
