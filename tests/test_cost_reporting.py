from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models.scan import ScanRun, ScanSourceResult
from app.services.cost_reporting import build_cost_report, prune_scan_history


def _db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_cost_report_counts_models_and_deterministic_bypasses():
    db = _db()
    now = datetime(2026, 8, 2, 12, 0, 0)
    scan = ScanRun(
        trigger="manual_all",
        status="completed",
        started_at=now,
        completed_at=now,
    )
    db.add(scan)
    db.flush()
    db.add_all(
        [
            ScanSourceResult(
                scan_run_id=scan.id,
                source_type="official_website",
                fetch_success=True,
                extraction_mode="gemini",
                llm_model="gemini-2.5-flash-lite",
                llm_input_tokens=1_000,
                llm_output_tokens=100,
                llm_estimated_cost_usd=0.00014,
                created_at=now,
            ),
            ScanSourceResult(
                scan_run_id=scan.id,
                source_type="official_website",
                fetch_success=True,
                extraction_mode="structured",
                structured_provider="seated",
                created_at=now,
            ),
            ScanSourceResult(
                scan_run_id=scan.id,
                source_type="official_website",
                fetch_success=True,
                extraction_mode="cache",
                created_at=now,
            ),
        ]
    )
    db.commit()

    report = build_cost_report(db, days=30, as_of=now)

    assert report.window.source_checks == 3
    assert report.window.llm_calls == 1
    assert report.window.deterministic_bypasses == 2
    assert report.window.input_tokens == 1_000
    assert report.window.estimated_cost_usd == 0.00014
    assert report.models[0].model == "gemini-2.5-flash-lite"


def test_scan_retention_keeps_running_and_recent_runs():
    db = _db()
    now = datetime(2026, 8, 2, 12, 0, 0)
    old_completed = ScanRun(
        trigger="scheduled",
        status="completed",
        started_at=now - timedelta(days=91),
    )
    old_running = ScanRun(
        trigger="scheduled",
        status="running",
        started_at=now - timedelta(days=91),
    )
    recent = ScanRun(
        trigger="scheduled",
        status="completed",
        started_at=now - timedelta(days=10),
    )
    db.add_all([old_completed, old_running, recent])
    db.commit()

    removed = prune_scan_history(db, 90, as_of=now)

    assert removed == 1
    assert db.get(ScanRun, old_completed.id) is None
    assert db.get(ScanRun, old_running.id) is not None
    assert db.get(ScanRun, recent.id) is not None
