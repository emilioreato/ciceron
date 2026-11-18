param([string]$Installer,[string]$RunKey,[string]$InstallDir)
function Move-Item {
    param([string]$LiteralPath,[string]$Destination,[switch]$Force)
    if ($LiteralPath -like '*.Ciceron-*.lnk') { throw 'Fallo de prueba al actualizar el acceso directo' }
    Microsoft.PowerShell.Management\Move-Item -LiteralPath $LiteralPath -Destination $Destination -Force:$Force
}
& $Installer -RunKey $RunKey -InstallDir $InstallDir -NoLaunch
if (!$?) { exit 1 }
