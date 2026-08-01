"""视频处理核心模块（移植自 SpriteFrameStudio）。"""
from __future__ import annotations

from typing import Optional, Dict, List
from pathlib import Path

import cv2
import numpy as np
import threading
import time

from app.models.frame_data import VideoInfo


class VideoProcessor:
    """视频处理器 - 负责视频加载和元数据提取"""

    def __init__(self):
        self._cap: Optional[cv2.VideoCapture] = None
        self._video_info: Optional[VideoInfo] = None
        self._frame_cache: Dict[int, np.ndarray] = {}
        self._base_cache_size = 200
        self._cache_size = self._base_cache_size
        self._last_accessed_frame = -1
        self._use_sequential_mode = False
        self._lock = threading.RLock()
        self._preload_thread: Optional[threading.Thread] = None
        self._preload_stop_event = threading.Event()
        self._preload_queue: List[int] = []
        self._preload_batch_size = 30
        self._max_preload_batch_size = 50
        self._min_preload_batch_size = 10

    @property
    def is_loaded(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    @property
    def video_info(self) -> Optional[VideoInfo]:
        return self._video_info

    def load_video(self, path: str) -> VideoInfo:
        """加载视频文件并提取元数据"""
        self.release()

        video_path = Path(path)
        if not video_path.exists():
            raise FileNotFoundError(f"视频文件不存在: {path}")

        self._cap = cv2.VideoCapture(str(video_path))
        if not self._cap.isOpened():
            raise IOError(f"无法打开视频文件: {path}")

        width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = self._cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))

        fourcc = int(self._cap.get(cv2.CAP_PROP_FOURCC))
        codec = "".join([chr((fourcc >> 8 * i) & 0xFF) for i in range(4)])

        duration = frame_count / fps if fps > 0 else 0

        self._video_info = VideoInfo(
            path=video_path,
            width=width,
            height=height,
            fps=fps,
            frame_count=frame_count,
            duration=duration,
            codec=codec
        )

        self._detect_seek_mode()
        self._adjust_cache_settings()

        return self._video_info

    def _adjust_cache_settings(self):
        """根据视频特性动态调整缓存设置"""
        if not self._video_info:
            return

        width = self._video_info.width
        height = self._video_info.height
        fps = self._video_info.fps
        resolution = width * height

        if resolution > 1920 * 1080:
            self._cache_size = max(100, int(self._base_cache_size * 0.5))
            self._preload_batch_size = min(self._max_preload_batch_size, 20)
        elif resolution > 1280 * 720:
            self._cache_size = self._base_cache_size
            self._preload_batch_size = 30
        else:
            self._cache_size = min(500, int(self._base_cache_size * 2))
            self._preload_batch_size = min(self._max_preload_batch_size, 40)

        if fps > 60:
            self._preload_batch_size = min(self._max_preload_batch_size, self._preload_batch_size + 10)
        elif fps < 24:
            self._preload_batch_size = max(self._min_preload_batch_size, self._preload_batch_size - 10)

    def _detect_seek_mode(self):
        """检测视频是否需要使用顺序读取模式"""
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        self._cap.read()

        target_frame = int(1.0 * self._video_info.fps)
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        actual_pos = self._cap.get(cv2.CAP_PROP_POS_FRAMES)

        self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

        self._use_sequential_mode = actual_pos < 0 or abs(actual_pos - target_frame) > 1

    def get_frame_at(self, timestamp: float) -> Optional[np.ndarray]:
        """获取指定时间戳的帧"""
        if not self.is_loaded or self._video_info is None:
            return None

        frame_number = int(timestamp * self._video_info.fps)
        return self.get_frame_by_index(frame_number)

    def get_frame_by_index(self, frame_index: int) -> Optional[np.ndarray]:
        """获取指定索引的帧"""
        if not self.is_loaded or self._video_info is None:
            return None

        if frame_index < 0 or frame_index >= self._video_info.frame_count:
            return None

        with self._lock:
            if frame_index in self._frame_cache:
                frame = self._frame_cache.pop(frame_index)
                self._frame_cache[frame_index] = frame
                self._last_accessed_frame = frame_index
                return frame.copy()

        if self._use_sequential_mode:
            frame = self._get_frame_sequential(frame_index)
        else:
            frame = self._get_frame_seek(frame_index)

        if frame is not None:
            self._add_to_cache(frame_index, frame)
            self._last_accessed_frame = frame_index
            return frame.copy()
        return None

    def _get_frame_seek(self, frame_index: int) -> Optional[np.ndarray]:
        """使用帧定位获取帧"""
        with self._lock:
            try:
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                ret, frame = self._cap.read()
                if ret:
                    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            except Exception as e:
                print(f"Error in _get_frame_seek: {e}")
            return None

    def _get_frame_sequential(self, frame_index: int) -> Optional[np.ndarray]:
        """顺序读取获取帧"""
        with self._lock:
            try:
                if frame_index == self._last_accessed_frame + 1:
                    ret, frame = self._cap.read()
                    if ret:
                        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    return None

                if not (frame_index > 0 and (frame_index - 1) in self._frame_cache):
                    timestamp_ms = (frame_index / self._video_info.fps) * 1000
                    self._cap.set(cv2.CAP_PROP_POS_MSEC, timestamp_ms)
                    actual_pos = self._cap.get(cv2.CAP_PROP_POS_FRAMES)

                    if actual_pos < 0:
                        self._cap.release()
                        self._cap = cv2.VideoCapture(str(self._video_info.path))
                        for _ in range(frame_index):
                            self._cap.read()

                ret, frame = self._cap.read()
                if ret:
                    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            except Exception as e:
                print(f"Error in _get_frame_sequential: {e}")
            return None

    def _add_to_cache(self, frame_index: int, frame: np.ndarray):
        """添加帧到缓存（LRU）"""
        with self._lock:
            if frame_index in self._frame_cache:
                del self._frame_cache[frame_index]
            self._frame_cache[frame_index] = frame.copy()

            if len(self._frame_cache) > self._cache_size:
                oldest_frame = next(iter(self._frame_cache))
                del self._frame_cache[oldest_frame]

    def get_frame_count_in_range(self, start_time: float, end_time: float, fps: float) -> int:
        """计算时间范围内按指定帧率的帧数"""
        duration = end_time - start_time
        return max(1, int(duration * fps))

    def release(self):
        """释放视频资源"""
        self.stop_preload()

        if self._cap is not None:
            self._cap.release()
            self._cap = None
            self._video_info = None
            with self._lock:
                self._frame_cache.clear()
            self._last_accessed_frame = -1
            self._use_sequential_mode = False

    def start_preload(self):
        """开始预加载线程"""
        if self._preload_thread is not None and self._preload_thread.is_alive():
            return

        self._preload_stop_event.clear()
        self._preload_thread = threading.Thread(target=self._preload_worker, daemon=True)
        self._preload_thread.start()

    def stop_preload(self):
        """停止预加载线程"""
        if self._preload_thread is not None:
            self._preload_stop_event.set()
            if self._preload_thread.is_alive():
                self._preload_thread.join(timeout=1.0)
            self._preload_thread = None

    def preload_range(self, start_frame: int, end_frame: int):
        """预加载指定范围的帧"""
        if not self.is_loaded or self._video_info is None:
            return

        start_frame = max(0, start_frame)
        end_frame = min(end_frame, self._video_info.frame_count - 1)

        with self._lock:
            self._preload_queue = list(range(start_frame, end_frame + 1))

    def _preload_worker(self):
        """预加载工作线程"""
        while not self._preload_stop_event.is_set():
            frames_to_preload = []
            with self._lock:
                if self._preload_queue:
                    frames_to_preload = self._preload_queue[:self._preload_batch_size]
                    self._preload_queue = self._preload_queue[self._preload_batch_size:]

            if frames_to_preload:
                for frame_index in frames_to_preload:
                    if self._preload_stop_event.is_set():
                        break
                    with self._lock:
                        if frame_index in self._frame_cache:
                            continue
                    try:
                        self.get_frame_by_index(frame_index)
                    except Exception as e:
                        print(f"Error in preload: {e}")
                        time.sleep(0.05)
                time.sleep(0.02)
            else:
                time.sleep(0.2)
