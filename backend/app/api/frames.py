"""帧管理 API：抽帧、列表、图像服务、选择、删除、重排、循环过渡、首尾补帧。"""
from __future__ import annotations

from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, Query, Response

from app.api.deps import get_session, require_indices
from app.api.schemas import (
    ExtractRequest, LoopTransitionRequest, ReorderRequest,
    SelectionRequest, SupplementRequest,
)
from app.core.crossfade import apply_loop_transition
from app.core.frame_extractor import FrameExtractor
from app.core.frame_supplement import interpolate_frames
from app.models.frame_data import FrameData
from app.services.job_manager import job_manager
from app.utils.image_utils import encode_preview, read_image

router = APIRouter(prefix="/sessions/{session_id}/frames", tags=["frames"])


# ---------- 抽帧 ----------
@router.post("/extract")
def extract_frames(session_id: str, req: ExtractRequest):
    session = get_session(session_id)
    if session.video_info is None:
        raise HTTPException(status_code=400, detail="请先上传视频")
    if req.end_time > session.video_info.duration + 0.001:
        raise HTTPException(status_code=400, detail=f"结束时间超出视频时长 {session.video_info.duration:.2f}s")

    def _job(ctx):
        extractor = FrameExtractor()
        ctx.register_cancel(extractor.cancel)
        ctx.report(0, "开始抽帧...")

        video_path = session.storage.video_path
        frames = extractor.extract_frames(
            str(video_path),
            req.start_time, req.end_time, req.fps,
            session.video_info,
            progress_callback=lambda cur, total, pct: ctx.report(pct, f"抽帧 {cur}/{total}")
        )

        if ctx.cancelled():
            return None

        session.frame_manager.clear()
        session.frame_store.save_raw_frames(frames)
        session.frame_manager.add_frames(frames)
        session.persist_metadata()
        ctx.report(100, f"抽帧完成: {len(frames)} 帧")
        return {"extracted": len(frames), "start_time": req.start_time, "end_time": req.end_time}

    job = job_manager.submit("extract", _job)
    return {"job_id": job.id}


# ---------- 列表 ----------
def _frame_summary(frame) -> dict:
    return {
        "id": frame.id,
        "index": frame.index,
        "timestamp": frame.timestamp,
        "status": frame.status.value,
        "is_selected": frame.is_selected,
        "has_raw": frame.has_image,
        "has_processed": frame.has_processed,
        "tag": frame.tag,
        "analysis": {
            "pose": frame.pose_id is not None,
            "contour": frame.contour_id is not None,
            "image": frame.image_feature_id is not None,
            "regional": frame.regional_feature_id is not None,
        },
    }


@router.get("")
def list_frames(session_id: str):
    session = get_session(session_id)
    return {
        "frames": [_frame_summary(f) for f in session.frame_manager.frames],
        "frame_count": session.frame_manager.frame_count,
        "selected_count": session.frame_manager.selected_count,
    }


@router.get("/{index}/info")
def frame_info(session_id: str, index: int):
    session = get_session(session_id)
    frame = session.frame_manager.get_frame(index)
    if frame is None:
        raise HTTPException(status_code=404, detail="帧不存在")
    return _frame_summary(frame)


# ---------- 图像服务 ----------
def _resolve_frame_path(session, frame, kind: str):
    """解析帧图像文件路径：优先 FrameData 记录的路径，其次按 id 计算。"""
    if kind == "processed":
        if frame.processed_path and frame.processed_path.exists():
            return frame.processed_path
        p = session.frame_store.proc_path(frame.id)
        return p if p.exists() else None
    if kind == "preview":
        # 预览优先显示处理结果（若有），使处理后能即时看到最新效果
        if frame.processed_path and frame.processed_path.exists():
            return frame.processed_path
        p = session.frame_store.proc_path(frame.id)
        if p.exists():
            return p
    # raw / preview 回退到 raw
    if frame.image_path and frame.image_path.exists():
        return frame.image_path
    p = session.frame_store.raw_path(frame.id)
    return p if p.exists() else None


