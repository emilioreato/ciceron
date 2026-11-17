param([string]$Installer,[string]$RunKey)
$script:lecturas = 0
function Get-Item {
    [CmdletBinding()]
    param([string]$LiteralPath,[string]$Path,[switch]$Force)
    if ($LiteralPath -eq $RunKey) {
        $script:lecturas++
        if ($script:lecturas -eq 3) {
            New-ItemProperty -LiteralPath $RunKey -Name Ciceron -Value 'C:\Otro\concurrente.exe' -PropertyType String -Force | Out-Null
        }
    }
    Microsoft.PowerShell.Management\Get-Item @PSBoundParameters
}
& $Installer -RunKey $RunKey -NoLaunch
if (!$?) { exit 1 }
