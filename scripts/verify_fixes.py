"""针对本次 7 项修改的针对性验证（对运行中的服务）。"""
import sys, io, json, time
import requests

BASE = "http://127.0.0.1:8000"
VIDEO = r"D:\Download\Wan2.2_i2v_00002_.mp4"

def ok(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra else ""))
    if not cond:
        global fails
        fails += 1

fails = 0

def wait_job(sid, jid, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = requests.get(f"{BASE}/api/jobs/{jid}").json()
        if j["status"] in ("done", "error", "cancelled"):
            return j
        time.sleep(0.4)
    return {"status": "timeout"}

# 1. 会话 + 上传
sid = requests.post(f"{BASE}/api/sessions").json()["id"]
ok("create session", bool(sid))

with open(VIDEO, "rb") as f:
    r = requests.post(f"{BASE}/api/sessions/{sid}/video", files={"file": f})
ok("upload video", r.status_code == 200, r.status_code)

# 2. 抽帧（前 1 秒 @ 5fps → 约 5 帧）
j = wait_job(sid, requests.post(f"{BASE}/api/sessions/{sid}/frames/extract",
    json={"start_time": 0, "end_time": 1, "fps": 5}).json()["job_id"])
ok("extract", j["status"] == "done", j.get("result"))

frames = requests.get(f"{BASE}/api/sessions/{sid}/frames").json()["frames"]
ok("frames count", len(frames) >= 3, len(frames))
idx0 = frames[0]["index"]

# 3. 颜色抠图（无需模型）
r = requests.post(f"{BASE}/api/sessions/{sid}/background/remove",
    json={"mode": "color", "params": {"lower": [35,50,50], "upper": [85,255,255]}})
j = wait_job(sid, r.json()["job_id"])
ok("bg remove", j["status"] == "done", j.get("result"))

frames = requests.get(f"{BASE}/api/sessions/{sid}/frames").json()["frames"]
ok("has_processed True", all(f["has_processed"] for f in frames))

# 4. 预览图应优先返回处理结果（与 raw 不同）
raw = requests.get(f"{BASE}/api/sessions/{sid}/frames/{idx0}/image?type=raw").content
prev = requests.get(f"{BASE}/api/sessions/{sid}/frames/{idx0}/image?type=preview").content
ok("preview differs from raw (processed preferred)", raw != prev, f"raw={len(raw)}B prev={len(prev)}B")

# 5. 历史记录存在
hist = requests.get(f"{BASE}/api/sessions/{sid}/history").json()["entries"]
ok("history entries >=1", len(hist) >= 1, [e["operation_name"] for e in hist])

# 6. 缩放（再产生一条历史）
r = requests.post(f"{BASE}/api/sessions/{sid}/image/scale",
    json={"mode": "percent", "percent": 80})
j = wait_job(sid, r.json()["job_id"])
ok("scale", j["status"] == "done", j.get("result"))
hist2 = requests.get(f"{BASE}/api/sessions/{sid}/history").json()["entries"]
ok("history entries >=2", len(hist2) >= 2, [e["operation_name"] for e in hist2])

# 7. 回退到初始状态 → processed 文件应被清除，预览回到 raw
old_step = hist2[0]["step_id"]
r = requests.post(f"{BASE}/api/sessions/{sid}/history/revert", json={"step_id": 0})
j = wait_job(sid, r.json()["job_id"])
ok("revert to init", j["status"] == "done", j.get("result"))

frames = requests.get(f"{BASE}/api/sessions/{sid}/frames").json()["frames"]
ok("has_processed False after revert", all(not f["has_processed"] for f in frames))
prev2 = requests.get(f"{BASE}/api/sessions/{sid}/frames/{idx0}/image?type=preview").content
ok("preview back to raw after revert", prev2 == raw, f"len={len(prev2)}B")

# 8. 魔棒：select + mask（mask 应保留透明通道）
r = requests.post(f"{BASE}/api/sessions/{sid}/image/wand/select",
    json={"frame_index": idx0, "x": 10, "y": 10, "tolerance": 32, "contiguous": True, "anti_alias": True})
ok("wand select", r.status_code == 200, r.json().get("bounds"))
mask = requests.get(f"{BASE}/api/sessions/{sid}/image/wand/mask?frame_index={idx0}").content
from PIL import Image
import io as _io
m = Image.open(_io.BytesIO(mask))
ok("wand mask is RGBA with transparency", m.mode == "RGBA", m.mode)
extrema = m.getextrema()
alpha_min = extrema[3][0]
ok("wand mask has transparent regions (alpha 0 present)", alpha_min == 0, f"alpha_min={alpha_min}")

# 9. 魔棒 apply delete → has_processed True
r = requests.post(f"{BASE}/api/sessions/{sid}/image/wand/apply",
    json={"frame_index": idx0, "operation": "delete"})
ok("wand apply", r.status_code == 200, r.json())
frames = requests.get(f"{BASE}/api/sessions/{sid}/frames").json()["frames"]
ok("has_processed True after wand", frames[0]["has_processed"])

# 10. 清理
requests.delete(f"{BASE}/api/sessions/{sid}")
print("----")
print("FAILS:", fails)
sys.exit(1 if fails else 0)
