from __future__ import annotations

from types import SimpleNamespace

from app.services.source_health import (
    apply_source_health,
    assess_event_content,
    fetch_error_assessment,
)


def _source(**overrides):
    values = {
        "consecutive_failures": 0,
        "last_error": None,
        "last_success_at": None,
        "last_checked_at": None,
        "health_status": "unknown",
        "last_health_code": None,
        "last_recovered_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _result():
    return SimpleNamespace(
        health_status=None,
        health_code=None,
        fetch_error=None,
    )


def test_explicit_no_upcoming_dates_is_healthy_empty_not_a_failure():
    assessment = assess_event_content(
        "Tour dates: No upcoming events. Check back soon.",
        0,
        extraction_failed=True,
    )
    source = _source(consecutive_failures=3, last_error="old widget warning")
    result = _result()

    transition = apply_source_health(source, result, assessment)

    assert assessment.status == "empty"
    assert assessment.code == "no_upcoming_events"
    assert assessment.is_problem is False
    assert transition.recovered is True
    assert source.consecutive_failures == 0
    assert source.last_error is None
    assert source.last_recovered_at is not None
    assert result.health_status == "recovered"


def test_dynamic_tour_shell_is_a_transient_warning():
    assessment = assess_event_content(
        "Tour tickets and show information will load here. " * 30,
        0,
    )

    assert assessment.status == "warning"
    assert assessment.code == "dynamic_listing_missing"
    assert assessment.transient is True


def test_structured_events_are_healthy_and_identified():
    assessment = assess_event_content(
        "TOURTRACKER_EVENT_JSON {}",
        5,
        extraction_mode="structured",
    )

    assert assessment.status == "healthy"
    assert assessment.code == "structured_events"


def test_hard_fetch_error_increments_streak_and_keeps_message():
    source = _source(consecutive_failures=1)
    result = _result()
    assessment = fetch_error_assessment("HTTP 503 from crawler")

    transition = apply_source_health(source, result, assessment)

    assert transition.recovered is False
    assert source.consecutive_failures == 2
    assert source.health_status == "error"
    assert source.last_error == "HTTP 503 from crawler"
    assert result.health_code == "fetch_failed"
    assert result.fetch_error == "HTTP 503 from crawler"
