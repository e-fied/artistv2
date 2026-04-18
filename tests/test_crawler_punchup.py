from __future__ import annotations

from app.config import AppSettings
from app.services.crawler import CrawlerService


def test_find_punchup_comedian_id_from_escaped_next_data():
    crawler = CrawlerService(AppSettings())
    page_html = (
        'self.__next_f.push(["$","$L1",null,'
        r'{\"comedian\":{\"id\":\"903698e7-3646-4662-9337-b0f435f5ab2e\",'
        r'\"slug\":\"timmynobrakes\",\"display_name\":\"Timmy No Brakes\"}}])'
    )

    artist_id = crawler._find_punchup_comedian_id(
        "https://punchup.live/timmynobrakes/tour",
        page_html,
    )

    assert artist_id == "903698e7-3646-4662-9337-b0f435f5ab2e"


def test_crawl_markdown_to_text_uses_raw_markdown_without_dict_string():
    crawler = CrawlerService(AppSettings())
    markdown_value = {
        "raw_markdown": "Punchup shell text",
        "markdown_with_citations": "Punchup shell text with citations",
        "references_markdown": "\n\n## References\n\n",
        "fit_markdown": "",
        "fit_html": "",
    }

    assert crawler._crawl_markdown_to_text(markdown_value) == "Punchup shell text"


def test_crawl_markdown_to_text_returns_empty_for_blank_dict():
    crawler = CrawlerService(AppSettings())
    markdown_value = {
        "raw_markdown": "\n",
        "markdown_with_citations": "\n",
        "references_markdown": "\n\n## References\n\n",
        "fit_markdown": "",
        "fit_html": "",
    }

    assert crawler._crawl_markdown_to_text(markdown_value) == ""


def test_fetch_markdown_enriches_blank_crawl4ai_result():
    crawler = CrawlerService(AppSettings())
    crawler._fetch_crawl4ai = lambda url: ""
    crawler._append_embedded_events = lambda url, markdown: "Punchup API tour events"

    markdown, crawler_used = crawler.fetch_markdown("https://punchup.live/timmynobrakes/tour")

    assert markdown == "Punchup API tour events"
    assert crawler_used == "crawl4ai"


def test_punchup_api_to_markdown_includes_visible_shows_only():
    crawler = CrawlerService(AppSettings())
    comedian_id = "903698e7-3646-4662-9337-b0f435f5ab2e"
    data = [
        {
            "id": "visible-show",
            "datetime": "2026-04-24T19:00:00",
            "title": "",
            "venue": "Kiva Auditorium",
            "location": "Albuquerque, NM",
            "ticket_link": "https://example.com/tickets",
            "is_sold_out": False,
            "comedian": {"display_name": "Timmy No Brakes"},
            "show_comedians": [
                {
                    "id": comedian_id,
                    "hidden_from_comedian_page": False,
                }
            ],
        },
        {
            "id": "hidden-show",
            "datetime": "2026-04-25T19:00:00",
            "venue": "Secret Venue",
            "location": "Hidden City, BC",
            "comedian": {"display_name": "Timmy No Brakes"},
            "show_comedians": [
                {
                    "id": comedian_id,
                    "hidden_from_comedian_page": True,
                }
            ],
        },
    ]

    markdown = crawler._punchup_api_to_markdown(
        data,
        "https://punchup.live/timmynobrakes/tour",
        comedian_id,
    )

    assert markdown is not None
    assert "Punchup API tour events for Timmy No Brakes" in markdown
    assert (
        "2026-04-24T19:00:00 | Timmy No Brakes | Kiva Auditorium | Albuquerque, NM"
        in markdown
    )
    assert "https://example.com/tickets" in markdown
    assert "https://punchup.live/e/visible-show" in markdown
    assert "Secret Venue" not in markdown
