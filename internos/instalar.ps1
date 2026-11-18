param(
    [string]$RunKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run',
    [string]$NativeRoot = 'HKCU:\Software',
    [string]$InstallDir = '',
    [string]$PreviousRoot = '',
    [switch]$Reparar,
    [switch]$Recuperar,
    [switch]$DesdeFuentes,
    [switch]$PreferirFuentes,
    [switch]$Empaquetado,
    [string]$SemillaPython = '',
    [switch]$NoLaunch,
    [switch]$SkipBrowser,
    [switch]$CloseRunning
)
$ErrorActionPreference = 'Stop'
if ($PreferirFuentes -and !$Empaquetado -and !$Reparar -and !$Recuperar) { $DesdeFuentes = $true }
if ($DesdeFuentes -and $Empaquetado) { throw 'Elige entre fuentes y paquete.' }
$repositoryRoot = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'preparar_fuentes.ps1')
. (Join-Path $PSScriptRoot 'control_fuentes.ps1')
$bundle = Join-Path $PSScriptRoot 'Ciceron'
$previousInstallDir = Join-Path $env:LOCALAPPDATA 'Ciceron'
$previousExe = Join-Path $previousInstallDir 'Ciceron.exe'
if (!$InstallDir) { $InstallDir = Join-Path $repositoryRoot 'Aplicacion' }
$installDir = [IO.Path]::GetFullPath($InstallDir)
$sourceBundle = if ($DesdeFuentes) { Join-Path $installDir ('.fuentes-' + [guid]::NewGuid().ToString('N')) }
$previousRelease = Join-Path $installDir 'version-anterior'
$releaseStage = Join-Path $installDir ('.version-' + [guid]::NewGuid().ToString('N'))
$receipt = Join-Path $installDir 'integracion-ciceron.json'
$dataFormat = Join-Path $installDir 'formato-datos.txt'
$browserInstaller = Join-Path $PSScriptRoot 'instalar_navegador.ps1'
if ($Recuperar) { $bundle = $previousRelease }
$source = Join-Path $bundle 'Ciceron.exe'
$sourceRuntime = Join-Path $bundle '_internal'
$sourceFormat = if ($Recuperar) { Join-Path $bundle 'formato-datos.txt' }
                else { Join-Path $PSScriptRoot 'formato-datos.txt' }
$destination = Join-Path $installDir 'Ciceron.exe'
$legacyInstallDir = Join-Path $env:LOCALAPPDATA 'GanaLaBatalla'
$legacyExe = Join-Path $legacyInstallDir 'Ciceron.exe'
$legacyNamedExe = Join-Path $legacyInstallDir 'GanaLaBatalla.exe'
$legacyDataDir = Join-Path $env:APPDATA 'GanaLaBatalla'
$previousDataDir = Join-Path $env:APPDATA 'Ciceron'
$dataDir = Join-Path $installDir 'datos'
$previousPackagesDir = Join-Path $previousInstallDir 'paquetes'
$packagesDir = Join-Path $dataDir 'paquetes'
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
$startupArgument = '--inicio-silencioso'
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
    $command = $Value.Trim()
    if ($command.StartsWith('"')) {
        $end = $command.IndexOf('"', 1)
        if ($end -lt 0) { return $null }
        $target = $command.Substring(1, $end - 1)
    } else {
        $target = ($command -split '\s+', 2)[0]
    }
    $expanded = [Environment]::ExpandEnvironmentVariables($target)
    try { return [IO.Path]::GetFullPath($expanded) } catch { return $null }
}

