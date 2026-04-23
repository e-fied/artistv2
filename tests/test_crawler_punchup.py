from __future__ import annotations

import httpx

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


def test_crawl_markdown_to_text_parses_stringified_markdown_dict():
    crawler = CrawlerService(AppSettings())
    markdown_value = (
        "{'raw_markdown': 'Illenium shell text', "
        "'markdown_with_citations': 'Illenium cited text', "
        "'fit_markdown': '', 'fit_html': ''}"
    )

    assert crawler._crawl_markdown_to_text(markdown_value) == "Illenium shell text"


def test_fetch_markdown_enriches_blank_crawl4ai_result():
    crawler = CrawlerService(AppSettings())
    crawler._fetch_crawl4ai = lambda url: ""
    crawler._append_embedded_events = lambda url, markdown: "Punchup API tour events"

    markdown, crawler_used = crawler.fetch_markdown("https://punchup.live/timmynobrakes/tour")

    assert markdown == "Punchup API tour events"
    assert crawler_used == "crawl4ai"


def test_find_seated_artist_id_from_widget_markup():
    crawler = CrawlerService(AppSettings())
    page_html = (
        '<script id="seated-55fdf2c0-script-992ceda5-c055-4a4b-b6ee-6e92d81f8d57" '
        'data-artist-id="992ceda5-c055-4a4b-b6ee-6e92d81f8d57" '
        'src="https://widget.seated.com/widget.js"></script>'
    )

    artist_id = crawler._find_seated_artist_id_in_text(page_html)

    assert artist_id == "992ceda5-c055-4a4b-b6ee-6e92d81f8d57"


def test_find_seated_artist_id_from_notification_link():
    crawler = CrawlerService(AppSettings())
    page_html = (
        '<a href="https://go.seated.com/notifications/welcome/'
        '992ceda5-c055-4a4b-b6ee-6e92d81f8d57">Follow ILLENIUM</a>'
    )

    artist_id = crawler._find_seated_artist_id_in_text(page_html)

    assert artist_id == "992ceda5-c055-4a4b-b6ee-6e92d81f8d57"


def test_seated_api_to_markdown_uses_relationship_order_and_end_date():
    crawler = CrawlerService(AppSettings())
    data = {
        "data": {
            "attributes": {"name": "ILLENIUM"},
            "relationships": {
                "tour-events": {
                    "data": [
                        {"id": "may-event", "type": "tour-events"},
                        {"id": "nov-event", "type": "tour-events"},
                    ]
                }
            },
        },
        "included": [
            {
                "id": "nov-event",
                "type": "tour-events",
                "attributes": {
                    "starts-at-date-local": "2026-11-19",
                    "ends-at-date-local": "2026-11-22",
                    "venue-name": "Ember Shores",
                    "formatted-address": "Playa del Carmen, Quintana Roo",
                },
            },
            {
                "id": "may-event",
                "type": "tour-events",
                "attributes": {
                    "starts-at-date-local": "2026-05-02",
                    "venue-name": "Empire Music Festival",
                    "formatted-address": "Guatemala City, Guatemala",
                },
            },
        ],
    }

    markdown = crawler._seated_api_to_markdown(data)

    assert markdown is not None
    assert markdown.index("Empire Music Festival") < markdown.index("Ember Shores")
    assert "2026-11-19 to 2026-11-22 | Ember Shores" in markdown


def test_fetch_seated_api_retries_406_with_fallback_headers():
    crawler = CrawlerService(AppSettings())
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            return httpx.Response(406)
        return httpx.Response(
            200,
            json={
                "data": {"attributes": {"name": "ILLENIUM"}},
                "included": [
                    {
                        "id": "4e642cc0-6c2b-4e2e-b65f-c83b56672809",
                        "type": "tour-events",
                        "attributes": {
                            "starts-at-date-local": "2026-05-02",
                            "venue-name": "Empire Music Festival",
                            "formatted-address": "Guatemala City, Guatemala",
                        },
                    }
                ],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))

    markdown = crawler._fetch_seated_api_events_markdown(
        client,
        "992ceda5-c055-4a4b-b6ee-6e92d81f8d57",
    )

    assert request_count == 2
    assert markdown is not None
    assert "Empire Music Festival" in markdown


