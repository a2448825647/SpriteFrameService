"""首尾补帧工具 - 在尾帧与首帧之间生成中间帧，使动画循环无缝衔接。

轻量实现：线性插值（支持 RGB/RGBA，预乘 alpha 混合避免透明区污染）。
原项目使用 RIFE AI 插帧（需 PyTorch + 模型），此处提供无需额外依赖的版本；
后续如需 AI 级插帧，可在相同接口上替换实现。
"""
from __future__ import annotations

from typing import List, Optional, Callable

import numpy as np


def interpolate_frames(
    first_frame: np.ndarray,
    last_frame: np.ndarray,
    num_frames: int,
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> List[np.ndarray]:
    """
    在 last_frame -> first_frame 之间生成 num_frames 个中间帧。

    用于循环衔接：动画播放到末尾后，中间帧平滑过渡回首帧。
    返回列表长度为 num_frames（不包含原始尾帧与首帧）。

    Args:
        first_frame: 第一帧（作为终点）
        last_frame: 最后一帧（作为起点）
        num_frames: 需要生成的中间帧数量 (1-7)
        progress_callback: 进度回调 (current, total, message)
    """
    num_frames = max(1, min(int(num_frames), 7))

    if progress_callback:
        progress_callback(0, num_frames + 1, "预处理图像...")

    # 统一通道数（以两者较多者为准）
    src, dst, has_alpha = _normalize_channels(last_frame, first_frame)

    result = []
    for i in range(1, num_frames + 1):
        t = i / (num_frames + 1)
        frame = _blend_premultiplied(src, dst, t, has_alpha)
        result.append(frame)
        if progress_callback:
            progress_callback(i, num_frames + 1, f"生成中间帧 {i}/{num_frames}")

    if progress_callback:
        progress_callback(num_frames + 1, num_frames + 1, "完成")

    return result


def _normalize_channels(a: np.ndarray, b: np.ndarray):
    """将两帧统一为相同通道数（RGB -> RGBA 补全 alpha=255）。"""
    a_ch = a.shape[2] if len(a.shape) == 3 else 1
    b_ch = b.shape[2] if len(b.shape) == 3 else 1

    # 灰度转 RGB
    if a.ndim == 2:
        a = np.stack([a] * 3, axis=2)
    if b.ndim == 2:
        b = np.stack([b] * 3, axis=2)
    if a.ndim == 3 and a.shape[2] == 1:
        a = np.repeat(a, 3, axis=2)
    if b.ndim == 3 and b.shape[2] == 1:
        b = np.repeat(b, 3, axis=2)

    has_alpha = (a.shape[2] == 4 or b.shape[2] == 4)

    if has_alpha:
        a = _add_alpha(a)
        b = _add_alpha(b)

    return a.astype(np.float32), b.astype(np.float32), has_alpha


def _add_alpha(img: np.ndarray) -> np.ndarray:
    if img.ndim == 3 and img.shape[2] == 4:
        return img
    h, w = img.shape[:2]
    alpha = np.full((h, w, 1), 255, dtype=img.dtype)
    return np.concatenate([img, alpha], axis=2)


def _blend_premultiplied(src: np.ndarray, dst: np.ndarray, t: float,
                         has_alpha: bool) -> np.ndarray:
    """预乘 alpha 混合：t=0 -> src，t=1 -> dst。"""
    if not has_alpha:
        blended = (1.0 - t) * src + t * dst
        return np.clip(blended, 0, 255).astype(np.uint8)

    rgb_src = src[:, :, :3]
    rgb_dst = dst[:, :, :3]

    a_src = src[:, :, 3:4] / 255.0
    a_dst = dst[:, :, 3:4] / 255.0

    premul_src = rgb_src * a_src
    premul_dst = rgb_dst * a_dst
    blended_premul = (1.0 - t) * premul_src + t * premul_dst

    # alpha 取两者最大值，保持轮廓清晰（避免半透明重影）
    alpha_src = src[:, :, 3]
    alpha_dst = dst[:, :, 3]
    blended_alpha = np.maximum(alpha_src, alpha_dst)

    out_a = blended_alpha[:, :, np.newaxis] / 255.0
    safe_a = np.where(out_a > 1e-6, out_a, 1.0)
    blended_rgb = blended_premul / safe_a

    result = np.zeros(src.shape, dtype=np.uint8)
    result[:, :, :3] = np.clip(blended_rgb, 0, 255).astype(np.uint8)
    result[:, :, 3] = np.clip(blended_alpha, 0, 255).astype(np.uint8)
    return result
