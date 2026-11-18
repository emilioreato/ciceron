param([switch]$Graficos, [switch]$Instalacion)
$ErrorActionPreference = 'Stop'
Push-Location (Join-Path $PSScriptRoot '..')
$oldPlatform = $env:QT_QPA_PLATFORM
try {
    $python = (Resolve-Path -LiteralPath '.venv/Scripts/python.exe').Path
    $failed = @()
    $env:QT_QPA_PLATFORM = 'offscreen'
    foreach ($name in @('app_paths', 'inicio', 'inicio_cuenta', 'centro', 'paquetes', 'browser_bridge', 'browser_ui')) {
        & $python "tests/$name.py"
        if ($LASTEXITCODE -ne 0) { $failed += $name }
    }
    & node --test navegador/tests/*.test.cjs
    if ($LASTEXITCODE -ne 0) { $failed += 'extension' }
    if ($Graficos) {
        $env:QT_QPA_PLATFORM = 'windows'
        foreach ($name in @('lente', 'contraste_vidrio')) {
            & $python "tests/$name.py"
            if ($LASTEXITCODE -ne 0) { $failed += $name }
        }
    }
    if ($Instalacion) {
        foreach ($name in @('instalacion', 'navegador_instalacion')) {
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "tests/$name.ps1"
            if ($LASTEXITCODE -ne 0) { $failed += $name }
        }
    }
    if ($failed.Count -gt 0) { throw "Pruebas fallidas - $($failed -join ', ')" }
    Write-Host 'Pruebas superadas.'
} finally {
    $env:QT_QPA_PLATFORM = $oldPlatform
    Pop-Location
}
