$ErrorActionPreference = 'Stop'
$repository = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$root = Join-Path ([IO.Path]::GetTempPath()) ('Ciceron-prueba-' + [guid]::NewGuid().ToString('N').Substring(0,8))
$fixture = Join-Path $root 'repo'
$profile = Join-Path $fixture 'diario'
$key = 'HKCU:\Software\CiceronPruebaFuentes-' + [guid]::NewGuid().ToString('N')
$run = $key + '\Run'
$native = $key + '\Native'
$seed = Join-Path $repository '.venv'
$env:APPDATA = Join-Path $root 'appdata'
$env:LOCALAPPDATA = Join-Path $root 'local'
$fakePrograms = Join-Path $root 'programas'
$env:ProgramFiles = $fakePrograms
${env:ProgramFiles(x86)} = $env:ProgramFiles
$env:QT_QPA_PLATFORM = 'offscreen'
$env:CICERON_DEV = '1'

function Install([string[]]$Flags) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer -InstallDir $profile -RunKey $run -NativeRoot $native -NoLaunch @Flags
    if ($LASTEXITCODE -ne 0) { throw "Fallo instalacion ($Flags)." }
}

function Start-TestCenter {
    $launcher = Join-Path $profile 'Ciceron.exe'
    $process = Start-Process -FilePath $launcher -ArgumentList '--inicio-silencioso' -WindowStyle Hidden -PassThru
    if (!$process.WaitForExit(8000) -or $process.ExitCode -ne 0) { throw 'Fallo el lanzador diario.' }
    for ($attempt = 0; $attempt -lt 80; $attempt++) {
        if (Test-CiceronSourceRunning $profile) { return }
        Start-Sleep -Milliseconds 100
    }
    throw 'El centro diario no abrio.'
}

