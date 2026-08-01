"""背景去除模块（移植自 SpriteFrameStudio）。

模型目录通过 app.config 解析（SPRITE_MODELS_DIR），不写死路径。
"""
from __future__ import annotations

from typing import Optional, Tuple, Callable, Dict
from enum import Enum
from pathlib import Path

import numpy as np
import cv2

from app.config import get_settings


class BackgroundMode(str, Enum):
    """背景去除模式"""
    AI = "ai"          # AI模式 (rembg)
    COLOR = "color"    # 颜色阈值模式


class AIModel(str, Enum):
    """AI模型类型"""
    U2NET = "u2net"                    # 通用模型 (176MB)
    U2NET_HUMAN = "u2net_human_seg"    # 人像专用 (176MB)
    SILUETA = "silueta"                # 轮廓精细 (43MB)
    ISNET_ANIME = "isnet-anime"        # 动漫专用 (176MB)
    BRIA_RMBG = "bria-rmbg-2.0"        # 新一代高精度模型


AI_MODEL_INFO: Dict[str, dict] = {
    "u2net": {
        "name": "U2Net (通用)",
        "size": "176MB",
        "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx",
        "input_size": (320, 320),
    },
    "u2net_human_seg": {
        "name": "U2Net Human (人像)",
        "size": "176MB",
        "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net_human_seg.onnx",
        "input_size": (320, 320),
    },
    "silueta": {
        "name": "Silueta (轮廓)",
        "size": "43MB",
        "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/silueta.onnx",
        "input_size": (320, 320),
    },
    "isnet-anime": {
        "name": "ISNet Anime (动漫)",
        "size": "176MB",
        "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-anime.onnx",
        "input_size": (1024, 1024),
    },
    "bria-rmbg-2.0": {
        "name": "BRIA RMBG 2.0 (推荐)",
        "size": "100MB+",
        "url": "本地加载",
        "input_size": (1024, 1024),
    },
}


class U2NetLocalSession:
    """本地 U2Net 会话，绕过 pooch 下载机制"""

    def __init__(self, model_path: str, model_name: str = "u2net",
                 force_cpu: bool = False,
                 progress_callback: Optional[Callable[[str], None]] = None):
        import onnxruntime as ort

        self.model_name = model_name
        self.input_size = AI_MODEL_INFO.get(model_name, {}).get("input_size", (320, 320))

        if progress_callback:
            progress_callback("正在初始化ONNX运行时...")

        sess_opts = ort.SessionOptions()
        sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        if force_cpu:
            providers = ['CPUExecutionProvider']
            if progress_callback:
                progress_callback("使用 CPU 模式...")
        else:
            available_providers = ort.get_available_providers()
            use_cuda = 'CUDAExecutionProvider' in available_providers

            if use_cuda:
                providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
                if progress_callback:
                    progress_callback("正在尝试启用 GPU 加速...")
            else:
                providers = ['CPUExecutionProvider']
                if progress_callback:
                    progress_callback("GPU 不可用，使用 CPU 模式...")

        try:
            self.inner_session = ort.InferenceSession(
                model_path,
                sess_options=sess_opts,
                providers=providers
            )

            actual_providers = self.inner_session.get_providers()
            self.device_type = "GPU (CUDA)" if 'CUDAExecutionProvider' in actual_providers else "CPU"

            if progress_callback:
                if not force_cpu and 'CUDAExecutionProvider' not in available_providers and self.device_type == "CPU":
                    progress_callback("警告: GPU 初始化失败，已回退到 CPU")
                else:
                    progress_callback(f"AI模型加载完成 (实际设备: {self.device_type})")
        except Exception as e:
            if not force_cpu and 'CUDAExecutionProvider' in providers:
                if progress_callback:
                    progress_callback(f"GPU 加载失败，回退到 CPU: {str(e)}")
                providers = ['CPUExecutionProvider']
                self.inner_session = ort.InferenceSession(
                    model_path,
                    sess_options=sess_opts,
                    providers=providers
                )
                self.device_type = "CPU"
            else:
                raise

    def predict(self, img):
        """预测遮罩"""
        from PIL import Image

        mean = (0.485, 0.456, 0.406)
        std = (0.229, 0.224, 0.225)

        im = img.convert("RGB").resize(self.input_size, Image.Resampling.LANCZOS)
        im_ary = np.array(im)
        im_ary = im_ary / max(np.max(im_ary), 1e-6)

        tmpImg = np.zeros((im_ary.shape[0], im_ary.shape[1], 3))
        tmpImg[:, :, 0] = (im_ary[:, :, 0] - mean[0]) / std[0]
        tmpImg[:, :, 1] = (im_ary[:, :, 1] - mean[1]) / std[1]
        tmpImg[:, :, 2] = (im_ary[:, :, 2] - mean[2]) / std[2]

        tmpImg = tmpImg.transpose((2, 0, 1))

        input_name = self.inner_session.get_inputs()[0].name
        input_data = {input_name: np.expand_dims(tmpImg, 0).astype(np.float32)}

        ort_outs = self.inner_session.run(None, input_data)

        pred = ort_outs[0][:, 0, :, :]
        ma = np.max(pred)
        mi = np.min(pred)
        pred = (pred - mi) / (ma - mi)
        pred = np.squeeze(pred)

        mask = Image.fromarray((pred.clip(0, 1) * 255).astype("uint8"), mode="L")
        mask = mask.resize(img.size, Image.Resampling.LANCZOS)

        return [mask]


