param(
    [string]$RunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run',
    [switch]$NoLaunch,
    [switch]$SkipBrowser
)
$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'GanaLaBatalla.exe'
$installDir = Join-Path $env:LOCALAPPDATA 'GanaLaBatalla'
$destination = Join-Path $installDir 'Ciceron.exe'
$legacyExe = Join-Path $installDir 'GanaLaBatalla.exe'
$stage = Join-Path $installDir 'Ciceron.instalando.tmp'
$backup = Join-Path $installDir 'Ciceron.respaldo.tmp'
$menu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$link = Join-Path $menu 'Mi centro.lnk'
$oldRun = $null; $oldRaw = $null; $oldKind = $null; $hadRun = $false; $runChanged = $false; $changedExe = $false; $tempLink = $null
$hadExe = $false
$mutex = New-Object System.Threading.Mutex($false, 'Local\CiceronInstalacion')
$locked = $false
try {
    try { $locked = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $locked = $true }
    if (!$locked) { throw 'Ya hay una instalación o desinstalación en curso. Espera a que termine.' }
    $hadExe = Test-Path -LiteralPath $destination
    if (!(Test-Path -LiteralPath $source -PathType Leaf)) { throw 'No se encuentra el ejecutable junto al instalador.' }
    if (!(Test-Path -LiteralPath $RunKey)) { throw 'No se encuentra la clave de inicio de Windows.' }
    try { $oldRun = (Get-ItemProperty -LiteralPath $RunKey -Name GanaLaBatalla -ErrorAction Stop).GanaLaBatalla; $hadRun = $true }
    catch [System.Management.Automation.PSArgumentException] { }
    if ($hadRun) {
        $registryKey = Get-Item -LiteralPath $RunKey
        $oldKind = $registryKey.GetValueKind('GanaLaBatalla')
        $oldRaw = $registryKey.GetValue('GanaLaBatalla', $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        if ($oldRun -isnot [string]) { throw 'La entrada GanaLaBatalla tiene un formato inesperado. No se ha modificado.' }
        $runTarget = $oldRun.Trim().Trim('"')
        if ($runTarget -ne $destination -and $runTarget -ne $legacyExe) { throw 'La entrada GanaLaBatalla del inicio apunta a otro programa. No se ha modificado.' }
    }
    $shell = New-Object -ComObject WScript.Shell
    if (Test-Path -LiteralPath $link) {
        $currentTarget = $shell.CreateShortcut($link).TargetPath
        if ($currentTarget -ne $destination -and $currentTarget -ne $legacyExe) { throw 'El acceso Mi centro ya pertenece a otra aplicación. No se ha modificado.' }
    }
    $alreadyInstalled = $hadExe -or (Test-Path -LiteralPath $legacyExe)
    $running = @(Get-Process -Name 'Ciceron','GanaLaBatalla' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $destination -or $_.Path -eq $legacyExe })
    if ($running.Count -gt 0) {
        $answer = Read-Host 'Para instalar o reinstalar, hay que cerrar Cicerón. Los cambios no guardados se perderán. Escribe SI para continuar'
        if ($answer -cne 'SI') { Write-Host 'Instalación cancelada; no se realizaron cambios.'; exit 0 }
    }
    New-Item -ItemType Directory -Force -Path $installDir,$menu | Out-Null
    if (Test-Path -LiteralPath $backup) { throw "Existe una copia de recuperación pendiente en $backup. No se sobrescribirá." }
    $tempLink = Join-Path $menu ('.Ciceron-' + [guid]::NewGuid().ToString('N') + '.lnk')
    $shortcut = $shell.CreateShortcut($tempLink)
    $shortcut.TargetPath = $destination; $shortcut.Arguments = '--abrir'; $shortcut.IconLocation = $destination + ',0'; $shortcut.WorkingDirectory = $installDir
    $shortcut.Save()
    Copy-Item -LiteralPath $source -Destination $stage -Force
    if ((Get-FileHash -LiteralPath $source).Hash -ne (Get-FileHash -LiteralPath $stage).Hash) { throw 'La copia de preparación no coincide con el original.' }
    if ($running.Count -gt 0) {
        foreach ($process in $running) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
        foreach ($process in $running) { try { $process.WaitForExit(5000) | Out-Null } catch [System.InvalidOperationException] { } }
        $remaining = @(Get-Process -Name 'Ciceron','GanaLaBatalla' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $destination -or $_.Path -eq $legacyExe })
        if ($remaining.Count -gt 0) { throw 'No se pudo cerrar Cicerón. Ciérralo y vuelve a intentarlo.' }
    }
    if ($hadExe) { [System.IO.File]::Replace($stage, $destination, $backup, $true) }
    else { Move-Item -LiteralPath $stage -Destination $destination }
    $changedExe = $true

    # Reject a concurrent change rather than overwrite another program's entry.
    $currentEntry = Get-ItemProperty -LiteralPath $RunKey -Name GanaLaBatalla -ErrorAction SilentlyContinue
    if ($hadRun) {
        if ($null -eq $currentEntry) { throw 'La entrada de inicio cambió durante la instalación; inténtalo de nuevo.' }
        $currentKey = Get-Item -LiteralPath $RunKey
        $currentRaw = $currentKey.GetValue('GanaLaBatalla', $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        if ($currentRaw -cne $oldRaw -or $currentKey.GetValueKind('GanaLaBatalla') -ne $oldKind) { throw 'La entrada de inicio cambió durante la instalación; inténtalo de nuevo.' }
    } elseif ($null -ne $currentEntry) { throw 'La entrada de inicio cambió durante la instalación; inténtalo de nuevo.' }
    # Repeated installations preserve a previously disabled startup preference.
    if ($hadRun -or !$alreadyInstalled) {
        New-ItemProperty -LiteralPath $RunKey -Name GanaLaBatalla -Value ('"' + $destination + '"') -PropertyType String -Force | Out-Null
        $runChanged = $true
    }
    Move-Item -LiteralPath $tempLink -Destination $link -Force
    if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Force }
    Write-Host 'Cicerón está instalado. Se conservó la configuración y la preferencia de inicio.'
    if ($RunKey -eq 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run') {
        try {
            $graphicsKey = 'HKCU:\Software\Microsoft\DirectX\UserGpuPreferences'
            if (!(Test-Path -LiteralPath $graphicsKey)) {
                New-Item -Path $graphicsKey -Force | Out-Null
            }
            $graphics = Get-Item -LiteralPath $graphicsKey
            if ($null -eq $graphics.GetValue($destination)) {
                New-ItemProperty -LiteralPath $graphicsKey -Name $destination -Value 'GpuPreference=2;' -PropertyType String | Out-Null
            }
        } catch { Write-Warning "Windows no pudo guardar la preferencia de GPU de Cicerón: $($_.Exception.Message)" }
    }
    $browserInstaller=Join-Path $PSScriptRoot 'instalar_navegador.ps1'
    if (!$SkipBrowser -and (Test-Path -LiteralPath $browserInstaller)) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $browserInstaller -PackageRoot (Split-Path $PSScriptRoot -Parent) -InstallDir $installDir
        if ($LASTEXITCODE -ne 0) { Write-Warning 'La aplicación está instalada, pero la integración del navegador quedó pendiente. Revisa el mensaje anterior o usa Preparar navegador en Cicerón.' }
    } elseif (!$SkipBrowser) { Write-Warning 'El paquete no incluye la preparación del navegador.' }
    if (!$NoLaunch) {
        try { Start-Process -FilePath $destination -ArgumentList '--abrir' -WindowStyle Normal } catch { Write-Warning "La instalación terminó, pero no se pudo abrir automáticamente: $($_.Exception.Message)" }
    }
} catch {
    $problem = $_.Exception.Message
    if ($runChanged) {
        try {
            $currentEntry = Get-ItemProperty -LiteralPath $RunKey -Name GanaLaBatalla -ErrorAction SilentlyContinue
            if ($null -eq $currentEntry -or $currentEntry.GanaLaBatalla -cne ('"' + $destination + '"')) { throw 'La entrada cambió de nuevo y no se sobrescribió.' }
            if ($hadRun) { New-ItemProperty -LiteralPath $RunKey -Name GanaLaBatalla -Value $oldRaw -PropertyType $oldKind.ToString() -Force | Out-Null }
            else { Remove-ItemProperty -LiteralPath $RunKey -Name GanaLaBatalla -ErrorAction SilentlyContinue }
        } catch { $problem += " No se pudo restaurar la entrada de inicio: $($_.Exception.Message)" }
    }
    if ($changedExe) {
        try {
            if ($hadExe -and (Test-Path -LiteralPath $backup)) { [System.IO.File]::Copy($backup, $destination, $true); Remove-Item -LiteralPath $backup -Force }
            elseif (!$hadExe) { Remove-Item -LiteralPath $destination -Force -ErrorAction SilentlyContinue }
        } catch { $problem += " No se pudo restaurar el ejecutable anterior: $($_.Exception.Message)" }
    }
    Write-Host "No se pudo completar la instalación: $problem"
    exit 1
} finally {
    if ($locked -and (Test-Path -LiteralPath $stage)) { Remove-Item -LiteralPath $stage -Force -ErrorAction SilentlyContinue }
    if ($tempLink -and (Test-Path -LiteralPath $tempLink)) { Remove-Item -LiteralPath $tempLink -Force -ErrorAction SilentlyContinue }
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
