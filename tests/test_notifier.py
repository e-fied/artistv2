from __future__ import annotations

from app.services.notifier import format_review_summary


def test_format_review_summary_includes_review_link():
    message = format_review_summary(
        3,
        [{"artist": "ROSÉ", "count": 2}, {"artist": "BLACKPINK", "count": 1}],
        review_url="https://artist.fied.ca/review",
    )

    assert "ROSÉ" in message
    assert "BLACKPINK" in message
    assert 'href="https://artist.fied.ca/review"' in message
