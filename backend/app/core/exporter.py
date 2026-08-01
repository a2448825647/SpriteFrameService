"""导出模块（移植自 SpriteFrameStudio）。

注意：调用方需先把帧图像从磁盘加载到内存（FrameData.image / processed_image），
Exporter 只负责消费内存图像并产出文件。
"""
from __future__ import annotations

from typing import List, Optional, Tuple
from pathlib import Path

import json
import math

import numpy as np
from PIL import Image

from app.models.frame_data import FrameData
from app.models.export_config import (
    ExportConfig, ExportFormat, LayoutMode,
    SpriteSheetMeta, FrameRect, ResampleFilter
)
from app.utils.pngquant import compress_png, format_file_size
from app.core.sprite_webp_exporter import export_sprite_sheet_as_webp


def get_pil_resample_filter(filter_type: ResampleFilter):
    """将ResampleFilter枚举转换为PIL的Resampling常量"""
    mapping = {
        ResampleFilter.NEAREST: Image.Resampling.NEAREST,
        ResampleFilter.BOX: Image.Resampling.BOX,
        ResampleFilter.BILINEAR: Image.Resampling.BILINEAR,
        ResampleFilter.HAMMING: Image.Resampling.HAMMING,
        ResampleFilter.BICUBIC: Image.Resampling.BICUBIC,
        ResampleFilter.LANCZOS: Image.Resampling.LANCZOS,
    }
    return mapping.get(filter_type, Image.Resampling.LANCZOS)


def _normalize_sizes(images: list, resample_filter) -> list:
    """将混合尺寸的帧统一缩放到首帧尺寸。"""
    if not images:
        return images
    target_h, target_w = images[0][1].shape[:2]
    result = []
    for frame_index, img in images:
        if img.shape[:2] != (target_h, target_w):
            img = np.array(Image.fromarray(img).resize((target_w, target_h), resample_filter))
        result.append((frame_index, img))
    return result


