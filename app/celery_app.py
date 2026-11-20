from celery import Celery

from .config import settings


celery_app = Celery(
    "ledgerforge",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(task_track_started=True)


@celery_app.task(
    bind=True,
    name="ledgerforge.process_18_month_payroll",
)
def process_18_month_payroll(self, job_id: str, processed_by: str) -> dict:
    from .routers.jobs import _run_18_month_payroll

    def report_progress(completed: int, total: int) -> None:
        progress = 95 if total == 0 else 10 + int(completed / total * 85)
        self.update_state(
            state="PROGRESS",
            meta={
                "progress": progress,
                "processed": completed,
                "total": total,
            },
        )

    return _run_18_month_payroll(job_id, processed_by, report_progress)
