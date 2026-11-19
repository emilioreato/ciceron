function Test-CiceronRuntime([string]$Runtime) {
    return (Test-Path -LiteralPath (Join-Path $Runtime 'base_library.zip') -PathType Leaf) -or
        ((Test-Path -LiteralPath (Join-Path $Runtime 'src\ciceron.pyw') -PathType Leaf) -and
         (Test-Path -LiteralPath (Join-Path $Runtime 'entorno.txt') -PathType Leaf) -and
         (Test-Path -LiteralPath (Join-Path $Runtime 'requirements-runtime.txt') -PathType Leaf))
}

function Initialize-CiceronEnvironment([string]$Root, [string]$Runtime, [string]$Seed) {
    $reference = Join-Path $Runtime 'entorno.txt'
    if (!(Test-Path -LiteralPath $reference -PathType Leaf)) { return }
    $requirements = Join-Path $Runtime 'requirements-runtime.txt'
    $key = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($key -cne ([string](Get-Content -LiteralPath $reference -Raw)).Trim()) { throw 'La referencia al entorno no coincide con las dependencias.' }
    $parent = Join-Path $Root '.entornos'
    $environment = Join-Path $parent $key
    $python = Join-Path $environment 'Scripts\python.exe'
    $marker = Join-Path $environment 'ubicacion.txt'
    $verify = @'
import importlib.metadata as metadata
import importlib.util
from pathlib import Path
import sys

import OpenGL
import PySide6.QtWidgets

assert sys.version_info[:2] == (3, 12)
assert importlib.util.find_spec('dxcam') is not None
for line in Path(sys.argv[1]).read_text().splitlines():
    if line.strip():
        name, version = line.strip().split('==')
        assert metadata.version(name) == version
'@
    if ((Test-Path -LiteralPath $marker -PathType Leaf) -and
        ([string](Get-Content -LiteralPath $marker -Raw -Encoding UTF8)).Trim() -eq $environment -and
        (Test-Path -LiteralPath $python -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $environment 'Scripts\pythonw.exe') -PathType Leaf)) {
        & $python -B -c $verify $requirements
        if ($LASTEXITCODE -eq 0) { return }
    }
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    $available = $false
    if ($py) {
        & $py.Source -3.12 --version 2>$null
        $available = $LASTEXITCODE -eq 0
    }
    if (!$available) {
        $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
        if (!$winget) { throw 'Se necesita Python 3.12 para Windows con el lanzador py. Instálalo y vuelve a intentarlo.' }
        if ((Read-Host 'Falta Python 3.12. ¿Instalarlo con WinGet? Escribe SI para continuar') -ine 'SI') {
            throw 'Se canceló la instalación de Python 3.12.'
        }
        & $winget.Source install --id Python.Python.3.12 --exact --source winget
        if ($LASTEXITCODE -ne 0) { throw 'WinGet no pudo instalar Python 3.12.' }
        $py = Get-Command py.exe -ErrorAction SilentlyContinue
        if (!$py) { throw 'Python se instaló. Vuelve a abrir el lanzador para cargar la configuración nueva.' }
    }
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    if (Test-Path -LiteralPath $environment) {
        $item = Get-Item -LiteralPath $environment -Force
        if (!$item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
            (Resolve-Path -LiteralPath $environment).Path -ne $environment) { throw 'Ruta de entorno inesperada.' }
        if (!$Seed -and (Test-Path -LiteralPath $python -PathType Leaf)) {
            & $python -B -c $verify $requirements
            if ($LASTEXITCODE -eq 0) {
                # Windows redirectors use pyvenv.cfg. Rewrite the environment paths
                # after a move without copying the installed wheels.
                & $py.Source -3.12 -m venv --without-pip $environment
                if ($LASTEXITCODE -eq 0) {
                    [IO.File]::WriteAllText($marker, $environment)
                    return
                }
                throw 'No se pudo reparar el entorno de Python en su ubicación nueva.'
            }
        }
        $retired = $environment + '.anterior-' + [guid]::NewGuid().ToString('N')
        [IO.Directory]::Move($environment, $retired)
    }
    if ($Seed) {
        & $py.Source -3.12 -m venv --without-pip $environment
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno de Python.' }
        Copy-Item -LiteralPath (Join-Path $Seed 'Lib\site-packages') -Destination (Join-Path $environment 'Lib') -Recurse -Force
    } else {
        & $py.Source -3.12 -m venv $environment
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno de Python.' }
        & $python -m pip install --disable-pip-version-check -r $requirements
        if ($LASTEXITCODE -ne 0) { throw 'Falló la instalación de las dependencias de Cicerón.' }
    }
    & $python -B -c $verify $requirements
    if ($LASTEXITCODE -ne 0) { throw 'El entorno no tiene las versiones requeridas por Cicerón.' }
    [IO.File]::WriteAllText($marker, $environment)
}

