"""视频上传与信息 API。"""
from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import get_session

router = APIRouter(prefix="/sessions/{session_id}/video", tags=["video"])


@router.post("")
async def upload_video(session_id: str, file: UploadFile = File(...)):
    """上传视频文件并读取元数据。"""
    session = get_session(session_id)

    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="文件为空")

    dest = session.storage.save_video(content, file.filename)

    try:
        video_info = session.video_processor.load_video(str(dest))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"无法解析视频: {e}")

    session.video_info = video_info

    # 清理旧的帧数据
    session.frame_manager.clear()
    session.history.clear()

    return {"video_info": video_info.model_dump(), "path": str(dest)}


@router.get("")
def get_video_file(session_id: str):
    """返回视频文件（供浏览器 <video> 预览）。"""
    session = get_session(session_id)
    path = session.storage.video_path
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="未上传视频")

    media_type = mimetypes.guess_type(path.name)[0] or "video/mp4"
    return FileResponse(str(path), media_type=media_type)


@router.get("/info")
def get_video_info(session_id: str):
    session = get_session(session_id)
    if session.video_info is None:
        path = session.storage.video_path
        if path is None:
            raise HTTPException(status_code=404, detail="未上传视频")
        session.video_info = session.video_processor.load_video(str(path))
    return session.video_info.model_dump()
