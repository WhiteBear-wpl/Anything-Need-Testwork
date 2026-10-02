@echo off
chcp 65001 >nul
setlocal EnableExtensions

cd /d "%~dp0"

if not exist backend\venv\Scripts\python.exe (
    echo [错误] 未找到后端虚拟环境。
    echo 请先双击运行 setup.bat。
    pause
    exit /b 1
)

if not exist web\node_modules (
    echo [错误] 未找到前端依赖。
    echo 请先双击运行 setup.bat。
    pause
    exit /b 1
)

if not exist .env (
    echo [提示] 未找到 .env，正在从 .env.example 复制...
    copy .env.example .env >nul
)

echo ==========================================
echo   AITC — 启动前后端与 Agent Worker
echo ==========================================
echo.

echo [AITC] 启动后端 http://localhost:8000 ...
start "AITC Backend" /D "%~dp0backend" cmd /k "venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"

echo [AITC] 启动 Agent Worker ...
start "AITC Worker" /D "%~dp0backend" cmd /k "venv\Scripts\python.exe -m app.worker"

echo [AITC] 启动前端 http://localhost:5173 ...
start "AITC Frontend" /D "%~dp0web" cmd /k "npm run dev"

echo.
echo ==========================================
echo   启动完成（三个新窗口分别运行后端、Worker、前端）
echo   前端:    http://localhost:5173
echo   后端:    http://localhost:8000
echo   API 文档: http://localhost:8000/docs
echo ==========================================
echo.
echo 关闭对应窗口即可停止服务；Runtime V2 任务需要 Worker 窗口保持运行。
pause
