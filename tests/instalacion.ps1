$ErrorActionPreference = 'Stop'
$root = Join-Path $PSScriptRoot '.instalacion-temporal'
$expected = Join-Path $PSScriptRoot '.instalacion-temporal'
$key = 'HKCU:\Software\CiceronPruebaCodex_Instalacion'
if (Test-Path -LiteralPath $root) { throw 'La carpeta de prueba ya existe; no se reemplaza.' }
if (Test-Path -LiteralPath $key) { throw 'La clave de prueba ya existe; no se reemplaza.' }
try {
    $package=Join-Path $root 'paquete'; $local=Join-Path $root 'local'; $app=Join-Path $root 'appdata'
    $installDir=Join-Path $root 'Aplicacion'
    New-Item -ItemType Directory -Force -Path $package,$local,$app | Out-Null
    foreach ($file in @('instalar.ps1', 'desinstalar.ps1', 'accesos_inicio.ps1', 'propiedades_acceso.cs')) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot "..\internos\$file") -Destination $package
    }
    $bundle=Join-Path $package 'Ciceron'; $sourceRuntime=Join-Path $bundle '_internal'
    New-Item -ItemType Directory -Force -Path $sourceRuntime | Out-Null
    [IO.File]::WriteAllText((Join-Path $bundle 'Ciceron.exe'),'contenido de prueba')
    [IO.File]::WriteAllText((Join-Path $sourceRuntime 'base_library.zip'),'runtime base')
    [IO.File]::WriteAllText((Join-Path $sourceRuntime 'runtime.marker'),'runtime inicial')
    $env:LOCALAPPDATA=$local; $env:APPDATA=$app
    $profile=Join-Path $app 'Ciceron'
    New-Item -ItemType Directory -Force $profile | Out-Null
    [IO.File]::WriteAllText((Join-Path $profile 'config.json'),'{"portable":"migrado"}')
    New-Item -Path $key | Out-Null
    $install=Join-Path $package 'instalar.ps1'; $uninstall=Join-Path $package 'desinstalar.ps1'
    & powershell.exe -NoProfile -File $install -RunKey $key -InstallDir $installDir -NoLaunch
    if ($LASTEXITCODE -ne 0) { throw 'Primera instalación fallida' }
    $dest=Join-Path $installDir 'Ciceron.exe'
    $installedRuntime=Join-Path $installDir '_internal'
    . (Join-Path $package 'accesos_inicio.ps1')
    $toolDirectory = Join-Path $app 'Microsoft\Windows\Start Menu\Programs\Ciceron'
    $toolShell = New-Object -ComObject WScript.Shell
    $explorer = New-Object -ComObject Shell.Application
    $toolFolder = $explorer.NameSpace($toolDirectory)
    $toolSpecs = @()
    foreach ($tool in $builtInTools) {
        foreach ($entry in Get-CiceronToolShortcuts $tool) {
            $file = $toolFolder.ParseName($entry.Name + '.lnk')
            if (!$file -or !(Test-CiceronToolShortcut $toolShell $file.Path $tool.Id $dest)) { throw "Acceso a $($entry.Name) incorrecto" }
            if ($file.ExtendedProperty('System.AppUserModel.ID') -cne $entry.AppId -or
                ($file.ExtendedProperty('System.Keywords') -join ',') -cne ($tool.Tags -join ',')) { throw "Metadatos de $($entry.Name) incorrectos" }
            $toolSpecs += [pscustomobject]@{ Path = $file.Path; AppId = $entry.AppId; ToolId = $tool.Id; Tags = @($tool.Tags) }
        }
    }
    if (!(Test-Path -LiteralPath $dest)) { throw 'No se instaló el ejecutable' }
    if ((Get-Content -LiteralPath (Join-Path $installedRuntime 'runtime.marker') -Raw) -ne 'runtime inicial') { throw 'No se instalaron las dependencias' }
    if (!(Test-Path -LiteralPath (Join-Path $installDir 'datos\config.json')) -or (Test-Path -LiteralPath $profile)) { throw 'No se migró el perfil al lado de la aplicación' }
    if ((Get-ItemProperty -Path $key -Name Ciceron).Ciceron -ne ('"'+$dest+'"')) { throw 'Registro incorrecto' }
    $guard=New-Object System.Threading.Mutex($false, 'Local\CiceronInstalacion')
    $guardHeld=$guard.WaitOne(0)
    if (!$guardHeld) { throw 'No se pudo preparar la prueba de concurrencia' }
    $sentinel=Join-Path $installDir 'Ciceron.instalando.tmp'
    [IO.File]::WriteAllText($sentinel,'operación en curso')
    try {
        & powershell.exe -NoProfile -File $install -RunKey $key -InstallDir $installDir -NoLaunch
        if ($LASTEXITCODE -eq 0 -or !(Test-Path -LiteralPath $sentinel)) { throw 'La segunda operación interfirió en la primera' }
    } finally { $guard.ReleaseMutex(); $guard.Dispose() }
    Remove-Item -LiteralPath $sentinel -Force
    $oldTime = [datetime]::SpecifyKind([datetime]'2000-01-01', [DateTimeKind]::Utc)
    (Get-Item -LiteralPath $dest).LastWriteTimeUtc = $oldTime
    & powershell.exe -NoProfile -File $install -RunKey $key -InstallDir $installDir -NoLaunch
    if ($LASTEXITCODE -ne 0) { throw 'Segunda instalación fallida' }
    foreach ($spec in $toolSpecs) {
        $file = $toolFolder.ParseName([IO.Path]::GetFileName($spec.Path))
        if (!$file -or !(Test-CiceronToolShortcut $toolShell $file.Path $spec.ToolId $dest)) { throw 'La reinstalación perdió un acceso interno' }
        if ($file.ExtendedProperty('System.AppUserModel.ID') -cne $spec.AppId -or
            ($file.ExtendedProperty('System.Keywords') -join ',') -cne ($spec.Tags -join ',')) { throw 'La reinstalación perdió los metadatos de Inicio' }
    }
    if ((Get-Item -LiteralPath $dest).LastWriteTimeUtc -eq $oldTime) { throw 'La reinstalación no reemplazó el ejecutable' }
    $oldLocalPackages=Join-Path $local 'Ciceron\paquetes\prueba'
    New-Item -ItemType Directory -Force $oldLocalPackages | Out-Null
    [IO.File]::WriteAllText((Join-Path $oldLocalPackages 'app.dat'),'paquete local conservado')
    & powershell.exe -NoProfile -File $install -RunKey $key -InstallDir $installDir -NoLaunch
    if ($LASTEXITCODE -ne 0 -or !(Test-Path (Join-Path $installDir 'datos\paquetes\prueba\app.dat')) -or (Test-Path (Join-Path $local 'Ciceron'))) { throw 'No se migraron los paquetes de la instalación anterior' }
    New-ItemProperty -Path $key -Name Ciceron -Value '"%LOCALAPPDATA%\Ciceron\Ciceron.exe"' -PropertyType ExpandString -Force | Out-Null
    & powershell.exe -NoProfile -File $install -RunKey $key -InstallDir $installDir -NoLaunch
    if ($LASTEXITCODE -ne 0) { throw 'No se reconoció la ruta de inicio expandible' }
    if ((Get-ItemProperty -Path $key -Name Ciceron).Ciceron -ne ('"'+$dest+'"')) { throw 'No se normalizó la ruta expandible' }
    Remove-ItemProperty -Path $key -Name Ciceron
    & powershell.exe -NoProfile -File $install -RunKey $key -InstallDir $installDir -NoLaunch
    if ($LASTEXITCODE -ne 0) { throw 'Instalación con inicio desactivado fallida' }
    if ($null -ne (Get-ItemProperty -Path $key -Name Ciceron -ErrorAction SilentlyContinue)) { throw 'Se reactivó el inicio sin permiso' }
    New-ItemProperty -Path $key -Name Ciceron -Value ('"'+$dest+'"') -PropertyType String | Out-Null
    [IO.File]::WriteAllText((Join-Path $bundle 'Ciceron.exe'),'versión distinta')
    [IO.File]::WriteAllText((Join-Path $sourceRuntime 'runtime.marker'),'runtime v2')
    & powershell.exe -NoProfile -File $install -RunKey $key -InstallDir $installDir -NoLaunch
    if ($LASTEXITCODE -ne 0 -or [IO.File]::ReadAllText($dest) -ne 'versión distinta') { throw 'Actualización fallida' }
    if ((Get-Content -LiteralPath (Join-Path $installedRuntime 'runtime.marker') -Raw) -ne 'runtime v2') { throw 'La actualización no reemplazó las dependencias' }
    # Force a failure after replacing the executable and changing the registry.
    $oldHash=(Get-FileHash -LiteralPath $dest).Hash
    $expanded='"%LOCALAPPDATA%\Ciceron\Ciceron.exe"'
    New-ItemProperty -Path $key -Name Ciceron -Value $expanded -PropertyType ExpandString -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $bundle 'Ciceron.exe'),'fallo simulado')
    [IO.File]::WriteAllText((Join-Path $sourceRuntime 'runtime.marker'),'runtime fallido')
    & powershell.exe -NoProfile -File (Join-Path $PSScriptRoot 'forzar-fallo.ps1') -Installer $install -RunKey $key -InstallDir $installDir
    if ($LASTEXITCODE -eq 0) { throw 'No se produjo el fallo simulado' }
    if ((Get-FileHash -LiteralPath $dest).Hash -ne $oldHash) { throw 'No se restauró el ejecutable' }
    if ((Get-Content -LiteralPath (Join-Path $installedRuntime 'runtime.marker') -Raw) -ne 'runtime v2') { throw 'No se restauró la versión anterior de las dependencias' }
    $reg=Get-Item -Path $key
    if ($reg.GetValueKind('Ciceron') -ne [Microsoft.Win32.RegistryValueKind]::ExpandString -or $reg.GetValue('Ciceron',$null,[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames) -ne $expanded) { throw 'No se restauró el valor y tipo del Registro' }
    if (Test-Path -LiteralPath (Join-Path $local 'Ciceron\Ciceron.respaldo.tmp')) { throw 'Quedó un respaldo tras recuperarse' }
    # A concurrent change to the registry must survive and the executable must roll back.
    [IO.File]::WriteAllText((Join-Path $bundle 'Ciceron.exe'),'cambio concurrente')
    [IO.File]::WriteAllText((Join-Path $sourceRuntime 'runtime.marker'),'runtime concurrente')
    & powershell.exe -NoProfile -File (Join-Path $PSScriptRoot 'forzar-cambio.ps1') -Installer $install -RunKey $key -InstallDir $installDir
    if ($LASTEXITCODE -eq 0) { throw 'No se detectó el cambio concurrente' }
    if ((Get-ItemProperty -Path $key -Name Ciceron).Ciceron -ne 'C:\Otro\concurrente.exe') { throw 'Se sobrescribió el cambio concurrente' }
    if ((Get-FileHash -LiteralPath $dest).Hash -ne $oldHash) { throw 'No se restauró el ejecutable tras el cambio concurrente' }
    New-ItemProperty -Path $key -Name Ciceron -Value ('"'+$dest+'"') -PropertyType String -Force | Out-Null
    # Reproduce an open application with a disposable process at the exact test path.
    Remove-Item -LiteralPath $dest -Force
    Add-Type -TypeDefinition 'public class PruebaCiceron { public static void Main() { System.Threading.Thread.Sleep(120000); } }' -OutputAssembly $dest -OutputType ConsoleApplication
    $dummy=Start-Process -FilePath $dest -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 1
    if (!(Get-Process -Id $dummy.Id -ErrorAction SilentlyContinue)) { throw 'El proceso de prueba terminó antes de la actualización' }
    Copy-Item -LiteralPath $dest -Destination (Join-Path $bundle 'Ciceron.exe') -Force
    $before=(Get-FileHash -LiteralPath $dest).Hash
    'NO' | & powershell.exe -NoProfile -File $install -RunKey $key -InstallDir $installDir -NoLaunch
    if ($LASTEXITCODE -ne 0 -or !(Get-Process -Id $dummy.Id -ErrorAction SilentlyContinue) -or (Get-FileHash -LiteralPath $dest).Hash -ne $before) { throw 'La cancelación modificó la instalación' }
    'SI' | & powershell.exe -NoProfile -File $install -RunKey $key -InstallDir $installDir -NoLaunch
    if ($LASTEXITCODE -ne 0 -or (Get-FileHash -LiteralPath $dest).Hash -ne $before) { throw 'Reinstalación con proceso abierto fallida' }
    if (Get-Process -Id $dummy.Id -ErrorAction SilentlyContinue) { throw 'El proceso de prueba no se cerró' }
    [IO.File]::WriteAllText((Join-Path $bundle 'Ciceron.exe'),'versión distinta')
    & powershell.exe -NoProfile -File $install -RunKey $key -InstallDir $installDir -NoLaunch
    if ($LASTEXITCODE -ne 0 -or [IO.File]::ReadAllText($dest) -ne 'versión distinta') { throw 'Actualización posterior fallida' }
    $data=Join-Path $installDir 'datos'; New-Item -ItemType Directory -Force $data | Out-Null
    [IO.File]::WriteAllText((Join-Path $data 'config.json'),'{"personal":"dato conservado"}')
    $links = Join-Path $app 'Microsoft\Windows\Start Menu\Programs\Ciceron'
    New-Item -ItemType Directory -Force $links | Out-Null
    $wsh = New-Object -ComObject WScript.Shell
    $managed = $wsh.CreateShortcut((Join-Path $links 'Prueba.lnk'))
    $managed.TargetPath = $dest
    $managed.Description = 'Ciceron.Library:0123456789abcdef prueba'
    $managed.Save()
    $external = $wsh.CreateShortcut((Join-Path $links 'Ajeno.lnk'))
    $external.TargetPath = $dest
    $external.Save()
    & powershell.exe -NoProfile -File $uninstall -RunKey $key -InstallDir $installDir -Confirmar
    if ($LASTEXITCODE -ne 0 -or (Test-Path -LiteralPath $dest)) { throw 'Desinstalación fallida' }
    if ($null -ne (Get-ItemProperty -Path $key -Name Ciceron -ErrorAction SilentlyContinue)) { throw 'No se eliminó el Registro' }
    if (!(Test-Path -LiteralPath (Join-Path $data 'config.json'))) { throw 'Se borró la configuración' }
    if ((Test-Path -LiteralPath (Join-Path $links 'Prueba.lnk')) -or
        !(Test-Path -LiteralPath (Join-Path $links 'Ajeno.lnk'))) { throw 'Limpieza incorrecta de accesos de Inicio' }
    foreach ($path in $toolPaths) {
        if (Test-Path -LiteralPath $path) { throw 'Quedó un acceso interno de Cicerón en Inicio' }
    }
    & powershell.exe -NoProfile -File $uninstall -RunKey $key -InstallDir $installDir -Confirmar
    if ($LASTEXITCODE -ne 0) { throw 'Segunda desinstalación fallida' }
    # An old-name installation and profile migrate into the canonical Ciceron paths.
    $oldInstall=Join-Path $local 'GanaLaBatalla'; $oldPackages=Join-Path $oldInstall 'paquetes\prueba'
    $oldProfile=Join-Path $app 'GanaLaBatalla'
    $currentProfile=Join-Path $app 'Ciceron'
    New-Item -ItemType Directory -Force -Path $oldPackages,$oldProfile,$currentProfile | Out-Null
    $oldSessions=Join-Path $oldProfile 'navegadores-activos'; $currentSessions=Join-Path $currentProfile 'navegadores-activos'
    New-Item -ItemType Directory -Force -Path $oldSessions,$currentSessions | Out-Null
    [IO.File]::WriteAllText((Join-Path $oldSessions 'misma-sesion.json'),'sesión anterior')
    [IO.File]::WriteAllText((Join-Path $currentSessions 'misma-sesion.json'),'sesión activa distinta')
    [IO.File]::WriteAllText((Join-Path $app 'Ciceron\config.json'),'{"theme":"system","solo-nuevo":"conservar"}')
    [IO.File]::WriteAllText((Join-Path $oldInstall 'Ciceron.exe'),'ejecutable antiguo')
    [IO.File]::WriteAllText((Join-Path $oldPackages 'aplicacion.dat'),'paquete conservado')
    [IO.File]::WriteAllText((Join-Path $oldProfile 'config.json'),'{"theme":"light","contador":"examen"}')
    New-ItemProperty -Path $key -Name GanaLaBatalla -Value ('"'+(Join-Path $oldInstall 'Ciceron.exe')+'"') -PropertyType String -Force | Out-Null
    & powershell.exe -NoProfile -File $install -RunKey $key -InstallDir $installDir -NoLaunch -SkipBrowser
    if ($LASTEXITCODE -ne 0) { throw 'Migración de la instalación antigua fallida' }
    $migratedPackage=Join-Path $installDir 'datos\paquetes\prueba\aplicacion.dat'
    $migratedProfile=Join-Path $installDir 'datos\config.json'
    if (!(Test-Path -LiteralPath $dest) -or !(Test-Path -LiteralPath $migratedPackage) -or !(Test-Path -LiteralPath $migratedProfile)) { throw 'No se conservaron todos los datos antiguos' }
    $mergedConfig=Get-Content -LiteralPath $migratedProfile -Raw | ConvertFrom-Json
    if ($mergedConfig.theme -ne 'system' -or $mergedConfig.contador -ne 'examen' -or $mergedConfig.'solo-nuevo' -ne 'conservar') { throw 'La combinación de configuración no conservó el perfil actual y los datos antiguos' }
    if (Test-Path -LiteralPath (Join-Path $migratedProfile 'navegadores-activos')) { throw 'Se migraron archivos temporales de sesiones del navegador' }
    if ((Test-Path -LiteralPath $oldInstall) -or (Test-Path -LiteralPath $oldProfile)) { throw 'Quedó la carpeta antigua después de migrar' }
    if ($null -ne (Get-ItemProperty -Path $key -Name GanaLaBatalla -ErrorAction SilentlyContinue) -or (Get-ItemProperty -Path $key -Name Ciceron).Ciceron -ne ('"'+$dest+'"')) { throw 'No se migró la entrada de inicio' }
    $movedInstallDir=Join-Path $root 'reubicado\Aplicacion'
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $movedInstallDir) | Out-Null
    Move-Item -LiteralPath $installDir -Destination $movedInstallDir
    $installDir=$movedInstallDir
    $dest=Join-Path $installDir 'Ciceron.exe'
    $installedRuntime=Join-Path $installDir '_internal'
    $movedDataFile=Join-Path $installDir 'datos\paquetes\prueba\aplicacion.dat'
    & powershell.exe -NoProfile -File $install -RunKey $key -InstallDir $installDir -NoLaunch -SkipBrowser
    if ($LASTEXITCODE -ne 0 -or !(Test-Path -LiteralPath $movedDataFile) -or
        (Get-ItemProperty -Path $key -Name Ciceron).Ciceron -ne ('"'+$dest+'"')) { throw 'La reubicación no actualizó el acceso ni conservó los datos' }
    foreach ($spec in $toolSpecs) {
        $file = $toolFolder.ParseName([IO.Path]::GetFileName($spec.Path))
        if (!$file -or !(Test-CiceronToolShortcut $toolShell $file.Path $spec.ToolId $dest)) { throw 'La reubicación dejó un acceso interno apuntando al destino anterior' }
    }
    & powershell.exe -NoProfile -File $uninstall -RunKey $key -InstallDir $installDir -Confirmar
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo retirar la instalación reubicada' }
    foreach ($spec in $toolSpecs) {
        if ($toolFolder.ParseName([IO.Path]::GetFileName($spec.Path))) { throw 'Quedó un acceso interno tras la desinstalación reubicada' }
    }
    New-ItemProperty -Path $key -Name Ciceron -Value 'C:\Otro\programa.exe' -PropertyType String | Out-Null
    & powershell.exe -NoProfile -File $install -RunKey $key -InstallDir $installDir -NoLaunch
    if ($LASTEXITCODE -eq 0) { throw 'No se detectó la entrada ajena' }
    & powershell.exe -NoProfile -File $uninstall -RunKey $key -InstallDir $installDir -Confirmar
    if ((Get-ItemProperty -Path $key -Name Ciceron).Ciceron -ne 'C:\Otro\programa.exe') { throw 'Se modificó una entrada ajena' }
    Write-Host 'Pruebas de instalación, actualización y desinstalación correctas.'
} finally {
    if ($null -ne $dummy -and (Get-Process -Id $dummy.Id -ErrorAction SilentlyContinue)) { Stop-Process -Id $dummy.Id -Force }
    if (Test-Path -LiteralPath $key) { Remove-Item -LiteralPath $key -Force }
    if (Test-Path -LiteralPath $root) {
        $resolved=(Resolve-Path -LiteralPath $root).Path
        if ($resolved -ne $expected) { throw 'Ruta de prueba inesperada; no se elimina.' }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
