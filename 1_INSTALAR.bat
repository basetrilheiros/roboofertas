@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
echo Base Trilheiros - instalacao local para Windows
echo.
py -3.12 -c "import struct; raise SystemExit(0 if struct.calcsize('P') == 8 else 1)" >nul 2>&1
if not errorlevel 1 goto python312
py -3.11 -c "import struct; raise SystemExit(0 if struct.calcsize('P') == 8 else 1)" >nul 2>&1
if not errorlevel 1 goto python311
python -c "import sys,struct; raise SystemExit(0 if (3,11) <= sys.version_info[:2] <= (3,12) and struct.calcsize('P') == 8 else 1)" >nul 2>&1
if not errorlevel 1 goto pythonpath
echo Instale Python 3.12 de 64 bits por uma fonte oficial, conforme o guia.
echo Depois feche esta janela e execute novamente 1_INSTALAR.bat.
pause
exit /b 1
:python312
set "BT_PY=py -3.12"
goto environment
:python311
set "BT_PY=py -3.11"
goto environment
:pythonpath
set "BT_PY=python"
:environment
if exist "app\.venv\Scripts\python.exe" goto dependencies
%BT_PY% -m venv "app\.venv"
if errorlevel 1 goto failure
:dependencies
"app\.venv\Scripts\python.exe" -m pip install --disable-pip-version-check --only-binary=:all: -r "app\requirements.txt"
if errorlevel 1 goto failure
"app\.venv\Scripts\python.exe" "windows\preparar_base_vazia.py"
if errorlevel 1 goto failure
"app\.venv\Scripts\python.exe" "windows\runtime.py" verificar
if errorlevel 1 goto failure
echo.
echo Instalacao concluida. Use 2_ABRIR.bat.
pause
exit /b 0
:failure
echo.
echo A instalacao nao foi concluida. Copie a mensagem de erro para pedir ajuda.
echo Nao apague app\data e nao execute como administrador para tentar corrigir.
pause
exit /b 1