New-Item -ItemType Directory -Path (Join-Path $fixture 'internos'),(Join-Path $fixture 'navegador') | Out-Null
. (Join-Path $repository 'internos\control_fuentes.ps1')
try {
    foreach ($name in @('src','assets','requirements-runtime.txt')) {
        Copy-Item -LiteralPath (Join-Path $repository $name) -Destination $fixture -Recurse
    }
    Copy-Item -LiteralPath (Join-Path $repository 'navegador\extension') -Destination (Join-Path $fixture 'navegador') -Recurse
    Get-ChildItem -LiteralPath (Join-Path $repository 'internos') -File |
        Where-Object { $_.Extension -in '.cs','.ps1','.bat','.txt','.py' } |
        Copy-Item -Destination (Join-Path $fixture 'internos')
    $paths = Join-Path $fixture 'src\app_paths.py'
    Add-Content -LiteralPath $paths -Encoding UTF8 -Value ("`r`ndef instance_suffix(): return '_" + [guid]::NewGuid().ToString('N') + "'")
    $installer = Join-Path $fixture 'internos\instalar.ps1'
    $chrome = Join-Path $fakePrograms 'Google\Chrome\Application'
    New-Item -ItemType Directory -Path $chrome -Force | Out-Null
    $fakeBrowser = Join-Path $chrome 'chrome.exe'
    if (Test-Path -LiteralPath $fakeBrowser) { throw 'El navegador simulado ya existe.' }
    [IO.File]::WriteAllText($fakeBrowser, 'fixture')
    New-Item -Path $run,$native -Force | Out-Null
    New-ItemProperty -LiteralPath $run -Name Ajeno -Value 'C:\Otro\app.exe' | Out-Null
    Install @('-PreferirFuentes','-SemillaPython',$seed,'-FuentesVivas')
    $data = Join-Path $profile 'datos'
    New-Item -ItemType Directory -Path $data -Force | Out-Null
    $saved = Join-Path $data 'prueba.txt'
    [IO.File]::WriteAllText($saved, 'datos propios')
    $entry = '_internal\src\ciceron.pyw'
    $first = (Get-FileHash -LiteralPath (Join-Path $profile $entry)).Hash
    Start-TestCenter
    $liveEntry = Join-Path $fixture 'src\ciceron.pyw'
    $baseline = [IO.File]::ReadAllText($liveEntry)
    $marker = Join-Path $fixture 'recarga.txt'
    $source = $baseline.Replace("if __name__=='__main__':", "Path(r'$marker').write_text('recarga')`r`nif __name__=='__main__':")
    if ($source -eq $baseline) { throw 'No se preparó el indicador de recarga.' }
    Start-Sleep -Milliseconds 750
    $reloadTime = [Diagnostics.Stopwatch]::StartNew()
    [IO.File]::WriteAllText($liveEntry + '.tmp', $source)
    [IO.File]::Replace($liveEntry + '.tmp', $liveEntry, ($liveEntry + '.original'))
    for ($i = 0; $i -lt 100 -and !(Test-Path -LiteralPath $marker); $i++) { Start-Sleep -Milliseconds 100 }
    if (!(Test-Path -LiteralPath $marker)) { throw 'No se aplicó automáticamente la edición del repositorio.' }
    for ($i = 0; $i -lt 100 -and !(Test-CiceronSourceRunning $profile); $i++) { Start-Sleep -Milliseconds 100 }
    if (!(Test-CiceronSourceRunning $profile)) { throw 'La recarga no dejó una instancia activa.' }
    Write-Host "Fuentes vivas: nueva instancia activa en $($reloadTime.ElapsedMilliseconds) ms."
    Start-Sleep -Milliseconds 750
    [IO.File]::WriteAllText($liveEntry, $baseline + "`r`ndef sintaxis rota(`r`n")
    Start-Sleep -Milliseconds 1200
    if (!(Test-CiceronSourceRunning $profile)) { throw 'Un error de sintaxis cerró el centro.' }
    $broken = $baseline.Replace("if __name__=='__main__':", "raise RuntimeError('prueba de respaldo')`r`nif __name__=='__main__':")
    $errorLog = Join-Path $data 'recarga-error.log'
    [IO.File]::WriteAllText($liveEntry, $broken)
    for ($i = 0; $i -lt 100 -and !(Test-Path -LiteralPath $errorLog); $i++) { Start-Sleep -Milliseconds 100 }
    if (!(Test-Path -LiteralPath $errorLog) -or [IO.File]::ReadAllText($errorLog) -notlike '*prueba de respaldo*') {
        throw 'El error de arranque desde el repositorio no quedó registrado.'
    }
    for ($i = 0; $i -lt 100 -and !(Test-CiceronSourceRunning $profile); $i++) { Start-Sleep -Milliseconds 100 }
    if (!(Test-CiceronSourceRunning $profile)) { throw 'No se abrió la copia estable.' }
    Start-Sleep -Milliseconds 750
    [IO.File]::WriteAllText($liveEntry, $source.Replace("'recarga'", "'reparado'"))
    for ($i = 0; $i -lt 100 -and [IO.File]::ReadAllText($marker) -ne 'reparado'; $i++) { Start-Sleep -Milliseconds 100 }
    if ([IO.File]::ReadAllText($marker) -ne 'reparado') { throw 'La copia estable no regresó al código corregido.' }
    for ($i = 0; $i -lt 100 -and !(Test-CiceronSourceRunning $profile); $i++) { Start-Sleep -Milliseconds 100 }
    Stop-CiceronSource $profile
    [IO.File]::WriteAllText($liveEntry, $baseline)
    Add-Content -LiteralPath (Join-Path $fixture 'src\ciceron.pyw') -Value '# revision de prueba'
    Install @('-PreferirFuentes','-CloseRunning')
    if ((Test-CiceronSourceRunning $profile) -or (Get-FileHash -LiteralPath (Join-Path $profile $entry)).Hash -eq $first) {
        throw 'No se cerro el centro o no se activo el codigo nuevo.'
    }
    Install @('-PreferirFuentes')
    Install @('-Recuperar')
    if ((Get-FileHash -LiteralPath (Join-Path $profile $entry)).Hash -ne $first) { throw 'No se recupero el codigo anterior.' }
    $moved = Join-Path $root 'con espacios'
    [IO.Directory]::Move($profile, $moved)
    $profile = $moved
    $installer = Join-Path $profile 'integracion\instalar.ps1'
    Install @('-Reparar')
    $launcher = Join-Path $profile 'Ciceron.exe'
    if ((Get-ItemProperty -LiteralPath $run).Ciceron -notlike ('"*' + $launcher + '" *')) { throw 'Inicio apunta a la ubicacion anterior.' }
    $manifest = Get-Content -LiteralPath (Join-Path $profile 'ciceron-native-host.json') -Raw | ConvertFrom-Json
    if (!(Test-Path -LiteralPath $manifest.path) -or (Split-Path -Parent $manifest.path) -ne $profile) {
        throw 'El puente no se registro en la ubicacion nueva.'
    }
    @'
import json, struct, subprocess, sys
payload = json.dumps({"type": "hello", "browser": "Chrome"}).encode()
bridge = subprocess.run([sys.argv[1]], input=struct.pack("<I", len(payload)) + payload,
                        capture_output=True, timeout=10, check=True)
length, = struct.unpack("<I", bridge.stdout[:4])
assert json.loads(bridge.stdout[4:4+length]), bridge.stderr
'@ | & (Join-Path $seed 'Scripts\python.exe') - $manifest.path
    if ($LASTEXITCODE -ne 0) { throw 'Fallo el intercambio nativo por stdio.' }
    Start-TestCenter
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $profile 'integracion\desinstalar.ps1') -InstallDir $profile -RunKey $run -NativeRoot $native -Confirmar
    if ($LASTEXITCODE -ne 0 -or (Test-CiceronSourceRunning $profile) -or (Test-Path -LiteralPath $launcher) -or
        [IO.File]::ReadAllText((Join-Path $profile 'datos\prueba.txt')) -ne 'datos propios' -or
        (Get-ItemProperty -LiteralPath $run).Ajeno -ne 'C:\Otro\app.exe') { throw 'La desinstalacion no conservo los datos o entradas ajenas.' }
    Write-Host 'Fuentes: instalacion, inicio, actualizacion, recuperacion, traslado, puente y desinstalacion verificados.'
} finally {
    Stop-CiceronSource $profile
    if (Test-Path -LiteralPath $key) { Remove-Item -LiteralPath $key -Recurse -Force }
    Write-Host "Perfil de prueba: $root"
}
