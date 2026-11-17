param(
    [string]$RunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run',
    [switch]$NoLaunch,
    [switch]$SkipBrowser,
    [switch]$CloseRunning
)
$ErrorActionPreference = 'Stop'
$bundle = Join-Path $PSScriptRoot 'Ciceron'
$source = Join-Path $bundle 'Ciceron.exe'
$sourceRuntime = Join-Path $bundle '_internal'
$installDir = Join-Path $env:LOCALAPPDATA 'Ciceron'
$destination = Join-Path $installDir 'Ciceron.exe'
$legacyInstallDir = Join-Path $env:LOCALAPPDATA 'GanaLaBatalla'
$legacyExe = Join-Path $legacyInstallDir 'Ciceron.exe'
$legacyNamedExe = Join-Path $legacyInstallDir 'GanaLaBatalla.exe'
$legacyDataDir = Join-Path $env:APPDATA 'GanaLaBatalla'
$dataDir = Join-Path $env:APPDATA 'Ciceron'
$stage = Join-Path $installDir 'Ciceron.instalando.tmp'
$backup = Join-Path $installDir 'Ciceron.respaldo.tmp'
$runtime = Join-Path $installDir '_internal'
$runtimeBackup = Join-Path $installDir '_internal.respaldo'
$runtimeStage = Join-Path $installDir ('.runtime-' + [guid]::NewGuid().ToString('N'))
$runtimeMoved = $false; $runtimeInstalled = $false
$menu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$link = Join-Path $menu 'Cicerón.lnk'
$legacyLink = Join-Path $menu 'Mi centro.lnk'
$runName = 'Ciceron'
$legacyRunName = 'GanaLaBatalla'
$oldRun = $null; $oldLegacyRun = $null
$runMutationStarted = $false; $changedExe = $false; $tempLink = $null
$hadExe = $false; $alreadyInstalled = $false; $locked = $false
$mutex = New-Object System.Threading.Mutex($false, 'Local\CiceronInstalacion')

