from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4


_lock = Lock()
_jobs: dict[str, dict[str, object]] = {}


def create_job(job_type: str) -> dict[str, object]:
    job_id = str(uuid4())
    job = {
        "job_id": job_id,
        "type": job_type,
        "status": "QUEUED",
        "progress": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "result": None,
        "error": None,
    }
    with _lock:
        _jobs[job_id] = job
    return dict(job)


def update_job(job_id: str, **changes: object) -> dict[str, object] | None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        job.update(changes)
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        return dict(job)


def get_job(job_id: str) -> dict[str, object] | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job is not None else None
