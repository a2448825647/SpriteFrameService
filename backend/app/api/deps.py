"""API 依赖与共享工具。"""
from __future__ import annotations

from typing import List, Optional

from fastapi import HTTPException

from app.services.session import Session, session_manager


def get_session(session_id: str) -> Session:
    """获取会话，不存在则 404。"""
    session = session_manager.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    return session


def require_indices(session: Session, indices: Optional[List[int]] = None) -> List[int]:
    """解析批量操作的目标帧：指定索引 → 选中帧 → 全部帧。

    未指定且无选中时回退到全部帧，避免误报「没有可处理的帧」。
    """
    fm = session.frame_manager
    if indices is None or len(indices) == 0:
        indices = [f.index for f in fm.selected_frames]
        if not indices:
            indices = list(range(fm.frame_count))
    valid = []
    for i in indices:
        if 0 <= i < fm.frame_count and i not in valid:
            valid.append(i)
    if not valid:
        raise HTTPException(status_code=400, detail="没有可处理的帧（请先提取帧）")
    return valid
