from types import SimpleNamespace
from datetime import date
from uuid import UUID

import pytest
from celery.exceptions import OperationalError
from fastapi import HTTPException

from app.auth import AuthenticatedPrincipal
from app.celery_app import process_18_month_payroll
from app.main import app
from app.routers import jobs


HR_PRINCIPAL = AuthenticatedPrincipal(
    employee_id="EMP-HR",
    role="HR",
    user_id="USER-HR",
)


def test_job_submission_records_queued_state_and_returns_progress_url(
    monkeypatch,
):
    stored = []
    sent = []
    monkeypatch.setattr(
        jobs.celery_app.backend,
        "store_result",
        lambda task_id, result, state: stored.append(
            (task_id, result, state)
        ),
    )
    monkeypatch.setattr(
        jobs.celery_app,
        "send_task",
        lambda name, args, task_id: sent.append((name, args, task_id)),
    )
    monkeypatch.setattr(jobs, "_require_available_worker", lambda: None)

    response = jobs.start_18_month_payroll_job(HR_PRINCIPAL)

    job_id = response["job_id"]
    UUID(job_id)
    assert response == {
        "job_id": job_id,
        "status": "QUEUED",
        "progress_url": f"/api/v1/jobs/{job_id}",
    }
    assert stored == [(job_id, {"progress": 0}, "QUEUED")]
    assert sent == [
        (
            "ledgerforge.process_18_month_payroll",
            [job_id, "USER-HR"],
            job_id,
        )
    ]


def test_job_submission_reports_unavailable_queue(monkeypatch):
    monkeypatch.setattr(jobs, "_require_available_worker", lambda: None)
    monkeypatch.setattr(
        jobs.celery_app.backend,
        "store_result",
        lambda *_args, **_kwargs: None,
    )

    def fail_to_publish(*_args, **_kwargs):
        raise OperationalError("broker unavailable")

    monkeypatch.setattr(jobs.celery_app, "send_task", fail_to_publish)

    with pytest.raises(HTTPException) as raised:
        jobs.start_18_month_payroll_job(HR_PRINCIPAL)

    assert raised.value.status_code == 503
    assert raised.value.detail == "The payroll job queue is unavailable."


@pytest.mark.parametrize(
    ("state", "info", "expected"),
    [
        ("QUEUED", {"progress": 0}, {"status": "QUEUED", "progress": 0}),
        (
            "PROGRESS",
            {"progress": 42, "processed": 3, "total": 7},
            {
                "status": "RUNNING",
                "progress": 42,
                "processed": 3,
                "total": 7,
            },
        ),
        ("STARTED", {}, {"status": "RUNNING", "progress": 0}),
        (
            "SUCCESS",
            {"processed": 7},
            {"status": "COMPLETED", "progress": 100, "result": {"processed": 7}},
        ),
        (
            "FAILURE",
            RuntimeError("batch failed"),
            {"status": "FAILED", "progress": 100, "error": "batch failed"},
        ),
    ],
)
def test_job_status_maps_celery_states(monkeypatch, state, info, expected):
    task_id = "0e6feaa3-8153-4f66-87e0-79d0d33a2bc1"
    result = SimpleNamespace(
        state=state,
        info=info,
        result=info if state == "SUCCESS" else info,
    )
    monkeypatch.setattr(
        jobs.celery_app,
        "AsyncResult",
        lambda requested_id: result
        if requested_id == task_id
        else None,
    )
    monkeypatch.setattr(jobs, "_require_available_worker", lambda: None)

    response = jobs.payroll_job_status(task_id, HR_PRINCIPAL)

    assert response == {"job_id": task_id, **expected}


def test_job_status_rejects_malformed_id():
    with pytest.raises(HTTPException) as raised:
        jobs.payroll_job_status("not-a-uuid", HR_PRINCIPAL)
    assert raised.value.status_code == 404


def test_job_status_rejects_unknown_task(monkeypatch):
    task_id = "0e6feaa3-8153-4f66-87e0-79d0d33a2bc1"
    monkeypatch.setattr(
        jobs.celery_app,
        "AsyncResult",
        lambda _requested_id: SimpleNamespace(
            state="PENDING",
            info=None,
            result=None,
        ),
    )
    monkeypatch.setattr(jobs, "_require_available_worker", lambda: None)

    with pytest.raises(HTTPException) as raised:
        jobs.payroll_job_status(task_id, HR_PRINCIPAL)
    assert raised.value.status_code == 404


