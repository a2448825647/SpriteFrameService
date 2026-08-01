"""帧图像落盘/读取：原始帧与处理后帧分别存 PNG（以帧 id 命名），元数据写 frames.json。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

import numpy as np

from app.core.frame_manager import FrameManager
from app.models.frame_data import FrameData, FrameStatus
from app.services.storage import SessionStorage
from app.utils.image_utils import read_image, save_image


def _frame_to_dict(frame: FrameData) -> dict:
    return {
        "id": frame.id,
        "index": frame.index,
        "timestamp": frame.timestamp,
        "status": frame.status.value,
        "is_selected": frame.is_selected,
        "image_path": str(frame.image_path) if frame.image_path else None,
        "processed_path": str(frame.processed_path) if frame.processed_path else None,
        "pose_id": frame.pose_id,
        "contour_id": frame.contour_id,
        "image_feature_id": frame.image_feature_id,
        "regional_feature_id": frame.regional_feature_id,
        "tag": frame.tag,
    }


class FrameStore:
    """帧存储：内存 FrameManager 的磁盘后端（文件以帧 id 命名）。"""

    def __init__(self, storage: SessionStorage):
        self._storage = storage

    # --- 保存 ---
    def save_raw_frames(self, frames: List[FrameData]) -> None:
        """将内存中的原始帧数组落盘，并清空数组只留路径。"""
        for frame in frames:
            if frame.image is not None:
                path = self._storage.raw_path(frame.id)
                save_image(path, frame.image)
                frame.image_path = path
                frame.image = None  # 释放内存

    def save_processed(self, frame_id: str, image: np.ndarray) -> Path:
        """保存处理后帧并返回路径。"""
        path = self._storage.proc_path(frame_id)
        save_image(path, image)
        return path

    # --- 读取 ---
    def load_raw(self, frame_id: str) -> Optional[np.ndarray]:
        path = self._storage.raw_path(frame_id)
        return read_image(path) if path.exists() else None

    def load_processed(self, frame_id: str) -> Optional[np.ndarray]:
        path = self._storage.proc_path(frame_id)
        return read_image(path) if path.exists() else None

    def raw_path(self, frame_id: str) -> Path:
        return self._storage.raw_path(frame_id)

    def proc_path(self, frame_id: str) -> Path:
        return self._storage.proc_path(frame_id)

    def remove_frame_files(self, frame_id: str) -> None:
        """删除帧的原始/处理文件。"""
        self._storage.remove_frame_files(frame_id)

    # --- 元数据 ---
    def save_metadata(self, frame_manager: FrameManager) -> None:
        """将当前帧元数据写入 frames.json。"""
        payload = [_frame_to_dict(f) for f in frame_manager.frames]
        self._storage.frames_json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1),
            encoding="utf-8"
        )

    def load_metadata(self, frame_manager: FrameManager) -> None:
        """从 frames.json 恢复帧元数据（仅当内存为空时）。"""
        if frame_manager.frame_count > 0 or not self._storage.frames_json.exists():
            return
        try:
            payload = json.loads(self._storage.frames_json.read_text(encoding="utf-8"))
        except Exception:
            return

        for d in payload:
            kwargs = {
                "index": d["index"],
                "timestamp": d["timestamp"],
                "status": FrameStatus(d.get("status", "raw")),
                "is_selected": d.get("is_selected", False),
                "image_path": Path(d["image_path"]) if d.get("image_path") else None,
                "processed_path": Path(d["processed_path"]) if d.get("processed_path") else None,
                "pose_id": d.get("pose_id"),
                "contour_id": d.get("contour_id"),
                "image_feature_id": d.get("image_feature_id"),
                "regional_feature_id": d.get("regional_feature_id"),
            }
            if d.get("id"):
                kwargs["id"] = d["id"]
            if d.get("tag"):
                kwargs["tag"] = d["tag"]
            frame_manager.add_frame(FrameData(**kwargs))
