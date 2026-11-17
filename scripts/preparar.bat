@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if errorlevel 1 goto error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto error
echo Entorno preparado.
exit /b 0
:error
echo No se pudo preparar el entorno. Comprueba Python y la conexion a Internet.
exit /b 1
