from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models.scan import ScanRun
from main import app


def test_base_template_shows_latest_scan_on_non_dashboard_pages():
    with TestClient(app) as client:
        db = SessionLocal()
        try:
            scan = ScanRun(
                trigger="manual_all",
                status="completed",
                started_at=datetime(2026, 6, 23, 12, 0, 0),
                completed_at=datetime(2026, 6, 23, 12, 1, 0),
            )
            db.add(scan)
            db.commit()
        finally:
            db.close()

        response = client.get("/events")

    assert response.status_code == 200
    assert "Last scan:" in response.text
    assert "No scans yet" not in response.text
