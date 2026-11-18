@echo off
setlocal
cd /d "%~dp0.."
if /i "%~1"=="--comprobar" goto verificar
call :verificar
if errorlevel 1 (
  if exist ".venv\" (
    ren ".venv" ".venv-anterior-%RANDOM%-%RANDOM%"
    if errorlevel 1 goto error
  )
  py -3.12 -m venv .venv
  if errorlevel 1 goto error
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto error
".venv\Scripts\python.exe" -c "from pathlib import Path; import sys; Path('.venv/.ciceron-root').write_text(sys.prefix, encoding='utf-8')"
if errorlevel 1 goto error
echo Entorno preparado.
exit /b 0
:verificar
if not exist ".venv\Scripts\python.exe" exit /b 1
if not exist ".venv\.ciceron-root" exit /b 1
".venv\Scripts\python.exe" -c "from pathlib import Path; import sys; sys.exit(not (sys.version_info[:2] == (3, 12) and Path('.venv/.ciceron-root').read_text(encoding='utf-8') == sys.prefix))"
exit /b %errorlevel%
:error
echo No se pudo preparar el entorno. Comprueba Python y la conexion a Internet.
exit /b 1