def test_job_submission_reports_unavailable_when_worker_is_absent(monkeypatch):
    monkeypatch.setattr(jobs.settings, "redis_url", None)
    with pytest.raises(HTTPException) as raised:
        jobs.start_18_month_payroll_job(HR_PRINCIPAL)
    assert raised.value.status_code == 503
    assert raised.value.detail == "Background payroll jobs are unavailable."


def test_job_submission_reports_unavailable_when_no_worker_pings(monkeypatch):
    monkeypatch.setattr(jobs.settings, "redis_url", "redis://unavailable")
    monkeypatch.setattr(jobs.celery_app.control, "ping", lambda **_kwargs: [])
    with pytest.raises(HTTPException) as raised:
        jobs.start_18_month_payroll_job(HR_PRINCIPAL)
    assert raised.value.status_code == 503
    assert raised.value.detail == "Background payroll workers are unavailable."


def test_job_status_reports_unavailable_when_worker_is_absent(monkeypatch):
    monkeypatch.setattr(jobs.settings, "redis_url", None)
    with pytest.raises(HTTPException) as raised:
        jobs.payroll_job_status(
            "0e6feaa3-8153-4f66-87e0-79d0d33a2bc1",
            HR_PRINCIPAL,
        )
    assert raised.value.status_code == 503


def test_payroll_task_is_bound_for_progress_updates():
    assert process_18_month_payroll.__bound__ is True


def test_payroll_task_reports_calculation_progress(monkeypatch):
    task_updates = []

    def run_payroll(job_id, processed_by, progress_callback):
        assert job_id == "job-123"
        assert processed_by == "USER-HR"
        progress_callback(1, 2)
        return {"runs_processed": 2}

    monkeypatch.setattr(jobs, "_run_18_month_payroll", run_payroll)
    monkeypatch.setattr(
        process_18_month_payroll,
        "update_state",
        lambda **state: task_updates.append(state),
    )

    assert process_18_month_payroll.run("job-123", "USER-HR") == {
        "runs_processed": 2
    }
    assert task_updates == [
        {
            "state": "PROGRESS",
            "meta": {"progress": 52, "processed": 1, "total": 2},
        }
    ]


def test_18_month_job_processes_only_draft_runs(monkeypatch):
    rows = []
    for offset in range(18):
        year = 2025 + (3 + offset) // 12
        month = (3 + offset) % 12 + 1
        period_start = date(year, month, 1)
        period_end = date(
            year,
            month,
            28 if month == 2 else 30 if month in {4, 6, 9, 11} else 31,
        )
        rows.append(
            SimpleNamespace(
                run_id=f"PR-{offset:02}",
                period_start=period_start,
                period_end=period_end,
                status="DRAFT" if offset == 0 else "PAID",
            )
        )

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _query):
            return SimpleNamespace(all=lambda: rows)

        def rollback(self):
            pass

    processed = []
    progress = []
    monkeypatch.setattr(jobs, "SessionLocal", FakeSession)
    monkeypatch.setattr(
        jobs,
        "process_payroll_run",
        lambda _db, run_id, *, processed_by: processed.append(
            (run_id, processed_by)
        ),
    )

    result = jobs._run_18_month_payroll(
        "job-18",
        "USER-HR",
        lambda completed, total: progress.append((completed, total)),
    )

    assert result["periods"] == 18
    assert result["runs_considered"] == 18
    assert result["runs_processed"] == 1
    assert result["processed_run_ids"] == ["PR-00"]
    assert result["runs_skipped"] == 17
    assert processed == [("PR-00", "USER-HR")]
    assert progress == [(index, 18) for index in range(1, 19)]


def test_18_month_job_fails_when_fewer_periods_exist(monkeypatch):
    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _query):
            return SimpleNamespace(
                all=lambda: [
                    SimpleNamespace(
                        run_id="PR-01",
                        period_start=date(2025, 4, 1),
                        period_end=date(2025, 4, 30),
                        status="DRAFT",
                    )
                ]
            )

        def rollback(self):
            pass

    monkeypatch.setattr(jobs, "SessionLocal", FakeSession)
    with pytest.raises(ValueError, match="requires 18 distinct payroll periods"):
        jobs._run_18_month_payroll("job-short", "USER-HR")


def test_all_registered_api_endpoints_have_v1_paths():
    paths = app.openapi()["paths"]
    versioned_paths = {path for path in paths if path.startswith("/api/v1/")}

    assert versioned_paths
    for path in versioned_paths:
        legacy_path = path.removeprefix("/api/v1")
        assert legacy_path in paths or path == "/api/v1/health"
