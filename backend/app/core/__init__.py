"""核心处理模块（移植自 SpriteFrameStudio，去 Qt 依赖）。"""
from .frame_extractor import FrameExtractor
from .frame_manager import FrameManager
from .video_processor import VideoProcessor
from .exporter import Exporter
from .pose_detector import (
    PoseDetector, ContourData, ImageFeatureData, RegionalFeatureData,
)
from .realesrgan_processor import RealESRGANProcessor, RealESRGANModel
from .history_manager import HistoryManager
from .magic_wand import MagicWand, Selection
from .background_remover import (
    BackgroundRemover, BackgroundMode, AIModel, AI_MODEL_INFO,
)
from .crossfade import apply_loop_transition, apply_transition_to_frame_data
from .frame_supplement import interpolate_frames

__all__ = [
    "FrameExtractor",
    "FrameManager",
    "VideoProcessor",
    "Exporter",
    "PoseDetector", "ContourData", "ImageFeatureData", "RegionalFeatureData",
    "RealESRGANProcessor", "RealESRGANModel",
    "HistoryManager",
    "MagicWand", "Selection",
    "BackgroundRemover", "BackgroundMode", "AIModel", "AI_MODEL_INFO",
    "apply_loop_transition", "apply_transition_to_frame_data",
    "interpolate_frames",
]
