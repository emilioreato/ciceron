@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0internos\instalar.ps1" %*
set "CICERON_RESULT=%errorlevel%"
pause
exit /b %CICERON_RESULT%
