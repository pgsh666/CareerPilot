@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "CAREERPILOT_LAUNCH_PYTHON=%CAREERPILOT_PYTHON%"
if not defined CAREERPILOT_LAUNCH_PYTHON if exist "%~dp0.venv\Scripts\python.exe" set "CAREERPILOT_LAUNCH_PYTHON=%~dp0.venv\Scripts\python.exe"
if not defined CAREERPILOT_LAUNCH_PYTHON set "CAREERPILOT_LAUNCH_PYTHON=python"
"%CAREERPILOT_LAUNCH_PYTHON%" "%~dp0backend\scripts\restore_local.py"
set "CAREERPILOT_LAUNCH_EXIT=%ERRORLEVEL%"
if not "%CAREERPILOT_LAUNCH_EXIT%"=="0" pause
exit /b %CAREERPILOT_LAUNCH_EXIT%