function Get-CiceronStartupCommand([string]$Path) {
    return '"' + $Path + '" ' + $startupArgument
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

function Copy-SafeTree([string]$From, [string]$To, [switch]$LegacyInstall, [switch]$MergeConfig, [switch]$AtRoot, [switch]$SkipTransient) {
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
        if ($SkipTransient -and ($item.Name -eq '__pycache__' -or $item.Extension -eq '.pyc')) { continue }
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "No se migran enlaces ni puntos de montaje: $($item.FullName)" }
        $target = Join-Path $To $item.Name
        if ($LegacyInstall -and $AtRoot -and $item.Name -eq 'paquetes') { continue }
        if ($SkipTransient -and (($AtRoot -and $item.Name -in @('navegadores-activos','arranques-paquetes','_metadata')) -or
            ((Split-Path -Leaf $From) -eq 'paquetes' -and $item.Name -eq 'datos-en-uso'))) { continue }
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
            Copy-SafeTree -From $item.FullName -To $target -LegacyInstall:$LegacyInstall -SkipTransient:$SkipTransient
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

function Remove-PreviousInstall([string]$Path, [string]$ExpectedPath) {
    if (!(Test-Path -LiteralPath $Path)) { return }
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    if (![string]::Equals($resolved, [IO.Path]::GetFullPath($ExpectedPath), [StringComparison]::OrdinalIgnoreCase)) {
        throw "Instalación anterior inesperada; se conserva: $resolved"
    }
    $rootItem = Get-Item -LiteralPath $resolved -Force
    if (!$rootItem.PSIsContainer -or ($rootItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "Instalación anterior insegura; se conserva: $resolved" }
    $allowed = @('Ciceron.exe','GanaLaBatalla.exe','_internal','ciceron-native-host.json','extension-path.txt',
        'Ciceron.instalando.tmp','Ciceron.respaldo.tmp','paquetes')
    foreach ($item in Get-ChildItem -LiteralPath $resolved -Force) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "La instalación anterior contiene un enlace; se conserva: $($item.FullName)" }
        if ($item.Name -notin $allowed -and $item.Name -notmatch '^CiceronHost-[0-9a-f]{16}\.exe$' -and
            $item.Name -notmatch '^manifest-[0-9a-f]+\.(tmp|bak)$') {
            throw "La instalación anterior contiene un archivo no reconocido; se conserva: $($item.Name)"
        }
    }
    Remove-SafeLegacyTree -Path $resolved -ExpectedPath $ExpectedPath
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

function Read-Format([string]$Path) {
    if (!(Test-Path -LiteralPath $Path -PathType Leaf)) { return '1' }
    $value = (Get-Content -LiteralPath $Path -Raw).Trim()
    if ($value -notmatch '^[1-9][0-9]{0,5}$') { throw 'Versión de formato de datos inválida.' }
    return $value
}

function Get-TreeHashes([string]$Root, [switch]$Extension, [switch]$Source) {
    if (!(Test-Path -LiteralPath $Root -PathType Container)) { return }
    foreach ($file in Get-ChildItem -LiteralPath $Root -File -Recurse -Force | Sort-Object FullName) {
        $relative = $file.FullName.Substring($Root.Length + 1)
        if ($Source -and ($relative -match '(^|\\)__pycache__\\' -or $file.Extension -eq '.pyc')) { continue }
        if ($relative -eq 'huellas.sha256') { continue }
        if ($Extension -and ($relative -like '_metadata\*' -or $relative -eq 'README.md')) { continue }
        "$relative $((Get-FileHash -LiteralPath $file.FullName).Hash)"
    }
}

function Copy-Release([string]$To, [string]$Format) {
    New-Item -ItemType Directory -Path $To | Out-Null
    Copy-Item -LiteralPath $destination -Destination $To
    Copy-SafeTree -From $runtime -To (Join-Path $To '_internal')
    Set-Content -LiteralPath (Join-Path $To 'formato-datos.txt') -Value $Format -Encoding Ascii
    $manifest = Join-Path $installDir 'ciceron-native-host.json'
    $extension = Join-Path $installDir '00 EXTENSION'
    if (Test-Path -LiteralPath $manifest -PathType Leaf) {
        $info = Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json
        $name = [IO.Path]::GetFileName($info.path)
        if ($name -notmatch '^CiceronHost-([0-9a-f]{16})\.exe$') { throw 'El puente anterior no se puede respaldar.' }
        $hash = $Matches[1]
        $hostPath = Join-Path $installDir $name
        if (!(Test-Path -LiteralPath $hostPath -PathType Leaf) -or
            !(Get-FileHash -LiteralPath $hostPath).Hash.StartsWith($hash,[StringComparison]::OrdinalIgnoreCase)) {
            throw 'El puente anterior no coincide con su manifiesto.'
        }
        Copy-SafeTree -From $extension -To (Join-Path $To '00 EXTENSION') -SkipTransient -AtRoot
        Copy-Item -LiteralPath $hostPath -Destination (Join-Path $To 'CiceronHost.exe')
    }
    Set-Content -LiteralPath (Join-Path $To 'huellas.sha256') -Value @(Get-TreeHashes $To) -Encoding UTF8
}

function Publish-PreviousRelease {
    if (!(Test-Path -LiteralPath $releaseStage -PathType Container)) { return }
    $retired = Join-Path $installDir ('.version-retirada-' + [guid]::NewGuid().ToString('N'))
    if (Test-Path -LiteralPath $previousRelease) {
        $item = Get-Item -LiteralPath $previousRelease -Force
        if (!$item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
            !(Test-Path -LiteralPath (Join-Path $previousRelease 'formato-datos.txt') -PathType Leaf)) {
            throw 'La carpeta de versión anterior no pertenece al instalador.'
        }
        [IO.Directory]::Move($previousRelease, $retired)
    }
    try { [IO.Directory]::Move($releaseStage, $previousRelease) }
    catch {
        if (Test-Path -LiteralPath $retired) { [IO.Directory]::Move($retired, $previousRelease) }
        throw
    }
    try { Remove-SafeLegacyTree -Path $retired -ExpectedPath $retired }
    catch { Write-Warning "Se conservó un respaldo adicional en $retired." }
}

function Backup-DataFormat {
    if (!(Test-Path -LiteralPath $dataDir -PathType Container)) { return }
    $leases = @()
    try {
        $lockDir = Join-Path $dataDir 'paquetes\datos-en-uso'
        if (Test-Path -LiteralPath $lockDir) {
            foreach ($file in Get-ChildItem -LiteralPath $lockDir -Filter '*.lock' -File) {
                $leases += [IO.File]::Open($file.FullName, 'Open', 'Read', 'None')
            }
        }
        $prefix = (Join-Path $dataDir 'paquetes\versiones') + '\'
        if (Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) }) {
            throw 'Cierra las aplicaciones empaquetadas antes de respaldar los datos.'
        }
        # Stage the complete copy and publish it only when all files verify.
        $backupName = 'datos-antes-de-actualizar-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)
        $backupPath = Join-Path $installDir $backupName
        $pending = $backupPath + '.tmp'
        # The lock files are synchronization objects and are excluded below.
        Copy-SafeTree -From $dataDir -To $pending -SkipTransient -AtRoot
        [IO.Directory]::Move($pending, $backupPath)
        Write-Host "Respaldo previo de datos: $backupPath"
    } catch {
        throw "No se pudo respaldar el formato anterior. Cierra las miniapps abiertas y vuelve a intentarlo. $($_.Exception.Message)"
    } finally {
        foreach ($lease in $leases) { $lease.Dispose() }
        if ($pending) { Remove-SafeLegacyTree -Path $pending -ExpectedPath $pending }
    }
}

