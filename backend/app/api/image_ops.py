"""图像处理 API：缩放、空白裁剪、边缘优化、RealESRGAN 增强、魔棒编辑。"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Response
from PIL import Image

from app.api.deps import get_session, require_indices
from app.api.schemas import (
    CropRequest, EnhanceRequest, OptimizeEdgesRequest,
    ScaleRequest, WandApplyRequest, WandSelectRequest,
)
from app.core.magic_wand import MagicWand
from app.core.realesrgan_processor import RealESRGANProcessor
from app.services.job_manager import job_manager
from app.utils.image_utils import encode_preview

router = APIRouter(prefix="/sessions/{session_id}/image", tags=["image-ops"])

_ALGO_MAP = {
    "nearest": Image.Resampling.NEAREST,
    "box": Image.Resampling.BOX,
    "bilinear": Image.Resampling.BILINEAR,
    "hamming": Image.Resampling.HAMMING,
    "bicubic": Image.Resampling.BICUBIC,
    "lanczos": Image.Resampling.LANCZOS,
}


def _push_history(session, indices, name: str, desc: str):
    session.history.push_snapshot(name, desc, indices, session.frame_manager)


# ---------- 缩放 ----------
@router.post("/scale")
def scale_frames(session_id: str, req: ScaleRequest):
    session = get_session(session_id)
    indices = require_indices(session, req.indices)
    algo = _ALGO_MAP.get(req.algorithm, Image.Resampling.LANCZOS)

    def _job(ctx):
        ctx.report(0, "开始缩放...")
        arrays = session.load_display_arrays(indices)
        first = next((a for a in arrays if a is not None), None)
        if first is None:
            return {"processed": 0, "message": "没有可用的帧图像"}

        orig_h, orig_w = first.shape[:2]
        if req.mode == "percent":
            scale = req.percent / 100.0
            target_w, target_h = int(orig_w * scale), int(orig_h * scale)
        else:
            target_w, target_h = req.width, req.height

        if target_w < 1 or target_h < 1:
            return {"processed": 0, "message": "目标尺寸非法"}

        _push_history(session, indices, "批量缩放",
                      f"{len(indices)}帧 {orig_w}x{orig_h}→{target_w}x{target_h} {req.algorithm}")

        processed = 0
        for i, (idx, img) in enumerate(zip(indices, arrays)):
            if ctx.cancelled():
                break
            if img is None:
                continue
            pil = Image.fromarray(img)
            scaled = pil.resize((target_w, target_h), algo)
            session.save_processed(idx, np.array(scaled))
            processed += 1
            ctx.report((i + 1) / len(indices) * 100, f"缩放 {i+1}/{len(indices)}")

        session.clear_frame_arrays()
        session.persist_metadata()
        return {"processed": processed, "total": len(indices),
                "from": f"{orig_w}x{orig_h}", "to": f"{target_w}x{target_h}"}

    job = job_manager.submit("scale", _job)
    return {"job_id": job.id}


# ---------- 空白裁剪 ----------
@router.post("/crop-whitespace")
def crop_whitespace(session_id: str, req: CropRequest):
    session = get_session(session_id)
    indices = require_indices(session, req.indices)

    def _job(ctx):
        ctx.report(0, "计算统一裁剪区域...")
        arrays = session.load_display_arrays(indices)

        min_x, min_y = float('inf'), float('inf')
        max_x, max_y = 0, 0
        valid_arrays = []
        for idx, img in zip(indices, arrays):
            if img is None:
                continue
            valid_arrays.append((idx, img))
            if len(img.shape) == 3 and img.shape[2] == 4:
                alpha = img[:, :, 3]
                rows = np.any(alpha > 0, axis=1)
                cols = np.any(alpha > 0, axis=0)
            else:
                gray = np.mean(img, axis=2) if len(img.shape) == 3 else img
                rows = np.any(gray > 10, axis=1)
                cols = np.any(gray > 10, axis=0)
            if np.any(rows) and np.any(cols):
                y_idx = np.where(rows)[0]
                x_idx = np.where(cols)[0]
                min_x = min(min_x, int(x_idx[0]))
                max_x = max(max_x, int(x_idx[-1]))
                min_y = min(min_y, int(y_idx[0]))
                max_y = max(max_y, int(y_idx[-1]))

        if min_x == float('inf'):
            return {"processed": 0, "message": "未找到有效内容区域"}

        h, w = valid_arrays[0][1].shape[:2]
        min_x = max(0, min_x - req.margin_left)
        max_x = min(w - 1, max_x + req.margin_right)
        min_y = max(0, min_y - req.margin_top)
        max_y = min(h - 1, max_y + req.margin_bottom)

        crop_w = max_x - min_x + 1
        crop_h = max_y - min_y + 1

        _push_history(session, indices, "空白裁剪",
                      f"裁剪 {w}x{h}→{crop_w}x{crop_h} 边距({req.margin_top},{req.margin_bottom},{req.margin_left},{req.margin_right}) | {len(indices)}帧")

        processed = 0
        for i, (idx, img) in enumerate(valid_arrays):
            if ctx.cancelled():
                break
            cropped = img[min_y:max_y + 1, min_x:max_x + 1].copy()
            session.save_processed(idx, cropped)
            processed += 1
            ctx.report((i + 1) / len(valid_arrays) * 100, f"裁剪 {i+1}/{len(valid_arrays)}")

        session.clear_frame_arrays()
        session.persist_metadata()
        return {"processed": processed, "total": len(indices), "size": f"{crop_w}x{crop_h}"}

    job = job_manager.submit("crop", _job)
    return {"job_id": job.id}


# ---------- 边缘优化 ----------
@router.post("/optimize-edges")
def optimize_edges(session_id: str, req: OptimizeEdgesRequest):
    session = get_session(session_id)
    indices = require_indices(session, req.indices)

    def _job(ctx):
        ctx.report(0, "开始边缘优化...")
        arrays = session.load_display_arrays(indices)

        _push_history(session, indices, "边缘优化",
                      f"边缘收缩 {req.erode}px | {len(indices)}帧")

        kernel_size = req.erode * 2 + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))

        processed = 0
        for i, (idx, img) in enumerate(zip(indices, arrays)):
            if ctx.cancelled():
                break
            if img is None or len(img.shape) != 3 or img.shape[2] != 4:
                continue
            alpha = img[:, :, 3]
            eroded = cv2.erode(alpha, kernel, iterations=1)
            optimized = img.copy()
            optimized[:, :, 3] = eroded
            session.save_processed(idx, optimized)
            processed += 1
            ctx.report((i + 1) / len(indices) * 100, f"边缘优化 {i+1}/{len(indices)}")

        session.clear_frame_arrays()
        session.persist_metadata()
        return {"processed": processed, "total": len(indices)}

    job = job_manager.submit("optimize-edges", _job)
    return {"job_id": job.id}


# ---------- RealESRGAN 增强 ----------
@router.post("/enhance")
def enhance_frames(session_id: str, req: EnhanceRequest):
    session = get_session(session_id)
    indices = require_indices(session, req.indices)
    processor = RealESRGANProcessor()

    if not processor.is_available():
        raise HTTPException(status_code=400, detail="Real-ESRGAN 不可用（缺少可执行文件或模型）")

    def _job(ctx):
        ctx.report(0, "开始增强...")
        arrays = session.load_display_arrays(indices)

        _push_history(session, indices, "图像增强",
                      f"RealESRGAN {req.model} | {len(indices)}帧")

        processed = 0
        for i, (idx, img) in enumerate(zip(indices, arrays)):
            if ctx.cancelled():
                break
            if img is None:
                continue
            result = processor.process_image(img, model_name=req.model, tile=req.tile)
            if result is not None:
                session.save_processed(idx, result)
                processed += 1
            ctx.report((i + 1) / len(indices) * 100, f"增强 {i+1}/{len(indices)}")

        session.clear_frame_arrays()
        session.persist_metadata()
        return {"processed": processed, "total": len(indices), "model": req.model}

    job = job_manager.submit("enhance", _job)
    return {"job_id": job.id}


# ---------- 魔棒选区 ----------
@router.post("/wand/select")
def wand_select(session_id: str, req: WandSelectRequest):
    """魔棒选区：存储 mask 并返回选区信息（mask 图由 /wand/mask 提供）。"""
    session = get_session(session_id)
    img = session.load_display_array(req.frame_index)
    if img is None:
        raise HTTPException(status_code=404, detail="帧图像不存在")

    try:
        selection = MagicWand().select(
            img,
            req.x, req.y,
            tolerance=req.tolerance,
            contiguous=req.contiguous,
            anti_alias=req.anti_alias,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 存储 mask（会话级，每帧一个）
    if not hasattr(session, "wand_masks"):
        session.wand_masks = {}
    session.wand_masks[req.frame_index] = selection.mask

    session.clear_frame_arrays()

    return {
        "frame_index": req.frame_index,
        "area": selection.area,
        "bounds": {
            "x": selection.x, "y": selection.y,
            "width": selection.width, "height": selection.height,
        },
    }


@router.get("/wand/mask")
def wand_mask(session_id: str, frame_index: int):
    """返回已存储的选区 mask 图（PNG，蓝色高亮）。"""
    session = get_session(session_id)
    masks: Dict[int, np.ndarray] = getattr(session, "wand_masks", {})
    mask = masks.get(frame_index)
    if mask is None:
        raise HTTPException(status_code=404, detail="请先对该帧执行选区操作")

    mask_img = (mask * 255).astype(np.uint8) if mask.max() <= 1 else mask
    rgba = np.zeros((*mask_img.shape, 4), dtype=np.uint8)
    rgba[:, :, 2] = mask_img  # 蓝色通道显示选区
    rgba[:, :, 3] = mask_img

    # 保留透明通道（选区外透明），前端叠加到画布上时不遮挡原图
    bytes_data = encode_preview(rgba, transparent_checker=False)
    return Response(content=bytes_data, media_type="image/png")


@router.post("/wand/apply")
def wand_apply(session_id: str, req: WandApplyRequest):
    """应用魔棒选区：delete 清除选区，fill 用颜色填充。"""
    session = get_session(session_id)
    masks: Dict[int, np.ndarray] = getattr(session, "wand_masks", {})
    mask = masks.get(req.frame_index)
    if mask is None:
        raise HTTPException(status_code=400, detail="请先对该帧执行选区操作")

    img = session.load_display_array(req.frame_index)
    if img is None:
        raise HTTPException(status_code=404, detail="帧图像不存在")

    _push_history(session, [req.frame_index], "魔棒编辑",
                  f"{'删除选区' if req.operation == 'delete' else '填充选区'} | 帧 {req.frame_index}")

    from app.core.magic_wand import Selection
    wand = MagicWand()
    wand._selection = Selection(
        mask=mask,
        bounds=(0, 0, img.shape[1], img.shape[0]),
        area=int(np.count_nonzero(mask > 0)),
        seed_point=(0, 0),
        tolerance=0,
        contiguous=True,
    )

    result = wand.apply_to_image(
        img,
        operation=req.operation,
        fill_color=tuple(req.fill_color) if req.fill_color else None,
    )
    session.save_processed(req.frame_index, result)
    session.clear_frame_arrays()
    session.persist_metadata()

    return {"frame_index": req.frame_index, "operation": req.operation}