class BackgroundRemover:
    """背景去除器"""

    _model_cache: Dict[str, U2NetLocalSession] = {}

    def __init__(self, progress_callback: Optional[Callable[[str], None]] = None):
        self._current_model: Optional[str] = None
        self._rembg_session: Optional[U2NetLocalSession] = None
        self._cancel_flag = False
        self._progress_callback = progress_callback

    def cancel(self):
        self._cancel_flag = True

    def _report_progress(self, message: str):
        if self._progress_callback:
            self._progress_callback(message)

    @staticmethod
    def get_model_path(model_name: str) -> Optional[Path]:
        """获取模型文件路径（优先项目 models 目录，其次用户 home）。"""
        settings = get_settings()
        project_model_path = settings.resolved_models_dir / f"{model_name}.onnx"

        home_model_path = Path.home() / ".u2net" / f"{model_name}.onnx"

        if project_model_path.exists():
            return project_model_path
        elif home_model_path.exists():
            return home_model_path
        return None

    @staticmethod
    def get_available_models() -> list:
        """获取可用的模型列表"""
        available = []
        for model_name, info in AI_MODEL_INFO.items():
            path = BackgroundRemover.get_model_path(model_name)
            available.append({
                "name": model_name,
                "display_name": info["name"],
                "size": info["size"],
                "url": info["url"],
                "installed": path is not None,
                "path": str(path) if path else None
            })
        return available

    def _init_rembg(self, model_name: str = "u2net", force_cpu: bool = False):
        """初始化rembg会话(懒加载)"""
        cache_key = f"{model_name}_{'cpu' if force_cpu else 'gpu'}"

        if cache_key in BackgroundRemover._model_cache:
            self._rembg_session = BackgroundRemover._model_cache[cache_key]
            self._current_model = model_name
            return

        model_path = self.get_model_path(model_name)

        if model_path is None:
            info = AI_MODEL_INFO.get(model_name, {})
            settings = get_settings()
            expected_path = settings.resolved_models_dir / f"{model_name}.onnx"
            raise FileNotFoundError(
                f"AI模型文件不存在，请手动下载:\n"
                f"模型: {info.get('name', model_name)}\n"
                f"下载地址: {info.get('url', '未知')}\n"
                f"存放位置: {expected_path}"
            )

        session = U2NetLocalSession(
            str(model_path),
            model_name=model_name,
            force_cpu=force_cpu,
            progress_callback=self._report_progress
        )

        BackgroundRemover._model_cache[cache_key] = session
        self._rembg_session = session
        self._current_model = model_name

    def remove_background(
        self,
        image: np.ndarray,
        mode: BackgroundMode = BackgroundMode.AI,
        color_params: Optional[dict] = None,
        ai_params: Optional[dict] = None
    ) -> np.ndarray:
        """去除图像背景，返回 RGBA (H, W, 4)。

        ai_params: {model, alpha_threshold, erode, feather, force_cpu}
        color_params: {lower, upper, invert, feather, denoise}
        """
        if mode == BackgroundMode.AI:
            return self._remove_ai(image, ai_params or {})
        else:
            return self._remove_color(image, color_params or {})

    def _remove_ai(self, image: np.ndarray, params: dict) -> np.ndarray:
        model_name = params.get('model', 'u2net')
        alpha_threshold = params.get('alpha_threshold', 0)
        erode = params.get('erode', 0)
        feather = params.get('feather', 0)
        force_cpu = params.get('force_cpu', get_settings().force_cpu)

        self._init_rembg(model_name, force_cpu=force_cpu)

        from PIL import Image

        original_alpha = None
        if len(image.shape) == 3 and image.shape[2] == 4:
            rgb_image = image[:, :, :3].copy()
            original_alpha = image[:, :, 3].copy()
        else:
            rgb_image = image

        pil_image = Image.fromarray(rgb_image)
        masks = self._rembg_session.predict(pil_image)
        mask = np.array(masks[0])

        mask = self._postprocess_mask(mask, alpha_threshold, erode, feather)

        if original_alpha is not None:
            mask = cv2.bitwise_and(mask, original_alpha)

        rgba = np.zeros((rgb_image.shape[0], rgb_image.shape[1], 4), dtype=np.uint8)
        rgba[:, :, :3] = rgb_image
        rgba[:, :, 3] = mask

        return rgba

    def _postprocess_mask(self, mask: np.ndarray, alpha_threshold: int = 0,
                          erode: int = 0, feather: int = 0) -> np.ndarray:
        """后处理遮罩"""
        result = mask.copy()

        if alpha_threshold > 0:
            result = np.where(result > alpha_threshold, 255, 0).astype(np.uint8)

        if erode != 0:
            kernel_size = abs(erode) * 2 + 1
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
            if erode > 0:
                result = cv2.erode(result, kernel, iterations=1)
            else:
                result = cv2.dilate(result, kernel, iterations=1)

        if feather > 0:
            blur_size = feather * 2 + 1
            result = cv2.GaussianBlur(result, (blur_size, blur_size), 0)

        return result

    def _remove_color(self, image: np.ndarray, params: dict) -> np.ndarray:
        """使用颜色阈值模式去除背景"""
        lower = params.get('lower', (35, 50, 50))
        upper = params.get('upper', (85, 255, 255))
        invert = params.get('invert', False)
        feather = params.get('feather', 0)
        denoise = params.get('denoise', 1)

        original_alpha = None
        if len(image.shape) == 3 and image.shape[2] == 4:
            rgb_image = image[:, :, :3].copy()
            original_alpha = image[:, :, 3].copy()
        else:
            rgb_image = image

        hsv = cv2.cvtColor(rgb_image, cv2.COLOR_RGB2HSV)

        mask = cv2.inRange(hsv, np.array(lower), np.array(upper))

        if not invert:
            mask = cv2.bitwise_not(mask)

        if denoise > 0:
            kernel_size = denoise * 2 + 1
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        if feather > 0:
            blur_size = feather * 2 + 1
            mask = cv2.GaussianBlur(mask, (blur_size, blur_size), 0)

        if original_alpha is not None:
            mask = cv2.bitwise_and(mask, original_alpha)

        rgba = np.zeros((rgb_image.shape[0], rgb_image.shape[1], 4), dtype=np.uint8)
        rgba[:, :, :3] = rgb_image
        rgba[:, :, 3] = mask

        return rgba

    def add_outline(self, rgba: np.ndarray, thickness: int, color: tuple = (0, 0, 0)) -> np.ndarray:
        """给RGBA图像添加轮廓描边"""
        return self._add_outline(rgba, thickness, color)

    def _add_outline(self, rgba: np.ndarray, thickness: int, color: tuple = (0, 0, 0)) -> np.ndarray:
        if thickness <= 0:
            return rgba

        alpha = rgba[:, :, 3]

        alpha_smooth = cv2.GaussianBlur(alpha, (5, 5), 0)
        _, binary = cv2.threshold(alpha_smooth, 127, 255, cv2.THRESH_BINARY)

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        binary = cv2.erode(binary, kernel, iterations=1)

        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = [cnt for cnt in contours if cv2.contourArea(cnt) > 100]

        if not contours:
            return rgba

        result = rgba.copy()
        rgb = np.ascontiguousarray(result[:, :, :3])
        cv2.drawContours(rgb, contours, -1, color, thickness, lineType=cv2.LINE_AA)
        result[:, :, :3] = rgb

        return result

    def batch_remove(
        self,
        images: list,
        mode: BackgroundMode = BackgroundMode.AI,
        color_params: Optional[dict] = None,
        ai_params: Optional[dict] = None,
        progress_callback: Optional[Callable[[int, int, float], None]] = None
    ) -> list:
        """批量去除背景"""
        self._cancel_flag = False
        results = []
        total = len(images)

        for i, image in enumerate(images):
            if self._cancel_flag:
                break

            result = self.remove_background(image, mode, color_params, ai_params)
            results.append(result)

            if progress_callback:
                progress = (i + 1) / total * 100
                progress_callback(i + 1, total, progress)

        return results

    @staticmethod
    def get_color_presets() -> dict:
        """获取颜色预设"""
        return {
            "绿幕": {
                'lower': (35, 50, 50),
                'upper': (85, 255, 255),
                'invert': False
            },
            "蓝幕": {
                'lower': (100, 50, 50),
                'upper': (130, 255, 255),
                'invert': False
            },
            "白色背景": {
                'lower': (0, 0, 200),
                'upper': (180, 30, 255),
                'invert': False
            },
            "黑色背景": {
                'lower': (0, 0, 0),
                'upper': (180, 255, 50),
                'invert': False
            }
        }
