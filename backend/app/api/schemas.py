"""API 请求体模型。"""
from __future__ import annotations

from typing import List, Optional, Tuple

from pydantic import BaseModel, Field

from app.models.export_config import ExportConfig


# ---------- Frames ----------
class ExtractRequest(BaseModel):
    start_time: float = Field(0, ge=0, description="开始时间(秒)")
    end_time: float = Field(10, gt=0, description="结束时间(秒)")
    fps: float = Field(10, gt=0, le=60, description="提取帧率")


class SelectionRequest(BaseModel):
    mode: str = Field("set", description="set/clear/all/invert/range")
    indices: Optional[List[int]] = Field(default=None, description="目标帧索引")
    range_start: Optional[int] = Field(default=None, description="range 模式起点")
    range_end: Optional[int] = Field(default=None, description="range 模式终点")


class ReorderRequest(BaseModel):
    new_order: List[int] = Field(..., description="新的帧顺序（旧索引列表）")


class LoopTransitionRequest(BaseModel):
    indices: Optional[List[int]] = Field(default=None, description="参与过渡的帧（默认选中）")
    count: int = Field(5, ge=1, le=30, description="过渡帧数")
    mode: str = Field("blend", description="blend=像素混合 / align=轮廓对齐")
    fps: float = Field(10, gt=0, le=60, description="预览GIF帧率")


class SupplementRequest(BaseModel):
    indices: Optional[List[int]] = Field(default=None, description="使用其首帧与尾帧进行衔接（默认选中）")
    num_frames: int = Field(3, ge=1, le=7, description="生成中间帧数量")


# ---------- Analysis ----------
class DetectRequest(BaseModel):
    mode: str = Field("pose", description="pose/pose_rtm/contour/image/regional")
    indices: Optional[List[int]] = Field(default=None, description="要检测的帧")
    weights: Optional[Tuple[float, float, float]] = Field(
        default=None, description="regional 模式区域权重 (上,中,下)"
    )


class RemoveSimilarRequest(BaseModel):
    mode: str = Field("pose", description="pose/pose_rtm/contour/image/regional")
    threshold: float = Field(0.9, ge=0, le=1, description="相似度阈值(0-1)")
    indices: Optional[List[int]] = Field(default=None, description="处理范围")


class FindLoopRequest(BaseModel):
    mode: str = Field("pose", description="pose/pose_rtm/contour/image/regional")
    indices: Optional[List[int]] = Field(default=None, description="候选帧（首帧必须包含）")
    apply_range: bool = Field(True, description="是否应用建议范围（取消范围外的选中）")


# ---------- Background ----------
class BackgroundParams(BaseModel):
    model: str = Field("u2net", description="AI 模型名")
    alpha_threshold: int = Field(0, ge=0, le=255, description="Alpha阈值")
    erode: int = Field(0, description="腐蚀像素(负为膨胀)")
    feather: int = Field(0, ge=0, description="羽化像素")
    force_cpu: Optional[bool] = Field(default=None, description="强制CPU")
    # color 模式
    lower: Optional[Tuple[int, int, int]] = Field(default=None, description="HSV下限")
    upper: Optional[Tuple[int, int, int]] = Field(default=None, description="HSV上限")
    invert: Optional[bool] = Field(default=None, description="颜色模式是否反选")
    denoise: Optional[int] = Field(default=None, ge=0, description="颜色模式去噪")
    color_feather: Optional[int] = Field(default=None, ge=0, description="颜色模式羽化")


class BackgroundTestRequest(BaseModel):
    frame_index: int = Field(..., description="帧索引")
    mode: str = Field("ai", description="ai/color")
    params: Optional[BackgroundParams] = Field(default_factory=BackgroundParams)


class BackgroundRemoveRequest(BaseModel):
    indices: Optional[List[int]] = Field(default=None, description="目标帧")
    mode: str = Field("ai", description="ai/color")
    params: Optional[BackgroundParams] = Field(default_factory=BackgroundParams)


class OutlineRequest(BaseModel):
    indices: Optional[List[int]] = Field(default=None, description="目标帧")
    thickness: int = Field(3, ge=0, description="描边厚度")
    color: Tuple[int, int, int] = Field((0, 0, 0), description="描边颜色 RGB")


# ---------- Image ops ----------
class ScaleRequest(BaseModel):
    indices: Optional[List[int]] = Field(default=None, description="目标帧")
    mode: str = Field("percent", description="percent/size")
    percent: float = Field(50, ge=1, le=400, description="缩放比例(%)")
    width: int = Field(512, ge=1, description="目标宽度(size模式)")
    height: int = Field(512, ge=1, description="目标高度(size模式)")
    algorithm: str = Field("lanczos", description="缩放算法")


class CropRequest(BaseModel):
    indices: Optional[List[int]] = Field(default=None, description="目标帧")
    margin_top: int = Field(0, ge=0)
    margin_bottom: int = Field(0, ge=0)
    margin_left: int = Field(0, ge=0)
    margin_right: int = Field(0, ge=0)


class OptimizeEdgesRequest(BaseModel):
    indices: Optional[List[int]] = Field(default=None, description="目标帧")
    erode: int = Field(1, ge=1, le=20, description="边缘收缩像素")


class EnhanceRequest(BaseModel):
    indices: Optional[List[int]] = Field(default=None, description="目标帧")
    model: str = Field("realesrgan-x4plus", description="模型名")
    tile: int = Field(0, ge=0, description="分块大小(0不使用)")


class WandSelectRequest(BaseModel):
    frame_index: int = Field(..., description="帧索引")
    x: int = Field(..., description="种子点x")
    y: int = Field(..., description="种子点y")
    tolerance: int = Field(32, ge=0, le=255, description="颜色容差")
    contiguous: bool = Field(True, description="连续选区")
    anti_alias: bool = Field(True, description="抗锯齿")


class WandApplyRequest(BaseModel):
    frame_index: int = Field(..., description="帧索引")
    operation: str = Field("delete", description="delete/fill")
    fill_color: Optional[Tuple[int, int, int, int]] = Field(
        default=None, description="fill 模式填充色 RGBA"
    )
    mask_url: Optional[str] = Field(default=None, description="选区 mask 图 URL（与 select 接口配合）")


# ---------- Export ----------
class ExportRequest(BaseModel):
    config: ExportConfig = Field(..., description="导出配置")
    indices: Optional[List[int]] = Field(default=None, description="导出的帧索引(默认选中)")


# ---------- History ----------
class RevertRequest(BaseModel):
    step_id: int = Field(..., description="回退到的步骤ID，0 表示初始状态")
