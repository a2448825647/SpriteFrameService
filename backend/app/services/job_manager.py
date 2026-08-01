"""进程内后台任务管理器（线程池执行长任务，前端轮询状态）。"""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Any

from app.config import get_settings


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class Job:
    id: str
    type: str
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0
    message: str = ""
    result: Optional[Any] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    cancel_requested: bool = False
    _cancel_callbacks: List[Callable[[], None]] = field(default_factory=list)
    _lock: Any = field(default_factory=threading.Lock)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "status": self.status.value,
            "progress": round(self.progress, 1),
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


class JobContext:
    """传给任务函数的上下文：进度上报 / 结果 / 取消。"""

    def __init__(self, job: Job):
        self._job = job

    def report(self, percent: float, message: str = "") -> None:
        with self._job._lock:
            self._job.progress = float(percent)
            if message:
                self._job.message = message

    def set_result(self, data: Any) -> None:
        with self._job._lock:
            self._job.result = data

    def cancelled(self) -> bool:
        return self._job.cancel_requested

    def register_cancel(self, fn: Callable[[], None]) -> None:
        with self._job._lock:
            self._job._cancel_callbacks.append(fn)


class JobManager:
    """线程池任务管理器。"""

    def __init__(self, max_workers: Optional[int] = None):
        self._jobs: Dict[str, Job] = {}
        self._jobs_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers or get_settings().max_workers,
            thread_name_prefix="spriteframe-job",
        )

    def submit(self, job_type: str, fn: Callable[[JobContext], Any]) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], type=job_type)
        with self._jobs_lock:
            self._jobs[job.id] = job

        def _runner():
            with job._lock:
                job.status = JobStatus.RUNNING
            ctx = JobContext(job)
            try:
                result = fn(ctx)
                if not ctx.cancelled():
                    with job._lock:
                        job.status = JobStatus.DONE
                        job.result = result
                        job.progress = 100.0
            except Exception as e:
                with job._lock:
                    job.status = JobStatus.ERROR
                    job.error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            finally:
                job.finished_at = time.time()

        self._executor.submit(_runner)
        return job

    def cancel(self, job_id: str) -> bool:
        with self._jobs_lock:
            job = self._jobs.get(job_id)
        if job is None:
            return False
        with job._lock:
            job.cancel_requested = True
            if job.status == JobStatus.QUEUED:
                job.status = JobStatus.CANCELLED
                job.finished_at = time.time()
            cbs = list(job._cancel_callbacks)
        for cb in cbs:
            try:
                cb()
            except Exception:
                pass
        return True

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def list(self, limit: int = 50) -> list[dict]:
        with self._jobs_lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)[:limit]
        return [j.to_dict() for j in jobs]


job_manager = JobManager()
