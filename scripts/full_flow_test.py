"""全流程测试：以真实视频为例，跑通 上传→抽帧→分析→去相似→找循环→抠图→描边→裁剪缩放→导出→下载。

用法：
    python scripts/full_flow_test.py [视频路径] [--base http://127.0.0.1:8000]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

# 确保控制台 UTF-8 输出（Windows GBK 终端）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

PASS, FAIL = 0, 0


def check(name: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}" + (f" | {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f" | {detail}" if detail else ""))


def poll_job(c, job_id: str, timeout: float = 600.0, interval: float = 0.3) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "error", "cancelled"):
            return j
        time.sleep(interval)
    return {"status": "timeout", "id": job_id}


def step(title: str):
    print(f"\n{'=' * 60}\n▶ {title}\n{'=' * 60}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video", nargs="?", default=r"D:\Download\Wan2.2_i2v_00002_.mp4")
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--fps", type=float, default=8.0)
    parser.add_argument("--max-ai-frames", type=int, default=10, help="AI 抠图最多帧数（CPU 速度考虑）")
    args = parser.parse_args()

    video = Path(args.video)
    if not video.exists():
        print(f"视频不存在: {video}")
        sys.exit(1)

    c = httpx.Client(base_url=args.base, timeout=180)

    step(f"1. 创建会话")
    sid = c.post("/api/sessions").json()["id"]
    check("会话创建", bool(sid), sid[:8])

    step(f"2. 上传视频 ({video.name})")
    with open(video, "rb") as f:
        r = c.post(f"/api/sessions/{sid}/video",
                   files={"file": (video.name, f, "video/mp4")})
    check("上传成功", r.status_code == 200, str(r.status_code))
    vi = r.json()["video_info"]
    check("视频元数据", vi["frame_count"] > 0,
          f"{vi['width']}x{vi['height']} {vi['fps']:.2f}fps {vi['duration']:.2f}s codec={vi['codec']}")

    step(f"3. 抽帧 (全时长, {args.fps} fps)")
    jid = c.post(f"/api/sessions/{sid}/frames/extract",
                 json={"start_time": 0, "end_time": vi["duration"], "fps": args.fps}).json()["job_id"]
    j = poll_job(c, jid)
    n = j.get("result", {}).get("extracted", 0)
    check("抽帧完成", j["status"] == "done" and n > 0, f"{n} 帧")
    frames = c.get(f"/api/sessions/{sid}/frames").json()["frames"]
    check("帧列表", len(frames) == n, f"count={len(frames)}")

    step("4. 姿势检测 (MediaPipe)")
    jid = c.post(f"/api/sessions/{sid}/analysis/detect",
                 json={"mode": "pose"}).json()["job_id"]
    j = poll_job(c, jid, timeout=300)
    pose_ok = j.get("result", {}).get("processed", 0)
    check("姿势检测", j["status"] == "done", f"成功 {pose_ok}/{n} 帧")
    frames = c.get(f"/api/sessions/{sid}/frames").json()["frames"]
    with_pose = sum(1 for f in frames if f["analysis"]["pose"])
    check("姿势数据落库", with_pose > 0, f"{with_pose} 帧有姿势")

    step("5. 图像特征 + 去相似帧")
    jid = c.post(f"/api/sessions/{sid}/analysis/detect",
                 json={"mode": "image"}).json()["job_id"]
    j = poll_job(c, jid)
    check("特征检测", j["status"] == "done", str(j.get("result")))
    jid = c.post(f"/api/sessions/{sid}/analysis/remove-similar",
                 json={"mode": "image", "threshold": 0.9}).json()["job_id"]
    j = poll_job(c, jid)
    r = j.get("result", {})
    check("去相似帧", j["status"] == "done",
          f"分组={len(r.get('groups', []))} 保留={r.get('kept')} 取消={r.get('removed')}")

    step("6. 找循环帧")
    jid = c.post(f"/api/sessions/{sid}/analysis/find-loop",
                 json={"mode": "image", "apply_range": False}).json()["job_id"]
    j = poll_job(c, jid)
    r = j.get("result", {})
    check("找循环", j["status"] == "done",
          f"首帧=#{r.get('first_index')} 循环点=#{r.get('loop_index')} 相似度={r.get('similarity')}")

    step(f"7. AI 抠图 (前 {args.max_ai_frames} 帧, silueta 模型)")
    c.post(f"/api/sessions/{sid}/frames/selection", json={"mode": "all"})
    ai_indices = list(range(min(args.max_ai_frames, n)))
    jid = c.post(f"/api/sessions/{sid}/background/remove",
                 json={"mode": "ai", "indices": ai_indices,
                       "params": {"model": "silueta", "alpha_threshold": 0, "erode": 1, "feather": 1}}).json()["job_id"]
    j = poll_job(c, jid, timeout=900)
    r = j.get("result", {})
    check("AI 抠图", j["status"] == "done" and r.get("processed", 0) > 0,
          f"{r.get('processed')}/{r.get('total')} 帧")
    frames = c.get(f"/api/sessions/{sid}/frames").json()["frames"]
    with_proc = sum(1 for f in frames if f["has_processed"])
    check("处理后帧落库", with_proc > 0, f"{with_proc} 帧")
    check("处理后帧图像", c.get(f"/api/sessions/{sid}/frames/0/image?type=processed").status_code == 200)

    step("8. 描边")
    jid = c.post(f"/api/sessions/{sid}/background/outline",
                 json={"indices": ai_indices[:4], "thickness": 3, "color": [255, 0, 0]}).json()["job_id"]
    j = poll_job(c, jid)
    check("描边", j["status"] == "done", str(j.get("result")))

    step("9. 空白裁剪 + 缩放")
    jid = c.post(f"/api/sessions/{sid}/image/crop-whitespace",
                 json={"indices": ai_indices[:4], "margin_left": 4, "margin_right": 4,
                       "margin_top": 4, "margin_bottom": 4}).json()["job_id"]
    j = poll_job(c, jid)
    check("空白裁剪", j["status"] == "done", str(j.get("result")))
    jid = c.post(f"/api/sessions/{sid}/image/scale",
                 json={"indices": ai_indices[:4], "mode": "percent", "percent": 75,
                       "algorithm": "lanczos"}).json()["job_id"]
    j = poll_job(c, jid)
    r = j.get("result", {})
    check("缩放", j["status"] == "done", f"{r.get('from')} → {r.get('to')}")

    step("10. 骨架叠加预览")
    r = c.get(f"/api/sessions/{sid}/analysis/0/overlay?mode=pose")
    check("骨架叠加图", r.status_code == 200 and len(r.content) > 0, f"{len(r.content)} bytes")

    step("11. 导出精灵图 + GIF")
    jid = c.post(f"/api/sessions/{sid}/export",
                 json={"config": {"format": "sprite_sheet", "output_name": "wan_sprite",
                                  "sprite_config": {"layout": "horizontal", "generate_json": True}},
                       "indices": ai_indices[:8]}).json()["job_id"]
    j = poll_job(c, jid)
    r = j.get("result", {})
    check("精灵图导出", j["status"] == "done" and any(f.endswith(".png") for f in r.get("files", [])),
          f"文件={r.get('files')}")
    jid = c.post(f"/api/sessions/{sid}/export",
                 json={"config": {"format": "gif", "output_name": "wan_gif",
                                  "gif_config": {"fps": 8}},
                       "indices": ai_indices[:12]}).json()["job_id"]
    j = poll_job(c, jid)
    r = j.get("result", {})
    check("GIF 导出", j["status"] == "done" and any(f.endswith(".gif") for f in r.get("files", [])),
          f"文件={r.get('files')}")

    step("12. 下载并验证产物")
    ok_dir = Path("data/fullflow_verify")
    ok_dir.mkdir(parents=True, exist_ok=True)

    # 精灵图多文件：逐个文件下载（避免 zip 混叠）
    for fname in ["wan_sprite.png", "wan_sprite.json"]:
        r = c.get(f"/api/sessions/{sid}/export/wan_sprite/files/{fname}")
        if r.status_code == 200:
            dst = ok_dir / fname
            dst.write_bytes(r.content)
            check(f"下载 {fname}", dst.stat().st_size > 0, f"{dst.stat().st_size} bytes")
        else:
            check(f"下载 {fname}", False, str(r.status_code))

    # GIF 单文件：直接下载
    r = c.get(f"/api/sessions/{sid}/export/wan_gif/download")
    if r.status_code == 200:
        dst = ok_dir / "wan_gif.gif"
        dst.write_bytes(r.content)
        check("下载 wan_gif.gif", dst.stat().st_size > 0, f"{dst.stat().st_size} bytes")
    else:
        check("下载 wan_gif.gif", False, str(r.status_code))

    # 校验产物可读性
    from PIL import Image
    png_path = ok_dir / "wan_sprite.png"
    if png_path.exists():
        try:
            im = Image.open(png_path)
            im.verify()
            check("精灵图 PNG 可读", True, f"{im.size if not hasattr(im, 'size') or im.size else 'ok'}")
        except Exception as e:
            check("精灵图 PNG 可读", False, str(e))
    gif_path = ok_dir / "wan_gif.gif"
    if gif_path.exists():
        try:
            im = Image.open(gif_path)
            im.seek(0)
            check("GIF 可读", im.is_animated, f"帧数={im.n_frames}")
        except Exception as e:
            check("GIF 可读", False, str(e))

    step("13. 删除会话清理")
    check("删除会话", c.delete(f"/api/sessions/{sid}").status_code == 200)

    print(f"\n{'=' * 60}\n结果: {PASS} 通过, {FAIL} 失败\n{'=' * 60}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
