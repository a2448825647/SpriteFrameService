"""历史记录 API：查看与回退。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import get_session
from app.api.schemas import RevertRequest
from app.services.job_manager import job_manager

router = APIRouter(prefix="/sessions/{session_id}/history", tags=["history"])


@router.get("")
def get_history(session_id: str):
    session = get_session(session_id)
    entries = []
    for e in session.history.get_entries():
        entries.append({
            "step_id": e.step_id,
            "operation_name": e.operation_name,
            "description": e.description,
            "affected_count": len(e.affected_indices),
            "affected_indices": e.affected_indices[:50],
            "memory_bytes": e.memory_bytes,
            "timestamp": e.timestamp,
        })
    return {"entries": entries, "memory": session.history.get_memory_usage()}


@router.post("/revert")
def revert_history(session_id: str, req: RevertRequest):
    session = get_session(session_id)

    def _job(ctx):
        ctx.report(0, "回退中...")
        affected = session.history.revert_to(req.step_id, session.frame_manager)
        session.flush_modified_frames(affected)
        session.persist_metadata()
        session.clear_frame_arrays()
        ctx.report(100, "回退完成")
        return {"affected": affected, "count": len(affected)}

    job = job_manager.submit("history-revert", _job)
    return {"job_id": job.id}
