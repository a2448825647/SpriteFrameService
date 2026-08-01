"""能力探测：平台信息、可用模型、GPU 等。"""
from __future__ import annotations

import sys

from fastapi import APIRouter
import onnxruntime as ort

from app.config import get_settings
from app.core.background_remover import BackgroundRemover
from app.core.realesrgan_processor import RealESRGANProcessor
from app.utils.pngquant import is_pngquant_available

router = APIRouter(tags=["capabilities"])


@router.get("/capabilities")
def capabilities():
    settings = get_settings()
    realesrgan = RealESRGANProcessor()

    providers = ort.get_available_providers()

    return {
        "platform": {
            "os": sys.platform,
            "python": sys.version.split()[0],
            "onnxruntime_providers": providers,
            "gpu_available": "CUDAExecutionProvider" in providers and not settings.force_cpu,
        },
        "paths": {
            "data_dir": str(settings.resolved_data_dir),
            "models_dir": str(settings.resolved_models_dir),
            "frontend_dir": str(settings.resolved_frontend_dir),
        },
        "background_models": BackgroundRemover.get_available_models(),
        "color_presets": BackgroundRemover.get_color_presets(),
        "realesrgan": realesrgan.get_available_models(),
        "realesrgan_info": realesrgan.get_executable_info(),
        "pngquant": is_pngquant_available(),
        "analysis_modes": [
            {"key": "pose", "name": "姿势 (MediaPipe)"},
            {"key": "pose_rtm", "name": "姿势 (RTMPose)"},
            {"key": "contour", "name": "轮廓匹配"},
            {"key": "image", "name": "图像特征"},
            {"key": "regional", "name": "分区域SSIM"},
        ],
        "export_formats": [
            {"key": "sprite_sheet", "name": "PNG 精灵图 + JSON"},
            {"key": "gif", "name": "GIF 动画"},
            {"key": "frames", "name": "单独帧图片"},
            {"key": "webp", "name": "WebP"},
            {"key": "godot", "name": "Godot SpriteFrames"},
        ],
        "scale_algorithms": ["nearest", "box", "bilinear", "hamming", "bicubic", "lanczos"],
    }
