param(
    [string]$RunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run',
    [string]$NativeRoot = 'HKCU:\Software',
    [string]$InstallDir = '',
    [switch]$Confirmar
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'control_fuentes.ps1')
$repositoryRoot = Split-Path $PSScriptRoot -Parent
if (!$InstallDir) { $InstallDir = Join-Path $repositoryRoot 'Aplicacion' }
$installDir = [IO.Path]::GetFullPath($InstallDir)
$destination = Join-Path $installDir 'Ciceron.exe'
$previousInstallDir = Join-Path $env:LOCALAPPDATA 'Ciceron'
$previousExe = Join-Path $previousInstallDir 'Ciceron.exe'
$legacyInstallDir = Join-Path $env:LOCALAPPDATA 'GanaLaBatalla'
$legacyExe = Join-Path $legacyInstallDir 'Ciceron.exe'
$legacyNamedExe = Join-Path $legacyInstallDir 'GanaLaBatalla.exe'
$menu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$mutex = New-Object System.Threading.Mutex($false, 'Local\CiceronInstalacion')
$locked = $false

function Get-RunExecutable([string]$Value) {
    $command = $Value.Trim()
    if ($command.StartsWith('"')) {
        $end = $command.IndexOf('"', 1)
        if ($end -lt 0) { return $null }
        $target = $command.Substring(1, $end - 1)
    } else {
        $target = ($command -split '\s+', 2)[0]
    }
    return [Environment]::ExpandEnvironmentVariables($target)
}

