@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0"
set "PYTHON_CMD="
py -3 -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD (
    python -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
    echo 请安装Python 3.10或更新版本，并勾选Add Python to PATH。
    pause
    exit /b 2
)
%PYTHON_CMD% start_capture.py normal %*
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo 采集程序结束码：%EXIT_CODE%
    echo 请查看上方错误提示。缺少串口库时会自动安装，首次安装需要联网。
)
pause
exit /b %EXIT_CODE%
