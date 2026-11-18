$ErrorActionPreference='Stop'
$root=Join-Path $PSScriptRoot '.navegador-temporal'
$key='HKCU:\Software\CiceronPruebaCodex_Navegador'
if ((Test-Path -LiteralPath $root) -or (Test-Path -LiteralPath $key)) { throw 'La ubicación temporal ya existe.' }
try {
    $package=Join-Path $root 'paquete'; $local=Join-Path $root 'local'; $app=Join-Path $root 'app'; $program=Join-Path $root 'program'
    New-Item -ItemType Directory -Force -Path (Join-Path $package 'internos'),(Join-Path $package 'navegador'),$local,$app,(Join-Path $program 'Google\Chrome\Application'),(Join-Path $program 'Microsoft\Edge\Application') | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot '..\navegador\extension') -Destination (Join-Path $package 'navegador\extension') -Recurse
    New-Item -ItemType Directory -Force -Path (Join-Path $package 'navegador\extension\_metadata') | Out-Null
    [IO.File]::WriteAllText((Join-Path $package 'internos\CiceronHost.exe'),'puente prueba')
    [IO.File]::WriteAllText((Join-Path $program 'Google\Chrome\Application\chrome.exe'),'simulado')
    [IO.File]::WriteAllText((Join-Path $program 'Microsoft\Edge\Application\msedge.exe'),'simulado')
    $env:LOCALAPPDATA=$local; $env:APPDATA=$app; $env:ProgramFiles=$program; ${env:ProgramFiles(x86)}=$program
    $installDir=Join-Path $root 'Aplicacion'
    $setup=Join-Path $PSScriptRoot '..\internos\instalar_navegador.ps1'
    $uninstall=Join-Path $PSScriptRoot '..\internos\desinstalar.ps1'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $setup -PackageRoot $package -InstallDir $installDir -RegistryRoot $key
    if ($LASTEXITCODE -ne 0) { throw 'Preparación fallida' }
    $manifest=Join-Path $installDir 'ciceron-native-host.json'; $ext=Join-Path $installDir '00 EXTENSION'
    if ((Get-Content -Raw (Join-Path $installDir 'extension-path.txt')).Trim() -ne '00 EXTENSION') { throw 'La ruta de extensión no es relativa' }
    if (Test-Path -LiteralPath (Join-Path $ext '_metadata')) { throw 'Se copió la caché de Chromium.' }
    $chrome=$key+'\Google\Chrome\NativeMessagingHosts\com.ciceron.browser'; $edge=$key+'\Microsoft\Edge\NativeMessagingHosts\com.ciceron.browser'
    if ((Get-Item $chrome).GetValue('') -ne $manifest -or (Get-Item $edge).GetValue('') -ne $manifest) { throw 'Registro nativo incorrecto' }
    $hostInfo=Get-Content $manifest -Raw | ConvertFrom-Json
    if (!(Test-Path -LiteralPath $hostInfo.path)) { throw 'Falta el puente registrado' }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $setup -PackageRoot $package -InstallDir $installDir -RegistryRoot $key
    if ($LASTEXITCODE -ne 0) { throw 'Reinstalación fallida' }
    [IO.File]::WriteAllText((Join-Path $ext 'personal.txt'),'conservar')
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $setup -PackageRoot $package -InstallDir $installDir -RegistryRoot $key
    if ($LASTEXITCODE -ne 2 -or !(Test-Path -LiteralPath (Join-Path $ext 'personal.txt'))) { throw 'Se perdió un archivo ajeno' }
    Set-Item -Path $edge -Value 'C:\Otro\bridge.json'
    New-ItemProperty -Path $chrome -Name OtroValor -Value 'conservar' | Out-Null
    $data=Join-Path $installDir 'datos'; New-Item -ItemType Directory -Force $data | Out-Null
    [IO.File]::WriteAllText((Join-Path $data 'config.json'),'mantener')
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $uninstall -RunKey ($key+'\Run') -NativeRoot $key -InstallDir $installDir -Confirmar
    if ($LASTEXITCODE -ne 0) { throw 'Desinstalación fallida' }
    if ((Get-Item $chrome).GetValue('') -or (Get-ItemProperty $chrome).OtroValor -ne 'conservar') { throw 'Se borró registro ajeno' }
    if ((Get-Item $edge).GetValue('') -ne 'C:\Otro\bridge.json') { throw 'Se borró puente ajeno' }
    if ((Test-Path $manifest) -or (Test-Path $hostInfo.path) -or !(Test-Path (Join-Path $ext 'personal.txt')) -or !(Test-Path (Join-Path $data 'config.json'))) { throw 'Limpieza incorrecta' }
    Write-Host 'Preparación y desinstalación del navegador verificadas.'
} finally {
    if (Test-Path -LiteralPath $key) { Remove-Item -LiteralPath $key -Recurse -Force }
    if (Test-Path -LiteralPath $root) {
        $resolved=(Resolve-Path -LiteralPath $root).Path
        if ($resolved -ne $root) { throw 'Ruta temporal inesperada.' }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
