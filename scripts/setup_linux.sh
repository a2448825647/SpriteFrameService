#!/usr/bin/env bash
# SpriteFrameService - Linux 环境初始化
set -e
cd "$(dirname "$0")/.."

echo "=========================================="
echo "  SpriteFrameService - Linux 初始化"
echo "=========================================="

PYTHON="${PYTHON:-python3}"

# 1. Python 虚拟环境
if [ ! -d ".venv" ]; then
  echo "[1/4] 创建 Python 虚拟环境 (.venv) ..."
  "$PYTHON" -m venv .venv
fi

# 2. 后端依赖
echo "[2/4] 安装后端依赖 ..."
.venv/bin/python -m pip install --upgrade pip -q
.venv/bin/python -m pip install -r backend/requirements.txt

# GPU 服务器可选：onnxruntime-gpu（需 CUDA/cuDNN，见 README）
if [ -n "$SPRITE_GPU" ]; then
  echo "      安装 onnxruntime-gpu ..."
  .venv/bin/python -m pip uninstall -y onnxruntime onnxruntime-gpu
  .venv/bin/python -m pip install onnxruntime-gpu
fi

# 3. 前端构建（需要 Node.js；如无则跳过，直接拷贝 dist）
if command -v npm >/dev/null 2>&1; then
  echo "[3/4] 构建前端 ..."
  ( cd frontend && npm install && npm run build )
else
  echo "[3/4] 未找到 npm，跳过前端构建。请将前端 dist 目录拷贝到 frontend/dist。"
fi

# 4. 模型目录检查
echo "[4/4] 检查模型目录 ..."
if [ ! -f "models/u2net.onnx" ] && [ -z "$SPRITE_MODELS_DIR" ]; then
  echo "      警告：未找到 models/ 目录。请放置抠图/姿势/RealESRGAN 模型，"
  echo "      或在 backend/.env 中设置 SPRITE_MODELS_DIR。"
fi

echo ""
echo "初始化完成。运行 scripts/run_linux.sh 启动服务。"