function Write-IntegrationReceipt {
    $temporary = $receipt + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
    try {
        [IO.File]::WriteAllText($temporary, (@{ schema = 1; root = $installDir } | ConvertTo-Json -Compress))
        if (Test-Path -LiteralPath $receipt) {
            $oldReceipt = $temporary + '.bak'
            [IO.File]::Replace($temporary, $receipt, $oldReceipt)
            Remove-Item -LiteralPath $oldReceipt -Force
        }
        else { [IO.File]::Move($temporary, $receipt) }
    } finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
}

function Install-PortableCommands {
    if ($Recuperar) { return }
    $toolsDir = Join-Path $installDir 'integracion'
    New-Item -ItemType Directory -Path $toolsDir -Force | Out-Null
    foreach ($file in @('instalar.ps1','desinstalar.ps1','instalar_navegador.ps1','accesos_inicio.ps1','propiedades_acceso.cs',
                        'preparar_fuentes.ps1','control_fuentes.ps1','lanzador.cs')) {
        $path = Join-Path $PSScriptRoot $file
        if (Test-Path -LiteralPath $path -PathType Leaf) { Copy-Item -LiteralPath $path -Destination $toolsDir -Force }
    }
    foreach ($file in @('Abrir Ciceron.bat','Desinstalar.bat','Reparar integracion.bat','Recuperar version anterior.bat')) {
        $path = Join-Path $PSScriptRoot $file
        if (Test-Path -LiteralPath $path -PathType Leaf) { Copy-Item -LiteralPath $path -Destination $installDir -Force }
    }
}