def test_fetch_embedded_events_uses_browser_headers_for_seated_pages(monkeypatch):
    crawler = CrawlerService(AppSettings())
    real_client = httpx.Client
    seen_user_agents = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_user_agents.append(request.headers.get("user-agent", ""))
        if request.url.host == "www.illenium.com":
            return httpx.Response(
                200,
                text=(
                    '<div id="seated-55fdf2c0" '
                    'data-artist-id="992ceda5-c055-4a4b-b6ee-6e92d81f8d57"></div>'
                ),
            )
        if request.url.host == "cdn.seated.com":
            return httpx.Response(
                200,
                json={
                    "data": {"attributes": {"name": "ILLENIUM"}},
                    "included": [
                        {
                            "id": "4e642cc0-6c2b-4e2e-b65f-c83b56672809",
                            "type": "tour-events",
                            "attributes": {
                                "starts-at-date-local": "2026-05-02",
                                "venue-name": "Empire Music Festival",
                                "formatted-address": "Guatemala City, Guatemala",
                            },
                        }
                    ],
                },
            )
        return httpx.Response(404)

    def client_factory(*args, **kwargs):
        return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "Client", client_factory)

    markdown = crawler._fetch_embedded_events_markdown("https://www.illenium.com/illenium/#tour")

    assert markdown is not None
    assert "Seated widget tour events for ILLENIUM" in markdown
    assert "Empire Music Festival" in markdown
    assert any("Mozilla/5.0" in user_agent for user_agent in seen_user_agents)


def test_find_upnex_event_portal_config_from_inline_script():
    crawler = CrawlerService(AppSettings())
    page_html = """
    <script src="https://upnex-events-test.pages.dev/events.js"></script>
    <script>
      initEvents({
        locationId: "9ofXWQPyRvJNOGpFT4yU",
        eventPortalToken:
         "token-123",
        waitlistFormId: "wrzqMgq05EdMG7Yv3yNl",
      });
    </script>
    """

    config = crawler._find_upnex_event_portal_config(page_html)

    assert config == {
        "location_id": "9ofXWQPyRvJNOGpFT4yU",
        "event_portal_token": "token-123",
    }


def test_upnex_api_to_markdown_includes_live_events_and_ticket_links():
    crawler = CrawlerService(AppSettings())
    data = {
        "data": {
            "location": {"name": "Ari Matti"},
            "events": [
                {
                    "status": "live",
                    "startDate": "2025-10-18",
                    "displayCity": "Denver, CO",
                    "displayVenue": "Paramount Theatre",
                    "address": "1621 Glenarm Pl, Denver, CO, USA",
                    "additionalInfo": "Killers of Kill Tony",
                    "ticketLinkGroups": [
                        {
                            "ticketLink": "https://tickets.example.com/denver",
                            "buttonText": "Tickets",
                        }
                    ],
                    "showtimes": [
                        {
                            "ticketLinks": [
                                {
                                    "ticketLink": "#",
                                    "buttonText": "Tickets",
                                }
                            ]
                        }
                    ],
                },
                {
                    "status": "draft",
                    "startDate": "2025-11-01",
                    "displayCity": "Hidden City",
                    "displayVenue": "Hidden Venue",
                },
            ],
        }
    }

    markdown = crawler._upnex_api_to_markdown(data)

    assert markdown is not None
    assert "Upnex event portal shows for Ari Matti" in markdown
    assert "2025-10-18 | Paramount Theatre | Denver, CO" in markdown
    assert "Killers of Kill Tony" in markdown
    assert "Tickets: https://tickets.example.com/denver" in markdown
    assert "Hidden Venue" not in markdown