class Exporter:
    """导出管理器"""

    def export(
        self,
        frames: List[FrameData],
        config: ExportConfig
    ) -> Tuple[str, Optional[str]]:
        """导出帧。返回 (主文件路径, 附加信息或None)。"""
        if config.format == ExportFormat.GIF:
            gif_path = self.export_gif(frames, config)
            return (str(gif_path), None)
        elif config.format == ExportFormat.GODOT:
            return self.export_godot(frames, config)
        elif config.format == ExportFormat.WEBP:
            if config.sprite_config is not None:
                return export_sprite_sheet_as_webp(frames, config)
            else:
                return self.export_webp(frames, config)
        elif config.format == ExportFormat.SPRITE_SHEET:
            return self.export_sprite_sheet(frames, config)
        else:
            return self.export_frames(frames, config)

    def export_sprite_sheet(
        self,
        frames: List[FrameData],
        config: ExportConfig
    ) -> Tuple[str, Optional[str]]:
        """导出精灵图。返回 (PNG路径, 附加信息)。"""
        if not frames:
            raise ValueError("没有要导出的帧")

        sprite_config = config.sprite_config

        images = []
        for frame in frames:
            img = frame.display_image
            if img is not None:
                if sprite_config.frame_width and sprite_config.frame_height:
                    pil_img = Image.fromarray(img)
                    resample_filter = get_pil_resample_filter(sprite_config.resample_filter)
                    pil_img = pil_img.resize(
                        (sprite_config.frame_width, sprite_config.frame_height),
                        resample_filter
                    )
                    img = np.array(pil_img)
                images.append((frame.index, img))

        if not images:
            raise ValueError("没有可导出的图像")

        # 统一尺寸：混合尺寸帧缩放到首帧尺寸（避免拼接错误）
        images = _normalize_sizes(images, get_pil_resample_filter(sprite_config.resample_filter))

        frame_height, frame_width = images[0][1].shape[:2]
        has_alpha = images[0][1].shape[2] == 4 if len(images[0][1].shape) == 3 else False

        num_frames = len(images)
        padding = sprite_config.padding

        if sprite_config.layout == LayoutMode.HORIZONTAL:
            cols = num_frames
            rows = 1
        elif sprite_config.layout == LayoutMode.VERTICAL:
            cols = 1
            rows = num_frames
        else:
            cols = sprite_config.columns or math.ceil(math.sqrt(num_frames))
            rows = math.ceil(num_frames / cols)

        sheet_width = cols * (frame_width + padding) - padding
        sheet_height = rows * (frame_height + padding) - padding

        if has_alpha:
            sheet = np.zeros((sheet_height, sheet_width, 4), dtype=np.uint8)
            sheet[:, :] = sprite_config.background_color
        else:
            sheet = np.zeros((sheet_height, sheet_width, 3), dtype=np.uint8)
            sheet[:, :] = sprite_config.background_color[:3]

        frame_rects = []
        for i, (frame_index, img) in enumerate(images):
            row = i // cols
            col = i % cols

            x = col * (frame_width + padding)
            y = row * (frame_height + padding)

            if has_alpha and img.shape[2] == 3:
                alpha = np.full((frame_height, frame_width, 1), 255, dtype=np.uint8)
                img = np.concatenate([img, alpha], axis=2)
            elif not has_alpha and img.shape[2] == 4:
                img = img[:, :, :3]

            sheet[y:y + frame_height, x:x + frame_width] = img

            frame_rects.append(FrameRect(
                frame_index=frame_index,
                x=x,
                y=y,
                width=frame_width,
                height=frame_height
            ))

        output_path = config.get_output_file()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        pil_sheet = Image.fromarray(sheet)
        pil_sheet.save(str(output_path))

        compress_info = None
        if config.pngquant_config.enabled:
            success, original_size, compressed_size = compress_png(
                output_path,
                quality_min=config.pngquant_config.quality_min,
                quality_max=config.pngquant_config.quality_max
            )
            if success:
                saved = original_size - compressed_size
                ratio = (1 - compressed_size / original_size) * 100 if original_size > 0 else 0
                compress_info = f"压缩: {format_file_size(original_size)} -> {format_file_size(compressed_size)} (节省 {ratio:.1f}%)"

        json_path = None
        if sprite_config.generate_json:
            json_path = config.get_json_file()

            meta = SpriteSheetMeta(
                image_path=output_path.name,
                image_width=sheet_width,
                image_height=sheet_height,
                frame_count=num_frames,
                frames=frame_rects
            )

            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(meta.model_dump(), f, indent=2, ensure_ascii=False)

        result_info = str(json_path) if json_path else compress_info
        if json_path and compress_info:
            result_info = f"{json_path}\n{compress_info}"

        return (str(output_path), result_info)

    def export_gif(self, frames: List[FrameData], config: ExportConfig) -> str:
        """导出GIF动画"""
        if not frames:
            raise ValueError("没有要导出的帧")

        gif_config = config.gif_config

        pil_images = []
        for frame in frames:
            img = frame.display_image
            if img is not None:
                if len(img.shape) == 3 and img.shape[2] == 4:
                    pil_img = Image.fromarray(img)
                    background = Image.new('RGB', pil_img.size, (255, 255, 255))
                    background.paste(pil_img, mask=pil_img.split()[3])
                    pil_img = background
                else:
                    pil_img = Image.fromarray(img)

                if gif_config.frame_width and gif_config.frame_height:
                    resample_filter = get_pil_resample_filter(gif_config.resample_filter)
                    pil_img = pil_img.resize(
                        (gif_config.frame_width, gif_config.frame_height),
                        resample_filter
                    )

                pil_images.append(pil_img)

        if not pil_images:
            raise ValueError("没有可导出的图像")

        duration = int(1000 / gif_config.fps)

        output_path = config.get_output_file()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        pil_images[0].save(
            str(output_path),
            save_all=True,
            append_images=pil_images[1:],
            duration=duration,
            loop=gif_config.loop,
            optimize=gif_config.optimize
        )

        return str(output_path)

    def export_frames(self, frames: List[FrameData], config: ExportConfig) -> Tuple[str, Optional[str]]:
        """导出单独的帧图片"""
        if not frames:
            raise ValueError("没有要导出的帧")

        output_dir = config.output_path or Path(".")
        output_dir.mkdir(parents=True, exist_ok=True)

        total_original = 0
        total_compressed = 0
        exported_files = []

        for frame in frames:
            img = frame.display_image
            if img is not None:
                pil_img = Image.fromarray(img)

                filename = f"{config.output_name}_{frame.index:04d}.png"
                file_path = output_dir / filename
                pil_img.save(str(file_path))
                exported_files.append(file_path)

        compress_info = None
        if config.pngquant_config.enabled and exported_files:
            for file_path in exported_files:
                success, original_size, compressed_size = compress_png(
                    file_path,
                    quality_min=config.pngquant_config.quality_min,
                    quality_max=config.pngquant_config.quality_max
                )
                if success:
                    total_original += original_size
                    total_compressed += compressed_size

            if total_original > 0:
                ratio = (1 - total_compressed / total_original) * 100
                compress_info = f"压缩: {format_file_size(total_original)} -> {format_file_size(total_compressed)} (节省 {ratio:.1f}%)"

        return (str(output_dir), compress_info)

    def export_webp(self, frames: List[FrameData], config: ExportConfig) -> Tuple[str, Optional[str]]:
        """导出WebP格式"""
        if not frames:
            raise ValueError("没有要导出的帧")

        webp_config = config.webp_config
        output_path = config.output_path or Path(".")
        output_path.mkdir(parents=True, exist_ok=True)

        exported_files = []

        for i, frame in enumerate(frames):
            img = frame.display_image
            if img is not None:
                pil_img = Image.fromarray(img)

                if webp_config.frame_width and webp_config.frame_height:
                    resample_filter = get_pil_resample_filter(webp_config.resample_filter)
                    pil_img = pil_img.resize(
                        (webp_config.frame_width, webp_config.frame_height),
                        resample_filter
                    )

                filename = f"{config.output_name}_{i:04d}.webp"
                file_path = output_path / filename
                pil_img.save(str(file_path), format='WebP', quality=webp_config.quality)
                exported_files.append(file_path)

        return (str(output_path), f"导出 {len(exported_files)} 个WebP文件")

    def export_godot(self, frames: List[FrameData], config: ExportConfig) -> Tuple[str, Optional[str]]:
        """导出Godot SpriteFrames资源"""
        if not frames:
            raise ValueError("没有要导出的帧")

        godot_config = config.godot_config
        output_path = config.output_path or Path(".")
        output_path.mkdir(parents=True, exist_ok=True)

        frame_resources = []

        if godot_config.export_individual_frames:
            for i, frame in enumerate(frames):
                img = frame.display_image
                if img is not None:
                    if godot_config.frame_width and godot_config.frame_height:
                        pil_img = Image.fromarray(img)
                        resample_filter = get_pil_resample_filter(godot_config.resample_filter)
                        pil_img = pil_img.resize(
                            (godot_config.frame_width, godot_config.frame_height),
                            resample_filter
                        )
                        img = np.array(pil_img)

                    pil_img = Image.fromarray(img)
                    frame_filename = f"{config.output_name}_frame_{i:04d}.png"
                    frame_path = output_path / frame_filename
                    pil_img.save(str(frame_path))

                    frame_resources.append(frame_filename)

        tres_path = config.get_output_file()

        tres_content = self._generate_godot_tres(
            frame_resources,
            godot_config.animation_name,
            godot_config.fps,
            godot_config.loop
        )

        with open(tres_path, 'w', encoding='utf-8') as f:
            f.write(tres_content)

        return (str(tres_path), f"导出 {len(frame_resources)} 个帧文件")

    def _generate_godot_tres(self, frame_paths: List[str], animation_name: str,
                             fps: float, loop: bool) -> str:
        """生成Godot .tres资源文件内容"""
        ext_resources = []
        for i, frame_path in enumerate(frame_paths, start=1):
            ext_resources.append(
                f'[ext_resource type="Texture2D" path="{frame_path}" id="{i}"]'
            )

        frames_list = []
        for i in range(len(frame_paths)):
            frame_entry = (
                '{\n'
                '"duration": 1.0,\n'
                f'"texture": ExtResource("{i+1}")\n'
                '}'
            )
            frames_list.append(frame_entry)

        ext_resources_str = '\n'.join(ext_resources)
        frames_list_str = ', '.join(frames_list)
        loop_str = "true" if loop else "false"

        tres_content = f'''[gd_resource type="SpriteFrames" load_steps={len(frame_paths)+1} format=3]

{ext_resources_str}

[resource]

animations = [{{
"frames": [{frames_list_str}],
"loop": {loop_str},
"name": "{animation_name}",
"speed": {fps}
}}]
'''

        return tres_content