function Invoke-BrowserIntegration([string[]]$Options) {
    $command = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$browserInstaller,
                 '-InstallDir',$installDir,'-RegistryRoot',$NativeRoot)
    if ($PreviousRoot) { $command += @('-PreviousRoot',$PreviousRoot) }
    & powershell.exe @command @Options
    $script:browserExit = $LASTEXITCODE
}

try {
    try { $locked = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $locked = $true }
    if (!$locked) { throw 'Ya hay una instalación o desinstalación en curso. Espera a que termine.' }
    if (($Reparar -and $Recuperar) -or ($DesdeFuentes -and ($Reparar -or $Recuperar))) {
        throw 'Elige una sola operación.'
    }
    if (!$Reparar -and !$DesdeFuentes -and (!(Test-Path -LiteralPath $source -PathType Leaf) -or
        !(Test-CiceronRuntime $sourceRuntime))) {
        if ($Recuperar) { throw 'No hay una versión anterior completa para recuperar.' }
        throw 'No se encuentra la compilación completa en internos\Ciceron.'
    }
    if ($Recuperar) {
        $inventory = Join-Path $previousRelease 'huellas.sha256'
        if (!(Test-Path -LiteralPath $inventory -PathType Leaf) -or
            ((Get-Content -LiteralPath $inventory -Encoding UTF8) -join "`n") -cne ((Get-TreeHashes $previousRelease) -join "`n")) {
            throw 'La versión anterior no coincide con sus huellas de verificación.'
        }
    }
    if (!(Test-Path -LiteralPath $RunKey)) { throw 'No se encuentra la clave de inicio de Windows.' }

    $hadExe = Test-Path -LiteralPath $destination -PathType Leaf
    $alreadyInstalled = $hadExe -or (Test-Path -LiteralPath $previousExe -PathType Leaf) -or
        (Test-Path -LiteralPath $legacyExe -PathType Leaf) -or (Test-Path -LiteralPath $legacyNamedExe -PathType Leaf)
    $oldRun = Get-RunState $runName
    $oldLegacyRun = Get-RunState $legacyRunName
    $ownedRunPaths = @($destination,$previousExe,$legacyExe,$legacyNamedExe)
    if (Test-Path -LiteralPath $receipt -PathType Leaf) {
        $integration = Get-Content -LiteralPath $receipt -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($integration.schema -ne 1 -or $integration.root -isnot [string] -or ![IO.Path]::IsPathRooted($integration.root)) {
            throw 'La referencia a la ubicación anterior está dañada.'
        }
        if (!$PreviousRoot) { $PreviousRoot = $integration.root }
    }
    if ($PreviousRoot) {
        $PreviousRoot = [IO.Path]::GetFullPath($PreviousRoot)
        $ownedRunPaths += Join-Path $PreviousRoot 'Ciceron.exe'
    }
    $ownRun = Test-OwnedRunState $oldRun $ownedRunPaths
    $ownLegacyRun = Test-OwnedRunState $oldLegacyRun $ownedRunPaths
    if (!$ownRun -or !$ownLegacyRun) {
        if (!$Reparar) { throw 'Hay una entrada de inicio que apunta a otro programa. Se conservó.' }
        Write-Warning 'Se conservaron las entradas de inicio que requieren revisión.'
    }

    $shell = New-Object -ComObject WScript.Shell
    $ownShortcut = $true
    foreach ($shortcutPath in @($link,$legacyLink)) {
        if (Test-Path -LiteralPath $shortcutPath) {
            $currentTarget = $shell.CreateShortcut($shortcutPath).TargetPath
            if ($currentTarget -notin $ownedRunPaths) {
                if (!$Reparar) { throw "El acceso $([IO.Path]::GetFileNameWithoutExtension($shortcutPath)) pertenece a otra aplicación." }
                if ($shortcutPath -eq $link) { $ownShortcut = $false }
                Write-Warning "Se conservó un acceso ajeno: $shortcutPath"
            }
        }
    }

    if (($Reparar -or $Recuperar) -and !$hadExe) { throw 'No se encuentra Ciceron.exe en la carpeta indicada.' }
    if ($Reparar) {
        Initialize-CiceronEnvironment $installDir $runtime $SemillaPython
        New-Item -ItemType Directory -Force -Path $menu | Out-Null
        if ($ownShortcut) {
            $tempLink = Join-Path $menu ('.Ciceron-' + [guid]::NewGuid().ToString('N') + '.lnk')
            $shortcut = $shell.CreateShortcut($tempLink)
            $shortcut.TargetPath = $destination; $shortcut.Arguments = '--alternar-centro'; $shortcut.IconLocation = $destination + ',0'; $shortcut.WorkingDirectory = $installDir
            $shortcut.Save()
        }
        if ($ownRun -and $ownLegacyRun -and ($oldRun.Exists -or $oldLegacyRun.Exists)) {
            if (!(Test-RunStateEqual (Get-RunState $runName) $oldRun) -or !(Test-RunStateEqual (Get-RunState $legacyRunName) $oldLegacyRun)) {
                throw 'La entrada de inicio cambió durante la reparación.'
            }
            $runMutationStarted = $true
            New-ItemProperty -LiteralPath $RunKey -Name $runName -Value (Get-CiceronStartupCommand $destination) -PropertyType String -Force | Out-Null
            if ($oldLegacyRun.Exists) { Remove-ItemProperty -LiteralPath $RunKey -Name $legacyRunName }
        }
        if ($tempLink) { Move-Item -LiteralPath $tempLink -Destination $link -Force }
        $runMutationStarted = $false
        . (Join-Path $PSScriptRoot 'accesos_inicio.ps1')
        Install-CiceronToolShortcuts $shell $menu $destination
        Repair-CiceronLibraryShortcuts $shell $menu $PreviousRoot $installDir
        if (!$SkipBrowser) {
            Invoke-BrowserIntegration @('-Repair')
            if ($browserExit -ne 0) { throw 'La reparación del navegador quedó pendiente. Revisa el mensaje anterior.' }
        }
        Write-IntegrationReceipt
        Write-Host 'Integración reparada. Si el navegador conserva la ruta anterior, vuelve a cargar la extensión desempaquetada desde la nueva carpeta.'
        exit 0
    }

    $ownedPaths = $ownedRunPaths
    $running = @(Get-Process -Name 'Ciceron','GanaLaBatalla' -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $ownedPaths -contains $_.Path })
    $sourceRunning = Test-CiceronSourceRunning $installDir
    if (($running.Count -gt 0 -or $sourceRunning) -and !$CloseRunning) {
        $answer = Read-Host 'Para instalar o reinstalar, hay que cerrar Cicerón. Los cambios no guardados se perderán. Escribe SI para continuar'
        if ($answer -cne 'SI') { Write-Host 'Instalación cancelada; no se realizaron cambios.'; exit 0 }
    }
    if ($DesdeFuentes) {
        New-CiceronSourceBundle $repositoryRoot $sourceBundle $installDir $SemillaPython
        $source = Join-Path $sourceBundle 'Ciceron.exe'
        $sourceRuntime = Join-Path $sourceBundle '_internal'
    } elseif ($Recuperar) {
        Initialize-CiceronEnvironment $installDir $sourceRuntime $SemillaPython
    }
    if (Test-CiceronSourceRunning $installDir) {
        if (!$sourceRunning -and !$CloseRunning) { throw 'Cicerón se abrió mientras se preparaba la instalación. Ciérralo y vuelve a intentarlo.' }
        Stop-CiceronSource $installDir
    }
    if ($running.Count -gt 0) { Stop-OwnedProcesses -Paths $ownedPaths }
    Stop-OwnedProcesses -Paths @($installDir,$legacyInstallDir) -Hosts

    New-Item -ItemType Directory -Force -Path $installDir,$menu | Out-Null
    if ((Test-Path -LiteralPath $backup) -or (Test-Path -LiteralPath $runtimeBackup)) {
        throw "Existe una copia de recuperación pendiente en $installDir. No se sobrescribirá."
    }
    if (!$Recuperar) {
        if (Test-Path -LiteralPath $previousPackagesDir) { Copy-SafeTree -From $previousPackagesDir -To $packagesDir }
        $legacyPackagesDir = Join-Path $legacyInstallDir 'paquetes'
        if (Test-Path -LiteralPath $legacyPackagesDir) { Copy-SafeTree -From $legacyPackagesDir -To $packagesDir }
        if (Test-Path -LiteralPath $legacyDataDir) { Copy-SafeTree -From $legacyDataDir -To $dataDir -MergeConfig -AtRoot -SkipTransient }
        if (Test-Path -LiteralPath $previousDataDir) { Copy-SafeTree -From $previousDataDir -To $dataDir -MergeConfig -AtRoot -SkipTransient }
    }
    $currentFormat = Read-Format $dataFormat
    $newFormat = Read-Format $sourceFormat
    if (!$Recuperar -and $currentFormat -ne $newFormat) { Backup-DataFormat }
    if (!$Recuperar -and $hadExe -and (Test-CiceronRuntime $runtime)) {
        $changed = (Get-FileHash -LiteralPath $source).Hash -ne (Get-FileHash -LiteralPath $destination).Hash -or
            $currentFormat -ne $newFormat -or ((Get-TreeHashes $runtime) -join "`n") -cne ((Get-TreeHashes $sourceRuntime) -join "`n")
        $hostSource = Join-Path $(if ($DesdeFuentes) { $sourceBundle } else { $PSScriptRoot }) 'CiceronHost.exe'
        $extensionSource = Join-Path $repositoryRoot 'navegador\extension'
        if (!$SkipBrowser -and (Test-Path -LiteralPath $hostSource -PathType Leaf)) {
            $hash = (Get-FileHash -LiteralPath $hostSource).Hash.Substring(0,16)
            $manifestPath = Join-Path $installDir 'ciceron-native-host.json'
            if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
                $installedHost = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
                $changed = $changed -or [IO.Path]::GetFileName($installedHost.path) -ine "CiceronHost-$hash.exe" -or
                    ((Get-TreeHashes (Join-Path $installDir '00 EXTENSION') -Extension) -join "`n") -cne ((Get-TreeHashes $extensionSource -Extension) -join "`n")
            }
        }
        if ($changed) { Copy-Release $releaseStage $currentFormat }
    }

    $tempLink = Join-Path $menu ('.Ciceron-' + [guid]::NewGuid().ToString('N') + '.lnk')
    $shortcut = $shell.CreateShortcut($tempLink)
    $shortcut.TargetPath = $destination; $shortcut.Arguments = '--alternar-centro'; $shortcut.IconLocation = $destination + ',0'; $shortcut.WorkingDirectory = $installDir
    $shortcut.Save()
    Copy-Item -LiteralPath $source -Destination $stage -Force
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $stage -Algorithm SHA256).Hash) { throw 'La copia de preparación no coincide con el original.' }
    Copy-SafeTree -From $sourceRuntime -To $runtimeStage
    if (Test-Path -LiteralPath $runtime) {
        $existingRuntime = Get-Item -LiteralPath $runtime -Force
        if (!$existingRuntime.PSIsContainer -or ($existingRuntime.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
            !(Test-CiceronRuntime $runtime)) {
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
        New-ItemProperty -LiteralPath $RunKey -Name $runName -Value (Get-CiceronStartupCommand $destination) -PropertyType String -Force | Out-Null
        if ($oldLegacyRun.Exists) { Remove-ItemProperty -LiteralPath $RunKey -Name $legacyRunName }
    }
    Move-Item -LiteralPath $tempLink -Destination $link -Force
    if ($Recuperar -and !$SkipBrowser -and (Test-Path -LiteralPath (Join-Path $bundle 'CiceronHost.exe') -PathType Leaf)) {
        if (!(Test-Path -LiteralPath $browserInstaller -PathType Leaf)) { throw 'Falta el script que recupera el puente y la extensión.' }
        Invoke-BrowserIntegration @('-BrowserBundle',$bundle)
        if ($browserExit -eq 2) { throw 'No se pudo recuperar la extensión y el puente de la versión anterior.' }
        if ($browserExit -ne 0) { Write-Warning 'El puente anterior está disponible. Ejecuta Reparar integración para revisar su registro.' }
    }
    Publish-PreviousRelease
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
    Set-Content -LiteralPath $dataFormat -Value $newFormat -Encoding Ascii
    if ($Recuperar) { Write-Host 'Se recuperó la versión anterior. Los datos actuales se conservaron.' }
    else { Write-Host 'Cicerón está instalado. Se conservaron los datos y la preferencia de inicio.' }
    Install-PortableCommands

    if ($RunKey -eq 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run') {
        try {
            $graphicsKey = 'HKCU:\Software\Microsoft\DirectX\UserGpuPreferences'
            if (!(Test-Path -LiteralPath $graphicsKey)) { New-Item -Path $graphicsKey -Force | Out-Null }
            $graphics = Get-Item -LiteralPath $graphicsKey
            foreach ($oldPath in @($previousExe,$legacyExe,$legacyNamedExe)) {
                if ($graphics.GetValue($oldPath) -eq 'GpuPreference=2;') {
                    if ($null -eq $graphics.GetValue($destination)) { New-ItemProperty -LiteralPath $graphicsKey -Name $destination -Value 'GpuPreference=2;' -PropertyType String | Out-Null }
                    Remove-ItemProperty -LiteralPath $graphicsKey -Name $oldPath -ErrorAction SilentlyContinue
                }
            }
            $graphics = Get-Item -LiteralPath $graphicsKey
            if ($null -eq $graphics.GetValue($destination)) { New-ItemProperty -LiteralPath $graphicsKey -Name $destination -Value 'GpuPreference=2;' -PropertyType String | Out-Null }
        } catch { Write-Warning "Windows no pudo guardar la preferencia de GPU de Cicerón: $($_.Exception.Message)" }
    }

    if (!$Recuperar -and !$SkipBrowser -and (Test-Path -LiteralPath $browserInstaller)) {
        if ($DesdeFuentes) { Invoke-BrowserIntegration @('-BrowserBundle',$sourceBundle) }
        else { Invoke-BrowserIntegration @('-PackageRoot',$repositoryRoot) }
        if ($browserExit -ne 0) { Write-Warning 'La aplicación está instalada, pero la integración del navegador quedó pendiente. Revisa el mensaje anterior o usa Preparar navegador en Cicerón.' }
    } elseif (!$Recuperar -and !$SkipBrowser) { Write-Warning 'El paquete no incluye la preparación del navegador.' }

    if (!$Recuperar) {
    $previousManifest = Join-Path $previousInstallDir 'ciceron-native-host.json'
    $oldManifest = Join-Path $legacyInstallDir 'ciceron-native-host.json'
    $oldManifestReferenced = $false
    foreach ($vendor in @('Google\Chrome','Microsoft\Edge')) {
        $nativeKey = $NativeRoot + '\' + $vendor + '\NativeMessagingHosts\com.ciceron.browser'
        if (Test-Path -LiteralPath $nativeKey) {
            $registeredManifest = (Get-Item -LiteralPath $nativeKey).GetValue('')
            if ($registeredManifest -and ($registeredManifest -in @($oldManifest,$previousManifest) -or
                ([IO.Path]::GetFileName($registeredManifest) -ieq 'ciceron-native-host.json' -and !(Test-Path -LiteralPath $registeredManifest)))) { $oldManifestReferenced = $true }
        }
    }
    if ($oldManifestReferenced) {
        Write-Warning 'Se conservó temporalmente la carpeta antigua porque un navegador todavía apunta a su puente nativo.'
    } else {
        if (Test-Path -LiteralPath $previousDataDir) { Remove-SafeLegacyTree -Path $previousDataDir -ExpectedPath $previousDataDir }
        if (Test-Path -LiteralPath $legacyDataDir) { Remove-SafeLegacyTree -Path $legacyDataDir -ExpectedPath $legacyDataDir }
    }
    if (!$oldManifestReferenced -and (Test-Path -LiteralPath $legacyInstallDir)) {
        $oldShortcut = Join-Path $menu 'Gana la batalla.lnk'
        if (Test-Path -LiteralPath $oldShortcut) {
            $oldTarget = $shell.CreateShortcut($oldShortcut).TargetPath
            if ($oldTarget -in @($legacyExe,$legacyNamedExe)) { Remove-Item -LiteralPath $oldShortcut -Force }
        }
        Remove-SafeLegacyTree -Path $legacyInstallDir -ExpectedPath $legacyInstallDir
    }
    if (!$oldManifestReferenced -and (Test-Path -LiteralPath $previousInstallDir)) {
        try { Remove-PreviousInstall -Path $previousInstallDir -ExpectedPath $previousInstallDir }
        catch { Write-Warning "Se conservó la instalación anterior para proteger archivos: $($_.Exception.Message)" }
    }
    }
    try {
        . (Join-Path $PSScriptRoot 'accesos_inicio.ps1')
        Install-CiceronToolShortcuts $shell $menu $destination
        Repair-CiceronLibraryShortcuts $shell $menu $PreviousRoot $installDir
    } catch {
        Write-Warning "Quedó pendiente preparar las aplicaciones internas en Inicio: $($_.Exception.Message)"
    }
    Write-IntegrationReceipt
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
            if ($shouldHaveStartup) { $expectedNew.Raw = (Get-CiceronStartupCommand $destination); $expectedNew.Kind = [Microsoft.Win32.RegistryValueKind]::String }
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
        if ($sourceBundle) {
            try { Remove-SafeLegacyTree -Path $sourceBundle -ExpectedPath $sourceBundle }
            catch { Write-Warning "Quedó una copia temporal en $sourceBundle." }
        }
        try { Remove-SafeLegacyTree -Path $runtimeStage -ExpectedPath $runtimeStage }
        catch { Write-Warning "Quedó una carpeta de preparación: $($_.Exception.Message)" }
        try { Remove-SafeLegacyTree -Path $releaseStage -ExpectedPath $releaseStage }
        catch { Write-Warning "Quedó una versión preparada en $releaseStage." }
    }
    if ($locked -and (Test-Path -LiteralPath $stage)) { Remove-Item -LiteralPath $stage -Force -ErrorAction SilentlyContinue }
    if ($tempLink -and (Test-Path -LiteralPath $tempLink)) { Remove-Item -LiteralPath $tempLink -Force -ErrorAction SilentlyContinue }
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
