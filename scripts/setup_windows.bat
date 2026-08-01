@echo off
setlocal
chcp 65001 > nul 2>&1
cd /d "%~dp0\.."

echo ==========================================
echo   SpriteFrameService - Windows 环境初始化
echo ==========================================

REM ---- Python 虚拟环境 ----
if not exist ".venv\Scripts\python.exe" (
    echo [1/3] 创建 Python 虚拟环境 (.venv) ...
    python -m venv .venv
    if errorlevel 1 (
        echo 创建失败。请安装 Python 3.11-3.13 后重试。
        pause & exit /b 1
    )
)

echo [2/3] 安装后端依赖 ...
.venv\Scripts\python.exe -m pip install --upgrade pip -q
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt -r backend\requirements-dev.txt
if errorlevel 1 (
    echo 后端依赖安装失败。
    pause & exit /b 1
)

REM ---- 前端构建 ----
if not exist "frontend\node_modules" (
    echo [3/3] 安装并构建前端 (需要 Node.js 18+) ...
    pushd frontend
    call npm install
    call npm run build
    popd
    if errorlevel 1 (
        echo 前端构建失败。
        pause & exit /b 1
    )
) else if exist "frontend\package.json" (
    echo [3/3] 构建前端 ...
    pushd frontend
    call npm run build
    popd
)

echo.
echo 初始化完成。运行 run_windows.bat 启动服务。
pause
