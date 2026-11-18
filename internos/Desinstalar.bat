@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0integracion\desinstalar.ps1" -InstallDir "%~dp0." %*
set "CICERON_RESULT=%errorlevel%"
pause
exit /b %CICERON_RESULT%
