@echo off
setlocal
cd /d "%~dp0.."
call "%~dp0preparar.bat" --comprobar >nul
if errorlevel 1 (
  call "%~dp0preparar.bat"
  if errorlevel 1 goto error
)
set "CICERON_DEV=1"
set "CICERON_HOME=%CD%\.desarrollo"
set "CICERON_DATA="
set "CICERON_SOURCE_ROOT="
set "CICERON_LIVE_SOURCE="
set "CICERON_LIVE_DIGEST="
".venv\Scripts\python.exe" src\ciceron.pyw --abrir
if errorlevel 1 goto error
exit /b 0
:error
echo No se pudo iniciar Ciceron.
pause
exit /b 1
