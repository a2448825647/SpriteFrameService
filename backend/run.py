"""启动入口：python run.py [--host 127.0.0.1] [--port 8000]

host/port 默认取 backend/.env 中的 SPRITE_HOST / SPRITE_PORT。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import uvicorn

from app.config import get_settings


def main():
    settings = get_settings()

    parser = argparse.ArgumentParser(description="SpriteFrameService 后端服务")
    parser.add_argument("--host", default=settings.host, help="监听地址")
    parser.add_argument("--port", type=int, default=settings.port, help="监听端口")
    parser.add_argument("--workers", type=int, default=1, help="uvicorn 进程数")
    args = parser.parse_args()

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        workers=args.workers,
        log_level="info",
    )


if __name__ == "__main__":
    main()
