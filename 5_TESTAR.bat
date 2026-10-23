@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0app"
set "PYTHONUTF8=1"
if not exist ".venv\Scripts\python.exe" goto missing
".venv\Scripts\python.exe" -m pytest -q
set "BT_RESULT=%ERRORLEVEL%"
pause
exit /b %BT_RESULT%
:missing
echo Execute primeiro 1_INSTALAR.bat.
pause
exit /b 1
