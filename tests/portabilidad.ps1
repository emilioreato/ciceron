$ErrorActionPreference = 'Stop'
$root = Join-Path $PSScriptRoot '.portabilidad-temporal'
$registry = 'HKCU:\Software\CiceronPruebaCodex_Portabilidad'
$run = $registry + '\Run'
$native = $registry + '\Nativo'
if ((Test-Path -LiteralPath $root) -or (Test-Path -LiteralPath $registry)) { throw 'La ubicación temporal ya existe.' }
try {
    $package = Join-Path $root 'paquete'
    $internal = Join-Path $package 'internos'
    $bundle = Join-Path $internal 'Ciceron'
    $runtime = Join-Path $bundle '_internal'
    $profile = Join-Path $root 'primera ruta\Aplicacion'
    $program = Join-Path $root 'programas'
    $chrome = Join-Path $program 'Google\Chrome\Application'
    $appdata = Join-Path $root 'Windows'
    $local = Join-Path $root 'Local'
    New-Item -ItemType Directory -Force -Path $runtime,$chrome,$appdata,$local,(Join-Path $package 'navegador') | Out-Null
    foreach ($name in @('instalar.ps1','instalar_navegador.ps1','accesos_inicio.ps1','propiedades_acceso.cs',
                        'preparar_fuentes.ps1','control_fuentes.ps1',
                        'Reparar integracion.bat','Recuperar version anterior.bat','formato-datos.txt')) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot "..\internos\$name") -Destination $internal
    }
    $extension = Join-Path $package 'navegador\extension'
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot '..\navegador\extension') -Destination $extension -Recurse
    [IO.File]::WriteAllText((Join-Path $chrome 'chrome.exe'), 'simulado')
    $env:APPDATA=$appdata; $env:LOCALAPPDATA=$local
    $env:ProgramFiles=$program; ${env:ProgramFiles(x86)}=$program
    New-Item -Path $run,$native -Force | Out-Null
    New-ItemProperty -LiteralPath $run -Name Ajeno -Value 'C:\Otro\app.exe' | Out-Null
    $installer = Join-Path $internal 'instalar.ps1'
    $exeSource = Join-Path $bundle 'Ciceron.exe'
    $dllSource = Join-Path $runtime 'base_library.zip'
    $hostSource = Join-Path $internal 'CiceronHost.exe'
    $formatSource = Join-Path $internal 'formato-datos.txt'
    $popup = Join-Path $extension 'popup.js'
    function Write-Version([string]$Version) {
        [IO.File]::WriteAllText($exeSource, "exe-$Version")
        [IO.File]::WriteAllText($dllSource, "runtime-$Version")
        [IO.File]::WriteAllText($hostSource, "host-$Version")
        [IO.File]::WriteAllText($popup, "// popup-$Version")
        [IO.File]::WriteAllText($formatSource, $Version)
    }
    function Invoke-Install([string]$Script, [string]$Directory, [string[]]$Flags) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Script -InstallDir $Directory -RunKey $run -NativeRoot $native -NoLaunch @Flags
        if ($LASTEXITCODE -ne 0) { throw "Falló el instalador: $LASTEXITCODE ($Flags)" }
    }
    Write-Version '1'
    Invoke-Install $installer $profile
    if (!(Test-Path -LiteralPath (Join-Path $profile 'Reparar integracion.bat'))) { throw 'Falta el comando portable.' }
    $data = Join-Path $profile 'datos'
    New-Item -ItemType Directory -Path $data -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $data 'config.json'), '{"nota":"previa"}')
    $paths = @{
        exe='Ciceron.exe'; runtime='_internal\base_library.zip'; popup='00 EXTENSION\popup.js'
        manifest='ciceron-native-host.json'; integration='integracion\instalar.ps1'
    }
    Write-Version '2'
    Invoke-Install $installer $profile
    $previous = Join-Path $profile 'version-anterior'
    if ((Get-Content -LiteralPath (Join-Path $previous $paths.exe) -Raw) -ne 'exe-1' -or
        (Get-Content -LiteralPath (Join-Path $previous $paths.runtime) -Raw) -ne 'runtime-1' -or
        (Get-Content -LiteralPath (Join-Path $previous 'CiceronHost.exe') -Raw) -ne 'host-1' -or
        (Get-Content -LiteralPath (Join-Path $previous $paths.popup) -Raw) -ne '// popup-1') {
        throw 'El respaldo no contiene el conjunto anterior completo.'
    }
    Invoke-Install $installer $profile
    if ((Get-Content -LiteralPath (Join-Path $previous $paths.exe) -Raw) -ne 'exe-1') { throw 'Una reparación idéntica perdió la versión anterior.' }
    $snapshots = @(Get-ChildItem -LiteralPath $profile -Directory -Filter 'datos-antes-de-actualizar-*')
    if ($snapshots.Count -ne 1 -or (Get-Content -LiteralPath (Join-Path $snapshots[0].FullName 'config.json') -Raw) -ne '{"nota":"previa"}') {
        throw 'Falta el respaldo previo al cambio de formato.'
    }
    [IO.File]::WriteAllText((Join-Path $data 'config.json'), '{"nota":"cambio posterior"}')
    $menu = Join-Path $appdata 'Microsoft\Windows\Start Menu\Programs'
    $library = Join-Path $menu 'Ciceron'
    $external = Join-Path $root 'Aplicacion ajena\otro.exe'
    New-Item -ItemType Directory -Path (Split-Path -Parent $external) | Out-Null
    [IO.File]::WriteAllText($external, 'ajeno')
    $shell = New-Object -ComObject WScript.Shell
    $externalLink = Join-Path $library 'Externo.lnk'
    $link = $shell.CreateShortcut($externalLink)
    $link.TargetPath = $external; $link.Description = 'Ciceron.Library:0123456789abcdef externo'; $link.Save()
    $portableFile = Join-Path $profile 'tools\mini.exe'
    New-Item -ItemType Directory -Path (Split-Path -Parent $portableFile) | Out-Null
    [IO.File]::WriteAllText($portableFile, 'portable')
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $digest = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes('portable:tools/mini.exe'))).Replace('-','').ToLowerInvariant().Substring(0,16)
    } finally { $sha.Dispose() }
    $portableLink = Join-Path $library 'Local.lnk'
    $link = $shell.CreateShortcut($portableLink)
    $link.TargetPath = $portableFile; $link.Description = "Ciceron.Library:$digest local"; $link.Save()
    $nativeKey = $native + '\Google\Chrome\NativeMessagingHosts\com.ciceron.browser'
    $alienKey = $native + '\Microsoft\Edge\NativeMessagingHosts\com.ciceron.browser'
    New-Item -Path $alienKey -Force | Out-Null
    Set-Item -LiteralPath $alienKey -Value 'C:\Ajeno\ciceron-native-host.json'
    New-ItemProperty -LiteralPath $nativeKey -Name OtroValor -Value 'conservar' | Out-Null
    $moved = Join-Path $root 'carpeta nueva con espacios\Ciceron portable'
    New-Item -ItemType Directory -Path (Split-Path -Parent $moved) | Out-Null
    if ((Resolve-Path -LiteralPath $profile).Path -ne $profile -or !$moved.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Ruta de prueba inesperada.' }
    [IO.Directory]::Move($profile, $moved)
    $portableInstaller = Join-Path $moved $paths.integration
    Invoke-Install $portableInstaller $moved @('-Reparar')
    $dest = Join-Path $moved 'Ciceron.exe'
    $manifest = Join-Path $moved $paths.manifest
    if ((Get-ItemProperty -LiteralPath $run).Ciceron -ne ('"' + $dest + '" --inicio-silencioso') -or
        (Get-ItemProperty -LiteralPath $run).Ajeno -ne 'C:\Otro\app.exe' -or
        (Get-Item -LiteralPath $nativeKey).GetValue('') -ne $manifest -or
        (Get-Item -LiteralPath $alienKey).GetValue('') -ne 'C:\Ajeno\ciceron-native-host.json' -or
        (Get-ItemProperty -LiteralPath $nativeKey).OtroValor -ne 'conservar' -or
        $shell.CreateShortcut($externalLink).TargetPath -ne $external -or
        $shell.CreateShortcut($portableLink).TargetPath -ne (Join-Path $moved 'tools\mini.exe') -or
        (Get-Content -LiteralPath $dest -Raw) -ne 'exe-2' -or
        (Get-Content -LiteralPath (Join-Path $moved 'datos\config.json') -Raw) -ne '{"nota":"cambio posterior"}') {
        throw 'La reparación movió un acceso ajeno, perdió datos o no rehizo la integración.'
    }
    Remove-ItemProperty -LiteralPath $run -Name Ciceron
    Invoke-Install $portableInstaller $moved @('-Reparar')
    if ($null -ne (Get-ItemProperty -LiteralPath $run -Name Ciceron -ErrorAction SilentlyContinue)) { throw 'Se reactivó el arranque automático.' }
    $previousRuntime = Join-Path (Join-Path $moved 'version-anterior') $paths.runtime
    [IO.File]::WriteAllText($previousRuntime, 'dañado')
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $portableInstaller -InstallDir $moved -RunKey $run -NativeRoot $native -NoLaunch -Recuperar
    if ($LASTEXITCODE -eq 0 -or (Get-Content -LiteralPath $dest -Raw) -ne 'exe-2') { throw 'Se recuperó una copia dañada.' }
    [IO.File]::WriteAllText($previousRuntime, 'runtime-1')
    Invoke-Install $portableInstaller $moved @('-Recuperar')
    $activeHost = (Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json).path
    if ((Get-Content -LiteralPath $dest -Raw) -ne 'exe-1' -or
        (Get-Content -LiteralPath (Join-Path $moved $paths.runtime) -Raw) -ne 'runtime-1' -or
        (Get-Content -LiteralPath $activeHost -Raw) -ne 'host-1' -or
        (Get-Content -LiteralPath (Join-Path $moved $paths.popup) -Raw) -ne '// popup-1' -or
        (Get-Content -LiteralPath (Join-Path $moved 'datos\config.json') -Raw) -ne '{"nota":"cambio posterior"}') {
        throw 'La recuperación no recuperó el conjunto anterior o revirtió datos actuales.'
    }
    Write-Host 'Portabilidad: reparación, recuperación completa y respaldo de formato verificados.'
} finally {
    if (Test-Path -LiteralPath $registry) { Remove-Item -LiteralPath $registry -Recurse -Force }
    if (Test-Path -LiteralPath $root) {
        $resolved = (Resolve-Path -LiteralPath $root).Path
        if ($resolved -ne $root) { throw 'Ruta temporal inesperada.' }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
