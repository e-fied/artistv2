from types import SimpleNamespace

from app.services.scanner import _search_ticketmaster_exact_matches


class FakeTicketmasterClient:
    def __init__(self, country_results=None, fallback_results=None):
        self.country_results = country_results or {}
        self.fallback_results = fallback_results or []
        self.calls = []

    def search_events_by_attraction(self, attraction_id, latlong=None, radius=None, country_code=None, size=50):
        self.calls.append(
            {
                "attraction_id": attraction_id,
                "latlong": latlong,
                "radius": radius,
                "country_code": country_code,
                "size": size,
            }
        )
        if country_code is None:
            return self.fallback_results
        return self.country_results.get(country_code, [])


def test_exact_attraction_search_queries_countries_without_geo_filters():
    client = FakeTicketmasterClient(country_results={"CA": [{"ticketmaster_event_id": "evt-1"}], "US": []})
    profiles = [
        SimpleNamespace(country_code="CA"),
        SimpleNamespace(country_code="CA"),
        SimpleNamespace(country_code="US"),
    ]

    events = _search_ticketmaster_exact_matches(client, "abc123", profiles)

    assert events == [{"ticketmaster_event_id": "evt-1"}]
    assert [call["country_code"] for call in client.calls] == ["CA", "US"]
    assert all(call["latlong"] is None for call in client.calls)
    assert all(call["radius"] is None for call in client.calls)


def test_exact_attraction_search_falls_back_when_country_queries_are_empty():
    client = FakeTicketmasterClient(country_results={"CA": []}, fallback_results=[{"ticketmaster_event_id": "evt-2"}])
    profiles = [SimpleNamespace(country_code="CA")]

    events = _search_ticketmaster_exact_matches(client, "abc123", profiles)

    assert events == [{"ticketmaster_event_id": "evt-2"}]
    assert [call["country_code"] for call in client.calls] == ["CA", None]
