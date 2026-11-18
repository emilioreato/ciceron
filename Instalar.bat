@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0internos\instalar.ps1" -PreferirFuentes %*
set "CICERON_RESULT=%errorlevel%"
pause
exit /b %CICERON_RESULT%
