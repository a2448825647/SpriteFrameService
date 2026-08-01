"""会话目录与文件布局。"""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from app.config import get_settings


class SessionStorage:
    """单个会话的磁盘布局：

    data/sessions/{sid}/
        video/           上传的视频
        frames/raw/      抽帧原始图
        frames/proc/     处理后图
        frames.json      帧元数据索引
        exports/         导出结果
        preview/         预览产物（循环过渡 GIF 等）
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.root = get_settings().sessions_dir / session_id

        self.video_dir = self.root / "video"
        self.raw_dir = self.root / "frames" / "raw"
        self.proc_dir = self.root / "frames" / "proc"
        self.exports_dir = self.root / "exports"
        self.preview_dir = self.root / "preview"
        self.frames_json = self.root / "frames.json"

        self.video_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.proc_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        self.preview_dir.mkdir(parents=True, exist_ok=True)

    # --- 视频 ---
    @property
    def video_path(self) -> Path | None:
        files = list(self.video_dir.glob("*"))
        if files:
            # 优先视频扩展名
            exts = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".flv", ".ts", ".wmv"}
            for f in files:
                if f.suffix.lower() in exts:
                    return f
            return files[0]
        return None

    def save_video(self, content: bytes, filename: str) -> Path:
        ext = Path(filename).suffix or ".mp4"
        # 固定命名为 upload.ext，便于后续预览
        dest = self.video_dir / f"upload{ext}"
        dest.write_bytes(content)
        return dest

    # --- 帧文件（以帧的稳定 id 命名，与位置索引解耦） ---
    def raw_path(self, frame_id: str) -> Path:
        return self.raw_dir / f"{frame_id}.png"

    def proc_path(self, frame_id: str) -> Path:
        return self.proc_dir / f"{frame_id}.png"

    def raw_exists(self, frame_id: str) -> bool:
        return self.raw_path(frame_id).exists()

    def proc_exists(self, frame_id: str) -> bool:
        return self.proc_path(frame_id).exists()

    def remove_frame_files(self, frame_id: str):
        for p in (self.raw_path(frame_id), self.proc_path(frame_id)):
            if p.exists():
                p.unlink()

    def remove_frame_thumb(self, frame_id: str) -> None:
        """删除缩略图缓存（如有）。"""
        p = self.raw_dir / f"{frame_id}.thumb.jpg"
        if p.exists():
            p.unlink()

    # --- 导出 ---
    def export_dir(self, name: str) -> Path:
        p = self.exports_dir / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    def list_exports(self) -> list[dict]:
        """列出导出结果目录及其文件。"""
        result = []
        if not self.exports_dir.exists():
            return result
        for d in sorted(self.exports_dir.iterdir()):
            if d.is_dir():
                files = [f for f in sorted(d.iterdir()) if f.is_file()]
                total = sum(f.stat().st_size for f in files)
                result.append({
                    "name": d.name,
                    "files": [{"name": f.name, "size": f.stat().st_size} for f in files],
                    "total_size": total,
                    "created": d.stat().st_ctime,
                })
        return result

    def clear(self):
        """删除会话全部文件。"""
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)


def create_session_storage() -> tuple[str, SessionStorage]:
    """创建新会话存储目录。"""
    sid = uuid.uuid4().hex[:12]
    return sid, SessionStorage(sid)
