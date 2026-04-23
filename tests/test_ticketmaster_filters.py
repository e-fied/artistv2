from __future__ import annotations

from app.services.ticketmaster import TicketmasterClient


def make_client() -> TicketmasterClient:
    client = TicketmasterClient("test-key")
    client.close()
    return client


def test_find_best_attraction_match_prefers_exact_normalized_name():
    client = make_client()
    client.search_attractions = lambda keyword, size=10: [
        {"id": "wrong", "name": "Guns N' Roses", "segment": "Music", "genre": "Rock"},
        {"id": "right", "name": "ROSÉ", "segment": "Music", "genre": "Pop"},
    ]

    match = client.find_best_attraction_match("ROSÉ", artist_type="music")

    assert match is not None
    assert match["id"] == "right"


def test_event_matches_artist_rejects_rose_false_positives():
    client = make_client()
    raw_event = {
        "name": "Guns N' Roses: World Tour 2026",
        "_embedded": {
            "attractions": [
                {
                    "name": "Guns N' Roses",
                    "classifications": [
                        {"segment": {"name": "Music"}, "genre": {"name": "Rock"}}
                    ],
                }
            ]
        },
    }

    assert client._event_matches_artist(raw_event, "ROSÉ", "music") is False


def test_event_matches_artist_accepts_exact_attraction_name():
    client = make_client()
    raw_event = {
        "name": "ROSÉ - World Tour",
        "_embedded": {
            "attractions": [
                {
                    "name": "ROSÉ",
                    "classifications": [
                        {"segment": {"name": "Music"}, "genre": {"name": "Pop"}}
                    ],
                }
            ]
        },
    }

    assert client._event_matches_artist(raw_event, "ROSÉ", "music") is True
