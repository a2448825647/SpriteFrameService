"""分析 API：姿势/轮廓/图像特征/区域SSIM 检测、去相似帧、找循环帧、骨架叠加。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from app.api.deps import get_session, require_indices
from app.api.schemas import DetectRequest, FindLoopRequest, RemoveSimilarRequest
from app.services.job_manager import job_manager
from app.utils.image_utils import encode_preview, read_image
import numpy as np
import cv2

router = APIRouter(prefix="/sessions/{session_id}/analysis", tags=["analysis"])

_MODE_TEXT = {
    "pose": "姿势",
    "pose_rtm": "姿势(RTM)",
    "contour": "轮廓",
    "image": "图像特征",
    "regional": "分区域SSIM",
}


def _get_data(fm, frame, mode):
    """按模式获取帧的分析数据对象。"""
    if mode in ("pose", "pose_rtm"):
        return fm.get_pose_for_frame(frame.index) if frame.pose_id else None
    if mode == "contour":
        return fm.get_contour_for_frame(frame.index) if frame.contour_id else None
    if mode == "image":
        return fm.get_image_feature_for_frame(frame.index) if frame.image_feature_id else None
    if mode == "regional":
        return fm.get_regional_feature_for_frame(frame.index) if frame.regional_feature_id else None
    return None


# ---------- 检测 ----------
@router.post("/detect")
def detect(session_id: str, req: DetectRequest):
    session = get_session(session_id)
    indices = require_indices(session, req.indices)
    mode = req.mode
    if mode not in _MODE_TEXT:
        raise HTTPException(status_code=400, detail=f"不支持的检测模式: {mode}")

    def _job(ctx):
        detector = session.pose_detector
        ctx.register_cancel(detector.cancel)
        ctx.report(0, f"开始检测{mode}...")

        arrays = session.load_display_arrays(indices)
        processed = 0

        for i, idx in enumerate(indices):
            if ctx.cancelled():
                break
            img = arrays[i]
            if img is None:
                continue

            data = None
            if mode == "pose":
                data = detector.detect_pose(img, idx)
            elif mode == "pose_rtm":
                data = detector.detect_pose_rtm(img, idx)
            elif mode == "contour":
                data = detector.extract_contour(img, idx)
            elif mode == "image":
                data = detector.extract_image_features(img, idx)
            elif mode == "regional":
                data = detector.extract_regional_features(img, idx, weights=req.weights)

            if data is not None:
                if mode in ("pose", "pose_rtm"):
                    session.frame_manager.add_pose(data)
                elif mode == "contour":
                    session.frame_manager.add_contour(data)
                elif mode == "image":
                    session.frame_manager.add_image_feature(data)
                elif mode == "regional":
                    session.frame_manager.add_regional_feature(data)
                processed += 1

            ctx.report((i + 1) / len(indices) * 100, f"{_MODE_TEXT[mode]}检测 {i+1}/{len(indices)}")

        session.clear_frame_arrays()
        session.persist_metadata()
        ctx.report(100, f"检测完成: {processed}/{len(indices)} 帧")
        return {"mode": mode, "processed": processed, "total": len(indices)}

    job = job_manager.submit("detect", _job)
    return {"job_id": job.id}


# ---------- 数据查询 ----------
def _data_payload(fm, frame, mode) -> dict | None:
    data = _get_data(fm, frame, mode)
    if data is None:
        return None
    if mode in ("pose", "pose_rtm"):
        return {
            "mode": mode,
            "id": data.id,
            "confidence": round(data.confidence, 4),
            "landmarks": [lm.model_dump() for lm in data.landmarks],
        }
    if mode == "contour":
        return {
            "mode": mode,
            "id": data.id,
            "hu_moments": [round(float(v), 6) for v in data.hu_moments],
        }
    if mode == "image":
        return {
            "mode": mode,
            "id": data.id,
            "hist": [round(float(v), 6) for v in data.hist],
            "phash": [bool(v) for v in data.phash],
        }
    if mode == "regional":
        return {
            "mode": mode,
            "id": data.id,
            "weights": list(data.weights),
        }
    return None


@router.get("/{index}")
def analysis_data(session_id: str, index: int):
    session = get_session(session_id)
    frame = session.frame_manager.get_frame(index)
    if frame is None:
        raise HTTPException(status_code=404, detail="帧不存在")

    result = {}
    for mode in _MODE_TEXT:
        payload = _data_payload(session.frame_manager, frame, mode)
        if payload is not None:
            result[mode] = payload
    return result


@router.get("/{index}/overlay")
def analysis_overlay(session_id: str, index: int, mode: str = "pose", fit: int = 0):
    """在帧图像上绘制分析结果（姿势骨架 / 轮廓线）。"""
    session = get_session(session_id)
    frame = session.frame_manager.get_frame(index)
    if frame is None:
        raise HTTPException(status_code=404, detail="帧不存在")

    data = _get_data(session.frame_manager, frame, mode)
    if data is None:
        raise HTTPException(status_code=404, detail="该帧没有对应分析数据")

    img = session.load_display_array(index)
    if img is None:
        raise HTTPException(status_code=404, detail="图像不存在")
    session.clear_frame_arrays()

    if mode in ("pose", "pose_rtm"):
        overlay = session.pose_detector.draw_pose_on_image(img, data)
    elif mode == "contour":
        overlay = img.copy()
        if data.contour is not None:
            cv2.polylines(overlay, [data.contour.astype(np.int32)], True, (0, 200, 255), 2)
    else:
        overlay = img

    bytes_data = encode_preview(
        overlay,
        transparent_checker=True,
        max_w=fit if fit > 0 else 0,
        max_h=fit if fit > 0 else 0,
    )
    return Response(content=bytes_data, media_type="image/png")


# ---------- 去相似帧 ----------
@router.post("/remove-similar")
def remove_similar(session_id: str, req: RemoveSimilarRequest):
    session = get_session(session_id)
    indices = require_indices(session, req.indices)
    mode = req.mode
    if mode not in _MODE_TEXT:
        raise HTTPException(status_code=400, detail=f"不支持的检测模式: {mode}")

    def _job(ctx):
        fm = session.frame_manager

        frames_with_data = []
        for idx in indices:
            frame = fm.get_frame(idx)
            if frame is None:
                continue
            data = _get_data(fm, frame, mode)
            if data is not None:
                frames_with_data.append((frame, data))

        if len(frames_with_data) < 2:
            return {"mode": mode, "groups": [], "kept": 0, "removed": 0,
                    "message": "有效数据不足 2 帧，请先检测"}

        groups = []
        anchor_frame, anchor_data = frames_with_data[0]
        current_members = [anchor_frame]

        for i in range(1, len(frames_with_data)):
            curr_frame, curr_data = frames_with_data[i]
            similarity = anchor_data.similarity_to(curr_data)
            if similarity >= req.threshold:
                current_members.append(curr_frame)
            else:
                groups.append((anchor_frame, current_members))
                anchor_frame, anchor_data = curr_frame, curr_data
                current_members = [curr_frame]
        groups.append((anchor_frame, current_members))

        kept = 0
        removed = 0
        group_info = []
        for anchor, members in groups:
            fm.select_frame(anchor.index, True)
            kept += 1
            for member in members[1:]:
                fm.select_frame(member.index, False)
                removed += 1
            group_info.append({
                "anchor": anchor.index,
                "members": [m.index for m in members],
                "count": len(members),
            })

        session.persist_metadata()
        return {
            "mode": mode,
            "threshold": req.threshold,
            "groups": group_info,
            "kept": kept,
            "removed": removed,
        }

    job = job_manager.submit("remove-similar", _job)
    return {"job_id": job.id}


# ---------- 找循环帧 ----------
@router.post("/find-loop")
def find_loop(session_id: str, req: FindLoopRequest):
    session = get_session(session_id)
    indices = require_indices(session, req.indices)
    mode = req.mode
    if mode not in _MODE_TEXT:
        raise HTTPException(status_code=400, detail=f"不支持的检测模式: {mode}")
    if len(indices) < 2:
        raise HTTPException(status_code=400, detail="至少需要 2 帧（首帧和候选循环点）")

    def _job(ctx):
        fm = session.frame_manager
        first_idx = indices[0]
        first_frame = fm.get_frame(first_idx)
        first_data = _get_data(fm, first_frame, mode) if first_frame else None

        if first_data is None:
            return {"mode": mode, "message": "首帧没有分析数据，请先检测"}

        best_similarity = -1.0
        best_idx = -1
        for idx in reversed(indices[1:]):
            frame = fm.get_frame(idx)
            if frame is None:
                continue
            data = _get_data(fm, frame, mode)
            if data is not None:
                sim = first_data.similarity_to(data)
                if sim > best_similarity:
                    best_similarity = sim
                    best_idx = idx

        if best_idx < 0:
            return {"mode": mode, "message": "没有找到有分析数据的候选帧"}

        end_idx = best_idx - 1
        result = {
            "mode": mode,
            "first_index": first_idx,
            "loop_index": best_idx,
            "similarity": round(best_similarity, 4),
            "suggested_range": [first_idx, end_idx],
        }

        if req.apply_range:
            for f in fm.frames:
                if not (first_idx <= f.index < best_idx):
                    f.is_selected = False
            session.persist_metadata()

        return result

    job = job_manager.submit("find-loop", _job)
    return {"job_id": job.id}
