@echo off
setlocal
chcp 65001 > nul 2>&1
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
    echo 未找到 .venv，请先运行 scripts\setup_windows.bat
    pause & exit /b 1
)

echo Starting SpriteFrameService backend ...
.venv\Scripts\python.exe backend\run.py

pause
