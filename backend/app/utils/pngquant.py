"""pngquant 压缩工具（跨平台二进制解析）。

pngquant 可执行文件默认位于 <project>/tools/pngquant/pngquant(.exe)，
也可通过 SPRITE_TOOLS_DIR 配置自定义目录。
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Tuple

from app.config import get_settings


def get_pngquant_path() -> Path | None:
    """获取 pngquant 可执行文件路径（跨平台）。"""
    return get_settings().pngquant_path


def is_pngquant_available() -> bool:
    return get_pngquant_path() is not None


def compress_png(
    input_path: Path,
    output_path: Path | None = None,
    quality_min: int = 60,
    quality_max: int = 80
) -> Tuple[bool, int, int]:
    """使用 pngquant 压缩 PNG 文件。

    Returns:
        (成功, 原始大小, 压缩后大小)
    """
    pngquant_path = get_pngquant_path()

    if pngquant_path is None or not input_path.exists():
        return (False, 0, 0)

    original_size = input_path.stat().st_size

    quality_arg = f"--quality={quality_min}-{quality_max}"

    if output_path is None:
        output_path = input_path
        cmd = [
            str(pngquant_path),
            quality_arg,
            "--force",
            "--ext", ".png",
            str(input_path)
        ]
    else:
        cmd = [
            str(pngquant_path),
            quality_arg,
            "--force",
            "-o", str(output_path),
            str(input_path)
        ]

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=30)

        # pngquant 返回码：0=成功, 99=质量无法达到但仍输出
        if result.returncode in (0, 99):
            compressed_size = output_path.stat().st_size
            return (True, original_size, compressed_size)
        return (False, original_size, original_size)
    except (subprocess.TimeoutExpired, Exception):
        return (False, original_size, original_size)


def format_file_size(size_bytes: int) -> str:
    """格式化文件大小为可读字符串"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
