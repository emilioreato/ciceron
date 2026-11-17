@echo off
setlocal
set "CICERON_EXE=%LOCALAPPDATA%\Ciceron\Ciceron.exe"

if not exist "%CICERON_EXE%" (
    echo No se encuentra Ciceron. Ejecuta Instalar.bat una vez para instalarlo.
    pause
    exit /b 1
)

start "" "%CICERON_EXE%" --abrir
if errorlevel 1 (
    echo No se pudo abrir Ciceron.
    pause
    exit /b 1
)
