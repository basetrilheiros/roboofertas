@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "BASETRILHEIROS_OAUTH_REAL=1"
"app\.venv\Scripts\python.exe" "windows\runtime.py" abrir
if errorlevel 1 pause
