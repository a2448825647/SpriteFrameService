"""历史记录管理模块（移植自 SpriteFrameStudio）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Optional

import time

import numpy as np

from app.core.frame_manager import FrameManager
from app.models.frame_data import FrameData


@dataclass
class HistoryEntry:
    """单条历史记录"""
    step_id: int                              # 步骤编号（全局自增）
    operation_name: str                       # 操作名称
    description: str                          # 详细描述
    timestamp: float                          # 操作时间戳
    affected_indices: List[int]               # 受影响的帧索引列表
    snapshots: Dict[int, np.ndarray]          # {帧索引: 操作前的图像副本}
    snapshot_states: Dict[int, bool]          # {帧索引: 快照时是否有processed_image}
    memory_bytes: int                         # 本条快照占用内存（字节）


class HistoryManager:
    """历史记录管理器"""
    MAX_STEPS = 10                            # 最大历史步数

    def __init__(self):
        self._entries: List[HistoryEntry] = []
        self._step_counter: int = 1
        self._total_memory: int = 0

    def push_snapshot(self, name: str, description: str, frame_indices: List[int],
                      frame_manager: FrameManager) -> int:
        """创建快照并添加到历史记录"""
        snapshots = {}
        snapshot_states = {}
        memory_bytes = 0

        for idx in frame_indices:
            frame = frame_manager.get_frame(idx)
            if frame and frame.display_image is not None:
                snapshots[idx] = np.copy(frame.display_image)
                snapshot_states[idx] = frame.has_processed
                memory_bytes += snapshots[idx].nbytes

        entry = HistoryEntry(
            step_id=self._step_counter,
            operation_name=name,
            description=description,
            timestamp=time.time(),
            affected_indices=frame_indices,
            snapshots=snapshots,
            snapshot_states=snapshot_states,
            memory_bytes=memory_bytes
        )

        self._entries.append(entry)
        self._total_memory += memory_bytes
        self._step_counter += 1

        self._cleanup_history()

        return entry.step_id

    def revert_to(self, step_id: int, frame_manager: FrameManager) -> List[int]:
        """回退到指定步骤（恢复到该步骤执行后的状态）。

        step_id=0 表示回退到初始状态。
        """
        if not self._entries:
            return []

        if step_id == 0:
            target_idx = -1
        else:
            target_idx = None
            for i, entry in enumerate(self._entries):
                if entry.step_id == step_id:
                    target_idx = i
                    break

            if target_idx is None:
                return []

            if target_idx == len(self._entries) - 1:
                return []

        affected_indices = set()

        for i in range(len(self._entries) - 1, target_idx, -1):
            entry = self._entries[i]
            for idx, snapshot in entry.snapshots.items():
                frame = frame_manager.get_frame(idx)
                if frame:
                    was_processed = entry.snapshot_states.get(idx, False)
                    if was_processed:
                        frame.processed_image = snapshot
                    else:
                        frame.image = snapshot
                        frame.processed_image = None
                    affected_indices.add(idx)

            self._total_memory -= entry.memory_bytes
            entry.snapshots.clear()
            entry.snapshot_states.clear()

        self._entries = self._entries[:target_idx + 1]

        return list(affected_indices)

    def clear(self):
        """清空历史记录"""
        for entry in self._entries:
            entry.snapshots.clear()
            entry.snapshot_states.clear()
        self._entries.clear()
        self._total_memory = 0
        self._step_counter = 1

    def get_entries(self) -> List[HistoryEntry]:
        """获取历史记录列表（最新的在最前面）"""
        return list(reversed(self._entries))

    def get_memory_usage(self) -> str:
        current_mb = self._total_memory / (1024 * 1024)
        return f"{current_mb:.1f} MB"

    def _cleanup_history(self):
        while len(self._entries) > self.MAX_STEPS:
            oldest_entry = self._entries.pop(0)
            self._total_memory -= oldest_entry.memory_bytes
            oldest_entry.snapshots.clear()
            oldest_entry.snapshot_states.clear()