def test_fetch_embedded_events_enriches_upnex_event_portal(monkeypatch):
    crawler = CrawlerService(AppSettings())
    real_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "arimatti.com":
            return httpx.Response(
                200,
                text="""
                <script src="https://upnex-events-test.pages.dev/events.js"></script>
                <script>
                  initEvents({
                    locationId: "9ofXWQPyRvJNOGpFT4yU",
                    eventPortalToken: "token-123",
                  });
                </script>
                """,
            )
        if request.url.host == "events-portal-sage.vercel.app":
            assert request.headers.get("authorization") == "Bearer token-123"
            return httpx.Response(
                200,
                json={
                    "data": {
                        "location": {"name": "Ari Matti"},
                        "events": [
                            {
                                "status": "live",
                                "startDate": "2025-10-18",
                                "displayCity": "Denver, CO",
                                "displayVenue": "Paramount Theatre",
                                "ticketLinkGroups": [
                                    {
                                        "ticketLink": "https://tickets.example.com/denver",
                                        "buttonText": "Tickets",
                                    }
                                ],
                            }
                        ],
                    }
                },
            )
        return httpx.Response(404)

    def client_factory(*args, **kwargs):
        return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "Client", client_factory)

    markdown = crawler._fetch_embedded_events_markdown("https://arimatti.com/#section-d4bgT3Wh1P")

    assert markdown is not None
    assert "Upnex event portal shows for Ari Matti" in markdown
    assert "Paramount Theatre" in markdown


def test_punchup_api_refetches_missing_comedian_id():
    crawler = CrawlerService(AppSettings())

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/timmynobrakes/tour":
            return httpx.Response(
                200,
                text=(
                    'self.__next_f.push(["$","$L1",null,'
                    r'{\"comedian\":{\"id\":\"903698e7-3646-4662-9337-b0f435f5ab2e\",'
                    r'\"slug\":\"timmynobrakes\",\"display_name\":\"Timmy No Brakes\"}}])'
                ),
            )
        if request.url.path == "/api/shows":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "visible-show",
                        "datetime": "2026-04-24T19:00:00",
                        "venue": "Kiva Auditorium",
                        "location": "Albuquerque, NM",
                        "comedian": {"display_name": "Timmy No Brakes"},
                    }
                ],
            )
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    markdown = crawler._fetch_punchup_api_events_markdown(
        client,
        "https://punchup.live/timmynobrakes/tour",
        "<html>No comedian id in this shell</html>",
    )

    assert markdown is not None
    assert "Punchup API tour events for Timmy No Brakes" in markdown
    assert "Kiva Auditorium" in markdown


def test_punchup_api_discovers_comedian_id_from_nearby_shows():
    crawler = CrawlerService(AppSettings())

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/timmynobrakes/tour":
            return httpx.Response(200, text="<html>No comedian id in this shell</html>")
        if request.url.path == "/api/shows" and "comedianId" not in request.url.params:
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "nearby-show",
                        "comedian_id": "903698e7-3646-4662-9337-b0f435f5ab2e",
                        "comedian": {
                            "id": "903698e7-3646-4662-9337-b0f435f5ab2e",
                            "slug": "timmynobrakes",
                            "display_name": "Timmy No Brakes",
                        },
                    }
                ],
            )
        if request.url.path == "/api/shows" and request.url.params.get("comedianId"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "visible-show",
                        "datetime": "2026-04-24T19:00:00",
                        "venue": "Kiva Auditorium",
                        "location": "Albuquerque, NM",
                        "comedian": {"display_name": "Timmy No Brakes"},
                    }
                ],
            )
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    markdown = crawler._fetch_punchup_api_events_markdown(
        client,
        "https://punchup.live/timmynobrakes/tour",
        "<html>No comedian id in this shell</html>",
    )

    assert markdown is not None
    assert "Punchup API tour events for Timmy No Brakes" in markdown
    assert "Kiva Auditorium" in markdown


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