@router.get("/{index}/image")
def get_frame_image(
    session_id: str,
    index: int,
    type: str = Query("preview", description="raw/processed/preview"),
    checker: int = Query(1, description="透明图合成棋盘格(1/0)"),
    fit: int = Query(0, description="最大边长缩放(0为原尺寸)"),
):
    session = get_session(session_id)
    frame = session.frame_manager.get_frame(index)
    if frame is None:
        raise HTTPException(status_code=404, detail="帧不存在")

    if type == "processed":
        path = _resolve_frame_path(session, frame, "processed")
        if path is None:
            raise HTTPException(status_code=404, detail="该帧尚无处理结果")
    elif type == "preview":
        path = _resolve_frame_path(session, frame, "preview")
        if path is None:
            raise HTTPException(status_code=404, detail="图像不存在")
    else:
        path = _resolve_frame_path(session, frame, "raw")
        if path is None:
            raise HTTPException(status_code=404, detail="图像不存在")

    img = read_image(path)
    if img is None:
        raise HTTPException(status_code=404, detail="图像读取失败")

    bytes_data = encode_preview(
        img,
        transparent_checker=bool(checker) and type == "preview",
        max_w=fit if fit > 0 else 0,
        max_h=fit if fit > 0 else 0,
    )
    return Response(content=bytes_data, media_type="image/png")


# ---------- 选择 ----------
@router.post("/selection")
def update_selection(session_id: str, req: SelectionRequest):
    session = get_session(session_id)
    fm = session.frame_manager

    if req.mode == "all":
        fm.select_all()
    elif req.mode in ("clear", "none"):
        fm.deselect_all()
    elif req.mode == "invert":
        for f in fm.frames:
            f.is_selected = not f.is_selected
    elif req.mode == "range":
        start = req.range_start if req.range_start is not None else 0
        end = req.range_end if req.range_end is not None else fm.frame_count - 1
        fm.select_range(start, end)
    else:  # set
        fm.deselect_all()
        for i in (req.indices or []):
            if 0 <= i < fm.frame_count:
                fm.select_frame(i, True)

    session.persist_metadata()
    return {"frame_count": fm.frame_count, "selected_count": fm.selected_count}


# ---------- 删除 ----------
@router.delete("/{index}")
def delete_frame(session_id: str, index: int):
    session = get_session(session_id)
    fm = session.frame_manager

    if not (0 <= index < fm.frame_count):
        raise HTTPException(status_code=404, detail="帧不存在")

    frame = fm.get_frame(index)
    if frame:
        session.frame_store.remove_frame_files(frame.id)
    fm.remove_frame(index)
    session.persist_metadata()
    return {"frame_count": fm.frame_count, "selected_count": fm.selected_count}


@router.post("/delete")
def delete_frames(session_id: str, indices: List[int]):
    """批量删除指定帧。"""
    session = get_session(session_id)
    fm = session.frame_manager

    for index in sorted(set(indices), reverse=True):
        if 0 <= index < fm.frame_count:
            frame = fm.get_frame(index)
            if frame:
                session.frame_store.remove_frame_files(frame.id)
            fm.remove_frame(index)

    session.persist_metadata()
    return {"frame_count": fm.frame_count, "selected_count": fm.selected_count}


# ---------- 重排 ----------
@router.post("/reorder")
def reorder_frames(session_id: str, req: ReorderRequest):
    session = get_session(session_id)
    fm = session.frame_manager

    if len(req.new_order) != fm.frame_count:
        raise HTTPException(status_code=400, detail="顺序长度与帧数不符")

    if sorted(req.new_order) != list(range(fm.frame_count)):
        raise HTTPException(status_code=400, detail="顺序必须为 0..N-1 的排列")

    fm.reorder_frames(req.new_order)
    session.persist_metadata()
    return {"frame_count": fm.frame_count}


