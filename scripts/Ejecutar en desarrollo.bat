@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  call "%~dp0preparar.bat"
  if errorlevel 1 goto error
)
".venv\Scripts\python.exe" src\ciceron.pyw
if errorlevel 1 goto error
exit /b 0
:error
echo No se pudo iniciar Ciceron.
pause
exit /b 1
