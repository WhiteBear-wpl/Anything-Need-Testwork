@echo off
setlocal
rem 一键运行自动化测试：run_tests.bat [api^|ui^|smoke^|all]
cd /d "%~dp0"

set "SUITE=%~1"
if "%SUITE%"=="" set "SUITE=all"
set "PLAYWRIGHT_BROWSERS_PATH=%~dp0.browsers"

if not exist venv\Scripts\pytest.exe (
    echo ==^> Initializing virtual environment
    python -m venv venv
    if errorlevel 1 ( echo Failed to create venv & pause & exit /b 1 )
    call venv\Scripts\pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 ( echo Failed to install dependencies & pause & exit /b 1 )
)

if not exist .browsers (
    if not "%SUITE%"=="api" (
        echo ==^> Installing Playwright Chromium
        call venv\Scripts\playwright install chromium
    )
)

if not exist reports mkdir reports

if "%SUITE%"=="api" (
    venv\Scripts\pytest api --html reports\api-report.html --self-contained-html
) else if "%SUITE%"=="ui" (
    venv\Scripts\pytest ui --screenshot only-on-failure --output ui\artifacts --html reports\ui-report.html --self-contained-html
) else if "%SUITE%"=="smoke" (
    venv\Scripts\pytest -m smoke --screenshot only-on-failure --output ui\artifacts --html reports\smoke-report.html --self-contained-html
) else if "%SUITE%"=="all" (
    venv\Scripts\pytest api ui --screenshot only-on-failure --output ui\artifacts --html reports\full-report.html --self-contained-html
) else (
    echo Usage: %~nx0 [api^|ui^|smoke^|all]
    exit /b 1
)