# ---------- 循环过渡 ----------
@router.post("/loop-transition")
def loop_transition(session_id: str, req: LoopTransitionRequest):
    """对选中帧应用循环过渡（非破坏性），生成 GIF 预览供查看。"""
    session = get_session(session_id)
    indices = require_indices(session, req.indices)
    if len(indices) < 2:
        raise HTTPException(status_code=400, detail="至少需要 2 帧才能进行循环过渡")
    if req.mode not in ("blend", "align"):
        raise HTTPException(status_code=400, detail="mode 仅支持 blend / align")

    def _job(ctx):
        ctx.report(10, "加载帧图像...")
        images = session.load_display_arrays(indices)
        images = [img for img in images if img is not None]
        if len(images) < 2:
            return {"error": "可用帧不足 2 张"}

        ctx.report(40, "应用循环过渡...")
        result_images = apply_loop_transition(images, req.count, req.mode)
        session.clear_frame_arrays()

        # 生成 GIF 预览（透明帧合成到棋盘格）
        from PIL import Image
        from app.utils.image_utils import composite_checkerboard

        pil_frames = []
        for img in result_images:
            if len(img.shape) == 3 and img.shape[2] == 4:
                img = composite_checkerboard(img)
            pil_frames.append(Image.fromarray(img))

        duration = int(1000 / req.fps)
        out_path = session.storage.preview_dir / "loop_transition.gif"
        pil_frames[0].save(
            str(out_path), save_all=True, append_images=pil_frames[1:],
            duration=duration, loop=0,
        )

        ctx.report(100, "循环过渡预览已生成")
        return {
            "original_count": len(indices),
            "result_count": len(result_images),
            "gif": "/api/sessions/{}/frames/preview/loop_transition.gif".format(session_id),
        }

    job = job_manager.submit("loop-transition", _job)
    return {"job_id": job.id}


@router.get("/preview/{name}")
def get_preview_file(session_id: str, name: str):
    """返回预览产物（如循环过渡 GIF）。"""
    session = get_session(session_id)
    safe = Path(name).name
    path = session.storage.preview_dir / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail="预览文件不存在")
    from fastapi.responses import FileResponse
    media = "image/gif" if safe.endswith(".gif") else "application/octet-stream"
    return FileResponse(str(path), media_type=media)


# ---------- 首尾补帧 ----------
@router.post("/supplement")
def supplement_frames(session_id: str, req: SupplementRequest):
    """在选中帧的尾帧与首帧之间生成中间帧（用于循环衔接），追加到帧管理。"""
    session = get_session(session_id)
    indices = require_indices(session, req.indices)
    if len(indices) < 2:
        raise HTTPException(status_code=400, detail="至少需要 2 帧（首帧和尾帧）")

    def _job(ctx):
        fm = session.frame_manager
        first = fm.get_frame(indices[0])
        last = fm.get_frame(indices[-1])
        if first is None or last is None:
            return {"error": "帧不存在"}

        ctx.report(10, "加载首尾帧...")
        first_img = session.load_display_array(first.index)
        last_img = session.load_display_array(last.index)
        if first_img is None or last_img is None:
            return {"error": "首尾帧图像不可用"}

        ctx.report(30, "生成中间帧...")
        middle_frames = interpolate_frames(
            first_img, last_img, req.num_frames,
            progress_callback=lambda cur, total, msg: ctx.report(
                30 + cur / total * 60, msg
            ),
        )

        # 追加到帧管理（标签：补），时间戳接在最后一帧之后
        base_index = fm.frame_count
        base_ts = last.timestamp if last.timestamp is not None else 0.0
        new_frames = []
        for i, img in enumerate(middle_frames):
            frame = FrameData(
                index=base_index + i,
                timestamp=base_ts + (i + 1) * 0.001,
                image=img,
                is_selected=True,
                tag="补",
            )
            new_frames.append(frame)

        session.frame_store.save_raw_frames(new_frames)
        fm.add_frames(new_frames)
        session.clear_frame_arrays()
        session.persist_metadata()

        ctx.report(100, f"补帧完成，新增 {len(new_frames)} 帧")
        return {"added": len(new_frames), "total": fm.frame_count}

    job = job_manager.submit("supplement", _job)
    return {"job_id": job.id}
