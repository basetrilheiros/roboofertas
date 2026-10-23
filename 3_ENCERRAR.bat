@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
if not exist "app\.venv\Scripts\python.exe" goto missing
"app\.venv\Scripts\python.exe" "windows\runtime.py" encerrar
if errorlevel 1 goto failure
pause
exit /b 0
:missing
echo Execute primeiro 1_INSTALAR.bat, na mesma pasta.
:failure
pause
exit /b 1
