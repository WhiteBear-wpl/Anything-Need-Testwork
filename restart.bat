@echo off
chcp 65001 >nul
setlocal EnableExtensions

cd /d "%~dp0"

echo ==========================================
echo   AITC — 一键重启（Windows）
echo ==========================================
echo.

echo [1/4] 清理占用端口和旧 Worker 进程...
call :kill_port 8000
call :kill_port 5173
taskkill /FI "WINDOWTITLE eq AITC Worker*" /T /F >nul 2>&1
timeout /t 1 /nobreak >nul

if not exist backend\venv\Scripts\python.exe (
    echo [错误] 未找到后端虚拟环境，请先运行 setup.bat。
    pause
    exit /b 1
)

if not exist web\node_modules (
    echo [错误] 未找到前端依赖，请先运行 setup.bat。
    pause
    exit /b 1
)

if not exist .env (
    copy .env.example .env >nul
    echo   已创建 .env
)

echo.
echo [2/4] 启动后端 (uvicorn :8000)...
start "AITC Backend" /D "%~dp0backend" cmd /k "venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"

echo.
echo [3/4] 启动 Agent Worker...
start "AITC Worker" /D "%~dp0backend" cmd /k "venv\Scripts\python.exe -m app.worker"

echo.
echo [4/4] 启动前端 (vite :5173)...
start "AITC Frontend" /D "%~dp0web" cmd /k "npm run dev"

echo.
echo ==========================================
echo   启动完成
echo   前端:    http://localhost:5173
echo   后端:    http://localhost:8000
echo   API 文档: http://localhost:8000/docs
echo ==========================================
pause
exit /b 0

:kill_port
set "PORT=%~1"
set "KILLED=0"
for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":%PORT% " ^| findstr LISTENING') do (
    if not "%%P"=="0" (
        taskkill /F /PID %%P >nul 2>&1
        if not errorlevel 1 set "KILLED=1"
    )
)
if "%KILLED%"=="1" (
    echo   ✔ 端口 :%PORT% 已停止
) else (
    echo   ✔ 端口 :%PORT% 无占用
)
exit /b 0
