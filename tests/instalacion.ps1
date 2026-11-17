$ErrorActionPreference = 'Stop'
$root = Join-Path $PSScriptRoot '.instalacion-temporal'
$expected = Join-Path $PSScriptRoot '.instalacion-temporal'
$key = 'HKCU:\Software\CiceronPruebaCodex_Instalacion'
if (Test-Path -LiteralPath $root) { throw 'La carpeta de prueba ya existe; no se reemplaza.' }
if (Test-Path -LiteralPath $key) { throw 'La clave de prueba ya existe; no se reemplaza.' }
try {
    $package=Join-Path $root 'paquete'; $local=Join-Path $root 'local'; $app=Join-Path $root 'app'
    New-Item -ItemType Directory -Force -Path $package,$local,$app | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot '..\internos\instalar.ps1'),(Join-Path $PSScriptRoot '..\internos\desinstalar.ps1') -Destination $package
    [IO.File]::WriteAllText((Join-Path $package 'GanaLaBatalla.exe'),'contenido de prueba')
    $env:LOCALAPPDATA=$local; $env:APPDATA=$app
    New-Item -Path $key | Out-Null
    $install=Join-Path $package 'instalar.ps1'; $uninstall=Join-Path $package 'desinstalar.ps1'
    & powershell.exe -NoProfile -File $install -RunKey $key -NoLaunch
    if ($LASTEXITCODE -ne 0) { throw 'Primera instalación fallida' }
    $dest=Join-Path $local 'GanaLaBatalla\Ciceron.exe'
    if (!(Test-Path -LiteralPath $dest)) { throw 'No se instaló el ejecutable' }
    if ((Get-ItemProperty -Path $key -Name GanaLaBatalla).GanaLaBatalla -ne ('"'+$dest+'"')) { throw 'Registro incorrecto' }
    $guard=New-Object System.Threading.Mutex($false, 'Local\CiceronInstalacion')
    $guardHeld=$guard.WaitOne(0)
    if (!$guardHeld) { throw 'No se pudo preparar la prueba de concurrencia' }
    $sentinel=Join-Path $local 'GanaLaBatalla\Ciceron.instalando.tmp'
    [IO.File]::WriteAllText($sentinel,'operación en curso')
    try {
        & powershell.exe -NoProfile -File $install -RunKey $key -NoLaunch
        if ($LASTEXITCODE -eq 0 -or !(Test-Path -LiteralPath $sentinel)) { throw 'La segunda operación interfirió en la primera' }
    } finally { $guard.ReleaseMutex(); $guard.Dispose() }
    Remove-Item -LiteralPath $sentinel -Force
    $oldTime = [datetime]::SpecifyKind([datetime]'2000-01-01', [DateTimeKind]::Utc)
    (Get-Item -LiteralPath $dest).LastWriteTimeUtc = $oldTime
    & powershell.exe -NoProfile -File $install -RunKey $key -NoLaunch
    if ($LASTEXITCODE -ne 0) { throw 'Segunda instalación fallida' }
    if ((Get-Item -LiteralPath $dest).LastWriteTimeUtc -eq $oldTime) { throw 'La reinstalación no reemplazó el ejecutable' }
    New-ItemProperty -Path $key -Name GanaLaBatalla -Value '"%LOCALAPPDATA%\GanaLaBatalla\Ciceron.exe"' -PropertyType ExpandString -Force | Out-Null
    & powershell.exe -NoProfile -File $install -RunKey $key -NoLaunch
    if ($LASTEXITCODE -ne 0) { throw 'No se reconoció la ruta de inicio expandible' }
    if ((Get-ItemProperty -Path $key -Name GanaLaBatalla).GanaLaBatalla -ne ('"'+$dest+'"')) { throw 'No se normalizó la ruta expandible' }
    Remove-ItemProperty -Path $key -Name GanaLaBatalla
    & powershell.exe -NoProfile -File $install -RunKey $key -NoLaunch
    if ($LASTEXITCODE -ne 0) { throw 'Instalación con inicio desactivado fallida' }
    if ($null -ne (Get-ItemProperty -Path $key -Name GanaLaBatalla -ErrorAction SilentlyContinue)) { throw 'Se reactivó el inicio sin permiso' }
    New-ItemProperty -Path $key -Name GanaLaBatalla -Value ('"'+$dest+'"') -PropertyType String | Out-Null
    [IO.File]::WriteAllText((Join-Path $package 'GanaLaBatalla.exe'),'versión distinta')
    & powershell.exe -NoProfile -File $install -RunKey $key -NoLaunch
    if ($LASTEXITCODE -ne 0 -or [IO.File]::ReadAllText($dest) -ne 'versión distinta') { throw 'Actualización fallida' }
    # Force a failure after replacing the executable and changing the registry.
    $oldHash=(Get-FileHash -LiteralPath $dest).Hash
    $expanded='"%LOCALAPPDATA%\GanaLaBatalla\Ciceron.exe"'
    New-ItemProperty -Path $key -Name GanaLaBatalla -Value $expanded -PropertyType ExpandString -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $package 'GanaLaBatalla.exe'),'fallo simulado')
    & powershell.exe -NoProfile -File (Join-Path $PSScriptRoot 'forzar-fallo.ps1') -Installer $install -RunKey $key
    if ($LASTEXITCODE -eq 0) { throw 'No se produjo el fallo simulado' }
    if ((Get-FileHash -LiteralPath $dest).Hash -ne $oldHash) { throw 'No se restauró el ejecutable' }
    $reg=Get-Item -Path $key
    if ($reg.GetValueKind('GanaLaBatalla') -ne [Microsoft.Win32.RegistryValueKind]::ExpandString -or $reg.GetValue('GanaLaBatalla',$null,[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames) -ne $expanded) { throw 'No se restauró el valor y tipo del Registro' }
    if (Test-Path -LiteralPath (Join-Path $local 'GanaLaBatalla\Ciceron.respaldo.tmp')) { throw 'Quedó un respaldo tras recuperarse' }
    # A concurrent change to the registry must survive and the executable must roll back.
    [IO.File]::WriteAllText((Join-Path $package 'GanaLaBatalla.exe'),'cambio concurrente')
    & powershell.exe -NoProfile -File (Join-Path $PSScriptRoot 'forzar-cambio.ps1') -Installer $install -RunKey $key
    if ($LASTEXITCODE -eq 0) { throw 'No se detectó el cambio concurrente' }
    if ((Get-ItemProperty -Path $key -Name GanaLaBatalla).GanaLaBatalla -ne 'C:\Otro\concurrente.exe') { throw 'Se sobrescribió el cambio concurrente' }
    if ((Get-FileHash -LiteralPath $dest).Hash -ne $oldHash) { throw 'No se restauró el ejecutable tras el cambio concurrente' }
    New-ItemProperty -Path $key -Name GanaLaBatalla -Value ('"'+$dest+'"') -PropertyType String -Force | Out-Null
    # Reproduce an open application with a disposable process at the exact test path.
    Remove-Item -LiteralPath $dest -Force
    Add-Type -TypeDefinition 'public class PruebaCiceron { public static void Main() { System.Threading.Thread.Sleep(120000); } }' -OutputAssembly $dest -OutputType ConsoleApplication
    $dummy=Start-Process -FilePath $dest -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 1
    if (!(Get-Process -Id $dummy.Id -ErrorAction SilentlyContinue)) { throw 'El proceso de prueba terminó antes de la actualización' }
    Copy-Item -LiteralPath $dest -Destination (Join-Path $package 'GanaLaBatalla.exe') -Force
    $before=(Get-FileHash -LiteralPath $dest).Hash
    'NO' | & powershell.exe -NoProfile -File $install -RunKey $key -NoLaunch
    if ($LASTEXITCODE -ne 0 -or !(Get-Process -Id $dummy.Id -ErrorAction SilentlyContinue) -or (Get-FileHash -LiteralPath $dest).Hash -ne $before) { throw 'La cancelación modificó la instalación' }
    'SI' | & powershell.exe -NoProfile -File $install -RunKey $key -NoLaunch
    if ($LASTEXITCODE -ne 0 -or (Get-FileHash -LiteralPath $dest).Hash -ne $before) { throw 'Reinstalación con proceso abierto fallida' }
    if (Get-Process -Id $dummy.Id -ErrorAction SilentlyContinue) { throw 'El proceso de prueba no se cerró' }
    [IO.File]::WriteAllText((Join-Path $package 'GanaLaBatalla.exe'),'versión distinta')
    & powershell.exe -NoProfile -File $install -RunKey $key -NoLaunch
    if ($LASTEXITCODE -ne 0 -or [IO.File]::ReadAllText($dest) -ne 'versión distinta') { throw 'Actualización posterior fallida' }
    $data=Join-Path $app 'GanaLaBatalla'; New-Item -ItemType Directory -Force $data | Out-Null
    [IO.File]::WriteAllText((Join-Path $data 'config.json'),'datos personales')
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
    & powershell.exe -NoProfile -File $uninstall -RunKey $key -Confirmar
    if ($LASTEXITCODE -ne 0 -or (Test-Path -LiteralPath $dest)) { throw 'Desinstalación fallida' }
    if ($null -ne (Get-ItemProperty -Path $key -Name GanaLaBatalla -ErrorAction SilentlyContinue)) { throw 'No se eliminó el Registro' }
    if (!(Test-Path -LiteralPath (Join-Path $data 'config.json'))) { throw 'Se borró la configuración' }
    if ((Test-Path -LiteralPath (Join-Path $links 'Prueba.lnk')) -or
        !(Test-Path -LiteralPath (Join-Path $links 'Ajeno.lnk'))) { throw 'Limpieza incorrecta de accesos de Inicio' }
    & powershell.exe -NoProfile -File $uninstall -RunKey $key -Confirmar
    if ($LASTEXITCODE -ne 0) { throw 'Segunda desinstalación fallida' }
    New-ItemProperty -Path $key -Name GanaLaBatalla -Value 'C:\Otro\programa.exe' -PropertyType String | Out-Null
    & powershell.exe -NoProfile -File $install -RunKey $key -NoLaunch
    if ($LASTEXITCODE -eq 0) { throw 'No se detectó la entrada ajena' }
    & powershell.exe -NoProfile -File $uninstall -RunKey $key -Confirmar
    if ((Get-ItemProperty -Path $key -Name GanaLaBatalla).GanaLaBatalla -ne 'C:\Otro\programa.exe') { throw 'Se modificó una entrada ajena' }
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
