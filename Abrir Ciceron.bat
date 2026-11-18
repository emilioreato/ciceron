@echo off
setlocal
set "CICERON_EXE=%~dp0Aplicacion\Ciceron.exe"

if not exist "%CICERON_EXE%" (
    echo No se encuentra Ciceron en la carpeta Aplicacion. Ejecuta Instalar.bat.
    pause
    exit /b 1
)

start "" "%CICERON_EXE%" --abrir
if errorlevel 1 (
    echo No se pudo abrir Ciceron.
    pause
    exit /b 1
)