try {
    try { $locked = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $locked = $true }
    if (!$locked) { throw 'Ya hay una instalación o desinstalación en curso. Espera a que termine.' }
    $ownedPaths = @($destination,$previousExe,$legacyExe,$legacyNamedExe,(Join-Path $installDir 'GanaLaBatalla.exe'))
    $registeredRoot = $null
    $receipt = Join-Path $installDir 'integracion-ciceron.json'
    if (Test-Path -LiteralPath $receipt -PathType Leaf) {
        $record = Get-Content -LiteralPath $receipt -Encoding UTF8 -Raw | ConvertFrom-Json
        if ($record.schema -eq 1 -and $record.root -is [string] -and [IO.Path]::IsPathRooted($record.root)) {
            $registeredRoot = [IO.Path]::GetFullPath($record.root)
            $ownedPaths += Join-Path $registeredRoot 'Ciceron.exe'
        }
    }
    $running = @(Get-Process -Name 'Ciceron','GanaLaBatalla' -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $ownedPaths -contains $_.Path })
    $sourceRunning = Test-CiceronSourceRunning $installDir
    if (!$Confirmar) {
        $question = 'Se quitarán Cicerón y su inicio automático. La configuración personal se conservará.'
        if ($running.Count -gt 0 -or $sourceRunning) { $question += ' Se cerrará la aplicación y se perderán los cambios no guardados.' }
        $answer = Read-Host ($question + ' Escribe SI para continuar')
        if ($answer -cne 'SI') { Write-Host 'Desinstalación cancelada.'; exit 0 }
    }
    if ($sourceRunning) { Stop-CiceronSource $installDir }
    foreach ($process in $running) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
    foreach ($process in $running) { try { $process.WaitForExit(5000) | Out-Null } catch [System.InvalidOperationException] { } }
    $remaining = @(Get-Process -Name 'Ciceron','GanaLaBatalla' -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $ownedPaths -contains $_.Path })
    if ($remaining.Count -gt 0) { throw 'No se pudo cerrar Cicerón; sus archivos y el inicio automático se conservan' }
    if (Test-Path -LiteralPath $RunKey) {
        foreach ($runName in @('Ciceron','GanaLaBatalla')) {
            $entry = Get-ItemProperty -LiteralPath $RunKey -Name $runName -ErrorAction SilentlyContinue
            if ($null -ne $entry) {
                $value = $entry.$runName
                if ($value -is [string]) {
                    $target = Get-RunExecutable $value
                    if ($target -in $ownedPaths) { Remove-ItemProperty -LiteralPath $RunKey -Name $runName }
                    else { Write-Warning "Se conservó la entrada $runName porque apunta a otro programa." }
                } else { Write-Warning "Se conservó la entrada $runName porque tiene un formato desconocido." }
            }
        }
    }
    $shell = New-Object -ComObject WScript.Shell
    foreach ($name in @('Cicerón.lnk','Mi centro.lnk','Gana la batalla.lnk')) {
        $link = Join-Path $menu $name
        if (Test-Path -LiteralPath $link) {
            $target = $shell.CreateShortcut($link).TargetPath
            if ($target -in $ownedPaths) { Remove-Item -LiteralPath $link -Force }
            else { Write-Warning "Se conservó el acceso $name porque apunta a otro programa." }
        }
    }
    $libraryLinks = Join-Path $menu 'Ciceron'
    $libraryDir = Get-Item -LiteralPath $libraryLinks -ErrorAction SilentlyContinue
    if ($libraryDir -and $libraryDir.PSIsContainer -and !($libraryDir.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        . (Join-Path $PSScriptRoot 'accesos_inicio.ps1')
        foreach ($tool in $builtInTools) {
            $names = @((Get-CiceronToolShortcuts $tool).Name) + $tool.OldName
            foreach ($name in $names) {
                $toolLink = Join-Path $libraryLinks ($name + '.lnk')
                if (Test-OwnedCiceronToolShortcut $shell $toolLink $tool.Id) {
                    Remove-Item -LiteralPath $toolLink -Force
                }
            }
        }
        foreach ($file in Get-ChildItem -LiteralPath $libraryLinks -Filter '*.lnk' -File) {
            if (!($file.Attributes -band [IO.FileAttributes]::ReparsePoint) -and
                $shell.CreateShortcut($file.FullName).Description -cmatch '^Ciceron\.Library:[0-9a-f]{16} ') {
                Remove-Item -LiteralPath $file.FullName -Force
            }
        }
        if (!(Get-ChildItem -LiteralPath $libraryLinks -Force | Select-Object -First 1)) {
            Remove-Item -LiteralPath $libraryLinks
        }
    }
    $manifest = Join-Path $installDir 'ciceron-native-host.json'
    $previousManifest = Join-Path $previousInstallDir 'ciceron-native-host.json'
    $legacyManifest = Join-Path $legacyInstallDir 'ciceron-native-host.json'
    $registeredManifest = if ($registeredRoot) { Join-Path $registeredRoot 'ciceron-native-host.json' }
    foreach ($vendor in @('Google\Chrome','Microsoft\Edge')) {
        $key = $NativeRoot + '\' + $vendor + '\NativeMessagingHosts\com.ciceron.browser'
        if (Test-Path -LiteralPath $key) {
            $item = Get-Item -LiteralPath $key
            $registered = $item.GetValue('')
            if ($registered -and $registered -in @($manifest,$previousManifest,$legacyManifest,$registeredManifest)) {
                if (!$key.StartsWith('HKCU:\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Raíz del Registro no compatible.' }
                $writable=[Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($key.Substring(6),$true)
                try { $writable.DeleteValue('', $false); $empty=$writable.GetValueNames().Count -eq 0 -and $writable.GetSubKeyNames().Count -eq 0 } finally { $writable.Dispose() }
                if ($empty) { Remove-Item -LiteralPath $key -Force }
            } else { Write-Warning 'Se conservó un registro de navegador que apunta a otro puente.' }
        }
    }
    $installRoots = @($installDir,$previousInstallDir,$legacyInstallDir)
    $hosts = @(Get-Process -Name 'CiceronHost-*' -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $installRoots -contains (Split-Path -Parent $_.Path) -and (Split-Path -Leaf $_.Path) -match '^CiceronHost-[0-9a-f]{16}\.exe$' })
    foreach ($process in $hosts) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
    foreach ($process in $hosts) { try { $process.WaitForExit(5000) | Out-Null } catch [System.InvalidOperationException] { } }
    foreach ($root in $installRoots) {
      foreach ($file in @(Get-ChildItem -LiteralPath $root -Filter 'CiceronHost-*.exe' -File -ErrorAction SilentlyContinue)) {
        if ($file.Name -match '^CiceronHost-[0-9a-f]{16}\.exe$') { Remove-Item -LiteralPath $file.FullName -Force }
      }
    }
    foreach ($manifestPath in @($manifest,$previousManifest,$legacyManifest)) {
      if (Test-Path -LiteralPath $manifestPath) {
        try { $data=Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $data=$null }
        if ($data.name -eq 'com.ciceron.browser' -and @($data.allowed_origins).Count -eq 1 -and @($data.allowed_origins)[0] -eq 'chrome-extension://cmbcmfhajdjlcepmkhjnfooadbccljpk/') { Remove-Item -LiteralPath $manifestPath -Force }
        else { Write-Warning "Se conservó el manifiesto de navegador desconocido: $manifestPath" }
      }
    }
    foreach ($root in $installRoots) {
      foreach ($path in @((Join-Path $root 'extension-path.txt'),(Join-Path $root 'Ciceron.exe'),(Join-Path $root 'GanaLaBatalla.exe'),(Join-Path $root 'Ciceron.instalando.tmp'),(Join-Path $root 'Ciceron.respaldo.tmp'))) {
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
      }
    }
    foreach ($root in $installRoots) { if ((Test-Path -LiteralPath $root) -and @(Get-ChildItem -LiteralPath $root -Force).Count -eq 0) { Remove-Item -LiteralPath $root -Force } }
    Write-Host 'Cicerón está desinstalado. Se conservó la configuración personal y la extensión cargada; puedes quitarla desde el navegador.'
} catch {
    Write-Host "No se pudo completar la desinstalación: $($_.Exception.Message). Puedes volver a ejecutar Desinstalar.bat."
    exit 1
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
