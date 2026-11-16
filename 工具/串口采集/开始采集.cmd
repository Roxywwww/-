@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHON_CMD="
py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD (
    python -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
    echo 请安装Python 3，并勾选Add Python to PATH。
    pause
    exit /b 2
)
%PYTHON_CMD% collect_serial.py
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo 采集程序结束码：%EXIT_CODE%
    echo 若是缺少依赖，请在当前目录运行：
    echo python -m pip install -r requirements.txt
)
pause
exit /b %EXIT_CODE%
