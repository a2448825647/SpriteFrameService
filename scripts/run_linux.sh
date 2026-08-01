#!/usr/bin/env bash
# SpriteFrameService - Linux 启动
set -e
cd "$(dirname "$0")/.."

if [ ! -x ".venv/bin/python" ]; then
  echo "未找到 .venv，请先运行 scripts/setup_linux.sh"
  exit 1
fi

HOST="${SPRITE_HOST:-0.0.0.0}"
PORT="${SPRITE_PORT:-8000}"

echo "Starting SpriteFrameService on ${HOST}:${PORT} ..."
exec .venv/bin/python backend/run.py --host "$HOST" --port "$PORT"
