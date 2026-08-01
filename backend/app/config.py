"""应用配置 - 使用 pydantic-settings 管理，全部路径跨平台。"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def _exe_name(basename: str) -> str:
    """Windows 下补 .exe，Linux/macOS 保持裸名。"""
    return f"{basename}.exe" if _is_windows() else basename


_BACKEND_DIR = Path(__file__).resolve().parent.parent  # backend/
_ENV_FILES = [
    _BACKEND_DIR / ".env",
    _BACKEND_DIR.parent / ".env",
]


class Settings(BaseSettings):
    """服务设置。

    环境变量（backend/.env 可覆盖）：
        SPRITE_DATA_DIR     运行时数据目录（sessions/ 存放于此）
        SPRITE_MODELS_DIR   模型根目录（默认 <project_root>/models）
        SPRITE_TOOLS_DIR    外部二进制目录（pngquant、realesrgan）
        SPRITE_HOST / SPRITE_PORT
        SPRITE_FORCE_CPU    强制 CPU（跳过 GPU provider）
        SPRITE_MAX_WORKERS  Job 线程池并发数
        SPRITE_FRONTEND_DIR 前端 dist 目录（默认 <project_root>/frontend/dist）
    """

    model_config = SettingsConfigDict(
        env_prefix="SPRITE_",
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- 目录 ---
    data_dir: Path = Path("data")
    models_dir: Path | None = None
    tools_dir: Path | None = None
    frontend_dir: Path | None = None

    # --- 服务 ---
    host: str = "127.0.0.1"
    port: int = 8000
    max_workers: int = 2

    # --- 处理 ---
    force_cpu: bool = False
    realesrgan_tile: int = 0

    @property
    def project_root(self) -> Path:
        """后端项目根目录（backend/ 的上层）。"""
        return Path(__file__).resolve().parent.parent.parent

    @property
    def sessions_dir(self) -> Path:
        """会话目录（基于解析后的 data_dir，跨 CWD 稳定）。"""
        return self.resolved_data_dir / "sessions"

    def _resolve(self, p: Path | str | None, default: Path) -> Path:
        p = Path(p).expanduser() if p else default
        return p if p.is_absolute() else self.project_root / p

    @property
    def resolved_data_dir(self) -> Path:
        return self._resolve(self.data_dir, self.project_root / "data")

    @property
    def resolved_models_dir(self) -> Path:
        default = self.project_root / "models"
        return self._resolve(self.models_dir, default)

    @property
    def resolved_tools_dir(self) -> Path:
        default = self.project_root / "tools"
        return self._resolve(self.tools_dir, default)

    @property
    def resolved_frontend_dir(self) -> Path:
        default = self.project_root / "frontend" / "dist"
        return self._resolve(self.frontend_dir, default)

    # --- 外部二进制（跨平台） ---
    @property
    def pngquant_path(self) -> Path | None:
        p = self.resolved_tools_dir / "pngquant" / _exe_name("pngquant")
        return p if p.exists() else None

    @property
    def realesrgan_exe(self) -> Path | None:
        """realesrgan-ncnn-vulkan 可执行文件。"""
        p = self.resolved_models_dir / "realesrgan" / _exe_name("realesrgan-ncnn-vulkan")
        return p if p.exists() else None

    @property
    def realesrgan_models_dir(self) -> Path | None:
        p = self.resolved_models_dir / "realesrgan" / "models"
        return p if p.exists() else None

    # --- 全局单例目录初始化 ---
    def ensure_dirs(self) -> None:
        self.resolved_data_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
