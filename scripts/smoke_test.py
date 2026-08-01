"""后端冒烟测试：跑通 创建会话→上传视频→抽帧→分析→抠图→导出 主线。

用法：
    # 方式一：进程内（推荐，无需启动服务器，需已安装 httpx）
    python scripts/smoke_test.py

    # 方式二：对已运行的服务器
    python scripts/smoke_test.py --live http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import io
import sys
import time
from pathlib import Path

# 确保控制台 UTF-8 输出（Windows GBK 终端）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

BASE = "http://127.0.0.1:8000"
PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    status = "PASS" if ok else "FAIL"
    if ok:
        PASS += 1
    else:
        FAIL += 1
    print(f"[{status}] {name}" + (f" | {detail}" if detail else ""))


def poll_job(client, job_id: str, timeout: float = 300.0) -> dict:
    """轮询任务直至结束。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "error", "cancelled"):
            return job
        time.sleep(0.3)
    return {"status": "timeout", "id": job_id}


def make_test_video(path: Path, seconds: float = 2.0, fps: float = 30.0,
                    size=(320, 240), bg=(60, 60, 220)) -> Path:
    """生成一个移动圆块的测试视频（背景为蓝色）。"""
    import cv2
    import numpy as np

    w, h = size
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    n = int(seconds * fps)
    for i in range(n):
        frame = np.full((h, w, 3), bg, dtype=np.uint8)
        x = int(w * 0.5 + 100 * np.sin(2 * np.pi * i / (fps * 0.8)))
        y = int(h * 0.5)
        cv2.circle(frame, (x, y), 40, (220, 80, 80), -1)
        writer.write(frame)
    writer.release()
    return path


def run_inprocess():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def run_live(base: str):
    import httpx
    return httpx.Client(base_url=base, timeout=120)


