"""帧数据管理模块（移植自 SpriteFrameStudio，服务化后图像落盘、元数据在内存）。"""
from __future__ import annotations

from typing import List, Optional, Dict

import numpy as np

from app.models.frame_data import FrameData, FrameStatus
from app.models.pose_data import PoseData
from app.core.pose_detector import ContourData, ImageFeatureData, RegionalFeatureData


class FrameManager:
    """帧数据管理器 - 管理提取的帧集合"""

    def __init__(self):
        self._frames: List[FrameData] = []
        self._poses: Dict[str, PoseData] = {}
        self._contours: Dict[str, ContourData] = {}
        self._image_features: Dict[str, ImageFeatureData] = {}
        self._regional_features: Dict[str, RegionalFeatureData] = {}

    @property
    def frame_count(self) -> int:
        return len(self._frames)

    @property
    def frames(self) -> List[FrameData]:
        return self._frames

    @property
    def selected_frames(self) -> List[FrameData]:
        return [f for f in self._frames if f.is_selected]

    @property
    def selected_count(self) -> int:
        return len(self.selected_frames)

    def clear(self):
        """清空所有帧"""
        self._frames.clear()
        self._poses.clear()
        self._contours.clear()
        self._image_features.clear()
        self._regional_features.clear()

    def add_frames(self, frames: List[FrameData]):
        self._frames.extend(frames)

    def add_frame(self, frame: FrameData):
        self._frames.append(frame)

    def get_frame(self, index: int) -> Optional[FrameData]:
        if 0 <= index < len(self._frames):
            return self._frames[index]
        return None

    def remove_frame(self, index: int) -> bool:
        """删除指定索引的帧"""
        if 0 <= index < len(self._frames):
            frame = self._frames.pop(index)
            if frame.pose_id and frame.pose_id in self._poses:
                del self._poses[frame.pose_id]
            if frame.contour_id and frame.contour_id in self._contours:
                del self._contours[frame.contour_id]
            if frame.image_feature_id and frame.image_feature_id in self._image_features:
                del self._image_features[frame.image_feature_id]
            if frame.regional_feature_id and frame.regional_feature_id in self._regional_features:
                del self._regional_features[frame.regional_feature_id]
            for i in range(index, len(self._frames)):
                self._frames[i].index = i
            return True
        return False

    def select_frame(self, index: int, selected: bool = True):
        if 0 <= index < len(self._frames):
            self._frames[index].is_selected = selected

    def select_all(self):
        for frame in self._frames:
            frame.is_selected = True

    def deselect_all(self):
        for frame in self._frames:
            frame.is_selected = False

    def select_range(self, start: int, end: int):
        for i in range(max(0, start), min(end + 1, len(self._frames))):
            self._frames[i].is_selected = True

    def get_frames_by_status(self, status: FrameStatus) -> List[FrameData]:
        return [f for f in self._frames if f.status == status]

    def update_frame_image(self, index: int, image: np.ndarray, processed: bool = False):
        """更新帧图像（内存态）"""
        if 0 <= index < len(self._frames):
            if processed:
                self._frames[index].processed_image = image
                self._frames[index].status = FrameStatus.BACKGROUND_REMOVED
            else:
                self._frames[index].image = image

    def add_pose(self, pose: PoseData):
        self._poses[pose.id] = pose
        if 0 <= pose.frame_index < len(self._frames):
            self._frames[pose.frame_index].pose_id = pose.id
            self._frames[pose.frame_index].status = FrameStatus.POSE_DETECTED

    def get_pose(self, pose_id: str) -> Optional[PoseData]:
        return self._poses.get(pose_id)

    def get_pose_for_frame(self, frame_index: int) -> Optional[PoseData]:
        frame = self.get_frame(frame_index)
        if frame and frame.pose_id:
            return self._poses.get(frame.pose_id)
        return None

    def add_contour(self, contour: ContourData):
        self._contours[contour.id] = contour
        if 0 <= contour.frame_index < len(self._frames):
            self._frames[contour.frame_index].contour_id = contour.id

    def get_contour(self, contour_id: str) -> Optional[ContourData]:
        return self._contours.get(contour_id)

    def get_contour_for_frame(self, frame_index: int) -> Optional[ContourData]:
        frame = self.get_frame(frame_index)
        if frame and frame.contour_id:
            return self._contours.get(frame.contour_id)
        return None

    def add_image_feature(self, feature: ImageFeatureData):
        self._image_features[feature.id] = feature
        if 0 <= feature.frame_index < len(self._frames):
            self._frames[feature.frame_index].image_feature_id = feature.id

    def get_image_feature(self, feature_id: str) -> Optional[ImageFeatureData]:
        return self._image_features.get(feature_id)

    def get_image_feature_for_frame(self, frame_index: int) -> Optional[ImageFeatureData]:
        frame = self.get_frame(frame_index)
        if frame and frame.image_feature_id:
            return self._image_features.get(frame.image_feature_id)
        return None

    def add_regional_feature(self, feature: RegionalFeatureData):
        self._regional_features[feature.id] = feature
        if 0 <= feature.frame_index < len(self._frames):
            self._frames[feature.frame_index].regional_feature_id = feature.id

    def get_regional_feature(self, feature_id: str) -> Optional[RegionalFeatureData]:
        return self._regional_features.get(feature_id)

    def get_regional_feature_for_frame(self, frame_index: int) -> Optional[RegionalFeatureData]:
        frame = self.get_frame(frame_index)
        if frame and getattr(frame, 'regional_feature_id', None):
            return self._regional_features.get(frame.regional_feature_id)
        return None

    def get_frames_with_images(self) -> List[FrameData]:
        return [f for f in self._frames if f.has_image]

    def reorder_frames(self, new_order: List[int]):
        """重新排序帧"""
        if len(new_order) != len(self._frames):
            return

        new_frames = []
        for i, old_index in enumerate(new_order):
            if 0 <= old_index < len(self._frames):
                frame = self._frames[old_index]
                frame.index = i
                new_frames.append(frame)

        self._frames = new_frames
