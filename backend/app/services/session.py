"""会话管理：一个会话 = 一个视频项目，包含帧管理器/历史/分析数据。"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

import numpy as np

from app.core.frame_manager import FrameManager
from app.core.history_manager import HistoryManager
from app.core.pose_detector import PoseDetector
from app.core.video_processor import VideoProcessor
from app.models.frame_data import FrameStatus, VideoInfo
from app.services.frame_store import FrameStore
from app.services.storage import SessionStorage, create_session_storage
from app.utils.image_utils import save_image


class Session:
    """单个处理会话（内存态，生命周期 = 服务进程）。

    帧图像以文件形式存于磁盘（FrameStore），处理时按需载入内存。
    """

    def __init__(self, session_id: str, storage: SessionStorage):
        self.id = session_id
        self.storage = storage
        self.created_at = time.time()
        self.last_access = time.time()

        self.frame_manager = FrameManager()
        self.frame_store = FrameStore(storage)
        self.history = HistoryManager()
        self.video_info: Optional[VideoInfo] = None

        # 懒加载处理器
        self._video_processor: Optional[VideoProcessor] = None
        self._pose_detector: Optional[PoseDetector] = None

    # --- 访问跟踪 ---
    def touch(self):
        self.last_access = time.time()

    @property
    def video_processor(self) -> VideoProcessor:
        if self._video_processor is None:
            self._video_processor = VideoProcessor()
        return self._video_processor

    @property
    def pose_detector(self) -> PoseDetector:
        if self._pose_detector is None:
            self._pose_detector = PoseDetector()
        return self._pose_detector

    # --- 帧图像加载/保存 ---
    def load_display_array(self, index: int) -> Optional[np.ndarray]:
        """加载帧的显示图像（内存处理图 → 内存原图 → 磁盘处理图 → 磁盘原图）。"""
        frame = self.frame_manager.get_frame(index)
        if frame is None:
            return None
        if frame.processed_image is not None:
            return frame.processed_image
        if frame.image is not None:
            return frame.image
        if self.frame_store.proc_path(frame.id).exists():
            img = self.frame_store.load_processed(frame.id)
            frame.processed_image = img
            return img
        if self.frame_store.raw_path(frame.id).exists():
            img = self.frame_store.load_raw(frame.id)
            frame.image = img
            return img
        return None

    def load_display_arrays(self, indices: List[int]) -> List[Optional[np.ndarray]]:
        """批量加载显示图像（临时驻留内存供处理/历史快照使用）。"""
        return [self.load_display_array(i) for i in indices]

    def save_processed(self, index: int, image: np.ndarray) -> None:
        """保存处理后帧到磁盘并更新元数据，随后释放内存数组。"""
        frame = self.frame_manager.get_frame(index)
        if frame is None:
            return
        path = self.frame_store.save_processed(frame.id, image)
        frame.processed_path = path
        frame.processed_image = None
        frame.image = None
        frame.status = FrameStatus.BACKGROUND_REMOVED

    def save_original(self, index: int, image: np.ndarray) -> None:
        """保存（回写）原始帧到磁盘，并丢弃之前的处理结果。"""
        frame = self.frame_manager.get_frame(index)
        if frame is None:
            return
        path = self.frame_store.raw_path(frame.id)
        save_image(path, image)
        frame.image_path = path
        # 回退到原始状态时清理处理结果，避免预览仍读到旧的处理图
        candidates = [frame.processed_path, self.frame_store.proc_path(frame.id)]
        frame.processed_path = None
        frame.processed_image = None
        frame.image = None
        frame.status = FrameStatus.RAW
        for p in candidates:
            if p and p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass

    def clear_frame_arrays(self):
        """释放全部帧的内存数组（仅保留磁盘路径）。"""
        for f in self.frame_manager.frames:
            f.image = None
            f.processed_image = None

    def flush_modified_frames(self, indices: List[int]):
        """将指定帧的内存数组写回磁盘并清空。"""
        for idx in indices:
            frame = self.frame_manager.get_frame(idx)
            if frame is None:
                continue
            if frame.processed_image is not None:
                self.save_processed(idx, frame.processed_image)
            elif frame.image is not None:
                self.save_original(idx, frame.image)

    def persist_metadata(self):
        self.frame_store.save_metadata(self.frame_manager)

    # --- 概要 ---
    def summary(self) -> dict:
        fm = self.frame_manager
        return {
            "id": self.id,
            "created_at": self.created_at,
            "video_info": self.video_info.model_dump() if self.video_info else None,
            "frame_count": fm.frame_count,
            "selected_count": fm.selected_count,
            "history_steps": len(self.history.get_entries()),
            "history_memory": self.history.get_memory_usage(),
        }


class SessionManager:
    """会话注册表（内存）。"""

    def __init__(self):
        self._sessions: Dict[str, Session] = {}

    def create(self) -> Session:
        sid, storage = create_session_storage()
        session = Session(sid, storage)
        self._sessions[sid] = session
        return session

    def get(self, session_id: str) -> Optional[Session]:
        session = self._sessions.get(session_id)
        if session:
            session.touch()
        return session

    def get_required(self, session_id: str) -> Session:
        session = self.get(session_id)
        if session is None:
            raise KeyError(f"会话不存在: {session_id}")
        return session

    def delete(self, session_id: str) -> bool:
        session = self._sessions.pop(session_id, None)
        if session:
            # 先释放视频句柄，避免 Windows 下文件被占用无法删除
            if session._video_processor is not None:
                session._video_processor.release()
                session._video_processor = None
            if session._pose_detector is not None:
                session._pose_detector.release()
                session._pose_detector = None
            session.frame_manager.clear()
            session.storage.clear()
            return True
        return False

    def list(self) -> list[dict]:
        return [s.summary() for s in self._sessions.values()]

    def cleanup_idle(self, max_idle_seconds: float = 86400) -> int:
        """清理空闲超时的会话（默认 24h）。"""
        now = time.time()
        dead = [sid for sid, s in self._sessions.items()
                if now - s.last_access > max_idle_seconds]
        for sid in dead:
            self.delete(sid)
        return len(dead)


session_manager = SessionManager()
