from collections.abc import Callable
from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import select
from celery.exceptions import OperationalError
from fastapi import APIRouter, Depends, HTTPException, status
from redis.exceptions import RedisError

from ..auth import AuthenticatedPrincipal, require_roles
from ..celery_app import celery_app
from ..config import settings
from ..database import SessionLocal
from ..models import PayrollRun
from ..payroll_workflow_service import process_payroll_run


router = APIRouter(prefix="/jobs", tags=["background jobs"])


def _require_available_worker() -> None:
    if not settings.redis_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Background payroll jobs are unavailable.",
        )
    try:
        workers = celery_app.control.ping(timeout=1.0)
    except (OperationalError, RedisError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Background payroll jobs are unavailable.",
        ) from exc
    if not workers:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Background payroll workers are unavailable.",
        )


def _run_18_month_payroll(
    job_id: str,
    processed_by: str,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, object]:
    with SessionLocal() as db:
        run_rows = db.execute(
            select(
                PayrollRun.run_id,
                PayrollRun.period_start,
                PayrollRun.period_end,
                PayrollRun.status,
            ).order_by(
                PayrollRun.period_start.desc(),
                PayrollRun.run_id,
            )
        ).all()
        periods = sorted(
            {(row.period_start, row.period_end) for row in run_rows},
            reverse=True,
        )[:18]
        if len(periods) != 18:
            raise ValueError(
                "The 18-month payroll job requires 18 distinct payroll periods; "
                f"found {len(periods)}."
            )
        selected_periods = set(periods)
        runs_by_period: dict[tuple[date, date], list[tuple[str, str]]] = {
            period: [] for period in periods
        }
        for row in run_rows:
            period = (row.period_start, row.period_end)
            if period in selected_periods:
                runs_by_period[period].append((row.run_id, row.status))
        db.rollback()

        processed_runs: list[str] = []
        skipped_runs: list[dict[str, str]] = []
        for completed_periods, period in enumerate(
            reversed(periods), start=1
        ):
            for run_id, run_status in runs_by_period[period]:
                if run_status == "DRAFT":
                    process_payroll_run(
                        db,
                        run_id,
                        processed_by=processed_by,
                    )
                    processed_runs.append(run_id)
                else:
                    skipped_runs.append(
                        {"run_id": run_id, "status": run_status}
                    )
            if progress_callback is not None:
                progress_callback(completed_periods, len(periods))

    return {
        "job_id": job_id,
        "periods": len(periods),
        "runs_considered": sum(map(len, runs_by_period.values())),
        "runs_processed": len(processed_runs),
        "processed_run_ids": processed_runs,
        "runs_skipped": len(skipped_runs),
        "skipped_runs": skipped_runs,
    }


@router.post("/payroll/18-month", status_code=202)
def start_18_month_payroll_job(
    principal: AuthenticatedPrincipal = Depends(require_roles("ADMIN", "HR")),
):
    if principal.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user ID is unavailable",
        )
    _require_available_worker()
    job_id = str(uuid4())
    try:
        celery_app.backend.store_result(
            job_id,
            {"progress": 0},
            state="QUEUED",
        )
        celery_app.send_task(
            "ledgerforge.process_18_month_payroll",
            args=[job_id, principal.user_id],
            task_id=job_id,
        )
    except (OperationalError, RedisError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The payroll job queue is unavailable.",
        ) from exc
    return {
        "job_id": job_id,
        "status": "QUEUED",
        "progress_url": f"/api/v1/jobs/{job_id}",
    }


@router.get("/{job_id}")
def payroll_job_status(
    job_id: str,
    principal: AuthenticatedPrincipal = Depends(require_roles("ADMIN", "HR")),
):
    try:
        UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc

    _require_available_worker()
    result = celery_app.AsyncResult(job_id)
    state = result.state
    info = result.info if isinstance(result.info, dict) else {}
    if state == "SUCCESS":
        return {
            "job_id": job_id,
            "status": "COMPLETED",
            "progress": 100,
            "result": result.result,
        }
    if state == "FAILURE":
        return {
            "job_id": job_id,
            "status": "FAILED",
            "progress": 100,
            "error": str(result.result),
        }
    if state == "PROGRESS":
        return {
            "job_id": job_id,
            "status": "RUNNING",
            **info,
        }
    if state == "QUEUED":
        return {
            "job_id": job_id,
            "status": "QUEUED",
            "progress": 0,
        }
    if state == "STARTED":
        return {"job_id": job_id, "status": "RUNNING", "progress": 0}
    raise HTTPException(status_code=404, detail="Job not found")
