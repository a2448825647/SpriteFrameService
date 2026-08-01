"""会话管理 API。"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import get_session
from app.services.session import session_manager

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("")
def create_session():
    session = session_manager.create()
    return {"id": session.id, "created_at": session.created_at}


@router.get("")
def list_sessions():
    return session_manager.list()


@router.get("/{session_id}")
def get_session_detail(session_id: str):
    session = get_session(session_id)
    return session.summary()


@router.delete("/{session_id}")
def delete_session(session_id: str):
    ok = session_manager.delete(session_id)
    return {"deleted": ok, "id": session_id}
