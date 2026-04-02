import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Optional


_JOBS: dict[str, dict[str, Any]] = {}
_TASKS: dict[str, asyncio.Task] = {}
_LOCK = asyncio.Lock()


_ALLOWED_FIELDS = {
    "status",
    "stage",
    "progress",
    "error",
    "data",
    "meta",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def create_job(meta: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    now = _utc_now()
    job = {
        "id": job_id,
        "status": "queued",
        "stage": "任务已创建",
        "progress": 0,
        "error": "",
        "data": None,
        "meta": meta or {},
        "created_at": now,
        "updated_at": now,
    }

    async with _LOCK:
        _JOBS[job_id] = job
    return dict(job)


async def update_job(job_id: str, **fields) -> Optional[dict[str, Any]]:
    now = _utc_now()
    async with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None

        for key, value in fields.items():
            if key in _ALLOWED_FIELDS:
                job[key] = value

        progress = job.get("progress")
        if isinstance(progress, (int, float)):
            job["progress"] = max(0, min(100, int(progress)))

        job["updated_at"] = now
        return dict(job)


async def get_job(job_id: str) -> Optional[dict[str, Any]]:
    async with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


async def list_jobs(limit: int = 30) -> list[dict[str, Any]]:
    async with _LOCK:
        jobs = sorted(
            _JOBS.values(),
            key=lambda x: x.get("created_at", ""),
            reverse=True,
        )
        return [dict(x) for x in jobs[:limit]]


async def attach_task(job_id: str, task: asyncio.Task) -> None:
    async with _LOCK:
        _TASKS[job_id] = task


async def finish_task(job_id: str) -> None:
    async with _LOCK:
        _TASKS.pop(job_id, None)


async def cancel_task(job_id: str) -> bool:
    async with _LOCK:
        task = _TASKS.get(job_id)
    if not task:
        return False
    task.cancel()
    return True