function Get-RunState([string]$Name) {
    $state = [ordered]@{ Exists = $false; Raw = $null; Kind = $null }
    if (!(Test-Path -LiteralPath $RunKey)) { return [pscustomobject]$state }
    $key = Get-Item -LiteralPath $RunKey
    if ($key.GetValueNames() -contains $Name) {
        $state.Exists = $true
        $state.Raw = $key.GetValue($Name, $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        $state.Kind = $key.GetValueKind($Name)
    }
    return [pscustomobject]$state
}

function Test-RunStateEqual($Actual, $Expected) {
    return ($Actual.Exists -eq $Expected.Exists -and (!$Actual.Exists -or ($Actual.Raw -ceq $Expected.Raw -and $Actual.Kind -eq $Expected.Kind)))
}

function Restore-RunState([string]$Name, $State) {
    if ($State.Exists) {
        New-ItemProperty -LiteralPath $RunKey -Name $Name -Value $State.Raw -PropertyType $State.Kind.ToString() -Force | Out-Null
    } else {
        Remove-ItemProperty -LiteralPath $RunKey -Name $Name -ErrorAction SilentlyContinue
    }
}

function Get-NormalizedTarget([string]$Value) {
    if ($Value -isnot [string]) { return $null }
    $expanded = [Environment]::ExpandEnvironmentVariables($Value.Trim().Trim('"'))
    try { return [IO.Path]::GetFullPath($expanded) } catch { return $null }
}

function Test-OwnedRunState($State, [string[]]$AllowedPaths) {
    if (!$State.Exists) { return $true }
    $target = Get-NormalizedTarget $State.Raw
    if (!$target) { return $false }
    foreach ($path in $AllowedPaths) {
        if ([string]::Equals($target, [IO.Path]::GetFullPath($path), [StringComparison]::OrdinalIgnoreCase)) { return $true }
    }
    return $false
}

function Merge-ConfigFile([string]$OldPath, [string]$CurrentPath) {
    try {
        $oldConfig = Get-Content -LiteralPath $OldPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $currentConfig = Get-Content -LiteralPath $CurrentPath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch { throw 'No se pudo combinar config.json; se conservaron ambos perfiles.' }
    if ($null -eq $oldConfig -or $null -eq $currentConfig -or $oldConfig -isnot [pscustomobject] -or $currentConfig -isnot [pscustomobject]) {
        throw 'config.json no tiene formato de objeto; se conservaron ambos perfiles.'
    }
    foreach ($property in $oldConfig.PSObject.Properties) {
        $existing = $currentConfig.PSObject.Properties[$property.Name]
        if ($null -eq $existing) { $currentConfig | Add-Member -MemberType NoteProperty -Name $property.Name -Value $property.Value }
        else { $existing.Value = $property.Value }
    }
    $temporary = $CurrentPath + '.migrando.tmp'
    $backupConfig = $CurrentPath + '.migrando.bak'
    try {
        $json = ConvertTo-Json -InputObject $currentConfig -Depth 50
        [IO.File]::WriteAllText($temporary,$json,(New-Object System.Text.UTF8Encoding($false)))
        [IO.File]::Replace($temporary,$CurrentPath,$backupConfig,$true)
        Remove-Item -LiteralPath $backupConfig -Force
    } catch {
        if ((Test-Path -LiteralPath $backupConfig) -and !(Test-Path -LiteralPath $CurrentPath)) { Move-Item -LiteralPath $backupConfig -Destination $CurrentPath }
        throw "No se pudo guardar la combinación de config.json: $($_.Exception.Message)"
    } finally {
        Remove-Item -LiteralPath $temporary,$backupConfig -Force -ErrorAction SilentlyContinue
    }
}

function Copy-SafeTree([string]$From, [string]$To, [switch]$LegacyInstall, [switch]$MergeConfig, [switch]$AtRoot) {
    $sourceItem = Get-Item -LiteralPath $From -Force
    if (!$sourceItem.PSIsContainer -or ($sourceItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "La carpeta antigua no es segura para migrar: $From"
    }
    if (Test-Path -LiteralPath $To) {
        $targetItem = Get-Item -LiteralPath $To -Force
        if (!$targetItem.PSIsContainer -or ($targetItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "La carpeta de destino no es segura: $To"
        }
    } else { New-Item -ItemType Directory -Path $To | Out-Null }

    foreach ($item in Get-ChildItem -LiteralPath $From -Force) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "No se migran enlaces ni puntos de montaje: $($item.FullName)" }
        $target = Join-Path $To $item.Name
        $managedLegacyFile = $LegacyInstall -and $AtRoot -and !$item.PSIsContainer -and (
            $item.Name -in @('Ciceron.exe','GanaLaBatalla.exe','ciceron-native-host.json','extension-path.txt',
                'Ciceron.instalando.tmp','Ciceron.respaldo.tmp') -or
            $item.Name -match '^CiceronHost-[0-9a-f]{16}\.exe$' -or
            $item.Name -match '^manifest-[0-9a-f]+\.(tmp|bak)$')
        if ($managedLegacyFile) { continue }

        if ($item.PSIsContainer) {
            if ((Test-Path -LiteralPath $target) -and !(Get-Item -LiteralPath $target -Force).PSIsContainer) {
                throw "Hay una carpeta y un archivo con el mismo nombre durante la migración: $target"
            }
            Copy-SafeTree -From $item.FullName -To $target -LegacyInstall:$LegacyInstall
        } elseif (Test-Path -LiteralPath $target) {
            $targetItem = Get-Item -LiteralPath $target -Force
            if ($targetItem.PSIsContainer -or ($targetItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                throw "Hay datos distintos en ambas ubicaciones; se conservaron las dos carpetas: $($item.Name)"
            }
            if ((Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash) {
                if ($MergeConfig -and $AtRoot -and $item.Name -eq 'config.json') { Merge-ConfigFile -OldPath $item.FullName -CurrentPath $target }
                else { throw "Hay datos distintos en ambas ubicaciones; se conservaron las dos carpetas: $($item.Name)" }
            }
        } else {
            Copy-Item -LiteralPath $item.FullName -Destination $target
            if ((Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash) {
                throw "La copia de migración no coincide: $($item.Name)"
            }
        }
    }
}

function Remove-SafeLegacyTree([string]$Path, [string]$ExpectedPath) {
    if (!(Test-Path -LiteralPath $Path)) { return }
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    if (![string]::Equals($resolved, [IO.Path]::GetFullPath($ExpectedPath), [StringComparison]::OrdinalIgnoreCase)) {
        throw "Ruta antigua inesperada; no se elimina: $resolved"
    }
    $rootItem = Get-Item -LiteralPath $resolved -Force
    if (!$rootItem.PSIsContainer -or ($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "Ruta antigua insegura; no se elimina: $resolved" }
    foreach ($item in Get-ChildItem -LiteralPath $resolved -Force -Recurse) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "La carpeta antigua contiene un enlace; no se elimina: $($item.FullName)" }
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}

function Stop-OwnedProcesses([string[]]$Paths, [switch]$Hosts) {
    if ($Hosts) {
        $processes = @(Get-Process -Name 'CiceronHost-*' -ErrorAction SilentlyContinue | Where-Object {
            $_.Path -and ($Paths -contains (Split-Path -Parent $_.Path)) -and (Split-Path -Leaf $_.Path) -match '^CiceronHost-[0-9a-f]{16}\.exe$'
        })
    } else {
        $processes = @(Get-Process -Name 'Ciceron','GanaLaBatalla' -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $Paths -contains $_.Path })
    }
    foreach ($process in $processes) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
    foreach ($process in $processes) { try { $process.WaitForExit(5000) | Out-Null } catch [System.InvalidOperationException] { } }
    if ($Hosts) {
        $remaining = @(Get-Process -Name 'CiceronHost-*' -ErrorAction SilentlyContinue | Where-Object {
            $_.Path -and ($Paths -contains (Split-Path -Parent $_.Path)) -and (Split-Path -Leaf $_.Path) -match '^CiceronHost-[0-9a-f]{16}\.exe$'
        })
    } else {
        $remaining = @(Get-Process -Name 'Ciceron','GanaLaBatalla' -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $Paths -contains $_.Path })
    }
    if ($remaining.Count -gt 0) { throw 'No se pudieron cerrar todos los procesos de Cicerón; no se borraron sus archivos.' }
}

try {
    try { $locked = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $locked = $true }
    if (!$locked) { throw 'Ya hay una instalación o desinstalación en curso. Espera a que termine.' }
    if (!(Test-Path -LiteralPath $source -PathType Leaf) -or
        !(Test-Path -LiteralPath (Join-Path $sourceRuntime 'base_library.zip') -PathType Leaf)) {
        throw 'No se encuentra la compilación completa en internos\Ciceron. Ejecuta scripts\Crear EXE.bat.'
    }
    if (!(Test-Path -LiteralPath $RunKey)) { throw 'No se encuentra la clave de inicio de Windows.' }

    $hadExe = Test-Path -LiteralPath $destination -PathType Leaf
    $alreadyInstalled = $hadExe -or (Test-Path -LiteralPath $legacyExe -PathType Leaf) -or (Test-Path -LiteralPath $legacyNamedExe -PathType Leaf)
    $oldRun = Get-RunState $runName
    $oldLegacyRun = Get-RunState $legacyRunName
    $ownedRunPaths = @($destination,$legacyExe,$legacyNamedExe)
    if (!(Test-OwnedRunState $oldRun $ownedRunPaths)) { throw 'La entrada Ciceron del inicio apunta a otro programa. No se ha modificado.' }
    if (!(Test-OwnedRunState $oldLegacyRun $ownedRunPaths)) { throw 'La entrada antigua del inicio apunta a otro programa. No se ha modificado.' }

    $shell = New-Object -ComObject WScript.Shell
    foreach ($shortcutPath in @($link,$legacyLink)) {
        if (Test-Path -LiteralPath $shortcutPath) {
            $currentTarget = $shell.CreateShortcut($shortcutPath).TargetPath
            if ($currentTarget -notin @($destination,$legacyExe,$legacyNamedExe)) {
                throw "El acceso $([IO.Path]::GetFileNameWithoutExtension($shortcutPath)) ya pertenece a otra aplicación. No se ha modificado."
            }
        }
    }

    $ownedPaths = @($destination,$legacyExe,$legacyNamedExe)
    $running = @(Get-Process -Name 'Ciceron','GanaLaBatalla' -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $ownedPaths -contains $_.Path })
    if ($running.Count -gt 0 -and !$CloseRunning) {
        $answer = Read-Host 'Para instalar o reinstalar, hay que cerrar Cicerón. Los cambios no guardados se perderán. Escribe SI para continuar'
        if ($answer -cne 'SI') { Write-Host 'Instalación cancelada; no se realizaron cambios.'; exit 0 }
    }
    if ($running.Count -gt 0) { Stop-OwnedProcesses -Paths $ownedPaths }
    Stop-OwnedProcesses -Paths @($installDir,$legacyInstallDir) -Hosts

    New-Item -ItemType Directory -Force -Path $installDir,$menu | Out-Null
    if ((Test-Path -LiteralPath $backup) -or (Test-Path -LiteralPath $runtimeBackup)) {
        throw "Existe una copia de recuperación pendiente en $installDir. No se sobrescribirá."
    }
    if (Test-Path -LiteralPath $legacyInstallDir) { Copy-SafeTree -From $legacyInstallDir -To $installDir -LegacyInstall -AtRoot }
    if (Test-Path -LiteralPath $legacyDataDir) { Copy-SafeTree -From $legacyDataDir -To $dataDir -MergeConfig -AtRoot }

    $tempLink = Join-Path $menu ('.Ciceron-' + [guid]::NewGuid().ToString('N') + '.lnk')
    $shortcut = $shell.CreateShortcut($tempLink)
    $shortcut.TargetPath = $destination; $shortcut.Arguments = '--abrir'; $shortcut.IconLocation = $destination + ',0'; $shortcut.WorkingDirectory = $installDir
    $shortcut.Save()
    Copy-Item -LiteralPath $source -Destination $stage -Force
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $stage -Algorithm SHA256).Hash) { throw 'La copia de preparación no coincide con el original.' }
    Copy-SafeTree -From $sourceRuntime -To $runtimeStage
    if (Test-Path -LiteralPath $runtime) {
        $existingRuntime = Get-Item -LiteralPath $runtime -Force
        if (!$existingRuntime.PSIsContainer -or ($existingRuntime.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
            !(Test-Path -LiteralPath (Join-Path $runtime 'base_library.zip') -PathType Leaf)) {
            throw 'La carpeta de dependencias existente no coincide con una instalación de Cicerón.'
        }
        Move-Item -LiteralPath $runtime -Destination $runtimeBackup
        $runtimeMoved = $true
    }
    Move-Item -LiteralPath $runtimeStage -Destination $runtime
    $runtimeInstalled = $true
    if ($hadExe) { [System.IO.File]::Replace($stage, $destination, $backup, $true) }
    else { Move-Item -LiteralPath $stage -Destination $destination }
    $changedExe = $true

    if (!(Test-RunStateEqual (Get-RunState $runName) $oldRun) -or !(Test-RunStateEqual (Get-RunState $legacyRunName) $oldLegacyRun)) {
        throw 'La entrada de inicio cambió durante la instalación; inténtalo de nuevo.'
    }
    if ($oldRun.Exists -or $oldLegacyRun.Exists -or !$alreadyInstalled) {
        $runMutationStarted = $true
        New-ItemProperty -LiteralPath $RunKey -Name $runName -Value ('"' + $destination + '"') -PropertyType String -Force | Out-Null
        if ($oldLegacyRun.Exists) { Remove-ItemProperty -LiteralPath $RunKey -Name $legacyRunName }
    }
    Move-Item -LiteralPath $tempLink -Destination $link -Force
    if (Test-Path -LiteralPath $legacyLink) {
        $legacyTarget = $shell.CreateShortcut($legacyLink).TargetPath
        if ($legacyTarget -in $ownedPaths) { Remove-Item -LiteralPath $legacyLink -Force }
    }
    $changedExe = $false; $runMutationStarted = $false
    $runtimeMoved = $false; $runtimeInstalled = $false
    try {
        if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Force }
        Remove-SafeLegacyTree -Path $runtimeBackup -ExpectedPath $runtimeBackup
    } catch { Write-Warning "Se conservó el respaldo: $($_.Exception.Message)" }
    Write-Host 'Cicerón está instalado. Se migraron los datos y se conservó la preferencia de inicio.'

    if ($RunKey -eq 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run') {
        try {
            $graphicsKey = 'HKCU:\Software\Microsoft\DirectX\UserGpuPreferences'
            if (!(Test-Path -LiteralPath $graphicsKey)) { New-Item -Path $graphicsKey -Force | Out-Null }
            $graphics = Get-Item -LiteralPath $graphicsKey
            foreach ($oldPath in @($legacyExe,$legacyNamedExe)) {
                if ($graphics.GetValue($oldPath) -eq 'GpuPreference=2;') {
                    if ($null -eq $graphics.GetValue($destination)) { New-ItemProperty -LiteralPath $graphicsKey -Name $destination -Value 'GpuPreference=2;' -PropertyType String | Out-Null }
                    Remove-ItemProperty -LiteralPath $graphicsKey -Name $oldPath -ErrorAction SilentlyContinue
                }
            }
            $graphics = Get-Item -LiteralPath $graphicsKey
            if ($null -eq $graphics.GetValue($destination)) { New-ItemProperty -LiteralPath $graphicsKey -Name $destination -Value 'GpuPreference=2;' -PropertyType String | Out-Null }
        } catch { Write-Warning "Windows no pudo guardar la preferencia de GPU de Cicerón: $($_.Exception.Message)" }
    }

    $browserInstaller = Join-Path $PSScriptRoot 'instalar_navegador.ps1'
    if (!$SkipBrowser -and (Test-Path -LiteralPath $browserInstaller)) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $browserInstaller -PackageRoot (Split-Path $PSScriptRoot -Parent) -InstallDir $installDir
        if ($LASTEXITCODE -ne 0) { Write-Warning 'La aplicación está instalada, pero la integración del navegador quedó pendiente. Revisa el mensaje anterior o usa Preparar navegador en Cicerón.' }
    } elseif (!$SkipBrowser) { Write-Warning 'El paquete no incluye la preparación del navegador.' }

    if (Test-Path -LiteralPath $legacyDataDir) { Remove-SafeLegacyTree -Path $legacyDataDir -ExpectedPath $legacyDataDir }
    $oldManifest = Join-Path $legacyInstallDir 'ciceron-native-host.json'
    $oldManifestReferenced = $false
    foreach ($vendor in @('Google\Chrome','Microsoft\Edge')) {
        $nativeKey = 'HKCU:\Software\' + $vendor + '\NativeMessagingHosts\com.ciceron.browser'
        if (Test-Path -LiteralPath $nativeKey) {
            if ([string]::Equals((Get-Item -LiteralPath $nativeKey).GetValue(''),$oldManifest,[StringComparison]::OrdinalIgnoreCase)) { $oldManifestReferenced = $true }
        }
    }
    if ($oldManifestReferenced) {
        Write-Warning 'Se conservó temporalmente la carpeta antigua porque un navegador todavía apunta a su puente nativo.'
    } elseif (Test-Path -LiteralPath $legacyInstallDir) {
        $oldShortcut = Join-Path $menu 'Gana la batalla.lnk'
        if (Test-Path -LiteralPath $oldShortcut) {
            $oldTarget = $shell.CreateShortcut($oldShortcut).TargetPath
            if ($oldTarget -in @($legacyExe,$legacyNamedExe)) { Remove-Item -LiteralPath $oldShortcut -Force }
        }
        Remove-SafeLegacyTree -Path $legacyInstallDir -ExpectedPath $legacyInstallDir
    }
    try {
        . (Join-Path $PSScriptRoot 'accesos_inicio.ps1')
        Install-CiceronToolShortcuts $shell $menu $destination
    } catch {
        Write-Warning "Quedó pendiente preparar las aplicaciones internas en Inicio: $($_.Exception.Message)"
    }
    if (!$NoLaunch) {
        try { Start-Process -FilePath $destination -ArgumentList '--abrir' -WindowStyle Normal } catch { Write-Warning "La instalación terminó, pero no se pudo abrir automáticamente: $($_.Exception.Message)" }
    }
} catch {
    $problem = $_.Exception.Message
    if ($runMutationStarted) {
        try {
            $currentRun = Get-RunState $runName
            $currentLegacyRun = Get-RunState $legacyRunName
            $shouldHaveStartup = $oldRun.Exists -or $oldLegacyRun.Exists -or !$alreadyInstalled
            $expectedNew = [pscustomobject]@{ Exists = $shouldHaveStartup; Raw = $null; Kind = $null }
            if ($shouldHaveStartup) { $expectedNew.Raw = '"' + $destination + '"'; $expectedNew.Kind = [Microsoft.Win32.RegistryValueKind]::String }
            $expectedLegacy = [pscustomobject]@{ Exists = $false; Raw = $null; Kind = $null }
            $newIsSafe = (Test-RunStateEqual $currentRun $oldRun) -or (Test-RunStateEqual $currentRun $expectedNew)
            $legacyIsSafe = (Test-RunStateEqual $currentLegacyRun $oldLegacyRun) -or (Test-RunStateEqual $currentLegacyRun $expectedLegacy)
            if ($newIsSafe -and $legacyIsSafe) {
                Restore-RunState $runName $oldRun
                Restore-RunState $legacyRunName $oldLegacyRun
            } else { throw 'La entrada cambió de nuevo y no se sobrescribió.' }
        } catch { $problem += " No se pudo restaurar el inicio: $($_.Exception.Message)" }
    }
    if ($changedExe) {
        try {
            if ($hadExe -and (Test-Path -LiteralPath $backup)) { [System.IO.File]::Copy($backup, $destination, $true); Remove-Item -LiteralPath $backup -Force }
            elseif (!$hadExe) { Remove-Item -LiteralPath $destination -Force -ErrorAction SilentlyContinue }
        } catch { $problem += " No se pudo restaurar el ejecutable anterior: $($_.Exception.Message)" }
    }
    try {
        if ($runtimeInstalled) { Remove-SafeLegacyTree -Path $runtime -ExpectedPath $runtime }
        if ($runtimeMoved) { Move-Item -LiteralPath $runtimeBackup -Destination $runtime }
    } catch { $problem += " No se restauraron las dependencias anteriores: $($_.Exception.Message)" }
    Write-Host "No se pudo completar la instalación: $problem"
    exit 1
} finally {
    if ($locked) {
        try { Remove-SafeLegacyTree -Path $runtimeStage -ExpectedPath $runtimeStage }
        catch { Write-Warning "Quedó una carpeta de preparación: $($_.Exception.Message)" }
    }
    if ($locked -and (Test-Path -LiteralPath $stage)) { Remove-Item -LiteralPath $stage -Force -ErrorAction SilentlyContinue }
    if ($tempLink -and (Test-Path -LiteralPath $tempLink)) { Remove-Item -LiteralPath $tempLink -Force -ErrorAction SilentlyContinue }
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