def main():
    parser = argparse.ArgumentParser(description="SpriteFrameService 冒烟测试")
    parser.add_argument("--live", nargs="?", const=BASE, default=None,
                        help="对已运行的服务器测试（给出 base url）")
    parser.add_argument("--no-export-ai", action="store_true",
                        help="跳过 AI 抠图（无模型时）")
    args = parser.parse_args()

    client = run_live(args.live) if args.live else run_inprocess()

    # 临时测试视频
    tmp_video = Path("data/smoke_test_video.mp4")
    tmp_video.parent.mkdir(parents=True, exist_ok=True)
    make_test_video(tmp_video)

    try:
        # 1. 健康检查
        check("health", client.get("/api/health").status_code == 200)

        # 2. 创建会话
        r = client.post("/api/sessions")
        check("创建会话", r.status_code == 200)
        sid = r.json()["id"]

        # 3. 上传视频
        with open(tmp_video, "rb") as f:
            r = client.post(f"/api/sessions/{sid}/video",
                            files={"file": (tmp_video.name, f, "video/mp4")})
        check("上传视频", r.status_code == 200)
        video_info = r.json().get("video_info", {})
        check("视频元数据", video_info.get("frame_count", 0) > 0, str(video_info.get("frame_count")))

        # 4. 抽帧
        r = client.post(f"/api/sessions/{sid}/frames/extract",
                        json={"start_time": 0, "end_time": 1.0, "fps": 5})
        check("发起抽帧", r.status_code == 200)
        job = poll_job(client, r.json()["job_id"])
        check("抽帧完成", job["status"] == "done" and job.get("result", {}).get("extracted", 0) >= 5,
              str(job))
        n_frames = job.get("result", {}).get("extracted", 0)

        # 5. 帧列表
        r = client.get(f"/api/sessions/{sid}/frames")
        check("帧列表", r.status_code == 200 and r.json()["frame_count"] == n_frames)

        # 6. 帧图像
        r = client.get(f"/api/sessions/{sid}/frames/0/image?type=raw")
        check("原始帧图像", r.status_code == 200 and len(r.content) > 0)

        # 7. 全选 + 图像特征检测
        client.post(f"/api/sessions/{sid}/frames/selection", json={"mode": "all"})
        r = client.post(f"/api/sessions/{sid}/analysis/detect",
                        json={"mode": "image", "indices": [0, 1, 2, 3, 4]})
        check("发起特征检测", r.status_code == 200)
        job = poll_job(client, r.json()["job_id"])
        check("特征检测完成", job["status"] == "done" and job.get("result", {}).get("processed", 0) >= 1,
              str(job))

        # 8. 去相似帧
        r = client.post(f"/api/sessions/{sid}/analysis/remove-similar",
                        json={"mode": "image", "threshold": 0.9})
        check("去相似帧", r.status_code == 200)
        job = poll_job(client, r.json()["job_id"])
        check("去相似完成", job["status"] == "done", str(job))

        # 9. 颜色抠图（蓝幕）
        r = client.post(f"/api/sessions/{sid}/background/remove",
                        json={"mode": "color", "indices": [0, 1],
                              "params": {"lower": [100, 50, 50], "upper": [130, 255, 255]}})
        check("发起抠图", r.status_code == 200)
        job = poll_job(client, r.json()["job_id"])
        check("抠图完成", job["status"] == "done", str(job))

        # 9.5 批量缩放（同时产生历史快照）
        r = client.post(f"/api/sessions/{sid}/image/scale",
                        json={"mode": "percent", "percent": 50, "indices": [0, 1]})
        check("发起缩放", r.status_code == 200)
        job = poll_job(client, r.json()["job_id"])
        check("缩放完成", job["status"] == "done", str(job))

        # 9.6 找循环帧（基于已有的图像特征数据）
        r = client.post(f"/api/sessions/{sid}/analysis/find-loop",
                        json={"mode": "image", "apply_range": False})
        check("找循环帧", r.status_code == 200)
        job = poll_job(client, r.json()["job_id"])
        check("找循环完成", job["status"] == "done", str(job))

        # 10. 抠图测试单帧
        r = client.get(f"/api/sessions/{sid}/frames/0/image?type=processed")
        check("处理后帧图像", r.status_code == 200 and len(r.content) > 0)

        # 10.5 历史回退
        r = client.get(f"/api/sessions/{sid}/history")
        check("历史记录", r.status_code == 200 and len(r.json()["entries"]) > 0)
        step_id = r.json()["entries"][0]["step_id"]
        r = client.post(f"/api/sessions/{sid}/history/revert", json={"step_id": step_id})
        check("发起回退", r.status_code == 200)
        job = poll_job(client, r.json()["job_id"])
        check("回退完成", job["status"] == "done", str(job))

        # 11. 导出精灵图
        r = client.post(f"/api/sessions/{sid}/export",
                        json={
                            "config": {
                                "format": "sprite_sheet",
                                "output_name": "smoke_sprite",
                                "sprite_config": {"layout": "horizontal", "generate_json": True},
                            },
                            "indices": [0, 1, 2],
                        })
        check("发起导出", r.status_code == 200)
        job = poll_job(client, r.json()["job_id"])
        check("导出完成", job["status"] == "done", str(job))
        export_files = job.get("result", {}).get("files", [])
        check("导出文件存在", any(f.endswith(".png") for f in export_files), str(export_files))

        # 11.5 GIF 导出
        r = client.post(f"/api/sessions/{sid}/export",
                        json={
                            "config": {"format": "gif", "output_name": "smoke_gif",
                                       "gif_config": {"fps": 8}},
                            "indices": [0, 1, 2],
                        })
        check("发起GIF导出", r.status_code == 200)
        job = poll_job(client, r.json()["job_id"])
        check("GIF导出完成", job["status"] == "done", str(job))

        # 12. 下载导出 zip
        r = client.get(f"/api/sessions/{sid}/export/smoke_sprite/download")
        check("导出下载", r.status_code == 200 and len(r.content) > 0)

        # 13. 删除会话
        r = client.delete(f"/api/sessions/{sid}")
        check("删除会话", r.status_code == 200)

    finally:
        tmp_video.unlink(missing_ok=True)

    print(f"\n结果: {PASS} 通过, {FAIL} 失败")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
