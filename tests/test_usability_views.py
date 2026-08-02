from __future__ import annotations

from datetime import date, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models.artist import Artist
from app.models.event import Event
from app.models.scan import ScanRun
from main import app


def _event(artist_id: int, name: str, event_date: date, *, attending: bool = False) -> Event:
    return Event(
        artist_id=artist_id,
        event_name=name,
        venue="Test Theatre",
        city="Vancouver",
        region="BC",
        country="Canada",
        event_date=event_date,
        source_type="official_website",
        source_provider="test_adapter",
        status="confirmed",
        confidence_score=1.0,
        dedup_key=f"test-{uuid4().hex}",
        is_attending=attending,
        notification_status="attending" if attending else "sent",
    )


def test_events_default_to_future_and_going_is_performance_specific():
    marker = uuid4().hex[:8]
    artist = Artist(name=f"View Test {marker}", artist_type="comedy")

    with TestClient(app) as client:
        db = SessionLocal()
        try:
            db.add(artist)
            db.flush()
            upcoming_name = f"Upcoming {marker}"
            going_name = f"Going {marker}"
            past_name = f"Past {marker}"
            db.add_all([
                _event(artist.id, upcoming_name, date.today() + timedelta(days=30)),
                _event(
                    artist.id,
                    going_name,
                    date.today() + timedelta(days=60),
                    attending=True,
                ),
                _event(artist.id, past_name, date.today() - timedelta(days=30)),
            ])
            db.commit()

            default_response = client.get("/events")
            going_response = client.get("/events?view=going")
            past_response = client.get("/events?view=past")

            assert default_response.status_code == 200
            assert upcoming_name in default_response.text
            assert going_name in default_response.text
            assert past_name not in default_response.text
            assert going_name in going_response.text
            assert upcoming_name not in going_response.text
            assert past_name in past_response.text
        finally:
            db.delete(artist)
            db.commit()
            db.close()


def test_scan_history_is_paginated_and_filters_failed_runs():
    marker = uuid4().hex[:8]
    created_ids: list[int] = []

    with TestClient(app) as client:
        db = SessionLocal()
        try:
            for index in range(27):
                scan = ScanRun(
                    trigger="manual_all",
                    status="failed" if index == 0 else "completed",
                    started_at=datetime.now() + timedelta(seconds=index),
                    completed_at=datetime.now() + timedelta(seconds=index + 1),
                    error_summary=f"{marker}-{index}",
                )
                db.add(scan)
                db.flush()
                created_ids.append(scan.id)
            db.commit()

            first_page = client.get("/scans/")
            failed_only = client.get("/scans/?status=failed")

            assert first_page.status_code == 200
            assert "Page 1 of" in first_page.text
            assert f"{marker}-26" in first_page.text
            assert f"{marker}-0" not in first_page.text
            assert failed_only.status_code == 200
            assert f"{marker}-0" in failed_only.text
            assert f"{marker}-1" not in failed_only.text
        finally:
            db.query(ScanRun).filter(ScanRun.id.in_(created_ids)).delete(
                synchronize_session=False
            )
            db.commit()
            db.close()
