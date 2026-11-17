@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    call "%~dp0preparar.bat"
    if errorlevel 1 goto error
)
set "PYINSTALLER_CONFIG_DIR=%CD%\.compilacion\cache"
".venv\Scripts\python.exe" -m PyInstaller --clean --noconfirm --onedir --windowed ^
    --name Ciceron --icon "%CD%\assets\ciceron.ico" --add-data "%CD%\assets\ciceron.png;assets" ^
    --distpath internos --workpath .compilacion --specpath .compilacion src\ciceron.pyw
if errorlevel 1 goto error
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --onefile --console --name CiceronHost --icon "%CD%\assets\ciceron.ico" --distpath .salida --workpath .compilacion --specpath .compilacion src\browser_bridge.py
if errorlevel 1 goto error
copy /y ".salida\CiceronHost.exe" "internos\CiceronHost.exe" >nul
if errorlevel 1 goto error
echo Ejecutable actualizado. Usa Instalar.bat para instalarlo.
pause
exit /b 0
:error
echo No se pudo crear el ejecutable.
pause
exit /b 1