function New-CiceronSourceBundle([string]$Repository, [string]$Output, [string]$Root, [string]$Seed) {
    $runtime = Join-Path $Output '_internal'
    $src = Join-Path $Repository 'src'
    $assets = Join-Path $Repository 'assets'
    $extension = Join-Path $Repository 'navegador\extension'
    $before = @(Get-TreeHashes $src -Source; Get-TreeHashes $assets; Get-TreeHashes $extension -Extension)
    New-Item -ItemType Directory -Path $runtime -Force | Out-Null
    Copy-SafeTree -From $src -To (Join-Path $runtime 'src') -SkipTransient
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'ejecutar_fuentes.py') -Destination $runtime
    Copy-SafeTree -From $assets -To (Join-Path $runtime 'assets')
    $birthday = Join-Path $Repository 'paquetes\happy-birthday'
    if (Test-Path -LiteralPath $birthday -PathType Container) {
        $panels = Join-Path $runtime 'paquetes\happy-birthday'
        New-Item -ItemType Directory -Path $panels -Force | Out-Null
        foreach ($file in @('qt_agenda.py','birthdays.py','startup.py','windows_tray.py','icono.ico')) {
            Copy-Item -LiteralPath (Join-Path $birthday $file) -Destination $panels
        }
    }
    Copy-SafeTree -From $extension -To (Join-Path $Output '00 EXTENSION') -SkipTransient -AtRoot
    $requirements = Join-Path $runtime 'requirements-runtime.txt'
    Copy-Item -LiteralPath (Join-Path $Repository 'requirements-runtime.txt') -Destination $requirements
    Set-Content -LiteralPath (Join-Path $runtime 'entorno.txt') -Value ((Get-FileHash -LiteralPath $requirements).Hash.ToLowerInvariant()) -Encoding Ascii
    $after = @(Get-TreeHashes $src -Source; Get-TreeHashes $assets; Get-TreeHashes $extension -Extension)
    $copied = @(Get-TreeHashes (Join-Path $runtime 'src') -Source; Get-TreeHashes (Join-Path $runtime 'assets'); Get-TreeHashes (Join-Path $Output '00 EXTENSION') -Extension)
    if (($before -join "`n") -cne ($after -join "`n") -or ($before -join "`n") -cne ($copied -join "`n")) {
        throw 'La revisión cambió durante la copia. Vuelve a ejecutar Instalar.bat cuando termine la edición o usa una copia aislada.'
    }
    Initialize-CiceronEnvironment $Root $runtime $Seed
    $launcher = Join-Path $PSScriptRoot 'lanzador.cs'
    $icon = Join-Path $runtime 'assets\ciceron.ico'
    $hash = (Get-FileHash -LiteralPath $launcher).Hash + (Get-FileHash -LiteralPath $icon).Hash
    $cache = Join-Path (Join-Path $Root '.entornos') ('lanzador-' + $hash.Substring(0,16) + $hash.Substring(64,16))
    if (!(Test-Path -LiteralPath (Join-Path $cache 'Ciceron.exe') -PathType Leaf) -or
        !(Test-Path -LiteralPath (Join-Path $cache 'CiceronHost.exe') -PathType Leaf)) {
        $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
        if (!(Test-Path -LiteralPath $compiler)) { $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe' }
        if (!(Test-Path -LiteralPath $compiler)) { throw 'No se encontró el compilador de .NET Framework para preparar los lanzadores.' }
        New-Item -ItemType Directory -Path $cache -Force | Out-Null
        foreach ($mode in @('winexe','exe')) {
            $name = if ($mode -eq 'winexe') { 'Ciceron.exe' } else { 'CiceronHost.exe' }
            $exe = Join-Path $cache $name
            & $compiler /nologo /codepage:65001 "/target:$mode" /optimize+ /reference:System.Windows.Forms.dll "/win32icon:$icon" "/out:$exe" $launcher
            if ($LASTEXITCODE -ne 0) { throw 'No se pudo preparar el lanzador de Windows.' }
        }
    }
    foreach ($name in @('Ciceron.exe','CiceronHost.exe')) {
        Copy-Item -LiteralPath (Join-Path $cache $name) -Destination $Output
    }
}
