"""后台任务 API：查询状态、取消。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.services.job_manager import job_manager

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("")
def list_jobs(limit: int = 50):
    return {"jobs": job_manager.list(limit=limit)}


@router.get("/{job_id}")
def get_job(job_id: str):
    job = job_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job.to_dict()


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str):
    ok = job_manager.cancel(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"cancelled": True, "id": job_id}
