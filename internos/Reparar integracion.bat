@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0integracion\instalar.ps1" -InstallDir "%~dp0." -Reparar %*
set "CICERON_RESULT=%errorlevel%"
pause
exit /b %CICERON_RESULT%
