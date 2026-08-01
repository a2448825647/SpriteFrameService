"""背景处理 API：AI/颜色抠图、参数测试、描边。"""
from __future__ import annotations

from typing import Tuple

from fastapi import APIRouter, HTTPException, Response

from app.api.deps import get_session, require_indices
from app.api.schemas import BackgroundParams, BackgroundRemoveRequest, BackgroundTestRequest, OutlineRequest
from app.core.background_remover import BackgroundMode, BackgroundRemover
from app.services.job_manager import job_manager
from app.utils.image_utils import encode_preview

router = APIRouter(prefix="/sessions/{session_id}/background", tags=["background"])


def _ai_params(p: BackgroundParams) -> dict:
    return {
        "model": p.model,
        "alpha_threshold": p.alpha_threshold,
        "erode": p.erode,
        "feather": p.feather,
        "force_cpu": p.force_cpu,
    }


def _color_params(p: BackgroundParams) -> dict:
    return {
        "lower": tuple(p.lower) if p.lower else (35, 50, 50),
        "upper": tuple(p.upper) if p.upper else (85, 255, 255),
        "invert": bool(p.invert) if p.invert is not None else False,
        "feather": p.color_feather if p.color_feather is not None else 0,
        "denoise": p.denoise if p.denoise is not None else 1,
    }


@router.get("/models")
def background_models(session_id: str):
    """可用 AI 模型 + 颜色预设。"""
    return {
        "models": BackgroundRemover.get_available_models(),
        "presets": BackgroundRemover.get_color_presets(),
    }


@router.get("/presets")
def color_presets(session_id: str):
    return BackgroundRemover.get_color_presets()


@router.post("/test")
def test_background(session_id: str, req: BackgroundTestRequest):
    """单帧参数测试：返回处理后图像（PNG）。"""
    session = get_session(session_id)
    img = session.load_display_array(req.frame_index)
    if img is None:
        raise HTTPException(status_code=404, detail="帧图像不存在")
    session.clear_frame_arrays()

    remover = BackgroundRemover()
    mode = BackgroundMode.AI if req.mode == "ai" else BackgroundMode.COLOR
    params = _ai_params(req.params) if req.mode == "ai" else _color_params(req.params)

    try:
        result = remover.remove_background(img, mode=mode, ai_params=params, color_params=params)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理失败: {e}")

    bytes_data = encode_preview(result, transparent_checker=True)
    return Response(content=bytes_data, media_type="image/png")


@router.post("/remove")
def remove_background(session_id: str, req: BackgroundRemoveRequest):
    session = get_session(session_id)
    indices = require_indices(session, req.indices)
    mode = BackgroundMode.AI if req.mode == "ai" else BackgroundMode.COLOR
    params = _ai_params(req.params) if req.mode == "ai" else _color_params(req.params)

    def _job(ctx):
        remover = BackgroundRemover()
        ctx.register_cancel(remover.cancel)
        ctx.report(0, "开始抠图...")

        arrays = session.load_display_arrays(indices)

        # 历史快照（供回退）
        session.history.push_snapshot(
            "背景去除",
            f"{'AI' if req.mode == 'ai' else '颜色'}抠图 | {len(indices)}帧",
            indices, session.frame_manager,
        )

        processed = 0
        for i, (idx, img) in enumerate(zip(indices, arrays)):
            if ctx.cancelled():
                break
            if img is None:
                continue
            result = remover.remove_background(img, mode=mode, ai_params=params, color_params=params)
            session.save_processed(idx, result)
            processed += 1
            ctx.report((i + 1) / len(indices) * 100, f"抠图 {i+1}/{len(indices)}")

        session.clear_frame_arrays()
        session.persist_metadata()
        ctx.report(100, f"抠图完成: {processed}/{len(indices)} 帧")
        return {"mode": req.mode, "processed": processed, "total": len(indices)}

    job = job_manager.submit("background", _job)
    return {"job_id": job.id}


@router.post("/outline")
def add_outline(session_id: str, req: OutlineRequest):
    session = get_session(session_id)
    indices = require_indices(session, req.indices)
    color: Tuple[int, int, int] = tuple(req.color)

    def _job(ctx):
        remover = BackgroundRemover()
        ctx.report(0, "开始描边...")

        arrays = session.load_display_arrays(indices)

        session.history.push_snapshot(
            "描边",
            f"描边 {req.thickness}px RGB{color} | {len(indices)}帧",
            indices, session.frame_manager,
        )

        processed = 0
        for i, (idx, img) in enumerate(zip(indices, arrays)):
            if ctx.cancelled():
                break
            if img is None:
                continue
            # 描边仅对 RGBA 有意义
            if len(img.shape) == 3 and img.shape[2] == 4:
                result = remover.add_outline(img, req.thickness, color)
                session.save_processed(idx, result)
                processed += 1
            ctx.report((i + 1) / len(indices) * 100, f"描边 {i+1}/{len(indices)}")

        session.clear_frame_arrays()
        session.persist_metadata()
        ctx.report(100, f"描边完成: {processed}/{len(indices)} 帧")
        return {"processed": processed, "total": len(indices)}

    job = job_manager.submit("outline", _job)
    return {"job_id": job.id}
