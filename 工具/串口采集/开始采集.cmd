@echo off
setlocal
chcp 65001 >nul
set "CAPTURE_ENTRY=choose_capture.py"
call "%~dp0_运行采集.cmd" %*
exit /b %ERRORLEVEL%
