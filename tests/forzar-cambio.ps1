param([string]$Installer,[string]$RunKey)
$script:lecturas = 0
function Get-ItemProperty {
    [CmdletBinding()]
    param([string]$LiteralPath,[string]$Name)
    if ($Name -eq 'GanaLaBatalla') {
        $script:lecturas++
        if ($script:lecturas -eq 2) {
            New-ItemProperty -LiteralPath $LiteralPath -Name $Name -Value 'C:\Otro\concurrente.exe' -PropertyType String -Force | Out-Null
        }
    }
    Microsoft.PowerShell.Management\Get-ItemProperty @PSBoundParameters
}
& $Installer -RunKey $RunKey -NoLaunch
if (!$?) { exit 1 }
