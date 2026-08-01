"""帧提取器模块（移植自 SpriteFrameStudio）。"""
from __future__ import annotations

from typing import List, Optional, Callable

import cv2
import numpy as np

from app.models.frame_data import FrameData, VideoInfo


class FrameExtractor:
    """帧提取器 - 从视频中按指定参数提取帧"""

    def __init__(self):
        self._cancel_flag = False

    def cancel(self):
        """取消提取操作"""
        self._cancel_flag = True

    def _check_seek_available(self, cap: cv2.VideoCapture, video_fps: float) -> bool:
        """检查视频是否支持帧定位"""
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        cap.read()

        target_frame = int(1.0 * video_fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        actual_pos = cap.get(cv2.CAP_PROP_POS_FRAMES)

        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

        return actual_pos >= 0 and abs(actual_pos - target_frame) <= 1

    def extract_frames(
        self,
        video_path: str,
        start_time: float,
        end_time: float,
        extract_fps: float,
        video_info: VideoInfo,
        progress_callback: Optional[Callable[[int, int, float], None]] = None
    ) -> List[FrameData]:
        """从视频中提取帧。

        Args:
            video_path: 视频文件路径
            start_time: 开始时间(秒)
            end_time: 结束时间(秒)
            extract_fps: 提取帧率(每秒多少帧)
            video_info: 视频信息
            progress_callback: 进度回调 (current, total, percent)
        """
        self._cancel_flag = False
        frames: List[FrameData] = []

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise IOError(f"无法打开视频文件: {video_path}")

        try:
            video_fps = video_info.fps
            duration = end_time - start_time
            frame_interval = 1.0 / extract_fps

            timestamps = []
            total_frames = int(duration * extract_fps) + 1
            for i in range(total_frames):
                timestamp = start_time + i * frame_interval
                if timestamp <= end_time:
                    timestamps.append(timestamp)

            total_frames = len(timestamps)

            seek_available = self._check_seek_available(cap, video_fps)

            if not seek_available:
                cap.release()
                cap = cv2.VideoCapture(video_path)

            if seek_available:
                for idx, timestamp in enumerate(timestamps):
                    if self._cancel_flag:
                        break

                    frame_number = round(timestamp * video_fps)

                    total_video_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    frame_number = max(0, min(frame_number, total_video_frames - 1))

                    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
                    ret, frame = cap.read()

                    if ret:
                        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        frames.append(FrameData(
                            index=idx,
                            timestamp=timestamp,
                            image=frame_rgb
                        ))

                    if progress_callback:
                        progress = (idx + 1) / total_frames * 100
                        progress_callback(idx + 1, total_frames, progress)
            else:
                target_frames = {round(ts * video_fps): (idx, ts) for idx, ts in enumerate(timestamps)}
                current_frame = 0

                while True:
                    if self._cancel_flag:
                        break

                    ret, frame = cap.read()
                    if not ret:
                        break

                    if current_frame in target_frames:
                        idx, timestamp = target_frames[current_frame]
                        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        frames.append(FrameData(
                            index=idx,
                            timestamp=timestamp,
                            image=frame_rgb
                        ))

                        if progress_callback:
                            progress = len(frames) / total_frames * 100
                            progress_callback(len(frames), total_frames, progress)

                        if len(frames) >= total_frames:
                            break

                    current_frame += 1
        finally:
            cap.release()

        return frames

    def extract_single_frame(
        self,
        video_path: str,
        timestamp: float,
        video_fps: float
    ) -> Optional[np.ndarray]:
        """提取单帧"""
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return None

        try:
            frame_number = int(timestamp * video_fps)

            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            actual_pos = cap.get(cv2.CAP_PROP_POS_FRAMES)

            if actual_pos < 0:
                cap.release()
                cap = cv2.VideoCapture(video_path)
                for _ in range(frame_number):
                    if not cap.read()[0]:
                        return None

            ret, frame = cap.read()

            if ret:
                return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            return None
        finally:
            cap.release()
