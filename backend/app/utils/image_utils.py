"""图像工具（服务版，无 Qt 依赖）。

提供 numpy <-> 文件/字节 转换、缩略图、透明图棋盘格预览等能力。
"""
from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np
from PIL import Image


def read_image(path: Path | str) -> Optional[np.ndarray]:
    """读取图像为 numpy 数组（RGB 或 RGBA）。失败返回 None。"""
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    if img.ndim == 2:
        return img
    if img.shape[2] == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    if img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
    return img


def save_image(path: Path | str, image: np.ndarray) -> None:
    """保存 numpy 图像到文件（RGB/RGBA/灰度均支持，按扩展名编码）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    ext = path.suffix.lower()
    if image.ndim == 2:
        cv2.imwrite(str(path), image)
        return

    if image.shape[2] == 4:
        bgr = cv2.cvtColor(image, cv2.COLOR_RGBA2BGRA)
    elif image.shape[2] == 3:
        bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    else:
        bgr = image[:, :, :3]
        bgr = cv2.cvtColor(bgr, cv2.COLOR_RGB2BGR)

    if ext in (".jpg", ".jpeg", ".webp"):
        cv2.imwrite(str(path), bgr)
    else:
        # PNG（默认，保留 alpha）
        cv2.imwrite(str(path), bgr)


def numpy_to_png_bytes(image: np.ndarray) -> bytes:
    """numpy 数组编码为 PNG 字节（支持灰度/RGB/RGBA）。"""
    if image.ndim == 2:
        ok, buf = cv2.imencode(".png", image)
    elif image.shape[2] == 3:
        ok, buf = cv2.imencode(".png", cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
    elif image.shape[2] == 4:
        ok, buf = cv2.imencode(".png", cv2.cvtColor(image, cv2.COLOR_RGBA2BGRA))
    else:
        ok, buf = cv2.imencode(".png", image[:, :, :3])
    if not ok:
        raise RuntimeError("图像编码失败")
    return buf.tobytes()


def numpy_to_jpeg_bytes(image: np.ndarray, quality: int = 85) -> bytes:
    """numpy 数组编码为 JPEG 字节。"""
    if image.ndim == 2:
        bgr = image
    elif image.shape[2] == 3:
        bgr = cv2.cvtColor(image[:, :, :3], cv2.COLOR_RGB2BGR)
    elif image.shape[2] == 4:
        # 透明图合成到棋盘格再编码 JPEG
        bgr = cv2.cvtColor(composite_checkerboard(image), cv2.COLOR_RGB2BGR)
    else:
        bgr = image[:, :, :3]
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("图像编码失败")
    return buf.tobytes()


def create_thumbnail(image: np.ndarray, max_size: int = 160) -> np.ndarray:
    """创建缩略图（保持宽高比，最大边不超过 max_size）。"""
    h, w = image.shape[:2]
    scale = min(1.0, max_size / max(h, w))
    if scale >= 1.0:
        return image
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    return cv2.resize(image, (nw, nh), interpolation=cv2.INTER_AREA)


def image_fit(image: np.ndarray, max_w: int, max_h: int) -> np.ndarray:
    """缩放图像以适配给定的显示区域（保持宽高比）。"""
    h, w = image.shape[:2]
    scale = min(max_w / w, max_h / h, 1.0)
    if scale >= 1.0:
        return image
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    return cv2.resize(image, (nw, nh), interpolation=cv2.INTER_AREA)


@lru_cache(maxsize=32)
def create_checkerboard(
    width: int,
    height: int,
    square_size: int = 10,
    color1: Tuple[int, int, int] = (200, 200, 200),
    color2: Tuple[int, int, int] = (255, 255, 255)
) -> np.ndarray:
    """创建棋盘格背景（缓存）。"""
    board = np.zeros((height, width, 3), dtype=np.uint8)

    y_coords, x_coords = np.ogrid[:height, :width]
    grid_x = x_coords // square_size
    grid_y = y_coords // square_size
    use_color1 = ((grid_x + grid_y) % 2 == 0)
    board[:] = np.where(use_color1[:, :, np.newaxis], color1, color2)

    return board


def composite_checkerboard(image: np.ndarray, square_size: int = 10) -> np.ndarray:
    """将 RGBA 图像合成到棋盘格背景上（RGB）。"""
    if image is None:
        return None

    if image.ndim != 3 or image.shape[2] != 4:
        return image[:, :, :3] if image.ndim == 3 else image

    h, w = image.shape[:2]
    checkerboard = create_checkerboard(w, h, square_size)

    alpha = image[:, :, 3:4] / 255.0
    rgb = image[:, :, :3]

    return (rgb * alpha + checkerboard * (1 - alpha)).astype(np.uint8)


def encode_preview(image: np.ndarray, transparent_checker: bool = False,
                   max_w: int = 0, max_h: int = 0, fmt: str = "png") -> bytes:
    """生成预览图像字节。

    Args:
        transparent_checker: RGBA 图像是否合成棋盘格
        max_w / max_h: 缩放上限（0 表示不缩放）
        fmt: png / jpeg
    """
    img = image
    has_alpha = img.ndim == 3 and img.shape[2] == 4

    if transparent_checker and has_alpha:
        img = composite_checkerboard(img)

    if max_w > 0 and max_h > 0:
        img = image_fit(img, max_w, max_h)

    if fmt == "jpeg":
        return numpy_to_jpeg_bytes(img)
    return numpy_to_png_bytes(img)


def pil_to_numpy(pil_img: Image.Image) -> np.ndarray:
    """PIL 图像转 numpy。"""
    return np.array(pil_img)


def numpy_to_pil(image: np.ndarray) -> Image.Image:
    """numpy 数组转 PIL（按通道数选择模式）。"""
    if image.ndim == 2:
        return Image.fromarray(image)
    if image.shape[2] == 3:
        return Image.fromarray(image, mode="RGB")
    if image.shape[2] == 4:
        return Image.fromarray(image, mode="RGBA")
    return Image.fromarray(image[:, :, :3], mode="RGB")
