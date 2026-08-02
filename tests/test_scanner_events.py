from __future__ import annotations

from types import SimpleNamespace

import app.services.scanner as scanner


def test_process_event_ignores_past_local_event(monkeypatch):
    """A stale tour page must never recreate or notify for a past local show."""
    profile = SimpleNamespace(id=1)
    match = SimpleNamespace(
        matched=True,
        confidence=1.0,
        reason="exact_city",
        profile=profile,
    )
    monkeypatch.setattr(scanner, "match_event_to_locations", lambda **kwargs: match)

    def fail_upsert(**kwargs):
        raise AssertionError("past events must be rejected before persistence")

    monkeypatch.setattr(scanner, "upsert_event", fail_upsert)

    result = scanner._process_event(
        db=SimpleNamespace(),
        artist=SimpleNamespace(id=21, name="Michael Blaustein"),
        event_data={
            "event_name": "Michael Blaustein: The Taste Me Tour",
            "venue": "Massey Theatre",
            "city": "Vancouver",
            "region": "BC",
            "country": "Canada",
            "date": "2026-05-08",
            "time": "19:00:00",
        },
        profiles=[profile],
        source_type="official_website",
    )

    assert result == "past"


def test_transient_source_diagnostic_waits_for_sustained_streak(monkeypatch):
    sent_messages = []
    monkeypatch.setattr(scanner, "send_telegram", lambda *args: sent_messages.append(args) or True)
    settings = SimpleNamespace(
        notify_source_health=True,
        telegram_bot_token="token",
        telegram_chat_id="chat",
    )
    artist = SimpleNamespace(name="Penn and Teller")
    source = SimpleNamespace(
        source_type="official_website",
        url="https://pennandteller.com/tour-dates/",
        consecutive_failures=1,
    )

    scanner._notify_source_health(
        settings,
        artist,
        source,
        "widget missing",
        transient_diagnostic=True,
    )
    assert sent_messages == []

    source.consecutive_failures = 3
    scanner._notify_source_health(
        settings,
        artist,
        source,
        "widget missing",
        transient_diagnostic=True,
    )
    assert len(sent_messages) == 1


def test_unchanged_content_cache_requires_previous_healthy_success():
    source = SimpleNamespace(
        content_hash="same",
        last_success_at=object(),
        consecutive_failures=0,
        last_error=None,
    )

    assert scanner._can_skip_unchanged_web_source(
        source,
        "same",
        use_content_cache=True,
    )
    assert not scanner._can_skip_unchanged_web_source(
        source,
        "same",
        use_content_cache=False,
    )

    source.last_error = "previous warning"
    assert not scanner._can_skip_unchanged_web_source(
        source,
        "same",
        use_content_cache=True,
    )
